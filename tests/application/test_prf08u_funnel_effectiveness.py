"""Provider-free bounded PRF-08T regressions using fictional topics/domains."""
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import Mock

from application.sources.query_temporal_intent import observation_window
from application.sources.query_opportunities import fingerprint, focus_repeated_queries
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.provider_query_projector import project_provider_query_text
from application.sources.deterministic_source_relevance import SourceRelevanceDecision, selection_sort_key
from application.evidence.temporal_scope import observation_eligibility
from domain.planning.research_design import ResearchDesign, ResearchQuestion, InformationNeed
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.research_brief import ResearchBrief
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from tests.application.research_quality.test_prf08c_research_integrity import _evidence


def design():
    return ResearchDesign(id='d', research_questions=(ResearchQuestion(id='RQ1', question='Water meter deployment counts'),),
        information_needs=(InformationNeed(id='IN1', research_question_id='RQ1',
            description='Dated deployment counts of water meters by region', geography='Canada',
            timeframe='Same period as the brief', evidence_expectation=EvidenceExpectation(
                nature=EvidenceNature.QUANTITATIVE, required_aspects=('regional_counts','measurement_basis'),
                requires_quantitative_evidence=True)),))


def brief():
    return ResearchBrief(title='Water meters', business_question='Meter counts', market='water meters',
        timeframe='1 January 2024 to 1 July 2025; sources available by 1 October 2025')


def request():
    return TargetedResearchRequest(workflow_run_id='r', research_design_id='d',
        research_question_id='RQ1', information_need_id='IN1', gap_types=(),
        missing_aspects=('regional_counts','measurement_basis'))


def dated(day='1 July 2025', *, period=None):
    text=f'As of {day}, there were 42 installed water meters.'
    return replace(_evidence('e','s',period,excerpt=text), statement=text)


class QueryTests(unittest.TestCase):
    def test_material_window_resolves_reference_without_publication_allowance(self):
        query=SearchQueryBuilder().build_queries(design(),brief=brief())[0]
        actual=query.provider_query_text or query.query_text
        self.assertIn('1 July 2025',actual)
        self.assertNotIn('October',actual)
        self.assertIn('Canada',actual)
        self.assertIn('water meters',actual.lower())

    def test_static_definition_not_forced_into_brief_window(self):
        need=replace(design().information_needs[0],description='Definition and methodology of meter categories',
                     timeframe='',evidence_expectation=EvidenceExpectation(nature=EvidenceNature.QUALITATIVE))
        self.assertEqual(observation_window(need,brief()),'')

    def test_long_material_period_cannot_silently_disappear(self):
        self.assertIsNone(project_provider_query_text(category_subject='water meters',geography='Canada',
            core_intent='Dated installations',timeframe='Observations from 1 January 2024 through 1 July 2025, excluding later measurements'))

    def test_repeated_query_uses_grounded_distinct_aspect_without_extra_slot(self):
        q=SearchQueryBuilder().build_queries(design(),brief=brief())[0]
        selected=focus_repeated_queries([q],design=design(),request=request(),history=[fingerprint(q)])
        self.assertEqual(len(selected),1)
        self.assertNotEqual(fingerprint(selected[0]),fingerprint(q))
        self.assertIn('"regional counts"',selected[0].provider_query_text)
        self.assertIn('1 July 2025',selected[0].provider_query_text)

    def test_exhausted_alternatives_do_not_dispatch_again(self):
        q=SearchQueryBuilder().build_queries(design(),brief=brief())[0]
        seen=[fingerprint(q)]
        for _ in range(2):
            result=focus_repeated_queries([q],design=design(),request=request(),history=seen)
            self.assertEqual(len(result),1)
            seen.append(fingerprint(result[0]))
        self.assertEqual(focus_repeated_queries([q],design=design(),request=request(),history=seen),[])

    def test_existing_localized_strategies_not_changed(self):
        q=SearchQueryBuilder().build_queries(design(),brief=brief())[0]
        self.assertEqual(focus_repeated_queries([q],design=design(),request=request(),history=[]),[q])


class SelectionTests(unittest.TestCase):
    def test_category_mismatch_cannot_claim_coverage_or_displace_aligned(self):
        import time
        from tests.application.sources.test_prf08g_coverage import _service,_OfflineRetriever,_pending
        from application.sources.source_acquisition_service import _CandidateGroup
        direct=SourceRelevanceDecision('direct','direct',2,1,1,'aligned','IN1',2,category_alignment='preserving')
        mismatch=replace(direct,category_alignment='not_preserving',reason='category_not_preserved')
        r=_OfflineRetriever();s=_service(r,cap=1)
        def group(url,d):return _CandidateGroup(url,[_pending('IN1',url)],d)
        outcome=s._acquire_candidates(project_id='p',workflow_run_id='r',research_design_id='d',design=design(),
            groups=[group('https://a.example/software',mismatch),group('https://z.example/meters',direct)],started_at=time.monotonic())
        self.assertEqual(r.fetched,['https://z.example/meters'])
        self.assertTrue(outcome[10])
        r2=_OfflineRetriever();s2=_service(r2,cap=1)
        outcome=s2._acquire_candidates(project_id='p',workflow_run_id='r',research_design_id='d',design=design(),
            groups=[group('https://a.example/software',mismatch)],started_at=time.monotonic())
        self.assertFalse(outcome[10])
        self.assertEqual(outcome[11],set())

    def test_zero_evidence_need_beats_better_covered_need_with_same_cap(self):
        from tests.application.sources.test_prf08g_coverage import _service,_acquire,_OfflineRetriever,_design
        r=_OfflineRetriever();s=_service(r,cap=1)
        s._evidence_repository=Mock()
        s._evidence_repository.list_for_project.return_value=[_evidence('e','s','2024',need='IN1')]
        result=_acquire(s,[('IN1','https://alpha.example/weak'),('IN2','https://beta.example/aligned')],design=_design(2))
        self.assertEqual(r.fetched,['https://beta.example/aligned'])
        self.assertEqual(result[4],1)

    def test_known_proxy_does_not_win_by_keyword_boost_or_domain(self):
        direct=SourceRelevanceDecision('direct','direct',2,1,1,'synthetic','IN1',2,expectation_boost=0)
        proxy=replace(direct,geo_alignment='proxy',expectation_boost=20,provider_rank=1)
        def key(d,u):return selection_sort_key(decision=d,need_coverage=1,best_rank=d.provider_rank,canonical_url=u)
        self.assertLess(key(direct,'https://z.example/data'),key(proxy,'https://a.example/data'))
        self.assertLess(key(direct,'https://a.example/data'),key(proxy,'https://z.example/data'))

    def test_valid_empty_deprioritized_before_second_empty_not_target_success(self):
        from application.evidence.evidence_extraction_scheduler import SourceOutcomeState,record_source_outcome,adaptive_depth_selection_key
        from tests.application.evidence.test_prf08p_content_identity import source,queue
        a,b=queue([source('a'),source('b','Other material')])
        empty=SourceOutcomeState('a');fresh=SourceOutcomeState('b')
        record_source_outcome(empty,phase='first_opportunity',persisted_evidence=0,valid_empty=True)
        self.assertEqual(empty.productive_calls,0)
        self.assertGreater(adaptive_depth_selection_key(a,state=empty,evidence_counts_by_need={}),
                           adaptive_depth_selection_key(b,state=fresh,evidence_counts_by_need={}))


class TemporalTests(unittest.TestCase):
    def test_explicit_period_unchanged(self):
        self.assertEqual(observation_eligibility(dated(period='1 July 2025'),date(2025,7,1)),'eligible')

    def test_grounded_canonical_as_of_qualifies_without_metadata(self):
        e=dated()
        self.assertEqual(observation_eligibility(e,date(2025,7,1)),'eligible')
        self.assertNotIn('observation_period',e.metadata)
        # Same canonical relation with geography between date and measurement,
        # mirroring the demonstrated shape without using historical records.
        e=replace(e,statement='As of 1 July 2025 in Canada, there were 42 installed water meters.')
        self.assertEqual(observation_eligibility(e,date(2025,7,1)),'eligible')

    def test_publication_alone_not_observation(self):
        e=replace(dated(),statement='Report published 1 July 2025',metadata={'published_at':'2025-07-01'})
        self.assertEqual(observation_eligibility(e,date(2025,7,1)),'unknown')

    def test_unrelated_date_not_promoted(self):
        e=replace(dated(),statement='There were 42 meters. A meeting took place on 1 July 2025.')
        self.assertEqual(observation_eligibility(e,date(2025,7,1)),'unknown')

    def test_post_cutoff_as_of_excluded(self):
        self.assertEqual(observation_eligibility(dated('2 July 2025'),date(2025,7,1)),'out_of_period')

    def test_unknown_and_mismatching_claim_remain_unknown(self):
        for e in (replace(dated(),source_excerpt='Unknown period'),replace(dated(),statement='As of 2 July 2025, there were 42 meters.')):
            self.assertEqual(observation_eligibility(e,date(2025,7,1)),'unknown')

    def test_explicit_conflicting_period_not_overridden(self):
        self.assertEqual(observation_eligibility(dated(period='2 July 2025'),date(2025,7,1)),'unknown')

    def test_publication_disguised_as_as_of_not_promoted(self):
        e=replace(dated(),statement='As of 1 July 2025, the report was published and recorded 42 meters.')
        self.assertEqual(observation_eligibility(e,date(2025,7,1)),'unknown')


class IntegratedTests(unittest.TestCase):
    def test_existing_partition_is_not_expanded(self):
        from tests.application.research_quality.test_prf08i_evidence_aware_continuation import _lowcost_budget
        from application.execution.budget_utils import EVIDENCE_PURPOSE_INITIAL,EVIDENCE_PURPOSE_REMEDIATION
        from application.execution.exceptions import BudgetExhaustedError
        budget=_lowcost_budget()
        for _ in range(6):
            budget.assert_can_call('evidence',purpose=EVIDENCE_PURPOSE_INITIAL)
            budget.record_llm_call('evidence',purpose=EVIDENCE_PURPOSE_INITIAL)
        with self.assertRaises(BudgetExhaustedError):budget.assert_can_call('evidence',purpose=EVIDENCE_PURPOSE_INITIAL)
        for _ in range(2):
            budget.assert_can_call('evidence',purpose=EVIDENCE_PURPOSE_REMEDIATION)
            budget.record_llm_call('evidence',purpose=EVIDENCE_PURPOSE_REMEDIATION)
        with self.assertRaises(BudgetExhaustedError):budget.assert_can_call('evidence',purpose=EVIDENCE_PURPOSE_REMEDIATION)

    def test_t_pattern_feedback_temporal_and_telemetry_parity(self):
        from tests.application.test_prf08s_funnel_telemetry import run_fixture
        from application import research_funnel_telemetry as funnel
        on,off=run_fixture(),run_fixture(False)
        self.assertEqual(on[4].calls,off[4].calls)
        self.assertEqual(on[5].calls,off[5].calls)
        self.assertEqual(on[3].to_dict(),off[3].to_dict())
        events=on[0].shared_state[funnel.KEY]['events']
        self.assertGreaterEqual(sum(e.get('status')=='valid_empty' for e in events),2)
        self.assertTrue(any(e['kind']=='candidate_decision' and not e['selected'] for e in events))
        q=SearchQueryBuilder().build_queries(design(),brief=brief())[0]
        next_queries=focus_repeated_queries([q],design=design(),request=request(),history=[fingerprint(q)])
        self.assertEqual(len(next_queries),1)
        self.assertNotEqual(fingerprint(next_queries[0]),fingerprint(q))
        # Feed the repeated-query recovery into bounded candidate selection:
        # a known mismatch for an already represented need competes with a
        # distinct aligned opportunity. Neither ordering nor domain is a score.
        import time
        from tests.application.sources.test_prf08g_coverage import _service,_OfflineRetriever,_pending
        from application.sources.source_acquisition_service import _CandidateGroup
        retrieval=_OfflineRetriever();acquisition=_service(retrieval,cap=1)
        acquisition._evidence_repository=on[6]
        good=SourceRelevanceDecision('direct','direct',2,1,1,'aligned','IN1',2,category_alignment='preserving')
        weak=replace(good,category_alignment='not_preserving')
        groups=[_CandidateGroup(url,[_pending('IN1',url)],decision) for url,decision in (
            ('https://a.example/unrelated',weak),('https://z.example/measurement',good))]
        selected=acquisition._acquire_candidates(project_id='project-1',workflow_run_id='run-1',research_design_id='d',
            design=design(),groups=groups,started_at=time.monotonic(),max_source_groups=len(next_queries))
        self.assertEqual(retrieval.fetched,['https://z.example/measurement'])
        self.assertEqual(selected[4],1)
        self.assertEqual(observation_eligibility(dated(),date(2025,7,1)),'eligible')
        self.assertFalse(on[3].ready_for_analysis)
