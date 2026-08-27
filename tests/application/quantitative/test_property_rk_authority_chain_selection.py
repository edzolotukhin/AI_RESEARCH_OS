import unittest
import tempfile
from dataclasses import dataclass, replace

from application.quantitative.authority_chain import QuantitativeAuthorityChainService
from application.quantitative.authority_chain_selection import QuantitativeAuthorityChainSelectionError, QuantitativeAuthorityChainSelectionService
from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from domain.quantitative.research_question_coverage import QuantitativeAuthorityReference
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_authority_chain_repository import QLQuantitativeAuthorityChainRepository
from infrastructure.persistence.quantitative_authority_chain_selection_repository import QLQuantitativeAuthorityChainSelectionRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider

@dataclass(frozen=True)
class FakeAuthority:
    project_id: str
    run_id: str
    fingerprint: str

class Store:
    def __init__(self): self.values={}
    def put(self,kind,identity,fp,project="p",run="r"):
        self.values[(kind,identity)]=FakeAuthority(project,run,fp); return QuantitativeAuthorityReference(kind,identity,fp)
    def loaders(self):
        return {kind:(lambda identity,*,project_id,kind=kind:self.values.get((kind,identity))) for kind,_ in self.values}

class PropertyRKTests(unittest.TestCase):
    def setUp(self):
        self.records=InMemoryQuantitativeStateRepository(); self.digest=Sha256DigestProvider(); self.state=QuantitativeStateService(repository=self.records,digest_provider=self.digest)
        self.manifests=QLQuantitativeAuthorityChainRepository(self.state); self.selections=QLQuantitativeAuthorityChainSelectionRepository(self.state); self.store=Store(); self.current=[]
        self.refs=self.make_refs("1")
        self.chain=QuantitativeAuthorityChainService(repository=self.manifests,digest_provider=self.digest,authority_loaders=self.store.loaders(),current_reference_resolver=lambda **_:tuple(self.current))
        self.service=QuantitativeAuthorityChainSelectionService(repository=self.selections,authority_chain_service=self.chain,digest_provider=self.digest)

    def make_refs(self,suffix):
        p=self.store.put
        return dict(brief=p("QZ_BRIEF",f"brief-{suffix}",f"brief-fp-{suffix}"),qz=p("QZ_DESIGN",f"qz-{suffix}",f"qz-fp-{suffix}"),ra=p("RA_QUESTIONNAIRE",f"ra-{suffix}",f"ra-fp-{suffix}"),rb=p("RB_RECONCILIATION",f"rb-{suffix}",f"rb-fp-{suffix}"),rc=p("RC_PLAN",f"rc-{suffix}",f"rc-fp-{suffix}"),rd=p("RD_MANIFEST",f"rd-{suffix}",f"rd-fp-{suffix}"),re=p("RE_LINEAGE",f"re-{suffix}",f"re-fp-{suffix}"),rf=p("RF_LINEAGE",f"rf-{suffix}",f"rf-fp-{suffix}"),rg=p("RG_LINEAGE",f"rg-{suffix}",f"rg-fp-{suffix}"),rh=p("RH_ASSESSMENT",f"rh-{suffix}",f"rh-fp-{suffix}"),ri=p("RI_OBJECTIVE",f"ri-{suffix}",f"ri-fp-{suffix}"),dataset=p("DATASET",f"dataset-{suffix}",f"dataset-fp-{suffix}"),codebook=p("CODEBOOK",f"codebook-{suffix}",f"codebook-fp-{suffix}"),qc=p("QC_APPROVAL",f"qc-{suffix}",f"qc-fp-{suffix}"))

    def manifest(self,refs):
        self.chain._loaders=self.store.loaders()
        value=self.chain.create_manifest(project_id="p",run_id="r",source_brief=refs["brief"],research_design=refs["qz"],questionnaire=refs["ra"],reconciliation=refs["rb"],analysis_plan=refs["rc"],analysis_execution=(refs["rd"],),finding_authority=(refs["re"],),insight_authority=(refs["rf"],),report_authority=(refs["rg"],),research_question_authorities=(refs["rh"],),objective_authorities=(refs["ri"],),dataset=refs["dataset"],codebook=refs["codebook"],qc_authority=refs["qc"])
        self.current[:]=self.chain.references(value); return value

    def activate(self):
        manifest=self.manifest(self.refs); selection=self.service.activate(project_id="p",run_id="r",manifest_id=manifest.manifest_id,created_at="t1",created_by="system")
        return manifest,selection

    def test_production_composition_exposes_durable_resolver(self):
        from tests.api.helpers import build_test_container
        with tempfile.TemporaryDirectory() as root:
            container=build_test_container(temp_dir=root)
            try:
                self.assertIsNotNone(container.quantitative_authority_chain_service)
                self.assertIsNotNone(container.quantitative_authority_chain_selection_service)
                self.assertIsInstance(container.quantitative_authority_chain_selection_service,QuantitativeAuthorityChainSelectionService)
            finally:
                container.shutdown()
    def test_activation_resolution_restart_and_idempotency(self):
        manifest,selection=self.activate(); projection=self.service.resolve_current_authority_chain(project_id="p",run_id="r")
        self.assertEqual(manifest.fingerprint,projection.manifest_fingerprint)
        self.assertEqual(selection,self.service.activate(project_id="p",run_id="r",manifest_id=manifest.manifest_id,created_at="ignored",created_by="ignored"))
        restarted=QuantitativeAuthorityChainSelectionService(repository=QLQuantitativeAuthorityChainSelectionRepository(self.state),authority_chain_service=self.chain,digest_provider=self.digest)
        self.assertEqual(manifest.fingerprint,restarted.resolve_current_authority_chain(project_id="p",run_id="r").manifest_fingerprint)

    def test_zero_wrong_scope_mode_and_stale_manifest_fail(self):
        with self.assertRaisesRegex(QuantitativeAuthorityChainSelectionError,"missing or ambiguous"): self.service.resolve_current_authority_chain(project_id="p",run_id="r")
        manifest,selection=self.activate()
        with self.assertRaises(QuantitativeAuthorityChainSelectionError): self.service.resolve_current_authority_chain(project_id="wrong",run_id="r")
        with self.assertRaisesRegex(QuantitativeAuthorityChainSelectionError,"dataset-only"): self.service.resolve_current_authority_chain(project_id="p",run_id="r",execution_mode="DATASET_ONLY_EXPLORATORY_EXECUTION")
        ref=self.current[0]
        self.store.values[(ref.authority_kind,ref.authority_id)]=replace(self.store.values[(ref.authority_kind,ref.authority_id)],fingerprint="stale")
        with self.assertRaisesRegex(Exception,"fingerprint mismatch"): self.service.resolve_current_authority_chain(project_id="p",run_id="r")

    def test_explicit_replacement_preserves_history(self):
        old_manifest,old=self.activate(); refs2=self.make_refs("2"); new_manifest=self.manifest(refs2)
        with self.assertRaisesRegex(QuantitativeAuthorityChainSelectionError,"explicitly supersede"): self.service.activate(project_id="p",run_id="r",manifest_id=new_manifest.manifest_id,created_at="t2",created_by="system")
        new=self.service.activate(project_id="p",run_id="r",manifest_id=new_manifest.manifest_id,created_at="t2",created_by="system",supersedes_selection_id=old.selection_id)
        self.assertEqual(new_manifest.fingerprint,self.service.resolve_current_authority_chain(project_id="p",run_id="r").manifest_fingerprint)
        self.assertEqual(old,self.service.load_historical(selection_id=old.selection_id,project_id="p",run_id="r")); self.assertIsNotNone(self.manifests.get_manifest(old_manifest.manifest_id,project_id="p"))

    def test_conflicting_and_multiple_heads_fail_closed(self):
        manifest,old=self.activate(); refs2=self.make_refs("2"); new_manifest=self.manifest(refs2)
        bad=replace(old,selection_id="conflicting-head",manifest_id=new_manifest.manifest_id,manifest_fingerprint=new_manifest.fingerprint,fingerprint="bad-fp",supersedes_selection_id=None)
        self.selections.save_selection(bad)
        with self.assertRaisesRegex(QuantitativeAuthorityChainSelectionError,"ambiguous"): self.service.resolve_current_authority_chain(project_id="p",run_id="r")

    def test_selection_and_manifest_corruption_fail_closed(self):
        manifest,selection=self.activate(); record=self.records._records[selection.selection_id]; self.records._records[selection.selection_id]=replace(record,payload_checksum="corrupt")
        with self.assertRaisesRegex(QuantitativePersistenceError,"checksum"): self.service.resolve_current_authority_chain(project_id="p",run_id="r")
        self.records._records[selection.selection_id]=record; mrecord=self.records._records[manifest.manifest_id]; self.records._records[manifest.manifest_id]=replace(mrecord,payload_checksum="corrupt")
        with self.assertRaisesRegex(QuantitativePersistenceError,"checksum"): self.service.resolve_current_authority_chain(project_id="p",run_id="r")

    def test_canonical_selection_fingerprint_mismatch_rejected(self):
        from application.quantitative.state_persistence import encode_quantitative
        manifest,selection=self.activate()
        record=self.records._records[selection.selection_id]
        tampered=replace(selection,created_by="tampered")
        payload=encode_quantitative(tampered)
        checksum=__import__("application.quantitative.fingerprints",fromlist=["canonical_digest"]).canonical_digest(payload,digest_provider=self.digest)
        self.records._records[selection.selection_id]=replace(record,payload=payload,payload_checksum=checksum)
        with self.assertRaisesRegex(QuantitativeAuthorityChainSelectionError,"fingerprint mismatch"):
            self.service.resolve_current_authority_chain(project_id="p",run_id="r")
if __name__=="__main__": unittest.main()
