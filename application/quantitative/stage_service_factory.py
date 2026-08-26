from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from application.quantitative.analysis_execution import QuantitativeAnalysisExecutionService
from application.quantitative.quality_control import assess_dataset_quality
from application.quantitative.finding_generation import (
    QuantitativeFindingGenerationService,
)
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.finding_lineage import QuantitativeFindingLineageService
from application.quantitative.insight_lineage import QuantitativeInsightLineageService
from application.quantitative.report_lineage import QuantitativeReportLineageService
from application.quantitative.research_question_coverage import QuantitativeResearchQuestionCoverageService
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
from domain.quantitative.quality import QualityControlRun
from domain.quantitative.weighting import WeightSet, WeightSetApproval
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
    analysis_plan_service: Any | None = None
    analysis_execution_repository_factory: Callable[[], Any] | None = None
    finding_lineage_repository_factory: Callable[[], Any] | None = None
    insight_lineage_repository_factory: Callable[[], Any] | None = None
    report_lineage_repository_factory: Callable[[], Any] | None = None
    research_question_coverage_repository_factory: Callable[[], Any] | None = None

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
        mode=state.get("analysis_execution_mode","DATASET_ONLY_EXPLORATORY_EXECUTION")
        storage=self.storage_factory(project_id,run_id)
        current_plan=None
        execution_service=None; projection=None; execution_weights={}
        if self.analysis_execution_repository_factory is not None:
            execution_service=QuantitativeAnalysisExecutionService(repository=self.analysis_execution_repository_factory(),state_service=self.state_service,storage=storage,digest_provider=self.digest_provider)
        finding_lineage_service=None
        if self.finding_lineage_repository_factory is not None and execution_service is not None:
            finding_lineage_service=QuantitativeFindingLineageService(repository=self.finding_lineage_repository_factory(),analysis_execution_repository=execution_service.repository,state_service=self.state_service,digest_provider=self.digest_provider)
        insight_lineage_service=None
        if self.insight_lineage_repository_factory is not None:
            insight_lineage_service=QuantitativeInsightLineageService(repository=self.insight_lineage_repository_factory(),digest_provider=self.digest_provider)
        report_lineage_service=None
        if self.report_lineage_repository_factory is not None:
            report_lineage_service=QuantitativeReportLineageService(repository=self.report_lineage_repository_factory(),digest_provider=self.digest_provider)
        research_question_coverage_service=None
        if self.research_question_coverage_repository_factory is not None:
            research_question_coverage_service=QuantitativeResearchQuestionCoverageService(
                repository=self.research_question_coverage_repository_factory(), digest_provider=self.digest_provider,
                state_service=self.state_service, analysis_plan_service=self.analysis_plan_service,
                analysis_execution_repository=getattr(execution_service,"repository",None),
                finding_lineage_repository=getattr(finding_lineage_service,"repository",None),
                insight_lineage_repository=getattr(insight_lineage_service,"repository",None),
                report_lineage_repository=getattr(report_lineage_service,"repository",None),
            )
        if mode=="DESIGN_AWARE_EXECUTION":
            if self.analysis_plan_service is None or execution_service is None: raise QuantitativeWorkflowError("design-aware Quantitative execution composition is unavailable")
            qc=self.state_service.load(state.get("qc_record_id",""),project_id=project_id,expected_type=QualityControlRun)
            approvals=QuantitativeApprovalService(self.state_service,self.digest_provider)
            qc_approval_id=state.get("cleaned_qc_approval_id") or state.get("qc_approval_id","")
            qc_approval=approvals.require_current(qc_approval_id,project_id=project_id,subject_fingerprint=qc.fingerprint)
            quality=assess_dataset_quality(dataset=dataset,qc_run=qc,manager_approved=True,approval_fingerprint=qc_approval.fingerprint,digest_provider=self.digest_provider)
            plans=self.analysis_plan_service._repository.list_plans(project_id=project_id,run_id=run_id)
            if not plans: raise QuantitativeWorkflowError("approved Analysis Plan is unavailable")
            current=plans[-1]
            current_plan=current
            weight_sets={x.weight_set_id:x for x in self.state_service.list_for_run(run_id,project_id=project_id,expected_type=WeightSet)}
            weight_approvals={x.weight_set_id:x for x in self.state_service.list_for_run(run_id,project_id=project_id,expected_type=WeightSetApproval) if x.state.value=="APPROVED"}
            for item in current.planned_analyses:
                binding=item.weight_set_binding
                if binding is not None and binding.weight_set_id in weight_sets and binding.weight_set_id in weight_approvals: execution_weights[item.planned_analysis_id]=(weight_sets[binding.weight_set_id],weight_approvals[binding.weight_set_id])
            projection=self.analysis_plan_service.execution_projection(project_id=project_id,run_id=run_id,dataset=dataset,codebook=codebook,quality_assessment=quality,weight_sets=execution_weights)
            plan=self._build_design_plan(run_id=run_id,dataset=dataset,codebook=codebook)
        elif mode=="DATASET_ONLY_EXPLORATORY_EXECUTION": plan=self._build_plan(run_id=run_id,dataset=dataset,codebook=codebook)
        else: raise QuantitativeWorkflowError("unknown Quantitative analysis execution mode")
        approvals=QuantitativeApprovalService(self.state_service,self.digest_provider)
        return RealQuantitativeStageService(
            plan=plan,
            storage=storage,
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
            analysis_execution_service=execution_service,
            analysis_execution_projection=projection,
            analysis_execution_weights=execution_weights,
            finding_lineage_service=finding_lineage_service,
            insight_lineage_service=insight_lineage_service,
            report_lineage_service=report_lineage_service,
            research_question_coverage_service=research_question_coverage_service,
            analysis_plan_authority=current_plan,
        )

    def _build_design_plan(self,*,run_id,dataset,codebook):
        questionnaire=build_questionnaire_snapshot(snapshot_id=f"questionnaire-{run_id}-rd",version="RD-1",codebook_version_id=codebook.codebook_version_id,question_variable_bindings=(),digest_provider=self.digest_provider)
        return QuantitativeVerticalPlan(b"","already-imported.sav",dataset.dataset_id,{},questionnaire,(),"",None,None,None,None,weight_mode="CONSTRUCT_FROM_TARGET_MARGINS")

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
