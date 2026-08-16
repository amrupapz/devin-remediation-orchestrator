import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import WEBHOOK_SECRET
from tests.conftest import FakeDevin, FakeGitHub


@pytest.fixture
def client(monkeypatch):
    devin = FakeDevin()
    main.orchestrator.devin = devin
    main.orchestrator.github = FakeGitHub()
    monkeypatch.setattr(main.orchestrator, "start", lambda: None)
    with TestClient(main.app) as test_client:
        test_client.devin = devin
        yield test_client


def payload(number=1, labels=("devin-ready",), action="labeled", repo="amrupapz/superset"):
    return {
        "action": action,
        "repository": {"full_name": repo},
        "issue": {
            "number": number,
            "title": "Remove dead POC component",
            "body": "acceptance criteria",
            "html_url": f"https://github.com/{repo}/issues/{number}",
            "labels": [{"name": name} for name in labels],
        },
    }


def post(client, body, signature=None):
    raw = json.dumps(body).encode()
    if signature is None:
        signature = (
            "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        )
    return client.post(
        "/webhook/github",
        content=raw,
        headers={
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )


def test_valid_signature_launches_a_session(client):
    response = post(client, payload())

    assert response.status_code == 200
    assert response.json() == {"launched": True}
    assert len(client.devin.created) == 1


def test_invalid_signature_is_rejected_and_nothing_is_launched(client):
    response = post(client, payload(), signature="sha256=" + "0" * 64)

    assert response.status_code == 401
    assert client.devin.created == []


def test_missing_signature_is_rejected(client):
    raw = json.dumps(payload()).encode()
    response = client.post(
        "/webhook/github", content=raw, headers={"X-GitHub-Event": "issues"}
    )

    assert response.status_code == 401
    assert client.devin.created == []


def test_other_repository_is_ignored(client):
    response = post(client, payload(repo="someone-else/superset"))

    assert response.json() == {"ignored": True, "reason": "repository"}
    assert client.devin.created == []


def test_issue_without_the_trigger_label_is_ignored(client):
    response = post(client, payload(labels=("bug",)))

    assert response.json() == {"ignored": True, "reason": "label"}
    assert client.devin.created == []


def test_unrelated_action_is_ignored(client):
    response = post(client, payload(action="closed"))

    assert response.json() == {"ignored": True, "reason": "event"}
    assert client.devin.created == []


def test_duplicate_webhook_delivery_does_not_create_a_second_session(client):
    assert post(client, payload()).json() == {"launched": True}
    assert post(client, payload()).json() == {"launched": False}
    assert len(client.devin.created) == 1


def test_health_and_metrics_endpoints(client):
    assert client.get("/health").json()["ok"] is True

    metrics = client.get("/metrics").json()
    assert metrics["repo"] == "amrupapz/superset"
    assert metrics["trigger_label"] == "devin-ready"
    assert metrics["issues_detected"] == 0
    assert client.get("/tasks").json() == []
