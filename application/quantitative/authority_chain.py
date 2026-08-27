from __future__ import annotations

from dataclasses import asdict
from uuid import NAMESPACE_URL, uuid5

from application.quantitative.fingerprints import canonical_digest
from application.quantitative.state_persistence import authority_fingerprint
from domain.quantitative.authority_chain import (
    AUTHORITY_CHAIN_METHOD_VERSION,
    QuantitativeDesignAwareAuthorityChainManifest,
    QuantitativeDesignAwareAuthorityChainProjection,
)


class QuantitativeAuthorityChainError(ValueError):
    pass


class QuantitativeAuthorityChainService:
    """Exact-reference integration over existing immutable Quantitative authority."""

    def __init__(self, *, repository, digest_provider, authority_loaders, current_reference_resolver=None):
        self.repository = repository
        self._digest = digest_provider
        self._loaders = dict(authority_loaders)
        self._current = current_reference_resolver

    @staticmethod
    def _groups(manifest):
        return (
            (manifest.source_brief,), (manifest.research_design,), (manifest.questionnaire,),
            (manifest.reconciliation,), (manifest.analysis_plan,), manifest.analysis_execution,
            manifest.finding_authority, manifest.insight_authority, manifest.report_authority,
            manifest.research_question_authorities, manifest.objective_authorities,
            (manifest.dataset,), (manifest.codebook,), (manifest.qc_authority,),
            manifest.weight_set_authorities, manifest.controlled_absences,
        )

    @classmethod
    def references(cls, manifest):
        return tuple(ref for group in cls._groups(manifest) for ref in group)

    def create_manifest(self, *, project_id, run_id, source_brief, research_design,
                        questionnaire, reconciliation, analysis_plan, analysis_execution,
                        finding_authority, insight_authority, report_authority,
                        research_question_authorities, objective_authorities, dataset,
                        codebook, qc_authority, weight_set_authorities=(), controlled_absences=()):
        values = dict(
            source_brief=source_brief, research_design=research_design,
            questionnaire=questionnaire, reconciliation=reconciliation,
            analysis_plan=analysis_plan, analysis_execution=tuple(analysis_execution),
            finding_authority=tuple(finding_authority), insight_authority=tuple(insight_authority),
            report_authority=tuple(report_authority),
            research_question_authorities=tuple(research_question_authorities),
            objective_authorities=tuple(objective_authorities), dataset=dataset, codebook=codebook,
            qc_authority=qc_authority, weight_set_authorities=tuple(weight_set_authorities),
            controlled_absences=tuple(controlled_absences),
        )
        refs = tuple(ref for value in values.values() for ref in (value if isinstance(value, tuple) else (value,)))
        self._validate_reference_set(refs, project_id=project_id, run_id=run_id)
        payload = {"contract": "Q2_10_2_AUTHORITY_CHAIN_V1", "project": project_id,
                   "run": run_id, "mode": "DESIGN_AWARE_EXECUTION",
                   "authorities": tuple(asdict(x) for x in refs),
                   "method": AUTHORITY_CHAIN_METHOD_VERSION}
        fingerprint = canonical_digest(payload, digest_provider=self._digest)
        manifest = QuantitativeDesignAwareAuthorityChainManifest(
            str(uuid5(NAMESPACE_URL, f"quant-chain:{project_id}:{run_id}:{fingerprint}")),
            project_id, run_id, "DESIGN_AWARE_EXECUTION", **values,
            method_version=AUTHORITY_CHAIN_METHOD_VERSION, fingerprint=fingerprint,
        )
        return self.repository.save_manifest(manifest)

    def resolve_exact(self, *, manifest_id, project_id, run_id):
        manifest = self.repository.get_manifest(manifest_id, project_id=project_id)
        if manifest is None or manifest.run_id != run_id or manifest.execution_mode != "DESIGN_AWARE_EXECUTION":
            raise QuantitativeAuthorityChainError("authority-chain manifest unavailable for project/run/mode")
        self._validate_reference_set(self.references(manifest), project_id=project_id, run_id=run_id)
        return self._projection(manifest)
    def resolve_current(self, *, manifest_id, project_id, run_id):
        manifest = self.repository.get_manifest(manifest_id, project_id=project_id)
        if manifest is None or manifest.run_id != run_id or manifest.execution_mode != "DESIGN_AWARE_EXECUTION":
            raise QuantitativeAuthorityChainError("authority-chain manifest unavailable for project/run/mode")
        refs = self.references(manifest)
        self._validate_reference_set(refs, project_id=project_id, run_id=run_id)
        if self._current is None:
            raise QuantitativeAuthorityChainError("current-reference resolver is unavailable")
        expected = tuple(self._current(project_id=project_id, run_id=run_id))
        if tuple(refs) != expected:
            raise QuantitativeAuthorityChainError("authority-chain manifest is not current")
        return self._projection(manifest)

    def reconstruct_forward(self, *, manifest_id, project_id, run_id):
        return self.resolve_current(manifest_id=manifest_id, project_id=project_id, run_id=run_id)

    def reconstruct_backward(self, *, manifest_id, objective_authority_id, project_id, run_id):
        manifest = self.repository.get_manifest(manifest_id, project_id=project_id)
        if manifest is None or not any(
            ref.authority_id == objective_authority_id for ref in manifest.objective_authorities
        ):
            raise QuantitativeAuthorityChainError("Objective authority is not bound to the exact integrated chain")
        return self.resolve_current(manifest_id=manifest_id, project_id=project_id, run_id=run_id)

    def _validate_reference_set(self, refs, *, project_id, run_id):
        identities = set()
        for ref in refs:
            identity = (ref.authority_kind, ref.authority_id)
            if identity in identities:
                raise QuantitativeAuthorityChainError("duplicate authority reference")
            identities.add(identity)
            loader = self._loaders.get(ref.authority_kind) or self._loaders.get("*")
            if loader is None:
                raise QuantitativeAuthorityChainError(f"unsupported authority kind: {ref.authority_kind}")
            value = loader(ref.authority_id, project_id=project_id)
            if value is None or getattr(value, "project_id", project_id) != project_id or getattr(value, "run_id", run_id) != run_id:
                raise QuantitativeAuthorityChainError("wrong-project/run or missing authority reference")
            if authority_fingerprint(value) != ref.authority_fingerprint:
                raise QuantitativeAuthorityChainError("authority fingerprint mismatch")

    @classmethod
    def _projection(cls, manifest):
        return QuantitativeDesignAwareAuthorityChainProjection(
            manifest.manifest_id, manifest.fingerprint, manifest.project_id, manifest.run_id,
            manifest.execution_mode, cls.references(manifest),
            manifest.research_question_authorities, manifest.objective_authorities,
            manifest.controlled_absences,
        )
