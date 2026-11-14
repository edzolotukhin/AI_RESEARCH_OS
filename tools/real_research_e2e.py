"""Bounded provider-backed Desk Research E2E driver for disposable CI only.

This driver talks to the running API; planning, Search, worker execution,
Evidence, Analysis, Report and finalization remain the application pipeline.
It intentionally emits aggregate diagnostics only.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _prepare_approved_desk_run(project_id: str) -> str:
    """Use the canonical application design gate in the disposable API runtime."""
    from application.composition_root import create_application_container
    from domain.research_brief import ResearchBrief

    container = create_application_container()
    try:
        project = container.project_service.get_project(project_id)
        project.selected_methods = ("DESK",)
        container.project_service.save_project(project)
        brief = ResearchBrief.from_dict(_brief())
        container.project_planning_service.save_brief(project, brief)
        project = container.project_service.get_project(project_id)
        container.project_planning_service.generate_design(project)
        project = container.project_service.get_project(project_id)
        design = project.current_research_design
        if design is None:
            raise RuntimeError("design generation did not persist a Research Design")
        container.project_planning_service.approve_design(
            project,
            actor_id=project.owner_principal_id or "recovery2-e2e",
            expected_design_id=design.id,
        )
        project = container.project_service.get_project(project_id)
        return container.project_planning_service.activate_desk(project).id
    finally:
        container.shutdown()


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required real-E2E setting: {name}")
    return value


def _json_request(base: str, path: str, *, method: str = "GET", token: str, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.JSONDecoder().decode(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"API {method} {path} returned HTTP {exc.code}: {detail[:400]}") from exc
    except URLError as exc:
        raise RuntimeError(f"API unavailable at {base}: {exc.reason}") from exc


def _count(base: str, path: str, token: str) -> int | None:
    try:
        _, payload = _json_request(base, path, token=token)
    except RuntimeError:
        return None
    value = payload.get("count")
    return int(value) if isinstance(value, int) else None


def _source_acquisition_diagnostics(results: dict) -> dict | None:
    """Return bounded acquisition telemetry from durable task results.

    Keep this projection aggregate-only: source URLs, content, source IDs and
    provider payloads must never be copied into CI diagnostics.
    """
    task_results = results.get("task_results")
    if not isinstance(task_results, list):
        return None
    summary = None
    funnel = None
    for item in task_results:
        snapshot = item.get("snapshot") if isinstance(item, dict) else None
        shared = snapshot.get("shared_state") if isinstance(snapshot, dict) else None
        if not isinstance(shared, dict):
            continue
        candidate = shared.get("source_acquisition")
        if isinstance(candidate, dict):
            summary = candidate
        candidate_funnel = shared.get("research_funnel_v1")
        if isinstance(candidate_funnel, dict):
            funnel = candidate_funnel
    if summary is None and funnel is None:
        return None

    def counts(values) -> dict[str, int]:
        return dict(Counter(str(value) for value in values if value))

    selection = summary.get("selection_decisions", []) if summary else []
    if not isinstance(selection, list):
        selection = []
    selection_counts = counts(item.get("action") for item in selection if isinstance(item, dict))
    decision_reason_counts = counts(item.get("reason") for item in selection if isinstance(item, dict))
    failure_counts = summary.get("failure_category_counts", {}) if summary else {}
    if not isinstance(failure_counts, dict):
        failure_counts = {}

    result = {
        "summary": {
            key: summary.get(key)
            for key in (
                "queries_executed", "candidate_count_raw", "candidate_count_unique",
                "candidates_attempted", "acquired_count", "truncated_count",
                "failed_count", "skipped_duplicate_count", "skipped_budget_count",
                "skipped_ineligible_count", "skipped_exhausted_count",
                "budget_exhausted", "coverage_target_satisfied",
                "information_needs_covered_count", "information_needs_total",
            )
            if summary is not None and key in summary
        },
        "failure_category_counts": {str(key): int(value) for key, value in failure_counts.items()},
        "selection_action_counts": selection_counts,
        "selection_reason_counts": decision_reason_counts,
    }
    if funnel is not None:
        events = funnel.get("events", [])
        if not isinstance(events, list):
            events = []
        result["funnel_event_counts"] = counts(
            event.get("kind") for event in events if isinstance(event, dict)
        )
        result["funnel_reason_counts"] = counts(
            event.get("reason") for event in events if isinstance(event, dict)
        )
        result["funnel_status_counts"] = counts(
            event.get("status") for event in events if isinstance(event, dict)
        )
    return result


def _acceptance_failure(diagnostics: dict) -> str | None:
    status = str(diagnostics.get("workflow_status") or "").lower()
    if status in {"failed", "error", "technical_error"}:
        return "workflow execution failed"
    if diagnostics.get("stage_errors"):
        return "one or more workflow stages failed"
    outcome = str(diagnostics.get("outcome") or "").upper()
    if outcome in {"INSUFFICIENT", "FAILED"}:
        return f"research outcome is {outcome}"
    if diagnostics.get("research_result_error"):
        return "authoritative research result is unavailable"
    if not diagnostics.get("outcome"):
        return "authoritative research outcome is missing"
    return None


def _brief() -> dict:
    return {
        "title": "Динаміка чисельності населення України у 2015–2021 роках",
        "business_question": "Як змінювалася чисельність населення України у 2015–2021 роках?",
        "objectives": ["Встановити річну динаміку чисельності населення України."],
        "geography": ["Україна"],
        "market": "population statistics",
        "target_entities": ["населення України"],
        "timeframe": "2015–2021",
        "constraints": ["Використовувати перевірені публічні статистичні джерела."],
        "deliverables": ["Аналітичний звіт з таблицею та висновками."],
        "language": "uk",
        "context": "Потрібні зіставні річні офіційні дані за 2015–2021 роки.",
        "known_information": [],
        "exclusions": [],
    }


def main() -> int:
    output = Path(os.environ.get("E2E_OUTPUT_DIR", "real_e2e_artifacts"))
    output.mkdir(parents=True, exist_ok=True)
    if os.environ.get("RUN_REAL_E2E") != "true":
        raise RuntimeError("RUN_REAL_E2E must equal true; refusing external calls")
    for name in ("E2E_API_BASE", "E2E_API_KEY", "OPENAI_API_KEY", "SEARCH_API_KEY"):
        _require(name)
    for name in ("E2E_MAX_SECONDS", "LLM_MAX_CALLS_PER_RUN", "SOURCE_MAX_SOURCES_PER_RUN", "LLM_MAX_TOKENS"):
        value = _require(name)
        if not value.isdigit() or int(value) <= 0:
            raise RuntimeError(f"invalid positive numeric limit: {name}")

    base, token = os.environ["E2E_API_BASE"], os.environ["E2E_API_KEY"]
    started = time.monotonic()
    status, project = _json_request(
        base, "/projects", method="POST", token=token,
        payload={"name": "Recovery 2 disposable Ukraine population E2E"},
    )
    project_id = project["id"]
    if os.environ.get("E2E_PREPARE_APPROVED_PROJECT") == "true":
        run_id = _prepare_approved_desk_run(project_id)
    else:
        _, submission = _json_request(
            base, f"/projects/{project_id}/research", method="POST", token=token,
            payload={"brief": _brief()},
        )
        run_id = submission["run_id"]
    deadline = started + int(os.environ["E2E_MAX_SECONDS"])
    terminal = None
    while time.monotonic() < deadline:
        _, terminal = _json_request(base, f"/workflow-runs/{run_id}", token=token)
        if terminal.get("is_terminal"):
            break
        time.sleep(5)
    if not terminal or not terminal.get("is_terminal"):
        raise RuntimeError("real research did not reach a terminal state within E2E_MAX_SECONDS")

    diagnostics = {
        "project_id": project_id,
        "workflow_run_id": run_id,
        "workflow_status": terminal.get("status"),
        "task_statuses": terminal.get("tasks", terminal.get("task_statuses")),
        "source_count": _count(base, f"/projects/{project_id}/sources", token),
        "evidence_count": _count(base, f"/projects/{project_id}/evidence?workflow_run_id={run_id}", token),
        "finding_count": _count(base, f"/projects/{project_id}/findings?workflow_run_id={run_id}", token),
        "insight_count": _count(base, f"/projects/{project_id}/insights?workflow_run_id={run_id}", token),
        "report_count": _count(base, f"/projects/{project_id}/reports?workflow_run_id={run_id}", token),
        "artifact_count": _count(base, f"/workflow-runs/{run_id}/artifacts", token),
    }
    try:
        _, result = _json_request(base, f"/workflow-runs/{run_id}/research-result", token=token)
        for key in ("outcome", "readiness", "budget_usage", "source_summary", "evidence_summary",
                    "finding_summary", "insight_summary", "latest_report", "artifact_status",
                    "provenance_summary", "limitations", "termination_reason"):
            if key in result:
                diagnostics[key] = result[key]
    except RuntimeError as exc:
        diagnostics["research_result_error"] = str(exc)
        diagnostics["research_result_error_expected"] = (
            diagnostics.get("workflow_status", "").lower() in {"failed", "error", "technical_error"}
            and "Ambiguous durable research outcome" in str(exc)
        )

    try:
        _, durable_results = _json_request(base, f"/workflow-runs/{run_id}/results", token=token)
        acquisition = _source_acquisition_diagnostics(durable_results)
        if acquisition is not None:
            diagnostics["source_acquisition_diagnostics"] = acquisition
    except RuntimeError as exc:
        diagnostics["source_acquisition_diagnostics_error"] = str(exc)

    (output / "diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "summary.md").write_text(
        "# Recovery 2 real-provider E2E\n\n" +
        "```json\n" + json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n```\n",
        encoding="utf-8",
    )
    failure = _acceptance_failure(diagnostics)
    if failure:
        diagnostics["acceptance_failure"] = failure
        (output / "diagnostics.json").write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        output = Path(os.environ.get("E2E_OUTPUT_DIR", "real_e2e_artifacts"))
        output.mkdir(parents=True, exist_ok=True)
        (output / "diagnostics.json").write_text(
            json.dumps({"status": "blocked_or_failed", "error_class": type(exc).__name__, "error": str(exc)[:400]}, indent=2),
            encoding="utf-8",
        )
        (output / "summary.md").write_text(
            f"# Recovery 2 real-provider E2E\n\nStatus: blocked_or_failed\n\nError class: `{type(exc).__name__}`\n",
            encoding="utf-8",
        )
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
