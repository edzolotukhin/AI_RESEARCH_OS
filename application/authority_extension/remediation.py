from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from application.authority_extension.selected_workflow import (
    AuthorityGap,
    AuthorityObservation,
    ExtensionBudgetExceeded,
    GapOutcome,
    SelectedAuthorityExtensionService,
    derive_gap_contract,
    gap_missing_dimensions,
    qualify_gap,
    _required_periods,
)
from application.research_quality.readiness_aggregation import (
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.research_loop_service import ResearchLoopService
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.sufficiency_status import SufficiencyStatus
from runtime.workflow_context import WorkflowContext


def _authority_kind(metadata: dict[str, Any]) -> str:
    assignment = metadata.get("semantic_assignment")
    if not isinstance(assignment, dict):
        return ""
    aspects = " ".join(
        str(item).casefold()
        for item in assignment.get("required_aspect_refs", ())
    )
    if any(item in aspects for item in ("real_volume", "real volume", "constant_price", "constant price")):
        return "retail_real_volume"
    if "deflator" in aspects:
        return "retail_deflator"
    if "cpi" in aspects or "consumer price" in aspects:
        return "cpi"
    return "nominal"


def evidence_observation(value) -> AuthorityObservation:
    metadata = value.metadata if isinstance(value.metadata, dict) else {}
    assignment = metadata.get("semantic_assignment")
    assignment = assignment if isinstance(assignment, dict) else {}
    geography_values = assignment.get("geography_applicability", ())
    geography = (
        str(geography_values[0])
        if isinstance(geography_values, list) and geography_values
        else ""
    )
    lineage = metadata.get("data_lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    period = str(metadata.get("observation_period", "")).strip()
    normalized_period = " ".join(period.casefold().split())
    normalized_excerpt = " ".join(value.source_excerpt.casefold().split())
    return AuthorityObservation(
        evidence_id=value.id,
        source_identity=str(
            lineage.get("origin_id")
            or metadata.get("acquired_content_identity")
            or value.source_id
        ),
        information_need_ids=tuple(value.information_need_refs),
        research_question_ids=tuple(value.research_question_refs),
        metric=" ".join(
            str(item) for item in assignment.get("required_aspect_refs", ())
        ) or value.statement,
        geography=geography,
        periods=(
            _required_periods(period)
            if normalized_period and normalized_period in normalized_excerpt
            else ()
        ),
        authority_kind=_authority_kind(metadata),
        workflow_run_id=value.workflow_run_id,
        research_design_id=value.research_design_id,
        project_id=value.project_id,
        conflicting=bool(metadata.get("conflicting", False)),
        observations=tuple(
            str(item) for item in metadata.get("observation_keys", ()) if str(item)
        ),
        source_type=str(metadata.get("source_type", "")),
        source_pattern_text=" ".join((value.statement, value.source_excerpt)),
    )


class ExtensionCoverageEvaluator:
    """Deterministic selected-IN readiness proof for the immutable gap contract."""

    def __init__(
        self,
        *,
        project_id: str | None = None,
        research_design_id: str | None = None,
        allowed_workflow_run_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.project_id = project_id
        self.research_design_id = research_design_id
        self.allowed_workflow_run_ids = allowed_workflow_run_ids

    def evaluate(self, *, design, evidence: Sequence) -> Any:
        gaps = derive_gap_contract(design, (item.id for item in design.information_needs))
        observations = tuple(
            evidence_observation(item)
            for item in evidence
            if (self.project_id is None or item.project_id == self.project_id)
            and (
                self.research_design_id is None
                or item.research_design_id == self.research_design_id
            )
            and (
                self.allowed_workflow_run_ids is None
                or item.workflow_run_id in self.allowed_workflow_run_ids
            )
        )
        assessments_by_question: dict[str, list[InformationNeedAssessment]] = {}
        for gap in gaps:
            relevant = tuple(
                item
                for item in observations
                if gap.information_need_id in item.information_need_ids
                and (
                    not gap.eligible_source_types
                    or item.source_type in gap.eligible_source_types
                )
                and not any(
                    pattern.casefold() in item.source_pattern_text.casefold()
                    for pattern in gap.prohibited_patterns
                )
            )
            outcome = qualify_gap(gap, observations)
            missing = gap_missing_dimensions(gap, observations)
            if outcome == GapOutcome.SATISFIED:
                status = SufficiencyStatus.SUFFICIENT
                gap_types: tuple[GapType, ...] = ()
            elif not relevant:
                status = SufficiencyStatus.MISSING
                gap_types = (GapType.NO_EVIDENCE,)
            elif any(item.conflicting for item in relevant):
                status = SufficiencyStatus.INSUFFICIENT
                gap_types = (GapType.CONFLICTING_EVIDENCE,)
            else:
                status = SufficiencyStatus.INSUFFICIENT
                gap_types = (GapType.INSUFFICIENT_DEPTH,)
                if any(item.startswith("independent_sources:") for item in missing):
                    gap_types = (*gap_types, GapType.INSUFFICIENT_DIVERSITY)
            directives = tuple(_directive(gap, item) for item in missing)[:5]
            assessment = InformationNeedAssessment(
                information_need_id=gap.information_need_id,
                research_question_id=gap.research_question_id,
                status=status,
                evidence_count=len(relevant),
                independent_source_count=len({item.source_identity for item in relevant}),
                quantitative_evidence_present=bool(relevant) if gap.quantitative else None,
                missing_aspects=missing,
                gap_types=gap_types,
                search_directives=directives,
                reason=(
                    "Explicit authority coverage contract satisfied."
                    if outcome == GapOutcome.SATISFIED
                    else "Missing authority dimensions: " + ", ".join(missing)
                ),
                quality_contract_mode=(
                    "explicit_expectation"
                    if next(
                        item for item in design.information_needs
                        if item.id == gap.information_need_id
                    ).evidence_coverage is not None
                    else "legacy_need"
                ),
            )
            assessments_by_question.setdefault(gap.research_question_id, []).append(
                assessment
            )
        rq_assessments = tuple(
            build_research_readiness_assessment(
                research_question_id=question.id,
                need_assessments=assessments_by_question.get(question.id, ()),
            )
            for question in design.research_questions
        )
        return build_research_readiness_result(rq_assessments)


def _directive(gap: AuthorityGap, missing: str) -> str:
    value = missing.replace(":", " ")
    return " ".join(
        item for item in (gap.metric, gap.geography, value) if item
    )


@dataclass
class AuthorityExtensionRemediationAdapter:
    service: SelectedAuthorityExtensionService
    loop_service: ResearchLoopService
    evidence_repository: Any
    source_repository: Any

    def _member_run_ids(self, context: WorkflowContext) -> tuple[str, ...]:
        state = self.service._state(context.workflow_run.id)
        extension = self.service.extensions.get_by_id(state.extension_id)
        return (
            extension.parent_source_workflow_run_id,
            extension.extension_workflow_run_id,
        )

    def evidence_scope(self, context: WorkflowContext) -> tuple:
        seen: set[str] = set()
        values = []
        for run_id in self._member_run_ids(context):
            for item in self.evidence_repository.list_for_project(
                context.project.id,
                workflow_run_id=run_id,
            ):
                if item.id not in seen:
                    seen.add(item.id)
                    values.append(item)
        return tuple(values)

    def source_scope(self, context: WorkflowContext) -> tuple:
        seen: set[str] = set()
        values = []
        for run_id in self._member_run_ids(context):
            for item in self.source_repository.list_for_project(
                context.project.id,
                workflow_run_id=run_id,
            ):
                if item.id not in seen:
                    seen.add(item.id)
                    values.append(item)
        return tuple(values)

    def run(self, context: WorkflowContext) -> WorkflowContext:
        extension = self.service.extensions.get_by_id(
            self.service._state(context.workflow_run.id).extension_id,
        )
        assert extension is not None
        evaluator = ExtensionCoverageEvaluator(
            project_id=extension.project_id,
            research_design_id=extension.research_design_id,
            allowed_workflow_run_ids=self._member_run_ids(context),
        )
        scoped_loop = self.loop_service.scoped_copy(
            evaluator=evaluator,
            evidence_scope=self.evidence_scope,
            source_scope=self.source_scope,
            progress_evaluator=_coverage_progress,
        )
        initial = evaluator.evaluate(
            design=context.workflow_template.research_design_snapshot,
            evidence=self.evidence_scope(context),
        )
        try:
            result, loop_state = scoped_loop.run_bounded_loop(
                context,
                initial_result=initial,
            )
            reason = loop_state.termination_reason or result.termination_reason
        except ExtensionBudgetExceeded as exc:
            reason = str(exc)
        self.service.record_remediation_terminal_reason(
            context.workflow_run.id,
            reason,
        )
        context.write_shared(
            "authority_extension_remediation",
            {"terminal_reason": reason},
        )
        return context


def _coverage_progress(before, after, information_need_id: str) -> bool:
    def need(result):
        return next(
            (
                item
                for assessment in result.research_question_assessments
                for item in assessment.information_need_assessments
                if item.information_need_id == information_need_id
            ),
            None,
        )

    old = need(before)
    new = need(after)
    if old is None or new is None:
        return False
    if old.status != new.status and new.status.value == "sufficient":
        return True
    old_missing = set(old.missing_aspects)
    new_missing = set(new.missing_aspects)
    if old_missing and new_missing < old_missing:
        return True
    return False
