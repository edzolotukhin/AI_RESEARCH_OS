from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from application.report.claim_contract import canonical_digest
from application.research_scope.numeric_normalization import extract_numeric_tokens
from domain.reports.report_claim import NumericFact


class NumericCompositionError(ValueError):
    def __init__(self, message: str, *, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def _error(category: str, *, field: str, value: Any = None) -> NumericCompositionError:
    bounded = value
    if isinstance(value, str):
        bounded = value[:128]
    elif isinstance(value, (list, tuple)):
        bounded = [str(item)[:128] for item in value[:16]]
    elif isinstance(value, dict):
        bounded = sorted(str(key)[:128] for key in value)[:16]
    elif value is not None and not isinstance(value, (int, float, bool)):
        bounded = type(value).__name__
    return NumericCompositionError(
        "invalid hybrid numeric claim composition",
        diagnostics={
            "validator_category": category,
            "repair_stage": "numeric_composition",
            "container": field.split(".", 1)[0].split("[", 1)[0],
            "field": field,
            "failure_reason": category,
            "candidate_bounded_value": bounded,
        },
    )


@dataclass(frozen=True)
class FactCatalog:
    claim_id: str
    claim_key: str
    facts: dict[str, NumericFact]
    periods: dict[str, str]

    def provider_payload(self) -> dict[str, Any]:
        return {
            "numeric_facts": [
                {"fact_ref": ref, "fact": fact.to_dict()}
                for ref, fact in self.facts.items()
            ],
            "periods": [
                {"period_ref": ref, "period": period}
                for ref, period in self.periods.items()
            ],
        }


def build_fact_catalog(*, claim_id: str, facts: tuple[NumericFact, ...], periods: tuple[str, ...]) -> FactCatalog:
    claim_key = canonical_digest({"claim_id": claim_id})[:16]
    fact_map: dict[str, NumericFact] = {}
    for fact in facts:
        ref = f"nf_{claim_key}_" + canonical_digest(fact.to_dict())
        previous = fact_map.get(ref)
        if previous is not None and previous != fact:
            raise _error("fact_ref_collision", field="fact_ref", value=ref)
        fact_map[ref] = fact
    period_map: dict[str, str] = {}
    for period in periods:
        ref = f"period_{claim_key}_" + canonical_digest({"period": period})
        previous = period_map.get(ref)
        if previous is not None and previous != period:
            raise _error("period_ref_collision", field="period_ref", value=ref)
        period_map[ref] = period
    return FactCatalog(claim_id, claim_key, fact_map, period_map)


def compose_assertion(
    assertion: Any,
    *,
    catalog: FactCatalog,
    trace: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], tuple[NumericFact, ...]]:
    _trace(trace, h2_path="claim_numeric_composition", composition_stage="segment_parse")
    if not isinstance(assertion, dict):
        raise _error("semantic_segment_schema", field="assertion", value=assertion)
    expected = {"kind", "certainty", "direction", "segments"}
    if set(assertion) != expected or not isinstance(assertion.get("segments"), list):
        raise _error("semantic_segment_schema", field="assertion", value=assertion)
    if any(not isinstance(assertion.get(field), str) or not assertion[field].strip() for field in ("kind", "certainty", "direction")):
        raise _error("semantic_segment_schema", field="assertion", value=assertion)
    segments = assertion["segments"]
    _trace(trace, segment_types=[item.get("type") for item in segments if isinstance(item, dict)])
    if not segments:
        raise _error("semantic_segment_schema", field="assertion.segments", value=segments)
    rendered: list[str] = []
    previous_was_typed = False
    selected_refs: list[str] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("type") not in {"text", "fact_ref", "period_ref"}:
            raise _error("semantic_segment_schema", field=f"assertion.segments[{index}]", value=segment)
        kind = segment["type"]
        if kind == "text":
            if set(segment) != {"type", "text"} or not isinstance(segment.get("text"), str) or not segment["text"]:
                raise _error("semantic_segment_schema", field=f"assertion.segments[{index}]", value=segment)
            if any(character.isdigit() for character in segment["text"]):
                _trace(trace, numeric_leakage_result="failed", composition_stage="numeric_leakage")
                raise _error("numeric_leakage", field=f"assertion.segments[{index}].text", value=segment["text"])
            rendered.append(segment["text"])
            previous_was_typed = False
        elif kind == "fact_ref":
            if set(segment) != {"type", "fact_ref"} or not isinstance(segment.get("fact_ref"), str):
                raise _error("semantic_segment_schema", field=f"assertion.segments[{index}]", value=segment)
            ref = segment["fact_ref"]
            _trace(trace, fact_refs=[ref])
            if ref not in catalog.facts:
                own_prefix = f"nf_{catalog.claim_key}_"
                if not ref.startswith("nf_"):
                    category = "unknown_fact_ref"
                elif not ref.startswith(own_prefix):
                    category = "cross_claim_fact_ref"
                else:
                    category = "foreign_fact_ref"
                raise _error(category, field=f"assertion.segments[{index}].fact_ref", value=ref)
            if ref in selected_refs:
                raise _error("duplicate_fact_ref", field=f"assertion.segments[{index}].fact_ref", value=ref)
            selected_refs.append(ref)
            expression = render_numeric_fact(catalog.facts[ref])
            _append_typed_segment(rendered, expression, previous_was_typed)
            previous_was_typed = True
            _trace(trace, rendered_fact_expressions=[expression], resolved_fact_refs=[ref], resolved_numeric_facts=[catalog.facts[ref].to_dict()])
        else:
            if set(segment) != {"type", "period_ref"} or not isinstance(segment.get("period_ref"), str):
                raise _error("semantic_segment_schema", field=f"assertion.segments[{index}]", value=segment)
            ref = segment["period_ref"]
            _trace(trace, period_refs=[ref])
            if ref not in catalog.periods:
                raise _error("period_ref_invalid", field=f"assertion.segments[{index}].period_ref", value=ref)
            _append_typed_segment(rendered, render_period(catalog.periods[ref]), previous_was_typed)
            previous_was_typed = True
            _trace(trace, period_refs=[ref])
    proposition = "".join(rendered).strip()
    if not proposition:
        raise _error("semantic_segment_schema", field="assertion.segments", value=segments)
    facts = tuple(catalog.facts[ref] for ref in selected_refs)
    _trace(
        trace,
        fact_refs=selected_refs,
        composed_proposition_digest=canonical_digest({"proposition": proposition}),
        composed_numeric_tokens=_numeric_tokens(proposition),
        numeric_leakage_result="passed",
        composition_stage="deterministic_rendering_complete",
    )
    return {
        "kind": assertion["kind"],
        "proposition": proposition,
        "certainty": assertion["certainty"],
        "direction": assertion["direction"],
    }, facts


def _trace(trace: dict[str, Any] | None, **values: Any) -> None:
    if trace is None:
        return
    trace.setdefault("h2_contract_version", "desk_h2_transient_segments_v1")
    trace.setdefault("h2_path", "claim_numeric_composition")
    trace.setdefault("legacy_proposition_present", False)
    trace.setdefault("legacy_proposition_used", False)
    trace.setdefault("fact_refs", [])
    trace.setdefault("period_refs", [])
    trace.setdefault("resolved_fact_refs", [])
    trace.setdefault("resolved_numeric_facts", [])
    trace.setdefault("rendered_fact_expressions", [])
    for key, value in values.items():
        if key in {"fact_refs", "period_refs", "resolved_fact_refs", "resolved_numeric_facts", "rendered_fact_expressions", "composed_numeric_tokens", "segment_types"}:
            existing = trace.setdefault(key, [])
            for item in value or []:
                if item not in existing and len(existing) < 16:
                    existing.append(item)
        else:
            trace[key] = value


def _numeric_tokens(proposition: str) -> list[str]:
    return list(extract_numeric_tokens(proposition))[:16]


def _append_typed_segment(rendered: list[str], expression: str, previous_was_typed: bool) -> None:
    """Keep adjacent system-owned typed segments lexically distinct."""
    if previous_was_typed:
        rendered.append(" ")
    rendered.append(expression)


def render_numeric_fact(fact: NumericFact) -> str:
    value = _render_value(fact.value)
    unit = fact.unit.strip()
    scale = fact.scale.strip()
    if unit == "%":
        expression = f"{value}%"
    elif scale.casefold() not in {"", "absolute"}:
        rendered_scale = {"million": "млн", "billion": "млрд"}.get(scale.casefold(), scale)
        expression = " ".join(item for item in (value, rendered_scale, unit) if item)
    else:
        expression = " ".join(item for item in (value, unit) if item)
    bindings: list[str] = []
    if fact.periods:
        bindings.append("період: " + ", ".join(fact.periods))
    if fact.geography:
        bindings.append("географія: " + ", ".join(fact.geography))
    if fact.metrics:
        bindings.append("показник: " + ", ".join(fact.metrics))
    if fact.population_dimensions:
        bindings.append("група: " + ", ".join(fact.population_dimensions))
    return expression + (f" ({'; '.join(bindings)})" if bindings else "")


def render_period(period: str) -> str:
    return f"період: {period}"


def _render_value(value: str) -> str:
    token = str(value).strip()
    try:
        number = Decimal(token)
    except InvalidOperation as exc:
        raise _error("deterministic_rendering_invariant", field="numeric_fact.value", value=value) from exc
    normalized = format(number, "f")
    sign = ""
    if normalized.startswith("-"):
        sign, normalized = "-", normalized[1:]
    integer, dot, fraction = normalized.partition(".")
    grouped = "\u202f".join(
        [integer[: len(integer) % 3]] + [integer[index:index + 3] for index in range(len(integer) % 3, len(integer), 3)]
    ).lstrip("\u202f") if len(integer) > 4 else integer
    fraction = fraction.rstrip("0")
    return sign + grouped + (("," + fraction) if dot and fraction else "")
