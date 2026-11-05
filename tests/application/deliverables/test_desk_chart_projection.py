import unittest
from types import SimpleNamespace

from application.deliverables.service import ProjectDeliverablesService


class _Repo:
    def __init__(self, values):
        self.values = {item.id: item for item in values}

    def get_by_id(self, value):
        return self.values.get(value)


class DeskChartProjectionTests(unittest.TestCase):
    def _service(self, *, finding, evidence, source):
        service = ProjectDeliverablesService.__new__(ProjectDeliverablesService)
        service.finding_repository = _Repo((finding,))
        service.evidence_repository = _Repo(evidence)
        service.source_repository = _Repo(source)
        return service

    def _report(self, *, finding_id="finding-1", evidence_ids=("evidence-1", "evidence-2")):
        return SimpleNamespace(
            project_id="project", workflow_run_id="run", research_design_id="design",
            finding_refs=(finding_id,), evidence_refs=evidence_ids,
            metadata={"charts": [{"title": "Metric", "finding_id": finding_id,
                                  "evidence_ids": evidence_ids}]},
        )

    def _records(self, *, finding_evidence=("evidence-1", "evidence-2"), valid=True,
                 foreign_source=False):
        finding = SimpleNamespace(
            id="finding-1", project_id="project", workflow_run_id="run",
            research_design_id="design", evidence_refs=finding_evidence,
            metadata={"validation_status": "validated"},
        )
        evidence = tuple(SimpleNamespace(
            id=value, project_id="project", workflow_run_id="run",
            research_design_id="design", source_id=("foreign-source" if foreign_source else f"source-{value}"),
            metadata={"chart_observation": {"metric": "metric", "unit": "units",
                                             "period": period, "value": number}} if valid else {},
        ) for value, period, number in (("evidence-1", "2024", 42), ("evidence-2", "2025", 47)))
        sources = tuple(SimpleNamespace(
            id=item.source_id, project_id=("other-project" if foreign_source else "project")
        ) for item in evidence)
        return finding, evidence, sources

    def test_qualified_evidence_produces_chart(self):
        finding, evidence, sources = self._records()
        charts = self._service(finding=finding, evidence=evidence, source=sources)._desk_charts(self._report())
        self.assertEqual(len(charts), 1)
        self.assertEqual((charts[0].labels, charts[0].values), (("2024", "2025"), (42, 47)))

    def test_evidence_from_different_finding_is_rejected(self):
        finding, evidence, sources = self._records(finding_evidence=("evidence-1",))
        self.assertEqual(self._service(finding=finding, evidence=evidence, source=sources)._desk_charts(self._report()), ())

    def test_missing_or_invalid_evidence_is_rejected(self):
        finding, evidence, sources = self._records(valid=False)
        self.assertEqual(self._service(finding=finding, evidence=evidence, source=sources)._desk_charts(self._report()), ())

    def test_foreign_source_lineage_is_rejected(self):
        finding, evidence, sources = self._records(foreign_source=True)
        self.assertEqual(self._service(finding=finding, evidence=evidence, source=sources)._desk_charts(self._report()), ())


if __name__ == "__main__":
    unittest.main()
