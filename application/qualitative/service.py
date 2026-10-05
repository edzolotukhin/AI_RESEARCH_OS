from __future__ import annotations
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from application.ports.qualitative_state_repository import QualitativeStateRecord
from application.qualitative.docx_export import render_transcript_docx
from application.qualitative.transcript_parser import parse_docx, parse_prepared_text
from domain.qualitative.authority import *
from domain.workflow_template import WorkflowTemplate
from application.persistence.exceptions import AccessDeniedError

QUAL_TEMPLATE = "cmf-qualitative-idi-v1"


class QualitativeService:
    def __init__(self, *, projects, workflows, repository, provider, digest_provider, activity_recorder=None, access_checker=None):
        self.projects, self.workflows, self.repository = projects, workflows, repository
        self.provider, self.digest, self.activity_recorder = provider, digest_provider, activity_recorder
        self.access_checker = access_checker

    def _project(self, project_id, owner_id):
        project = self.projects.get_project(project_id)
        if project.owner_principal_id != owner_id and not (self.access_checker and self.access_checker(project_id, owner_id)):
            raise AccessDeniedError("Qualitative authority not found")
        return project

    def _put(self, project_id, run_id, kind, record_id, payload, parent=None, data=None):
        encoded = data if data is not None else repr(sorted(payload.items())).encode()
        self.repository.create(QualitativeStateRecord(record_id, project_id, run_id, kind,
            {**payload, **({"private_bytes": data} if data is not None else {})}, self.digest.sha256_hex(encoded), parent))

    def _get(self, project_id, record_id, kind=None):
        value = self.repository.get_for_project(record_id, project_id=project_id)
        if value is None or (kind and value.record_type != kind): raise LookupError("Qualitative authority not found")
        return value

    def _activity(self, project_id, run_id, event_type, source_kind, source_id):
        if self.activity_recorder is not None:
            self.activity_recorder(project_id, run_id, event_type, source_kind, source_id)

    def create_run(self, project_id, *, owner_id):
        project = self._project(project_id, owner_id)
        if "QUALITATIVE" not in (project.selected_methods or ()): raise ValueError("QUALITATIVE is not selected")
        existing_run = next((run for run in self.workflows.list_workflow_runs_for_project(project_id)
                             if run.workflow_template_id == QUAL_TEMPLATE), None)
        if existing_run: return self._get(project_id, existing_run.id, "run")
        run_id = str(uuid4()); template = WorkflowTemplate(QUAL_TEMPLATE, "In-Depth Interviews")
        self.workflows.publish_template_snapshot(template, project_id=project_id)
        self.workflows.create_workflow_run(template, project_id=project_id, run_id=run_id, initially_paused=True)
        self._put(project_id, run_id, "run", run_id, {"method_id":"QUALITATIVE", "method_version":"1"})
        self._activity(project_id, run_id, "QUAL_RUN_CREATED", "run", run_id)
        return self._get(project_id, run_id)

    def create_participant(self, project_id, run_id, pseudonym, *, owner_id):
        self._project(project_id, owner_id); self._get(project_id, run_id, "run")
        identity = str(uuid4()); value = Participant(identity, project_id, run_id, pseudonym)
        self._put(project_id, run_id, "participant", identity, asdict(value)); return value

    def record_consent(self, project_id, run_id, participant_id, state, context, *, owner_id, attested=False):
        self._project(project_id, owner_id); self._get(project_id, participant_id, "participant")
        identity = str(uuid4()); value = ConsentRecord(identity, participant_id, ConsentState(state),
                                                        datetime.now(UTC), context, attested)
        payload = asdict(value); payload["state"] = value.state.value; payload["recorded_at"] = value.recorded_at.isoformat()
        self._put(project_id, run_id, "consent", identity, payload); return value

    def create_session(self, project_id, run_id, participant_id, context, *, owner_id):
        self._project(project_id, owner_id); participant = self._get(project_id, participant_id, "participant")
        if participant.run_id != run_id: raise ValueError("Participant belongs to another run")
        identity = str(uuid4()); value = Session(identity, project_id, run_id, participant_id, context=context)
        self._put(project_id, run_id, "session", identity, asdict(value))
        self._activity(project_id, run_id, "QUAL_SESSION_CREATED", "session", identity); return value

    def upload(self, project_id, run_id, session_id, *, filename, media_type, content, owner_id):
        self._project(project_id, owner_id); session = self._get(project_id, session_id, "session")
        if session.run_id != run_id: raise ValueError("Session belongs to another run")
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if suffix == "docx": kind, limit = ArtifactKind.PREPARED_DOCX, 10_000_000
        elif suffix == "txt": kind, limit = ArtifactKind.PREPARED_TEXT, 5_000_000
        elif suffix in {"wav","mp3","m4a","mp4","webm"}: kind, limit = ArtifactKind.AUDIO, 100_000_000
        else: raise ValueError("Unsupported qualitative artifact type")
        if not content or len(content) > limit: raise ValueError("Invalid qualitative artifact size")
        identity = str(uuid4()); artifact = QualitativeArtifact.from_bytes(content=content, artifact_id=identity,
            project_id=project_id, run_id=run_id, session_id=session_id, kind=kind, media_type=media_type,
            original_filename=filename, imported_at=datetime.now(UTC))
        payload = asdict(artifact); payload["kind"] = kind.value; payload["imported_at"] = artifact.imported_at.isoformat()
        self._put(project_id, run_id, "artifact", identity, payload, data=content)
        self._activity(project_id, run_id, "QUAL_ARTIFACT_ACCEPTED", "qual_artifact", identity)
        if kind is ArtifactKind.AUDIO: return artifact, self.queue_transcription(project_id, run_id, identity, owner_id=owner_id)
        segments = parse_docx(content) if kind is ArtifactKind.PREPARED_DOCX else parse_prepared_text(content.decode("utf-8"))
        return artifact, self._canonicalize(project_id, run_id, session_id, identity, SourceMode.PREPARED_TRANSCRIPT, segments)

    def queue_transcription(self, project_id, run_id, artifact_id, *, owner_id):
        self._project(project_id, owner_id); artifact = self._get(project_id, artifact_id, "artifact")
        if artifact.payload["kind"] != ArtifactKind.AUDIO.value: raise ValueError("Transcription requires audio")
        identity = str(uuid4()); self._put(project_id, run_id, "job", identity,
            {"artifact_id":artifact_id, "state":"queued", "provider_job_id":None}); return self._get(project_id, identity)

    def process_job(self, project_id, job_id, *, owner_id):
        self._project(project_id, owner_id); job = self._get(project_id, job_id, "job")
        return self._process_job_record(job)

    def _process_job_record(self, job):
        project_id, job_id = job.project_id, job.record_id
        if job.payload["state"] == "ready": return self._get(project_id, job.payload["transcript_version_id"], "transcript")
        artifact = self._get(project_id, job.payload["artifact_id"], "artifact")
        transcribing_id = f"{job_id}:transcribing"
        existing = self.repository.get_for_project(f"{job_id}:ready", project_id=project_id)
        if existing: return self._get(project_id, existing.payload["transcript_version_id"], "transcript")
        if self.repository.get_for_project(transcribing_id, project_id=project_id) is None:
            self._put(project_id, job.run_id, "job_state", transcribing_id,
                      {"job_id":job_id,"artifact_id":artifact.record_id,"state":"transcribing"}, parent=job_id)
            self._activity(project_id, job.run_id, "QUAL_TRANSCRIPTION_STARTED", "transcription_job", job_id)
        content = artifact.payload["private_bytes"]; artifact_id = artifact.record_id
        try:
            provider_job = self.provider.submit(
                artifact_id=artifact_id, content=content, media_type=artifact.payload["media_type"])
            result = self.provider.result(provider_job_id=provider_job, source_artifact_id=artifact_id)
            if result.source_artifact_id != artifact_id:
                raise ValueError("Provider result bound to wrong artifact")
        except Exception as exc:
            failed_id = f"{job_id}:failed"
            if self.repository.get_for_project(failed_id, project_id=project_id) is None:
                self._put(project_id, job.run_id, "job", failed_id,
                    {"job_id":job_id,"artifact_id":artifact_id,"state":"failed",
                     "error_category":type(exc).__name__}, parent=job_id)
                self._activity(project_id, job.run_id, "QUAL_TRANSCRIPTION_FAILED", "transcription_job", failed_id)
            raise
        provider_id = f"{job_id}:provider-result"
        if self.repository.get_for_project(provider_id, project_id=project_id) is None:
            self._put(project_id, job.run_id, "job_state", provider_id,
                {"job_id":job_id,"artifact_id":artifact_id,"state":"provider_result_received",
                 "provider":result.provider,"provider_job_id":provider_job}, parent=transcribing_id)
        canonical_id = f"{job_id}:canonicalizing"
        if self.repository.get_for_project(canonical_id, project_id=project_id) is None:
            self._put(project_id, job.run_id, "job_state", canonical_id,
                      {"job_id":job_id,"artifact_id":artifact_id,"state":"canonicalizing"}, parent=provider_id)
        existing_transcript = next((x for x in self.repository.list_for_run(job.run_id, project_id=project_id,
            record_type="transcript") if x.payload.get("source_artifact_id") == artifact_id
            and x.payload.get("source_mode") == SourceMode.AUDIO_TRANSCRIPTION.value), None)
        transcript = (transcript_from_payload(existing_transcript.payload) if existing_transcript else
            self._canonicalize(project_id, job.run_id, artifact.payload["session_id"], artifact_id,
                               SourceMode.AUDIO_TRANSCRIPTION, result.segments))
        ready_id = f"{job_id}:ready"; self._put(project_id, job.run_id, "job", ready_id,
            {"artifact_id":artifact_id,"state":"ready","provider":result.provider,"provider_job_id":provider_job,
             "transcript_version_id":transcript.transcript_version_id}, parent=job_id)
        self._activity(project_id, job.run_id, "QUAL_TRANSCRIPTION_COMPLETED", "transcription_job", ready_id)
        return transcript

    def process_next_job(self, worker_id="worker"):
        for job in self.repository.list_by_type("job"):
            if job.payload.get("state") != "queued": continue
            if self.repository.get_for_project(f"{job.record_id}:ready", project_id=job.project_id): continue
            if self.repository.get_for_project(f"{job.record_id}:failed", project_id=job.project_id): continue
            self._process_job_record(job); return True
        return False

    def _canonicalize(self, project_id, run_id, session_id, artifact_id, source_mode, segments, *, parent=None, kind=TranscriptKind.VERBATIM, analysis_eligible=True):
        identity = str(uuid4()); previous = self.repository.list_for_run(run_id, project_id=project_id, record_type="transcript")
        version = 1 + max((x.payload["version"] for x in previous if x.payload["session_id"] == session_id), default=0)
        transcript = TranscriptVersion.create(transcript_version_id=identity, project_id=project_id, run_id=run_id,
            session_id=session_id, source_artifact_id=artifact_id, source_mode=source_mode, version=version, kind=kind,
            segments=segments, parent_version_id=parent, analysis_eligible=analysis_eligible, redacted=parent is not None)
        payload = asdict(transcript); payload["source_mode"] = source_mode.value; payload["kind"] = kind.value
        for item in payload["segments"]: item["speaker_role"] = item["speaker_role"].value if hasattr(item["speaker_role"], "value") else item["speaker_role"]
        self._put(project_id, run_id, "transcript", identity, payload, parent=parent)
        self._activity(project_id, run_id, "QUAL_TRANSCRIPT_READY", "transcript", identity)
        if transcript.analysis_eligible: self._activity(project_id, run_id, "QUAL_AUTHORITY_READY", "transcript", identity)
        return transcript

    def export_docx(self, project_id, transcript_id, *, owner_id):
        self._project(project_id, owner_id); record = self._get(project_id, transcript_id, "transcript")
        transcript = transcript_from_payload(record.payload); session = self._get(project_id, transcript.session_id, "session")
        participant = self._get(project_id, session.payload["participant_id"], "participant")
        exports = self.repository.list_for_run(record.run_id, project_id=project_id, record_type="export")
        existing = next((x for x in exports if x.payload["transcript_version_id"] == transcript_id), None)
        if existing: return existing
        data = render_transcript_docx(transcript, session_id=transcript.session_id, participant=participant.payload["pseudonym"])
        identity = str(uuid4()); self._put(project_id, record.run_id, "export", identity,
            {"transcript_version_id":transcript_id,"filename":f"transcript-v{transcript.version}.docx",
             "media_type":"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}, data=data)
        self._activity(project_id, record.run_id, "QUAL_TRANSCRIPT_DOCX_GENERATED", "transcript_export", identity)
        return self._get(project_id, identity)

    def derive_transcript(self, project_id, transcript_id, *, owner_id, segment_text=None,
                          speaker_roles=None, clean=False, redacted=True):
        self._project(project_id, owner_id); parent = self._get(project_id, transcript_id, "transcript")
        source = transcript_from_payload(parent.payload); segment_text = segment_text or {}; speaker_roles = speaker_roles or {}
        segments = tuple(TranscriptSegment(x.segment_id, x.order, segment_text.get(x.segment_id, x.text),
            x.speaker_label, SpeakerRole(speaker_roles.get(x.segment_id, x.speaker_role.value)),
            x.start_ms, x.end_ms, x.words) for x in source.segments)
        return self._canonicalize(project_id, source.run_id, source.session_id, source.source_artifact_id,
            source.source_mode, segments, parent=source.transcript_version_id,
            kind=TranscriptKind.CLEAN if clean else TranscriptKind.VERBATIM, analysis_eligible=redacted)

    def records(self, project_id, run_id, *, owner_id, kind=None):
        self._project(project_id, owner_id); self._get(project_id, run_id, "run")
        return self.repository.list_for_run(run_id, project_id=project_id, record_type=kind)

    def readiness(self, project_id, run_id, *, owner_id):
        records = self.records(project_id, run_id, owner_id=owner_id)
        by_kind = lambda name: [x for x in records if x.record_type == name]
        participant = by_kind("participant")[-1] if by_kind("participant") else None
        consent = max(by_kind("consent"), key=lambda x: x.payload["recorded_at"]) if by_kind("consent") else None
        session = by_kind("session")[-1] if by_kind("session") else None
        artifact = by_kind("artifact")[-1] if by_kind("artifact") else None
        transcript = by_kind("transcript")[-1] if by_kind("transcript") else None
        p = None if participant is None else Participant(**participant.payload)
        c = None if consent is None else ConsentRecord(consent.payload["consent_id"], consent.payload["participant_id"],
            ConsentState(consent.payload["state"]), datetime.fromisoformat(consent.payload["recorded_at"]),
            consent.payload["context"], consent.payload.get("researcher_attested", False))
        s = None if session is None else Session(**session.payload)
        t = None if transcript is None else transcript_from_payload(transcript.payload)
        return assess_readiness(participant=p, consent=c, session=s, artifact=artifact, transcript=t)

    def download(self, project_id, export_id, *, owner_id):
        self._project(project_id, owner_id); return self._get(project_id, export_id, "export")


def transcript_from_payload(value):
    segments = tuple(TranscriptSegment(segment_id=x["segment_id"], order=x["order"], text=x["text"],
        speaker_label=x.get("speaker_label"), speaker_role=SpeakerRole(x["speaker_role"]),
        start_ms=x.get("start_ms"), end_ms=x.get("end_ms"),
        words=tuple(TranscriptWord(**word) for word in x.get("words", ()))) for x in value["segments"])
    return TranscriptVersion(value["transcript_version_id"], value["project_id"], value["run_id"], value["session_id"],
        value["source_artifact_id"], SourceMode(value["source_mode"]), value["version"], TranscriptKind(value["kind"]),
        segments, value["checksum"], value.get("parent_version_id"), value.get("language"), value.get("redacted",False),
        value.get("analysis_eligible",False), tuple(value.get("warnings",())))
