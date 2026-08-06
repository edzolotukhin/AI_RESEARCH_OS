"""Tests for P1-02 deterministic sufficiency signals and evaluator."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType

from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _design(*, need_ids: tuple[str, ...] = ("in-1", "in-2")) -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(
                id="rq-1",
                question="What is the market outlook?",
                objective_refs=(),
            ),
        ),
        information_needs=tuple(
            InformationNeed(
                id=need_id,
                research_question_id="rq-1",
                description=f"Need {need_id}",
            )
            for need_id in need_ids
        ),
    )


def _evidence(
    *,
    evidence_id: str,
    source_id: str = "source-1",
    information_need_refs: tuple[str, ...] = ("in-1",),
    research_question_refs: tuple[str, ...] = ("rq-1",),
    deduplication_key: str = "",
    metadata: dict | None = None,
    quality_signals: dict | None = None,
) -> Evidence:
    return Evidence(
        id=evidence_id,
        project_id="project-1",
        source_id=source_id,
        source_content_checksum=f"checksum-{evidence_id}",
        workflow_run_id="run-1",
        research_design_id="design-1",
        research_question_refs=research_question_refs,
        information_need_refs=information_need_refs,
        statement=f"Statement {evidence_id}",
        source_excerpt=f"Excerpt {evidence_id}",
        created_at="2026-01-01T00:00:00+00:00",
        deduplication_key=deduplication_key or f"dedup-{evidence_id}",
        metadata=metadata or {},
        quality_signals=quality_signals or {},
    )


class DeterministicSufficiencyEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._evaluator = DeterministicSufficiencyEvaluator()

    def test_need_without_evidence_present_with_no_evidence_gap(self) -> None:
        results = self._evaluator.evaluate(design=_design(), evidence=())
        self.assertEqual(len(results), 2)
        by_id = {item.information_need_id: item for item in results}
        missing = by_id["in-1"]
        self.assertEqual(missing.evidence_count, 0)
        self.assertEqual(missing.deterministic_gap_types, (GapType.NO_EVIDENCE,))

    def test_evidence_maps_by_information_need_refs(self) -> None:
        evidence = (
            _evidence(evidence_id="ev-1", information_need_refs=("in-1",)),
            _evidence(evidence_id="ev-2", information_need_refs=("in-2",)),
        )
        results = self._evaluator.evaluate(design=_design(), evidence=evidence)
        by_id = {item.information_need_id: item for item in results}
        self.assertEqual(by_id["in-1"].evidence_count, 1)
        self.assertEqual(by_id["in-1"].evidence_ids, ("ev-1",))
        self.assertEqual(by_id["in-2"].evidence_count, 1)

    def test_multiple_evidence_same_source_counts_one_independent_source(self) -> None:
        evidence = (
            _evidence(evidence_id="ev-1", source_id="source-a", information_need_refs=("in-1",)),
            _evidence(evidence_id="ev-2", source_id="source-a", information_need_refs=("in-1",)),
        )
        result = next(
            item
            for item in self._evaluator.evaluate(design=_design(), evidence=evidence)
            if item.information_need_id == "in-1"
        )
        self.assertEqual(result.evidence_count, 2)
        self.assertEqual(result.independent_source_count, 1)
        self.assertEqual(result.source_ids, ("source-a",))

    def test_multiple_sources_increase_independent_source_count(self) -> None:
        evidence = (
            _evidence(evidence_id="ev-1", source_id="source-a", information_need_refs=("in-1",)),
            _evidence(evidence_id="ev-2", source_id="source-b", information_need_refs=("in-1",)),
        )
        result = next(
            item
            for item in self._evaluator.evaluate(design=_design(), evidence=evidence)
            if item.information_need_id == "in-1"
        )
        self.assertEqual(result.independent_source_count, 2)
        self.assertEqual(result.source_ids, ("source-a", "source-b"))

    def test_duplicate_evidence_does_not_increase_unique_count(self) -> None:
        shared_key = "shared-dedup-key"
        evidence = (
            _evidence(
                evidence_id="ev-1",
                information_need_refs=("in-1",),
                deduplication_key=shared_key,
            ),
            _evidence(
                evidence_id="ev-2",
                information_need_refs=("in-1",),
                deduplication_key=shared_key,
            ),
        )
        result = next(
            item
            for item in self._evaluator.evaluate(design=_design(), evidence=evidence)
            if item.information_need_id == "in-1"
        )
        self.assertEqual(result.evidence_count, 1)
        self.assertEqual(result.duplicate_evidence_count, 1)

    def test_unknown_information_need_ref_is_reported(self) -> None:
        evidence = (
            _evidence(
                evidence_id="ev-1",
                information_need_refs=("in-1", "in-unknown"),
            ),
        )
        result = next(
            item
            for item in self._evaluator.evaluate(design=_design(), evidence=evidence)
            if item.information_need_id == "in-1"
        )
        self.assertTrue(
            any("unknown information_need_id" in warning for warning in result.warnings),
        )
        self.assertEqual(result.evidence_count, 1)

    def test_all_design_needs_always_present(self) -> None:
        results = self._evaluator.evaluate(
            design=_design(need_ids=("in-a", "in-b", "in-c")),
            evidence=(_evidence(evidence_id="ev-1", information_need_refs=("in-b",)),),
        )
        self.assertEqual(
            [item.information_need_id for item in results],
            ["in-a", "in-b", "in-c"],
        )

    def test_input_ordering_does_not_change_result(self) -> None:
        design = _design()
        evidence_a = (
            _evidence(evidence_id="ev-2", information_need_refs=("in-2",)),
            _evidence(evidence_id="ev-1", information_need_refs=("in-1",)),
        )
        evidence_b = tuple(reversed(evidence_a))
        results_a = self._evaluator.evaluate(design=design, evidence=evidence_a)
        results_b = self._evaluator.evaluate(design=design, evidence=evidence_b)
        self.assertEqual(
            [item.to_dict() for item in results_a],
            [item.to_dict() for item in results_b],
        )

    def test_deterministic_serialization_roundtrip(self) -> None:
        original = DeterministicSufficiencySignals(
            information_need_id="in-1",
            research_question_id="rq-1",
            evidence_count=2,
            independent_source_count=1,
            evidence_ids=("ev-1", "ev-2"),
            source_ids=("source-1",),
            quantitative_evidence_present=None,
            duplicate_evidence_count=0,
            deterministic_gap_types=(),
            warnings=("sample warning",),
        )
        restored = DeterministicSufficiencySignals.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(
            json.dumps(original.to_dict(), sort_keys=True),
            json.dumps(restored.to_dict(), sort_keys=True),
        )

    def test_missing_freshness_metadata_does_not_create_score(self) -> None:
        result = next(
            item
            for item in self._evaluator.evaluate(
                design=_design(),
                evidence=(_evidence(evidence_id="ev-1"),),
            )
            if item.information_need_id == "in-1"
        )
        self.assertFalse(result.freshness_available)
        self.assertIsNone(result.freshness_score)

    def test_missing_quality_metadata_does_not_create_score(self) -> None:
        result = next(
            item
            for item in self._evaluator.evaluate(
                design=_design(),
                evidence=(_evidence(evidence_id="ev-1"),),
            )
            if item.information_need_id == "in-1"
        )
        self.assertFalse(result.source_quality_available)
        self.assertIsNone(result.source_quality_score)

    def test_missing_diversity_metadata_does_not_create_score(self) -> None:
        result = next(
            item
            for item in self._evaluator.evaluate(
                design=_design(),
                evidence=(_evidence(evidence_id="ev-1"),),
            )
            if item.information_need_id == "in-1"
        )
        self.assertFalse(result.source_diversity_available)
        self.assertIsNone(result.source_diversity_score)

    def test_missing_quantitative_metadata_returns_none(self) -> None:
        result = next(
            item
            for item in self._evaluator.evaluate(
                design=_design(),
                evidence=(
                    _evidence(
                        evidence_id="ev-1",
                        information_need_refs=("in-1",),
                    ),
                ),
            )
            if item.information_need_id == "in-1"
        )
        self.assertIsNone(result.quantitative_evidence_present)

    def test_explicit_quantitative_metadata_is_used(self) -> None:
        result = next(
            item
            for item in self._evaluator.evaluate(
                design=_design(),
                evidence=(
                    _evidence(
                        evidence_id="ev-1",
                        metadata={"quantitative_evidence_present": True},
                    ),
                ),
            )
            if item.information_need_id == "in-1"
        )
        self.assertTrue(result.quantitative_evidence_present)

    def test_evaluator_has_no_llm_imports(self) -> None:
        path = REPO_ROOT / "application" / "research_quality" / "deterministic_sufficiency_evaluator.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertFalse(any("llm" in item.lower() for item in imports))


class ResearchQualityLayerBoundaryTests(unittest.TestCase):
    def test_application_research_quality_does_not_import_infrastructure(self) -> None:
        forbidden = ("infrastructure.",)
        violations: list[str] = []
        package_root = REPO_ROOT / "application" / "research_quality"
        for path in sorted(package_root.rglob("*.py")):
            if path.name.endswith("_factory.py"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                else:
                    continue
                if any(
                    module == prefix.rstrip(".") or module.startswith(prefix)
                    for prefix in forbidden
                ):
                    violations.append(f"{path.name} -> {module}")
        self.assertEqual(violations, [])

    def test_domain_research_quality_does_not_import_application_or_infrastructure(
        self,
    ) -> None:
        forbidden = ("application.", "infrastructure.", "agency.")
        violations: list[str] = []
        package_root = REPO_ROOT / "domain" / "research_quality"
        for path in sorted(package_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                else:
                    continue
                if any(
                    module == prefix.rstrip(".") or module.startswith(prefix)
                    for prefix in forbidden
                ):
                    violations.append(f"{path.name} -> {module}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
