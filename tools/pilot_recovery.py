from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    # The recovery image copies the canonical validator as a standalone module
    # so it does not need the application's full runtime dependency graph.
    from structured_json_validator import JsonValidator
except ModuleNotFoundError:  # repository/test execution
    from application.structured_output.json_validator import JsonValidator


SHA = re.compile(r"^[0-9a-f]{40}$")


class RecoveryError(RuntimeError):
    pass


def decode_json(text: str, *, expected: type) -> object:
    result = JsonValidator().validate(text)
    if not result.is_valid or not isinstance(result.data, expected):
        raise RecoveryError("recovery metadata is invalid")
    return result.data


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RecoveryError(f"{name} is required")
    return value


def run(args: list[str], *, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RecoveryError(f"{Path(args[0]).name} operation failed")
    return completed.stdout or ""


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inventory(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise RecoveryError("required protected storage is unavailable")
    return {
        item.relative_to(root).as_posix(): digest(item)
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


def metadata() -> dict[str, object]:
    app_sha = required("APP_SHA")
    if not SHA.fullmatch(app_sha):
        raise RecoveryError("APP_SHA must be an exact full commit SHA")
    return {
        "format": "ai-research-os-pilot-recovery-v1",
        "backup_id": f"pilot-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(UTC).isoformat(),
        "application_sha": app_sha,
        "alembic_head": required("ALEMBIC_HEAD"),
        "deployment_profile": "single-host-pilot-v1",
        "postgres_version": run(["pg_dump", "--version"], capture=True).strip(),
        "authority_classes": ["postgresql", "quant_protected", "project_compatibility"],
    }


def restic_base() -> list[str]:
    password_file = Path(required("RESTIC_PASSWORD_FILE"))
    if not password_file.is_file():
        raise RecoveryError("backup encryption credential is unavailable")
    required("RESTIC_REPOSITORY")
    return ["restic", "--password-file", str(password_file)]


def create_backup() -> None:
    database_url = required("DATABASE_URL")
    protected = Path(required("QUANTITATIVE_PROTECTED_STORAGE_ROOT"))
    projects = Path(required("PROJECTS_ROOT"))
    work = Path(required("BACKUP_WORK_ROOT"))
    work.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    bundle = Path(tempfile.mkdtemp(prefix="pilot-backup-", dir=work))
    try:
        dump = bundle / "postgres.dump"
        run(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump), database_url])
        shutil.copytree(protected, bundle / "protected", dirs_exist_ok=True)
        shutil.copytree(projects, bundle / "projects", dirs_exist_ok=True)
        manifest = metadata()
        manifest["postgres_sha256"] = digest(dump)
        manifest["protected_files"] = inventory(bundle / "protected")
        manifest["project_files"] = inventory(bundle / "projects")
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        output = run(restic_base() + ["backup", "--json", str(bundle)], capture=True)
        summaries = [decode_json(line, expected=dict) for line in output.splitlines() if line.strip()]
        summary = next((item for item in reversed(summaries) if item.get("message_type") == "summary"), None)
        if not summary or not summary.get("snapshot_id"):
            raise RecoveryError("backup completed without a snapshot identity")
        run(restic_base() + ["check", "--read-data-subset=10%"])
        print(json.dumps({
            "status": "backup_complete",
            "backup_id": manifest["backup_id"],
            "snapshot_id": summary["snapshot_id"],
            "duration_seconds": round(time.monotonic() - started, 3),
            "protected_file_count": len(manifest["protected_files"]),
            "project_file_count": len(manifest["project_files"]),
        }, sort_keys=True))
    finally:
        shutil.rmtree(bundle, ignore_errors=True)


def check_repository(full: bool) -> None:
    command = restic_base() + ["check"]
    if full:
        command.append("--read-data")
    run(command)
    print(json.dumps({"status": "repository_integrity_ok", "full_data_read": full}))


def initialize_repository() -> None:
    run(restic_base() + ["init"])
    print(json.dumps({"status": "repository_initialized"}))


def retention() -> None:
    run(restic_base() + [
        "forget", "--keep-daily", "14", "--keep-weekly", "8", "--prune"
    ])
    print(json.dumps({"status": "retention_complete", "daily": 14, "weekly": 8}))


def status() -> None:
    values = decode_json(
        run(restic_base() + ["snapshots", "--json"], capture=True) or "[]",
        expected=list,
    )
    if not values:
        raise RecoveryError("no successful backup snapshot is available")
    latest = max(values, key=lambda item: item["time"])
    created = datetime.fromisoformat(latest["time"].replace("Z", "+00:00"))
    age = (datetime.now(UTC) - created).total_seconds()
    payload = {
        "status": "backup_available",
        "snapshot_id": latest["id"],
        "created_at": latest["time"],
        "age_seconds": round(age, 3),
        "within_24h_policy": age <= 24 * 60 * 60,
    }
    encoded = json.dumps(payload, sort_keys=True)
    status_file = os.environ.get("BACKUP_STATUS_FILE")
    if status_file:
        target = Path(status_file); target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp"); temporary.write_text(encoded, encoding="utf-8"); temporary.replace(target)
    print(encoded)


def ensure_empty(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise RecoveryError("restore target storage is not empty")


def restore(snapshot: str) -> None:
    if required("RESTORE_CONFIRMATION") != "DISPOSABLE_EMPTY_TARGET":
        raise RecoveryError("explicit disposable restore confirmation is required")
    database_url = required("DATABASE_URL")
    protected = Path(required("QUANTITATIVE_PROTECTED_STORAGE_ROOT"))
    projects = Path(required("PROJECTS_ROOT"))
    ensure_empty(protected)
    ensure_empty(projects)
    table_count = run([
        "psql", database_url, "-Atqc",
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
    ], capture=True).strip()
    if table_count != "0":
        raise RecoveryError("restore target database is not empty")
    work = Path(required("BACKUP_WORK_ROOT")); work.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="pilot-restore-", dir=work))
    started = time.monotonic()
    try:
        run(restic_base() + ["restore", snapshot, "--target", str(target)])
        manifests = list(target.rglob("manifest.json"))
        if len(manifests) != 1:
            raise RecoveryError("backup manifest is missing or ambiguous")
        bundle = manifests[0].parent
        manifest = decode_json(manifests[0].read_text(encoding="utf-8"), expected=dict)
        if manifest.get("application_sha") != required("APP_SHA"):
            raise RecoveryError("backup application SHA is incompatible with restore runtime")
        if manifest.get("alembic_head") != required("ALEMBIC_HEAD"):
            raise RecoveryError("backup migration head is incompatible with restore runtime")
        dump = bundle / "postgres.dump"
        if digest(dump) != manifest.get("postgres_sha256"):
            raise RecoveryError("PostgreSQL backup checksum mismatch")
        if inventory(bundle / "protected") != manifest.get("protected_files"):
            raise RecoveryError("protected storage checksum mismatch")
        if inventory(bundle / "projects") != manifest.get("project_files"):
            raise RecoveryError("project storage checksum mismatch")
        run(["pg_restore", "--no-owner", "--no-privileges", "--dbname", database_url, str(dump)])
        shutil.copytree(bundle / "protected", protected, dirs_exist_ok=True)
        shutil.copytree(bundle / "projects", projects, dirs_exist_ok=True)
        run([
            "psql", database_url, "-c",
            "UPDATE browser_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE revoked_at IS NULL",
        ])
        print(json.dumps({
            "status": "restore_complete",
            "backup_id": manifest["backup_id"],
            "snapshot_id": snapshot,
            "duration_seconds": round(time.monotonic() - started, 3),
            "sessions_revoked": True,
        }, sort_keys=True))
    finally:
        shutil.rmtree(target, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Encrypted pilot backup and isolated restore")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("create")
    check = sub.add_parser("check"); check.add_argument("--full", action="store_true")
    sub.add_parser("retention")
    sub.add_parser("status")
    restore_parser = sub.add_parser("restore"); restore_parser.add_argument("snapshot")
    args = parser.parse_args()
    try:
        if args.command == "init": initialize_repository()
        elif args.command == "create": create_backup()
        elif args.command == "check": check_repository(args.full)
        elif args.command == "retention": retention()
        elif args.command == "status": status()
        else: restore(args.snapshot)
        return 0
    except (RecoveryError, OSError) as exc:
        print(f"pilot recovery operation failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
