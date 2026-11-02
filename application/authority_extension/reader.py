from __future__ import annotations

from dataclasses import dataclass

from domain.research_authority import ComposedResearchAuthority


class AuthorityCompositionError(ValueError):
    pass


@dataclass(frozen=True)
class ComposedAuthorityReader:
    sources: object
    evidence: object
    findings: object
    insights: object

    def _members(self, composition: ComposedResearchAuthority) -> tuple[str, ...]:
        return composition.member_workflow_run_ids

    def list_sources(self, composition: ComposedResearchAuthority):
        return self._list(self.sources, composition, "source")

    def list_evidence(self, composition: ComposedResearchAuthority):
        return self._list(self.evidence, composition, "evidence")

    def list_findings(self, composition: ComposedResearchAuthority):
        return self._list(self.findings, composition, "finding")

    def list_insights(self, composition: ComposedResearchAuthority):
        return self._list(self.insights, composition, "insight")

    @staticmethod
    def _list(repository, composition, kind):
        values = []
        for run_id in composition.member_workflow_run_ids:
            values.extend(repository.list_for_project(composition.project_id, workflow_run_id=run_id))
        return values

    @staticmethod
    def validate_member(composition: ComposedResearchAuthority, *, project_id: str, research_design_id: str, workflow_run_id: str) -> None:
        if (project_id, research_design_id) != (composition.project_id, composition.research_design_id):
            raise AuthorityCompositionError("composition project/design mismatch")
        if workflow_run_id not in composition.member_workflow_run_ids:
            raise AuthorityCompositionError("workflow is not a composition member")
