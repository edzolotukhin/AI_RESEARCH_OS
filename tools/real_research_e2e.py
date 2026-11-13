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
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
            return response.status, json.loads(response.read().decode("utf-8"))
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

    (output / "diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "summary.md").write_text(
        "# Recovery 2 real-provider E2E\n\n" +
        "```json\n" + json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n```\n",
        encoding="utf-8",
    )
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
