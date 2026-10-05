from sqlalchemy import select, update
from application.identity import BrowserSession, ProjectMembership, ProjectRole, User, UserStatus
from infrastructure.persistence.postgresql.models.identity_model import BrowserSessionModel, ProjectMembershipModel, UserModel
from infrastructure.persistence.postgresql.mappers.project_mapper import project_to_model
from infrastructure.persistence.postgresql.project_activity import record_activity


class PostgreSQLIdentityStore:
    def __init__(self, sessions): self.sessions = sessions
    @staticmethod
    def _user(m): return None if m is None else User(m.id,m.email,m.display_name,m.password_hash,UserStatus(m.status),m.created_at,m.updated_at)
    @staticmethod
    def _session(m): return None if m is None else BrowserSession(m.id,m.user_id,m.token_hash,m.created_at,m.expires_at,m.revoked_at)
    @staticmethod
    def _member(m): return None if m is None else ProjectMembership(m.project_id,m.user_id,ProjectRole(m.role),m.created_at,m.created_by)
    def create_user(self,u):
        with self.sessions.session() as s: s.add(UserModel(id=u.id,email=u.email,display_name=u.display_name,password_hash=u.password_hash,status=u.status.value,created_at=u.created_at,updated_at=u.updated_at));s.commit()
    def get_user(self,i):
        with self.sessions.session() as s:return self._user(s.get(UserModel,i))
    def get_user_by_email(self,e):
        with self.sessions.session() as s:return self._user(s.scalar(select(UserModel).where(UserModel.email==e)))
    def list_users(self):
        with self.sessions.session() as s:return [self._user(x) for x in s.scalars(select(UserModel).order_by(UserModel.email))]
    def set_user_status(self,i,status,at):
        with self.sessions.session() as s:s.execute(update(UserModel).where(UserModel.id==i).values(status=status.value,updated_at=at));s.commit()
    def create_session(self,v):
        with self.sessions.session() as s:s.add(BrowserSessionModel(id=v.id,user_id=v.user_id,token_hash=v.token_hash,created_at=v.created_at,expires_at=v.expires_at,revoked_at=v.revoked_at));s.commit()
    def get_session_by_hash(self,h):
        with self.sessions.session() as s:return self._session(s.scalar(select(BrowserSessionModel).where(BrowserSessionModel.token_hash==h)))
    def revoke_session(self,h,at):
        with self.sessions.session() as s:s.execute(update(BrowserSessionModel).where(BrowserSessionModel.token_hash==h).values(revoked_at=at));s.commit()
    def revoke_user_sessions(self,i,at):
        with self.sessions.session() as s:s.execute(update(BrowserSessionModel).where(BrowserSessionModel.user_id==i,BrowserSessionModel.revoked_at.is_(None)).values(revoked_at=at));s.commit()
    def create_membership(self,m):
        with self.sessions.session() as s:s.add(ProjectMembershipModel(project_id=m.project_id,user_id=m.user_id,role=m.role.value,created_at=m.created_at,created_by=m.created_by));s.commit()
    def create_owned_project(self, project, membership):
        """Persist a browser-created project and its first OWNER atomically."""
        with self.sessions.session() as s:
            s.add(project_to_model(project, version=0)); s.flush()
            s.add(ProjectMembershipModel(project_id=membership.project_id,user_id=membership.user_id,
                role=membership.role.value,created_at=membership.created_at,created_by=membership.created_by))
            record_activity(s,project_id=project.id,semantic_key="project-created",
                event_type="PROJECT_CREATED",source_kind="project",source_id=project.id,
                occurred_at=project.created_at or None,actor_id=membership.user_id)
    def get_membership(self,p,u):
        with self.sessions.session() as s:return self._member(s.get(ProjectMembershipModel,(p,u)))
    def list_memberships_for_user(self,u):
        with self.sessions.session() as s:return [self._member(x) for x in s.scalars(select(ProjectMembershipModel).where(ProjectMembershipModel.user_id==u))]
    def list_memberships_for_project(self,p):
        with self.sessions.session() as s:return [self._member(x) for x in s.scalars(select(ProjectMembershipModel).where(ProjectMembershipModel.project_id==p))]
    def update_membership_role(self,p,u,r):
        with self.sessions.session() as s:s.execute(update(ProjectMembershipModel).where(ProjectMembershipModel.project_id==p,ProjectMembershipModel.user_id==u).values(role=r.value));s.commit()
    def remove_membership(self,p,u):
        with self.sessions.session() as s:m=s.get(ProjectMembershipModel,(p,u));s.delete(m) if m else None;s.commit()
