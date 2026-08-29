import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace as NS

from application.quantitative.authority_chain import QuantitativeAuthorityChainService
from application.quantitative.authority_chain_selection import QuantitativeAuthorityChainSelectionService
from application.quantitative.authority_finalization import (
    QuantitativeAuthorityFinalizationError,
    QuantitativeAuthorityFinalizationInput,
    QuantitativeAuthorityFinalizationService,
)
from application.quantitative.workflow import QUANTITATIVE_SAFE_STATE_KEY
from application.quantitative.state_persistence import QuantitativeStateService
from domain.quantitative.research_question_coverage import DatasetOnlyResearchQuestionCoverageAbsence, QuantitativeAuthorityReference
from domain.quantitative.workflow import QuantitativeTerminalOutcome, QuantitativeTerminalResult
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_authority_chain_repository import QLQuantitativeAuthorityChainRepository
from infrastructure.persistence.quantitative_authority_chain_selection_repository import QLQuantitativeAuthorityChainSelectionRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


class PropertyRLTests(unittest.TestCase):
    def setUp(self):
        self.backing = InMemoryQuantitativeStateRepository()
        self.digest = Sha256DigestProvider()
        self.state = QuantitativeStateService(repository=self.backing, digest_provider=self.digest)
        self.chain_repo = QLQuantitativeAuthorityChainRepository(self.state)
        self.selection_repo = QLQuantitativeAuthorityChainSelectionRepository(self.state)
        self.chain = QuantitativeAuthorityChainService(
            repository=self.chain_repo, digest_provider=self.digest,
            authority_loaders={"*": self._load},
        )
        self.selection = QuantitativeAuthorityChainSelectionService(
            repository=self.selection_repo, authority_chain_service=self.chain,
            digest_provider=self.digest,
        )
        self.project = NS(id="p")
        self.run = NS(id="r", project_id="p", status=WorkflowStatus.COMPLETED)
        self.projects = NS(get_project=lambda project_id: self.project if project_id == "p" else (_ for _ in ()).throw(ValueError("missing project")))
        self.workflow_results = {QUANTITATIVE_SAFE_STATE_KEY: {}}
        self.workflows = NS(
            get_workflow_run=lambda run_id: self.run if run_id == "r" else (_ for _ in ()).throw(ValueError("missing run")),
            get_task_results=lambda run_id: dict(self.workflow_results) if run_id == "r" else (_ for _ in ()).throw(ValueError("missing run")),
        )
        self.current_ids = {"qz": "qz", "ra": "ra", "rb": "rb", "rc": "rc"}
        self.service = self._service()
        self.refs = {name: self._ref(kind, name) for name, kind in (
            ("brief", "QZ_BRIEF"), ("qz", "QZ_DESIGN"),
            ("ra", "RA_QUESTIONNAIRE"), ("rb", "RB_RECONCILIATION"),
            ("rc", "RC_PLAN"), ("rd", "RD_MANIFEST"),
            ("re", "RE_LINEAGE"), ("rf", "RF_LINEAGE"),
            ("rg", "RG_LINEAGE"), ("rh", "RH_ASSESSMENT"),
            ("ri", "RI_OBJECTIVE"), ("dataset", "DATASET"),
            ("codebook", "CODEBOOK"), ("qc", "QC_APPROVAL"),
            ("weight", "WEIGHT_SET"), ("no_report", "RG_CONTROLLED_ABSENCE"),
        )}
        self.terminal_record_id = "terminal-record"
        self.terminal = self._terminal()

    def _service(self):
        return QuantitativeAuthorityFinalizationService(
            project_service=self.projects, workflow_service=self.workflows,
            state_service=self.state, authority_chain_service=self.chain,
            authority_chain_selection_service=self.selection,
            research_design_service=NS(resolve_current_approved=lambda **_: self._load(self.current_ids["qz"], project_id="p")),
            questionnaire_service=NS(resolve_current_approved=lambda **_: self._load(self.current_ids["ra"], project_id="p")),
            reconciliation_service=NS(resolve_current_accepted=lambda **_: self._load(self.current_ids["rb"], project_id="p")),
            analysis_plan_service=NS(resolve_current_approved=lambda **_: self._load(self.current_ids["rc"], project_id="p")),
            research_question_coverage_service=NS(resolve_current_approved=lambda **_: None),
            objective_coverage_service=NS(get_approved_projection=lambda **_: None),
            digest_provider=self.digest,
        )

    def _load(self, record_id, *, project_id):
        try:
            return self.state.load(record_id, project_id=project_id)
        except ValueError:
            return None

    def _ref(self, kind, identity):
        fingerprint = f"fp-{identity}"
        value = DatasetOnlyResearchQuestionCoverageAbsence(identity, "p", "r", "BOUND", "", fingerprint)
        self.state.persist(value, record_id=identity, project_id="p", run_id="r", accepted=True)
        return QuantitativeAuthorityReference(kind, identity, fingerprint)

    def _terminal(self, outcome=QuantitativeTerminalOutcome.COMPLETED):
        value = QuantitativeTerminalResult(
            "terminal", "p", "r", "QUANTITATIVE", "dataset", "fp-dataset",
            "APPROVED", (), "weight", "fp-weight", "weight-approval", (),
            1, 0, 1, 0, "report" if outcome is QuantitativeTerminalOutcome.COMPLETED else "",
            "ACCEPTED" if outcome is QuantitativeTerminalOutcome.COMPLETED else outcome.value,
            (), "COMPLETED", outcome, f"terminal-{outcome.value}",
        )
        self.state.persist(value, record_id=self.terminal_record_id, project_id="p", run_id="r", accepted=True)
        self.workflow_results[QUANTITATIVE_SAFE_STATE_KEY] = {
            "terminal_result_record_id": self.terminal_record_id,
        }
        return value

    def request(self, **changes):
        request = QuantitativeAuthorityFinalizationInput(
            "p", "r", self.terminal_record_id, self.refs["brief"], self.refs["qz"],
            self.refs["ra"], self.refs["rb"], self.refs["rc"], (self.refs["rd"],),
            (self.refs["re"],), (self.refs["rf"],), (self.refs["rg"],),
            (self.refs["rh"],), (self.refs["ri"],), self.refs["dataset"],
            self.refs["codebook"], self.refs["qc"], (self.refs["weight"],), (),
        )
        return replace(request, **changes)

    def test_real_transition_idempotency_restart_and_backward_chain(self):
        self.assertNotEqual(self.terminal_record_id, self.terminal.result_id)
        first = self.service.finalize(self.request(), created_at="t", created_by="system")
        second = self.service.finalize(self.request(), created_at="ignored", created_by="ignored")
        self.assertEqual(first, second)
        restarted = self._service()
        self.assertEqual(first, restarted.resolve_current(project_id="p", run_id="r"))
        backward = self.service.reconstruct_backward(
            objective_authority_id="ri",
            project_id="p", run_id="r",
        )
        self.assertEqual(first.manifest_fingerprint, backward.manifest_fingerprint)
        self.assertEqual((("ri", "fp-ri"),), first.approved_objective_authorities)

    def test_current_resolution_requires_exact_durable_terminal_record_id(self):
        finalized = self.service.finalize(self.request(), created_at="t", created_by="system")
        self.workflow_results[QUANTITATIVE_SAFE_STATE_KEY] = {
            "terminal_result_record_id": self.terminal.result_id,
        }
        with self.assertRaisesRegex(ValueError, "unavailable for project"):
            self.service.resolve_current(project_id="p", run_id="r")
        self.workflow_results[QUANTITATIVE_SAFE_STATE_KEY] = {}
        with self.assertRaisesRegex(
            QuantitativeAuthorityFinalizationError, "no durable terminal record",
        ):
            self.service.resolve_current(project_id="p", run_id="r")
        self.workflow_results[QUANTITATIVE_SAFE_STATE_KEY] = {
            "terminal_result_record_id": self.terminal_record_id,
        }
        self.assertEqual(
            finalized,
            self.service.resolve_current(project_id="p", run_id="r"),
        )

    def test_resolve_current_revalidates_qz_ra_rb_rc_and_preserves_history(self):
        finalized = self.service.finalize(self.request(), created_at="t", created_by="system")
        selection, exact_chain = self.selection.resolve_current_selection(project_id="p", run_id="r")
        self.assertEqual(finalized, self.service.resolve_current(project_id="p", run_id="r"))
        self.assertEqual(finalized, self.service.resolve_current(project_id="p", run_id="r"))

        for key, kind in (("qz", "QZ_DESIGN"), ("ra", "RA_QUESTIONNAIRE"),
                          ("rb", "RB_RECONCILIATION"), ("rc", "RC_PLAN")):
            with self.subTest(authority=key):
                historical = self._load(self.refs[key].authority_id, project_id="p")
                self.current_ids[key] = self._ref(kind, f"{key}-v2").authority_id
                with self.assertRaisesRegex(QuantitativeAuthorityFinalizationError, f"stale {key.upper()}"):
                    self.service.resolve_current(project_id="p", run_id="r")
                with self.assertRaisesRegex(QuantitativeAuthorityFinalizationError, f"stale {key.upper()}"):
                    self.service.reconstruct_backward(project_id="p", run_id="r", objective_authority_id="ri")
                restarted = self._service()
                with self.assertRaisesRegex(QuantitativeAuthorityFinalizationError, f"stale {key.upper()}"):
                    restarted.resolve_current(project_id="p", run_id="r")
                self.assertEqual(selection, self.selection.load_historical(
                    selection_id=selection.selection_id, project_id="p", run_id="r",
                ))
                self.assertEqual(exact_chain, self.chain.resolve_exact(
                    manifest_id=finalized.manifest_id, project_id="p", run_id="r",
                ))
                self.assertEqual(historical, self._load(self.refs[key].authority_id, project_id="p"))
                self.current_ids[key] = key
                self.assertEqual(finalized, self.service.resolve_current(project_id="p", run_id="r"))
    def test_controlled_no_report_finalizes_without_fabricating_report(self):
        self.backing._records.pop(self.terminal_record_id)
        self.terminal = self._terminal(QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_REPORT)
        request = self.request(
            report_authority=(), controlled_absences=(self.refs["no_report"],),
        )
        value = self.service.finalize(request, created_at="t", created_by="system")
        self.assertEqual("COMPLETED_WITH_NO_SUPPORTED_REPORT", value.terminal_outcome)
        self.assertEqual("RG_CONTROLLED_ABSENCE", value.controlled_absences[0][0])

    def test_fail_closed_preconditions_and_partial_resume(self):
        for request, message in (
            (self.request(execution_mode="DATASET_ONLY_EXPLORATORY_EXECUTION"), "dataset-only"),
            (self.request(analysis_execution=()), "RD/RH"),
            (self.request(research_question_authorities=()), "RD/RH"),
            (self.request(dataset=replace(self.refs["dataset"], authority_fingerprint="bad")), "Dataset"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(QuantitativeAuthorityFinalizationError, message):
                self.service.finalize(request, created_at="t", created_by="system")
        self.run.status = WorkflowStatus.RUNNING
        with self.assertRaisesRegex(QuantitativeAuthorityFinalizationError, "not successfully terminal"):
            self.service.finalize(self.request(), created_at="t", created_by="system")
        self.run.status = WorkflowStatus.COMPLETED
        manifest = self.chain.create_manifest(
            project_id="p", run_id="r", source_brief=self.refs["brief"], research_design=self.refs["qz"],
            questionnaire=self.refs["ra"], reconciliation=self.refs["rb"], analysis_plan=self.refs["rc"],
            analysis_execution=(self.refs["rd"],), finding_authority=(self.refs["re"],),
            insight_authority=(self.refs["rf"],), report_authority=(self.refs["rg"],),
            research_question_authorities=(self.refs["rh"],), objective_authorities=(self.refs["ri"],),
            dataset=self.refs["dataset"], codebook=self.refs["codebook"], qc_authority=self.refs["qc"],
            weight_set_authorities=(self.refs["weight"],),
        )
        resumed = self.service.finalize(self.request(), created_at="t", created_by="system")
        self.assertEqual(manifest.manifest_id, resumed.manifest_id)

    def test_conflicting_selection_corruption_and_terminal_ambiguity_fail(self):
        current = self.service.finalize(self.request(), created_at="t", created_by="system")
        other = self._ref("RI_OBJECTIVE", "ri-other")
        with self.assertRaisesRegex(Exception, "supersede"):
            self.service.finalize(self.request(objective_authorities=(other,)), created_at="t2", created_by="system")
        record = self.backing._records[current.manifest_id]
        self.backing._records[current.manifest_id] = replace(record, payload_checksum="corrupt")
        with self.assertRaisesRegex(Exception, "checksum"):
            self.service.resolve_current(project_id="p", run_id="r")

    def test_historical_qz_ra_rb_rc_fail_before_manifest_or_rk_activation(self):
        for key, kind in (("qz", "QZ_DESIGN"), ("ra", "RA_QUESTIONNAIRE"),
                          ("rb", "RB_RECONCILIATION"), ("rc", "RC_PLAN")):
            with self.subTest(authority=key):
                current = self._ref(kind, f"{key}-current")
                self.current_ids[key] = current.authority_id
                before_manifests = self.chain_repo.list_manifests(project_id="p", run_id="r")
                before_selections = self.selection_repo.list_selections(project_id="p", run_id="r")
                with self.assertRaisesRegex(QuantitativeAuthorityFinalizationError, f"stale {key.upper()}"):
                    self.service.finalize(self.request(), created_at="t", created_by="system")
                self.assertEqual(before_manifests, self.chain_repo.list_manifests(project_id="p", run_id="r"))
                self.assertEqual(before_selections, self.selection_repo.list_selections(project_id="p", run_id="r"))
                self.assertIsNotNone(self._load(self.refs[key].authority_id, project_id="p"))
                self.current_ids[key] = key
    def test_production_composition_exposes_rl_ri_and_rj(self):
        from tests.api.helpers import build_test_container
        with tempfile.TemporaryDirectory() as root:
            container = build_test_container(temp_dir=root)
            try:
                self.assertIsNotNone(container.quantitative_authority_finalization_service)
                rl = container.quantitative_authority_finalization_service
                self.assertEqual("QuantitativeResearchDesignService", type(rl._designs).__name__)
                self.assertEqual("QuantitativeQuestionnaireService", type(rl._questionnaires).__name__)
                self.assertEqual("QuantitativeMeasurementReconciliationService", type(rl._reconciliations).__name__)
                self.assertEqual("QuantitativeAnalysisPlanService", type(rl._plans).__name__)
                self.assertIs(rl._objectives, container.quantitative_objective_coverage_service)
                self.assertIsNotNone(container.quantitative_objective_coverage_service)
                self.assertIsNotNone(container.quantitative_study_sufficiency_service)
            finally:
                container.shutdown()


if __name__ == "__main__":
    unittest.main()
