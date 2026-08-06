from __future__ import annotations

from typing import Any

from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.evidence.exceptions import EvidenceConfigurationError
from application.execution.exceptions import BudgetExhaustedError
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient


class LlmEvidenceExtractor(EvidenceExtractor):
    """Production evidence extractor using structured LLM output on bounded chunks."""

    method_name = "llm"

    def __init__(self, *, llm_client: LLMClient) -> None:
        self._llm_client = llm_client
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
        try:
            response = self._llm_client.generate(prompt)
        except BudgetExhaustedError:
            raise
        except Exception as exc:
            raise EvidenceConfigurationError(
                "LLM evidence extraction failed",
            ) from exc

        payload = self._parse_payload(response.content)
        allowed_need_ids = set(run_context.information_need_ids)
        question_for_need = {
            need.id: need.research_question_id
            for need in design.information_needs
            if need.id in allowed_need_ids
        }
        candidates: list[EvidenceCandidate] = []
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            need_id = str(item.get("information_need_id", "")).strip()
            if need_id not in allowed_need_ids:
                continue
            excerpt = str(item.get("source_excerpt", "")).strip()
            statement = str(item.get("statement", "")).strip()
            if not excerpt or not statement:
                continue
            evidence_type = str(
                item.get("evidence_type", EvidenceType.DIRECT_EXCERPT.value),
            )
            if evidence_type not in {member.value for member in EvidenceType}:
                evidence_type = EvidenceType.DIRECT_EXCERPT.value
            confidence = item.get("confidence")
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
        raise ValueError("LLM evidence payload must be a JSON object")
