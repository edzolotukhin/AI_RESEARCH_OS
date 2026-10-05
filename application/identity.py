"""Pilot human identity, browser sessions, and project memberships."""
from __future__ import annotations

from dataclasses import dataclass
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import hmac
import secrets
from typing import Protocol
from uuid import uuid4

current_human_actor_id: ContextVar[str | None] = ContextVar("current_human_actor_id", default=None)


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProjectRole(StrEnum):
    OWNER = "OWNER"
    RESEARCHER = "RESEARCHER"
    VIEWER = "VIEWER"


@dataclass(frozen=True)
class User:
    id: str
    email: str
    display_name: str
    password_hash: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BrowserSession:
    id: str
    user_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class ProjectMembership:
    project_id: str
    user_id: str
    role: ProjectRole
    created_at: datetime
    created_by: str | None


class IdentityStore(Protocol):
    def create_user(self, user: User) -> None: ...
    def get_user(self, user_id: str) -> User | None: ...
    def get_user_by_email(self, email: str) -> User | None: ...
    def list_users(self) -> list[User]: ...
    def set_user_status(self, user_id: str, status: UserStatus, at: datetime) -> None: ...
    def create_session(self, session: BrowserSession) -> None: ...
    def get_session_by_hash(self, token_hash: str) -> BrowserSession | None: ...
    def revoke_session(self, token_hash: str, at: datetime) -> None: ...
    def revoke_user_sessions(self, user_id: str, at: datetime) -> None: ...
    def create_membership(self, membership: ProjectMembership) -> None: ...
    def get_membership(self, project_id: str, user_id: str) -> ProjectMembership | None: ...
    def list_memberships_for_user(self, user_id: str) -> list[ProjectMembership]: ...
    def list_memberships_for_project(self, project_id: str) -> list[ProjectMembership]: ...
    def update_membership_role(self, project_id: str, user_id: str, role: ProjectRole) -> None: ...
    def remove_membership(self, project_id: str, user_id: str) -> None: ...


class PasswordHasher:
    """Versioned stdlib scrypt encoding; no application-defined cipher."""
    _N, _R, _P = 2**14, 8, 1

    def hash(self, password: str) -> str:
        self._validate(password)
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=self._N, r=self._R, p=self._P, dklen=32)
        return f"scrypt${self._N}${self._R}${self._P}${salt.hex()}${digest.hex()}"

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt, expected = encoded.split("$", 5)
            if algorithm != "scrypt": return False
            actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
            return hmac.compare_digest(actual, bytes.fromhex(expected))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _validate(password: str) -> None:
        if len(password) < 12 or len(password) > 256:
            raise ValueError("Password must contain between 12 and 256 characters")


class IdentityService:
    SESSION_TTL = timedelta(hours=12)
    LOGIN_WINDOW = timedelta(minutes=15)
    LOGIN_FAILURE_LIMIT = 5
    _ROLES_MUTATE = {ProjectRole.OWNER, ProjectRole.RESEARCHER}

    def __init__(self, store: IdentityStore, *, hasher: PasswordHasher | None = None):
        self.store, self.hasher = store, hasher or PasswordHasher()
        self._login_failures: dict[str, list[datetime]] = {}

    def create_user(self, email: str, display_name: str, password: str) -> User:
        email = email.strip().casefold(); display_name = display_name.strip()
        if "@" not in email or len(email) > 254 or not display_name:
            raise ValueError("A valid email and display name are required")
        if self.store.get_user_by_email(email): raise ValueError("User already exists")
        now = datetime.now(UTC)
        user = User(str(uuid4()), email, display_name, self.hasher.hash(password), UserStatus.ACTIVE, now, now)
        self.store.create_user(user); return user

    def authenticate(self, email: str, password: str) -> User | None:
        identity = email.strip().casefold(); now = datetime.now(UTC)
        recent = [value for value in self._login_failures.get(identity, ()) if now - value < self.LOGIN_WINDOW]
        self._login_failures[identity] = recent
        if len(recent) >= self.LOGIN_FAILURE_LIMIT: return None
        user = self.store.get_user_by_email(identity)
        encoded = user.password_hash if user else self.hasher.hash("invalid-password-placeholder")
        valid = self.hasher.verify(password, encoded)
        if valid and user and user.status is UserStatus.ACTIVE:
            self._login_failures.pop(identity, None); return user
        recent.append(now); self._login_failures[identity] = recent
        return None

    def create_session(self, user: User) -> tuple[str, BrowserSession]:
        now = datetime.now(UTC); token = secrets.token_urlsafe(32)
        session = BrowserSession(str(uuid4()), user.id, self._token_hash(token), now, now + self.SESSION_TTL)
        self.store.create_session(session); return token, session

    def resolve_session(self, token: str | None) -> User | None:
        if not token: return None
        session = self.store.get_session_by_hash(self._token_hash(token))
        if not session or session.revoked_at or session.expires_at <= datetime.now(UTC): return None
        user = self.store.get_user(session.user_id)
        return user if user and user.status is UserStatus.ACTIVE else None

    def logout(self, token: str | None) -> None:
        if token: self.store.revoke_session(self._token_hash(token), datetime.now(UTC))

    def disable_user(self, user_id: str) -> None:
        now = datetime.now(UTC); self.store.set_user_status(user_id, UserStatus.DISABLED, now); self.store.revoke_user_sessions(user_id, now)

    def enable_user(self, user_id: str) -> None:
        self.store.set_user_status(user_id, UserStatus.ACTIVE, datetime.now(UTC))

    def add_membership(self, project_id: str, user_id: str, role: ProjectRole, *, actor_id: str | None) -> ProjectMembership:
        existing = self.store.get_membership(project_id, user_id)
        if existing: raise ValueError("Membership already exists")
        membership = ProjectMembership(project_id, user_id, role, datetime.now(UTC), actor_id)
        self.store.create_membership(membership); return membership

    def require(self, project_id: str, user_id: str, *, mutate: bool = False, owner: bool = False) -> ProjectMembership:
        membership = self.store.get_membership(project_id, user_id)
        if not membership or (owner and membership.role is not ProjectRole.OWNER) or (mutate and membership.role not in self._ROLES_MUTATE):
            raise PermissionError("Project access denied")
        return membership

    def change_role(self, project_id: str, user_id: str, role: ProjectRole, *, actor_id: str) -> None:
        self.require(project_id, actor_id, owner=True)
        current = self.require(project_id, user_id)
        if current.role is ProjectRole.OWNER and role is not ProjectRole.OWNER and self._owner_count(project_id) <= 1:
            raise ValueError("Project must retain at least one OWNER")
        self.store.update_membership_role(project_id, user_id, role)

    def remove_membership(self, project_id: str, user_id: str, *, actor_id: str) -> None:
        self.require(project_id, actor_id, owner=True); current = self.require(project_id, user_id)
        if current.role is ProjectRole.OWNER and self._owner_count(project_id) <= 1:
            raise ValueError("Project must retain at least one OWNER")
        self.store.remove_membership(project_id, user_id)

    def _owner_count(self, project_id: str) -> int:
        return sum(m.role is ProjectRole.OWNER for m in self.store.list_memberships_for_project(project_id))

    @staticmethod
    def _token_hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()
