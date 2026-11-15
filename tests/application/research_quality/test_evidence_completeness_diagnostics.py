from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from application.research_quality.evidence_completeness_diagnostics import build_evidence_coverage_diagnostics
from domain.evidence.evidence import Evidence
from domain.planning.research_design import EvidenceCoverageContract
from domain.sources.source import Source


NEED = "in-population"
RUN = "run"
DESIGN = "design"
SUBJECT = "subject"
SUBJECT_FINGERPRINT = "fingerprint"


def source(identifier="source-1", period="2019", *, workflow=RUN, design=DESIGN, numeric="100"):
    text = f"Population {period} {numeric} persons Ukraine"
    checksum = sha256(text.encode()).hexdigest()
    return Source(
        identifier, "project", "https://secret.example/data.xlsx", "https://secret.example/data.xlsx",
        "Private title", "2026-01-01T00:00:00Z", content_text=text, content_checksum=checksum,
        metadata={"structured_tables_v2": [{"sheet": "Population", "table_range": "A1:D2", "row": 2,
            "header_checksum": "header-checksum", "excerpt": text, "ambiguous_headers": False,
            "cells": [
                {"cell": "A2", "header": "Year", "value": period, "numeric_value": period, "formula": False},
                {"cell": "B2", "header": "Population", "value": numeric, "numeric_value": numeric, "formula": False},
                {"cell": "C2", "header": "Unit", "value": "persons", "numeric_value": None, "formula": False},
                {"cell": "D2", "header": "Geography", "value": "Ukraine", "numeric_value": None, "formula": False},
            ]}]},
        raw_content_checksum=f"raw-{identifier}", raw_checksum_kind="sha256-bytes",
        terminal_resource_key=f"terminal-{identifier}", extraction_revision="xlsx-structured-v2", content_revision=2,
        workflow_run_refs=(workflow,), research_design_refs=(design,),
    )


def evidence(item_source, period="2019", *, identifier="evidence-1", structured=True,
             needs=(NEED,), assignment_need=NEED, lineage=None, unit="persons", geography="Ukraine",
             workflow=RUN, design=DESIGN, numeric="100", subject_id=SUBJECT,
             subject_fingerprint=SUBJECT_FINGERPRINT):
    excerpt = item_source.content_text
    provenance = {"raw_workbook_checksum": item_source.raw_content_checksum,
        "raw_checksum_kind": item_source.raw_checksum_kind, "terminal_resource_key": item_source.terminal_resource_key,
        "extraction_revision": item_source.extraction_revision, "content_revision": item_source.content_revision,
        "sheet": "Population", "table_range": "A1:D2", "row": 2, "cell": "B2", "period_cell": "A2",
        "unit_cells": ["C2"], "geography_cells": ["D2"], "header_checksum": "header-checksum"}
    metadata = {"observation_period": period, "metric": "Population", "numeric_value": numeric,
        "normalized_numeric_value": numeric, "unit": unit, "geography": geography,
        "semantic_assignment": {"contract_version": "desk_evidence_candidate_v2",
            "validation_version": "desk_semantic_assignment_v1", "information_need_id": assignment_need,
            "subject_id": subject_id, "subject_fingerprint": subject_fingerprint, "binding_type": "canonical_subject",
            "supporting_relation_id": None, "required_aspect_refs": [], "geography_applicability": ["Ukraine"],
            "semantic_justification": "fixture", "lexical_diagnostics": {}},
        "data_lineage": lineage or {"status": "established", "origin_id": f"origin-{item_source.id}"}}
    locator = {"normalized_start": 0, "normalized_end": len(excerpt),
        "excerpt_hash": sha256(excerpt.encode()).hexdigest()}
    if structured:
        metadata.update(structured_table=True, workbook_provenance=provenance); locator["structured"] = provenance
    return Evidence(identifier, "project", item_source.id, item_source.content_checksum, workflow, design,
        f"Population {period}", excerpt, "2026-01-01T00:00:00Z", information_need_refs=needs,
        source_locator=locator, extraction_method="xlsx-structured-v2" if structured else "llm", metadata=metadata)


def contract(periods=("2019", "2020")):
    return EvidenceCoverageContract(required_periods=periods, required_metric="Population", geography="Ukraine",
        required_observations=("annual level",), minimum_independent_sources=1)


def readiness(count, need=NEED, *, current=True):
    return {"information_need_id": need, "status": "partial", "evidence_count": count,
        "independent_source_count": 1, "missing_aspects": ["private"],
        "gap_types": ["missing_quantitative_data"], "assessment_current": current, "analysis_eligible": True,
        "reason": "secret", "search_directives": ["private query"]}


def build(*, sources=(), rows=(), temporal=None, coverage=None, snapshot=None, count=0, history=(),
          sources_complete=True, evidence_complete=True, need=NEED, max_periods=32, max_loop_attempts=16):
    return build_evidence_coverage_diagnostics(
        information_need_id=need, workflow_run_id=RUN, research_design_id=DESIGN,
        research_subject_id=SUBJECT, research_subject_fingerprint=SUBJECT_FINGERPRINT,
        allowed_dependency_information_need_ids=(), required_numeric_unit="persons",
        coverage_contract=coverage or contract(), sources=sources, evidence=rows,
        temporal_qualification_by_evidence_and_need=temporal or {}, readiness_snapshot=snapshot or readiness(count, need),
        sources_complete=sources_complete, evidence_complete=evidence_complete, research_loop_history=history,
        max_periods=max_periods, max_loop_attempts=max_loop_attempts)


def eligible(*ids, need=NEED):
    return {(identifier, need): "applicable_satisfied" for identifier in ids}


class EvidenceCompletenessDiagnosticsTests(unittest.TestCase):
    def test_complete_and_incomplete_series(self):
        s1, s2 = source("s1", "2019"), source("s2", "2020")
        e1, e2 = evidence(s1, identifier="e1"), evidence(s2, "2020", identifier="e2")
        full = build(sources=(s1, s2), rows=(e1, e2), temporal=eligible("e1", "e2"), count=2)
        self.assertEqual([row["status"] for row in full["period_coverage"]], ["confirmed", "confirmed"])
        partial = build(sources=(s1,), rows=(e1,), temporal=eligible("e1"), count=1)
        self.assertEqual([row["status"] for row in partial["period_coverage"]], ["confirmed", "missing"])

    def test_undeclared_period_and_exact_date_do_not_fill_year(self):
        for period in ("2021", "2019-01-01"):
            with self.subTest(period=period):
                item = source(period=period); row = evidence(item, period)
                result = build(sources=(item,), rows=(row,), temporal=eligible(row.id), count=1)
                self.assertTrue(all(value["status"] == "missing" for value in result["period_coverage"]))
                self.assertEqual(result["qualification"]["rejection_reason_counts"], {"undeclared_period": 1})

    def test_forged_metadata_and_missing_assignment_are_unknown(self):
        item = source(); row = evidence(item)
        for metadata in ({**row.metadata, "numeric_value": "999"}, {k: v for k, v in row.metadata.items() if k != "semantic_assignment"}):
            with self.subTest(keys=tuple(metadata)):
                forged = replace(row, metadata=metadata)
                result = build(sources=(item,), rows=(forged,), temporal=eligible(row.id), count=1)
                self.assertEqual(result["period_coverage"][0]["status"], "unknown")
                self.assertEqual(result["qualification"]["numeric_binding_verified_evidence_count"], 0)

    def test_source_scope_and_row_unit_geography_are_verified(self):
        base = source(); row = evidence(base)
        foreign = source(workflow="other")
        bad_unit = replace(base, metadata={"structured_tables_v2": [{**base.metadata["structured_tables_v2"][0],
            "cells": [{**cell, "value": "thousands"} if cell["cell"] == "C2" else cell for cell in base.metadata["structured_tables_v2"][0]["cells"]]}]})
        bad_geo = replace(base, metadata={"structured_tables_v2": [{**base.metadata["structured_tables_v2"][0],
            "cells": [{**cell, "value": "Poland"} if cell["cell"] == "D2" else cell for cell in base.metadata["structured_tables_v2"][0]["cells"]]}]})
        for item, current in ((foreign, replace(row, source_id=foreign.id, source_content_checksum=foreign.content_checksum,
                                                   source_excerpt=foreign.content_text)), (bad_unit, row), (bad_geo, row)):
            with self.subTest(item=item.id):
                result = build(sources=(item,), rows=(current,), temporal=eligible(current.id), count=1)
                self.assertEqual(result["period_coverage"][0]["status"], "unknown")

    def test_conflicting_unit_and_geography_cells_are_rejected(self):
        base = source()
        original_row = base.metadata["structured_tables_v2"][0]
        conflicting = replace(base, metadata={"structured_tables_v2": [{
            **original_row,
            "cells": [
                *original_row["cells"],
                {"cell": "E2", "header": "Units", "value": "thousands", "numeric_value": None, "formula": False},
                {"cell": "F2", "header": "Country", "value": "Poland", "numeric_value": None, "formula": False},
            ],
        }]})
        row = evidence(conflicting)
        result = build(sources=(conflicting,), rows=(row,), temporal=eligible(row.id), count=1)
        self.assertEqual(result["period_coverage"][0]["status"], "unknown")
        self.assertEqual(result["qualification"]["numeric_binding_verified_evidence_count"], 0)
        self.assertEqual(result["qualification"]["rejection_reason_counts"], {"numeric_binding_unverified": 1})

    def test_subject_identity_mismatch_is_rejected(self):
        item = source()
        for field in ("subject_id", "subject_fingerprint"):
            with self.subTest(field=field):
                kwargs = {field: "wrong"}
                row = evidence(item, **kwargs)
                result = build(sources=(item,), rows=(row,), temporal=eligible(row.id), count=1)
                self.assertEqual(result["period_coverage"][0]["status"], "unknown")
                self.assertEqual(result["qualification"]["numeric_binding_verified_evidence_count"], 0)

    def test_conflicting_numeric_observations_do_not_confirm_period(self):
        first = source("s1", numeric="100")
        second = source("s2", numeric="101")
        e1 = evidence(first, identifier="e1", numeric="100")
        e2 = evidence(second, identifier="e2", numeric="101")
        result = build(sources=(first, second), rows=(e1, e2), temporal=eligible("e1", "e2"), count=2)
        period = result["period_coverage"][0]
        self.assertEqual(period["status"], "unknown")
        self.assertEqual(period["confirmed_observation_count"], 0)
        self.assertEqual(period["rejection_reason_counts"], {"conflicting_numeric_observations": 1})
        self.assertEqual(result["qualification"]["numeric_binding_verified_evidence_count"], 2)
        self.assertEqual(result["qualification"]["confirmed_observation_count"], 0)
        self.assertEqual(result["qualification"]["rejection_reason_counts"], {"conflicting_numeric_observations": 1})

    def test_mirrors_and_unknown_lineage_do_not_multiply_independence(self):
        for lineage in ({"status": "established", "origin_id": "same-primary"}, {"status": "unknown"}):
            with self.subTest(lineage=lineage):
                s1, s2 = source("s1"), source("s2")
                e1, e2 = evidence(s1, identifier="e1", lineage=lineage), evidence(s2, identifier="e2", lineage=lineage)
                result = build(sources=(s1, s2), rows=(e1, e2), temporal=eligible("e1", "e2"), count=2)
                self.assertEqual(result["qualification"]["independent_source_count"], 1)
                self.assertEqual(result["period_coverage"][0]["independent_source_count"], 1)

    def test_incomplete_or_inconsistent_collections_are_unavailable(self):
        item = source(); row = evidence(item)
        for kwargs, reason in (({"sources_complete": False}, "collections_incomplete"),
                               ({"evidence_complete": None}, "collections_incomplete"),
                               ({"rows": (row,), "count": 1}, "source_collection_inconsistent")):
            with self.subTest(reason=reason):
                result = build(**kwargs)
                self.assertEqual(result["availability"], "unavailable")
                self.assertEqual(result["unavailable_reason"], reason)

    def test_readiness_count_mismatch_is_unavailable(self):
        item = source(); row = evidence(item)
        result = build(sources=(item,), rows=(row,), temporal=eligible(row.id), count=0)
        self.assertEqual(result["unavailable_reason"], "readiness_evidence_count_mismatch")

    def test_temporal_result_is_scoped_to_evidence_and_need(self):
        item = source(); row = evidence(item, needs=(NEED, "other"))
        temporal = {(row.id, NEED): "applicable_satisfied", (row.id, "other"): "applicable_failed"}
        result = build(sources=(item,), rows=(row,), temporal=temporal, count=1)
        self.assertEqual(result["period_coverage"][0]["status"], "confirmed")

    def test_not_applicable_cannot_confirm_dated_observation(self):
        item = source(); row = evidence(item)
        result = build(sources=(item,), rows=(row,), temporal={(row.id, NEED): "not_applicable"}, count=0)
        self.assertEqual(result["period_coverage"][0]["status"], "unknown")
        self.assertEqual(result["qualification"]["rejection_reason_counts"], {"temporal_unresolved": 1})

    def test_counters_are_disjoint_and_consistent(self):
        s1, s2, s3 = source("s1"), source("s2"), source("s3")
        confirmed = evidence(s1, identifier="confirmed")
        claim = evidence(s2, identifier="claim", structured=False)
        invalid = replace(evidence(s3, identifier="invalid"), source_content_checksum="wrong")
        result = build(sources=(s1, s2, s3), rows=(confirmed, claim, invalid),
            temporal=eligible("confirmed", "claim", "invalid"), count=2)
        self.assertEqual(result["qualification"], {
            "persisted_evidence_count": 3, "citation_valid_evidence_count": 2,
            "temporally_eligible_evidence_count": 2, "numeric_binding_verified_evidence_count": 1,
            "confirmed_observation_count": 1, "independent_source_count": 2,
            "rejection_reason_counts": {"invalid_citation": 1, "numeric_binding_unverified": 1}})

    def test_temporal_out_of_period_is_distinct(self):
        item = source(); row = evidence(item)
        result = build(sources=(item,), rows=(row,), temporal={(row.id, NEED): "applicable_failed"}, count=0)
        self.assertEqual(result["period_coverage"][0]["status"], "missing")
        self.assertEqual(result["qualification"]["rejection_reason_counts"], {"temporal_out_of_period": 1})

    def test_bounded_safe_deterministic_projection(self):
        item = source(); row = evidence(item, structured=False)
        history = [{"attempt": index + 1, "round_number": 1, "targeted_need_ids": [NEED],
            "strategy_id": "direct" if index == 0 else "private", "improved": False,
            "remediation_attempt_diagnostics": {"target_qualifying_delta": 0, "exception_message": "credential=top-secret"}}
            for index in range(3)]
        first = build(sources=(item,), rows=(row,), temporal=eligible(row.id), count=1, history=history, max_loop_attempts=2)
        second = build(sources=(item,), rows=(row,), temporal=eligible(row.id), count=1, history=history, max_loop_attempts=2)
        self.assertEqual(first, second); self.assertTrue(first["truncated"])
        serialized = json.dumps(first, sort_keys=True)
        for forbidden in ("https://", item.id, row.id, row.source_excerpt, "top-secret", "private query", "provider_payload"):
            self.assertNotIn(forbidden, serialized)

    def test_period_truncation_and_unmapped_requirement_are_explicit(self):
        result = build(coverage=contract(("2019", "not a period", "2020")), max_periods=1)
        self.assertEqual(result["requirements"]["required_periods"], ["2019"])
        self.assertEqual(result["requirements"]["unmapped_required_period_count"], 1)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
