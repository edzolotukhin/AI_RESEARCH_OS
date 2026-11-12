from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
from application.review.h3_review_branch import H3_REVIEW_BRANCH_KEY


class RevisionUnavailableError(RuntimeError):
    code = "h3_revision_implementation_unavailable"


class RevisionExecutor(BaseExecutor):
    """Durable H3 revision boundary; the real adapter is supplied in J2."""

    def __init__(self, revision_service=None, review_repository=None) -> None:
        self._revision_service = revision_service
        self._review_repository = review_repository

    def run(self, context):
        if context.read_shared(DESK_REPORT_CONTRACT_PIN) != H3_REPORT_CONTRACT:
            raise RevisionUnavailableError("h3_revision_requires_persisted_h3_contract")
        review = context.read_shared("review_1")
        if not isinstance(review, dict) or review.get("verdict") != "revise":
            raise RevisionUnavailableError("h3_revision_requires_review_1_revise")
        if self._revision_service is None:
            raise RevisionUnavailableError("h3_revision_implementation_unavailable")
        if self._review_repository is None:
            result = self._revision_service.revise_for_context(context)
        else:
            persisted = self._review_repository.get_by_id(str(review.get("review_id") or ""))
            if (persisted is None or persisted.project_id != context.project.id
                    or persisted.workflow_run_id != context.workflow_run.id
                    or persisted.report_id != review.get("report_id")
                    or persisted.research_design_id != context.workflow_template.research_design_snapshot.id
                    or persisted.review_attempt != 1 or persisted.verdict.value != "revise"):
                raise RevisionUnavailableError("h3_revision_requires_exact_persisted_review")
            result = self._revision_service.revise_for_context(context, review_result=persisted)
        if not isinstance(result, dict) or int(result.get("revision_count", 0)) != 1:
            raise RevisionUnavailableError("h3_revision_result_invalid")
        context.write_shared("h3_revision", dict(result))
        branch = dict(context.read_shared(H3_REVIEW_BRANCH_KEY) or {})
        branch.update({
            "contract": H3_REPORT_CONTRACT,
            "round": 1,
            "decision": "revise",
            "revision_count": 1,
            "finalization_eligible": False,
            "terminal_reason": None,
        })
        context.write_shared(H3_REVIEW_BRANCH_KEY, branch)
        return context
