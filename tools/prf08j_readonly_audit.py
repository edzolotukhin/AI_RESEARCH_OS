"""PRF-08J-only read-only metadata audit; no provider calls or payload output."""
import json
import os
from collections import Counter
from urllib.parse import urlparse

import psycopg
from application.evidence.temporal_scope import qualifying_evidence, exact_observation_cutoff, temporal_eligibility
from application.research_quality.deterministic_sufficiency_evaluator import DeterministicSufficiencyEvaluator
from domain.evidence.evidence import Evidence
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief

RUN = "28b1b640-1ad0-5614-b1e0-4a01e9db3e19"
PROJECT = "17fdec94-faf7-46b1-bec1-c09b74fdf1e5"


def safe_summary(value):
    if not isinstance(value, dict):
        return value
    return {k: v for k, v in value.items() if isinstance(v, (int, float, bool)) or v is None or k.endswith(("_state", "_reason", "_status"))}


def main():
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(url)
    assert (parsed.username, parsed.hostname, parsed.path) == ("prf08j", "postgres", "/prf08j_acceptance")
    with psycopg.connect(url, options="-c default_transaction_read_only=on") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT brief,planning_design FROM projects WHERE id=%s", (PROJECT,))
            b, d = cur.fetchone()
            brief, design = ResearchBrief.from_dict(b), ResearchDesign.from_dict(d)
            cur.execute("SELECT row_to_json(e) FROM evidence e WHERE workflow_run_id=%s ORDER BY created_at,id", (RUN,))
            raw = [Evidence.from_dict(r[0]) for r in cur.fetchall()]
            qualified = qualifying_evidence(design=design, evidence=raw, brief=brief)
            qids = {e.id for e in qualified}
            cur.execute("SELECT status,task_results FROM workflow_runs WHERE id=%s", (RUN,))
            status, results = cur.fetchone()
            cur.execute("SELECT task_id,name,status,created_at,updated_at FROM workflow_tasks WHERE workflow_run_id=%s ORDER BY sort_order", (RUN,))
            tasks = cur.fetchall()
            cur.execute("SELECT id,url,retrieval_status,information_need_refs FROM sources WHERE project_id=%s ORDER BY retrieved_at,id", (PROJECT,))
            sources = cur.fetchall()
    output = {"run_id": RUN, "status": status, "raw": len(raw), "qualifying": len(qualified),
              "per_need": {n.id: {"raw": sum(n.id in e.information_need_refs for e in raw), "qualifying": sum(n.id in e.information_need_refs for e in qualified)} for n in design.information_needs},
              "sources": [{"id": s[0], "url": s[1], "status": s[2], "needs": s[3], "raw": sum(e.source_id == s[0] for e in raw), "qualifying": sum(e.source_id == s[0] for e in qualified)} for s in sources], "stages": []}
    cutoff = exact_observation_cutoff(brief)
    signals = {s.information_need_id: s for s in DeterministicSufficiencyEvaluator().evaluate(design=design, evidence=qualified)}
    output["integrity"] = {n.id: {"temporal": dict(Counter(temporal_eligibility(e, n, cutoff) for e in raw if n.id in e.information_need_refs)), "independent_lineages": signals[n.id].independent_source_count} for n in design.information_needs}
    for task_id, name, state, created, updated in tasks:
        shared = results.get(task_id, {}).get("shared_state", {})
        stage = {"name": name, "status": state, "created": str(created), "updated": str(updated), "shared_keys": list(shared)}
        for key in ("source_acquisition", "evidence_extraction", "research_readiness", "research_loop_state", "remediation_extraction"):
            if key == "source_acquisition" and name != "Collect sources":
                continue
            if key == "evidence_extraction" and name != "Extract evidence":
                continue
            value = shared.get(key)
            if not isinstance(value, dict):
                continue
            summary = safe_summary(value)
            if key in ("evidence_extraction", "remediation_extraction"):
                ids = value.get("evidence_ids", [])
                selected = [e for e in raw if e.id in ids]
                summary["qualifying_produced"] = sum(e.id in qids for e in selected)
                summary["per_need_produced"] = {n.id: {"raw": sum(n.id in e.information_need_refs for e in selected), "qualifying": sum(n.id in e.information_need_refs and e.id in qids for e in selected)} for n in design.information_needs}
            if key == "research_readiness":
                summary["sufficiency_assessment_diagnostics"] = value.get("sufficiency_assessment_diagnostics")
            if key == "research_loop_state":
                summary["scheduler_decisions"] = value.get("scheduler_decisions", [])
                summary["history"] = [{k: v for k, v in h.items() if k != "readiness_after"} for h in value.get("history", [])]
            diag = value.get("diagnostics", {})
            if isinstance(diag, dict):
                summary["diagnostics"] = safe_summary(diag)
                summary["work_items"] = []
                offset = 0
                for w in diag.get("work_items", []):
                    item = {k: w.get(k) for k in ("queue_index", "source_id", "information_need_ids", "primary_need_id", "phase", "extractor_attempts", "extractor_status", "raw_candidate_count", "budget_remaining_before", "budget_remaining_after")}
                    item["outcomes"] = dict(Counter(c.get("outcome") for c in w.get("candidate_outcomes", [])))
                    item["inner_statuses"] = [c.get("extractor_status") for c in w.get("inner_chunks", [])]
                    item["responses"] = [{k: c.get("response_shape", {}).get(k) for k in ("response_classification", "structured_attempts", "completion_output_tokens", "completion_reasoning_tokens", "completion_max_output_tokens")} for c in w.get("inner_chunks", [])]
                    count = item["outcomes"].get("persisted", 0)
                    work_ids = value.get("evidence_ids", [])[offset:offset + count]
                    offset += count
                    matched = [e for e in raw if e.id in work_ids]
                    assert len(matched) == count and all(e.source_id == w["source_id"] for e in matched)
                    item["qualifying_produced"] = sum(e.id in qids for e in matched)
                    summary["work_items"].append(item)
            stage[key] = summary
        output["stages"].append(stage)
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
