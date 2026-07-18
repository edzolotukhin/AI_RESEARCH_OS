from uuid import uuid4
from datetime import datetime

from domain.project import Project
from domain.factories.base_factory import BaseFactory


class ProjectFactory(BaseFactory):
    """
    Фабрика создания проектов.
    """

    def create(self, name: str) -> Project:

        now = datetime.utcnow().isoformat()

        return Project(
            id=str(uuid4()),
            name=name,
            created_at=now,
            updated_at=now,
        )