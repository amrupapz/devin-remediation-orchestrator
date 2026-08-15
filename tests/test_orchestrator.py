from app.devin import DevinClient
from app.orchestrator import BLOCKED, DONE, Orchestrator


class MemoryStore:
    def __init__(self):
        self.rows = {}

    def get(self, number):
        return self.rows.get(number)

    def all_tasks(self):
        return list(self.rows.values())

    def count_by_status(self, status):
        return sum(row["status"] == status for row in self.rows.values())

    def insert(self, number, title, url, status):
        self.rows[number] = {
            "issue_number": number,
            "title": title,
            "issue_url": url,
            "status": status,
            "session_id": None,
            "session_url": None,
            "pr_url": None,
            "outcome": None,
            "verification": None,
            "risk_notes": None,
            "error": None,
            "commented": 0,
            "started_at": None,
            "finished_at": None,
            "acus_consumed": None,
        }

    def update(self, number, **fields):
        self.rows[number].update(fields)


class GitHub:
    def __init__(self, issues):
        self.issues = issues
        self.comments = []

    def labelled_issues(self):
        return self.issues

    def comment(self, number, body):
        self.comments.append((number, body))


ISSUE = {
    "number": 1,
    "title": "Remove orphaned component",
    "body": "Delete the unused POC.",
    "html_url": "https://github.com/amrupapz/superset/issues/1",
}


def test_dry_run_end_to_end_is_idempotent_and_observable():
    task_store = MemoryStore()
    github = GitHub([ISSUE])
    devin = DevinClient(dry_run=True, dry_run_seconds=0)
    orchestrator = Orchestrator(devin=devin, github=github, task_store=task_store)

    assert orchestrator.sync_issues() == 1
    assert orchestrator.sync_issues() == 0
    orchestrator.poll_sessions()

    task = task_store.get(1)
    assert task["status"] == DONE
    assert task["pr_url"].endswith("/pull/1")
    assert task["commented"] == 1
    assert orchestrator.metrics()["success_rate"] == 100.0
    assert orchestrator.metrics()["acus_consumed"] == 1.25


def test_finished_without_pr_is_visible_as_blocked():
    task_store = MemoryStore()
    github = GitHub([])
    task_store.insert(1, ISSUE["title"], ISSUE["html_url"], "running")
    task_store.update(1, session_id="devin-1", session_url="https://app.devin.ai/sessions/devin-1")
    orchestrator = Orchestrator(
        devin=DevinClient(dry_run=True), github=github, task_store=task_store
    )

    orchestrator._apply_session(
        task_store.get(1),
        {
            "status": "running",
            "status_detail": "finished",
            "structured_output": {
                "status": "fixed",
                "verification": "tests passed",
                "risk_notes": "no PR was produced",
            },
        },
    )

    assert task_store.get(1)["status"] == BLOCKED
    assert orchestrator.metrics()["blocked"] == 1
