"""Sanitized production-shaped authority corpus for downstream qualification.

The identifiers and semantic values below are deterministic test data.  The
cardinalities and authority *shapes* mirror the canonical Desk study, but this
module intentionally contains no production source text.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.reports.report_claim import NumericFact


@dataclass(frozen=True)
class ProductionShapedAuthorityCorpus:
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]
    rq_ids: tuple[str, ...]
    information_need_ids: tuple[str, ...]
    facts: tuple[NumericFact, ...]

    @property
    def cardinalities(self) -> tuple[int, int, int, int]:
        return tuple(map(len, (
            self.source_ids, self.evidence_ids, self.finding_ids, self.insight_ids,
        )))


def production_shaped_authority_corpus() -> ProductionShapedAuthorityCorpus:
    """Return reusable sanitized authority with known production-shaped forms."""

    facts = (
        NumericFact("7.8", "%", "absolute", ("україна",), ("2026",), ("частка",), ("домогосподарства",)),
        NumericFact("8.7", "%", "absolute", ("україна",), ("2025", "2026"), ("частка",), ()),
        NumericFact("43", "%", "absolute", ("україна",), ("2021",), (), ()),
        NumericFact("1.06", "млрд", "absolute", ("україна",), ("2021",), ("обсяг",), ()),
        NumericFact("106", "млрд", "absolute", ("україна",), ("2021",), ("обсяг",), ()),
        NumericFact("48705", "грн", "absolute", ("київ",), (), ("дохід",), ("працівники",)),
        NumericFact("23", "%", "absolute", ("україна",), (), (), ()),
        NumericFact("36", "%", "absolute", ("львівська область",), ("2025",), ("частка",), ()),
        NumericFact("10", "count", "million", (), ("2025",), (), ()),
        NumericFact("102.0", "%", "absolute", ("україна",), ("2025",), ("індекс",), ()),
    )
    return ProductionShapedAuthorityCorpus(
        source_ids=tuple(f"source-{index:02d}" for index in range(1, 31)),
        evidence_ids=tuple(f"evidence-{index:02d}" for index in range(1, 20)),
        finding_ids=tuple(f"finding-{index}" for index in range(1, 5)),
        insight_ids=tuple(f"insight-{index}" for index in range(1, 6)),
        rq_ids=("rq-market-size", "rq-dynamics", "rq-regions", "rq-outlook"),
        information_need_ids=("in-value", "in-period", "in-region", "in-comparison", "in-limitations"),
        facts=facts,
    )
