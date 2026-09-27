"""Explicitly construct real synthetic sources for non-citation unit fixtures.

Never use on persisted acceptance records or in tests of malformed citations.
This is fixture setup, not a mock of the production integrity decision.
"""
from hashlib import sha256
from application.evidence.grounding import verify_grounding
from domain.sources.source import Source
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository


def sources_for(evidence, repository=None):
    repository = repository if repository is not None else InMemorySourceRepository()
    groups = {}
    for item in evidence:
        groups.setdefault(item.source_id, []).append(item)
    for source_id, items in groups.items():
        text = "\n".join(dict.fromkeys(e.source_excerpt for e in items))
        checksum = sha256(text.encode()).hexdigest()
        source = Source(source_id, items[0].project_id, "https://fixture.test/" + source_id,
            "https://fixture.test/" + source_id, "Synthetic fixture", "2026-01-01",
            content_text=text, content_checksum=checksum,
            workflow_run_refs=tuple(dict.fromkeys(e.workflow_run_id for e in items)))
        if repository.get_by_id(source_id) is None:
            repository.create(source)
        else:
            repository.save(source)
        for item in items:
            item.source_content_checksum = checksum
            item.source_locator = verify_grounding(source_text=text, excerpt=item.source_excerpt).to_dict()
    return repository
