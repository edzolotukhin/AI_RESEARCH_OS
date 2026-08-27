import unittest
from dataclasses import dataclass, replace

from application.quantitative.authority_chain import (
    QuantitativeAuthorityChainError,
    QuantitativeAuthorityChainService,
)
from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from domain.quantitative.research_question_coverage import QuantitativeAuthorityReference
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_authority_chain_repository import QLQuantitativeAuthorityChainRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


@dataclass(frozen=True)
class FakeAuthority:
    project_id: str
    run_id: str
    fingerprint: str


class AuthorityStore:
    def __init__(self):
        self.values = {}

    def put(self, kind, authority_id, fingerprint, project="p", run="r"):
        self.values[(kind, authority_id)] = FakeAuthority(project, run, fingerprint)
        return QuantitativeAuthorityReference(kind, authority_id, fingerprint)

    def loaders(self):
        result = {}
        for kind, _ in self.values:
            result[kind] = lambda authority_id, *, project_id, kind=kind: self.values.get((kind, authority_id))
        return result


class Q2102AuthorityChainIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.records = InMemoryQuantitativeStateRepository()
        self.state = QuantitativeStateService(repository=self.records, digest_provider=Sha256DigestProvider())
        self.repo = QLQuantitativeAuthorityChainRepository(self.state)
        self.store = AuthorityStore()
        put = self.store.put
        self.refs = dict(
            brief=put("QZ_BRIEF", "brief-v1", "brief-fp"),
            qz=put("QZ_DESIGN", "design-v1", "qz-fp"),
            ra=put("RA_QUESTIONNAIRE", "questionnaire-v1", "ra-fp"),
            rb=put("RB_RECONCILIATION", "reconciliation-v1", "rb-fp"),
            rc=put("RC_PLAN", "plan-v1", "rc-fp"),
            rd=put("RD_MANIFEST", "rd-manifest", "rd-fp"),
            rd_cov=put("RD_COVERAGE", "rd-coverage", "rd-cov-fp"),
            re_input=put("RE_INPUT", "re-input", "re-input-fp"),
            re_lineage=put("RE_LINEAGE", "re-lineage", "re-lineage-fp"),
            re_coverage=put("RE_COVERAGE", "re-coverage", "re-cov-fp"),
            rf_input=put("RF_INPUT", "rf-input", "rf-input-fp"),
            rf_lineage=put("RF_LINEAGE", "rf-lineage", "rf-lineage-fp"),
            rf_coverage=put("RF_COVERAGE", "rf-coverage", "rf-cov-fp"),
            rg_input=put("RG_INPUT", "rg-input", "rg-input-fp"),
            rg_lineage=put("RG_LINEAGE", "rg-lineage", "rg-lineage-fp"),
            rg_coverage=put("RG_COVERAGE", "rg-coverage", "rg-cov-fp"),
            rh1=put("RH_ASSESSMENT", "rh-rq-1", "rh-rq-1-fp"),
            rh2=put("RH_ASSESSMENT", "rh-rq-shared", "rh-shared-fp"),
            rh3=put("RH_ASSESSMENT", "rh-rq-3", "rh-rq-3-fp"),
            rh1a=put("RH_APPROVAL", "rh-ap-1", "rh-ap-1-fp"),
            rh2a=put("RH_APPROVAL", "rh-ap-shared", "rh-ap-shared-fp"),
            rh3a=put("RH_APPROVAL", "rh-ap-3", "rh-ap-3-fp"),
            ri1=put("RI_OBJECTIVE", "ri-objective-1", "ri-obj-1-fp"),
            ri2=put("RI_OBJECTIVE", "ri-objective-2", "ri-obj-2-fp"),
            dataset=put("DATASET", "dataset-v1", "dataset-fp"),
            codebook=put("CODEBOOK", "codebook-v1", "codebook-fp"),
            qc=put("QC_APPROVAL", "qc-ap-1", "qc-fp"),
            weight=put("WEIGHT_SET", "weights-v1", "weight-fp"),
        )
        self.current = []
        self.service = QuantitativeAuthorityChainService(
            repository=self.repo, digest_provider=Sha256DigestProvider(),
            authority_loaders=self.store.loaders(),
            current_reference_resolver=lambda **_: tuple(self.current),
        )

    def create(self, *, controlled_absences=()):
        r = self.refs
        value = self.service.create_manifest(
            project_id="p", run_id="r", source_brief=r["brief"], research_design=r["qz"],
            questionnaire=r["ra"], reconciliation=r["rb"], analysis_plan=r["rc"],
            analysis_execution=(r["rd"], r["rd_cov"]),
            finding_authority=(r["re_input"], r["re_lineage"], r["re_coverage"]),
            insight_authority=(r["rf_input"], r["rf_lineage"], r["rf_coverage"]),
            report_authority=(r["rg_input"], r["rg_lineage"], r["rg_coverage"]),
            research_question_authorities=(r["rh1"], r["rh1a"], r["rh2"], r["rh2a"], r["rh3"], r["rh3a"]),
            objective_authorities=(r["ri1"], r["ri2"]), dataset=r["dataset"],
            codebook=r["codebook"], qc_authority=r["qc"],
            weight_set_authorities=(r["weight"],), controlled_absences=controlled_absences,
        )
        self.current[:] = self.service.references(value)
        return value

    def test_forward_and_backward_converge_on_exact_manifest(self):
        manifest = self.create()
        forward = self.service.reconstruct_forward(manifest_id=manifest.manifest_id, project_id="p", run_id="r")
        backward = self.service.reconstruct_backward(manifest_id=manifest.manifest_id,
            objective_authority_id=self.refs["ri2"].authority_id, project_id="p", run_id="r")
        self.assertEqual(manifest.fingerprint, forward.manifest_fingerprint)
        self.assertEqual(forward, backward)
        self.assertEqual(2, len(forward.objective_authorities))
        self.assertEqual(6, len(forward.research_question_authorities))

    def test_restart_loads_identical_and_replay_is_idempotent(self):
        manifest = self.create()
        restarted = QuantitativeAuthorityChainService(
            repository=QLQuantitativeAuthorityChainRepository(self.state),
            digest_provider=Sha256DigestProvider(), authority_loaders=self.store.loaders(),
            current_reference_resolver=lambda **_: tuple(self.current),
        )
        self.assertEqual(manifest, self.create())
        self.assertEqual(manifest.fingerprint, restarted.resolve_current(
            manifest_id=manifest.manifest_id, project_id="p", run_id="r").manifest_fingerprint)

    def test_every_representative_upstream_change_stales_current_chain(self):
        manifest = self.create()
        for index in range(len(self.current)):
            old = self.current[index]
            self.current[index] = replace(old, authority_fingerprint=old.authority_fingerprint + "-new")
            with self.assertRaisesRegex(QuantitativeAuthorityChainError, "not current"):
                self.service.resolve_current(manifest_id=manifest.manifest_id, project_id="p", run_id="r")
            self.current[index] = old

    def test_wrong_scope_fingerprint_duplicate_and_corruption_fail_closed(self):
        manifest = self.create()
        with self.assertRaises(QuantitativeAuthorityChainError):
            self.service.resolve_current(manifest_id=manifest.manifest_id, project_id="wrong", run_id="r")
        with self.assertRaisesRegex(QuantitativeAuthorityChainError, "fingerprint"):
            self.service.create_manifest(project_id="p", run_id="r", source_brief=replace(self.refs["brief"],authority_fingerprint="bad"),
                research_design=self.refs["qz"],questionnaire=self.refs["ra"],reconciliation=self.refs["rb"],analysis_plan=self.refs["rc"],
                analysis_execution=(self.refs["rd"],),finding_authority=(self.refs["re_input"],),insight_authority=(),report_authority=(),
                research_question_authorities=(self.refs["rh1"],),objective_authorities=(self.refs["ri1"],),dataset=self.refs["dataset"],
                codebook=self.refs["codebook"],qc_authority=self.refs["qc"])
        with self.assertRaisesRegex(QuantitativeAuthorityChainError, "duplicate"):
            self.service.create_manifest(project_id="p",run_id="r",source_brief=self.refs["brief"],research_design=self.refs["qz"],
                questionnaire=self.refs["ra"],reconciliation=self.refs["rb"],analysis_plan=self.refs["rc"],analysis_execution=(self.refs["rd"],self.refs["rd"]),
                finding_authority=(),insight_authority=(),report_authority=(),research_question_authorities=(self.refs["rh1"],),
                objective_authorities=(self.refs["ri1"],),dataset=self.refs["dataset"],codebook=self.refs["codebook"],qc_authority=self.refs["qc"])
        record = self.records._records[manifest.manifest_id]
        self.records._records[manifest.manifest_id] = replace(record, payload_checksum="corrupt")
        with self.assertRaises(QuantitativePersistenceError):
            self.repo.get_manifest(manifest.manifest_id, project_id="p")

    def test_controlled_absence_is_explicit_and_dataset_only_cannot_build(self):
        absence = self.store.put("RG_CONTROLLED_ABSENCE", "no-report", "no-report-fp")
        self.service._loaders = self.store.loaders()
        manifest = self.create(controlled_absences=(absence,))
        projection = self.service.resolve_current(manifest_id=manifest.manifest_id, project_id="p", run_id="r")
        self.assertEqual((absence,), projection.controlled_absences)
        with self.assertRaisesRegex(QuantitativeAuthorityChainError, "project/run/mode"):
            self.service.resolve_current(manifest_id=manifest.manifest_id, project_id="p", run_id="dataset-only")


if __name__ == "__main__":
    unittest.main()
