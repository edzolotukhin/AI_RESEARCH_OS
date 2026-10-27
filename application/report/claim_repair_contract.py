from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


class _Missing:
    pass


MISSING = _Missing()


class RepairContractError(ValueError):
    def __init__(self, message: str, *, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


_FIELDS = frozenset({
    "version", "claim_id", "project_id", "source_workflow_run_id",
    "report_workflow_run_id", "design_id", "research_question_ids",
    "information_need_ids", "finding_ids", "insight_ids", "evidence_ids",
    "assertion", "scope", "support", "validation",
})
_REFERENCE_FIELDS = (
    "research_question_ids", "information_need_ids", "finding_ids",
    "insight_ids", "evidence_ids",
)
_SUPPORT_REFERENCE_FIELDS = ("evidence_ids", "source_ids", "citation_ids")
_SUPPORT_FIELDS = frozenset({
    *_SUPPORT_REFERENCE_FIELDS,
    "finding_content_digests",
    "evidence_content_digests",
})


def structural_error(
    *, container: str, field: str, ownership_class: str, shape: str,
    failure_reason: str, candidate: Any = None, allowed: Any = None,
) -> RepairContractError:
    def bounded(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [str(item)[:128] for item in value[:32]]
        if isinstance(value, dict):
            return sorted(str(key)[:128] for key in value)[:32]
        return type(value).__name__

    validator_category = (
        "immutable_lineage_conflict" if ownership_class == "SYSTEM_IMMUTABLE"
        else "repair_scope_schema" if container == "scope"
        else "repair_provenance_broadening" if shape == "explicit_broadening"
        else "repair_contract_invalid"
    )
    diagnostics = {
        "validator_category": validator_category,
        "repair_stage": "repair_composition",
        "container": container,
        "field": field,
        "ownership_class": ownership_class,
        "shape": shape,
        "failure_reason": failure_reason,
        "candidate_shape": "null" if candidate is None else type(candidate).__name__,
        "candidate_bounded_value": bounded(candidate),
        "allowed_shape": "canonical" if allowed is None else type(allowed).__name__,
        "allowed_bounded_value": bounded(allowed),
        "scope_dimension": field,
        "candidate_scope": ({field: candidate} if ownership_class == "SYSTEM_IMMUTABLE" else bounded(candidate)),
        "allowed_scope": ({field: allowed} if ownership_class == "SYSTEM_IMMUTABLE" else bounded(allowed)),
    }
    if container == "scope":
        diagnostics["scope_shape"] = shape
    return RepairContractError(
        "invalid ReportClaim repair delta",
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class RepairDelta:
    values: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RepairDelta:
        if not isinstance(payload, dict):
            raise structural_error(
                container="claim", field="claim", ownership_class="PROVIDER_SEMANTIC",
                shape="container_malformed", failure_reason="container_malformed",
                candidate=payload, allowed="object",
            )
        unknown = set(payload) - _FIELDS
        if unknown:
            raise structural_error(
                container="claim", field="claim", ownership_class="PROVIDER_SEMANTIC",
                shape="container_malformed", failure_reason="unknown_fields",
                candidate=sorted(unknown), allowed=sorted(_FIELDS),
            )
        values = copy.deepcopy(payload)
        for field in _REFERENCE_FIELDS:
            value = values.get(field, MISSING)
            if value is not MISSING and value is not None and not isinstance(value, list):
                raise structural_error(
                    container="claim", field=field,
                    ownership_class="PROVIDER_SELECTABLE_WITHIN_ENVELOPE",
                    shape="field_malformed", failure_reason="field_malformed",
                    candidate=value, allowed="array",
                )
        for field in ("assertion", "scope", "support", "validation"):
            value = values.get(field, MISSING)
            if value is not MISSING and value is not None and not isinstance(value, dict):
                raise structural_error(
                    container=field, field=field,
                    ownership_class=("PROVIDER_SEMANTIC" if field == "assertion" else "SYSTEM_STRUCTURAL"),
                    shape=("whole_scope_malformed" if field == "scope" else "container_malformed"),
                    failure_reason="container_malformed",
                    candidate=value, allowed="object",
                )
        support = values.get("support", MISSING)
        if isinstance(support, dict):
            unknown_support = set(support) - _SUPPORT_FIELDS
            if unknown_support:
                raise structural_error(
                    container="support", field="support",
                    ownership_class="SYSTEM_STRUCTURAL",
                    shape="container_malformed", failure_reason="unknown_fields",
                    candidate=sorted(unknown_support), allowed=sorted(_SUPPORT_FIELDS),
                )
            for field in _SUPPORT_REFERENCE_FIELDS:
                value = support.get(field, MISSING)
                if value is not MISSING and value is not None and not isinstance(value, list):
                    raise structural_error(
                        container="support", field=f"support.{field}",
                        ownership_class="PROVIDER_SELECTABLE_WITHIN_ENVELOPE",
                        shape="field_malformed", failure_reason="field_malformed",
                        candidate=value, allowed="array",
                    )
        return cls(values)

    def get(self, field: str) -> Any:
        return self.values.get(field, MISSING)
