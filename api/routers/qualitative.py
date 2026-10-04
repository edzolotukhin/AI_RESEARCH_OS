from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from api.auth import PrincipalDep, bearer_scheme
from api.dependencies import ContainerDep

router = APIRouter(prefix="/projects/{project_id}/qualitative", tags=["qualitative"])

class ParticipantRequest(BaseModel): pseudonym: str
class ConsentRequest(BaseModel): participant_id: str; state: str; context: str; researcher_attested: bool = False
class SessionRequest(BaseModel): participant_id: str; context: str = ""
class TranscriptDerivationRequest(BaseModel):
    segment_text: dict[str,str] = Field(default_factory=dict)
    speaker_roles: dict[str,str] = Field(default_factory=dict)
    clean: bool = False
    redacted: bool = True

def service(container): return container.qualitative_service

@router.post("/runs", dependencies=[Depends(bearer_scheme)])
def create_run(project_id: str, container: ContainerDep, principal: PrincipalDep):
    value = service(container).create_run(project_id, owner_id=principal.principal_id)
    return {"run_id":value.record_id,"method_id":"QUALITATIVE","method_version":"1"}

@router.post("/{run_id}/participants", dependencies=[Depends(bearer_scheme)])
def participant(project_id: str, run_id: str, body: ParticipantRequest, container: ContainerDep, principal: PrincipalDep):
    return service(container).create_participant(project_id, run_id, body.pseudonym, owner_id=principal.principal_id)

@router.post("/{run_id}/consents", dependencies=[Depends(bearer_scheme)])
def consent(project_id: str, run_id: str, body: ConsentRequest, container: ContainerDep, principal: PrincipalDep):
    return service(container).record_consent(project_id, run_id, body.participant_id, body.state, body.context,
        owner_id=principal.principal_id, attested=body.researcher_attested)

@router.post("/{run_id}/sessions", dependencies=[Depends(bearer_scheme)])
def session(project_id: str, run_id: str, body: SessionRequest, container: ContainerDep, principal: PrincipalDep):
    return service(container).create_session(project_id, run_id, body.participant_id, body.context,
                                              owner_id=principal.principal_id)

@router.post("/{run_id}/sessions/{session_id}/artifacts", dependencies=[Depends(bearer_scheme)])
async def upload(project_id: str, run_id: str, session_id: str, container: ContainerDep, principal: PrincipalDep,
                 artifact: UploadFile = File(...)):
    source, result = service(container).upload(project_id, run_id, session_id, filename=artifact.filename or "",
        media_type=artifact.content_type or "application/octet-stream", content=await artifact.read(),
        owner_id=principal.principal_id)
    result_id = result.transcript_version_id if hasattr(result, "transcript_version_id") else result.record_id
    return {"artifact_id":source.artifact_id, "result_id":result_id,
            "source_mode":"audio" if source.kind.value == "audio" else "prepared_transcript"}

@router.post("/{run_id}/jobs/{job_id}/process", dependencies=[Depends(bearer_scheme)])
def process(project_id: str, run_id: str, job_id: str, container: ContainerDep, principal: PrincipalDep):
    value = service(container).process_job(project_id, job_id, owner_id=principal.principal_id)
    return {"transcript_version_id":value.transcript_version_id}

@router.get("/{run_id}", dependencies=[Depends(bearer_scheme)])
def detail(project_id: str, run_id: str, container: ContainerDep, principal: PrincipalDep):
    records = service(container).records(project_id, run_id, owner_id=principal.principal_id)
    return {"run_id":run_id,"readiness":service(container).readiness(project_id,run_id,owner_id=principal.principal_id).value,
            "records":[{"id":x.record_id,"type":x.record_type,"payload":{k:v for k,v in x.payload.items() if k != "private_bytes"}} for x in records]}

@router.post("/transcripts/{transcript_id}/exports", dependencies=[Depends(bearer_scheme)])
def export(project_id: str, transcript_id: str, container: ContainerDep, principal: PrincipalDep):
    value = service(container).export_docx(project_id, transcript_id, owner_id=principal.principal_id)
    return {"export_id":value.record_id,"checksum":value.checksum,"filename":value.payload["filename"]}

@router.post("/transcripts/{transcript_id}/versions", dependencies=[Depends(bearer_scheme)])
def derive(project_id: str, transcript_id: str, body: TranscriptDerivationRequest,
           container: ContainerDep, principal: PrincipalDep):
    value=service(container).derive_transcript(project_id,transcript_id,owner_id=principal.principal_id,
        segment_text=body.segment_text,speaker_roles=body.speaker_roles,clean=body.clean,redacted=body.redacted)
    return {"transcript_version_id":value.transcript_version_id,"version":value.version,
            "parent_version_id":value.parent_version_id,"kind":value.kind.value}

@router.get("/exports/{export_id}", dependencies=[Depends(bearer_scheme)])
def download(project_id: str, export_id: str, container: ContainerDep, principal: PrincipalDep):
    value = service(container).download(project_id, export_id, owner_id=principal.principal_id)
    return Response(value.payload["private_bytes"], media_type=value.payload["media_type"], headers={
        "Content-Disposition":f'attachment; filename="{value.payload["filename"]}"', "Cache-Control":"private, no-store"})
