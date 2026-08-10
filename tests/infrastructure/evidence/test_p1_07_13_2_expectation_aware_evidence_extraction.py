"""P1-07.13.2 expectation-aware Evidence extraction."""

from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.expectation_aware_extraction_context import (
    EXTRACTION_SYSTEM_GUIDANCE,
    build_extraction_need_payload,
    format_extraction_need_line,
)
from application.evidence.grounding import verify_grounding
from application.evidence.exceptions import UngroundedEvidenceError
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.executors.evidence_executor import EvidenceExecutor
from application.research_quality.production_targeted_research_runner import (
    ProductionTargetedResearchRunner,
)
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.project import Project
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from runtime.workflow_context import WorkflowContext

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTRACTOR_PATH = REPO_ROOT / "infrastructure" / "evidence" / "llm_evidence_extractor.py"
CONTEXT_PATH = REPO_ROOT / "application" / "evidence" / "expectation_aware_extraction_context.py"
SEARCH_BUILDER = REPO_ROOT / "application" / "sources" / "search_query_builder.py"
TARGETED_BUILDER = (
    REPO_ROOT / "application" / "research_quality" / "targeted_search_query_builder.py"
)

IN1_ASPECTS = (
    "market_value_estimate",
    "volume_proxy_methods",
    "growth_rate_cagr",
    "maturity_stage_indicators",
    "key_demand_drivers",
)
IN11_ASPECTS = (
    "food_safety_rules",
    "facility_requirements",
    "inspection_regimes",
    "pesticide_fertilizer_controls",
    "recordkeeping",
)
EUROPE_TAM_TEXT = (
    "The Europe microgreens market was valued at USD 1.2 billion in 2024. "
    "HoReCa demand and convenience foods are cited as growth drivers. "
    "No Serbia-specific volume proxy or maturity stage classification is provided."
)


def _ee(
    *,
    aspects: tuple[str, ...] = IN1_ASPECTS,
    nature: EvidenceNature = EvidenceNature.MIXED,
    quantitative: bool = True,
    geography: str | None = "Serbia",
    timeframe: str | None = "2019-2026",
    minimum_independent_sources: int | None = 3,
) -> EvidenceExpectation:
    return EvidenceExpectation(
        nature=nature,
        required_aspects=aspects,
        geography=geography,
        timeframe=timeframe,
        minimum_independent_sources=minimum_independent_sources,
        requires_quantitative_evidence=quantitative,
    )


def _design(
    *,
    expectation: EvidenceExpectation | None = None,
    description: str = "Estimate current market size and growth drivers for HoReCa microgreens.",
    geography: str = "Serbia",
    timeframe: str = "2019-2026 with 2025-2026 projections",
    need_id: str = "IN1",
) -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        language="en",
        research_questions=(
            ResearchQuestion(id="RQ1", question="What is the market?", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id=need_id,
                research_question_id="RQ1",
                description=description,
                geography=geography,
                timeframe=timeframe,
                evidence_expectation=expectation,
            ),
        ),
    )


def _source(*, content: str = EUROPE_TAM_TEXT, title: str = "Europe Microgreens Market") -> Source:
    return Source(
        id="source-1",
        project_id="project-1",
        url="https://example.com/europe-microgreens",
        canonical_url="https://example.com/europe-microgreens",
        title=title,
        retrieved_at="2026-01-01T00:00:00+00:00",
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum="checksum-1",
        workflow_run_refs=("run-1",),
        research_design_refs=("design-1",),
        information_need_refs=("IN1",),
        research_question_refs=("RQ1",),
        metadata={
            "discovery_records": [
                {
                    "provider": "tavily",
                    "query_id": "sq-IN1",
                    "rank": 1,
                    "workflow_run_id": "run-1",
                    "research_design_id": "design-1",
                    "information_need_id": "IN1",
                },
            ],
        },
    )


def _run_context(*, need_id: str = "IN1") -> RunScopedSourceContext:
    return RunScopedSourceContext(
        workflow_run_id="run-1",
        research_design_id="design-1",
        information_need_ids=(need_id,),
        research_question_ids=("RQ1",),
        query_ids=(f"sq-{need_id}",),
    )


def _recording_client(content: str = '{"items":[]}') -> Mock:
    client = Mock()

    def _generate(prompt, *, options=None):
        return LLMResponse(
            content=content,
            finish_reason="stop",
            configured_reasoning_effort=(
                options.reasoning_effort if options is not None else None
            ),
        )

    client.generate.side_effect = _generate
    return client


def _captured_prompt(client: Mock):
    return client.generate.call_args.args[0]


class ExpectationAwareExtractionContextTests(unittest.TestCase):
    def test_case_1_explicit_ee_reaches_llm_facing_messages(self) -> None:
        design = _design(expectation=_ee())
        client = _recording_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=design,
            run_context=_run_context(),
        )
        prompt = _captured_prompt(client)
        user = prompt.user
        system = prompt.system
        self.assertIn("Estimate current market size", user)
        self.assertIn("required_aspects=market_value_estimate,volume_proxy_methods", user)
        for aspect in IN1_ASPECTS:
            self.assertIn(aspect, user)
        self.assertIn("geography=Serbia", user)
        self.assertIn("timeframe=2019-2026", user)
        self.assertIn("nature=mixed", user)
        self.assertIn("required_aspects", system)
        self.assertIn("source_excerpt MUST be an exact substring", system)

    def test_case_2_quantitative_requirement_without_fabrication(self) -> None:
        design = _design(expectation=_ee(quantitative=True, nature=EvidenceNature.QUANTITATIVE))
        client = _recording_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=design,
            run_context=_run_context(),
        )
        prompt = _captured_prompt(client)
        blob = f"{prompt.system}\n{prompt.user}"
        self.assertIn("requires_quantitative_evidence=true", prompt.user)
        self.assertIn("preferentially extract", prompt.system.lower())
        self.assertIn("grounded quantitative", prompt.system.lower())
        self.assertIn("never invent numbers", prompt.system.lower())
        self.assertIn("do not fabricate", prompt.system.lower())
        self.assertIn("absent from source_text", blob.lower())

    def test_case_3_non_quantitative_expectation(self) -> None:
        design = _design(
            expectation=_ee(
                quantitative=False,
                nature=EvidenceNature.QUALITATIVE,
                aspects=IN11_ASPECTS,
            ),
            description="Summarize regulatory framework for microgreens food safety.",
            need_id="IN11",
        )
        client = _recording_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(content="Food hygiene rules require HACCP documentation."),
            design=design,
            run_context=_run_context(need_id="IN11"),
        )
        prompt = _captured_prompt(client)
        self.assertIn("requires_quantitative_evidence=false", prompt.user)
        self.assertIn("nature=qualitative", prompt.user)
        self.assertNotIn("must extract numeric", prompt.system.lower())
        self.assertNotIn("reject qualitative", prompt.system.lower())

    def test_case_4_missing_aspect_source_does_not_manufacture(self) -> None:
        excerpt = "The Europe microgreens market was valued at USD 1.2 billion in 2024."
        payload = {
            "items": [
                {
                    "statement": "Europe microgreens market value was USD 1.2 billion in 2024.",
                    "source_excerpt": excerpt,
                    "information_need_id": "IN1",
                }
            ]
        }
        client = _recording_client(json.dumps(payload))
        candidates = LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=_design(expectation=_ee()),
            run_context=_run_context(),
        )
        self.assertEqual(len(candidates), 1)
        self.assertIn("USD 1.2 billion", candidates[0].statement)
        self.assertEqual(candidates[0].source_excerpt, excerpt)
        verify_grounding(source_text=EUROPE_TAM_TEXT, excerpt=excerpt)
        self.assertNotIn("maturity stage", candidates[0].statement.lower())
        empty_client = _recording_client('{"items":[]}')
        empty = LlmEvidenceExtractor(llm_client=empty_client).extract(
            source=_source(),
            design=_design(expectation=_ee()),
            run_context=_run_context(),
        )
        self.assertEqual(empty, [])

    def test_case_5_grounding_regression(self) -> None:
        with self.assertRaises(UngroundedEvidenceError):
            verify_grounding(
                source_text=EUROPE_TAM_TEXT,
                excerpt="Serbia HoReCa microgreens TAM is EUR 40 million.",
            )
        invented = {
            "items": [
                {
                    "statement": "Serbia TAM is EUR 40 million.",
                    "source_excerpt": "Serbia HoReCa microgreens TAM is EUR 40 million.",
                    "information_need_id": "IN1",
                }
            ]
        }
        client = _recording_client(json.dumps(invented))
        extractor = LlmEvidenceExtractor(llm_client=client)
        design = _design(expectation=_ee())
        source = _source()
        candidates = extractor.extract(
            source=source,
            design=design,
            run_context=_run_context(),
        )
        self.assertEqual(len(candidates), 1)
        with self.assertRaises(UngroundedEvidenceError):
            verify_grounding(
                source_text=source.content_text,
                excerpt=candidates[0].source_excerpt,
            )
        template = WorkflowTemplate(
            id="template-1",
            name="Desk",
            task_definitions=[
                TaskDefinition(
                    id="task-extract-evidence",
                    name="Extract",
                    executor_id="evidence",
                    executor_type=ExecutorType.AGENT,
                ),
            ],
            research_design_snapshot=design,
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]
        source_repo = InMemorySourceRepository()
        source_repo.create(source)
        evidence_repo = InMemoryEvidenceRepository()
        service = EvidenceExtractionService(
            evidence_extractor=extractor,
            evidence_repository=evidence_repo,
            source_repository=source_repo,
        )
        summary = service.extract_for_source_ids(
            context,
            ("source-1",),
            allow_empty=True,
        )
        self.assertEqual(summary.evidence_extracted, 0)
        self.assertEqual(
            len(evidence_repo.list_for_project("project-1", workflow_run_id="run-1")),
            0,
        )

    def test_case_6_legacy_ee_none_compatible(self) -> None:
        design = _design(expectation=None)
        payload = build_extraction_need_payload(design.information_needs[0])
        self.assertNotIn("required_aspects", payload)
        self.assertNotIn("nature", payload)
        self.assertNotIn("evidence_expectation", payload)
        line = format_extraction_need_line(payload)
        self.assertEqual(
            line,
            "- id=IN1 question_id=RQ1 description=Estimate current market size "
            "and growth drivers for HoReCa microgreens.",
        )
        client = _recording_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=design,
            run_context=_run_context(),
        )
        prompt = _captured_prompt(client)
        self.assertNotIn("required_aspects=", prompt.user)
        self.assertNotIn("nature=", prompt.user)
        self.assertIn("description=Estimate current market size", prompt.user)

    def test_case_7_initial_path_uses_expectation_context(self) -> None:
        initial_src = inspect.getsource(EvidenceExecutor.run)
        self.assertIn("extract_for_context", initial_src)
        service_src = inspect.getsource(EvidenceExtractionService.extract_for_context)
        self.assertIn("_extract_work_queue", service_src)
        client = _recording_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=_design(expectation=_ee()),
            run_context=_run_context(),
        )
        self.assertIn("required_aspects=", _captured_prompt(client).user)

    def test_case_8_remediation_path_equivalent_context(self) -> None:
        runner_src = inspect.getsource(ProductionTargetedResearchRunner.run)
        self.assertIn("extract_for_source_ids", runner_src)
        self.assertIn("EVIDENCE_PURPOSE_REMEDIATION", runner_src)
        targeted_src = inspect.getsource(EvidenceExtractionService.extract_for_source_ids)
        self.assertIn("_extract_work_queue", targeted_src)
        extractor_src = inspect.getsource(LlmEvidenceExtractor.extract)
        self.assertIn("build_extraction_need_payload", extractor_src)
        self.assertIn("EXTRACTION_SYSTEM_GUIDANCE", extractor_src)
        design = _design(expectation=_ee())
        template = WorkflowTemplate(
            id="template-1",
            name="Desk",
            task_definitions=[
                TaskDefinition(
                    id="task-extract-evidence",
                    name="Extract",
                    executor_id="evidence",
                    executor_type=ExecutorType.AGENT,
                ),
            ],
            research_design_snapshot=design,
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]
        source_repo = InMemorySourceRepository()
        source_repo.create(_source())
        client = _recording_client()
        service = EvidenceExtractionService(
            evidence_extractor=LlmEvidenceExtractor(llm_client=client),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=source_repo,
        )
        service.extract_for_source_ids(context, ("source-1",), allow_empty=True)
        self.assertEqual(client.generate.call_count, 1)
        prompt = _captured_prompt(client)
        self.assertIn("required_aspects=", prompt.user)
        self.assertIn("geography=Serbia", prompt.user)

    def test_case_9_no_extra_llm_calls(self) -> None:
        client = _recording_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=_design(expectation=_ee()),
            run_context=_run_context(),
        )
        self.assertEqual(client.generate.call_count, 1)
        legacy = _recording_client()
        LlmEvidenceExtractor(llm_client=legacy).extract(
            source=_source(),
            design=_design(expectation=None),
            run_context=_run_context(),
        )
        self.assertEqual(legacy.generate.call_count, 1)

    def test_case_10_sufficiency_boundary_unchanged(self) -> None:
        blob = EXTRACTION_SYSTEM_GUIDANCE.lower()
        self.assertIn("do not assess sufficiency", blob)
        self.assertIn("readiness", blob)
        for status in ("sufficient", "partial", "insufficient", "missing"):
            self.assertNotIn(f"status={status}", blob)
            self.assertNotIn(f'"{status}"', blob)
        self.assertNotIn("ready_for_analysis", blob)
        output_schema = '{"items":[{"statement"'
        self.assertIn(output_schema, EXTRACTION_SYSTEM_GUIDANCE)

    def test_case_11_minimum_independent_sources_not_a_per_source_quota(self) -> None:
        payload = build_extraction_need_payload(
            _design(expectation=_ee(minimum_independent_sources=2)).information_needs[0],
        )
        self.assertNotIn("minimum_independent_sources", payload)
        client = _recording_client()
        LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=_design(expectation=_ee(minimum_independent_sources=2)),
            run_context=_run_context(),
        )
        prompt = _captured_prompt(client)
        combined = f"{prompt.system}\n{prompt.user}"
        self.assertNotIn("minimum_independent_sources=2", combined)
        self.assertNotIn("extract from 2 independent sources", combined.lower())
        self.assertIn("multi-source", prompt.system.lower())
        self.assertIn(
            "do not treat this single-source extraction as satisfying",
            prompt.system.lower(),
        )

    def test_case_12_live_style_subset_source(self) -> None:
        design = _design(expectation=_ee())
        client = _recording_client(
            json.dumps(
                {
                    "items": [
                        {
                            "statement": "Europe microgreens market was valued at USD 1.2 billion in 2024.",
                            "source_excerpt": (
                                "The Europe microgreens market was valued at USD 1.2 billion in 2024."
                            ),
                            "information_need_id": "IN1",
                        }
                    ]
                }
            )
        )
        candidates = LlmEvidenceExtractor(llm_client=client).extract(
            source=_source(),
            design=design,
            run_context=_run_context(),
        )
        prompt = _captured_prompt(client)
        for aspect in IN1_ASPECTS:
            self.assertIn(aspect, prompt.user)
        self.assertEqual(len(candidates), 1)
        verify_grounding(
            source_text=EUROPE_TAM_TEXT,
            excerpt=candidates[0].source_excerpt,
        )
        self.assertNotIn("volume proxy", candidates[0].statement.lower())
        self.assertNotIn("maturity stage classification is nascent", candidates[0].statement.lower())


class SearchUnchangedAndSourceScanTests(unittest.TestCase):
    def test_search_13_1_builders_unchanged_by_this_milestone(self) -> None:
        search = SEARCH_BUILDER.read_text(encoding="utf-8")
        targeted = TARGETED_BUILDER.read_text(encoding="utf-8")
        self.assertIn("build_expectation_aware_query_text", search)
        self.assertIn("build_expectation_aware_query_text", targeted)
        self.assertIn("missing_aspects", targeted)
        self.assertNotIn("expectation_aware_extraction_context", search)
        self.assertNotIn("expectation_aware_extraction_context", targeted)

    def test_no_openai_token_in_new_helper(self) -> None:
        source = CONTEXT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("openai", alias.name.lower())
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("openai", node.module.lower())
        self.assertNotIn("incomplete_details", source.lower())


if __name__ == "__main__":
    unittest.main()
