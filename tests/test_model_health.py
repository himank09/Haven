"""Real-world provider failures (seen with a free-tier Gemini key, 2026-11-26): clear messages, one retry
when a model is overloaded, failing models marked in /api/models, popular models listed first."""
import json

import httpx
import pytest

from haven.providers import registry
from tests.fakes import keys as K
from tests.fakes.hub import sse_gemini

H = {"X-Desk-Token": "test-token"}
BUSY = '{"error": {"code": 503, "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.", "status": "UNAVAILABLE"}}'
QUOTA = '{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.", "status": "RESOURCE_EXHAUSTED"}}'
RETIRED = '{"error": {"code": 404, "message": "This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.8-flash.", "status": "NOT_FOUND"}}'
MODELS = {"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"], "thinking": True}
                     for n in ("gemini-3.8-flash", "gemini-2.5-flash", "gemini-4-hydrogen", "gemini-3.5-flash-lite", "gemini-4-carbon")]}


@pytest.fixture
def gem(live, hub, monkeypatch):
    from haven import chat

    monkeypatch.setattr(chat, "RETRY_BUSY_AFTER", 0.05)
    registry.HEALTH.clear()
    hub["gemini"].models = MODELS
    assert httpx.post(live.base + "/api/providers", json={"key": K.GEMINI}, headers=H, timeout=30).status_code == 200
    return hub["gemini"]


def chat_once(live, model):
    ev = []
    with httpx.Client(timeout=30) as c:
        with c.stream("POST", live.base + "/api/chat", json={"model": model, "messages": [{"role": "user", "content": "hello"}]}, headers=H) as r:
            for ln in r.iter_lines():
                if ln.strip():
                    ev.append(json.loads(ln))
    return ev


def models(live):
    return {m["id"]: m for m in httpx.get(live.base + "/api/models", headers=H).json()["models"] if m["provider"] == "gemini"}


def test_overloaded_model_is_retried_once_then_answers(live, gem):
    calls = {"n": 0}

    def reject(body):
        calls["n"] += 1
        return (503, BUSY) if calls["n"] == 1 else None
    gem.reject_if = reject
    gem.chunks = sse_gemini(["Hi there!"])
    ev = chat_once(live, "gemini:gemini-3.8-flash")
    assert "".join(e.get("content", "") for e in ev) == "Hi there!"
    assert any("trying once more" in e.get("note", "") for e in ev)
    assert not any("error" in e for e in ev) and calls["n"] == 2


def test_still_overloaded_says_so_and_marks_model(live, gem):
    gem.chat_status, gem.chat_body = 503, BUSY
    ev = chat_once(live, "gemini:gemini-3.8-flash")
    err = [e["error"] for e in ev if "error" in e]
    assert err == ["Provider error: gemini-3.8-flash is overloaded right now (Google Gemini reports high demand). "
                   "Try again in a minute, or pick another model."]
    assert len(gem.chat_requests()) == 2  # one automatic retry, no more
    assert models(live)["gemini-3.8-flash"]["issue"] == "busy right now"


def test_free_plan_quota_message(live, gem):
    gem.chat_status, gem.chat_body = 429, QUOTA
    err = [e["error"] for e in chat_once(live, "gemini:gemini-4-carbon") if "error" in e]
    assert err == ["gemini-4-carbon isn't included in your Google Gemini plan (quota exceeded). Pick another model, or check billing with Google Gemini."]
    assert len(gem.chat_requests()) == 1  # quota: no pointless retry
    assert models(live)["gemini-4-carbon"]["issue"] == "not on your plan"


def test_rate_limit_without_quota_wording_unchanged(live, gem):
    gem.chat_status, gem.chat_headers = 429, {"retry-after": "7"}
    err = [e["error"] for e in chat_once(live, "gemini:gemini-3.8-flash") if "error" in e]
    assert err == ["Rate limited, try again in 7s."]


def test_retired_model_message(live, gem):
    gem.chat_status, gem.chat_body = 404, RETIRED
    err = [e["error"] for e in chat_once(live, "gemini:gemini-2.5-flash") if "error" in e]
    assert err[0].startswith("Model not available on this key: Google Gemini has retired gemini-2.5-flash for new keys.")
    assert models(live)["gemini-2.5-flash"]["issue"] == "retired"


def test_success_clears_the_mark(live, gem):
    gem.chat_status, gem.chat_body = 503, BUSY
    chat_once(live, "gemini:gemini-3.8-flash")
    assert models(live)["gemini-3.8-flash"]["issue"]
    gem.chat_status, gem.chat_body = 200, ""
    gem.chunks = sse_gemini(["ok"])
    chat_once(live, "gemini:gemini-3.8-flash")
    assert models(live)["gemini-3.8-flash"]["issue"] == ""


def test_popular_models_listed_first(live, gem):
    ids = list(models(live))
    # catalog order for Gemini: 4 Carbon, 4 Hydrogen, (4 Argon not offered), 3.5 Flash-Lite; then the rest as listed
    assert ids[:3] == ["gemini-4-carbon", "gemini-4-hydrogen", "gemini-3.5-flash-lite"]
    assert set(ids[3:]) == {"gemini-3.8-flash", "gemini-2.5-flash"}
    ms = models(live)
    assert ms["gemini-4-carbon"]["popular"] and not ms["gemini-3.8-flash"]["popular"]


def test_add_a_model_by_name(live, gem, client):
    r = client.patch("/api/providers/gemini", json={"extra_models": ["gemini-exp-9999"]})
    assert r.status_code == 200 and r.json()["extra_models"] == ["gemini-exp-9999"]
    assert "gemini-exp-9999" in models(live)
    assert [p for p in client.get("/api/providers").json()["providers"] if p["id"] == "gemini"][0]["extra_models"] == ["gemini-exp-9999"]
