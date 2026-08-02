from __future__ import annotations

from dataclasses import asdict

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
from infrastructure.persistence.postgresql.models.project_model import ProjectModel


def project_to_model(project: Project, *, version: int) -> ProjectModel:
    return ProjectModel(
        id=project.id,
        name=project.name,
        status=project.status,
        client_request=_client_request_to_dict(project.client_request),
        qualification=_qualification_to_dict(project.qualification),
        brief=_research_brief_to_dict(project.research_brief),
        research_design=_methodology_proposal_to_dict(project.methodology_proposal),
        created_at=project.created_at,
        updated_at=project.updated_at,
        owner_principal_id=project.owner_principal_id,
        version=version,
    )


def project_to_update_values(project: Project) -> dict:
    return {
        "name": project.name,
        "status": project.status,
        "client_request": _client_request_to_dict(project.client_request),
        "qualification": _qualification_to_dict(project.qualification),
        "brief": _research_brief_to_dict(project.research_brief),
        "research_design": _methodology_proposal_to_dict(project.methodology_proposal),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "owner_principal_id": project.owner_principal_id,
    }


def project_from_model(model: ProjectModel) -> Project:
    return Project(
        id=model.id,
        name=model.name,
        status=model.status or ProjectStatus.LEAD,
        client_request=_client_request_from_dict(model.client_request),
        qualification=_qualification_from_dict(model.qualification),
        research_brief=_research_brief_from_dict(model.brief),
        methodology_proposal=_methodology_proposal_from_dict(model.research_design),
        created_at=model.created_at or "",
        updated_at=model.updated_at or "",
        owner_principal_id=model.owner_principal_id,
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


def _research_brief_to_dict(value: ResearchBrief | None) -> dict | None:
    if value is None:
        return None
    return value.to_dict()


def _research_brief_from_dict(payload: dict | None) -> ResearchBrief | None:
    return ResearchBrief.from_dict(payload)


def _methodology_proposal_to_dict(value: MethodologyProposal | None) -> dict | None:
    if value is None:
        return None
    return asdict(value)


def _methodology_proposal_from_dict(payload: dict | None) -> MethodologyProposal | None:
    if payload is None:
        return None
    return MethodologyProposal(
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
