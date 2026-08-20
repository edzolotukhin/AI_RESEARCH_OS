from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation, localcontext
from uuid import NAMESPACE_URL, uuid5

from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.weighting import WeightingError
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, PiiClassification, VariableRole, VariableType
from domain.quantitative.weighting import (
    WeightConstructionMethod, WeightMissingPolicy, WeightSet, WeightSourceType,
    WeightTrimmingPolicy, WeightValidationStatus, WeightingConvergenceDiagnostic,
    WeightingTargetMargin, WeightingTargetPlan,
)


METHOD_VERSION = "QN_RAKING_V1"
_CATEGORICAL = {VariableType.CATEGORICAL, VariableType.DEMOGRAPHIC, VariableType.ORDINAL_SCALE}


def _plan_payload(*, plan_id, dataset_fingerprint, margins, target_source, target_total_tolerance, convergence_tolerance, maximum_iterations, minimum_weight, maximum_weight, trimming_policy, approved):
    return {"plan_id":plan_id,"dataset":dataset_fingerprint,"margins":[(item.variable_id,[(canonical_scalar(category),str(target)) for category,target in item.category_targets]) for item in margins],"source":target_source,"target_tolerance":str(target_total_tolerance),"convergence":str(convergence_tolerance),"iterations":maximum_iterations,"bounds":[str(minimum_weight),str(maximum_weight)],"trimming":trimming_policy.value,"method":METHOD_VERSION,"missing":"FAIL","normalization":"PRESERVE_SAMPLE_TOTAL","approved":approved}


def build_weighting_target_plan(*, plan_id: str, dataset: DatasetVersion, margins: tuple[WeightingTargetMargin, ...], target_source: str, target_total_tolerance: Decimal, convergence_tolerance: Decimal, maximum_iterations: int, minimum_weight: Decimal, maximum_weight: Decimal, trimming_policy: WeightTrimmingPolicy, digest_provider, approved: bool = True) -> WeightingTargetPlan:
    payload=_plan_payload(plan_id=plan_id,dataset_fingerprint=dataset.dataset_fingerprint,margins=margins,target_source=target_source,target_total_tolerance=target_total_tolerance,convergence_tolerance=convergence_tolerance,maximum_iterations=maximum_iterations,minimum_weight=minimum_weight,maximum_weight=maximum_weight,trimming_policy=trimming_policy,approved=approved)
    return WeightingTargetPlan(plan_id,dataset.version_id,dataset.dataset_fingerprint,margins,target_source,target_total_tolerance,WeightConstructionMethod.RAKING,convergence_tolerance,maximum_iterations,minimum_weight,maximum_weight,trimming_policy,"PRESERVE_SAMPLE_TOTAL",WeightMissingPolicy.FAIL,approved,METHOD_VERSION,canonical_digest(payload,digest_provider=digest_provider))


class TargetMarginWeightingService:
    def __init__(self, *, storage, digest_provider) -> None:
        self._storage, self._digest = storage, digest_provider

    def construct(self, *, dataset: DatasetVersion, codebook: CodebookVersion, plan: WeightingTargetPlan) -> WeightSet:
        self._validate_plan(dataset,codebook,plan)
        rows=self._storage.get_parsed_rows(dataset.version_id); refs=self._storage.get_respondent_lineage(dataset.version_id)
        if not rows or len(rows)!=len(refs): raise WeightingError("weighting dataset/lineage is empty or inconsistent")
        positions={item.variable_id:index for index,item in enumerate(codebook.variables)}
        categories=[]
        for margin in plan.margins:
            observed=[]
            for row in rows:
                value=row[positions[margin.variable_id]]
                if value is None: raise WeightingError("missing weighting-control value is unsupported")
                observed.append(self._key(value))
            targets={self._key(category):target for category,target in margin.category_targets}
            if any(target>0 and key not in observed for key,target in targets.items()): raise WeightingError("positive target has an empty sample category")
            if any(key not in targets for key in observed): raise WeightingError("sample category is absent from target margin")
            categories.append((margin,tuple(observed),targets))
        with localcontext() as ctx:
            ctx.prec=50
            weights=[Decimal(1) for _ in refs]; clipped=0; converged=False; max_error=Decimal("Infinity")
            for iteration in range(1,plan.maximum_iterations+1):
                for _,observed,targets in categories:
                    total=sum(weights)
                    for category,target_share in sorted(targets.items()):
                        indices=[i for i,value in enumerate(observed) if value==category]
                        current=sum(weights[i] for i in indices)
                        if current==0 and target_share>0: raise WeightingError("raking margin is structurally impossible")
                        factor=(target_share*total/current) if current else Decimal(1)
                        for i in indices:
                            candidate=weights[i]*factor
                            if candidate<plan.minimum_weight or candidate>plan.maximum_weight:
                                if plan.trimming_policy is WeightTrimmingPolicy.NONE: raise WeightingError("constructed weight exceeds explicit bounds")
                                candidate=min(plan.maximum_weight,max(plan.minimum_weight,candidate)); clipped+=1
                            weights[i]=candidate
                max_error,achieved=self._diagnostics(weights,categories)
                if max_error<=plan.convergence_tolerance: converged=True; break
            if not converged: raise WeightingError("raking did not converge within maximum_iterations")
            total=sum(weights); squared=sum(item*item for item in weights); effective=(total*total/squared)
            vector=tuple(sorted(zip(refs,weights)))
            vector_fp=canonical_digest([(ref,str(weight)) for ref,weight in vector],digest_provider=self._digest)
            diag_payload={"plan":plan.fingerprint,"iterations":iteration,"error":str(max_error),"achieved":[(variable,[(canonical_scalar(category),str(share)) for category,share in values]) for variable,values in achieved],"clipped":clipped,"effective":str(effective),"method":METHOD_VERSION}
            diagnostic=WeightingConvergenceDiagnostic(plan.plan_id,plan.fingerprint,iteration,max_error,achieved,True,clipped>0,clipped,effective,canonical_digest(diag_payload,digest_provider=self._digest))
            validation_fp=canonical_digest({"plan":plan.fingerprint,"vector":vector_fp,"diagnostic":diagnostic.fingerprint},digest_provider=self._digest)
            reproducibility=canonical_digest({"dataset":dataset.dataset_fingerprint,"plan":plan.fingerprint,"vector":vector_fp,"validation":validation_fp,"method":METHOD_VERSION},digest_provider=self._digest)
            return WeightSet(str(uuid5(NAMESPACE_URL,f"qn-weightset:{reproducibility}")),dataset.version_id,dataset.dataset_fingerprint,WeightSourceType.TARGET_MARGINS,plan.fingerprint,canonical_digest(tuple(refs),digest_provider=self._digest),vector,vector_fp,len(vector),len(refs),len(vector),Decimal(1),min(weights),max(weights),total/Decimal(len(weights)),total,sum(1 for item in weights if item==0),0,0,0,0,0,WeightValidationStatus.VALID,(),validation_fp,reproducibility,parser_name="deterministic-raking",parser_version=METHOD_VERSION,construction_plan_id=plan.plan_id,construction_plan_fingerprint=plan.fingerprint,convergence_diagnostic=diagnostic,effective_sample_size=effective)

    def _validate_plan(self,dataset,codebook,plan):
        if not plan.approved or plan.method is not WeightConstructionMethod.RAKING or plan.version!=METHOD_VERSION: raise WeightingError("target plan is not approved QN raking authority")
        if plan.dataset_version_id!=dataset.version_id or plan.dataset_fingerprint!=dataset.dataset_fingerprint: raise WeightingError("target plan is stale for DatasetVersion")
        expected=canonical_digest(_plan_payload(plan_id=plan.plan_id,dataset_fingerprint=plan.dataset_fingerprint,margins=plan.margins,target_source=plan.target_source,target_total_tolerance=plan.target_total_tolerance,convergence_tolerance=plan.convergence_tolerance,maximum_iterations=plan.maximum_iterations,minimum_weight=plan.minimum_weight,maximum_weight=plan.maximum_weight,trimming_policy=plan.trimming_policy,approved=plan.approved),digest_provider=self._digest)
        if expected!=plan.fingerprint: raise WeightingError("target plan fingerprint mismatch")
        if not plan.margins or plan.maximum_iterations<1 or plan.convergence_tolerance<=0 or plan.minimum_weight<=0 or plan.maximum_weight<plan.minimum_weight: raise WeightingError("invalid raking controls")
        seen=set()
        for margin in plan.margins:
            if margin.variable_id in seen: raise WeightingError("duplicate control variable")
            seen.add(margin.variable_id)
            try: variable=codebook.variable_by_id(margin.variable_id)
            except KeyError as exc: raise WeightingError("unknown control variable") from exc
            if variable.variable_type not in _CATEGORICAL or not variable.analytically_eligible or variable.role in {VariableRole.PII,VariableRole.TECHNICAL_ID,VariableRole.WEIGHT} or variable.pii_classification is not PiiClassification.NONE: raise WeightingError("control variable is not eligible categorical authority")
            targets={}; total=Decimal(0)
            for category,raw in margin.category_targets:
                try: target=Decimal(str(raw))
                except (InvalidOperation,ValueError): raise WeightingError("target is non-numeric")
                key=self._key(category)
                if key in targets or not target.is_finite() or target<0: raise WeightingError("invalid or duplicate target category")
                targets[key]=target; total+=target
            known={self._key(value) for value,_ in variable.value_labels}
            if known and any(key not in known for key in targets): raise WeightingError("unknown target category")
            if abs(total-Decimal(1))>plan.target_total_tolerance: raise WeightingError("target distribution does not sum to one")

    @staticmethod
    def _key(value):
        scalar=canonical_scalar(value); return scalar["type"],scalar["value"]

    @staticmethod
    def _diagnostics(weights,categories):
        total=sum(weights); achieved=[]; max_error=Decimal(0)
        for margin,observed,targets in categories:
            values=[]
            for category,target in sorted(targets.items()):
                share=sum(weights[i] for i,value in enumerate(observed) if value==category)/total
                values.append((category[1],share)); max_error=max(max_error,abs(share-target))
            achieved.append((margin.variable_id,tuple(values)))
        return max_error,tuple(achieved)
