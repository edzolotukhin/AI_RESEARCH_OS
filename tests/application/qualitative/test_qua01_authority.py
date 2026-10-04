from datetime import datetime, timezone
import io
import zipfile
import unittest

from application.methods.catalog import production_methods
from application.qualitative.transcript_parser import parse_docx, parse_prepared_text
from application.qualitative.transcription import DeterministicTranscriptionProvider
from domain.qualitative.authority import (
    ArtifactKind, ConsentRecord, ConsentState, Participant, QualitativeArtifact,
    QualitativeReadiness, Session, SourceMode, SpeakerRole, TranscriptKind,
    TranscriptSegment, TranscriptSpanRef, TranscriptVersion, assess_readiness,
)


def minimal_docx(paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:body>{body}</w:body></w:document>').encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


class Qua01AuthorityTests(unittest.TestCase):
    def transcript(self, segments, **extra):
        return TranscriptVersion.create(
            transcript_version_id=extra.pop("transcript_version_id", "tv1"), project_id="p", run_id="r",
            session_id="s", source_artifact_id="a", source_mode=SourceMode.PREPARED_TRANSCRIPT,
            version=extra.pop("version", 1), kind=TranscriptKind.VERBATIM, segments=segments, **extra)

    def test_three_authority_families_are_exact(self):
        registry = production_methods()
        self.assertEqual(registry.resolve("DESK", "1").capabilities.support_kinds, ("text_citation",))
        self.assertEqual(registry.resolve("QUANTITATIVE", "1").capabilities.support_kinds, ("dataset_authority",))
        qualitative = registry.resolve("QUALITATIVE", "1")
        self.assertEqual(qualitative.identity.name, "In-Depth Interviews")
        self.assertEqual(qualitative.capabilities.support_kinds, ("transcript_authority",))

    def test_prepared_text_preserves_speakers_and_never_fabricates_time(self):
        segments = parse_prepared_text("Interviewer: Why?\nP01: Because.\nUnlabelled answer")
        self.assertEqual([x.speaker_role for x in segments],
                         [SpeakerRole.INTERVIEWER, SpeakerRole.PARTICIPANT, SpeakerRole.UNKNOWN])
        self.assertTrue(all(x.start_ms is None and x.end_ms is None for x in segments))

    def test_docx_and_timestamped_input_converge_on_segments(self):
        segments = parse_docx(minimal_docx(["[00:12:34] Interviewer: Why?", "00:12:41 P07: Because."]))
        self.assertEqual([x.start_ms for x in segments], [754000, 761000])
        self.assertEqual(segments[1].speaker_role, SpeakerRole.PARTICIPANT)

    def test_span_is_exact_and_rejects_stale_or_out_of_range(self):
        transcript = self.transcript(parse_prepared_text("P01: canonical answer"))
        ref = TranscriptSpanRef("tv1", transcript.checksum, "segment-0001", 0, 9)
        self.assertEqual(ref.resolve(transcript), "canonical")
        with self.assertRaises(ValueError):
            TranscriptSpanRef("tv1", "changed", "segment-0001", 0, 9).resolve(transcript)
        with self.assertRaises(ValueError):
            TranscriptSpanRef("tv1", transcript.checksum, "segment-0001", 0, 999).resolve(transcript)

    def test_artifact_bytes_are_immutable_and_version_two_requires_parent(self):
        artifact = QualitativeArtifact.from_bytes(content=b"source", artifact_id="a", project_id="p",
            run_id="r", session_id="s", kind=ArtifactKind.PREPARED_DOCX, media_type="application/docx",
            original_filename="transcript.docx", imported_at=datetime.now(timezone.utc))
        artifact.verify(b"source")
        with self.assertRaises(ValueError):
            artifact.verify(b"changed")
        with self.assertRaises(ValueError):
            self.transcript(parse_prepared_text("P01: answer"), version=2, transcript_version_id="tv2")

    def test_withdrawn_consent_fails_closed_and_ready_requires_eligible_version(self):
        participant = Participant("participant", "p", "r", "P01")
        session = Session("s", "p", "r", "participant")
        artifact = object()
        withdrawn = ConsentRecord("c", "participant", ConsentState.WITHDRAWN,
                                  datetime.now(timezone.utc), "withdrawn")
        transcript = self.transcript(parse_prepared_text("P01: answer"), analysis_eligible=True)
        self.assertEqual(assess_readiness(participant=participant, consent=withdrawn, session=session,
                                         artifact=artifact, transcript=transcript),
                         QualitativeReadiness.CONSENT_NOT_ELIGIBLE)
        eligible = ConsentRecord("c2", "participant", ConsentState.ELIGIBLE,
                                 datetime.now(timezone.utc), "researcher attestation", True)
        self.assertEqual(assess_readiness(participant=participant, consent=eligible, session=session,
                                         artifact=artifact, transcript=transcript),
                         QualitativeReadiness.AUTHORITY_READY_FOR_CODING)

    def test_provider_result_is_bound_to_exact_artifact(self):
        segments = parse_prepared_text("Speaker A: timed")
        provider = DeterministicTranscriptionProvider({"audio-a": segments})
        job = provider.submit(artifact_id="audio-a", content=b"audio", media_type="audio/wav")
        self.assertEqual(provider.result(provider_job_id=job, source_artifact_id="audio-a").segments, segments)
        with self.assertRaises(ValueError):
            provider.result(provider_job_id=job, source_artifact_id="audio-b")


if __name__ == "__main__":
    unittest.main()
