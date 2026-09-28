"""Tracked, offline design-aware Quant authority fixture for PostgreSQL acceptance."""

from pathlib import Path

from domain.quantitative.analysis import AnalysisSpecification
from domain.quantitative.analysis_plan import (
    AnalysisExecutionSupport, AnalysisWeightingPolicy, PlanVariableBinding,
    PlannedAnalysis,
)
from domain.quantitative.dataset import CodebookVersion, DatasetVersion
from domain.quantitative.measurement_reconciliation import ReviewedMeasurementMapping
from domain.quantitative.questionnaire_authority import (
    AnswerOption, ExpectedVariableBinding, QuestionnaireAuthorshipMode,
    QuestionnaireQuestion, QuestionnaireQuestionRole, QuestionnaireQuestionType,
    QuestionnaireSection,
)
from domain.quantitative.research_design_authority import (
    AnalyticalRequirement, DeliverableRequirement, MethodologyIntent,
    QuantitativeResearchQuestion, RequirementObligation, ResearchObjective,
    ResearchPriority, TargetPopulation,
)


OWNER = "qnt02-owner"
SAV = (Path(__file__).parent / "rb_reconciliation.sav").read_bytes()


def prepare_bound_analysis(app, *, study=None):
    """Create only canonical synthetic authority, then pause before semantic generation."""
    ui = app.quantitative_ui_service
    if study is None:
        study = ui.create_study(
            owner_id=OWNER, title="Synthetic QNT-02 fixture",
            description="Offline authority", submission_key="qnt02-bound-analysis",
        )
    scope = {"project_id": study.project_id, "run_id": study.run_id}
    designs = app.quantitative_authority_finalization_service._designs
    brief = designs.create_brief(
        brief_id="brief", version_id="brief-v1", **scope, title="Choice",
        business_context="Synthetic study", business_problem="Understand choice",
        decision_context="Describe choice", research_purpose="Describe choice distribution",
        intended_audience=("Research",), target_deliverables=("Report",),
        constraints=("Synthetic",), provenance="TEST_AUTHORED", created_at="t1",
        created_by="author",
    )
    brief = designs.submit_brief_for_review(
        brief.version_id, **scope, new_version_id="brief-review",
        actor_id="reviewer", changed_at="t2",
    )
    brief = designs.approve_brief(
        brief.version_id, **scope, new_version_id="brief-approved",
        approval_id="brief-approval", expected_fingerprint=brief.fingerprint,
        actor_id="owner", decided_at="t3", rationale="Reviewed",
    )
    objective = ResearchObjective("objective", "Describe choice", ResearchPriority.HIGH)
    question = QuantitativeResearchQuestion(
        "rq", "What choices are measured?", ("objective",), "DISTRIBUTION",
        ResearchPriority.HIGH,
    )
    requirement = AnalyticalRequirement(
        "ar", "ONE_WAY", "Describe choice distribution", ("objective",),
        ("rq",), RequirementObligation.MANDATORY,
    )
    design = designs.create_design(
        design_id="design", version_id="design-v1", **scope,
        source_brief_version_id=brief.version_id,
        source_brief_fingerprint=brief.fingerprint,
        objectives=(objective,), research_questions=(question,), hypotheses=(),
        target_population=TargetPopulation(("Synthetic",), ("Adults",), ()),
        methodology_intent=MethodologyIntent(
            "QUANTITATIVE", "EXTERNAL_SURVEY", "Synthetic", "UNWEIGHTED"
        ),
        analytical_requirements=(requirement,),
        deliverable_requirements=(DeliverableRequirement(
            "report", "REPORT", "Research", "en", RequirementObligation.MANDATORY
        ),),
        assumptions=("Synthetic data",), limitations=("Fixture",),
        created_at="t4", created_by="author",
    )
    design = designs.submit_for_review(
        design.version_id, **scope, new_version_id="design-review",
        actor_id="reviewer", changed_at="t5",
    )
    design = designs.approve(
        design.version_id, **scope, new_version_id="design-approved",
        approval_id="design-approval", expected_fingerprint=design.fingerprint,
        actor_id="owner", decided_at="t6", rationale="Reviewed",
    )
    questionnaires = app.quantitative_authority_finalization_service._questionnaires
    questionnaire_question = QuestionnaireQuestion(
        "choice", "main", QuestionnaireQuestionRole.SUBSTANTIVE,
        QuestionnaireQuestionType.SINGLE_CHOICE, "Choice?", None, None,
        ("ar",), None, True,
        (AnswerOption("yes", "Yes", "1", 1), AnswerOption("no", "No", "2", 2)),
        None, (), (), (ExpectedVariableBinding("ev", "categorical"),), True,
        1, "team",
    )
    questionnaire = questionnaires.create_draft(
        questionnaire_id="q", version_id="q-v1", **scope,
        research_design_version_id=design.version_id,
        research_design_fingerprint=design.fingerprint,
        title="Choice", purpose="Measure choice", language="en",
        sections=(QuestionnaireSection("main", "Main", "Core", 1),),
        questions=(questionnaire_question,), routing_rules=(),
        provenance="TEST_AUTHORED",
        authorship_mode=QuestionnaireAuthorshipMode.INTERNAL_HUMAN,
        estimated_interview_length_minutes=2, assumptions=(), limitations=(),
        created_at="t7", created_by="author",
    )
    questionnaire = questionnaires.submit_for_review(
        questionnaire.version_id, **scope, new_version_id="q-review",
        actor_id="reviewer", changed_at="t8",
    )
    questionnaire = questionnaires.approve(
        questionnaire.version_id, **scope, new_version_id="q-approved",
        approval_id="q-approval", expected_fingerprint=questionnaire.fingerprint,
        expected_validation_fingerprint=questionnaire.validation_manifest_fingerprint,
        expected_coverage_fingerprint=questionnaire.coverage_manifest_fingerprint,
        actor_id="owner", decided_at="t9", rationale="Reviewed",
    )
    if not study.dataset_record_id:
        study = ui.upload(study.study_id, owner_id=OWNER,
                          filename="synthetic.sav", content=SAV)
    dataset = ui.state.load(
        study.dataset_record_id, project_id=study.project_id,
        expected_type=DatasetVersion,
    )
    codebook = ui.state.load(
        study.codebook_record_id, project_id=study.project_id,
        expected_type=CodebookVersion,
    )
    study = ui.run_default_qc(study.study_id, owner_id=OWNER)
    qc = ui.state.load(study.qc_record_id, project_id=study.project_id)
    study = ui.approve_qc(
        study.study_id, owner_id=OWNER, actor_id="owner",
        fingerprint=qc.fingerprint, decision="APPROVED", rationale="Reviewed",
    )
    reconciliations = app.quantitative_authority_finalization_service._reconciliations
    candidate = reconciliations.create(
        reconciliation_id="rb", version_id="rb-v1", **scope,
        dataset=dataset, codebook=codebook, created_at="t10", created_by="system",
    )
    expected = questionnaires.derive_expected_measurement_schema(
        questionnaire.version_id, project_id=study.project_id
    ).variables[0]
    actual = next(
        item for item in codebook.variables
        if item.variable_id == candidate.variable_outcomes[0].actual_variable_id
    )
    codes = tuple((str(code), str(code)) for code, _ in expected.value_labels)
    mapping = ReviewedMeasurementMapping(
        "mapping", expected.expected_variable_id, expected.fingerprint,
        actual.variable_id, actual.fingerprint, codes, (("9", "9"),),
        codes, (), "reviewer", "Synthetic labels and missing semantics reviewed",
        "t11", "review-ev",
    )
    reviewed = reconciliations.create(
        reconciliation_id="rb", version_id="rb-reviewed", **scope,
        dataset=dataset, codebook=codebook, created_at="t12",
        created_by="reviewer", reviewed_mappings=(mapping,),
        parent_version_id=candidate.version_id,
    )
    accepted = reconciliations.approve(
        reviewed.version_id, **scope, approval_id="rb-approval",
        expected_fingerprint=reviewed.fingerprint, actor_id="owner",
        decided_at="t13", rationale="Reviewed", dataset=dataset,
        codebook=codebook,
    )
    outcome = accepted.variable_outcomes[0]
    binding = PlanVariableBinding(
        outcome.expected_variable_id, outcome.actual_variable_id,
        outcome.actual_variable_fingerprint,
    )
    analysis = PlannedAnalysis(
        "pa", AnalysisSpecification("spec", binding.actual_variable_id), "",
        ("objective",), ("rq",), ("ar",), (binding,), "TOTAL_DISTRIBUTION",
        "MANDATORY", AnalysisWeightingPolicy.UNWEIGHTED, None, None, (), (),
        AnalysisExecutionSupport.SUPPORTED,
    )
    plans = app.quantitative_authority_finalization_service._plans
    plan = plans.create_draft(
        plan_id="plan", version_id="plan-v1", **scope, dataset=dataset,
        codebook=codebook, planned_analyses=(analysis,), planned_comparisons=(),
        created_at="t14", created_by="author",
    )
    plan = plans.submit_for_review(
        plan.version_id, **scope, new_version_id="plan-review",
        actor_id="reviewer", changed_at="t15",
    )
    plan = plans.approve(
        plan.version_id, **scope, new_version_id="plan-approved",
        approval_id="plan-approval", expected_fingerprint=plan.fingerprint,
        actor_id="owner", decided_at="t16", rationale="Reviewed",
        dataset=dataset, codebook=codebook,
    )
    activated = ui.activate_design_aware_workflow(study.study_id, owner_id=OWNER)
    if activated.state != "ANALYZING":
        raise AssertionError(f"Unexpected Quant activation state: {activated.state}")
    return {
        "study_id": study.study_id,
        "project_id": study.project_id,
        "run_id": study.run_id,
        "dataset_version_id": dataset.version_id,
        "dataset_fingerprint": dataset.dataset_fingerprint,
        "plan_version_id": plan.version_id,
        "plan_fingerprint": plan.fingerprint,
    }
