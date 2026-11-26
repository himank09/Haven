"""Image generation (Gemini "Nano Banana" models) through the real server and the fake hub."""
import json

import httpx
import pytest

from haven import images
from tests.fakes import keys as K
from tests.fakes.hub import FAKE_PNG

H = {"X-Desk-Token": "test-token"}
IMG_MODELS = {"models": [
    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"], "thinking": True},
    {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.1-flash-lite-image", "supportedGenerationMethods": ["generateContent"]},
]}


def make(live, prompt="draw a red fox", **extra):
    body = {"image": True, "model": "", "messages": [{"role": "user", "content": prompt}], **extra}
    ev = []
    with httpx.Client(timeout=30) as c, c.stream("POST", live.base + "/api/chat", json=body, headers=H) as r:
        assert r.status_code == 200, r.read()
        ev = [json.loads(ln) for ln in r.iter_lines() if ln.strip()]
    assert ev[-1].get("done") is True
    return ev


def add_gemini(live):
    r = httpx.post(live.base + "/api/providers", json={"key": K.GEMINI}, headers=H, timeout=30)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("text,yes", [
    ("draw a cat on a skateboard", True), ("Generate an image of a sunset", True),
    ("can you make me a logo for my bakery", True), ("please create a cute cartoon picture of a dog", True),
    ("what is an image file", False), ("make a plan for my week", False), ("explain how drawing tablets work", False),
])
def test_detect(text, yes):
    assert images.looks_like_image_request(text) is yes


def test_needs_gemini(live):
    ev = make(live)
    assert "Gemini key" in "".join(e.get("error", "") for e in ev)


def test_makes_and_serves_image(live, hub):
    hub["gemini"].models = IMG_MODELS
    add_gemini(live)
    ev = make(live)
    names = [e["image"] for e in ev if "image" in e]
    assert len(names) == 1 and names[0].endswith(".png")
    assert ev[-1]["model"].endswith("gemini-3.1-flash-lite-image")  # cheapest preferred model
    req = [r for r in hub["gemini"].requests if r["kind"] == "image"][-1]
    assert req["json"]["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert K.GEMINI not in json.dumps(ev)
    r = httpx.get(live.base + "/api/images/" + names[0], headers=H)
    assert r.status_code == 200 and r.content == FAKE_PNG
    assert httpx.get(live.base + "/api/images/" + names[0]).status_code == 403  # token required
    assert httpx.get(live.base + "/api/images/..%2Fsettings.json", headers=H).status_code == 404


def test_shield_masks_prompt(live, hub):
    hub["gemini"].models = IMG_MODELS
    add_gemini(live)
    make(live, "draw a poster with my email jane.doe@example.com on it")
    sent = json.dumps([r for r in hub["gemini"].requests if r["kind"] == "image"][-1]["json"])
    assert "jane.doe@example.com" not in sent


def test_quota_error_is_clear(live, hub):
    hub["gemini"].models = IMG_MODELS
    hub["gemini"].chat_status = 429
    add_gemini(live)
    err = "".join(e.get("error", "") for e in make(live))
    assert "billing" in err and K.GEMINI not in err


def test_saved_with_images(live, hub):
    hub["gemini"].models = IMG_MODELS
    add_gemini(live)
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    make(live, save={"conversation_id": cid, "message_id": "m1"})
    msgs = httpx.get(live.base + f"/api/conversations/{cid}", headers=H).json()["messages"]
    a = [m for m in msgs if m["id"] == "m1"][0]
    assert len(a["meta"]["images"]) == 1 and not a["meta"]["live"]
