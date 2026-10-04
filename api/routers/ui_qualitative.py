from pathlib import Path
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from api.ui.principal import resolve_ui_principal

router = APIRouter(prefix="/ui/projects/{project_id}/qualitative", tags=["qualitative-ui"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

def _ctx(request, project_id, run_id, error=None):
    owner = resolve_ui_principal(request.app.state.container).principal_id
    service = request.app.state.container.qualitative_service
    return {"request":request,"project_id":project_id,"run_id":run_id,"error":error,
            "records":service.records(project_id,run_id,owner_id=owner),
            "readiness":service.readiness(project_id,run_id,owner_id=owner).value,
            "analysis_readiness":request.app.state.container.qualitative_analysis_service.readiness(
                project_id,run_id,owner_id=owner)}

@router.get("/{run_id}", response_class=HTMLResponse)
def detail(request: Request, project_id: str, run_id: str):
    return templates.TemplateResponse(request,"qualitative/detail.html",_ctx(request,project_id,run_id))

@router.post("/{run_id}/participants")
def participant(request: Request, project_id: str, run_id: str, pseudonym: str = Form(...)):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_service.create_participant(project_id,run_id,pseudonym,owner_id=owner)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/consents")
def consent(request: Request, project_id: str, run_id: str, participant_id: str=Form(...), state: str=Form(...), context: str=Form("")):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_service.record_consent(project_id,run_id,participant_id,state,context,owner_id=owner,attested=True)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/sessions")
def session(request: Request, project_id: str, run_id: str, participant_id: str=Form(...), context: str=Form("")):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_service.create_session(project_id,run_id,participant_id,context,owner_id=owner)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/sessions/{session_id}/artifacts")
async def artifact(request: Request, project_id: str, run_id: str, session_id: str, artifact: UploadFile=File(...)):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_service.upload(project_id,run_id,session_id,filename=artifact.filename or "",media_type=artifact.content_type or "application/octet-stream",content=await artifact.read(),owner_id=owner)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/jobs/{job_id}")
def process(request: Request, project_id: str, run_id: str, job_id: str):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_service.process_job(project_id,job_id,owner_id=owner)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/analysis/corpora")
def corpus(request: Request, project_id: str, run_id: str, transcript_ids: list[str]=Form(...), instructions: str=Form("")):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_analysis_service.create_corpus(
        project_id,run_id,transcript_ids,owner_id=owner,instructions=instructions)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/analysis/codebooks")
def codebook(request: Request, project_id: str, run_id: str, label: str=Form(...), definition: str=Form(...), origin: str=Form("human")):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_analysis_service.create_codebook(
        project_id,run_id,[{"label":label,"definition":definition,"origin":origin}],owner_id=owner)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/analysis/codings")
def coding(request: Request, project_id: str, run_id: str, corpus_id: str=Form(...), codebook_id: str=Form(...),
           code_id: str=Form(...), transcript_id: str=Form(...), transcript_checksum: str=Form(...),
           segment_id: str=Form(...), start: int=Form(...), end: int=Form(...), memo: str=Form("")):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_analysis_service.create_coding(project_id,run_id,corpus_id,codebook_id,[{
        "code_id":code_id,"transcript_version_id":transcript_id,"transcript_checksum":transcript_checksum,
        "segment_id":segment_id,"start":start,"end":end,"memo":memo,"origin":"human","review_state":"accepted"}],
        owner_id=owner,status="accepted")
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/analysis/ai-jobs")
def ai_job(request: Request, project_id: str, run_id: str, corpus_id: str=Form(...), codebook_id: str=Form(...),
           batch_key: str=Form(...), kind: str=Form("coding"), coding_id: str|None=Form(None)):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_analysis_service.request_ai_job(project_id,run_id,corpus_id,codebook_id,
        owner_id=owner,batch_key=batch_key,kind=kind,coding_id=coding_id)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/analysis/proposals/{proposal_id}/{decision}")
def proposal_review(request: Request, project_id: str, run_id: str, proposal_id: str, decision: str):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_analysis_service.review_ai_proposal(project_id,proposal_id,owner_id=owner,decision=decision)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.post("/{run_id}/transcripts/{transcript_id}/exports")
def export(request: Request, project_id: str, run_id: str, transcript_id: str):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    request.app.state.container.qualitative_service.export_docx(project_id,transcript_id,owner_id=owner)
    return RedirectResponse(f"/ui/projects/{project_id}/qualitative/{run_id}",303)

@router.get("/{run_id}/exports/{export_id}")
def download(request: Request, project_id: str, run_id: str, export_id: str):
    owner=resolve_ui_principal(request.app.state.container).principal_id
    value=request.app.state.container.qualitative_service.download(project_id,export_id,owner_id=owner)
    return Response(value.payload["private_bytes"],media_type=value.payload["media_type"],headers={"Content-Disposition":f'attachment; filename="{value.payload["filename"]}"'})
