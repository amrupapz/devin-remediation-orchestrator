"""Mock end-to-end: labelled issues -> sessions -> PRs -> metrics."""

from app import store
from app.devin import DevinClient
from app.github import GitHubClient
from app.orchestrator import DONE, RUNNING, Orchestrator


def test_dry_run_flow_from_issues_to_metrics():
    devin = DevinClient(api_key="", org_id="", dry_run=True)
    orch = Orchestrator(devin=devin, github=GitHubClient(token="", dry_run=True))

    launched = orch.sync_issues()
    assert launched == 2

    orch.poll_sessions()
    running = orch.metrics()
    assert running["issues_detected"] == 2
    assert running["sessions_launched"] == 2
    assert running["in_flight"] == 2
    assert running["prs_opened"] == 0
    assert all(task["status"] == RUNNING for task in store.all_tasks())

    # Fast-forward the canned lifecycle instead of sleeping for it.
    for state in devin._fake.values():
        state["created"] -= 60
    orch.poll_sessions()

    tasks = store.all_tasks()
    assert {task["status"] for task in tasks} == {DONE}
    for task in tasks:
        assert task["session_url"].startswith("https://app.devin.ai/sessions/")
        assert task["acus_consumed"] > 0
        assert task["verification"]
        assert task["risk_notes"]
        assert (task["pr_url"] is not None) == (task["status"] == DONE)

    metrics = orch.metrics()
    assert metrics["in_flight"] == 0
    assert metrics["prs_opened"] == 2
    assert metrics["blocked"] == 0
    assert metrics["success_rate"] == 100.0
    assert metrics["acus_consumed"] > 0
    assert metrics["engineer_hours_saved"] == round(
        metrics["prs_opened"] * metrics["hours_saved_assumption"], 1
    )

    # Re-polling settled tasks changes nothing and launches nothing new.
    orch.poll_sessions()
    assert orch.sync_issues() == 0
    assert orch.metrics() == metrics
