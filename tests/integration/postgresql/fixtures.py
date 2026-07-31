"""Rich domain fixtures for PostgreSQL integration tests."""

from __future__ import annotations

from domain.client_qualification import ClientQualification
from domain.client_request import ClientRequest
from domain.project import Project
from domain.project_brief import ProjectBrief
from domain.research_design import (
    BusinessProblem,
    Methodology,
    ResearchDesign,
    ResearchObjectives,
    ResearchStrategy,
    Risk,
    RiskAssessment,
    SamplingPlan,
)
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
        brief=ProjectBrief(
            client="Acme GmbH",
            project_title="Pricing Research",
            business_problem="Launch price unknown",
            research_goal="Determine optimal price band",
            research_objectives=["Assess WTP", "Map competitor prices"],
            research_object="Premium widget",
            target_audience="Buyers 25-45",
            geography="Germany",
            constraints=["4-week timeline"],
            timeline="Q4 2026",
            comments="Prefer online panel",
            attachments=["brief.pdf"],
        ),
        research_design=ResearchDesign(
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

    assert expected.brief is not None
    assert actual.brief is not None
    assert actual.brief == expected.brief

    assert expected.research_design is not None
    assert actual.research_design is not None
    assert actual.research_design == expected.research_design
