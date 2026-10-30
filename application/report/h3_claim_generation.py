"""H3 structural claim generation.

The provider selects typed authority references and numeric-free connective text.
Factual authority is never reconstructed from rendered prose.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.report.claim_authority import ClaimAuthority, ClaimAuthorityError, derive_claim_authority
from application.report.typed_rendering import (
    CitationAuthorityRef, ClaimAuthorityRef, FactAuthorityRef, H3AuthorityCatalog,
    H3_CONTRACT_VERSION, H3_LOCALE, H3_RENDERER_VERSION, PeriodAuthorityRef,
    TypedRenderDocument, TypedRenderError, TypedRenderNode, TypedRenderNodeType,
    TypedRenderErrorCode,
    authority_input_digest, render_typed_document,
)
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.reports.report_claim import (
    CERTAINTIES, CLAIM_KINDS, DIRECTIONS, H3_REPORT_CLAIM_VERSION, ReportClaim,
)


H3CandidateProvider = Callable[[dict[str, Any]], dict[str, Any]]


class H3ProviderPayloadError(ValueError):
    """Bounded, non-content diagnostics for a provider contract failure."""

    def __init__(self, message: str, *, field_path: str | None = None,
                 expected_kind: str | None = None, actual_kind: str | None = None,
                 shape: str | None = None, parser_stage: str = "h3_dto",
                 allowed_values: tuple[str, ...] = (), actual_token: str | None = None) -> None:
        super().__init__(message)
        self.error_code = message
        self.field_path = field_path
        self.expected_kind = expected_kind
        self.actual_kind = actual_kind
        self.shape = shape
        self.parser_stage = parser_stage
        self.allowed_values = tuple(allowed_values)[:32]
        self.actual_token = actual_token[:64] if isinstance(actual_token, str) else None


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__[:32]


def _shape(value: Any) -> str:
    """Return only bounded structural metadata, never provider content."""
    if isinstance(value, dict):
        keys = sorted(str(key)[:48] for key in value)[:24]
        return "object(keys=" + ",".join(keys) + ")"
    if isinstance(value, list):
        return f"array(length={min(len(value), 1000)})"
    return _kind(value)


class H3UnsupportedCandidate(ValueError):
    pass


class H3ClaimOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_UNSUPPORTED = "REJECTED_UNSUPPORTED"
    REJECTED_PROVIDER_INVALID = "REJECTED_PROVIDER_INVALID"
    AUTHORITY_INVALID = "AUTHORITY_INVALID"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class H3CoverageOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    LIMITED = "LIMITED"
    REPORT_INSUFFICIENT_COVERAGE = "REPORT_INSUFFICIENT_COVERAGE"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"


class H3ReportOutcomeError(ValueError):
    def __init__(self, result: "H3ClaimGenerationResult") -> None:
        self.result = result
        super().__init__(result.coverage_outcome.value)


class H3ReportInsufficientCoverage(H3ReportOutcomeError):
    pass


class H3ReportTechnicalError(H3ReportOutcomeError):
    pass


@dataclass(frozen=True)
class H3ClaimDiagnostic:
    candidate_id: str
    research_question_ids: tuple[str, ...]
    information_need_ids: tuple[str, ...]
    outcome: H3ClaimOutcome
    category: str
    provider_attempt_count: int
    repair_attempted: bool
    structural_error_codes: tuple[str, ...] = ()
    affected_reference_ids: tuple[str, ...] = ()
    authority_digest: str | None = None
    ast_digest: str | None = None
    phase: str = "INITIAL"
    candidate_index: int | None = None
    error_code: str | None = None
    field_path: str | None = None
    expected_kind: str | None = None
    actual_kind: str | None = None
    bounded_shape_summary: str | None = None
    parser_stage: str | None = None
    repair_correlation: str | None = None
    allowed_values: tuple[str, ...] = ()
    actual_token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "research_question_ids": list(self.research_question_ids),
            "information_need_ids": list(self.information_need_ids),
            "outcome": self.outcome.value,
            "category": self.category,
            "provider_attempt_count": self.provider_attempt_count,
            "repair_attempted": self.repair_attempted,
            "structural_error_codes": list(self.structural_error_codes)[:16],
            "affected_reference_ids": list(self.affected_reference_ids)[:32],
            "authority_digest": self.authority_digest,
            "ast_digest": self.ast_digest,
            "phase": self.phase,
            "candidate_index": self.candidate_index,
            "error_code": self.error_code,
            "field_path": self.field_path,
            "expected_kind": self.expected_kind,
            "actual_kind": self.actual_kind,
            "bounded_shape_summary": self.bounded_shape_summary,
            "parser_stage": self.parser_stage,
            "repair_correlation": self.repair_correlation,
            "allowed_values": list(self.allowed_values)[:32],
            "actual_token": self.actual_token,
        }


@dataclass(frozen=True)
class H3ClaimGenerationResult:
    claims: tuple[ReportClaim, ...]
    diagnostics: tuple[H3ClaimDiagnostic, ...]
    coverage_outcome: H3CoverageOutcome
    missing_research_question_ids: tuple[str, ...]
    missing_information_need_ids: tuple[str, ...]
    provider_attempt_count: int
    repair_count: int

    def to_diagnostic_dict(self) -> dict[str, Any]:
        return {
            "contract_version": H3_CONTRACT_VERSION,
            "coverage_outcome": self.coverage_outcome.value,
            "accepted_claim_count": len(self.claims),
            "rejected_claim_count": sum(item.outcome is not H3ClaimOutcome.ACCEPTED for item in self.diagnostics),
            "missing_research_question_ids": list(self.missing_research_question_ids),
            "missing_information_need_ids": list(self.missing_information_need_ids),
            "provider_attempt_count": self.provider_attempt_count,
            "repair_count": self.repair_count,
            "claims": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class _Prepared:
    finding: Finding
    authority: ClaimAuthority
    claim_id: str
    catalog: H3AuthorityCatalog
    insight_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]


def generate_h3_structural_claims(
    *, project_id: str, source_workflow_run_id: str, report_workflow_run_id: str,
    design: ResearchDesign, findings: tuple[Finding, ...], insights: tuple[Insight, ...],
    evidence_by_id: dict[str, Evidence], citation_id_by_source: dict[str, str],
    candidate_provider: H3CandidateProvider,
    correction_provider: H3CandidateProvider | None,
    required_research_question_ids: tuple[str, ...],
    required_information_need_ids: tuple[str, ...],
) -> H3ClaimGenerationResult:
    prepared: list[_Prepared] = []
    diagnostics: list[H3ClaimDiagnostic] = []
    technical = False
    for finding in findings:
        candidate_id = str(uuid5(NAMESPACE_URL, f"h3:{report_workflow_run_id}:{finding.id}"))
        try:
            authority = derive_claim_authority(
                project_id=project_id, source_workflow_run_id=source_workflow_run_id,
                report_workflow_run_id=report_workflow_run_id, design=design,
                findings=(finding,), evidence_by_id=evidence_by_id,
            )
            insight_ids = tuple(sorted(item.id for item in insights if finding.id in item.finding_refs))
            catalog, citation_ids = _catalog_for_authority(
                claim_id=candidate_id, authority=authority,
                citation_id_by_source=citation_id_by_source,
            )
            prepared.append(_Prepared(finding, authority, candidate_id, catalog, insight_ids, citation_ids))
        except ClaimAuthorityError as exc:
            technical = True
            diagnostics.append(H3ClaimDiagnostic(
                candidate_id, tuple(finding.research_question_refs), tuple(finding.information_need_refs),
                H3ClaimOutcome.AUTHORITY_INVALID, type(exc).__name__, 0, False,
            ))
    if technical:
        return _result((), diagnostics, required_research_question_ids, required_information_need_ids, 0, 0, technical=True)
    if not prepared:
        return _result((), diagnostics, required_research_question_ids, required_information_need_ids, 0, 0)

    attempts = 1
    try:
        from application.report.h3_provider_contract import debit_h3_provider_call
        debit_h3_provider_call()
        raw = candidate_provider(_provider_request(prepared))
        candidates = _decode_response(raw)
    except Exception as exc:
        candidates = {}
        initial_error = exc
    else:
        initial_error = None

    claims: list[ReportClaim] = []
    invalid: list[tuple[_Prepared, Exception]] = []
    for item in prepared:
        try:
            if initial_error is not None:
                raise initial_error
            claim = _build_claim(item, candidates[item.claim_id])
        except Exception as exc:
            if isinstance(exc, H3UnsupportedCandidate):
                diagnostics.append(_rejected(item, exc, attempts, False))
                continue
            if not _provider_owned(exc):
                diagnostics.append(H3ClaimDiagnostic(
                    item.claim_id, item.authority.research_question_ids,
                    item.authority.information_need_ids, H3ClaimOutcome.SYSTEM_ERROR,
                    type(exc).__name__, attempts, False,
                    authority_digest=authority_input_digest(item.catalog),
                ))
                return _result(tuple(claims), diagnostics, required_research_question_ids,
                               required_information_need_ids, attempts, 0, technical=True)
            invalid.append((item, exc))
        else:
            claims.append(claim)
            diagnostics.append(_accepted(item, claim, attempts, False))

    repair_count = 0
    if invalid and correction_provider is not None:
        repair_count = 1
        attempts += 1
        try:
            from application.report.h3_provider_contract import debit_h3_provider_call
            debit_h3_provider_call()
            repaired = _decode_response(correction_provider(_repair_request(invalid)))
        except Exception as repair_exc:
            repaired = {}
            repair_batch_error: Exception | None = repair_exc
        else:
            repair_batch_error = None
        for item, initial_exc in invalid:
            try:
                if repair_batch_error is not None:
                    raise repair_batch_error
                claim = _build_claim(item, repaired[item.claim_id])
            except Exception as exc:
                if not _provider_owned(exc):
                    diagnostics.append(H3ClaimDiagnostic(
                        item.claim_id, item.authority.research_question_ids,
                        item.authority.information_need_ids, H3ClaimOutcome.SYSTEM_ERROR,
                        type(exc).__name__, attempts, True,
                        authority_digest=authority_input_digest(item.catalog),
                    ))
                    return _result(tuple(claims), diagnostics, required_research_question_ids,
                                   required_information_need_ids, attempts, repair_count, technical=True)
                diagnostics.append(_rejected(item, exc, attempts, True))
            else:
                claims.append(claim)
                diagnostics.append(_accepted(item, claim, attempts, True))
    else:
        for item, exc in invalid:
            diagnostics.append(_rejected(item, exc, attempts, False))
    return _result(tuple(claims), diagnostics, required_research_question_ids, required_information_need_ids, attempts, repair_count)


def restore_h3_claim_structure(claim: ReportClaim) -> tuple[TypedRenderDocument, H3AuthorityCatalog]:
    """Restore and verify persisted H3 structure without inspecting proposition text."""
    if claim.version != H3_CONTRACT_VERSION or claim.structural_assertion is None:
        raise ValueError("not_an_h3_structural_claim")
    envelope = claim.structural_assertion
    document = TypedRenderDocument.from_dict(envelope["typed_ast"])
    catalog = H3AuthorityCatalog.from_canonical_dict(envelope["authority_catalog"])
    rendered = render_typed_document(
        document, catalog, locale=str(envelope["locale"]),
        renderer_version=str(envelope["renderer_version"]),
    )
    if (
        rendered.authority_digest != envelope["authority_input_digest"]
        or rendered.ast_digest != envelope["typed_ast_digest"]
        or rendered.render_digest != envelope["render_digest"]
        or rendered.text != envelope["rendered_assertion"]
    ):
        raise ValueError("h3_structural_integrity_mismatch")
    return document, catalog


def _catalog_for_authority(
    *, claim_id: str, authority: ClaimAuthority, citation_id_by_source: dict[str, str],
) -> tuple[H3AuthorityCatalog, tuple[str, ...]]:
    facts: dict[str, FactAuthorityRef] = {}
    periods: dict[str, PeriodAuthorityRef] = {}
    for index, fact in enumerate(authority.scope.numeric_facts, start=1):
        fact_ref = f"{claim_id}:fact:{index}"
        facts[fact_ref] = FactAuthorityRef(fact_ref, claim_id, fact)
        for period_index, period in enumerate(fact.periods, start=1):
            ref = f"{fact_ref}:period:{period_index}"
            periods[ref] = PeriodAuthorityRef(ref, claim_id, period, fact_ref)
    fact_periods = {period.period for period in periods.values()}
    for index, period in enumerate(
        (item for item in authority.scope.periods if item not in fact_periods), start=1,
    ):
        ref = f"{claim_id}:period:{index}"
        periods[ref] = PeriodAuthorityRef(ref, claim_id, period)
    citation_ids = tuple(sorted({citation_id_by_source[item] for item in authority.source_ids if item in citation_id_by_source}))
    citations = {
        citation_id: CitationAuthorityRef(citation_id, claim_id, source_id, citation_id)
        for source_id, citation_id in citation_id_by_source.items()
        if source_id in authority.source_ids
    }
    return H3AuthorityCatalog(
        claims={claim_id: ClaimAuthorityRef(claim_id, citation_ids)},
        facts=facts, periods=periods, citations=citations,
        limitations={}, interpretations={},
    ), citation_ids


def _provider_request(prepared: list[_Prepared]) -> dict[str, Any]:
    return {
        "contract_version": H3_CONTRACT_VERSION,
        "instruction": "Return typed nodes only. TEXT must contain no digits, URLs, source names, or authority annotations.",
        "allowed_vocabulary": _allowed_vocabulary(),
        "candidates": [
            {
                "claim_id": item.claim_id,
                "research_question_ids": list(item.authority.research_question_ids),
                "information_need_ids": list(item.authority.information_need_ids),
                "finding_ids": list(item.authority.finding_ids),
                "authorized_catalog": item.catalog.to_canonical_dict(),
            }
            for item in prepared
        ],
    }


def _repair_request(invalid: list[tuple[_Prepared, Exception]]) -> dict[str, Any]:
    return {
        "contract_version": H3_CONTRACT_VERSION,
        "repair": True,
        "allowed_vocabulary": _allowed_vocabulary(),
        "candidates": [
            {
                "claim_id": item.claim_id,
                "authorized_catalog": item.catalog.to_canonical_dict(),
                "error_codes": _error_codes(exc),
            }
            for item, exc in invalid
        ],
    }


def _allowed_vocabulary() -> dict[str, list[str]]:
    return {
        "kind": sorted(CLAIM_KINDS),
        "certainty": sorted(CERTAINTIES),
        "direction": sorted(DIRECTIONS),
        "node_type": [item.value for item in TypedRenderNodeType],
    }


def _decode_response(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"contract_version", "claims"}:
        raise H3ProviderPayloadError(
            "malformed_h3_provider_payload", field_path="root",
            expected_kind="object", actual_kind=_kind(payload), shape=_shape(payload),
        )
    if payload["contract_version"] != H3_CONTRACT_VERSION:
        raise H3ProviderPayloadError(
            "malformed_h3_provider_payload", field_path="contract_version",
            expected_kind="string", actual_kind=_kind(payload["contract_version"]),
            shape=_shape(payload["contract_version"]),
        )
    if not isinstance(payload["claims"], list):
        raise H3ProviderPayloadError(
            "malformed_h3_provider_payload", field_path="claims",
            expected_kind="array", actual_kind=_kind(payload["claims"]),
            shape=_shape(payload["claims"]),
        )
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(payload["claims"]):
        if not isinstance(item, dict):
            raise H3ProviderPayloadError(
                "malformed_h3_claim_payload", field_path=f"claims[{index}]",
                expected_kind="object", actual_kind=_kind(item), shape=_shape(item),
            )
        if set(item) == {"claim_id", "outcome", "category"}:
            if item["outcome"] != H3ClaimOutcome.REJECTED_UNSUPPORTED.value or not str(item["category"]).strip():
                raise H3ProviderPayloadError(
                    "malformed_h3_claim_rejection", field_path=f"claims[{index}]",
                    expected_kind="rejection object", actual_kind="object", shape=_shape(item),
                )
        elif set(item) != {"claim_id", "kind", "certainty", "direction", "nodes"}:
            raise H3ProviderPayloadError(
                "malformed_h3_claim_payload", field_path=f"claims[{index}]",
                expected_kind="claim object", actual_kind="object", shape=_shape(item),
            )
        claim_id = str(item["claim_id"])
        if not claim_id or claim_id in result:
            raise H3ProviderPayloadError(
                "duplicate_or_empty_claim_id", field_path=f"claims[{index}].claim_id",
                expected_kind="non-empty unique string", actual_kind=_kind(item.get("claim_id")),
                shape=_shape(item.get("claim_id")),
            )
        if "nodes" in item:
            if not isinstance(item["nodes"], list):
                raise H3ProviderPayloadError(
                    "malformed_h3_claim_payload", field_path=f"claims[{index}].nodes",
                    expected_kind="array", actual_kind=_kind(item["nodes"]), shape=_shape(item["nodes"]),
                )
            for field, allowed in (("kind", CLAIM_KINDS), ("certainty", CERTAINTIES), ("direction", DIRECTIONS)):
                value = item[field]
                if value not in allowed:
                    raise H3ProviderPayloadError(
                        "invalid_h3_assertion_enum", field_path=f"claims[{index}].assertion.{field}",
                        expected_kind=f"enum:{field}", actual_kind=_kind(value), shape=_shape(value),
                        allowed_values=tuple(sorted(allowed)),
                        actual_token=(value if isinstance(value, str) else None),
                    )
        result[claim_id] = item
    return result


def _document(item: _Prepared, raw: dict[str, Any]) -> TypedRenderDocument:
    nodes: list[TypedRenderNode] = []
    for index, payload in enumerate(raw["nodes"]):
        if not isinstance(payload, dict) or set(payload) - {"node_id", "node_type", "owner_claim_ref", "text", "authority_ref", "presentation_variant"}:
            raise H3ProviderPayloadError(
                "malformed_h3_node", field_path=f"nodes[{index}]",
                expected_kind="object", actual_kind=_kind(payload), shape=_shape(payload),
            )
        if "node_type" not in payload:
            raise H3ProviderPayloadError(
                "malformed_h3_node", field_path=f"nodes[{index}].node_type",
                expected_kind="string", actual_kind="missing", shape="missing",
            )
        try:
            node_type = TypedRenderNodeType(str(payload["node_type"]))
        except ValueError as exc:
            raise H3ProviderPayloadError(
                "invalid_h3_node_type", field_path=f"nodes[{index}].node_type",
                expected_kind="allowed node type", actual_kind=_kind(payload["node_type"]),
                shape=_shape(payload["node_type"]),
            ) from exc
        nodes.append(TypedRenderNode(
            node_id=str(payload.get("node_id") or f"{item.claim_id}:node:{index + 1}"),
            node_type=node_type,
            owner_claim_ref=(str(payload["owner_claim_ref"]) if payload.get("owner_claim_ref") is not None else None),
            text=(str(payload["text"]) if payload.get("text") is not None else None),
            authority_ref=(str(payload["authority_ref"]) if payload.get("authority_ref") is not None else None),
            presentation_variant=(str(payload["presentation_variant"]) if payload.get("presentation_variant") is not None else None),
        ))
    return TypedRenderDocument(H3_CONTRACT_VERSION, item.claim_id, item.claim_id, tuple(nodes))


def _build_claim(item: _Prepared, raw: dict[str, Any]) -> ReportClaim:
    if raw.get("outcome") == H3ClaimOutcome.REJECTED_UNSUPPORTED.value:
        raise H3UnsupportedCandidate(str(raw["category"])[:96])
    document = _document(item, raw)
    rendered = render_typed_document(document, item.catalog)
    authority = item.authority
    envelope = {
        "contract_version": H3_CONTRACT_VERSION,
        "typed_ast": document.to_dict(),
        "authority_catalog": item.catalog.to_canonical_dict(),
        "authority_input_digest": rendered.authority_digest,
        "source_authority_digest": authority.authority_digest,
        "typed_ast_digest": rendered.ast_digest,
        "renderer_version": rendered.renderer_version,
        "locale": rendered.locale,
        "rendered_assertion": rendered.text,
        "render_digest": rendered.render_digest,
    }
    return ReportClaim(
        claim_id=item.claim_id, project_id=authority.project_id,
        source_workflow_run_id=authority.source_workflow_run_id,
        report_workflow_run_id=authority.report_workflow_run_id,
        design_id=authority.design_id,
        research_question_ids=authority.research_question_ids,
        information_need_ids=authority.information_need_ids,
        finding_ids=authority.finding_ids, insight_ids=item.insight_ids,
        evidence_ids=authority.evidence_ids,
        kind=str(raw["kind"]), proposition=rendered.text,
        certainty=str(raw["certainty"]), direction=str(raw["direction"]),
        scope=authority.scope, support_evidence_ids=authority.evidence_ids,
        source_ids=authority.source_ids, citation_ids=item.citation_ids,
        finding_content_digests=authority.finding_content_digests,
        evidence_content_digests=authority.evidence_content_digests,
        status="validated", contract_version=H3_REPORT_CLAIM_VERSION,
        authority_digest=authority.authority_digest,
        validated_at=datetime.now(timezone.utc).isoformat(),
        structural_assertion=envelope, version=H3_REPORT_CLAIM_VERSION,
    )


def _accepted(item: _Prepared, claim: ReportClaim, attempts: int, repair: bool) -> H3ClaimDiagnostic:
    return H3ClaimDiagnostic(
        item.claim_id, item.authority.research_question_ids, item.authority.information_need_ids,
        H3ClaimOutcome.ACCEPTED, "structurally_valid", attempts, repair,
        authority_digest=claim.authority_digest,
        ast_digest=str(claim.structural_assertion["typed_ast_digest"]),
    )


def _rejected(item: _Prepared, exc: Exception, attempts: int, repair: bool) -> H3ClaimDiagnostic:
    affected = ()
    if isinstance(exc, KeyError):
        affected = (str(exc.args[0]),)
    payload = exc if isinstance(exc, H3ProviderPayloadError) else None
    candidate_index = None
    if payload and payload.field_path:
        match = re.search(r"claims\[(\d+)\]", payload.field_path)
        candidate_index = int(match.group(1)) if match else None
    return H3ClaimDiagnostic(
        item.claim_id, item.authority.research_question_ids, item.authority.information_need_ids,
        (H3ClaimOutcome.REJECTED_UNSUPPORTED if isinstance(exc, H3UnsupportedCandidate) else H3ClaimOutcome.REJECTED_PROVIDER_INVALID),
        (str(exc)[:96] if isinstance(exc, H3UnsupportedCandidate) else type(exc).__name__), attempts, repair,
        structural_error_codes=tuple(_error_codes(exc)), affected_reference_ids=affected,
        authority_digest=authority_input_digest(item.catalog),
        phase="REPAIR" if repair else "INITIAL",
        candidate_index=candidate_index,
        error_code=(payload.error_code if payload else (str(exc)[:96] or type(exc).__name__)),
        field_path=payload.field_path if payload else None,
        expected_kind=payload.expected_kind if payload else None,
        actual_kind=payload.actual_kind if payload else None,
        bounded_shape_summary=payload.shape if payload else None,
        parser_stage=payload.parser_stage if payload else None,
        repair_correlation=item.claim_id if repair else None,
        allowed_values=(payload.allowed_values if payload else ()),
        actual_token=(payload.actual_token if payload else None),
    )


def _error_codes(exc: Exception) -> list[str]:
    if isinstance(exc, TypedRenderError):
        return [exc.code.value]
    if isinstance(exc, KeyError):
        return ["missing_candidate"]
    return [str(exc)[:96] or type(exc).__name__]


_PROVIDER_STRUCTURAL_CODES = frozenset({
    code for code in TypedRenderErrorCode
    if code not in {TypedRenderErrorCode.UNSUPPORTED_LOCALE, TypedRenderErrorCode.UNSUPPORTED_RENDERER}
})


def _provider_owned(exc: Exception) -> bool:
    return isinstance(exc, H3ProviderPayloadError) or (
        isinstance(exc, TypedRenderError) and exc.code in _PROVIDER_STRUCTURAL_CODES
    ) or isinstance(exc, KeyError)


def _result(
    claims: tuple[ReportClaim, ...], diagnostics: list[H3ClaimDiagnostic],
    required_rqs: tuple[str, ...], required_ins: tuple[str, ...],
    attempts: int, repair_count: int, *, technical: bool = False,
) -> H3ClaimGenerationResult:
    covered_rqs = {ref for claim in claims for ref in claim.research_question_ids}
    covered_ins = {ref for claim in claims for ref in claim.information_need_ids}
    missing_rqs = tuple(sorted(set(required_rqs) - covered_rqs))
    missing_ins = tuple(sorted(set(required_ins) - covered_ins))
    if technical:
        outcome = H3CoverageOutcome.TECHNICAL_ERROR
    elif missing_rqs or missing_ins:
        outcome = H3CoverageOutcome.REPORT_INSUFFICIENT_COVERAGE
    elif any(item.outcome is not H3ClaimOutcome.ACCEPTED for item in diagnostics):
        outcome = H3CoverageOutcome.LIMITED
    else:
        outcome = H3CoverageOutcome.SUCCESS
    return H3ClaimGenerationResult(claims, tuple(diagnostics), outcome, missing_rqs, missing_ins, attempts, repair_count)
