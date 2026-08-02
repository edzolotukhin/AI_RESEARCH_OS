"""Rich domain fixtures for PostgreSQL integration tests."""

from __future__ import annotations

from domain.client_qualification import ClientQualification
from domain.client_request import ClientRequest
from domain.legacy.methodology_proposal import (
    BusinessProblem,
    Methodology,
    MethodologyProposal,
    ResearchObjectives,
    ResearchStrategy,
    Risk,
    RiskAssessment,
    SamplingPlan,
)
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.value_objects.project_status import ProjectStatus


def build_rich_project(project_id: str = "project-rich") -> Project:
    """Construct a Project with all currently durable nested fields populated."""
    return Project(
        id=project_id,
        name="Unicode research — étude 日本語",
        status=ProjectStatus.RESEARCH_DESIGN,
        client_request=ClientRequest(
            source="referral",
            client_name="Acme GmbH",
            contact_person="María López",
            contact_email="maria@acme.example",
            contact_phone="+49-30-123456",
            message="Need pricing research with emoji 🎯",
        ),
        qualification=ClientQualification(
            summary="Qualified lead",
            project_understanding="Pricing study for DACH",
            understanding_score=87,
            project_state="qualified",
            next_question="Confirm sample size",
            missing_information=["budget", "timeline detail"],
        ),
        research_brief=ResearchBrief(
            title="Pricing Research",
            business_question="Launch price unknown",
            objectives=("Assess WTP", "Map competitor prices"),
            geography=("Germany",),
            target_entities=("Premium widget", "Buyers 25-45"),
            timeframe="Q4 2026",
            constraints=("4-week timeline",),
            context="Acme GmbH Prefer online panel",
            language="en",
        ),
        methodology_proposal=MethodologyProposal(
            business_problem=BusinessProblem(
                description="Price sensitivity for launch",
                business_decision="Set launch price",
            ),
            objectives=ResearchObjectives(
                primary="Estimate optimal price",
                secondary=["Segment differences"],
            ),
            strategy=ResearchStrategy(
                recommendation="Quant survey",
                rationale="Need statistical pricing model",
                alternatives=["Qual interviews"],
            ),
            methodology=Methodology(
                methods=["online survey"],
                target_audience="Recent buyers",
                geography="Germany",
                timeline="4 weeks",
            ),
            sampling=SamplingPlan(
                sample_size=800,
                sampling_method="random panel",
                quotas=["50% male", "50% female"],
            ),
            risks=RiskAssessment(
                risks=[
                    Risk(
                        description="Low incidence",
                        mitigation="Boost sample",
                    ),
                ],
            ),
        ),
        created_at="2026-07-31T08:00:00+00:00",
        updated_at="2026-07-31T09:30:00+00:00",
        runs=[],
    )


def assert_projects_semantically_equal(
    expected: Project,
    actual: Project,
) -> None:
    assert actual.id == expected.id
    assert actual.name == expected.name
    assert actual.status == expected.status
    assert actual.created_at == expected.created_at
    assert actual.updated_at == expected.updated_at
    assert actual.runs == []

    assert expected.client_request is not None
    assert actual.client_request is not None
    assert actual.client_request == expected.client_request

    assert expected.qualification is not None
    assert actual.qualification is not None
    assert actual.qualification == expected.qualification

    assert expected.research_brief is not None
    assert actual.research_brief is not None
    assert actual.research_brief == expected.research_brief

    assert expected.methodology_proposal is not None
    assert actual.methodology_proposal is not None
    assert actual.methodology_proposal == expected.methodology_proposal
