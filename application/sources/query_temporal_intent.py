"""Resolve only material observation constraints, independently of telemetry."""
import re


def observation_window(need, brief):
    timeframe = need.timeframe or ""
    if re.search(r"\b(?:19|20)\d{2}\b", timeframe):
        return timeframe
    expectation = need.evidence_expectation
    material = bool(expectation and expectation.requires_quantitative_evidence) or bool(
        re.search(r"\b(dated|deployment|opening|change|trend|measurement|observation)s?\b",
                  need.description, re.I)
    )
    if material and brief is not None:
        # Availability/publication clauses are not the observation interval.
        return re.split(r";|(?=\bsources?\s+(?:available|published|retrieved)\b)",
                        brief.timeframe, maxsplit=1, flags=re.I)[0].strip()
    return ""
