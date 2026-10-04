from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from api.ui.quantitative_facade import build_quantitative_ui_facade
from application.quantitative.ui_service import QuantitativeUiError
from application.structured_output.json_validator import JsonValidator

templates=Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent/"templates")); router=APIRouter(prefix="/ui/quantitative",tags=["quantitative-ui"])
def _error(request,message,status_code=422): return templates.TemplateResponse(request,"quantitative/error.html",{"request":request,"message":message},status_code=status_code)
@router.get("/new",response_class=HTMLResponse,include_in_schema=False)
def new_study(request:Request): return templates.TemplateResponse(request,"quantitative/new.html",{"request":request,"submission_key":str(uuid4())})
@router.post("/studies",include_in_schema=False)
def create_study(request:Request,title:str=Form(""),description:str=Form(""),submission_key:str=Form("")):
    try:
        s=build_quantitative_ui_facade(request.app.state.container).create(title=title,description=description,submission_key=submission_key)
        return RedirectResponse(f"/ui/quantitative/studies/{s.study_id}",status_code=303)
    except QuantitativeUiError as exc:return _error(request,str(exc))
@router.get("/studies/{study_id}",include_in_schema=False)
def study_detail(study_id:str):return RedirectResponse(f"/ui/quantitative/studies/{study_id}/overview",status_code=303)
def _screen(request,study_id,section):
    try:
        facade=build_quantitative_ui_facade(request.app.state.container)
        study=facade.get(study_id)
        return templates.TemplateResponse(request,f"quantitative/{section}.html",{
            "request":request,"view":facade.view(study_id,active=section),
            "study":study,"authority":facade.authority(study_id),
            "diagnostics":facade.diagnostics(study_id) if study.weight_set_record_id else None,
        })
    except (QuantitativeUiError,ValueError,KeyError) as exc:return _error(request,str(exc),404)
@router.get("/studies/{study_id}/overview",response_class=HTMLResponse,include_in_schema=False)
def overview(request:Request,study_id:str):return _screen(request,study_id,"overview")
@router.get("/studies/{study_id}/data",response_class=HTMLResponse,include_in_schema=False)
def data(request:Request,study_id:str):return _screen(request,study_id,"data")
@router.get("/studies/{study_id}/analysis",response_class=HTMLResponse,include_in_schema=False)
def analysis(request:Request,study_id:str):return _screen(request,study_id,"analysis")
@router.get("/studies/{study_id}/results",response_class=HTMLResponse,include_in_schema=False)
def results(request:Request,study_id:str):return _screen(request,study_id,"results")
@router.get("/studies/{study_id}/report",response_class=HTMLResponse,include_in_schema=False)
def report(request:Request,study_id:str):return _screen(request,study_id,"report")
def _go(study_id,section="overview"):return RedirectResponse(f"/ui/quantitative/studies/{study_id}/{section}",status_code=303)
@router.post("/studies/{study_id}/dataset",include_in_schema=False)
async def upload_dataset(request:Request,study_id:str,dataset:UploadFile=File(...),replace_existing:bool=Form(False)):
    try:
        content=await dataset.read(20*1024*1024+1);build_quantitative_ui_facade(request.app.state.container).upload(study_id,filename=dataset.filename or "dataset",content=content,replace_existing=replace_existing);return _go(study_id,"data")
    except QuantitativeUiError as exc:return _error(request,str(exc))
    except Exception:return _error(request,"Dataset upload could not be processed safely")
@router.get("/studies/{study_id}/status.json",include_in_schema=False)
def study_status(request:Request,study_id:str):
    try:
        f=build_quantitative_ui_facade(request.app.state.container);s=f.get(study_id);a=f.authority(study_id);return JSONResponse({"study_id":s.study_id,"project_id":s.project_id,"run_id":s.run_id,"state":s.state,"setup_state":s.state,"execution_status":f.execution_status(study_id),"revision":s.revision,"dataset_available":bool(s.dataset_record_id),"weight_set_available":bool(s.weight_set_record_id),"canonical":a["canonical"],"dataset_version":a["dataset_version"],"design_state":a["design_state"],"design_version":a["design_version"]})
    except QuantitativeUiError as exc:return JSONResponse({"detail":str(exc)},status_code=404)
@router.post("/studies/{study_id}/qc",include_in_schema=False)
def run_qc(request:Request,study_id:str):
    try:build_quantitative_ui_facade(request.app.state.container).run_qc(study_id);return _go(study_id,"data")
    except QuantitativeUiError as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/qc-approval",include_in_schema=False)
def approve_qc(request:Request,study_id:str,fingerprint:str=Form(...),decision:str=Form("APPROVED"),rationale:str=Form("")):
    try:build_quantitative_ui_facade(request.app.state.container).approve_qc(study_id,fingerprint=fingerprint,decision=decision,rationale=rationale);return _go(study_id,"data")
    except (QuantitativeUiError,ValueError) as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/target-margins",include_in_schema=False)
def target_margins(request:Request,study_id:str,targets_json:str=Form(...)):
    parsed=JsonValidator().validate(targets_json)
    if not parsed.is_valid or not isinstance(parsed.data,dict):return _error(request,"Target margins must be a valid JSON object")
    try:build_quantitative_ui_facade(request.app.state.container).construct_weights(study_id,parsed.data);return _go(study_id,"data")
    except (QuantitativeUiError,ValueError) as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/weight-approval",include_in_schema=False)
def approve_weight(request:Request,study_id:str,fingerprint:str=Form(...),decision:str=Form("APPROVED"),rationale:str=Form("")):
    try:build_quantitative_ui_facade(request.app.state.container).approve_weights(study_id,fingerprint=fingerprint,decision=decision,rationale=rationale);return _go(study_id,"data")
    except (QuantitativeUiError,ValueError) as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/cleaning",include_in_schema=False)
def apply_cleaning(request:Request,study_id:str,variable_name:str=Form(...),replacements_json:str=Form(...)):
    parsed=JsonValidator().validate(replacements_json)
    if not parsed.is_valid or not isinstance(parsed.data,dict):return _error(request,"Cleaning replacements must be a valid JSON object")
    try:build_quantitative_ui_facade(request.app.state.container).clean(study_id,variable_name=variable_name,replacements=parsed.data);return _go(study_id,"data")
    except (QuantitativeUiError,ValueError) as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/resume",include_in_schema=False)
def resume_quantitative(request:Request,study_id:str):
    try:build_quantitative_ui_facade(request.app.state.container).resume(study_id);return _go(study_id,"analysis")
    except QuantitativeUiError as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/rearm",include_in_schema=False)
def rearm_quantitative(request:Request,study_id:str,reason:str=Form(...)):
    try:build_quantitative_ui_facade(request.app.state.container).rearm(study_id,reason=reason);return _go(study_id)
    except QuantitativeUiError as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/design",include_in_schema=False)
def configure_design(request:Request,study_id:str,title:str=Form(...),research_question:str=Form(...),population:str=Form(...),procedure:str=Form(...),primary_variable_id:str=Form(...),group_variable_id:str=Form(""),outcome_category:str=Form(""),group_a_category:str=Form(""),group_b_category:str=Form(""),weighting_mode:str=Form("UNWEIGHTED")):
    try:
        build_quantitative_ui_facade(request.app.state.container).configure_design(
            study_id,title=title,research_question=research_question,population=population,
            procedure=procedure,primary_variable_id=primary_variable_id,
            group_variable_id=group_variable_id or None,outcome_category=outcome_category or None,
            group_a_category=group_a_category or None,group_b_category=group_b_category or None,
            weighting_mode=weighting_mode)
        return _go(study_id,"analysis")
    except (QuantitativeUiError,ValueError,KeyError) as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/design/approve",include_in_schema=False)
def approve_design(request:Request,study_id:str,plan_version_id:str=Form(...),expected_fingerprint:str=Form(...),rationale:str=Form("")):
    try:
        build_quantitative_ui_facade(request.app.state.container).approve_design(
            study_id,plan_version_id=plan_version_id,expected_fingerprint=expected_fingerprint,
            rationale=rationale)
        return _go(study_id,"analysis")
    except (QuantitativeUiError,ValueError,KeyError) as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/analysis/execute",include_in_schema=False)
def execute_analysis(request:Request,study_id:str):
    try:
        build_quantitative_ui_facade(request.app.state.container).execute_analysis(study_id)
        return _go(study_id,"analysis")
    except (QuantitativeUiError,ValueError,KeyError) as exc:return _error(request,str(exc))
@router.post("/studies/{study_id}/analysis/authorize-semantics",include_in_schema=False)
def authorize_analysis_semantics(request:Request,study_id:str,expected_authority_fingerprint:str=Form(...),rationale:str=Form("")):
    try:
        build_quantitative_ui_facade(request.app.state.container).authorize_semantics(
            study_id,expected_authority_fingerprint=expected_authority_fingerprint,rationale=rationale)
        return _go(study_id,"results")
    except (QuantitativeUiError,ValueError,KeyError) as exc:return _error(request,str(exc))
@router.get("/studies/{study_id}/result.json",include_in_schema=False)
def quantitative_result(request:Request,study_id:str):
    try:return JSONResponse(build_quantitative_ui_facade(request.app.state.container).result(study_id))
    except QuantitativeUiError as exc:return JSONResponse({"detail":str(exc)},status_code=404)
