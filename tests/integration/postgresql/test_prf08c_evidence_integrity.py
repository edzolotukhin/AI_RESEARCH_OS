"""Disposable PostgreSQL round trip for PRF-08C integrity metadata."""

from __future__ import annotations

import unittest
from hashlib import sha256
from application.evidence.grounding import verify_grounding
from datetime import datetime, timezone
from uuid import uuid4

from application.evidence.temporal_scope import qualifying_evidence
from application.research_quality.deterministic_sufficiency_evaluator import DeterministicSufficiencyEvaluator
from domain.evidence.evidence import Evidence
from domain.factories.project_factory import ProjectFactory
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief
from domain.sources.source import Source
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL test database required")
class Prf08cEvidenceIntegrityPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_prf08e_undated_definition_is_eligible_after_jsonb_roundtrip(self) -> None:
        project = ProjectFactory().create("PRF-08E synthetic definition")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        source_repo = PostgreSQLSourceRepository(self.session_factory)
        evidence_repo = PostgreSQLEvidenceRepository(self.session_factory)
        source_id = str(uuid4())
        content = "A connector is defined as an outlet on a device."
        checksum = sha256(content.encode()).hexdigest()
        source_repo.create(Source(
            id=source_id, project_id=project.id,
            url="https://example.test/definitions",
            canonical_url="https://example.test/definitions",
            title="Synthetic definitions", retrieved_at=datetime.now(timezone.utc).isoformat(),
            content_text="A connector is defined as an outlet on a device.",
            content_checksum=checksum,
        ))
        evidence_repo.create(Evidence(
            id=str(uuid4()), project_id=project.id, source_id=source_id,
            source_content_checksum=checksum, workflow_run_id="synthetic-prf08e-run",
            source_locator=verify_grounding(source_text=content, excerpt=content).to_dict(),
            research_design_id="synthetic-design", statement="A connector is defined as an outlet",
            source_excerpt="A connector is defined as an outlet on a device.",
            created_at=datetime.now(timezone.utc).isoformat(),
            research_question_refs=("RQ1",), information_need_refs=("IN1",),
            deduplication_key="synthetic-definition",
        ))
        loaded = evidence_repo.list_for_project(project.id, workflow_run_id="synthetic-prf08e-run")
        self.assertEqual(len(loaded), 1)
        self.assertNotIn("observation_period", loaded[0].metadata)
        design = ResearchDesign(
            id="synthetic-design", research_questions=(ResearchQuestion(id="RQ1", question="Definitions?"),),
            information_needs=(InformationNeed(
                id="IN1", research_question_id="RQ1", description="Connector definition and classification",
            ),),
        )
        brief = ResearchBrief(title="Synthetic", business_question="Definitions?",
                              timeframe="1 January 2025 to 1 July 2026")
        self.assertEqual(len(qualifying_evidence(design=design, evidence=loaded, brief=brief,
                                               source_repository=source_repo)), 1)

    def test_lineage_and_period_survive_jsonb_roundtrip(self) -> None:
        project = ProjectFactory().create("PRF-08C synthetic persistence")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        source_repo = PostgreSQLSourceRepository(self.session_factory)
        evidence_repo = PostgreSQLEvidenceRepository(self.session_factory)
        now = datetime.now(timezone.utc).isoformat()
        records = (
            ("official", "1 July 2026"),
            ("provider", "August 2026"),
        )
        for label, period in records:
            source_id = str(uuid4())
            content = f"Observed {period} from shared dataset."
            checksum = sha256(content.encode()).hexdigest()
            source_repo.create(Source(
                id=source_id, project_id=project.id,
                url=f"https://{label}.example.test/data",
                canonical_url=f"https://{label}.example.test/data",
                title=label, retrieved_at=now,
                content_text=f"Observed {period} from shared dataset.",
                content_checksum=checksum,
            ))
            evidence_repo.create(Evidence(
                id=str(uuid4()), project_id=project.id, source_id=source_id,
                source_content_checksum=checksum,
                source_locator=verify_grounding(source_text=content, excerpt=content).to_dict(),
                workflow_run_id="synthetic-prf08c-run", research_design_id="synthetic-design",
                statement=f"Count as at {period}", source_excerpt=f"Observed {period} from shared dataset.",
                created_at=now, research_question_refs=("RQ1",), information_need_refs=("IN1",),
                deduplication_key=f"dedup-{label}",
                metadata={
                    "observation_period": period,
                    "data_lineage": {"status": "established", "origin_id": "shared-dataset"},
                },
            ))
        loaded = evidence_repo.list_for_project(project.id, workflow_run_id="synthetic-prf08c-run")
        self.assertEqual(len(loaded), 2)
        self.assertEqual({item.metadata["observation_period"] for item in loaded}, {"1 July 2026", "August 2026"})
        design = ResearchDesign(
            id="synthetic-design",
            research_questions=(ResearchQuestion(id="RQ1", question="What changed?"),),
            information_needs=(InformationNeed(
                id="IN1", research_question_id="RQ1", description="Observed count",
                timeframe="1 January 2025 to 1 July 2026",
            ),),
        )
        brief = ResearchBrief(
            title="Synthetic study", business_question="What changed?",
            timeframe="1 January 2025 to 1 July 2026; sources available by 25 September 2026",
        )
        eligible = qualifying_evidence(design=design, evidence=loaded, brief=brief, source_repository=source_repo)
        self.assertEqual(len(eligible), 1)
        signals = DeterministicSufficiencyEvaluator().evaluate(design=design, evidence=eligible)
        self.assertEqual(signals[0].independent_source_count, 1)


if __name__ == "__main__":
    unittest.main()
