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
    assert chips == ["12", "3–5", "4", "7"]
    assert "(p. 999)" in pg.inner_text("#thread .a .body")  # beyond the page count: plain text
    pg.hover("#thread .cite[data-p='12']")
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
    pg.click(".dlg .tab[data-tab=privacy]")
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


# ---------------- popular-model catalog, provider cards, add a model by name ----------------
def test_locked_popular_model_explains_and_unlocks_after_adding_key(pg, live, hub):
    hub["openai"].models = {"data": [{"id": "gpt-6.2-sol"}, {"id": "gpt-6.2-astra"}, {"id": "gpt-4o"}, {"id": "o4-mini"}]}
    open_app(pg, live)
    pg.click("#pill")
    locked = pg.locator("#pl li.m.locked", has_text="GPT-6.2 Sol")
    assert locked.count() == 1 and "Everyday default" in locked.inner_text()
    locked.click()
    pg.wait_for_selector("#notice:not([hidden])")
    assert "GPT-6.2 Sol needs an OpenAI API key" in pg.inner_text("#notice")
    assert "NEEDS KEY" in pg.inner_text("#pill").upper()
    send(pg, "hello")  # nothing is sent while the model is locked
    assert pg.locator("#thread > *").count() == 0 and hub["openai"].chat_requests() == []
    pg.click("#noticebtn")  # -> Settings, OpenAI card, key field open
    pg.wait_for_selector(".pform[data-form=openai]:not([hidden])")
    assert pg.evaluate("document.activeElement.dataset.f") == "key"
    pg.fill(".pform[data-form=openai] [data-f=key]", K.OPENAI)
    pg.click(".pform[data-form=openai] [data-save]")
    pg.wait_for_selector(".pcard[data-kind=openai] .stat.ok")
    assert "Connected" in pg.inner_text(".pcard[data-kind=openai]")
    assert K.OPENAI not in pg.content()
    pg.wait_for_function("document.querySelector('#pill').innerText.toUpperCase().includes('CLOUD')")
    assert "GPT-6.2 Sol" in pg.inner_text("#pill")  # the model you picked is now unlocked and selected
    pg.keyboard.press("Escape")
    pg.click("#pill")
    rows = pg.locator("#pl li.m:not(.locked)").all_inner_texts()
    openai_rows = [r for r in rows if "gpt" in r.lower() or "o4" in r]
    assert openai_rows[0].startswith("GPT-6.2 Sol") and openai_rows[1].startswith("GPT-6.2 Astra")  # everyday model first, friendly names
    assert "More OpenAI models" in pg.inner_text("#pl")
    assert pg.locator("#pl li.m.locked", has_text="GPT-6.2").count() == 0


def test_add_a_model_by_name(pg, live, hub):
    add_key(live, K.OPENAI)
    open_app(pg, live)
    pg.click("#pill")
    pg.click("#pl [data-addmodel=openai]")
    pg.wait_for_selector(".xm[data-xm=openai] .xform:not([hidden])")
    pg.fill(".xm[data-xm=openai] [data-xin]", "my-finetune-v2")
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".xm[data-xm=openai] .xchip:has-text('my-finetune-v2')")
    pg.wait_for_function("document.querySelector('#pill').innerText.includes('my-finetune-v2')", timeout=3000)
    hub["openai"].chunks = sse_openai(["custom model here"])
    pg.keyboard.press("Escape")
    send(pg, "hi")
    wait_done(pg)
    assert hub["openai"].chat_requests()[-1]["json"]["model"] == "my-finetune-v2"


def test_failing_model_is_marked_in_picker(pg, live, hub, monkeypatch):
    from haven import chat
    from haven.providers import registry

    monkeypatch.setattr(chat, "RETRY_BUSY_AFTER", 0.05)
    registry.HEALTH.clear()
    hub["openai"].models = {"data": [{"id": "gpt-6.2-sol"}, {"id": "gpt-6-luna"}]}
    add_key(live, K.OPENAI)
    open_app(pg, live)
    pg.evaluate("setModel('openai:gpt-6.2-sol')")
    hub["openai"].chat_status = 503
    hub["openai"].chat_body = '{"error": {"message": "This model is currently experiencing high demand."}}'
    send(pg, "hello")
    wait_done(pg)
    assert "overloaded right now" in pg.inner_text("#thread .a .body")
    pg.click("#pill")
    pg.wait_for_function("[...document.querySelectorAll('#pl li.m')].some(li => li.innerText.includes('gpt-6.2-sol') && li.innerText.includes('busy right now'))", timeout=3000)
    registry.HEALTH.clear()



def test_fresh_window_defaults_to_free_plan_gemini_and_lists_it_above_ollama(browser, live, hub, monkeypatch):
    """Seen on a real free-tier key: the first popular Gemini model used to be a paid-only one."""
    monkeypatch.setenv("HAVEN_BASE_OLLAMA", "http://127.0.0.1:9")     # Ollama not running
    monkeypatch.setenv("HAVEN_BASE_LMSTUDIO", "http://127.0.0.1:9/v1")
    hub["gemini"].models = {"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"], "thinking": True}
                                       for n in ("gemini-3.8-flash", "gemini-4-carbon", "gemini-4-hydrogen", "gemini-3.5-flash-lite")]}
    add_key(live, K.GEMINI)
    ctx, page = new_page(browser, live)  # fresh window: no remembered model
    open_app(page, live)
    assert "Gemini 3.5 Flash-Lite" in page.inner_text("#pill")
    page.click("#pill")
    groups = [g.splitlines()[0].lower() for g in page.locator("#pl .grp").all_inner_texts()]
    assert groups.index("google gemini") < groups.index("ollama")  # connected provider before download suggestions
    first = page.locator("#pl li.m").first.inner_text()
    assert first.startswith("Gemini 3.5 Flash-Lite")
    ctx.close()
