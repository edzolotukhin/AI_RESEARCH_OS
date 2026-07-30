from __future__ import annotations

from dataclasses import dataclass

from domain.value_objects.executor_type import ExecutorType


@dataclass(frozen=True)
class ExecutorCapability:
    """
    Immutable description of a registered executor capability.
    """

    executor_id: str
    executor_type: ExecutorType
    description: str


AGENT_EXECUTOR_CAPABILITIES: tuple[ExecutorCapability, ...] = (
    ExecutorCapability(
        executor_id="planner",
        executor_type=ExecutorType.AGENT,
        description="Designs research workflows and planning tasks",
    ),
    ExecutorCapability(
        executor_id="search",
        executor_type=ExecutorType.AGENT,
        description="Collects evidence and research data",
    ),
    ExecutorCapability(
        executor_id="analysis",
        executor_type=ExecutorType.AGENT,
        description="Performs analysis and synthesis",
    ),
    ExecutorCapability(
        executor_id="report",
        executor_type=ExecutorType.AGENT,
        description="Prepares research reports and deliverables",
    ),
    ExecutorCapability(
        executor_id="proposal",
        executor_type=ExecutorType.AGENT,
        description="Creates client proposals",
    ),
)
