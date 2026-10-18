from types import SimpleNamespace
import unittest

from application.analysis.exceptions import InvalidAnalysisProvenanceError
from application.analysis.provenance_validation import (
    validate_finding_candidate,
    validate_insight_candidate,
)
from application.ports.analysis_ports import FindingCandidate, InsightCandidate
from application.ports.report_ports import ReportSectionCandidate
from application.report.exceptions import InvalidReportProvenanceError, ReportError
from application.report.provenance_validation import validate_section_candidate
from application.report.substantive_coverage import validate_two_dimensional_coverage
from application.research_quality.analysis_coverage import (
    COVERAGE_SNAPSHOT_VERSION,
    build_analysis_coverage_snapshot,
)
from application.research_quality.readiness_aggregation import (
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.research_readiness_gate import ResearchReadinessGate
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.reports.report_section import ReportSection
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.sufficiency_status import SufficiencyStatus


def _design():
    return ResearchDesign(
        id="design",
        research_questions=(ResearchQuestion("rq1", "Question one"), ResearchQuestion("rq2", "Question two")),
        information_needs=(
            InformationNeed("in1", "rq1", "Need one", evidence_expectation=EvidenceExpectation(EvidenceNature.MIXED, required_aspects=("a1", "a2"))),
            InformationNeed("in2", "rq2", "Need two", evidence_expectation=EvidenceExpectation(EvidenceNature.MIXED, required_aspects=("b1",))),
        ),
    )


def _need(need_id, status, *, supported=(), missing=(), current=True, gaps=(), contradictions=(), count=1):
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id="rq1" if need_id == "in1" else "rq2",
        status=status,
        evidence_count=count,
        independent_source_count=min(1, count),
        supported_aspects=supported,
        missing_aspects=missing,
        required_aspect_ids=("a1", "a2") if need_id == "in1" else ("b1",),
        assessment_current=current,
        gap_types=gaps,
        contradictions=contradictions,
    )


def _result(first, second):
    return build_research_readiness_result((
        build_research_readiness_assessment(research_question_id="rq1", need_assessments=(first,)),
        build_research_readiness_assessment(research_question_id="rq2", need_assessments=(second,)),
    ))


def _partial_result():
    return _result(
        _need("in1", SufficiencyStatus.PARTIAL, supported=("a1",), missing=("a2",)),
        _need("in2", SufficiencyStatus.MISSING, count=0, gaps=(GapType.NO_EVIDENCE,)),
    )


def _evidence(need_id="in1"):
    return Evidence(
        id=f"e-{need_id}", project_id="p", source_id="s", source_content_checksum="c",
        workflow_run_id="run", research_design_id="design", statement="Supported statement",
        source_excerpt="Supported excerpt", created_at="2026-01-01T00:00:00Z",
        research_question_refs=("rq1" if need_id == "in1" else "rq2",),
        information_need_refs=(need_id,), metadata={},
    )


def _finding(*, need_id="in1"):
    return Finding(
        id=f"f-{need_id}", project_id="p", workflow_run_id="run", research_design_id="design",
        statement="Finding", rationale="Rationale", evidence_refs=(f"e-{need_id}",),
        created_at="2026-01-01T00:00:00Z", research_question_refs=("rq1" if need_id == "in1" else "rq2",),
        information_need_refs=(need_id,),
    )


class _Task:
    def __init__(self, definition_id):
        self.definition_id, self.is_terminal, self.skipped = definition_id, False, False
    def skip(self):
        self.skipped, self.is_terminal = True, True


def test_partial_readiness_allows_analysis_orchestration():
    tasks = [_Task("task-analyze"), _Task("task-write-report"), _Task("task-review-report")]
    ResearchReadinessGate().apply_analysis_gate(SimpleNamespace(workflow_run=SimpleNamespace(tasks=tasks)), _partial_result())
    assert not any(task.skipped for task in tasks)


def test_no_analysis_scope_skips_downstream():
    result = _result(_need("in1", SufficiencyStatus.MISSING, count=0, gaps=(GapType.NO_EVIDENCE,)), _need("in2", SufficiencyStatus.MISSING, count=0, gaps=(GapType.NO_EVIDENCE,)))
    tasks = [_Task("task-analyze"), _Task("task-write-report")]
    ResearchReadinessGate().apply_analysis_gate(SimpleNamespace(workflow_run=SimpleNamespace(tasks=tasks)), result)
    assert all(task.skipped for task in tasks)


def test_snapshot_is_deterministic_and_explicit():
    payload = build_analysis_coverage_snapshot(_partial_result()).to_dict()
    assert payload["coverage_snapshot_version"] == COVERAGE_SNAPSHOT_VERSION
    assert payload["report_scope"] == "limited"
    assert payload["covered_information_need_ids"] == ["in1"]
    assert payload["partial_information_need_ids"] == ["in1"]
    assert payload["missing_information_need_ids"] == ["in2"]
    assert payload["covered_required_aspect_refs"] == {"in1": ["a1"]}
    assert payload["missing_required_aspect_refs"] == {"in1": ["a2"]}


def test_complete_snapshot_preserves_strict_semantics():
    result = _result(_need("in1", SufficiencyStatus.SUFFICIENT, supported=("a1", "a2")), _need("in2", SufficiencyStatus.SUFFICIENT, supported=("b1",)))
    snapshot = build_analysis_coverage_snapshot(result)
    assert snapshot.complete_design_ready and snapshot.analysis_ready
    assert snapshot.report_scope == "complete"


def test_finding_is_limited_to_eligible_evidence_scope():
    candidate = FindingCandidate("Statement", "Why", ("e-in1",), information_need_refs=("in1",), metadata={"required_aspect_refs": ["a1"]})
    validated = validate_finding_candidate(candidate, evidence_by_id={"e-in1": _evidence()}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), eligible_information_need_ids=("in1",), supported_aspects_by_information_need={"in1": ("a1",)})
    assert validated.information_need_refs == ("in1",)
    assert validated.research_question_refs == ("rq1",)


def test_finding_missing_ineligible_need_is_rejected():
    candidate = FindingCandidate("Statement", "Why", ("e-in2",), information_need_refs=("in2",))
    with unittest.TestCase().assertRaises(InvalidAnalysisProvenanceError):
        validate_finding_candidate(candidate, evidence_by_id={"e-in2": _evidence("in2")}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), eligible_information_need_ids=("in1",), supported_aspects_by_information_need={"in1": ("a1",)})


def test_finding_unsupported_aspect_is_rejected():
    candidate = FindingCandidate("Statement", "Why", ("e-in1",), information_need_refs=("in1",), metadata={"required_aspect_refs": ["a2"]})
    with unittest.TestCase().assertRaisesRegex(
        InvalidAnalysisProvenanceError,
        "unsupported required aspect",
    ):
        validate_finding_candidate(candidate, evidence_by_id={"e-in1": _evidence()}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), eligible_information_need_ids=("in1",), supported_aspects_by_information_need={"in1": ("a1",)})


def test_existing_cross_run_finding_provenance_remains_enforced():
    with unittest.TestCase().assertRaises(InvalidAnalysisProvenanceError):
        validate_finding_candidate(FindingCandidate("x", "y", ("e-in1",)), evidence_by_id={"e-in1": _evidence()}, project_id="p", workflow_run_id="other", research_design_id="design", design=_design())


def test_insight_over_valid_finding_is_allowed():
    finding = _finding()
    validated = validate_insight_candidate(InsightCandidate("Insight", "Implication", (finding.id,)), findings_by_id={finding.id: finding}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), eligible_information_need_ids=("in1",))
    assert validated.research_question_refs == ("rq1",)


def test_insight_unsupported_scope_is_rejected():
    finding = _finding(need_id="in2")
    with unittest.TestCase().assertRaises(InvalidAnalysisProvenanceError):
        validate_insight_candidate(InsightCandidate("Insight", "Implication", (finding.id,)), findings_by_id={finding.id: finding}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), eligible_information_need_ids=("in1",))


def test_insight_explicit_unsupported_rq_is_rejected():
    finding = _finding()
    with unittest.TestCase().assertRaises(InvalidAnalysisProvenanceError):
        validate_insight_candidate(InsightCandidate("Insight", "Implication", (finding.id,), research_question_refs=("rq2",)), findings_by_id={finding.id: finding}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), eligible_information_need_ids=("in1",))


def test_zero_insights_is_a_valid_bounded_input_state():
    snapshot = build_analysis_coverage_snapshot(_partial_result())
    assert snapshot.analysis_ready and snapshot.eligible_information_need_ids == ("in1",)


def _section_candidate(**overrides):
    values = dict(title="Section", content="Supported content", research_question_refs=("rq1",), finding_refs=("f-in1",), insight_refs=(), evidence_refs=("e-in1",), metadata={})
    values.update(overrides)
    return ReportSectionCandidate(**values)


def test_limited_report_section_supported_scope_is_allowed():
    finding, evidence = _finding(), _evidence()
    validated = validate_section_candidate(_section_candidate(), findings_by_id={finding.id: finding}, insights_by_id={}, evidence_by_id={evidence.id: evidence}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), allowed_research_question_ids=("rq1",))
    assert validated.research_question_refs == ("rq1",)


def test_limited_report_unsupported_rq_is_rejected():
    finding, evidence = _finding(), _evidence()
    with unittest.TestCase().assertRaises(InvalidReportProvenanceError):
        validate_section_candidate(_section_candidate(research_question_refs=("rq2",)), findings_by_id={finding.id: finding}, insights_by_id={}, evidence_by_id={evidence.id: evidence}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), allowed_research_question_ids=("rq1",))


def test_limited_report_complete_claim_is_rejected():
    finding, evidence = _finding(), _evidence()
    with unittest.TestCase().assertRaisesRegex(
        InvalidReportProvenanceError,
        "complete research",
    ):
        validate_section_candidate(_section_candidate(metadata={"report_scope": "complete"}), findings_by_id={finding.id: finding}, insights_by_id={}, evidence_by_id={evidence.id: evidence}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), allowed_research_question_ids=("rq1",))


def test_report_provenance_remains_enforced():
    with unittest.TestCase().assertRaises(InvalidReportProvenanceError):
        validate_section_candidate(_section_candidate(finding_refs=("unknown",)), findings_by_id={}, insights_by_id={}, evidence_by_id={"e-in1": _evidence()}, project_id="p", workflow_run_id="run", research_design_id="design", design=_design(), allowed_research_question_ids=("rq1",))


def test_limited_coverage_requires_only_supported_rq():
    finding = _finding()
    section = ReportSection(id="s1", title="rq1", content="Supported", research_question_refs=("rq1",), finding_refs=(finding.id,), evidence_refs=("e-in1",))
    assert validate_two_dimensional_coverage((section,), findings=(finding,), insights=(), design=_design(), required_research_question_ids=("rq1",)) == ()


def test_limited_coverage_requires_every_finding_backed_rq():
    first = _finding()
    second = _finding(need_id="in2")
    section = ReportSection(id="s1", title="rq1", content="Supported", research_question_refs=("rq1",), finding_refs=(first.id,), evidence_refs=("e-in1",))
    errors = validate_two_dimensional_coverage(
        (section,),
        findings=(first, second),
        insights=(),
        design=_design(),
        required_research_question_ids=("rq1", "rq2"),
    )
    assert "substantive_coverage_missing:rq2" in errors


def test_complete_coverage_still_requires_all_rqs():
    finding = _finding()
    section = ReportSection(id="s1", title="rq1", content="Supported", research_question_refs=("rq1",), finding_refs=(finding.id,), evidence_refs=("e-in1",))
    errors = validate_two_dimensional_coverage((section,), findings=(finding,), insights=(), design=_design())
    assert "structural_coverage_missing:rq2" in errors


def test_blocked_and_contradictory_needs_are_not_eligible():
    result = _result(_need("in1", SufficiencyStatus.PARTIAL, supported=("a1",), contradictions=("conflict",)), _need("in2", SufficiencyStatus.BLOCKED, gaps=(GapType.UNRESOLVABLE,)))
    assert build_analysis_coverage_snapshot(result).eligible_information_need_ids == ()


def test_ready_for_analysis_remains_strict_and_distinct():
    result = _partial_result()
    assert result.ready_for_analysis is False
    assert result.complete_design_ready is False
    assert result.analysis_ready is True


def test_zero_insights_with_valid_finding_produces_limited_report():
    from tests.application.report.test_report_coverage import _context, _deterministic_service
    from application.research_quality.research_readiness_service import SHARED_STATE_KEY

    design = ResearchDesign(
        id="design-coverage",
        research_questions=(ResearchQuestion("rq1", "Question one"), ResearchQuestion("rq2", "Question two")),
        information_needs=(InformationNeed("in1", "rq1", "Need one"), InformationNeed("in2", "rq2", "Need two")),
        limitations=("Desk research only",),
        language="en",
    )
    service = _deterministic_service()
    context = _context(design=design)
    evidence = Evidence(id="e", project_id=context.project.id, source_id="s", source_content_checksum="c", workflow_run_id=context.workflow_run.id, research_design_id=design.id, statement="Supported", source_excerpt="Supported", created_at="2026-01-01T00:00:00Z", research_question_refs=("rq1",), information_need_refs=("in1",), deduplication_key="e")
    from tests.helpers.citation_fixtures import sources_for
    sources_for((evidence,), service._source_repository)
    service._evidence_repository.create(evidence)
    service._finding_repository.create(Finding(id="f", project_id=context.project.id, workflow_run_id=context.workflow_run.id, research_design_id=design.id, statement="Finding", rationale="Rationale", evidence_refs=("e",), created_at="2026-01-01T00:00:00Z", research_question_refs=("rq1",), information_need_refs=("in1",), deduplication_key="f"))
    context.write_shared(SHARED_STATE_KEY, _partial_result().to_dict())
    summary = service.write_for_context(context)
    report = service._report_repository.get_by_id(summary.report_id)
    assert report is not None
    assert report.insight_refs == ()
    assert report.metadata["report_scope"] == "limited"
    assert report.metadata["covered_information_need_ids"] == ["in1"]
    assert "in2" in report.metadata["missing_information_need_ids"]


def test_limited_report_uses_validated_finding_rqs_and_retains_no_finding_gap():
    from tests.application.report.test_report_coverage import _context, _deterministic_service
    from application.research_quality.research_readiness_service import SHARED_STATE_KEY
    from tests.helpers.citation_fixtures import sources_for

    question_ids = ("rq1", "rq3", "rq4", "rq5")
    needs = tuple(
        InformationNeed(
            f"in-{rq_id}",
            rq_id,
            f"Need for {rq_id}",
            evidence_expectation=EvidenceExpectation(
                EvidenceNature.MIXED,
                required_aspects=(f"aspect-{rq_id}",),
            ),
        )
        for rq_id in question_ids
    )
    design = ResearchDesign(
        id="design-coverage",
        research_questions=tuple(
            ResearchQuestion(rq_id, f"Question {rq_id}") for rq_id in question_ids
        ),
        information_needs=needs,
        limitations=("Desk research only",),
        language="en",
    )
    assessments = tuple(
        build_research_readiness_assessment(
            research_question_id=rq_id,
            need_assessments=(
                InformationNeedAssessment(
                    information_need_id=f"in-{rq_id}",
                    research_question_id=rq_id,
                    status=SufficiencyStatus.PARTIAL,
                    evidence_count=1,
                    independent_source_count=1,
                    supported_aspects=(f"aspect-{rq_id}",),
                    required_aspect_ids=(f"aspect-{rq_id}",),
                ),
            ),
        )
        for rq_id in question_ids
    )
    readiness = build_research_readiness_result(assessments)
    assert readiness.analysis_eligible_information_need_ids == tuple(
        sorted(f"in-{rq_id}" for rq_id in question_ids)
    )

    service = _deterministic_service()
    context = _context(design=design)
    persisted_evidence = []
    for rq_id in ("rq1", "rq4", "rq5"):
        need_id = f"in-{rq_id}"
        evidence = Evidence(
            id=f"e-{rq_id}",
            project_id=context.project.id,
            source_id=f"s-{rq_id}",
            source_content_checksum="pending",
            workflow_run_id=context.workflow_run.id,
            research_design_id=design.id,
            statement=f"Supported evidence for {rq_id}",
            source_excerpt=f"Supported evidence for {rq_id}",
            created_at="2026-01-01T00:00:00Z",
            research_question_refs=(rq_id,),
            information_need_refs=(need_id,),
            deduplication_key=f"e-{rq_id}",
        )
        persisted_evidence.append(evidence)
        service._evidence_repository.create(evidence)
        service._finding_repository.create(
            Finding(
                id=f"f-{rq_id}",
                project_id=context.project.id,
                workflow_run_id=context.workflow_run.id,
                research_design_id=design.id,
                statement=f"Validated finding for {rq_id}",
                rationale="Supported rationale",
                evidence_refs=(evidence.id,),
                created_at="2026-01-01T00:00:00Z",
                research_question_refs=(rq_id,),
                information_need_refs=(need_id,),
                deduplication_key=f"f-{rq_id}",
            ),
        )
    sources_for(tuple(persisted_evidence), service._source_repository)
    context.write_shared(SHARED_STATE_KEY, readiness.to_dict())

    summary = service.write_for_context(context)
    report = service._report_repository.get_by_id(summary.report_id)
    assert report is not None
    assert report.metadata["report_scope"] == "limited"
    assert report.metadata["analysis_eligible_information_need_ids"] == [
        "in-rq1", "in-rq3", "in-rq4", "in-rq5",
    ]
    reported_rq_ids = {
        ref
        for section in report.sections
        if section.metadata.get("section_kind") != "limitations"
        for ref in section.research_question_refs
    }
    assert reported_rq_ids == {
        "rq1", "rq4", "rq5",
    }, reported_rq_ids
    assert any("ResearchQuestions without validated Findings: rq3." == item for item in report.limitations)
    assert any("InformationNeeds without validated Findings" in item for item in report.limitations)
    assert all("complete research" not in item.lower() for item in report.limitations)


def test_limited_report_with_zero_validated_findings_remains_blocked():
    from tests.application.report.test_report_coverage import _context, _deterministic_service
    from application.research_quality.research_readiness_service import SHARED_STATE_KEY

    service = _deterministic_service()
    context = _context(design=_design())
    context.write_shared(SHARED_STATE_KEY, _partial_result().to_dict())
    with unittest.TestCase().assertRaisesRegex(
        ReportError,
        "No run-scoped findings available",
    ):
        service.write_for_context(context)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite
