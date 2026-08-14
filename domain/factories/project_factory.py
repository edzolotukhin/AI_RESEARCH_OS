from uuid import uuid4
from datetime import UTC, datetime

from domain.project import Project
from domain.factories.base_factory import BaseFactory


class ProjectFactory(BaseFactory):
    """
    Фабрика создания проектов.
    """

    def create(self, name: str, *, project_id: str | None = None) -> Project:

        now = datetime.now(UTC).isoformat()

        return Project(
            id=project_id or str(uuid4()),
            name=name,
            created_at=now,
            updated_at=now,
        )
