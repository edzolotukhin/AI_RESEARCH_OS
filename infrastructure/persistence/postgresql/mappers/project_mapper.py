from __future__ import annotations

from dataclasses import asdict

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
from infrastructure.persistence.postgresql.models.project_model import ProjectModel


def project_to_model(project: Project, *, version: int) -> ProjectModel:
    return ProjectModel(
        id=project.id,
        name=project.name,
        status=project.status,
        client_request=_client_request_to_dict(project.client_request),
        qualification=_qualification_to_dict(project.qualification),
        brief=_brief_to_dict(project.brief),
        research_design=_research_design_to_dict(project.research_design),
        created_at=project.created_at,
        updated_at=project.updated_at,
        version=version,
    )


def project_to_update_values(project: Project) -> dict:
    return {
        "name": project.name,
        "status": project.status,
        "client_request": _client_request_to_dict(project.client_request),
        "qualification": _qualification_to_dict(project.qualification),
        "brief": _brief_to_dict(project.brief),
        "research_design": _research_design_to_dict(project.research_design),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def project_from_model(model: ProjectModel) -> Project:
    return Project(
        id=model.id,
        name=model.name,
        status=model.status or ProjectStatus.LEAD,
        client_request=_client_request_from_dict(model.client_request),
        qualification=_qualification_from_dict(model.qualification),
        brief=_brief_from_dict(model.brief),
        research_design=_research_design_from_dict(model.research_design),
        created_at=model.created_at or "",
        updated_at=model.updated_at or "",
        runs=[],
    )


def _client_request_to_dict(value: ClientRequest | None) -> dict | None:
    if value is None:
        return None
    return asdict(value)


def _client_request_from_dict(payload: dict | None) -> ClientRequest | None:
    if payload is None:
        return None
    return ClientRequest(**payload)


def _qualification_to_dict(value: ClientQualification | None) -> dict | None:
    if value is None:
        return None
    return asdict(value)


def _qualification_from_dict(payload: dict | None) -> ClientQualification | None:
    if payload is None:
        return None
    return ClientQualification(**payload)


def _brief_to_dict(value: ProjectBrief | None) -> dict | None:
    if value is None:
        return None
    return asdict(value)


def _brief_from_dict(payload: dict | None) -> ProjectBrief | None:
    if payload is None:
        return None
    return ProjectBrief(**payload)


def _research_design_to_dict(value: ResearchDesign | None) -> dict | None:
    if value is None:
        return None
    return asdict(value)


def _research_design_from_dict(payload: dict | None) -> ResearchDesign | None:
    if payload is None:
        return None
    return ResearchDesign(
        business_problem=BusinessProblem(**payload.get("business_problem", {})),
        objectives=ResearchObjectives(**payload.get("objectives", {})),
        strategy=ResearchStrategy(**payload.get("strategy", {})),
        methodology=Methodology(**payload.get("methodology", {})),
        sampling=SamplingPlan(**payload.get("sampling", {})),
        risks=RiskAssessment(
            risks=[
                Risk(**risk)
                for risk in payload.get("risks", {}).get("risks", [])
            ],
        ),
    )
