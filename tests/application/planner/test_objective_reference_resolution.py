from __future__ import annotations

from dataclasses import replace
from unittest import TestCase

from application.planner.objective_reference_resolution import (
    resolve_objective_reference_texts,
)
from application.sources.deterministic_source_relevance import build_relevance_context
from application.report.substantive_coverage import objective_tokens
from domain.common.exceptions import ValidationError
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief


class ObjectiveReferenceResolutionTests(TestCase):
    def _brief_and_design(self):
        brief = ResearchBrief("P", "Q", objectives=("Measure population",)).materialize_objective_registry()
        design = ResearchDesign(
            "d",
            (ResearchQuestion("rq", "What is the population?", objective_refs=("obj-001",)),),
            (InformationNeed("in", "rq", "Population"),),
            objective_reference_contract="objective_ids_v1",
            objective_registry_identity=brief.objective_registry_identity,
        )
        return brief, design

    def test_v2_id_resolves_to_exact_registry_text(self):
        brief, design = self._brief_and_design()
        self.assertEqual(
            resolve_objective_reference_texts(brief, design, ("obj-001",)),
            ("Measure population",),
        )
        context = build_relevance_context(design, design.information_needs[0], brief=brief)
        self.assertIn("population", context.rq_tokens)
        self.assertNotIn("obj", context.rq_tokens)

    def test_unknown_and_foreign_ids_fail_closed(self):
        brief, design = self._brief_and_design()
        with self.assertRaises(ValidationError):
            resolve_objective_reference_texts(brief, design, ("obj-999",))
        foreign = ResearchBrief("P", "Q", objectives=("Other",)).materialize_objective_registry()
        with self.assertRaises(ValidationError):
            resolve_objective_reference_texts(foreign, design, ("obj-001",))

    def test_v2_relevance_context_without_brief_fails_closed(self):
        _, design = self._brief_and_design()
        with self.assertRaises(ValidationError):
            build_relevance_context(design, design.information_needs[0])

    def test_legacy_relevance_context_without_brief_remains_supported(self):
        _, design = self._brief_and_design()
        legacy = replace(design, objective_reference_contract="legacy_text_v1")
        build_relevance_context(legacy, legacy.information_needs[0])

    def test_report_objective_tokens_resolve_v2_text_and_reject_missing_or_foreign_brief(self):
        brief, design = self._brief_and_design()
        tokens = objective_tokens(design.research_questions[0], design=design, brief=brief)
        self.assertIn("population", tokens)
        self.assertNotIn("obj", tokens)
        with self.assertRaises(ValidationError):
            objective_tokens(design.research_questions[0], design=design)
        foreign = ResearchBrief("P", "Q", objectives=("Other",)).materialize_objective_registry()
        with self.assertRaises(ValidationError):
            objective_tokens(design.research_questions[0], design=design, brief=foreign)

    def test_report_objective_tokens_keep_legacy_behavior(self):
        brief, design = self._brief_and_design()
        legacy = replace(design, objective_reference_contract="legacy_text_v1")
        self.assertTrue(objective_tokens(legacy.research_questions[0], design=legacy))

    def test_legacy_text_refs_remain_unchanged(self):
        brief, design = self._brief_and_design()
        legacy = replace(design, objective_reference_contract="legacy_text_v1")
        self.assertEqual(
            resolve_objective_reference_texts(brief, legacy, ("Historical objective",)),
            ("Historical objective",),
        )
