"""Provider-free selection of bounded Quantitative Finding proposals.

The existing QH parser and support validator remain the sole authority for
resolving IDs, numbers and provenance. This selector never computes statistics.
"""

from __future__ import annotations

from typing import Any, Mapping

from application.structured_output.json_validator import JsonValidator


class DeterministicQuantitativeFindingProposalGenerator:
    identity = "QNT03_DETERMINISTIC_FINDING_SELECTOR_V1"

    def generate(self, prompt: str) -> Mapping[str, Any]:
        marker = "\nAUTHORITATIVE_BUNDLE="
        if marker not in prompt:
            raise ValueError("canonical Quantitative Finding bundle is unavailable")
        decoded = JsonValidator().validate(prompt.split(marker, 1)[1])
        if not decoded.is_valid or not isinstance(decoded.data, Mapping):
            raise ValueError("canonical Quantitative Finding bundle is malformed")
        bundle = decoded.data
        results = bundle.get("statistical_results")
        comparisons = bundle.get("comparison_results")
        if not isinstance(results, list) or not isinstance(comparisons, list):
            raise ValueError("canonical Quantitative Finding bundle is malformed")
        proposals: list[dict[str, Any]] = []
        available = {item["result_id"] for item in results}
        for item in sorted(comparisons, key=lambda value: value["comparison_result_id"]):
            if not {item["group_a_result_id"], item["group_b_result_id"]} <= available:
                raise ValueError("comparison precursors are unavailable")
            significant = item["significant"]
            proposals.append({
                "claim_type": ("SIGNIFICANT_COMPARISON" if significant
                               else "NON_SIGNIFICANT_COMPARISON"),
                "finding_text": (
                    f"Observed comparison difference {item['observed_difference_1dp']}. "
                    + ("Canonical test reports statistical significance."
                       if significant else "Canonical test does not establish significance.")
                ),
                "selected_result_ids": [item["group_a_result_id"],
                                        item["group_b_result_id"]],
                "selected_comparison_ids": [item["comparison_result_id"]],
            })
            if len(proposals) > 25:
                raise ValueError("canonical Quantitative Finding bundle exceeds bounded output")
        for item in results:
            claim_types = item.get("allowed_claim_types", ())
            claim_type = next(
                (kind for kind in ("DESCRIPTIVE_VALUE", "NUMERIC_SUMMARY", "KPI_VALUE")
                 if kind in claim_types),
                None,
            )
            if claim_type is None:
                continue
            display = item["display_value_1dp"]
            suffix = "%" if claim_type == "DESCRIPTIVE_VALUE" else ""
            proposals.append({
                "claim_type": claim_type,
                "finding_text": f"Observed {display}{suffix} for the selected result.",
                "selected_result_ids": [item["result_id"]],
                "selected_comparison_ids": [],
            })
            if len(proposals) > 25:
                raise ValueError("canonical Quantitative Finding bundle exceeds bounded output")
        return {"proposals": proposals}
