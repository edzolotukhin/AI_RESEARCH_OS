from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight

from application.services.finding_service import FindingService, InsightService
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
)
from infrastructure.persistence.memory.in_memory_insight_repository import (
    InMemoryInsightRepository,
)


class RunFindingInsightCountTests(unittest.TestCase):
    def test_finding_and_insight_counts_are_run_specific(self) -> None:
        finding_repo = InMemoryFindingRepository()
        insight_repo = InMemoryInsightRepository()
        finding_service = FindingService(finding_repository=finding_repo)
        insight_service = InsightService(insight_repository=insight_repo)
        now = datetime.now(timezone.utc).isoformat()
        project_id = "project-1"

        def _finding(*, run_id: str, suffix: str) -> None:
            finding_repo.create(
                Finding(
                    id=str(uuid4()),
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="design-1",
                    statement=f"Finding {suffix}",
                    rationale="Rationale",
                    evidence_refs=("evidence-1",),
                    finding_type=FindingType.SYNTHESIS,
                    analysis_method="deterministic",
                    deduplication_key=f"finding-{run_id}-{suffix}",
                    created_at=now,
                ),
            )

        def _insight(*, run_id: str, suffix: str) -> None:
            insight_repo.create(
                Insight(
                    id=str(uuid4()),
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="design-1",
                    statement=f"Insight {suffix}",
                    implication="Implication",
                    finding_refs=("finding-1",),
                    deduplication_key=f"insight-{run_id}-{suffix}",
                    created_at=now,
                ),
            )

        _finding(run_id="run-1", suffix="a")
        _finding(run_id="run-1", suffix="b")
        _insight(run_id="run-1", suffix="a")

        self.assertEqual(finding_service.count_for_run(project_id, "run-1"), 2)
        self.assertEqual(insight_service.count_for_run(project_id, "run-1"), 1)
        self.assertEqual(finding_service.count_for_run(project_id, "run-2"), 0)
        self.assertEqual(insight_service.count_for_run(project_id, "run-2"), 0)

        _finding(run_id="run-2", suffix="c")
        _insight(run_id="run-2", suffix="b")
        _insight(run_id="run-2", suffix="c")

        self.assertEqual(finding_service.count_for_run(project_id, "run-1"), 2)
        self.assertEqual(insight_service.count_for_run(project_id, "run-1"), 1)
        self.assertEqual(finding_service.count_for_run(project_id, "run-2"), 1)
        self.assertEqual(insight_service.count_for_run(project_id, "run-2"), 2)


if __name__ == "__main__":
    unittest.main()
