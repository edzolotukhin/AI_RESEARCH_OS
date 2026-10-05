from application.identity import UserStatus


class InMemoryIdentityStore:
    def __init__(self): self.users={};self.sessions={};self.memberships={}
    def create_user(self,u): self.users[u.id]=u
    def get_user(self,i): return self.users.get(i)
    def get_user_by_email(self,e): return next((u for u in self.users.values() if u.email==e),None)
    def list_users(self): return sorted(self.users.values(),key=lambda u:u.email)
    def set_user_status(self,i,status,at):
        from dataclasses import replace
        self.users[i]=replace(self.users[i],status=status,updated_at=at)
    def create_session(self,s): self.sessions[s.token_hash]=s
    def get_session_by_hash(self,h): return self.sessions.get(h)
    def revoke_session(self,h,at):
        from dataclasses import replace
        if h in self.sessions:self.sessions[h]=replace(self.sessions[h],revoked_at=at)
    def revoke_user_sessions(self,i,at):
        from dataclasses import replace
        for h,s in list(self.sessions.items()):
            if s.user_id==i and not s.revoked_at:self.sessions[h]=replace(s,revoked_at=at)
    def create_membership(self,m):
        key=(m.project_id,m.user_id)
        if key in self.memberships:raise ValueError("Membership already exists")
        self.memberships[key]=m
    def get_membership(self,p,u): return self.memberships.get((p,u))
    def list_memberships_for_user(self,u): return [m for m in self.memberships.values() if m.user_id==u]
    def list_memberships_for_project(self,p): return [m for m in self.memberships.values() if m.project_id==p]
    def update_membership_role(self,p,u,r):
        from dataclasses import replace
        self.memberships[(p,u)]=replace(self.memberships[(p,u)],role=r)
    def remove_membership(self,p,u): self.memberships.pop((p,u),None)
