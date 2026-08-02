from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.content_chunking import (
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS,
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS,
)
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.executors.evidence_executor import EvidenceExecutor
from application.ports.evidence_ports import EvidenceExtractor, EvidenceRepository
from application.ports.source_ports import SourceRepository
from infrastructure.evidence.deterministic_evidence_extractor import (
    DeterministicEvidenceExtractor,
)
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor


def build_evidence_extractor(
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    *,
    llm_client,
) -> EvidenceExtractor:
    if overrides.evidence_extractor is not None:
        inner = overrides.evidence_extractor
    else:
        provider_name = config.evidence_extractor.lower()
        if provider_name == "deterministic":
            inner = DeterministicEvidenceExtractor()
        elif provider_name == "llm":
            if llm_client is None:
                raise ValueError("LLM client is required for EVIDENCE_EXTRACTOR=llm")
            inner = LlmEvidenceExtractor(llm_client=llm_client)
        else:
            raise ValueError(
                f"Unsupported EVIDENCE_EXTRACTOR: {provider_name!r}. "
                "Expected one of: llm, deterministic.",
            )

    return ChunkedEvidenceExtractor(
        inner,
        chunk_chars=config.evidence_extraction_chunk_chars,
        overlap_chars=config.evidence_extraction_chunk_overlap_chars,
    )


def build_evidence_extraction_service(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    source_repository: SourceRepository,
    llm_client,
) -> EvidenceExtractionService:
    return EvidenceExtractionService(
        evidence_extractor=build_evidence_extractor(
            config,
            overrides,
            llm_client=llm_client,
        ),
        evidence_repository=evidence_repository,
        source_repository=source_repository,
    )


def build_evidence_executor(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    source_repository: SourceRepository,
    llm_client,
) -> EvidenceExecutor:
    return EvidenceExecutor(
        evidence_extraction_service=build_evidence_extraction_service(
            config=config,
            overrides=overrides,
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            llm_client=llm_client,
        ),
    )
