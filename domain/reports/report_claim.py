from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any


REPORT_CLAIM_VERSION = "desk_report_claim_v1"
REPORT_CLAIM_V2_VERSION = "desk_report_claim_v2"
H3_REPORT_CLAIM_VERSION = "desk_h3_structural_claim_v1"
_V2_MAX_REFERENCES = 256
_V2_MAX_TEXT = 32_768
CLAIM_KINDS = frozenset({"observation", "trend", "comparison", "association", "causal", "contradiction", "limitation"})
CERTAINTIES = frozenset({"direct", "qualified", "uncertain", "mixed"})
DIRECTIONS = frozenset({"increase", "decrease", "stable", "mixed", "not_applicable"})


class ReportClaimContractError(ValueError):
    pass


class FrozenDict(dict[str, Any]):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("ReportClaim digest maps are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        return FrozenDict(self)


def _digest_map(value: Any, *, field: str, required: bool) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ReportClaimContractError(f"{field} must be an object")
    if required and not value:
        raise ReportClaimContractError(f"{field} must not be empty")
    if len(value) > _V2_MAX_REFERENCES:
        raise ReportClaimContractError(f"{field} exceeds bounded size")
    if any(not isinstance(key, str) or not isinstance(digest, str) for key, digest in value.items()):
        raise ReportClaimContractError(f"{field} keys and values must be strings")
    result = {key.strip(): digest.strip() for key, digest in value.items()}
    if len(result) != len(value):
        raise ReportClaimContractError(f"{field} contains colliding normalized IDs")
    if any(not key or key == "*" or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest) for key, digest in result.items()):
        raise ReportClaimContractError(f"{field} must contain SHA-256 digests keyed by non-empty IDs")
    return result


def _reference_map(value: Any, *, field: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict) or len(value) > _V2_MAX_REFERENCES:
        raise ReportClaimContractError(f"{field} must be a bounded object")
    if any(not isinstance(key, str) for key in value):
        raise ReportClaimContractError(f"{field} keys must be strings")
    if any(not key.strip() or key.strip() == "*" for key in value):
        raise ReportClaimContractError(f"{field} contains an empty or wildcard ID")
    result = {key.strip(): _strict_v2_strings(refs, field=f"{field}.{key}", required=True) for key, refs in value.items()}
    if len(result) != len(value):
        raise ReportClaimContractError(f"{field} contains colliding normalized IDs")
    return result


def _strings(value: Any, *, field: str, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ReportClaimContractError(f"{field} must be an array")
    result = tuple(str(item).strip() for item in value)
    if any(not item or item == "*" for item in result):
        raise ReportClaimContractError(f"{field} contains an empty or wildcard value")
    if required and not result:
        raise ReportClaimContractError(f"{field} must not be empty")
    return tuple(dict.fromkeys(result))


def _strict_v2_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ReportClaimContractError(f"{field} must be a string")
    result = value.strip()
    if not result or result == "*":
        raise ReportClaimContractError(f"{field} must be a non-empty non-wildcard string")
    return result


def _strict_v2_strings(value: Any, *, field: str, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ReportClaimContractError(f"{field} must be an array")
    if any(not isinstance(item, str) for item in value):
        raise ReportClaimContractError(f"{field} elements must be strings")
    if len(set(value)) != len(value):
        raise ReportClaimContractError(f"{field} contains duplicate IDs")
    result = tuple(_strict_v2_string(item, field=field) for item in value)
    if len(set(result)) != len(result):
        raise ReportClaimContractError(f"{field} contains colliding normalized IDs")
    if required and not result:
        raise ReportClaimContractError(f"{field} must not be empty")
    return result


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
    insight_content_digests: dict[str, str] = field(default_factory=dict)
    insight_finding_refs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source_revision_digests: dict[str, str] = field(default_factory=dict)
    numeric_observation_proof_digests: dict[str, str] = field(default_factory=dict)
    claim_digest: str = ""

    def __post_init__(self) -> None:
        for field_name in ("claim_id", "project_id", "source_workflow_run_id", "report_workflow_run_id", "design_id", "proposition", "authority_digest", "validated_at"):
            if not str(getattr(self, field_name)).strip():
                raise ReportClaimContractError(f"{field_name} is required")
        if self.version not in {REPORT_CLAIM_VERSION, REPORT_CLAIM_V2_VERSION, H3_REPORT_CLAIM_VERSION} or self.contract_version != self.version:
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
        object.__setattr__(self, "insight_content_digests", FrozenDict(self.insight_content_digests))
        object.__setattr__(self, "insight_finding_refs", FrozenDict({key: tuple(value) for key, value in self.insight_finding_refs.items()}))
        object.__setattr__(self, "source_revision_digests", FrozenDict(self.source_revision_digests))
        object.__setattr__(self, "numeric_observation_proof_digests", FrozenDict(self.numeric_observation_proof_digests))
        if set(self.evidence_ids) != set(self.support_evidence_ids):
            raise ReportClaimContractError("graph/support evidence IDs must match")
        if set(self.finding_content_digests) != set(self.finding_ids):
            raise ReportClaimContractError("Finding digest keys must match Finding IDs")
        if set(self.evidence_content_digests) != set(self.evidence_ids):
            raise ReportClaimContractError("Evidence digest keys must match Evidence IDs")
        if not self.source_ids:
            raise ReportClaimContractError("source_ids must not be empty")
        if self.version == REPORT_CLAIM_V2_VERSION:
            self._validate_v2()
        elif any((self.insight_content_digests, self.insight_finding_refs, self.source_revision_digests, self.numeric_observation_proof_digests, self.claim_digest)):
            raise ReportClaimContractError("v1/H3 ReportClaim cannot contain v2 lineage")

    def _validate_v2(self) -> None:
        collections = (
            self.research_question_ids, self.information_need_ids, self.finding_ids,
            self.insight_ids, self.evidence_ids, self.source_ids, self.citation_ids,
        )
        if any(len(items) > _V2_MAX_REFERENCES for items in collections):
            raise ReportClaimContractError("v2 reference list exceeds bounded size")
        for name, items in (
            ("research_question_ids", self.research_question_ids),
            ("information_need_ids", self.information_need_ids),
            ("finding_ids", self.finding_ids), ("insight_ids", self.insight_ids),
            ("evidence_ids", self.evidence_ids), ("source_ids", self.source_ids),
            ("citation_ids", self.citation_ids),
        ):
            _strict_v2_strings(items, field=name, required=name not in {"insight_ids", "citation_ids"})
        _strict_v2_strings(self.support_evidence_ids, field="support.evidence_ids", required=True)
        if len(self.proposition) > _V2_MAX_TEXT or any(len(str(item)) > 256 for items in collections for item in items):
            raise ReportClaimContractError("v2 text or reference ID exceeds bounded size")
        scope_collections = (
            self.scope.geography_country, self.scope.geography_subnational, self.scope.periods,
            self.scope.metrics, self.scope.population_dimensions, self.scope.numeric_facts,
        )
        if any(len(items) > _V2_MAX_REFERENCES for items in scope_collections):
            raise ReportClaimContractError("v2 scope exceeds bounded size")
        if any(len(refs) > _V2_MAX_REFERENCES for refs in self.insight_finding_refs.values()):
            raise ReportClaimContractError("v2 Insight Finding refs exceed bounded size")
        if set(self.insight_content_digests) != set(self.insight_ids) or set(self.insight_finding_refs) != set(self.insight_ids):
            raise ReportClaimContractError("Insight lineage keys must match Insight IDs")
        if any(not set(refs) <= set(self.finding_ids) for refs in self.insight_finding_refs.values()):
            raise ReportClaimContractError("Insight Finding refs must be selected Finding IDs")
        if set(self.source_revision_digests) != set(self.source_ids):
            raise ReportClaimContractError("Source revision digest keys must match Source IDs")
        if not set(self.numeric_observation_proof_digests) <= set(self.evidence_ids):
            raise ReportClaimContractError("numeric proof digest keys must be selected Evidence IDs")
        for name in ("finding_content_digests", "insight_content_digests", "evidence_content_digests", "source_revision_digests", "numeric_observation_proof_digests"):
            _digest_map(dict(getattr(self, name)), field=f"support.{name}", required=name != "numeric_observation_proof_digests" and (name != "insight_content_digests" or bool(self.insight_ids)))
        _reference_map(dict(self.insight_finding_refs), field="support.insight_finding_refs")
        expected_authority = _digest(authority_digest_v2_payload(self))
        if self.authority_digest != expected_authority:
            raise ReportClaimContractError("v2 authority digest mismatch")
        if len(self.claim_digest) != 64 or self.claim_digest != _digest(claim_digest_v2_payload(self)):
            raise ReportClaimContractError("v2 claim digest mismatch")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReportClaim:
        expected = {"version", "claim_id", "project_id", "source_workflow_run_id", "report_workflow_run_id", "design_id", "research_question_ids", "information_need_ids", "finding_ids", "insight_ids", "evidence_ids", "assertion", "scope", "support", "validation"}
        version = payload.get("version")
        if version == H3_REPORT_CLAIM_VERSION:
            expected.add("structural_assertion")
        _exact(payload, expected, field="ReportClaim")
        assertion, support, validation = payload["assertion"], payload["support"], payload["validation"]
        _exact(assertion, {"kind", "proposition", "certainty", "direction"}, field="assertion")
        support_fields = {"evidence_ids", "source_ids", "citation_ids", "finding_content_digests", "evidence_content_digests"}
        validation_fields = {"status", "contract_version", "authority_digest", "validated_at"}
        if version == REPORT_CLAIM_V2_VERSION:
            support_fields.update({"insight_content_digests", "insight_finding_refs", "source_revision_digests", "numeric_observation_proof_digests"})
            validation_fields.add("claim_digest")
        _exact(support, support_fields, field="support")
        _exact(validation, validation_fields, field="validation")
        v2 = version == REPORT_CLAIM_V2_VERSION
        for key in ("finding_content_digests", "evidence_content_digests"):
            if v2:
                continue
            if not isinstance(support[key], dict) or any(not str(k).strip() or not str(v).strip() for k, v in support[key].items()):
                raise ReportClaimContractError(f"support.{key} must be a non-empty string map")
        strings = _strict_v2_strings if v2 else _strings
        scalar = (lambda value, field: _strict_v2_string(value, field=field)) if v2 else (lambda value, field: str(value))
        return cls(claim_id=scalar(payload["claim_id"], "claim_id"), project_id=scalar(payload["project_id"], "project_id"), source_workflow_run_id=scalar(payload["source_workflow_run_id"], "source_workflow_run_id"), report_workflow_run_id=scalar(payload["report_workflow_run_id"], "report_workflow_run_id"), design_id=scalar(payload["design_id"], "design_id"), research_question_ids=strings(payload["research_question_ids"], field="research_question_ids", required=True), information_need_ids=strings(payload["information_need_ids"], field="information_need_ids", required=True), finding_ids=strings(payload["finding_ids"], field="finding_ids", required=True), insight_ids=strings(payload["insight_ids"], field="insight_ids"), evidence_ids=strings(payload["evidence_ids"], field="evidence_ids", required=True), kind=scalar(assertion["kind"], "assertion.kind"), proposition=scalar(assertion["proposition"], "assertion.proposition"), certainty=scalar(assertion["certainty"], "assertion.certainty"), direction=scalar(assertion["direction"], "assertion.direction"), scope=ClaimScope.from_dict(payload["scope"]), support_evidence_ids=strings(support["evidence_ids"], field="support.evidence_ids", required=True), source_ids=strings(support["source_ids"], field="support.source_ids", required=True), citation_ids=strings(support["citation_ids"], field="support.citation_ids"), finding_content_digests=_digest_map(support["finding_content_digests"], field="support.finding_content_digests", required=True) if v2 else {str(k): str(v) for k, v in support["finding_content_digests"].items()}, evidence_content_digests=_digest_map(support["evidence_content_digests"], field="support.evidence_content_digests", required=True) if v2 else {str(k): str(v) for k, v in support["evidence_content_digests"].items()}, status=scalar(validation["status"], "validation.status"), contract_version=scalar(validation["contract_version"], "validation.contract_version"), authority_digest=scalar(validation["authority_digest"], "validation.authority_digest"), validated_at=scalar(validation["validated_at"], "validation.validated_at"), structural_assertion=dict(payload["structural_assertion"]) if "structural_assertion" in payload else None, version=scalar(version, "version"), insight_content_digests=_digest_map(support["insight_content_digests"], field="support.insight_content_digests", required=bool(payload["insight_ids"])) if v2 else {}, insight_finding_refs=_reference_map(support["insight_finding_refs"], field="support.insight_finding_refs") if v2 else {}, source_revision_digests=_digest_map(support["source_revision_digests"], field="support.source_revision_digests", required=v2) if v2 else {}, numeric_observation_proof_digests=_digest_map(support["numeric_observation_proof_digests"], field="support.numeric_observation_proof_digests", required=False) if v2 else {}, claim_digest=scalar(validation["claim_digest"], "validation.claim_digest") if v2 else "")

    def to_dict(self) -> dict[str, Any]:
        payload = {"version": self.version, "claim_id": self.claim_id, "project_id": self.project_id, "source_workflow_run_id": self.source_workflow_run_id, "report_workflow_run_id": self.report_workflow_run_id, "design_id": self.design_id, "research_question_ids": list(self.research_question_ids), "information_need_ids": list(self.information_need_ids), "finding_ids": list(self.finding_ids), "insight_ids": list(self.insight_ids), "evidence_ids": list(self.evidence_ids), "assertion": {"kind": self.kind, "proposition": self.proposition, "certainty": self.certainty, "direction": self.direction}, "scope": self.scope.to_dict(), "support": {"evidence_ids": list(self.support_evidence_ids), "source_ids": list(self.source_ids), "citation_ids": list(self.citation_ids), "finding_content_digests": dict(self.finding_content_digests), "evidence_content_digests": dict(self.evidence_content_digests)}, "validation": {"status": self.status, "contract_version": self.contract_version, "authority_digest": self.authority_digest, "validated_at": self.validated_at}}
        if self.version == REPORT_CLAIM_V2_VERSION:
            payload["support"].update({"insight_content_digests": dict(sorted(self.insight_content_digests.items())), "insight_finding_refs": {key: sorted(value) for key, value in sorted(self.insight_finding_refs.items())}, "source_revision_digests": dict(sorted(self.source_revision_digests.items())), "numeric_observation_proof_digests": dict(sorted(self.numeric_observation_proof_digests.items()))})
            payload["validation"]["claim_digest"] = self.claim_digest
        if self.structural_assertion is not None:
            payload["structural_assertion"] = self.structural_assertion
        return payload


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def authority_digest_v2_payload(claim: ReportClaim) -> dict[str, Any]:
    return {
        "contract_version": REPORT_CLAIM_V2_VERSION,
        "source_workflow_run_id": claim.source_workflow_run_id,
        "design_id": claim.design_id,
        "finding_content_digests": dict(sorted(claim.finding_content_digests.items())),
        "insight_content_digests": dict(sorted(claim.insight_content_digests.items())),
        "insight_finding_refs": {key: sorted(value) for key, value in sorted(claim.insight_finding_refs.items())},
        "evidence_content_digests": dict(sorted(claim.evidence_content_digests.items())),
        "source_revision_digests": dict(sorted(claim.source_revision_digests.items())),
        "numeric_observation_proof_digests": dict(sorted(claim.numeric_observation_proof_digests.items())),
        "scope": claim.scope.to_dict(),
    }


def claim_digest_v2_payload(claim: ReportClaim) -> dict[str, Any]:
    return {
        "contract_version": REPORT_CLAIM_V2_VERSION,
        "claim_id": claim.claim_id,
        "project_id": claim.project_id,
        "source_workflow_run_id": claim.source_workflow_run_id,
        "report_workflow_run_id": claim.report_workflow_run_id,
        "design_id": claim.design_id,
        "research_question_ids": sorted(claim.research_question_ids),
        "information_need_ids": sorted(claim.information_need_ids),
        "finding_ids": sorted(claim.finding_ids),
        "insight_ids": sorted(claim.insight_ids),
        "evidence_ids": sorted(claim.evidence_ids),
        "assertion": {"kind": claim.kind, "proposition": claim.proposition, "certainty": claim.certainty, "direction": claim.direction},
        "scope": claim.scope.to_dict(),
        "support": {
            "evidence_ids": sorted(claim.support_evidence_ids), "source_ids": sorted(claim.source_ids),
            "citation_ids": sorted(claim.citation_ids),
            "finding_content_digests": dict(sorted(claim.finding_content_digests.items())),
            "insight_content_digests": dict(sorted(claim.insight_content_digests.items())),
            "insight_finding_refs": {key: sorted(value) for key, value in sorted(claim.insight_finding_refs.items())},
            "evidence_content_digests": dict(sorted(claim.evidence_content_digests.items())),
            "source_revision_digests": dict(sorted(claim.source_revision_digests.items())),
            "numeric_observation_proof_digests": dict(sorted(claim.numeric_observation_proof_digests.items())),
        },
        "authority_digest": claim.authority_digest,
    }


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
    if "composed_authority" in value:
        expected.add("composed_authority")
    _exact(value, expected, field="structural_assertion")
    if "composed_authority" in value:
        composed = value["composed_authority"]
        if not isinstance(composed, dict):
            raise ReportClaimContractError("H3 composed authority must be an object")
        _exact(composed, {
            "authority_mode", "parent_source_workflow_run_id",
            "composition_member_workflow_run_ids", "composition_version",
            "composition_digest",
        }, field="structural_assertion.composed_authority")
        if composed["authority_mode"] != "composed":
            raise ReportClaimContractError("H3 composed authority mode mismatch")
        if not composed["composition_member_workflow_run_ids"]:
            raise ReportClaimContractError("H3 composed authority membership is empty")
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
