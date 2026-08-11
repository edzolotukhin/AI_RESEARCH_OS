"""Stage-scoped LLM client composition (P1-08.2).

DETERMINISTIC_PLANNER selects a deterministic Planner client only.
Analysis / Report / Review / Evidence / Research-quality resolve independently
and must never inherit the planner-only DeterministicLLMClient implicitly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from application.config import ApplicationConfig, ApplicationOverrides
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.llm.llm_client import LLMClient


class LlmClientCompositionError(RuntimeError):
    """Fail-closed composition error when a required live client is unavailable."""


@dataclass(frozen=True)
class StageLlmClients:
    """Resolved, budget-wrapped LLM clients per capability/stage."""

    planner: LLMClient
    analysis: LLMClient
    report: LLMClient
    review: LLMClient
    evidence: LLMClient

    def diagnostics(self) -> dict[str, dict[str, str]]:
        return {
            "planner": describe_llm_client(self.planner),
            "analysis": describe_llm_client(self.analysis),
            "report": describe_llm_client(self.report),
            "review": describe_llm_client(self.review),
            "evidence": describe_llm_client(self.evidence),
        }


def deterministic_planner_enabled(
    environ: dict[str, str] | None = None,
) -> bool:
    env = environ if environ is not None else os.environ
    return str(env.get("DETERMINISTIC_PLANNER", "")).lower() in {"1", "true", "yes"}


def unwrap_llm_client(client: LLMClient) -> LLMClient:
    """Return the innermost non-budget-enforcing delegate when present."""
    current: Any = client
    seen: set[int] = set()
    while isinstance(current, BudgetEnforcingLLMClient):
        identity = id(current)
        if identity in seen:
            break
        seen.add(identity)
        current = current._delegate
    return current


def describe_llm_client(client: LLMClient) -> dict[str, str]:
    """Safe forensics fields (no secrets)."""
    inner = unwrap_llm_client(client)
    inner_name = type(inner).__name__
    classification = "test_or_other"
    if inner_name == "OpenAIClient":
        classification = "live"
    elif inner_name == "DeterministicLLMClient":
        classification = "deterministic"
    provider = "unknown"
    model = ""
    if inner_name == "OpenAIClient":
        provider = "openai"
        configuration = getattr(inner, "_configuration", None)
        model = str(getattr(configuration, "model", "") or "")
    elif inner_name == "DeterministicLLMClient":
        provider = "deterministic"
    return {
        "wrapper": type(client).__name__,
        "concrete_client": inner_name,
        "provider": provider,
        "model": model,
        "classification": classification,
    }


def create_live_llm_client(config: ApplicationConfig) -> LLMClient:
    """Construct the configured production live LLM client (no planner flag)."""
    from infrastructure.llm.llm_configuration import LLMConfiguration
    from infrastructure.llm.openai_client import OpenAIClient

    llm_configuration = LLMConfiguration(
        model=config.llm_model,
        max_tokens=config.llm_max_tokens,
    )
    return OpenAIClient(configuration=llm_configuration)


def create_deterministic_planner_llm_client() -> LLMClient:
    from infrastructure.llm.deterministic_llm_client import DeterministicLLMClient

    return DeterministicLLMClient()


def _budget_wrap(client: LLMClient) -> LLMClient:
    if isinstance(client, BudgetEnforcingLLMClient):
        return client
    return BudgetEnforcingLLMClient(client)


def _require_non_planner_deterministic(
    *,
    stage: str,
    client: LLMClient,
    allow_deterministic: bool,
) -> LLMClient:
    """Prevent silent planner-deterministic fallback into downstream stages."""
    if allow_deterministic:
        return client
    inner = unwrap_llm_client(client)
    if type(inner).__name__ == "DeterministicLLMClient":
        raise LlmClientCompositionError(
            f"{stage} is configured for a live/test LLM client but resolved "
            f"DeterministicLLMClient. DETERMINISTIC_PLANNER must not substitute "
            f"downstream stage clients."
        )
    return client


def resolve_stage_llm_clients(
    config: ApplicationConfig,
    overrides: ApplicationOverrides | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> StageLlmClients:
    """
    Resolve stage-scoped LLM clients.

    Resolution order per stage:
    1. stage-specific override
    2. shared overrides.llm_client (test/custom wiring)
    3. stage default (planner may be deterministic; others use live OpenAI)
    """
    overrides = overrides or ApplicationOverrides()
    det_planner = deterministic_planner_enabled(environ)

    live_inner = create_live_llm_client(config)
    shared_override = overrides.llm_client

    def _downstream_inner(stage_override: LLMClient | None) -> LLMClient:
        if stage_override is not None:
            return stage_override
        if shared_override is not None:
            return shared_override
        return live_inner

    if overrides.planner_llm_client is not None:
        planner_inner = overrides.planner_llm_client
    elif det_planner:
        planner_inner = create_deterministic_planner_llm_client()
    elif shared_override is not None:
        planner_inner = shared_override
    else:
        planner_inner = live_inner

    analysis_inner = _downstream_inner(overrides.analysis_llm_client)
    report_inner = _downstream_inner(overrides.report_llm_client)
    review_inner = _downstream_inner(overrides.review_llm_client)
    evidence_inner = _downstream_inner(overrides.evidence_llm_client)

    # Fail closed: ANALYSIS/REPORT/REVIEW=llm must not silently get planner det client
    # unless the caller explicitly injected DeterministicLLMClient as a test double
    # via stage override or shared override.
    explicit_downstream = (
        shared_override is not None
        or overrides.analysis_llm_client is not None
        or overrides.report_llm_client is not None
        or overrides.review_llm_client is not None
        or overrides.evidence_llm_client is not None
    )
    if not explicit_downstream:
        for stage_name, engine_name, inner in (
            ("analysis", config.analysis_engine, analysis_inner),
            ("report", config.report_engine, report_inner),
            ("review", config.review_engine, review_inner),
        ):
            if str(engine_name).lower() == "llm":
                _require_non_planner_deterministic(
                    stage=stage_name,
                    client=inner,
                    allow_deterministic=False,
                )

    # Share one budget wrapper when inners are identical to preserve object identity
    # for the common live path; still wrap distinct inners separately.
    budgeted_by_id: dict[int, LLMClient] = {}

    def _wrap(inner: LLMClient) -> LLMClient:
        key = id(inner)
        existing = budgeted_by_id.get(key)
        if existing is not None:
            return existing
        wrapped = _budget_wrap(inner)
        budgeted_by_id[key] = wrapped
        return wrapped

    return StageLlmClients(
        planner=_wrap(planner_inner),
        analysis=_wrap(analysis_inner),
        report=_wrap(report_inner),
        review=_wrap(review_inner),
        evidence=_wrap(evidence_inner),
    )


# Back-compat name used by older tests/imports.
def create_llm_client_for_legacy_tests(config: ApplicationConfig) -> LLMClient:
    """
    Legacy helper: returns the live OpenAI client only.

    DETERMINISTIC_PLANNER no longer changes this function. Prefer
    resolve_stage_llm_clients() for composition.
    """
    return create_live_llm_client(config)
