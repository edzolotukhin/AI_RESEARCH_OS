"""One-operation facade over existing Desk services, not a second research loop."""
from dataclasses import replace, asdict
import time

from application import research_funnel_telemetry as funnel
from application.evidence.content_identity_queue import distinct_content_queue
from application.evidence.evidence_extraction_diagnostics import (
    EvidenceExtractionDiagnostics, activate_diagnostics, deactivate_diagnostics,
)
from application.evidence.evidence_extraction_scheduler import (
    build_need_fair_extraction_queue, SourceOutcomeState, record_source_outcome,
    adaptive_depth_selection_key, PHASE_FIRST_OPPORTUNITY,
)
from application.sources.source_acquisition_service import _PendingCandidate
from application.sources.retrieval_portfolio import derive_initial_retrieval_portfolio
from application.sources.query_opportunities import KEY as QUERY_HISTORY
from application.research_kernel.dispatch import invoke, current_dispatch
from domain.sources.source_candidate import SourceCandidate


class _MeteredPort:
    def __init__(self, delegate, operation):
        self.delegate, self.operation = delegate, operation

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def search(self, query):
        try:
            return invoke("search", "search", lambda: self.delegate.search(query))
        except Exception:
            scope = current_dispatch()
            if scope and scope.count:
                scope.mark_ambiguous()
            raise

    def retrieve(self, candidate):
        return invoke("retriever", "retrieve", lambda: self.delegate.retrieve(candidate))


class DeskPrimitives:
    def __init__(self, context, acquisition, extraction):
        self.context, self.acquisition, self.extraction = context, acquisition, extraction
        acquisition._search_provider = _MeteredPort(acquisition._search_provider, "search")
        acquisition._source_retriever = _MeteredPort(acquisition._source_retriever, "retrieve")
        self.design = context.workflow_template.research_design_snapshot
        self.brief = context.workflow_template.research_brief_snapshot

    def initial_queries(self):
        return [arm for query in self.acquisition._query_builder.build_queries(self.design, brief=self.brief)
                for arm in derive_initial_retrieval_portfolio(query,
                    supports_arm=self.acquisition._search_provider.supports_retrieval_arm)]

    @funnel.observed("initial_search")
    def search(self, context, query):
        _, grouped = self.acquisition._collect_candidates(
            [query], execution_history=context.shared_state.setdefault(QUERY_HISTORY, []))
        eligible, _, _, _ = self.acquisition._select_groups(grouped, design=self.design,
            brief=self.brief, exhausted_pairs=self.acquisition._exhausted_pairs_for_queries(context, [query]))
        # Persist only selected canonical candidate DTOs, not provider response
        # dictionaries. Signed/credential-bearing URLs are not rewritten/fetched.
        rows = []
        for group in eligible:
            for item in group.items:
                candidate = item.candidate
                if funnel.safe_url(candidate.url) != candidate.url:
                    continue
                dto = candidate.to_dict()
                dto["metadata"] = {k: funnel.safe_text(v) for k, v in candidate.metadata.items()
                                   if k in ("provider_country", "provider_result_count")}
                for field in ("provider", "title", "snippet", "provider_result_id", "published_at", "source_type"):
                    if dto.get(field) is not None:
                        dto[field] = funnel.safe_text(dto[field])
                rows.append({"candidate": dto, "query_id": query.id, "canonical_url": group.canonical_url})
        return rows

    def groups(self, rows, queries):
        grouped = {}
        for row in rows:
            query = queries[row["query_id"]]
            item = _PendingCandidate(SourceCandidate.from_dict(row["candidate"]), query, row["canonical_url"])
            grouped.setdefault(item.canonical_url, []).append(item)
        return self.acquisition._select_groups(grouped, design=self.design, brief=self.brief,
            exhausted_pairs=self.acquisition._exhausted_pairs_for_queries(self.context, list(queries.values())))[0]

    @funnel.observed("continuation_search")
    def acquire(self, context, group):
        # Existing selection/retrieval/persistence/dedup path, capped to one group.
        remaining = max(0, context.shared_state["ark_acquisition_deadline"] - time.time())
        result = self.acquisition._acquire_candidates(
            project_id=context.project.id, workflow_run_id=context.workflow_run.id,
            research_design_id=self.design.id, design=self.design, groups=[group],
            started_at=time.monotonic() - max(0, self.acquisition._budget.acquisition_max_seconds - remaining),
            max_source_groups=1, selection_decisions=[])
        return tuple(result[0])

    def work_items(self, counts=None):
        context = self.context
        sources = self.extraction._eligible_sources(context.project.id, context.workflow_run.id)
        chars, overlap = self.extraction._chunk_settings()
        queue = build_need_fair_extraction_queue(sources, design=self.design,
            workflow_run_id=context.workflow_run.id, research_design_id=self.design.id,
            chunk_chars=chars, overlap_chars=overlap)
        queue = distinct_content_queue(queue)
        outcomes = context.shared_state.get("ark_source_outcomes", {})
        first = [item for item in queue if item.phase == PHASE_FIRST_OPPORTUNITY]
        depth = [item for item in queue if item.phase != PHASE_FIRST_OPPORTUNITY]
        depth.sort(key=lambda item: adaptive_depth_selection_key(item,
            state=SourceOutcomeState(**outcomes.get(item.source.id, {"source_id": item.source.id})),
            evidence_counts_by_need=counts or {}))
        return first + depth

    @funnel.observed("continuation_extraction")
    def extract(self, context, item, target):
        if target and target not in item.run_context.information_need_ids:
            raise ValueError("target is not in authoritative source provenance")
        if target:
            item = replace(item, primary_need_id=target,
                run_context=replace(item.run_context, target_information_need_id=target))
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id=context.workflow_run.id)
        diagnostics.queue_items = diagnostics.outer_chunks = 1
        diagnostics.sources_discovered = diagnostics.sources_eligible = diagnostics.sources_with_run_context = 1
        diagnostics.information_needs_represented = item.run_context.information_need_ids
        token = activate_diagnostics(diagnostics)
        try:
            # Same validation/persistence path; only this new caller permits
            # valid-empty. One already bounded outer work item, no batch loop.
            summary = self.extraction._extract_work_queue([item], design=self.design,
                project_id=context.project.id, workflow_run_id=context.workflow_run.id,
                research_design_id=self.design.id, allow_empty_failure=False, diagnostics=diagnostics)
            outcomes = context.shared_state.setdefault("ark_source_outcomes", {})
            state = SourceOutcomeState(**outcomes.get(item.source.id, {"source_id": item.source.id}))
            record_source_outcome(state, phase=item.phase, persisted_evidence=summary.evidence_extracted,
                valid_empty=bool(diagnostics.work_items) and all(
                    self.extraction._trace_is_valid_empty(trace) for trace in diagnostics.work_items))
            outcomes[item.source.id] = asdict(state)
            return summary
        finally:
            deactivate_diagnostics(token)
