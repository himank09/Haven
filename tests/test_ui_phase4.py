"""§8.5 citation chips and §8.6 Privacy Shield in the page (Playwright)."""
import time

import httpx
import pytest

from tests.fakes import keys as K
from tests.fakes.hub import ndjson_ollama, sse_openai
from tests.helpers import img_bytes, make_pdf
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


def attach(pg, path):
    with pg.expect_file_chooser() as fc:
        pg.click("#b-attach")
    fc.value.set_files(str(path))


def test_citation_chips_and_hover(pg, live, hub, tmp_path):
    f = tmp_path / "manual.pdf"
    f.write_bytes(make_pdf([f"Section {i}: maintenance schedule details for unit {i}." for i in range(1, 21)]))
    open_app(pg, live)
    attach(pg, f)
    hub["ollama"].chunks = ndjson_ollama(["Oil change is every 6 months (p. 12). Filters ", "(pp. 3–5), belts (p. 4, 7). Ignore (p. 999)."])
    send(pg, "When is the oil change?")
    wait_done(pg)
    chips = pg.locator("#thread .a .body .cite").all_inner_texts()
    assert chips == ["p. 12", "pp. 3–5", "p. 4", "p. 7"]
    assert "(p. 999)" in pg.inner_text("#thread .a .body")  # beyond the page count: plain text
    pg.hover("#thread .cite:has-text('p. 12')")
    pg.wait_for_selector(".citetip")
    tip = pg.inner_text(".citetip")
    assert tip.startswith("Page 12") and "Section 12: maintenance schedule" in tip
    pg.reload()  # chips survive a reload (page count + previews are saved with the message)
    pg.wait_for_selector("#thread .a .body .cite")
    assert pg.locator("#thread .a .body .cite").count() == 4


def cloud(live, hub):
    hub["openai"].models = {"data": [{"id": "gpt-4o"}]}
    add_key(live, K.OPENAI)


def test_shield_shows_real_values_copies_them_and_stores_them(pg, live, hub):
    cloud(live, hub)
    open_app(pg, live)
    pg.evaluate("setModel('openai:gpt-4o')")
    assert pg.is_visible("#shield") and pg.get_attribute("#shield", "aria-pressed") == "true"
    hub["openai"].chunks = sse_openai(["I'll call [PHONE_1] and mail ", "[EMAIL 1]", " today."])
    send(pg, "Remind me to call 9876543210 and email ravi@mail.co.in")
    wait_done(pg)
    body = pg.inner_text("#thread .a .body")
    assert body == "I'll call 9876543210 and mail ravi@mail.co.in today."
    assert "Privacy Shield hid 1 email address and 1 phone number before sending to OpenAI." in pg.inner_text("#thread .a .notes")
    sent = str(hub["openai"].chat_requests()[-1]["json"])
    assert "9876543210" not in sent and "ravi@mail.co.in" not in sent
    pg.click("#thread .a [data-act=copy]")
    assert pg.evaluate("navigator.clipboard.readText()") == "I'll call 9876543210 and mail ravi@mail.co.in today."
    cid = pg.evaluate("haven.conv.id")
    stored = api_get(live, f"/api/conversations/{cid}")["messages"]
    assert stored[0]["content"].startswith("Remind me to call 9876543210") and stored[1]["content"] == body
    pg.reload()
    pg.wait_for_selector("#thread .a .body")
    assert pg.inner_text("#thread .a .body") == body


def test_shield_toggle_hidden_for_local_and_persists(pg, live, hub):
    cloud(live, hub)
    open_app(pg, live)
    pg.evaluate("setModel('ollama:qwen3:4b')")
    assert pg.is_hidden("#shield")
    pg.evaluate("setModel('openai:gpt-4o')")
    pg.click("#shield")
    assert pg.get_attribute("#shield", "aria-pressed") == "false" and "off" in pg.inner_text("#shield").lower()
    time.sleep(0.2)
    assert api_get(live, "/api/settings")["shield"] is False
    hub["openai"].chunks = sse_openai(["fine"])
    send(pg, "call 9876543210")
    wait_done(pg)
    assert "Privacy Shield is off" in pg.inner_text("#thread .a .notes")
    assert "9876543210" in str(hub["openai"].chat_requests()[-1]["json"])
    pg.reload()
    pg.wait_for_selector("html[data-ready='1']")
    assert pg.get_attribute("#shield", "aria-pressed") == "false"
    pg.click("#b-gear")
    assert not pg.is_checked("#shieldtg")
    pg.check("#shieldtg")
    time.sleep(0.2)
    assert api_get(live, "/api/settings")["shield"] is True


def test_uncheckable_file_asks_once_per_conversation(pg, live, hub, tmp_path):
    cloud(live, hub)
    img = tmp_path / "id-card.jpg"
    img.write_bytes(img_bytes("JPEG", (60, 40)))
    open_app(pg, live)
    pg.evaluate("setModel('openai:gpt-4o')")
    dialogs = []

    def on_dialog(d):
        dialogs.append(d.message)
        d.accept()
    pg.on("dialog", on_dialog)
    hub["openai"].chunks = sse_openai(["An ID card."])
    attach(pg, img)
    send(pg, "What is this?")
    pg.wait_for_function("document.querySelector('#thread > .a:last-child .body')?.innerText === 'An ID card.'")
    wait_done(pg)
    assert len(dialogs) == 1 and "can't be checked for personal details" in dialogs[0]
    assert len(hub["openai"].chat_requests()) == 1
    hub["openai"].chunks = sse_openai(["Still an ID card."])
    send(pg, "And now?")
    pg.wait_for_function("document.querySelector('#thread > .a:last-child .body')?.innerText === 'Still an ID card.'")
    assert len(dialogs) == 1  # once per conversation
    pg.keyboard.press("Control+n")
    attach(pg, img)
    send(pg, "New chat, same photo")
    pg.wait_for_function("document.querySelectorAll('#thread > .a').length === 1 && !document.querySelector('#send').classList.contains('stop')")
    assert len(dialogs) == 2  # a new conversation asks again


def test_declining_keeps_the_file_on_this_pc(pg, live, hub, tmp_path):
    cloud(live, hub)
    img = tmp_path / "passport.jpg"
    img.write_bytes(img_bytes("JPEG", (60, 40)))
    open_app(pg, live)
    pg.evaluate("setModel('openai:gpt-4o')")
    pg.on("dialog", lambda d: d.dismiss())
    attach(pg, img)
    send(pg, "Read my passport")
    pg.wait_for_function("document.querySelector('#toasttxt').innerText === 'Not sent'")
    assert hub["openai"].chat_requests() == []
    assert pg.locator("#thread > *").count() == 0
    assert pg.input_value("#input") == "Read my passport"  # put back so nothing is lost
