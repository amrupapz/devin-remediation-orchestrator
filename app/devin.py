import time
import uuid
from typing import Any, Optional

import httpx

from app.config import (
    DEVIN_API_BASE,
    DEVIN_API_KEY,
    DEVIN_API_VERSION,
    DEVIN_DRY_RUN_SECONDS,
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

# Real artifacts from the live run, so the credential-free demo shows the same
# links a reviewer can open on GitHub.
DRY_RUN_ARTIFACTS = {
    "1": {
        "session_url": "https://app.devin.ai/sessions/d6e49f1b5aba47cd916d5cdafca769ed",
        "pr_url": "https://github.com/amrupapz/superset/pull/3",
        "verification": "Frontend pre-commit checks passed; focused Jest suite passed 6/6 tests.",
        "risk_notes": "Deletion only; confirm no downstream plugin imports the POC module.",
    },
    "2": {
        "session_url": "https://app.devin.ai/sessions/e3177eecf75c4fac8f39d0e3459ab4a9",
        "pr_url": "https://github.com/amrupapz/superset/pull/4",
        "verification": "Focused useIsMobile Jest suite passed 5/5 tests; lint and type checks passed.",
        "risk_notes": "Test-only change; review the MediaQueryList double and breakpoint assertion.",
    },
}


class DevinClient:
    """Client for the Devin session endpoints the orchestrator needs.

    Talks to `/v3/organizations/{org_id}/sessions` when authenticated as a
    service user (`cog_` key with an organization id), and to `/v1/sessions`
    with a personal key, which has no access to the organization endpoints.
    """

    def __init__(
        self,
        api_key: str = DEVIN_API_KEY,
        org_id: str = DEVIN_ORG_ID,
        api_base: str = DEVIN_API_BASE,
        dry_run: bool = DRY_RUN,
        max_acu_limit: int = MAX_ACU_PER_SESSION,
        dry_run_seconds: float = DEVIN_DRY_RUN_SECONDS,
        http_client: Any = httpx,
        api_version: str = DEVIN_API_VERSION,
    ):
        self.api_key = api_key
        self.org_id = org_id
        self.api_base = api_base.rstrip("/")
        self.dry_run = dry_run
        self.api_version = self._resolve_version(api_version, api_key)
        self.max_acu_limit = max_acu_limit
        self.dry_run_seconds = dry_run_seconds
        self.http = http_client
        self._fake: dict[str, dict] = {}

        if not dry_run and not api_key:
            raise ValueError("DEVIN_API_KEY and DEVIN_ORG_ID are required when DRY_RUN=false")

    @staticmethod
    def _resolve_version(requested: str, api_key: str) -> str:
        """Personal keys (`apk_`) can only use v1; service users use v3."""
        requested = (requested or "auto").lower()
        if requested in {"v1", "v3"}:
            return requested
        return "v1" if api_key.startswith("apk_") else "v3"

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    @property
    def _sessions_url(self) -> str:
        if self.api_version == "v1":
            return f"{self.api_base}/v1/sessions"
        if not self.org_id:
            raise RuntimeError("DEVIN_ORG_ID is required for live Devin v3 calls")
        return f"{self.api_base}/v3/organizations/{self.org_id}/sessions"

    @staticmethod
    def build_prompt(repo: str, number: int, title: str, body: str, base_branch: str) -> str:
        return PROMPT_TEMPLATE.format(
            repo=repo,
            number=number,
            title=title,
            body=(body or "").strip(),
            base_branch=base_branch,
        )

    def create_session(self, prompt: str, title: str, tags: list[str], repo: str = "") -> dict:
        if self.dry_run:
            session_id = f"devin-dryrun-{uuid.uuid4().hex[:12]}"
            issue_tag = next((tag for tag in tags if tag.startswith("issue-")), "issue-1")
            issue_number = issue_tag.removeprefix("issue-")
            artifact = DRY_RUN_ARTIFACTS.get(issue_number, {})
            self._fake[session_id] = {
                "created": time.time(),
                "issue_number": issue_number,
                "pr_url": artifact.get(
                    "pr_url", f"https://github.com/{repo}/pull/{issue_number}"
                ),
                "verification": artifact.get(
                    "verification", "Focused formatting, lint, type, and test checks passed."
                ),
                "risk_notes": artifact.get(
                    "risk_notes", "Review the generated change before merging."
                ),
            }
            return {
                "session_id": session_id,
                "url": artifact.get(
                    "session_url", f"https://app.devin.ai/sessions/{session_id}"
                ),
                "status": "new",
                "acus_consumed": 0,
            }
        payload = {
            "prompt": prompt,
            "title": title,
            "tags": tags,
            "idempotent": True,
            "max_acu_limit": self.max_acu_limit,
            "structured_output_schema": STRUCTURED_OUTPUT_SCHEMA,
        }
        if self.api_version == "v3":
            payload["structured_output_required"] = True
        if repo:
            payload["repos"] = [f"https://github.com/{repo}"]
        response = self.http.post(
            self._sessions_url,
            headers=self._headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def get_session(self, session_id: str) -> dict:
        if self.dry_run:
            return self._fake_progress(session_id)
        response = self.http.get(
            f"{self._sessions_url}/{session_id}",
            headers=self._headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def _fake_progress(self, session_id: str) -> dict:
        """Canned v3-shaped lifecycle so the pipeline runs without credentials."""
        fake = self._fake.setdefault(
            session_id,
            {
                "created": time.time(),
                "issue_number": "1",
                "pr_url": DRY_RUN_ARTIFACTS["1"]["pr_url"],
                "verification": DRY_RUN_ARTIFACTS["1"]["verification"],
                "risk_notes": DRY_RUN_ARTIFACTS["1"]["risk_notes"],
            },
        )
        elapsed = time.time() - fake["created"]
        if elapsed < self.dry_run_seconds:
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
            "pull_requests": [{"pr_state": "open", "pr_url": fake["pr_url"]}],
            "acus_consumed": 1.25,
            "structured_output": {
                "status": "fixed",
                "pr_url": fake["pr_url"],
                "verification": fake["verification"],
                "risk_notes": fake["risk_notes"],
            },
        }


def is_settled(session: dict) -> bool:
    """True when a session will do no further work on its own.

    Handles both shapes: v1 reports `status_enum`, v3 reports
    `status` plus `status_detail`.
    """
    if session.get("status_enum") in {"finished", "blocked", "expired", "stopped"}:
        return True
    status = session.get("status")
    if status in ERROR_STATES or status in {"exit", "suspended"}:
        return True
    if status in RUNNING_STATES:
        return session.get("status_detail") == FINISHED_DETAIL
    return False


# Kept as the name main's suite imports; the semantics are identical.


def extract_pr_url(session: dict) -> Optional[str]:
    """Prefer the PRs Devin actually opened; fall back to structured output."""
    for pr in session.get("pull_requests") or []:
        url = pr.get("pr_url") or pr.get("url")
        if url:
            return url
    output = session.get("structured_output") or {}
    if output.get("pr_url"):
        return output["pr_url"]
    pull_request = session.get("pull_request") or {}
    return pull_request.get("url")


def session_terminal_state(session: dict) -> str:
    status = session.get("status")
    if status == "suspended" or session.get("status_enum") == "blocked":
        return "blocked"
    if status in {"error"} or session.get("status_enum") == "expired":
        return "failed"
    return "finished"
