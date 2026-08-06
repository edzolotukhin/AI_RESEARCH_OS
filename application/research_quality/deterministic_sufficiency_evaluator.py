from __future__ import annotations

from typing import Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType

_SCORE_KEYS = {
    "freshness": ("freshness_score", "freshness"),
    "source_quality": ("source_quality_score", "source_quality"),
    "source_diversity": ("source_diversity_score", "source_diversity"),
}


class DeterministicSufficiencyEvaluator:
    """Computes objective sufficiency facts per InformationNeed (no policy/LLM)."""

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> tuple[DeterministicSufficiencySignals, ...]:
        known_need_ids = {need.id for need in design.information_needs}
        need_by_id = {need.id: need for need in design.information_needs}
        sorted_needs = sorted(
            design.information_needs,
            key=lambda need: (need.research_question_id, need.id),
        )

        mapped_evidence: dict[str, list[Evidence]] = {
            need.id: [] for need in sorted_needs
        }
        need_warnings: dict[str, list[str]] = {need.id: [] for need in sorted_needs}

        for item in sorted(evidence, key=lambda record: record.id):
            known_refs = [
                ref for ref in item.information_need_refs if ref in known_need_ids
            ]
            unknown_refs = [
                ref for ref in item.information_need_refs if ref not in known_need_ids
            ]
            if unknown_refs:
                warning = (
                    f"evidence {item.id} references unknown information_need_id(s): "
                    + ", ".join(sorted(unknown_refs))
                )
                if known_refs:
                    for ref in known_refs:
                        need_warnings[ref].append(warning)
                else:
                    target_needs = [
                        need
                        for need in sorted_needs
                        if not item.research_question_refs
                        or need.research_question_id in item.research_question_refs
                    ]
                    for need in target_needs:
                        need_warnings[need.id].append(warning)

            for ref in known_refs:
                need = need_by_id[ref]
                if (
                    item.research_question_refs
                    and need.research_question_id not in item.research_question_refs
                ):
                    need_warnings[ref].append(
                        f"evidence {item.id} references information_need {ref} but "
                        f"research_question_refs {list(item.research_question_refs)} "
                        f"do not include {need.research_question_id}",
                    )
                mapped_evidence[ref].append(item)

        return tuple(
            self._signals_for_need(
                need=need,
                mapped=mapped_evidence[need.id],
                warnings=need_warnings[need.id],
            )
            for need in sorted_needs
        )

    def _signals_for_need(
        self,
        *,
        need: InformationNeed,
        mapped: list[Evidence],
        warnings: list[str],
    ) -> DeterministicSufficiencySignals:
        unique_evidence, duplicate_count = _deduplicate_evidence(mapped)
        evidence_ids = tuple(sorted(item.id for item in unique_evidence))
        source_ids = tuple(sorted({item.source_id for item in unique_evidence}))

        freshness_available, freshness_score = _aggregate_score(
            unique_evidence,
            score_key=_SCORE_KEYS["freshness"][0],
            alt_key=_SCORE_KEYS["freshness"][1],
        )
        quality_available, quality_score = _aggregate_score(
            unique_evidence,
            score_key=_SCORE_KEYS["source_quality"][0],
            alt_key=_SCORE_KEYS["source_quality"][1],
        )
        diversity_available, diversity_score = _aggregate_score(
            unique_evidence,
            score_key=_SCORE_KEYS["source_diversity"][0],
            alt_key=_SCORE_KEYS["source_diversity"][1],
        )

        gap_types: list[GapType] = []
        if not unique_evidence:
            gap_types.append(GapType.NO_EVIDENCE)

        normalized_warnings = _normalize_warnings(warnings)
        if not _contradiction_signal_available(unique_evidence):
            normalized_warnings = _append_warning(
                normalized_warnings,
                "contradiction signal unavailable: no structured contradiction metadata",
            )

        return DeterministicSufficiencySignals(
            information_need_id=need.id,
            research_question_id=need.research_question_id,
            evidence_count=len(unique_evidence),
            independent_source_count=len(source_ids),
            evidence_ids=evidence_ids,
            source_ids=source_ids,
            freshness_available=freshness_available,
            freshness_score=freshness_score,
            source_quality_available=quality_available,
            source_quality_score=quality_score,
            source_diversity_available=diversity_available,
            source_diversity_score=diversity_score,
            quantitative_evidence_present=_quantitative_evidence_present(
                unique_evidence,
            ),
            duplicate_evidence_count=duplicate_count,
            contradictions=_collect_contradictions(unique_evidence),
            deterministic_gap_types=tuple(gap_types),
            warnings=normalized_warnings,
        )


def _deduplicate_evidence(
    mapped: list[Evidence],
) -> tuple[list[Evidence], int]:
    """Return unique evidence and duplicate count using stable identifiers."""
    sorted_items = sorted(mapped, key=lambda item: item.id)
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    unique: list[Evidence] = []
    duplicates = 0

    for item in sorted_items:
        if item.id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(item.id)

        dedup_key = item.deduplication_key.strip() if item.deduplication_key else item.id
        if dedup_key in seen_keys:
            duplicates += 1
            continue
        seen_keys.add(dedup_key)
        unique.append(item)

    return unique, duplicates


def _read_unit_score(container: dict, key: str) -> float | None:
    value = container.get(key)
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= score <= 1.0:
        return score
    return None


def _aggregate_score(
    evidence_items: Sequence[Evidence],
    *,
    score_key: str,
    alt_key: str,
) -> tuple[bool, float | None]:
    scores: list[float] = []
    for item in evidence_items:
        for container in (item.quality_signals, item.metadata):
            score = _read_unit_score(container, score_key)
            if score is None:
                score = _read_unit_score(container, alt_key)
            if score is not None:
                scores.append(score)
                break
    if not scores:
        return False, None
    return True, min(scores)


def _quantitative_evidence_present(
    evidence_items: Sequence[Evidence],
) -> bool | None:
    if not evidence_items:
        return None
    flags: list[bool] = []
    for item in evidence_items:
        for container in (item.metadata, item.quality_signals):
            if "quantitative_evidence_present" in container:
                flags.append(bool(container["quantitative_evidence_present"]))
                break
            if "quantitative" in container:
                flags.append(bool(container["quantitative"]))
                break
    if not flags:
        return None
    return any(flags)


def _collect_contradictions(evidence_items: Sequence[Evidence]) -> tuple[str, ...]:
    collected: list[str] = []
    seen: set[str] = set()
    for item in evidence_items:
        raw = item.metadata.get("contradictions")
        if raw is None:
            continue
        if isinstance(raw, str):
            values = (raw,)
        elif isinstance(raw, (list, tuple)):
            values = tuple(str(value) for value in raw)
        else:
            continue
        for value in values:
            text = value.strip()
            if text and text not in seen:
                seen.add(text)
                collected.append(text)
    return tuple(collected)


def _contradiction_signal_available(evidence_items: Sequence[Evidence]) -> bool:
    for item in evidence_items:
        if "contradictions" in item.metadata:
            return True
    return False


def _normalize_warnings(warnings: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for warning in sorted(warnings):
        text = warning.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _append_warning(
    warnings: tuple[str, ...],
    message: str,
) -> tuple[str, ...]:
    return _normalize_warnings((*warnings, message))
