from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.report.claim_authority import ClaimAuthority, ClaimAuthorityError, derive_claim_authority
from application.report.claim_validation import validate_report_claim
from application.report.claim_rendering import ClaimRenderingError, validate_claim_proposition
from application.report.claim_repair_contract import MISSING, RepairDelta, structural_error
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
            raw = _restore_immutable_lineage(envelope, raw)
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
                raw = _compose_repair_candidate(item["envelope"], RepairDelta.from_dict(raw))
                _validate_narrowing_only(item["envelope"], raw)
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


_IMMUTABLE_LINEAGE_FIELDS = (
    "claim_id", "project_id", "source_workflow_run_id", "report_workflow_run_id", "design_id",
)


def _restore_immutable_lineage(canonical: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return candidate
    result = dict(candidate)
    for field in _IMMUTABLE_LINEAGE_FIELDS:
        expected = canonical.get(field)
        supplied = candidate.get(field)
        if supplied not in (None, "") and supplied != expected:
            raise ClaimGenerationError(
                "claim output conflicts with system-owned lineage",
                diagnostics={
                    "validator_category": "immutable_lineage_conflict",
                    "scope_dimension": "lineage",
                    "candidate_scope": {field: supplied},
                    "allowed_scope": {field: expected},
                },
            )
        result[field] = expected
    return result


_SELECTABLE_PROVENANCE_FIELDS = (
    "research_question_ids", "information_need_ids", "finding_ids", "insight_ids",
    "evidence_ids",
)
_SELECTABLE_SUPPORT_FIELDS = ("evidence_ids", "source_ids", "citation_ids")


def _compose_repair_candidate(canonical: dict[str, Any], delta: RepairDelta) -> dict[str, Any]:
    result = copy.deepcopy(canonical)
    for field in _IMMUTABLE_LINEAGE_FIELDS:
        supplied = delta.get(field)
        expected = canonical[field]
        if supplied is not MISSING and supplied not in (None, "") and supplied != expected:
            raise structural_error(
                container="claim", field=field, ownership_class="SYSTEM_IMMUTABLE",
                shape="system_value_conflict", failure_reason="system_value_conflict",
                candidate=supplied, allowed=expected,
            )
        result[field] = expected
    supplied_version = delta.get("version")
    if supplied_version is not MISSING and supplied_version not in (None, "") and supplied_version != canonical["version"]:
        raise structural_error(
            container="claim", field="version", ownership_class="SYSTEM_DERIVED",
            shape="system_value_conflict", failure_reason="system_value_conflict",
            candidate=supplied_version, allowed=canonical["version"],
        )
    result["version"] = canonical["version"]

    for field in _SELECTABLE_PROVENANCE_FIELDS:
        result[field] = _selection(
            value=delta.get(field), allowed=canonical[field], container="claim",
            field=field, required=field != "insight_ids",
        )

    result["assertion"] = _compose_assertion(canonical["assertion"], delta.get("assertion"))
    result["support"] = _compose_support(canonical, delta.get("support"), result)
    result["scope"] = _compose_repair_scope(
        canonical.get("scope"), None if delta.get("scope") is MISSING else delta.get("scope"),
    )
    result["validation"] = _compose_validation(canonical["validation"], delta.get("validation"))
    return result


def _selection(*, value: Any, allowed: list[Any], container: str, field: str, required: bool) -> list[Any]:
    if value is MISSING or value is None:
        return copy.deepcopy(allowed)
    if not isinstance(value, list):
        raise structural_error(
            container=container, field=field,
            ownership_class="PROVIDER_SELECTABLE_WITHIN_ENVELOPE",
            shape="field_malformed", failure_reason="field_malformed",
            candidate=value, allowed=allowed,
        )
    if required and not value:
        raise structural_error(
            container=container, field=field,
            ownership_class="PROVIDER_SELECTABLE_WITHIN_ENVELOPE",
            shape="field_empty", failure_reason="field_empty",
            candidate=value, allowed=allowed,
        )
    if not set(value) <= set(allowed):
        raise structural_error(
            container=container, field=field,
            ownership_class="PROVIDER_SELECTABLE_WITHIN_ENVELOPE",
            shape="explicit_broadening", failure_reason="foreign_reference",
            candidate=value, allowed=allowed,
        )
    return list(dict.fromkeys(value))


def _compose_assertion(canonical: dict[str, Any], value: Any) -> dict[str, Any]:
    if value is MISSING or value is None:
        raise structural_error(
            container="assertion", field="assertion", ownership_class="PROVIDER_SEMANTIC",
            shape="container_omitted" if value is MISSING else "container_null",
            failure_reason="required_semantic_content_missing", candidate=None, allowed="complete assertion",
        )
    expected = {"kind", "proposition", "certainty", "direction"}
    if set(value) != expected:
        raise structural_error(
            container="assertion", field="assertion", ownership_class="PROVIDER_SEMANTIC",
            shape="container_malformed", failure_reason="required_semantic_content_missing",
            candidate=sorted(value), allowed=sorted(expected),
        )
    if any(value[field] is None or not str(value[field]).strip() for field in expected):
        raise structural_error(
            container="assertion", field="assertion", ownership_class="PROVIDER_SEMANTIC",
            shape="field_empty", failure_reason="required_semantic_content_missing",
            candidate=sorted(field for field in expected if value[field] is None or not str(value[field]).strip()),
            allowed=sorted(expected),
        )
    return copy.deepcopy(value)


def _compose_support(canonical: dict[str, Any], value: Any, result: dict[str, Any]) -> dict[str, Any]:
    canonical_support = canonical["support"]
    if value is MISSING or value is None:
        value = {}
    if not isinstance(value, dict):
        raise structural_error(
            container="support", field="support", ownership_class="SYSTEM_STRUCTURAL",
            shape="container_malformed", failure_reason="container_malformed",
            candidate=value, allowed="object",
        )
    supplied_evidence = value.get("evidence_ids", MISSING)
    evidence = list(result["evidence_ids"]) if supplied_evidence is MISSING or supplied_evidence is None else _selection(
        value=supplied_evidence, allowed=canonical_support["evidence_ids"],
        container="support", field="support.evidence_ids", required=True,
    )
    if set(evidence) != set(result["evidence_ids"]):
        raise structural_error(
            container="support", field="support.evidence_ids",
            ownership_class="PROVIDER_SELECTABLE_WITHIN_ENVELOPE",
            shape="digest_selection_mismatch", failure_reason="digest_selection_mismatch",
            candidate=evidence, allowed=result["evidence_ids"],
        )
    source_ids = _selection(
        value=value.get("source_ids", MISSING), allowed=canonical_support["source_ids"],
        container="support", field="support.source_ids", required=True,
    )
    citation_ids = _selection(
        value=value.get("citation_ids", MISSING), allowed=canonical_support["citation_ids"],
        container="support", field="support.citation_ids", required=False,
    )
    finding_digests = {key: canonical_support["finding_content_digests"][key] for key in result["finding_ids"]}
    evidence_digests = {key: canonical_support["evidence_content_digests"][key] for key in result["evidence_ids"]}
    for field, expected in (
        ("finding_content_digests", finding_digests),
        ("evidence_content_digests", evidence_digests),
    ):
        supplied = value.get(field, MISSING)
        if supplied is not MISSING and supplied is not None and supplied != expected:
            raise structural_error(
                container="support", field=f"support.{field}", ownership_class="SYSTEM_DERIVED",
                shape="system_value_conflict", failure_reason="digest_selection_mismatch",
                candidate=supplied, allowed=expected,
            )
    return {
        "evidence_ids": evidence, "source_ids": source_ids, "citation_ids": citation_ids,
        "finding_content_digests": finding_digests,
        "evidence_content_digests": evidence_digests,
    }


def _compose_validation(canonical: dict[str, Any], value: Any) -> dict[str, Any]:
    if value is not MISSING and value is not None:
        if not isinstance(value, dict):
            raise structural_error(
                container="validation", field="validation", ownership_class="SYSTEM_DERIVED",
                shape="container_malformed", failure_reason="container_malformed",
                candidate=value, allowed="canonical validation",
            )
        conflicts = {key: supplied for key, supplied in value.items() if key not in canonical or supplied != canonical[key]}
        if conflicts:
            raise structural_error(
                container="validation", field="validation", ownership_class="SYSTEM_DERIVED",
                shape="system_value_conflict", failure_reason="system_value_conflict",
                candidate=sorted(conflicts), allowed=sorted(canonical),
            )
    return copy.deepcopy(canonical)


_SCOPE_DIMENSIONS = ("periods", "metrics", "population_dimensions", "numeric_facts")
_GEOGRAPHY_DIMENSIONS = ("country", "subnational")


def _scope_shape_error(*, shape: str, dimension: str, candidate: Any, allowed: Any) -> ClaimGenerationError:
    return ClaimGenerationError(
        "claim correction requires a valid structured scope",
        diagnostics={
            "validator_category": "repair_scope_schema",
            "scope_shape": shape,
            "scope_dimension": dimension,
            "candidate_scope": candidate if isinstance(candidate, (str, int, float, bool)) else None,
            "allowed_scope": allowed if isinstance(allowed, (str, int, float, bool)) else None,
        },
    )


def _compose_repair_scope(canonical: Any, candidate: Any) -> dict[str, Any]:
    if not isinstance(canonical, dict):
        raise _scope_shape_error(shape="canonical_scope_malformed", dimension="scope", candidate=None, allowed=None)
    if candidate is None:
        return copy.deepcopy(canonical)
    if not isinstance(candidate, dict):
        raise _scope_shape_error(shape="whole_scope_malformed", dimension="scope", candidate=type(candidate).__name__, allowed="object")
    allowed_scope_fields = {*_SCOPE_DIMENSIONS, "geography"}
    unknown_scope_fields = set(candidate) - allowed_scope_fields
    if unknown_scope_fields:
        raise _scope_shape_error(
            shape="nested_dimension_malformed", dimension="scope",
            candidate=sorted(unknown_scope_fields), allowed=sorted(allowed_scope_fields),
        )
    result = copy.deepcopy(candidate)
    for field in _SCOPE_DIMENSIONS:
        if field not in result or result[field] is None:
            result[field] = copy.deepcopy(canonical.get(field))
        elif field == "numeric_facts" and not isinstance(result[field], list):
            raise _scope_shape_error(shape="nested_dimension_malformed", dimension=field, candidate=type(result[field]).__name__, allowed="array")
        elif field != "numeric_facts" and not isinstance(result[field], list):
            raise _scope_shape_error(shape="nested_dimension_malformed", dimension=field, candidate=type(result[field]).__name__, allowed="array")
        elif field != "numeric_facts" and any(not isinstance(item, str) or not item.strip() for item in result[field]):
            raise _scope_shape_error(shape="nested_dimension_malformed", dimension=field, candidate=result[field], allowed="non-empty string array")
    geography = result.get("geography")
    canonical_geography = canonical.get("geography")
    if geography is None:
        result["geography"] = copy.deepcopy(canonical_geography)
    elif not isinstance(geography, dict):
        raise _scope_shape_error(shape="nested_dimension_malformed", dimension="geography", candidate=type(geography).__name__, allowed="object")
    else:
        geography = copy.deepcopy(geography)
        unknown_geography_fields = set(geography) - set(_GEOGRAPHY_DIMENSIONS)
        if unknown_geography_fields:
            raise _scope_shape_error(
                shape="nested_dimension_malformed", dimension="geography",
                candidate=sorted(unknown_geography_fields), allowed=list(_GEOGRAPHY_DIMENSIONS),
            )
        for field in _GEOGRAPHY_DIMENSIONS:
            if field not in geography or geography[field] is None:
                geography[field] = copy.deepcopy((canonical_geography or {}).get(field))
            elif not isinstance(geography[field], list):
                raise _scope_shape_error(shape="nested_dimension_malformed", dimension=f"geography.{field}", candidate=type(geography[field]).__name__, allowed="array")
            elif any(not isinstance(item, str) or not item.strip() for item in geography[field]):
                raise _scope_shape_error(shape="nested_dimension_malformed", dimension=f"geography.{field}", candidate=geography[field], allowed="non-empty string array")
        result["geography"] = geography
    for index, fact in enumerate(result.get("numeric_facts", [])):
        if not isinstance(fact, dict):
            raise _scope_shape_error(shape="nested_dimension_malformed", dimension=f"numeric_facts[{index}]", candidate=type(fact).__name__, allowed="object")
        allowed_fact_fields = {"value", "unit", "scale", "geography", "periods", "metrics", "population_dimensions"}
        if set(fact) != allowed_fact_fields:
            raise _scope_shape_error(
                shape="nested_dimension_malformed", dimension=f"numeric_facts[{index}]",
                candidate=sorted(fact), allowed=sorted(allowed_fact_fields),
            )
        for field in ("value", "unit", "scale"):
            if not isinstance(fact[field], str) or not fact[field].strip():
                raise _scope_shape_error(
                    shape="nested_dimension_malformed", dimension=f"numeric_facts[{index}].{field}",
                    candidate=fact[field], allowed="non-empty string",
                )
        for field in ("geography", "periods", "metrics", "population_dimensions"):
            value = fact[field]
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise _scope_shape_error(
                    shape="nested_dimension_malformed", dimension=f"numeric_facts[{index}].{field}",
                    candidate=value, allowed="non-empty string array",
                )
    return result


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
    for field in _IMMUTABLE_LINEAGE_FIELDS:
        if corrected.get(field) != original.get(field):
            raise ClaimGenerationError(
                "claim correction may not change lineage or support graph",
                diagnostics={
                    "validator_category": "repair_lineage_narrowing_violation",
                    "scope_dimension": "lineage",
                    "candidate_scope": {field: corrected.get(field)},
                    "allowed_scope": {field: original.get(field)},
                },
            )
    for field in _SELECTABLE_PROVENANCE_FIELDS:
        if not set(corrected.get(field, [])) <= set(original.get(field, [])):
            raise ClaimGenerationError(
                "claim correction may not broaden provenance",
                diagnostics={
                    "validator_category": "repair_provenance_broadening",
                    "scope_dimension": field,
                    "candidate_scope": list(corrected.get(field, []))[:32],
                    "allowed_scope": list(original.get(field, []))[:32],
                },
            )
    original_support = dict(original.get("support") or {})
    corrected_support = dict(corrected.get("support") or {})
    for field in _SELECTABLE_SUPPORT_FIELDS:
        if not set(corrected_support.get(field, [])) <= set(original_support.get(field, [])):
            raise ClaimGenerationError(
                "claim correction may not broaden support provenance",
                diagnostics={
                    "validator_category": "repair_provenance_broadening",
                    "scope_dimension": f"support.{field}",
                    "candidate_scope": list(corrected_support.get(field, []))[:32],
                    "allowed_scope": list(original_support.get(field, []))[:32],
                },
            )
    before, after = original.get("scope"), corrected.get("scope")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ClaimGenerationError(
            "claim correction requires structured scope",
            diagnostics={"validator_category": "repair_scope_schema"},
        )
    for field in ("periods", "metrics", "population_dimensions"):
        if not set(after.get(field, [])) <= set(before.get(field, [])):
            raise ClaimGenerationError(
                "claim correction may only narrow scope",
                diagnostics={
                    "validator_category": "repair_scope_broadening",
                    "scope_dimension": field,
                    "candidate_scope": list(after.get(field, []))[:16],
                    "allowed_scope": list(before.get(field, []))[:16],
                },
            )
    for field in ("country", "subnational"):
        if not set((after.get("geography") or {}).get(field, [])) <= set((before.get("geography") or {}).get(field, [])):
            raise ClaimGenerationError(
                "claim correction may only narrow geography",
                diagnostics={
                    "validator_category": "repair_scope_broadening",
                    "scope_dimension": "geography",
                    "candidate_scope": list((after.get("geography") or {}).get(field, []))[:16],
                    "allowed_scope": list((before.get("geography") or {}).get(field, []))[:16],
                },
            )
    before_facts = {_fact_identity(item) for item in before.get("numeric_facts", []) if isinstance(item, dict)}
    after_facts = {_fact_identity(item) for item in after.get("numeric_facts", []) if isinstance(item, dict)}
    if not after_facts <= before_facts:
        raise ClaimGenerationError(
            "claim correction may not add or alter numeric authority",
            diagnostics={
                "validator_category": "repair_numeric_authority_change",
                "scope_dimension": "numeric_authority",
                "rejected_numeric_facts": [item for item in after.get("numeric_facts", []) if isinstance(item, dict)][:16],
                "allowed_numeric_facts": [item for item in before.get("numeric_facts", []) if isinstance(item, dict)][:32],
            },
        )


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
        for key in ("code", "validator_category", "repair_stage", "container", "field",
                    "ownership_class", "shape", "failure_reason", "candidate_shape",
                    "candidate_bounded_value", "allowed_shape", "allowed_bounded_value",
                    "scope_shape", "scope_dimension", "candidate_scope", "allowed_scope",
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
