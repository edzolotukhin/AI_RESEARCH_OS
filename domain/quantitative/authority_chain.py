from __future__ import annotations

from dataclasses import dataclass

from domain.quantitative.research_question_coverage import QuantitativeAuthorityReference


AUTHORITY_CHAIN_METHOD_VERSION = "q2-10.2-1"


@dataclass(frozen=True)
class QuantitativeDesignAwareAuthorityChainManifest:
    manifest_id: str
    project_id: str
    run_id: str
    execution_mode: str
    source_brief: QuantitativeAuthorityReference
    research_design: QuantitativeAuthorityReference
    questionnaire: QuantitativeAuthorityReference
    reconciliation: QuantitativeAuthorityReference
    analysis_plan: QuantitativeAuthorityReference
    analysis_execution: tuple[QuantitativeAuthorityReference, ...]
    finding_authority: tuple[QuantitativeAuthorityReference, ...]
    insight_authority: tuple[QuantitativeAuthorityReference, ...]
    report_authority: tuple[QuantitativeAuthorityReference, ...]
    research_question_authorities: tuple[QuantitativeAuthorityReference, ...]
    objective_authorities: tuple[QuantitativeAuthorityReference, ...]
    dataset: QuantitativeAuthorityReference
    codebook: QuantitativeAuthorityReference
    qc_authority: QuantitativeAuthorityReference
    weight_set_authorities: tuple[QuantitativeAuthorityReference, ...]
    controlled_absences: tuple[QuantitativeAuthorityReference, ...]
    method_version: str
    fingerprint: str


@dataclass(frozen=True)
class QuantitativeDesignAwareAuthorityChainProjection:
    manifest_id: str
    manifest_fingerprint: str
    project_id: str
    run_id: str
    execution_mode: str
    ordered_authorities: tuple[QuantitativeAuthorityReference, ...]
    research_question_authorities: tuple[QuantitativeAuthorityReference, ...]
    objective_authorities: tuple[QuantitativeAuthorityReference, ...]
    controlled_absences: tuple[QuantitativeAuthorityReference, ...]
