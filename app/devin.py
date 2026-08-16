import time
import uuid
from typing import Optional

import httpx

from app.config import (
    DEVIN_API_BASE,
    DEVIN_API_KEY,
    DEVIN_ORG_ID,
    DRY_RUN,
    MAX_ACU_PER_SESSION,
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

# v3 `status` values. A session is only settled once it leaves the running set.
RUNNING_STATES = {"new", "claimed", "running", "resuming"}
FINISHED_DETAIL = "finished"
ERROR_STATES = {"error"}


class DevinClient:
    """Client for the Devin v3 session endpoints the orchestrator needs.

    Authenticates as a service user (`cog_` key) against
    `/v3/organizations/{org_id}/sessions`.
    """

    def __init__(
        self,
        api_key: str = DEVIN_API_KEY,
        org_id: str = DEVIN_ORG_ID,
        dry_run: bool = DRY_RUN,
        max_acu_limit: int = MAX_ACU_PER_SESSION,
    ):
        self.api_key = api_key
        self.org_id = org_id
        self.dry_run = dry_run
        self.max_acu_limit = max_acu_limit
        self._fake: dict[str, dict] = {}

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    @property
    def _sessions_url(self) -> str:
        return f"{DEVIN_API_BASE}/v3/organizations/{self.org_id}/sessions"

    @staticmethod
    def build_prompt(repo: str, number: int, title: str, body: str, base_branch: str) -> str:
        return PROMPT_TEMPLATE.format(
            repo=repo,
            number=number,
            title=title,
            body=(body or "").strip(),
            base_branch=base_branch,
        )

    def create_session(self, prompt: str, title: str, tags: list[str]) -> dict:
        if self.dry_run:
            session_id = f"devin-dryrun-{uuid.uuid4().hex[:12]}"
            self._fake[session_id] = {"created": time.time()}
            return {
                "session_id": session_id,
                "url": f"https://app.devin.ai/sessions/{session_id}",
                "status": "new",
                "acus_consumed": 0,
            }
        if not self.org_id:
            raise RuntimeError("DEVIN_ORG_ID is required for live Devin v3 calls")
        response = httpx.post(
            self._sessions_url,
            headers=self._headers,
            json={
                "prompt": prompt,
                "title": title,
                "tags": tags,
                "idempotent": True,
                "max_acu_limit": self.max_acu_limit,
                "structured_output_schema": STRUCTURED_OUTPUT_SCHEMA,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def get_session(self, session_id: str) -> dict:
        if self.dry_run:
            return self._fake_progress(session_id)
        if not self.org_id:
            raise RuntimeError("DEVIN_ORG_ID is required for live Devin v3 calls")
        response = httpx.get(
            f"{self._sessions_url}/{session_id}",
            headers=self._headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def _fake_progress(self, session_id: str) -> dict:
        """Canned v3-shaped lifecycle so the pipeline runs without credentials."""
        started = self._fake.setdefault(session_id, {"created": time.time()})["created"]
        elapsed = time.time() - started
        if elapsed < 20:
            return {
                "session_id": session_id,
                "status": "running",
                "status_detail": "working",
                "pull_requests": [],
                "acus_consumed": 0.4,
            }
        blocked = int(session_id[-1], 16) % 4 == 0
        if blocked:
            return {
                "session_id": session_id,
                "status": "running",
                "status_detail": FINISHED_DETAIL,
                "pull_requests": [],
                "acus_consumed": 1.1,
                "structured_output": {
                    "status": "blocked",
                    "pr_url": None,
                    "verification": "Inspected the referenced module; no lint run.",
                    "risk_notes": "Acceptance criteria conflict with live usage; needs a human decision.",
                },
            }
        return {
            "session_id": session_id,
            "status": "exit",
            "status_detail": FINISHED_DETAIL,
            "pull_requests": [
                {"pr_url": "https://github.com/example/superset/pull/1", "pr_state": "open"}
            ],
            "acus_consumed": 2.6,
            "structured_output": {
                "status": "fixed",
                "pr_url": "https://github.com/example/superset/pull/1",
                "verification": "npx oxfmt --check <files>; pre-commit run; jest <suite> -> all passed",
                "risk_notes": "Deletion only; confirm no downstream plugin imports the module.",
            },
        }


def is_settled(session: dict) -> bool:
    """True when a v3 session will do no further work on its own."""
    status = session.get("status")
    if status in ERROR_STATES or status in {"exit", "suspended"}:
        return True
    if status in RUNNING_STATES:
        return session.get("status_detail") == FINISHED_DETAIL
    return False


def extract_pr_url(session: dict) -> Optional[str]:
    """Prefer the PRs Devin actually opened; fall back to structured output."""
    for pr in session.get("pull_requests") or []:
        url = pr.get("pr_url") or pr.get("url")
        if url:
            return url
    output = session.get("structured_output") or {}
    pr_url = output.get("pr_url")
    return pr_url or None
