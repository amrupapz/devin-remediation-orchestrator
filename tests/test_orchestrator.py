from app import store
from app.devin import extract_pr_url, is_settled
from app.orchestrator import BLOCKED, DONE, FAILED, RUNNING, Orchestrator
from tests.conftest import FakeDevin, FakeGitHub, issue

PR_URL = "https://github.com/amrupapz/superset/pull/3"


def finished(pr_url=PR_URL, outcome="fixed", status="exit", detail="finished", acus=2.5):
    session = {
        "session_id": "devin-test-1",
        "status": status,
        "status_detail": detail,
        "acus_consumed": acus,
        "pull_requests": [{"pr_url": pr_url, "pr_state": "open"}] if pr_url else [],
        "structured_output": {
            "status": outcome,
            "pr_url": pr_url,
            "verification": "pre-commit run -> Passed; npx jest suite -> 6/6 passed",
            "risk_notes": "Deletion only; confirm no downstream imports.",
        },
    }
    return session


def run(devin, github=None):
    orch = Orchestrator(devin=devin, github=github or FakeGitHub())
    return orch


def test_launches_one_session_per_issue_and_stores_the_link():
    devin = FakeDevin()
    orch = run(devin)

    assert orch.handle_issue(issue(1)) is True

    task = store.get(1)
    assert task["status"] == RUNNING
    assert task["session_id"] == "devin-test-1"
    assert task["session_url"].endswith("devin-test-1")
    assert devin.created[0]["tags"] == ["remediation-orchestrator", "issue-1"]


def test_duplicate_issue_does_not_create_a_second_session():
    devin = FakeDevin()
    orch = run(devin, FakeGitHub(issues=[issue(1)]))

    assert orch.handle_issue(issue(1)) is True
    assert orch.handle_issue(issue(1)) is False
    assert orch.sync_issues() == 0  # the poller must not re-launch either
    assert len(devin.created) == 1


def test_concurrency_cap_defers_extra_issues(monkeypatch):
    monkeypatch.setattr("app.orchestrator.MAX_CONCURRENT", 1)
    devin = FakeDevin()
    orch = run(devin)

    assert orch.handle_issue(issue(1)) is True
    assert orch.handle_issue(issue(2)) is False
    assert len(devin.created) == 1


def test_session_launch_failure_marks_the_task_failed():
    devin = FakeDevin(create_error=RuntimeError("403 Forbidden"))
    orch = run(devin)

    assert orch.handle_issue(issue(7)) is False
    task = store.get(7)
    assert task["status"] == FAILED
    assert "403" in task["error"]


def test_successful_completion_records_pr_and_comments_on_the_issue():
    devin = FakeDevin(sessions={"devin-test-1": finished()})
    github = FakeGitHub()
    orch = run(devin, github)
    orch.handle_issue(issue(1))

    orch.poll_sessions()

    task = store.get(1)
    assert task["status"] == DONE
    assert task["outcome"] == "fixed"
    assert task["pr_url"] == PR_URL
    assert task["acus_consumed"] == 2.5
    assert task["session_status"] == "exit"
    assert task["commented"] == 1

    number, body = github.comments[0]
    assert number == 1
    assert PR_URL in body
    assert "https://app.devin.ai/sessions/devin-test-1" in body
    assert "pre-commit run" in body


def test_running_session_is_left_alone_but_acus_are_tracked():
    working = {"status": "running", "status_detail": "working", "acus_consumed": 0.7}
    devin = FakeDevin(sessions={"devin-test-1": working})
    github = FakeGitHub()
    orch = run(devin, github)
    orch.handle_issue(issue(1))

    orch.poll_sessions()

    task = store.get(1)
    assert task["status"] == RUNNING
    assert task["acus_consumed"] == 0.7
    assert github.comments == []


def test_finished_session_without_a_pull_request_is_not_a_success():
    # The agent claims success but opened no PR: a PR URL is the only proof.
    session = finished(pr_url=None, outcome="fixed")
    devin = FakeDevin(sessions={"devin-test-1": session})
    github = FakeGitHub()
    orch = run(devin, github)
    orch.handle_issue(issue(1))

    orch.poll_sessions()

    task = store.get(1)
    assert task["status"] == BLOCKED
    assert task["pr_url"] is None
    assert "did not open a pull request" in github.comments[0][1]
    assert orch.metrics()["prs_opened"] == 0
    assert orch.metrics()["success_rate"] == 0.0


def test_blocked_outcome_is_reported_with_the_reason():
    session = finished(pr_url=None, outcome="blocked", status="running", detail="finished")
    devin = FakeDevin(sessions={"devin-test-1": session})
    github = FakeGitHub()
    orch = run(devin, github)
    orch.handle_issue(issue(2))

    orch.poll_sessions()

    task = store.get(2)
    assert task["status"] == BLOCKED
    assert task["outcome"] == "blocked"
    assert "confirm no downstream imports" in github.comments[0][1]


def test_errored_and_suspended_sessions_are_failures():
    devin = FakeDevin(
        sessions={
            "devin-test-1": {"status": "error", "status_detail": None, "pull_requests": []},
            "devin-test-2": {
                "status": "suspended",
                "status_detail": "usage_limit_exceeded",
                "pull_requests": [],
            },
        }
    )
    orch = run(devin)
    orch.handle_issue(issue(1))
    orch.handle_issue(issue(2))

    orch.poll_sessions()

    assert store.get(1)["status"] == FAILED
    assert store.get(2)["status"] == FAILED
    assert store.get(2)["outcome"] == "usage_limit_exceeded"
    assert orch.metrics()["failed"] == 2


def test_v3_status_settlement_rules():
    assert is_settled({"status": "running", "status_detail": "finished"}) is True
    assert is_settled({"status": "running", "status_detail": "working"}) is False
    assert is_settled({"status": "new"}) is False
    assert is_settled({"status": "exit"}) is True
    assert is_settled({"status": "error"}) is True
    assert is_settled({"status": "suspended", "status_detail": "inactivity"}) is True


def test_pr_url_prefers_the_session_pull_requests_over_structured_output():
    session = {
        "pull_requests": [{"pr_url": PR_URL, "pr_state": "open"}],
        "structured_output": {"pr_url": "https://example.com/wrong"},
    }
    assert extract_pr_url(session) == PR_URL
    assert extract_pr_url({"pull_requests": [], "structured_output": {"pr_url": PR_URL}}) == PR_URL
    assert extract_pr_url({"pull_requests": [], "structured_output": {"pr_url": None}}) is None


def test_metrics_summarise_throughput():
    devin = FakeDevin(
        sessions={
            "devin-test-1": finished(),
            "devin-test-2": finished(pr_url=None, outcome="blocked"),
        }
    )
    orch = run(devin)
    orch.handle_issue(issue(1))
    orch.handle_issue(issue(2))
    orch.poll_sessions()

    metrics = orch.metrics()
    assert metrics["issues_detected"] == 2
    assert metrics["sessions_launched"] == 2
    assert metrics["prs_opened"] == 1
    assert metrics["blocked"] == 1
    assert metrics["success_rate"] == 50.0
    assert metrics["in_flight"] == 0
    assert metrics["acus_consumed"] == 5.0
    assert metrics["median_time_to_pr_seconds"] is not None
