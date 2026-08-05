"""One-off live run diagnostic — read-only PostgreSQL analysis."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

RUN_ID = os.environ.get("DIAGNOSE_RUN_ID", "ed6d88a8-dd0e-4aad-b035-31b31bbe433e")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from application.report.coverage_validation import (
    covered_research_question_ids,
    section_supports_question,
)
from application.review.issue_deduplication import (
    deduplicate_review_issues,
    normalize_review_message,
    review_issue_semantic_key,
)
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType


def _engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def _fetch_one(conn, sql: str, **params):
    return conn.execute(text(sql), params).mappings().first()


def _fetch_all(conn, sql: str, **params):
    return conn.execute(text(sql), params).mappings().all()


def _load_design(snapshot: dict) -> list[dict]:
    design = snapshot.get("research_design_snapshot") or {}
    return design.get("research_questions") or []


def _issue_from_row(item: dict) -> ReviewIssue:
    return ReviewIssue.from_dict(item)


def _type_ref_key(issue: ReviewIssue) -> tuple:
    return (
        issue.issue_type.value,
        issue.severity.value,
        tuple(sorted(issue.finding_refs)),
        tuple(sorted(issue.insight_refs)),
        tuple(sorted(issue.evidence_refs)),
        tuple(sorted(issue.source_refs)),
        tuple(sorted(issue.research_question_refs)),
    )


def main() -> None:
    engine = _engine()
    out: dict = {"run_id": RUN_ID}

    with engine.connect() as conn:
        run = _fetch_one(
            conn,
            "SELECT id, project_id, workflow_template_id, status FROM workflow_runs WHERE id = :run_id",
            run_id=RUN_ID,
        )
        if run is None:
            raise SystemExit(f"Run not found: {RUN_ID}")
        out["workflow_run"] = dict(run)

        template = _fetch_one(
            conn,
            "SELECT snapshot_data FROM workflow_templates WHERE id = :id",
            id=run["workflow_template_id"],
        )
        snapshot = (template or {}).get("snapshot_data") or {}
        design = snapshot.get("research_design_snapshot") or snapshot.get("research_design") or {}
        questions = design.get("research_questions") or []
        out["research_questions"] = questions

        evidence = _fetch_all(
            conn,
            "SELECT id, statement, source_id, research_question_refs, evidence_type FROM evidence WHERE workflow_run_id = :run_id",
            run_id=RUN_ID,
        )
        findings = _fetch_all(
            conn,
            "SELECT id, statement, finding_type, evidence_refs, research_question_refs FROM findings WHERE workflow_run_id = :run_id",
            run_id=RUN_ID,
        )
        insights = _fetch_all(
            conn,
            "SELECT id, statement, finding_refs, research_question_refs FROM insights WHERE workflow_run_id = :run_id",
            run_id=RUN_ID,
        )
        report = _fetch_one(
            conn,
            "SELECT id, sections, limitations, executive_summary, citation_registry, generation_method FROM reports WHERE workflow_run_id = :run_id ORDER BY revision_number DESC LIMIT 1",
            run_id=RUN_ID,
        )
        review = _fetch_one(
            conn,
            "SELECT id, verdict, summary, issues, review_method, review_attempt FROM review_results WHERE workflow_run_id = :run_id ORDER BY review_attempt DESC LIMIT 1",
            run_id=RUN_ID,
        )

    out["counts"] = {
        "evidence": len(evidence),
        "findings": len(findings),
        "insights": len(insights),
        "report_sections": len((report or {}).get("sections") or []),
        "review_issues": len((review or {}).get("issues") or []),
    }

    sections = (report or {}).get("sections") or []
    limitations = (report or {}).get("limitations") or []
    exec_summary = (report or {}).get("executive_summary") or ""
    citation_registry = (report or {}).get("citation_registry") or {}
    design_limitations = design.get("limitations") or []

    # Index helpers
    ev_by_rq: dict[str, list] = defaultdict(list)
    for row in evidence:
        for rq in row["research_question_refs"] or []:
            ev_by_rq[rq].append(row["id"])
    fi_by_rq: dict[str, list] = defaultdict(list)
    for row in findings:
        for rq in row["research_question_refs"] or []:
            fi_by_rq[rq].append(row["id"])
    in_by_rq: dict[str, list] = defaultdict(list)
    for row in insights:
        for rq in row["research_question_refs"] or []:
            in_by_rq[rq].append(row["id"])

    contradiction_findings = [
        f for f in findings if f["finding_type"] == "contradiction"
    ]

    # Simple finding objects for coverage_validation
    class _F:
        def __init__(self, d):
            self.id = d["id"]
            self.research_question_refs = tuple(d.get("research_question_refs") or [])

    class _S:
        def __init__(self, d):
            self.id = d.get("id", "")
            self.title = d.get("title", "")
            self.content = d.get("content", "")
            self.research_question_refs = tuple(d.get("research_question_refs") or [])
            self.finding_refs = tuple(d.get("finding_refs") or [])
            self.insight_refs = tuple(d.get("insight_refs") or [])
            self.evidence_refs = tuple(d.get("evidence_refs") or [])
            self.citation_ids = tuple(d.get("citation_ids") or [])

    finding_objs = [_F(f) for f in findings]
    section_objs = [_S(s) for s in sections]

    class _Design:
        def __init__(self, qs):
            self.research_questions = [type("Q", (), {"id": q["id"], "question": q.get("question", "")})() for q in qs]

    design_obj = _Design(questions)
    ref_covered = covered_research_question_ids(section_objs, findings=finding_objs, design=design_obj)

    corpus = " ".join([exec_summary] + [s.content for s in section_objs]).lower()
    ack_words = ("contradict", "conflict", "uncertain", "mixed", "inconsistent")

    matrix = []
    issues = (review or {}).get("issues") or []
    issue_objs = [_issue_from_row(i) for i in issues]

    for q in questions:
        qid = q["id"]
        qtext = q.get("question", "")[:80]
        supporting_sections = []
        for s in section_objs:
            if section_supports_question(s, qid, finding_objs):
                supporting_sections.append(
                    {
                        "id": s.id,
                        "title": s.title[:60],
                        "rq_refs": list(s.research_question_refs),
                        "finding_refs": len(s.finding_refs),
                        "citation_ids": len(s.citation_ids),
                    }
                )
        # substantive: question tokens in section content
        tokens = [t for t in qtext.lower().split() if len(t) > 4][:5]
        substantive_hits = sum(
            1
            for s in section_objs
            if section_supports_question(s, qid, finding_objs)
            and (not tokens or sum(t in s.content.lower() for t in tokens) >= min(2, len(tokens)))
        )
        rq_issues = [
            i for i in issue_objs if qid in i.research_question_refs or qid in (i.message or "")
        ]
        cov_issues = [i for i in rq_issues if i.issue_type == ReviewIssueType.COVERAGE_GAP]
        matrix.append(
            {
                "rq_id": qid,
                "question": qtext,
                "evidence_count": len(ev_by_rq.get(qid, [])),
                "finding_count": len(fi_by_rq.get(qid, [])),
                "insight_count": len(in_by_rq.get(qid, [])),
                "ref_coverage_write_gate": qid in ref_covered,
                "supporting_section_count": len(supporting_sections),
                "substantive_section_hits": substantive_hits,
                "sections": supporting_sections[:5],
                "review_coverage_gap_count": len(cov_issues),
                "review_issue_count": len(rq_issues),
            }
        )

    out["rq_matrix"] = matrix

    # Write gate vs structural semantic gaps
    structural_cov = [
        i
        for i in issue_objs
        if i.issue_type == ReviewIssueType.COVERAGE_GAP and i.severity == ReviewIssueSeverity.MAJOR
    ]
    out["write_gate"] = {
        "ref_covered_rq_ids": sorted(ref_covered),
        "missing_at_write_gate": [q["id"] for q in questions if q["id"] not in ref_covered],
        "report_section_count": len(sections),
        "report_limitations_count": len(limitations),
        "design_limitations": design_limitations,
        "citation_registry_size": len(citation_registry),
    }

    # Dedup analysis on persisted issues (simulate pre-dedup by duplicating cross-section pattern impossible - analyze uniqueness)
    deduped = deduplicate_review_issues(issue_objs)
    type_ref_keys = Counter(_type_ref_key(i) for i in issue_objs)
    msg_keys = Counter(review_issue_semantic_key(i) for i in issue_objs)
    loose_keys = Counter(
        (i.issue_type.value, i.severity.value, normalize_review_message(i.message))
        for i in issue_objs
    )

    out["dedup"] = {
        "persisted_count": len(issue_objs),
        "deduped_count_current_key": len(deduped),
        "unique_type_ref_key": len(type_ref_keys),
        "unique_message_key": len(loose_keys),
        "top_message_clusters": loose_keys.most_common(15),
        "issues_removed_by_dedup": len(issue_objs) - len(deduped),
    }

    # If dedup ran, persisted should equal deduped; if not, they're same input
    out["dedup"]["dedup_applied_at_persist"] = len(issue_objs) == len(deduped)

    by_type = Counter(f"{i.issue_type.value}/{i.severity.value}" for i in issue_objs)
    out["issue_breakdown"] = dict(by_type)

    # Contradiction analysis
    out["contradictions"] = {
        "contradiction_finding_count": len(contradiction_findings),
        "contradiction_finding_ids": [f["id"] for f in contradiction_findings[:10]],
        "acknowledgment_keywords_in_corpus": any(w in corpus for w in ack_words),
        "contradiction_review_issues": len(
            [i for i in issue_objs if i.issue_type == ReviewIssueType.CONTRADICTION]
        ),
        "sample_contradiction_findings": [
            {"id": f["id"], "statement": f["statement"][:120]} for f in contradiction_findings[:5]
        ],
    }

    # Limitations
    lim_issues = [i for i in issue_objs if i.issue_type == ReviewIssueType.MISSING_LIMITATION]
    lim_msgs = Counter(normalize_review_message(i.message) for i in lim_issues)
    out["limitations"] = {
        "report_limitations": limitations,
        "design_limitations": design_limitations,
        "missing_limitation_issue_count": len(lim_issues),
        "unique_limitation_messages": len(lim_msgs),
        "top_limitation_clusters": lim_msgs.most_common(10),
    }

    # Provenance samples
    unsupported = [i for i in issue_objs if i.issue_type == ReviewIssueType.UNSUPPORTED_CLAIM][:5]
    missing_cit = [i for i in issue_objs if i.issue_type == ReviewIssueType.MISSING_CITATION][:5]
    fi_by_id = {f["id"]: f for f in findings}

    def _trace_issue(issue: ReviewIssue) -> dict:
        sec = next((s for s in section_objs if s.id == issue.report_section_id), None)
        trace = {
            "issue_type": issue.issue_type.value,
            "severity": issue.severity.value,
            "message": issue.message[:160],
            "section_id": issue.report_section_id,
            "section_title": sec.title if sec else None,
            "section_finding_refs": list(sec.finding_refs) if sec else [],
            "section_citation_ids": list(sec.citation_ids) if sec else [],
            "issue_finding_refs": list(issue.finding_refs),
        }
        if sec and sec.finding_refs:
            trace["finding_statements"] = [
                fi_by_id.get(fid, {}).get("statement", "")[:80]
                for fid in sec.finding_refs[:3]
            ]
        return trace

    out["provenance_samples"] = {
        "unsupported_claim": [_trace_issue(i) for i in unsupported],
        "missing_citation": [_trace_issue(i) for i in missing_cit],
        "sections_without_citations_but_with_evidence": sum(
            1 for s in section_objs if s.evidence_refs and not s.citation_ids
        ),
        "sections_with_citations": sum(1 for s in section_objs if s.citation_ids),
        "total_citations_in_registry": len(citation_registry),
    }

    # structural vs semantic coverage gaps
    structural_cov = [
        i
        for i in issue_objs
        if i.issue_type == ReviewIssueType.COVERAGE_GAP
        and "not covered in the report" in i.message
    ]
    semantic_cov = [
        i
        for i in issue_objs
        if i.issue_type == ReviewIssueType.COVERAGE_GAP and i not in structural_cov
    ]
    out["coverage_gap_analysis"] = {
        "total": len([i for i in issue_objs if i.issue_type == ReviewIssueType.COVERAGE_GAP]),
        "structural_style_major": sum(
            1 for i in structural_cov if i.severity == ReviewIssueSeverity.MAJOR
        ),
        "semantic_style": len(semantic_cov),
        "semantic_style_major": sum(
            1 for i in semantic_cov if i.severity == ReviewIssueSeverity.MAJOR
        ),
    }

    explicit_rq_refs = Counter(
        q for s in section_objs for q in s.research_question_refs
    )
    out["section_rq_ref_counts"] = dict(explicit_rq_refs)

    prefix_clusters = Counter(
        normalize_review_message(i.message)[:80] for i in issue_objs
    )
    out["message_prefix_clusters_top"] = prefix_clusters.most_common(10)

    out["review"] = {
        "verdict": (review or {}).get("verdict"),
        "summary": (review or {}).get("summary"),
        "review_method": (review or {}).get("review_method"),
        "review_attempt": (review or {}).get("review_attempt"),
        "estimated_llm_calls": len(sections),
    }

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
