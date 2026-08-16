import os

# The app reads its configuration at import time, so the test environment has
# to be in place before anything under app/ is imported.
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("DB_PATH", "/tmp/orchestrator-tests.db")
os.environ.setdefault("GITHUB_REPO", "amrupapz/superset")
os.environ.setdefault("TRIGGER_LABEL", "devin-ready")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("MAX_CONCURRENT", "3")

import pytest  # noqa: E402

from app import store  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store(tmp_path):
    """Give every test its own SQLite file."""
    store.use_database(str(tmp_path / "orchestrator.db"))
    yield
    store.use_database(str(tmp_path / "orchestrator.db"))


class FakeDevin:
    """Stands in for DevinClient with a scripted session lifecycle."""

    def __init__(self, sessions=None, create_error=None):
        self.sessions = sessions or {}
        self.create_error = create_error
        self.created: list[dict] = []

    build_prompt = staticmethod(lambda **kwargs: "prompt")

    def create_session(self, prompt, title, tags):
        if self.create_error:
            raise self.create_error
        session_id = f"devin-test-{len(self.created) + 1}"
        self.created.append({"prompt": prompt, "title": title, "tags": tags})
        return {
            "session_id": session_id,
            "url": f"https://app.devin.ai/sessions/{session_id}",
            "status": "new",
        }

    def get_session(self, session_id):
        return self.sessions[session_id]


class FakeGitHub:
    def __init__(self, issues=None, comment_error=None):
        self.issues = issues or []
        self.comment_error = comment_error
        self.comments: list[tuple[int, str]] = []

    def labelled_issues(self, label=None):
        return self.issues

    def comment(self, issue_number, body):
        if self.comment_error:
            raise self.comment_error
        self.comments.append((issue_number, body))


def issue(number: int, title: str = "Fix a thing") -> dict:
    return {
        "number": number,
        "title": title,
        "body": "acceptance criteria",
        "html_url": f"https://github.com/amrupapz/superset/issues/{number}",
    }
