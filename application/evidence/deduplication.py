from __future__ import annotations

import hashlib


def compute_deduplication_key(
    *,
    source_id: str,
    source_content_checksum: str,
    statement: str,
    source_excerpt: str,
    information_need_refs: tuple[str, ...],
) -> str:
    canonical = "|".join(
        [
            source_id,
            source_content_checksum,
            statement.strip(),
            source_excerpt.strip(),
            ",".join(sorted(information_need_refs)),
        ],
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
