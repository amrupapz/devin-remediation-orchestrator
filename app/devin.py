import time
import uuid
from typing import Optional

import httpx

from app.config import DEVIN_API_BASE, DEVIN_API_KEY, DRY_RUN

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

    def __init__(self, api_key: str = DEVIN_API_KEY, dry_run: bool = DRY_RUN):
        self.api_key = api_key
        self.dry_run = dry_run
        self._fake: dict[str, dict] = {}

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

    def create_session(self, prompt: str, title: str, tags: list[str]) -> dict:
        if self.dry_run:
            session_id = f"devin-dryrun-{uuid.uuid4().hex[:12]}"
            self._fake[session_id] = {"created": time.time()}
            return {
                "session_id": session_id,
                "url": f"https://app.devin.ai/sessions/{session_id}",
            }
        response = httpx.post(
            f"{DEVIN_API_BASE}/v1/sessions",
            headers=self._headers,
            json={
                "prompt": prompt,
                "title": title,
                "tags": tags,
                "idempotent": True,
                "structured_output_schema": STRUCTURED_OUTPUT_SCHEMA,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def get_session(self, session_id: str) -> dict:
        if self.dry_run:
            return self._fake_progress(session_id)
        response = httpx.get(
            f"{DEVIN_API_BASE}/v1/sessions/{session_id}",
            headers=self._headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def _fake_progress(self, session_id: str) -> dict:
        """Canned lifecycle so the whole pipeline is runnable without credentials."""
        started = self._fake.setdefault(session_id, {"created": time.time()})["created"]
        elapsed = time.time() - started
        if elapsed < 20:
            return {"session_id": session_id, "status_enum": "working"}
        blocked = int(session_id[-1], 16) % 4 == 0
        if blocked:
            return {
                "session_id": session_id,
                "status_enum": "finished",
                "structured_output": {
                    "status": "blocked",
                    "pr_url": None,
                    "verification": "Inspected the referenced module; no lint run.",
                    "risk_notes": "Acceptance criteria conflict with live usage; needs a human decision.",
                },
            }
        return {
            "session_id": session_id,
            "status_enum": "finished",
            "pull_request": {"url": "https://github.com/example/superset/pull/1"},
            "structured_output": {
                "status": "fixed",
                "pr_url": "https://github.com/example/superset/pull/1",
                "verification": "npx prettier --check <files>; npx tsc --noEmit; jest <suite> -> all passed",
                "risk_notes": "Deletion only; confirm no downstream plugin imports the module.",
            },
        }


def extract_pr_url(session: dict) -> Optional[str]:
    output = session.get("structured_output") or {}
    pr_url = output.get("pr_url")
    if pr_url:
        return pr_url
    pull_request = session.get("pull_request") or {}
    return pull_request.get("url")
