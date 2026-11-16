"""Independent, provider-free verification of persisted ReportClaim v2 authority.

The returned snapshot is defensively detached from repository-owned objects.
It is not a recursively frozen object graph: callers must treat the detached
domain values as read-only by contract.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import copy
from types import MappingProxyType
from typing import Any, Mapping

from application.analysis.numeric_integrity import (
    is_numeric_acquired_need,
    qualify_numeric_information_need,
)
from application.evidence.temporal_scope import qualify_evidence_with_temporal_decisions
from application.report.claim_contract import claim_digest_v2
from application.report.claim_lineage_v2 import ClaimLineageV2Error, ClaimLineageV2Material, build_claim_lineage_v2
from application.report.claim_rendering import validate_claim_proposition
from domain.reports.report_claim import REPORT_CLAIM_V2_VERSION, ReportClaim


class ClaimLineageVerificationV2Error(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedClaimLineageV2Snapshot:
    """Defensively detached authority read-set from one verification pass.

    ``frozen=True`` protects the snapshot container only. It does not claim
    deep immutability for every nested domain value.
    """

    claim: ReportClaim
    report: Any
    design: Any
    brief: Any
    findings: tuple[Any, ...]
    insights: tuple[Any, ...]
    evidence_by_id: Mapping[str, Any]
    source_by_id: Mapping[str, Any]
    temporal_decisions: Mapping[tuple[str, str], str]
    numeric_qualifications: Mapping[str, Any]
    material: ClaimLineageV2Material

    def __post_init__(self) -> None:
        """Detach the verified read-set from mutable repository objects."""
        object.__setattr__(self, "claim", copy.deepcopy(self.claim))
        object.__setattr__(self, "report", copy.deepcopy(self.report))
        object.__setattr__(self, "design", copy.deepcopy(self.design))
        object.__setattr__(self, "brief", copy.deepcopy(self.brief))
        object.__setattr__(self, "findings", copy.deepcopy(self.findings))
        object.__setattr__(self, "insights", copy.deepcopy(self.insights))
        object.__setattr__(self, "evidence_by_id", MappingProxyType(copy.deepcopy(dict(self.evidence_by_id))))
        object.__setattr__(self, "source_by_id", MappingProxyType(copy.deepcopy(dict(self.source_by_id))))
        object.__setattr__(self, "temporal_decisions", MappingProxyType(copy.deepcopy(dict(self.temporal_decisions))))
        object.__setattr__(self, "numeric_qualifications", MappingProxyType(copy.deepcopy(dict(self.numeric_qualifications))))
        detached_material = replace(
            self.material,
            finding_content_digests=MappingProxyType(copy.deepcopy(dict(self.material.finding_content_digests))),
            insight_content_digests=MappingProxyType(copy.deepcopy(dict(self.material.insight_content_digests))),
            insight_finding_refs=MappingProxyType(copy.deepcopy(dict(self.material.insight_finding_refs))),
            evidence_content_digests=MappingProxyType(copy.deepcopy(dict(self.material.evidence_content_digests))),
            source_revision_digests=MappingProxyType(copy.deepcopy(dict(self.material.source_revision_digests))),
            numeric_observation_proof_digests=MappingProxyType(copy.deepcopy(dict(self.material.numeric_observation_proof_digests))),
        )
        object.__setattr__(self, "material", detached_material)

    def to_revision_inputs(self):
        """Adapt this exact read-set for the inactive revision builder."""
        from application.report.claim_revision_v2 import ClaimRevisionV2Context, VerifiedV2RevisionInput
        context = ClaimRevisionV2Context(
            design=self.design,
            findings=self.findings,
            insights=self.insights,
            evidence_by_id=self.evidence_by_id,
            source_by_id=self.source_by_id,
            temporal_decisions=self.temporal_decisions,
            allowed_workflow_run_ids=(self.claim.source_workflow_run_id,),
            numeric_qualifications=self.numeric_qualifications,
        )
        verified = VerifiedV2RevisionInput(
            claim=self.claim,
            verified_proposition=self.claim.proposition,
            finding_ids=self.claim.finding_ids,
            insight_ids=self.claim.insight_ids,
            evidence_ids=self.claim.evidence_ids,
            source_ids=self.claim.source_ids,
        )
        return verified, context


def verify_persisted_claim_v2(
    *, claim: ReportClaim, report: Any, finding_repository: Any,
    insight_repository: Any, evidence_repository: Any, source_repository: Any,
    workflow_run_repository: Any, workflow_template_repository: Any,
    proposition_trace: dict[str, Any] | None = None,
) -> ReportClaim:
    """Verify v2 and preserve the historical claim-returning API."""
    original_claim = claim
    verify_persisted_claim_v2_snapshot(
        claim=claim, report=report, finding_repository=finding_repository,
        insight_repository=insight_repository, evidence_repository=evidence_repository,
        source_repository=source_repository, workflow_run_repository=workflow_run_repository,
        workflow_template_repository=workflow_template_repository,
        proposition_trace=proposition_trace,
    )
    return original_claim


def verify_persisted_claim_v2_snapshot(
    *, claim: ReportClaim, report: Any, finding_repository: Any,
    insight_repository: Any, evidence_repository: Any, source_repository: Any,
    workflow_run_repository: Any, workflow_template_repository: Any,
    proposition_trace: dict[str, Any] | None = None,
) -> VerifiedClaimLineageV2Snapshot:
    """Verify v2 and return the exact immutable authority read-set used."""
    try:
        if claim.version != REPORT_CLAIM_V2_VERSION or claim.contract_version != REPORT_CLAIM_V2_VERSION:
            raise ClaimLineageVerificationV2Error("exact ReportClaim v2 contract is required")
        if (claim.project_id != report.project_id
                or claim.report_workflow_run_id != report.workflow_run_id
                or claim.design_id != report.research_design_id):
            raise ClaimLineageVerificationV2Error("ReportClaim Report context mismatch")
        if claim.claim_digest != claim_digest_v2(claim):
            raise ClaimLineageVerificationV2Error("ReportClaim v2 claim digest mismatch")
        validate_claim_proposition(claim, h2_trace=proposition_trace)

        source_run = workflow_run_repository.get_by_id(claim.source_workflow_run_id)
        if source_run is None or source_run.project_id != claim.project_id:
            raise ClaimLineageVerificationV2Error("source WorkflowRun is missing or foreign")
        template = workflow_template_repository.get_by_id(source_run.workflow_template_id)
        if template is None:
            raise ClaimLineageVerificationV2Error("source WorkflowTemplate is missing")
        design = template.research_design_snapshot
        brief = template.research_brief_snapshot
        if design is None or brief is None or design.id != claim.design_id:
            raise ClaimLineageVerificationV2Error("authoritative Design or Brief is unavailable")

        findings = _load_exact(finding_repository, claim.finding_ids, "Finding")
        insights = _load_exact(insight_repository, claim.insight_ids, "Insight")
        evidence = _load_exact(evidence_repository, claim.evidence_ids, "Evidence")
        sources = _load_exact(source_repository, claim.source_ids, "Source")
        evidence_by_id = {item.id: item for item in evidence}
        source_by_id = {item.id: item for item in sources}

        temporal = qualify_evidence_with_temporal_decisions(
            design=design, evidence=evidence, brief=brief,
            source_repository=source_repository,
        )
        selected_need_ids = {ref for item in findings for ref in item.information_need_refs}
        qualifications = {
            need.id: qualify_numeric_information_need(
                design=design, information_need=need, evidence=evidence,
                source_repository=source_repository,
                temporal_decisions=temporal.decisions,
                allowed_workflow_run_ids=(claim.source_workflow_run_id,),
            )
            for need in design.information_needs
            if need.id in selected_need_ids and is_numeric_acquired_need(need)
        }
        material = build_claim_lineage_v2(
            project_id=claim.project_id,
            source_workflow_run_id=claim.source_workflow_run_id,
            report_workflow_run_id=claim.report_workflow_run_id,
            design=design, scope=claim.scope, findings=findings, insights=insights,
            evidence_by_id=evidence_by_id, source_by_id=source_by_id,
            temporal_decisions=temporal.decisions,
            allowed_workflow_run_ids=(claim.source_workflow_run_id,),
            numeric_qualifications=qualifications,
        )
        comparisons = (
            (claim.project_id, material.project_id),
            (claim.source_workflow_run_id, material.source_workflow_run_id),
            (claim.report_workflow_run_id, material.report_workflow_run_id),
            (claim.design_id, material.design_id),
            (claim.finding_ids, material.finding_ids),
            (claim.insight_ids, material.insight_ids),
            (claim.evidence_ids, material.evidence_ids),
            (claim.source_ids, material.source_ids),
            (claim.scope, material.scope),
            (dict(claim.finding_content_digests), dict(material.finding_content_digests)),
            (dict(claim.insight_content_digests), dict(material.insight_content_digests)),
            (dict(claim.insight_finding_refs), dict(material.insight_finding_refs)),
            (dict(claim.evidence_content_digests), dict(material.evidence_content_digests)),
            (dict(claim.source_revision_digests), dict(material.source_revision_digests)),
            (dict(claim.numeric_observation_proof_digests), dict(material.numeric_observation_proof_digests)),
            (claim.authority_digest, material.authority_digest),
        )
        if any(persisted != authoritative for persisted, authoritative in comparisons):
            raise ClaimLineageVerificationV2Error("persisted ReportClaim v2 authority is stale or corrupted")
        return VerifiedClaimLineageV2Snapshot(
            claim=claim, report=report, design=design, brief=brief,
            findings=findings, insights=insights,
            evidence_by_id=MappingProxyType(dict(evidence_by_id)),
            source_by_id=MappingProxyType(dict(source_by_id)),
            temporal_decisions=MappingProxyType(dict(temporal.decisions)),
            numeric_qualifications=MappingProxyType(dict(qualifications)),
            material=material,
        )
    except ClaimLineageVerificationV2Error:
        raise
    except (ClaimLineageV2Error, KeyError, LookupError, AttributeError, TypeError, ValueError) as exc:
        raise ClaimLineageVerificationV2Error("authoritative ReportClaim v2 verification failed") from exc


def _load_exact(repository: Any, identifiers: tuple[str, ...], label: str) -> tuple[Any, ...]:
    loaded = []
    for identifier in identifiers:
        item = repository.get_by_id(identifier)
        if item is None or item.id != identifier:
            raise ClaimLineageVerificationV2Error(f"authoritative {label} is missing")
        loaded.append(item)
    if len({item.id for item in loaded}) != len(identifiers):
        raise ClaimLineageVerificationV2Error(f"authoritative {label} identity is ambiguous")
    return tuple(loaded)
