from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.report.claim_authority import ClaimAuthority, ClaimAuthorityError, derive_claim_authority
from application.report.claim_validation import validate_report_claim
from application.report.claim_rendering import ClaimRenderingError, validate_claim_proposition
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.reports.report_claim import REPORT_CLAIM_VERSION, ReportClaim

ClaimCandidateProvider = Callable[[dict[str, Any]], dict[str, Any]]


class ClaimGenerationError(ValueError):
    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def generate_validated_claims(
    *, project_id: str, source_workflow_run_id: str,
    report_workflow_run_id: str, design: ResearchDesign,
    findings: tuple[Finding, ...], insights: tuple[Insight, ...],
    evidence_by_id: dict[str, Evidence], citation_id_by_source: dict[str, str],
    candidate_provider: ClaimCandidateProvider | None = None,
    correction_provider: ClaimCandidateProvider | None = None,
) -> tuple[ReportClaim, ...]:
    prepared: list[tuple[Finding, ClaimAuthority, dict[str, Any]]] = []
    for finding in findings:
        authority = derive_claim_authority(
            project_id=project_id,
            source_workflow_run_id=source_workflow_run_id,
            report_workflow_run_id=report_workflow_run_id,
            design=design,
            findings=(finding,),
            evidence_by_id=evidence_by_id,
        )
        envelope = _candidate_payload(
            authority=authority, finding=finding, insights=insights,
            citation_id_by_source=citation_id_by_source,
        )
        prepared.append((finding, authority, envelope))

    if candidate_provider:
        request = prepared[0][2] if len(prepared) == 1 else {"claims": [item[2] for item in prepared]}
        try:
            generated = candidate_provider(request)
        except Exception as provider_error:
            raise ClaimGenerationError(
                "ReportClaim initial provider failed",
                diagnostics={
                    "category": "initial_provider_failed",
                    "failure_stage": "initial_provider",
                    "attempt_count": 1,
                },
            ) from provider_error
        raws = _unpack_provider_claims(generated, prepared)
    else:
        raws = [item[2] for item in prepared]

    claims: list[ReportClaim | None] = [None] * len(prepared)
    invalid: list[dict[str, Any]] = []
    for index, ((finding, authority, envelope), raw) in enumerate(zip(prepared, raws)):
        try:
            claim = validate_report_claim(ReportClaim.from_dict(raw), authority)
            validate_claim_proposition(claim)
        except (ClaimAuthorityError, ClaimRenderingError, ValueError) as first_error:
            invalid.append({"index": index, "finding": finding, "authority": authority,
                            "envelope": envelope, "candidate": raw,
                            "diagnostics": _generation_diagnostics(
                                "initial_validation_failed", first_error,
                                envelope=envelope,
                            )})
            continue
        claims[index] = claim

    if invalid:
        if correction_provider is None:
            raise ClaimGenerationError(
                "invalid ReportClaim generation",
                diagnostics={
                    **invalid[0]["diagnostics"],
                    "category": "provider_not_configured",
                    "failure_stage": "repair_provider_configuration",
                    "invalid_claim_count": len(invalid),
                    "attempt_count": 0,
                },
            )
        try:
            corrected = correction_provider(_repair_request_batch(invalid))
            corrected_by_id = _unpack_repair_claims(corrected, invalid)
        except Exception as repair_error:
            raise ClaimGenerationError("ReportClaim correction provider failed", diagnostics={
                "category": "repair_provider_failed", "failure_stage": "repair_provider",
                "repair_attempted": True, "attempt_count": 1,
            }) from repair_error
        for item in invalid:
            raw = corrected_by_id.get(item["envelope"]["claim_id"])
            if not isinstance(raw, dict):
                raise ClaimGenerationError("ReportClaim correction was incomplete", diagnostics={
                    "category": "repair_output_malformed", "failure_stage": "repair_output",
                    "repair_attempted": True, "attempt_count": 1,
                })
            try:
                _validate_narrowing_only(item["candidate"], raw)
                claim = validate_report_claim(ReportClaim.from_dict(raw), item["authority"])
                validate_claim_proposition(claim)
            except Exception as repair_error:
                raise ClaimGenerationError("corrected ReportClaim remains invalid", diagnostics={
                    **_generation_diagnostics(
                        "repair_validation_failed", repair_error,
                        envelope=item["envelope"],
                    ),
                    "repair_attempted": True,
                    "repair_exhausted": True,
                    "attempt_count": 1,
                }) from repair_error
            claims[item["index"]] = claim
    return tuple(claim for claim in claims if claim is not None)


def _candidate_payload(*, authority: ClaimAuthority, finding: Finding,
                       insights: tuple[Insight, ...],
                       citation_id_by_source: dict[str, str]) -> dict[str, Any]:
    claim_id = str(uuid5(NAMESPACE_URL, f"{authority.report_workflow_run_id}:{authority.design_id}:{finding.id}:desk_report_claim_v1"))
    kind = {
        FindingType.TREND: "trend", FindingType.COMPARISON: "comparison",
        FindingType.CONTRADICTION: "contradiction",
    }.get(finding.finding_type, "observation")
    certainty = "direct" if finding.confidence is None or finding.confidence >= .75 else "qualified" if finding.confidence >= .5 else "uncertain"
    payload = {
        "version": REPORT_CLAIM_VERSION,
        "claim_id": claim_id,
        "project_id": authority.project_id,
        "source_workflow_run_id": authority.source_workflow_run_id,
        "report_workflow_run_id": authority.report_workflow_run_id,
        "design_id": authority.design_id,
        "research_question_ids": list(authority.research_question_ids),
        "information_need_ids": list(authority.information_need_ids),
        "finding_ids": list(authority.finding_ids),
        "insight_ids": sorted(item.id for item in insights if finding.id in item.finding_refs),
        "evidence_ids": list(authority.evidence_ids),
        "assertion": {"kind": kind, "proposition": finding.statement.strip(), "certainty": certainty, "direction": "not_applicable"},
        "scope": authority.scope.to_dict(),
        "support": {
            "evidence_ids": list(authority.evidence_ids),
            "source_ids": list(authority.source_ids),
            "citation_ids": sorted(citation_id_by_source[source_id] for source_id in authority.source_ids if source_id in citation_id_by_source),
            "finding_content_digests": dict(authority.finding_content_digests),
            "evidence_content_digests": dict(authority.evidence_content_digests),
        },
        "validation": {"status": "validated", "contract_version": REPORT_CLAIM_VERSION, "authority_digest": authority.authority_digest, "validated_at": datetime.now(timezone.utc).isoformat()},
    }
    return payload


def _validate_narrowing_only(original: dict[str, Any], corrected: dict[str, Any]) -> None:
    graph_fields = ("project_id", "source_workflow_run_id", "report_workflow_run_id", "design_id", "research_question_ids", "information_need_ids", "finding_ids", "insight_ids", "evidence_ids")
    for field in graph_fields:
        if corrected.get(field) != original.get(field):
            raise ClaimGenerationError("claim correction may not change lineage or support graph")
    before, after = original.get("scope"), corrected.get("scope")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ClaimGenerationError("claim correction requires structured scope")
    for field in ("periods", "metrics", "population_dimensions"):
        if not set(after.get(field, [])) <= set(before.get(field, [])):
            raise ClaimGenerationError("claim correction may only narrow scope")
    for field in ("country", "subnational"):
        if not set((after.get("geography") or {}).get(field, [])) <= set((before.get("geography") or {}).get(field, [])):
            raise ClaimGenerationError("claim correction may only narrow geography")
    before_facts = {_fact_identity(item) for item in before.get("numeric_facts", []) if isinstance(item, dict)}
    after_facts = {_fact_identity(item) for item in after.get("numeric_facts", []) if isinstance(item, dict)}
    if not after_facts <= before_facts:
        raise ClaimGenerationError("claim correction may not add or alter numeric authority")


def _repair_request(raw: dict[str, Any], envelope: dict[str, Any], error: Exception) -> dict[str, Any]:
    diagnostics = getattr(error, "diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    bounded = {
        key: diagnostics[key]
        for key in ("code", "rejected_tokens", "unit_type", "section_id", "research_question_ids")
        if key in diagnostics
    }
    return {"candidate": raw, "authority": envelope, "diagnostics": bounded}


def _unpack_provider_claims(generated: dict[str, Any], prepared) -> list[dict[str, Any]]:
    if len(prepared) == 1:
        return [generated]
    values = generated.get("claims") if isinstance(generated, dict) else None
    if not isinstance(values, list) or len(values) != len(prepared) or not all(isinstance(item, dict) for item in values):
        raise ClaimGenerationError("provider returned malformed claim batch", diagnostics={
            "category": "initial_output_malformed",
            "failure_stage": "initial_output",
            "attempt_count": 1,
        })
    return values


def _repair_request_batch(invalid: list[dict[str, Any]]) -> dict[str, Any]:
    requests = []
    for item in invalid:
        requests.append({
            "claim_id": item["envelope"]["claim_id"],
            "candidate": item["candidate"],
            "authority": item["envelope"],
            "diagnostics": item["diagnostics"],
        })
    if len(requests) == 1:
        return {"candidate": requests[0]["candidate"], "authority": requests[0]["authority"], "diagnostics": requests[0]["diagnostics"]}
    return {"claims": requests}


def _unpack_repair_claims(corrected: dict[str, Any], invalid: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(invalid) == 1:
        claim_id = invalid[0]["envelope"]["claim_id"]
        return {claim_id: corrected}
    values = corrected.get("claims") if isinstance(corrected, dict) else None
    if not isinstance(values, list) or len(values) != len(invalid) or not all(isinstance(item, dict) for item in values):
        raise ClaimGenerationError("provider returned malformed repair batch", diagnostics={
            "category": "repair_output_malformed", "failure_stage": "repair_output",
            "repair_attempted": True, "attempt_count": 1,
        })
    result = {}
    for item in values:
        claim_id = item.get("claim_id")
        if not isinstance(claim_id, str) or claim_id in result:
            raise ClaimGenerationError("provider returned ambiguous repair batch", diagnostics={
                "category": "repair_output_malformed", "failure_stage": "repair_output",
                "repair_attempted": True, "attempt_count": 1,
            })
        result[claim_id] = item
    return result


def _generation_diagnostics(
    category: str,
    error: Exception,
    *,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = getattr(error, "diagnostics", {})
    result = {
        "category": category,
        "failure_stage": "repair_validation" if category.startswith("repair_") else "initial_validation",
        "attempt_count": 1,
    }
    if isinstance(diagnostics, dict):
        for key in ("code", "validator_category", "scope_dimension", "candidate_scope", "allowed_scope",
                    "rejected_tokens", "unit_type", "section_id", "research_question_ids",
                    "claim_ids", "finding_ids", "evidence_ids", "allowed_numeric_values",
                    "allowed_period_values", "rejected_numeric_facts", "allowed_numeric_facts",
                    "source_workflow_run_id", "report_workflow_run_id"):
            if key in diagnostics:
                result[key] = diagnostics[key]
    if envelope:
        result.setdefault("claim_ids", [str(envelope.get("claim_id", ""))[:128]])
        result.setdefault("finding_ids", [str(item)[:128] for item in envelope.get("finding_ids", [])[:16]])
        result.setdefault("research_question_ids", [str(item)[:128] for item in envelope.get("research_question_ids", [])[:16]])
        result.setdefault("information_need_ids", [str(item)[:128] for item in envelope.get("information_need_ids", [])[:16]])
        result.setdefault("evidence_ids", [str(item)[:128] for item in envelope.get("evidence_ids", [])[:32]])
    return result


def _fact_identity(item: dict[str, Any]) -> str:
    import json
    return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
