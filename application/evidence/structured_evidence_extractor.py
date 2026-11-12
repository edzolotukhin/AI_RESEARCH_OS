"""Deterministic explicit table mapping into the existing candidate contract."""
from decimal import Decimal
import re

from application.evidence.grounding import normalize_source_text
from application.evidence.semantic_assignment import CONTRACT_VERSION
from application.evidence.subject_relevance import assess_subject_text, SUBJECT_RELEVANT
from application.evidence.evidence_extraction_diagnostics import get_active_diagnostics
from application.ports.evidence_ports import EvidenceCandidate


def label(value):
    return " ".join(re.sub(r"[_\W]+", " ", str(value).casefold()).split())


def reject(source, need, reason):
    diagnostics=get_active_diagnostics()
    if diagnostics is not None and len(diagnostics.structured_rejections)<100:
        entry={"source_id":source.id,"information_need_id":need.id,"reason":reason}
        if entry not in diagnostics.structured_rejections:
            diagnostics.structured_rejections.append(entry)


class StructuredEvidenceExtractor:
    method_name="xlsx-structured-v2"

    def extract(self, *, source, design, run_context):
        rows=source.metadata.get("structured_tables_v2") or []
        candidates=[]
        for need in design.information_needs:
            if need.id not in run_context.information_need_ids:
                continue
            coverage=need.evidence_coverage
            if coverage is None or not coverage.required_metric:
                reject(source,need,"ambiguous_metric_binding")
                continue
            geography_constraints=[value for value in (need.geography,coverage.geography,
                need.evidence_expectation.geography if need.evidence_expectation else "") if value]
            if len({label(value) for value in geography_constraints})>1:
                reject(source,need,"conflicting_geography_contract")
                continue
            subject=design.research_subject
            if subject is None or not subject.executable:
                reject(source,need,"executable_subject_missing")
                continue
            matching=[]
            if not any(label(re.sub(r"\s*\([^)]*\)\s*$","",c.get("header","")))==label(coverage.required_metric) for row in rows for c in row.get("cells",())):
                reject(source,need,"ambiguous_metric_binding")
            for row in rows:
                cells=row["cells"]
                metrics=[c for c in cells if label(re.sub(r"\s*\([^)]*\)\s*$","",c["header"]))==label(coverage.required_metric)]
                periods=[c for c in cells if label(c["header"]) in {"year","рік","год"}]
                if not metrics:
                    continue
                if row["ambiguous_headers"] or len(metrics)!=1 or len(periods)!=1:
                    reject(source,need,"ambiguous_metric_binding")
                    continue
                metric,period=metrics[0],periods[0]
                if metric["formula"] or period["formula"] or metric["numeric_value"] is None or not re.fullmatch(r"(?:19|20)\d{2}",period["value"]):
                    reject(source,need,"invalid_value_or_period")
                    continue
                if coverage.required_periods and period["value"] not in coverage.required_periods:
                    continue
                units=[c["value"] for c in cells if label(c["header"]) in {"unit","units","одиниця","одиниці"} and c["value"]]
                header_unit=re.search(r"\(([^)]+)\)\s*$",metric["header"])
                if header_unit:
                    units.append(header_unit[1])
                if len(set(label(u) for u in units))!=1:
                    reject(source,need,"unit_missing_or_mismatch")
                    continue
                geographies=[c["value"] for c in cells if label(c["header"]) in {"geography","country","географія","країна"} and c["value"]]
                expected=need.geography or coverage.geography or (need.evidence_expectation.geography if need.evidence_expectation else "")
                if (expected and (len(set(label(g) for g in geographies))!=1 or label(geographies[0])!=label(expected))) or (geographies and len(set(label(g) for g in geographies))!=1):
                    reject(source,need,"geography_mismatch_or_missing")
                    continue
                matching.append((row,metric,period,units[0],expected or (geographies[0] if geographies else "")))
            by_period={}
            for item in matching:
                by_period.setdefault(item[2]["value"],[]).append(item)
            for period,items in by_period.items():
                if len(items)!=1:
                    reject(source,need,"ambiguous_metric_binding")
                    continue
                row,metric,period_cell,unit,geography=items[0]
                excerpt=row["excerpt"]
                if normalize_source_text(excerpt) not in normalize_source_text(source.content_text):
                    continue  # This row belongs to another extraction chunk.
                decision=assess_subject_text(subject=subject,statement=excerpt,excerpt=excerpt,information_need_id=need.id,design=design)
                if decision.decision!=SUBJECT_RELEVANT:
                    reject(source,need,"subject_binding_unresolved")
                    continue
                facts={"level","value","metric","period","timepoint","year","unit",label(coverage.required_metric)}
                if geography:
                    facts.add("geography")
                aspects=tuple(a for a in (need.evidence_expectation.required_aspects if need.evidence_expectation else ()) if label(a) in facts)
                binding={"subject_id":subject.subject_id,"subject_fingerprint":subject.semantic_fingerprint,
                    "binding_type":"supporting_relation" if decision.supporting_relation_id else "canonical_subject",
                    "supporting_relation_id":decision.supporting_relation_id}
                numeric=Decimal(metric["numeric_value"])
                provenance={"terminal_resource_key":source.terminal_resource_key,"raw_workbook_checksum":source.raw_content_checksum,
                    "raw_checksum_kind":source.raw_checksum_kind,"content_revision":source.content_revision,
                    "extraction_revision":source.extraction_revision,"sheet":row["sheet"],"sheet_index":row["sheet_index"],
                    "table_range":row["table_range"],"header_cells":row["header_cells"],"header_values":row["header_values"],
                    "header_checksum":row["header_checksum"],"row":row["row"],"column":metric["column"],
                    "cell":metric["cell"],"period_cell":period_cell["cell"],
                    "metric_header_cell":row["header_cells"][metric["column"]-1],
                    "period_header_cell":row["header_cells"][period_cell["column"]-1],
                    "unit_cells":[c["cell"] for c in row["cells"] if label(c["header"]) in {"unit","units","одиниця","одиниці"}],
                    "geography_cells":[c["cell"] for c in row["cells"] if label(c["header"]) in {"geography","country","географія","країна"}]}
                statement=f'{metric["header"]}={metric["value"]} | {period_cell["header"]}={period} | Unit={unit}'
                if geography:
                    statement += f" | Geography={geography}"
                candidates.append(EvidenceCandidate(statement=statement,source_excerpt=excerpt,evidence_type="direct_excerpt",
                    research_question_refs=(need.research_question_id,),information_need_refs=(need.id,),confidence=None,direct=True,
                    contract_version=CONTRACT_VERSION,required_aspect_refs=aspects,subject_binding=binding,
                    semantic_justification="Explicit table header, period and cell value; literal canonical row.",
                    geography_applicability=(expected,) if (expected:=need.geography or (need.evidence_expectation.geography if need.evidence_expectation else "")) else (),
                    metadata={"structured_table":True,"metric":coverage.required_metric,
                        "numeric_value":int(numeric) if numeric==numeric.to_integral_value() else float(numeric),
                        "normalized_numeric_value":str(numeric),"original_cell_value":metric["value"],
                        "unit":unit,"geography":geography,"observation_period":period,"workbook_provenance":provenance}))
        return candidates


class CompositeEvidenceExtractor:
    """Structured observations and existing chunked text share one service."""
    def __init__(self, text_extractor):
        self.text_extractor=text_extractor
        self.method_name=getattr(text_extractor,"method_name","unknown")
        self.chunk_chars=text_extractor.chunk_chars
        self.overlap_chars=text_extractor.overlap_chars

    @property
    def _inner(self):
        """Retain existing provider configuration/diagnostic inspection."""
        return self.text_extractor._inner

    def extract(self, *, source, design, run_context):
        if source.metadata.get("structured_tables_v2") or any(row.get("period") is not None for row in source.metadata.get("structured_rows",[]) if isinstance(row,dict)):
            # Never let a rejected numeric workbook fall through to an LLM that
            # could re-label the same ambiguous table as qualified numeric data.
            from dataclasses import replace
            structured=StructuredEvidenceExtractor().extract(source=source,design=design,run_context=run_context)
            narrative_ids=tuple(n.id for n in design.information_needs if n.id in run_context.information_need_ids
                and n.evidence_expectation is not None and n.evidence_expectation.nature.value=="qualitative"
                and not n.evidence_expectation.requires_quantitative_evidence)
            if not narrative_ids:
                return structured
            narrative=self.text_extractor.extract(source=source,design=design,run_context=replace(run_context,information_need_ids=narrative_ids))
            # Qualitative descriptions may coexist, but cannot duplicate a
            # structured numeric observation under a different IN assignment.
            numeric_values={c["value"] for row in source.metadata.get("structured_tables_v2",()) for c in row["cells"] if c.get("numeric_value") is not None and label(c["header"]) not in {"year","рік","год"}}
            narrative=[c for c in narrative if not any(re.search(r"(?<!\w)"+re.escape(value)+r"(?!\w)",c.statement+" "+c.source_excerpt) for value in numeric_values)]
            return structured+narrative
        return self.text_extractor.extract(source=source,design=design,run_context=run_context)
