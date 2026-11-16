"""Side-effect-free regeneration of a ReportClaim v2 revision.

``VerifiedV2RevisionInput`` is a trust-boundary object, not a verification
mechanism. Only the future F4-B4b2 orchestration layer may construct it after
independent persisted verification and proposition validation. This module
checks internal consistency and rebuilds authority; it never verifies the
receipt of that external verification itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from application.report.claim_contract import authority_digest_v2, claim_digest_v2
from application.report.claim_lineage_v2 import ClaimLineageV2Error, build_claim_lineage_v2
from application.analysis.numeric_integrity import NumericQualificationResult
from domain.reports.report_claim import REPORT_CLAIM_V2_VERSION, ReportClaim


class ClaimRevisionV2Error(ValueError):
    """Raised when a v2 revision cannot be rebuilt from authoritative inputs."""


@dataclass(frozen=True)
class VerifiedV2RevisionInput:
    """Explicit input contract supplied by the authoritative orchestrator.

    The fields are copied from the independently verified persisted claim and
    must match it exactly. Their presence is not evidence of verification;
    provenance of this object remains the responsibility of F4-B4b2.
    """

    claim: ReportClaim
    verified_proposition: str
    finding_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClaimRevisionV2Context:
    design: Any
    findings: tuple[Any, ...]
    insights: tuple[Any, ...]
    evidence_by_id: Mapping[str, Any]
    source_by_id: Mapping[str, Any]
    temporal_decisions: Mapping[tuple[str, str], str]
    allowed_workflow_run_ids: tuple[str, ...]
    numeric_qualifications: Mapping[str, NumericQualificationResult]


def rebuild_report_claim_v2(
    verified_input: VerifiedV2RevisionInput,
    *,
    new_report_id: str,
    new_report_revision: int,
    report_workflow_run_id: str,
    validated_at: str,
    context: ClaimRevisionV2Context,
) -> ReportClaim:
    """Rebuild one v2 claim without persistence or production routing.

    Independent verification is deliberately not performed here. F4-B4b2 must
    construct ``verified_input`` only after it has independently verified the
    persisted claim and proposition against authoritative records.
    """
    previous_claim = verified_input.claim
    if (previous_claim.version != REPORT_CLAIM_V2_VERSION
            or previous_claim.contract_version != REPORT_CLAIM_V2_VERSION):
        raise ClaimRevisionV2Error("previous claim must be an exact ReportClaim v2")
    if not new_report_id or new_report_revision < 1 or not report_workflow_run_id or not validated_at:
        raise ClaimRevisionV2Error("new report identity is incomplete")
    if (verified_input.verified_proposition != previous_claim.proposition
            or tuple(sorted(verified_input.finding_ids)) != tuple(sorted(previous_claim.finding_ids))
            or tuple(sorted(verified_input.insight_ids)) != tuple(sorted(previous_claim.insight_ids))
            or tuple(sorted(verified_input.evidence_ids)) != tuple(sorted(previous_claim.evidence_ids))
            or tuple(sorted(verified_input.source_ids)) != tuple(sorted(previous_claim.source_ids))):
        raise ClaimRevisionV2Error("verified revision input is inconsistent with the persisted claim")

    selected_finding_ids = tuple(sorted(item.id for item in context.findings))
    selected_insight_ids = tuple(sorted(item.id for item in context.insights))
    selected_evidence_ids = tuple(sorted({ref for item in context.findings for ref in item.evidence_refs}))
    selected_source_ids = tuple(sorted({context.evidence_by_id[item].source_id for item in selected_evidence_ids
                                        if item in context.evidence_by_id}))
    selected_rq_ids = tuple(sorted({ref for item in context.findings for ref in item.research_question_refs}))
    selected_need_ids = tuple(sorted({ref for item in context.findings for ref in item.information_need_refs}))
    if (selected_finding_ids != tuple(sorted(verified_input.finding_ids))
            or selected_insight_ids != tuple(sorted(verified_input.insight_ids))
            or selected_evidence_ids != tuple(sorted(previous_claim.evidence_ids))
            or selected_evidence_ids != tuple(sorted(previous_claim.support_evidence_ids))
            or selected_source_ids != tuple(sorted(previous_claim.source_ids))):
        raise ClaimRevisionV2Error("revision context does not preserve selected claim support")

    try:
        material = build_claim_lineage_v2(
            project_id=previous_claim.project_id,
            source_workflow_run_id=previous_claim.source_workflow_run_id,
            report_workflow_run_id=report_workflow_run_id,
            design=context.design,
            scope=previous_claim.scope,
            findings=context.findings,
            insights=context.insights,
            evidence_by_id=context.evidence_by_id,
            source_by_id=context.source_by_id,
            temporal_decisions=context.temporal_decisions,
            allowed_workflow_run_ids=context.allowed_workflow_run_ids,
            numeric_qualifications=context.numeric_qualifications,
        )
    except (ClaimLineageV2Error, KeyError, LookupError, TypeError, ValueError) as exc:
        raise ClaimRevisionV2Error("authoritative v2 lineage cannot be rebuilt") from exc

    if (material.design_id != previous_claim.design_id
            or selected_rq_ids != tuple(sorted(previous_claim.research_question_ids))
            or selected_need_ids != tuple(sorted(previous_claim.information_need_ids))):
        raise ClaimRevisionV2Error("revision context does not preserve claim scope identity")

    if (dict(material.finding_content_digests) != dict(previous_claim.finding_content_digests)
            or dict(material.insight_content_digests) != dict(previous_claim.insight_content_digests)
            or dict(material.insight_finding_refs) != dict(previous_claim.insight_finding_refs)
            or dict(material.evidence_content_digests) != dict(previous_claim.evidence_content_digests)
            or dict(material.source_revision_digests) != dict(previous_claim.source_revision_digests)
            or dict(material.numeric_observation_proof_digests) != dict(previous_claim.numeric_observation_proof_digests)):
        raise ClaimRevisionV2Error("upstream authority changed since the verified claim")

    claim_id = str(uuid5(NAMESPACE_URL, f"{new_report_id}:{new_report_revision}:{previous_claim.claim_id}"))
    values = {
        "claim_id": claim_id,
        "project_id": previous_claim.project_id,
        "source_workflow_run_id": previous_claim.source_workflow_run_id,
        "report_workflow_run_id": report_workflow_run_id,
        "design_id": previous_claim.design_id,
        "research_question_ids": selected_rq_ids,
        "information_need_ids": selected_need_ids,
        "finding_ids": material.finding_ids,
        "insight_ids": material.insight_ids,
        "evidence_ids": material.evidence_ids,
        "kind": previous_claim.kind,
        "proposition": previous_claim.proposition,
        "certainty": previous_claim.certainty,
        "direction": previous_claim.direction,
        "scope": material.scope,
        "support_evidence_ids": material.evidence_ids,
        "source_ids": material.source_ids,
        "citation_ids": previous_claim.citation_ids,
        "finding_content_digests": dict(material.finding_content_digests),
        "evidence_content_digests": dict(material.evidence_content_digests),
        "status": previous_claim.status,
        "contract_version": REPORT_CLAIM_V2_VERSION,
        "authority_digest": "",
        "validated_at": validated_at,
        "version": REPORT_CLAIM_V2_VERSION,
        "insight_content_digests": dict(material.insight_content_digests),
        "insight_finding_refs": dict(material.insight_finding_refs),
        "source_revision_digests": dict(material.source_revision_digests),
        "numeric_observation_proof_digests": dict(material.numeric_observation_proof_digests),
        "claim_digest": "",
    }
    draft = SimpleNamespace(**values)
    values["authority_digest"] = authority_digest_v2(draft)
    draft.authority_digest = values["authority_digest"]
    values["claim_digest"] = claim_digest_v2(draft)
    return ReportClaim(**values)
