"""Conservative subject continuity at the candidate-to-Evidence boundary.

IDs and an exact quote prove provenance, not relevance. Generic research/aspect
vocabulary cannot establish the subject of an explicitly specified need.
This is a deterministic negative guard, not a semantic sufficiency evaluator.
"""
import re

from application.sources.category_subject import _NON_SUBJECT_WORDS

_GENERIC = _NON_SUBJECT_WORDS | frozenset("""
    a an as at be been being by can do does each evidence fact facts find given
    has have in into is it its may must not of on only or other per same should
    than that their these they this those to under use used using was were when
    will within would relevant require required requirement requirements
    document documented documentation describe description include includes
    count counts value values total dated date dates period periods year years
    definition definitions defined term terms terminology method methodology
    methodological measure measurement metric metrics scheme basis note notes
    source sources feed feeds dependency dependencies cutoff cutoffs cut off
    alignment aligned comparable comparability comparison compare comparing
    limitation limitations sensitive questions question unanswered unsupported
    inconsistency inconsistencies arising different differing divergence
    catalog commercial commercially sensitive available public reported report
    reporting disclosure disclosures quantitative qualitative signal signals
    scope sample regional region regions geography country countries latest
    desk linked objective objectives coverage
    distribution change changes observed observation observations about between
""".split())


def _tokens(text):
    return {word.rstrip("s") for word in re.findall(r"[^\W\d_]+", text.casefold())
            if len(word) >= 3 and word not in _GENERIC}


def relevant_need_refs(candidate, *, design):
    """Validate each proposed IN independently; never force the primary target.

    Legacy needs without explicit expectations retain their established contract.
    Generic/thin descriptions cannot supply a reliable negative subject verdict.
    Neither URLs, publisher titles nor extractor metadata can certify relevance.
    """
    questions = {q.id: q for q in design.research_questions}
    needs = {n.id: n for n in design.information_needs}
    claim = _tokens(candidate.statement)
    excerpt = _tokens(candidate.source_excerpt)
    retained = []
    for ref in candidate.information_need_refs:
        need = needs[ref]
        if need.evidence_expectation is None:
            retained.append(ref)
            continue
        anchors = _tokens(need.description)
        # Geography/time and abstract aspect labels are not subject identity.
        anchors -= _tokens(need.geography + " " + need.timeframe)
        question = questions.get(need.research_question_id)
        if question is not None:
            shared = anchors & _tokens(question.question)
            if shared:
                anchors = shared
        if not anchors or (anchors & claim and anchors & excerpt):
            retained.append(ref)
    return tuple(retained)
