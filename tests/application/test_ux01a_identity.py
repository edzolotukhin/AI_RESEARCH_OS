import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from application.identity import IdentityService, PasswordHasher, ProjectRole, UserStatus
from infrastructure.persistence.memory.in_memory_identity_store import InMemoryIdentityStore


class IdentityServiceTests(unittest.TestCase):
    def setUp(self):
        self.store=InMemoryIdentityStore();self.service=IdentityService(self.store)
        self.alice=self.service.create_user("Alice@Example.com","Alice","correct horse battery")
        self.bob=self.service.create_user("bob@example.com","Bob","another correct horse")

    def test_password_hash_is_salted_and_authentication_is_generic(self):
        other=self.service.create_user("other@example.com","Other","correct horse battery")
        self.assertNotEqual(self.alice.password_hash,other.password_hash)
        self.assertNotIn("correct horse",self.alice.password_hash)
        self.assertEqual(self.service.authenticate("alice@example.com","correct horse battery"),self.alice)
        self.assertIsNone(self.service.authenticate("alice@example.com","wrong password value"))
        self.assertIsNone(self.service.authenticate("missing@example.com","wrong password value"))

    def test_session_logout_expiry_forgery_and_disable_fail_closed(self):
        token,_=self.service.create_session(self.alice);self.assertEqual(self.service.resolve_session(token),self.alice)
        self.assertIsNone(self.service.resolve_session(token+"x"));self.service.logout(token);self.assertIsNone(self.service.resolve_session(token))
        token,session=self.service.create_session(self.alice);self.store.sessions[session.token_hash]=replace(session,expires_at=datetime.now(UTC)-timedelta(seconds=1));self.assertIsNone(self.service.resolve_session(token))
        token,_=self.service.create_session(self.alice);self.service.disable_user(self.alice.id);self.assertIsNone(self.service.resolve_session(token))

    def test_membership_roles_removal_and_last_owner(self):
        self.service.add_membership("p",self.alice.id,ProjectRole.OWNER,actor_id=self.alice.id)
        self.service.add_membership("p",self.bob.id,ProjectRole.RESEARCHER,actor_id=self.alice.id)
        self.service.require("p",self.bob.id,mutate=True)
        self.service.change_role("p",self.bob.id,ProjectRole.VIEWER,actor_id=self.alice.id)
        with self.assertRaises(PermissionError):self.service.require("p",self.bob.id,mutate=True)
        with self.assertRaises(ValueError):self.service.remove_membership("p",self.alice.id,actor_id=self.alice.id)
        self.service.remove_membership("p",self.bob.id,actor_id=self.alice.id)
        with self.assertRaises(PermissionError):self.service.require("p",self.bob.id)

    def test_non_owner_cannot_administer_membership(self):
        self.service.add_membership("p",self.alice.id,ProjectRole.OWNER,actor_id=self.alice.id)
        self.service.add_membership("p",self.bob.id,ProjectRole.RESEARCHER,actor_id=self.alice.id)
        with self.assertRaises(PermissionError):self.service.change_role("p",self.alice.id,ProjectRole.VIEWER,actor_id=self.bob.id)

    def test_login_failures_are_bounded_without_revealing_account_existence(self):
        for _ in range(self.service.LOGIN_FAILURE_LIMIT):
            self.assertIsNone(self.service.authenticate("alice@example.com", "wrong password value"))
        self.assertIsNone(self.service.authenticate("alice@example.com", "correct horse battery"))
        for _ in range(self.service.LOGIN_FAILURE_LIMIT):
            self.assertIsNone(self.service.authenticate("missing@example.com", "wrong password value"))


if __name__=="__main__":unittest.main()
