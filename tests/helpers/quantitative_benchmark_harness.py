from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import json
from pathlib import Path
import pickle
import re
from typing import Any, Callable, Mapping

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.quantitative.execution_diagnostics import validate_diagnostics
from application.quantitative.state_persistence import authority_fingerprint
from application.quantitative.workflow import QUANTITATIVE_SAFE_STATE_KEY
from application.ports.quantitative_state_repository import QuantitativeStateRecord
from domain.workflow_status import WorkflowStatus


_UNSAFE_TEXT = re.compile(
    r"authorization|bearer\s+|\bsk-[a-z0-9_-]+|[a-z]:\\|/users/|/home/|"
    r"\.sav\b|\.pptx\b|\.docx\b|respondent|api[_ -]?key",
    re.IGNORECASE,
)


def _safe_text(value: object, limit: int = 256) -> str:
    text = " ".join(str(value).split())
    return "[redacted benchmark diagnostic]" if _UNSAFE_TEXT.search(text) else text[:limit]


class _PickleStore:
    def __init__(self, path: Path, default: dict[str, Any]) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load(default)

    def _load(self, default: dict[str, Any]) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(default)
        with self.path.open("rb") as handle:
            value = pickle.load(handle)
        if not isinstance(value, dict):
            raise ValueError("invalid benchmark repository snapshot")
        return value

    def flush(self) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("wb") as handle:
            pickle.dump(self.data, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temporary.replace(self.path)


class FileBackedBenchmarkProjectRepository:
    def __init__(self, root: Path) -> None:
        self._store = _PickleStore(root / "projects.pickle", {"items": {}, "versions": {}})

    def create(self, project) -> None:
        if project.id in self._store.data["items"]:
            raise DuplicateEntityError(f"Project already exists: {project.id}")
        self._store.data["items"][project.id] = copy.deepcopy(project)
        self._store.data["versions"][project.id] = 0
        self._store.flush()

    def save(self, project, *, expected_version=None) -> int:
        if project.id not in self._store.data["items"]:
            raise EntityNotFoundError(f"Project not found: {project.id}")
        current = self._store.data["versions"][project.id]
        if expected_version is not None and expected_version != current:
            raise ConcurrentModificationError("Project version mismatch")
        self._store.data["items"][project.id] = copy.deepcopy(project)
        self._store.data["versions"][project.id] = current + 1
        self._store.flush()
        return current + 1

    def get_by_id(self, project_id):
        return copy.deepcopy(self._store.data["items"].get(project_id))

    def list(self, *, offset=0, limit=None, owner_principal_id=None):
        values = [self._store.data["items"][key] for key in sorted(self._store.data["items"])]
        if owner_principal_id is not None:
            values = [value for value in values if value.owner_principal_id == owner_principal_id]
        values = values[offset:]
        if limit is not None:
            values = values[:limit]
        return copy.deepcopy(values)

    def delete(self, project_id, *, expected_version=None) -> None:
        if project_id not in self._store.data["items"]:
            raise EntityNotFoundError(f"Project not found: {project_id}")
        current = self._store.data["versions"][project_id]
        if expected_version is not None and expected_version != current:
            raise ConcurrentModificationError("Project version mismatch")
        del self._store.data["items"][project_id]
        del self._store.data["versions"][project_id]
        self._store.flush()


class FileBackedBenchmarkWorkflowRunRepository:
    def __init__(self, root: Path) -> None:
        self._store = _PickleStore(
            root / "workflow-runs.pickle",
            {"runs": {}, "versions": {}, "projects": {}, "results": {}},
        )

    def create(self, workflow_run, *, project_id) -> None:
        if workflow_run.id in self._store.data["runs"]:
            raise DuplicateEntityError(f"WorkflowRun already exists: {workflow_run.id}")
        value = copy.deepcopy(workflow_run)
        value.project_id = project_id
        self._store.data["runs"][value.id] = value
        self._store.data["versions"][value.id] = 0
        self._store.data["results"][value.id] = {}
        self._store.data["projects"].setdefault(project_id, []).append(value.id)
        self._store.flush()

    def get_by_id(self, run_id):
        return copy.deepcopy(self._store.data["runs"].get(run_id))

    def delete(self, run_id) -> None:
        value = self._store.data["runs"].pop(run_id, None)
        if value is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        self._store.data["versions"].pop(run_id, None)
        self._store.data["results"].pop(run_id, None)
        self._store.data["projects"].get(value.project_id, []).remove(run_id)
        self._store.flush()

    def save(self, workflow_run, *, expected_version=None, task_results=None) -> int:
        if workflow_run.id not in self._store.data["runs"]:
            raise EntityNotFoundError(f"WorkflowRun not found: {workflow_run.id}")
        current = self._store.data["versions"][workflow_run.id]
        if expected_version is not None and expected_version != current:
            raise ConcurrentModificationError("WorkflowRun version mismatch")
        self._store.data["runs"][workflow_run.id] = copy.deepcopy(workflow_run)
        if task_results is not None:
            self._store.data["results"][workflow_run.id] = copy.deepcopy(task_results)
        self._store.data["versions"][workflow_run.id] = current + 1
        self._store.flush()
        return current + 1

    def get_task_results(self, run_id):
        return copy.deepcopy(self._store.data["results"].get(run_id, {}))

    def get_version(self, run_id):
        if run_id not in self._store.data["runs"]:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        return self._store.data["versions"][run_id]

    def list_for_project(self, project_id, *, status: WorkflowStatus | None = None):
        values = [
            self._store.data["runs"][run_id]
            for run_id in self._store.data["projects"].get(project_id, ())
        ]
        if status is not None:
            values = [value for value in values if value.status == status]
        return copy.deepcopy(values)


class FileBackedBenchmarkQuantitativeStateRepository:
    def __init__(self, root: Path) -> None:
        self._store = _PickleStore(root / "quantitative-state.pickle", {"records": {}})

    def create(self, record: QuantitativeStateRecord) -> None:
        if record.record_id in self._store.data["records"]:
            raise ValueError("immutable Quantitative record already exists")
        self._store.data["records"][record.record_id] = copy.deepcopy(record)
        self._store.flush()

    def get_for_project(self, record_id, *, project_id):
        value = self._store.data["records"].get(record_id)
        return copy.deepcopy(value) if value is not None and value.project_id == project_id else None

    def list_for_run(self, run_id, *, project_id, record_type=None):
        return tuple(
            copy.deepcopy(value)
            for _, value in sorted(self._store.data["records"].items())
            if value.run_id == run_id
            and value.project_id == project_id
            and (record_type is None or value.record_type == record_type)
        )


@dataclass(frozen=True)
class DurableBenchmarkRepositoryBundle:
    project_repository: FileBackedBenchmarkProjectRepository
    workflow_run_repository: FileBackedBenchmarkWorkflowRunRepository
    quantitative_state_repository: FileBackedBenchmarkQuantitativeStateRepository

    @classmethod
    def open(cls, root: str | Path):
        path = Path(root)
        return cls(
            FileBackedBenchmarkProjectRepository(path),
            FileBackedBenchmarkWorkflowRunRepository(path),
            FileBackedBenchmarkQuantitativeStateRepository(path),
        )


@dataclass
class BenchmarkJournal:
    protocol: str
    source_hashes: Mapping[str, str]
    failure_path: Path
    project_id: str | None = None
    run_id: str | None = None
    phase: str = "PREFLIGHT"
    last_successful_authority: str | None = None
    terminal_result_record_id: str | None = None
    ppt_content_reads: int = 0
    ppt_parses: int = 0
    ppt_renders: int = 0
    ppt_xml_reads: int = 0
    phase_a_freeze_created: bool = False

    def failure_payload(self, error: BaseException, diagnostics: Mapping[str, Any] | None):
        return {
            "artifact_kind": "BENCHMARK_FAILURE",
            "protocol": self.protocol,
            "project_id": self.project_id,
            "workflow_run_id": self.run_id,
            "source_hashes": dict(self.source_hashes),
            "phase": self.phase,
            "exception_class": type(error).__name__,
            "sanitized_message": _safe_text(error),
            "diagnostics": dict(diagnostics or {}),
            "terminal_result_record_id": self.terminal_result_record_id,
            "last_successful_authority": self.last_successful_authority,
            "blindness": {
                "ppt_content_reads": self.ppt_content_reads,
                "ppt_parses": self.ppt_parses,
                "ppt_renders": self.ppt_renders,
                "ppt_xml_reads": self.ppt_xml_reads,
            },
            "phase_a_freeze_created": self.phase_a_freeze_created,
        }

    def run(self, operation: Callable[[], Any], diagnostics_loader=lambda: None):
        try:
            return operation()
        except BaseException as primary:
            try:
                payload = self.failure_payload(primary, diagnostics_loader())
                self.failure_path.parent.mkdir(parents=True, exist_ok=True)
                self.failure_path.write_text(
                    json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
                )
            except BaseException:
                pass
            raise


def resolve_workflow_produced_rh(*, workflow_repository, rh_repository, project_id, run_id):
    results = workflow_repository.get_task_results(run_id)
    safe = results.get(QUANTITATIVE_SAFE_STATE_KEY, {})
    manifest_id = safe.get("rq_coverage_manifest_record_id")
    if not isinstance(manifest_id, str) or not manifest_id:
        raise ValueError("workflow-produced RH manifest is unavailable")
    manifest = rh_repository.get_run_manifest(manifest_id, project_id=project_id)
    if manifest is None or manifest.project_id != project_id or manifest.run_id != run_id:
        raise ValueError("workflow-produced RH manifest has wrong scope")
    assessments = []
    for version_id, fingerprint in manifest.assessment_versions_and_fingerprints:
        value = rh_repository.get_assessment(version_id, project_id=project_id)
        if value is None or authority_fingerprint(value) != fingerprint:
            raise ValueError("workflow-produced RH assessment fingerprint mismatch")
        assessments.append(value)
    return manifest, tuple(assessments)


def durable_diagnostics(*, workflow_repository, project_id, run_id):
    return validate_diagnostics(
        workflow_repository.get_task_results(run_id),
        project_id=project_id,
        run_id=run_id,
    )


def is_phase_a_freeze(path: str | Path) -> bool:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        value.get("artifact_kind") == "PHASE_A_FREEZE"
        and value.get("phase_a_complete") is True
        and isinstance(value.get("freeze_fingerprint"), str)
    )
