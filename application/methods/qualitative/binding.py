from application.methods.contracts import Capabilities, MethodIdentity
from domain.qualitative.authority import TranscriptVersion


class QualitativeBinding:
    identity = MethodIdentity(
        "QUALITATIVE", "1", "In-Depth Interviews", 1,
        "idi-design-1", "qual-transcript-1", 1, "qual-integrity-1",
        "qual-readiness-1", "qual-coding-pending", "qual-review-pending", "qual-report-pending",
    )
    capabilities = Capabilities(
        "qualitative_artifact", ("transcript_authority",), ("DOCX",),
        ("consent", "transcript"), findings=False, insights=False,
    )

    def bind_transcript(self, *, transcript) -> None:
        if not isinstance(transcript, TranscriptVersion):
            raise ValueError("Canonical transcript authority is required")
        if not transcript.analysis_eligible:
            raise ValueError("Transcript is not eligible for future coding")

    def run_stage(self, stage, context, delegate):
        if stage not in {"qual_artifact", "qual_transcription", "qual_transcript", "qual_export"}:
            raise ValueError("Unsupported Qualitative stage")
        return delegate(context)

    def report_sources(self, project_id, run_ids, delegate):
        return delegate(project_id, run_ids)
