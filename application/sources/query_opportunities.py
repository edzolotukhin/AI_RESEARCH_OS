"""Canonical execution feedback, not observational telemetry or a call budget."""
from dataclasses import replace
from hashlib import sha256
from application.sources.url_canonicalizer import normalize_query_text
from application.sources.expectation_aware_query_intent import render_aspect_query_terms

KEY = "research_executed_query_fingerprints"


def fingerprint(query):
    text = normalize_query_text(query.provider_query_text or query.query_text).casefold()
    return sha256((query.information_need_id + "\n" + text).encode()).hexdigest()


def focus_repeated_queries(queries, *, design, request, history):
    """Replace a repeated opportunity with a grounded aspect phrase, never add calls.

    Localized initial arms remain distinct provider strategies. On continuation,
    already dispatched text is not a new opportunity merely because its ID changed.
    """
    seen = set(history)
    need = next(n for n in design.information_needs if n.id == request.information_need_id)
    aspects = request.missing_aspects or (
        need.evidence_expectation.required_aspects if need.evidence_expectation else ()
    )
    selected = []
    for query in queries:
        if fingerprint(query) not in seen:
            selected.append(query)
            seen.add(fingerprint(query))
            continue
        for aspect in aspects:
            phrase = render_aspect_query_terms(aspect).replace('"', '').strip()
            if not phrase:
                continue
            # Exact aspect phrase is a meaningful retrieval constraint, unlike
            # a new ordinal, whitespace change or arbitrary query suffix.
            text = normalize_query_text(f'{query.query_text} "{phrase}"')
            candidate = replace(query, provider_query_text=text)
            if fingerprint(candidate) not in seen:
                selected.append(candidate)
                seen.add(fingerprint(candidate))
                break
    return selected
