import unittest
from fastapi.testclient import TestClient
from api.app import create_fastapi_app
from tests.api.helpers import build_test_container


class BrowserIdentityE2ETests(unittest.TestCase):
    def setUp(self):
        self.container=build_test_container()
        delattr(self.container,"_test_api_key_plaintext")
        self.alice=self.container.identity_service.create_user("alice@example.com","Alice","correct horse battery")
        self.bob=self.container.identity_service.create_user("bob@example.com","Bob","another correct horse")
        self.context=TestClient(create_fastapi_app(container=self.container));self.client=self.context.__enter__()
    def tearDown(self):
        self.context.__exit__(None,None,None);self.container.shutdown()
    def login(self,email,password):return self.client.post("/ui/login",data={"email":email,"password":password},follow_redirects=False)
    def logout(self):return self.client.post("/ui/logout",follow_redirects=False)
    def test_new_project_route_requires_login_not_existing_membership(self):
        anonymous = self.client.get("/ui/projects/new", follow_redirects=False)
        self.assertEqual(anonymous.status_code, 303)
        self.assertTrue(anonymous.headers["location"].startswith("/ui/login?next="))

        self.assertEqual(self.login("bob@example.com", "another correct horse").status_code, 303)
        self.assertEqual(self.client.get("/ui/projects/new").status_code, 200)

        self.logout(); self.login("alice@example.com", "correct horse battery")
        created = self.client.post(
            "/ui/projects", data={"name": "Alice only", "selected_methods": "DESK"},
            follow_redirects=False,
        )
        project_id = created.headers["location"].rsplit("/", 1)[-1]
        self.logout(); self.login("bob@example.com", "another correct horse")
        self.assertEqual(self.client.get(f"/ui/projects/{project_id}").status_code, 404)

    def test_login_project_membership_role_removal_and_logout(self):
        self.assertEqual(self.client.get("/ui/projects",follow_redirects=False).status_code,303)
        self.assertEqual(self.login("alice@example.com","wrong password value").status_code,401)
        response=self.login("alice@example.com","correct horse battery");self.assertEqual(response.status_code,303)
        cookie=response.headers["set-cookie"].lower();self.assertIn("httponly",cookie);self.assertIn("samesite=lax",cookie)
        created=self.client.post("/ui/projects",data={"name":"Secret Project A","selected_methods":"DESK"},follow_redirects=False)
        project_id=created.headers["location"].rsplit("/",1)[-1]
        membership=self.container.identity_service.store.get_membership(project_id,self.alice.id)
        self.assertEqual(membership.role.value,"OWNER")
        self.logout();self.login("bob@example.com","another correct horse")
        self.assertNotIn("Secret Project A",self.client.get("/ui/projects").text)
        self.assertEqual(self.client.get(f"/ui/projects/{project_id}").status_code,404)
        self.assertEqual(self.client.get(f"/ui/projects/{project_id}/outputs").status_code,404)
        self.assertEqual(self.client.get(f"/ui/projects/{project_id}/reports/DESK/guessed/pdf/guessed").status_code,404)
        self.logout();self.login("alice@example.com","correct horse battery")
        self.assertEqual(self.client.post(f"/ui/projects/{project_id}/members",data={"user_id":self.bob.id,"role":"RESEARCHER"},follow_redirects=False).status_code,303)
        self.logout();self.login("bob@example.com","another correct horse")
        self.assertIn("Secret Project A",self.client.get("/ui/projects").text)
        self.logout();self.login("alice@example.com","correct horse battery")
        self.client.post(f"/ui/projects/{project_id}/members/{self.bob.id}/role",data={"role":"VIEWER"})
        self.logout();self.login("bob@example.com","another correct horse")
        self.assertEqual(self.client.post(f"/ui/projects/{project_id}/methods",data={"method":"QUALITATIVE"}).status_code,404)
        self.logout();self.login("alice@example.com","correct horse battery")
        self.client.post(f"/ui/projects/{project_id}/members/{self.bob.id}/remove")
        self.logout();self.login("bob@example.com","another correct horse")
        self.assertEqual(self.client.get(f"/ui/projects/{project_id}").status_code,404)
        self.logout();self.assertEqual(self.client.get("/ui/projects",follow_redirects=False).status_code,303)

    def test_cross_origin_mutation_is_rejected_and_account_has_no_service_secret(self):
        response=self.login("alice@example.com","correct horse battery")
        self.assertEqual(response.status_code,303)
        denied=self.client.post("/ui/projects",data={"name":"Nope","selected_methods":"DESK"},
                                headers={"Origin":"https://attacker.invalid"},follow_redirects=False)
        self.assertEqual(denied.status_code,403)
        account=self.client.get("/ui/account")
        self.assertEqual(account.status_code,200)
        self.assertIn("Alice",account.text)
        self.assertNotIn("api_key",account.text.casefold())
        self.assertNotIn("authorization",account.text.casefold())

    def test_disabled_existing_session_fails_closed(self):
        self.login("alice@example.com","correct horse battery");self.container.identity_service.disable_user(self.alice.id)
        self.assertEqual(self.client.get("/ui/projects",follow_redirects=False).status_code,303)
        self.assertEqual(self.login("alice@example.com","correct horse battery").status_code,401)


if __name__=="__main__":unittest.main()
