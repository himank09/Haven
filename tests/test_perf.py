"""§8.9 Performance budgets, measured (fail if exceeded). Numbers are printed so the final report can quote them.

Run on this machine only; a slower laptop will give different numbers. Each test says exactly what it measures.
"""
import json
import statistics
import time

import httpx
import psutil
import pytest

from haven import storage
from tests.fakes import keys as K
from tests.fakes.hub import ndjson_ollama, sse_openai
from tests.ui import H, add_key, new_page, open_app, send, wait_done

pytestmark = [pytest.mark.ui, pytest.mark.slow]
RESULTS = {}


def report(name, value):
    RESULTS[name] = value
    print(f"\n[perf] {name}: {value}")


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--js-flags=--expose-gc", "--enable-precise-memory-info"])
        yield b
        b.close()


@pytest.fixture
def pg(browser, live):
    ctx, page = new_page(browser, live)
    yield page
    assert page.errors == [], page.errors
    ctx.close()


def test_page_interactive_after_server_ready(pg, live, hub):
    """From navigation start to the app being usable (models + chats loaded). Budget 1.5 s."""
    times = []
    for _ in range(3):
        pg.goto(live.base + "/?t=test-token")
        pg.wait_for_selector("html[data-ready='1']")
        times.append(int(pg.evaluate("document.documentElement.dataset.readyAt")))
    report("server ready -> page interactive (ms, worst of 3)", max(times))
    assert max(times) < 1500


def test_model_picker_open_and_search_with_2000_models(pg, live, hub):
    hub["openrouter"].models = {"data": [{"id": f"vendor{i % 40}/model-{i}", "name": f"Vendor {i % 40}: Model {i}",
                                          "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}} for i in range(2000)]}
    add_key(live, K.OPENROUTER)
    open_app(pg, live)
    assert pg.evaluate("haven.models.length") >= 2000
    opens = [pg.evaluate("(() => { const t = performance.now(); openPicker(); const d = performance.now() - t; closePicker(); return d; })()") for _ in range(5)]
    searches = []
    pg.evaluate("openPicker()")
    for q in ["model-1", "vendor3", "vendor12 model-17", "zzz", ""]:
        searches.append(pg.evaluate("q => { const t = performance.now(); const i = document.querySelector('#pq'); i.value = q; renderPicker(); return performance.now() - t; }", q))
    report("model picker open, 2,000 models (ms, max of 5)", round(max(opens), 1))
    report("model picker search, 2,000 models (ms, max of 5 queries)", round(max(searches), 1))
    assert max(opens) < 50 and max(searches) < 50


def first_token_ms(url, body, headers, n=30):
    out = []
    with httpx.Client(timeout=30) as c:
        for _ in range(n):
            t0 = time.perf_counter()
            with c.stream("POST", url, json=body, headers=headers) as r:
                for ln in r.iter_lines():
                    if "content" in ln or '"text"' in ln:
                        out.append((time.perf_counter() - t0) * 1000)
                        break
    return out


def test_server_added_latency_to_first_token(live, hub):
    """Same instant fake, called directly vs. through Haven's /api/chat: the difference is what Haven adds."""
    add_key(live, K.OPENAI)
    hub["openai"].chunks = sse_openai(["hi", " there"])
    direct = first_token_ms(hub.url("openai") + "/chat/completions", {"model": "openai-chat-1", "messages": [], "stream": True}, {})
    via = first_token_ms(live.base + "/api/chat", {"model": "openai:openai-chat-1", "messages": [{"role": "user", "content": "hi"}]}, H)
    p95 = lambda xs: sorted(xs)[int(len(xs) * 0.95) - 1]
    added = p95(via) - p95(direct)
    report("first token direct to fake (ms, p95)", round(p95(direct), 1))
    report("first token through Haven (ms, p95)", round(p95(via), 1))
    report("server-added latency to first token (ms, p95 difference)", round(added, 1))
    assert added < 30


@pytest.mark.parametrize("per_chunk,delay,label", [
    (4, 0.02, "200 tok/s"),        # the brief's pace: 4 tokens every 20 ms (Windows timers can't do 5 ms reliably)
    (1, 0.0, "stress, unpaced"),   # as fast as the fake can send: many tokens per frame
])
def test_streaming_5000_tokens(pg, live, hub, per_chunk, delay, label):
    """Long tasks (>50 ms) are counted with PerformanceObserver; the work Haven does per painted frame is timed."""
    open_app(pg, live)
    toks = []
    for i in range(5000):
        toks.append(("\n\n" if i % 60 == 0 else "") + ("`code` " if i % 97 == 0 else f"word{i} "))
    hub["ollama"].chunks = ndjson_ollama(["".join(toks[i:i + per_chunk]) for i in range(0, 5000, per_chunk)])
    hub["ollama"].delay = delay
    pg.evaluate("""() => {
      window.__long = []; new PerformanceObserver(l => l.getEntries().forEach(e => window.__long.push(e.duration))).observe({entryTypes: ['longtask']});
      window.__paint = []; const orig = window.repaint; window.repaint = m => { const t = performance.now(); orig(m); window.__paint.push(performance.now() - t); };
      window.__frames = []; let last = performance.now();
      (function f(){ const n = performance.now(); window.__frames.push(n - last); last = n; if (!window.__stopFrames) requestAnimationFrame(f); })();
    }""")
    t0 = time.time()
    send(pg, "stream a lot")
    wait_done(pg, 120000)
    took = time.time() - t0
    stats = pg.evaluate("""() => { window.__stopFrames = 1; const f = window.__frames.slice(5), p = window.__paint;
      return {long: window.__long, paintAvg: p.reduce((a, b) => a + b, 0) / p.length, paintMax: Math.max(...p), paints: p.length,
              frameAvg: f.reduce((a, b) => a + b, 0) / f.length, frameMax: Math.max(...f)}; }""")
    report(f"[{label}] 5,000 tokens streamed in (s)", round(took, 1))
    report(f"[{label}] long tasks >50 ms during streaming", len(stats["long"]))
    report(f"[{label}] Haven work per painted frame (ms, avg / max)", f"{stats['paintAvg']:.2f} / {stats['paintMax']:.1f} over {stats['paints']} frames")
    report(f"[{label}] rAF frame interval (ms, avg / max)", f"{stats['frameAvg']:.1f} / {stats['frameMax']:.1f}")
    assert len(pg.inner_text("#thread > .a:last-child .body")) > 30000
    assert stats["long"] == [], stats["long"]
    assert stats["paintAvg"] < 16 and stats["paintMax"] < 50


def test_switch_to_conversation_with_500_messages(pg, live, hub):
    s = storage.get()
    big = s.create_conv("Big one", "")
    for i in range(500):
        role = "user" if i % 2 == 0 else "assistant"
        txt = f"Question {i}?" if role == "user" else f"## Answer {i}\n\nSome **markdown** with a list:\n\n- a\n- b\n\n```py\nprint({i})\n```"
        s.upsert_message(big["id"], {"role": role, "content": txt})
    s.create_conv("Small", "")
    open_app(pg, live)
    times = []
    for _ in range(3):
        pg.evaluate("newChat(false)")
        times.append(pg.evaluate("""async id => { const t = performance.now(); await openConv(id);
            await new Promise(r => requestAnimationFrame(() => r())); return performance.now() - t; }""", big["id"]))
    pg.wait_for_function("document.querySelectorAll('#thread > *').length === 500", timeout=10000)
    report("switch to a 500-message chat, to first paint (ms, worst of 3)", round(max(times), 1))
    assert max(times) < 150


def test_sidebar_search_with_1000_conversations(pg, live, hub):
    s = storage.get()
    for i in range(1000):
        cid = f"c{i:04d}"
        s.create_conv(f"Chat number {i}", "", cid)
        s.upsert_message(cid, {"role": "user", "content": f"message {i} " + ("unicornword" if i == 500 else "plain")})
    open_app(pg, live)
    assert pg.locator("#convs .conv").count() == 1000
    ms = pg.evaluate("""() => new Promise(res => { const i = document.querySelector('#cq'), t = performance.now();
        i.value = 'unicornword'; i.dispatchEvent(new Event('input'));
        const check = () => { const c = document.querySelectorAll('#convs .conv'); if (c.length === 1 && c[0].innerText.includes('Chat number 500')) res(performance.now() - t); else requestAnimationFrame(check); };
        check(); })""")
    title_ms = pg.evaluate("""() => { const i = document.querySelector('#cq'), t = performance.now(); i.value = 'number 99'; i.dispatchEvent(new Event('input')); return performance.now() - t; }""")
    report("sidebar search in message text, 1,000 chats (ms, to results on screen)", round(ms, 1))
    report("sidebar title filter, 1,000 chats (ms)", round(title_ms, 1))
    assert ms < 100 and title_ms < 100


def test_memory_after_many_streamed_conversations(pg, live, hub):
    """Shortened version of the brief's 30-minute check: 25 chats x 1,500 tokens (~2 min). Not the full 30 minutes."""
    open_app(pg, live)
    pg.evaluate("window.gc && gc()")
    before = pg.evaluate("performance.memory.usedJSHeapSize")
    hub["ollama"].chunks = ndjson_ollama([f"token{i} " for i in range(1500)])
    for n in range(25):
        pg.evaluate("newChat(false)")
        send(pg, f"conversation {n}")
        wait_done(pg, 60000)
    pg.evaluate("newChat(false)")
    pg.evaluate("window.gc && gc()")
    time.sleep(0.5)
    after = pg.evaluate("performance.memory.usedJSHeapSize")
    growth = (after - before) / 1048576
    report("page JS heap growth after 25 streamed chats (MB) [shortened, not 30 min]", round(growth, 1))
    assert growth < 100


def test_idle_cpu(browser, live, hub):
    ctx, pg = new_page(browser, live)
    open_app(pg, live)
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Performance.enable")
    m0 = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
    proc = psutil.Process()
    c0 = sum(proc.cpu_times()[:2])
    time.sleep(10)
    m1 = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
    c1 = sum(proc.cpu_times()[:2])
    ctx.close()
    page_pct = (m1["TaskDuration"] - m0["TaskDuration"]) / 10 * 100
    server_pct = (c1 - c0) / 10 / psutil.cpu_count() * 100
    report("idle CPU, page main thread over 10 s (%)", round(page_pct, 2))
    report("idle CPU, test process incl. Haven server + fake hub over 10 s (% of all cores)", round(server_pct, 2))
    assert page_pct < 1 and server_pct < 1


def test_zz_print_summary():
    print("\n[perf] summary " + json.dumps(RESULTS, indent=1))
