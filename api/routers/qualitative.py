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
class CorpusRequest(BaseModel): transcript_ids: list[str]; instructions: str = ""
class CodebookRequest(BaseModel): codes: list[dict]; parent_id: str | None = None; status: str = "draft"; memo: str = ""
class CodingRequest(BaseModel): corpus_id: str; codebook_id: str; applications: list[dict]; parent_id: str | None = None; status: str = "accepted"; memo: str = ""
class AiProposalRequest(BaseModel): corpus_id: str; codebook_id: str; batch_key: str; payload: dict
class AiReviewRequest(BaseModel): decision: str
class ThematicRequest(BaseModel): coding_id: str; categories: list[dict] = Field(default_factory=list); themes: list[dict]; parent_id: str | None = None; status: str = "draft"; memo: str = ""
class AiJobRequest(BaseModel): corpus_id: str; codebook_id: str; batch_key: str; kind: str = "coding"; coding_id: str | None = None

def service(container): return container.qualitative_service
def analysis(container): return container.qualitative_analysis_service

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

@router.post("/{run_id}/analysis/corpora", dependencies=[Depends(bearer_scheme)])
def corpus(project_id: str, run_id: str, body: CorpusRequest, container: ContainerDep, principal: PrincipalDep):
    value=analysis(container).create_corpus(project_id,run_id,body.transcript_ids,owner_id=principal.principal_id,instructions=body.instructions)
    return value.payload

@router.post("/{run_id}/analysis/codebooks", dependencies=[Depends(bearer_scheme)])
def codebook(project_id: str, run_id: str, body: CodebookRequest, container: ContainerDep, principal: PrincipalDep):
    return analysis(container).create_codebook(project_id,run_id,body.codes,owner_id=principal.principal_id,
        parent_id=body.parent_id,status=body.status,memo=body.memo).payload

@router.post("/{run_id}/analysis/codings", dependencies=[Depends(bearer_scheme)])
def coding(project_id: str, run_id: str, body: CodingRequest, container: ContainerDep, principal: PrincipalDep):
    return analysis(container).create_coding(project_id,run_id,body.corpus_id,body.codebook_id,body.applications,
        owner_id=principal.principal_id,parent_id=body.parent_id,status=body.status,memo=body.memo).payload

@router.post("/{run_id}/analysis/ai-proposals", dependencies=[Depends(bearer_scheme)])
def ai_proposal(project_id: str, run_id: str, body: AiProposalRequest, container: ContainerDep, principal: PrincipalDep):
    return analysis(container).create_ai_proposal(project_id,run_id,body.corpus_id,body.codebook_id,
        batch_key=body.batch_key,payload=body.payload,owner_id=principal.principal_id).payload

@router.post("/{run_id}/analysis/ai-jobs", dependencies=[Depends(bearer_scheme)])
def ai_job(project_id: str, run_id: str, body: AiJobRequest, container: ContainerDep, principal: PrincipalDep):
    return analysis(container).request_ai_job(project_id,run_id,body.corpus_id,body.codebook_id,
        owner_id=principal.principal_id,batch_key=body.batch_key,kind=body.kind,coding_id=body.coding_id).payload

@router.post("/{run_id}/analysis/ai-jobs/process", dependencies=[Depends(bearer_scheme)])
def process_ai_job(project_id: str, run_id: str, container: ContainerDep, principal: PrincipalDep):
    analysis(container)._owner(project_id,principal.principal_id)
    return {"processed":analysis(container).process_next_job()}

@router.post("/{run_id}/analysis/ai-jobs/{job_id}/retry", dependencies=[Depends(bearer_scheme)])
def retry_ai_job(project_id: str, run_id: str, job_id: str, container: ContainerDep, principal: PrincipalDep):
    value=analysis(container).retry_ai_job(project_id,job_id,owner_id=principal.principal_id)
    if value.run_id != run_id: raise ValueError("Qualitative AI job belongs to another run")
    return value.payload

@router.post("/analysis/ai-proposals/{proposal_id}/review", dependencies=[Depends(bearer_scheme)])
def ai_review(project_id: str, proposal_id: str, body: AiReviewRequest, container: ContainerDep, principal: PrincipalDep):
    return analysis(container).review_ai_proposal(project_id,proposal_id,owner_id=principal.principal_id,decision=body.decision).payload

@router.post("/{run_id}/analysis/themes", dependencies=[Depends(bearer_scheme)])
def thematic(project_id: str, run_id: str, body: ThematicRequest, container: ContainerDep, principal: PrincipalDep):
    return analysis(container).create_thematic_revision(project_id,run_id,body.coding_id,categories=body.categories,
        themes=body.themes,owner_id=principal.principal_id,status=body.status,parent_id=body.parent_id,memo=body.memo).payload

@router.get("/{run_id}/analysis/readiness", dependencies=[Depends(bearer_scheme)])
def analysis_readiness(project_id: str, run_id: str, container: ContainerDep, principal: PrincipalDep):
    return {"readiness":analysis(container).readiness(project_id,run_id,owner_id=principal.principal_id)}

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
