from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import Mock

from application.factories.research_design_factory import ResearchDesignFactory
from application.exceptions.structured_output_error import StructuredOutputError
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.executor_catalog import ExecutorCatalog
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.planner.research_design_payload_schema import (
    PLANNER_PAYLOAD_SCHEMA,
    RESEARCH_DESIGN_PAYLOAD_SCHEMA,
)
from application.prompts.builders.planner_prompt_builder import PlannerPromptBuilder
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import PythonFormatPromptRenderer
from application.structured_output.correction_prompt import (
    StructuredOutputCorrectionPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.planning.research_design import ResearchDesign
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.workflow_run import WorkflowRun
from runtime.workflow_context import WorkflowContext


def _relation(identity, *, need="in-retention", question="rq-retention",
              aspect="repeat_purchase_rate", label="repeat purchase rate",
              relation_type="economic_context"):
    return {
        "relation_id": identity,
        "relation_type": relation_type,
        "information_need_refs": [need],
        "research_question_refs": [question],
        "required_aspect_refs": [aspect] if aspect is not None else [],
        "concepts": [identity],
        "lexical_representations": [{
            "representation_id": f"{identity}-en",
            "language": "en",
            "label": label,
            "normalized_phrases": [label],
            "concept_refs": [identity],
        }],
        "explanation": label,
    }


def planner_payload(*, relations=None):
    if relations is None:
        relations = [
            _relation("repeat-rate"),
            _relation(
                "cancellation-rate", need="in-cancellation", question="rq-cancellation",
                aspect="cancellation_rate", label="cancellation rate",
            ),
            {**_relation("malformed"), "relation_id": ""},
            _relation("bad-type", relation_type="free_form_context"),
            _relation("stale", need="in-stale"),
            _relation("cross-question", question="rq-cancellation"),
            _relation("wrong-aspect", aspect="cancellation_rate"),
            _relation("aspect-mismatch", label="billing friction"),
            _relation("ungrounded", aspect=None, label="satellite weather"),
            {**_relation("missing-lexical"), "lexical_representations": []},
        ]
    return {
        "research_questions": [
            {
                "id": "rq-retention",
                "question": "How stable is customer retention?",
                "objective_refs": ["Assess customer retention."],
                "priority": 1,
                "rationale": "Retention determines durable demand.",
            },
            {
                "id": "rq-cancellation",
                "question": "What is the cancellation pattern?",
                "objective_refs": ["Assess customer retention."],
                "priority": 2,
                "rationale": "Cancellation is a bounded retention outcome.",
            },
        ],
        "information_needs": [
            {
                "id": "in-retention",
                "research_question_id": "rq-retention",
                "description": "Establish repeat purchase rate for subscription services.",
                "priority": 1,
                "preferred_source_types": ["company reports"],
                "timeframe": "Current period",
                "geography": "Global",
                "evidence_expectation": {
                    "nature": "quantitative",
                    "required_aspects": ["repeat_purchase_rate"],
                    "geography": "Global",
                    "timeframe": "Current period",
                    "requires_quantitative_evidence": True,
                },
            },
            {
                "id": "in-cancellation",
                "research_question_id": "rq-cancellation",
                "description": "Establish cancellation rate for subscription services.",
                "priority": 2,
                "preferred_source_types": ["company reports"],
                "timeframe": "Current period",
                "geography": "Global",
                "evidence_expectation": {
                    "nature": "quantitative",
                    "required_aspects": ["cancellation_rate"],
                    "geography": "Global",
                    "timeframe": "Current period",
                    "requires_quantitative_evidence": True,
                },
            },
        ],
        "research_subject": {
            "version": "RESEARCH_SUBJECT/1",
            "canonical_label": "Consumer retention systems",
            "canonical_language": "en",
            "lexical_representations": [
                {"language": "en", "label": "subscription retention behavior"},
            ],
            "supporting_relations": relations,
            "exclusions": ["primary field experiments"],
        },
        "source_strategy": ["company reports"],
        "analysis_plan": ["Compare retention and cancellation measures."],
        "deliverable_plan": ["Retention assessment"],
        "assumptions": [],
        "limitations": ["Secondary evidence only."],
        "language": "en",
    }


def _project():
    project = Project(id="ow20d-project", name="Generic subscription study")
    project.research_brief = ResearchBrief(
        title="Generic subscription study",
        business_question="How stable is subscription demand?",
        objectives=("Assess customer retention.",),
        market="Subscription services",
        language="en",
    )
    return project


def _design(payload):
    parsed = StructuredOutputParser().parse(
        json.dumps(payload), payload_contract=ResearchDesignPayloadContract(),
    )
    return PlannerDesignServiceImpl(
        ResearchDesignParser(), ResearchDesignFactory(),
    ).create_design(_project(), parsed)


def test_real_planner_shaped_payload_preserves_valid_siblings_and_diagnostics():
    design = _design(planner_payload())
    subject = design.research_subject

    assert subject.canonical_label == "Subscription services"
    assert {row.label for row in subject.lexical_representations} == {
        "Subscription services", "subscription retention behavior",
    }
    assert {row.relation_id for row in subject.supporting_relations} == {
        "repeat-rate", "cancellation-rate",
    }
    for relation in subject.supporting_relations:
        assert set(relation.information_need_refs) <= {
            row.id for row in design.information_needs
        }
        assert set(relation.research_question_refs) <= {
            row.id for row in design.research_questions
        }

    diagnostics = subject.provenance["relation_diagnostics"]
    assert diagnostics == {
        "subject_proposal_present": True,
        "proposed_relation_count": 10,
        "accepted_relation_count": 2,
        "rejected_relation_count": 8,
        "rejection_category_counts": {
            "malformed_shape": 1,
            "invalid_relation_type": 1,
            "missing_or_stale_information_need": 1,
            "invalid_research_question_scope": 1,
            "invalid_required_aspect_scope": 1,
            "missing_semantic_grounding": 2,
            "aspect_lexical_mismatch": 0,
            "missing_lexical_representation": 1,
        },
    }

    reduced = replace(
        subject, supporting_relations=subject.supporting_relations[:-1],
        semantic_fingerprint="",
    )
    assert reduced.semantic_fingerprint != subject.semantic_fingerprint
    assert ResearchDesign.from_dict(design.to_dict()) == design


def test_empty_planner_relation_list_is_distinguishable_from_rejection():
    diagnostics = _design(planner_payload(relations=[])).research_subject.provenance[
        "relation_diagnostics"
    ]
    assert diagnostics["subject_proposal_present"] is True
    assert diagnostics["proposed_relation_count"] == 0
    assert diagnostics["accepted_relation_count"] == 0
    assert diagnostics["rejected_relation_count"] == 0
    assert set(diagnostics["rejection_category_counts"].values()) == {0}


def test_exact_aspect_ref_accepts_ukrainian_inflection_grounded_in_linked_need():
    payload = planner_payload(relations=[_relation(
        "income-level", aspect="household_income_level",
        label="динаміка доходів домогосподарств",
    )])
    payload["research_questions"][0]["question"] = (
        "Як змінюються доходи домогосподарств?"
    )
    payload["information_needs"][0]["description"] = (
        "Встановити динаміку доходів домогосподарств."
    )
    payload["information_needs"][0]["evidence_expectation"]["required_aspects"] = [
        "household_income_level"
    ]

    subject = _design(payload).research_subject

    assert [row.relation_id for row in subject.supporting_relations] == ["income-level"]
    assert subject.supporting_relations[0].required_aspect_refs == (
        "household_income_level",
    )


def test_exact_aspect_ref_accepts_other_language_grounded_in_linked_need():
    payload = planner_payload(relations=[_relation(
        "retention-es", aspect="customer_retention_rate",
        label="retención de clientes",
    )])
    payload["research_questions"][0]["question"] = (
        "¿Cómo cambia la retención de clientes?"
    )
    payload["information_needs"][0]["description"] = (
        "Establecer la retención de clientes durante el período."
    )
    payload["information_needs"][0]["evidence_expectation"]["required_aspects"] = [
        "customer_retention_rate"
    ]

    subject = _design(payload).research_subject

    assert [row.relation_id for row in subject.supporting_relations] == ["retention-es"]


def test_invalid_stale_or_wrong_scope_aspect_refs_remain_rejected():
    subject = _design(planner_payload(relations=[
        _relation("stale-aspect", aspect="missing_aspect", label="repeat purchase rate"),
        _relation("wrong-scope", aspect="cancellation_rate", label="repeat purchase rate"),
    ])).research_subject

    assert subject.supporting_relations == ()
    diagnostics = subject.provenance["relation_diagnostics"]
    assert diagnostics["rejection_category_counts"]["invalid_required_aspect_scope"] == 2


def test_exact_aspect_ref_does_not_admit_unrelated_relation_text():
    subject = _design(planner_payload(relations=[
        _relation("unrelated", label="satellite weather patterns"),
    ])).research_subject

    assert subject.supporting_relations == ()
    diagnostics = subject.provenance["relation_diagnostics"]
    assert diagnostics["rejection_category_counts"]["missing_semantic_grounding"] == 1


def test_initial_and_correction_contracts_share_complete_subject_schema():
    assert PLANNER_PAYLOAD_SCHEMA is RESEARCH_DESIGN_PAYLOAD_SCHEMA
    for field in (
        '"research_subject"', '"supporting_relations"', '"relation_id"',
        '"information_need_refs"', '"research_question_refs"',
        '"required_aspect_refs"', '"lexical_representations"', '"exclusions"',
    ):
        assert field in RESEARCH_DESIGN_PAYLOAD_SCHEMA

    correction = StructuredOutputCorrectionPromptBuilder().build(
        original_prompt=Prompt(system="system", user="user"),
        invalid_response=LLMResponse(content="{"),
        error=StructuredOutputError("invalid", stage="validate"),
        payload_schema=PLANNER_PAYLOAD_SCHEMA,
        truncated=False,
    )
    assert '"research_subject"' in correction.user
    assert '"supporting_relations"' in correction.user


def test_rendered_initial_project_prompt_contains_canonical_schema():
    builder = PlannerPromptBuilder(
        FileTemplateLoader(), PythonFormatPromptRenderer(), ExecutorCatalog(()),
    )
    context = WorkflowContext(
        project=_project(),
        workflow_run=WorkflowRun(id="planning"),
    )
    prompt = builder.build(context)
    assert RESEARCH_DESIGN_PAYLOAD_SCHEMA in prompt.system
    assert '"supporting_relations"' in prompt.system


def test_real_correction_retry_retains_composite_subject_contract():
    client = Mock()
    client.generate.side_effect = [
        LLMResponse(content="{ invalid"),
        LLMResponse(content=json.dumps(planner_payload(relations=[_relation("repeat-rate")]))),
    ]
    payload = StructuredOutputGenerator(
        llm_client=client,
        parser=StructuredOutputParser(),
        max_attempts=2,
    ).generate(
        Prompt(system="system", user="user"),
        payload_contract=ResearchDesignPayloadContract(),
    )
    correction = client.generate.call_args_list[1].args[0]
    assert '"research_subject"' in correction.user
    assert '"supporting_relations"' in correction.user
    assert len(_design(payload).research_subject.supporting_relations) == 1


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for function in (
        test_real_planner_shaped_payload_preserves_valid_siblings_and_diagnostics,
        test_empty_planner_relation_list_is_distinguishable_from_rejection,
        test_initial_and_correction_contracts_share_complete_subject_schema,
        test_rendered_initial_project_prompt_contains_canonical_schema,
        test_real_correction_retry_retains_composite_subject_contract,
    ):
        suite.addTest(unittest.FunctionTestCase(function))
    return suite
