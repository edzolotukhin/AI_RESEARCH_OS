from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.app import create_fastapi_app
from domain.planning.research_design import (
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)
from domain.research_brief import ResearchBrief
from domain.task_definition import TaskDefinition
from domain.workflow_template import WorkflowTemplate
from tests.api.helpers import build_test_container


class AuthorityExtensionOperatorIngressTests(unittest.TestCase):
    ORIGIN = "http://testserver"

    def setUp(self):
        self.container = build_test_container()
        delattr(self.container, "_test_api_key_plaintext")
        self.owner = self.container.identity_service.create_user(
            "owner@example.com", "Owner", "correct horse battery",
        )
        self.other = self.container.identity_service.create_user(
            "other@example.com", "Other", "another correct horse",
        )
        self.context = TestClient(create_fastapi_app(container=self.container))
        self.client = self.context.__enter__()
        self._login("owner@example.com", "correct horse battery")
        created = self.client.post(
            "/ui/projects",
            data={"name": "Extension", "selected_methods": "DESK"},
            follow_redirects=False,
        )
        self.project_id = created.headers["location"].rsplit("/", 1)[-1]
        design = ResearchDesign(
            "design",
            (ResearchQuestion("rq", "RQ"),),
            (InformationNeed(
                "in1", "rq", "Need", timeframe="2021", geography="UA",
            ),),
        )
        template = WorkflowTemplate(
            "parent-template",
            "Parent",
            [TaskDefinition("t", "t", "search")],
            research_brief_snapshot=ResearchBrief("Parent", "Parent question"),
            research_design_snapshot=design,
        )
        self.container.workflow_service.publish_template_snapshot(
            template, project_id=self.project_id,
        )
        self.parent = self.container.workflow_service.create_workflow_run(
            template, project_id=self.project_id,
        )
        self.url = f"/ui/projects/{self.project_id}/authority-extensions"
        self.body = {
            "parent_source_workflow_run_id": self.parent.id,
            "selected_information_need_ids": ["in1"],
            "confirmed": True,
        }

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.container.shutdown()

    def _login(self, email: str, password: str):
        return self.client.post(
            "/ui/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )

    def _post(self, *, key="operator-extension", body=None, origin=ORIGIN):
        headers = {"Idempotency-Key": key}
        if origin is not None:
            headers["Origin"] = origin
        return self.client.post(
            self.url, json=self.body if body is None else body,
            headers=headers, follow_redirects=False,
        )

    def test_owner_submission_is_idempotent_and_secret_free(self):
        before = len(self.container.workflow_service.list_workflow_runs_for_project(
            self.project_id,
        ))
        first = self._post()
        second = self._post()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["extension_id"], second.json()["extension_id"])
        self.assertEqual(first.json()["workflow_run_id"], second.json()["workflow_run_id"])
        self.assertEqual(
            len(self.container.workflow_service.list_workflow_runs_for_project(
                self.project_id,
            )),
            before + 1,
        )
        response_text = first.text.casefold()
        self.assertNotIn("authorization", response_text)
        self.assertNotIn("session", response_text)
        self.assertNotIn("api_key", response_text)

    def test_authentication_authorization_confirmation_and_shape_fail_closed(self):
        self.client.post("/ui/logout", follow_redirects=False)
        self.assertEqual(self._post(key="anonymous").status_code, 303)
        self.client.cookies.set("ai_research_os_session", "invalid-session")
        self.assertEqual(self._post(key="invalid-session").status_code, 303)
        self.client.cookies.delete("ai_research_os_session")

        self._login("other@example.com", "another correct horse")
        self.assertEqual(self._post(key="foreign").status_code, 404)

        self.client.post("/ui/logout", follow_redirects=False)
        self._login("owner@example.com", "correct horse battery")
        unconfirmed = dict(self.body, confirmed=False)
        self.assertEqual(
            self._post(key="unconfirmed", body=unconfirmed).status_code, 409,
        )
        extra = dict(self.body, authority_override={"minimum_sources": 0})
        self.assertEqual(self._post(key="extra", body=extra).status_code, 422)
        self.assertEqual(self._post(key="cross-origin", origin="https://attacker.invalid").status_code, 403)
        self.assertEqual(self._post(key="missing-origin", origin=None).status_code, 403)


if __name__ == "__main__":
    unittest.main()
