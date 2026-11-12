"""Deterministic OUTPUT verification against frozen Design and immutable H3 claims."""
from dataclasses import asdict
from decimal import Decimal

from application.deliverables.contracts import PdfTable, PresentationChart
from application.report.claim_contract import canonical_digest
from domain.planning.derivation import InformationNeedKind


def verified_output_materials(*, design, claims, report):
    requirements = [n for n in design.information_needs if n.kind == InformationNeedKind.OUTPUT]
    if not requirements:
        return (), (), None
    if report.research_design_id != design.id:
        raise ValueError("output_design_scope_mismatch")
    if any(c.project_id != report.project_id or c.report_workflow_run_id != report.workflow_run_id or
           c.design_id != design.id or c.status != "validated" for c in claims):
        raise ValueError("output_claim_scope_mismatch")
    tables, charts, verified = [], [], []
    for need in requirements:
        if need.output_format not in {"table", "chart"} or not need.depends_on_information_need_ids:
            raise ValueError("output_requirement_needs_explicit_format_and_dependencies")
        selected = [c for c in claims if set(c.information_need_ids).intersection(need.depends_on_information_need_ids)]
        if not set(need.depends_on_information_need_ids) <= {ref for c in selected for ref in c.information_need_ids}:
            raise ValueError("output_dependency_claim_missing")
        observations = {}
        for claim in selected:
            if not claim.citation_ids or not claim.support_evidence_ids:
                raise ValueError("output_citation_missing")
            for fact in claim.scope.numeric_facts:
                if len(fact.periods) != 1 or len(fact.metrics) != 1 or not fact.unit:
                    continue
                key = (fact.periods[0], fact.metrics[0], fact.unit, tuple(fact.geography), fact.scale)
                number = Decimal(fact.value)
                if not number.is_finite() or (key in observations and observations[key] != number):
                    raise ValueError("output_conflicting_values")
                observations[key] = number
        if len(observations) < 2 or len({key[1:] for key in observations}) != 1:
            raise ValueError("output_requires_unambiguous_comparable_series")
        by_id = {n.id: n for n in design.information_needs}
        required_periods = {p for ref in need.depends_on_information_need_ids
            for p in ((by_id[ref].evidence_coverage.required_periods if by_id[ref].evidence_coverage else ()))}
        if required_periods and not required_periods <= {key[0] for key in observations}:
            raise ValueError("output_required_period_missing")
        ordered = sorted(observations)
        metric, unit = ordered[0][1:3]
        if need.output_format == "table":
            tables.append(PdfTable(need.description, ("Рік", "Значення", "Одиниця"),
                tuple((key[0], str(observations[key]), unit) for key in ordered), base=metric, unit=unit))
        else:
            charts.append(PresentationChart(need.description, tuple(key[0] for key in ordered),
                tuple(float(observations[key]) for key in ordered), base=metric, unit=unit,
                source_ref=", ".join(sorted({ref for c in selected for ref in c.citation_ids}))))
        verified.append(dict(information_need_id=need.id, output_format=need.output_format,
            claim_ids=sorted(c.claim_id for c in selected), periods=[key[0] for key in ordered], satisfied=True))
    payload = dict(version="verified-output-materials-v1", requirements=verified,
        tables=[{**asdict(t), "headers": list(t.headers), "rows": [list(row) for row in t.rows]} for t in tables],
        charts=[{**asdict(c), "labels": list(c.labels), "values": list(c.values)} for c in charts])
    payload["digest"] = canonical_digest(payload)
    return tuple(tables), tuple(charts), payload
