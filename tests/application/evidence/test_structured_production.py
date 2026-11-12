from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import io
import unittest
from unittest.mock import Mock
from openpyxl import Workbook

from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.evidence.structured_evidence_extractor import StructuredEvidenceExtractor
from application.evidence.provenance_validation import validate_candidate_provenance
from application.evidence.temporal_scope import qualifying_evidence
from application.evidence.citation_integrity import citation_is_valid
from domain.planning.research_design import ResearchDesign, ResearchQuestion, InformationNeed, EvidenceCoverageContract
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_subject import ResearchSubject, LexicalRepresentation, SubjectResolutionStatus
from domain.research_brief import ResearchBrief
from domain.sources.source import Source
from infrastructure.retrieval.xlsx_text_extractor import extract_xlsx_text
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository


def design():
    subject=ResearchSubject("population","Population","en",("population",),
        (LexicalRepresentation("population-en","en","Population",("population",),("population",),"fixture","approved"),),
        resolution_status=SubjectResolutionStatus.RESOLVED)
    need=InformationNeed("in-pop","rq-pop","Population",geography="Ukraine",
        evidence_expectation=EvidenceExpectation(EvidenceNature.QUANTITATIVE,required_aspects=("level","timepoint","geography"),geography="Ukraine",requires_quantitative_evidence=True),
        evidence_coverage=EvidenceCoverageContract(required_metric="Population",required_periods=("2019","2020","2021"),geography="Ukraine"))
    return ResearchDesign("design",(ResearchQuestion("rq-pop","Population"),),(need,),research_subject=subject)


def workbook_rows(extra=None,merged=False,formula=False):
    book=Workbook()
    sheet=book.active
    sheet.title="Population"
    sheet.append(["Year","Population","Unit","Geography"])
    for year,value in ((2019,1000),(2020,950),(2021,900)):
        sheet.append([year,"=1000-50" if formula else value,"persons","Ukraine"])
    if extra:
        sheet.append([])
        for row in extra:
            sheet.append(row)
    if merged:
        sheet.merge_cells("B1:C1")
    stream=io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def source(data=None):
    data=data or workbook_rows()
    result=extract_xlsx_text(data)
    return Source("source","project","https://example.org/data.xlsx","https://example.org/data.xlsx","Population",
        datetime.now(timezone.utc).isoformat(),content_text=result.text,content_checksum=sha256(result.text.encode()).hexdigest(),
        metadata=result.metadata,raw_content_checksum=sha256(data).hexdigest(),raw_checksum_kind="sha256-bytes",extraction_revision="xlsx-structured-v2",
        workflow_run_refs=("run",),research_design_refs=("design",),information_need_refs=("in-pop",),research_question_refs=("rq-pop",))


def context():
    return RunScopedSourceContext("run","design",("in-pop",),("rq-pop",),())


class StructuredProductionTests(unittest.TestCase):
    def test_exact_rows_and_v2_validation(self):
        item=source()
        candidates=StructuredEvidenceExtractor().extract(source=item,design=design(),run_context=context())
        self.assertEqual([c.metadata["numeric_value"] for c in candidates],[1000,950,900])
        self.assertEqual([c.metadata["observation_period"] for c in candidates],["2019","2020","2021"])
        for candidate in candidates:
            validated=validate_candidate_provenance(candidate,run_context=context(),design=design())
            self.assertEqual(validated.metadata["semantic_assignment"]["required_aspect_refs"],["level","timepoint","geography"])
            self.assertIn(candidate.source_excerpt,item.content_text)
            self.assertEqual(candidate.metadata["workbook_provenance"]["column"],2)

    def test_other_metric_table_is_not_mapped(self):
        item=source(workbook_rows([["Year","Growth rate","Unit","Geography"],[2019,99,"percent","Ukraine"]]))
        candidates=StructuredEvidenceExtractor().extract(source=item,design=design(),run_context=context())
        self.assertEqual([c.metadata["numeric_value"] for c in candidates],[1000,950,900])
        base=design()
        growth=replace(base.information_needs[0],id="in-growth",evidence_coverage=replace(base.information_needs[0].evidence_coverage,required_metric="Growth rate"))
        combined=replace(base,information_needs=(*base.information_needs,growth))
        scope=replace(context(),information_need_ids=("in-pop","in-growth"))
        candidates=StructuredEvidenceExtractor().extract(source=item,design=combined,run_context=scope)
        self.assertEqual([c.metadata["numeric_value"] for c in candidates if c.information_need_refs==("in-growth",)],[99])
        self.assertTrue(all("Growth rate=" not in c.statement for c in candidates if c.information_need_refs==("in-pop",)))

    def test_duplicate_metric_period_is_ambiguous(self):
        item=source(workbook_rows([["Year","Population","Unit","Geography"],[2019,999,"persons","Ukraine"]]))
        candidates=StructuredEvidenceExtractor().extract(source=item,design=design(),run_context=context())
        self.assertNotIn("2019",[c.metadata["observation_period"] for c in candidates])

    def test_merged_headers_and_formulas_fail_closed(self):
        for data in (workbook_rows(merged=True),workbook_rows(formula=True)):
            self.assertEqual(StructuredEvidenceExtractor().extract(source=source(data),design=design(),run_context=context()),[])

    def test_missing_period_and_metric_are_not_guessed(self):
        for header,period in (("Unspecified",2019),("Population","unknown")):
            book=Workbook()
            book.active.append(["Year",header,"Unit","Geography"])
            book.active.append([period,1000,"persons","Ukraine"])
            output=io.BytesIO()
            book.save(output)
            self.assertEqual(StructuredEvidenceExtractor().extract(source=source(output.getvalue()),design=design(),run_context=context()),[])

    def test_unresolved_upper_header_level_is_not_discarded(self):
        book=Workbook()
        book.active.append(["Subgroup: men"])
        book.active.append(["Year","Population","Unit","Geography"])
        book.active.append([2019,1000,"persons","Ukraine"])
        output=io.BytesIO()
        book.save(output)
        self.assertEqual(StructuredEvidenceExtractor().extract(source=source(output.getvalue()),design=design(),run_context=context()),[])

    def test_qualitative_text_coexists_without_duplicate_numeric_claims(self):
        from application.evidence.structured_evidence_extractor import CompositeEvidenceExtractor
        from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
        from application.ports.evidence_ports import EvidenceCandidate
        item=source()
        note="Population methodology is census based."
        item.content_text += "\n"+note
        base=design()
        need=InformationNeed("notes","rq-pop","Population methodology",evidence_expectation=EvidenceExpectation(EvidenceNature.QUALITATIVE))
        model=replace(base,information_needs=(*base.information_needs,need))
        scope=replace(context(),information_need_ids=("in-pop","notes"))
        class TextBoundary:
            def extract(self,**kwargs):
                return [EvidenceCandidate(note,note,"direct_excerpt",("rq-pop",),("notes",)),
                        EvidenceCandidate("Population 2019 = 1000",item.metadata["structured_tables_v2"][0]["excerpt"],"direct_excerpt",("rq-pop",),("notes",))]
        result=CompositeEvidenceExtractor(ChunkedEvidenceExtractor(TextBoundary())).extract(source=item,design=model,run_context=scope)
        self.assertEqual(len(result),4)
        self.assertEqual([c.statement for c in result if c.information_need_refs==("notes",)],[note])

    def test_wrong_geography_and_unit_conflict(self):
        for needle,replacement in (("Ukraine","Poland"),("Population","Population (percent)")):
            book=Workbook()
            book.active.append(["Year","Population","Unit","Geography"])
            book.active.append([2019,1000,"persons","Ukraine"])
            for row in book.active:
                for cell in row:
                    if cell.value==needle:
                        cell.value=replacement
            output=io.BytesIO()
            book.save(output)
            self.assertEqual(StructuredEvidenceExtractor().extract(source=source(output.getvalue()),design=design(),run_context=context()),[])

    def test_production_factory_persistence_qualification_and_dedup(self):
        sources=InMemorySourceRepository()
        evidence=InMemoryEvidenceRepository()
        item=source()
        sources.create(item)
        provider=Mock()
        service=build_evidence_extraction_service(config=ApplicationConfig(evidence_extractor="llm"),overrides=ApplicationOverrides(),evidence_repository=evidence,source_repository=sources,llm_client=provider)
        kwargs=dict(source=item,design=design(),project_id="project",workflow_run_id="run",research_design_id="design",run_context=context())
        first=service._extract_from_source(**kwargs)
        second=service._extract_from_source(**kwargs)
        rows=evidence.list_for_project("project",workflow_run_id="run")
        rows.sort(key=lambda e:e.metadata["observation_period"])
        self.assertEqual(len(rows),3,(first,second))
        self.assertEqual([e.metadata["numeric_value"] for e in rows],[1000,950,900])
        for row in rows:
            self.assertTrue(citation_is_valid(row,item))
            self.assertEqual(row.extraction_method,"xlsx-structured-v2")
            self.assertIn("cell",row.source_locator["structured"])
        self.assertEqual(len(qualifying_evidence(design=design(),evidence=rows,brief=ResearchBrief(title="Population",business_question="Population",timeframe="2019–2021"),source_repository=sources)),3)
        forged=replace(rows[0],metadata={**rows[0].metadata,"observation_period":"2018"})
        self.assertEqual(qualifying_evidence(design=design(),evidence=(forged,),brief=ResearchBrief(title="Population",business_question="Population",timeframe="2019–2021"),source_repository=sources),())
        provider.generate.assert_not_called()
