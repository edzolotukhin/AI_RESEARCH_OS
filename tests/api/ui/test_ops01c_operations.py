import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from api.app import create_fastapi_app
from application.operations.status import OperationsStatusService
from tests.api.helpers import build_test_container

class OperationsUiTests(unittest.TestCase):
    def setUp(self):
        self.container = build_test_container(); delattr(self.container, "_test_api_key_plaintext")
        self.admin = self.container.identity_service.create_user("operator@example.com", "Pilot Operator", "correct horse battery")
        self.researcher = self.container.identity_service.create_user("researcher@example.com", "Researcher", "another correct horse")
        self.viewer = self.container.identity_service.create_user("viewer@example.com", "Viewer", "viewer correct horse")
        self.root = tempfile.TemporaryDirectory(); now = datetime.now(timezone.utc)
        worker = Path(self.root.name)/"worker.json"; backup = Path(self.root.name)/"backup.json"; storage = Path(self.root.name)/"storage"; storage.mkdir()
        worker.write_text(json.dumps({"observed_at": now.isoformat()}), encoding="utf-8"); backup.write_text('{"within_24h_policy":true}', encoding="utf-8")
        self.container.operations_status_service = OperationsStatusService(readiness=lambda:(True,"ready"), environment="pilot", worker_status_file=str(worker), backup_status_file=str(backup), storage_paths={"Protected artifacts":str(storage)})
        self.env = patch.dict(os.environ, {"PILOT_ADMIN_USER_ID": self.admin.id}, clear=False); self.env.start()
        self.context=TestClient(create_fastapi_app(container=self.container)); self.client=self.context.__enter__()
    def tearDown(self):
        self.context.__exit__(None,None,None); self.env.stop(); self.root.cleanup(); self.container.shutdown()
    def login(self,user,password): return self.client.post("/ui/login",data={"email":user,"password":password},follow_redirects=False)
    def test_operator_can_access_bounded_read_only_page(self):
        self.login("operator@example.com","correct horse battery"); response=self.client.get("/ui/operations")
        self.assertEqual(response.status_code,200)
        for value in ("Операції","Healthy","Database","Worker","Backup","Protected artifacts","Transcription provider"):
            self.assertIn(value,response.text)
        self.assertNotIn("postgresql://",response.text); self.assertNotIn("api_key",response.text.casefold())
    def test_researcher_and_unauthenticated_are_denied_server_side(self):
        self.assertEqual(self.client.get("/ui/operations",follow_redirects=False).status_code,303)
        self.login("researcher@example.com","another correct horse")
        self.assertEqual(self.client.get("/ui/operations").status_code,403)
        self.assertNotIn("Операції",self.client.get("/ui/projects").text)
        self.client.post("/ui/logout", follow_redirects=False)
        self.login("viewer@example.com","viewer correct horse")
        self.assertEqual(self.client.get("/ui/operations").status_code,403)

if __name__ == "__main__": unittest.main()
