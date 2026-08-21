from __future__ import annotations

from application.container import ApplicationContainer
from application.quantitative.ui_service import QuantitativeUiError


class QuantitativeUiFacade:
    def __init__(self, container: ApplicationContainer) -> None:
        from api.ui.principal import resolve_ui_principal
        self.principal = resolve_ui_principal(container)
        self.service = container.quantitative_ui_service
        if self.service is None:
            raise QuantitativeUiError("Quantitative UI is not configured")

    @property
    def owner_id(self) -> str:
        return self.principal.principal_id

    def create(self, **values):
        return self.service.create_study(owner_id=self.owner_id, **values)

    def get(self, study_id: str):
        return self.service.get(study_id, owner_id=self.owner_id)

    def upload(self, study_id: str, **values):
        return self.service.upload(study_id, owner_id=self.owner_id, **values)

    def import_review(self, study_id: str):
        return self.service.import_review(study_id, owner_id=self.owner_id)

    def execution_status(self, study_id: str):
        return self.service.execution_status(study_id, owner_id=self.owner_id)

    def diagnostics(self, study_id: str):
        return self.service.weighting_diagnostics(study_id, owner_id=self.owner_id)

    def run_qc(self, study_id: str):
        return self.service.run_default_qc(study_id, owner_id=self.owner_id)

    def approve_qc(self, study_id: str, **values):
        return self.service.approve_qc(study_id, owner_id=self.owner_id, actor_id=self.owner_id, **values)

    def construct_weights(self, study_id: str, targets):
        return self.service.construct_weights_from_payload(study_id, owner_id=self.owner_id, targets=targets)

    def approve_weights(self, study_id: str, **values):
        return self.service.approve_weights(study_id, owner_id=self.owner_id, actor_id=self.owner_id, **values)

    def clean(self, study_id: str, **values):
        return self.service.apply_recode_cleaning(study_id, owner_id=self.owner_id, actor_id=self.owner_id, **values)

    def resume(self, study_id: str):
        return self.service.resume_workflow(study_id, owner_id=self.owner_id)

    def result(self, study_id: str):
        return self.service.result_projection(study_id, owner_id=self.owner_id)


def build_quantitative_ui_facade(container: ApplicationContainer) -> QuantitativeUiFacade:
    return QuantitativeUiFacade(container)
