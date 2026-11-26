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


def pics(ev):
    return [e["image"] for e in ev if "image" in e]


def retry(ev):
    return next((e["retry"] for e in ev if "retry" in e), None)


def options(live):
    return httpx.get(live.base + "/api/image-models", headers=H).json()["options"]


def test_options_list_every_model(live, hub):
    hub["gemini"].models = IMG_MODELS
    add_gemini(live)
    opts = {o["id"]: o for o in options(live)}
    assert list(opts)[:3] == ["hfspace", "cf", "pollinations"]  # free ones first
    assert opts["hfspace"]["free"] and opts["hfspace"]["ready"]
    assert not opts["cf"]["ready"] and "Cloudflare" in opts["cf"]["setup"]
    assert opts["gemini:gemini-3.1-flash-lite-image"]["label"] == "Nano Banana 2 Lite"
    assert opts["gemini:gemini-3.1-flash-lite-image"]["free"] is False
    assert not opts["hf"]["ready"]


def test_automatic_uses_free_space_first(live, hub):
    ev = make(live, "draw a red fox in the snow")
    assert pics(ev) and not errors(ev) and ev[-1]["model"] == "images:hfspace"
    assert [r["svc"] for r in hub.img_requests if r["path"].endswith("/call/infer")] == ["space"]
    r = httpx.get(live.base + "/api/images/" + pics(ev)[0], headers=H)
    assert r.status_code == 200 and r.content == FAKE_PNG
    assert httpx.get(live.base + "/api/images/" + pics(ev)[0]).status_code == 403  # token required
    assert httpx.get(live.base + "/api/images/..%2Fsettings.json", headers=H).status_code == 404


def test_automatic_moves_on_quietly(live, hub):
    hub.img_status["space"] = 429  # today's free GPU time used up
    hub["gemini"].models = IMG_MODELS
    hub["gemini"].chat_status = 429
    add_gemini(live)
    ev = make(live)
    assert ev[-1]["model"] == "images:pollinations" and pics(ev) and not errors(ev)
    assert "Gemini" not in notes(ev) and "quota" not in notes(ev).lower() and "billing" not in notes(ev)


def test_space_sends_token_when_saved(live, hub):
    services(live, hf_token="hf_FAKEtoken1234567890")
    make(live)
    call = [r for r in hub.img_requests if r["path"].endswith("/call/infer")][-1]
    assert call["headers"]["authorization"] == "Bearer hf_FAKEtoken1234567890"
    assert call["json"]["data"][0] == "draw a red fox"


def test_no_option_ready(live, hub):
    hub.img_status["space"] = 503
    services(live, pollinations=False)
    ev = make(live)
    assert errors(ev) and not pics(ev) and retry(ev) == []


def test_chosen_model_failing_offers_the_others(live, hub):
    hub["gemini"].models = IMG_MODELS
    hub["gemini"].chat_status = 429
    add_gemini(live)
    ev = make(live, image_model="gemini:gemini-3.1-flash-lite-image")
    err = errors(ev)
    assert err.startswith("Couldn't make the picture with Nano Banana 2 Lite") and K.GEMINI not in err
    assert not pics(ev)
    assert retry(ev)[:2] == ["hfspace", "pollinations"] and "gemini:gemini-3.1-flash-lite-image" not in retry(ev)
    assert [r for r in hub.img_requests] == []  # only the chosen model was tried


def test_chosen_model_not_set_up(live, hub):
    ev = make(live, image_model="hf")
    assert "Hugging Face token" in errors(ev) and "hfspace" in retry(ev) and hub.img_requests == []


def test_pick_each_free_model(live, hub):
    services(live, cf_account="0123456789abcdef0123456789abcdef", cf_token="cfFAKEtoken000999")
    for oid, svc in (("cf", "cf"), ("pollinations", "poll"), ("hfspace", "space")):
        ev = make(live, image_model=oid)
        assert pics(ev) and ev[-1]["model"] == f"images:{oid}", oid
        assert hub.img_requests[-1]["svc"] == svc
    assert httpx.post(live.base + "/api/image-services", json={"cf_account": "nope"}, headers=H).status_code == 400
    cf = [r for r in hub.img_requests if r["svc"] == "cf"][-1]
    assert "/0123456789abcdef0123456789abcdef/" in cf["path"] and cf["json"]["prompt"] == "draw a red fox"


def test_hugging_face_paid_route(live, hub, test_home):
    st = services(live, hf_token="hf_FAKEtoken1234567890")
    assert st["services"]["hf"]["saved"] and st["services"]["hf"]["hint"].endswith("7890")
    ev = make(live, image_model="hf")
    assert ev[-1]["model"] == "images:hf" and hub.img_requests[-1]["json"]["inputs"] == "draw a red fox"
    hub.img_status["hf"] = 402
    assert "credits" in errors(make(live, image_model="hf"))
    for f in (test_home / "Haven").glob("*.json"):
        assert "hf_FAKEtoken1234567890" not in f.read_text(encoding="utf-8")


def test_gemini_chosen(live, hub):
    hub["gemini"].models = IMG_MODELS
    add_gemini(live)
    ev = make(live, image_model="gemini:gemini-2.5-flash-image")
    assert pics(ev) and ev[-1]["model"].endswith("gemini-2.5-flash-image")
    req = [r for r in hub["gemini"].requests if r["kind"] == "image"][-1]
    assert req["json"]["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert "gemini-2.5-flash-image" in req["path"]


def test_shield_masks_prompt(live, hub):
    make(live, "draw a poster with my email jane.doe@example.com on it")
    assert "jane.doe" not in json.dumps(hub.img_requests)


def test_saved_with_images_and_retry(live, hub):
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    make(live, save={"conversation_id": cid, "message_id": "m1"})
    hub.img_status["space"] = 503
    make(live, image_model="hfspace", save={"conversation_id": cid, "message_id": "m2"})
    msgs = {m["id"]: m for m in httpx.get(live.base + f"/api/conversations/{cid}", headers=H).json()["messages"]}
    assert len(msgs["m1"]["meta"]["images"]) == 1 and not msgs["m1"]["meta"]["live"]
    assert msgs["m2"]["meta"]["retry"] == ["pollinations"] and msgs["m2"]["meta"]["error"]
