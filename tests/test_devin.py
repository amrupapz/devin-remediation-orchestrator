from app.devin import DevinClient, extract_pr_url, session_is_terminal


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class HTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return Response({"session_id": "devin-123", "url": "https://app.devin.ai/sessions/devin-123"})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return Response({"status": "running", "status_detail": "finished"})


def test_v3_create_and_get_contract():
    http = HTTP()
    client = DevinClient(
        api_key="cog_test",
        org_id="org-test",
        api_base="https://api.devin.ai/",
        max_acu=3,
        dry_run=False,
        http_client=http,
    )

    created = client.create_session("fix it", "issue 1", ["issue-1"], "owner/repo")
    client.get_session(created["session_id"])

    method, url, request = http.calls[0]
    assert method == "POST"
    assert url == "https://api.devin.ai/v3/organizations/org-test/sessions"
    assert request["json"]["repos"] == ["https://github.com/owner/repo"]
    assert request["json"]["structured_output_required"] is True
    assert request["json"]["max_acu_limit"] == 3
    assert http.calls[1][1].endswith("/v3/organizations/org-test/sessions/devin-123")


def test_v3_finished_state_and_pull_request_shape():
    session = {
        "status": "running",
        "status_detail": "finished",
        "pull_requests": [{"pr_url": "https://github.com/owner/repo/pull/7"}],
    }
    assert session_is_terminal(session)
    assert extract_pr_url(session) == "https://github.com/owner/repo/pull/7"


def test_live_mode_requires_service_user_and_org():
    try:
        DevinClient(api_key="", org_id="", dry_run=False)
    except ValueError as exc:
        assert "DEVIN_API_KEY and DEVIN_ORG_ID" in str(exc)
    else:
        raise AssertionError("missing live credentials must fail closed")
