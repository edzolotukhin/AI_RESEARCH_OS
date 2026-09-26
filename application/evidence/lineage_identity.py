"""Conservative identity for grounded underlying provenance, never fuzzy names."""
import re
import unicodedata


def canonical_lineage_identity(lineage: object) -> str:
    if not isinstance(lineage, dict) or lineage.get("status") != "established":
        return ""
    origin = lineage.get("origin_id")
    if not isinstance(origin, str):
        return ""
    normalized = " ".join(unicodedata.normalize("NFKC", origin).casefold().split())
    # A grounded explicit upstream attribution is an identity relation, not a
    # similarity heuristic. Do not strip dataset names, legal suffixes or URLs.
    basis = lineage.get("basis_excerpt")
    if isinstance(basis, str):
        grounded = " ".join(unicodedata.normalize("NFKC", basis).casefold().split())
        if normalized and normalized in grounded:
            match = re.fullmatch(r".+,\s*sourced from\s+([^,;]+)", normalized)
            if match:
                normalized = match.group(1).strip()
    return normalized
