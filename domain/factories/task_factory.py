from uuid import uuid4
from datetime import datetime, UTC

from domain.task import Task

from domain.factories.base_factory import BaseFactory


class TaskFactory(BaseFactory):
    """
    Фабрика создания задач.
    """

    def create(
        self,
        name: str,
        description: str = "",
        assigned_agent: str = "",
    ) -> Task:

        now = datetime.now(UTC).isoformat()

        return Task(
            id=str(uuid4()),
            name=name,
            description=description,
            assigned_agent=assigned_agent,
            created_at=now,
            updated_at=now,
        )