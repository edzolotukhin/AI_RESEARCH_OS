from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from uuid import uuid4

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.evidence.provenance_validation import (
    InvalidProvenanceError,
    validate_candidate_provenance,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_subject import LexicalRepresentation
from domain.research_brief import ResearchBrief
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.workflow_status import WorkflowStatus
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    create_test_engine,
    integration_tests_enabled,
    postgresql_application_config,
    reset_schema,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "OW-07 PostgreSQL proof requires a disposable test database",
)
class Ow07ResearchSubjectPostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        reset_schema(self.engine)
        self.addCleanup(self.engine.dispose)

    def _container(self):
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=True,
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()),
        )
        self.addCleanup(container.shutdown)
        return container

    def _approved_project(self, container):
        project = container.project_service.create_project(
            "OW-07 PostgreSQL",
            owner_principal_id="owner",
            selected_methods=("DESK",),
        )
        planner = container.project_planning_service
        planner.save_brief(
            project,
            ResearchBrief(
                title="Ринок преміального корму для собак",
                business_question="Які чинники визначають вибір покупця?",
                objectives=("Оцінити позиціонування",),
                geography=("Україна",),
                market="Преміальний корм для собак",
                timeframe="2026",
                language="uk",
            ),
        )
        planner.generate_design(container.project_service.get_project(project.id))
        project = container.project_service.get_project(project.id)
        design = project.current_research_design
        subject = design.research_subject
        english = LexicalRepresentation(
            representation_id="ow07-en",
            language="en",
            label="premium dog food",
            normalized_phrases=("premium dog food",),
            concept_refs=subject.core_concepts,
            provenance="deterministic_test_proposal",
        )
        project.current_research_design = replace(
            design,
            research_subject=replace(
                subject,
                lexical_representations=(*subject.lexical_representations, english),
                semantic_fingerprint="",
            ),
        )
        container.project_service.save_project(project)
        project = container.project_service.get_project(project.id)
        planner.approve_design(
            project,
            actor_id="owner",
            expected_design_id=project.current_research_design.id,
        )
        return container.project_service.get_project(project.id)

    @staticmethod
    def _fail(container, run):
        run.ready(); run.start(); run.fail()
        container.workflow_service.save_workflow_run(
            run,
            expected_version=container.workflow_service.get_workflow_run_version(run.id),
            task_results={"ow07_failure_marker": {"reason": "sanitized"}},
        )

    def test_design_snapshot_restart_and_retry_chain_preserve_subject_identity(self):
        first = self._container()
        project = self._approved_project(first)
        approved = project.current_research_design.research_subject
        self.assertTrue(approved.executable)
        self.assertEqual({row.language for row in approved.approved_representations}, {"uk", "en"})

        with patch.object(first.project_planning_service.planner, "run",
                          side_effect=AssertionError("Planner rerun")):
            run = first.project_planning_service.activate_desk(project)
        snapshot = first.workflow_service.get_template(run.workflow_template_id).research_design_snapshot
        self.assertEqual(snapshot.research_subject.to_dict(), approved.to_dict())

        first.shutdown()
        restarted = self._container()
        reloaded = restarted.project_service.get_project(project.id)
        self.assertEqual(reloaded.current_research_design.research_subject.to_dict(), approved.to_dict())
        restored_template = restarted.workflow_service.get_template(run.workflow_template_id)
        self.assertEqual(restored_template.research_design_snapshot.research_subject.to_dict(),
                         approved.to_dict())

        self._fail(restarted, restarted.workflow_service.get_workflow_run(run.id))
        with patch.object(restarted.project_planning_service.planner, "run",
                          side_effect=AssertionError("Planner rerun")):
            replacement = restarted.project_planning_service.retry_failed_desk(reloaded)
        self._fail(restarted, replacement)
        with patch.object(restarted.project_planning_service.planner, "run",
                          side_effect=AssertionError("Planner rerun")):
            chained = restarted.project_planning_service.retry_failed_desk(
                restarted.project_service.get_project(project.id),
            )
        self.assertEqual(restarted.workflow_service.get_workflow_run(run.id).status,
                         WorkflowStatus.FAILED)
        for attempt in (replacement, chained):
            frozen = restarted.workflow_service.get_template(
                attempt.workflow_template_id,
            ).research_design_snapshot.research_subject
            self.assertEqual((frozen.subject_id, frozen.version, frozen.semantic_fingerprint),
                             (approved.subject_id, approved.version, approved.semantic_fingerprint))
            self.assertEqual(frozen.lexical_representations, approved.lexical_representations)

    def test_evidence_subject_audit_metadata_round_trips_and_rejected_candidate_is_not_persisted(self):
        container = self._container()
        project = self._approved_project(container)
        design = project.current_research_design
        run = container.project_planning_service.activate_desk(project)
        need = design.information_needs[0]
        question = next(row for row in design.research_questions if row.id == need.research_question_id)
        text = f"{design.research_subject.canonical_label}. {need.description}"
        candidate = EvidenceCandidate(
            statement=text,
            source_excerpt=text,
            evidence_type="direct_excerpt",
            research_question_refs=(),
            information_need_refs=(need.id,),
        )
        validated = validate_candidate_provenance(
            candidate,
            design=design,
            run_context=RunScopedSourceContext(
                run.id, design.id, (need.id,), (question.id,), ("query-1",),
            ),
        )
        audit = validated.metadata["_research_subject_audit"]
        now = datetime.now(timezone.utc).isoformat()
        source = Source(
            id=str(uuid4()), project_id=project.id,
            url="https://example.test/ow07", canonical_url="https://example.test/ow07",
            title="OW-07 fixture", retrieved_at=now,
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text=text, content_checksum="ow07-checksum",
            workflow_run_refs=(run.id,), research_design_refs=(design.id,),
            research_question_refs=(question.id,), information_need_refs=(need.id,),
        )
        container.source_service._source_repository.create(source)
        evidence = Evidence(
            id=str(uuid4()), project_id=project.id, source_id=source.id,
            source_content_checksum=source.content_checksum,
            workflow_run_id=run.id, research_design_id=design.id,
            statement=validated.statement, source_excerpt=validated.source_excerpt,
            evidence_type=EvidenceType.DIRECT_EXCERPT,
            research_question_refs=validated.research_question_refs,
            information_need_refs=validated.information_need_refs,
            deduplication_key="ow07-evidence", created_at=now,
            metadata={"research_subject": audit},
        )
        container.evidence_service._evidence_repository.create(evidence)
        restored = container.evidence_service.get_evidence(evidence.id)
        self.assertEqual(restored.metadata["research_subject"], audit)

        rejected = EvidenceCandidate(
            statement="Automotive brands compete on price and positioning.",
            source_excerpt="Automotive brands compete on price and positioning.",
            evidence_type="direct_excerpt",
            research_question_refs=(),
            information_need_refs=(need.id,),
        )
        with self.assertRaises(InvalidProvenanceError):
            validate_candidate_provenance(
                rejected,
                design=design,
                run_context=RunScopedSourceContext(
                    run.id, design.id, (need.id,), (question.id,), ("query-1",),
                ),
            )
        self.assertEqual(container.evidence_service.count_for_run(project.id, run.id), 1)

    def test_legacy_subjectless_design_round_trips_without_upgrade(self):
        first = self._container()
        project = self._approved_project(first)
        project.current_research_design = replace(
            project.current_research_design,
            research_subject=None,
        )
        first.project_service.save_project(project)
        first.shutdown()
        restarted = self._container()
        restored = restarted.project_service.get_project(project.id)
        self.assertIsNone(restored.current_research_design.research_subject)


if __name__ == "__main__":
    unittest.main()
