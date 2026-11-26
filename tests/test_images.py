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


def services(live, **body):
    r = httpx.post(live.base + "/api/image-services", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def errors(ev):
    return "".join(e.get("error", "") for e in ev)


def notes(ev):
    return " ".join(e.get("note", "") for e in ev)


def test_no_service_set_up(live, hub):
    services(live, pollinations=False)
    ev = make(live)
    assert "Settings" in errors(ev) and "Images" in errors(ev)
    assert hub.img_requests == []


def test_pollinations_needs_no_account(live, hub):
    ev = make(live, "draw a red fox in the snow")
    assert [e for e in ev if "image" in e] and not errors(ev)
    assert ev[-1]["model"] == "images:pollinations" and "Pollinations" in notes(ev)
    assert [r["svc"] for r in hub.img_requests] == ["poll"]
    assert "red%20fox" in hub.img_requests[0]["path"] or "red fox" in hub.img_requests[0]["path"]


def test_hugging_face_token_used_first(live, hub, test_home):
    st = services(live, hf_token="hf_FAKEtoken1234567890")
    assert st["services"]["hf"]["saved"] and st["services"]["hf"]["hint"].endswith("7890")
    assert "hf_FAKEtoken1234567890" not in json.dumps(st)
    ev = make(live)
    assert ev[-1]["model"] == "images:hf"
    req = hub.img_requests[-1]
    assert req["svc"] == "hf" and req["headers"]["authorization"] == "Bearer hf_FAKEtoken1234567890"
    assert req["json"]["inputs"] == "draw a red fox"
    assert "hf_FAKEtoken1234567890" not in (test_home / "Haven" / "settings.json").read_text(encoding="utf-8")
    assert "hf_FAKEtoken1234567890" not in json.dumps(ev)


def test_cloudflare(live, hub):
    assert httpx.post(live.base + "/api/image-services", json={"cf_account": "not-an-id"}, headers=H).status_code == 400
    services(live, cf_account="0123456789abcdef0123456789abcdef", cf_token="cfFAKEtoken000999", service="cf")
    ev = make(live)
    assert ev[-1]["model"] == "images:cf" and [e for e in ev if "image" in e]
    assert "/0123456789abcdef0123456789abcdef/" in hub.img_requests[-1]["path"]
    assert hub.img_requests[-1]["json"]["prompt"] == "draw a red fox"


def test_falls_back_when_allowance_is_used_up(live, hub):
    services(live, hf_token="hf_FAKEtoken1234567890")
    hub.img_status["hf"] = 402  # no credits
    ev = make(live)
    assert "Hugging Face" in notes(ev) and "Trying Pollinations" in notes(ev)
    assert ev[-1]["model"] == "images:pollinations" and not errors(ev)


def test_all_services_fail(live, hub):
    hub.img_status["poll"] = 503
    ev = make(live)
    assert errors(ev) and not [e for e in ev if "image" in e]


def test_pinned_service_is_the_only_one(live, hub):
    services(live, service="hf")
    ev = make(live)  # Hugging Face picked but no token saved: nothing usable, no silent fallback
    assert "Settings" in errors(ev) and hub.img_requests == []


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
    services(live, service="pollinations")
    make(live, "draw a poster with my email jane.doe@example.com on it")
    assert "jane.doe" not in json.dumps(hub.img_requests[-1])


def test_quota_error_is_clear(live, hub):
    hub["gemini"].models = IMG_MODELS
    hub["gemini"].chat_status = 429
    add_gemini(live)
    services(live, pollinations=False)
    err = errors(make(live))
    assert "billing" in err and K.GEMINI not in err
    services(live, pollinations=True)  # free fallback after Gemini says no
    ev = make(live)
    assert "billing" in notes(ev) and ev[-1]["model"] == "images:pollinations"


def test_saved_with_images(live, hub):
    hub["gemini"].models = IMG_MODELS
    add_gemini(live)
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    make(live, save={"conversation_id": cid, "message_id": "m1"})
    msgs = httpx.get(live.base + f"/api/conversations/{cid}", headers=H).json()["messages"]
    a = [m for m in msgs if m["id"] == "m1"][0]
    assert len(a["meta"]["images"]) == 1 and not a["meta"]["live"]
