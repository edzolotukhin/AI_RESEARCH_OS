"""Offline interval and unrelated-topic reproductions on fictional research."""
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import Mock
from tests.helpers.citation_fixtures import sources_for

from application.evidence.temporal_scope import observation_interval, qualifying_evidence
from application.evidence.provenance_validation import validate_candidate_provenance, InvalidProvenanceError
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from domain.planning.research_design import ResearchDesign, ResearchQuestion, InformationNeed
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.research_brief import ResearchBrief
from tests.application.research_quality.test_prf08c_research_integrity import _evidence
from tests.application.evidence.test_prf08p_content_identity import source
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator


def design():
    return ResearchDesign(id='design-1', research_questions=(
        ResearchQuestion(id='rq-1', question='What are the water meter counts?'),
        ResearchQuestion(id='rq-2', question='Which pump definitions are comparable?')),
        information_needs=(
            InformationNeed(id='in-1', research_question_id='rq-1', description='Water meter counts',
                evidence_expectation=EvidenceExpectation(nature=EvidenceNature.QUANTITATIVE)),
            InformationNeed(id='in-2', research_question_id='rq-2', description='Definitions of pump categories and comparability limitations',
                evidence_expectation=EvidenceExpectation(nature=EvidenceNature.QUALITATIVE))))


def candidate(text, refs=('in-1',)):
    return EvidenceCandidate(statement=text, source_excerpt=text,
        evidence_type='direct_excerpt', information_need_refs=refs, research_question_refs=())


def validate(item):
    return validate_candidate_provenance(item, design=design(), run_context=RunScopedSourceContext(
        workflow_run_id='run-1', research_design_id='design-1', information_need_ids=('in-1','in-2'),
        research_question_ids=('rq-1','rq-2'), query_ids=(), target_information_need_id='in-1'))


class TemporalTests(unittest.TestCase):
    def qualified(self, period, *, excerpt=None, timeframe='1 January 2025 to 1 July 2026'):
        fact = _evidence('e','s',period,excerpt=excerpt,need='in-1')
        return qualifying_evidence(design=design(), evidence=(fact,),
            source_repository=sources_for((fact,)),
            brief=ResearchBrief(title='Meters',business_question='Meter counts',timeframe=timeframe))

    def test_pre_window_year_does_not_qualify(self):
        self.assertFalse(self.qualified('2024'))

    def test_quarter_notations_normalize_deterministically(self):
        for text in ('Q1 2026','2026 Q1','first quarter of 2026','First quarter 2026'):
            with self.subTest(text=text):
                self.assertEqual(observation_interval(text),(date(2026,1,1),date(2026,3,31)))

    def test_grounded_textual_quarter_qualifies(self):
        self.assertTrue(self.qualified('first quarter of 2026'))

    def test_grounded_canonical_quarter_qualifies(self):
        self.assertTrue(self.qualified('Q1 2026'))

    def test_post_cutoff_quarter_is_excluded(self):
        self.assertFalse(self.qualified('Q3 2026'))

    def test_overlapping_year_not_partially_qualified(self):
        self.assertFalse(self.qualified('2026'))
        self.assertTrue(self.qualified('2025'))

    def test_publication_date_not_an_observation(self):
        self.assertFalse(self.qualified(None,excerpt='Published 1 April 2026. Meter values are unavailable.'))

    def test_arbitrary_date_in_metadata_prose_not_mined(self):
        self.assertFalse(self.qualified('Discusses a conference in 2025'))

    def test_unknown_is_conservative(self):
        self.assertFalse(self.qualified(None))

    def test_exact_and_month_dates_supported(self):
        for p in ('2026-04-01','1 April 2026','April 2026'):
            self.assertTrue(self.qualified(p))

    def test_invalid_date_not_downgraded_to_month(self):
        self.assertIsNone(observation_interval('30 February 2025'))
        self.assertIsNone(observation_interval('2025-02-30'))
        self.assertIsNone(observation_interval('2025-13-01'))

    def test_explicit_period_cannot_be_publication_only(self):
        self.assertFalse(self.qualified('1 April 2026',excerpt='Published on 1 April 2026. Meter values are unavailable.'))

    def test_reversed_and_ambiguous_ranges_unknown(self):
        self.assertIsNone(observation_interval('Q2 2026 to Q1 2025'))
        self.assertIsNone(observation_interval('2025 or 2026'))

    def test_mixed_precision_range_preserves_order(self):
        self.assertEqual(observation_interval('Q1 2025 to 1 July 2026'),
                         (date(2025,1,1),date(2026,7,1)))

    def test_explicit_year_boundary_is_bounded(self):
        self.assertTrue(self.qualified('2025',timeframe='2025'))
        self.assertFalse(self.qualified('2024',timeframe='2025'))


class RelevanceTests(unittest.TestCase):
    def test_generic_task_language_is_not_a_subject_constraint(self):
        from application.evidence.relevance_validation import relevant_need_refs
        d=design()
        d=replace(d, information_needs=(replace(d.information_needs[0],
            description='Desk research sources relevant to the linked objective.'),))
        self.assertEqual(relevant_need_refs(candidate('A grounded synthetic fact.'),design=d),('in-1',))

    def test_relevant_target_survives(self):
        self.assertEqual(validate(candidate('Water meters numbered 42.')).information_need_refs,('in-1',))

    def test_legitimate_cross_need_retains_correct_rq(self):
        result=validate(candidate('Pump categories differ.',('in-2',)))
        self.assertEqual(result.information_need_refs,('in-2',))
        self.assertEqual(result.research_question_refs,('rq-2',))

    def test_incorrect_ref_removed_without_discarding_cross_need(self):
        result=validate(candidate('Pump categories differ.',('in-1','in-2')))
        self.assertEqual(result.information_need_refs,('in-2',))

    def test_unrelated_topic_with_shared_method_words_rejected(self):
        with self.assertRaisesRegex(InvalidProvenanceError,'subject relevance'):
            validate(candidate('Collectible certificates have different definitions and comparability limitations.',('in-2',)))

    def test_subject_in_statement_cannot_launder_unrelated_excerpt(self):
        item=replace(candidate('Water meter counts.'),source_excerpt='Collectible certificates are valuable.')
        with self.assertRaises(InvalidProvenanceError):
            validate(item)

    def test_metadata_cannot_self_certify_relevance(self):
        item=replace(candidate('Collectible certificates are valuable.'),metadata={'relevant':True,'subject':'water meters'})
        with self.assertRaises(InvalidProvenanceError):
            validate(item)

    def fixture(self, enabled):
        from tests.application.evidence.test_prf08p_content_identity import ContentIdentityTests
        _, context, repo, _ = ContentIdentityTests().setup_service()
        context.workflow_template.research_design_snapshot=design()
        context.execution_metadata['research_funnel_enabled']=enabled
        from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
        sources=InMemorySourceRepository()
        text='Collectible certificates have different definitions and comparability limitations.'
        s=replace(source(text=text),information_need_refs=('in-2',),research_question_refs=('rq-2',),
            metadata={'discovery_records':[{'workflow_run_id':'run-1','research_design_id':'design-1','query_id':'sq-in-2'}]})
        sources.create(s)
        extractor=Mock()
        extractor.extract.return_value=[candidate(text,('in-2',))]
        service=EvidenceExtractionService(evidence_extractor=extractor,source_repository=sources,evidence_repository=repo)
        result=service.extract_for_source_ids(context,(s.id,),allow_empty=True)
        readiness=ResearchReadinessService(evaluator=DeterministicResearchSufficiencyEvaluator(),evidence_repository=repo).evaluate_for_context(context)
        return result,readiness,repo,context,extractor

    def test_unrelated_rejected_before_storage_coverage_and_readiness(self):
        result,readiness,repo,context,extractor=self.fixture(True)
        self.assertEqual(result.evidence_extracted,0)
        self.assertFalse(repo.list_for_project('project-1',workflow_run_id='run-1'))
        self.assertFalse(readiness.ready_for_analysis)
        self.assertEqual(extractor.extract.call_count,1)
        self.assertEqual(result.diagnostics.work_items[0].candidate_outcomes[0].rejection_reason,'relevance')

    def test_telemetry_is_observational(self):
        on=self.fixture(True); off=self.fixture(False)
        self.assertEqual(on[0].evidence_extracted,off[0].evidence_extracted)
        self.assertEqual(on[1].ready_for_analysis,off[1].ready_for_analysis)
        self.assertEqual(on[4].extract.call_count,off[4].extract.call_count)
