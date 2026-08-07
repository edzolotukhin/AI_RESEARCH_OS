"""P1-06 M3 mini-live semantic sufficiency harness (fixtures + observable runner)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.raw_semantic_decision_contract import (
    RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
    raw_semantic_decision_from_payload,
)
from application.research_quality.semantic_sufficiency_adapter import (
    semantic_assessment_from_raw_decision,
)
from domain.ai.prompt import Prompt
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import BLOCKING_GAP_TYPES
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    NormalizedSemanticDecision,
    normalize_semantic_decision,
)
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_policy import (
    SufficiencyPolicyDecision,
    apply_sufficiency_policy,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
from infrastructure.research_quality.sufficiency_structured_output import (
    DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
)

MINI_LIVE_ENV_FLAG = "SUFFICIENCY_MINI_LIVE"
MAX_STRUCTURED_OUTPUT_ATTEMPTS = DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS

SCENARIO_A_ID = "scenario_a_obviously_sufficient"
SCENARIO_B_ID = "scenario_b_obviously_insufficient"

NEED_ID = "mini-live-horeca-belgrade"
RQ_ID = "rq-horeca-belgrade"
DESIGN_ID = "mini-live-design"
PROJECT_ID = "mini-live-project"
RUN_ID = "mini-live-run"


@dataclass(frozen=True)
class MiniLiveScenario:
    scenario_id: str
    research_question: ResearchQuestion
    information_need: InformationNeed
    evidence: tuple[Evidence, ...]
    expected_supported_aspects: tuple[str, ...]
    expected_missing_aspects: tuple[str, ...]
    expected_coverage: float
    expected_status: SufficiencyStatus
    expected_search_directives: tuple[str, ...] = ()


@dataclass
class ScenarioTelemetry:
    attempts: int = 0
    finish_reason: str | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    max_output_tokens: int | None = None
    visible_output_length: int | None = None
    parse_failure_category: str | None = None
    contract_failure_category: str | None = None
    llm_calls: int = 0
    retries: int = 0
    elapsed_seconds: float = 0.0
    estimated_cost_usd: float | None = None
    attempt_history: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "finish_reason": self.finish_reason,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "max_output_tokens": self.max_output_tokens,
            "visible_output_length": self.visible_output_length,
            "parse_failure_category": self.parse_failure_category,
            "contract_failure_category": self.contract_failure_category,
            "llm_calls": self.llm_calls,
            "retries": self.retries,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "estimated_cost_usd": self.estimated_cost_usd,
            "attempt_history": list(self.attempt_history),
        }


@dataclass
class ScenarioRunResult:
    scenario_id: str
    information_need_id: str
    evidence_count: int
    independent_source_count: int
    raw_semantic: RawSemanticDecision
    normalized: NormalizedSemanticDecision
    policy: SufficiencyPolicyDecision
    final_assessment: SemanticSufficiencyAssessment
    telemetry: ScenarioTelemetry = field(default_factory=ScenarioTelemetry)
    mode: str = "offline"

    def to_report_dict(self) -> dict[str, Any]:
        blocking = any(
            gap_type in BLOCKING_GAP_TYPES for gap_type in self.policy.gap_types
        )
        return {
            "scenario_id": self.scenario_id,
            "mode": self.mode,
            "information_need_id": self.information_need_id,
            "evidence_count": self.evidence_count,
            "independent_source_count": self.independent_source_count,
            "raw_semantic_decision": self.raw_semantic.to_dict(),
            "normalized_semantic_decision": {
                "supported_aspects": list(self.normalized.supported_aspects),
                "missing_aspects": list(self.normalized.missing_aspects),
                "semantic_conflicts": list(self.normalized.semantic_conflicts),
                "confidence": self.normalized.confidence,
                "reason": self.normalized.reason,
                "required_aspects": list(self.normalized.required_aspects),
            },
            "policy": {
                "coverage": self.policy.coverage,
                "gap_types": [gap.value for gap in self.policy.gap_types],
                "evidence_count": self.evidence_count,
                "derived_status": self.policy.status.value,
                "blocking": blocking,
            },
            "final_assessment": self.final_assessment.to_dict(),
            "telemetry": self.telemetry.to_dict(),
        }


def mini_live_information_need() -> InformationNeed:
    return InformationNeed(
        id=NEED_ID,
        research_question_id=RQ_ID,
        description=(
            "Determine whether fresh microgreens are currently commercially offered "
            "to HoReCa customers in Belgrade."
        ),
        evidence_expectation=None,
    )


def mini_live_research_question() -> ResearchQuestion:
    return ResearchQuestion(
        id=RQ_ID,
        question=(
            "Are fresh microgreens currently commercially available to HoReCa "
            "customers in Belgrade?"
        ),
        objective_refs=(),
    )


def _base_evidence(
    *,
    evidence_id: str,
    source_id: str,
    statement: str,
    source_excerpt: str,
    checksum_suffix: str,
) -> Evidence:
    return Evidence(
        id=evidence_id,
        project_id=PROJECT_ID,
        source_id=source_id,
        source_content_checksum=f"checksum-{checksum_suffix}",
        workflow_run_id=RUN_ID,
        research_design_id=DESIGN_ID,
        research_question_refs=(RQ_ID,),
        information_need_refs=(NEED_ID,),
        statement=statement,
        source_excerpt=source_excerpt,
        created_at="2026-08-07T12:00:00+00:00",
        deduplication_key=f"dedup-{evidence_id}",
    )


def scenario_a_fixtures() -> MiniLiveScenario:
    return MiniLiveScenario(
        scenario_id=SCENARIO_A_ID,
        research_question=mini_live_research_question(),
        information_need=mini_live_information_need(),
        evidence=(
            _base_evidence(
                evidence_id="ev-a-1",
                source_id="source-belgrade-supplier-a",
                checksum_suffix="a1",
                statement=(
                    "GreenSprout Belgrade supplies fresh microgreens to restaurants "
                    "and hotels in Belgrade on a current commercial basis."
                ),
                source_excerpt=(
                    "Our Belgrade operation delivers fresh microgreens weekly to "
                    "restaurants, hotels, and catering partners across the city."
                ),
            ),
            _base_evidence(
                evidence_id="ev-a-2",
                source_id="source-horeca-trade-b",
                checksum_suffix="a2",
                statement=(
                    "A 2026 HoReCa supplier directory lists active commercial "
                    "microgreens supply for Belgrade restaurant clients."
                ),
                source_excerpt=(
                    "Category: HoReCa produce suppliers — Belgrade — microgreens — "
                    "status: currently available for restaurant orders."
                ),
            ),
            _base_evidence(
                evidence_id="ev-a-3",
                source_id="source-belgrade-supplier-a",
                checksum_suffix="a3",
                statement=(
                    "The supplier confirms ongoing 2026 commercial availability of "
                    "fresh microgreens for Belgrade HoReCa buyers."
                ),
                source_excerpt=(
                    "Fresh microgreens remain available for HoReCa customers in "
                    "Belgrade throughout the current season."
                ),
            ),
        ),
        expected_supported_aspects=(LEGACY_NEED_ASPECT_ID,),
        expected_missing_aspects=(),
        expected_coverage=1.0,
        expected_status=SufficiencyStatus.SUFFICIENT,
        expected_search_directives=(),
    )


def scenario_b_fixtures() -> MiniLiveScenario:
    return MiniLiveScenario(
        scenario_id=SCENARIO_B_ID,
        research_question=mini_live_research_question(),
        information_need=mini_live_information_need(),
        evidence=(
            _base_evidence(
                evidence_id="ev-b-1",
                source_id="source-serbia-agri-overview",
                checksum_suffix="b1",
                statement=(
                    "Microgreens are cultivated in Serbia and discussed as part of "
                    "urban agriculture trends."
                ),
                source_excerpt=(
                    "Serbia has seen growing interest in microgreens among urban "
                    "growers, with production mentioned in several regions."
                ),
            ),
            _base_evidence(
                evidence_id="ev-b-2",
                source_id="source-nutrition-blog",
                checksum_suffix="b2",
                statement=(
                    "Microgreens are nutrient-dense and popular in healthy diets."
                ),
                source_excerpt=(
                    "Health-focused diets often include microgreens for vitamins "
                    "and antioxidants, regardless of geography."
                ),
            ),
        ),
        expected_supported_aspects=(),
        expected_missing_aspects=(LEGACY_NEED_ASPECT_ID,),
        expected_coverage=0.0,
        expected_status=SufficiencyStatus.INSUFFICIENT,
        expected_search_directives=(LEGACY_NEED_ASPECT_ID,),
    )


def all_mini_live_scenarios() -> tuple[MiniLiveScenario, ...]:
    return (scenario_a_fixtures(), scenario_b_fixtures())


def deterministic_signals_for_scenario(
    scenario: MiniLiveScenario,
) -> DeterministicSufficiencySignals:
    design = ResearchDesign(
        id=DESIGN_ID,
        research_questions=(scenario.research_question,),
        information_needs=(scenario.information_need,),
    )
    signals = DeterministicSufficiencyEvaluator().evaluate(
        design=design,
        evidence=scenario.evidence,
    )
    return next(item for item in signals if item.information_need_id == NEED_ID)


def evaluate_from_raw_semantic(
    *,
    scenario: MiniLiveScenario,
    raw_semantic: RawSemanticDecision,
    mode: str = "offline",
    telemetry: ScenarioTelemetry | None = None,
) -> ScenarioRunResult:
    signals = deterministic_signals_for_scenario(scenario)
    normalized = normalize_semantic_decision(
        raw=raw_semantic,
        evidence_expectation=scenario.information_need.evidence_expectation,
    )
    policy = apply_sufficiency_policy(
        information_need=scenario.information_need,
        evidence_expectation=scenario.information_need.evidence_expectation,
        signals=signals,
        raw_semantic=raw_semantic,
    )
    final = semantic_assessment_from_raw_decision(
        information_need=scenario.information_need,
        signals=signals,
        raw_semantic=raw_semantic,
    )
    return ScenarioRunResult(
        scenario_id=scenario.scenario_id,
        information_need_id=scenario.information_need.id,
        evidence_count=signals.evidence_count,
        independent_source_count=signals.independent_source_count,
        raw_semantic=raw_semantic,
        normalized=normalized,
        policy=policy,
        final_assessment=final,
        telemetry=telemetry or ScenarioTelemetry(),
        mode=mode,
    )


def evaluate_scenario_offline(scenario: MiniLiveScenario) -> ScenarioRunResult:
    raw = RawSemanticDecision(
        supported_aspects=scenario.expected_supported_aspects,
        missing_aspects=scenario.expected_missing_aspects,
        semantic_conflicts=(),
        confidence=0.9 if scenario.expected_status == SufficiencyStatus.SUFFICIENT else 0.4,
        reason=f"Offline fixture for {scenario.scenario_id}.",
    )
    return evaluate_from_raw_semantic(
        scenario=scenario,
        raw_semantic=raw,
        mode="offline",
    )


def _attempt_history_from_generator(generator: Any) -> tuple[dict[str, Any], ...]:
    history = getattr(generator, "attempt_history", None)
    if history is None:
        return ()
    if isinstance(history, tuple):
        return tuple(
            item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in history
        )
    return ()


def _telemetry_from_generator(generator: Any, *, elapsed_seconds: float) -> ScenarioTelemetry:
    last = getattr(generator, "last_telemetry", None)
    attempt_history = _attempt_history_from_generator(generator)
    if last is None:
        return ScenarioTelemetry(
            elapsed_seconds=elapsed_seconds,
            attempt_history=attempt_history,
        )
    if hasattr(last, "attempts"):
        attempts = int(getattr(last, "attempts", 1) or 1)
        return ScenarioTelemetry(
            attempts=attempts,
            finish_reason=getattr(last, "finish_reason", None),
            output_tokens=getattr(last, "output_tokens", None),
            reasoning_tokens=getattr(last, "reasoning_tokens", None),
            max_output_tokens=getattr(last, "max_output_tokens", None),
            visible_output_length=getattr(last, "visible_output_length", None),
            parse_failure_category=getattr(last, "parse_failure_category", None),
            contract_failure_category=getattr(last, "contract_failure_category", None),
            llm_calls=attempts,
            retries=max(0, attempts - 1),
            elapsed_seconds=elapsed_seconds,
            estimated_cost_usd=getattr(last, "estimated_cost_usd", None),
            attempt_history=attempt_history,
        )
    attempts = int(last.get("attempts") or 1)
    return ScenarioTelemetry(
        attempts=attempts,
        finish_reason=last.get("finish_reason"),
        output_tokens=last.get("output_tokens"),
        reasoning_tokens=last.get("reasoning_tokens"),
        max_output_tokens=last.get("max_output_tokens"),
        visible_output_length=last.get("visible_output_length"),
        parse_failure_category=last.get("parse_failure_category"),
        contract_failure_category=last.get("contract_failure_category"),
        llm_calls=attempts,
        retries=max(0, attempts - 1),
        elapsed_seconds=elapsed_seconds,
        estimated_cost_usd=last.get("estimated_cost_usd"),
        attempt_history=attempt_history,
    )


def evaluate_scenario_live(
    *,
    scenario: MiniLiveScenario,
    assessor: Any,
) -> ScenarioRunResult:
    """Run the production semantic boundary with harness-only observability."""
    from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
        _build_user_payload,
        _system_prompt,
    )

    signals = deterministic_signals_for_scenario(scenario)
    prompt = Prompt(
        system=_system_prompt(),
        user=_build_user_payload(
            research_question=scenario.research_question,
            information_need=scenario.information_need,
            evidence=scenario.evidence,
            deterministic_signals=signals,
        ),
    )
    started = time.perf_counter()
    payload = assessor._structured_output.generate(
        prompt,
        payload_schema=RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
    )
    elapsed = time.perf_counter() - started
    telemetry = _telemetry_from_generator(
        assessor._structured_output,
        elapsed_seconds=elapsed,
    )
    raw = raw_semantic_decision_from_payload(payload)
    return evaluate_from_raw_semantic(
        scenario=scenario,
        raw_semantic=raw,
        mode="live",
        telemetry=telemetry,
    )


def build_production_semantic_assessor(config: Any) -> Any:
    """Build LlmSemanticSufficiencyAssessor with production generation settings."""
    from infrastructure.llm.llm_configuration import LLMConfiguration
    from infrastructure.llm.openai_client import OpenAIClient
    from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
        LlmSemanticSufficiencyAssessor,
    )

    llm_client = OpenAIClient(
        configuration=LLMConfiguration(
            model=config.llm_model,
            max_tokens=config.llm_max_tokens,
        ),
    )
    return LlmSemanticSufficiencyAssessor(
        llm_client=llm_client,
        max_output_tokens=config.sufficiency_max_output_tokens,
        reasoning_effort=config.sufficiency_reasoning_effort,
    )


@dataclass
class ScenarioAcceptance:
    scenario_id: str
    passed: bool
    failures: tuple[str, ...] = ()


def validate_offline_fixture_expectations(result: ScenarioRunResult) -> ScenarioAcceptance:
    scenario = next(
        item for item in all_mini_live_scenarios() if item.scenario_id == result.scenario_id
    )
    failures: list[str] = []

    if result.evidence_count <= 0:
        failures.append("evidence_count must be > 0")
    if scenario.scenario_id == SCENARIO_A_ID and result.independent_source_count < 2:
        failures.append("scenario A requires >= 2 independent sources")

    if result.policy.coverage != scenario.expected_coverage:
        failures.append(
            f"coverage expected {scenario.expected_coverage}, got {result.policy.coverage}"
        )
    if result.final_assessment.status != scenario.expected_status:
        failures.append(
            f"status expected {scenario.expected_status.value}, "
            f"got {result.final_assessment.status.value}"
        )
    if result.final_assessment.search_directives != scenario.expected_search_directives:
        failures.append(
            "search_directives mismatch: "
            f"expected {scenario.expected_search_directives}, "
            f"got {result.final_assessment.search_directives}"
        )
    if scenario.expected_status == SufficiencyStatus.INSUFFICIENT:
        if result.final_assessment.status == SufficiencyStatus.MISSING:
            failures.append("INSUFFICIENT scenario must not become MISSING")

    return ScenarioAcceptance(
        scenario_id=result.scenario_id,
        passed=not failures,
        failures=tuple(failures),
    )


def validate_live_acceptance(result: ScenarioRunResult) -> ScenarioAcceptance:
    scenario = next(
        item for item in all_mini_live_scenarios() if item.scenario_id == result.scenario_id
    )
    failures: list[str] = []

    offline = validate_offline_fixture_expectations(result)
    failures.extend(offline.failures)

    allowed_aspects = {LEGACY_NEED_ASPECT_ID}
    observed_aspects = set(result.raw_semantic.supported_aspects) | set(
        result.raw_semantic.missing_aspects
    )
    unexpected = observed_aspects - allowed_aspects
    if unexpected:
        failures.append(f"unexpected aspect identifiers: {sorted(unexpected)}")

    if result.raw_semantic.semantic_conflicts:
        failures.append("semantic_conflicts must be empty for first mini-live")

    if scenario.scenario_id == SCENARIO_A_ID:
        if result.raw_semantic.supported_aspects != (LEGACY_NEED_ASPECT_ID,):
            failures.append(
                "scenario A raw supported_aspects must be exactly __legacy_need__"
            )
        if result.raw_semantic.missing_aspects:
            failures.append("scenario A raw missing_aspects must be empty")
        if any(gap in BLOCKING_GAP_TYPES for gap in result.policy.gap_types):
            failures.append("scenario A must have no blocking gaps")
    elif scenario.scenario_id == SCENARIO_B_ID:
        if result.raw_semantic.supported_aspects:
            failures.append("scenario B raw supported_aspects must be empty")
        if result.raw_semantic.missing_aspects != (LEGACY_NEED_ASPECT_ID,):
            failures.append(
                "scenario B raw missing_aspects must be exactly __legacy_need__"
            )

    if result.telemetry.retries > 0:
        failures.append(
            f"not clean first-pass acceptance (retries={result.telemetry.retries})"
        )
    if result.telemetry.llm_calls > MAX_STRUCTURED_OUTPUT_ATTEMPTS:
        failures.append(
            "unexpected retry explosion: "
            f"llm_calls={result.telemetry.llm_calls} "
            f"> max_attempts={MAX_STRUCTURED_OUTPUT_ATTEMPTS}"
        )

    return ScenarioAcceptance(
        scenario_id=result.scenario_id,
        passed=not failures,
        failures=tuple(failures),
    )


def run_offline_harness() -> tuple[ScenarioRunResult, ...]:
    return tuple(evaluate_scenario_offline(scenario) for scenario in all_mini_live_scenarios())


def run_live_harness(assessor: Any) -> tuple[ScenarioRunResult, ...]:
    """Run live scenarios sequentially; stop before the next provider call on failure."""
    if len(all_mini_live_scenarios()) > 2:
        raise RuntimeError("mini-live is limited to 2 scenarios")
    results: list[ScenarioRunResult] = []
    for scenario in all_mini_live_scenarios():
        result = evaluate_scenario_live(scenario=scenario, assessor=assessor)
        results.append(result)
        acceptance = validate_live_acceptance(result)
        if not acceptance.passed:
            break
    return tuple(results)


def aggregate_usage(results: Sequence[ScenarioRunResult]) -> dict[str, Any]:
    total_calls = sum(item.telemetry.llm_calls for item in results)
    total_retries = sum(item.telemetry.retries for item in results)
    total_elapsed = sum(item.telemetry.elapsed_seconds for item in results)
    costs = [
        item.telemetry.estimated_cost_usd
        for item in results
        if item.telemetry.estimated_cost_usd is not None
    ]
    return {
        "scenario_count": len(results),
        "llm_calls": total_calls,
        "retries": total_retries,
        "elapsed_seconds": round(total_elapsed, 3),
        "estimated_cost_usd": round(sum(costs), 6) if costs else None,
    }


def format_report(results: Sequence[ScenarioRunResult]) -> str:
    payload = {
        "scenarios": [item.to_report_dict() for item in results],
        "total_usage": aggregate_usage(results),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
