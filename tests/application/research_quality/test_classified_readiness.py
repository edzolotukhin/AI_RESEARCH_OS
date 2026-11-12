from dataclasses import replace
import unittest

from application.analysis.analysis_coverage_service import assess_analysis_coverage
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from application.research_quality.authoritative_outcome import derive_authoritative_outcome
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.planning.derivation import InformationNeedKind
from tests.application.analysis.test_executable_derivations import setup_memory, derived_design
from tests.application.evidence.test_structured_production import design as legacy_design


def readiness(context,evidence,sources):
    service=ResearchReadinessService(evaluator=DeterministicResearchSufficiencyEvaluator(),evidence_repository=evidence,source_repository=sources)
    return service,service.assess_and_apply(context)


def coverage(context,findings,evidence,sources):
    return assess_analysis_coverage(project_id=context.project.id,design=context.workflow_template.research_design_snapshot,
        findings=findings,evidence=evidence.list_for_project(context.project.id),brief=context.workflow_template.research_brief_snapshot,source_repository=sources)


class ClassifiedReadinessTests(unittest.TestCase):
    def test_output_only_question_is_deferred_without_blocking_analysis(self):
        from domain.planning.research_design import ResearchQuestion
        model = derived_design()
        model = replace(model, research_questions=(*model.research_questions, ResearchQuestion("rq-output", "Presentation")),
            information_needs=tuple(replace(n, research_question_id="rq-output") if n.kind == InformationNeedKind.OUTPUT else n
                for n in model.information_needs))
        context, _, _, evidence, sources, _ = setup_memory(model)
        _, result = readiness(context, evidence, sources)
        self.assertTrue(result.ready_for_analysis)
        self.assertNotIn("table", result.analysis_eligible_information_need_ids)

    def test_zero_denominator_only_blocks_percent_operations(self):
        context, _, _, evidence, sources, _ = setup_memory(series=((2019, 0), (2020, 950), (2021, 900)))
        _, result = readiness(context, evidence, sources)
        diagnostics = result.to_dict()["derived_prerequisites"]
        for need_id, diagnostic in diagnostics.items():
            self.assertEqual(diagnostic["status"], "not_ready" if "PERCENT" in need_id else "ready")
            if "PERCENT" in need_id:
                self.assertIn("zero_denominator", diagnostic["reasons"])

    def test_semantic_derivation_uses_validated_findings_and_lineage(self):
        from domain.planning.derivation import DerivationOperation
        context, analysis, findings, evidence, sources, provider = setup_memory(
            derived_design(operations=(DerivationOperation.TREND_CHARACTERIZATION,)))
        readiness(context, evidence, sources)
        analysis.analyze_for_context(context)
        rows = findings.list_for_project("project")
        self.assertTrue(coverage(context, rows, evidence, sources).fully_covered)
        derived = next(f for f in rows if f.metadata.get("derivation"))
        self.assertEqual(derived.metadata["derivation"]["validation_method"], "semantic-entailment-v1")
        forged = replace(derived, metadata={**derived.metadata, "derivation": {
            **derived.metadata["derivation"], "source_revision_lineage": []}})
        self.assertFalse(coverage(context, [f if f.id != derived.id else forged for f in rows], evidence, sources).fully_covered)

    def test_real_engine_gate_skips_downstream_for_missing_acquired_or_derived(self):
        from application.workflow_engine import WorkflowEngine
        from application.task_scheduler import TaskScheduler
        from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
        from domain.value_objects.task_status import TaskStatus
        from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
        from tests.helpers.workflow_run_builder import make_task, make_workflow_run

        for missing_kind in ("ACQUIRED", "DERIVED", None):
            context, analysis, findings, evidence, sources, _ = setup_memory()
            readiness(context, evidence, sources)
            analysis.analyze_for_context(context)
            rows = findings.list_for_project("project")
            missing_id = ("in-pop" if missing_kind == "ACQUIRED" else
                next(f.information_need_refs[0] for f in rows if f.metadata.get("derivation")))
            selected = InMemoryFindingRepository()
            for finding in rows:
                if missing_kind is None or missing_id not in finding.information_need_refs:
                    selected.create(finding)
            analyze = make_task("task-analyze", status=TaskStatus.COMPLETED)
            report = make_task("task-write-report", depends_on=["task-analyze"])
            review = make_task("task-review-report-1", depends_on=["task-write-report"])
            finalize = make_task("task-finalize-deliverables", depends_on=["task-review-report-1"])
            context.workflow_run = make_workflow_run(analyze, report, review, finalize, run_id="run")
            context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
            engine = WorkflowEngine(scheduler=TaskScheduler(), task_executor=None, completion_policy=None,
                finding_repository=selected, evidence_repository=evidence, source_repository=sources)
            engine._apply_post_analysis_outcome(context, analyze)
            if missing_kind is None:
                self.assertTrue(context.read_shared("analysis_coverage")["fully_covered"])
                self.assertTrue(all(t.status == TaskStatus.CREATED for t in (report, review, finalize)))
            else:
                self.assertIn(missing_id, context.read_shared("analysis_coverage")["missing_information_need_ids"])
                self.assertTrue(all(t.status == TaskStatus.SKIPPED for t in (report, review, finalize)))
                self.assertNotEqual(context.read_shared("research_product_outcome")["outcome"], "COMPLETED")

    def test_ready_without_derived_or_output_evidence_and_roundtrip(self):
        context,analysis,findings,evidence,sources,_=setup_memory()
        service,result=readiness(context,evidence,sources)
        self.assertTrue(result.ready_for_analysis,result.to_dict())
        self.assertTrue(result.analysis_ready)
        self.assertEqual(len(result.analysis_eligible_information_need_ids),5)
        self.assertNotIn("table",result.analysis_eligible_information_need_ids)
        self.assertTrue(all(n.evidence_count==0 for rq in result.research_question_assessments for n in rq.information_need_assessments if n.information_need_kind in {"DERIVED","OUTPUT"}))
        restored=ResearchReadinessResult.from_dict(result.to_dict())
        self.assertEqual(restored.to_dict(),result.to_dict())
        self.assertEqual(restored.to_dict()["output_obligations"][0]["verification_stage"],"report_finalization")
        self.assertFalse(restored.to_dict()["output_obligations"][0]["satisfied"])

    def test_acquired_without_evidence_not_ready(self):
        context,analysis,findings,evidence,sources,_=setup_memory(series=())
        _,result=readiness(context,evidence,sources)
        self.assertFalse(result.analysis_ready)
        self.assertIn("in-pop",result.blocking_information_need_ids)
        for diagnostic in result.to_dict()["derived_prerequisites"].values():
            self.assertIn("in-pop",diagnostic["missing_dependencies"])

    def test_missing_year_units_and_geography_are_not_ready(self):
        for arguments in (dict(series=((2019,1000),(2021,900))),dict(unit="thousands")):
            context,analysis,findings,evidence,sources,_=setup_memory(**arguments)
            _,result=readiness(context,evidence,sources)
            diagnostics=result.to_dict()["derived_prerequisites"]
            self.assertTrue(all(d["status"]=="not_ready" for d in diagnostics.values()))
            self.assertTrue(all(ref not in result.analysis_eligible_information_need_ids for ref in diagnostics))
        model=derived_design()
        model=replace(model,information_needs=tuple(replace(n,derivation=replace(n.derivation,geography="Poland")) if n.derivation else n for n in model.information_needs))
        context,analysis,findings,evidence,sources,_=setup_memory(model)
        _,result=readiness(context,evidence,sources)
        self.assertTrue(all("geography_mismatch" in d["reasons"] for d in result.to_dict()["derived_prerequisites"].values()))

    def test_analysis_coverage_and_authoritative_outcome(self):
        context,analysis,findings,evidence,sources,_=setup_memory()
        readiness(context,evidence,sources)
        summary=analysis.analyze_for_context(context)
        rows=findings.list_for_project("project",workflow_run_id="run")
        complete=coverage(context,rows,evidence,sources)
        self.assertTrue(complete.fully_covered,complete.to_dict())
        self.assertNotIn("table",complete.required_information_need_ids)
        model=context.workflow_template.research_design_snapshot
        def outcome(rows,assessment):
            return derive_authoritative_outcome(required_information_need_ids=(n.id for n in model.information_needs),
                readiness_payload=context.read_shared("research_readiness"),findings=rows,evidence=evidence.list_for_project("project"),project_id="project",workflow_run_id="run",research_design_id="design",coverage_missing_information_need_ids=assessment.missing_information_need_ids)
        self.assertEqual(outcome(rows,complete),("COMPLETED",()))
        removed=next(f for f in rows if f.metadata.get("derivation"))
        remaining=[f for f in rows if f.id!=removed.id]
        self.assertIn(removed.information_need_refs[0],coverage(context,remaining,evidence,sources).missing_information_need_ids)
        # A YoY IN has two Findings; remove all of that IN's results.
        missing_need=removed.information_need_refs[0]
        remaining=[f for f in rows if missing_need not in f.information_need_refs]
        incomplete=coverage(context,remaining,evidence,sources)
        self.assertIn(missing_need,incomplete.missing_information_need_ids)
        self.assertNotEqual(outcome(remaining,incomplete)[0],"COMPLETED")
        acquired_missing=[f for f in rows if "in-pop" not in f.information_need_refs]
        self.assertFalse(coverage(context,acquired_missing,evidence,sources).fully_covered)

    def test_tampered_or_unvalidated_derived_does_not_cover(self):
        context,analysis,findings,evidence,sources,_=setup_memory()
        readiness(context,evidence,sources)
        analysis.analyze_for_context(context)
        rows=findings.list_for_project("project")
        target=next(f for f in rows if f.metadata.get("derivation"))
        missing=target.information_need_refs[0]
        altered=replace(target,metadata={**target.metadata,"derivation":{**target.metadata["derivation"],"raw_result":"42"}})
        candidates=[f for f in rows if missing not in f.information_need_refs]+[altered]
        self.assertIn(missing,coverage(context,candidates,evidence,sources).missing_information_need_ids)
        candidates=[replace(f,metadata={}) if "in-pop" in f.information_need_refs else f for f in rows]
        self.assertIn("in-pop",coverage(context,candidates,evidence,sources).missing_information_need_ids)

    def test_legacy_design_readiness_unchanged(self):
        context,analysis,findings,evidence,sources,_=setup_memory(legacy_design())
        before=context.workflow_template.research_design_snapshot.to_dict()
        expected=DeterministicResearchSufficiencyEvaluator().evaluate(design=context.workflow_template.research_design_snapshot,evidence=evidence.list_for_project("project"))
        service=ResearchReadinessService(evaluator=DeterministicResearchSufficiencyEvaluator(),evidence_repository=evidence,source_repository=sources)
        result=service.evaluate_for_context(context)
        self.assertEqual(result.to_dict(),expected.to_dict())
        self.assertNotIn("classification_version",result.to_dict())
        self.assertEqual(context.workflow_template.research_design_snapshot.to_dict(),before)
