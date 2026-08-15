import hashlib
import hmac

from app.main import actionable_issue, verify_webhook_signature


def test_webhook_hmac_accepts_only_matching_signature():
    raw = b'{"action":"labeled"}'
    secret = "test-secret"
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(raw, signature, secret)
    assert not verify_webhook_signature(raw, "sha256=bad", secret)


def test_issue_event_must_have_trigger_label():
    payload = {
        "action": "labeled",
        "issue": {"labels": [{"name": "devin-ready"}]},
    }
    assert actionable_issue(payload, "issues", "devin-ready")
    assert not actionable_issue(payload, "pull_request", "devin-ready")
    assert not actionable_issue(payload, "issues", "different-label")
