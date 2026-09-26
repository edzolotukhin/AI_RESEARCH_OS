"""Bounded observational journal; never participates in research decisions."""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
import hashlib
import os
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

KEY = "research_funnel_v1"
MAX_EVENTS = 4096
MAX_TEXT = 2048
_active = ContextVar("research_funnel_observer", default=None)
_extraction = ContextVar("research_funnel_extraction", default=None)
_sensitive = re.compile(r"secret|password|token|authorization|cookie|key|signature", re.I)
_credential = re.compile(r"\b(?:sk-|tvly-|airos_)[A-Za-z0-9_-]+|\b(?:Bearer|Basic)\s+[^\s,;]+", re.I)


def digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def safe_text(value):
    text = str(value or "")
    for key, secret in os.environ.items():
        if _sensitive.search(key) and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    text = _credential.sub("[REDACTED]", text)
    text = re.sub(r'''(?ix)["']?(?:api[_-]?key|token|password|secret|authorization|cookie)["']?\s*[:=]\s*(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;&]+)''', "[REDACTED]", text)
    return text[:MAX_TEXT]


def safe_url(value):
    try:
        parts = urlsplit(str(value))
    except ValueError:
        return "[INVALID_URL]"
    host = parts.netloc.rsplit("@", 1)[-1]
    query = urlencode([(k, "[REDACTED]" if _sensitive.search(k) else v)
                       for k, v in parse_qsl(parts.query, keep_blank_values=True)])
    return safe_text(urlunsplit((parts.scheme, host, parts.path, query, "")))


def guarded(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if _active.get() is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:
            # Diagnostics failure must not replace a research result/exception.
            _active.get()["journal"]["observer_errors"] += 1
            return None
    return wrapper


@guarded
def emit(kind, **fields):
    state = _active.get()
    journal = state["journal"]
    journal["sequence"] += 1
    identifier = f'{state["run_id"]}:f{journal["sequence"]}'
    if len(journal["events"]) >= MAX_EVENTS:
        journal["dropped_events"] += 1
        return identifier
    # Callers pass explicit fields only, never arbitrary provider dictionaries.
    journal["events"].append({"event_id": identifier, "run_id": state["run_id"],
        "kind": kind, "stage": state["stage"], **fields})
    return identifier


def observed(stage):
    """Bind only around existing entry points; normal checkpointing persists it."""
    def decorate(fn):
        @wraps(fn)
        def wrapper(self, context, *args, **kwargs):
            if context.execution_metadata.get("research_funnel_enabled", True) is False:
                token = _active.set(None)
                try:
                    return fn(self, context, *args, **kwargs)
                finally:
                    _active.reset(token)
            journal = context.shared_state.setdefault(KEY, {"version": 1, "sequence": 0,
                "events": [], "dropped_events": 0, "observer_errors": 0})
            state = {"journal": journal, "run_id": context.workflow_run.id,
                     "stage": stage, "candidates": [], "sources": {}}
            token = _active.set(state)
            result = None
            try:
                result = fn(self, context, *args, **kwargs)
                if stage in {"qualification", "readiness"}:
                    readiness_result(result)
                return result
            finally:
                if stage in {"initial_search", "continuation_search"}:
                    finish_selection(result)
                _active.reset(token)
        return wrapper
    return decorate


@guarded
def search_start(query):
    journal = _active.get()["journal"]
    journal["search_ordinal"] = journal.get("search_ordinal", 0) + 1
    text = query.provider_query_text or query.query_text
    safe = safe_text(text)
    return emit("search", call_ordinal=journal["search_ordinal"], query_id=safe_text(query.id), target_in=safe_text(query.information_need_id),
        target_rq=safe_text(query.research_question_id), query=safe,
        query_hash=digest(text), query_exact=(safe == text),
        arm=safe_text(getattr(query.retrieval_arm, "value", "")))


@guarded
def search_results(search_id, query, candidates, limit):
    from application.sources.url_canonicalizer import canonicalize_url
    for ordinal, candidate in enumerate(candidates, 1):
        canonical = ""
        reason = "pending"
        if ordinal > limit:
            reason = "candidate_limit"
        try:
            if urlsplit(candidate.url).scheme not in {"http", "https"}:
                reason = "unsupported_url"
            else:
                canonical = canonicalize_url(candidate.url)
        except ValueError:
            reason = "invalid_url"
        cid = f"{search_id}:c{ordinal}"
        row = {"candidate_id": cid, "search_id": search_id, "candidate_ordinal": ordinal,
               "target_in": safe_text(query.information_need_id),
               "url": safe_url(candidate.url), "canonical_url": safe_url(canonical),
               "canonical_identity": digest(canonical) if canonical else "", "reason": reason}
        emit("candidate", **row)
        if len(_active.get()["candidates"]) < MAX_EVENTS:
            _active.get()["candidates"].append(row)
    emit("search_result", search_id=search_id, status="success", count=len(candidates))


@guarded
def acquisition_attempt(canonical_url, failed=False):
    state = _active.get()
    identity = digest(canonical_url)
    candidate_ids = [c["candidate_id"] for c in state["candidates"]
                     if c["canonical_identity"] == identity and c["reason"] == "pending"]
    identifier = emit("acquisition_failure" if failed else "acquisition_attempt",
        canonical_identity=identity, candidate_ids=candidate_ids,
        attempted=True, reason="retriever_exception" if failed else "selected")
    state["sources"][identity] = {"source_id": "", "attempted": True,
                                  "acquisition_id": identifier}


@guarded
def acquired(source, did_fetch):
    from application.sources.content_identity import acquired_content_identity
    identity = digest(source.canonical_url)
    event = {"canonical_identity": identity, "source_id": safe_text(source.id),
             "attempted": did_fetch, "status": safe_text(source.retrieval_status.value),
             "content_identity": acquired_content_identity(source), "content_length": len(source.content_text),
             "failure_category": safe_text(source.metadata.get("failure_category", ""))
                 if source.metadata.get("failure_category") in {"timeout", "http_error", "unsupported_content_type", "empty_content", "network_error"}
                 else ("none" if source.content_text else "other")}
    event["candidate_ids"] = [c["candidate_id"] for c in _active.get()["candidates"] if c["canonical_identity"] == identity and c["reason"] == "pending"]
    event["acquisition_id"] = emit("acquisition", **event)
    _active.get()["sources"][identity] = event


@guarded
def finish_selection(summary):
    state = _active.get()
    decisions = getattr(summary, "selection_decisions", ())
    primary = set()
    for candidate in state["candidates"]:
        identity = candidate["canonical_identity"]
        source = state["sources"].get(identity)
        matching = [d for d in decisions if digest(d.get("canonical_url", "")) == identity]
        reason = candidate["reason"]
        selected = False
        if reason == "pending":
            if source:
                selected = identity not in primary
                reason = "selected" if selected else "duplicate_url"
                primary.add(identity)
            elif matching:
                action = str(matching[-1].get("action", ""))
                reason = {
                    "skipped_duplicate_content": "duplicate_content",
                    "exhausted_for_need": "already_exhausted",
                    "skipped_budget": "acquisition_budget_unavailable",
                    "unrelated_rejected": "ineligible",
                }.get(action, "selection_rule")
            elif summary is None:
                reason = "stage_failed_before_selection"
            elif getattr(summary, "coverage_complete_early_stop", False):
                reason = "lower_priority_coverage_complete"
            else:
                reason = "acquisition_budget_unavailable"
        emit("candidate_decision", candidate_id=candidate["candidate_id"], target_in=candidate["target_in"],
             canonical_identity=identity, selected=selected, reason=reason,
             source_id=source["source_id"] if source else "",
             acquisition_id=source["acquisition_id"] if source else None,
             decision_code=safe_text(matching[-1].get("reason", "")) if matching else reason,
             attempted=bool(source and source["attempted"] and selected))
        if any(d.get("action") == "skipped_duplicate_content" for d in matching):
            emit("content_dedup", candidate_id=candidate["candidate_id"], canonical_identity=identity,
                 source_id=source["source_id"] if source else "", reason="duplicate_content")


@guarded
def extraction_start(item):
    from application.sources.content_identity import acquired_content_identity
    journal = _active.get()["journal"]
    journal["extraction_ordinal"] = journal.get("extraction_ordinal", 0) + 1
    return emit("extraction_start", extraction_ordinal=journal["extraction_ordinal"], source_id=safe_text(item.source.id),
        content_identity=acquired_content_identity(item.source), target_in=safe_text(item.primary_need_id),
        chunk_index=item.chunk_index, scope=[safe_text(n) for n in item.run_context.information_need_ids])


@guarded
def extraction_result(identifier, trace, capped=False):
    shapes = [{"response_classification": c.response_shape.response_classification,
               "structured_attempts": c.response_shape.structured_attempts}
              for c in trace.inner_chunks if c.response_shape is not None]
    classes = [s.get("response_classification", "") for s in shapes]
    status = trace.extractor_status
    if capped and status == "pending":
        status = "extraction_budget_unavailable"
    if trace.exception_class:
        status = "failure" if status != "budget_stop" else "extraction_budget_unavailable"
    elif any(c not in {"", "valid_candidates", "valid_empty_result"} for c in classes):
        status = "invalid_output"
    elif status == "no_candidates":
        status = "valid_empty"
    persisted = [o for o in trace.candidate_outcomes if o.outcome == "persisted"]
    target = sum(trace.primary_need_id in o.information_need_refs for o in persisted)
    emit("extraction_result", extraction_id=identifier, source_id=safe_text(trace.source_id),
         target_in=safe_text(trace.primary_need_id), status=status,
         evidence_count=len(persisted), target_evidence_count=target,
         cross_only_evidence_count=sum(trace.primary_need_id not in o.information_need_refs for o in persisted),
         cross_in_evidence_count=sum(any(n != trace.primary_need_id for n in o.information_need_refs) for o in persisted),
         retry_counts=[max(0, int(s.get("structured_attempts") or 1)-1) for s in shapes],
         rejections=[safe_text(o.rejection_reason) for o in trace.candidate_outcomes if o.outcome == "rejected"])
    for chunk_index, shape in enumerate(shapes):
        for ordinal in range(min(32, int(shape.get("structured_attempts") or 1))):
            emit("extraction_attempt", extraction_id=identifier, inner_chunk_index=chunk_index,
                 retry_ordinal=ordinal, outcome=(safe_text(shape["response_classification"])
                 if ordinal == int(shape.get("structured_attempts") or 1)-1 else "intermediate_outcome_not_retained"))


@guarded
def produced(evidence_id, source_id, refs, dedup_hit):
    emit("evidence", extraction_id=_extraction.get(), evidence_id=safe_text(evidence_id),
         source_id=safe_text(source_id), supported_ins=[safe_text(n) for n in refs], dedup_hit=dedup_hit)


@guarded
def qualification(evidence_id, need_id, qualifies, reason):
    emit("qualification", evidence_id=safe_text(evidence_id), supported_in=safe_text(need_id),
         qualifying=qualifies, reason=reason, policy="canonical_temporal_filter")


@guarded
def readiness_result(result):
    emit("readiness", ready_for_analysis=result.ready_for_analysis,
         termination_reason=safe_text(result.termination_reason))
    for assessment in result.research_question_assessments:
        for need in assessment.information_need_assessments:
            emit("need_sufficiency", target_in=safe_text(need.information_need_id),
                 status=safe_text(need.status.value), evidence_count=need.evidence_count,
                 independent_source_count=need.independent_source_count)


@guarded
def queue_dedup(before, after):
    from application.sources.content_identity import acquired_content_identity
    remaining = {(i.source.id, i.chunk_index) for i in after}
    for item in before:
        if (item.source.id, item.chunk_index) not in remaining:
            emit("extraction_skipped", source_id=safe_text(item.source.id),
                 content_identity=acquired_content_identity(item.source),
                 target_in=safe_text(item.primary_need_id), chunk_index=item.chunk_index,
                 reason="duplicate_content")


@guarded
def extraction_unattempted(queue, diagnostics):
    attempted = {(w.source_id, w.chunk_index) for w in diagnostics.work_items}
    for item in queue:
        if (item.source.id, item.chunk_index) not in attempted:
            emit("extraction_skipped", source_id=safe_text(item.source.id),
                 target_in=safe_text(item.primary_need_id), chunk_index=item.chunk_index,
                 reason=("extraction_budget_unavailable" if diagnostics.budget_stop or diagnostics.remediation_attempt_capped
                         else "stage_interrupted"))
