from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from domain.common.exceptions import ValidationError


class AuthorityExtensionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"
    TECHNICAL_ERROR = "technical_error"
    FAILED = "failed"


class AuthorityExtensionExecutionMode(StrEnum):
    BOUNDED_RESEARCH = "BOUNDED_RESEARCH"
    EXISTING_QUALIFYING_EVIDENCE_ONLY = "EXISTING_QUALIFYING_EVIDENCE_ONLY"


@dataclass(frozen=True)
class ResearchAuthorityExtension:
    extension_id: str
    project_id: str
    research_design_id: str
    parent_source_workflow_run_id: str
    extension_workflow_run_id: str
    selected_information_need_ids: tuple[str, ...]
    gap_contract_digest: str
    idempotency_key: str
    created_at: str
    status: AuthorityExtensionStatus = AuthorityExtensionStatus.CREATED
    terminal_reason: str | None = None
    execution_mode: AuthorityExtensionExecutionMode = AuthorityExtensionExecutionMode.BOUNDED_RESEARCH

    def __post_init__(self) -> None:
        for name in ("extension_id", "project_id", "research_design_id", "parent_source_workflow_run_id", "extension_workflow_run_id", "gap_contract_digest", "idempotency_key", "created_at"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValidationError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        needs = tuple(sorted(set(str(item).strip() for item in self.selected_information_need_ids if str(item).strip())))
        if not needs:
            raise ValidationError("selected_information_need_ids must not be empty")
        object.__setattr__(self, "selected_information_need_ids", needs)
        if self.parent_source_workflow_run_id == self.extension_workflow_run_id:
            raise ValidationError("extension workflow must differ from parent source workflow")
        object.__setattr__(self, "execution_mode", AuthorityExtensionExecutionMode(self.execution_mode))
        object.__setattr__(self, "status", AuthorityExtensionStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {"extension_id": self.extension_id, "project_id": self.project_id, "research_design_id": self.research_design_id, "parent_source_workflow_run_id": self.parent_source_workflow_run_id, "extension_workflow_run_id": self.extension_workflow_run_id, "selected_information_need_ids": list(self.selected_information_need_ids), "gap_contract_digest": self.gap_contract_digest, "idempotency_key": self.idempotency_key, "created_at": self.created_at, "execution_mode": self.execution_mode.value, "status": self.status.value, "terminal_reason": self.terminal_reason}


@dataclass(frozen=True)
class ComposedResearchAuthority:
    composition_id: str
    project_id: str
    research_design_id: str
    parent_source_workflow_run_id: str
    member_workflow_run_ids: tuple[str, ...]
    selected_information_need_ids: tuple[str, ...]
    composition_version: str
    composition_digest: str
    created_at: str

    def __post_init__(self) -> None:
        members = tuple(dict.fromkeys(str(item).strip() for item in self.member_workflow_run_ids if str(item).strip()))
        if self.parent_source_workflow_run_id not in members:
            raise ValidationError("composition must include its parent source workflow")
        if not members:
            raise ValidationError("composition membership must not be empty")
        object.__setattr__(self, "member_workflow_run_ids", members)
        object.__setattr__(self, "selected_information_need_ids", tuple(sorted(set(self.selected_information_need_ids))))

    def to_dict(self) -> dict[str, Any]:
        return {"composition_id": self.composition_id, "project_id": self.project_id, "research_design_id": self.research_design_id, "parent_source_workflow_run_id": self.parent_source_workflow_run_id, "member_workflow_run_ids": list(self.member_workflow_run_ids), "selected_information_need_ids": list(self.selected_information_need_ids), "composition_version": self.composition_version, "composition_digest": self.composition_digest, "created_at": self.created_at}
