import unittest
from fastapi.testclient import TestClient
from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from api.app import create_fastapi_app
from application.qualitative.transcription import DeterministicTranscriptionProvider
from infrastructure.qualitative.analysis_provider import DeterministicQualitativeAnalysisProvider
from domain.qualitative.authority import SpeakerRole, TranscriptSegment
from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.application.qualitative.test_qua01_authority import minimal_docx
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import create_test_engine, integration_tests_enabled, postgresql_application_config, reset_schema


@unittest.skipUnless(integration_tests_enabled(), "QUA-01 PostgreSQL acceptance requires disposable test database")
class Qua01PostgresqlE2E(unittest.TestCase):
    def setUp(self):
        self.engine=create_test_engine(); reset_schema(self.engine); self.addCleanup(self.engine.dispose)
    def container(self):
        return create_application_container(config=postgresql_application_config(deterministic_stage_executors=True),
            overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()))
    def client(self, container, key=None):
        key=key or bootstrap_test_api_key(container); context=TestClient(create_fastapi_app(container=container)); raw=context.__enter__()
        self.addCleanup(context.__exit__,None,None,None); return raw,auth_headers(key),key
    def context(self, raw, headers, container):
        owner=container.authentication_service.authenticate_api_key(headers["Authorization"].split()[1]).principal_id
        project=container.project_service.create_project("QUA-01 PG",owner_principal_id=owner,selected_methods=("QUALITATIVE",))
        run=raw.post(f"/projects/{project.id}/qualitative/runs",headers=headers).json()["run_id"]
        participant=raw.post(f"/projects/{project.id}/qualitative/{run}/participants",headers=headers,json={"pseudonym":"P01"}).json()["participant_id"]
        raw.post(f"/projects/{project.id}/qualitative/{run}/consents",headers=headers,json={"participant_id":participant,"state":"eligible","context":"attested","researcher_attested":True})
        session=raw.post(f"/projects/{project.id}/qualitative/{run}/sessions",headers=headers,json={"participant_id":participant,"context":"IDI"}).json()["session_id"]
        return project.id,run,session
    def test_prepared_docx_persists_authority_and_identical_export_after_restart(self):
        first=self.container(); self.addCleanup(first.shutdown); raw,headers,key=self.client(first)
        project,run,session=self.context(raw,headers,first)
        upload=raw.post(f"/projects/{project}/qualitative/{run}/sessions/{session}/artifacts",headers=headers,
            files={"artifact":("prepared.docx",minimal_docx(["Interviewer: Why?","P01: Because."]),"application/vnd.openxmlformats-officedocument.wordprocessingml.document")}).json()
        export=raw.post(f"/projects/{project}/qualitative/transcripts/{upload['result_id']}/exports",headers=headers).json()
        before=raw.get(f"/projects/{project}/qualitative/exports/{export['export_id']}",headers=headers).content
        first.shutdown(); restarted=self.container(); self.addCleanup(restarted.shutdown); raw2,headers2,_=self.client(restarted,key)
        detail=raw2.get(f"/projects/{project}/qualitative/{run}",headers=headers2).json()
        after=raw2.get(f"/projects/{project}/qualitative/exports/{export['export_id']}",headers=headers2).content
        self.assertEqual(detail["readiness"],"authority_ready_for_coding"); self.assertEqual(before,after)
    def test_audio_is_processed_by_existing_worker_loop(self):
        container=self.container(); self.addCleanup(container.shutdown); raw,headers,_=self.client(container)
        project,run,session=self.context(raw,headers,container)
        upload=raw.post(f"/projects/{project}/qualitative/{run}/sessions/{session}/artifacts",headers=headers,
            files={"artifact":("interview.wav",b"RIFF\x04\x00\x00\x00WAVEfixture","audio/wav")}).json()
        container.qualitative_service.provider=DeterministicTranscriptionProvider({upload["artifact_id"]:(
            TranscriptSegment("segment-0001",0,"Answer",speaker_label="A",speaker_role=SpeakerRole.PARTICIPANT,start_ms=100,end_ms=900),)})
        from worker.loop import WorkerLoop
        self.assertGreaterEqual(WorkerLoop(container,worker_id="qua01-worker").run_until_idle(),1)
        detail=raw.get(f"/projects/{project}/qualitative/{run}",headers=headers).json()
        transcript=next(x for x in detail["records"] if x["type"]=="transcript")
        self.assertEqual(transcript["payload"]["source_mode"],"audio_transcription")
        self.assertEqual(transcript["payload"]["segments"][0]["start_ms"],100)

    def test_qua02_multi_interview_analysis_persists_exact_authority_after_restart(self):
        first=self.container(); self.addCleanup(first.shutdown); raw,headers,key=self.client(first)
        owner=first.authentication_service.authenticate_api_key(headers["Authorization"].split()[1]).principal_id
        project=first.project_service.create_project("QUA-02 PG",owner_principal_id=owner,selected_methods=("QUALITATIVE",))
        run=raw.post(f"/projects/{project.id}/qualitative/runs",headers=headers).json()["run_id"]
        transcripts=[]
        for pseudonym,text in (("P01","Home charging is easy"),("P02","Public charging fails"),("P03","Petrol is safer for trips")):
            participant=raw.post(f"/projects/{project.id}/qualitative/{run}/participants",headers=headers,json={"pseudonym":pseudonym}).json()["participant_id"]
            raw.post(f"/projects/{project.id}/qualitative/{run}/consents",headers=headers,json={"participant_id":participant,"state":"eligible","context":"attested","researcher_attested":True})
            session=raw.post(f"/projects/{project.id}/qualitative/{run}/sessions",headers=headers,json={"participant_id":participant,"context":"IDI"}).json()["session_id"]
            transcripts.append(raw.post(f"/projects/{project.id}/qualitative/{run}/sessions/{session}/artifacts",headers=headers,
                files={"artifact":(f"{pseudonym}.txt",f"{pseudonym}: {text}".encode(),"text/plain")}).json()["result_id"])
        corpus=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/corpora",headers=headers,json={"transcript_ids":transcripts}).json()
        codebook=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/codebooks",headers=headers,json={"codes":[
            {"code_id":"charging","label":"Charging","definition":"Charging experience"},
            {"code_id":"deviant","label":"Deviant case","definition":"Contrasting preference"}],"status":"accepted"}).json()
        records=raw.get(f"/projects/{project.id}/qualitative/{run}",headers=headers).json()["records"]
        by_id={x["id"]:x["payload"] for x in records if x["type"]=="transcript"}; applications=[]
        for index,transcript_id in enumerate(transcripts):
            segment=by_id[transcript_id]["segments"][0]
            applications.append({"application_id":f"a{index}","code_id":"deviant" if index==2 else "charging",
                "transcript_version_id":transcript_id,"transcript_checksum":by_id[transcript_id]["checksum"],
                "segment_id":segment["segment_id"],"start":0,"end":len(segment["text"])})
        coding=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/codings",headers=headers,json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"applications":applications}).json()
        thematic=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/themes",headers=headers,json={
            "coding_id":coding["coding_revision_id"],"categories":[],"themes":[{"theme_id":"t1","title":"Adoption experience",
            "description":"Corpus-bound interpretation","code_ids":["charging","deviant"],"category_ids":[],
            "supporting_application_ids":["a0","a1"],"contradictory_application_ids":["a2"]}],"status":"accepted"}).json()
        first.shutdown(); restarted=self.container(); self.addCleanup(restarted.shutdown); raw2,headers2,_=self.client(restarted,key)
        ready=raw2.get(f"/projects/{project.id}/qualitative/{run}/analysis/readiness",headers=headers2).json()
        detail=raw2.get(f"/projects/{project.id}/qualitative/{run}",headers=headers2).json()
        persisted=next(x for x in detail["records"] if x["id"]==thematic["thematic_revision_id"])
        from application.query.project_outputs_query_service import ProjectOutputsQueryService
        outputs=ProjectOutputsQueryService(container=restarted).get(
            restarted.project_service.get_project(project.id),owner_id=owner)
        qualitative=next(x for x in outputs.methods if x.name == "Глибинні інтерв’ю")
        activity=restarted.activity_reader.list_for_project(project.id)
        self.assertEqual(ready["readiness"],"ready_for_findings")
        self.assertEqual(persisted["payload"]["themes"][0]["participant_count"],3)
        self.assertIn("Прийнятий тематичний аналіз",qualitative.outputs)
        self.assertTrue(any("готовий до висновків" in item.label.lower() for item in activity.events))

    def test_qua02_ai_acceptance_replay_and_failed_retry_survive_process_restart(self):
        first=self.container(); self.addCleanup(first.shutdown); raw,headers,key=self.client(first)
        owner=first.authentication_service.authenticate_api_key(headers["Authorization"].split()[1]).principal_id
        project=first.project_service.create_project("QUA-02 AI restart",owner_principal_id=owner,selected_methods=("QUALITATIVE",))
        run=raw.post(f"/projects/{project.id}/qualitative/runs",headers=headers).json()["run_id"]
        participant=raw.post(f"/projects/{project.id}/qualitative/{run}/participants",headers=headers,json={"pseudonym":"P01"}).json()["participant_id"]
        raw.post(f"/projects/{project.id}/qualitative/{run}/consents",headers=headers,json={"participant_id":participant,"state":"eligible","context":"attested","researcher_attested":True})
        session=raw.post(f"/projects/{project.id}/qualitative/{run}/sessions",headers=headers,json={"participant_id":participant,"context":"IDI"}).json()["session_id"]
        transcript_id=raw.post(f"/projects/{project.id}/qualitative/{run}/sessions/{session}/artifacts",headers=headers,
            files={"artifact":("P01.txt",b"P01: Canonical restart evidence","text/plain")}).json()["result_id"]
        corpus=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/corpora",headers=headers,json={"transcript_ids":[transcript_id]}).json()
        codebook=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/codebooks",headers=headers,json={"codes":[
            {"code_id":"restart","label":"Restart","definition":"Restart evidence"}],"status":"accepted"}).json()
        transcript=next(x["payload"] for x in raw.get(f"/projects/{project.id}/qualitative/{run}",headers=headers).json()["records"] if x["id"]==transcript_id)
        segment=transcript["segments"][0]; application={"application_id":"restart-app","code_id":"restart",
            "transcript_version_id":transcript_id,"transcript_checksum":transcript["checksum"],"segment_id":segment["segment_id"],
            "start":0,"end":len(segment["text"])}
        job=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/ai-jobs",headers=headers,json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"batch_key":"restart-batch"}).json()
        first.shutdown(); restarted=self.container(); self.addCleanup(restarted.shutdown); raw2,headers2,_=self.client(restarted,key)
        restarted.qualitative_analysis_service.provider=DeterministicQualitativeAnalysisProvider({"restart-batch":{"applications":[application]}})
        self.assertTrue(restarted.qualitative_analysis_service.process_next_job())
        records=raw2.get(f"/projects/{project.id}/qualitative/{run}",headers=headers2).json()["records"]
        proposal=next(x for x in records if x["type"]=="ai_analysis_proposal")
        accepted=raw2.post(f"/projects/{project.id}/qualitative/analysis/ai-proposals/{proposal['id']}/review",headers=headers2,json={"decision":"accepted"}).json()
        replay=raw2.post(f"/projects/{project.id}/qualitative/analysis/ai-proposals/{proposal['id']}/review",headers=headers2,json={"decision":"accepted"})
        self.assertEqual(replay.status_code,200,replay.text)
        self.assertEqual(replay.json()["canonical_id"],accepted["canonical_id"])
        canonical=restarted.qualitative_analysis_service.repository.get_for_project(accepted["canonical_id"],project_id=project.id)
        self.assertEqual(len(canonical.payload["applications"]),1); self.assertEqual(canonical.payload["corpus_id"],corpus["corpus_id"])
        failed=raw2.post(f"/projects/{project.id}/qualitative/{run}/analysis/ai-jobs",headers=headers2,json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"batch_key":"failure-batch"}).json()
        restarted.qualitative_analysis_service.provider=DeterministicQualitativeAnalysisProvider({})
        with self.assertRaises(ValueError): restarted.qualitative_analysis_service.process_next_job()
        restarted.shutdown(); recovered=self.container(); self.addCleanup(recovered.shutdown); raw3,headers3,_=self.client(recovered,key)
        retry=raw3.post(f"/projects/{project.id}/qualitative/{run}/analysis/ai-jobs/{failed['job_id']}/retry",headers=headers3).json()
        self.assertEqual(retry["attempt"],2)
        recovered.qualitative_analysis_service.provider=DeterministicQualitativeAnalysisProvider({"failure-batch":{"applications":[{**application,"application_id":"retry-app"}]}})
        self.assertTrue(recovered.qualitative_analysis_service.process_next_job())
        proposals=recovered.qualitative_analysis_service.repository.list_for_run(run,project_id=project.id,record_type="ai_analysis_proposal")
        self.assertEqual(len([x for x in proposals if x.payload["batch_key"]=="failure-batch"]),1)

    def test_qua03_findings_insights_review_and_approval_survive_restart(self):
        first=self.container(); self.addCleanup(first.shutdown); raw,headers,key=self.client(first)
        owner=first.authentication_service.authenticate_api_key(headers["Authorization"].split()[1]).principal_id
        project=first.project_service.create_project("QUA-03 PG",owner_principal_id=owner,selected_methods=("QUALITATIVE",))
        run=raw.post(f"/projects/{project.id}/qualitative/runs",headers=headers).json()["run_id"]
        transcripts=[]
        for p,text in (("P01","Official guidance was confusing"),("P02","Peer advice felt trustworthy")):
            participant=raw.post(f"/projects/{project.id}/qualitative/{run}/participants",headers=headers,json={"pseudonym":p}).json()["participant_id"]
            raw.post(f"/projects/{project.id}/qualitative/{run}/consents",headers=headers,json={"participant_id":participant,"state":"eligible","context":"attested","researcher_attested":True})
            session=raw.post(f"/projects/{project.id}/qualitative/{run}/sessions",headers=headers,json={"participant_id":participant}).json()["session_id"]
            transcripts.append(raw.post(f"/projects/{project.id}/qualitative/{run}/sessions/{session}/artifacts",headers=headers,
                files={"artifact":(f"{p}.txt",f"{p}: {text}".encode(),"text/plain")}).json()["result_id"])
        corpus=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/corpora",headers=headers,json={"transcript_ids":transcripts}).json()
        codebook=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/codebooks",headers=headers,json={"codes":[
            {"code_id":"guidance","label":"Guidance","definition":"Guidance"},{"code_id":"trust","label":"Trust","definition":"Trust"}],"status":"accepted"}).json()
        records=raw.get(f"/projects/{project.id}/qualitative/{run}",headers=headers).json()["records"]
        by_id={x["id"]:x["payload"] for x in records if x["type"]=="transcript"}; apps=[]
        for i,(transcript_id,code_id) in enumerate(zip(transcripts,("guidance","trust")),1):
            segment=by_id[transcript_id]["segments"][0]; apps.append({"application_id":f"a{i}","code_id":code_id,
                "transcript_version_id":transcript_id,"transcript_checksum":by_id[transcript_id]["checksum"],
                "segment_id":segment["segment_id"],"start":0,"end":len(segment["text"])})
        coding=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/codings",headers=headers,json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"applications":apps}).json()
        thematic=raw.post(f"/projects/{project.id}/qualitative/{run}/analysis/themes",headers=headers,json={
            "coding_id":coding["coding_revision_id"],"categories":[],"themes":[{"theme_id":"guidance-theme","title":"Guidance trust",
            "description":"Official and peer guidance were contrasted","code_ids":["guidance","trust"],"category_ids":[],
            "supporting_application_ids":["a1","a2"],"contradictory_application_ids":[]}],"status":"accepted"}).json()
        raw.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/ai-jobs",headers=headers,json={
            "thematic_id":thematic["thematic_revision_id"],"batch_key":"pg-finding","kind":"finding"})
        first.shutdown(); restarted=self.container(); self.addCleanup(restarted.shutdown); raw2,headers2,_=self.client(restarted,key)
        restarted.qualitative_post_analysis_service.provider=DeterministicQualitativeAnalysisProvider({"pg-finding":{"findings":[{
            "title":"Guidance gap","statement":"Participants frequently described a guidance trust gap.",
            "explanation":"The accepted Theme contains both interview spans.","theme_ids":["guidance-theme"]}]}})
        self.assertTrue(restarted.qualitative_post_analysis_service.process_next_job())
        proposal=restarted.qualitative_post_analysis_service._records(project.id,run,"qualitative_post_analysis_proposal")[0]
        finding_id=raw2.post(f"/projects/{project.id}/qualitative/post-analysis/ai-proposals/{proposal.record_id}/review",headers=headers2,
            json={"decision":"accepted"}).json()["canonical_ids"][0]
        second=raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/findings",headers=headers2,json={
            "thematic_id":thematic["thematic_revision_id"],"title":"Contrasting guidance sources",
            "statement":"Several participants contrasted official and peer guidance.",
            "explanation":"The accepted Theme preserves both interview spans.","theme_ids":["guidance-theme"],"status":"accepted"}).json()
        raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/ai-jobs",headers=headers2,json={
            "thematic_id":thematic["thematic_revision_id"],"batch_key":"pg-insight","kind":"insight",
            "finding_ids":[finding_id,second["finding_id"]]})
        restarted.qualitative_post_analysis_service.provider=DeterministicQualitativeAnalysisProvider({"pg-insight":{"insights":[{
            "title":"Trust interpretation","statement":"The accepted Findings indicate a guidance interpretation gap.",
            "implication":"Improve official guidance credibility.","finding_ids":[finding_id,second["finding_id"]]}]}})
        self.assertTrue(restarted.qualitative_post_analysis_service.process_next_job())
        insight_proposal=next(x for x in restarted.qualitative_post_analysis_service._records(project.id,run,"qualitative_post_analysis_proposal")
                              if x.payload["kind"]=="insight")
        insight_id=raw2.post(f"/projects/{project.id}/qualitative/post-analysis/ai-proposals/{insight_proposal.record_id}/review",headers=headers2,
            json={"decision":"accepted"}).json()["canonical_ids"][0]
        revision=raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/revisions",headers=headers2,json={
            "thematic_id":thematic["thematic_revision_id"],"finding_ids":[finding_id,second["finding_id"]],"insight_ids":[insight_id]}).json()
        raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/revisions/{revision['revision_id']}/review",headers=headers2,
            json={"decision":"changes_required","comments":"Clarify implication"})
        revised=raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/findings",headers=headers2,json={
            "thematic_id":thematic["thematic_revision_id"],"title":"Contrasting guidance sources clarified",
            "statement":"Several participants contrasted official and peer guidance.",
            "explanation":"The revised Finding remains bound to the accepted Theme.","theme_ids":["guidance-theme"],
            "status":"accepted","parent_id":second["finding_id"]}).json()
        revised_insight=raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/insights",headers=headers2,json={
            "thematic_id":thematic["thematic_revision_id"],"title":"Trust interpretation clarified",
            "statement":"The accepted Findings indicate a guidance interpretation gap.",
            "implication":"Improve official guidance credibility.","finding_ids":[finding_id,revised["finding_id"]],
            "status":"accepted","parent_id":insight_id}).json()
        successor=raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/revisions",headers=headers2,json={
            "thematic_id":thematic["thematic_revision_id"],"finding_ids":[finding_id,revised["finding_id"]],
            "insight_ids":[revised_insight["insight_id"]],"parent_id":revision["revision_id"]}).json()
        approved=raw2.post(f"/projects/{project.id}/qualitative/{run}/post-analysis/revisions/{successor['revision_id']}/review",headers=headers2,
            json={"decision":"approved","comments":"Approved"}).json()["approved_revision"]
        restarted.shutdown(); recovered=self.container(); self.addCleanup(recovered.shutdown); raw3,headers3,_=self.client(recovered,key)
        state=raw3.get(f"/projects/{project.id}/qualitative/{run}/post-analysis",headers=headers3).json()
        self.assertEqual(state["readiness"],"ready_for_deliverables")
        self.assertEqual(next(x for x in state["records"] if x["type"]=="qualitative_approved_revision")["id"],approved["approved_revision_id"])
        activity=recovered.activity_reader.list_for_project(project.id)
        self.assertTrue(any("готова до документів" in item.label.lower() for item in activity.events))
