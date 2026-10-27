from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from hashlib import sha256

from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.grounding import verify_grounding
from application.report.exceptions import ReportError
from application.report.report_factory import build_report_service
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.ai.llm_response import LLMResponse
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template_builder import WorkflowTemplateBuilder
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from runtime.workflow_context import WorkflowContext
from tests.fixtures.research_brief import sample_research_brief
import tests.application.report.test_report_claim_contract as claim_fixtures


class _MissingClaimProviderEngine(DeterministicReportEngine):
    method_name = "llm"
    generate_claim_candidates = None
    repair_claim_candidates = None


class _ScriptedLLMClient:
    def __init__(self, *, initial_mode: str, repair_mode: str = "authority") -> None:
        self.initial_mode = initial_mode
        self.repair_mode = repair_mode
        self.initial_calls: list[dict] = []
        self.repair_calls: list[dict] = []

    def generate(self, prompt, *, options=None) -> LLMResponse:
        del options
        request = json.loads(prompt.user.split("BOUNDED CLAIM REQUEST\n", 1)[1])
        if "bounded repair call" in prompt.system:
            self.repair_calls.append(copy.deepcopy(request))
            if "claims" in request:
                key = "authority" if self.repair_mode == "authority" else "candidate"
                result = {"claims": [copy.deepcopy(item[key]) for item in request["claims"]]}
            else:
                key = "authority" if self.repair_mode == "authority" else "candidate"
                result = copy.deepcopy(request[key])
        else:
            self.initial_calls.append(copy.deepcopy(request))
            result = copy.deepcopy(request)
            candidates = result["claims"] if "claims" in result else [result]
            if self.initial_mode == "invalid":
                for claim in candidates:
                    claim["assertion"]["proposition"] = "1,06 млрд"
        return LLMResponse(content=json.dumps(result, ensure_ascii=False))


class ProductionClaimProviderCompositionTests(unittest.TestCase):
    def _build(self, *, engine=None, llm_client=None, finding_count: int = 1):
        fixture = claim_fixtures.ReportClaimContractTests()
        fixture.setUp()
        project = ProjectFactory().create("Claim provider composition")
        source_text = "E"
        source = Source(
            id="source-1",
            project_id=project.id,
            url="https://example.com/source",
            canonical_url="https://example.com/source",
            title="Source",
            retrieved_at="2026-01-01T00:00:00Z",
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text=source_text,
            content_checksum=sha256(source_text.encode()).hexdigest(),
            research_question_refs=("rq-1",),
            information_need_refs=("in-1",),
            workflow_run_refs=("source-run",),
            research_design_refs=(fixture.design.id,),
        )
        source_repo = InMemorySourceRepository()
        source_repo.create(source)
        evidence = replace(
            fixture.evidence,
            project_id=project.id,
            source_content_checksum=source.content_checksum,
            source_locator=verify_grounding(
                source_text=source_text,
                excerpt="E",
            ).to_dict(),
            deduplication_key="evidence-1",
        )
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(evidence)
        finding_repo = InMemoryFindingRepository()
        for index in range(finding_count):
            finding_repo.create(replace(
                fixture.finding,
                id=f"finding-{index + 1}",
                project_id=project.id,
                evidence_refs=(evidence.id,),
                deduplication_key=f"finding-{index + 1}",
            ))
        insight_repo = InMemoryInsightRepository()
        report_repo = InMemoryReportRepository()
        claim_repo = InMemoryReportClaimRepository(report_repo)
        artifact_repo = InMemoryArtifactRepository()
        template = (
            WorkflowTemplateBuilder(id="template", name="T")
            .add_task(
                id="report",
                name="Write",
                executor_id="report",
                executor_type=ExecutorType.AGENT,
            )
            .build()
        )
        template.research_brief_snapshot = replace(sample_research_brief(), timeframe="")
        template.research_design_snapshot = fixture.design
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template,
            run_id="source-run",
        )
        run.project_id = project.id
        context = WorkflowContext(
            project=project,
            workflow_run=run,
            workflow_template=template,
            current_task=run.tasks[0],
        )
        service = build_report_service(
            config=ApplicationConfig(report_engine="llm"),
            overrides=ApplicationOverrides(report_engine=engine),
            finding_repository=finding_repo,
            insight_repository=insight_repo,
            evidence_repository=evidence_repo,
            source_repository=source_repo,
            report_repository=report_repo,
            report_claim_repository=claim_repo,
            artifact_repository=artifact_repo,
            llm_client=llm_client,
        )
        return service, context, report_repo, claim_repo

    def test_real_factory_reproduces_zero_call_when_provider_is_missing(self) -> None:
        service, context, report_repo, _ = self._build(engine=_MissingClaimProviderEngine())
        with self.assertRaises(ReportError):
            service.write_for_context(context)
        diagnostic = context.read_shared("report_generation_diagnostics")
        self.assertEqual("provider_not_configured", diagnostic["claim_generation"]["category"])
        self.assertEqual([], report_repo.list_for_project(context.project.id))

    def test_valid_initial_uses_one_call_and_no_repair(self) -> None:
        client = _ScriptedLLMClient(initial_mode="valid")
        service, context, report_repo, claim_repo = self._build(llm_client=client)
        summary = service.write_for_context(context)
        self.assertEqual(1, len(client.initial_calls))
        self.assertEqual(0, len(client.repair_calls))
        self.assertIsNotNone(report_repo.get_by_id(summary.report_id))
        self.assertEqual(1, len(claim_repo.list_for_report(summary.report_id, 1)))

    def test_invalid_initial_gets_one_successful_batch_repair(self) -> None:
        client = _ScriptedLLMClient(initial_mode="invalid")
        service, context, report_repo, claim_repo = self._build(llm_client=client)
        summary = service.write_for_context(context)
        self.assertEqual((1, 1), (len(client.initial_calls), len(client.repair_calls)))
        self.assertEqual("1,06 млрд", client.repair_calls[0]["candidate"]["assertion"]["proposition"])
        claims = claim_repo.list_for_report(summary.report_id, 1)
        self.assertEqual(1, len(claims))
        self.assertNotEqual("1,06 млрд", claims[0].proposition)
        self.assertIsNotNone(report_repo.get_by_id(summary.report_id))

    def test_invalid_repair_fails_closed_after_two_total_calls(self) -> None:
        client = _ScriptedLLMClient(initial_mode="invalid", repair_mode="candidate")
        service, context, report_repo, _ = self._build(llm_client=client)
        with self.assertRaises(ReportError):
            service.write_for_context(context)
        self.assertEqual((1, 1), (len(client.initial_calls), len(client.repair_calls)))
        self.assertEqual([], report_repo.list_for_project(context.project.id))
        diagnostic = context.read_shared("report_generation_diagnostics")["claim_generation"]
        self.assertEqual("repair_validation_failed", diagnostic["category"])
        self.assertTrue(diagnostic["repair_exhausted"])
        self.assertIn("rejected_tokens", diagnostic)
        self.assertNotIn("prompt", diagnostic)
        self.assertNotIn("response", diagnostic)

    def test_multiple_invalid_claims_share_one_batch_repair_without_authority_borrowing(self) -> None:
        client = _ScriptedLLMClient(initial_mode="invalid")
        service, context, _, claim_repo = self._build(llm_client=client, finding_count=2)
        summary = service.write_for_context(context)
        self.assertEqual((1, 1), (len(client.initial_calls), len(client.repair_calls)))
        batch = client.repair_calls[0]["claims"]
        self.assertEqual(2, len(batch))
        self.assertNotEqual(batch[0]["claim_id"], batch[1]["claim_id"])
        for item in batch:
            self.assertEqual(item["claim_id"], item["authority"]["claim_id"])
            self.assertEqual(item["candidate"]["finding_ids"], item["authority"]["finding_ids"])
        self.assertEqual(2, len(claim_repo.list_for_report(summary.report_id, 1)))


if __name__ == "__main__":
    unittest.main()
