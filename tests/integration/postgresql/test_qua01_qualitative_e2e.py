import unittest
from fastapi.testclient import TestClient
from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from api.app import create_fastapi_app
from application.qualitative.transcription import DeterministicTranscriptionProvider
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
            files={"artifact":("interview.wav",b"RIFFfixture","audio/wav")}).json()
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
