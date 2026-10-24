from __future__ import annotations

import hashlib
import json
from typing import Any

from domain.reports.report_claim import REPORT_CLAIM_VERSION, ClaimScope, NumericFact


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def content_digest(payload: Any) -> str:
    return canonical_digest(payload)


def report_claim_compatibility(claims: tuple[Any, ...]) -> str:
    """Historical/current prose Reports remain explicit until Package 2 opts in."""
    if not claims:
        return "legacy_unstructured"
    if all(getattr(item, "version", None) == REPORT_CLAIM_VERSION and getattr(item, "status", None) == "validated" for item in claims):
        return REPORT_CLAIM_VERSION
    return "invalid_structured_claims"


def authority_digest(*, source_workflow_run_id: str, design_id: str, finding_content_digests: dict[str, str], evidence_content_digests: dict[str, str], scope: ClaimScope) -> str:
    return canonical_digest({"contract_version": REPORT_CLAIM_VERSION, "source_workflow_run_id": source_workflow_run_id, "design_id": design_id, "finding_content_digests": dict(sorted(finding_content_digests.items())), "evidence_content_digests": dict(sorted(evidence_content_digests.items())), "scope": scope.to_dict()})


def scope_from_authoritative_payload(payload: dict[str, Any]) -> ClaimScope:
    anchors = payload.get("geography_anchors") or []
    countries: list[str] = []
    subnational: list[str] = []
    for item in anchors:
        if not isinstance(item, dict):
            continue
        target = countries if item.get("level") == "country" else subnational
        value = str(item.get("value", "")).strip()
        if value:
            target.append(value)
    facts = []
    for item in payload.get("numeric_facts", []):
        if not isinstance(item, dict):
            continue
        facts.append(NumericFact.from_dict({"value": item.get("value", ""), "unit": item.get("unit", ""), "scale": item.get("scale", "absolute"), "geography": item.get("geography", []), "periods": item.get("periods", []), "metrics": item.get("metrics", []), "population_dimensions": item.get("population_dimensions", [])}))
    return ClaimScope(tuple(sorted(set(countries))), tuple(sorted(set(subnational))), tuple(sorted(set(payload.get("periods", [])))), tuple(sorted(set(payload.get("metrics", [])))), tuple(sorted(set(payload.get("population_dimensions", [])))), tuple(facts))
