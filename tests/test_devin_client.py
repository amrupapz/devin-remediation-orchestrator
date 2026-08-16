import httpx
import pytest

from app.devin import DevinClient


class Recorder:
    def __init__(self, payload=None):
        self.payload = payload or {"session_id": "devin-abc", "url": "https://app.devin.ai/x"}
        self.calls: list[dict] = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return httpx.Response(200, json=self.payload, request=httpx.Request("POST", url))


def client(**kwargs):
    defaults = dict(api_key="cog_test_key", org_id="org-test", dry_run=False, max_acu_limit=7)
    defaults.update(kwargs)
    return DevinClient(**defaults)


def test_create_session_posts_to_the_v3_organization_endpoint(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(httpx, "post", recorder)

    client().create_session(prompt="do the thing", title="Remediate #1", tags=["issue-1"])

    call = recorder.calls[0]
    assert call["url"] == "https://api.devin.ai/v3/organizations/org-test/sessions"
    assert call["headers"]["Authorization"] == "Bearer cog_test_key"
    assert call["json"]["max_acu_limit"] == 7
    assert call["json"]["idempotent"] is True
    assert call["json"]["structured_output_schema"]["required"] == [
        "status",
        "verification",
        "risk_notes",
    ]


def test_get_session_reads_the_v3_organization_endpoint(monkeypatch):
    recorder = Recorder(payload={"session_id": "devin-abc", "status": "exit"})
    monkeypatch.setattr(httpx, "get", recorder)

    session = client().get_session("devin-abc")

    assert recorder.calls[0]["url"] == (
        "https://api.devin.ai/v3/organizations/org-test/sessions/devin-abc"
    )
    assert session["status"] == "exit"


def test_live_calls_require_an_organization_id():
    with pytest.raises(RuntimeError, match="DEVIN_ORG_ID"):
        client(org_id="").create_session(prompt="p", title="t", tags=[])
    with pytest.raises(RuntimeError, match="DEVIN_ORG_ID"):
        client(org_id="").get_session("devin-abc")


def test_personal_keys_fall_back_to_the_v1_endpoint(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(httpx, "post", recorder)

    personal = client(api_key="apk_personal_key")
    assert personal.api_version == "v1"
    personal.create_session(prompt="p", title="t", tags=["issue-1"])

    call = recorder.calls[0]
    assert call["url"] == "https://api.devin.ai/v1/sessions"
    # v3-only flag must not leak into a v1 payload.
    assert "structured_output_required" not in call["json"]


def test_api_version_can_be_pinned():
    assert client(api_version="v1").api_version == "v1"
    assert client(api_key="apk_personal_key", api_version="v3").api_version == "v3"


def test_dry_run_never_calls_the_api(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("dry run must not touch the network")

    monkeypatch.setattr(httpx, "post", explode)
    monkeypatch.setattr(httpx, "get", explode)

    mock_client = DevinClient(api_key="", org_id="", dry_run=True)
    session = mock_client.create_session(prompt="p", title="t", tags=[])

    assert session["session_id"].startswith("devin-dryrun-")
    assert mock_client.get_session(session["session_id"])["status_detail"] == "working"


def test_prompt_pins_branch_base_and_issue_reference():
    prompt = DevinClient.build_prompt(
        repo="amrupapz/superset",
        number=2,
        title="Add tests",
        body="acceptance",
        base_branch="master",
    )
    assert "devin/issue-2" in prompt
    assert 'against master containing "Fixes #2"' in prompt
    assert "status=blocked" in prompt
