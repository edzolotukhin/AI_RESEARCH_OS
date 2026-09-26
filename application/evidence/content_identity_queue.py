"""Collapse URL aliases before paid extraction; retain scoped semantic refs."""
from dataclasses import replace

from application.sources.content_identity import acquired_content_identity
from application.sources.provenance_merge import merge_refs


def distinct_content_queue(queue):
    representatives = {}
    contexts = {}
    aliases = {}
    for item in queue:
        identity = acquired_content_identity(item.source) or "source:" + item.source.id
        representatives.setdefault(identity, item.source.id)
        contexts.setdefault(identity, item.run_context)
        context = contexts[identity]
        contexts[identity] = replace(context,
            information_need_ids=merge_refs(context.information_need_ids, item.run_context.information_need_ids),
            research_question_ids=merge_refs(context.research_question_ids, item.run_context.research_question_ids),
            query_ids=merge_refs(context.query_ids, item.run_context.query_ids))
        aliases.setdefault(identity, {})[item.source.id] = item.source.url
    result = []
    for item in queue:
        identity = acquired_content_identity(item.source) or "source:" + item.source.id
        if representatives[identity] != item.source.id:
            continue
        if len(aliases[identity]) == 1:
            result.append(item)
            continue
        source = replace(item.source, metadata={**item.source.metadata,
            "content_aliases": [{"source_id": sid, "url": url} for sid, url in aliases[identity].items()]})
        result.append(replace(item, source=source, run_context=contexts[identity]))
    return result
