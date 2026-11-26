"""§8.7 Chat UI and §8.8 security, with Playwright (Chromium) against the real server and fake providers."""
import json
import time

import httpx
import pytest

from haven import storage
from tests.fakes import keys as K
from tests.fakes.hub import ndjson_ollama, sse_openai
from tests.ui import (CONTRAST_JS, H, api_get, add_key, last_answer, new_page, open_app, send, wait_done, wait_until)

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


def say(hub, *pieces, delay=0.0):
    hub["ollama"].chunks = ndjson_ollama(list(pieces))
    hub["ollama"].delay = delay
    hub["ollama"].infinite = None


# ---------------- send / copy / regenerate / edit ----------------
def test_send_stream_copy_regenerate_edit(pg, live, hub):
    open_app(pg, live)
    assert "qwen3:4b" in pg.inner_text("#pill") and "Private" in pg.inner_text("#pill")
    say(hub, "Here is **bold** text\n\n", "- item one\n", "- item two", delay=0.05)
    send(pg, "first question")
    pg.wait_for_selector("#send.stop")                         # streaming visible
    pg.wait_for_selector("#thread > .a:last-child .body strong")
    wait_done(pg)
    assert "item two" in last_answer(pg)
    assert pg.evaluate("document.activeElement.id") == "input"  # focus kept after sending
    # Copy copies the exact markdown source
    pg.click("#thread > .a:last-child [data-act=copy]")
    clip = pg.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")  # Windows stores \r\n on the clipboard
    assert clip == "Here is **bold** text\n\n- item one\n- item two"
    # Regenerate replaces the last answer
    say(hub, "A different answer")
    pg.click("#thread > .a:last-child [data-act=regen]")
    pg.wait_for_function("document.querySelector('#thread > .a:last-child .body')?.innerText === 'A different answer'")
    wait_done(pg)
    assert pg.locator("#thread > .a").count() == 1
    cid = pg.evaluate("haven.conv.id")
    msgs = api_get(live, f"/api/conversations/{cid}")["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["content"] == "A different answer"
    # Edit truncates and resends
    say(hub, "second reply")
    send(pg, "second question")
    wait_done(pg)
    say(hub, "edited reply")
    pg.hover("#thread > .uwrap:nth-child(1)")
    pg.click("#thread > .uwrap:nth-child(1) [data-act=edit]")
    assert pg.input_value("#input") == "first question" and pg.is_visible("#editing")
    pg.fill("#input", "first question, edited")
    pg.keyboard.press("Enter")
    pg.wait_for_function("document.querySelector('#thread > .a:last-child .body')?.innerText === 'edited reply'")
    wait_done(pg)
    texts = pg.locator("#thread > *").all_inner_texts()
    assert len(texts) == 2 and "first question, edited" in texts[0] and "edited reply" in texts[1]
    msgs = api_get(live, f"/api/conversations/{cid}")["messages"]
    assert [m["content"] for m in msgs] == ["first question, edited", "edited reply"]


def test_stop_mid_stream(pg, live, hub):
    open_app(pg, live)
    hub["ollama"].infinite = lambda i: ndjson_ollama([f"tok{i} "])[0]
    hub["ollama"].delay = 0.03
    send(pg, "go on forever")
    pg.wait_for_function("(document.querySelector('#thread > .a:last-child .body') || {}).innerText?.includes('tok3')")
    t = pg.evaluate("""() => new Promise(res => { const t0 = performance.now(); document.querySelector('#send').click();
        const check = () => { const b = document.querySelector('#send');
          if (!b.classList.contains('stop')) res(performance.now() - t0); else requestAnimationFrame(check); }; check(); })""")
    assert t < 100, t
    pg.fill("#input", "usable")
    assert pg.input_value("#input") == "usable"
    assert "Stopped" in pg.inner_text("#thread > .a:last-child .tools")
    cid = pg.evaluate("haven.conv.id")
    m = wait_until(lambda: (lambda ms: ms[-1] if ms and ms[-1]["meta"].get("stopped") else None)(api_get(live, f"/api/conversations/{cid}")["messages"]))
    assert m and m["content"].startswith("tok0 tok1 tok2 tok3")


def test_keyboard_shortcuts(pg, live, hub):
    open_app(pg, live)
    say(hub, "ok")
    pg.focus("#input")
    pg.keyboard.type("line one")
    pg.keyboard.press("Shift+Enter")
    pg.keyboard.type("line two")
    assert pg.input_value("#input") == "line one\nline two"
    pg.keyboard.press("Enter")
    wait_done(pg)
    assert pg.inner_text("#thread .u") == "line one\nline two"
    assert pg.evaluate("document.activeElement.id") == "input"
    # Up in an empty composer edits the last message
    pg.keyboard.press("ArrowUp")
    assert pg.input_value("#input") == "line one\nline two" and pg.is_visible("#editing")
    pg.keyboard.press("Escape")  # cancels the edit
    assert not pg.is_visible("#editing")
    # Esc stops generation
    hub["ollama"].infinite = lambda i: ndjson_ollama([f"x{i} "])[0]
    hub["ollama"].delay = 0.03
    send(pg, "stream please")
    pg.wait_for_selector("#send.stop")
    pg.wait_for_function("document.querySelector('#thread > .a:last-child .body')?.innerText.includes('x2')")
    pg.keyboard.press("Escape")
    pg.wait_for_selector("#send:not(.stop)")
    # Ctrl+K tools, Ctrl+M models, Ctrl+N new chat
    pg.keyboard.press("Control+k")
    assert pg.is_visible("#pal.on")
    pg.keyboard.press("Escape")
    pg.keyboard.press("Control+m")
    assert pg.is_visible("#picker") and pg.evaluate("document.activeElement.id") == "pq"
    pg.keyboard.press("Escape")
    assert not pg.is_visible("#picker")
    pg.keyboard.press("Control+n")
    assert pg.locator("#thread > *").count() == 0 and pg.evaluate("document.activeElement.id") == "input"
    pg.keyboard.press("Control+Shift+F")
    assert pg.evaluate("document.activeElement.id") == "cq"


def test_model_picker_groups_badges_and_switch(pg, live, hub):
    hub["openai"].models = {"data": [{"id": "gpt-4o"}, {"id": "o4-mini"}]}
    add_key(live, K.OPENAI)
    open_app(pg, live)
    pg.click("#pill")
    groups = pg.locator("#pl .grp").all_inner_texts()
    assert any("ollama" in g.lower() for g in groups) and any("openai" in g.lower() for g in groups)
    row = pg.locator("#pl li.m", has_text="gpt-4o")
    assert "Cloud" in row.inner_text() and row.locator("svg").count() >= 1  # vision icon
    assert "Private" in pg.locator("#pl li.m", has_text="qwen3:4b").inner_text()
    pg.fill("#pq", "o4")
    assert pg.locator("#pl li.m").count() == 1
    pg.keyboard.press("Enter")
    assert "o4-mini" in pg.inner_text("#pill") and "Cloud" in pg.inner_text("#pill")
    assert "OpenAI" in pg.inner_text("#foottxt")
    assert pg.is_visible("#think")  # reasoning model: Think shown
    pg.keyboard.press("Control+m")
    assert pg.locator("#pl .grp").first.inner_text().lower() == "recent"
    assert "o4-mini" in pg.locator("#pl li.m").first.inner_text()  # last used model on top
    pg.fill("#pq", "gpt-4o")
    pg.keyboard.press("Enter")
    assert pg.is_hidden("#think")  # model can't think: toggle hidden


def test_switch_model_mid_chat_and_deleted_provider(pg, live, hub):
    hub["openai"].models = {"data": [{"id": "gpt-4o"}]}
    add_key(live, K.OPENAI)
    open_app(pg, live)
    say(hub, "local answer")
    send(pg, "hi")
    wait_done(pg)
    pg.evaluate("setModel('openai:gpt-4o')")
    hub["openai"].chunks = sse_openai(["cloud answer"])
    send(pg, "and now?")
    wait_done(pg)
    assert last_answer(pg) == "cloud answer"
    hist = hub["openai"].chat_requests()[-1]["json"]["messages"]
    assert [m["content"] for m in hist if m["role"] != "system"] == ["hi", "local answer", "and now?"]
    # delete the provider while this chat uses it
    httpx.delete(live.base + "/api/providers/openai", headers=H)
    pg.evaluate("refreshModels()")
    pg.wait_for_selector("#notice:not([hidden])")
    assert "Model no longer available, pick another" in pg.inner_text("#notice")
    send(pg, "still there?")
    pg.wait_for_selector("#picker:not([hidden])")  # asks for a model instead of crashing


# ---------------- sidebar ----------------
def test_sidebar_new_switch_rename_delete_undo_search(pg, live, hub):
    open_app(pg, live)
    say(hub, "about apples")
    send(pg, "Tell me about apples")
    wait_done(pg)
    pg.click("#b-new2")
    say(hub, "Bananas are berries. The word zanzibar appears here.")
    send(pg, "And bananas?")
    wait_done(pg)
    items = pg.locator("#convs .conv")
    assert items.count() == 2 and "And bananas?" in items.nth(0).inner_text()
    assert pg.locator("#convs .grp").first.inner_text().lower() == "today"
    # switch
    pg.click("#convs .conv:has-text('Tell me about apples')")
    pg.wait_for_function("document.querySelector('#thread').innerText.includes('about apples')")
    # rename
    pg.hover("#convs .conv:has-text('Tell me about apples')")
    pg.click("#convs .conv:has-text('Tell me about apples') .menu")
    pg.click(".popmenu [data-a=rename]")
    pg.fill("#convs input", "Fruit notes")
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#convs .conv:has-text('Fruit notes')")
    assert any(c["title"] == "Fruit notes" for c in api_get(live, "/api/conversations")["conversations"])
    # search finds text inside messages
    pg.fill("#cq", "zanzibar")
    pg.wait_for_function("document.querySelector('#convs').innerText.includes('And bananas?')")
    assert pg.locator("#convs .conv").count() == 1
    pg.fill("#cq", "")
    # delete + undo
    pg.click("#convs .conv:has-text('Fruit notes') .menu")
    pg.click(".popmenu [data-a=delete]")
    assert pg.locator("#convs .conv").count() == 1
    pg.click("#toastbtn")
    pg.wait_for_selector("#convs .conv:has-text('Fruit notes')")
    time.sleep(5.3)
    assert len(api_get(live, "/api/conversations")["conversations"]) == 2  # undo really kept it
    # delete for real
    pg.click("#convs .conv:has-text('Fruit notes') .menu")
    pg.click(".popmenu [data-a=delete]")
    wait_until(lambda: len(api_get(live, "/api/conversations")["conversations"]) == 1, timeout=7)
    assert len(api_get(live, "/api/conversations")["conversations"]) == 1


def test_switching_chats_during_streaming_never_writes_into_the_wrong_chat(pg, live, hub):
    """Design: a stream keeps running in the background for its own chat; switching away only stops painting it."""
    open_app(pg, live)
    say(hub, "B answer")
    send(pg, "chat B")
    wait_done(pg)
    pg.click("#b-new2")
    say(hub, *[f"A{i} " for i in range(40)], delay=0.03)
    send(pg, "chat A")
    pg.wait_for_function("document.querySelector('#thread > .a:last-child .body')?.innerText.includes('A3')")
    a_id = pg.evaluate("haven.conv.id")
    pg.click("#convs .conv:has-text('chat B')")
    pg.wait_for_function("document.querySelector('#thread').innerText.includes('B answer')")
    assert pg.locator("#convs .conv:has-text('chat A') .live").count() == 1  # still answering in the background
    time.sleep(1.5)
    assert "A3" not in pg.inner_text("#thread")
    assert pg.locator("#thread > *").count() == 2
    pg.wait_for_function("!document.querySelector('#convs .live')", timeout=10000)
    pg.click("#convs .conv:has-text('chat A')")
    pg.wait_for_function("document.querySelector('#thread').innerText.includes('A39')")
    msgs = api_get(live, f"/api/conversations/{a_id}")["messages"]
    assert msgs[-1]["content"] == "".join(f"A{i} " for i in range(40))


def test_reload_restores_list_and_current_chat(pg, live, hub):
    open_app(pg, live)
    say(hub, "## Heading\n\nfirst answer")
    send(pg, "one")
    wait_done(pg)
    pg.click("#b-new2")
    say(hub, "second answer")
    send(pg, "two")
    wait_done(pg)
    before_thread = pg.inner_html("#thread .msg.a .body")
    before_side = pg.inner_text("#convs")
    pg.reload()
    pg.wait_for_selector("html[data-ready='1']")
    pg.wait_for_function("document.querySelectorAll('#thread > *').length === 2")
    assert pg.inner_text("#convs") == before_side
    assert pg.inner_html("#thread .msg.a .body") == before_thread
    assert pg.inner_text("#thread .u") == "two"


def test_thread6_migration_imports_once(pg, live, hub):
    pg.goto(live.base + "/?t=test-token")
    pg.wait_for_selector("html[data-ready='1']")
    old = [{"r": "u", "text": "old question"}, {"r": "a", "text": "old **answer**", "info": "qwen · 2.0s"},
           {"r": "u", "text": "Compress, balanced", "files": ["a.pdf"], "tool": 1},
           {"r": "f", "act": "compress", "state": "done", "title": "a_compressed.pdf", "sub": "<div class='sz'><b>120 KB</b></div>"}]
    pg.evaluate("t => { localStorage.setItem('thread6', JSON.stringify(t)); localStorage.removeItem('migrated6'); }", old)
    pg.reload()
    pg.wait_for_selector("html[data-ready='1']")
    convs = api_get(live, "/api/conversations")["conversations"]
    assert [c["title"] for c in convs] == ["Earlier chats"]
    assert pg.evaluate("localStorage.getItem('thread6')") is None
    msgs = api_get(live, f"/api/conversations/{convs[0]['id']}")["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "tool"]
    assert msgs[3]["meta"]["subText"] == "120 KB"
    pg.reload()
    pg.wait_for_selector("html[data-ready='1']")
    assert len(api_get(live, "/api/conversations")["conversations"]) == 1  # only once
    pg.click("#convs .conv")
    pg.wait_for_function("document.querySelector('#thread').innerText.includes('old answer')")
    assert pg.locator("#thread .card").count() == 1


def test_auto_scroll_follows_only_at_bottom(pg, live, hub):
    pg.set_viewport_size({"width": 1000, "height": 600})
    open_app(pg, live)
    say(hub, *[f"Line {i}\n\n" for i in range(120)], delay=0.03)
    send(pg, "long one")
    pg.wait_for_function("document.querySelector('#thread > .a:last-child .body')?.innerText.includes('Line 30')")
    at_bottom = "(() => { const s = document.querySelector('#scroll'); return Math.abs(s.scrollHeight - s.scrollTop - s.clientHeight) < 90; })()"
    assert pg.evaluate(at_bottom)                  # follows while at the bottom
    assert pg.is_hidden("#tobottom")
    pg.evaluate("document.querySelector('#scroll').scrollTop = 0")
    time.sleep(0.6)
    assert pg.evaluate("document.querySelector('#scroll').scrollTop") < 50  # scrolled up: stays put
    assert pg.is_visible("#tobottom")
    pg.click("#tobottom")
    time.sleep(0.4)
    assert pg.evaluate(at_bottom)
    wait_done(pg, 20000)


def test_empty_state_no_models_shows_onboarding(pg, live, hub, monkeypatch):
    monkeypatch.setenv("HAVEN_BASE_OLLAMA", "http://127.0.0.1:9")
    monkeypatch.setenv("HAVEN_BASE_LMSTUDIO", "http://127.0.0.1:9/v1")
    open_app(pg, live)
    assert pg.is_visible("#onboard")
    assert "Start Ollama" in pg.inner_text("#onboard")
    for b in ("#ob-key", "#ob-ollama", "#ob-retry"):
        assert pg.is_enabled(b)
    pg.click("#ob-ollama")
    assert pg.evaluate("window.__opened") == ["https://ollama.com/download"]
    pg.click("#ob-key")
    pg.wait_for_selector("#sheet.on")
    pg.wait_for_function("document.activeElement.id === 'nkey'", timeout=2000)
    assert pg.is_visible("#tiles")  # file tools still there


def test_empty_state_chips_depend_on_files(pg, live, hub, tmp_path):
    from tests.helpers import make_pdf

    open_app(pg, live)
    assert "Explain something simply" in pg.inner_text("#chips")
    f = tmp_path / "notes.pdf"
    f.write_bytes(make_pdf(["hello"]))
    with pg.expect_file_chooser() as fc:
        pg.click("#b-attach")
    fc.value.set_files(str(f))
    pg.wait_for_function("document.querySelector('#chips').innerText.includes('Summarise this')")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_contrast_of_key_text(browser, live, hub, scheme):
    ctx, pg = new_page(browser, live, scheme=scheme)
    open_app(pg, live)
    say(hub, "Answer text with `code` and a [link](https://example.com).")
    send(pg, "question")
    wait_done(pg)
    pg.hover("#thread > .a")
    sels = ["#thread .u", "#thread .a .body p", "#thread .a .meta", "#thread .a .chipbtn", "#convs .conv .t", "#convs .grp",
            "#pillname", "#foottxt", ".newchat", "#cq", "#input"]
    bad = [r for s in sels for r in pg.evaluate(CONTRAST_JS, s) if r["ratio"] < 4.5]
    ctx.close()
    assert bad == [], bad


@pytest.mark.parametrize("w,h", [(800, 600), (1920, 1080)])
def test_layout_sizes_no_overflow(browser, live, hub, w, h):
    ctx, pg = new_page(browser, live, w, h)
    open_app(pg, live)
    say(hub, "A " * 400 + "\n\n```\n" + "x" * 500 + "\n```")
    send(pg, "q " * 50)
    wait_done(pg)
    over = pg.evaluate("""() => { const W = innerWidth, out = [];
        for (const s of ['.top', '#pill', '#composer', '#thread', '.dock', '#b-gear']) { const r = document.querySelector(s).getBoundingClientRect();
          if (r.right > W + 1 || r.left < -1) out.push([s, r.left, r.right, W]); }
        if (document.documentElement.scrollWidth > W) out.push(['doc', document.documentElement.scrollWidth]);
        return out; }""")
    side = pg.evaluate("document.querySelector('#side').getBoundingClientRect().right")
    if w < 900:
        assert side <= 0  # collapsed into a drawer
        pg.click("#b-side")
        time.sleep(0.4)
        assert pg.evaluate("document.querySelector('#side').getBoundingClientRect().left") >= -1
    else:
        assert side > 200
    ctx.close()
    assert over == [], over


def test_file_tool_from_new_layout(pg, live, hub, tmp_path):
    from tests.helpers import image_pdf

    open_app(pg, live)
    f = tmp_path / "scan.pdf"
    f.write_bytes(image_pdf(800, 600))
    with pg.expect_file_chooser() as fc:
        pg.click("#b-attach")
    fc.value.set_files(str(f))
    pg.click("#acts .act[data-a=compress]")
    pg.click("#pgo")
    pg.wait_for_selector("#thread .card.done", timeout=30000)
    assert "smaller" in pg.inner_text("#thread .card .sub")
    cid = pg.evaluate("haven.conv.id")
    msgs = api_get(live, f"/api/conversations/{cid}")["messages"]
    assert [m["role"] for m in msgs] == ["user", "tool"] and msgs[1]["meta"]["state"] == "done"
    assert msgs[0]["meta"]["files"][0]["name"] == "scan.pdf" and "data" not in json.dumps(msgs[0]["meta"])  # names only, no bytes
    pg.reload()
    pg.wait_for_selector("#thread .card.done")  # tool cards persist like messages


# ---------------- §8.8 security: markdown is untrusted ----------------
XSS = [
    "<script>window.__xss=1</script>",
    '<img src=x onerror="window.__xss=1">',
    "[click](javascript:window.__xss=1)",
    "[x](data:text/html,<script>window.__xss=1</script>)",
    '<iframe src="javascript:window.__xss=1"></iframe><iframe srcdoc="<script>parent.__xss=1</script>"></iframe>',
    '<svg onload="window.__xss=1"><circle r=5 /></svg>',
    '<a href="file:///C:/">local file</a> and [file](file:///C:/Windows)',
    '<div style="background:url(https://evil.example/x.png)">css</div> <style>body{background:url(https://evil.example/y)}</style>',
    "![tracker](https://evil.example/pixel.png)",
    "<a href=\"https://evil.example\" onclick=\"window.__xss=1\">x</a>",
    "`<img src=x onerror=window.__xss=1>` and ```\n<script>window.__xss=1</script>\n```",
    "[**bold `x` link**](javascript:alert(1))",
]


@pytest.mark.parametrize("payload", XSS)
def test_untrusted_markdown_never_runs_or_loads(pg, live, hub, payload):
    open_app(pg, live)
    say(hub, payload)
    send(pg, "show me")
    wait_done(pg)
    time.sleep(0.2)
    for el in pg.locator("#thread .body a, #thread .body .lnk").all():
        el.click()
    time.sleep(0.2)
    assert pg.evaluate("window.__xss") is None
    assert pg.locator("#thread .body script, #thread .body iframe, #thread .body img, #thread .body svg:not(.i), #thread .body style, #thread .body [style]").count() == 0
    assert pg.locator("#thread .body [onerror], #thread .body [onload], #thread .body [onclick], #thread .body [href]").count() == 0
    outside = [u for u in pg.requests if not u.startswith(live.base) and not u.startswith("data:")]
    assert outside == []
    # a user clicking a https link the model printed may open it in the browser; nothing else may ever open
    assert all(u.startswith("https://") for u in pg.evaluate("window.__opened"))


def test_links_https_open_on_click_http_not(pg, live, hub):
    open_app(pg, live)
    say(hub, "See [secure](https://example.com/a?b=1) and [plain](http://example.com/insecure) and https://auto.example.org/x")
    send(pg, "links")
    wait_done(pg)
    assert pg.evaluate("window.__opened") == []  # nothing opens by itself
    pg.click("#thread .body .lnk:has-text('secure')")
    assert pg.evaluate("window.__opened") == ["https://example.com/a?b=1"]
    pg.click("#thread .body .lnk-http")
    assert pg.evaluate("window.__opened") == ["https://example.com/a?b=1"]
    assert "http://example.com/insecure" in pg.inner_text("#thread .body")
    pg.click("#thread .body .lnk:has-text('auto.example.org')")
    assert pg.evaluate("window.__opened")[-1] == "https://auto.example.org/x"


def test_markdown_features_render(pg, live, hub):
    open_app(pg, live)
    md = ("# H1\n## H2\n\n**b** *i* ~~s~~ `c`\n\n- a\n  - nested\n- b\n\n1. one\n2. two\n\n> quote\n\n"
          "| x | y |\n|---|:-:|\n| 1 | 2 |\n\n---\n\n```python\nprint('hi')\n```\n")
    say(hub, md)
    send(pg, "md")
    wait_done(pg)
    b = "#thread .a .body"
    for sel in ("h1", "h2", "strong", "em", "del", "code", "ul ul li", "ol li", "blockquote", "table td", "hr", ".code .code-h"):
        assert pg.locator(f"{b} {sel}").count() >= 1, sel
    assert pg.inner_text(f"{b} .code-h span") == "python"
    pg.click(f"{b} .code .cp")
    assert pg.evaluate("navigator.clipboard.readText()") == "print('hi')"


def test_incomplete_markdown_mid_stream_does_not_throw(pg, live, hub):
    open_app(pg, live)
    pieces = ["Start\n\n```py\nfor i in range(3):\n", "    print(i)\n", "| a | b |\n|--", "-|---|\n| 1 |", " 2 |\n``", "`\n\n**bo", "ld** end"]
    say(hub, *pieces, delay=0.05)
    send(pg, "partial")
    wait_done(pg)
    assert pg.locator("#thread .a .body .code").count() == 1 and "bold end" in last_answer(pg)


def test_huge_single_line_wraps_without_freezing(pg, live, hub):
    open_app(pg, live)
    big = "x" * 1_000_000
    hub["ollama"].chunks = ndjson_ollama([big[i:i + 50_000] for i in range(0, len(big), 50_000)])
    t0 = time.monotonic()
    send(pg, "huge")
    wait_done(pg, 30000)
    took = time.monotonic() - t0
    t1 = time.monotonic()
    assert pg.evaluate("1 + 1") == 2
    responsive = time.monotonic() - t1
    over = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
    print(f"\n1 MB single line: rendered in {took:.2f}s, page answered in {responsive * 1000:.0f} ms")
    assert over <= 0 and responsive < 1 and took < 15


def test_html_in_conversation_title_is_escaped(pg, live, hub):
    open_app(pg, live)
    say(hub, "ok")
    send(pg, '<img src=x onerror="window.__xss=1"><b>bold?</b>')
    wait_done(pg)
    t = pg.inner_text("#convs .conv .t")
    assert t.startswith("<img src=x") and pg.locator("#convs img, #convs b").count() == 0
    assert pg.evaluate("window.__xss") is None


def test_other_pages_cannot_use_the_api(browser, live):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("data:text/html,<p>evil page</p>")
    res = page.evaluate("""async (base) => { try { const r = await fetch(base + '/api/status'); return 'status ' + r.status; }
                           catch (e) { return 'blocked'; } }""", live.base)
    ctx.close()
    assert res in ("blocked", "status 403")
    assert httpx.get(live.base + "/api/conversations").status_code == 403
    r = httpx.options(live.base + "/api/conversations", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_page_has_a_strict_content_security_policy(live):
    html = httpx.get(live.base + "/").text
    assert "Content-Security-Policy" in html
    csp = html.split('Content-Security-Policy" content="')[1].split('"')[0]
    for d in ("default-src 'self'", "connect-src 'self'", "frame-src 'none'", "object-src 'none'"):
        assert d in csp
    assert "unsafe-eval" not in csp and "http" not in csp
