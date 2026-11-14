from tools.real_research_e2e import _acceptance_failure, _source_acquisition_diagnostics


def test_failed_workflow_is_not_an_accepted_e2e_result():
    assert _acceptance_failure({"workflow_status": "failed"}) == "workflow execution failed"


def test_insufficient_outcome_is_not_an_accepted_e2e_result():
    assert _acceptance_failure({"workflow_status": "completed", "outcome": "INSUFFICIENT"}) == (
        "research outcome is INSUFFICIENT"
    )


def test_completed_result_with_outcome_is_accepted():
    assert _acceptance_failure({"workflow_status": "completed", "outcome": "COMPLETED"}) is None


def test_missing_outcome_is_not_an_accepted_e2e_result():
    assert _acceptance_failure({"workflow_status": "completed"}) == (
        "authoritative research outcome is missing"
    )


def test_ambiguous_outcome_is_only_expected_for_failed_workflow():
    failed = {"workflow_status": "failed", "research_result_error": "Ambiguous durable research outcome"}
    completed = {"workflow_status": "completed", "research_result_error": "Ambiguous durable research outcome"}
    assert _acceptance_failure(failed) == "workflow execution failed"
    assert _acceptance_failure(completed) == "authoritative research result is unavailable"


def test_source_acquisition_diagnostics_aggregates_durable_summary_without_identifiers():
    result = _source_acquisition_diagnostics({
        "task_results": [{
            "snapshot": {
                "shared_state": {
                    "source_acquisition": {
                        "candidate_count_raw": 12,
                        "candidate_count_unique": 10,
                        "candidates_attempted": 5,
                        "acquired_count": 2,
                        "failed_count": 3,
                        "skipped_duplicate_count": 2,
                        "skipped_budget_count": 3,
                        "failure_category_counts": {"http_error": 2, "unsupported_content_type": 1},
                        "selection_decisions": [
                            {"canonical_url": "https://secret.example/a", "source_id": "private-id", "action": "fetch_failed", "reason": "http_error"},
                            {"canonical_url": "https://secret.example/b", "source_id": "private-id-2", "action": "skipped_duplicate_content", "reason": "acquired_duplicate_content"},
                        ],
                    },
                    "research_funnel_v1": {
                        "events": [
                            {"kind": "candidate", "url": "https://secret.example/a"},
                            {"kind": "acquisition", "status": "failed", "source_id": "private-id", "reason": "http_error"},
                        ],
                    },
                },
            },
        }],
    })

    assert result["summary"]["acquired_count"] == 2
    assert result["summary"]["candidate_count_raw"] == 12
    assert result["failure_category_counts"] == {"http_error": 2, "unsupported_content_type": 1}
    assert result["selection_action_counts"] == {"fetch_failed": 1, "skipped_duplicate_content": 1}
    assert result["funnel_event_counts"] == {"candidate": 1, "acquisition": 1}
    serialized = str(result)
    assert "secret.example" not in serialized
    assert "private-id" not in serialized
