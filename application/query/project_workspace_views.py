from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkspaceMethodState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    READY = "READY"
    RUNNING = "RUNNING"
    ATTENTION = "ATTENTION"
    COMPLETED = "COMPLETED"
    LIMITED = "LIMITED"


@dataclass(frozen=True)
class MethodOutputAvailabilityView:
    findings_count: int | None = None
    insights_count: int | None = None
    analyses_count: int | None = None
    report_available: bool | None = None
    review_available: bool | None = None


@dataclass(frozen=True)
class WorkspaceActionView:
    label: str
    href: str


@dataclass(frozen=True)
class MethodWorkspaceView:
    name: str
    state: WorkspaceMethodState
    state_label: str
    explanation: str
    progress: int | None
    output: MethodOutputAvailabilityView
    primary_action: WorkspaceActionView
    open_action: WorkspaceActionView | None = None


@dataclass(frozen=True)
class ProjectBriefSummaryView:
    title: str
    business_question: str
    objectives: tuple[str, ...]


@dataclass(frozen=True)
class ProjectWorkspaceView:
    project_id: str
    project_name: str
    lifecycle: str
    brief: ProjectBriefSummaryView | None
    desk: MethodWorkspaceView | None
    quantitative: MethodWorkspaceView | None
    qualitative: MethodWorkspaceView | None
    methods: tuple[MethodWorkspaceView, ...]
    available_methods: tuple[str, ...]
    design_status: str | None
    design_current: bool
    attention_items: tuple[str, ...]
    role: str = "OWNER"
    can_mutate: bool = True
    can_manage_access: bool = True


@dataclass(frozen=True)
class ProjectListItemView:
    project_id: str
    project_name: str
    lifecycle: str
    method_states: tuple[tuple[str, str], ...]
    attention: bool
    role: str = "OWNER"
    next_action: str = "Open project"


@dataclass(frozen=True)
class ProjectListView:
    projects: tuple[ProjectListItemView, ...]
