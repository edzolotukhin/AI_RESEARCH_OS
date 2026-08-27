from __future__ import annotations
from dataclasses import asdict
from uuid import NAMESPACE_URL, uuid5
from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.authority_chain import AUTHORITY_CHAIN_SELECTION_METHOD_VERSION, QuantitativeCurrentAuthorityChainSelection

class QuantitativeAuthorityChainSelectionError(ValueError): pass

class QuantitativeAuthorityChainSelectionService:
    def __init__(self, *, repository, authority_chain_service, digest_provider):
        self.repository=repository; self._chains=authority_chain_service; self._digest=digest_provider
    def activate(self, *, project_id, run_id, manifest_id, created_at, created_by, supersedes_selection_id=None):
        projection=self._chains.resolve_exact(manifest_id=manifest_id,project_id=project_id,run_id=run_id)
        if projection.execution_mode!="DESIGN_AWARE_EXECUTION": raise QuantitativeAuthorityChainSelectionError("dataset-only or wrong-mode chain cannot be activated")
        current=self._current_head(project_id=project_id,run_id=run_id,allow_missing=True)
        if current is not None:
            if (current.manifest_id,current.manifest_fingerprint)==(projection.manifest_id,projection.manifest_fingerprint):
                if supersedes_selection_id not in (None,current.supersedes_selection_id): raise QuantitativeAuthorityChainSelectionError("conflicting identical activation")
                return current
            if supersedes_selection_id!=current.selection_id: raise QuantitativeAuthorityChainSelectionError("replacement must explicitly supersede exact current selection")
        elif supersedes_selection_id is not None: raise QuantitativeAuthorityChainSelectionError("cannot supersede unavailable current selection")
        qz=self._one(projection,"QZ_DESIGN"); rc=self._one(projection,"RC_PLAN")
        payload={"contract":"RK_CURRENT_CHAIN_SELECTION_V1","project":project_id,"run":run_id,"mode":projection.execution_mode,"manifest":projection.manifest_id,"manifest_fingerprint":projection.manifest_fingerprint,"qz":asdict(qz),"rc":asdict(rc),"supersedes":supersedes_selection_id,"actor":created_by,"time":created_at,"method":AUTHORITY_CHAIN_SELECTION_METHOD_VERSION}
        fingerprint=canonical_digest(payload,digest_provider=self._digest)
        value=QuantitativeCurrentAuthorityChainSelection(str(uuid5(NAMESPACE_URL,f"rk:{project_id}:{run_id}:{fingerprint}")),project_id,run_id,"QUANTITATIVE",projection.execution_mode,projection.manifest_id,projection.manifest_fingerprint,qz.authority_id,qz.authority_fingerprint,rc.authority_id,rc.authority_fingerprint,supersedes_selection_id,created_at,created_by,AUTHORITY_CHAIN_SELECTION_METHOD_VERSION,fingerprint)
        return self.repository.save_selection(value)
    def resolve_current_selection(self, *, project_id, run_id, execution_mode="DESIGN_AWARE_EXECUTION"):
        if execution_mode != "DESIGN_AWARE_EXECUTION":
            raise QuantitativeAuthorityChainSelectionError("no design-aware authority-chain selection for dataset-only mode")
        selection=self._current_head(project_id=project_id,run_id=run_id)
        projection=self.resolve_current_authority_chain(project_id=project_id,run_id=run_id,execution_mode=execution_mode)
        return selection,projection
    def resolve_current_authority_chain(self, *, project_id, run_id, execution_mode="DESIGN_AWARE_EXECUTION"):
        if execution_mode!="DESIGN_AWARE_EXECUTION": raise QuantitativeAuthorityChainSelectionError("no design-aware authority-chain selection for dataset-only mode")
        selection=self._current_head(project_id=project_id,run_id=run_id)
        projection=self._chains.resolve_exact(manifest_id=selection.manifest_id,project_id=project_id,run_id=run_id)
        if (projection.manifest_id,projection.manifest_fingerprint)!=(selection.manifest_id,selection.manifest_fingerprint): raise QuantitativeAuthorityChainSelectionError("selection references stale manifest fingerprint")
        qz=self._one(projection,"QZ_DESIGN"); rc=self._one(projection,"RC_PLAN")
        if (qz.authority_id,qz.authority_fingerprint)!=(selection.research_design_id,selection.research_design_fingerprint) or (rc.authority_id,rc.authority_fingerprint)!=(selection.analysis_plan_id,selection.analysis_plan_fingerprint): raise QuantitativeAuthorityChainSelectionError("selection governing authority mismatch")
        return projection
    def load_historical(self, *, selection_id, project_id, run_id):
        value=self.repository.get_selection(selection_id,project_id=project_id)
        if value is None or value.run_id!=run_id: raise QuantitativeAuthorityChainSelectionError("selection unavailable for project/run")
        return value
    def _current_head(self, *, project_id, run_id, allow_missing=False):
        values=tuple(self.repository.list_selections(project_id=project_id,run_id=run_id)); superseded={x.supersedes_selection_id for x in values if x.supersedes_selection_id}; heads=tuple(x for x in values if x.selection_id not in superseded)
        if not heads and allow_missing: return None
        if len(heads)!=1: raise QuantitativeAuthorityChainSelectionError("current authority-chain selection is missing or ambiguous")
        head=heads[0]
        if self._fingerprint(head)!=head.fingerprint: raise QuantitativeAuthorityChainSelectionError("authority-chain selection fingerprint mismatch")
        by_id={x.selection_id:x for x in values}; seen=set(); cursor=head
        while cursor is not None:
            if cursor.selection_id in seen: raise QuantitativeAuthorityChainSelectionError("authority-chain selection cycle")
            seen.add(cursor.selection_id); cursor=by_id.get(cursor.supersedes_selection_id) if cursor.supersedes_selection_id else None
        return head
    def _fingerprint(self,value):
        from domain.quantitative.research_question_coverage import QuantitativeAuthorityReference
        qz=QuantitativeAuthorityReference("QZ_DESIGN",value.research_design_id,value.research_design_fingerprint)
        rc=QuantitativeAuthorityReference("RC_PLAN",value.analysis_plan_id,value.analysis_plan_fingerprint)
        payload={"contract":"RK_CURRENT_CHAIN_SELECTION_V1","project":value.project_id,"run":value.run_id,"mode":value.execution_mode,"manifest":value.manifest_id,"manifest_fingerprint":value.manifest_fingerprint,"qz":asdict(qz),"rc":asdict(rc),"supersedes":value.supersedes_selection_id,"actor":value.created_by,"time":value.created_at,"method":value.method_version}
        return canonical_digest(payload,digest_provider=self._digest)
    @staticmethod
    def _one(projection,kind):
        values=tuple(x for x in projection.ordered_authorities if x.authority_kind==kind)
        if len(values)!=1: raise QuantitativeAuthorityChainSelectionError(f"exact {kind} authority is missing or ambiguous")
        return values[0]
