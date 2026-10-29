"""Fail-closed production/pilot deployment entrypoint.

Every Compose command is pinned to the pilot file, pilot environment and the
``app`` project.  The module is deliberately dependency-free so its invariant
checks can be unit-tested without a Docker daemon.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROJECT_NAME = "app"
COMPOSE_FILE = "docker-compose.pilot.yml"
ENV_FILE = ".env.pilot"
REQUIRED_SERVICES = ("postgres", "api", "worker")
BACKEND_NETWORK = "app_pilot_backend"
POSTGRES_VOLUME = "app_pilot_postgres_data"
COMPOSE_WAIT_TIMEOUT_SECONDS = "120"
CRITICAL_SOURCE_FILES = (
    "application/report/claim_numeric_composition.py",
    "application/report/editorial_composer.py",
    "application/runtime/workflow_runtime_persister.py",
)


class DeploymentGuardError(RuntimeError):
    pass


def compose_command(*args: str) -> tuple[str, ...]:
    return (
        "docker", "compose", "--project-name", PROJECT_NAME,
        "--env-file", ENV_FILE, "--file", COMPOSE_FILE, *args,
    )


@dataclass
class Runner:
    root: Path
    dry_run: bool = False

    def run(self, command: Iterable[str], *, mutate: bool = False) -> str:
        values = tuple(command)
        if mutate and values[:2] == ("docker", "compose"):
            assert_pinned_compose_command(values)
        print("+ " + " ".join(values))
        if self.dry_run and mutate:
            return ""
        completed = subprocess.run(
            values, cwd=self.root, text=True, capture_output=True,
            encoding="utf-8", errors="replace",
        )
        if completed.returncode:
            message = (completed.stderr or completed.stdout).strip()[-2000:]
            raise DeploymentGuardError(
                f"command failed ({completed.returncode}): {values[0]}: {message}"
            )
        return completed.stdout.strip()


def assert_pinned_compose_command(command: tuple[str, ...]) -> None:
    required = {
        ("--project-name", PROJECT_NAME),
        ("--env-file", ENV_FILE),
        ("--file", COMPOSE_FILE),
    }
    pairs = set(zip(command, command[1:]))
    if not required <= pairs:
        raise DeploymentGuardError("production Compose command is not pilot-pinned")


def validate_release_sha(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value or "") is None:
        raise DeploymentGuardError("release SHA must be exactly 40 lowercase hexadecimal characters")
    return value


def validate_clean_head(*, supplied_sha: str, head: str, status: str) -> None:
    if head != supplied_sha:
        raise DeploymentGuardError(f"checkout HEAD {head} does not equal requested release {supplied_sha}")
    if status.strip():
        raise DeploymentGuardError("tracked checkout contains modifications")


def _network_names(service: dict[str, Any]) -> set[str]:
    networks = service.get("networks") or {}
    return set(networks if isinstance(networks, dict) else networks)


def validate_compose_topology(config: dict[str, Any]) -> None:
    if config.get("name") != PROJECT_NAME:
        raise DeploymentGuardError("Compose project is not app")
    services = config.get("services")
    if not isinstance(services, dict) or not set(REQUIRED_SERVICES) <= set(services):
        raise DeploymentGuardError("required pilot services are missing")
    networks = config.get("networks") or {}
    backend = networks.get("pilot_backend") if isinstance(networks, dict) else None
    if not isinstance(backend, dict) or backend.get("name") != BACKEND_NETWORK:
        raise DeploymentGuardError("pilot backend network resolves unexpectedly")
    for service_name in REQUIRED_SERVICES:
        if "pilot_backend" not in _network_names(services[service_name]):
            raise DeploymentGuardError(f"{service_name} is outside pilot_backend")
    volumes = config.get("volumes") or {}
    postgres_volume = volumes.get("pilot_postgres_data") if isinstance(volumes, dict) else None
    if not isinstance(postgres_volume, dict) or postgres_volume.get("name") != POSTGRES_VOLUME:
        raise DeploymentGuardError("pilot PostgreSQL volume resolves unexpectedly")
    mounts = services["postgres"].get("volumes") or []
    if not any(
        isinstance(item, dict)
        and item.get("type") == "volume"
        and item.get("source") == "pilot_postgres_data"
        and item.get("target") == "/var/lib/postgresql/data"
        for item in mounts
    ):
        raise DeploymentGuardError("postgres is not mounted on pilot_postgres_data")


def parse_alembic_heads(output: str) -> tuple[str, ...]:
    return tuple(
        line.split()[0] for line in output.splitlines()
        if "(head)" in line and line.split()
    )


def assert_single_migration_head(*, heads_output: str, current_output: str) -> str:
    heads = parse_alembic_heads(heads_output)
    if len(heads) != 1:
        raise DeploymentGuardError(f"expected one Alembic head, found {len(heads)}")
    if heads[0] not in current_output:
        raise DeploymentGuardError("database revision does not equal repository Alembic head")
    return heads[0]


def assert_container_topology(inspections: dict[str, dict[str, Any]]) -> None:
    for service in REQUIRED_SERVICES:
        value = inspections.get(service)
        if not isinstance(value, dict):
            raise DeploymentGuardError(f"running {service} container is missing")
        networks = value.get("NetworkSettings", {}).get("Networks", {})
        if BACKEND_NETWORK not in networks:
            raise DeploymentGuardError(f"running {service} is outside {BACKEND_NETWORK}")
        if "app_default" in networks:
            raise DeploymentGuardError(f"running {service} is attached to app_default")
    mounts = inspections["postgres"].get("Mounts", ())
    if not any(
        item.get("Type") == "volume"
        and item.get("Name") == POSTGRES_VOLUME
        and item.get("Destination") == "/var/lib/postgresql/data"
        for item in mounts if isinstance(item, dict)
    ):
        raise DeploymentGuardError("running postgres does not use the protected pilot volume")


def assert_healthy(inspections: dict[str, dict[str, Any]]) -> None:
    for service in REQUIRED_SERVICES:
        state = inspections[service].get("State", {})
        if not state.get("Running") or state.get("Health", {}).get("Status") != "healthy":
            raise DeploymentGuardError(f"{service} is not healthy")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_digest_match(*, component: str, checkout_digest: str, runtime_digest: str) -> None:
    if not checkout_digest or checkout_digest != runtime_digest:
        raise DeploymentGuardError(f"source digest mismatch: {component}")


def deployment_commands() -> tuple[tuple[str, ...], ...]:
    """Ordered mutating commands; exposed for daemon-free invariant tests."""
    return (
        compose_command("build", "migrate", "api", "worker"),
        compose_command(
            "up", "-d", "--wait", "--wait-timeout", COMPOSE_WAIT_TIMEOUT_SECONDS,
            "postgres",
        ),
        compose_command("--profile", "operations", "run", "--rm", "migrate"),
        compose_command(
            "up", "-d", "--wait", "--wait-timeout", COMPOSE_WAIT_TIMEOUT_SECONDS,
            "--no-deps", "--force-recreate", "api", "worker",
        ),
        compose_command(
            "up", "-d", "--wait", "--wait-timeout", COMPOSE_WAIT_TIMEOUT_SECONDS,
            "--no-deps", "proxy",
        ),
    )


class PilotDeployment:
    def __init__(self, *, root: Path, release_sha: str, runner: Runner) -> None:
        self.root = root
        self.release_sha = validate_release_sha(release_sha)
        self.runner = runner
        self.config: dict[str, Any] = {}
        self.expected_head = ""
        self.built_images: dict[str, str] = {}

    def preflight(self) -> None:
        for name in (COMPOSE_FILE, ENV_FILE):
            if not (self.root / name).is_file():
                raise DeploymentGuardError(f"required deployment file is missing: {name}")
        head = self.runner.run(("git", "rev-parse", "HEAD"))
        status = self.runner.run(("git", "status", "--porcelain", "--untracked-files=no"))
        validate_clean_head(supplied_sha=self.release_sha, head=head, status=status)
        rendered = self.runner.run(compose_command("config", "--format", "json"))
        try:
            self.config = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise DeploymentGuardError("pilot Compose config did not render as JSON") from exc
        validate_compose_topology(self.config)
        self.runner.run(("docker", "volume", "inspect", POSTGRES_VOLUME))

    def build(self) -> None:
        self.runner.run(deployment_commands()[0], mutate=True)
        for service in ("api", "worker", "migrate"):
            image = self.runner.run(compose_command("images", "--quiet", service))
            if not image:
                raise DeploymentGuardError(f"built image identity unavailable for {service}")
            self.built_images[service] = image.splitlines()[0]

    def migrate(self) -> None:
        self.runner.run(deployment_commands()[1], mutate=True)
        heads = self.runner.run(compose_command(
            "--profile", "operations", "run", "--rm", "--no-deps", "migrate",
            "python", "-m", "alembic", "heads",
        ))
        parsed = parse_alembic_heads(heads)
        if len(parsed) != 1:
            raise DeploymentGuardError(f"expected one repository Alembic head, found {len(parsed)}")
        self.expected_head = parsed[0]
        self.runner.run(deployment_commands()[2], mutate=True)
        current = self.runner.run(compose_command(
            "--profile", "operations", "run", "--rm", "--no-deps", "migrate",
            "python", "-m", "alembic", "current",
        ))
        assert_single_migration_head(heads_output=heads, current_output=current)

    def recreate(self) -> None:
        self.runner.run(deployment_commands()[3], mutate=True)
        self.runner.run(deployment_commands()[4], mutate=True)

    def _container_id(self, service: str) -> str:
        value = self.runner.run(compose_command("ps", "--quiet", service))
        if not value:
            raise DeploymentGuardError(f"running container unavailable for {service}")
        return value.splitlines()[0]

    def _inspect(self) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        inspections: dict[str, dict[str, Any]] = {}
        ids: dict[str, str] = {}
        for service in REQUIRED_SERVICES:
            identifier = self._container_id(service)
            ids[service] = identifier
            payload = self.runner.run(("docker", "inspect", identifier))
            values = json.loads(payload)
            if not isinstance(values, list) or len(values) != 1:
                raise DeploymentGuardError(f"unexpected inspect payload for {service}")
            inspections[service] = values[0]
        return inspections, ids

    def verify(self) -> None:
        head = self.runner.run(("git", "rev-parse", "HEAD"))
        status = self.runner.run(("git", "status", "--porcelain", "--untracked-files=no"))
        validate_clean_head(supplied_sha=self.release_sha, head=head, status=status)
        inspections: dict[str, dict[str, Any]] = {}
        ids: dict[str, str] = {}
        for _ in range(30):
            inspections, ids = self._inspect()
            try:
                assert_container_topology(inspections)
                assert_healthy(inspections)
                break
            except DeploymentGuardError:
                time.sleep(2)
        else:
            raise DeploymentGuardError("pilot services did not become healthy before timeout")
        for service in ("api", "worker"):
            if inspections[service].get("Image") != self.built_images.get(service):
                raise DeploymentGuardError(f"running {service} does not use the freshly built image")
        logs = self.runner.run(compose_command("logs", "--no-color", "--tail", "200", "worker"))
        lowered = logs.casefold()
        if "database_unavailable" in lowered or "could not translate host name \"postgres\"" in lowered:
            raise DeploymentGuardError("worker reports PostgreSQL DNS/availability failure")
        for service in ("api", "worker"):
            for relative in CRITICAL_SOURCE_FILES:
                host_digest = sha256_file(self.root / relative)
                output = self.runner.run(compose_command(
                    "exec", "-T", service, "sha256sum", relative,
                ))
                runtime_digest = output.split()[0] if output.split() else ""
                assert_digest_match(
                    component=f"{service}:{relative}",
                    checkout_digest=host_digest, runtime_digest=runtime_digest,
                )
        host = self.config.get("services", {}).get("proxy", {}).get("environment", {}).get("PILOT_HOST")
        if not isinstance(host, str) or not host:
            raise DeploymentGuardError("PILOT_HOST is unavailable in rendered pilot config")
        try:
            with urllib.request.urlopen(f"https://{host}/ready", timeout=10) as response:
                if response.status != 200:
                    raise DeploymentGuardError("public HTTPS readiness did not return 200")
        except Exception as exc:
            if isinstance(exc, DeploymentGuardError):
                raise
            raise DeploymentGuardError("public HTTPS readiness failed") from exc

    def execute(self, *, verify_only: bool = False) -> None:
        self.preflight()
        if self.runner.dry_run:
            for command in deployment_commands():
                assert_pinned_compose_command(command)
                print("PLAN " + " ".join(command))
            return
        if not verify_only:
            self.build(); self.migrate(); self.recreate()
        else:
            for service in ("api", "worker", "migrate"):
                image = self.runner.run(compose_command("images", "--quiet", service))
                self.built_images[service] = image.splitlines()[0] if image else ""
        self.verify()
        print(f"DEPLOYMENT PASS release={self.release_sha} alembic_head={self.expected_head or 'verify-only'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy one exact pilot release safely")
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        deployment = PilotDeployment(
            root=args.root.resolve(), release_sha=args.release_sha,
            runner=Runner(args.root.resolve(), dry_run=args.dry_run),
        )
        deployment.execute(verify_only=args.verify_only)
    except (DeploymentGuardError, OSError, ValueError) as exc:
        print(f"DEPLOYMENT FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
