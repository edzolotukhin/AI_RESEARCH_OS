import os
from types import SimpleNamespace

import pytest

from tests.qualification.p8d_targeted_pptx_retry import guard_database, preflight


def test_database_guard_rejects_wrong_target(monkeypatch):
    monkeypatch.setenv("POSTGRESQL_INTEGRATION_TESTS", "1")
    monkeypatch.setenv("POSTGRESQL_DISPOSABLE_TEST_DATABASE", "1")
    monkeypatch.setenv("DATABASE_URL_TEST", "postgresql://u:p@127.0.0.1:55432/other_test")
    with pytest.raises(RuntimeError):
        guard_database()


def test_preflight_rejects_non_failed_job():
    job = SimpleNamespace(
        id="44e62b98-fd83-400a-9550-0bbb84b2c640", state="completed", failure_code=None,
        run_id="76dd7c91-ab9f-5097-88b6-1755fdf15a49", project_id="p", source_id="r",
        report_revision=1, review_id="8da1af19-cd85-4ba6-87af-1eb99128ca93",
        completed_deliverable_id=None, renderer_version="pptxgenjs-4.0.1-2",
        template_version="neutral-corporate-1", attempts=3, source_run_id=None,
    )
    jobs = SimpleNamespace(list_recent=lambda: [job])
    service = SimpleNamespace(presentation_jobs=jobs)
    container = SimpleNamespace(
        project_deliverables_service=service,
        workflow_service=SimpleNamespace(get_workflow_run=lambda _: SimpleNamespace(project_id="p")),
        project_service=SimpleNamespace(get_project=lambda _: SimpleNamespace(id="p")),
        report_query_service=SimpleNamespace(list_reports_for_project=lambda *_args, **_kwargs: [SimpleNamespace(id="r", revision_number=1)]),
        review_query_service=SimpleNamespace(list_reviews_for_project=lambda *_args, **_kwargs: [SimpleNamespace(id="8da1af19-cd85-4ba6-87af-1eb99128ca93", verdict="approve")]),
    )
    with pytest.raises(RuntimeError):
        preflight(container)
