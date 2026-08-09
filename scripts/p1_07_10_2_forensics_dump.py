"""Read-only P1-07.10.2 forensic dump. No provider calls."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

from sqlalchemy import create_engine, text

RUN_ID = os.environ.get("FORENSICS_RUN_ID", "22678610-f5cd-4956-a96f-fd758c510716")


def main() -> None:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://ai_research_os:ai_research_os_dev@localhost:5432/ai_research_os",
    )
    engine = create_engine(url)
    out: dict = {"run_id": RUN_ID}
    with engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT id, project_id, status, workflow_template_id, task_results "
                "FROM workflow_runs WHERE id = :run_id"
            ),
            {"run_id": RUN_ID},
        ).mappings().first()
        if run is None:
            raise SystemExit(f"Run not found: {RUN_ID}")
        task_results = run["task_results"] or {}
        shared: dict = {}
        for payload in task_results.values():
            if not isinstance(payload, dict):
                continue
            snapshot = payload.get("shared_state")
            if not isinstance(snapshot, dict):
                continue
            if "research_readiness" in snapshot or len(snapshot) >= len(shared):
                shared = snapshot
        submission = conn.execute(
            text(
                "SELECT correlation_id, source "
                "FROM research_submissions WHERE run_id = :run_id"
            ),
            {"run_id": RUN_ID},
        ).mappings().first()
        out["workflow_run"] = {
            "id": str(run["id"]),
            "project_id": str(run["project_id"]),
            "status": run["status"],
            "workflow_template_id": str(run["workflow_template_id"]),
            "correlation_id": (submission or {}).get("correlation_id"),
            "source": (submission or {}).get("source"),
        }
        tasks = conn.execute(
            text(
                "SELECT task_id, definition_id, name, status, executor_id "
                "FROM workflow_tasks WHERE workflow_run_id = :run_id "
                "ORDER BY sort_order"
            ),
            {"run_id": RUN_ID},
        ).mappings().all()
        out["tasks"] = [dict(t) for t in tasks]

        tpl = conn.execute(
            text("SELECT snapshot_data FROM workflow_templates WHERE id = :id"),
            {"id": run["workflow_template_id"]},
        ).mappings().first()
        snap = (tpl or {}).get("snapshot_data") or {}
        design = (
            snap.get("research_design_snapshot")
            or snap.get("research_design")
            or {}
        )
        needs = design.get("information_needs") or []
        out["design"] = {
            "id": design.get("id"),
            "rq_count": len(design.get("research_questions") or []),
            "in_count": len(needs),
            "needs": [
                {
                    "id": n.get("id"),
                    "priority": n.get("priority"),
                    "research_question_id": n.get("research_question_id"),
                    "has_evidence_expectation": bool(n.get("evidence_expectation")),
                }
                for n in needs
            ],
        }

        evidence_rows = conn.execute(
            text(
                "SELECT id, information_need_refs, research_question_refs "
                "FROM evidence WHERE workflow_run_id = :run_id"
            ),
            {"run_id": RUN_ID},
        ).mappings().all()
        per_in: Counter[str] = Counter()
        for item in evidence_rows:
            refs = item["information_need_refs"] or []
            if not refs:
                per_in["<none>"] += 1
            for need_id in refs:
                per_in[str(need_id)] += 1
        out["evidence_persist_count"] = len(evidence_rows)
        out["evidence_per_information_need"] = dict(sorted(per_in.items()))
        out["unique_ins_with_evidence"] = sorted(
            k for k in per_in if k != "<none>"
        )

        out["source_acquisition"] = shared.get("source_acquisition")
        ev = shared.get("evidence_extraction") or {}
        diag = ev.get("diagnostics") or {}
        out["evidence_extraction_summary"] = {
            "sources_processed": ev.get("sources_processed"),
            "evidence_extracted": ev.get("evidence_extracted"),
            "sources_without_evidence": ev.get("sources_without_evidence"),
            "budget_stop_reason": ev.get("budget_stop_reason") or diag.get("budget_stop_reason"),
            "failure_classification": diag.get("failure_classification"),
            "extractor_attempts": diag.get("extractor_attempts"),
            "raw_candidates": diag.get("raw_candidates"),
            "persisted_evidence": diag.get("persisted_evidence"),
            "response_classification_counts": diag.get("response_classification_counts"),
            "work_item_count": len(diag.get("work_items") or []),
        }
        calls = []
        for idx, item in enumerate(diag.get("work_items") or []):
            inners = item.get("inner_chunks") or []
            nested = ((inners[0] or {}).get("response_shape") if inners else None) or {}
            shape = item.get("response_shape") or nested or {}
            completion = shape.get("completion") or nested.get("completion") or {}
            calls.append(
                {
                    "queue": idx,
                    "source_id": item.get("source_id"),
                    "information_need_ids": item.get("information_need_ids"),
                    "response_classification": shape.get("response_classification")
                    or item.get("response_classification"),
                    "finish_reason": completion.get("finish_reason")
                    or shape.get("finish_reason"),
                    "incomplete_reason": completion.get("incomplete_reason")
                    or shape.get("incomplete_reason"),
                    "was_truncated": completion.get("was_truncated")
                    or shape.get("was_truncated"),
                    "output_tokens": completion.get("output_tokens")
                    or shape.get("output_tokens"),
                    "reasoning_tokens": completion.get("reasoning_tokens")
                    or shape.get("reasoning_tokens"),
                    "max_output_tokens": completion.get("max_output_tokens")
                    or shape.get("max_output_tokens"),
                    "configured_reasoning_effort": completion.get(
                        "configured_reasoning_effort"
                    )
                    or shape.get("completion_configured_reasoning_effort"),
                    "response_length": completion.get("response_length")
                    or shape.get("visible_output_length"),
                    "parsed_root": shape.get("parsed_root_type") or shape.get("parsed_root"),
                    "items_pre": shape.get("items_count_pre_filter"),
                    "items_post": shape.get("items_count_post_filter"),
                    "raw_candidates": item.get("raw_candidate_count"),
                    "exception": item.get("exception_class") or item.get("exception"),
                    "extractor_status": item.get("extractor_status"),
                }
            )
        out["evidence_provider_calls"] = calls

        readiness = shared.get("research_readiness") or {}
        out["readiness"] = {
            "ready_for_analysis": readiness.get("ready_for_analysis"),
            "research_outcome": readiness.get("research_outcome"),
            "targeted_research_required": readiness.get("targeted_research_required"),
            "termination_reason": readiness.get("termination_reason"),
            "research_loop_count": readiness.get("research_loop_count"),
            "research_loop_termination_reason": readiness.get(
                "research_loop_termination_reason"
            ),
            "blocking_information_need_ids": readiness.get(
                "blocking_information_need_ids"
            ),
            "blocking_research_question_ids": readiness.get(
                "blocking_research_question_ids"
            ),
        }
        need_rows = []
        for rq in readiness.get("research_question_assessments") or []:
            for need in rq.get("information_need_assessments") or []:
                need_rows.append(
                    {
                        "information_need_id": need.get("information_need_id"),
                        "research_question_id": need.get("research_question_id"),
                        "status": need.get("status"),
                        "evidence_count": need.get("evidence_count"),
                        "confidence": need.get("confidence"),
                        "missing_aspects": need.get("missing_aspects"),
                        "gap_types": need.get("gap_types"),
                        "reason": need.get("reason"),
                    }
                )
        if not need_rows:
            for need in readiness.get("information_need_assessments") or []:
                need_rows.append(
                    {
                        "information_need_id": need.get("information_need_id"),
                        "research_question_id": need.get("research_question_id"),
                        "status": need.get("status"),
                        "evidence_count": need.get("evidence_count"),
                        "confidence": need.get("confidence"),
                        "missing_aspects": need.get("missing_aspects"),
                        "gap_types": need.get("gap_types"),
                        "reason": need.get("reason"),
                    }
                )
        out["need_assessments"] = need_rows
        loop = shared.get("research_loop_state") or {}
        out["research_loop_state"] = {
            "current_round": loop.get("current_round"),
            "research_loop_count": loop.get("research_loop_count"),
            "termination_reason": loop.get("termination_reason"),
            "gap_attempt_counts": loop.get("gap_attempt_counts"),
            "pending_targeted_need_id": loop.get("pending_targeted_need_id"),
            "history": loop.get("history") or readiness.get("research_loop_history"),
        }
        out["run_usage_in_task_results"] = task_results.get("_run_usage_summary")
        out["run_usage_in_shared_state"] = shared.get("run_usage_summary")
        out["shared_state_keys"] = sorted(shared.keys())
        out["source_acquisition_summary"] = shared.get("source_acquisition")

    dest = os.environ.get(
        "FORENSICS_OUT",
        "artifacts/acceptance/p1_07_10_2_forensics.json",
    )
    with open(dest, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, default=str)
    print(f"wrote {dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
