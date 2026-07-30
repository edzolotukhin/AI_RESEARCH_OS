from __future__ import annotations

from collections.abc import Iterable

from .executor_definitions import ExecutorCapability


class ExecutorCatalog:
    """
    Immutable catalog of executor capabilities available to the Planner.
    """

    def __init__(
        self,
        capabilities: tuple[ExecutorCapability, ...],
    ) -> None:
        executor_ids = [capability.executor_id for capability in capabilities]

        if len(executor_ids) != len(set(executor_ids)):
            raise ValueError("ExecutorCatalog cannot contain duplicate executor IDs.")

        self._capabilities = capabilities
        self._executor_ids = tuple(executor_ids)

    @classmethod
    def from_capabilities(
        cls,
        capabilities: Iterable[ExecutorCapability],
    ) -> "ExecutorCatalog":
        return cls(tuple(capabilities))

    @property
    def capabilities(self) -> tuple[ExecutorCapability, ...]:
        return self._capabilities

    @property
    def executor_ids(self) -> tuple[str, ...]:
        return self._executor_ids

    def contains(
        self,
        executor_id: str,
    ) -> bool:
        return executor_id.strip() in self._executor_ids

    def format_for_prompt(self) -> str:
        lines = [
            "Available executors:",
            *[
                f"- {capability.executor_id}: {capability.description}"
                for capability in self._capabilities
            ],
            "",
            "For every task, executor_id must exactly match one of the listed IDs.",
            "Do not create new executor IDs.",
            "Do not use job titles or display labels instead of executor_id.",
        ]

        return "\n".join(lines)
