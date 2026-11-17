"""Provider-free construction of authoritative ReportClaim v2 lineage material."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from application.analysis.numeric_integrity import (
    NumericQualificationResult,
    ValidatedNumericObservation,
    is_numeric_acquired_need,
    same,
)
from application.evidence.temporal_scope import NO_EXPLICIT_TEMPORAL_CONSTRAINT
from application.report.claim_contract import authority_digest_v2, component_digest_v2
from application.research_scope.numeric_normalization import normalize_numeric_value
from domain.reports.report_claim import ClaimScope


class ClaimLineageV2Error(ValueError):
    pass


_TEMPORALLY_ELIGIBLE = frozenset({
    "applicable_satisfied", "not_applicable", NO_EXPLICIT_TEMPORAL_CONSTRAINT,
})


@dataclass(frozen=True)
class ClaimLineageV2Material:
    project_id: str
    source_workflow_run_id: str
    report_workflow_run_id: str
    design_id: str
    finding_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    scope: ClaimScope
    finding_content_digests: Mapping[str, str]
    insight_content_digests: Mapping[str, str]
    insight_finding_refs: Mapping[str, tuple[str, ...]]
    evidence_content_digests: Mapping[str, str]
    source_revision_digests: Mapping[str, str]
    numeric_observation_proof_digests: Mapping[str, str]
    authority_digest: str


def build_claim_lineage_v2(
    *, project_id: str, source_workflow_run_id: str, report_workflow_run_id: str,
    design: Any, scope: ClaimScope, findings: Sequence[Any], insights: Sequence[Any],
    evidence_by_id: Mapping[str, Any], source_by_id: Mapping[str, Any],
    temporal_decisions: Mapping[tuple[str, str], str],
    allowed_workflow_run_ids: Sequence[str],
    numeric_qualifications: Mapping[str, NumericQualificationResult],
) -> ClaimLineageV2Material:
    """Build immutable lineage from persisted authority; never creates a ReportClaim."""
    allowed_runs = tuple(sorted(set(allowed_workflow_run_ids)))
    if not all((project_id, source_workflow_run_id, report_workflow_run_id, design.id)):
        raise ClaimLineageV2Error("lineage identity is incomplete")
    if source_workflow_run_id not in allowed_runs or not findings:
        raise ClaimLineageV2Error("source workflow authority is unavailable")
    design_need_ids = {item.id for item in design.information_needs}
    design_rq_ids = {item.id for item in design.research_questions}
    needs_by_id = {item.id: item for item in design.information_needs}

    finding_by_id: dict[str, Any] = {}
    evidence_ids: set[str] = set()
    for finding in findings:
        if finding.id in finding_by_id:
            raise ClaimLineageV2Error("duplicate Finding authority")
        if (finding.project_id != project_id or finding.research_design_id != design.id
                or finding.workflow_run_id != source_workflow_run_id
                or finding.workflow_run_id not in allowed_runs):
            raise ClaimLineageV2Error("Finding authority is foreign")
        if (not finding.evidence_refs or not set(finding.information_need_refs) <= design_need_ids
                or not set(finding.research_question_refs) <= design_rq_ids):
            raise ClaimLineageV2Error("Finding graph is unsupported")
        finding_by_id[finding.id] = finding
        evidence_ids.update(finding.evidence_refs)

    insight_by_id: dict[str, Any] = {}
    selected_finding_ids = set(finding_by_id)
    for insight in insights:
        if insight.id in insight_by_id:
            raise ClaimLineageV2Error("duplicate Insight authority")
        if (insight.project_id != project_id or insight.research_design_id != design.id
                or insight.workflow_run_id != source_workflow_run_id
                or insight.workflow_run_id not in allowed_runs):
            raise ClaimLineageV2Error("Insight authority is foreign")
        if not insight.finding_refs or not set(insight.finding_refs) <= selected_finding_ids:
            raise ClaimLineageV2Error("Insight Finding graph is incomplete or foreign")
        insight_by_id[insight.id] = insight

    evidence: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    for evidence_id in sorted(evidence_ids):
        item = evidence_by_id.get(evidence_id)
        if item is None:
            raise ClaimLineageV2Error("referenced Evidence is missing")
        if (item.project_id != project_id or item.research_design_id != design.id
                or item.workflow_run_id != source_workflow_run_id
                or item.workflow_run_id not in allowed_runs
                or not set(item.information_need_refs) <= design_need_ids
                or not set(item.research_question_refs) <= design_rq_ids):
            raise ClaimLineageV2Error("Evidence authority is foreign")
        if not item.information_need_refs:
            raise ClaimLineageV2Error("Evidence InformationNeed authority is missing")
        for need_id in item.information_need_refs:
            if temporal_decisions.get((item.id, need_id)) not in _TEMPORALLY_ELIGIBLE:
                raise ClaimLineageV2Error("Evidence temporal authority is unavailable")
        source = source_by_id.get(item.source_id)
        if source is None:
            raise ClaimLineageV2Error("referenced Source revision is missing")
        if (source.project_id != project_id or source.id != item.source_id
                or item.source_content_checksum != source.content_checksum
                or source_workflow_run_id not in tuple(source.workflow_run_refs)
                or design.id not in tuple(source.research_design_refs)
                or not all((source.content_checksum, source.terminal_resource_key,
                            source.raw_content_checksum, source.raw_checksum_kind,
                            source.extraction_revision))
                or source.content_revision < 1):
            raise ClaimLineageV2Error("Evidence Source revision identity mismatch")
        evidence[item.id] = item
        sources[source.id] = source

    for finding in findings:
        finding_needs = set(finding.information_need_refs)
        finding_questions = set(finding.research_question_refs)
        for evidence_id in finding.evidence_refs:
            item = evidence[evidence_id]
            evidence_needs = set(item.information_need_refs)
            evidence_questions = set(item.research_question_refs)
            if (not evidence_needs or not evidence_needs <= finding_needs
                    or not evidence_questions or not evidence_questions <= finding_questions):
                raise ClaimLineageV2Error("Evidence does not support Finding requirements")

    proof_digests: dict[str, str] = {}
    accepted_observations: list[ValidatedNumericObservation] = []
    for need_id in sorted({ref for finding in findings for ref in finding.information_need_refs}):
        need = needs_by_id[need_id]
        if not is_numeric_acquired_need(need):
            continue
        qualification = numeric_qualifications.get(need_id)
        if qualification is None or qualification.information_need_id != need_id or not qualification.available:
            raise ClaimLineageV2Error("numeric qualification is unavailable")
        accepted_items = tuple(qualification.accepted_evidence)
        accepted_ids = {item.id for item in accepted_items}
        observations = tuple(qualification.observations)
        observation_ids = [item.evidence_id for item in observations]
        if (len(accepted_ids) != len(accepted_items) or len(set(observation_ids)) != len(observation_ids)
                or accepted_ids != set(observation_ids)):
            raise ClaimLineageV2Error("numeric accepted Evidence and observations disagree")
        required_ids = {
            item.id for item in evidence.values() if need_id in item.information_need_refs
        }
        if not required_ids <= accepted_ids:
            raise ClaimLineageV2Error("Finding cites rejected numeric Evidence")
        accepted_by_id = {item.id: item for item in accepted_items}
        for evidence_id in required_ids:
            accepted = accepted_by_id[evidence_id]
            authoritative = evidence[evidence_id]
            if (accepted.project_id != authoritative.project_id
                    or accepted.workflow_run_id != authoritative.workflow_run_id
                    or accepted.research_design_id != authoritative.research_design_id
                    or accepted.source_id != authoritative.source_id
                    or accepted.source_content_checksum != authoritative.source_content_checksum):
                raise ClaimLineageV2Error("numeric accepted Evidence authority mismatch")
        for observation in (item for item in observations if item.evidence_id in required_ids):
            _validate_numeric_observation_lineage(
                observation, need_id=need_id, evidence=evidence, sources=sources,
                temporal_decisions=temporal_decisions,
            )
            if observation.evidence_id in proof_digests:
                raise ClaimLineageV2Error("multiple numeric proofs per Evidence are unsupported")
            proof_digests[observation.evidence_id] = component_digest_v2(
                _numeric_observation_payload(observation),
            )
            accepted_observations.append(observation)

    if accepted_observations:
        _validate_numeric_scope(scope, accepted_observations)

    finding_digests = {
        item.id: component_digest_v2(_finding_payload(item))
        for item in sorted(findings, key=lambda value: value.id)
    }
    insight_digests = {
        item.id: component_digest_v2(_insight_payload(item))
        for item in sorted(insights, key=lambda value: value.id)
    }
    insight_refs = {
        item.id: tuple(sorted(item.finding_refs))
        for item in sorted(insights, key=lambda value: value.id)
    }
    evidence_digests = {
        item.id: component_digest_v2(_evidence_payload(item))
        for item in sorted(evidence.values(), key=lambda value: value.id)
    }
    source_digests = {
        item.id: component_digest_v2(_source_revision_payload(item))
        for item in sorted(sources.values(), key=lambda value: value.id)
    }
    material = ClaimLineageV2Material(
        project_id=project_id, source_workflow_run_id=source_workflow_run_id,
        report_workflow_run_id=report_workflow_run_id, design_id=design.id,
        finding_ids=tuple(sorted(finding_by_id)), insight_ids=tuple(sorted(insight_by_id)),
        evidence_ids=tuple(sorted(evidence)), source_ids=tuple(sorted(sources)), scope=scope,
        finding_content_digests=MappingProxyType(finding_digests),
        insight_content_digests=MappingProxyType(insight_digests),
        insight_finding_refs=MappingProxyType(insight_refs),
        evidence_content_digests=MappingProxyType(evidence_digests),
        source_revision_digests=MappingProxyType(source_digests),
        numeric_observation_proof_digests=MappingProxyType(dict(sorted(proof_digests.items()))),
        authority_digest="",
    )
    return replace(material, authority_digest=authority_digest_v2(material))


def _validate_numeric_observation_lineage(
    observation: ValidatedNumericObservation, *, need_id: str,
    evidence: Mapping[str, Any], sources: Mapping[str, Any],
    temporal_decisions: Mapping[tuple[str, str], str],
) -> None:
    item = evidence.get(observation.evidence_id)
    source = sources.get(observation.source_id)
    if item is None or source is None or item.source_id != source.id:
        raise ClaimLineageV2Error("numeric observation graph is incomplete")
    if temporal_decisions.get((item.id, need_id)) != "applicable_satisfied":
        raise ClaimLineageV2Error("numeric observation temporal authority is unavailable")
    if (observation.information_need_id != need_id
            or observation.source_content_checksum != source.content_checksum
            or observation.raw_content_checksum != source.raw_content_checksum
            or observation.raw_checksum_kind != source.raw_checksum_kind
            or observation.terminal_resource_key != source.terminal_resource_key
            or observation.extraction_revision != source.extraction_revision
            or observation.content_revision != source.content_revision):
        raise ClaimLineageV2Error("numeric observation Source revision mismatch")


def _validate_numeric_scope(
    scope: ClaimScope, observations: Sequence[ValidatedNumericObservation],
) -> None:
    for fact in scope.numeric_facts:
        if not fact.metrics or not fact.geography or not fact.periods:
            raise ClaimLineageV2Error("numeric ClaimScope fact is incomplete")
        expected_value = normalize_numeric_value(fact.value)
        for metric in fact.metrics:
            for geography in fact.geography:
                for period in fact.periods:
                    if not any(
                        normalize_numeric_value(item.value) == expected_value
                        and same(item.unit, fact.unit)
                        and same(item.metric, metric)
                        and same(item.geography, geography)
                        and item.period == period
                        for item in observations
                    ):
                        raise ClaimLineageV2Error("numeric ClaimScope fact lacks accepted observation authority")


def _finding_payload(item: Any) -> dict[str, Any]:
    return {
        "statement": item.statement, "rationale": item.rationale,
        "evidence_refs": sorted(item.evidence_refs),
        "research_question_refs": sorted(item.research_question_refs),
        "information_need_refs": sorted(item.information_need_refs),
        "finding_type": item.finding_type.value, "confidence": item.confidence,
        "analysis_method": item.analysis_method,
        "validated_derivation": item.metadata.get("derivation"),
    }


def _insight_payload(item: Any) -> dict[str, Any]:
    return {
        "statement": item.statement, "implication": item.implication,
        "finding_refs": sorted(item.finding_refs),
        "research_question_refs": sorted(item.research_question_refs),
        "confidence": item.confidence,
    }


def _evidence_payload(item: Any) -> dict[str, Any]:
    return {
        "statement": item.statement, "source_excerpt": item.source_excerpt,
        "source_id": item.source_id, "source_content_checksum": item.source_content_checksum,
        "research_question_refs": sorted(item.research_question_refs),
        "information_need_refs": sorted(item.information_need_refs),
        "evidence_type": item.evidence_type.value, "source_locator": item.source_locator,
        "extraction_method": item.extraction_method,
    }


def _source_revision_payload(item: Any) -> dict[str, Any]:
    return {
        "source_id": item.id, "content_checksum": item.content_checksum,
        "raw_content_checksum": item.raw_content_checksum,
        "raw_checksum_kind": item.raw_checksum_kind,
        "terminal_resource_key": item.terminal_resource_key,
        "content_revision": item.content_revision,
        "extraction_revision": item.extraction_revision,
        "workflow_run_refs": sorted(item.workflow_run_refs),
        "research_design_refs": sorted(item.research_design_refs),
    }


def _numeric_observation_payload(item: ValidatedNumericObservation) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id, "source_id": item.source_id,
        "information_need_id": item.information_need_id,
        "subject_id": item.subject_id, "subject_fingerprint": item.subject_fingerprint,
        "metric": item.metric, "unit": item.unit, "geography": item.geography,
        "period": item.period, "value": _decimal_text(item.value),
        "source_content_checksum": item.source_content_checksum,
        "raw_content_checksum": item.raw_content_checksum,
        "raw_checksum_kind": item.raw_checksum_kind,
        "terminal_resource_key": item.terminal_resource_key,
        "extraction_revision": item.extraction_revision,
        "content_revision": item.content_revision, "cell": item.cell,
        "lineage": dict(item.lineage),
    }


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
