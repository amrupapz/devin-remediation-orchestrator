import httpx

from app.config import (
    DRY_RUN,
    GITHUB_API_BASE,
    GITHUB_REPO,
    GITHUB_TOKEN,
    TRIGGER_LABEL,
)

_DRY_RUN_ISSUES = [
    {
        "number": 1,
        "title": "Remove the orphaned dashboard ExampleComponent POC",
        "body": "**Acceptance:** remove the unused POC component and stale comments.",
        "html_url": f"https://github.com/{GITHUB_REPO}/issues/1",
    },
    {
        "number": 2,
        "title": "Add direct tests for the useIsMobile media-query lifecycle",
        "body": "**Acceptance:** cover mount, resize and unmount paths of the hook.",
        "html_url": f"https://github.com/{GITHUB_REPO}/issues/2",
    },
]


class GitHubClient:
    def __init__(self, token: str = GITHUB_TOKEN, repo: str = GITHUB_REPO, dry_run: bool = DRY_RUN):
        self.token = token
        self.repo = repo
        self.dry_run = dry_run

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def labelled_issues(self, label: str = TRIGGER_LABEL) -> list[dict]:
        if self.dry_run:
            return _DRY_RUN_ISSUES
        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{self.repo}/issues",
            headers=self._headers,
            params={"labels": label, "state": "open", "per_page": 100},
            timeout=30,
        )
        response.raise_for_status()
        # The issues endpoint also returns pull requests; keep only real issues.
        return [i for i in response.json() if "pull_request" not in i]

    def comment(self, issue_number: int, body: str) -> None:
        if self.dry_run:
            return
        response = httpx.post(
            f"{GITHUB_API_BASE}/repos/{self.repo}/issues/{issue_number}/comments",
            headers=self._headers,
            json={"body": body},
            timeout=30,
        )
        response.raise_for_status()
