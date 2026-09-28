"""Reuse the full saved-report authorization/review/immutable-PDF contract via CMF."""
from copy import deepcopy

from tests.api.ui import test_prf06e_project_deliverables as legacy
from tests.application.test_ark02_desk import fixture
from tests.application.test_cmf02 import pin_context
from application.methods.desk.profile import PIN


class CMFDeliverableUiTests(legacy.DeliverableUiTests):
    def _desk(self, project_id="prf06e-project", run_id="prf06e-run"):
        project, run = super()._desk(project_id, run_id)
        config, context, *_ = fixture()
        pin_context(config, context)
        # Synthetic repository fixture only; production pins are written atomically
        # by PostgreSQL activation, covered separately in CMFWorkerTests.
        self.container.workflow_service.save_workflow_run(run,
            task_results={PIN: deepcopy(context.execution_metadata[PIN])})
        return project, run
