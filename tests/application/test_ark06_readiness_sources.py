"""Synthetic ARK-05 shape; no historical payloads or provider calls."""
from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch

from application.evidence.citation_integrity import citation_is_valid
from application.research_quality.research_readiness_service import (
    ResearchReadinessService, ReadinessSourceUnavailableError,
)
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from application.methods.desk.executor import VersionedDeskExecutor
from application.execution.execution_budget_context import execution_budget_scope
from application.execution.execution_budget_factory import create_execution_budget
from domain.planning.research_design import (
    EvidenceCoverageContract, InformationNeed, ResearchDesign, ResearchQuestion,
)
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_subject import (
    LexicalRepresentation, ResearchSubject, SubjectResolutionStatus,
)
from domain.research_brief import ResearchBrief
from tests.application.test_ark02_desk import fixture
from tests.application.test_ark02_kernel import Store
from tests.application.research_quality.test_prf08c_research_integrity import _evidence
from tests.application.research_quality.test_evidence_completeness_diagnostics import (
    evidence as structured_evidence,
    source as structured_source,
)
from tests.helpers.citation_fixtures import sources_for


def replay():
    cfg, ctx, sources, evidence, llm, adapter, overrides, client = fixture()
    subject = ResearchSubject(
        'population', 'Population', 'en', ('population',),
        (LexicalRepresentation(
            'population-en', 'en', 'Population', ('population',),
            ('population',), 'fixture', 'approved',
        ),),
        resolution_status=SubjectResolutionStatus.RESOLVED,
    )
    design = ResearchDesign('offline-design', research_questions=(ResearchQuestion('RQ1', 'Population counts'),),
        information_needs=tuple(InformationNeed(f'IN{i}', 'RQ1', 'Population counts',
            timeframe='1 January 2025 to 1 July 2026', geography='Ukraine',
            evidence_expectation=EvidenceExpectation(nature=EvidenceNature.QUANTITATIVE),
            evidence_coverage=EvidenceCoverageContract(
                required_periods=('Q1 2026',), required_metric='Population',
                required_unit='persons', geography='Ukraine',
            )) for i in range(1, 6)), research_subject=subject)
    ctx.workflow_template.research_design_snapshot = design
    ctx.workflow_template.research_brief_snapshot = ResearchBrief(
        'Synthetic population', 'How many people?',
        timeframe='1 January 2025 to 1 July 2026', geography=('Ukraine',),
    )
    rows = []
    for i in range(5):
        item_source = replace(
            structured_source(f's{i}', 'Q1 2026', workflow=ctx.workflow_run.id,
                              design=design.id, numeric='100'),
            project_id=ctx.project.id, url=f'https://fixture.test/s{i}.xlsx',
            canonical_url=f'https://fixture.test/s{i}.xlsx',
            raw_content_checksum=f'{i + 1:064x}',
        )
        sources.create(item_source)
        rows.append(replace(
            structured_evidence(
                item_source, 'Q1 2026', identifier=f'e{i}', needs=('IN1',),
                assignment_need='IN1', workflow=ctx.workflow_run.id, design=design.id,
                numeric='100', subject_id=subject.subject_id,
                subject_fingerprint=subject.semantic_fingerprint,
            ),
            project_id=ctx.project.id, research_question_refs=('RQ1',),
            deduplication_key=f'key{i}',
        ))
    unresolved = [replace(_evidence(f'e{i}', f's{i}', None),
                          project_id=ctx.project.id, workflow_run_id=ctx.workflow_run.id,
                          deduplication_key=f'key{i}') for i in range(5, 9)]
    sources_for(unresolved, sources)
    rows.extend(unresolved)
    for row in rows:
        evidence.create(row)
    evaluator = DeterministicResearchSufficiencyEvaluator()
    service = ResearchReadinessService(evaluator=evaluator, evidence_repository=evidence, source_repository=sources)
    return ctx, sources, rows, service


class ReadinessSourcesTests(TestCase):
    def test_nine_valid_five_qualifying_still_insufficient_and_final_reassessment(self):
        ctx, sources, rows, service = replay()
        self.assertTrue(all(citation_is_valid(e, sources.get_by_id(e.source_id)) for e in rows))
        with patch.object(service._evaluator, 'evaluate', wraps=service._evaluator.evaluate) as evaluate:
            result = service.evaluate_for_context(ctx)
        self.assertEqual(len(evaluate.call_args.kwargs['evidence']), 5)
        self.assertFalse(result.ready_for_analysis)
        final = service._finalize_terminal_readiness(ctx, result)
        self.assertFalse(final.ready_for_analysis)
        counts = {n.information_need_id:n.terminal_evidence_count for rq in final.research_question_assessments for n in rq.information_need_assessments}
        self.assertEqual(counts, {'IN1':5, 'IN2':0, 'IN3':0, 'IN4':0, 'IN5':0})
        with patch.object(service._evaluator, 'evaluate', wraps=service._evaluator.evaluate) as evaluate:
            service.evaluate_for_context(ctx)
        self.assertEqual(len(evaluate.call_args.kwargs['evidence']), 5)

    def test_missing_dependency_is_operational_not_insufficiency(self):
        ctx, _, _, service = replay()
        service._source_repository = None
        for call in (lambda:service.assess_and_apply(ctx), lambda:service._missing_readiness_fallback(ctx)):
            with self.assertRaisesRegex(ReadinessSourceUnavailableError, 'readiness_source_repository_unavailable'):
                call()
        self.assertNotIn('research_readiness', ctx.shared_state)

    def test_backend_failure_propagates_without_refusal(self):
        ctx, sources, _, service = replay()
        with patch.object(sources, 'get_by_id', side_effect=RuntimeError('offline source storage unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'source storage unavailable'):
                service.assess_and_apply(ctx)
        self.assertNotIn('research_readiness', ctx.shared_state)

    def test_final_readiness_missing_dependency_is_explicit(self):
        ctx, _, _, service = replay()
        candidate = service.evaluate_for_context(ctx)
        service._source_repository = None
        with self.assertRaises(ReadinessSourceUnavailableError):
            service._finalize_terminal_readiness(ctx, candidate)

    def test_missing_dependency_even_empty_is_not_genuine_insufficiency(self):
        cfg, ctx, sources, evidence, _, adapter, _, _ = fixture()
        adapter.readiness._source_repository = None
        with self.assertRaises(ReadinessSourceUnavailableError):
            adapter.readiness.evaluate_for_context(ctx)

    def test_invalid_and_unresolvable_never_qualify(self):
        ctx, sources, rows, service = replay()
        rows[0].source_locator['normalized_start'] = -1
        original = sources.get_by_id
        with patch.object(sources, 'get_by_id', side_effect=lambda sid: None if sid == rows[1].source_id else original(sid)), patch.object(service._evaluator, 'evaluate', wraps=service._evaluator.evaluate) as evaluate:
            result = service.evaluate_for_context(ctx)
        self.assertEqual(len(evaluate.call_args.kwargs['evidence']), 3)
        self.assertFalse(result.ready_for_analysis)

    def test_production_executor_and_resume_inject_identical_source_repository(self):
        cfg, ctx, sources, evidence, _, _, overrides, client = fixture()
        store = Store()
        for _ in range(2):
            with patch('application.methods.desk.executor.ResearchReadinessService', wraps=ResearchReadinessService) as constructor:
                executor = VersionedDeskExecutor(None, 'search', config=cfg, overrides=overrides,
                    sources=sources, evidence=evidence, llm_client=client, store_factory=lambda c:store)
                with execution_budget_scope(create_execution_budget(cfg)):
                    executor.run(ctx)
                self.assertIs(constructor.call_args.kwargs['source_repository'], sources)
        self.assertEqual(store.load().used['extractions'], 8)
