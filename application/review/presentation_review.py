from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Mapping

from application.ports.review_ports import ReviewIssueCandidate
from application.report.claim_contract import canonical_digest
from application.report.coverage_contract import ReportCoverageContract
from application.report.editorial_contract import EDITORIAL_CONTRACT_VERSION, PresentationReport
from application.report.presentation_persistence import presentation_report_digest, read_presentation_report
from domain.reports.report import Report
from domain.reports.report_claim import ReportClaim


MAX_SEMANTIC_REVIEW_CALLS_PER_PASS = 2
MAX_EDITORIAL_REVISION_CALLS = 2
MAX_FULL_REPORT_LIFECYCLE_CALLS = 10


class PresentationReviewError(ValueError):
    pass


class PresentationTargetType(str, Enum):
    REPORT = "REPORT"
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    SECTION = "SECTION"
    PARAGRAPH = "PARAGRAPH"
    EDITORIAL_UNIT = "EDITORIAL_UNIT"
    REPORT_CLAIM = "REPORT_CLAIM"
    COVERAGE_LIMITATION = "COVERAGE_LIMITATION"


SEMANTIC_ISSUE_TYPES = frozenset({
    "readability", "clarity", "organization", "synthesis", "repetition",
    "executive_summary_usefulness", "section_coherence",
    "limitation_wording", "interpretation_communication",
})


@dataclass(frozen=True)
class PresentationReviewTarget:
    target_type: PresentationTargetType
    target_ref: str
    claim_refs: tuple[str, ...] = ()
    section_id: str | None = None


@dataclass(frozen=True)
class PresentationReviewInput:
    project_id: str
    workflow_run_id: str
    research_design_id: str
    report_id: str
    revision_number: int
    previous_report_id: str | None
    report_contract_version: str
    authority_digest: str
    presentation_digest: str
    presentation: PresentationReport
    claims: tuple[ReportClaim, ...]
    targets: tuple[PresentationReviewTarget, ...]
    paragraph_claim_refs: Mapping[str, tuple[str, ...]]
    claim_support: Mapping[str, Mapping[str, tuple[str, ...]]]
    canonical_citations: Mapping[str, Mapping[str, str]]
    coverage_contract: ReportCoverageContract
    limitations: tuple[Any, ...]

    def target_catalog(self) -> dict[tuple[str, str], PresentationReviewTarget]:
        return {(item.target_type.value, item.target_ref): item for item in self.targets}

    def provider_payload(self) -> str:
        paragraphs = self.presentation.executive_summary.paragraphs + tuple(
            paragraph for section in self.presentation.sections for paragraph in section.paragraphs
        )
        payload = {
            "contract_version": EDITORIAL_CONTRACT_VERSION,
            "report_id": self.report_id,
            "revision_number": self.revision_number,
            "authority_digest": self.authority_digest,
            "presentation_digest": self.presentation_digest,
            "title": self.presentation.title,
            "paragraphs": [
                {
                    "paragraph_id": item.paragraph_id,
                    "text": item.text,
                    "claim_refs": list(item.claim_refs),
                    "citation_refs": list(item.citation_refs),
                    "limitation_refs": list(item.limitation_refs),
                }
                for item in paragraphs
            ],
            "targets": [
                {"target_type": item.target_type.value, "target_ref": item.target_ref}
                for item in self.targets
            ],
            "limitations": [item.limitation_id for item in self.limitations],
            "coverage": self.coverage_contract.to_metadata(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_presentation_review_input(
    *, report: Report, claims: tuple[ReportClaim, ...],
    coverage_contract: ReportCoverageContract,
) -> PresentationReviewInput:
    presentation = read_presentation_report(report, claims=claims)
    if presentation is None:
        raise PresentationReviewError("presentation_report_missing")
    claim_by_id = {item.claim_id: item for item in claims}
    if len(claim_by_id) != len(claims):
        raise PresentationReviewError("duplicate_report_claim")

    targets: list[PresentationReviewTarget] = [
        PresentationReviewTarget(PresentationTargetType.REPORT, report.id),
        PresentationReviewTarget(PresentationTargetType.EXECUTIVE_SUMMARY, "executive_summary"),
    ]
    paragraph_claim_refs: dict[str, tuple[str, ...]] = {}
    seen_paragraphs: set[str] = set()
    seen_units: set[str] = set()
    summary_claims = tuple(dict.fromkeys(
        ref for paragraph in presentation.executive_summary.paragraphs for ref in paragraph.claim_refs
    ))
    targets[1] = PresentationReviewTarget(
        PresentationTargetType.EXECUTIVE_SUMMARY, "executive_summary", summary_claims,
    )
    for section in presentation.sections:
        section_claims = tuple(dict.fromkeys(ref for p in section.paragraphs for ref in p.claim_refs))
        targets.append(PresentationReviewTarget(
            PresentationTargetType.SECTION, section.section_id, section_claims, section.section_id,
        ))
        for paragraph in section.paragraphs:
            _add_paragraph_targets(paragraph, targets, paragraph_claim_refs, seen_paragraphs, seen_units, section.section_id)
    for paragraph in presentation.executive_summary.paragraphs:
        _add_paragraph_targets(paragraph, targets, paragraph_claim_refs, seen_paragraphs, seen_units, None)
    for claim in claims:
        targets.append(PresentationReviewTarget(
            PresentationTargetType.REPORT_CLAIM, claim.claim_id, (claim.claim_id,),
        ))
    for limitation in presentation.limitations:
        targets.append(PresentationReviewTarget(
            PresentationTargetType.COVERAGE_LIMITATION, limitation.limitation_id,
            limitation.supported_claim_refs,
        ))

    referenced_claims = {ref for refs in paragraph_claim_refs.values() for ref in refs}
    referenced_claims.update(ref for item in presentation.limitations for ref in item.supported_claim_refs)
    if not referenced_claims <= set(claim_by_id):
        raise PresentationReviewError("foreign_report_claim_ref")

    canonical_citations = {
        item.citation_ref: {
            "claim_ref": item.claim_ref, "citation_id": item.citation_id,
            "source_id": item.source_id, "display_key": item.display_key,
        }
        for item in presentation.citations
    }
    if len(canonical_citations) != len(presentation.citations):
        raise PresentationReviewError("duplicate_presentation_citation")
    for citation in presentation.citations:
        registry_item = report.citation_registry.get(citation.citation_id)
        if not isinstance(registry_item, Mapping):
            raise PresentationReviewError("citation_registry_entry_missing")
        expected_display = citation.citation_id
        expected_ref = "ec_" + canonical_digest({
            "claim_ref": citation.claim_ref,
            "citation_id": citation.citation_id,
            "source_id": citation.source_id,
        })
        if (
            citation.citation_ref != expected_ref
            or
            citation.source_id != str(registry_item.get("source_id", ""))
            or citation.title != str(registry_item.get("title", ""))
            or citation.canonical_url != str(registry_item.get("canonical_url", ""))
            or citation.display_key != expected_display
        ):
            raise PresentationReviewError("canonical_citation_mismatch")

    return PresentationReviewInput(
        project_id=report.project_id, workflow_run_id=report.workflow_run_id,
        research_design_id=report.research_design_id, report_id=report.id,
        revision_number=report.revision_number, previous_report_id=report.previous_report_id,
        report_contract_version=EDITORIAL_CONTRACT_VERSION,
        authority_digest=presentation.authority_digest,
        presentation_digest=presentation_report_digest(presentation),
        presentation=presentation, claims=claims, targets=tuple(targets),
        paragraph_claim_refs=paragraph_claim_refs,
        claim_support={
            item.claim_id: {
                "finding_ids": item.finding_ids, "evidence_ids": item.evidence_ids,
                "insight_ids": item.insight_ids, "source_ids": item.source_ids,
            }
            for item in claims
        },
        canonical_citations=canonical_citations,
        coverage_contract=coverage_contract, limitations=presentation.limitations,
    )


def deterministic_presentation_issues(review_input: PresentationReviewInput) -> tuple[ReviewIssueCandidate, ...]:
    issues: list[ReviewIssueCandidate] = []
    claims = {item.claim_id: item for item in review_input.claims}
    citations = review_input.canonical_citations
    used_citations: set[str] = set()
    paragraphs = review_input.presentation.executive_summary.paragraphs + tuple(
        p for section in review_input.presentation.sections for p in section.paragraphs
    )
    for paragraph in paragraphs:
        foreign_claims = set(paragraph.claim_refs) - set(claims)
        if foreign_claims:
            issues.append(_deterministic_issue("unsupported_claim_mapping", paragraph.paragraph_id, paragraph.claim_refs))
            continue
        if (paragraph.fact_refs or paragraph.period_refs) and not paragraph.citation_refs:
            issues.append(_deterministic_issue("missing_required_citation", paragraph.paragraph_id, paragraph.claim_refs, "missing_citation"))
        for ref in paragraph.citation_refs:
            citation = citations.get(ref)
            if citation is None:
                issues.append(_deterministic_issue("unknown_citation_ref", paragraph.paragraph_id, paragraph.claim_refs, "missing_citation"))
                continue
            used_citations.add(ref)
            claim = claims.get(citation["claim_ref"])
            if claim is None or citation["claim_ref"] not in paragraph.claim_refs:
                issues.append(_deterministic_issue("citation_claim_mismatch", paragraph.paragraph_id, paragraph.claim_refs, "missing_citation"))
                continue
            if citation["citation_id"] not in claim.citation_ids or citation["source_id"] not in claim.source_ids:
                issues.append(_deterministic_issue("citation_support_mismatch", paragraph.paragraph_id, paragraph.claim_refs, "missing_citation"))
            if not citation["display_key"]:
                issues.append(_deterministic_issue("citation_display_key_missing", paragraph.paragraph_id, paragraph.claim_refs, "missing_citation"))
        for claim_ref in paragraph.claim_refs:
            claim = claims[claim_ref]
            if not claim.finding_ids or not claim.evidence_ids or not claim.support_evidence_ids:
                issues.append(_deterministic_issue("claim_support_lineage_missing", paragraph.paragraph_id, (claim_ref,)))
    for ref in sorted(set(citations) - used_citations):
        issues.append(_deterministic_issue(
            "orphan_citation", review_input.report_id,
            (citations[ref]["claim_ref"],), "missing_citation", target_type="REPORT",
        ))

    if review_input.coverage_contract.mode == "limited":
        disclosed = {item.topic_ref for item in review_input.limitations}
        for rq_id in review_input.coverage_contract.excluded_rq_ids:
            if rq_id not in disclosed:
                issues.append(_deterministic_issue(
                    "required_limitation_missing", review_input.report_id, (),
                    "missing_limitation", rq_id, target_type="REPORT",
                ))
    for limitation in review_input.limitations:
        if not set(limitation.supported_claim_refs) <= set(claims):
            issues.append(_deterministic_issue(
                "limitation_claim_scope_invalid", limitation.limitation_id,
                limitation.supported_claim_refs, "missing_limitation",
                target_type="COVERAGE_LIMITATION",
            ))
    return tuple(issues)


def resolve_semantic_presentation_issues(
    payload: Mapping[str, Any], *, review_input: PresentationReviewInput,
) -> tuple[ReviewIssueCandidate, ...]:
    if set(payload) != {"issues"} or not isinstance(payload.get("issues"), list) or len(payload["issues"]) > 12:
        raise PresentationReviewError("semantic_review_schema_invalid")
    catalog = review_input.target_catalog()
    result: list[ReviewIssueCandidate] = []
    for raw in payload["issues"]:
        fields = {"target_type", "target_ref", "issue_type", "severity", "message", "revision_instruction"}
        if not isinstance(raw, Mapping) or set(raw) != fields:
            raise PresentationReviewError("semantic_review_issue_schema_invalid")
        key = (str(raw["target_type"]), str(raw["target_ref"]))
        target = catalog.get(key)
        if target is None:
            raise PresentationReviewError("semantic_review_target_invalid")
        issue_type = str(raw["issue_type"])
        severity = str(raw["severity"])
        if issue_type not in SEMANTIC_ISSUE_TYPES or severity not in {"major", "minor"}:
            raise PresentationReviewError("semantic_review_issue_invalid")
        if (
            target.target_type == PresentationTargetType.REPORT
            and issue_type not in {"organization", "synthesis", "repetition"}
        ):
            raise PresentationReviewError("whole_report_revision_not_authorized")
        message = str(raw["message"]).strip()[:500]
        instruction = str(raw["revision_instruction"]).strip()[:300]
        if not message or not instruction:
            raise PresentationReviewError("semantic_review_issue_invalid")
        result.append(ReviewIssueCandidate(
            issue_type="structure_issue", severity=severity, message=message,
            report_section_id=target.section_id, claim_refs=target.claim_refs,
            report_revision=review_input.revision_number, suggested_action=instruction,
            metadata={
                "contract_version": EDITORIAL_CONTRACT_VERSION,
                "semantic_issue_type": issue_type,
                "target_type": target.target_type.value,
                "target_ref": target.target_ref,
            },
        ))
    return tuple(result)


def _add_paragraph_targets(paragraph, targets, paragraph_claim_refs, seen_paragraphs, seen_units, section_id):
    if paragraph.paragraph_id in seen_paragraphs:
        raise PresentationReviewError("duplicate_paragraph_ref")
    seen_paragraphs.add(paragraph.paragraph_id)
    paragraph_claim_refs[paragraph.paragraph_id] = paragraph.claim_refs
    targets.append(PresentationReviewTarget(
        PresentationTargetType.PARAGRAPH, paragraph.paragraph_id, paragraph.claim_refs, section_id,
    ))
    for unit_id in paragraph.unit_ids:
        if unit_id in seen_units:
            raise PresentationReviewError("duplicate_editorial_unit_ref")
        seen_units.add(unit_id)
        targets.append(PresentationReviewTarget(
            PresentationTargetType.EDITORIAL_UNIT, unit_id, paragraph.claim_refs, section_id,
        ))


def _deterministic_issue(
    code, target_ref, claim_refs=(), issue_type="unsupported_claim", rq_id=None,
    target_type="PARAGRAPH",
):
    return ReviewIssueCandidate(
        issue_type=issue_type, severity="major",
        message=f"Deterministic presentation validation failed: {code}",
        claim_refs=tuple(claim_refs), research_question_refs=((rq_id,) if rq_id else ()),
        suggested_action="Correct the presentation using only persisted authority",
        metadata={
            "contract_version": EDITORIAL_CONTRACT_VERSION, "code": code,
            "target_type": target_type, "target_ref": target_ref,
            "deterministic": True,
        },
    )
