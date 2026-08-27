import tempfile
import unittest
from unittest.mock import Mock

from application.config import ApplicationConfig, ApplicationOverrides
from application.composition_root import create_application_container
from domain.quantitative.research_question_coverage import (
    DatasetOnlyResearchQuestionCoverageAbsence,
    QuantitativeAuthorityReference,
)
from infrastructure.persistence.memory.in_memory_project_repository import InMemoryProjectRepository
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.memory.in_memory_workflow_run_repository import InMemoryWorkflowRunRepository


class Q2126ProductionCurrentReconstructionBridgeTests(unittest.TestCase):
    def _container(self, root, projects, runs, quantitative):
        return create_application_container(
            config=ApplicationConfig(
                projects_root=root,
                persistence_backend="memory",
                deterministic_stage_executors=True,
                search_provider="deterministic",
            ),
            overrides=ApplicationOverrides(
                llm_client=Mock(),
                project_repository=projects,
                workflow_run_repository=runs,
                quantitative_state_repository=quantitative,
            ),
        )

    def _authority(self, container, identity, kind):
        value = DatasetOnlyResearchQuestionCoverageAbsence(
            identity, "p", "r", "BOUND", "", f"fp-{identity}",
        )
        container.quantitative_authority_finalization_service._state.persist(
            value, record_id=identity, project_id="p", run_id="r", accepted=True,
        )
        return QuantitativeAuthorityReference(kind, identity, f"fp-{identity}")

    def _manifest(self, container):
        refs = {
            name: self._authority(container, name, kind)
            for name, kind in (
                ("brief", "QZ_BRIEF"), ("qz", "QZ_DESIGN"),
                ("ra", "RA_QUESTIONNAIRE"), ("rb", "RB_RECONCILIATION"),
                ("rc", "RC_PLAN"), ("rd", "RD_MANIFEST"),
                ("re", "RE_LINEAGE"), ("rf", "RF_LINEAGE"),
                ("rg", "RG_LINEAGE"), ("rh", "RH_ASSESSMENT"),
                ("ri", "RI_OBJECTIVE"), ("dataset", "DATASET"),
                ("codebook", "CODEBOOK"), ("qc", "QC_APPROVAL"),
            )
        }
        chain = container.quantitative_authority_chain_service
        manifest = chain.create_manifest(
            project_id="p", run_id="r", source_brief=refs["brief"],
            research_design=refs["qz"], questionnaire=refs["ra"],
            reconciliation=refs["rb"], analysis_plan=refs["rc"],
            analysis_execution=(refs["rd"],), finding_authority=(refs["re"],),
            insight_authority=(refs["rf"],), report_authority=(refs["rg"],),
            research_question_authorities=(refs["rh"],),
            objective_authorities=(refs["ri"],), dataset=refs["dataset"],
            codebook=refs["codebook"], qc_authority=refs["qc"],
        )
        container.quantitative_authority_chain_selection_service.activate(
            project_id="p", run_id="r", manifest_id=manifest.manifest_id,
            created_at="t", created_by="tester",
        )
        return manifest

    def test_production_bridge_uses_rl_and_durable_rk_for_forward_and_backward(self):
        projects = InMemoryProjectRepository()
        runs = InMemoryWorkflowRunRepository()
        quantitative = InMemoryQuantitativeStateRepository()
        with tempfile.TemporaryDirectory() as root:
            first = self._container(root, projects, runs, quantitative)
            manifest = self._manifest(first)
            rl = first.quantitative_authority_finalization_service
            rl.resolve_current = Mock(return_value=object())

            forward = first.quantitative_authority_chain_service.reconstruct_forward(
                manifest_id=manifest.manifest_id, project_id="p", run_id="r",
            )
            backward = first.quantitative_authority_chain_service.reconstruct_backward(
                manifest_id=manifest.manifest_id, objective_authority_id="ri",
                project_id="p", run_id="r",
            )
            self.assertEqual(manifest.fingerprint, forward.manifest_fingerprint)
            self.assertEqual(forward, backward)
            self.assertEqual(2, rl.resolve_current.call_count)
            first.shutdown()

            second = self._container(root, projects, runs, quantitative)
            self.assertIsNot(first, second)
            second_rl = second.quantitative_authority_finalization_service
            second_rl.resolve_current = Mock(return_value=object())
            restarted = second.quantitative_authority_chain_service.reconstruct_forward(
                manifest_id=manifest.manifest_id, project_id="p", run_id="r",
            )
            self.assertEqual(forward, restarted)

            second_rl.resolve_current.side_effect = ValueError("stale QZ")
            with self.assertRaisesRegex(ValueError, "stale QZ"):
                second.quantitative_authority_chain_service.reconstruct_forward(
                    manifest_id=manifest.manifest_id, project_id="p", run_id="r",
                )
            with self.assertRaisesRegex(ValueError, "stale QZ"):
                second.quantitative_authority_chain_service.reconstruct_backward(
                    manifest_id=manifest.manifest_id, objective_authority_id="ri",
                    project_id="p", run_id="r",
                )
            historical = second.quantitative_authority_chain_service.resolve_exact(
                manifest_id=manifest.manifest_id, project_id="p", run_id="r",
            )
            self.assertEqual(forward, historical)
            second.shutdown()


if __name__ == "__main__":
    unittest.main()
