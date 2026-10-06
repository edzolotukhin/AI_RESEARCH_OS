from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
from typing import Callable, Iterable

from application.structured_output.json_validator import JsonValidator

_RANK = {"Healthy": 0, "Disabled": 0, "Attention": 1, "Unavailable": 2, "Critical": 3}

@dataclass(frozen=True)
class ComponentStatus:
    name: str
    status: str
    reason: str
    checked_at: datetime

@dataclass(frozen=True)
class JobObservation:
    job_id: str
    job_type: str
    project_id: str | None
    state: str
    updated_at: datetime
    safe_error: str | None = None

@dataclass(frozen=True)
class OperationalSnapshot:
    environment: str
    overall: str
    checked_at: datetime
    components: tuple[ComponentStatus, ...]
    jobs: tuple[JobObservation, ...]
    job_counts: dict[str, int]
    stop_conditions: tuple[str, ...]

def sanitize_detail(value: object) -> str:
    text = str(value or "status unavailable").replace("\r", " ").replace("\n", " ")[:180]
    lowered = text.casefold()
    if any(marker in lowered for marker in ("password", "authorization", "api_key", "token", "database_url", "postgresql://", "postgresql+")):
        return "Operational detail withheld."
    return text

def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

class OperationsStatusService:
    """Aggregate trustworthy, bounded signals without provider calls or mutations."""

    def __init__(self, *, readiness: Callable[[], tuple[bool, str]],
                 jobs: Callable[[], Iterable[JobObservation]] | None = None,
                 now: Callable[[], datetime] | None = None,
                 environment: str | None = None,
                 worker_status_file: str | None = None,
                 backup_status_file: str | None = None,
                 storage_paths: dict[str, str] | None = None,
                 provider_failures: dict[str, int] | None = None) -> None:
        self.readiness = readiness
        self.jobs = jobs or (lambda: ())
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.environment = environment or os.environ.get("APP_ENV", "development")
        self.worker_status_file = worker_status_file or os.environ.get("WORKER_HEARTBEAT_FILE")
        self.backup_status_file = backup_status_file or os.environ.get("BACKUP_STATUS_FILE")
        self.storage_paths = storage_paths or {"Project storage": os.environ.get("PROJECTS_ROOT", "agency/projects"),
                                               "Protected artifacts": os.environ.get("QUANTITATIVE_PROTECTED_STORAGE_ROOT", "")}
        self.provider_failures = provider_failures or {}

    def snapshot(self) -> OperationalSnapshot:
        now = self.now()
        components = [ComponentStatus("API", "Healthy", "Process is serving this page.", now)]
        try:
            ready, reason = self.readiness()
            components.append(ComponentStatus("Database", "Healthy" if ready else "Critical",
                                              "Readiness query succeeded." if ready else sanitize_detail(reason), now))
        except Exception as exc:
            components.append(ComponentStatus("Database", "Unavailable", sanitize_detail(exc), now))
        components.append(self._worker(now))
        observations = tuple(self.jobs())[:50]
        stale = tuple(j for j in observations if j.state in {"queued", "pending", "running", "processing"}
                      and (now - _utc(j.updated_at)).total_seconds() > 30 * 60)
        failed = tuple(j for j in observations if j.state == "failed")
        components.append(ComponentStatus("Jobs", "Critical" if stale else ("Attention" if failed else "Healthy"),
                                          f"{len(stale)} stale; {len(failed)} failed in bounded recent view.", now))
        components.append(self._backup(now))
        components.extend(self._storage(now))
        components.extend(self._providers(now))
        overall = max((c.status for c in components), key=lambda status: _RANK[status])
        counts = {name: sum(j.state in aliases for j in observations) for name, aliases in {
            "queued": {"queued", "pending"}, "running": {"running", "processing"}, "failed": {"failed"}, "completed": {"completed"}}.items()}
        counts["stale"] = len(stale)
        return OperationalSnapshot(self.environment, overall, now, tuple(components), observations, counts,
                                   tuple(c.name for c in components if c.status in {"Critical", "Unavailable"}))

    def _read_status(self, path: str | None) -> dict | None:
        if not path or not Path(path).is_file(): return None
        result = JsonValidator().validate(Path(path).read_text(encoding="utf-8"))
        return result.data if result.is_valid and isinstance(result.data, dict) else None

    def _worker(self, now: datetime) -> ComponentStatus:
        data = self._read_status(self.worker_status_file)
        if not data:
            state = "Unavailable" if self.environment.casefold() in {"pilot", "production", "prod"} else "Disabled"
            return ComponentStatus("Worker", state, "No current worker heartbeat is available.", now)
        try:
            seen = datetime.fromisoformat(str(data["observed_at"]).replace("Z", "+00:00")); age = (now - _utc(seen)).total_seconds()
            return ComponentStatus("Worker", "Healthy" if age <= 90 else "Critical", f"Last heartbeat {int(max(age, 0))} seconds ago.", now)
        except (KeyError, TypeError, ValueError) as exc:
            return ComponentStatus("Worker", "Unavailable", sanitize_detail(exc), now)

    def _backup(self, now: datetime) -> ComponentStatus:
        data = self._read_status(self.backup_status_file)
        if not data:
            state = "Unavailable" if self.environment.casefold() in {"pilot", "production", "prod"} else "Disabled"
            return ComponentStatus("Backup", state, "Backup status is not available in this environment.", now)
        fresh = data.get("within_24h_policy") is True
        return ComponentStatus("Backup", "Healthy" if fresh else "Critical", "Latest snapshot is within the accepted 24-hour policy." if fresh else "Latest successful backup is overdue.", now)

    def _storage(self, now: datetime) -> list[ComponentStatus]:
        values = []
        for label, raw in self.storage_paths.items():
            if not raw: values.append(ComponentStatus(label, "Disabled", "Storage is not configured here.", now)); continue
            try:
                usage = shutil.disk_usage(Path(raw)); percent = round(usage.used * 100 / usage.total, 1)
                state = "Critical" if percent >= 90 else ("Attention" if percent >= 70 else "Healthy")
                values.append(ComponentStatus(label, state, f"{percent}% used; {usage.free // (1024**3)} GiB free.", now))
            except OSError as exc: values.append(ComponentStatus(label, "Unavailable", sanitize_detail(exc), now))
        return values

    def _providers(self, now: datetime) -> list[ComponentStatus]:
        configured = (("Search provider", bool(os.environ.get("SEARCH_API_KEY")), "Desk source discovery"),
                      ("Transcription provider", os.environ.get("ALLOW_PARTICIPANT_DATA_EXTERNAL_TRANSCRIPTION", "0").casefold() in {"1", "true", "yes"}, "Qualitative transcription"))
        values = []
        for name, enabled, purpose in configured:
            failures = int(self.provider_failures.get(name, 0))
            if not enabled: values.append(ComponentStatus(name, "Disabled", f"{purpose}: disabled by configuration or privacy policy.", now))
            elif failures >= 3: values.append(ComponentStatus(name, "Attention", f"{failures} recent operational failures; no provider ping was made.", now))
            else: values.append(ComponentStatus(name, "Healthy", f"{purpose}: configured; no provider ping was made.", now))
        return values
