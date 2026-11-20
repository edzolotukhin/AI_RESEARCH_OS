from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import io
import unittest
import zipfile
from unittest.mock import Mock

from openpyxl import Workbook

from application.analysis.numeric_integrity import (
    project_numeric_evidence_for_design,
    qualify_numeric_information_need,
)
from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.evidence.structured_evidence_extractor import StructuredEvidenceExtractor
from application.evidence.temporal_scope import qualify_evidence_with_temporal_decisions
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import (
    EvidenceCoverageContract,
    EvidenceExpectation,
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)
from domain.planning.research_subject import (
    LexicalRepresentation,
    ResearchSubject,
    SubjectResolutionStatus,
)
from domain.research_brief import ResearchBrief
from domain.sources.source import Source
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.retrieval.xlsx_text_extractor import extract_xlsx_text


YEARS = tuple(str(year) for year in range(2015, 2022))
VALUES = (42_759_700, 42_590_900, 42_414_900, 42_216_800, 41_902_400, 41_588_400, 41_167_300)


def ir3_workbook(*, unit: str = "persons", geography: str = "Ukraine", years=YEARS) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Resident population"
    sheet.append(["Year", "Resident population", "Unit", "Geography"])
    for index, year in enumerate(years):
        sheet.append([int(year), VALUES[index % len(VALUES)], unit, geography])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def ir3_zip(**kwargs) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("resident_population_2015_2021.xlsx", ir3_workbook(**kwargs))
    return stream.getvalue()


def ir3_design() -> ResearchDesign:
    subject = ResearchSubject(
        "subject-ua-resident-population",
        "Resident population",
        "en",
        ("resident population", "population"),
        (
            LexicalRepresentation(
                "resident-population-en",
                "en",
                "Resident population",
                ("resident population", "population"),
                ("resident-population",),
                "fixture",
                "approved",
            ),
        ),
        resolution_status=SubjectResolutionStatus.RESOLVED,
    )
    need = InformationNeed(
        "in",
        "rq",
        "Resident population by year",
        geography="Ukraine",
        evidence_expectation=EvidenceExpectation(
            EvidenceNature.QUANTITATIVE,
            required_aspects=("level", "timepoint", "geography"),
            geography="Ukraine",
            requires_quantitative_evidence=True,
        ),
        evidence_coverage=EvidenceCoverageContract(
            required_metric="Resident population",
            required_unit="persons",
            required_periods=YEARS,
            geography="Ukraine",
        ),
    )
    return ResearchDesign(
        "design",
        (ResearchQuestion("rq", "Resident population of Ukraine, 2015-2021"),),
        (need,),
        research_subject=subject,
    )


def ir3_source(raw: bytes | None = None) -> Source:
    raw = raw or ir3_zip()
    parsed = extract_xlsx_text(raw, content_type="application/zip")
    if not parsed.ok:
        raise AssertionError(parsed.failure_reason)
    return Source(
        "source",
        "project",
        "https://fixture.invalid/resident-population.zip",
        "https://fixture.invalid/resident-population.zip",
        "Resident population 2015-2021",
        datetime.now(timezone.utc).isoformat(),
        content_type="application/zip",
        content_text=parsed.text,
        content_checksum=sha256(parsed.text.encode()).hexdigest(),
        metadata=parsed.metadata,
        raw_content_checksum=sha256(raw).hexdigest(),
        raw_checksum_kind="sha256-bytes",
        extraction_revision="xlsx-structured-v2",
        workflow_run_refs=("run",),
        research_design_refs=("design",),
        information_need_refs=("in",),
        research_question_refs=("rq",),
    )


def _extract(raw: bytes | None = None):
    source = ir3_source(raw)
    sources = InMemorySourceRepository()
    evidence = InMemoryEvidenceRepository()
    sources.create(source)
    provider = Mock()
    provider.generate.side_effect = AssertionError("structured extraction must not call a provider")
    service = build_evidence_extraction_service(
        config=ApplicationConfig(evidence_extractor="llm"),
        overrides=ApplicationOverrides(),
        evidence_repository=evidence,
        source_repository=sources,
        llm_client=provider,
    )
    context = RunScopedSourceContext("run", "design", ("in",), ("rq",), ())
    ids, extracted, failures, empty = service._extract_from_source(
        source=source,
        design=ir3_design(),
        project_id="project",
        workflow_run_id="run",
        research_design_id="design",
        run_context=context,
    )
    rows = tuple(evidence.get_by_id(item_id) for item_id in ids)
    provider.generate.assert_not_called()
    return source, sources, rows, (extracted, failures, empty)


def _qualification(evidence, source_repository, *, temporal_decisions=None):
    return qualify_numeric_information_need(
        design=ir3_design(),
        information_need=ir3_design().information_needs[0],
        evidence=evidence,
        source_repository=source_repository,
        temporal_decisions=temporal_decisions or {
            (item.id, "in"): "applicable_satisfied" for item in evidence
        },
        allowed_workflow_run_ids=("run",),
    )


class _SingleSourceRepository:
    def __init__(self, source):
        self.source = source

    def get_by_id(self, source_id):
        return self.source if source_id == self.source.id else None


class IR3StructuredNumericClosureTests(unittest.TestCase):
    def test_zip_xlsx_candidates_persist_and_pass_temporal_f1_f2(self):
        source, sources, rows, outcome = _extract()
        self.assertEqual(outcome, (7, 0, False))
        self.assertEqual(len(rows), 7)
        brief = ResearchBrief(
            title="Resident population",
            business_question="Resident population",
            timeframe="2015–2021",
        )
        temporal = qualify_evidence_with_temporal_decisions(
            design=ir3_design(), evidence=rows, brief=brief, source_repository=sources,
        )
        projection = project_numeric_evidence_for_design(
            design=ir3_design(),
            evidence=temporal.evidence,
            source_repository=sources,
            temporal_decisions=temporal.decisions,
            allowed_workflow_run_ids=("run",),
        )
        result = projection.qualifications["in"]
        self.assertTrue(result.available)
        self.assertEqual(result.missing_periods, ())
        self.assertEqual(result.qualified_periods, YEARS)
        self.assertEqual(
            {item.id for item in result.accepted_evidence}, {item.id for item in rows},
        )
        self.assertEqual(tuple(sorted(item.period for item in result.observations)), YEARS)
        for index, row in enumerate(
            sorted(rows, key=lambda item: item.metadata["observation_period"]), start=2,
        ):
            structured = row.source_locator["structured"]
            self.assertEqual(structured, row.metadata["workbook_provenance"])
            self.assertEqual(structured["sheet"], "Resident population")
            self.assertEqual(structured["cell"], f"B{index}")
            self.assertEqual(structured["period_cell"], f"A{index}")
            self.assertEqual(structured["raw_workbook_checksum"], source.raw_content_checksum)
            self.assertEqual(structured["extraction_revision"], source.extraction_revision)
            self.assertEqual(structured["content_revision"], source.content_revision)

    def test_wrong_unit_is_rejected_by_f1_and_wrong_geography_by_extraction(self):
        context = RunScopedSourceContext("run", "design", ("in",), ("rq",), ())
        source, sources, rows, outcome = _extract(ir3_zip(unit="thousands"))
        self.assertEqual(outcome, (7, 0, False))
        unit_result = _qualification(rows, sources)
        self.assertEqual(
            unit_result.rejection_reason_counts,
            {"numeric_unit_or_geography_binding_invalid": 7},
        )
        self.assertEqual(unit_result.accepted_evidence, ())

        source = ir3_source(ir3_zip(geography="Poland"))
        self.assertEqual(
            StructuredEvidenceExtractor().extract(
                source=source, design=ir3_design(), run_context=context,
            ),
            [],
        )

    def test_out_of_contract_period_is_not_persisted(self):
        years = tuple(str(year) for year in range(2015, 2021)) + ("2022",)
        _, sources, rows, outcome = _extract(ir3_zip(years=years))
        self.assertEqual(outcome, (6, 0, False))
        self.assertNotIn("2022", {item.metadata["observation_period"] for item in rows})
        result = _qualification(rows, sources)
        self.assertEqual(result.missing_periods, ("2021",))

    def test_changed_source_checksum_is_rejected(self):
        source, _, rows, _ = _extract()
        changed = replace(source, raw_content_checksum="0" * 64)
        result = _qualification(rows, _SingleSourceRepository(changed))
        self.assertEqual(result.rejection_reason_counts, {"numeric_source_revision_mismatch": 7})
        self.assertEqual(result.accepted_evidence, ())

    def test_wrong_period_cell_and_range_are_rejected(self):
        source, _, rows, _ = _extract()
        row = rows[0]
        variants = []
        for key, value, expected in (
            ("period_cell", "Z99", "numeric_cell_binding_invalid"),
            ("cell", "Z98", "numeric_cell_binding_invalid"),
            ("table_range", "Z1:Z2", "ambiguous_numeric_source"),
        ):
            provenance = {**row.metadata["workbook_provenance"], key: value}
            variants.append((
                replace(
                    row,
                    metadata={**row.metadata, "workbook_provenance": provenance},
                    source_locator={**row.source_locator, "structured": provenance},
                ),
                expected,
            ))
        for forged, expected in variants:
            with self.subTest(expected=expected):
                result = _qualification((forged,), _SingleSourceRepository(source))
                self.assertEqual(result.rejection_reason_counts, {expected: 1})
                self.assertEqual(result.accepted_evidence, ())

    def test_wrong_subject_binding_is_rejected(self):
        source, _, rows, _ = _extract()
        row = rows[0]
        assignment = {**row.metadata["semantic_assignment"], "subject_fingerprint": "forged"}
        forged = replace(row, metadata={**row.metadata, "semantic_assignment": assignment})
        result = _qualification((forged,), _SingleSourceRepository(source))
        self.assertEqual(result.rejection_reason_counts, {"unvalidated_numeric_semantics": 1})
        self.assertEqual(result.accepted_evidence, ())


if __name__ == "__main__":
    unittest.main()
