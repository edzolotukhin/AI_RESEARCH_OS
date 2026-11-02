from __future__ import annotations

import hashlib
import json
from typing import Iterable

from domain.research_authority import ComposedResearchAuthority

COMPOSITION_VERSION = "research_authority_composition_v1"


def canonical_gap_digest(gap_contract: object) -> str:
    payload = json.dumps(gap_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def composition_digest(*, project_id: str, research_design_id: str, parent_source_workflow_run_id: str, member_workflow_run_ids: Iterable[str], selected_information_need_ids: Iterable[str], version: str = COMPOSITION_VERSION) -> str:
    payload = {"version": version, "project_id": project_id, "research_design_id": research_design_id, "parent_source_workflow_run_id": parent_source_workflow_run_id, "member_workflow_run_ids": sorted(set(member_workflow_run_ids)), "selected_information_need_ids": sorted(set(selected_information_need_ids))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_composition(*, composition_id: str, project_id: str, research_design_id: str, parent_source_workflow_run_id: str, member_workflow_run_ids: Iterable[str], selected_information_need_ids: Iterable[str], created_at: str) -> ComposedResearchAuthority:
    members = tuple(dict.fromkeys(member_workflow_run_ids))
    needs = tuple(sorted(set(selected_information_need_ids)))
    return ComposedResearchAuthority(composition_id=composition_id, project_id=project_id, research_design_id=research_design_id, parent_source_workflow_run_id=parent_source_workflow_run_id, member_workflow_run_ids=members, selected_information_need_ids=needs, composition_version=COMPOSITION_VERSION, composition_digest=composition_digest(project_id=project_id, research_design_id=research_design_id, parent_source_workflow_run_id=parent_source_workflow_run_id, member_workflow_run_ids=members, selected_information_need_ids=needs), created_at=created_at)
