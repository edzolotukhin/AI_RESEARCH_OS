from __future__ import annotations

from typing import Any

from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

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
    ) -> None:
        self._llm_client = llm_client
        self._reasoning_effort = reasoning_effort
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
            {
                "id": need.id,
                "research_question_id": need.research_question_id,
                "description": need.description,
            }
            for need in design.information_needs
            if need.id in run_context.information_need_ids
        ]
        if not needs_payload:
            reset_response_shape()
            return []

        prompt = Prompt(
            system=(
                "Extract grounded research evidence from the provided source text chunk. "
                "Return JSON only with shape "
                '{"items":[{"statement":"...","source_excerpt":"...",'
                '"information_need_id":"...","evidence_type":"direct_excerpt",'
                '"direct":true,"confidence":0.8}]}. '
                "source_excerpt MUST be an exact substring of source_text after "
                "whitespace normalization. Do not invent IDs beyond "
                "information_need_id values listed in information_needs."
            ),
            user=self._build_user_payload(source=source, needs_payload=needs_payload),
        )
        response_shape: ResponseShapeDiagnostics | None = None
        try:
            response = self._llm_client.generate(
                prompt,
                options=LLMGenerationOptions(
                    reasoning_effort=self._reasoning_effort,
                ),
            )
        except BudgetExhaustedError:
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
        try:
            classification, payload = classify_evidence_llm_response(
                response,
                json_extractor=self._json_extractor,
                json_validator=self._json_validator,
            )
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
            need_id = str(item.get("information_need_id", "")).strip()
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
            excerpt = str(item.get("source_excerpt", "")).strip()
            statement = str(item.get("statement", "")).strip()
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
            lines.append(
                f"- id={need['id']} question_id={need['research_question_id']} "
                f"description={need['description']}",
            )
        return "\n".join(lines)

    def _parse_payload(self, content: str) -> dict[str, Any]:
        for candidate in self._json_extractor.extract_all(content):
            validation = self._json_validator.validate(candidate)
            if validation.is_valid and isinstance(validation.data, dict):
                return validation.data
        raise ValueError(_PAYLOAD_OBJECT_ERROR)
