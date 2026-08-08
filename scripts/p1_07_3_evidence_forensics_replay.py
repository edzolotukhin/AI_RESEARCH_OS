"""P1-07.3 offline evidence extraction forensics replay (no providers).

Replays the evidence extraction path using persisted source/context data when
available, or deterministic fixtures when historical LLM responses were not
persisted.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUN_ID = os.environ.get(
    "FORENSICS_RUN_ID",
    "e81ef916-9c5f-47cc-b8af-7a1e2e110802",
)


def _fixture_replay() -> dict:
    """Deterministic replay when historical LLM payloads are unavailable."""
    from datetime import datetime, timezone

    from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
    from domain.sources.retrieval_status import RetrievalStatus
    from domain.sources.source import Source

    from application.evidence.evidence_extraction_service import EvidenceExtractionService
    from application.evidence.evidence_extraction_diagnostics import (
        EvidenceStageFailureClassification,
    )
    from application.execution.execution_budget import ExecutionBudget
    from application.execution.execution_budget_context import (
        _current_budget,
        ensure_run_budget,
        set_execution_stage,
    )
    from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
    from infrastructure.persistence.memory.in_memory_evidence_repository import (
        InMemoryEvidenceRepository,
    )
    from infrastructure.persistence.memory.in_memory_source_repository import (
        InMemorySourceRepository,
    )
    from runtime.workflow_context import WorkflowContext
    from domain.factories.workflow_run_factory import WorkflowRunFactory
    from domain.factories.task_factory import TaskFactory
    from domain.project import Project
    from domain.workflow_template import WorkflowTemplate
    from domain.task_definition import TaskDefinition
    from domain.value_objects.executor_type import ExecutorType
    from domain.evidence.evidence_type import EvidenceType

    class _ZeroCandidateBudgetedExtractor(EvidenceExtractor):
        """Simulates 8 LLM calls returning zero grounded candidates."""

        method_name = "replay-fixture"

        def extract(self, *, source, design, run_context):
            budget = _current_budget.get()
            if budget is not None:
                budget.assert_can_call("evidence")
                budget.record_llm_call("evidence", output_tokens=3647, reasoning_tokens=3440)
            return []

    design = ResearchDesign(
        id="design-replay",
        research_questions=(
            ResearchQuestion(id="RQ1", question="Question?", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(id="IN1", research_question_id="RQ1", description="Need 1"),
            InformationNeed(id="IN2", research_question_id="RQ1", description="Need 2"),
            InformationNeed(id="IN3", research_question_id="RQ1", description="Need 3"),
        ),
    )
    template = WorkflowTemplate(
        id="tpl-replay",
        name="Replay",
        task_definitions=[
            TaskDefinition(
                id="task-extract-evidence",
                name="Extract",
                executor_id="evidence",
                executor_type=ExecutorType.AGENT,
            ),
        ],
        research_design_snapshot=design,
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = RUN_ID
    context = WorkflowContext(
        project=Project(id="project-replay", name="Replay"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]

    now = datetime.now(timezone.utc).isoformat()
    source_repo = InMemorySourceRepository()
    for index, need_id in enumerate(("IN1", "IN2", "IN3"), start=1):
        source_repo.create(
            Source(
                id=f"source-{index}",
                project_id="project-replay",
                url=f"https://example.com/{index}",
                canonical_url=f"https://example.com/{index}",
                title=f"Source {index}",
                retrieved_at=now,
                retrieval_status=RetrievalStatus.ACQUIRED,
                content_text=("Serbia microgreens market content " * 4000)[:12000 + index],
                content_checksum=f"checksum-{index}",
                workflow_run_refs=(RUN_ID,),
                research_design_refs=("design-replay",),
                information_need_refs=(need_id,),
                research_question_refs=("RQ1",),
                metadata={
                    "discovery_records": [
                        {
                            "provider": "tavily",
                            "query_id": f"sq-{need_id}",
                            "rank": 1,
                            "workflow_run_id": RUN_ID,
                            "research_design_id": "design-replay",
                        },
                    ],
                },
            ),
        )

    service = EvidenceExtractionService(
        evidence_extractor=_ZeroCandidateBudgetedExtractor(),
        evidence_repository=InMemoryEvidenceRepository(),
        source_repository=source_repo,
    )
    budget = ExecutionBudget(evidence_max_llm_calls=8)
    ensure_run_budget(context)
    context.execution_metadata["execution_budget"] = budget
    _current_budget.set(budget)
    set_execution_stage("evidence")

    diagnostics_holder: list = []

    class _CapturingService(EvidenceExtractionService):
        def _extract_work_queue(self, queue, **kwargs):
            kwargs["allow_empty_failure"] = False
            summary = super()._extract_work_queue(queue, **kwargs)
            diagnostics_holder.append(summary.diagnostics)
            return summary

    capturing = _CapturingService(
        evidence_extractor=_ZeroCandidateBudgetedExtractor(),
        evidence_repository=InMemoryEvidenceRepository(),
        source_repository=source_repo,
    )
    summary = capturing.extract_for_context(context)
    diagnostics = diagnostics_holder[0]
    return {
        "mode": "fixture_replay",
        "run_id": RUN_ID,
        "historical_llm_responses_available": False,
        "replay_boundary": "extractor_returns_empty_candidates",
        "summary": summary.to_dict(),
        "failure_classification": diagnostics.failure_classification,
        "expected_live_classification": EvidenceStageFailureClassification.NO_CANDIDATES.value,
        "notes": [
            "Historical LLM responses for run were not persisted locally.",
            "Fixture reproduces cap=8, zero-candidate path only.",
            "Cannot prove exact live rejection mix without stored LLM payloads.",
        ],
    }


def _database_replay() -> dict | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None

    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    out: dict = {"mode": "database_replay", "run_id": RUN_ID}

    with engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT id, project_id, status, workflow_template_id, task_results "
                "FROM workflow_runs WHERE id = :run_id"
            ),
            {"run_id": RUN_ID},
        ).mappings().first()
        if run is None:
            out["error"] = "run_not_found"
            return out

        out["workflow_status"] = run["status"]
        task_results = run["task_results"] or {}
        shared = task_results.get("shared_state") or {}
        out["shared_state_keys"] = sorted(shared.keys())
        out["evidence_extraction"] = shared.get("evidence_extraction")
        out["run_usage_summary"] = task_results.get("_run_usage_summary")

        sources = conn.execute(
            text(
                "SELECT id, content_checksum, retrieval_status, "
                "length(content_text) AS content_length, information_need_refs "
                "FROM sources WHERE :run_id = ANY(workflow_run_refs)"
            ),
            {"run_id": RUN_ID},
        ).mappings().all()
        out["sources"] = [dict(row) for row in sources]
        out["source_count"] = len(sources)

        evidence = conn.execute(
            text("SELECT id, source_id, information_need_refs FROM evidence WHERE workflow_run_id = :run_id"),
            {"run_id": RUN_ID},
        ).mappings().all()
        out["evidence_rows"] = [dict(row) for row in evidence]
        out["evidence_count"] = len(evidence)

    out["historical_llm_responses_available"] = False
    out["replay_boundary"] = "database_metadata_only"
    out["notes"] = [
        "Sources and usage summary may be replayed from DB when DATABASE_URL is set.",
        "LLM extraction payloads were not persisted; exact candidate replay unavailable.",
    ]
    return out


def main() -> None:
    payload: dict = {"run_id": RUN_ID}
    db_result = _database_replay()
    if db_result is not None:
        payload["database"] = db_result

    payload["fixture"] = _fixture_replay()

    output_path = Path(os.environ.get("FORENSICS_OUTPUT", "artifacts/p1_07_3_evidence_forensics.json"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Wrote {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
