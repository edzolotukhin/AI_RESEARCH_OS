from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_research_design_repository import QuantitativeResearchDesignRepository
from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.research_design_authority import (
    AnalyticalRequirement, ApprovedResearchDesignProjection,
    DatasetOnlyResearchAuthority, DeliverableRequirement, Hypothesis,
    MethodologyIntent, ObjectiveCoverageAuthority, ObjectiveCoverageStatus,
    QuantitativeResearchDesignApproval, QuantitativeResearchDesignVersion,
    QuantitativeResearchQuestion, QuantitativeStudyBriefApproval,
    QuantitativeStudyBriefVersion,
    QuantitativeStudyMode, QuantitativeTraceabilityManifest,
    ResearchDesignApprovalDecision, ResearchDesignLifecycle, StudyWeightingMode,
    ResearchObjective, TargetPopulation,
)

QUANTITATIVE = "QUANTITATIVE"

_WEIGHTED_INTENTS = frozenset({"WEIGHTED", "TARGET_MARGINS", "PRECOMPUTED_WEIGHTSET"})


def resolve_study_weighting_mode(value: QuantitativeResearchDesignVersion) -> StudyWeightingMode:
    """Resolve the closed execution mode from exact approved QZ intent."""
    intent = value.methodology_intent.weighting_intent.strip().upper()
    if intent == StudyWeightingMode.UNWEIGHTED.value:
        return StudyWeightingMode.UNWEIGHTED
    if intent in _WEIGHTED_INTENTS:
        return StudyWeightingMode.WEIGHTED
    return StudyWeightingMode.UNRESOLVED
DATASET_ONLY_LIMITATION = "Objective coverage cannot be assessed because no approved Quantitative Research Design is present."


class QuantitativeResearchDesignError(ValueError):
    pass


def _text(value: str) -> str:
    result = " ".join(str(value).split())
    if not result or len(result) > 4000:
        raise QuantitativeResearchDesignError("Research Design text is empty or oversized")
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", result) or re.search(r"(?:\+?\d[\s().-]*){7,}", result):
        raise QuantitativeResearchDesignError("direct PII is forbidden in Research Design authority")
    return result


def _texts(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({_text(item) for item in values}))


def _unique_ids(values, attribute: str, label: str) -> None:
    ids = [getattr(item, attribute) for item in values]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise QuantitativeResearchDesignError(f"duplicate or empty {label} ID")


def _brief_payload(value: QuantitativeStudyBriefVersion) -> dict:
    return {
        "contract": "QZ_BRIEF_V1", "brief_id": value.brief_id,
        "project_id": value.project_id, "methodology": value.methodology,
        "title": value.title, "business_context": value.business_context,
        "business_problem": value.business_problem, "decision_context": value.decision_context,
        "research_purpose": value.research_purpose,
        "intended_audience": list(value.intended_audience),
        "target_deliverables": list(value.target_deliverables),
        "constraints": list(value.constraints), "provenance": value.provenance,
    }


def _design_payload(value: QuantitativeResearchDesignVersion) -> dict:
    return {
        "contract": "QZ_DESIGN_V1", "design_id": value.design_id,
        "project_id": value.project_id, "methodology": value.methodology,
        "source_brief_version_id": value.source_brief_version_id,
        "source_brief_fingerprint": value.source_brief_fingerprint,
        "objectives": [{"id": i.objective_id, "statement": i.statement, "priority": i.priority.value} for i in value.objectives],
        "questions": [{"id": i.question_id, "statement": i.statement, "objectives": list(i.objective_ids), "intent": i.analytical_intent, "priority": i.priority.value} for i in value.research_questions],
        "hypotheses": [{"id": i.hypothesis_id, "statement": i.statement, "objectives": list(i.objective_ids), "questions": list(i.research_question_ids), "direction": i.direction.value, "intent": i.validation_intent} for i in value.hypotheses],
        "target_population": {"geography": list(value.target_population.geography), "eligibility": list(value.target_population.eligibility), "exclusions": list(value.target_population.exclusions), "constraints": list(value.target_population.population_constraints)},
        "methodology_intent": {"methodology": value.methodology_intent.methodology, "collection_mode": value.methodology_intent.collection_mode, "sample_intent": value.methodology_intent.sample_intent, "weighting_intent": value.methodology_intent.weighting_intent, "confidence_significance_expectation": value.methodology_intent.confidence_significance_expectation},
        "analytical_requirements": [{"id": i.requirement_id, "type": i.requirement_type, "statement": i.statement, "objectives": list(i.objective_ids), "questions": list(i.research_question_ids), "obligation": i.obligation.value} for i in value.analytical_requirements],
        "deliverable_requirements": [{"id": i.requirement_id, "type": i.deliverable_type, "audience": i.audience, "language": i.language, "obligation": i.obligation.value} for i in value.deliverable_requirements],
        "assumptions": list(value.assumptions), "limitations": list(value.limitations),
    }


class QuantitativeResearchDesignService:
    def __init__(self, *, repository: QuantitativeResearchDesignRepository, digest_provider: DeterministicDigestProvider) -> None:
        self._repository = repository
        self._digest = digest_provider

    def create_brief(self, *, brief_id: str, version_id: str, project_id: str, run_id: str,
                     title: str, business_context: str, business_problem: str,
                     decision_context: str, research_purpose: str,
                     intended_audience: tuple[str, ...], target_deliverables: tuple[str, ...],
                     constraints: tuple[str, ...], provenance: str, created_at: str, created_by: str) -> QuantitativeStudyBriefVersion:
        value = QuantitativeStudyBriefVersion(
            brief_id, version_id, 1, project_id, QUANTITATIVE, _text(title),
            _text(business_context), _text(business_problem), _text(decision_context),
            _text(research_purpose), _texts(intended_audience), _texts(target_deliverables),
            _texts(constraints), _text(provenance), None, created_at, created_by,
            ResearchDesignLifecycle.DRAFT, "",
        )
        value = replace(value, fingerprint=canonical_digest(_brief_payload(value), digest_provider=self._digest))
        self._repository.save_brief(value, run_id=run_id)
        return value

    def revise_brief(self, current_version_id: str, *, project_id: str, run_id: str,
                     version_id: str, created_at: str, created_by: str, **changes) -> QuantitativeStudyBriefVersion:
        current = self._require_brief(current_version_id, project_id)
        allowed = {"title", "business_context", "business_problem", "decision_context", "research_purpose", "intended_audience", "target_deliverables", "constraints", "provenance"}
        if set(changes) - allowed: raise QuantitativeResearchDesignError("unsupported Brief revision field")
        normalized = {key: (_texts(value) if key in {"intended_audience", "target_deliverables", "constraints"} else _text(value)) for key, value in changes.items()}
        value = replace(current, version_id=version_id, version_sequence=current.version_sequence + 1,
                        parent_version_id=current.version_id, created_at=created_at, created_by=created_by,
                        lifecycle_status=ResearchDesignLifecycle.DRAFT, fingerprint="", approval_reference=None, **normalized)
        value = replace(value, fingerprint=canonical_digest(_brief_payload(value), digest_provider=self._digest))
        self._repository.save_brief(value, run_id=run_id)
        return value

    def submit_brief_for_review(self, version_id: str, *, project_id: str, run_id: str,
                                new_version_id: str, actor_id: str, changed_at: str) -> QuantitativeStudyBriefVersion:
        current = self._require_brief(version_id, project_id)
        if current.lifecycle_status is not ResearchDesignLifecycle.DRAFT:
            raise QuantitativeResearchDesignError("only a Draft Brief can be submitted for review")
        value = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1,
                        parent_version_id=current.version_id, created_at=changed_at, created_by=actor_id,
                        lifecycle_status=ResearchDesignLifecycle.IN_REVIEW, approval_reference=None)
        self._repository.save_brief(value, run_id=run_id)
        return value

    def approve_brief(self, version_id: str, *, project_id: str, run_id: str,
                      new_version_id: str, approval_id: str, expected_fingerprint: str,
                      actor_id: str, decided_at: str, rationale: str) -> QuantitativeStudyBriefVersion:
        return self._decide_brief(version_id, project_id=project_id, run_id=run_id,
            new_version_id=new_version_id, approval_id=approval_id,
            expected_fingerprint=expected_fingerprint, actor_id=actor_id,
            decided_at=decided_at, rationale=rationale,
            decision=ResearchDesignApprovalDecision.APPROVED)

    def reject_brief(self, version_id: str, *, project_id: str, run_id: str,
                     new_version_id: str, approval_id: str, expected_fingerprint: str,
                     actor_id: str, decided_at: str, rationale: str) -> QuantitativeStudyBriefVersion:
        return self._decide_brief(version_id, project_id=project_id, run_id=run_id,
            new_version_id=new_version_id, approval_id=approval_id,
            expected_fingerprint=expected_fingerprint, actor_id=actor_id,
            decided_at=decided_at, rationale=rationale,
            decision=ResearchDesignApprovalDecision.REJECTED)

    def resolve_approved_brief(self, version_id: str, *, project_id: str) -> QuantitativeStudyBriefVersion:
        value = self._require_brief(version_id, project_id)
        approval = self._repository.get_brief_approval(value.approval_reference or "", project_id=project_id)
        if (value.lifecycle_status is not ResearchDesignLifecycle.APPROVED or approval is None
                or approval.decision is not ResearchDesignApprovalDecision.APPROVED
                or approval.brief_version_id != value.version_id
                or approval.brief_fingerprint != value.fingerprint):
            raise QuantitativeResearchDesignError("Study Brief approval is missing, rejected, or stale")
        return value

    def resolve_current_approved_brief(self, *, project_id: str, run_id: str) -> QuantitativeStudyBriefVersion:
        briefs = self._repository.list_briefs(project_id=project_id, run_id=run_id)
        parent_ids = {item.parent_version_id for item in briefs if item.parent_version_id}
        heads = tuple(item for item in briefs if item.version_id not in parent_ids)
        if len(heads) != 1:
            raise QuantitativeResearchDesignError("no unique current Quantitative Study Brief")
        return self.resolve_approved_brief(heads[0].version_id, project_id=project_id)

    def create_design(self, *, design_id: str, version_id: str, project_id: str, run_id: str,
                      source_brief_version_id: str, source_brief_fingerprint: str,
                      objectives: tuple[ResearchObjective, ...], research_questions: tuple[QuantitativeResearchQuestion, ...],
                      hypotheses: tuple[Hypothesis, ...], target_population: TargetPopulation,
                      methodology_intent: MethodologyIntent, analytical_requirements: tuple[AnalyticalRequirement, ...],
                      deliverable_requirements: tuple[DeliverableRequirement, ...], assumptions: tuple[str, ...],
                      limitations: tuple[str, ...], created_at: str, created_by: str) -> QuantitativeResearchDesignVersion:
        brief = self._require_brief(source_brief_version_id, project_id)
        if brief.methodology != QUANTITATIVE or brief.fingerprint != source_brief_fingerprint:
            raise QuantitativeResearchDesignError("Brief version or fingerprint is stale or incompatible")
        value = QuantitativeResearchDesignVersion(
            design_id, version_id, 1, project_id, QUANTITATIVE,
            brief.version_id, brief.fingerprint, objectives, research_questions, hypotheses,
            target_population, methodology_intent, analytical_requirements, deliverable_requirements,
            assumptions, limitations, None, created_at, created_by,
            ResearchDesignLifecycle.DRAFT, None, "",
        )
        value = self._canonical_design(value)
        self._repository.save_design(value, run_id=run_id)
        self._repository.save_manifest(self._manifest(value), run_id=run_id)
        return value

    def revise_design(self, current_version_id: str, *, project_id: str, run_id: str,
                      version_id: str, created_at: str, created_by: str, **changes) -> QuantitativeResearchDesignVersion:
        current = self._require_design(current_version_id, project_id)
        allowed = {"objectives", "research_questions", "hypotheses", "target_population", "methodology_intent", "analytical_requirements", "deliverable_requirements", "assumptions", "limitations"}
        if set(changes) - allowed: raise QuantitativeResearchDesignError("unsupported Research Design revision field")
        value = replace(current, version_id=version_id, version_sequence=current.version_sequence + 1,
                        parent_version_id=current.version_id, created_at=created_at, created_by=created_by,
                        lifecycle_status=ResearchDesignLifecycle.DRAFT, approval_reference=None, fingerprint="", **changes)
        value = self._canonical_design(value)
        self._repository.save_design(value, run_id=run_id)
        self._repository.save_manifest(self._manifest(value), run_id=run_id)
        return value

    def submit_for_review(self, version_id: str, *, project_id: str, run_id: str,
                          new_version_id: str, actor_id: str, changed_at: str) -> QuantitativeResearchDesignVersion:
        return self._transition(version_id, project_id=project_id, run_id=run_id, new_version_id=new_version_id, actor_id=actor_id, changed_at=changed_at, status=ResearchDesignLifecycle.IN_REVIEW)

    def approve(self, version_id: str, *, project_id: str, run_id: str, new_version_id: str,
                approval_id: str, expected_fingerprint: str, actor_id: str, decided_at: str, rationale: str) -> QuantitativeResearchDesignVersion:
        current = self._require_design(version_id, project_id)
        if current.lifecycle_status is not ResearchDesignLifecycle.IN_REVIEW:
            raise QuantitativeResearchDesignError("only an in-review Design can be approved")
        if current.fingerprint != expected_fingerprint:
            raise QuantitativeResearchDesignError("approval fingerprint is stale")
        source_brief = self.resolve_current_approved_brief(project_id=project_id, run_id=run_id)
        if (source_brief.version_id, source_brief.fingerprint) != (current.source_brief_version_id, current.source_brief_fingerprint):
            raise QuantitativeResearchDesignError("Design source Brief is not current approved authority")
        value = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1,
                        parent_version_id=current.version_id, created_at=decided_at, created_by=actor_id,
                        lifecycle_status=ResearchDesignLifecycle.APPROVED, approval_reference=approval_id)
        approval_payload = {"approval_id": approval_id, "project_id": project_id, "methodology": QUANTITATIVE, "design_version_id": new_version_id, "design_fingerprint": value.fingerprint, "actor_id": actor_id, "decided_at": decided_at, "decision": "APPROVED", "rationale": _text(rationale)}
        approval = QuantitativeResearchDesignApproval(approval_id, project_id, QUANTITATIVE, new_version_id, value.fingerprint, actor_id, decided_at, ResearchDesignApprovalDecision.APPROVED, approval_payload["rationale"], canonical_digest(approval_payload, digest_provider=self._digest))
        self._repository.save_design(value, run_id=run_id)
        self._repository.save_manifest(self._manifest(value), run_id=run_id)
        self._repository.save_approval(approval, run_id=run_id)
        return value

    def reject(self, version_id: str, *, project_id: str, run_id: str, new_version_id: str,
               approval_id: str, expected_fingerprint: str, actor_id: str, decided_at: str, rationale: str) -> QuantitativeResearchDesignVersion:
        current = self._require_design(version_id, project_id)
        if current.lifecycle_status is not ResearchDesignLifecycle.IN_REVIEW: raise QuantitativeResearchDesignError("only an in-review Design can be rejected")
        if current.fingerprint != expected_fingerprint:
            raise QuantitativeResearchDesignError("approval fingerprint is stale")
        value = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1, parent_version_id=current.version_id, created_at=decided_at, created_by=actor_id, lifecycle_status=ResearchDesignLifecycle.REJECTED, approval_reference=approval_id)
        payload = {"approval_id": approval_id, "project_id": project_id, "methodology": QUANTITATIVE, "design_version_id": new_version_id, "design_fingerprint": value.fingerprint, "actor_id": actor_id, "decided_at": decided_at, "decision": "REJECTED", "rationale": _text(rationale)}
        approval = QuantitativeResearchDesignApproval(approval_id, project_id, QUANTITATIVE, new_version_id, value.fingerprint, actor_id, decided_at, ResearchDesignApprovalDecision.REJECTED, payload["rationale"], canonical_digest(payload, digest_provider=self._digest))
        self._repository.save_design(value, run_id=run_id); self._repository.save_manifest(self._manifest(value), run_id=run_id); self._repository.save_approval(approval, run_id=run_id)
        return value

    def supersede(self, version_id: str, *, project_id: str, run_id: str, new_version_id: str, actor_id: str, changed_at: str) -> QuantitativeResearchDesignVersion:
        current = self._require_design(version_id, project_id)
        if current.lifecycle_status is not ResearchDesignLifecycle.APPROVED: raise QuantitativeResearchDesignError("only an approved Design can be superseded")
        return self._transition(version_id, project_id=project_id, run_id=run_id, new_version_id=new_version_id, actor_id=actor_id, changed_at=changed_at, status=ResearchDesignLifecycle.SUPERSEDED)

    def resolve_current_approved(self, *, project_id: str, run_id: str) -> QuantitativeResearchDesignVersion:
        source_brief = self.resolve_current_approved_brief(project_id=project_id, run_id=run_id)
        designs = tuple(
            item
            for item in self._repository.list_designs(project_id=project_id, run_id=run_id)
            if (item.source_brief_version_id, item.source_brief_fingerprint)
            == (source_brief.version_id, source_brief.fingerprint)
        )
        if not designs:
            raise QuantitativeResearchDesignError("no current approved Quantitative Research Design")
        current_sequence = max(item.version_sequence for item in designs)
        candidates = tuple(item for item in designs if item.version_sequence == current_sequence)
        if len(candidates) != 1 or candidates[0].lifecycle_status is not ResearchDesignLifecycle.APPROVED:
            raise QuantitativeResearchDesignError("no current approved Quantitative Research Design: authority is ambiguous or not approved")
        value = candidates[0]
        approval = self._repository.get_approval(value.approval_reference or "", project_id=project_id)
        if approval is None or approval.decision is not ResearchDesignApprovalDecision.APPROVED or approval.design_version_id != value.version_id or approval.design_fingerprint != value.fingerprint:
            raise QuantitativeResearchDesignError("Research Design approval is missing, rejected, or stale")
        return value

    def approved_projection(self, *, project_id: str, run_id: str) -> ApprovedResearchDesignProjection:
        value = self.resolve_current_approved(project_id=project_id, run_id=run_id)
        population = value.target_population.geography + value.target_population.eligibility + value.target_population.exclusions + value.target_population.population_constraints
        return ApprovedResearchDesignProjection(value.design_id, value.version_id, value.fingerprint,
            tuple((i.objective_id, i.statement) for i in value.objectives),
            tuple((i.question_id, i.statement) for i in value.research_questions),
            tuple((i.requirement_id, i.requirement_type, i.statement) for i in value.analytical_requirements), population,
            tuple((i.requirement_id, i.deliverable_type, i.language) for i in value.deliverable_requirements), value.limitations)

    def resolve_dataset_only(self, *, authority_id: str, project_id: str, run_id: str) -> DatasetOnlyResearchAuthority:
        payload = {"contract": "QZ_DATASET_ONLY_V1", "authority_id": authority_id, "project_id": project_id, "run_id": run_id, "mode": QuantitativeStudyMode.DATASET_ONLY_EXPLORATORY.value, "coverage": ObjectiveCoverageStatus.NOT_ASSESSED_NO_RESEARCH_DESIGN.value, "limitation": DATASET_ONLY_LIMITATION}
        value = DatasetOnlyResearchAuthority(authority_id, project_id, run_id, QuantitativeStudyMode.DATASET_ONLY_EXPLORATORY, ObjectiveCoverageAuthority.ABSENT, ObjectiveCoverageStatus.NOT_ASSESSED_NO_RESEARCH_DESIGN, DATASET_ONLY_LIMITATION, canonical_digest(payload, digest_provider=self._digest))
        self._repository.save_dataset_only(value)
        return value

    def _decide_brief(self, version_id, *, project_id, run_id, new_version_id, approval_id,
                      expected_fingerprint, actor_id, decided_at, rationale, decision):
        current = self._require_brief(version_id, project_id)
        if current.lifecycle_status is not ResearchDesignLifecycle.IN_REVIEW:
            raise QuantitativeResearchDesignError("only an in-review Brief can be decided")
        if current.fingerprint != expected_fingerprint:
            raise QuantitativeResearchDesignError("Brief decision fingerprint is stale")
        status = ResearchDesignLifecycle.APPROVED if decision is ResearchDesignApprovalDecision.APPROVED else ResearchDesignLifecycle.REJECTED
        value = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1,
                        parent_version_id=current.version_id, created_at=decided_at, created_by=actor_id,
                        lifecycle_status=status, approval_reference=approval_id)
        payload = {"approval_id": approval_id, "project_id": project_id, "methodology": QUANTITATIVE,
                   "brief_version_id": new_version_id, "brief_fingerprint": value.fingerprint,
                   "actor_id": actor_id, "decided_at": decided_at, "decision": decision.value,
                   "rationale": _text(rationale)}
        approval = QuantitativeStudyBriefApproval(approval_id, project_id, QUANTITATIVE,
            new_version_id, value.fingerprint, actor_id, decided_at, decision, payload["rationale"],
            canonical_digest(payload, digest_provider=self._digest))
        self._repository.save_brief(value, run_id=run_id)
        self._repository.save_brief_approval(approval, run_id=run_id)
        return value

    def _transition(self, version_id, *, project_id, run_id, new_version_id, actor_id, changed_at, status):
        current = self._require_design(version_id, project_id)
        value = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1, parent_version_id=current.version_id, created_at=changed_at, created_by=actor_id, lifecycle_status=status, approval_reference=None if status is not ResearchDesignLifecycle.APPROVED else current.approval_reference)
        self._repository.save_design(value, run_id=run_id); self._repository.save_manifest(self._manifest(value), run_id=run_id)
        return value

    def _require_brief(self, version_id, project_id):
        value = self._repository.get_brief(version_id, project_id=project_id)
        if value is None or value.project_id != project_id or value.methodology != QUANTITATIVE: raise QuantitativeResearchDesignError("Quantitative Brief is unavailable for project")
        return value

    def _require_design(self, version_id, project_id):
        value = self._repository.get_design(version_id, project_id=project_id)
        if value is None or value.project_id != project_id or value.methodology != QUANTITATIVE: raise QuantitativeResearchDesignError("Quantitative Research Design is unavailable for project")
        return value

    def _canonical_design(self, value):
        objectives = tuple(sorted((replace(i, statement=_text(i.statement)) for i in value.objectives), key=lambda i: i.objective_id))
        questions = tuple(sorted((replace(i, statement=_text(i.statement), objective_ids=tuple(sorted(i.objective_ids)), analytical_intent=_text(i.analytical_intent)) for i in value.research_questions), key=lambda i: i.question_id))
        hypotheses = tuple(sorted((replace(i, statement=_text(i.statement), objective_ids=tuple(sorted(i.objective_ids)), research_question_ids=tuple(sorted(i.research_question_ids)), validation_intent=_text(i.validation_intent)) for i in value.hypotheses), key=lambda i: i.hypothesis_id))
        requirements = tuple(sorted((replace(i, requirement_type=_text(i.requirement_type), statement=_text(i.statement), objective_ids=tuple(sorted(i.objective_ids)), research_question_ids=tuple(sorted(i.research_question_ids))) for i in value.analytical_requirements), key=lambda i: i.requirement_id))
        deliverables = tuple(sorted((replace(i, deliverable_type=_text(i.deliverable_type), audience=_text(i.audience), language=_text(i.language)) for i in value.deliverable_requirements), key=lambda i: i.requirement_id))
        for items, attr, label in ((objectives, "objective_id", "Objective"), (questions, "question_id", "Research Question"), (hypotheses, "hypothesis_id", "Hypothesis"), (requirements, "requirement_id", "Analytical Requirement"), (deliverables, "requirement_id", "Deliverable Requirement")): _unique_ids(items, attr, label)
        all_ids = [i.objective_id for i in objectives] + [i.question_id for i in questions] + [i.hypothesis_id for i in hypotheses] + [i.requirement_id for i in requirements] + [i.requirement_id for i in deliverables]
        if len(all_ids) != len(set(all_ids)): raise QuantitativeResearchDesignError("entity IDs must be globally unique within a Design")
        objective_ids, question_ids = {i.objective_id for i in objectives}, {i.question_id for i in questions}
        for item in questions:
            if not item.objective_ids or not set(item.objective_ids) <= objective_ids: raise QuantitativeResearchDesignError("Research Question has dangling Objective reference")
        for item in hypotheses:
            if not item.objective_ids and not item.research_question_ids: raise QuantitativeResearchDesignError("Hypothesis requires Objective or Research Question linkage")
            if not set(item.objective_ids) <= objective_ids or not set(item.research_question_ids) <= question_ids: raise QuantitativeResearchDesignError("Hypothesis has dangling reference")
        for item in requirements:
            if not item.objective_ids and not item.research_question_ids: raise QuantitativeResearchDesignError("Analytical Requirement requires Objective or Research Question linkage")
            if not set(item.objective_ids) <= objective_ids or not set(item.research_question_ids) <= question_ids: raise QuantitativeResearchDesignError("Analytical Requirement has dangling reference")
        if value.methodology_intent.methodology != QUANTITATIVE: raise QuantitativeResearchDesignError("wrong Research Design methodology")
        population = replace(value.target_population, geography=_texts(value.target_population.geography), eligibility=_texts(value.target_population.eligibility), exclusions=_texts(value.target_population.exclusions), population_constraints=_texts(value.target_population.population_constraints))
        intent = replace(value.methodology_intent, collection_mode=_text(value.methodology_intent.collection_mode), sample_intent=_text(value.methodology_intent.sample_intent), weighting_intent=_text(value.methodology_intent.weighting_intent), confidence_significance_expectation=None if value.methodology_intent.confidence_significance_expectation is None else _text(value.methodology_intent.confidence_significance_expectation))
        result = replace(value, objectives=objectives, research_questions=questions, hypotheses=hypotheses, target_population=population, methodology_intent=intent, analytical_requirements=requirements, deliverable_requirements=deliverables, assumptions=_texts(value.assumptions), limitations=_texts(value.limitations))
        return replace(result, fingerprint=canonical_digest(_design_payload(result), digest_provider=self._digest))

    def _manifest(self, value):
        payload = {"contract": "QZ_TRACEABILITY_V1", "design_version_id": value.version_id, "design_fingerprint": value.fingerprint, "objective_ids": [i.objective_id for i in value.objectives], "question_to_objectives": [[i.question_id, list(i.objective_ids)] for i in value.research_questions], "requirement_to_objectives": [[i.requirement_id, list(i.objective_ids)] for i in value.analytical_requirements], "requirement_to_questions": [[i.requirement_id, list(i.research_question_ids)] for i in value.analytical_requirements]}
        return QuantitativeTraceabilityManifest(f"{value.version_id}:traceability", value.project_id, value.version_id, value.fingerprint, tuple(payload["objective_ids"]), tuple((i[0], tuple(i[1])) for i in payload["question_to_objectives"]), tuple((i[0], tuple(i[1])) for i in payload["requirement_to_objectives"]), tuple((i[0], tuple(i[1])) for i in payload["requirement_to_questions"]), canonical_digest(payload, digest_provider=self._digest))
