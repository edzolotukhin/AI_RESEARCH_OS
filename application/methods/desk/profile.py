"""Non-secret immutable execution profile pinned at new Desk activation."""
from dataclasses import fields

MARKER = "research_kernel"
PIN = "_research_execution_v1"


def profile(config):
    names = {f.name for f in fields(config) if f.name.startswith((
        "source_", "evidence_", "sufficiency_", "targeted_", "research_max_"))}
    names.update(("llm_model", "llm_max_tokens", "llm_max_calls_per_run", "analysis_max_llm_calls",
                  "report_max_llm_calls", "review_max_calls", "search_provider", "research_sufficiency_assessor"))
    return {name: getattr(config, name) for name in sorted(names)}


def template_marker(template):
    values = [definition.metadata[MARKER] for definition in template.task_definitions
              if MARKER in definition.metadata]
    if not values:
        return None
    if any(value != values[0] for value in values):
        raise ValueError("mixed research execution versions")
    value = values[0]
    if value.get("version") != 1 or not isinstance(value.get("profile"), dict):
        raise ValueError("unsupported research execution version")
    return value
