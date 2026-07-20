import json
from pathlib import Path
from dataclasses import asdict

from domain.project import Project


class ProjectRepository:
    """
    Repository отвечает за создание, сохранение и загрузку проектов.
    Пока реализованы create_project() и save_project().
    """

    def __init__(self):
        self.projects_root = Path("agency/projects")

    def create_project(self, project: Project) -> Path:
        project_dir = self.projects_root / project.id

        project_dir.mkdir(parents=True, exist_ok=True)

        (project_dir / "knowledge").mkdir(exist_ok=True)
        (project_dir / "artifacts").mkdir(exist_ok=True)
        (project_dir / "attachments").mkdir(exist_ok=True)
        (project_dir / "reports").mkdir(exist_ok=True)
        (project_dir / "logs").mkdir(exist_ok=True)

        return project_dir

    def save_project(self, project: Project):
        project_dir = self.projects_root / project.id
        project_file = project_dir / "project.json"

        with open(project_file, "w", encoding="utf-8") as f:
            json.dump(
                asdict(project),
                f,
                indent=4,
                ensure_ascii=False,
            )

    def load_project(self, project_id: str):
        raise NotImplementedError

    def list_projects(self):
        raise NotImplementedError

    def delete_project(self, project_id: str):
        raise NotImplementedError