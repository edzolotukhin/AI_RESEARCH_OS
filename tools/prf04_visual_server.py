"""Disposable in-memory PRF-04 browser demonstration; never writes canonical data."""

from __future__ import annotations

import uvicorn

from api.ui.principal import resolve_ui_principal
from tools import pf03_visual_server


app = pf03_visual_server.app
container = app.state.container
owner_id = resolve_ui_principal(container).principal_id

# A completed Desk project with a second, independently activated method.
both = container.project_service.get_project("pf03-completed-project")
container.project_planning_service.add_method(both, "QUANTITATIVE")
container.quantitative_ui_service.create_quantitative_study_for_project(
    project_id=both.id, owner_id=owner_id, title="Демонстраційне кількісне дослідження",
    description="Ізольований приклад без завантажених даних", submission_key="prf04-both",
)

# A quantitative-only project demonstrates project/run/study navigation.
quant = container.project_service.create_project(
    "PRF-04 кількісний метод", owner_principal_id=owner_id,
    selected_methods=("QUANTITATIVE",), project_id="prf04-quant-project",
)
container.quantitative_ui_service.create_quantitative_study_for_project(
    project_id=quant.id, owner_id=owner_id, title="Демонстраційне кількісне дослідження",
    description="Ізольований приклад без результатів", submission_key="prf04-quant",
)

container.project_service.create_project(
    "PRF-04 метод без запуску", owner_principal_id=owner_id,
    selected_methods=("DESK",), project_id="prf04-unactivated-project",
)
container.project_service.create_project(
    "PRF-04 недоступний проєкт", owner_principal_id="another-user",
    selected_methods=("DESK",), project_id="prf04-foreign-project",
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8009)
