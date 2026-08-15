import threading
import time
from statistics import median

from app import store
from app.config import (
    BASE_BRANCH,
    GITHUB_REPO,
    HOURS_SAVED_PER_ISSUE,
    MAX_CONCURRENT,
    POLL_INTERVAL,
    TRIGGER_LABEL,
)
from app.devin import DevinClient, extract_pr_url
from app.github import GitHubClient
from app.log import event

RUNNING = "running"
DONE = "done"
BLOCKED = "blocked"
FAILED = "failed"
TERMINAL = {DONE, BLOCKED, FAILED}


class Orchestrator:
    def __init__(self, devin: DevinClient | None = None, github: GitHubClient | None = None):
        self.devin = devin or DevinClient()
        self.github = github or GitHubClient()
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # --- triggers -----------------------------------------------------

    def sync_issues(self) -> int:
        """Pick up every open trigger-labelled issue that has no session yet."""
        launched = 0
        for issue in self.github.labelled_issues():
            if self.handle_issue(issue):
                launched += 1
        return launched

    def handle_issue(self, issue: dict) -> bool:
        number = issue["number"]
        with self._lock:
            if store.get(number):
                return False
            if store.count_by_status(RUNNING) >= MAX_CONCURRENT:
                event("launch_deferred", issue=number, reason="concurrency_cap")
                return False
            store.insert(number, issue["title"], issue.get("html_url", ""), RUNNING)

        prompt = self.devin.build_prompt(
            repo=GITHUB_REPO,
            number=number,
            title=issue["title"],
            body=issue.get("body") or "",
            base_branch=BASE_BRANCH,
        )
        try:
            session = self.devin.create_session(
                prompt=prompt,
                title=f"Remediate {GITHUB_REPO}#{number}",
                tags=["remediation-orchestrator", f"issue-{number}"],
            )
        except Exception as exc:
            store.update(number, status=FAILED, error=str(exc), finished_at=time.time())
            event("launch_failed", issue=number, error=str(exc))
            return False

        store.update(
            number,
            session_id=session.get("session_id"),
            session_url=session.get("url"),
            started_at=time.time(),
        )
        event(
            "session_launched",
            issue=number,
            session_id=session.get("session_id"),
            url=session.get("url"),
        )
        return True

    # --- session tracking ---------------------------------------------

    def poll_sessions(self) -> None:
        for task in store.all_tasks():
            if task["status"] != RUNNING or not task["session_id"]:
                continue
            try:
                session = self.devin.get_session(task["session_id"])
            except Exception as exc:
                event("poll_failed", issue=task["issue_number"], error=str(exc))
                continue
            self._apply_session(task, session)

    def _apply_session(self, task: dict, session: dict) -> None:
        number = task["issue_number"]
        state = session.get("status_enum")
        if state not in {"finished", "blocked", "expired"}:
            return

        output = session.get("structured_output") or {}
        outcome = output.get("status") or ("blocked" if state == "blocked" else "unknown")
        pr_url = extract_pr_url(session)
        status = DONE if outcome == "fixed" and pr_url else BLOCKED
        if state == "expired":
            status = FAILED

        store.update(
            number,
            status=status,
            outcome=outcome,
            pr_url=pr_url,
            verification=output.get("verification"),
            risk_notes=output.get("risk_notes"),
            finished_at=time.time(),
        )
        event("session_finished", issue=number, status=status, outcome=outcome, pr_url=pr_url)
        self._comment(number, status, pr_url, task["session_url"], output)

    def _comment(self, number: int, status: str, pr_url, session_url, output: dict) -> None:
        task = store.get(number) or {}
        if task.get("commented"):
            return
        if status == DONE:
            body = (
                f"Devin opened a pull request for this issue: {pr_url}\n\n"
                f"Session: {session_url}\n\n"
                f"**Verification**\n{output.get('verification', 'n/a')}\n\n"
                f"**Reviewer notes**\n{output.get('risk_notes', 'n/a')}"
            )
        else:
            body = (
                f"Devin did not open a pull request (outcome: `{output.get('status', status)}`).\n\n"
                f"Session: {session_url}\n\n"
                f"**Reason**\n{output.get('risk_notes') or output.get('verification') or 'no detail reported'}"
            )
        try:
            self.github.comment(number, body)
            store.update(number, commented=1)
            event("issue_commented", issue=number)
        except Exception as exc:
            event("comment_failed", issue=number, error=str(exc))

    # --- metrics -------------------------------------------------------

    def metrics(self) -> dict:
        tasks = store.all_tasks()
        finished = [t for t in tasks if t["status"] in TERMINAL]
        with_pr = [t for t in tasks if t["pr_url"]]
        durations = [
            t["finished_at"] - t["started_at"]
            for t in finished
            if t["finished_at"] and t["started_at"]
        ]
        return {
            "repo": GITHUB_REPO,
            "trigger_label": TRIGGER_LABEL,
            "issues_detected": len(tasks),
            "sessions_launched": len([t for t in tasks if t["session_id"]]),
            "in_flight": len([t for t in tasks if t["status"] == RUNNING]),
            "prs_opened": len(with_pr),
            "blocked": len([t for t in tasks if t["status"] == BLOCKED]),
            "failed": len([t for t in tasks if t["status"] == FAILED]),
            "success_rate": round(100 * len(with_pr) / len(finished), 1) if finished else 0.0,
            "median_time_to_pr_seconds": round(median(durations)) if durations else None,
            "engineer_hours_saved": round(len(with_pr) * HOURS_SAVED_PER_ISSUE, 1),
            "hours_saved_assumption": HOURS_SAVED_PER_ISSUE,
        }

    # --- background loops ------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_issues()
                self.poll_sessions()
            except Exception as exc:  # keep the loop alive
                event("loop_error", error=str(exc))
            self._stop.wait(POLL_INTERVAL)
