"""Shared structural rendering substrate for H3 claims and editorial output.

Authority is validated from typed references before rendering.  Rendered text is
never parsed to recover factual authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from domain.reports.report_claim import NumericFact


H3_CONTRACT_VERSION = "desk_h3_structural_claim_v1"
H3_RENDERER_VERSION = "desk_h3_uk_v1"
H3_LOCALE = "uk-UA"


class TypedRenderErrorCode(str, Enum):
    INVALID_CONTRACT = "invalid_contract"
    DUPLICATE_NODE_ID = "duplicate_node_id"
    MALFORMED_NODE = "malformed_node"
    UNKNOWN_CLAIM_REF = "unknown_claim_ref"
    UNKNOWN_FACT_REF = "unknown_fact_ref"
    CROSS_CLAIM_FACT_REF = "cross_claim_fact_ref"
    UNKNOWN_PERIOD_REF = "unknown_period_ref"
    CROSS_CLAIM_PERIOD_REF = "cross_claim_period_ref"
    FACT_LOCAL_PERIOD_MISMATCH = "fact_local_period_mismatch"
    UNKNOWN_CITATION_REF = "unknown_citation_ref"
    CROSS_CLAIM_CITATION_REF = "cross_claim_citation_ref"
    UNSUPPORTED_CITATION_REF = "unsupported_citation_ref"
    UNKNOWN_LIMITATION_REF = "unknown_limitation_ref"
    CROSS_CLAIM_LIMITATION_REF = "cross_claim_limitation_ref"
    UNKNOWN_INTERPRETATION_REF = "unknown_interpretation_ref"
    CROSS_CLAIM_INTERPRETATION_REF = "cross_claim_interpretation_ref"
    TEXT_DIGIT_LEAKAGE = "text_digit_leakage"
    TEXT_URL_LEAKAGE = "text_url_leakage"
    TEXT_INTERNAL_ID_LEAKAGE = "text_internal_id_leakage"
    TEXT_SOURCE_NAME_LEAKAGE = "text_source_name_leakage"
    TEXT_FACT_ANNOTATION_LEAKAGE = "text_fact_annotation_leakage"
    UNSUPPORTED_VARIANT = "unsupported_presentation_variant"
    UNSUPPORTED_LOCALE = "unsupported_locale"
    UNSUPPORTED_RENDERER = "unsupported_renderer_version"
    EMPTY_RENDER = "empty_render"


class TypedRenderError(ValueError):
    def __init__(self, code: TypedRenderErrorCode, *, node_id: str | None = None) -> None:
        self.code = code
        self.node_id = node_id
        super().__init__(code.value)


class TypedRenderNodeType(str, Enum):
    TEXT = "TEXT"
    FACT_REF = "FACT_REF"
    PERIOD_REF = "PERIOD_REF"
    CLAIM_REF = "CLAIM_REF"
    CITATION_REF = "CITATION_REF"
    LIMITATION_REF = "LIMITATION_REF"
    INTERPRETATION_REF = "INTERPRETATION_REF"


@dataclass(frozen=True)
class TypedRenderNode:
    node_id: str
    node_type: TypedRenderNodeType
    owner_claim_ref: str | None = None
    text: str | None = None
    authority_ref: str | None = None
    presentation_variant: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "owner_claim_ref": self.owner_claim_ref,
            "text": self.text,
            "authority_ref": self.authority_ref,
            "presentation_variant": self.presentation_variant,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TypedRenderNode":
        expected = {"node_id", "node_type", "owner_claim_ref", "text", "authority_ref", "presentation_variant"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise TypedRenderError(TypedRenderErrorCode.MALFORMED_NODE)
        try:
            node_type = TypedRenderNodeType(str(payload["node_type"]))
        except ValueError as exc:
            raise TypedRenderError(TypedRenderErrorCode.MALFORMED_NODE) from exc
        return cls(
            node_id=str(payload["node_id"]), node_type=node_type,
            owner_claim_ref=str(payload["owner_claim_ref"]) if payload["owner_claim_ref"] is not None else None,
            text=str(payload["text"]) if payload["text"] is not None else None,
            authority_ref=str(payload["authority_ref"]) if payload["authority_ref"] is not None else None,
            presentation_variant=str(payload["presentation_variant"]) if payload["presentation_variant"] is not None else None,
        )


@dataclass(frozen=True)
class TypedRenderDocument:
    contract_version: str
    document_id: str
    owner_id: str
    nodes: tuple[TypedRenderNode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "document_id": self.document_id,
            "owner_id": self.owner_id,
            "nodes": [item.to_dict() for item in self.nodes],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TypedRenderDocument":
        expected = {"contract_version", "document_id", "owner_id", "nodes"}
        if not isinstance(payload, Mapping) or set(payload) != expected or not isinstance(payload["nodes"], list):
            raise TypedRenderError(TypedRenderErrorCode.INVALID_CONTRACT)
        return cls(
            str(payload["contract_version"]), str(payload["document_id"]),
            str(payload["owner_id"]),
            tuple(TypedRenderNode.from_dict(item) for item in payload["nodes"]),
        )


@dataclass(frozen=True)
class ClaimAuthorityRef:
    claim_ref: str
    citation_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class FactAuthorityRef:
    fact_ref: str
    owner_claim_ref: str
    numeric_fact: NumericFact


@dataclass(frozen=True)
class PeriodAuthorityRef:
    period_ref: str
    owner_claim_ref: str
    period: str
    fact_ref: str | None = None


@dataclass(frozen=True)
class CitationAuthorityRef:
    citation_ref: str
    owner_claim_ref: str
    source_id: str
    display_key: str


@dataclass(frozen=True)
class LimitationAuthorityRef:
    limitation_ref: str
    owner_claim_refs: tuple[str, ...]
    display_text: str


@dataclass(frozen=True)
class InterpretationAuthorityRef:
    interpretation_ref: str
    owner_claim_refs: tuple[str, ...]
    label: str
    provider_text: str


class TypedAuthorityCatalog(Protocol):
    claims: Mapping[str, ClaimAuthorityRef]
    facts: Mapping[str, FactAuthorityRef]
    periods: Mapping[str, PeriodAuthorityRef]
    citations: Mapping[str, CitationAuthorityRef]
    limitations: Mapping[str, LimitationAuthorityRef]
    interpretations: Mapping[str, InterpretationAuthorityRef]
    forbidden_source_names: tuple[str, ...]

    def to_canonical_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class H3AuthorityCatalog:
    claims: Mapping[str, ClaimAuthorityRef]
    facts: Mapping[str, FactAuthorityRef]
    periods: Mapping[str, PeriodAuthorityRef]
    citations: Mapping[str, CitationAuthorityRef]
    limitations: Mapping[str, LimitationAuthorityRef]
    interpretations: Mapping[str, InterpretationAuthorityRef]
    forbidden_source_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("claims", "facts", "periods", "citations", "limitations", "interpretations"):
            object.__setattr__(self, field, MappingProxyType(dict(getattr(self, field))))
        object.__setattr__(self, "forbidden_source_names", tuple(self.forbidden_source_names))

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "claims": {
                key: {"claim_ref": value.claim_ref, "citation_refs": list(value.citation_refs)}
                for key, value in sorted(self.claims.items())
            },
            "facts": {
                key: {
                    "fact_ref": value.fact_ref,
                    "owner_claim_ref": value.owner_claim_ref,
                    "numeric_fact": value.numeric_fact.to_dict(),
                }
                for key, value in sorted(self.facts.items())
            },
            "periods": {
                key: {
                    "period_ref": value.period_ref,
                    "owner_claim_ref": value.owner_claim_ref,
                    "period": value.period,
                    "fact_ref": value.fact_ref,
                }
                for key, value in sorted(self.periods.items())
            },
            "citations": {
                key: {
                    "citation_ref": value.citation_ref,
                    "owner_claim_ref": value.owner_claim_ref,
                    "source_id": value.source_id,
                    "display_key": value.display_key,
                }
                for key, value in sorted(self.citations.items())
            },
            "limitations": {
                key: {
                    "limitation_ref": value.limitation_ref,
                    "owner_claim_refs": list(value.owner_claim_refs),
                    "display_text": value.display_text,
                }
                for key, value in sorted(self.limitations.items())
            },
            "interpretations": {
                key: {
                    "interpretation_ref": value.interpretation_ref,
                    "owner_claim_refs": list(value.owner_claim_refs),
                    "label": value.label,
                    "provider_text": value.provider_text,
                }
                for key, value in sorted(self.interpretations.items())
            },
            "forbidden_source_names": sorted(self.forbidden_source_names),
        }

    @classmethod
    def from_canonical_dict(cls, payload: Mapping[str, Any]) -> "H3AuthorityCatalog":
        expected = {"claims", "facts", "periods", "citations", "limitations", "interpretations", "forbidden_source_names"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise TypedRenderError(TypedRenderErrorCode.INVALID_CONTRACT)
        try:
            return cls(
                claims={key: ClaimAuthorityRef(str(value["claim_ref"]), tuple(value["citation_refs"])) for key, value in payload["claims"].items()},
                facts={key: FactAuthorityRef(str(value["fact_ref"]), str(value["owner_claim_ref"]), NumericFact.from_dict(dict(value["numeric_fact"]))) for key, value in payload["facts"].items()},
                periods={key: PeriodAuthorityRef(str(value["period_ref"]), str(value["owner_claim_ref"]), str(value["period"]), str(value["fact_ref"]) if value["fact_ref"] is not None else None) for key, value in payload["periods"].items()},
                citations={key: CitationAuthorityRef(str(value["citation_ref"]), str(value["owner_claim_ref"]), str(value["source_id"]), str(value["display_key"])) for key, value in payload["citations"].items()},
                limitations={key: LimitationAuthorityRef(str(value["limitation_ref"]), tuple(value["owner_claim_refs"]), str(value["display_text"])) for key, value in payload["limitations"].items()},
                interpretations={key: InterpretationAuthorityRef(str(value["interpretation_ref"]), tuple(value["owner_claim_refs"]), str(value["label"]), str(value["provider_text"])) for key, value in payload["interpretations"].items()},
                forbidden_source_names=tuple(str(item) for item in payload["forbidden_source_names"]),
            )
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise TypedRenderError(TypedRenderErrorCode.INVALID_CONTRACT) from exc


@dataclass(frozen=True)
class TypedRenderResult:
    text: str
    locale: str
    renderer_version: str
    authority_digest: str
    ast_digest: str
    render_digest: str


_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_INTERNAL_ID = re.compile(
    r"(?i)(?<![\w-])(?:rq\d*|in\d*|finding|evidence|claim|source|citation)[_-][\w-]+"
)
_FACT_ANNOTATION = re.compile(
    r"(?i)(?:\b(?:period|період|географія|metric|метрика|показник|population|популяція|група)\s*:)"
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def authority_input_digest(catalog: TypedAuthorityCatalog) -> str:
    return canonical_digest(catalog.to_canonical_dict())


def typed_ast_digest(document: TypedRenderDocument) -> str:
    return canonical_digest(document.to_dict())


def rendered_output_digest(*, text: str, locale: str, renderer_version: str) -> str:
    return canonical_digest({
        "locale": locale,
        "renderer_version": renderer_version,
        "text": text,
    })


def validate_typed_render_document(
    document: TypedRenderDocument, catalog: TypedAuthorityCatalog,
) -> None:
    if document.contract_version != H3_CONTRACT_VERSION or not document.document_id or not document.owner_id:
        raise TypedRenderError(TypedRenderErrorCode.INVALID_CONTRACT)
    seen_node_ids: set[str] = set()
    for node in document.nodes:
        if not node.node_id or node.node_id in seen_node_ids:
            raise TypedRenderError(TypedRenderErrorCode.DUPLICATE_NODE_ID, node_id=node.node_id)
        seen_node_ids.add(node.node_id)
        _validate_node(node, catalog)


def _validate_node(node: TypedRenderNode, catalog: TypedAuthorityCatalog) -> None:
    if node.node_type is TypedRenderNodeType.TEXT:
        if node.owner_claim_ref is not None or node.authority_ref is not None or node.presentation_variant is not None or not node.text:
            raise TypedRenderError(TypedRenderErrorCode.MALFORMED_NODE, node_id=node.node_id)
        _validate_provider_text(node.text, catalog, node.node_id)
        return
    if node.text is not None or not node.authority_ref:
        raise TypedRenderError(TypedRenderErrorCode.MALFORMED_NODE, node_id=node.node_id)
    if node.node_type is TypedRenderNodeType.CLAIM_REF:
        if node.authority_ref not in catalog.claims or node.owner_claim_ref != node.authority_ref:
            raise TypedRenderError(TypedRenderErrorCode.UNKNOWN_CLAIM_REF, node_id=node.node_id)
        _no_variant(node)
        return
    if not node.owner_claim_ref or node.owner_claim_ref not in catalog.claims:
        raise TypedRenderError(TypedRenderErrorCode.UNKNOWN_CLAIM_REF, node_id=node.node_id)
    if node.node_type is TypedRenderNodeType.FACT_REF:
        fact = catalog.facts.get(node.authority_ref)
        if fact is None:
            raise TypedRenderError(TypedRenderErrorCode.UNKNOWN_FACT_REF, node_id=node.node_id)
        if fact.owner_claim_ref != node.owner_claim_ref:
            raise TypedRenderError(TypedRenderErrorCode.CROSS_CLAIM_FACT_REF, node_id=node.node_id)
        if node.presentation_variant not in {None, "value_with_unit", "geography", "metric", "population"}:
            raise TypedRenderError(TypedRenderErrorCode.UNSUPPORTED_VARIANT, node_id=node.node_id)
        return
    if node.node_type is TypedRenderNodeType.PERIOD_REF:
        period = catalog.periods.get(node.authority_ref)
        if period is None:
            raise TypedRenderError(TypedRenderErrorCode.UNKNOWN_PERIOD_REF, node_id=node.node_id)
        if period.owner_claim_ref != node.owner_claim_ref:
            raise TypedRenderError(TypedRenderErrorCode.CROSS_CLAIM_PERIOD_REF, node_id=node.node_id)
        if period.fact_ref is not None:
            fact = catalog.facts.get(period.fact_ref)
            if fact is None or fact.owner_claim_ref != node.owner_claim_ref or period.period not in fact.numeric_fact.periods:
                raise TypedRenderError(TypedRenderErrorCode.FACT_LOCAL_PERIOD_MISMATCH, node_id=node.node_id)
        if node.presentation_variant not in {None, "year", "locative"}:
            raise TypedRenderError(TypedRenderErrorCode.UNSUPPORTED_VARIANT, node_id=node.node_id)
        return
    if node.node_type is TypedRenderNodeType.CITATION_REF:
        citation = catalog.citations.get(node.authority_ref)
        if citation is None:
            raise TypedRenderError(TypedRenderErrorCode.UNKNOWN_CITATION_REF, node_id=node.node_id)
        if citation.owner_claim_ref != node.owner_claim_ref:
            raise TypedRenderError(TypedRenderErrorCode.CROSS_CLAIM_CITATION_REF, node_id=node.node_id)
        if node.authority_ref not in catalog.claims[node.owner_claim_ref].citation_refs:
            raise TypedRenderError(TypedRenderErrorCode.UNSUPPORTED_CITATION_REF, node_id=node.node_id)
        _no_variant(node)
        return
    if node.node_type is TypedRenderNodeType.LIMITATION_REF:
        limitation = catalog.limitations.get(node.authority_ref)
        if limitation is None:
            raise TypedRenderError(TypedRenderErrorCode.UNKNOWN_LIMITATION_REF, node_id=node.node_id)
        if node.owner_claim_ref not in limitation.owner_claim_refs:
            raise TypedRenderError(TypedRenderErrorCode.CROSS_CLAIM_LIMITATION_REF, node_id=node.node_id)
        _no_variant(node)
        return
    interpretation = catalog.interpretations.get(node.authority_ref)
    if interpretation is None:
        raise TypedRenderError(TypedRenderErrorCode.UNKNOWN_INTERPRETATION_REF, node_id=node.node_id)
    if node.owner_claim_ref not in interpretation.owner_claim_refs:
        raise TypedRenderError(TypedRenderErrorCode.CROSS_CLAIM_INTERPRETATION_REF, node_id=node.node_id)
    _validate_provider_text(interpretation.provider_text, catalog, node.node_id)
    _no_variant(node)


def _no_variant(node: TypedRenderNode) -> None:
    if node.presentation_variant is not None:
        raise TypedRenderError(TypedRenderErrorCode.UNSUPPORTED_VARIANT, node_id=node.node_id)


def _validate_provider_text(text: str, catalog: TypedAuthorityCatalog, node_id: str) -> None:
    if any(character.isdigit() for character in text):
        raise TypedRenderError(TypedRenderErrorCode.TEXT_DIGIT_LEAKAGE, node_id=node_id)
    if _URL.search(text):
        raise TypedRenderError(TypedRenderErrorCode.TEXT_URL_LEAKAGE, node_id=node_id)
    folded = text.casefold()
    known_ids = (
        *catalog.claims, *catalog.facts, *catalog.periods, *catalog.citations,
        *catalog.limitations, *catalog.interpretations,
    )
    if _INTERNAL_ID.search(text) or any(item and item.casefold() in folded for item in known_ids):
        raise TypedRenderError(TypedRenderErrorCode.TEXT_INTERNAL_ID_LEAKAGE, node_id=node_id)
    if any(item.strip() and item.casefold() in folded for item in catalog.forbidden_source_names):
        raise TypedRenderError(TypedRenderErrorCode.TEXT_SOURCE_NAME_LEAKAGE, node_id=node_id)
    if _FACT_ANNOTATION.search(text):
        raise TypedRenderError(TypedRenderErrorCode.TEXT_FACT_ANNOTATION_LEAKAGE, node_id=node_id)


def render_typed_document(
    document: TypedRenderDocument, catalog: TypedAuthorityCatalog, *,
    locale: str = H3_LOCALE, renderer_version: str = H3_RENDERER_VERSION,
) -> TypedRenderResult:
    if locale != H3_LOCALE:
        raise TypedRenderError(TypedRenderErrorCode.UNSUPPORTED_LOCALE)
    if renderer_version != H3_RENDERER_VERSION:
        raise TypedRenderError(TypedRenderErrorCode.UNSUPPORTED_RENDERER)
    validate_typed_render_document(document, catalog)
    parts: list[str] = []
    rendered_citations: set[str] = set()
    previous_visible_type: TypedRenderNodeType | None = None
    for node in document.nodes:
        value = _render_node(node, catalog, rendered_citations)
        if value:
            _append_with_boundary(
                parts, value,
                previous_type=previous_visible_type,
                current_type=node.node_type,
            )
            previous_visible_type = node.node_type
    text = "".join(parts).strip()
    if not text:
        raise TypedRenderError(TypedRenderErrorCode.EMPTY_RENDER)
    return TypedRenderResult(
        text=text,
        locale=locale,
        renderer_version=renderer_version,
        authority_digest=authority_input_digest(catalog),
        ast_digest=typed_ast_digest(document),
        render_digest=rendered_output_digest(
            text=text, locale=locale, renderer_version=renderer_version,
        ),
    )


def verify_render_integrity(result: TypedRenderResult) -> bool:
    return result.render_digest == rendered_output_digest(
        text=result.text, locale=result.locale, renderer_version=result.renderer_version,
    )


def _render_node(
    node: TypedRenderNode, catalog: TypedAuthorityCatalog, rendered_citations: set[str],
) -> str:
    if node.node_type is TypedRenderNodeType.TEXT:
        return node.text or ""
    if node.node_type is TypedRenderNodeType.CLAIM_REF:
        return ""
    if node.node_type is TypedRenderNodeType.FACT_REF:
        return _render_fact(catalog.facts[node.authority_ref or ""], node.presentation_variant)
    if node.node_type is TypedRenderNodeType.PERIOD_REF:
        return _render_period(catalog.periods[node.authority_ref or ""], node.presentation_variant)
    if node.node_type is TypedRenderNodeType.CITATION_REF:
        if node.authority_ref in rendered_citations:
            return ""
        rendered_citations.add(node.authority_ref or "")
        return f"[{catalog.citations[node.authority_ref or ''].display_key}]"
    if node.node_type is TypedRenderNodeType.LIMITATION_REF:
        return catalog.limitations[node.authority_ref or ""].display_text
    return catalog.interpretations[node.authority_ref or ""].provider_text


def _render_fact(fact: FactAuthorityRef, variant: str | None) -> str:
    numeric = fact.numeric_fact
    if variant == "geography":
        return _single(numeric.geography, TypedRenderErrorCode.UNSUPPORTED_VARIANT)
    if variant == "metric":
        return _single(numeric.metrics, TypedRenderErrorCode.UNSUPPORTED_VARIANT)
    if variant == "population":
        return _single(numeric.population_dimensions, TypedRenderErrorCode.UNSUPPORTED_VARIANT)
    value = _decimal_uk(numeric.value)
    if numeric.unit == "%":
        return f"{value}%"
    scale = "" if numeric.scale.casefold() in {"", "absolute"} else {
        "million": "млн", "billion": "млрд", "thousand": "тис.",
    }.get(numeric.scale.casefold(), numeric.scale)
    return " ".join(item for item in (value, scale, numeric.unit) if item)


def _render_period(period: PeriodAuthorityRef, variant: str | None) -> str:
    if re.fullmatch(r"\d{4}", period.period):
        return f"{period.period} році" if variant == "locative" else period.period
    return period.period


def _decimal_uk(value: str) -> str:
    try:
        normalized = format(Decimal(str(value)), "f")
    except InvalidOperation as exc:
        raise TypedRenderError(TypedRenderErrorCode.MALFORMED_NODE) from exc
    integer, dot, fraction = normalized.partition(".")
    fraction = fraction.rstrip("0")
    return integer + (("," + fraction) if dot and fraction else "")


def _single(values: tuple[str, ...], code: TypedRenderErrorCode) -> str:
    if len(values) != 1:
        raise TypedRenderError(code)
    return values[0]


def _append_with_boundary(
    parts: list[str], value: str, *, previous_type: TypedRenderNodeType | None,
    current_type: TypedRenderNodeType,
) -> None:
    if not value:
        return
    structural_separation = bool(
        previous_type is not None
        and previous_type is not TypedRenderNodeType.TEXT
        and current_type not in {TypedRenderNodeType.TEXT, TypedRenderNodeType.CITATION_REF}
    )
    lexical_separation = bool(
        parts and parts[-1] and parts[-1][-1].isalnum() and value[0].isalnum()
    )
    if (structural_separation or lexical_separation) and parts and not parts[-1][-1].isspace():
        parts.append(" ")
    parts.append(value)
