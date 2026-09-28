"""Nonempty canonical Evidence parity across CMF readiness and analysis."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from application.methods.catalog import production_methods
from application.methods.executor import MethodExecutor
from application.evidence.temporal_scope import qualifying_evidence
from application.analysis.analysis_service import AnalysisService
from application.executors.analysis_executor import AnalysisExecutor
from infrastructure.analysis.deterministic_analysis_engine import DeterministicAnalysisEngine
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from tests.application.test_ark06_readiness_sources import replay
from tests.application.test_cmf02 import pin_context


class BoundaryParityTests(TestCase):
    def test_nonempty_readiness_qualification_equal_and_invalid_cannot_qualify(self):
        ctx, sources, rows, readiness = replay()
        pin_context(None, ctx)
        before = deepcopy([r.to_dict() for r in rows])
        result = readiness.evaluate_for_context(ctx)
        routed = MethodExecutor("research_quality",
            SimpleNamespace(run=readiness.evaluate_for_context), production_methods()).run(ctx)
        self.assertEqual(result.to_dict(), routed.to_dict())
        self.assertEqual(before, [r.to_dict() for r in rows])
        sources._sources.clear()
        self.assertEqual(qualifying_evidence(design=ctx.workflow_template.research_design_snapshot,
            evidence=rows, brief=ctx.workflow_template.research_brief_snapshot, source_repository=sources), ())

    def test_analysis_reads_persisted_snapshot_preserves_evidence_and_separates_findings(self):
        summaries = []
        for migrated in (False, True):
            ctx, sources, rows, readiness = replay()
            if migrated: pin_context(None, ctx)
            repo = readiness._evidence_repository
            before = deepcopy([r.to_dict() for r in repo.list_for_project(ctx.project.id)])
            findings, insights = InMemoryFindingRepository(), InMemoryInsightRepository()
            engine = DeterministicAnalysisEngine()
            service = AnalysisService(analysis_engine=engine, evidence_repository=repo,
                finding_repository=findings, insight_repository=insights, source_repository=sources,
                max_evidence_per_batch=20, max_chars_per_batch=50000)
            executor = AnalysisExecutor(analysis_service=service)
            with patch.object(engine, "analyze_findings", wraps=engine.analyze_findings) as calls:
                MethodExecutor("analysis", executor, production_methods()).run(ctx)
            actual = calls.call_args.args[0]
            self.assertEqual(len(actual.evidence_batch), 5)
            self.assertTrue(all(item.id in {r.id for r in rows} for item in actual.evidence_batch))
            self.assertEqual(before, [r.to_dict() for r in repo.list_for_project(ctx.project.id)])
            fs = findings.list_for_project(ctx.project.id)
            ins = insights.list_for_project(ctx.project.id)
            self.assertTrue(fs)
            self.assertTrue(ins)
            self.assertTrue(set(ins[0].finding_refs).issubset({f.id for f in fs}))
            self.assertTrue(set(fs[0].evidence_refs).issubset({r.id for r in rows}))
            summaries.append((tuple(item.id for item in actual.evidence_batch),
                              fs[0].statement, ins[0].statement))
        self.assertEqual(summaries[0], summaries[1])
