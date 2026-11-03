from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable, Iterable, Protocol
from uuid import uuid4

from application.authority_extension.identity import build_composition, canonical_gap_digest
from domain.planning.research_design import ResearchDesign
from domain.research_authority import AuthorityExtensionStatus, ResearchAuthorityExtension
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate


EXTENSION_TEMPLATE_ID = "desk-authority-extension-v1"
EXTENSION_STAGES = (
    "extension_plan", "extension_search", "extension_evidence",
    "extension_readiness", "extension_analysis", "extension_finalize",
)
EXTENSION_EXECUTORS = tuple(f"authority-{stage.replace('_', '-')}" for stage in EXTENSION_STAGES)
SEARCH_BUDGET_MAX = 12
PROVIDER_BUDGET_MAX = 7
MAX_CONSERVATIVE_ANALYSIS_FINDING_BATCHES = 2


class ExtensionContractError(ValueError):
    pass


class ExtensionBudgetExceeded(ExtensionContractError):
    pass


class GapOutcome(StrEnum):
    SATISFIED = "satisfied"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"
    TECHNICAL_ERROR = "technical_error"


@dataclass(frozen=True)
class AuthorityGap:
    information_need_id: str
    research_question_id: str
    metric: str
    geography: str
    required_periods: tuple[str, ...]
    minimum_independent_sources: int = 1
    quantitative: bool = True
    required_authority_kinds: tuple[str, ...] = ()
    prohibited_patterns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "information_need_id": self.information_need_id,
            "research_question_id": self.research_question_id,
            "metric": self.metric,
            "geography": self.geography,
            "required_periods": list(self.required_periods),
            "minimum_independent_sources": self.minimum_independent_sources,
            "quantitative": self.quantitative,
            "required_authority_kinds": list(self.required_authority_kinds),
            "prohibited_patterns": list(self.prohibited_patterns),
        }


@dataclass(frozen=True)
class AuthorityObservation:
    evidence_id: str
    source_identity: str
    information_need_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    metric: str
    geography: str
    periods: tuple[str, ...]
    authority_kind: str
    workflow_run_id: str
    research_design_id: str
    project_id: str
    conflicting: bool = False


@dataclass(frozen=True)
class ExtensionFinding:
    finding_id: str
    information_need_id: str
    evidence_ids: tuple[str, ...]
    workflow_run_id: str
    project_id: str
    research_design_id: str


@dataclass(frozen=True)
class BudgetState:
    search_used: int = 0
    provider_used: int = 0
    analysis_reserved: int = 0
    analysis_used: int = 0

    def consume_search(self) -> "BudgetState":
        if self.search_used >= SEARCH_BUDGET_MAX:
            raise ExtensionBudgetExceeded("authority_extension_search_budget_exhausted")
        return replace(self, search_used=self.search_used + 1)

    def consume_provider(self) -> "BudgetState":
        if self.provider_used >= PROVIDER_BUDGET_MAX:
            raise ExtensionBudgetExceeded("authority_extension_provider_budget_exhausted")
        return replace(self, provider_used=self.provider_used + 1)

    def reserve_analysis(self, required: int) -> "BudgetState":
        required = max(0, int(required))
        if self.provider_used + required > PROVIDER_BUDGET_MAX:
            raise ExtensionBudgetExceeded(
                "authority_extension_analysis_reservation_exceeds_budget",
            )
        return replace(self, analysis_reserved=required)

    def consume_provider_for_stage(self, stage: str) -> "BudgetState":
        if stage == "analysis":
            if self.analysis_used >= self.analysis_reserved:
                raise ExtensionBudgetExceeded(
                    "authority_extension_analysis_budget_exhausted",
                )
        elif self.provider_used - self.analysis_used >= (
            PROVIDER_BUDGET_MAX - self.analysis_reserved
        ):
            raise ExtensionBudgetExceeded(
                "authority_extension_evidence_budget_exhausted",
            )
        next_state = replace(self, provider_used=self.provider_used + 1)
        if stage == "analysis":
            next_state = replace(next_state, analysis_used=self.analysis_used + 1)
        return next_state


@dataclass(frozen=True)
class ExtensionState:
    extension_id: str
    workflow_run_id: str
    gaps: tuple[AuthorityGap, ...]
    budget: BudgetState = BudgetState()
    observations: tuple[AuthorityObservation, ...] = ()
    findings: tuple[ExtensionFinding, ...] = ()
    outcomes: tuple[tuple[str, GapOutcome], ...] = ()
    composition_id: str | None = None
    composition_digest: str | None = None


class ExtensionStateStore(Protocol):
    def load(self, workflow_run_id: str) -> ExtensionState | None: ...
    def save(self, state: ExtensionState) -> None: ...


class InMemoryExtensionStateStore:
    def __init__(self) -> None:
        self._states: dict[str, ExtensionState] = {}

    def load(self, workflow_run_id: str) -> ExtensionState | None:
        return self._states.get(workflow_run_id)

    def save(self, state: ExtensionState) -> None:
        self._states[state.workflow_run_id] = state


class WorkflowExtensionStateStore:
    """Persists the complete bounded lifecycle ledger in WorkflowRun task results."""

    KEY = "authority_extension_v1"

    def __init__(self, workflow_service) -> None:
        self._workflows = workflow_service
        self._runtime_context: ContextVar[Any | None] = ContextVar(
            "authority_extension_runtime_context",
            default=None,
        )

    @contextmanager
    def runtime_scope(self, context):
        token = self._runtime_context.set(context)
        try:
            yield
        finally:
            self._runtime_context.reset(token)

    def load(self, workflow_run_id: str) -> ExtensionState | None:
        context = self._runtime_context.get()
        if context is not None:
            payload = context.read_shared(self.KEY)
            if isinstance(payload, dict):
                return _state_from_dict(payload)
        payload = self._workflows.get_task_results(workflow_run_id).get(self.KEY)
        if not isinstance(payload, dict):
            return None
        return _state_from_dict(payload)

    def save(self, state: ExtensionState) -> None:
        payload = _state_to_dict(state)
        context = self._runtime_context.get()
        if context is not None:
            from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY

            checkpoint = context.services.get(CHECKPOINT_SERVICE_KEY)
            persist = getattr(checkpoint, "persist_named_result", None)
            if not callable(persist):
                raise ExtensionContractError(
                    "authority extension runtime checkpoint is unavailable"
                )
            context.write_shared(self.KEY, payload)
            persist(context, self.KEY, payload)
            return
        run = self._workflows.get_workflow_run(state.workflow_run_id)
        results = self._workflows.get_task_results(state.workflow_run_id)
        results[self.KEY] = payload
        version = self._workflows.get_workflow_run_version(state.workflow_run_id)
        self._workflows.save_workflow_run(run, expected_version=version, task_results=results)


def _state_to_dict(state: ExtensionState) -> dict[str, Any]:
    return {
        "version": "authority_extension_state_v1",
        "extension_id": state.extension_id,
        "workflow_run_id": state.workflow_run_id,
        "gaps": [gap.to_dict() for gap in state.gaps],
        "budget": {
            "search_used": state.budget.search_used,
            "provider_used": state.budget.provider_used,
            "analysis_reserved": state.budget.analysis_reserved,
            "analysis_used": state.budget.analysis_used,
        },
        "observations": [item.__dict__ for item in state.observations],
        "findings": [item.__dict__ for item in state.findings],
        "outcomes": [[key, value.value] for key, value in state.outcomes],
        "composition_id": state.composition_id,
        "composition_digest": state.composition_digest,
    }


def _state_from_dict(payload: dict[str, Any]) -> ExtensionState:
    if payload.get("version") != "authority_extension_state_v1":
        raise ExtensionContractError("unsupported authority extension state")
    return ExtensionState(
        extension_id=str(payload["extension_id"]),
        workflow_run_id=str(payload["workflow_run_id"]),
        gaps=tuple(AuthorityGap(
            information_need_id=str(item["information_need_id"]),
            research_question_id=str(item["research_question_id"]), metric=str(item["metric"]),
            geography=str(item["geography"]), required_periods=tuple(item["required_periods"]),
            minimum_independent_sources=int(item["minimum_independent_sources"]),
            quantitative=bool(item["quantitative"]),
            required_authority_kinds=tuple(item["required_authority_kinds"]),
            prohibited_patterns=tuple(item["prohibited_patterns"]),
        ) for item in payload["gaps"]),
        budget=BudgetState(**payload["budget"]),
        observations=tuple(AuthorityObservation(**{
            **item, "information_need_ids": tuple(item["information_need_ids"]),
            "research_question_ids": tuple(item["research_question_ids"]),
            "periods": tuple(item["periods"]),
        }) for item in payload["observations"]),
        findings=tuple(ExtensionFinding(**{
            **item, "evidence_ids": tuple(item["evidence_ids"]),
        }) for item in payload["findings"]),
        outcomes=tuple((str(item[0]), GapOutcome(item[1])) for item in payload["outcomes"]),
        composition_id=payload.get("composition_id"), composition_digest=payload.get("composition_digest"),
    )


def extension_template(
    *, design: ResearchDesign, research_brief, template_id: str = EXTENSION_TEMPLATE_ID,
) -> WorkflowTemplate:
    definitions: list[TaskDefinition] = []
    for index, stage in enumerate(EXTENSION_STAGES):
        definitions.append(TaskDefinition(
            id=stage, name=stage, executor_id=EXTENSION_EXECUTORS[index],
            executor_type=ExecutorType.TOOL,
            depends_on=[] if index == 0 else [EXTENSION_STAGES[index - 1]],
            metadata={"authority_extension": True},
        ))
    return WorkflowTemplate(
        id=template_id, name="Bounded selected authority extension",
        task_definitions=definitions, research_brief_snapshot=research_brief,
        research_design_snapshot=design,
    )


def derive_gap_contract(
    design: ResearchDesign,
    selected_information_need_ids: Iterable[str],
) -> tuple[AuthorityGap, ...]:
    selected = tuple(sorted(set(str(value).strip() for value in selected_information_need_ids if str(value).strip())))
    by_id = {need.id: need for need in design.information_needs}
    if not selected or any(value not in by_id for value in selected):
        raise ExtensionContractError("selected information need is not in immutable design")
    gaps: list[AuthorityGap] = []
    for need_id in selected:
        need = by_id[need_id]
        text = f"{need.id} {need.description}".casefold()
        real_retail = "real_adjustment" in text or "real-volume" in text or "constant-price" in text
        gaps.append(AuthorityGap(
            information_need_id=need.id,
            research_question_id=need.research_question_id,
            metric=need.description,
            geography=need.geography,
            required_periods=_required_periods(need.timeframe),
            minimum_independent_sources=2,
            quantitative=True,
            required_authority_kinds=("retail_real_volume", "retail_deflator") if real_retail else (),
            prohibited_patterns=("cpi_only", "nominal_plus_cpi") if real_retail else (),
        ))
    return tuple(gaps)


def _required_periods(value: str) -> tuple[str, ...]:
    years: set[str] = set()
    normalized = value.replace("–", "-").replace("—", "-")
    for start, end in re.findall(r"\b(20\d{2})\s*-\s*(20\d{2})\b", normalized):
        first, last = int(start), int(end)
        if first <= last and last - first <= 20:
            years.update(str(year) for year in range(first, last + 1))
    years.update(re.findall(r"\b20\d{2}\b", normalized))
    return tuple(sorted(years))


def selected_design(design: ResearchDesign, selected_ids: Iterable[str]) -> ResearchDesign:
    selected = set(selected_ids)
    needs = tuple(need for need in design.information_needs if need.id in selected)
    question_ids = {need.research_question_id for need in needs}
    return replace(
        design,
        information_needs=needs,
        research_questions=tuple(
            question for question in design.research_questions if question.id in question_ids
        ),
    )


def qualify_gap(gap: AuthorityGap, observations: Iterable[AuthorityObservation]) -> GapOutcome:
    relevant = [item for item in observations if gap.information_need_id in item.information_need_ids]
    if any(item.conflicting for item in relevant):
        return GapOutcome.CONFLICTING
    if not relevant:
        return GapOutcome.INSUFFICIENT
    if gap.required_authority_kinds and not any(
        item.authority_kind in gap.required_authority_kinds for item in relevant
    ):
        return GapOutcome.INSUFFICIENT
    if gap.geography and any(item.geography != gap.geography for item in relevant):
        return GapOutcome.INSUFFICIENT
    periods = {period for item in relevant for period in item.periods}
    if gap.required_periods and not set(gap.required_periods).issubset(periods):
        return GapOutcome.INSUFFICIENT
    identities = {item.source_identity for item in relevant}
    if len(identities) < gap.minimum_independent_sources:
        return GapOutcome.INSUFFICIENT
    return GapOutcome.SATISFIED


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


def extension_template_id(
    *, project_id: str, parent_workflow_run_id: str, design_id: str,
    gap_contract_digest: str, idempotency_key: str,
) -> str:
    """Identify one immutable authority-extension attempt snapshot."""
    return _stable_id(
        EXTENSION_TEMPLATE_ID,
        project_id,
        parent_workflow_run_id,
        design_id,
        gap_contract_digest,
        idempotency_key,
    )


class SelectedAuthorityExtensionService:
    """Application controller; external dispatch is injected and budget-wrapped."""

    def __init__(self, *, workflow_service, extension_repository,
                 composed_authority_repository, state_store: ExtensionStateStore,
                 capability_check: Callable[[], bool] | None = None) -> None:
        self.workflows = workflow_service
        self.extensions = extension_repository
        self.compositions = composed_authority_repository
        self.states = state_store
        self.capability_check = capability_check or (lambda: False)

    def runtime_state_scope(self, context):
        scope = getattr(self.states, "runtime_scope", None)
        return scope(context) if callable(scope) else nullcontext()

    def reserve_analysis_budget(self, workflow_run_id: str) -> ExtensionState:
        state = self._state(workflow_run_id)
        required_questions = {
            gap.research_question_id for gap in state.gaps
        }
        # Reserve one finding call per selected research question, with a
        # bounded second finding batch for a broad single-question selection.
        # This covers the P5 shape without making a global four-call
        # reservation for every extension. Insight and entailment each need
        # one additional call.
        finding_batches = max(1, len(required_questions))
        if (
            len(required_questions) == 1
            and len(state.gaps) >= 3
        ):
            finding_batches = min(
                MAX_CONSERVATIVE_ANALYSIS_FINDING_BATCHES,
                finding_batches + 1,
            )
        required = finding_batches + 2
        updated = replace(
            state,
            budget=state.budget.reserve_analysis(required),
        )
        self.states.save(updated)
        return updated

    def start(self, *, project_id: str, parent_workflow_run_id: str,
              design: ResearchDesign, selected_information_need_ids: Iterable[str],
              idempotency_key: str, confirmed: bool) -> ResearchAuthorityExtension:
        if not confirmed:
            raise ExtensionContractError("explicit confirmation is required")
        existing = self.extensions.get_by_idempotency_key(project_id, idempotency_key)
        if existing is not None:
            if (existing.parent_source_workflow_run_id != parent_workflow_run_id or
                    existing.research_design_id != design.id or
                    existing.selected_information_need_ids != tuple(sorted(set(selected_information_need_ids)))):
                raise ExtensionContractError("idempotency key payload conflict")
            return existing
        parent = self.workflows.get_workflow_run(parent_workflow_run_id)
        if parent.project_id != project_id:
            raise ExtensionContractError("parent workflow is outside project")
        parent_template = self.workflows.get_template(parent.workflow_template_id)
        if parent_template.research_brief_snapshot is None:
            raise ExtensionContractError("parent workflow has no immutable research brief")
        gaps = derive_gap_contract(design, selected_information_need_ids)
        payload = [gap.to_dict() for gap in gaps]
        gap_contract_digest = canonical_gap_digest(payload)
        run_id = str(uuid4())
        template = extension_template(
            design=selected_design(design, (gap.information_need_id for gap in gaps)),
            research_brief=parent_template.research_brief_snapshot,
            template_id=extension_template_id(
                project_id=project_id,
                parent_workflow_run_id=parent_workflow_run_id,
                design_id=design.id,
                gap_contract_digest=gap_contract_digest,
                idempotency_key=idempotency_key,
            ),
        )
        self.workflows.publish_template_snapshot(template, project_id=project_id)
        # The generic worker must not claim the run until the extension stage
        # adapters submit it explicitly. Persisting it PAUSED makes creation
        # atomic and fail-closed instead of exposing a half-configured run.
        self.workflows.create_workflow_run(
            template, project_id=project_id, run_id=run_id, initially_paused=True,
        )
        extension = ResearchAuthorityExtension(
            extension_id=str(uuid4()), project_id=project_id,
            research_design_id=design.id,
            parent_source_workflow_run_id=parent_workflow_run_id,
            extension_workflow_run_id=run_id,
            selected_information_need_ids=tuple(gap.information_need_id for gap in gaps),
            gap_contract_digest=gap_contract_digest,
            idempotency_key=idempotency_key, created_at=datetime.now(UTC).isoformat(),
        )
        try:
            stored = self.extensions.create_or_get(extension)
        except Exception:
            self.workflows.delete_workflow_run(run_id)
            raise
        if stored.extension_id != extension.extension_id:
            # A concurrent request won the idempotency identity. The losing
            # PAUSED run owns no artifacts and is safe to compensate.
            self.workflows.delete_workflow_run(run_id)
            return stored
        self.states.save(ExtensionState(stored.extension_id, stored.extension_workflow_run_id, gaps))
        return stored

    def activate(self, extension_id: str) -> ResearchAuthorityExtension:
        if not self.capability_check():
            raise ExtensionContractError("authority extension stage adapters are incomplete")
        extension = self.extensions.get_by_id(extension_id)
        if extension is None:
            raise ExtensionContractError("authority extension not found")
        run = self.workflows.get_workflow_run(extension.extension_workflow_run_id)
        if run.status.value != "paused":
            return extension
        run.resume()
        self.workflows.save_workflow_run(
            run, expected_version=self.workflows.get_workflow_run_version(run.id),
            task_results=self.workflows.get_task_results(run.id),
        )
        self.extensions.save(replace(extension, status=AuthorityExtensionStatus.ACTIVE))
        return self.extensions.get_by_id(extension_id)

    def dispatch_search(self, workflow_run_id: str, operation: Callable[[], Any],
                        *, information_need_id: str | None = None) -> Any:
        state = self._state(workflow_run_id)
        if information_need_id is not None:
            selected = {gap.information_need_id for gap in state.gaps}
            if information_need_id not in selected:
                raise ExtensionContractError("search expands selected information-need scope")
            if dict(state.outcomes).get(information_need_id) == GapOutcome.SATISFIED:
                return None
        next_state = replace(state, budget=state.budget.consume_search())
        self.states.save(next_state)  # persist before dispatch
        return operation()

    def unresolved_information_need_ids(self, workflow_run_id: str) -> tuple[str, ...]:
        state = self._state(workflow_run_id)
        outcomes = self._evaluate_outcomes(state)
        return tuple(key for key, value in outcomes if value != GapOutcome.SATISFIED)

    def dispatch_provider(
        self, workflow_run_id: str, operation: Callable[[], Any], *, stage: str | None = None,
    ) -> Any:
        state = self._state(workflow_run_id)
        budget = (
            state.budget.consume_provider_for_stage(stage)
            if stage in {"evidence", "analysis"}
            else state.budget.consume_provider()
        )
        next_state = replace(state, budget=budget)
        self.states.save(next_state)  # persist before dispatch
        return operation()

    def record_observations(self, workflow_run_id: str,
                            observations: Iterable[AuthorityObservation]) -> ExtensionState:
        state = self._state(workflow_run_id)
        selected = {gap.information_need_id for gap in state.gaps}
        by_id = {item.evidence_id: item for item in state.observations}
        extension = self.extensions.get_by_id(state.extension_id)
        assert extension is not None
        for item in observations:
            if item.project_id != extension.project_id or item.research_design_id != extension.research_design_id:
                raise ExtensionContractError("cross-project or cross-design evidence")
            if item.workflow_run_id not in {extension.parent_source_workflow_run_id, workflow_run_id}:
                raise ExtensionContractError("evidence is not an authority member")
            if not item.information_need_ids or not set(item.information_need_ids).issubset(selected):
                raise ExtensionContractError("evidence expands selected information-need scope")
            by_id.setdefault(item.evidence_id, item)
        updated = replace(state, observations=tuple(sorted(by_id.values(), key=lambda value: value.evidence_id)))
        self.states.save(updated)
        return updated

    def evaluate(self, workflow_run_id: str) -> ExtensionState:
        state = self._state(workflow_run_id)
        outcomes = self._evaluate_outcomes(state)
        updated = replace(state, outcomes=outcomes)
        self.states.save(updated)
        return updated

    @staticmethod
    def _evaluate_outcomes(
        state: ExtensionState,
    ) -> tuple[tuple[str, GapOutcome], ...]:
        return tuple(
            (gap.information_need_id, qualify_gap(gap, state.observations))
            for gap in state.gaps
        )

    def record_findings(self, workflow_run_id: str,
                        findings: Iterable[ExtensionFinding]) -> ExtensionState:
        state = self._state(workflow_run_id)
        extension = self.extensions.get_by_id(state.extension_id)
        assert extension is not None
        selected = {gap.information_need_id for gap in state.gaps}
        evidence_ids = {item.evidence_id for item in state.observations}
        by_id = {item.finding_id: item for item in state.findings}
        for item in findings:
            if (item.project_id, item.research_design_id, item.workflow_run_id) != (
                extension.project_id, extension.research_design_id, workflow_run_id,
            ):
                raise ExtensionContractError("finding ownership mismatch")
            if item.information_need_id not in selected or not item.evidence_ids or not set(item.evidence_ids).issubset(evidence_ids):
                raise ExtensionContractError("finding authority is outside selected composition")
            by_id.setdefault(item.finding_id, item)
        updated = replace(state, findings=tuple(sorted(by_id.values(), key=lambda value: value.finding_id)))
        self.states.save(updated)
        return updated

    def finalize(self, workflow_run_id: str, *, created_at: str) -> ExtensionState:
        state = self.evaluate(workflow_run_id)
        extension = self.extensions.get_by_id(state.extension_id)
        assert extension is not None
        outcomes = dict(state.outcomes)
        selected = set(extension.selected_information_need_ids)
        finding_needs = {item.information_need_id for item in state.findings}
        if any(value == GapOutcome.CONFLICTING for value in outcomes.values()):
            self.extensions.save(replace(extension, status=AuthorityExtensionStatus.CONFLICTING, terminal_reason="selected_authority_conflicting"))
            return state
        if any(value != GapOutcome.SATISFIED for value in outcomes.values()) or finding_needs != selected:
            self.extensions.save(replace(extension, status=AuthorityExtensionStatus.INSUFFICIENT, terminal_reason="selected_authority_incomplete"))
            return state
        composition = build_composition(
            composition_id=_stable_id("composition", extension.extension_id),
            project_id=extension.project_id, research_design_id=extension.research_design_id,
            parent_source_workflow_run_id=extension.parent_source_workflow_run_id,
            member_workflow_run_ids=(extension.parent_source_workflow_run_id, workflow_run_id),
            selected_information_need_ids=extension.selected_information_need_ids,
            created_at=created_at,
        )
        composition = self.compositions.create_or_get(composition)
        self.extensions.save(replace(extension, status=AuthorityExtensionStatus.SUCCEEDED, terminal_reason=None))
        updated = replace(state, composition_id=composition.composition_id,
                          composition_digest=composition.composition_digest)
        self.states.save(updated)
        return updated

    def fail_technical(self, workflow_run_id: str, reason: str) -> None:
        state = self._state(workflow_run_id)
        extension = self.extensions.get_by_id(state.extension_id)
        assert extension is not None
        self.extensions.save(replace(extension, status=AuthorityExtensionStatus.TECHNICAL_ERROR,
                                     terminal_reason=reason[:256]))

    def _state(self, workflow_run_id: str) -> ExtensionState:
        state = self.states.load(workflow_run_id)
        if state is None:
            raise ExtensionContractError("authority extension state is unavailable")
        return state
