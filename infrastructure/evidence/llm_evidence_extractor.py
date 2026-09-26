from __future__ import annotations

from typing import Any

from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.evidence.expectation_aware_extraction_context import (
    EXTRACTION_SYSTEM_GUIDANCE,
    build_extraction_need_payload,
    format_extraction_need_line,
)
from application.evidence.evidence_extractor_response_shape import (
    publish_response_shape,
    reset_response_shape,
    ResponseShapeDiagnostics,
)
from application.evidence.evidence_response_classification import (
    EvidenceResponseClassification,
    FAILURE_RESPONSE_CLASSIFICATIONS,
    classify_evidence_llm_response,
)
from application.evidence.exceptions import (
    EvidenceConfigurationError,
    EvidenceResponseOutcomeError,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget_context import get_execution_budget
from application.execution.execution_budget_retry import (
    consume_llm_call_retry_flag, mark_llm_call_as_retry,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient

_PAYLOAD_OBJECT_ERROR = "LLM evidence payload must be a JSON object"


class LlmEvidenceExtractor(EvidenceExtractor):
    """Production evidence extractor using structured LLM output on bounded chunks."""

    method_name = "llm"

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        reasoning_effort: str = "minimal",
        max_structured_retries: int = 1,
    ) -> None:
        if max_structured_retries not in (0, 1):
            raise ValueError("max_structured_retries must be 0 or 1")
        self._llm_client = llm_client
        self._reasoning_effort = reasoning_effort
        self._max_structured_retries = max_structured_retries
        self._json_extractor = JsonExtractor()
        self._json_validator = JsonValidator()

    def extract(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        run_context: RunScopedSourceContext,
    ) -> list[EvidenceCandidate]:
        needs_payload = [
            build_extraction_need_payload(need)
            for need in design.information_needs
            if need.id in run_context.information_need_ids
        ]
        if not needs_payload:
            reset_response_shape()
            return []

        prompt = Prompt(
            system=EXTRACTION_SYSTEM_GUIDANCE + (
                " This is targeted continuation. Prioritize the explicit target_information_need_id. "
                "Do not substitute another need for an unsupported target. Cross-need facts may "
                "be retained with their true listed IDs; they do not repair the target."
                if run_context.target_information_need_id else ""
            ),
            user=self._build_user_payload(source=source, needs_payload=needs_payload) + (
                f"\ntarget_information_need_id: {run_context.target_information_need_id}"
                if run_context.target_information_need_id else ""
            ),
        )
        response_shape: ResponseShapeDiagnostics | None = None
        try:
            for attempt in range(self._max_structured_retries + 1):
                if attempt and get_execution_budget() is not None:
                    mark_llm_call_as_retry()
                try:
                    response = self._llm_client.generate(
                        prompt,
                        options=LLMGenerationOptions(
                            reasoning_effort=self._reasoning_effort,
                        ),
                    )
                except BudgetExhaustedError:
                    if attempt:
                        consume_llm_call_retry_flag()
                    reset_response_shape()
                    raise
                except Exception as exc:
                    reset_response_shape()
                    raise EvidenceConfigurationError(
                        "LLM evidence extraction failed",
                    ) from exc
                response_shape = ResponseShapeDiagnostics.from_llm_response(
                    response,
                    json_extractor=self._json_extractor,
                    json_validator=self._json_validator,
                )
                response_shape.structured_attempts = attempt + 1
                classification, payload = classify_evidence_llm_response(
                    response,
                    json_extractor=self._json_extractor,
                    json_validator=self._json_validator,
                )
                if (
                    attempt < self._max_structured_retries
                    and classification in {
                        EvidenceResponseClassification.INVALID_JSON,
                        EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH,
                    }
                ):
                    prompt = Prompt(
                        system=prompt.system,
                        user=prompt.user + "\nPrevious response failed JSON/items validation ("
                        + classification.value + "). Return one complete JSON object "
                        'with an items array, or {"items":[]}. Do not add prose.',
                    )
                    continue
                break
            assert response_shape is not None
            response_shape.record_response_classification(classification.value)

            if classification in FAILURE_RESPONSE_CLASSIFICATIONS:
                if payload is not None:
                    response_shape.record_object_root(payload)
                raise self._outcome_error(classification)

            assert payload is not None
            response_shape.record_object_root(payload)
            candidates = self._build_candidates_from_payload(
                payload,
                design=design,
                run_context=run_context,
                response_shape=response_shape,
            )
            if response_shape.rejected_schema_invalid_item:
                response_shape.record_response_classification(
                    EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH.value,
                )
                raise self._outcome_error(
                    EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH,
                )
            response_shape.items_count_post_filter = len(candidates)
            publish_response_shape(response_shape)
            return candidates
        except Exception:
            if response_shape is not None:
                publish_response_shape(response_shape)
            raise

    @staticmethod
    def _outcome_error(
        classification: EvidenceResponseClassification,
    ) -> EvidenceResponseOutcomeError:
        if classification is EvidenceResponseClassification.EMPTY_PROVIDER_OUTPUT:
            message = "LLM evidence response contained no visible provider output"
        elif classification is EvidenceResponseClassification.INCOMPLETE_PROVIDER_OUTPUT:
            message = "LLM evidence response was incomplete"
        elif classification is EvidenceResponseClassification.SCHEMA_CONTRACT_MISMATCH:
            message = "LLM evidence payload does not satisfy the items schema contract"
        else:
            message = _PAYLOAD_OBJECT_ERROR
        return EvidenceResponseOutcomeError(
            message,
            classification=classification.value,
        )

    def _build_candidates_from_payload(
        self,
        payload: dict[str, Any],
        *,
        design: ResearchDesign,
        run_context: RunScopedSourceContext,
        response_shape: ResponseShapeDiagnostics,
    ) -> list[EvidenceCandidate]:
        allowed_need_ids = set(run_context.information_need_ids)
        question_for_need = {
            need.id: need.research_question_id
            for need in design.information_needs
            if need.id in allowed_need_ids
        }
        candidates: list[EvidenceCandidate] = []
        for item_index, item in enumerate(payload.get("items", [])):
            if not isinstance(item, dict):
                response_shape.record_item_rejection(
                    item_index=item_index,
                    outcome="rejected_non_object_item",
                )
                continue
            if (
                (item.get("information_need_id") is not None
                 and not isinstance(item["information_need_id"], str))
                or (item.get("statement") is not None
                    and not isinstance(item["statement"], str))
                or (item.get("source_excerpt") is not None
                    and not isinstance(item["source_excerpt"], str))
                or ("direct" in item and not isinstance(item["direct"], bool))
                or ("evidence_type" in item and (
                    not isinstance(item["evidence_type"], str)
                    or item["evidence_type"] not in {member.value for member in EvidenceType}
                ))
                or ("confidence" in item and item["confidence"] is not None and (
                    isinstance(item["confidence"], bool)
                    or not isinstance(item["confidence"], (int, float))
                ))
            ):
                response_shape.record_item_rejection(
                    item_index=item_index, outcome="rejected_schema_invalid_item",
                )
                continue
            need_id = (item.get("information_need_id") or "").strip()
            if not need_id:
                response_shape.record_item_rejection(
                    item_index=item_index,
                    outcome="rejected_missing_information_need_id",
                )
                continue
            if need_id not in allowed_need_ids:
                response_shape.record_item_rejection(
                    item_index=item_index,
                    outcome="rejected_unknown_information_need_id",
                )
                continue
            excerpt = (item.get("source_excerpt") or "").strip()
            statement = (item.get("statement") or "").strip()
            if not statement:
                response_shape.record_item_rejection(
                    item_index=item_index,
                    outcome="rejected_empty_statement",
                )
                continue
            if not excerpt:
                response_shape.record_item_rejection(
                    item_index=item_index,
                    outcome="rejected_empty_source_excerpt",
                )
                continue
            evidence_type = str(
                item.get("evidence_type", EvidenceType.DIRECT_EXCERPT.value),
            )
            if evidence_type not in {member.value for member in EvidenceType}:
                evidence_type = EvidenceType.DIRECT_EXCERPT.value
            confidence = item.get("confidence")
            metadata: dict[str, Any] = {}
            for field in ("observation_period", "data_origin_id", "data_origin_excerpt"):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    metadata[field] = value.strip()
            try:
                candidates.append(
                    EvidenceCandidate(
                        statement=statement,
                        source_excerpt=excerpt,
                        evidence_type=evidence_type,
                        research_question_refs=(question_for_need[need_id],),
                        information_need_refs=(need_id,),
                        confidence=float(confidence) if confidence is not None else None,
                        direct=bool(item.get("direct", True)),
                        metadata=metadata,
                    ),
                )
            except (TypeError, ValueError):
                response_shape.record_item_rejection(
                    item_index=item_index,
                    outcome="rejected_invalid_confidence",
                )
                raise
            except Exception:
                response_shape.record_item_rejection(
                    item_index=item_index,
                    outcome="rejected_candidate_construction_error",
                )
                raise
        return candidates

    @staticmethod
    def _build_user_payload(*, source: Source, needs_payload: list[dict[str, Any]]) -> str:
        lines = [
            f"source_title: {source.title}",
            "source_text:",
            source.content_text,
            "information_needs:",
        ]
        for need in needs_payload:
            lines.append(format_extraction_need_line(need))
        return "\n".join(lines)

    def _parse_payload(self, content: str) -> dict[str, Any]:
        for candidate in self._json_extractor.extract_all(content):
            validation = self._json_validator.validate(candidate)
            if validation.is_valid and isinstance(validation.data, dict):
                return validation.data
        raise ValueError(_PAYLOAD_OBJECT_ERROR)
