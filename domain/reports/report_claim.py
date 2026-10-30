from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


REPORT_CLAIM_VERSION = "desk_report_claim_v1"
H3_REPORT_CLAIM_VERSION = "desk_h3_structural_claim_v1"
CLAIM_KINDS = frozenset({"observation", "trend", "comparison", "association", "causal", "contradiction", "limitation"})
CERTAINTIES = frozenset({"direct", "qualified", "uncertain", "mixed"})
DIRECTIONS = frozenset({"increase", "decrease", "stable", "mixed", "not_applicable"})


class ReportClaimContractError(ValueError):
    pass


class FrozenDict(dict[str, str]):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("ReportClaim digest maps are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        return FrozenDict(self)


def _strings(value: Any, *, field: str, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ReportClaimContractError(f"{field} must be an array")
    result = tuple(str(item).strip() for item in value)
    if any(not item or item == "*" for item in result):
        raise ReportClaimContractError(f"{field} contains an empty or wildcard value")
    if required and not result:
        raise ReportClaimContractError(f"{field} must not be empty")
    return tuple(dict.fromkeys(result))


def _exact(payload: dict[str, Any], expected: set[str], *, field: str) -> None:
    missing, unknown = expected - set(payload), set(payload) - expected
    if missing or unknown:
        raise ReportClaimContractError(f"{field} fields invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")


@dataclass(frozen=True)
class NumericFact:
    value: str
    unit: str
    scale: str
    geography: tuple[str, ...]
    periods: tuple[str, ...]
    metrics: tuple[str, ...]
    population_dimensions: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(not str(value).strip() or str(value).strip() == "*" for value in (self.value, self.unit, self.scale)):
            raise ReportClaimContractError("numeric value/unit/scale are required and may not be wildcard")
        for name in ("geography", "periods", "metrics", "population_dimensions"):
            if any(not str(item).strip() or str(item).strip() == "*" for item in getattr(self, name)):
                raise ReportClaimContractError(f"numeric.{name} contains an empty or wildcard value")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> NumericFact:
        expected = {"value", "unit", "scale", "geography", "periods", "metrics", "population_dimensions"}
        if not isinstance(payload, dict):
            raise ReportClaimContractError("numeric fact must be an object")
        _exact(payload, expected, field="numeric fact")
        values = {name: str(payload[name]).strip() for name in ("value", "unit", "scale")}
        if any(not value or value == "*" for value in values.values()):
            raise ReportClaimContractError("numeric value/unit/scale are required and may not be wildcard")
        return cls(**values, geography=_strings(payload["geography"], field="numeric.geography"), periods=_strings(payload["periods"], field="numeric.periods"), metrics=_strings(payload["metrics"], field="numeric.metrics"), population_dimensions=_strings(payload["population_dimensions"], field="numeric.population_dimensions"))

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "unit": self.unit, "scale": self.scale, "geography": list(self.geography), "periods": list(self.periods), "metrics": list(self.metrics), "population_dimensions": list(self.population_dimensions)}


@dataclass(frozen=True)
class ClaimScope:
    geography_country: tuple[str, ...]
    geography_subnational: tuple[str, ...]
    periods: tuple[str, ...]
    metrics: tuple[str, ...]
    population_dimensions: tuple[str, ...]
    numeric_facts: tuple[NumericFact, ...]

    def __post_init__(self) -> None:
        for name in ("geography_country", "geography_subnational", "periods", "metrics", "population_dimensions"):
            if any(not str(item).strip() or str(item).strip() == "*" for item in getattr(self, name)):
                raise ReportClaimContractError(f"scope.{name} contains an empty or wildcard value")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClaimScope:
        if not isinstance(payload, dict):
            raise ReportClaimContractError("scope must be an object")
        _exact(payload, {"geography", "periods", "metrics", "population_dimensions", "numeric_facts"}, field="scope")
        geography = payload["geography"]
        if not isinstance(geography, dict):
            raise ReportClaimContractError("scope.geography must be an object")
        _exact(geography, {"country", "subnational"}, field="scope.geography")
        if not isinstance(payload["numeric_facts"], (list, tuple)):
            raise ReportClaimContractError("scope.numeric_facts must be an array")
        return cls(_strings(geography["country"], field="scope.geography.country"), _strings(geography["subnational"], field="scope.geography.subnational"), _strings(payload["periods"], field="scope.periods"), _strings(payload["metrics"], field="scope.metrics"), _strings(payload["population_dimensions"], field="scope.population_dimensions"), tuple(NumericFact.from_dict(item) for item in payload["numeric_facts"]))

    def to_dict(self) -> dict[str, Any]:
        return {"geography": {"country": list(self.geography_country), "subnational": list(self.geography_subnational)}, "periods": list(self.periods), "metrics": list(self.metrics), "population_dimensions": list(self.population_dimensions), "numeric_facts": [item.to_dict() for item in self.numeric_facts]}


@dataclass(frozen=True)
class ReportClaim:
    claim_id: str
    project_id: str
    source_workflow_run_id: str
    report_workflow_run_id: str
    design_id: str
    research_question_ids: tuple[str, ...]
    information_need_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    kind: str
    proposition: str
    certainty: str
    direction: str
    scope: ClaimScope
    support_evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]
    finding_content_digests: dict[str, str]
    evidence_content_digests: dict[str, str]
    status: str
    contract_version: str
    authority_digest: str
    validated_at: str
    structural_assertion: dict[str, Any] | None = None
    version: str = REPORT_CLAIM_VERSION

    def __post_init__(self) -> None:
        for field_name in ("claim_id", "project_id", "source_workflow_run_id", "report_workflow_run_id", "design_id", "proposition", "authority_digest", "validated_at"):
            if not str(getattr(self, field_name)).strip():
                raise ReportClaimContractError(f"{field_name} is required")
        if self.version not in {REPORT_CLAIM_VERSION, H3_REPORT_CLAIM_VERSION} or self.contract_version != self.version:
            raise ReportClaimContractError("unsupported ReportClaim contract version")
        if self.version == H3_REPORT_CLAIM_VERSION:
            _validate_h3_structural_assertion(
                self.structural_assertion, proposition=self.proposition,
                authority_digest=self.authority_digest,
            )
        elif self.structural_assertion is not None:
            raise ReportClaimContractError("legacy ReportClaim cannot contain structural_assertion")
        if self.kind not in CLAIM_KINDS or self.certainty not in CERTAINTIES or self.direction not in DIRECTIONS:
            raise ReportClaimContractError("invalid assertion enum")
        if self.status != "validated":
            raise ReportClaimContractError("validation.status must equal validated")
        for name in ("research_question_ids", "information_need_ids", "finding_ids", "evidence_ids", "support_evidence_ids"):
            if not getattr(self, name):
                raise ReportClaimContractError(f"{name} must not be empty")
        for name in ("research_question_ids", "information_need_ids", "finding_ids", "insight_ids", "evidence_ids", "support_evidence_ids", "source_ids", "citation_ids"):
            if any(not str(item).strip() or str(item).strip() == "*" for item in getattr(self, name)):
                raise ReportClaimContractError(f"{name} contains an empty or wildcard value")
        object.__setattr__(self, "finding_content_digests", FrozenDict(self.finding_content_digests))
        object.__setattr__(self, "evidence_content_digests", FrozenDict(self.evidence_content_digests))
        if set(self.evidence_ids) != set(self.support_evidence_ids):
            raise ReportClaimContractError("graph/support evidence IDs must match")
        if set(self.finding_content_digests) != set(self.finding_ids):
            raise ReportClaimContractError("Finding digest keys must match Finding IDs")
        if set(self.evidence_content_digests) != set(self.evidence_ids):
            raise ReportClaimContractError("Evidence digest keys must match Evidence IDs")
        if not self.source_ids:
            raise ReportClaimContractError("source_ids must not be empty")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReportClaim:
        expected = {"version", "claim_id", "project_id", "source_workflow_run_id", "report_workflow_run_id", "design_id", "research_question_ids", "information_need_ids", "finding_ids", "insight_ids", "evidence_ids", "assertion", "scope", "support", "validation"}
        if payload.get("version") == H3_REPORT_CLAIM_VERSION:
            expected.add("structural_assertion")
        _exact(payload, expected, field="ReportClaim")
        assertion, support, validation = payload["assertion"], payload["support"], payload["validation"]
        _exact(assertion, {"kind", "proposition", "certainty", "direction"}, field="assertion")
        _exact(support, {"evidence_ids", "source_ids", "citation_ids", "finding_content_digests", "evidence_content_digests"}, field="support")
        _exact(validation, {"status", "contract_version", "authority_digest", "validated_at"}, field="validation")
        for key in ("finding_content_digests", "evidence_content_digests"):
            if not isinstance(support[key], dict) or any(not str(k).strip() or not str(v).strip() for k, v in support[key].items()):
                raise ReportClaimContractError(f"support.{key} must be a non-empty string map")
        return cls(claim_id=str(payload["claim_id"]), project_id=str(payload["project_id"]), source_workflow_run_id=str(payload["source_workflow_run_id"]), report_workflow_run_id=str(payload["report_workflow_run_id"]), design_id=str(payload["design_id"]), research_question_ids=_strings(payload["research_question_ids"], field="research_question_ids", required=True), information_need_ids=_strings(payload["information_need_ids"], field="information_need_ids", required=True), finding_ids=_strings(payload["finding_ids"], field="finding_ids", required=True), insight_ids=_strings(payload["insight_ids"], field="insight_ids"), evidence_ids=_strings(payload["evidence_ids"], field="evidence_ids", required=True), kind=str(assertion["kind"]), proposition=str(assertion["proposition"]), certainty=str(assertion["certainty"]), direction=str(assertion["direction"]), scope=ClaimScope.from_dict(payload["scope"]), support_evidence_ids=_strings(support["evidence_ids"], field="support.evidence_ids", required=True), source_ids=_strings(support["source_ids"], field="support.source_ids", required=True), citation_ids=_strings(support["citation_ids"], field="support.citation_ids"), finding_content_digests={str(k): str(v) for k, v in support["finding_content_digests"].items()}, evidence_content_digests={str(k): str(v) for k, v in support["evidence_content_digests"].items()}, status=str(validation["status"]), contract_version=str(validation["contract_version"]), authority_digest=str(validation["authority_digest"]), validated_at=str(validation["validated_at"]), structural_assertion=dict(payload["structural_assertion"]) if "structural_assertion" in payload else None, version=str(payload["version"]))

    def to_dict(self) -> dict[str, Any]:
        payload = {"version": self.version, "claim_id": self.claim_id, "project_id": self.project_id, "source_workflow_run_id": self.source_workflow_run_id, "report_workflow_run_id": self.report_workflow_run_id, "design_id": self.design_id, "research_question_ids": list(self.research_question_ids), "information_need_ids": list(self.information_need_ids), "finding_ids": list(self.finding_ids), "insight_ids": list(self.insight_ids), "evidence_ids": list(self.evidence_ids), "assertion": {"kind": self.kind, "proposition": self.proposition, "certainty": self.certainty, "direction": self.direction}, "scope": self.scope.to_dict(), "support": {"evidence_ids": list(self.support_evidence_ids), "source_ids": list(self.source_ids), "citation_ids": list(self.citation_ids), "finding_content_digests": dict(self.finding_content_digests), "evidence_content_digests": dict(self.evidence_content_digests)}, "validation": {"status": self.status, "contract_version": self.contract_version, "authority_digest": self.authority_digest, "validated_at": self.validated_at}}
        if self.structural_assertion is not None:
            payload["structural_assertion"] = self.structural_assertion
        return payload


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_h3_structural_assertion(
    value: Any, *, proposition: str, authority_digest: str,
) -> None:
    if not isinstance(value, dict):
        raise ReportClaimContractError("H3 structural_assertion must be an object")
    expected = {
        "contract_version", "typed_ast", "authority_catalog",
        "authority_input_digest", "source_authority_digest", "typed_ast_digest", "renderer_version",
        "locale", "rendered_assertion", "render_digest",
    }
    _exact(value, expected, field="structural_assertion")
    if value["contract_version"] != H3_REPORT_CLAIM_VERSION:
        raise ReportClaimContractError("H3 structural assertion contract mismatch")
    if _digest(value["authority_catalog"]) != value["authority_input_digest"]:
        raise ReportClaimContractError("H3 authority digest mismatch")
    if value["source_authority_digest"] != authority_digest:
        raise ReportClaimContractError("H3 source authority digest mismatch")
    if _digest(value["typed_ast"]) != value["typed_ast_digest"]:
        raise ReportClaimContractError("H3 AST digest mismatch")
    if value["rendered_assertion"] != proposition:
        raise ReportClaimContractError("H3 rendered assertion mismatch")
    render_payload = {
        "locale": value["locale"],
        "renderer_version": value["renderer_version"],
        "text": value["rendered_assertion"],
    }
    if _digest(render_payload) != value["render_digest"]:
        raise ReportClaimContractError("H3 render digest mismatch")
