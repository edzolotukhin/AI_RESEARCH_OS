from __future__ import annotations

from dataclasses import dataclass

from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.sources.provenance_merge import merge_refs


@dataclass(frozen=True)
class RunScopedSourceContext:
    """Authoritative run/design semantic scope for evidence from a shared Source."""

    workflow_run_id: str
    research_design_id: str
    information_need_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    query_ids: tuple[str, ...]


def _need_id_from_query_id(query_id: str) -> str | None:
    if query_id.startswith("sq-"):
        return query_id[3:]
    return None


def _records_for_run_design(
    source: Source,
    *,
    workflow_run_id: str,
    research_design_id: str,
) -> list[dict]:
    return [
        record
        for record in (source.metadata.get("discovery_records") or [])
        if str(record.get("workflow_run_id")) == workflow_run_id
        and str(record.get("research_design_id")) == research_design_id
    ]


def resolve_run_scoped_context(
    *,
    source: Source,
    design: ResearchDesign,
    workflow_run_id: str,
    research_design_id: str,
) -> RunScopedSourceContext:
    """
    Derive run-scoped semantic refs from discovery_records for the current run.

    Aggregate Source ref arrays may include merged provenance from other runs;
    they are not used when per-run discovery records exist.
    """
    valid_needs = {need.id: need for need in design.information_needs}
    valid_questions = {question.id for question in design.research_questions}

    records = _records_for_run_design(
        source,
        workflow_run_id=workflow_run_id,
        research_design_id=research_design_id,
    )

    query_ids: tuple[str, ...] = ()
    need_ids: tuple[str, ...] = ()
    question_ids: tuple[str, ...] = ()

    if records:
        raw_query_ids: tuple[str, ...] = ()
        raw_need_ids: tuple[str, ...] = ()
        raw_question_ids: tuple[str, ...] = ()
        for record in records:
            query_id = str(record.get("query_id", "")).strip()
            if query_id:
                raw_query_ids = merge_refs(raw_query_ids, (query_id,))

            need_id = str(record.get("information_need_id", "")).strip()
            if not need_id and query_id:
                need_id = _need_id_from_query_id(query_id) or ""
            if need_id and need_id in valid_needs:
                raw_need_ids = merge_refs(raw_need_ids, (need_id,))

            question_id = str(record.get("research_question_id", "")).strip()
            if question_id and question_id in valid_questions:
                raw_question_ids = merge_refs(raw_question_ids, (question_id,))

        query_ids = raw_query_ids
        need_ids = raw_need_ids
        if raw_question_ids:
            question_ids = raw_question_ids
        else:
            for need_id in need_ids:
                need = valid_needs[need_id]
                if need.research_question_id in valid_questions:
                    question_ids = merge_refs(
                        question_ids,
                        (need.research_question_id,),
                    )
    elif (
        workflow_run_id in source.workflow_run_refs
        and research_design_id in source.research_design_refs
        and len(source.workflow_run_refs) == 1
        and len(source.research_design_refs) == 1
    ):
        need_ids = tuple(
            need_id
            for need_id in source.information_need_refs
            if need_id in valid_needs
        )
        query_ids = tuple(f"sq-{need_id}" for need_id in need_ids)
        for need_id in need_ids:
            need = valid_needs[need_id]
            if need.research_question_id in valid_questions:
                question_ids = merge_refs(question_ids, (need.research_question_id,))

    return RunScopedSourceContext(
        workflow_run_id=workflow_run_id,
        research_design_id=research_design_id,
        information_need_ids=need_ids,
        research_question_ids=question_ids,
        query_ids=query_ids,
    )
