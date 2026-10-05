"""QUA-03 Findings, Insights, Review and Approved Revision authority."""
from __future__ import annotations

import re
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict


_OVERCLAIM = re.compile(r"\b(?:\d+(?:\.\d+)?%|most consumers|the market believes|this proves)\b", re.I)


class QualitativePostAnalysisService:
    """Append-only qualitative post-analysis, projected into shared CMF Review."""

    def __init__(self, authority, provider=None, review_repository=None):
        self.authority, self.provider, self.reviews = authority, provider, review_repository

    @property
    def repository(self): return self.authority.repository

    def _owner(self, project_id, owner_id): self.authority._project(project_id, owner_id)
    def _get(self, project_id, identity, kind=None): return self.authority._get(project_id, identity, kind)
    def _records(self, project_id, run_id, kind):
        return self.repository.list_for_run(run_id, project_id=project_id, record_type=kind)

    def _accepted_thematic(self, project_id, run_id, thematic_id):
        value=self._get(project_id,thematic_id,"thematic_revision")
        if value.run_id != run_id or value.payload.get("status") != "accepted":
            raise ValueError("Accepted Thematic Analysis Revision is required")
        return value

    @staticmethod
    def _language(value):
        if not value.strip() or _OVERCLAIM.search(value):
            raise ValueError("Unsupported qualitative population or certainty claim")

    def create_finding(self, project_id, run_id, thematic_id, *, title, statement, explanation,
                       theme_ids, owner_id, status="draft", origin="human", parent_id=None, identity=None):
        self._owner(project_id,owner_id); thematic=self._accepted_thematic(project_id,run_id,thematic_id)
        self._language(statement); self._language(explanation)
        if status not in {"draft","accepted"} or not theme_ids: raise ValueError("Invalid qualitative Finding state")
        themes={x["theme_id"]:x for x in thematic.payload["themes"]}
        if not set(theme_ids).issubset(themes): raise ValueError("Finding references a foreign or stale Theme")
        if parent_id:
            parent=self._get(project_id,parent_id,"qualitative_finding")
            if parent.run_id != run_id or parent.payload["thematic_revision_id"] != thematic_id:
                raise ValueError("Parent Finding belongs to another authority")
        selected=[themes[x] for x in theme_ids]
        support=tuple(dict.fromkeys(y for x in selected for y in x.get("supporting_application_ids",[])))
        deviant=tuple(dict.fromkeys(y for x in selected for y in x.get("contradictory_application_ids",[])))
        if not support: raise ValueError("Finding requires canonical Theme evidence")
        identity=identity or str(uuid4()); revision=1+len(self._records(project_id,run_id,"qualitative_finding"))
        self.authority._put(project_id,run_id,"qualitative_finding",identity,{"finding_id":identity,"revision":revision,
            "thematic_revision_id":thematic_id,"title":title,"statement":statement,"explanation":explanation,
            "theme_ids":theme_ids,"supporting_application_ids":support,"deviant_application_ids":deviant,
            "status":status,"origin":origin},parent=parent_id)
        if status=="accepted": self.authority._activity(project_id,run_id,"QUAL_FINDING_ACCEPTED","qual_finding",identity)
        return self._get(project_id,identity)

    def create_insight(self, project_id, run_id, thematic_id, *, title, statement, implication,
                       finding_ids, owner_id, status="draft", origin="human", parent_id=None, identity=None):
        self._owner(project_id,owner_id); self._accepted_thematic(project_id,run_id,thematic_id)
        self._language(statement); self._language(implication)
        if status not in {"draft","accepted"} or not finding_ids: raise ValueError("Insight requires Findings")
        findings=[]
        for finding_id in finding_ids:
            item=self._get(project_id,finding_id,"qualitative_finding")
            if item.run_id != run_id or item.payload.get("status") != "accepted" or item.payload["thematic_revision_id"] != thematic_id:
                raise ValueError("Insight requires accepted Findings from the exact thematic authority")
            findings.append(item)
        if parent_id:
            parent=self._get(project_id,parent_id,"qualitative_insight")
            if parent.run_id != run_id or parent.payload["thematic_revision_id"] != thematic_id:
                raise ValueError("Parent Insight belongs to another authority")
        identity=identity or str(uuid4()); revision=1+len(self._records(project_id,run_id,"qualitative_insight"))
        self.authority._put(project_id,run_id,"qualitative_insight",identity,{"insight_id":identity,"revision":revision,
            "thematic_revision_id":thematic_id,"title":title,"statement":statement,"implication":implication,
            "finding_ids":finding_ids,"status":status,"origin":origin},parent=parent_id)
        if status=="accepted": self.authority._activity(project_id,run_id,"QUAL_INSIGHT_ACCEPTED","qual_insight",identity)
        return self._get(project_id,identity)

    def create_revision(self, project_id, run_id, thematic_id, finding_ids, insight_ids, *, owner_id, parent_id=None):
        self._owner(project_id,owner_id); self._accepted_thematic(project_id,run_id,thematic_id)
        if not finding_ids or not insight_ids: raise ValueError("Revision requires accepted Findings and Insights")
        if parent_id:
            parent=self._get(project_id,parent_id,"qualitative_post_analysis_revision")
            if parent.run_id != run_id or parent.payload["thematic_revision_id"] != thematic_id:
                raise ValueError("Parent revision belongs to another authority")
        for identity,kind in [(x,"qualitative_finding") for x in finding_ids]+[(x,"qualitative_insight") for x in insight_ids]:
            item=self._get(project_id,identity,kind)
            if item.run_id != run_id or item.payload.get("status") != "accepted" or item.payload["thematic_revision_id"] != thematic_id:
                raise ValueError("Revision contains draft, foreign or stale authority")
        for insight_id in insight_ids:
            if not set(self._get(project_id,insight_id).payload["finding_ids"]).issubset(finding_ids):
                raise ValueError("Insight provenance is outside the revision")
        identity=str(uuid4()); number=1+len(self._records(project_id,run_id,"qualitative_post_analysis_revision"))
        self.authority._put(project_id,run_id,"qualitative_post_analysis_revision",identity,{"revision_id":identity,
            "revision":number,"method_id":"QUALITATIVE","method_version":"1","thematic_revision_id":thematic_id,
            "finding_ids":finding_ids,"insight_ids":insight_ids,"status":"in_review"},parent=parent_id)
        self.authority._activity(project_id,run_id,"QUAL_FINDINGS_REVISION_CREATED","qual_post_analysis_revision",identity)
        self.authority._activity(project_id,run_id,"QUAL_REVIEW_REQUESTED","qual_post_analysis_revision",identity)
        return self._get(project_id,identity)

    def request_ai_job(self, project_id, run_id, thematic_id, *, owner_id, batch_key, kind, finding_ids=()):
        self._owner(project_id,owner_id); thematic=self._accepted_thematic(project_id,run_id,thematic_id)
        if kind not in {"finding","insight"}: raise ValueError("Invalid QUA-03 AI job kind")
        findings=[]
        if kind == "insight":
            if not finding_ids: raise ValueError("Insight proposal requires accepted Findings")
            for identity in finding_ids:
                item=self._get(project_id,identity,"qualitative_finding")
                if item.run_id != run_id or item.payload.get("status") != "accepted" or item.payload["thematic_revision_id"] != thematic_id:
                    raise ValueError("Insight proposal contains foreign or draft Finding")
                findings.append(item.payload)
        existing=next((x for x in self._records(project_id,run_id,"qualitative_post_analysis_job")
                       if x.payload["batch_key"]==batch_key),None)
        if existing: return existing
        identity=str(uuid4()); request={"job_id":identity,"batch_key":batch_key,"kind":kind,
            "thematic_revision":thematic.payload,"findings":findings}
        self.authority._put(project_id,run_id,"qualitative_post_analysis_job",identity,{"job_id":identity,"state":"queued",
            "batch_key":batch_key,"kind":kind,"owner_id":owner_id,"thematic_revision_id":thematic_id,
            "finding_ids":list(finding_ids),"request":request})
        return self._get(project_id,identity)

    def process_next_job(self):
        for job in self.repository.list_by_type("qualitative_post_analysis_job"):
            if job.payload.get("state") != "queued": continue
            ready_id=f"{job.record_id}:ready"; failed_id=f"{job.record_id}:failed"
            if self.repository.get_for_project(ready_id,project_id=job.project_id) or self.repository.get_for_project(failed_id,project_id=job.project_id): continue
            try:
                output=self.provider.propose(job.payload["request"])
                proposal=next((x for x in self._records(job.project_id,job.run_id,"qualitative_post_analysis_proposal")
                               if x.payload["batch_key"]==job.payload["batch_key"]),None)
                if proposal is None:
                    self._validate_proposal(job,output)
                    proposal_id=str(uuid4()); self.authority._put(job.project_id,job.run_id,"qualitative_post_analysis_proposal",
                        proposal_id,{"proposal_id":proposal_id,"batch_key":job.payload["batch_key"],"kind":job.payload["kind"],
                        "thematic_revision_id":job.payload["thematic_revision_id"],"finding_ids":job.payload.get("finding_ids",[]),
                        "payload":output,"status":"pending_review"},parent=job.record_id)
                    proposal=self._get(job.project_id,proposal_id)
                    self.authority._activity(job.project_id,job.run_id,"QUAL_AI_FINDINGS_READY","qual_ai_proposal",proposal_id)
                self.authority._put(job.project_id,job.run_id,"qualitative_post_analysis_job_state",ready_id,
                    {"job_id":job.record_id,"state":"proposals_ready","proposal_id":proposal.record_id},parent=job.record_id)
            except Exception as exc:
                self.authority._put(job.project_id,job.run_id,"qualitative_post_analysis_job_state",failed_id,
                    {"job_id":job.record_id,"state":"failed","error_category":type(exc).__name__},parent=job.record_id)
                raise
            return True
        return False

    def _validate_proposal(self, job, output):
        values=output.get("findings" if job.payload["kind"]=="finding" else "insights",[])
        if not values: raise ValueError("AI proposal is empty")
        thematic=self._accepted_thematic(job.project_id,job.run_id,job.payload["thematic_revision_id"])
        theme_ids={x["theme_id"] for x in thematic.payload["themes"]}
        finding_ids=set(job.payload.get("finding_ids",[]))
        for item in values:
            self._language(item.get("statement","")); self._language(item.get("explanation",item.get("implication","")))
            refs=set(item.get("theme_ids",[]) if job.payload["kind"]=="finding" else item.get("finding_ids",[]))
            if not refs or not refs.issubset(theme_ids if job.payload["kind"]=="finding" else finding_ids):
                raise ValueError("AI proposal references unsupported authority")

    def review_ai_proposal(self, project_id, proposal_id, *, owner_id, decision):
        self._owner(project_id,owner_id); proposal=self._get(project_id,proposal_id,"qualitative_post_analysis_proposal")
        if decision not in {"accepted","rejected"}: raise ValueError("Invalid proposal decision")
        review_id=f"{proposal_id}:{decision}"; accepted=self.repository.get_for_project(f"{proposal_id}:accepted",project_id=project_id)
        if accepted and decision=="rejected": raise ValueError("Canonical proposal acceptance is immutable")
        existing=self.repository.get_for_project(review_id,project_id=project_id)
        if existing: return existing
        if decision=="rejected":
            self.authority._put(project_id,proposal.run_id,"qualitative_post_analysis_proposal_review",review_id,
                {"proposal_id":proposal_id,"decision":decision,"canonical_ids":[]},parent=proposal_id)
            return self._get(project_id,review_id)
        sessions=getattr(self.repository,"_sessions",None)
        with (sessions.activation(project_id) if sessions is not None else nullcontext()):
            existing=self.repository.get_for_project(review_id,project_id=project_id)
            if existing: return existing
            canonical=[]; values=proposal.payload["payload"].get("findings" if proposal.payload["kind"]=="finding" else "insights",[])
            for index,item in enumerate(values,1):
                identity=f"{proposal_id}:canonical:{index}"
                if proposal.payload["kind"]=="finding":
                    value=self.create_finding(project_id,proposal.run_id,proposal.payload["thematic_revision_id"],
                        title=item["title"],statement=item["statement"],explanation=item["explanation"],theme_ids=item["theme_ids"],
                        owner_id=owner_id,status="accepted",origin="ai_accepted",identity=identity)
                else:
                    value=self.create_insight(project_id,proposal.run_id,proposal.payload["thematic_revision_id"],
                        title=item["title"],statement=item["statement"],implication=item["implication"],finding_ids=item["finding_ids"],
                        owner_id=owner_id,status="accepted",origin="ai_accepted",identity=identity)
                canonical.append(value.record_id)
            self.authority._put(project_id,proposal.run_id,"qualitative_post_analysis_proposal_review",review_id,
                {"proposal_id":proposal_id,"decision":"accepted","canonical_ids":canonical},parent=proposal_id)
        return self._get(project_id,review_id)

    def review(self, project_id, run_id, revision_id, *, owner_id, decision, comments=""):
        self._owner(project_id,owner_id); revision=self._get(project_id,revision_id,"qualitative_post_analysis_revision")
        if revision.run_id != run_id or decision not in {"changes_required","approved"}: raise ValueError("Invalid Review")
        review_id=self._review_id(revision_id, decision)
        approved_id=self._approved_id(revision_id)
        existing=self.repository.get_for_project(review_id,project_id=project_id)
        if existing: return existing, (self.repository.get_for_project(approved_id,project_id=project_id) if decision=="approved" else None)
        sessions=getattr(self.repository,"_sessions",None)
        with (sessions.activation(project_id) if sessions is not None else nullcontext()):
            if decision == "approved":
                if self.repository.get_for_project(self._review_id(revision_id,"changes_required"),project_id=project_id):
                    raise ValueError("A changes-required revision must be replaced by a successor before approval")
                self._validate_revision(project_id,run_id,revision)
            self.authority._put(project_id,run_id,"qualitative_review",review_id,{"review_id":review_id,
                "revision_id":revision_id,"decision":decision,"comments":comments,"reviewed_by":owner_id,
                "reviewed_at":datetime.now(UTC).isoformat()},parent=revision_id)
            self.authority._activity(project_id,run_id,"QUAL_REVIEW_APPROVED" if decision=="approved" else "QUAL_REVIEW_CHANGES_REQUIRED",
                "qual_review",review_id)
            approved=None
            if decision == "approved":
                self.authority._put(project_id,run_id,"qualitative_approved_revision",approved_id,{"approved_revision_id":approved_id,
                    "revision_id":revision_id,"revision":revision.payload["revision"],"review_id":review_id,
                    "thematic_revision_id":revision.payload["thematic_revision_id"],"finding_ids":revision.payload["finding_ids"],
                    "insight_ids":revision.payload["insight_ids"],"status":"ready_for_deliverables"},parent=revision_id)
                approved=self._get(project_id,approved_id)
                self.authority._activity(project_id,run_id,"QUAL_APPROVED_REVISION_CREATED","qual_approved_revision",approved_id)
                self.authority._activity(project_id,run_id,"QUAL_READY_FOR_DELIVERABLES","qual_approved_revision",approved_id)
            self._project_shared_review(project_id,run_id,revision,review_id,decision,comments)
        return self._get(project_id,review_id),approved

    @staticmethod
    def _review_id(revision_id, decision):
        return str(uuid5(NAMESPACE_URL, f"qua-review:{revision_id}:{decision}"))

    @staticmethod
    def _approved_id(revision_id):
        return str(uuid5(NAMESPACE_URL, f"qua-approved:{revision_id}"))

    def _validate_revision(self, project_id, run_id, revision):
        self._accepted_thematic(project_id,run_id,revision.payload["thematic_revision_id"])
        for identity,kind in [(x,"qualitative_finding") for x in revision.payload["finding_ids"]]+[(x,"qualitative_insight") for x in revision.payload["insight_ids"]]:
            item=self._get(project_id,identity,kind)
            if item.payload.get("status") != "accepted" or item.payload["thematic_revision_id"] != revision.payload["thematic_revision_id"]:
                raise ValueError("Approved Revision contains unsupported authority")

    def _project_shared_review(self, project_id, run_id, revision, review_id, decision, comments):
        if self.reviews is None: return
        if self.reviews.get_by_id(review_id): return
        verdict=ReviewVerdict.APPROVE if decision=="approved" else ReviewVerdict.REVISE
        issues=() if verdict is ReviewVerdict.APPROVE else (ReviewIssue(id=f"{review_id}:issue:1",
            issue_type=ReviewIssueType.INCONSISTENT_ANALYSIS,severity=ReviewIssueSeverity.MAJOR,message=comments or "Changes required"),)
        self.reviews.create(ReviewResult(id=review_id,project_id=project_id,workflow_run_id=run_id,
            research_design_id=revision.payload["thematic_revision_id"],report_id=revision.record_id,review_attempt=1,
            verdict=verdict,quality_dimensions=(),issues=issues,summary=comments or decision,
            review_method="QUA03_HUMAN_REVIEW_V1",created_at=datetime.now(UTC).isoformat(),
            deduplication_key=str(uuid5(NAMESPACE_URL,f"qua-review:{review_id}")),metadata={"methodology":"QUALITATIVE"}))

    def readiness(self, project_id, run_id, *, owner_id):
        self._owner(project_id,owner_id)
        return "ready_for_deliverables" if self._records(project_id,run_id,"qualitative_approved_revision") else "findings_insights_review"
