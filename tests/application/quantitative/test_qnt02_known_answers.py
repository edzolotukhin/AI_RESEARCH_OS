"""Independent numerical checks over the accepted deterministic QG fixture."""

from __future__ import annotations

import unittest
from math import sqrt

from application.quantitative.comparison_statistics import MEAN_METHOD, PROPORTION_METHOD
from tests.application.quantitative import test_property_qg_deterministic_comparison_provenance as qg_fixture


class Qnt02KnownAnswerComparisonsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = qg_fixture.PropertyQGDeterministicComparisonProvenanceTests()
        self.fixture.setUp()

    def test_two_sided_unweighted_proportion_z_known_answer(self) -> None:
        fixture = self.fixture
        a, b, view = fixture.proportion_inputs()
        result = fixture.compare.compare_proportions(
            dataset=fixture.imported.dataset_version,
            codebook=fixture.imported.codebook,
            specification=fixture.spec(PROPORTION_METHOD, "response_sig"),
            group_a_result=a, group_b_result=b, view=view,
        )
        # 18/20 versus 2/20, pooled p=20/40: (0.9-0.1)/sqrt(.5*.5*(1/20+1/20)).
        self.assertAlmostEqual(float(result.observed_difference), 80.0)
        self.assertAlmostEqual(float(result.test_statistic), 0.8 / sqrt(0.025), places=12)
        self.assertAlmostEqual(float(result.p_value), 4.200393976022014e-7, delta=1e-13)
        self.assertTrue(result.significant)
        self.assertEqual(result.method, PROPORTION_METHOD)

    def test_two_sided_unweighted_welch_known_answer(self) -> None:
        fixture = self.fixture
        a, b, view_a, view_b = fixture.mean_inputs()
        result = fixture.compare.compare_means(
            dataset=fixture.imported.dataset_version,
            codebook=fixture.imported.codebook,
            specification=fixture.spec(MEAN_METHOD, "score_sig"),
            group_a_result=a, group_b_result=b, view_a=view_a, view_b=view_b,
        )
        # 0..19 versus 30..49; both sample variances = 35, n=20 each, Welch df=38.
        self.assertAlmostEqual(float(result.observed_difference), -30.0)
        self.assertAlmostEqual(float(result.test_statistic), -30 / sqrt(35 / 20 + 35 / 20), places=12)
        self.assertAlmostEqual(float(result.p_value), 1.6703390682008514e-18, delta=1e-22)
        self.assertTrue(result.significant)
        self.assertEqual(result.method, MEAN_METHOD)


if __name__ == "__main__":
    unittest.main()
