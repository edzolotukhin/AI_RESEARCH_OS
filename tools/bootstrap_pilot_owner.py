"""Create the first pilot user without committing or printing its password.

Required environment: DATABASE_URL, PILOT_OWNER_EMAIL, PILOT_OWNER_DISPLAY_NAME,
PILOT_OWNER_PASSWORD. Optional UX01A_LEGACY_PROJECT_IDS is a comma-separated,
explicit allowlist of existing projects to claim; no project is claimed implicitly.
"""
import os
from application.composition_root import create_application_container
from application.identity import ProjectRole

def main():
    required={k:(os.environ.get(k) or "").strip() for k in ("PILOT_OWNER_EMAIL","PILOT_OWNER_DISPLAY_NAME","PILOT_OWNER_PASSWORD")}
    if not all(required.values()):raise SystemExit("Pilot owner environment is incomplete")
    container=create_application_container()
    if container.identity_service is None:raise SystemExit("Identity persistence is unavailable")
    service=container.identity_service;existing=service.store.get_user_by_email(required["PILOT_OWNER_EMAIL"].casefold())
    user=existing or service.create_user(required["PILOT_OWNER_EMAIL"],required["PILOT_OWNER_DISPLAY_NAME"],required["PILOT_OWNER_PASSWORD"])
    for project_id in filter(None,((os.environ.get("UX01A_LEGACY_PROJECT_IDS") or "").split(","))):
        project_id=project_id.strip();container.project_service.get_project(project_id)
        membership=service.store.get_membership(project_id,user.id)
        if membership is None:service.add_membership(project_id,user.id,ProjectRole.OWNER,actor_id=user.id)
        elif membership.role is not ProjectRole.OWNER:raise SystemExit(f"Existing membership is not OWNER: {project_id}")
    print(f"pilot_owner_id={user.id} status={user.status.value}")
    container.shutdown()
    return 0

if __name__=="__main__":raise SystemExit(main())
