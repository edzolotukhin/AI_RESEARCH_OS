"""Durable, bounded operational diagnostics for Quantitative execution.

These records are execution audit state, never research evidence authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import re
from typing import Any, Mapping


SEMANTIC_LEDGER_KEY = "_quantitative_semantic_call_ledger"
FAILURE_DIAGNOSTIC_KEY = "_quantitative_failure_diagnostic"
LEDGER_VERSION = "q2-13c-1"
SEMANTIC_STAGES = {"quant_findings": "QI", "quant_insights": "QJ", "quant_report": "QK"}
STAGE_NAMES = {"quant_analysis": "RD", **SEMANTIC_STAGES}
CALL_LIMITS = {"QI": 1, "QJ": 1, "QK": 1}


class QuantitativeExecutionDiagnosticsError(RuntimeError):
    pass


def is_quantitative_diagnostic_stage(definition_id: str) -> bool:
    return definition_id in STAGE_NAMES


def _digest(value: Mapping[str, Any]) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _safe_failure(error: BaseException, *, after_dispatch: bool | None = None) -> tuple[str, str]:
    category = type(error).__name__[:96]
    boundary = " after provider dispatch" if after_dispatch else " before provider dispatch" if after_dispatch is False else ""
    return category, f"{category}{boundary}"[:256]


_PROVIDER_ERROR_KEYS = {
    "status_code", "code", "type", "param", "message", "request_id",
    "exception_class",
}
_SENSITIVE_PROVIDER_TEXT = re.compile(
    r"authorization|bearer\s+|\bsk-[a-z0-9_-]+|[a-z]:\\|/users/|/home/|"
    r"\.sav\b|\.pptx\b|\.docx\b|respondent|raw[_ -]?sav|api[_ -]?key",
    re.IGNORECASE,
)


def _bounded_provider_text(value: Any, *, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = " ".join(value.split())
    if _SENSITIVE_PROVIDER_TEXT.search(normalized):
        return "[redacted provider diagnostic]"
    return normalized[:limit]


def _safe_provider_error(error: BaseException) -> dict[str, Any] | None:
    body = getattr(error, "body", None)
    body_error = body.get("error") if isinstance(body, Mapping) else None
    if not isinstance(body_error, Mapping):
        body_error = body if isinstance(body, Mapping) else {}
    status = getattr(error, "status_code", None)
    metadata = {
        "status_code": status if isinstance(status, int) else None,
        "code": _bounded_provider_text(
            getattr(error, "code", None) or body_error.get("code"), limit=96
        ),
        "type": _bounded_provider_text(
            getattr(error, "type", None) or body_error.get("type"), limit=96
        ),
        "param": _bounded_provider_text(
            getattr(error, "param", None) or body_error.get("param"), limit=96
        ),
        "message": _bounded_provider_text(body_error.get("message"), limit=256),
        "request_id": _bounded_provider_text(
            getattr(error, "request_id", None), limit=128
        ),
        "exception_class": type(error).__name__[:96],
    }
    if not any(
        value is not None
        for key, value in metadata.items()
        if key != "exception_class"
    ):
        return None
    return metadata


def build_stage_failure_diagnostic(context, error: BaseException) -> dict[str, Any]:
    task = context.current_task
    definition_id = task.definition_id if task is not None else "unknown"
    stage = STAGE_NAMES.get(definition_id, definition_id)
    previous = context.shared_state.get(FAILURE_DIAGNOSTIC_KEY)
    attempt = 1
    if isinstance(previous, Mapping) and previous.get("stage_id") == definition_id:
        attempt = int(previous.get("attempt_number", 0)) + 1
    category, message = _safe_failure(error)
    safe = context.shared_state.get("quantitative", {})
    last_authority = None
    if isinstance(safe, Mapping):
        for key in (
            "report_generation_record_id", "insight_generation_record_id",
            "finding_generation_record_id", "analysis_execution_manifest_record_id",
            "analysis_plan_version_id", "qc_approval_id", "codebook_record_id",
            "dataset_record_id",
        ):
            value = safe.get(key)
            if isinstance(value, str) and value:
                last_authority = {"key": key, "record_id": value}
                break
    payload = {
        "project_id": context.project.id,
        "run_id": context.workflow_run.id,
        "task_id": task.id if task is not None else None,
        "stage_id": definition_id,
        "stage": stage,
        "attempt_number": attempt,
        "status": "FAILED",
        "failure_category": category,
        "failure_message": message,
        "terminal_result_persisted": False,
        "last_successful_authority": last_authority,
        "method_version": LEDGER_VERSION,
    }
    payload["fingerprint"] = _digest(payload)
    return payload


class SemanticCallRecorder:
    def __init__(self, context, checkpoint) -> None:
        self.context = context
        self.checkpoint = checkpoint

    def planned(self, *, stage: str, provider: str, model: str, input_fingerprint: str) -> str:
        if stage not in CALL_LIMITS:
            raise QuantitativeExecutionDiagnosticsError("unsupported Quantitative semantic stage")
        entries = self._entries()
        ordinal = 1 + sum(1 for item in entries if item.get("stage") == stage and item.get("status") != "FAILED_BEFORE_DISPATCH")
        if ordinal > CALL_LIMITS[stage]:
            raise QuantitativeExecutionDiagnosticsError("Quantitative semantic call budget is exhausted")
        call_id = f"{self.context.workflow_run.id}:{stage}:{ordinal}"
        if any(item.get("call_id") == call_id for item in entries):
            raise QuantitativeExecutionDiagnosticsError("duplicate Quantitative semantic call ordinal")
        entry = {
            "call_id": call_id, "project_id": self.context.project.id,
            "run_id": self.context.workflow_run.id, "stage": stage,
            "call_ordinal": ordinal, "attempt_ordinal": 1,
            "provider": provider[:64], "model": model[:128],
            "input_authority_fingerprint": input_fingerprint,
            "status": "PLANNED", "dispatched": False, "returned": False,
            "response_authority_fingerprint": None, "failure_classification": None,
            "failure_message": None, "retry_used": False, "retry_ordinal": 0,
            "method_version": LEDGER_VERSION,
        }
        entry["audit_fingerprint"] = _digest(entry)
        entries.append(entry)
        self._store(entries)
        return call_id

    def dispatched(self, call_id: str) -> None:
        self._transition(call_id, "DISPATCHED", dispatched=True)

    def completed(self, call_id: str, response_fingerprint: str) -> None:
        self._transition(call_id, "COMPLETED", returned=True, response_authority_fingerprint=response_fingerprint)

    def returned(self, call_id: str, response_fingerprint: str) -> None:
        self._transition(call_id, "RETURNED", returned=True, response_authority_fingerprint=response_fingerprint)

    def complete_current(self) -> None:
        call_id = self._current_call_id("RETURNED")
        entries = self._entries()
        response_fingerprint = next(item["response_authority_fingerprint"] for item in entries if item["call_id"] == call_id)
        self.completed(call_id, response_fingerprint)

    def fail_current_after_return(self, error: BaseException) -> None:
        self.failed(self._current_call_id("RETURNED"), error, after_dispatch=True)

    def failed(self, call_id: str, error: BaseException, *, after_dispatch: bool) -> None:
        category, message = _safe_failure(error, after_dispatch=after_dispatch)
        changes = {
            "failure_classification": category,
            "failure_message": message,
        }
        provider_error = _safe_provider_error(error)
        if provider_error is not None:
            changes["provider_error_metadata"] = provider_error
        self._transition(
            call_id,
            "FAILED_AFTER_DISPATCH" if after_dispatch else "FAILED_BEFORE_DISPATCH",
            **changes,
        )

    def _entries(self) -> list[dict[str, Any]]:
        value = self.context.shared_state.get(SEMANTIC_LEDGER_KEY, ())
        if not isinstance(value, (list, tuple)):
            raise QuantitativeExecutionDiagnosticsError("semantic call ledger is corrupted")
        return [dict(item) for item in value]

    def _transition(self, call_id: str, status: str, **changes: Any) -> None:
        entries = self._entries()
        matches = [index for index, item in enumerate(entries) if item.get("call_id") == call_id]
        if len(matches) != 1:
            raise QuantitativeExecutionDiagnosticsError("semantic call ledger identity is invalid")
        index = matches[0]
        current = entries[index]
        allowed = {
            "PLANNED": {"DISPATCHED", "FAILED_BEFORE_DISPATCH"},
            "DISPATCHED": {"RETURNED", "FAILED_AFTER_DISPATCH"},
            "RETURNED": {"COMPLETED", "FAILED_AFTER_DISPATCH"},
        }
        if status not in allowed.get(str(current.get("status")), set()):
            raise QuantitativeExecutionDiagnosticsError("impossible semantic call transition")
        current.update(changes)
        current["status"] = status
        current.pop("audit_fingerprint", None)
        current["audit_fingerprint"] = _digest(current)
        entries[index] = current
        self._store(entries)

    def _current_call_id(self, required_status: str) -> str:
        entries = [item for item in self._entries() if item.get("status") == required_status]
        if len(entries) != 1:
            raise QuantitativeExecutionDiagnosticsError("current semantic call is ambiguous")
        return str(entries[0]["call_id"])

    def _store(self, entries: list[dict[str, Any]]) -> None:
        self.context.shared_state[SEMANTIC_LEDGER_KEY] = entries
        if self.checkpoint is not None:
            self.checkpoint.on_task_progress(self.context)


_recorder: ContextVar[SemanticCallRecorder | None] = ContextVar("quantitative_semantic_call_recorder", default=None)


@contextmanager
def semantic_call_recording_scope(context, checkpoint):
    recorder = SemanticCallRecorder(context, checkpoint) if context.current_task and context.current_task.definition_id in SEMANTIC_STAGES else None
    token = _recorder.set(recorder)
    try:
        yield
    finally:
        _recorder.reset(token)


def get_semantic_call_recorder() -> SemanticCallRecorder | None:
    return _recorder.get()


def semantic_stage() -> str | None:
    from application.execution.execution_budget_context import get_execution_stage
    return SEMANTIC_STAGES.get(get_execution_stage() or "")


def validate_diagnostics(task_results: Mapping[str, Any], *, project_id: str, run_id: str) -> dict[str, Any]:
    diagnostic = task_results.get(FAILURE_DIAGNOSTIC_KEY)
    if diagnostic is not None:
        if not isinstance(diagnostic, Mapping) or diagnostic.get("project_id") != project_id or diagnostic.get("run_id") != run_id:
            raise QuantitativeExecutionDiagnosticsError("failure diagnostic has wrong scope")
        raw = dict(diagnostic); fingerprint = raw.pop("fingerprint", None)
        if fingerprint != _digest(raw):
            raise QuantitativeExecutionDiagnosticsError("failure diagnostic is corrupted")
    entries = task_results.get(SEMANTIC_LEDGER_KEY, ())
    if not isinstance(entries, (list, tuple)):
        raise QuantitativeExecutionDiagnosticsError("semantic call ledger is corrupted")
    seen: set[tuple[str, int]] = set()
    counts = {stage: 0 for stage in CALL_LIMITS}
    validated = []
    for item in entries:
        if not isinstance(item, Mapping) or item.get("project_id") != project_id or item.get("run_id") != run_id:
            raise QuantitativeExecutionDiagnosticsError("semantic call ledger has wrong scope")
        raw = dict(item); fingerprint = raw.pop("audit_fingerprint", None)
        if fingerprint != _digest(raw):
            raise QuantitativeExecutionDiagnosticsError("semantic call ledger is corrupted")
        stage = str(item.get("stage"))
        status = str(item.get("status"))
        if stage not in CALL_LIMITS or status not in {
            "PLANNED", "DISPATCHED", "RETURNED", "COMPLETED",
            "FAILED_BEFORE_DISPATCH", "FAILED_AFTER_DISPATCH",
        }:
            raise QuantitativeExecutionDiagnosticsError("semantic call ledger state is invalid")
        identity = (stage, int(item.get("call_ordinal", 0)))
        if identity[1] != 1 or item.get("retry_used") is not False or item.get("retry_ordinal") != 0:
            raise QuantitativeExecutionDiagnosticsError("semantic call retry authority is invalid")
        if identity in seen:
            raise QuantitativeExecutionDiagnosticsError("duplicate semantic call ordinal")
        seen.add(identity)
        dispatched = bool(item.get("dispatched"))
        returned = bool(item.get("returned"))
        if status in {"PLANNED", "FAILED_BEFORE_DISPATCH"} and dispatched:
            raise QuantitativeExecutionDiagnosticsError("pre-dispatch call has dispatch authority")
        if status in {"DISPATCHED", "RETURNED", "COMPLETED", "FAILED_AFTER_DISPATCH"} and not dispatched:
            raise QuantitativeExecutionDiagnosticsError("post-dispatch call was never dispatched")
        if status in {"RETURNED", "COMPLETED"} and not returned:
            raise QuantitativeExecutionDiagnosticsError("returned call has no return authority")
        if returned and not item.get("response_authority_fingerprint"):
            raise QuantitativeExecutionDiagnosticsError("returned call has no response fingerprint")
        provider_error = item.get("provider_error_metadata")
        if provider_error is not None:
            if (
                not isinstance(provider_error, Mapping)
                or set(provider_error) != _PROVIDER_ERROR_KEYS
            ):
                raise QuantitativeExecutionDiagnosticsError("provider error metadata is invalid")
            status_code = provider_error.get("status_code")
            if status_code is not None and not isinstance(status_code, int):
                raise QuantitativeExecutionDiagnosticsError("provider status code is invalid")
            limits = {
                "code": 96, "type": 96, "param": 96, "message": 256,
                "request_id": 128, "exception_class": 96,
            }
            for key, limit in limits.items():
                value = provider_error.get(key)
                if value is not None and (
                    not isinstance(value, str)
                    or len(value) > limit
                    or _SENSITIVE_PROVIDER_TEXT.search(value)
                ):
                    raise QuantitativeExecutionDiagnosticsError(
                        "provider error metadata is unsafe"
                    )
        if item.get("dispatched"):
            counts[stage] += 1
            if counts[stage] > CALL_LIMITS[stage]:
                raise QuantitativeExecutionDiagnosticsError("semantic call budget is exceeded")
        validated.append(dict(item))
    return {
        "failure": dict(diagnostic) if isinstance(diagnostic, Mapping) else None,
        "calls": tuple(validated), "dispatched": counts,
        "total_dispatched": sum(counts.values()),
        "remaining": {stage: CALL_LIMITS[stage] - counts[stage] for stage in CALL_LIMITS},
        "terminal_result_persisted": bool(task_results.get("quantitative", {}).get("terminal_result_record_id")) if isinstance(task_results.get("quantitative"), Mapping) else False,
    }
