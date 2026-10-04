"""QUA-02 application service over the append-only qualitative authority store."""
from __future__ import annotations

from contextlib import nullcontext
from uuid import uuid4

from domain.qualitative.analysis import reject_population_claim
from domain.qualitative.authority import ConsentState, TranscriptSpanRef
from application.qualitative.service import transcript_from_payload


class QualitativeAnalysisService:
    def __init__(self, authority, provider=None):
        self.authority, self.provider = authority, provider

    @property
    def repository(self): return self.authority.repository

    def _record(self, project_id, record_id, kind=None):
        return self.authority._get(project_id, record_id, kind)

    def _owner(self, project_id, owner_id): self.authority._project(project_id, owner_id)

    def create_corpus(self, project_id, run_id, transcript_ids, *, owner_id, instructions=""):
        self._owner(project_id, owner_id); self._record(project_id, run_id, "run")
        if not transcript_ids or len(set(transcript_ids)) != len(transcript_ids):
            raise ValueError("Corpus requires distinct transcript versions")
        members = []
        for transcript_id in transcript_ids:
            record = self._record(project_id, transcript_id, "transcript")
            if record.run_id != run_id or not record.payload.get("analysis_eligible"):
                raise ValueError("Transcript is not eligible for this corpus")
            session = self._record(project_id, record.payload["session_id"], "session")
            participant = self._record(project_id, session.payload["participant_id"], "participant")
            consents = [x for x in self.repository.list_for_run(run_id, project_id=project_id, record_type="consent")
                        if x.payload["participant_id"] == participant.record_id]
            consent = max(consents, key=lambda x: x.payload["recorded_at"]) if consents else None
            if consent is None or consent.payload["state"] != ConsentState.ELIGIBLE.value:
                raise ValueError("Consent is not eligible for new analysis")
            members.append({"session_id":session.record_id,"participant_id":participant.record_id,
                "participant_pseudonym":participant.payload["pseudonym"],"transcript_version_id":transcript_id,
                "transcript_checksum":record.payload["checksum"],"source_artifact_id":record.payload["source_artifact_id"],
                "consent_record_id":consent.record_id})
        identity = str(uuid4()); previous = self.repository.list_for_run(run_id, project_id=project_id, record_type="analysis_corpus")
        self.authority._put(project_id, run_id, "analysis_corpus", identity,
            {"corpus_id":identity,"revision":len(previous)+1,"method_id":"QUALITATIVE","method_version":"1",
             "members":members,"instructions":instructions,"status":"frozen"})
        self.authority._activity(project_id,run_id,"QUAL_ANALYSIS_CORPUS_FROZEN","qual_analysis_corpus",identity)
        return self._record(project_id, identity)

    def create_codebook(self, project_id, run_id, codes, *, owner_id, parent_id=None, status="draft", memo="", identity=None):
        self._owner(project_id, owner_id); self._record(project_id, run_id, "run")
        if status not in {"draft","accepted"}: raise ValueError("Invalid codebook status")
        if parent_id and self._record(project_id, parent_id, "codebook_revision").run_id != run_id:
            raise ValueError("Parent codebook belongs to another run")
        normalized=[]; seen=set()
        for item in codes:
            code_id=item.get("code_id") or str(uuid4())
            if code_id in seen or not item.get("label","").strip() or not item.get("definition","").strip():
                raise ValueError("Invalid or duplicate code")
            seen.add(code_id); normalized.append({**item,"code_id":code_id,"origin":item.get("origin","human")})
        identity=identity or str(uuid4()); previous=self.repository.list_for_run(run_id,project_id=project_id,record_type="codebook_revision")
        self.authority._put(project_id,run_id,"codebook_revision",identity,
            {"codebook_revision_id":identity,"revision":len(previous)+1,"codes":normalized,"status":status,"memo":memo},parent=parent_id)
        self.authority._activity(project_id,run_id,"QUAL_CODEBOOK_REVISION_CREATED","qual_codebook",identity)
        return self._record(project_id,identity)

    def _validated_applications(self, project_id, corpus, codebook, applications, extra_codes=()):
        members={x["transcript_version_id"]:x for x in corpus.payload["members"]}
        codes={x["code_id"] for x in codebook.payload["codes"]}|set(extra_codes); output=[]; identities=set()
        for value in applications:
            member=members.get(value.get("transcript_version_id"))
            if member is None or value.get("code_id") not in codes: raise ValueError("Application is outside corpus/codebook")
            transcript_record=self._record(project_id,member["transcript_version_id"],"transcript")
            transcript=transcript_from_payload(transcript_record.payload)
            ref=TranscriptSpanRef(member["transcript_version_id"],value.get("transcript_checksum",member["transcript_checksum"]),
                value["segment_id"],int(value["start"]),int(value["end"]))
            excerpt=ref.resolve(transcript)
            app_id=value.get("application_id") or str(uuid4())
            if app_id in identities: raise ValueError("Duplicate code application")
            identities.add(app_id); output.append({**value,"application_id":app_id,
                "transcript_checksum":member["transcript_checksum"],"session_id":member["session_id"],
                "participant_id":member["participant_id"],"participant_pseudonym":member["participant_pseudonym"],
                "excerpt":excerpt,"origin":value.get("origin","human"),"review_state":value.get("review_state","accepted")})
        return output

    def create_coding(self, project_id, run_id, corpus_id, codebook_id, applications, *, owner_id,
                      status="accepted", parent_id=None, memo="", identity=None):
        self._owner(project_id,owner_id); corpus=self._record(project_id,corpus_id,"analysis_corpus")
        codebook=self._record(project_id,codebook_id,"codebook_revision")
        if corpus.run_id != run_id or codebook.run_id != run_id: raise ValueError("Foreign analytical authority")
        if status not in {"draft","accepted"}: raise ValueError("Invalid coding status")
        if parent_id and self._record(project_id,parent_id,"coding_revision").run_id != run_id:
            raise ValueError("Parent coding belongs to another run")
        normalized=self._validated_applications(project_id,corpus,codebook,applications)
        identity=identity or str(uuid4()); previous=self.repository.list_for_run(run_id,project_id=project_id,record_type="coding_revision")
        self.authority._put(project_id,run_id,"coding_revision",identity,
            {"coding_revision_id":identity,"revision":len(previous)+1,"corpus_id":corpus_id,"codebook_revision_id":codebook_id,
             "applications":normalized,"status":status,"memo":memo},parent=parent_id)
        if status == "accepted": self.authority._activity(project_id,run_id,"QUAL_CODING_REVISION_ACCEPTED","qual_coding",identity)
        return self._record(project_id,identity)

    def create_ai_proposal(self, project_id, run_id, corpus_id, codebook_id, *, batch_key, payload, owner_id):
        self._owner(project_id,owner_id); corpus=self._record(project_id,corpus_id,"analysis_corpus")
        codebook=self._record(project_id,codebook_id,"codebook_revision")
        existing=next((x for x in self.repository.list_for_run(run_id,project_id=project_id,record_type="ai_analysis_proposal")
                       if x.payload["batch_key"] == batch_key),None)
        if existing: return existing
        candidates={x.get("code_id") for x in payload.get("codes",[]) if x.get("code_id")}
        applications=self._validated_applications(project_id,corpus,codebook,payload.get("applications",[]),candidates)
        for theme in payload.get("themes",[]):
            reject_population_claim(theme.get("description",""))
            if not theme.get("supporting_application_ids"): raise ValueError("AI theme requires evidence")
        identity=str(uuid4()); self.authority._put(project_id,run_id,"ai_analysis_proposal",identity,
            {"proposal_id":identity,"corpus_id":corpus_id,"codebook_revision_id":codebook_id,"batch_key":batch_key,
             "codes":payload.get("codes",[]),"applications":applications,"themes":payload.get("themes",[]),"status":"pending_review"})
        self.authority._activity(project_id,run_id,"QUAL_AI_CODING_COMPLETED","qual_ai_proposal",identity)
        return self._record(project_id,identity)

    def review_ai_proposal(self, project_id, proposal_id, *, owner_id, decision):
        self._owner(project_id,owner_id); proposal=self._record(project_id,proposal_id,"ai_analysis_proposal")
        if decision not in {"accepted","rejected"}: raise ValueError("Invalid proposal decision")
        accepted_id=f"{proposal_id}:accepted"
        accepted=self.repository.get_for_project(accepted_id,project_id=project_id)
        if accepted and decision == "rejected": raise ValueError("Canonical proposal acceptance is immutable")
        existing=self.repository.get_for_project(f"{proposal_id}:{decision}",project_id=project_id)
        if existing: return existing
        if decision == "rejected":
            self.authority._put(project_id,proposal.run_id,"ai_proposal_review",f"{proposal_id}:rejected",
                {"proposal_id":proposal_id,"decision":"rejected","status":"reviewed","canonical":None},parent=proposal_id)
            return self._record(project_id,f"{proposal_id}:rejected")

        sessions=getattr(self.repository,"_sessions",None)
        with (sessions.activation(project_id) if sessions is not None else nullcontext()):
            existing=self.repository.get_for_project(accepted_id,project_id=project_id)
            if existing: return existing
            if proposal.payload.get("kind") == "thematic":
                canonical=self.create_thematic_revision(project_id,proposal.run_id,proposal.payload["coding_revision_id"],
                    categories=proposal.payload.get("categories",[]),themes=proposal.payload.get("themes",[]),owner_id=owner_id,
                    status="draft",memo=f"Accepted AI proposal {proposal_id}",identity=f"{proposal_id}:thematic")
                canonical_kind="thematic_revision"
            else:
                source=self._record(project_id,proposal.payload["codebook_revision_id"],"codebook_revision")
                known={x["code_id"] for x in source.payload["codes"]}
                required={x["code_id"] for x in proposal.payload.get("applications",[])}
                candidates={x.get("code_id"):x for x in proposal.payload.get("codes",[]) if x.get("code_id")}
                if not required.issubset(known|set(candidates)): raise ValueError("Proposal references an unreviewed phantom code")
                if required-known:
                    codes=list(source.payload["codes"])+[{**candidates[x],"origin":"ai_accepted"} for x in sorted(required-known)]
                    codebook=self.create_codebook(project_id,proposal.run_id,codes,owner_id=owner_id,parent_id=source.record_id,
                        status="draft",memo=f"Accepted AI proposal {proposal_id}",identity=f"{proposal_id}:codebook")
                else: codebook=source
                applications=[{**x,"origin":"ai_accepted","review_state":"accepted"} for x in proposal.payload.get("applications",[])]
                canonical=self.create_coding(project_id,proposal.run_id,proposal.payload["corpus_id"],codebook.record_id,
                    applications,owner_id=owner_id,status="accepted",
                    memo=f"Accepted AI proposal {proposal_id}",identity=f"{proposal_id}:coding")
                canonical_kind="coding_revision"
            self.authority._put(project_id,proposal.run_id,"ai_proposal_review",accepted_id,
                {"proposal_id":proposal_id,"decision":"accepted","status":"canonicalized","canonical_kind":canonical_kind,
                 "canonical_id":canonical.record_id},parent=proposal_id)
            # Canonical creators emit the applicable migration-020 coding/thematic event in this transaction.
        return self._record(project_id,accepted_id)

    def retry_ai_job(self, project_id, job_id, *, owner_id):
        self._owner(project_id,owner_id); job=self._record(project_id,job_id,"ai_analysis_job")
        states=self.repository.list_for_run(job.run_id,project_id=project_id,record_type="ai_analysis_job_state")
        if any(x.payload.get("job_id")==job_id and x.payload.get("state")=="proposals_ready" for x in states):
            raise ValueError("Completed qualitative AI job cannot be retried")
        if not any(x.payload.get("job_id")==job_id and x.payload.get("state")=="failed" for x in states):
            raise ValueError("Only a failed qualitative AI job can be retried")
        logical=job.payload.get("logical_job_id",job.record_id)
        attempts=[x for x in self.repository.list_for_run(job.run_id,project_id=project_id,record_type="ai_analysis_job")
                  if x.payload.get("logical_job_id",x.record_id)==logical]
        if len(attempts)>=3: raise ValueError("Qualitative AI retry limit reached")
        attempt=len(attempts)+1; identity=f"{logical}:attempt:{attempt}"
        existing=self.repository.get_for_project(identity,project_id=project_id)
        if existing: return existing
        payload={**job.payload,"job_id":identity,"state":"queued","logical_job_id":logical,"attempt":attempt,"retry_of":job_id}
        payload["request"]={**payload["request"],"job_id":identity,"attempt":attempt}
        self.authority._put(project_id,job.run_id,"ai_analysis_job",identity,payload,parent=job_id)
        # Migration 020 has no retry event; the immutable attempt row is the retry audit authority.
        return self._record(project_id,identity)

    def request_ai_job(self, project_id, run_id, corpus_id, codebook_id, *, owner_id, batch_key, kind="coding", coding_id=None):
        self._owner(project_id,owner_id); corpus=self._record(project_id,corpus_id,"analysis_corpus")
        codebook=self._record(project_id,codebook_id,"codebook_revision")
        if corpus.run_id != run_id or codebook.run_id != run_id or kind not in {"coding","thematic"}:
            raise ValueError("Invalid qualitative AI job authority")
        if kind == "thematic":
            coding=self._record(project_id,coding_id,"coding_revision")
            if coding.run_id != run_id or coding.payload["status"] != "accepted": raise ValueError("Accepted coding required")
        existing=next((x for x in self.repository.list_for_run(run_id,project_id=project_id,record_type="ai_analysis_job")
                       if x.payload["batch_key"] == batch_key),None)
        if existing: return existing
        identity=str(uuid4()); request={"job_id":identity,"kind":kind,"batch_key":batch_key,"corpus":corpus.payload,
            "codebook":codebook.payload,"coding":None if not coding_id else self._record(project_id,coding_id,"coding_revision").payload}
        self.authority._put(project_id,run_id,"ai_analysis_job",identity,{"job_id":identity,"state":"queued","batch_key":batch_key,
            "kind":kind,"owner_id":owner_id,"corpus_id":corpus_id,"codebook_revision_id":codebook_id,"coding_revision_id":coding_id,
            "request":request})
        return self._record(project_id,identity)

    def process_next_job(self, worker_id="worker"):
        for job in self.repository.list_by_type("ai_analysis_job"):
            if job.payload.get("state") != "queued": continue
            ready_id=f"{job.record_id}:ready"; failed_id=f"{job.record_id}:failed"
            if self.repository.get_for_project(ready_id,project_id=job.project_id) or self.repository.get_for_project(failed_id,project_id=job.project_id): continue
            running_id=f"{job.record_id}:running"
            if not self.repository.get_for_project(running_id,project_id=job.project_id):
                self.authority._put(job.project_id,job.run_id,"ai_analysis_job_state",running_id,{"job_id":job.record_id,"state":"running"},parent=job.record_id)
            try:
                output=self.provider.propose(job.payload["request"])
                if job.payload["kind"] == "coding":
                    proposal=self.create_ai_proposal(job.project_id,job.run_id,job.payload["corpus_id"],job.payload["codebook_revision_id"],
                        batch_key=job.payload["batch_key"],payload=output,owner_id=job.payload["owner_id"])
                else:
                    coding=self._record(job.project_id,job.payload["coding_revision_id"],"coding_revision")
                    valid={x["application_id"] for x in coding.payload["applications"]}
                    for theme in output.get("themes",[]):
                        refs=theme.get("supporting_application_ids",[])+theme.get("contradictory_application_ids",[])
                        if not refs or not set(refs).issubset(valid): raise ValueError("Thematic proposal evidence is invalid")
                        reject_population_claim(theme.get("description",""))
                    proposal=next((x for x in self.repository.list_for_run(job.run_id,project_id=job.project_id,
                        record_type="ai_analysis_proposal") if x.payload.get("batch_key")==job.payload["batch_key"]),None)
                    if proposal is None:
                        proposal_id=str(uuid4()); self.authority._put(job.project_id,job.run_id,"ai_analysis_proposal",proposal_id,
                            {"proposal_id":proposal_id,"kind":"thematic","batch_key":job.payload["batch_key"],"coding_revision_id":coding.record_id,
                             "categories":output.get("categories",[]),"themes":output.get("themes",[]),"status":"pending_review"})
                        proposal=self._record(job.project_id,proposal_id)
                self.authority._put(job.project_id,job.run_id,"ai_analysis_job_state",ready_id,
                    {"job_id":job.record_id,"state":"proposals_ready","proposal_id":proposal.record_id},parent=job.record_id)
            except Exception as exc:
                self.authority._put(job.project_id,job.run_id,"ai_analysis_job_state",failed_id,
                    {"job_id":job.record_id,"state":"failed","error_category":type(exc).__name__},parent=job.record_id)
                raise
            return True
        return False

    def create_thematic_revision(self, project_id, run_id, coding_id, *, categories, themes, owner_id,
                                 status="draft", parent_id=None, memo="", identity=None):
        self._owner(project_id,owner_id); coding=self._record(project_id,coding_id,"coding_revision")
        if coding.run_id != run_id or coding.payload["status"] != "accepted": raise ValueError("Accepted coding is required")
        if status not in {"draft","accepted"}: raise ValueError("Invalid thematic status")
        if parent_id and self._record(project_id,parent_id,"thematic_revision").run_id != run_id:
            raise ValueError("Parent thematic revision belongs to another run")
        apps={x["application_id"]:x for x in coding.payload["applications"]}; codes={x["code_id"] for x in coding.payload["applications"]}
        category_ids=set()
        for item in categories:
            if item["category_id"] in category_ids or not set(item.get("code_ids",[])).issubset(codes): raise ValueError("Invalid category")
            category_ids.add(item["category_id"])
        normalized=[]
        for item in themes:
            reject_population_claim(item.get("description","")); support=item.get("supporting_application_ids",[])
            contradictions=item.get("contradictory_application_ids",[])
            if not support or not set(support+contradictions).issubset(apps): raise ValueError("Theme evidence is invalid")
            if not set(item.get("code_ids",[])).issubset(codes) or not set(item.get("category_ids",[])).issubset(category_ids):
                raise ValueError("Theme references unknown analytical objects")
            represented=[apps[x] for x in dict.fromkeys(support+contradictions)]
            normalized.append({**item,"participant_count":len({x["participant_id"] for x in represented}),
                "session_count":len({x["session_id"] for x in represented}),"span_count":len(represented)})
        identity=identity or str(uuid4()); previous=self.repository.list_for_run(run_id,project_id=project_id,record_type="thematic_revision")
        self.authority._put(project_id,run_id,"thematic_revision",identity,
            {"thematic_revision_id":identity,"revision":len(previous)+1,"coding_revision_id":coding_id,
             "corpus_id":coding.payload["corpus_id"],"codebook_revision_id":coding.payload["codebook_revision_id"],
             "categories":categories,"themes":normalized,"status":status,"memo":memo},parent=parent_id)
        self.authority._activity(project_id,run_id,"QUAL_THEMATIC_REVISION_CREATED","qual_thematic_analysis",identity)
        if status == "accepted":
            self.authority._activity(project_id,run_id,"QUAL_THEMATIC_ANALYSIS_ACCEPTED","qual_thematic_analysis",identity)
            self.authority._activity(project_id,run_id,"QUAL_READY_FOR_FINDINGS","qual_thematic_analysis",identity)
        return self._record(project_id,identity)

    def readiness(self, project_id, run_id, *, owner_id):
        self._owner(project_id,owner_id)
        accepted=[x for x in self.repository.list_for_run(run_id,project_id=project_id,record_type="thematic_revision")
                  if x.payload.get("status") == "accepted"]
        if accepted: return "ready_for_findings"
        proposals=self.repository.list_for_run(run_id,project_id=project_id,record_type="ai_analysis_proposal")
        if proposals: return "ai_proposals_pending_review"
        codings=self.repository.list_for_run(run_id,project_id=project_id,record_type="coding_revision")
        if codings: return "themes_require_review"
        corpora=self.repository.list_for_run(run_id,project_id=project_id,record_type="analysis_corpus")
        return "codebook_draft" if corpora else "corpus_incomplete"
