"""Conservative observation-period eligibility for a dated Desk brief.

Publication time is deliberately not an input. A later publication can report
an earlier observation; a published source cannot make a later observation
in-period. Unknown periods remain stored but do not qualify for dated needs.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import replace
from datetime import date
from typing import Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign
from domain.research_brief import ResearchBrief

_MONTHS = {name.casefold(): index for index, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.casefold(): index for index, name in enumerate(calendar.month_abbr) if name})
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(20\d{2})-(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])\b")
_DAY_MONTH = re.compile(rf"\b([1-9]|[12]\d|3[01])\s+({_MONTH_PATTERN})\s+(20\d{{2}})\b", re.I)
_MONTH_YEAR = re.compile(rf"\b({_MONTH_PATTERN})\s+(20\d{{2}})\b", re.I)
_QUARTER = re.compile(r"\bQ([1-4])\s+(20\d{2})\b", re.I)
_YEAR = re.compile(r"\b20\d{2}\b")
_QUARTER_WORDS = {"first": "1", "second": "2", "third": "3", "fourth": "4"}


def normalize_observation_period(text: str) -> str:
    """Normalize explicit calendar quarters; never mine surrounding prose."""
    text = " ".join(text.split())
    text = re.sub(r"\b(first|second|third|fourth) quarter(?: of)? (20\d{2})\b",
                  lambda m: f"Q{_QUARTER_WORDS[m[1].lower()]} {m[2]}", text, flags=re.I)
    return re.sub(r"\b(20\d{2})\s+Q([1-4])\b", r"Q\2 \1", text, flags=re.I)


def observation_interval(text: str) -> tuple[date, date] | None:
    """Only complete supported periods or explicit ranges are authoritative."""
    text = normalize_observation_period(text)
    atom = rf"(?:20\d{{2}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}} (?:{_MONTH_PATTERN}) 20\d{{2}}|(?:{_MONTH_PATTERN}) 20\d{{2}}|Q[1-4] 20\d{{2}}|20\d{{2}})"
    match = re.fullmatch(rf"({atom})(?:\s*(?:to|through|–|—)\s*({atom}))?", text, re.I)
    if match is None:
        return None
    endpoints = []
    for part in (match[1], match[2] or match[1]):
        periods = _periods(part)
        if len(periods) != 1:
            return None
        if (re.fullmatch(r"20\d{2}-\d{1,2}-\d{1,2}", part) or
                re.fullmatch(rf"\d{{1,2}} (?:{_MONTH_PATTERN}) 20\d{{2}}", part, re.I)) and not periods[0][2]:
            return None
        endpoints.append(periods[0])
    if endpoints[0][0] > endpoints[1][1]:
        return None
    return endpoints[0][0], endpoints[1][1]
_STATIC_NEED = re.compile(
    r"\b(defin\w*|terminolog\w*|methodolog\w*|classif\w*|categor\w*|"
    r"distinction\w*|comparab\w*|taxonomy|connector\w*|site.type\w*)\b",
    re.I,
)
_STATIC_CLAIM = re.compile(
    r"\b(?:defined as|definition of|refers to|means|classified as|"
    r"classification of|methodology for|method for|categor(?:y|ies|ised|ized)|"
    r"a charging device is|a connector is|a charging site is)\b",
    re.I,
)
_TIME_SENSITIVE_CLAIM = re.compile(
    r"\b(?:there (?:are|were)|number of|count of|total (?:of|was|is)|"
    r"increas\w*|decreas\w*|grew|growth|declin\w*|share of|"
    r"percent(?:age)?|observed|recorded|installed|operat(?:ed|ing)|"
    r"forecast|projected|as at|as of)\b|\b\d[\d,]*\s*(?:chargers?|devices?|sites?|%)\b",
    re.I,
)


def _periods(text: str) -> list[tuple[date, date, bool]]:
    """Return start, end and exact-day flag, without double-reading years."""
    found: list[tuple[date, date, bool]] = []
    occupied: set[int] = set()

    def add(match: re.Match[str], start: date, end: date, exact: bool) -> None:
        found.append((start, end, exact))
        occupied.update(range(*match.span()))

    for match in _ISO.finditer(text):
        try:
            day = date(*(int(part) for part in match.groups()))
        except ValueError:
            continue
        add(match, day, day, True)
    for match in _DAY_MONTH.finditer(text):
        if any(index in occupied for index in range(*match.span())):
            continue
        try:
            day = date(int(match[3]), _MONTHS[match[2].casefold()], int(match[1]))
        except ValueError:
            continue
        add(match, day, day, True)
    for match in _MONTH_YEAR.finditer(text):
        if any(index in occupied for index in range(*match.span())):
            continue
        year, month = int(match[2]), _MONTHS[match[1].casefold()]
        add(match, date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), False)
    for match in _QUARTER.finditer(text):
        if any(index in occupied for index in range(*match.span())):
            continue
        year, first_month = int(match[2]), 3 * (int(match[1]) - 1) + 1
        last_month = first_month + 2
        add(match, date(year, first_month, 1), date(year, last_month, calendar.monthrange(year, last_month)[1]), False)
    for match in _YEAR.finditer(text):
        if any(index in occupied for index in range(*match.span())):
            continue
        year = int(match.group())
        add(match, date(year, 1, 1), date(year, 12, 31), False)
    return found


def exact_observation_cutoff(brief: ResearchBrief | None) -> date | None:
    """Only an explicit day in the frozen timeframe activates a day cutoff."""
    if brief is None:
        return None
    # Publication-availability clauses describe when documents could be read,
    # not when the observed state applies. The frozen observation interval is
    # the first timeframe clause; never promote a later availability date.
    observation_clause = re.split(
        r";|(?=\bsources?\s+(?:available|published|retrieved)\b)",
        brief.timeframe, maxsplit=1, flags=re.I,
    )[0]
    exact = [end for _, end, is_exact in _periods(observation_clause) if is_exact]
    return max(exact, default=None)


def observation_eligibility(evidence: Evidence, cutoff: date, *, start: date | None = None) -> str:
    """eligible, out_of_period, or unknown; never infer from publication date."""
    reference = evidence.metadata.get("observation_period")
    if not isinstance(reference, str) or not reference.strip():
        # A grounded, leading as-of clause in BOTH canonical claim and excerpt
        # explicitly binds the observation. Never search arbitrary body dates,
        # source publication metadata, or infer from a date elsewhere in prose.
        exact_date = rf"(?:20\d{{2}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}\s+(?:{_MONTH_PATTERN})\s+20\d{{2}})"
        pattern = rf"^\s*as of\s+({exact_date})(?=[,:\s])"
        claim = re.match(pattern, evidence.statement, re.I)
        excerpt = re.match(pattern, evidence.source_excerpt, re.I)
        if not claim or not excerpt:
            return "unknown"
        observation = r"^\s*[, :]?\s*(?:in [^.;:]+?\s+)?(?:there (?:were|was)|measured|recorded|stood at|totalled|totaled)\b"
        if not re.search(observation, evidence.statement[claim.end():], re.I) or not re.search(observation, evidence.source_excerpt[excerpt.end():], re.I):
            return "unknown"
        if re.search(r"\b(?:published|publication|released|forecast|projected)\b", evidence.statement, re.I):
            return "unknown"
        reference = claim[1].strip()
        if reference.casefold() != excerpt[1].strip().casefold():
            return "unknown"
        exact = _periods(reference)
        if len(exact) != 1 or not exact[0][2]:
            return "unknown"
    # An extractor-supplied period is usable only when grounded in the actual
    # source excerpt. Free-form model metadata alone cannot establish a date.
    if " ".join(reference.casefold().split()) not in " ".join(evidence.source_excerpt.casefold().split()):
        return "unknown"
    excerpt = " ".join(evidence.source_excerpt.casefold().split())
    occurrences = list(re.finditer(re.escape(" ".join(reference.casefold().split())), excerpt))
    if occurrences and all(re.search(r"(?:published|released|publication date)\s*(?:on|:)?\s*$",
                                     excerpt[:match.start()]) for match in occurrences):
        return "unknown"
    interval = observation_interval(reference)
    if interval is None:
        return "unknown"
    if interval[1] > cutoff or (start is not None and interval[0] < start):
        return "out_of_period"
    if re.search(r"\b(forecast|projection|predicted|expected by)\b", evidence.source_excerpt, re.I):
        return "unknown"
    return "eligible"


def temporal_eligibility(
    evidence: Evidence, need: InformationNeed, cutoff: date, *, start: date | None = None,
) -> str:
    """Claim/need-specific state; source metadata cannot waive a dated claim."""
    claim = f"{evidence.statement} {evidence.source_excerpt}"
    need_text = " ".join((
        need.description,
        *(need.evidence_expectation.required_aspects
          if need.evidence_expectation is not None else ()),
    ))
    if (
        _STATIC_NEED.search(need_text)
        and _STATIC_CLAIM.search(claim)
        and not _TIME_SENSITIVE_CLAIM.search(claim)
        and not evidence.metadata.get("observation_period")
    ):
        return "not_applicable"
    status = observation_eligibility(evidence, cutoff, start=start)
    return {
        "eligible": "applicable_satisfied",
        "out_of_period": "applicable_failed",
        "unknown": "applicable_unresolved",
    }[status]


def qualifying_evidence(
    *,
    design: ResearchDesign,
    evidence: Sequence[Evidence],
    brief: ResearchBrief | None,
) -> tuple[Evidence, ...]:
    """Retain only in-period need references for an explicitly dated brief."""
    from application import research_funnel_telemetry as funnel
    cutoff = exact_observation_cutoff(brief)
    start = None
    if brief is not None:
        clause = re.split(r";|(?=\bsources?\s+(?:available|published|retrieved)\b)",
                          brief.timeframe, maxsplit=1, flags=re.I)[0].strip()
        boundary = observation_interval(clause)
        if boundary is not None:
            start, cutoff = boundary
    if cutoff is None:
        for item in evidence:
            for ref in item.information_need_refs:
                funnel.qualification(item.id, ref, True, "no_exact_cutoff")
        return tuple(evidence)
    # A dated frozen Brief is a run-wide observation contract. An omitted
    # per-need timeframe does not silently waive it.
    needs_by_id = {need.id: need for need in design.information_needs}
    filtered: list[Evidence] = []
    for item in evidence:
        kept = []
        for ref in item.information_need_refs:
            reason = temporal_eligibility(item, needs_by_id[ref], cutoff, start=start) if ref in needs_by_id else "unknown_need_passthrough"
            qualifies = reason in {"applicable_satisfied", "not_applicable", "unknown_need_passthrough"}
            funnel.qualification(item.id, ref, qualifies, reason)
            if qualifies:
                kept.append(ref)
        refs = tuple(kept)
        if refs:
            filtered.append(replace(item, information_need_refs=refs))
    return tuple(filtered)
