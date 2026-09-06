"""`lab.platform.webhook` — the substrate's one outbound JSON POST.

Small, and worth its own test for two reasons. It is the ONLY place the two sanctioned direct-egress
paths (an approval channel, the meeting notifier) touch the network, so its shape is the shape of
every message the lab sends outward; and it is the Azure seam — if notification ever moves behind
APIM or an Event Grid topic, this is the function that changes.

Offline: `urlopen` is replaced, so nothing leaves the machine.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_webhook.py
"""
import json

import pytest

from lab.platform import webhook


class FakeResponse:
    def __init__(self, body=b"ok"):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(webhook.urllib.request, "urlopen",
                        lambda req, timeout=None: calls.append((req, timeout)) or FakeResponse())
    return calls


def test_it_posts_json_and_returns_the_body(sent):
    assert webhook.post_json("https://flow.example/hook", {"chat_id": "19:x@thread.v2"}) == "ok"
    req, timeout = sent[0]
    assert req.method == "POST" and req.full_url == "https://flow.example/hook"
    assert json.loads(req.data) == {"chat_id": "19:x@thread.v2"}
    assert timeout == webhook.TIMEOUT_S, "a hung webhook must not hold a consumer forever"


def test_the_content_type_is_the_one_the_live_webhook_was_verified_against(sent):
    """`application/json`, bare. JSON is UTF-8 by definition, and this is what the Teams Workflows
    webhook has actually accepted — a charset parameter added here would change a working path for
    no gain."""
    webhook.post_json("https://flow.example/hook", {})
    assert sent[0][0].headers["Content-type"] == "application/json"


def test_a_failed_send_raises_so_the_caller_decides_what_it_means(monkeypatch):
    """No retry, no back-off, no queue in here. Each caller already has a policy — a channel leaves
    its stream entry unacked, the notifier records the reason and lets the reclaim retry — and a
    hidden retry would silently take that decision away from them."""
    def boom(req, timeout=None):
        raise OSError("connection refused")
    monkeypatch.setattr(webhook.urllib.request, "urlopen", boom)
    with pytest.raises(OSError):
        webhook.post_json("https://flow.example/hook", {})


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
