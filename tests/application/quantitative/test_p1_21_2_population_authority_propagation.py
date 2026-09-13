from __future__ import annotations

import unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

from application.quantitative.finding_lineage import QuantitativeFindingLineageError, QuantitativeFindingLineageService
from application.quantitative.vertical_service import RealQuantitativeStageService
from domain.quantitative.analysis_execution import AnalysisExecutionManifestStatus, AnalysisItemExecutionStatus, QuantitativeAnalysisExecutionMode
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative import test_p1_21_1_canonical_population_builder as p1211
from tests.application.quantitative import test_property_re_finding_lineage as re_tests


POPULATION = "qualified respondents within the canonical analytical base"


class P1212PopulationAuthorityPropagationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = re_tests.PropertyREFindingLineageTests(methodName="runTest")
        self.fixture.setUp()

    def vertical(self, population=POPULATION):
        projection = replace(
            self.fixture.projection,
            planned_analyses=tuple(
                replace(item, population_description=population)
                for item in self.fixture.projection.planned_analyses
            ),
        )
        generator = re_tests.RecordingFindingGenerator()
        vertical = self.fixture._vertical(generator)
        vertical.analysis_execution_projection = projection
        return vertical, generator

    def test_initial_vertical_qi_build_propagates_population(self):
        vertical, generator = self.vertical()
        updated = vertical._quant_findings(
            self.fixture.project, self.fixture.run, self.fixture._safe_state()
        )
        authority = self.fixture.repository.get_input_authority(
            updated["finding_input_authority_record_id"], project_id=self.fixture.project
        )
        contexts = tuple(
            item.semantic_evidence_context
            for item in authority.analysis_entries
            if item.semantic_evidence_context is not None
        )
        self.assertTrue(contexts)
        self.assertTrue(all(item.population_description == POPULATION for item in contexts))
        self.assertEqual(generator.calls, 1)

    def test_three_build_paths_have_identical_context_fingerprints(self):
        vertical, _ = self.vertical()
        mapping = vertical._population_descriptions(
            project_id=self.fixture.project, manifest=self.fixture.manifest
        )
        builds = tuple(
            self.fixture.lineage.build_input_authority(
                project_id=self.fixture.project,
                run_id=self.fixture.run,
                manifest=self.fixture.manifest,
                projection=vertical.analysis_execution_projection,
                dataset=self.fixture.dataset,
                codebook=self.fixture.codebook,
                population_descriptions=mapping,
            )
            for _ in range(3)
        )
        fingerprints = tuple(
            tuple(
                item.semantic_evidence_context.fingerprint
                for item in authority.analysis_entries
                if item.semantic_evidence_context is not None
            )
            for authority in builds
        )
        self.assertEqual(fingerprints[0], fingerprints[1])
        self.assertEqual(fingerprints[1], fingerprints[2])

    def test_none_preserves_historical_behavior(self):
        vertical, _ = self.vertical(None)
        self.assertEqual(
            vertical._population_descriptions(
                project_id=self.fixture.project, manifest=self.fixture.manifest
            ),
            {},
        )

    def test_invalid_population_forms_fail_closed(self):
        for value in (" bad ", 7, "x" * 1001):
            with self.subTest(value=repr(value)[:20]):
                vertical, _ = self.vertical(value)
                mapping = vertical._population_descriptions(
                    project_id=self.fixture.project, manifest=self.fixture.manifest
                )
                with self.assertRaisesRegex(
                    QuantitativeFindingLineageError, "bounded validated text"
                ):
                    self.fixture.lineage.build_input_authority(
                        project_id=self.fixture.project,
                        run_id=self.fixture.run,
                        manifest=self.fixture.manifest,
                        projection=vertical.analysis_execution_projection,
                        dataset=self.fixture.dataset,
                        codebook=self.fixture.codebook,
                        population_descriptions=mapping,
                    )

    def test_unknown_result_population_fails_closed(self):
        with self.assertRaisesRegex(
            QuantitativeFindingLineageError, "unavailable StatisticalResult"
        ):
            self.fixture.authority(population_descriptions={"unknown-result": POPULATION})

    def test_production_contains_no_study_specific_identifiers(self):
        paths = (
            "application/quantitative/vertical_service.py",
            "application/quantitative/finding_lineage.py",
            "application/quantitative/analysis_planning.py",
            "domain/quantitative/analysis_plan.py",
        )
        for path in paths:
            text = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("ATTITUDE_799", text)
            self.assertNotIn("SL73R5", text)
            self.assertNotIn("study-3", text.casefold())


if __name__ == "__main__":
    unittest.main()
class _BoundaryCaptured(RuntimeError): pass
class _State:
    def __init__(self, values): self.values=values
    def load(self, record_id, **_): return self.values[record_id]
class _ExecutionRepository:
    def __init__(self, manifest, coverage, outcomes): self.manifest,self.coverage,self.outcomes=manifest,coverage,outcomes
    def get_manifest(self,*_,**__): return self.manifest
    def get_coverage(self,*_,**__): return self.coverage
    def get_analysis_outcome(self,outcome_id,**_): return self.outcomes[outcome_id]
class _CapturingLineage:
    def __init__(self, inner): self.inner,self.captured,self.repository=inner,None,SimpleNamespace()
    def build_input_authority(self,**kwargs):
        self.captured=self.inner.build_input_authority(**kwargs)
        raise _BoundaryCaptured

class P1212Study3ProductionBoundaryTests(unittest.TestCase):
    EXPECTED=(
        "09b8240d39e940c074fe127b939669a3c6b805faedd774767b63112141ef8fa2",
        "27ec5a383ab16c81681b206351a3957f1c1c980d3b86f7288468f07edb426d29",
        "a3137e6c7c5895dc98a0f1dd9c6759b13ce774f2e6b495b76b89c0d38719e7cb",
        "f8e0f5e3306d281fd3e00f377fb90fc4f0570a1ece1eaf917fac5f3694cca51e",
        "b8dcc5ed16c3b9da87623f82458307c32965ae679003e1aff6bdbc1bd109f568")
    def setUp(self):
        source=p1211.P1211CanonicalPopulationBuilderTests(methodName="runTest"); source.setUp()
        self.results=tuple(source.authority(i) for i in range(5)); self.codebook=source.codebook
        self.project="study-3-r3"; self.run="study-3-r3-run"
        self.dataset=SimpleNamespace(version_id="study-3-version",dataset_fingerprint="study-3-dataset-fp",data_fingerprint="study-3-data-fp",schema_fingerprint="study-3-schema-fp")
        planned=[]; outcomes=[]
        for i,result in enumerate(self.results):
            aid=f"a{i+1}"; pid=f"planned-{aid}"
            planned.append(SimpleNamespace(planned_analysis_id=pid,specification=SimpleNamespace(specification_id=f"spec-{aid}"),specification_fingerprint=f"spec-fp-{aid}",objective_ids=("objective",),research_question_ids=("rq",),analytical_requirement_ids=("ATTITUDE",),obligation="MANDATORY",assumptions=(),limitations=(),population_description=p1211.POPULATION))
            artifact=SimpleNamespace(artifact_type="STATISTICAL_RESULT",record_id=result.result_id,authority_fingerprint=result.reproducibility_fingerprint)
            outcomes.append(SimpleNamespace(outcome_id=f"outcome-{aid}",project_id=self.project,run_id=self.run,planned_analysis_id=pid,plan_fingerprint="study-3-plan-fp",status=AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS,artifacts=(artifact,),limitations=(),fingerprint=f"outcome-fp-{aid}"))
        self.projection=SimpleNamespace(plan_id="study-3-plan",plan_version_id="study-3-plan-version",plan_fingerprint="study-3-plan-fp",quality_assessment_fingerprint="study-3-quality-fp",planned_analyses=tuple(planned),planned_comparisons=())
        coverage=SimpleNamespace(coverage_id="coverage",fingerprint="coverage-fp")
        self.manifest=SimpleNamespace(manifest_id="study-3-manifest",fingerprint="study-3-manifest-fp",project_id=self.project,run_id=self.run,execution_mode=QuantitativeAnalysisExecutionMode.DESIGN_AWARE_EXECUTION,status=AnalysisExecutionManifestStatus.COMPLETED,plan_id=self.projection.plan_id,plan_version_id=self.projection.plan_version_id,plan_fingerprint=self.projection.plan_fingerprint,dataset_version_id=self.dataset.version_id,dataset_fingerprint=self.dataset.dataset_fingerprint,data_fingerprint=self.dataset.data_fingerprint,schema_fingerprint=self.dataset.schema_fingerprint,codebook_version_id=self.codebook.codebook_version_id,codebook_fingerprint=self.codebook.fingerprint,quality_assessment_fingerprint=self.projection.quality_assessment_fingerprint,analysis_outcome_ids=tuple(x.outcome_id for x in outcomes),comparison_outcome_ids=(),coverage_manifest_id=coverage.coverage_id,coverage_manifest_fingerprint=coverage.fingerprint,limitations=())
        repo=_ExecutionRepository(self.manifest,coverage,{x.outcome_id:x for x in outcomes})
        values={x.result_id:x for x in self.results}; values.update(dataset=self.dataset,codebook=self.codebook,manifest=self.manifest)
        for name in ("re-input","re-manifest","re-coverage","rf-input","rf-manifest","rf-coverage"): values[name]=object()
        self.state=_State(values); self.execution=SimpleNamespace(repository=repo)
        self.inner=QuantitativeFindingLineageService(repository=None,analysis_execution_repository=repo,state_service=self.state,digest_provider=Sha256DigestProvider())
    def capture(self,stage):
        lineage=_CapturingLineage(self.inner); vertical=RealQuantitativeStageService.__new__(RealQuantitativeStageService)
        vertical.analysis_execution_projection=self.projection; vertical.analysis_execution_service=self.execution; vertical.finding_lineage=lineage; vertical.insight_lineage=object(); vertical.report_lineage=object(); vertical.state=self.state
        state={"analysis_execution_mode":"DESIGN_AWARE_EXECUTION","analysis_execution_manifest_record_id":"manifest","dataset_record_id":"dataset","codebook_record_id":"codebook","finding_input_authority_record_id":"re-input","finding_lineage_manifest_record_id":"re-manifest","finding_coverage_manifest_record_id":"re-coverage","insight_input_authority_record_id":"rf-input","insight_lineage_manifest_record_id":"rf-manifest","insight_coverage_manifest_record_id":"rf-coverage"}
        with self.assertRaises(_BoundaryCaptured):
            if stage=="initial": vertical._quant_findings(self.project,self.run,state)
            elif stage=="rebuild1": vertical._design_aware_insights(self.project,self.run,state,object())
            else: vertical._design_aware_report(self.project,self.run,state,object(),object())
        return lineage.captured
    def test_five_authorities_survive_initial_and_two_rebuilds(self):
        observed=[]
        for stage in ("initial","rebuild1","rebuild2"):
            authority=self.capture(stage); contexts={x.result_id:x.semantic_evidence_context for x in authority.analysis_entries}
            self.assertTrue(all(contexts[x.result_id].population_description==p1211.POPULATION for x in self.results))
            observed.append(tuple(contexts[x.result_id].fingerprint for x in self.results))
        self.assertEqual(observed,[self.EXPECTED,self.EXPECTED,self.EXPECTED])