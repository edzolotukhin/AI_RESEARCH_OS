from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from application.quantitative.finding_generation import (
    QuantitativeFindingGenerationService,
)
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.insight_synthesis import (
    QuantitativeInsightSynthesisService,
    QuantitativeInsightValidator,
)
from application.quantitative.quality_control import build_questionnaire_snapshot
from application.quantitative.report_composition import (
    QuantitativeReportCompositionService,
    QuantitativeReportValidator,
)
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.vertical_service import (
    QuantitativeVerticalPlan,
    RealQuantitativeStageService,
)
from application.quantitative.workflow import (
    QUANTITATIVE_SAFE_STATE_KEY,
    QUANTITATIVE_STAGE_SERVICE_KEY,
    QUANTITATIVE_WORKFLOW_ID,
    QuantitativeApprovalService,
    QuantitativeWorkflowError,
    validate_safe_workflow_state,
)
from domain.quantitative.analysis import (
    AnalysisSpecification,
    CrossTabAnalysisSpecification,
    NpsAnalysisSpecification,
    NumericAnalysisSpecification,
)
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, VariableType
from domain.workflow_status import WorkflowStatus
from runtime.workflow_context import WorkflowContext


@dataclass(frozen=True)
class QuantitativeStageServiceFactory:
    """Rebuild the run-scoped Quantitative authority from durable identifiers."""

    state_service: QuantitativeStateService
    digest_provider: Any
    storage_factory: Callable[[str, str], Any]
    importers: tuple[Any, ...]
    finding_generator: Any
    insight_generator: Any
    report_generator: Any
    generation_mode: str

    def create(
        self,
        *,
        project_id: str,
        run_id: str,
        safe_state: Mapping[str, object],
    ) -> RealQuantitativeStageService:
        if not project_id or not run_id:
            raise QuantitativeWorkflowError("Quantitative project/run identity is required")
        state = validate_safe_workflow_state(safe_state)
        scoped_record_ids = {
            value
            for key, value in state.items()
            if key.endswith("_record_id") or key.endswith("_approval_id")
        }
        for record_id in scoped_record_ids:
            self.state_service.require_record_scope(
                record_id,
                project_id=project_id,
                run_id=run_id,
            )
        dataset_record_id = state.get("dataset_record_id")
        codebook_record_id = state.get("codebook_record_id")
        if not dataset_record_id or not codebook_record_id:
            raise QuantitativeWorkflowError(
                "Durable Quantitative dataset authority is unavailable"
            )
        dataset = self.state_service.load(
            dataset_record_id,
            project_id=project_id,
            expected_type=DatasetVersion,
        )
        codebook = self.state_service.load(
            codebook_record_id,
            project_id=project_id,
            expected_type=CodebookVersion,
        )
        plan = self._build_plan(run_id=run_id, dataset=dataset, codebook=codebook)
        approvals = QuantitativeApprovalService(self.state_service, self.digest_provider)
        return RealQuantitativeStageService(
            plan=plan,
            storage=self.storage_factory(project_id, run_id),
            digest_provider=self.digest_provider,
            state_service=self.state_service,
            approval_service=approvals,
            finding_service=QuantitativeFindingGenerationService(
                generator=self.finding_generator,
                support_validator=QuantitativeFindingSupportValidator(
                    digest_provider=self.digest_provider
                ),
                digest_provider=self.digest_provider,
            ),
            insight_service=QuantitativeInsightSynthesisService(
                generator=self.insight_generator,
                validator=QuantitativeInsightValidator(
                    digest_provider=self.digest_provider
                ),
                digest_provider=self.digest_provider,
            ),
            report_service=QuantitativeReportCompositionService(
                generator=self.report_generator,
                validator=QuantitativeReportValidator(
                    digest_provider=self.digest_provider
                ),
                digest_provider=self.digest_provider,
            ),
            importers=self.importers,
            generation_mode=self.generation_mode,
        )

    def _build_plan(
        self,
        *,
        run_id: str,
        dataset: DatasetVersion,
        codebook: CodebookVersion,
    ) -> QuantitativeVerticalPlan:
        categoricals = [
            item
            for item in codebook.variables
            if item.variable_type is VariableType.CATEGORICAL
            and item.analytically_eligible
        ]
        numerics = [
            item
            for item in codebook.variables
            if item.variable_type is VariableType.NUMERIC and item.analytically_eligible
        ]
        if len(categoricals) < 2 or not numerics:
            raise QuantitativeWorkflowError(
                "Dataset lacks the required deterministic analysis variables"
            )
        row = next(
            (item for item in categoricals if item.name == "mylabl"),
            categoricals[0],
        )
        column = next(
            (item for item in categoricals if item.name == "myord"),
            categoricals[1],
        )
        numeric = numerics[0]
        questionnaire = build_questionnaire_snapshot(
            snapshot_id=f"questionnaire-{run_id}-terminal",
            version="QO-1",
            codebook_version_id=codebook.codebook_version_id,
            question_variable_bindings=tuple(
                (item.name, item.variable_id) for item in codebook.variables
            ),
            answer_domains=((numeric.variable_id, (0, 7, 8, 9, 10)),),
            digest_provider=self.digest_provider,
        )
        return QuantitativeVerticalPlan(
            b"",
            "already-imported.sav",
            dataset.dataset_id,
            {},
            questionnaire,
            (),
            "",
            AnalysisSpecification("qo-one-way", row.variable_id),
            CrossTabAnalysisSpecification(
                "qo-cross-tab",
                row.variable_id,
                weighting_status="WEIGHTED",
                column_variable_id=column.variable_id,
            ),
            NumericAnalysisSpecification(
                "qo-numeric", numeric.variable_id, weighting_status="WEIGHTED"
            ),
            NpsAnalysisSpecification(
                "qo-nps", numeric.variable_id, weighting_status="WEIGHTED"
            ),
            weight_mode="CONSTRUCT_FROM_TARGET_MARGINS",
        )


@dataclass(frozen=True)
class QuantitativeWorkflowContextServiceResolver:
    """Hydrate ephemeral services after durable workflow state is restored."""

    factory: QuantitativeStageServiceFactory

    def resolve(self, context: WorkflowContext) -> Mapping[str, object]:
        if context.workflow_run.workflow_template_id != QUANTITATIVE_WORKFLOW_ID:
            return {}
        if context.workflow_run.status is WorkflowStatus.PAUSED:
            return {}
        safe_state = context.shared_state.get(QUANTITATIVE_SAFE_STATE_KEY, {})
        if not isinstance(safe_state, Mapping):
            raise QuantitativeWorkflowError("Durable Quantitative state is invalid")
        return {
            QUANTITATIVE_STAGE_SERVICE_KEY: self.factory.create(
                project_id=context.project.id,
                run_id=context.workflow_run.id,
                safe_state=safe_state,
            )
        }
