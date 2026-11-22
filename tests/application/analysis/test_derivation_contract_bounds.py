from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from application.analysis.derivations import DerivationRefused, dependency_authority
from domain.planning.derivation import DerivationContract, DerivationOperation


class DerivationContractBoundsTests(TestCase):
    def test_one_evidence_can_cover_more_periods_than_input_bound(self):
        contract = DerivationContract(
            DerivationOperation.CUMULATIVE_ABSOLUTE_CHANGE,
            "Population", "persons", "Ukraine",
            required_periods=("2019", "2020", "2021"), max_inputs=1,
        )
        self.assertEqual(contract.required_periods, ("2019", "2020", "2021"))

    def test_dependency_input_bound_is_still_enforced(self):
        need = SimpleNamespace(
            depends_on_information_need_ids=("population",),
            derivation=SimpleNamespace(max_inputs=1),
        )
        findings = [
            SimpleNamespace(
                id=f"finding-{index}", project_id="project",
                workflow_run_id="run", research_design_id="design",
                information_need_refs=("population",),
                evidence_refs=(f"evidence-{index}",),
                metadata={"validation_status": "validated"},
            ) for index in (1, 2)
        ]
        evidence = [
            SimpleNamespace(
                id=f"evidence-{index}", project_id="project",
                research_design_id="design", workflow_run_id="run",
            ) for index in (1, 2)
        ]
        with patch(
            "application.analysis.derivations.qualifying_evidence",
            return_value=tuple(evidence),
        ), self.assertRaisesRegex(DerivationRefused, "dependency_input_bound_or_empty"):
            dependency_authority(
                need, findings, evidence,
                design=SimpleNamespace(id="design"), project_id="project",
                workflow_run_id="run", allowed_runs=("run",),
                brief=None, source_repository=None,
            )

    def test_invalid_duplicate_or_unordered_periods_are_rejected(self):
        for periods in (("2020", "2020"), ("2021", "2020"), ("2020-Q1", "2021-Q1")):
            with self.subTest(periods=periods), self.assertRaises(ValueError):
                DerivationContract(
                    DerivationOperation.CUMULATIVE_ABSOLUTE_CHANGE,
                    "Population", "persons", "Ukraine", required_periods=periods,
                )
