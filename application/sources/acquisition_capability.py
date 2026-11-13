"""Pure capability decisions; no network or Evidence qualification side effects."""
from dataclasses import dataclass

ACQUISITION_CAPABILITY = "bounded-navigation-v2"
TEXT_EXTRACTION_CAPABILITY = "html-text-v1"
TABLE_EXTRACTION_CAPABILITY = "xlsx-structured-v2"


@dataclass(frozen=True)
class AcquisitionDecision:
    action: str
    reason: str
    resource_kind: str


def decide_acquisition(source, *, structured=False, research_design_id="",
                       extraction_revision=TABLE_EXTRACTION_CAPABILITY, force_refetch=False):
    kind = "table" if structured else "text"
    if source is None:
        return AcquisitionDecision("REFETCH", "not_acquired", kind)
    if force_refetch:
        return AcquisitionDecision("REFETCH", "explicit_refresh", kind)
    if source.retrieval_status.value not in {"acquired", "truncated"}:
        return AcquisitionDecision("REFETCH", "previous_acquisition_failed", kind)
    if structured:
        if not source.metadata.get("structured_rows"):
            return AcquisitionDecision("REFETCH", "table_capability_missing", kind)
        if source.extraction_revision != extraction_revision:
            return AcquisitionDecision("REEXTRACT", "extraction_capability_changed", kind)
    if research_design_id and research_design_id not in source.research_design_refs:
        return AcquisitionDecision("REVALIDATE", "new_design_scope", kind)
    return AcquisitionDecision("REUSE", "capability_sufficient", kind)
