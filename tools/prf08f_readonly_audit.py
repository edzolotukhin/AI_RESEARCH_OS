"""Read-only PRF-08F evidence/temporal/lineage audit; never calls providers."""

from __future__ import annotations

import json
import os
from collections import Counter
from urllib.parse import urlparse

import psycopg

from application.evidence.temporal_scope import (
    exact_observation_cutoff,
    observation_eligibility,
    qualifying_evidence,
    temporal_eligibility,
)
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from domain.evidence.evidence import Evidence
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief


PROJECT_ID = "19546177-6604-4bbf-ad2d-3fe18895096c"
RUN_ID = "8b587f8b-43f0-5e2c-85b5-83c7792e37a9"


def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    parsed = urlparse(url.replace("postgresql+psycopg://", "postgresql://", 1))
    if (parsed.username, parsed.hostname, parsed.path) != (
        "prf08f", "postgres", "/prf08f_acceptance",
    ):
        raise RuntimeError("Refusing non-PRF-08F database")
    with psycopg.connect(
        url.replace("postgresql+psycopg://", "postgresql://", 1),
        options="-c default_transaction_read_only=on",
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT brief, planning_design FROM projects WHERE id = %s",
                (PROJECT_ID,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("PRF-08F project absent")
            brief = ResearchBrief.from_dict(row[0])
            design = ResearchDesign.from_dict(row[1])
            if brief is None or design is None:
                raise RuntimeError("Frozen brief/design absent")
            cursor.execute(
                "SELECT row_to_json(e) FROM evidence e "
                "WHERE project_id = %s AND workflow_run_id = %s ORDER BY id",
                (PROJECT_ID, RUN_ID),
            )
            raw = tuple(Evidence.from_dict(item) for (item,) in cursor.fetchall())
    cutoff = exact_observation_cutoff(brief)
    if cutoff is None:
        raise RuntimeError("Frozen observation cutoff missing")
    qualifying = qualifying_evidence(design=design, evidence=raw, brief=brief)
    signal_by_need = {
        signal.information_need_id: signal
        for signal in DeterministicSufficiencyEvaluator().evaluate(
            design=design, evidence=qualifying,
        )
    }
    items = []
    for need in design.information_needs:
        mapped = [item for item in raw if need.id in item.information_need_refs]
        eligible = [item for item in qualifying if need.id in item.information_need_refs]
        signal = signal_by_need[need.id]
        items.append({
            "information_need": need.id,
            "research_question": need.research_question_id,
            "raw_evidence": len(mapped),
            "qualifying_evidence": len(eligible),
            "temporal_state": dict(Counter(
                temporal_eligibility(item, need, cutoff) for item in mapped
            )),
            "static_undated_accepted_ids": sorted(
                item.id[:8] for item in mapped
                if temporal_eligibility(item, need, cutoff) == "not_applicable"
            ),
            "out_of_period_excluded_ids": sorted(
                item.id[:8] for item in mapped
                if temporal_eligibility(item, need, cutoff) == "applicable_failed"
            ),
            "observation_period_state": dict(Counter(
                observation_eligibility(item, cutoff) for item in mapped
            )),
            "independent_lineages": signal.independent_source_count,
            "known_origin_ids": sorted({
                item.metadata.get("data_lineage", {}).get("origin_id", "")
                for item in eligible
                if isinstance(item.metadata.get("data_lineage"), dict)
                and item.metadata["data_lineage"].get("status") == "established"
            }),
            "qualifying_source_id_prefixes": sorted({item.source_id[:8] for item in eligible}),
        })
    print(json.dumps({
        "run_id": RUN_ID,
        "design_id": design.id,
        "cutoff": cutoff.isoformat(),
        "raw_evidence": len(raw),
        "qualifying_evidence": len(qualifying),
        "needs": items,
        "unmapped_research_questions": sorted({
            question.id for question in design.research_questions
        } - {need.research_question_id for need in design.information_needs}),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
