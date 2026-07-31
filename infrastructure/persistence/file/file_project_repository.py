from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.ports.project_repository import ProjectRepository
from domain.project import Project
from domain.value_objects.project_status import ProjectStatus


class FileProjectRepository:
    """
    Transitional file-based ProjectRepository adapter.

    This adapter preserves the legacy JSON-on-disk layout used before PF-02.
    It does **not** support complete Project aggregate round-trip: nested
    optional fields (ClientRequest, ProjectBrief, ResearchDesign, etc.) are
    not restored on load. The PostgreSQL adapter (PF-03) will implement the
    full persistence model with dedicated mappers.

    Filesystem, JSON, and directory concerns live here only.
    """

    _META_FILE = ".meta.json"

    def __init__(self, projects_root: str = "agency/projects") -> None:
        self._projects_root = Path(projects_root)

    def create(self, project: Project) -> None:
        project_dir = self._project_dir(project.id)
        if self._aggregate_exists(project.id):
            raise DuplicateEntityError(
                f"Project already exists: {project.id}"
            )

        project_dir.mkdir(parents=True, exist_ok=True)

        for name in (
            "knowledge",
            "artifacts",
            "attachments",
            "reports",
            "logs",
        ):
            (project_dir / name).mkdir(exist_ok=True)

        self._write_meta(project.id, version=0)

        project_file = project_dir / "project.json"
        payload = self._project_to_dict(project)

        with open(project_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4, ensure_ascii=False)

    def save(
        self,
        project: Project,
        *,
        expected_version: int | None = None,
    ) -> int:
        if not self._aggregate_exists(project.id):
            raise EntityNotFoundError(
                f"Project not found: {project.id}"
            )

        current_version = self._read_version(project.id)
        if (
            expected_version is not None
            and expected_version != current_version
        ):
            raise ConcurrentModificationError(
                f"Project {project.id} version mismatch: "
                f"expected {expected_version}, found {current_version}."
            )

        project_file = self._project_dir(project.id) / "project.json"
        payload = self._project_to_dict(project)

        with open(project_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4, ensure_ascii=False)

        new_version = current_version + 1
        self._write_meta(project.id, version=new_version)
        return new_version

    def get_by_id(self, project_id: str) -> Project | None:
        project_file = self._project_dir(project_id) / "project.json"
        if not project_file.exists():
            return None

        with open(project_file, encoding="utf-8") as handle:
            payload = json.load(handle)

        return self._project_from_dict(payload)

    def list(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Project]:
        if not self._projects_root.exists():
            return []

        project_ids = sorted(
            path.name
            for path in self._projects_root.iterdir()
            if path.is_dir()
            and (path / "project.json").exists()
        )

        if offset:
            project_ids = project_ids[offset:]
        if limit is not None:
            project_ids = project_ids[:limit]

        projects: list[Project] = []
        for project_id in project_ids:
            project = self.get_by_id(project_id)
            if project is not None:
                projects.append(project)

        return projects

    def delete(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        if not self._aggregate_exists(project_id):
            raise EntityNotFoundError(f"Project not found: {project_id}")

        if expected_version is not None:
            current_version = self._read_version(project_id)
            if expected_version != current_version:
                raise ConcurrentModificationError(
                    f"Project {project_id} version mismatch: "
                    f"expected {expected_version}, found {current_version}."
                )

        project_dir = self._project_dir(project_id)
        if project_dir.exists():
            shutil.rmtree(project_dir)

    def _aggregate_exists(self, project_id: str) -> bool:
        return self._meta_path(project_id).exists()

    def _project_dir(self, project_id: str) -> Path:
        return self._projects_root / project_id

    def _meta_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / self._META_FILE

    def _read_version(self, project_id: str) -> int:
        meta_path = self._meta_path(project_id)
        if not meta_path.exists():
            return 0

        with open(meta_path, encoding="utf-8") as handle:
            payload = json.load(handle)

        return int(payload.get("version", 0))

    def _write_meta(self, project_id: str, *, version: int) -> None:
        meta_path = self._meta_path(project_id)
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump({"version": version}, handle)

    @staticmethod
    def _project_to_dict(project: Project) -> dict[str, Any]:
        payload = asdict(project)
        payload["runs"] = []
        return payload

    @staticmethod
    def _project_from_dict(payload: dict[str, Any]) -> Project:
        return Project(
            id=payload["id"],
            name=payload["name"],
            status=payload.get("status", ProjectStatus.LEAD),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
            runs=[],
        )
