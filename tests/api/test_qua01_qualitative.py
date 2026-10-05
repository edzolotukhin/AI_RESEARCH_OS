from application.qualitative.transcription import DeterministicTranscriptionProvider
from domain.qualitative.authority import SpeakerRole, TranscriptSegment, TranscriptWord
from tests.api.helpers import ApiTestCase
from tests.application.qualitative.test_qua01_authority import minimal_docx


class Qua01ApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        principal = self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext).principal_id
        self.owner = principal
        self.project = self.container.project_service.create_project(
            "Qual acceptance", owner_principal_id=principal, selected_methods=("QUALITATIVE",))

    def create_context(self):
        run = self.client.post(f"/projects/{self.project.id}/qualitative/runs").json()["run_id"]
        participant = self.client.post(f"/projects/{self.project.id}/qualitative/{run}/participants",
                                       json={"pseudonym":"P01"}).json()["participant_id"]
        self.client.post(f"/projects/{self.project.id}/qualitative/{run}/consents", json={
            "participant_id":participant,"state":"eligible","context":"researcher attestation",
            "researcher_attested":True})
        session = self.client.post(f"/projects/{self.project.id}/qualitative/{run}/sessions",
            json={"participant_id":participant,"context":"IDI"}).json()["session_id"]
        return run, session

    def test_prepared_docx_no_audio_end_to_end_and_immutable_download(self):
        run, session = self.create_context()
        uploaded = self.client.post(f"/projects/{self.project.id}/qualitative/{run}/sessions/{session}/artifacts",
            files={"artifact":("prepared.docx",minimal_docx(["Interviewer: Why?","P01: Because."]),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        self.assertEqual(uploaded.status_code, 200)
        transcript = uploaded.json()["result_id"]
        detail = self.client.get(f"/projects/{self.project.id}/qualitative/{run}").json()
        self.assertEqual(detail["readiness"], "authority_ready_for_coding")
        canonical = next(x for x in detail["records"] if x["id"] == transcript)
        self.assertTrue(all(x["start_ms"] is None for x in canonical["payload"]["segments"]))
        export = self.client.post(f"/projects/{self.project.id}/qualitative/transcripts/{transcript}/exports").json()
        first = self.client.get(f"/projects/{self.project.id}/qualitative/exports/{export['export_id']}").content
        second = self.client.get(f"/projects/{self.project.id}/qualitative/exports/{export['export_id']}").content
        self.assertEqual(first, second); self.assertTrue(first.startswith(b"PK"))
        self.assertFalse(any(x["payload"].get("kind") == "audio" for x in detail["records"]))

    def test_audio_job_uses_deterministic_provider_and_preserves_timing(self):
        run, session = self.create_context()
        self.container.qualitative_service.provider = DeterministicTranscriptionProvider({"audio-fixed": ()})
        # Upload assigns an opaque artifact identity, so bind the deterministic fixture after upload.
        uploaded = self.client.post(f"/projects/{self.project.id}/qualitative/{run}/sessions/{session}/artifacts",
            files={"artifact":("interview.wav",b"RIFF\x04\x00\x00\x00WAVEsynthetic","audio/wav")}).json()
        artifact_id, job_id = uploaded["artifact_id"], uploaded["result_id"]
        segments=(TranscriptSegment("segment-0001",0,"Hello",speaker_label="A",speaker_role=SpeakerRole.INTERVIEWER,
            start_ms=1000,end_ms=1500,words=(TranscriptWord("Hello",1000,1500),)),)
        self.container.qualitative_service.provider = DeterministicTranscriptionProvider({artifact_id:segments})
        processed=self.client.post(f"/projects/{self.project.id}/qualitative/{run}/jobs/{job_id}/process")
        self.assertEqual(processed.status_code,200)
        detail=self.client.get(f"/projects/{self.project.id}/qualitative/{run}").json()
        transcript=next(x for x in detail["records"] if x["type"]=="transcript")
        self.assertEqual(transcript["payload"]["segments"][0]["start_ms"],1000)

    def test_audio_provider_failure_is_terminal_and_not_retried(self):
        class FailingProvider:
            calls = 0

            def submit(inner_self, **_kwargs):
                inner_self.calls += 1
                raise RuntimeError("synthetic provider failure")

        run, session = self.create_context()
        uploaded = self.client.post(
            f"/projects/{self.project.id}/qualitative/{run}/sessions/{session}/artifacts",
            files={"artifact":("interview.wav",b"RIFF\x04\x00\x00\x00WAVEsynthetic","audio/wav")}).json()
        provider = FailingProvider()
        self.container.qualitative_service.provider = provider

        with self.assertRaises(RuntimeError):
            self.container.qualitative_service.process_job(
                self.project.id, uploaded["result_id"], owner_id=self.owner)

        detail = self.client.get(f"/projects/{self.project.id}/qualitative/{run}").json()
        failed = [x for x in detail["records"] if x["type"] == "job" and x["payload"].get("state") == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["payload"]["error_category"], "RuntimeError")
        self.assertFalse(self.container.qualitative_service.process_next_job())
        self.assertEqual(provider.calls, 1)

    def test_correction_creates_exact_new_version_without_moving_v1(self):
        run, session = self.create_context()
        uploaded=self.client.post(f"/projects/{self.project.id}/qualitative/{run}/sessions/{session}/artifacts",
            files={"artifact":("prepared.txt",b"P01: original answer","text/plain")}).json()
        v1=uploaded["result_id"]
        derived=self.client.post(f"/projects/{self.project.id}/qualitative/transcripts/{v1}/versions",json={
            "segment_text":{"segment-0001":"corrected answer"},"speaker_roles":{"segment-0001":"participant"},
            "clean":True,"redacted":True}).json()
        self.assertEqual(derived["version"],2); self.assertEqual(derived["parent_version_id"],v1)
        detail=self.client.get(f"/projects/{self.project.id}/qualitative/{run}").json()
        versions={x["id"]:x for x in detail["records"] if x["type"]=="transcript"}
        self.assertEqual(versions[v1]["payload"]["segments"][0]["text"],"original answer")
        self.assertEqual(versions[derived["transcript_version_id"]]["payload"]["segments"][0]["text"],"corrected answer")
