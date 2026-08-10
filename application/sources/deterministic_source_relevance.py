"""Deterministic post-retrieval source eligibility (P1-07.14.1).

Not a second quality contract. EvidenceExpectation remains authoritative for
Sufficiency. This module only decides which provider candidates are worth
fetching, using tokens already present on the ResearchDesign / SearchQuery /
SourceCandidate.

Tiers:
- direct: topic overlap with context anchors and matching geography tokens
- proxy: topic overlap with weaker/unknown/broader geography
- ineligible: positive evidence of unrelated/conflicting topic
  (generic contract-language overlap without distinctive parent topic)
- unscored: no positive topic signal, or context too thin — remain fetchable

Absence of lexical overlap is not treated as demonstrated unrelatedness.
Candidate fields used: title, snippet/content preview, URL/domain.
Provider metadata (including score) is not tokenized.

Geography is never an absolute hard gate. Broad scale/region language is a
proxy, not a rejection. A conflicting named place cannot outrank direct/proxy
on provider rank alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.source_candidate import SourceCandidate

from application.sources.expectation_aware_query_intent import render_aspect_query_terms
from application.sources.url_canonicalizer import normalize_query_text

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "analysis",
        "and",
        "are",
        "available",
        "been",
        "before",
        "between",
        "compile",
        "current",
        "data",
        "define",
        "document",
        "does",
        "estimate",
        "focus",
        "for",
        "from",
        "growth",
        "guide",
        "have",
        "html",
        "http",
        "https",
        "identify",
        "indicative",
        "industry",
        "information",
        "into",
        "latest",
        "market",
        "more",
        "most",
        "need",
        "needs",
        "only",
        "other",
        "outlook",
        "overview",
        "pdf",
        "prioritize",
        "question",
        "report",
        "reports",
        "share",
        "size",
        "snippet",
        "some",
        "study",
        "such",
        "summarize",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "this",
        "through",
        "title",
        "trend",
        "trends",
        "typical",
        "using",
        "what",
        "when",
        "which",
        "with",
        "www",
        "year",
        "years",
    }
)

# Research-contract / process language. Not a product taxonomy: these tokens
# come from EE aspect identifiers and generic IN wording and must not alone
# make an off-topic page look aligned with the parent research question.
_GENERIC_CONTRACT_WORDS = frozenset(
    {
        "attributes",
        "benchmarks",
        "buyer",
        "buyers",
        "certification",
        "certifications",
        "channel",
        "channels",
        "criteria",
        "decision",
        "expectations",
        "format",
        "formats",
        "lead",
        "level",
        "milestones",
        "moq",
        "moqs",
        "options",
        "positioning",
        "process",
        "procurement",
        "quality",
        "reliability",
        "requirements",
        "rollout",
        "route",
        "service",
        "specs",
        "specification",
        "specifications",
        "strategy",
        "targeting",
        "times",
        "weighting",
    }
)

_SCALE_WORDS = frozenset(
    {
        "global",
        "globally",
        "international",
        "internationally",
        "world",
        "worldwide",
        "regional",
        "regionally",
    }
)

_BROAD_REGION_WORDS = frozenset(
    {
        "africa",
        "african",
        "america",
        "americas",
        "asia",
        "asian",
        "balkans",
        "caribbean",
        "cee",
        "easterneurope",
        "eu",
        "eurasia",
        "europe",
        "european",
        "latam",
        "mediterranean",
        "oceania",
        "see",
        "westerneurope",
    }
)

# Named-place hints for conflicting-geography detection only. Not a product
# taxonomy and not a Sufficiency geography model.
_NAMED_PLACE_HINTS = frozenset(
    {
        "algeria",
        "argentina",
        "australia",
        "austria",
        "belgium",
        "brazil",
        "bulgaria",
        "canada",
        "chile",
        "china",
        "colombia",
        "croatia",
        "czechia",
        "denmark",
        "egypt",
        "estonia",
        "ethiopia",
        "finland",
        "france",
        "germany",
        "ghana",
        "greece",
        "hungary",
        "india",
        "indonesia",
        "ireland",
        "israel",
        "italy",
        "japan",
        "kenya",
        "latvia",
        "lithuania",
        "malaysia",
        "mexico",
        "morocco",
        "netherlands",
        "nigeria",
        "norway",
        "pakistan",
        "peru",
        "philippines",
        "poland",
        "portugal",
        "romania",
        "russia",
        "serbia",
        "singapore",
        "slovakia",
        "slovenia",
        "southafrica",
        "southkorea",
        "spain",
        "sweden",
        "switzerland",
        "tanzania",
        "thailand",
        "turkey",
        "uganda",
        "ukraine",
        "unitedkingdom",
        "unitedstates",
        "vietnam",
        "zambia",
    }
)

ELIGIBILITY_DIRECT = "direct"
ELIGIBILITY_PROXY = "proxy"
ELIGIBILITY_INELIGIBLE = "ineligible"
ELIGIBILITY_UNSCORED = "unscored"

GEO_DIRECT = "direct"
GEO_PROXY = "proxy"
GEO_UNRELATED = "unrelated"
GEO_UNKNOWN = "unknown"

ACTION_SELECTED = "selected"
ACTION_PROXY = "proxy_deprioritized"
ACTION_REJECTED = "unrelated_rejected"
ACTION_EXHAUSTED = "exhausted_for_need"
ACTION_SKIPPED_BUDGET = "skipped_budget"
ACTION_FETCH_FAILED = "fetch_failed"

_MIN_DISTINCTIVE_ANCHORS = 2


def tokenize(text: str, *, min_length: int = 4) -> frozenset[str]:
    if not text:
        return frozenset()
    normalized = normalize_query_text(str(text)).casefold()
    return frozenset(
        token
        for token in _TOKEN_RE.findall(normalized)
        if len(token) >= min_length and token not in _STOPWORDS
    )


def geography_tokens(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()
    normalized = normalize_query_text(str(text)).casefold().replace("/", " ")
    return frozenset(
        token
        for token in _TOKEN_RE.findall(normalized)
        if len(token) >= 3 and token not in _STOPWORDS
    )


@dataclass(frozen=True)
class RelevanceContext:
    information_need_id: str
    research_question_id: str
    need_tokens: frozenset[str]
    rq_tokens: frozenset[str]
    rq_only_tokens: frozenset[str]
    topic_anchors: frozenset[str]
    required_geo_tokens: frozenset[str]
    has_distinctive_anchors: bool
    legacy_expectation: bool


@dataclass(frozen=True)
class SourceRelevanceDecision:
    eligibility: str
    geo_alignment: str
    topic_score: int
    rq_overlap: int
    need_overlap: int
    reason: str
    information_need_id: str
    provider_rank: int

    @property
    def is_fetch_eligible(self) -> bool:
        return self.eligibility != ELIGIBILITY_INELIGIBLE

    @property
    def tier_rank(self) -> int:
        if self.eligibility == ELIGIBILITY_DIRECT:
            return 3
        if self.eligibility in {ELIGIBILITY_PROXY, ELIGIBILITY_UNSCORED}:
            return 2
        return 0

    @property
    def geo_penalty(self) -> int:
        return {
            GEO_DIRECT: 0,
            GEO_UNKNOWN: 1,
            GEO_PROXY: 2,
            GEO_UNRELATED: 3,
        }.get(self.geo_alignment, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligibility": self.eligibility,
            "geo_alignment": self.geo_alignment,
            "topic_score": self.topic_score,
            "rq_overlap": self.rq_overlap,
            "need_overlap": self.need_overlap,
            "reason": self.reason,
            "information_need_id": self.information_need_id,
            "provider_rank": self.provider_rank,
        }


def build_relevance_context(
    design: ResearchDesign,
    need: InformationNeed,
) -> RelevanceContext:
    question = _question_for_need(design, need)
    rq_text_parts = []
    if question is not None:
        rq_text_parts.extend(
            [question.question, question.rationale, " ".join(question.objective_refs)]
        )
    rq_tokens = tokenize(" ".join(rq_text_parts))

    aspect_text = ""
    geo_text = need.geography
    time_text = need.timeframe
    legacy = need.evidence_expectation is None
    if need.evidence_expectation is not None:
        ee = need.evidence_expectation
        aspect_text = " ".join(
            render_aspect_query_terms(aspect) for aspect in ee.required_aspects
        )
        if ee.geography:
            geo_text = ee.geography
        if ee.timeframe:
            time_text = ee.timeframe

    need_tokens = tokenize(
        " ".join(
            part
            for part in (need.description, aspect_text, geo_text or "", time_text or "")
            if part
        )
    )
    required_geo = geography_tokens(geo_text)
    rq_only = rq_tokens - need_tokens
    topic_anchors = rq_tokens | need_tokens | required_geo
    distinctive = frozenset(
        token
        for token in (topic_anchors - required_geo)
        if not token.isdigit() and token not in _GENERIC_CONTRACT_WORDS
    )
    return RelevanceContext(
        information_need_id=need.id,
        research_question_id=need.research_question_id,
        need_tokens=need_tokens,
        rq_tokens=rq_tokens,
        rq_only_tokens=rq_only,
        topic_anchors=topic_anchors,
        required_geo_tokens=required_geo,
        has_distinctive_anchors=len(distinctive) >= _MIN_DISTINCTIVE_ANCHORS,
        legacy_expectation=legacy,
    )


def evaluate_candidate(
    context: RelevanceContext,
    candidate: SourceCandidate,
    *,
    canonical_url: str = "",
) -> SourceRelevanceDecision:
    blob = _candidate_blob(candidate, canonical_url)
    candidate_tokens = tokenize(blob) | geography_tokens(blob)
    rq_overlap = len(context.rq_tokens & candidate_tokens)
    need_overlap = len(context.need_tokens & candidate_tokens)
    anchor_overlap = len(context.topic_anchors & candidate_tokens)
    geo_alignment = _classify_geography(context.required_geo_tokens, candidate_tokens)
    provider_rank = int(candidate.rank or 0)

    if not context.has_distinctive_anchors or context.legacy_expectation:
        reason = (
            "legacy_ee_none_rank_compatible"
            if context.legacy_expectation
            else "thin_context_unscored_rank_fallback"
        )
        eligibility = ELIGIBILITY_UNSCORED
        if context.legacy_expectation and anchor_overlap > 0:
            eligibility = (
                ELIGIBILITY_DIRECT
                if geo_alignment == GEO_DIRECT
                else ELIGIBILITY_PROXY
            )
            reason = f"legacy_topic_aligned_geo_{geo_alignment}"
        return SourceRelevanceDecision(
            eligibility=eligibility,
            geo_alignment=geo_alignment,
            topic_score=anchor_overlap,
            rq_overlap=rq_overlap,
            need_overlap=need_overlap,
            reason=reason,
            information_need_id=context.information_need_id,
            provider_rank=provider_rank,
        )

    topic_signal = frozenset(
        token
        for token in (
            context.topic_anchors - context.required_geo_tokens - _GENERIC_CONTRACT_WORDS
        )
        if not token.isdigit()
    )
    distinctive_overlap = len(topic_signal & candidate_tokens)
    generic_contract_overlap = candidate_tokens & _GENERIC_CONTRACT_WORDS & (
        context.need_tokens | context.topic_anchors
    )
    if (
        context.has_distinctive_anchors
        and distinctive_overlap == 0
        and generic_contract_overlap
    ):
        return SourceRelevanceDecision(
            eligibility=ELIGIBILITY_INELIGIBLE,
            geo_alignment=geo_alignment,
            topic_score=need_overlap,
            rq_overlap=rq_overlap,
            need_overlap=need_overlap,
            reason="generic_local_overlap_without_parent_topic",
            information_need_id=context.information_need_id,
            provider_rank=provider_rank,
        )

    if distinctive_overlap == 0 and context.has_distinctive_anchors:
        return SourceRelevanceDecision(
            eligibility=ELIGIBILITY_UNSCORED,
            geo_alignment=geo_alignment,
            topic_score=0,
            rq_overlap=rq_overlap,
            need_overlap=need_overlap,
            reason="no_positive_topic_signal_unscored",
            information_need_id=context.information_need_id,
            provider_rank=provider_rank,
        )

    topic_score = (rq_overlap * 3) + need_overlap + len(
        context.required_geo_tokens & candidate_tokens
    )
    if geo_alignment == GEO_DIRECT and rq_overlap + need_overlap > 0:
        eligibility = ELIGIBILITY_DIRECT
        reason = "topic_and_geography_aligned"
    else:
        eligibility = ELIGIBILITY_PROXY
        reason = f"topic_aligned_geo_{geo_alignment}"

    return SourceRelevanceDecision(
        eligibility=eligibility,
        geo_alignment=geo_alignment,
        topic_score=topic_score,
        rq_overlap=rq_overlap,
        need_overlap=need_overlap,
        reason=reason,
        information_need_id=context.information_need_id,
        provider_rank=provider_rank,
    )


def selection_sort_key(
    *,
    decision: SourceRelevanceDecision,
    need_coverage: int,
    best_rank: int,
    canonical_url: str,
) -> tuple:
    return (
        -decision.tier_rank,
        -need_coverage,
        -decision.topic_score,
        decision.geo_penalty,
        best_rank,
        canonical_url,
    )


def _classify_geography(
    required: frozenset[str],
    candidate_tokens: frozenset[str],
) -> str:
    if not required:
        return GEO_UNKNOWN
    if required & candidate_tokens:
        return GEO_DIRECT
    if candidate_tokens & _SCALE_WORDS or candidate_tokens & _BROAD_REGION_WORDS:
        return GEO_PROXY
    named = candidate_tokens & _NAMED_PLACE_HINTS
    if named and not named & required:
        return GEO_UNRELATED
    return GEO_UNKNOWN


def _candidate_blob(candidate: SourceCandidate, canonical_url: str) -> str:
    host = ""
    raw_url = canonical_url or candidate.url or ""
    try:
        host = urlparse(raw_url).netloc
    except ValueError:
        host = ""
    return " ".join(
        part
        for part in (
            candidate.title or "",
            candidate.snippet or "",
            raw_url.replace("/", " ").replace("-", " ").replace("_", " ").replace(".", " "),
            host.replace(".", " "),
        )
        if part
    )


def _question_for_need(
    design: ResearchDesign,
    need: InformationNeed,
) -> ResearchQuestion | None:
    for question in design.research_questions:
        if question.id == need.research_question_id:
            return question
    return None
