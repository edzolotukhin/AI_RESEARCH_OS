from tools.real_research_e2e import _acceptance_failure


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
