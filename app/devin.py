import time
import uuid
from typing import Any, Optional

import httpx

from app.config import (
    DEVIN_API_BASE,
    DEVIN_API_KEY,
    DEVIN_DRY_RUN_SECONDS,
    DEVIN_MAX_ACU,
    DEVIN_ORG_ID,
    DRY_RUN,
)

STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "pr_url": {
            "type": ["string", "null"],
            "description": "URL of the pull request opened, or null if none",
        },
        "status": {
            "type": "string",
            "enum": ["fixed", "blocked", "not_applicable"],
            "description": "Outcome of the remediation attempt",
        },
        "verification": {
            "type": "string",
            "description": "Exact commands run and their results",
        },
        "risk_notes": {
            "type": "string",
            "description": "What a human reviewer must check before merging",
        },
    },
    "required": ["status", "verification", "risk_notes"],
    "additionalProperties": False,
}

PROMPT_TEMPLATE = """Repository: https://github.com/{repo}
Resolve issue #{number}: {title}

{body}

Requirements:
- Work on branch: devin/issue-{number}
- Make the minimal change that satisfies the acceptance criteria; do not
  refactor or clean up anything outside the stated scope.
- Run the narrowest relevant lint / type / test checks for the touched code
  and record the exact commands and their output.
- Open a pull request against {base_branch} containing "Fixes #{number}" and
  the verification commands with their results.
- If the change is unsafe, or the acceptance criteria are wrong or already
  satisfied, do NOT force a pull request: report status=blocked (or
  not_applicable) with the reason instead.
"""


class DevinClient:
    """Minimal client for the two Devin API calls the orchestrator needs."""

    def __init__(
        self,
        api_key: str = DEVIN_API_KEY,
        org_id: str = DEVIN_ORG_ID,
        api_base: str = DEVIN_API_BASE,
        max_acu: int = DEVIN_MAX_ACU,
        dry_run: bool = DRY_RUN,
        dry_run_seconds: float = DEVIN_DRY_RUN_SECONDS,
        http_client: Any = httpx,
    ):
        self.api_key = api_key
        self.org_id = org_id
        self.api_base = api_base.rstrip("/")
        self.max_acu = max_acu
        self.dry_run = dry_run
        self.dry_run_seconds = dry_run_seconds
        self.http = http_client
        self._fake: dict[str, dict] = {}

        if not dry_run and (not api_key or not org_id):
            raise ValueError("DEVIN_API_KEY and DEVIN_ORG_ID are required when DRY_RUN=false")

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def build_prompt(repo: str, number: int, title: str, body: str, base_branch: str) -> str:
        return PROMPT_TEMPLATE.format(
            repo=repo,
            number=number,
            title=title,
            body=(body or "").strip(),
            base_branch=base_branch,
        )

    def create_session(self, prompt: str, title: str, tags: list[str], repo: str) -> dict:
        if self.dry_run:
            session_id = f"devin-dryrun-{uuid.uuid4().hex[:12]}"
            issue_tag = next((tag for tag in tags if tag.startswith("issue-")), "issue-1")
            self._fake[session_id] = {
                "created": time.time(),
                "pr_number": issue_tag.removeprefix("issue-"),
            }
            return {
                "session_id": session_id,
                "url": f"https://app.devin.ai/sessions/{session_id}",
            }
        response = self.http.post(
            f"{self.api_base}/v3/organizations/{self.org_id}/sessions",
            headers=self._headers,
            json={
                "prompt": prompt,
                "title": title,
                "tags": tags,
                "repos": [f"https://github.com/{repo}"],
                "max_acu_limit": self.max_acu,
                "structured_output_required": True,
                "structured_output_schema": STRUCTURED_OUTPUT_SCHEMA,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def get_session(self, session_id: str) -> dict:
        if self.dry_run:
            return self._fake_progress(session_id)
        response = self.http.get(
            f"{self.api_base}/v3/organizations/{self.org_id}/sessions/{session_id}",
            headers=self._headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def _fake_progress(self, session_id: str) -> dict:
        """Canned lifecycle so the whole pipeline is runnable without credentials."""
        fake = self._fake.setdefault(session_id, {"created": time.time(), "pr_number": "1"})
        started = fake["created"]
        elapsed = time.time() - started
        if elapsed < self.dry_run_seconds:
            return {"session_id": session_id, "status": "running", "status_detail": "working"}
        return {
            "session_id": session_id,
            "status": "running",
            "status_detail": "finished",
            "pull_requests": [{"pr_state": "open", "pr_url": f"https://github.com/example/superset/pull/{fake['pr_number']}"}],
            "acus_consumed": 1.25,
            "structured_output": {
                "status": "fixed",
                "pr_url": f"https://github.com/example/superset/pull/{fake['pr_number']}",
                "verification": "npx prettier --check <files>; npx tsc --noEmit; jest <suite> -> all passed",
                "risk_notes": "Deletion only; confirm no downstream plugin imports the module.",
            },
        }


def extract_pr_url(session: dict) -> Optional[str]:
    output = session.get("structured_output") or {}
    pr_url = output.get("pr_url")
    if pr_url:
        return pr_url
    pull_requests = session.get("pull_requests") or []
    if pull_requests:
        return pull_requests[0].get("pr_url")
    pull_request = session.get("pull_request") or {}
    return pull_request.get("url")


def session_is_terminal(session: dict) -> bool:
    """Support v3 and legacy fixtures while callers migrate."""
    if session.get("status_enum") in {"finished", "blocked", "expired"}:
        return True
    status = session.get("status")
    return status in {"error", "suspended", "exit"} or (
        status == "running" and session.get("status_detail") == "finished"
    )


def session_terminal_state(session: dict) -> str:
    status = session.get("status")
    if status == "suspended" or session.get("status_enum") == "blocked":
        return "blocked"
    if status in {"error", "exit"} or session.get("status_enum") == "expired":
        return "failed"
    return "finished"
