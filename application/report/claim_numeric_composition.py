from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from application.report.claim_contract import canonical_digest
from application.research_scope.numeric_normalization import (
    extract_numeric_tokens,
    rendered_fact_matches_numeric_fact,
    rendered_facts,
)
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
    if trace is not None:
        segment_types = [str(item.get("type", ""))[:32] for item in segments if isinstance(item, dict)]
        trace["segment_types"] = segment_types[:32]
        trace["segment_types_truncated"] = len(segment_types) > 32
    if not segments:
        raise _error("semantic_segment_schema", field="assertion.segments", value=segments)
    rendered: list[str] = []
    expected_numeric_tokens: list[str] = []
    previous_was_typed = False
    selected_refs: list[str] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("type") not in {"text", "fact_ref", "period_ref"}:
            raise _error("semantic_segment_schema", field=f"assertion.segments[{index}]", value=segment)
        kind = segment["type"]
        if kind == "text":
            if set(segment) != {"type", "text"} or not isinstance(segment.get("text"), str) or not segment["text"]:
                raise _error("semantic_segment_schema", field=f"assertion.segments[{index}]", value=segment)
            _record_segment(trace, index=index, kind=kind, text=segment["text"])
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
            _validate_rendered_fact(expression, catalog.facts[ref], index=index)
            _record_segment(trace, index=index, kind=kind, ref=ref, expression=expression)
            _append_typed_segment(rendered, expression, previous_was_typed)
            expected_numeric_tokens.extend(extract_numeric_tokens(expression))
            previous_was_typed = True
            _trace(trace, rendered_fact_expressions=[expression], resolved_fact_refs=[ref], resolved_numeric_facts=[catalog.facts[ref].to_dict()])
        else:
            if set(segment) != {"type", "period_ref"} or not isinstance(segment.get("period_ref"), str):
                raise _error("semantic_segment_schema", field=f"assertion.segments[{index}]", value=segment)
            ref = segment["period_ref"]
            _trace(trace, period_refs=[ref])
            if ref not in catalog.periods:
                raise _error("period_ref_invalid", field=f"assertion.segments[{index}].period_ref", value=ref)
            period_expression = render_period(catalog.periods[ref])
            _record_segment(
                trace, index=index, kind=kind, ref=ref,
                expression=period_expression, resolved_period=catalog.periods[ref],
            )
            _append_typed_segment(rendered, period_expression, previous_was_typed)
            expected_numeric_tokens.extend(extract_numeric_tokens(period_expression))
            previous_was_typed = True
            _trace(trace, period_refs=[ref], resolved_period_values=[catalog.periods[ref]])
    proposition = "".join(rendered).strip()
    if not proposition:
        raise _error("semantic_segment_schema", field="assertion.segments", value=segments)
    composed_tokens = tuple(extract_numeric_tokens(proposition))
    expected_tokens = tuple(dict.fromkeys(expected_numeric_tokens))
    _record_invariant_tokens(trace, actual=composed_tokens, expected=expected_tokens)
    if composed_tokens != expected_tokens:
        _trace(trace, numeric_leakage_result="failed", composition_stage="typed_numeric_validation")
        raise _error(
            "deterministic_rendering_invariant",
            field="assertion.segments",
            value={"expected": expected_tokens, "actual": composed_tokens},
        )
    facts = tuple(catalog.facts[ref] for ref in selected_refs)
    _trace(
        trace,
        fact_refs=selected_refs,
        composed_proposition_digest=canonical_digest({"proposition": proposition}),
        composed_numeric_tokens=list(composed_tokens),
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
    trace.setdefault("resolved_period_values", [])
    for key, value in values.items():
        if key in {"fact_refs", "period_refs", "resolved_fact_refs", "resolved_numeric_facts", "rendered_fact_expressions", "resolved_period_values", "composed_numeric_tokens", "segment_types"}:
            existing = trace.setdefault(key, [])
            for item in value or []:
                if item not in existing and len(existing) < 16:
                    existing.append(item)
        else:
            trace[key] = value


def _record_invariant_tokens(
    trace: dict[str, Any] | None, *, actual: tuple[str, ...], expected: tuple[str, ...],
) -> None:
    if trace is None:
        return
    trace["actual_numeric_tokens"] = [str(item)[:64] for item in actual[:32]]
    trace["actual_numeric_tokens_truncated"] = len(actual) > 32
    trace["expected_numeric_tokens"] = [str(item)[:64] for item in expected[:32]]
    trace["expected_numeric_tokens_truncated"] = len(expected) > 32


def _record_segment(
    trace: dict[str, Any] | None, *, index: int, kind: str,
    text: str | None = None, ref: str | None = None,
    expression: str | None = None, resolved_period: str | None = None,
) -> None:
    if trace is None:
        return
    diagnostics = trace.setdefault("segment_diagnostics", [])
    if len(diagnostics) >= 32:
        trace["segment_diagnostics_truncated"] = True
        return
    item: dict[str, Any] = {"index": index, "type": kind[:32]}
    if kind == "text":
        value = text or ""
        item.update({
            "content_present": bool(value),
            "content_length": len(value),
            "content_digest": canonical_digest({"text": value}),
        })
    else:
        tokens = tuple(extract_numeric_tokens(expression or ""))
        item.update({
            "ref": (ref or "")[:128],
            "rendered_expression": (expression or "")[:160],
            "rendered_expression_truncated": len(expression or "") > 160,
            "rendered_numeric_tokens": [str(token)[:64] for token in tokens[:16]],
            "rendered_numeric_tokens_truncated": len(tokens) > 16,
        })
        if resolved_period is not None:
            item["resolved_period_value"] = resolved_period[:64]
            item["resolved_period_value_truncated"] = len(resolved_period) > 64
    diagnostics.append(item)
    trace.setdefault("segment_diagnostics_truncated", False)


def _numeric_tokens(proposition: str) -> list[str]:
    return list(extract_numeric_tokens(proposition))[:16]


def _append_typed_segment(rendered: list[str], expression: str, previous_was_typed: bool) -> None:
    """Keep adjacent system-owned typed segments lexically distinct."""
    if previous_was_typed:
        rendered.append(" ")
    rendered.append(expression)


def _validate_rendered_fact(expression: str, fact: NumericFact, *, index: int) -> None:
    parsed = tuple(item for item in rendered_facts(expression) if item.value is not None)
    if len(parsed) != 1 or not rendered_fact_matches_numeric_fact(parsed[0], fact)[0]:
        raise _error(
            "deterministic_rendering_invariant",
            field=f"assertion.segments[{index}].fact_ref",
            value=fact.to_dict(),
        )


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
