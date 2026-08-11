"""P1-08.1 claim-grade Brand A awareness fixture for offline downstream tests."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import (
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)
from domain.research_brief import ResearchBrief

PROJECT_ID = "proj-p1082-claim"
RUN_ID = "run-p1082-claim"
DESIGN_ID = "design-p1082-claim"
EVIDENCE_IDS = ("ev-aided-2024", "ev-aided-2025", "ev-unaided")
SOURCE_IDS = ("src-survey-2024", "src-survey-2025", "src-unaided")
NOW = "2026-08-10T00:00:00+00:00"


def claim_grade_brief() -> ResearchBrief:
    return ResearchBrief(
        title="Brand A Awareness Delta 2024-2025",
        business_question="What changed in Brand A awareness between 2024 and 2025?",
        objectives=("Quantify Brand A aided and unaided awareness change 2024-2025.",),
        geography=("Germany",),
        market="Consumer packaged goods",
        target_entities=("Brand A",),
        timeframe="2024-2025",
        constraints=(),
        deliverables=("Executive summary",),
        language="en",
        context="P1-08.1/P1-08.2 claim-grade controlled fixture",
        known_information=(),
        exclusions=(),
    )


def claim_grade_design(*, design_id: str = DESIGN_ID) -> ResearchDesign:
    expectation = EvidenceExpectation(
        nature=EvidenceNature.MIXED,
        required_aspects=("aided_awareness_trend", "unaided_awareness_trend"),
        geography="Germany",
        timeframe="2024-2025",
        minimum_independent_sources=2,
        requires_quantitative_evidence=True,
    )
    return ResearchDesign(
        id=design_id,
        research_questions=(
            ResearchQuestion(
                id="rq-1",
                question="What changed in Brand A awareness between 2024 and 2025?",
                objective_refs=(
                    "Quantify Brand A aided and unaided awareness change 2024-2025.",
                ),
                priority=1,
                rationale="Primary awareness delta question.",
            ),
        ),
        information_needs=(
            InformationNeed(
                id="in-rq-1",
                research_question_id="rq-1",
                description=(
                    "Independent survey observations for Brand A aided and unaided "
                    "awareness in 2024 and 2025."
                ),
                priority=1,
                preferred_source_types=("survey reports", "brand trackers"),
                timeframe="2024-2025",
                geography="Germany",
                evidence_expectation=expectation,
            ),
        ),
        source_strategy=("survey reports", "brand trackers"),
        analysis_plan=("awareness benchmarking", "year-over-year delta synthesis"),
        deliverable_plan=("executive summary", "awareness findings"),
        assumptions=("Survey methodologies are comparable across years.",),
        limitations=("No primary fieldwork; secondary survey reports only.",),
        language="en",
    )


def claim_grade_evidence(
    *,
    project_id: str = PROJECT_ID,
    workflow_run_id: str = RUN_ID,
    research_design_id: str = DESIGN_ID,
) -> tuple[Evidence, ...]:
    rows = (
        (
            EVIDENCE_IDS[0],
            SOURCE_IDS[0],
            "In the 2024 survey, aided awareness of Brand A was 41%.",
        ),
        (
            EVIDENCE_IDS[1],
            SOURCE_IDS[1],
            "In the 2025 survey, aided awareness of Brand A was 48%.",
        ),
        (
            EVIDENCE_IDS[2],
            SOURCE_IDS[2],
            "Unaided awareness increased from 18% in 2024 to 23% in 2025.",
        ),
    )
    return tuple(
        Evidence(
            id=eid,
            project_id=project_id,
            source_id=sid,
            source_content_checksum=f"checksum-{eid}",
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            statement=statement,
            source_excerpt=statement,
            created_at=NOW,
            evidence_type=EvidenceType.DIRECT_EXCERPT,
            research_question_refs=("rq-1",),
            information_need_refs=("in-rq-1",),
            extraction_method="claim_grade_fixture",
            confidence=0.9,
            deduplication_key=eid,
            metadata={"claim_grade": True},
        )
        for eid, sid, statement in rows
    )
