"""Provider-free production-shaped Desk extension through H3 delivery."""

from __future__ import annotations

import copy
import ast
from dataclasses import replace
from hashlib import sha256
import json
import re
import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.ports.analysis_ports import FindingCandidate, InsightCandidate
from application.ports.evidence_ports import EvidenceCandidate
from application.ports.source_ports import SearchProvider, SourceRetriever
from application.report.h3_coverage_plan import build_h3_coverage_plan
from application.report.typed_rendering import H3_CONTRACT_VERSION
from application.authority_extension import COMPOSED_AUTHORITY_KEY
from application.evidence.grounding import verify_grounding
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.planning.research_subject import (
    LexicalRepresentation, RepresentationApprovalStatus, ResearchSubject,
    SubjectResolutionStatus,
)
from domain.research_brief import ResearchBrief
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate
from domain.task_definition import TaskDefinition
from domain.workflow_template import WorkflowTemplate
from domain.ai.llm_response import LLMResponse
from tests.application.report.test_h3_claim_generation import _valid_response
from tests.application.report.test_h3_editorial_delivery import _editorial_payload
from tests.api.helpers import drain_background_runs
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase, configure_structured_finalization_test_boundary,
    integration_tests_enabled, postgresql_application_config,
)


TS = "2026-01-01T00:00:00+00:00"
PROJECT = "touchpoll-e2e"
PARENT = "touchpoll-parent"
NEEDS = ("in1_nominal_turnover", "in2_real_adjustment", "in3_trend_character")


def _subject() -> ResearchSubject:
    return ResearchSubject(
        subject_id="ukraine-retail", canonical_label="Ukraine retail market",
        canonical_language="en", core_concepts=("ukraine", "retail", "turnover"),
        lexical_representations=(LexicalRepresentation(
            "subject-en", "en", "Ukraine retail market",
            ("ukraine retail market", "retail turnover", "retail real volume"),
            ("ukraine", "retail"), "synthetic qualification",
            RepresentationApprovalStatus.APPROVED,
        ),),
        resolution_status=SubjectResolutionStatus.RESOLVED,
        provenance={"fixture": "provider-free-e2e"},
    )


def _design() -> ResearchDesign:
    subject = _subject()
    specs = (
        (NEEDS[0], "annual nominal retail turnover 2021 2022 2023 2024 2025 2026", ("nominal_turnover",)),
        (NEEDS[1], "retail real volume and retail deflator 2021 2022 2023 2024 2025 2026", ("retail_real_volume", "retail_deflator", "cpi")),
        (NEEDS[2], "comparable retail trend and turning point 2021 2022 2023 2024 2025 2026", ("trend_direction",)),
    )
    return ResearchDesign(
        id="touchpoll-design",
        research_questions=(ResearchQuestion("rq-retail", "How did Ukraine retail change from 2021 to 2026?"),),
        information_needs=tuple(
            InformationNeed(
                need_id, "rq-retail", description, timeframe="2021,2022,2023,2024,2025,2026",
                geography="UA", evidence_expectation=EvidenceExpectation(
                    nature=EvidenceNature.QUANTITATIVE, required_aspects=aspects,
                    geography="UA", timeframe="2021,2022,2023,2024,2025,2026",
                    minimum_independent_sources=2, requires_quantitative_evidence=True,
                ),
            )
            for need_id, description, aspects in specs
        ),
        source_strategy=("official statistics", "independent industry authority"),
        analysis_plan=("compare annual series",), deliverable_plan=("report", "pdf", "pptx"),
        language="uk", research_subject=subject,
    )


class _Search(SearchProvider):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query):
        self.calls += 1
        need = query.information_need_id
        rows = [
            (f"https://fixture.test/{need}/parent", f"Parent authority {need}"),
            (f"https://fixture.test/{need}/new", f"New authority {need}"),
        ]
        if need == NEEDS[1]:
            rows.append(("https://fixture.test/in2/cpi-only", "CPI only temptation"))
        return [
            SourceCandidate(
                provider="fixture", provider_result_id=f"{query.id}-{index}", url=url,
                title=title, snippet=f"Ukraine retail {need} 2021 2026", source_type="web",
                rank=index, query_id=query.id,
            )
            for index, (url, title) in enumerate(rows, start=1)
        ]


class _Retriever(SourceRetriever):
    def retrieve(self, candidate):
        text = (
            "Ukraine CPI general inflation was 10% in 2026."
            if "cpi-only" in candidate.url
            else f"Ukraine retail authority {candidate.title}: 2021–2026 retail value was 100 UAH in 2021 and 120 UAH in 2026."
        )
        return Source(
            id="", project_id="", url=candidate.url, canonical_url=candidate.url,
            title=candidate.title, retrieved_at=TS, retrieval_status=RetrievalStatus.ACQUIRED,
            content_type="text/plain", content_text=text,
            metadata={"fixture": "provider-free-e2e"},
        )


class _EvidenceExtractor:
    def __init__(self, design: ResearchDesign) -> None:
        self.design = design
        self.calls = 0

    def extract(self, *, source, design, run_context):
        self.calls += 1
        need_id = run_context.target_information_need_id or run_context.information_need_ids[0]
        need = next(item for item in design.information_needs if item.id == need_id)
        if "cpi-only" in source.canonical_url:
            aspect = "cpi"
            statement = "Ukraine CPI general inflation was 10% in 2026."
        else:
            aspect = {
                NEEDS[0]: "nominal_turnover",
                NEEDS[1]: "retail_real_volume",
                NEEDS[2]: "trend_direction",
            }[need_id]
            statement = source.content_text
        return [EvidenceCandidate(
            statement=statement, source_excerpt=statement,
            evidence_type=EvidenceType.DIRECT_EXCERPT.value,
            research_question_refs=(need.research_question_id,),
            information_need_refs=(need.id,), confidence=0.99, direct=True,
            metadata={"observation_period": "2021–2026"},
            contract_version="desk_evidence_candidate_v2",
            required_aspect_refs=(aspect,),
            subject_binding={
                "binding_type": "canonical_subject",
                "subject_id": design.research_subject.subject_id,
                "subject_fingerprint": design.research_subject.semantic_fingerprint,
            },
            semantic_justification="The excerpt directly names Ukraine retail and the assigned metric.",
            geography_applicability=("UA",),
        )]


class _Analysis:
    method_name = "provider-free-touchpoll-e2e"

    def analyze_findings(self, analysis_input):
        values = []
        for need_id in NEEDS:
            refs = tuple(sorted(
                item.id for item in analysis_input.evidence_batch
                if need_id in item.information_need_refs
                and "cpi-only" not in item.statement.casefold()
                and not (
                    need_id == NEEDS[1]
                    and "cpi general inflation" in item.statement.casefold()
                )
            ))
            if refs:
                values.append(FindingCandidate(
                    statement=f"Authority supports {need_id} for 2021 through 2026.",
                    rationale="Two independent grounded sources support this selected need.",
                    evidence_refs=refs, research_question_refs=("rq-retail",),
                    information_need_refs=(need_id,), finding_type="synthesis",
                    confidence=0.95, metadata={"fixture": "provider-free-e2e"},
                ))
        return values

    def analyze_insights(self, analysis_input):
        return [InsightCandidate(
            statement="The composed retail authority supports a bounded trend conclusion.",
            implication="Use the validated nominal, real-volume and trend series together.",
            finding_refs=tuple(item.id for item in analysis_input.persisted_findings),
            research_question_refs=("rq-retail",), confidence=0.9,
        )]


class _H3Engine:
    method_name = "provider-free-h3"

    def __init__(self) -> None:
        self.initial_calls = 0
        self.repair_calls = 0

    def generate_h3_claim_candidates(self, request):
        self.initial_calls += 1
        payload = _valid_response(request)
        if payload["claims"]:
            payload["claims"][0]["nodes"][0]["text"] = "Unsupported factual value 999 "
        return payload

    def repair_h3_claim_candidates(self, request):
        self.repair_calls += 1
        return _valid_response(request)


class _Editorial:
    def __init__(self) -> None: self.calls = 0
    def compose(self, request):
        self.calls += 1
        return _editorial_payload(request, report_id=request["report_id"])


class _Review:
    def __init__(self) -> None: self.calls = 0
    def review(self, request):
        self.calls += 1
        return {"decision": "APPROVE", "issues": []}


class _PdfRenderer:
    def render(self, document):
        return b"%PDF-1.4\n% provider-free qualification\n"


class _AnalysisProvider:
    """Deterministic provider double used behind the production analysis path."""

    def __init__(self):
        self.calls = []

    def generate(self, prompt, *, options=None):
        self.calls.append(prompt)
        if '"verdicts"' in prompt.system:
            candidate_ids = re.findall(r"candidate_id=([^\s]+)", prompt.user)
            return LLMResponse(content=json.dumps({
                "verdicts": [
                    {
                        "candidate_id": candidate_id,
                        "status": "SUPPORTED",
                        "supported_evidence_ids": [
                            ast.literal_eval(refs)[0]
                            for refs in re.findall(
                                r"evidence_refs=\[([^\]]+)\]", prompt.user,
                            )[:1]
                            if ast.literal_eval(refs)
                        ],
                        "unsupported_claim_parts": [],
                        "rationale": "deterministic supported fixture",
                    }
                    for candidate_id in candidate_ids
                ],
            }))
        if '"insights"' in prompt.system:
            finding_ids = re.findall(r"- id=([^\s]+) statement=", prompt.user)
            return LLMResponse(content=json.dumps({
                "insights": [{
                    "statement": "Selected evidence indicates a stable trend.",
                    "implication": "The selected scope is analyzable.",
                    "finding_refs": finding_ids[:1],
                    "research_question_refs": ["rq-retail"],
                    "confidence": 0.8,
                }],
            }))
        evidence_ids = re.findall(r"- id=([^\s]+) statement=", prompt.user)
        need = NEEDS[0]
        return LLMResponse(content=json.dumps({
            "findings": [{
                "statement": "Selected evidence supports the retail trend.",
                "rationale": "The selected evidence is directly grounded.",
                "evidence_refs": evidence_ids[:1],
                "research_question_refs": ["rq-retail"],
                "information_need_refs": [need],
                "finding_type": "synthesis",
                "confidence": 0.8,
            }],
        }))


@unittest.skipUnless(integration_tests_enabled(), "isolated PostgreSQL integration database required")
class FullDeskResearchProviderFreeE2ETests(PostgreSQLIntegrationTestCase):
    def _parent(self, container, design):
        project = container.project_service.create_project(
            "Ukraine retail provider-free E2E", owner_principal_id="owner",
            project_id=PROJECT, selected_methods=("DESK",),
        )
        brief = ResearchBrief(
            title="Ринок роздрібної торгівлі України у 2021–2026 роках",
            business_question="How did Ukraine retail change?",
            objectives=("Measure nominal, real and trend changes",), geography=("UA",),
            market="retail", timeframe="2021–2026", deliverables=("report", "pdf", "pptx"),
            language="uk",
        )
        template = WorkflowTemplate(
            "touchpoll-parent-template", "Touchpoll parent",
            [TaskDefinition("seed", "Persist synthetic parent", "proposal")],
            research_brief_snapshot=brief, research_design_snapshot=design,
        )
        container.workflow_service.publish_template_snapshot(template, project_id=PROJECT)
        run = container.workflow_service.create_workflow_run(template, project_id=PROJECT, run_id=PARENT)
        run.ready(); run.start(); run.tasks[0].ready(); run.tasks[0].start(); run.tasks[0].complete(); run.complete()
        container.workflow_service.save_workflow_run(run, expected_version=0, task_results={
            "research_readiness": {
                "analysis_ready": True, "complete_design_ready": False,
                "status": "insufficient", "eligible_information_need_ids": [],
                "analysis_eligible_information_need_ids": list(NEEDS),
            }
        })
        sources = container.source_service._source_repository
        evidences = container.evidence_service._evidence_repository
        findings = container.finding_service._finding_repository
        insights = container.insight_service._insight_repository
        for index in range(30):
            need = NEEDS[index] if index < 3 else None
            url = f"https://fixture.test/{need}/parent" if need else f"https://fixture.test/archive/{index}"
            text = (
                f"Ukraine retail authority {need}: 2021–2026 retail value was 100 UAH in 2021 and 120 UAH in 2026."
                if need else f"Ukraine retail historical source {index}, archived baseline 2020."
            )
            source = Source(
                f"parent-source-{index}", PROJECT, url, url, f"Parent {index}", TS,
                retrieval_status=RetrievalStatus.ACQUIRED, content_type="text/plain",
                content_text=text, content_checksum=sha256(text.encode()).hexdigest(),
                workflow_run_refs=(PARENT,), research_design_refs=(design.id,),
                research_question_refs=(("rq-retail",) if need else ()),
                information_need_refs=((need,) if need else ()),
            )
            sources.create(source)
        for index in range(19):
            source = sources.get_by_id(f"parent-source-{index}")
            locator = verify_grounding(source_text=source.content_text, excerpt=source.content_text)
            evidences.create(Evidence(
                f"parent-evidence-{index}", PROJECT, source.id, source.content_checksum,
                PARENT, design.id, source.content_text, source.content_text, TS,
                research_question_refs=("rq-retail",),
                information_need_refs=(),
                source_locator=locator.to_dict(), deduplication_key=f"parent-e-{index}",
                metadata={"observation_period": "2020"},
            ))
        for index in range(4):
            findings.create(Finding(
                f"parent-finding-{index}", PROJECT, PARENT, design.id,
                f"Historical parent finding {index}", "Historical baseline only",
                (f"parent-evidence-{index}",), TS,
                research_question_refs=("rq-retail",),
                information_need_refs=(),
                deduplication_key=f"parent-f-{index}",
            ))
        for index in range(5):
            insights.create(Insight(
                f"parent-insight-{index}", PROJECT, PARENT, design.id,
                f"Historical insight {index}", "Historical baseline",
                (f"parent-finding-{index % 4}",), TS,
                research_question_refs=("rq-retail",), deduplication_key=f"parent-i-{index}",
            ))
        return project

    def test_full_provider_free_extension_to_h3_delivery(self):
        design = _design(); search = _Search(); extractor = _EvidenceExtractor(design)
        analysis = _Analysis(); engine = _H3Engine(); editorial = _Editorial(); review = _Review()
        container = create_application_container(
            config=postgresql_application_config(
                background_execution_mode="external", search_provider="deterministic",
                evidence_extractor="deterministic", analysis_engine="deterministic",
                report_engine="deterministic", review_engine="deterministic",
                desk_report_contract_version=H3_CONTRACT_VERSION,
            ),
            overrides=ApplicationOverrides(
                search_provider=search, source_retriever=_Retriever(),
                evidence_extractor=extractor, analysis_engine=analysis,
                report_engine=engine, h3_editorial_provider=editorial,
                h3_review_provider=review,
            ),
        )
        self.addCleanup(container.shutdown)
        container.agency.initialize()
        configure_structured_finalization_test_boundary(container)
        project = self._parent(container, design)
        before_sources = [item.to_dict() for item in container.source_service.list_sources_for_run(PARENT, project_id=PROJECT)]
        self.assertEqual((30, 19, 4, 5), (
            len(before_sources), container.evidence_service.count_for_run(PROJECT, PARENT),
            container.finding_service.count_for_run(PROJECT, PARENT),
            container.insight_service.count_for_run(PROJECT, PARENT),
        ))
        extension = container.authority_extension_service.start(
            project_id=PROJECT, parent_workflow_run_id=PARENT, design=design,
            selected_information_need_ids=NEEDS,
            idempotency_key="touchpoll-full-provider-free-e2e", confirmed=True,
        )
        container.authority_extension_service.activate(extension.extension_id)
        drain_background_runs(container, worker_id="extension-worker")
        extension = container.authority_extension_service.extensions.get_by_id(extension.extension_id)
        state = container.authority_extension_service._state(extension.extension_workflow_run_id)
        self.assertEqual("succeeded", extension.status.value)
        self.assertEqual({need: "satisfied" for need in NEEDS}, {
            need: outcome.value for need, outcome in state.outcomes
        })
        self.assertIsNotNone(state.composition_id)
        composition = container.authority_extension_service.compositions.get_by_id(state.composition_id)
        self.assertEqual(PARENT, composition.parent_source_workflow_run_id)
        self.assertEqual(
            {PARENT, extension.extension_workflow_run_id},
            set(composition.member_workflow_run_ids),
        )
        self.assertEqual(before_sources, [item.to_dict() for item in container.source_service.list_sources_for_run(PARENT, project_id=PROJECT)])
        extension_sources = container.source_service.list_sources_for_run(
            extension.extension_workflow_run_id, project_id=PROJECT,
        )
        self.assertTrue(extension_sources)
        self.assertFalse(any("/parent" in item.canonical_url for item in extension_sources))

        extension_evidence = container.evidence_service.list_evidence_for_project(
            PROJECT, workflow_run_id=extension.extension_workflow_run_id,
        )
        cpi = [item for item in extension_evidence if "CPI general inflation" in item.statement]
        self.assertTrue(cpi)
        observations = container.authority_extension_service._state(
            extension.extension_workflow_run_id,
        ).observations
        cpi_observations = [item for item in observations if item.authority_kind == "cpi"]
        self.assertTrue(cpi_observations)
        self.assertEqual("satisfied", dict(state.outcomes)[NEEDS[1]].value)

        # Fresh repositories after composition prove the authority is durable.
        fresh = create_application_container(
            config=postgresql_application_config(
                background_execution_mode="external", search_provider="deterministic",
                evidence_extractor="deterministic", analysis_engine="deterministic",
                report_engine="deterministic", review_engine="deterministic",
                desk_report_contract_version=H3_CONTRACT_VERSION,
            ),
            overrides=ApplicationOverrides(
                search_provider=search, source_retriever=_Retriever(),
                evidence_extractor=extractor, analysis_engine=analysis,
                report_engine=engine, h3_editorial_provider=editorial,
                h3_review_provider=review,
            ),
        )
        self.addCleanup(fresh.shutdown); fresh.agency.initialize()
        configure_structured_finalization_test_boundary(fresh)
        fresh.project_deliverables_service.renderer = _PdfRenderer()
        durable_composition = fresh.authority_extension_service.compositions.get_by_id(state.composition_id)
        self.assertEqual(composition.composition_digest, durable_composition.composition_digest)

        all_evidence = [
            item for member in durable_composition.member_workflow_run_ids
            for item in fresh.evidence_service.list_evidence_for_project(PROJECT, workflow_run_id=member)
        ]
        all_findings = [
            item for member in durable_composition.member_workflow_run_ids
            for item in fresh.finding_service.list_findings_for_project(PROJECT, workflow_run_id=member)
        ]

        all_insights = [
            item for member in durable_composition.member_workflow_run_ids
            for item in fresh.insight_service.list_insights_for_project(PROJECT, workflow_run_id=member)
        ]
        plan = build_h3_coverage_plan(
            design=design, required_information_need_ids=NEEDS,
            findings=tuple(all_findings), evidence_by_id={item.id: item for item in all_evidence},
            insights=tuple(all_insights),
        )
        self.assertTrue(plan.is_fully_fillable)

        replay = fresh.desk_downstream_replay_service.start(
            project_id=PROJECT, source_run_id=PARENT, owner_id="owner",
        )
        replay_state = fresh.workflow_service.get_task_results(replay.id)
        self.assertEqual(replay_state[COMPOSED_AUTHORITY_KEY]["composition_id"], composition.composition_id)
        self.assertEqual(
            ["report", "review", "revision", "review", "finalization"],
            [task.executor_id for task in fresh.workflow_service.get_template(replay.workflow_template_id).task_definitions],
        )
        drain_background_runs(fresh, worker_id="h3-worker")
        terminal = fresh.workflow_service.get_workflow_run(replay.id)
        self.assertEqual("completed", terminal.status.value)
        reports = fresh.report_query_service.list_reports_for_project(PROJECT, workflow_run_id=replay.id)
        self.assertEqual(1, len(reports)); report = reports[0]
        claims = fresh.project_deliverables_service.report_claims.list_for_report(report.id, report.revision_number)
        self.assertTrue(claims)
        self.assertTrue(all(
            claim.structural_assertion["composed_authority"]["composition_digest"]
            == composition.composition_digest for claim in claims
        ))
        self.assertNotIn("999", report.executive_summary)
        reviews = fresh.review_query_service.list_reviews_for_project(PROJECT, workflow_run_id=replay.id)
        self.assertEqual(["approve"], [item.verdict.value for item in reviews])
        item = fresh.project_deliverables_service.source(
            PROJECT, "DESK", report.id, owner_id=project.owner_principal_id,
        )
        self.assertEqual("finalization_complete", item.finalization_state)
        self.assertIsNotNone(item.pdf); self.assertIsNotNone(item.pptx)
        pdf, pdf_content = fresh.project_deliverables_service.store.get(item.pdf.id)
        pptx, pptx_content = fresh.project_deliverables_service.store.get(item.pptx.id)
        self.assertTrue(pdf_content); self.assertTrue(pptx_content)
        self.assertEqual(item.document.approved_delivery_provenance, item.pdf.approved_delivery_provenance)
        self.assertEqual(item.pdf.approved_delivery_provenance, item.pptx.approved_delivery_provenance)

        replay_again = fresh.desk_downstream_replay_service.start(
            project_id=PROJECT, source_run_id=PARENT, owner_id="owner",
        )
        self.assertEqual(replay.id, replay_again.id)
        self.assertEqual(1, engine.initial_calls); self.assertEqual(1, engine.repair_calls)
        self.assertLessEqual(engine.initial_calls + engine.repair_calls + editorial.calls + review.calls, 7)
        self.assertEqual((30, 19, 4, 5), (
            fresh.source_service.count_acquired_for_run(PROJECT, PARENT),
            fresh.evidence_service.count_for_run(PROJECT, PARENT),
            fresh.finding_service.count_for_run(PROJECT, PARENT),
            fresh.insight_service.count_for_run(PROJECT, PARENT),
        ))

    def test_production_shaped_analysis_uses_budget_proxy_and_selected_scope(self):
        design = _design(); search = _Search(); extractor = _EvidenceExtractor(design)
        provider = _AnalysisProvider()
        container = create_application_container(
            config=postgresql_application_config(
                background_execution_mode="external", search_provider="deterministic",
                evidence_extractor="deterministic", analysis_engine="llm",
                report_engine="deterministic", review_engine="deterministic",
                desk_report_contract_version=H3_CONTRACT_VERSION,
            ),
            overrides=ApplicationOverrides(
                search_provider=search, source_retriever=_Retriever(),
                evidence_extractor=extractor, analysis_llm_client=provider,
                report_engine=_H3Engine(), h3_editorial_provider=_Editorial(),
                h3_review_provider=_Review(),
            ),
        )
        self.addCleanup(container.shutdown)
        container.agency.initialize()
        configure_structured_finalization_test_boundary(container)
        self._parent(container, design)
        extension = container.authority_extension_service.start(
            project_id=PROJECT, parent_workflow_run_id=PARENT, design=design,
            selected_information_need_ids=NEEDS,
            idempotency_key="production-shaped-analysis-e2e", confirmed=True,
        )
        container.authority_extension_service.activate(extension.extension_id)
        drain_background_runs(container, worker_id="extension-worker")
        extension = container.authority_extension_service.extensions.get_by_id(extension.extension_id)
        state = container.authority_extension_service._state(extension.extension_workflow_run_id)
        self.assertEqual("succeeded", extension.status.value)
        self.assertGreaterEqual(len(provider.calls), 3)
        self.assertLessEqual(len(provider.calls), 7)
        self.assertTrue(any(NEEDS[0] in prompt.user for prompt in provider.calls))
        self.assertFalse(any("archive" in prompt.user for prompt in provider.calls))
        self.assertTrue(all(
            need in set(NEEDS)
            for prompt in provider.calls
            for need in re.findall(r"information_needs=\['([^']+)'\]", prompt.user)
        ))
        self.assertIsNotNone(state.composition_id)
        self.assertEqual(3, state.budget.analysis_reserved)
        self.assertEqual(len(provider.calls), state.budget.provider_used)
        self.assertGreater(
            container.finding_service.count_for_run(
                PROJECT, extension.extension_workflow_run_id,
            ),
            0,
        )
        fresh = create_application_container(
            config=postgresql_application_config(
                background_execution_mode="external", search_provider="deterministic",
                evidence_extractor="deterministic", analysis_engine="llm",
                report_engine="deterministic", review_engine="deterministic",
                desk_report_contract_version=H3_CONTRACT_VERSION,
            ),
            overrides=ApplicationOverrides(
                search_provider=search, source_retriever=_Retriever(),
                evidence_extractor=extractor, analysis_llm_client=provider,
                report_engine=_H3Engine(), h3_editorial_provider=_Editorial(),
                h3_review_provider=_Review(),
            ),
        )
        self.addCleanup(fresh.shutdown)
        fresh.agency.initialize()
        restored = fresh.authority_extension_service._state(
            extension.extension_workflow_run_id,
        )
        self.assertEqual(state.budget, restored.budget)
        self.assertEqual(state.composition_id, restored.composition_id)
