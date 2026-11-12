"""Explicitly construct real synthetic sources for non-citation unit fixtures.

Never use on persisted acceptance records or in tests of malformed citations.
This is fixture setup, not a mock of the production integrity decision.
"""
from hashlib import sha256
from dataclasses import replace
from uuid import uuid4
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
        existing = repository.get_by_id(source_id)
        if existing is None:
            repository.create(source)
        elif existing.content_text == text and existing.content_checksum == checksum:
            source = existing
        else:
            # Fixture initialization is acquisition too: never rewrite the
            # historical snapshot or manufacture identity fields for save().
            source = repository.create_immutable_revision(replace(existing,
                id=str(uuid4()), content_text=text, content_checksum=checksum,
                raw_checksum_kind="legacy-surrogate", raw_content_checksum="",
                workflow_run_refs=source.workflow_run_refs))
        for item in items:
            item.source_id = source.id
            item.source_content_checksum = checksum
            item.source_locator = verify_grounding(source_text=text, excerpt=item.source_excerpt).to_dict()
    return repository
