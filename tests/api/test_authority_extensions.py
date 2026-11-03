from __future__ import annotations

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief
from domain.task_definition import TaskDefinition
from domain.workflow_template import WorkflowTemplate
from tests.api.auth_helpers import auth_headers, bootstrap_second_test_api_key
from tests.api.helpers import ApiTestCase, AuthenticatedTestClient


class AuthorityExtensionApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.project_id = self.client.post("/projects", json={"name": "Extension"}).json()["id"]
        design = ResearchDesign(
            "design", (ResearchQuestion("rq", "RQ"),),
            (InformationNeed("in1", "rq", "Need", timeframe="2021", geography="UA"),),
        )
        template = WorkflowTemplate(
            "parent-template", "Parent", [TaskDefinition("t", "t", "search")],
            research_brief_snapshot=ResearchBrief("Parent", "Parent question"),
            research_design_snapshot=design,
        )
        self.container.workflow_service.publish_template_snapshot(template, project_id=self.project_id)
        self.parent = self.container.workflow_service.create_workflow_run(template, project_id=self.project_id)
        self.url = f"/projects/{self.project_id}/authority-extensions"
        self.body = {"parent_source_workflow_run_id": self.parent.id,
                     "selected_information_need_ids": ["in1"], "confirmed": True}

    def _post(self, **kwargs):
        headers = {"Idempotency-Key": kwargs.pop("key", "extension-key")}
        return self.client.post(self.url, json=kwargs.pop("body", self.body), headers=headers)

    def test_owner_submission_and_idempotency_are_durable(self):
        first = self._post(); second = self._post()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["extension_id"], second.json()["extension_id"])
        self.assertEqual(first.json()["workflow_run_id"], second.json()["workflow_run_id"])
        self.assertEqual(self.container.workflow_service.get_workflow_run(first.json()["workflow_run_id"]).status.value, "running")

    def test_unauthorized_wrong_parent_and_wrong_project_are_rejected(self):
        other = bootstrap_second_test_api_key(self.container, name="other")
        foreign = AuthenticatedTestClient(self._raw_client, auth_headers(other))
        self.assertIn(foreign.post(self.url, json=self.body, headers={"Idempotency-Key": "x"}).status_code, {403, 404})
        bad = dict(self.body, parent_source_workflow_run_id="missing")
        self.assertIn(self._post(body=bad, key="bad-parent").status_code, {403, 404})
        self.assertIn(self.client.post("/projects/missing/authority-extensions", json=self.body,
                                      headers={"Idempotency-Key": "wrong"}).status_code, {403, 404})

    def test_scope_confirmation_and_client_gap_semantics_fail_closed(self):
        outside = dict(self.body, selected_information_need_ids=["foreign"])
        self.assertEqual(self._post(body=outside, key="outside").status_code, 409)
        missing = dict(self.body); missing.pop("confirmed")
        self.assertEqual(self._post(body=missing, key="missing").status_code, 422)
        arbitrary = dict(self.body, gap_contract={"minimum_independent_sources": 0})
        self.assertEqual(self._post(body=arbitrary, key="arbitrary").status_code, 422)

    def test_missing_capability_leaves_workflow_paused(self):
        service = self.container.authority_extension_service
        service.capability_check = lambda: False
        response = self._post(key="blocked")
        self.assertEqual(response.status_code, 409)
        extension = service.extensions.get_by_idempotency_key(self.project_id, "blocked")
        run = self.container.workflow_service.get_workflow_run(extension.extension_workflow_run_id)
        self.assertEqual(run.status.value, "paused")
