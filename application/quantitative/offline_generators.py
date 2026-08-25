"""Explicit deterministic adapters for synthetic/local Quantitative acceptance.

These adapters are never composed unless deterministic stage execution is
enabled. They propose text only; QH/QJ/QK validators remain authoritative.
"""
from __future__ import annotations

from application.structured_output.json_validator import JsonValidator


def _bundle(prompt: str, marker: str):
    parsed = JsonValidator().validate(prompt.split(marker, 1)[1])
    if not parsed.is_valid:
        raise ValueError("offline aggregate bundle is invalid")
    return parsed.data


class OfflineFindingGenerator:
    identity = "qo-offline-findings-v1"

    def generate(self, prompt):
        results = _bundle(prompt, "AUTHORITATIVE_BUNDLE=")["statistical_results"]
        percentage = next(item for item in results if "PERCENTAGE" in item["statistic_type"])
        weighted = next(item for item in results if item["weighting_status"] == "WEIGHTED" and "PERCENTAGE" in item["statistic_type"])

        def decode(raw):
            if not isinstance(raw, dict): return raw
            value, kind = raw.get("value"), raw.get("type")
            return int(value) if kind in ("integer", "int") else float(value) if kind in ("decimal", "float") else value

        def proposal(item, invented=False):
            scalar = item["value"]["value"] if isinstance(item["value"], dict) else item["value"]
            return {"claim_type":"DESCRIPTIVE_VALUE", "finding_text":f"Supported aggregate was {item['display_value_1dp'] if not invented else '999.0'}.",
                    "statistical_result_refs":[item["result_id"]], "statistical_result_fingerprints":{item["result_id"]:item["reproducibility_fingerprint"]},
                    "comparison_result_refs":[], "comparison_result_fingerprints":{}, "value":str(scalar if not invented else 999),
                    "display_value":item["display_value_1dp"] if not invented else "999.0", "rounding_decimal_places":1,
                    "variable_id":item["variable_id"], "statistic_type":item["statistic_type"], "category_value":decode(item["category_value"]),
                    "filter_definition":item["filter_definition"], "base_definition":item["base_definition"],
                    "weighting_status":item["weighting_status"], "weight_set_fingerprint":item["weight_set_fingerprint"],
                    "direction":None, "limitation_note":"Synthetic aggregate."}
        return {"proposals":[proposal(percentage), proposal(weighted), proposal(percentage, True)]}


class OfflineInsightGenerator:
    identity = "qo-offline-insights-v1"
    def generate(self, prompt):
        finding = _bundle(prompt, "ACCEPTED_FINDINGS=")[0]
        base={"insight_type":"SYNTHESIS", "supporting_finding_ids":[finding["finding_id"]],
              "direction":None, "limitation_note":"Synthetic aggregate."}
        valid=dict(base, insight_text=f"Supported result was {finding['display_value']}.", referenced_display_values=[finding["display_value"]])
        invalid=dict(base, insight_text="Unsupported result was 999.0.", referenced_display_values=["999.0"])
        return {"proposals":[valid, invalid]}


class OfflineReportGenerator:
    identity = "qo-offline-report-v1"
    def generate(self, prompt):
        support=_bundle(prompt, "APPROVED_SUPPORT="); finding=support["findings"][0]; insight=support["insights"][0]
        value=finding["display_value"]
        section={"section_id":"section-1", "section_type":"KEY_FINDINGS", "title":"Results",
                 "narrative":f"Supported result was {value}.", "finding_refs":[finding["finding_id"]],
                 "finding_fingerprints":{finding["finding_id"]:finding["validation_fingerprint"]},
                 "insight_refs":[insight["insight_id"]], "insight_fingerprints":{insight["insight_id"]:insight["validation_fingerprint"]},
                 "referenced_display_values":[value], "authoritative_result_refs":finding["result_refs"],
                 "authoritative_table_refs":[], "weighting_status":finding["weighting"], "filter_definition":finding["filter"],
                 "base_definition":finding["base"], "direction":None}
        return {"title":"Synthetic Quantitative Report", "finding_refs":[finding["finding_id"]],
                "finding_fingerprints":{finding["finding_id"]:finding["validation_fingerprint"]},
                "insight_refs":[insight["insight_id"]], "insight_fingerprints":{insight["insight_id"]:insight["validation_fingerprint"]},
                "sections":[section]}
