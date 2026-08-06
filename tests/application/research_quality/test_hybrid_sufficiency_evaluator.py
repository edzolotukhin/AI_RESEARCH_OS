"""Tests for P1-03 hybrid research sufficiency evaluator."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus

from application.research_quality.evidence_payload import (
    DEFAULT_MAX_EVIDENCE_ITEMS,
    select_bounded_evidence,
)
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.semantic_sufficiency_contract import (
    semantic_sufficiency_payload_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _design(
    *,
    need_ids: tuple[str, ...] = ("in-1", "in-2"),
    rq_ids: tuple[str, ...] = ("rq-1",),
) -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=tuple(
            ResearchQuestion(
                id=rq_id,
                question=f"Question for {rq_id}?",
                objective_refs=(),
            )
            for rq_id in rq_ids
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
    confidence: float | None = None,
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
        deduplication_key=f"dedup-{evidence_id}",
        confidence=confidence,
        metadata=metadata or {},
        quality_signals=quality_signals or {},
    )


def _semantic(
    *,
    status: SufficiencyStatus,
    missing_aspects: tuple[str, ...] = (),
    gap_types: tuple[GapType, ...] = (),
    search_directives: tuple[str, ...] = (),
    confidence: float | None = 0.8,
    reason: str = "Semantic assessment.",
) -> SemanticSufficiencyAssessment:
    return SemanticSufficiencyAssessment(
        status=status,
        missing_aspects=missing_aspects,
        gap_types=gap_types,
        search_directives=search_directives,
        confidence=confidence,
        reason=reason,
    )


class RecordingSemanticAssessor:
    def __init__(
        self,
        *,
        default: SemanticSufficiencyAssessment | None = None,
        by_need: dict[str, SemanticSufficiencyAssessment] | None = None,
        side_effect: BaseException | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self._default = default or _semantic(status=SufficiencyStatus.SUFFICIENT)
        self._by_need = by_need or {}
        self._side_effect = side_effect

    def assess(self, **kwargs) -> SemanticSufficiencyAssessment:
        self.calls.append(kwargs)
        if self._side_effect is not None:
            raise self._side_effect
        need_id = kwargs["information_need"].id
        return self._by_need.get(need_id, self._default)


class HybridSufficiencyEvaluatorTests(unittest.TestCase):
    def test_missing_need_short_circuits_without_semantic_call(self) -> None:
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(design=_design(), evidence=())

        self.assertEqual(len(semantic.calls), 0)
        assessments = result.research_question_assessments[0].information_need_assessments
        by_id = {item.information_need_id: item for item in assessments}
        self.assertEqual(by_id["in-1"].status, SufficiencyStatus.MISSING)
        self.assertEqual(by_id["in-2"].status, SufficiencyStatus.MISSING)
        self.assertEqual(by_id["in-1"].gap_types, (GapType.NO_EVIDENCE,))

    def test_evidence_present_calls_semantic_once_per_need(self) -> None:
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evidence = (
            _evidence(evidence_id="ev-1", information_need_refs=("in-1",)),
            _evidence(evidence_id="ev-2", information_need_refs=("in-2",)),
        )
        evaluator.evaluate(design=_design(), evidence=evidence)
        self.assertEqual(len(semantic.calls), 2)

    def test_only_mapped_evidence_passed_to_semantic(self) -> None:
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evidence = (
            _evidence(evidence_id="ev-1", information_need_refs=("in-1",)),
            _evidence(evidence_id="ev-2", information_need_refs=("in-2",)),
            _evidence(evidence_id="ev-3", information_need_refs=("in-1",)),
        )
        evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=evidence,
        )
        self.assertEqual(len(semantic.calls), 1)
        passed_ids = {item.id for item in semantic.calls[0]["evidence"]}
        self.assertEqual(passed_ids, {"ev-1", "ev-3"})

    def test_semantic_sufficient_maps_to_final_sufficient(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={"in-1": _semantic(status=SufficiencyStatus.SUFFICIENT)},
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(assessment.evidence_count, 1)

    def test_partial_is_blocking_with_directives(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={
                "in-1": _semantic(
                    status=SufficiencyStatus.PARTIAL,
                    missing_aspects=("recent market size",),
                    gap_types=(GapType.INSUFFICIENT_DEPTH,),
                    search_directives=("Find 2025 market size data",),
                ),
            },
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.status, SufficiencyStatus.PARTIAL)
        self.assertEqual(assessment.missing_aspects, ("recent market size",))
        self.assertEqual(assessment.search_directives, ("Find 2025 market size data",))
        self.assertFalse(result.ready_for_analysis)

    def test_insufficient_is_blocking(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={
                "in-1": _semantic(
                    status=SufficiencyStatus.INSUFFICIENT,
                    gap_types=(GapType.INSUFFICIENT_DIVERSITY,),
                ),
            },
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        self.assertEqual(
            result.research_question_assessments[0].information_need_assessments[0].status,
            SufficiencyStatus.INSUFFICIENT,
        )
        self.assertFalse(result.ready_for_analysis)

    def test_blocked_is_blocking_without_targeted_research(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={
                "in-1": _semantic(
                    status=SufficiencyStatus.BLOCKED,
                    gap_types=(GapType.UNRESOLVABLE,),
                    reason="Cannot resolve with public sources.",
                ),
            },
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)

    def test_all_sufficient_needs_make_rq_ready(self) -> None:
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evidence = (
            _evidence(evidence_id="ev-1", information_need_refs=("in-1",)),
            _evidence(evidence_id="ev-2", information_need_refs=("in-2",)),
        )
        result = evaluator.evaluate(design=_design(), evidence=evidence)
        self.assertTrue(result.research_question_assessments[0].ready_for_analysis)

    def test_mixed_statuses_make_rq_not_ready(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={
                "in-2": _semantic(status=SufficiencyStatus.PARTIAL),
            },
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evidence = (
            _evidence(evidence_id="ev-1", information_need_refs=("in-1",)),
            _evidence(evidence_id="ev-2", information_need_refs=("in-2",)),
        )
        result = evaluator.evaluate(design=_design(), evidence=evidence)
        self.assertFalse(result.research_question_assessments[0].ready_for_analysis)

    def test_all_rqs_ready_makes_run_ready(self) -> None:
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design(need_ids=("in-1",), rq_ids=("rq-1", "rq-2"))
        design = ResearchDesign(
            id=design.id,
            research_questions=design.research_questions,
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Need for rq-1",
                ),
                InformationNeed(
                    id="in-2",
                    research_question_id="rq-2",
                    description="Need for rq-2",
                ),
            ),
        )
        evidence = (
            _evidence(
                evidence_id="ev-1",
                information_need_refs=("in-1",),
                research_question_refs=("rq-1",),
            ),
            _evidence(
                evidence_id="ev-2",
                information_need_refs=("in-2",),
                research_question_refs=("rq-2",),
            ),
        )
        result = evaluator.evaluate(design=design, evidence=evidence)
        self.assertTrue(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)

    def test_actionable_gaps_set_targeted_research_required(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={"in-1": _semantic(status=SufficiencyStatus.PARTIAL)},
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        self.assertTrue(result.targeted_research_required)

    def test_only_blocked_gaps_do_not_require_targeted_research(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={"in-1": _semantic(status=SufficiencyStatus.BLOCKED)},
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        self.assertFalse(result.targeted_research_required)

    def test_unknown_evidence_refs_do_not_create_new_needs(self) -> None:
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evidence = (
            _evidence(
                evidence_id="ev-1",
                information_need_refs=("unknown-need",),
            ),
        )
        result = evaluator.evaluate(design=_design(need_ids=("in-1",)), evidence=evidence)
        assessed_ids = {
            item.information_need_id
            for rq in result.research_question_assessments
            for item in rq.information_need_assessments
        }
        self.assertEqual(assessed_ids, {"in-1"})
        self.assertEqual(len(semantic.calls), 0)

    def test_evaluator_does_not_create_or_replan_design_entities(self) -> None:
        design = _design(need_ids=("in-1",))
        original_need_count = len(design.information_needs)
        original_rq_count = len(design.research_questions)
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evaluator.evaluate(
            design=design,
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        self.assertEqual(len(design.information_needs), original_need_count)
        self.assertEqual(len(design.research_questions), original_rq_count)

    def test_semantic_result_serialization_is_deterministic(self) -> None:
        original = _semantic(
            status=SufficiencyStatus.PARTIAL,
            missing_aspects=("aspect b", "aspect a"),
            gap_types=(GapType.INSUFFICIENT_DEPTH, GapType.STALE_EVIDENCE),
            search_directives=("directive b", "directive a"),
        )
        restored = SemanticSufficiencyAssessment.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(
            json.dumps(restored.to_dict(), sort_keys=True),
            json.dumps(original.to_dict(), sort_keys=True),
        )

    def test_technical_semantic_error_propagates(self) -> None:
        semantic = RecordingSemanticAssessor(
            side_effect=SemanticSufficiencyAssessmentError("provider failure"),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        with self.assertRaises(SemanticSufficiencyAssessmentError):
            evaluator.evaluate(
                design=_design(need_ids=("in-1",)),
                evidence=(_evidence(evidence_id="ev-1"),),
            )

    def test_research_insufficiency_does_not_raise(self) -> None:
        semantic = RecordingSemanticAssessor(
            by_need={"in-1": _semantic(status=SufficiencyStatus.INSUFFICIENT)},
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        self.assertFalse(result.ready_for_analysis)

    def test_no_runtime_wiring(self) -> None:
        composition_root = REPO_ROOT / "application" / "composition_root.py"
        if composition_root.exists():
            text = composition_root.read_text(encoding="utf-8")
            self.assertNotIn("HybridResearchSufficiencyEvaluator", text)
            self.assertNotIn("LlmSemanticSufficiencyAssessor", text)
            self.assertNotIn("ResearchSufficiencyEvaluator", text)


class EvidencePayloadTests(unittest.TestCase):
    def test_bounded_selection_is_deterministic(self) -> None:
        items = tuple(
            _evidence(
                evidence_id=f"ev-{index}",
                confidence=0.1 * index if index % 2 == 0 else None,
            )
            for index in range(1, 15)
        )
        first = select_bounded_evidence(items, max_items=5)
        second = select_bounded_evidence(items, max_items=5)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)

    def test_bounded_selection_prefers_higher_confidence(self) -> None:
        items = (
            _evidence(evidence_id="ev-low", confidence=0.2),
            _evidence(evidence_id="ev-high", confidence=0.9),
            _evidence(evidence_id="ev-mid", confidence=0.5),
        )
        selected = select_bounded_evidence(items, max_items=2)
        self.assertEqual([item.id for item in selected], ["ev-high", "ev-mid"])


class SufficiencyStructuredOutputContractTests(unittest.TestCase):
    def test_valid_payload_passes_contract(self) -> None:
        payload = {
            "status": "partial",
            "missing_aspects": ["recent data"],
            "gap_types": ["insufficient_depth"],
            "search_directives": ["Find 2025 figures"],
            "confidence": 0.7,
            "reason": "Evidence lacks recent quantitative detail.",
        }
        self.assertTrue(semantic_sufficiency_payload_contract(payload))

    def test_invalid_status_fails_contract(self) -> None:
        payload = {
            "status": "maybe",
            "missing_aspects": [],
            "gap_types": [],
            "search_directives": [],
            "confidence": None,
            "reason": "Invalid.",
        }
        self.assertFalse(semantic_sufficiency_payload_contract(payload))


class HybridArchitectureTests(unittest.TestCase):
    def test_application_package_does_not_import_infrastructure(self) -> None:
        forbidden = ("infrastructure.", "agency.")
        violations: list[str] = []
        package_root = REPO_ROOT / "application" / "research_quality"
        for path in sorted(package_root.rglob("*.py")):
            if path.name == "__init__.py" or path.name.endswith("_factory.py"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                if module and any(
                    module == prefix.rstrip(".") or module.startswith(prefix)
                    for prefix in forbidden
                ):
                    violations.append(f"{path.name} -> {module}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
