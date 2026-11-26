"""Collapsed sidebar rail with hover panel, Profile, styled tooltips, responsive tools row."""
import base64
import io
import json
import time

import httpx
import pytest
from PIL import Image

from haven import storage
from tests.fakes import keys as K
from tests.fakes.hub import ndjson_ollama, sse_openai
from tests.ui import H, add_key, api_get, new_page, open_app, send, wait_done

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def pg(browser, live):
    ctx, page = new_page(browser, live)
    yield page
    assert page.errors == [], page.errors
    ctx.close()


def seed_chats(n=3):
    s = storage.get()
    for i in range(n):
        c = s.create_conv(f"Chat number {i}", "")
        s.upsert_message(c["id"], {"role": "user", "content": f"hello {i}"})


def is_peek(pg):
    return pg.evaluate("document.documentElement.classList.contains('side-peek')")


# ---------------- rail + hover panel ----------------
def test_collapse_to_rail_and_hover_shows_recent_chats(pg, live, hub):
    seed_chats(3)
    open_app(pg, live)
    assert pg.is_visible("#sidein") and pg.is_hidden("#rail")
    pg.click("#b-side-close")
    pg.wait_for_selector("#rail", state="visible")
    assert pg.is_hidden("#sidein") and pg.evaluate("JSON.parse(localStorage.getItem('side'))") is False
    pg.wait_for_function("document.querySelector('#side').getBoundingClientRect().width < 70", timeout=2000)  # after the slide animation
    pg.hover("#r-recent")
    pg.wait_for_selector("#sidein", state="visible")
    assert is_peek(pg)
    assert pg.locator("#convs .conv").count() == 3
    box = pg.evaluate("(() => { const r = document.querySelector('#sidein').getBoundingClientRect(); return [r.left, r.width]; })()")
    assert box[0] > 55 and box[1] > 200  # floats next to the rail
    pg.mouse.move(900, 500)  # move away: it tucks back in
    pg.wait_for_function("!document.documentElement.classList.contains('side-peek')", timeout=2000)
    assert pg.is_hidden("#sidein")


def test_moving_from_rail_into_panel_keeps_it_open_and_click_opens_chat(pg, live, hub):
    seed_chats(2)
    open_app(pg, live)
    pg.click("#b-side-close")
    pg.hover("#r-recent")
    pg.wait_for_selector("#sidein", state="visible")
    pg.hover("#convs .conv:has-text('Chat number 1')")
    time.sleep(0.5)
    assert is_peek(pg)  # still open while the mouse is over the panel
    pg.click("#convs .conv:has-text('Chat number 1')")
    pg.wait_for_function("document.querySelector('#thread').innerText.includes('hello 1')")
    assert not is_peek(pg)  # opening a chat closes the panel


def test_rail_buttons_and_keyboard(pg, live, hub):
    seed_chats(1)
    open_app(pg, live)
    pg.click("#b-side-close")
    pg.click("#r-search")
    pg.wait_for_function("document.activeElement.id === 'cq'", timeout=2000)
    assert is_peek(pg)
    pg.keyboard.press("Escape")  # first Esc clears the search box focus behaviour; panel closes on Esc
    pg.keyboard.press("Escape")
    assert not is_peek(pg)
    pg.keyboard.press("Control+Shift+F")
    pg.wait_for_function("document.activeElement.id === 'cq'", timeout=2000)
    assert is_peek(pg)
    pg.keyboard.press("Escape"); pg.keyboard.press("Escape")
    pg.click("#r-open")  # expand for good
    pg.wait_for_selector("#rail", state="hidden")
    assert pg.is_visible("#sidein") and not is_peek(pg)
    assert pg.evaluate("JSON.parse(localStorage.getItem('side'))") is True


def test_pin_button_in_panel_expands_sidebar(pg, live, hub):
    open_app(pg, live)
    pg.click("#b-side-close")
    pg.hover("#r-recent")
    pg.wait_for_selector("#sidein", state="visible")
    pg.click("#b-side-close")  # inside the floating panel: keep the sidebar open
    pg.wait_for_selector("#rail", state="hidden")
    pg.mouse.move(900, 500)
    time.sleep(0.4)
    assert pg.is_visible("#sidein")


def test_narrow_window_still_uses_drawer_not_rail(browser, live, hub):
    ctx, pg = new_page(browser, live, 700, 600)
    open_app(pg, live)
    assert pg.is_hidden("#rail") and pg.is_visible("#b-side")
    pg.click("#b-side")
    time.sleep(0.35)
    assert pg.evaluate("document.querySelector('#side').getBoundingClientRect().left") >= -1
    ctx.close()


# ---------------- profile ----------------
def test_profile_saved_shown_and_used_in_chats(pg, live, hub):
    open_app(pg, live)
    assert "Set up your profile" in pg.inner_text("#me")
    pg.click("#me")
    pg.wait_for_selector(".tabp[data-p=profile]:not([hidden])")
    pg.fill("#pf-name", "Asha Verma")
    pg.fill("#pf-call", "Asha")
    pg.fill("#pf-about", "Engineering student. Explain maths step by step.")
    pg.click("#pf-style [data-v=concise]")
    pg.click("#pf-colors [data-h='265']")
    assert pg.inner_text("#pf-av") == "AV"
    pg.click("#pf-save")
    pg.wait_for_function("document.querySelector('#pf-msg').innerText === 'Saved'")
    p = api_get(live, "/api/profile")
    assert p["name"] == "Asha Verma" and p["call"] == "Asha" and p["style"] == "concise" and p["hue"] == 265
    assert pg.inner_text("#me-nm") == "Asha Verma" and pg.inner_text("#r-av") == "AV"
    pg.keyboard.press("Escape")
    assert pg.inner_text("#greet").upper().endswith(", ASHA")
    hub["ollama"].chunks = ndjson_ollama(["Hi Asha"])
    send(pg, "hello")
    wait_done(pg)
    sysmsg = hub["ollama"].chat_requests()[-1]["json"]["messages"][0]
    assert sysmsg["role"] == "system" and "The user's name is Asha" in sysmsg["content"]
    assert "Explain maths step by step" in sysmsg["content"] and "Keep answers short" in sysmsg["content"]


def test_profile_off_is_not_sent(pg, live, hub, client):
    client.post("/api/profile", json={"name": "Asha", "about": "secret notes", "use_in_chats": False})
    open_app(pg, live)
    hub["ollama"].chunks = ndjson_ollama(["ok"])
    send(pg, "hello")
    wait_done(pg)
    assert "Asha" not in json.dumps(hub["ollama"].chat_requests()[-1]["json"])


def test_profile_photo_upload(pg, live, hub, tmp_path):
    f = tmp_path / "me.png"
    Image.new("RGB", (900, 600), "orange").save(f)
    open_app(pg, live)
    pg.click("#me")
    with pg.expect_file_chooser() as fc:
        pg.click("#pf-photo")
    fc.value.set_files(str(f))
    pg.wait_for_selector("#pf-av img")
    pg.click("#pf-save")
    pg.wait_for_function("document.querySelector('#pf-msg').innerText === 'Saved'")
    img = api_get(live, "/api/profile")["image"]
    assert img.startswith("data:image/jpeg;base64,") and len(img) < 60_000  # resized to 256 px on this PC
    assert Image.open(io.BytesIO(base64.b64decode(img.split(",", 1)[1]))).size == (256, 256)
    assert pg.locator("#me-av img").count() == 1


def test_profile_api_validation(client):
    assert client.post("/api/profile", json={"style": "shouty"}).status_code == 400
    assert client.post("/api/profile", json={"image": "data:text/html;base64,PHNjcmlwdD4="}).status_code == 400
    assert client.post("/api/profile", json={"image": "javascript:alert(1)"}).status_code == 400
    r = client.post("/api/profile", json={"name": "x" * 500, "about": "y" * 5000})
    assert r.status_code == 200 and len(r.json()["name"]) == 60 and len(r.json()["about"]) == 1500


def test_profile_name_is_escaped(pg, live, hub, client):
    client.post("/api/profile", json={"name": '<img src=x onerror="window.__xss=1">'})
    open_app(pg, live)
    assert pg.locator("#me img, #r-av img").count() == 0
    assert pg.evaluate("window.__xss") is None


def test_profile_masked_for_cloud_with_shield(pg, live, hub, client):
    client.post("/api/profile", json={"name": "Asha", "about": "Call me on 9876543210 if needed."})
    add_key(live, K.OPENAI)
    open_app(pg, live)
    pg.evaluate("setModel('openai:openai-chat-1')")
    hub["openai"].chunks = sse_openai(["ok"])
    send(pg, "hello")
    wait_done(pg)
    sent = json.dumps(hub["openai"].chat_requests()[-1]["json"])
    assert "9876543210" not in sent and "[PHONE_1]" in sent


# ---------------- tooltips + layout ----------------
def test_styled_tooltip_replaces_native_title(pg, live, hub):
    open_app(pg, live)
    pg.hover("#b-gear")
    pg.wait_for_selector(".tip.on", timeout=2000)
    assert pg.inner_text(".tip") == "Settings"
    assert pg.get_attribute("#b-gear", "title") is None  # no plain Windows tooltip on top
    assert pg.get_attribute("#b-gear", "aria-label") == "Settings"  # still has an accessible name
    pg.mouse.move(600, 500)
    pg.wait_for_selector(".tip.on", state="detached", timeout=2000) if pg.locator(".tip.on").count() == 0 else \
        pg.wait_for_function("!document.querySelector('.tip').classList.contains('on')", timeout=2000)


def test_tools_row_is_one_line_with_more(pg, live, hub):
    open_app(pg, live)
    tops = pg.evaluate("[...document.querySelectorAll('#tiles .tile')].map(t => Math.round(t.getBoundingClientRect().top))")
    assert len(set(tops)) == 1 and len(tops) == 5
    pg.click("#tiles [data-more]")
    assert pg.is_visible("#pal.on")
