from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import ContainerDep
from application.authority_extension.selected_workflow import ExtensionContractError


router = APIRouter(tags=["authority-extensions"])


class AuthorityExtensionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_source_workflow_run_id: str = Field(min_length=1)
    selected_information_need_ids: list[str] = Field(min_length=1)
    confirmed: bool


class AuthorityExtensionResponse(BaseModel):
    extension_id: str
    workflow_run_id: str
    status: str
    selected_information_need_ids: list[str]
    gap_contract_digest: str


@router.post(
    "/projects/{project_id}/authority-extensions",
    response_model=AuthorityExtensionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(bearer_scheme)],
    summary="Create a bounded selected-information-need authority extension",
)
def create_authority_extension(
    project_id: str,
    body: AuthorityExtensionRequest,
    container: ContainerDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> AuthorityExtensionResponse:
    authorization.require_project(principal, project_id)
    if principal.authentication_type == "browser_session":
        try:
            container.identity_service.require(
                project_id, principal.principal_id, owner=True,
            )
        except (AttributeError, PermissionError) as exc:
            raise HTTPException(status_code=403, detail="OWNER access required") from exc
    parent, _ = authorization.require_run(principal, body.parent_source_workflow_run_id)
    if parent.project_id != project_id:
        raise HTTPException(status_code=404, detail="Parent workflow not found")
    template = container.workflow_service.get_template(parent.workflow_template_id)
    design = template.research_design_snapshot
    if design is None:
        raise HTTPException(status_code=409, detail="Parent workflow has no immutable research design")
    service = container.authority_extension_service
    if service is None:
        raise HTTPException(status_code=503, detail="Authority extension service unavailable")
    try:
        extension = service.start(
            project_id=project_id,
            parent_workflow_run_id=parent.id,
            design=design,
            selected_information_need_ids=body.selected_information_need_ids,
            idempotency_key=idempotency_key,
            confirmed=body.confirmed,
        )
        extension = service.activate(extension.extension_id)
    except ExtensionContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AuthorityExtensionResponse(
        extension_id=extension.extension_id,
        workflow_run_id=extension.extension_workflow_run_id,
        status=extension.status.value,
        selected_information_need_ids=list(extension.selected_information_need_ids),
        gap_contract_digest=extension.gap_contract_digest,
    )
