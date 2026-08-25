from dataclasses import replace

from domain.quantitative.measurement_reconciliation import (
    ReconciliationLifecycle, ReviewedMeasurementMapping,
)
from domain.quantitative.questionnaire_authority import (
    QuestionnaireRoutingRule, RoutingAction, RoutingActionType,
    RoutingCondition, RoutingConditionKind,
)
from tests.application.quantitative.test_property_rb_measurement_reconciliation import (
    PropertyRBMeasurementReconciliationTests,
)
from tests.application.quantitative.test_property_ra_questionnaire_authority import (
    PropertyRAQuestionnaireAuthorityTests,
)


class PropertyRBCompletionTests(PropertyRBMeasurementReconciliationTests):
    def test_reviewed_rename_requires_exact_approval_and_survives_restart(self):
        expected = self.schema.variables[0]
        actual = replace(self.codebook.variables[0], name="renamed_external_variable")
        decision = ReviewedMeasurementMapping(
            "mapping-decision", expected.expected_variable_id, expected.fingerprint,
            actual.variable_id, actual.fingerprint, (), (), (), (), "owner",
            "External codebook confirms stable semantic identity", "now", "decision-fingerprint",
        )
        codebook = replace(self.codebook, variables=(actual,) + self.codebook.variables[1:])
        draft = self.create(version_id="reviewed-v1", codebook=codebook, reviewed_mappings=(decision,))
        self.assertEqual(draft.lifecycle_status, ReconciliationLifecycle.DRAFT)
        with self.assertRaisesRegex(Exception, "stale"):
            self.service.approve(draft.version_id, project_id=self.project, run_id=self.run,
                approval_id="rb-approval", expected_fingerprint="stale", actor_id="owner",
                decided_at="later", rationale="Approved reviewed mapping")
        approved = self.service.approve(draft.version_id, project_id=self.project, run_id=self.run,
            approval_id="rb-approval", expected_fingerprint=draft.fingerprint, actor_id="owner",
            decided_at="later", rationale="Approved reviewed mapping")
        self.assertEqual(approved.lifecycle_status, ReconciliationLifecycle.APPROVED)
        self.assertNotEqual(approved.version_id, draft.version_id)
        resolved = self.service.resolve_current_accepted(project_id=self.project, run_id=self.run,
            dataset=self.dataset, codebook=codebook)
        self.assertEqual(resolved.fingerprint, approved.fingerprint)

    def test_supported_single_choice_skip_route_derives_qc_rule(self):
        ra = PropertyRAQuestionnaireAuthorityTests(methodName="runTest"); ra.setUp()
        route = QuestionnaireRoutingRule(
            "skip-quality", "q-sex", 1,
            RoutingCondition(RoutingConditionKind.EQUALS_OPTION, question_id="q-sex", option_ids=("sex-a",)),
            RoutingAction(RoutingActionType.SKIP_QUESTION, target_id="q-route"),
        )
        draft = ra.create(version_id="route-questionnaire", routes=(route,))
        questionnaire = ra.approve(draft)
        schema = ra.service.derive_expected_measurement_schema(questionnaire.version_id, project_id=ra.project)
        variables = tuple(replace(self.codebook.variables[0], variable_id="route-"+item.expected_variable_id,
            name=item.variable_name, label=item.label, variable_type=item.variable_type,
            role=item.analytical_role, measurement_level=item.measurement_level,
            value_labels=tuple(item.value_labels), missing_rules=(), pii_classification=item.pii_expectation,
            multiple_response_set=item.multiple_response_set_id, semantic_hooks=item.semantic_hooks,
            fingerprint="route-fp-"+item.expected_variable_id) for item in schema.variables)
        codebook = replace(self.codebook, variables=variables)
        dataset = replace(self.dataset, project_id=ra.project, run_id=ra.run,
            codebook_version_id=codebook.codebook_version_id, codebook_fingerprint=codebook.fingerprint)
        from application.quantitative.measurement_reconciliation import QuantitativeMeasurementReconciliationService
        service = QuantitativeMeasurementReconciliationService(repository=self.repository,
            questionnaire_service=ra.service, digest_provider=self.digest)
        value = service.create(reconciliation_id="route-rb", version_id="route-rb-v1",
            project_id=ra.project, run_id=ra.run, dataset=dataset, codebook=codebook,
            created_at="now", created_by="owner")
        snapshot = self.repository.get_snapshot(value.questionnaire_snapshot_id, project_id=ra.project)
        self.assertEqual(len(snapshot.routing_rules), 1)
        self.assertEqual(snapshot.routing_rules[0].antecedent_variable_id, "route-ev-sex")
        self.assertEqual(snapshot.routing_rules[0].target_variable_id, "route-ev-route")
