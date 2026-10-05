"""Source-bound qualitative Report revisions for QUA-04 deliverables."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from application.deliverables.contracts import PdfSection, PdfSourceDocument


class QualitativeReportError(ValueError):
    pass


class QualitativeReportService:
    def __init__(self, authority):
        self.authority = authority
        self.repository = authority.repository

    def _owner(self, project_id, owner_id):
        self.authority._project(project_id, owner_id)

    def _get(self, project_id, identity, kind=None):
        try:
            return self.authority._get(project_id, identity, kind)
        except LookupError as exc:
            raise QualitativeReportError("Qualitative report authority not found") from exc

    def _approved_chain(self, project_id, run_id, approved_id):
        approved = self._get(project_id, approved_id, "qualitative_approved_revision")
        if approved.run_id != run_id or approved.payload.get("status") != "ready_for_deliverables":
            raise QualitativeReportError("Exact approved qualitative revision is required")
        thematic = self._get(project_id, approved.payload["thematic_revision_id"], "thematic_revision")
        if thematic.run_id != run_id or thematic.payload.get("status") != "accepted":
            raise QualitativeReportError("Accepted thematic authority is unavailable")
        findings = [self._get(project_id, identity, "qualitative_finding")
                    for identity in approved.payload["finding_ids"]]
        insights = [self._get(project_id, identity, "qualitative_insight")
                    for identity in approved.payload["insight_ids"]]
        if any(x.run_id != run_id or x.payload.get("status") != "accepted" or
               x.payload.get("thematic_revision_id") != thematic.record_id for x in findings + insights):
            raise QualitativeReportError("Approved qualitative authority is inconsistent")
        if any(not set(x.payload.get("finding_ids", ())).issubset(approved.payload["finding_ids"])
               for x in insights):
            raise QualitativeReportError("Insight provenance is outside the approved revision")
        return approved, thematic, findings, insights

    def create_draft(self, project_id, run_id, approved_id, *, owner_id, title):
        self._owner(project_id, owner_id)
        approved, thematic, findings, insights = self._approved_chain(project_id, run_id, approved_id)
        existing = [x for x in self.repository.list_for_run(run_id, project_id=project_id,
                    record_type="qualitative_report_revision")
                    if x.payload.get("approved_revision_id") == approved_id]
        if existing:
            return max(existing, key=lambda x: x.payload["revision"])
        report_id = str(uuid5(NAMESPACE_URL, f"qua-report:{project_id}:{run_id}:{approved_id}"))
        payload = self._payload(report_id, 1, approved, thematic, findings, insights,
                                evidence=self._evidence(project_id, thematic),
                                title=title.strip() or "Якісний дослідницький звіт", status="draft")
        self.authority._put(project_id, run_id, "qualitative_report_revision", report_id, payload)
        self.authority._activity(project_id, run_id, "QUAL_REPORT_DRAFT_CREATED", "qual_report", report_id)
        return self._get(project_id, report_id)

    def revise(self, project_id, run_id, report_id, *, owner_id, title, executive_summary,
               methodology, limitations, conclusion):
        self._owner(project_id, owner_id)
        previous = self._get(project_id, report_id, "qualitative_report_revision")
        if previous.run_id != run_id or previous.payload.get("status") != "draft":
            raise QualitativeReportError("Only a draft Report can be edited")
        approved, thematic, findings, insights = self._approved_chain(
            project_id, run_id, previous.payload["approved_revision_id"])
        revision = previous.payload["revision"] + 1
        identity = str(uuid5(NAMESPACE_URL, f"qua-report:{report_id}:revision:{revision}"))
        payload = self._payload(identity, revision, approved, thematic, findings, insights,
            evidence=self._evidence(project_id, thematic),
            title=title, status="draft", executive_summary=executive_summary,
            methodology=methodology, limitations=limitations, conclusion=conclusion)
        payload["report_root_id"] = previous.payload.get("report_root_id", previous.record_id)
        self.authority._put(project_id, run_id, "qualitative_report_revision", identity, payload,
                            parent=previous.record_id)
        return self._get(project_id, identity)

    def finalize(self, project_id, run_id, report_id, *, owner_id):
        self._owner(project_id, owner_id)
        draft = self._get(project_id, report_id, "qualitative_report_revision")
        if draft.run_id != run_id:
            raise QualitativeReportError("Report belongs to another run")
        self._approved_chain(project_id, run_id, draft.payload["approved_revision_id"])
        if draft.payload.get("status") == "final":
            return draft
        if draft.payload.get("status") != "draft":
            raise QualitativeReportError("Report draft is required")
        identity = str(uuid5(NAMESPACE_URL, f"qua-report-final:{draft.record_id}"))
        existing = self.repository.get_for_project(identity, project_id=project_id)
        if existing:
            return existing
        payload = dict(draft.payload)
        payload.update({"report_id": identity, "status": "final",
                        "finalized_at": datetime.now(UTC).isoformat(),
                        "source_draft_id": draft.record_id})
        self.authority._put(project_id, run_id, "qualitative_report_revision", identity, payload,
                            parent=draft.record_id)
        self.authority._activity(project_id, run_id, "QUAL_REPORT_FINALIZED", "qual_report", identity)
        self.authority._activity(project_id, run_id, "QUAL_DELIVERABLE_READY", "qual_report", identity)
        return self._get(project_id, identity)

    def _evidence(self, project_id, thematic):
        coding = self._get(project_id, thematic.payload["coding_revision_id"], "coding_revision")
        allowed = {identity for theme in thematic.payload.get("themes", ())
                   for identity in theme.get("supporting_application_ids", ()) +
                   theme.get("contradictory_application_ids", ())}
        result = []
        for app in coding.payload.get("applications", ()):
            if app.get("application_id") not in allowed:
                continue
            pseudonym = app.get("participant_pseudonym", "Participant")
            label = pseudonym if str(pseudonym).upper().startswith(("P", "I")) else "Participant"
            result.append({"application_id": app["application_id"], "label": label,
                           "excerpt": app.get("excerpt", ""),
                           "transcript_version_id": app["transcript_version_id"],
                           "segment_id": app["segment_id"], "start": app["start"], "end": app["end"],
                           "timestamp": None})
        return result

    @staticmethod
    def _payload(identity, revision, approved, thematic, findings, insights, *, evidence, title, status,
                 executive_summary=None, methodology=None, limitations=None, conclusion=None):
        themes = {x["theme_id"]: x for x in thematic.payload.get("themes", ())}
        deviant = []
        for finding in findings:
            for theme_id in finding.payload.get("theme_ids", ()):
                theme = themes.get(theme_id, {})
                if theme.get("contradictory_application_ids"):
                    deviant.append(f"{theme.get('title', theme_id)}: збережено суперечливі або девіантні свідчення.")
        return {
            "report_id": identity, "report_root_id": identity, "revision": revision,
            "approved_revision_id": approved.record_id,
            "approved_revision_version": approved.payload["revision"],
            "thematic_revision_id": thematic.record_id,
            "finding_ids": list(approved.payload["finding_ids"]),
            "insight_ids": list(approved.payload["insight_ids"]),
            "title": title.strip() or "Якісний дослідницький звіт",
            "executive_summary": (executive_summary or "Звіт узагальнює лише схвалені якісні Findings та Insights."),
            "methodology": (methodology or "Глибинні інтерв’ю; прийняте кодування і тематичний аналіз; Findings та Insights пройшли review."),
            "limitations": (limitations or "Висновки описують дослідницький корпус і не є статистично репрезентативними."),
            "conclusion": (conclusion or "Імплікації обмежені схваленою якісною аналітичною версією."),
            "deviant_cases": deviant,
            "evidence_excerpts": evidence,
            "status": status, "created_at": datetime.now(UTC).isoformat(),
        }

    def documents(self, project_id, run_ids):
        documents = []
        for run_id in sorted(run_ids):
            for report in self.repository.list_for_run(run_id, project_id=project_id,
                                                       record_type="qualitative_report_revision"):
                if report.payload.get("status") != "final":
                    continue
                approved, thematic, findings, insights = self._approved_chain(
                    project_id, run_id, report.payload["approved_revision_id"])
                finding_sections = tuple(PdfSection(
                    f"Finding: {item.payload['title']}",
                    (item.payload["statement"], item.payload["explanation"]),
                    tuple(item.payload.get("supporting_application_ids", ())) +
                    tuple(item.payload.get("deviant_application_ids", ())),
                ) for item in findings)
                insight_sections = tuple(PdfSection(
                    f"Insight: {item.payload['title']}",
                    (item.payload["statement"], item.payload["implication"]),
                    tuple(item.payload.get("finding_ids", ())),
                ) for item in insights)
                deviant = tuple(report.payload.get("deviant_cases", ()))
                evidence = tuple(f"{x['label']}: «{x['excerpt']}»" for x in report.payload.get("evidence_excerpts", ()))
                sections = (PdfSection("Методологія", (report.payload["methodology"],)),
                            *finding_sections, *insight_sections)
                if deviant:
                    sections += (PdfSection("Суперечності та девіантні випадки", deviant),)
                if evidence:
                    sections += (PdfSection("Підтверджувальні уривки", evidence,
                                            tuple(x["application_id"] for x in report.payload["evidence_excerpts"])),)
                sections += (PdfSection("Висновок та імплікації", (report.payload["conclusion"],)),)
                documents.append(PdfSourceDocument(
                    project_id=project_id, method="QUALITATIVE", run_id=run_id, study_id=None,
                    source_id=report.record_id, source_version=report.checksum, status="Фіналізовано",
                    title=report.payload["title"], summary=report.payload["executive_summary"],
                    sections=sections, limitations=(report.payload["limitations"],),
                    citation_registry=tuple((x.record_id, x.payload["title"]) for x in findings + insights),
                    created_at=report.payload["created_at"], revision_number=report.payload["revision"],
                    previous_report_id=report.parent_record_id,
                ))
        return sorted(documents, key=lambda x: (x.created_at or "", x.source_id), reverse=True)
