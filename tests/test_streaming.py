"""§8.4 Streaming, run against every adapter through the real server (uvicorn, real sockets)."""
import asyncio
import base64
import io
import json
import threading
import time

import httpx
import psutil
import pytest
import respx
from PIL import Image

from haven.providers import base, registry
from tests.fakes import keys as K
from tests.fakes.hub import ndjson_ollama, rechunk, sse, sse_anthropic, sse_gemini, sse_openai, stream_for

H = {"X-Desk-Token": "test-token"}
STYLES = ["openai", "anthropic", "gemini", "ollama"]
SETUP = {"openai": (K.OPENAI, "openai:openai-chat-1"), "anthropic": (K.ANTHROPIC, "anthropic:claude-test-1"),
         "gemini": (K.GEMINI, "gemini:gemini-2.5-flash"), "ollama": (None, "ollama:qwen3:4b")}
UNICODE = ["Hello 👋🏽 ", "नमस्ते दुनिया ", "你好，世界 ", "مرحبا بالعالم", " a\r\nb", " end ✅"]


def setup(live, style):
    key, model = SETUP[style]
    if key:
        r = httpx.post(live.base + "/api/providers", json={"key": key}, headers=H, timeout=30)
        assert r.status_code == 200, r.text
    else:
        asyncio.run(registry.CACHE.poll_local())
    return model


def chat(live, model, messages=None, files=None, think=False, system=None, timeout=60, shield_ok=False):
    body = {"model": model, "messages": messages or [{"role": "user", "content": "hi"}], "think": think, "shield_ok": shield_ok}
    if files:
        body["files"] = files
    if system:
        body["system"] = system
    events = []
    with httpx.Client(timeout=timeout) as c:
        with c.stream("POST", live.base + "/api/chat", json=body, headers=H) as r:
            assert r.status_code == 200, r.read()
            for ln in r.iter_lines():
                if ln.strip():
                    events.append(json.loads(ln))
    return events


def text(events, key="content"):
    return "".join(e.get(key, "") for e in events)


def check_contract(events):
    assert events[-1].get("done") is True, events[-3:]
    assert sum(1 for e in events if e.get("done")) == 1
    for e in events:
        assert set(e) <= {"content", "thinking", "note", "error", "done", "speed", "usage", "unmask", "docs", "confirm"}, e


# ---------------- normal streams ----------------
@pytest.mark.parametrize("style", STYLES)
def test_exact_text_unicode(live, hub, style):
    model = setup(live, style)
    hub[style].chunks = stream_for(style, UNICODE)
    ev = chat(live, model)
    check_contract(ev)
    assert text(ev) == "".join(UNICODE)
    assert not any("error" in e for e in ev)


@pytest.mark.parametrize("size", [1, 3, 7])
@pytest.mark.parametrize("style", STYLES)
def test_chunks_split_anywhere_incl_utf8(live, hub, style, size):
    model = setup(live, style)
    hub[style].chunks = rechunk(stream_for(style, UNICODE), size)  # splits lines, JSON and multi-byte chars
    ev = chat(live, model)
    assert text(ev) == "".join(UNICODE)


@pytest.mark.parametrize("style", ["openai", "anthropic", "gemini"])
def test_many_events_in_one_chunk(live, hub, style):
    model = setup(live, style)
    hub[style].chunks = [b"".join(stream_for(style, UNICODE))]
    assert text(chat(live, model)) == "".join(UNICODE)


def test_sse_comments_blank_lines_crlf_and_missing_done(live, hub):
    model = setup(live, "openai")
    objs = [{"choices": [{"delta": {"content": t}}]} for t in ["one ", "two ", "three"]]
    raw = [b": keep-alive\r\n\r\n", b"\r\n",
           b"data: " + json.dumps(objs[0]).encode() + b"\r\n\r\n",
           b": OPENROUTER PROCESSING\n\n", b"data:\n\n", b"data: \n\n",
           b"data: " + json.dumps(objs[1]).encode() + b"\n\n",
           b"data:" + json.dumps(objs[2]).encode()]  # no space after colon, no trailing blank line, no [DONE]
    hub["openai"].chunks = raw
    ev = chat(live, model)
    check_contract(ev)
    assert text(ev) == "one two three"


@pytest.mark.parametrize("style", ["openai", "anthropic", "gemini", "ollama"])
def test_malformed_json_event_is_skipped(live, hub, style):
    model = setup(live, style)
    chunks = stream_for(style, ["before ", "after"])
    bad = b"{not json at all\n" if style == "ollama" else b"data: {not json at all\n\n"
    chunks.insert(2, bad)
    hub[style].chunks = chunks
    ev = chat(live, model)
    assert text(ev) == "before after"
    assert not any("error" in e for e in ev)


def test_very_long_output_100k(live, hub):
    model = setup(live, "openai")
    pieces = [f"{i:05d}" + "x" * 95 for i in range(1000)]
    hub["openai"].chunks = sse_openai(pieces)
    t0 = time.perf_counter()
    ev = chat(live, model)
    assert text(ev) == "".join(pieces) and len(text(ev)) == 100_000
    print(f"\n100k chars streamed in {time.perf_counter() - t0:.2f}s")


# ---------------- thinking ----------------
@pytest.mark.parametrize("style", STYLES)
def test_thinking_events(live, hub, style):
    model = setup(live, style)
    if style == "ollama":
        from haven.providers import ollama

        hub["ollama"].show = {"qwen3:4b": {"capabilities": ["completion", "thinking"]}}
        ollama._SHOW.clear()
        registry.CACHE.local.clear()
        asyncio.run(registry.CACHE.poll_local())
    hub[style].chunks = stream_for(style, ["Answer."], thinking=["Let me ", "think…"])
    ev = chat(live, model, think=True)
    assert text(ev, "thinking") == "Let me think…"
    assert text(ev) == "Answer."
    req = hub[style].chat_requests()[-1]["json"]
    if style == "anthropic":
        assert req["thinking"]["type"] in ("enabled", "adaptive")
    if style == "gemini":
        assert req["generationConfig"]["thinkingConfig"]["includeThoughts"] is True
    if style == "ollama":
        assert req["think"] is True


@pytest.mark.parametrize("kind,field", [("deepseek", "reasoning_content"), ("cerebras", "reasoning"), ("groq", "reasoning")])
def test_openai_compatible_reasoning_fields(live, hub, kind, field):
    key = {"deepseek": K.SK_AMBIG, "cerebras": K.CEREBRAS, "groq": K.GROQ}[kind]
    hub[kind].models = {"data": [{"id": "r-model-reasoner"}]}
    if kind == "deepseek":
        hub["openai"].models_status = 401
    r = httpx.post(live.base + "/api/providers", json={"key": key}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    hub[kind].chunks = sse_openai(["42"], reasoning=["step 1, ", "step 2"], field=field)
    ev = chat(live, f"{kind}:r-model-reasoner", think=True)
    assert text(ev, "thinking") == "step 1, step 2" and text(ev) == "42"


def test_openrouter_reasoning_details(live, hub):
    hub["openrouter"].models = {"data": [{"id": "x/thinker", "supported_parameters": ["reasoning"]}]}
    httpx.post(live.base + "/api/providers", json={"key": K.OPENROUTER}, headers=H, timeout=30)
    objs = [{"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "text": "hmm "}]}}]},
            {"choices": [{"delta": {"reasoning": "ok", "reasoning_details": [{"type": "reasoning.text", "text": "ok"}]}}]},
            {"choices": [{"delta": {"content": "Done"}}]}]
    hub["openrouter"].chunks = sse(objs)
    ev = chat(live, "openrouter:x/thinker", think=True)
    assert text(ev, "thinking") == "hmm ok" and text(ev) == "Done"
    assert hub["openrouter"].chat_requests()[-1]["json"]["reasoning"] == {"enabled": True}
    assert hub["openrouter"].chat_requests()[-1]["headers"]["x-openrouter-title"] == "Haven"


def test_mistral_thinking_chunks(live, hub):
    hub["mistral"].models = {"data": [{"id": "magistral-small-latest", "capabilities": {"completion_chat": True, "reasoning": True}}]}
    hub["together"].models_status = 401
    httpx.post(live.base + "/api/providers", json={"key": K.PLAIN}, headers=H, timeout=30)
    objs = [{"choices": [{"delta": {"content": [{"type": "thinking", "thinking": [{"type": "text", "text": "pondering"}]}]}}]},
            {"choices": [{"delta": {"content": [{"type": "text", "text": "Result"}]}}]}]
    hub["mistral"].chunks = sse(objs)
    ev = chat(live, "mistral:magistral-small-latest", think=True)
    assert text(ev, "thinking") == "pondering" and text(ev) == "Result"


def test_think_tags_in_content_split_across_chunks(live, hub):
    hub["mistral"].models_status = 401
    httpx.post(live.base + "/api/providers", json={"key": K.PLAIN}, headers=H, timeout=30)
    pieces = ["<thi", "nk>I should ", "add.</th", "ink>\n\n", "2 + 2 = 4"]
    hub["together"].chunks = sse_openai(pieces)
    ev = chat(live, "together:meta-llama/Llama-3.3-70B-Instruct-Turbo")
    assert text(ev, "thinking") == "I should add." and text(ev) == "2 + 2 = 4"


def test_models_without_thinking_get_no_think_params(live, hub):
    model = setup(live, "openai")
    hub["openai"].chunks = sse_openai(["hi"])
    chat(live, model, think=True)  # Think on, but openai-chat-1 can't think
    req = hub["openai"].chat_requests()[-1]["json"]
    assert "reasoning_effort" not in req and "reasoning" not in req
    m = [m for m in httpx.get(live.base + "/api/models", headers=H).json()["models"] if m["full_id"] == model][0]
    assert m["think"] == "no"  # the UI hides/disables the Think toggle for this model


def test_reasoning_model_think_maps_to_effort(live, hub):
    hub["openai"].models = {"data": [{"id": "o4-mini"}, {"id": "gpt-4o"}]}
    setup(live, "openai")
    hub["openai"].chunks = sse_openai(["ok"])
    chat(live, "openai:o4-mini", think=True)
    req = hub["openai"].chat_requests()[-1]["json"]
    assert req["reasoning_effort"] == "high" and "temperature" not in req and "max_tokens" not in req
    assert req["stream_options"] == {"include_usage": True}


def test_optional_param_rejected_is_retried_without_it(live, hub):
    hub["openai"].models = {"data": [{"id": "o4-mini"}]}
    setup(live, "openai")
    hub["openai"].chunks = sse_openai(["fine"])
    hub["openai"].reject_if = lambda body: (400, '{"error": {"message": "Unrecognized request argument supplied: stream_options"}}')         if "stream_options" in body else None
    ev = chat(live, "openai:o4-mini", think=True)
    assert text(ev) == "fine" and not any("error" in e for e in ev)
    reqs = hub["openai"].chat_requests()
    assert len(reqs) == 2
    assert "stream_options" in reqs[0]["json"] and "stream_options" not in reqs[1]["json"]


# ---------------- errors ----------------
ERRORS = [(401, {}, "Key rejected by"), (403, {}, "Key rejected by"), (404, {}, "Model not available"),
          (429, {"retry-after": "7"}, "Rate limited, try again in 7s"), (500, {}, "Provider error"),
          (503, {}, "Provider error"), (413, {}, "Too long for this model")]


@pytest.mark.parametrize("status,headers,expected", ERRORS)
@pytest.mark.parametrize("style", ["openai", "anthropic", "gemini"])
def test_http_errors_before_first_token(live, hub, style, status, headers, expected):
    model = setup(live, style)
    hub[style].chat_status = status
    hub[style].chat_headers = headers
    ev = chat(live, model)
    check_contract(ev)
    errs = [e["error"] for e in ev if "error" in e]
    assert len(errs) == 1 and errs[0].startswith(expected), errs
    assert "Traceback" not in json.dumps(ev) and "File \"" not in json.dumps(ev)


def test_context_too_long_400(live, hub):
    model = setup(live, "openai")
    hub["openai"].chat_status = 400
    hub["openai"].chat_body = '{"error": {"message": "This model\'s maximum context length is 128000 tokens."}}'
    errs = [e["error"] for e in chat(live, model) if "error" in e]
    assert errs == ["Too long for this model. Remove a file or start a new chat."]


def test_ollama_errors(live, hub):
    model = setup(live, "ollama")
    hub["ollama"].chat_status = 404
    hub["ollama"].chat_body = '{"error": "model \\"qwen3:4b\\" not found, try pulling it first"}'
    errs = [e["error"] for e in chat(live, model) if "error" in e]
    assert len(errs) == 1 and errs[0].startswith("Model not available")


@pytest.mark.parametrize("base_url,expected", [
    ("http://127.0.0.1:9/v1", "Can't reach OpenAI. Check internet."),            # connection refused
    ("http://haven-test-nonexistent.invalid/v1", "Can't reach OpenAI. Check internet."),  # DNS failure
])
def test_network_errors(live, hub, monkeypatch, base_url, expected):
    model = setup(live, "openai")
    monkeypatch.setenv("HAVEN_BASE_OPENAI", base_url)
    ev = chat(live, model)
    check_contract(ev)
    assert [e["error"] for e in ev if "error" in e] == [expected]


@pytest.mark.parametrize("exc,expected", [
    (httpx.ConnectTimeout("timed out"), "Can't reach OpenAI. Check internet."),
    (httpx.ReadTimeout("timed out"), "Took too long: OpenAI didn't answer in time."),
    (httpx.ConnectError("[Errno 11001] getaddrinfo failed"), "Can't reach OpenAI. Check internet."),
])
async def test_timeouts_and_dns_mapping(exc, expected):
    cfg = registry.make_config({"id": "openai", "kind": "openai"}, K.OPENAI)
    model = base.ModelInfo(id="gpt-x", provider="openai", kind="openai")
    with respx.mock:
        respx.post(cfg.base_url + "/chat/completions").mock(side_effect=exc)
        with pytest.raises(base.ProviderError) as ei:
            async for _ in registry.ADAPTERS["openai"].stream_chat(cfg, model, [{"role": "user", "content": "hi"}], [], None, False):
                pass
    assert ei.value.message.startswith(expected)  # brief: timeout -> "Took too long"
    await base.close_clients()


@pytest.mark.parametrize("style", STYLES)
def test_error_mid_stream_keeps_text(live, hub, style):
    model = setup(live, style)
    chunks = stream_for(style, ["partial ", "answer"])
    err = {"openai": b'data: {"error": {"message": "upstream exploded"}}\n\n',
           "anthropic": b'event: error\ndata: {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}\n\n',
           "gemini": b'data: {"error": {"code": 500, "message": "internal"}}\n\n',
           "ollama": b'{"error": "out of memory"}\n'}[style]
    cut = {"openai": 3, "anthropic": 5, "gemini": 2, "ollama": 2}[style]
    hub[style].chunks = chunks[:cut] + [err] + chunks[cut:]
    ev = chat(live, model)
    check_contract(ev)
    assert text(ev) == "partial answer"
    errs = [e["error"] for e in ev if "error" in e]
    assert len(errs) == 1
    assert [list(e)[0] for e in ev].index("error") > [list(e)[0] for e in ev].index("content")


def test_connection_dropped_mid_stream(live, hub):
    model = setup(live, "openai")
    hub["openai"].chunks = sse_openai(["a", "b", "c", "d"])
    hub["openai"].drop_after = 3
    ev = chat(live, model)
    check_contract(ev)
    assert text(ev) == "ab"
    errs = [e["error"] for e in ev if "error" in e]
    assert len(errs) == 1 and "Can't reach OpenAI" in errs[0]


# ---------------- cancellation ----------------
def _endless(style):
    def gen(i):
        piece = f"tok{i} "
        return stream_for(style, [piece])[{"openai": 1, "anthropic": 3, "gemini": 0, "ollama": 0}[style]]  # the text-delta event
    return gen


def _abort_after(live, model, n_tokens):
    body = {"model": model, "messages": [{"role": "user", "content": "go"}]}
    got = 0
    with httpx.Client(timeout=30) as c:
        with c.stream("POST", live.base + "/api/chat", json=body, headers=H) as r:
            for ln in r.iter_lines():
                if ln.strip() and "content" in json.loads(ln):
                    got += 1
                    if got >= n_tokens:
                        break
        t_close = time.monotonic()
    return t_close


@pytest.mark.parametrize("style", STYLES)
def test_cancel_closes_upstream_within_500ms(live, hub, style):
    model = setup(live, style)
    p = hub[style]
    p.infinite = _endless(style)
    p.delay = 0.02
    t_close = _abort_after(live, model, 3)
    for _ in range(100):
        if p.disconnected_at:
            break
        time.sleep(0.01)
    assert p.disconnected_at is not None, "upstream never saw the disconnect"
    lag = p.disconnected_at - t_close
    sent_at_close = p.sent
    time.sleep(0.3)
    assert p.sent <= sent_at_close + 1  # no more upstream work after the stop
    print(f"\n{style}: upstream closed {lag * 1000:.0f} ms after the client stopped")
    assert lag < 0.5, lag
    # the next request works normally
    p.infinite = None
    p.disconnected_at = None
    p.chunks = stream_for(style, ["fresh"])
    p.delay = 0
    assert text(chat(live, model)) == "fresh"


def test_cancel_while_upstream_is_silent(live, hub):
    """A model 'thinking' silently: no bytes flow, so only active disconnect detection can stop it."""
    model = setup(live, "openai")
    p = hub["openai"]
    p.first_delay = 30
    p.chunks = sse_openai(["late"])
    body = {"model": model, "messages": [{"role": "user", "content": "go"}]}
    with httpx.Client(timeout=30) as c:
        with c.stream("POST", live.base + "/api/chat", json=body, headers=H) as r:
            time.sleep(0.4)
        t_close = time.monotonic()
    for _ in range(100):
        if p.disconnected_at:
            break
        time.sleep(0.01)
    assert p.disconnected_at is not None
    print(f"\nsilent upstream closed {(p.disconnected_at - t_close) * 1000:.0f} ms after the client stopped")
    assert p.disconnected_at - t_close < 0.5


def _server_tasks(live):
    from haven import server

    async def count():
        return {"tasks": len(asyncio.all_tasks())}

    if not any(getattr(r, "path", "") == "/api/_test_tasks" for r in server.app.router.routes):
        server.app.add_api_route("/api/_test_tasks", count)
    return httpx.get(live.base + "/api/_test_tasks", headers=H).json()["tasks"]


def _conns_to(port):
    me = psutil.Process()
    return sum(1 for c in me.net_connections(kind="tcp") if c.raddr and c.raddr.port == port and c.status == "ESTABLISHED")


def test_50_rapid_start_stop_cycles_leak_nothing(live, hub):
    model = setup(live, "openai")
    p = hub["openai"]
    p.infinite = _endless("openai")
    p.delay = 0.005
    _abort_after(live, model, 1)
    time.sleep(0.3)
    tasks0, conns0 = _server_tasks(live), _conns_to(hub.port)
    for _ in range(50):
        _abort_after(live, model, 2)
    time.sleep(0.8)
    tasks1, conns1 = _server_tasks(live), _conns_to(hub.port)
    print(f"\ntasks {tasks0}->{tasks1}, upstream connections {conns0}->{conns1}")
    assert tasks1 <= tasks0 + 1
    assert conns1 <= max(conns0, 1) + base.LIMITS.max_keepalive_connections
    p.infinite = None
    p.chunks = sse_openai(["still ok"])
    assert text(chat(live, model)) == "still ok"


def test_two_streams_at_once_no_cross_talk(live, hub):
    setup(live, "openai")
    setup(live, "anthropic")
    hub["openai"].chunks = sse_openai([f"O{i} " for i in range(40)])
    hub["anthropic"].chunks = sse_anthropic([f"A{i} " for i in range(40)])
    hub["openai"].delay = hub["anthropic"].delay = 0.005
    out = {}

    def run(name, model):
        out[name] = text(chat(live, model))

    ts = [threading.Thread(target=run, args=("o", SETUP["openai"][1])), threading.Thread(target=run, args=("a", SETUP["anthropic"][1]))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert out["o"] == "".join(f"O{i} " for i in range(40))
    assert out["a"] == "".join(f"A{i} " for i in range(40))


def test_same_provider_two_models_concurrently(live, hub):
    hub["openai"].models = {"data": [{"id": "m-one"}, {"id": "m-two"}]}
    setup(live, "openai")
    hub["openai"].chunk_fn = lambda body: sse_openai([f"{body['model']}-{i} " for i in range(30)])
    hub["openai"].delay = 0.005
    out = {}

    def run(m):
        out[m] = text(chat(live, f"openai:{m}"))

    ts = [threading.Thread(target=run, args=(m,)) for m in ("m-one", "m-two")]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    for m in ("m-one", "m-two"):
        assert out[m] == "".join(f"{m}-{i} " for i in range(30))


# ---------------- attachments + history ----------------
def png_b64():  # opaque PNG: Haven sends it as JPEG (v0.9 normalize_image behaviour)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


IMG = {"name": "photo.png", "mime": "image/png"}


@pytest.mark.parametrize("style", STYLES)
def test_vision_model_gets_image_in_provider_format(live, hub, style):
    if style == "openai":
        hub["openai"].models = {"data": [{"id": "gpt-4o"}]}
    if style == "ollama":
        hub["ollama"].models = {"models": [{"name": "llava:7b", "digest": "v1"}]}
        hub["ollama"].show = {"llava:7b": {"capabilities": ["completion", "vision"]}}
    model = setup(live, style)
    model = {"openai": "openai:gpt-4o", "ollama": "ollama:llava:7b"}.get(style, model)
    hub[style].chunks = stream_for(style, ["a red square"])
    # shield_ok: the user already said "send anyway" for images to the cloud (§8.6 covers asking)
    ev = chat(live, model, files=[{**IMG, "data": png_b64()}], messages=[{"role": "user", "content": "what is this?"}], shield_ok=True)
    assert text(ev) == "a red square" and not any("can't see images" in e.get("note", "") for e in ev)
    req = hub[style].chat_requests()[-1]["json"]
    if style == "openai":
        parts = req["messages"][-1]["content"]
        assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/")
        assert parts[-1] == {"type": "text", "text": "what is this?"}
    elif style == "anthropic":
        blk = req["messages"][-1]["content"][0]
        assert blk["type"] == "image" and blk["source"]["media_type"] == "image/jpeg"
        assert base64.b64decode(blk["source"]["data"])[:2] == bytes([0xFF, 0xD8])  # really a JPEG
    elif style == "gemini":
        assert req["contents"][-1]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"
    else:
        assert len(req["messages"][-1]["images"]) == 1


@pytest.mark.parametrize("style", ["openai", "ollama"])
def test_non_vision_model_with_image_gets_a_note(live, hub, style):
    model = setup(live, style)
    hub[style].chunks = stream_for(style, ["no image seen"])
    ev = chat(live, model, files=[{**IMG, "data": png_b64()}], shield_ok=True)
    check_contract(ev)
    notes = [e["note"] for e in ev if "note" in e]
    assert any("can't see images" in n for n in notes)
    assert text(ev) == "no image seen"
    req = json.dumps(hub[style].chat_requests()[-1]["json"])
    assert "base64" not in req and '"images"' not in req


HISTORY = [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1 (from another model)"},
           {"role": "user", "content": "Q2"}]


def test_switch_model_mid_conversation_history_mapping(live, hub):
    for style in ("openai", "anthropic", "gemini", "ollama"):
        model = setup(live, style)
        hub[style].chunks = stream_for(style, ["ok"])
        chat(live, model, messages=HISTORY, system="SYS")
    o = hub["openai"].chat_requests()[-1]["json"]["messages"]
    assert [m["role"] for m in o] == ["system", "user", "assistant", "user"] and o[0]["content"] == "SYS"
    a = hub["anthropic"].chat_requests()[-1]["json"]
    assert a["system"] == "SYS" and [m["role"] for m in a["messages"]] == ["user", "assistant", "user"]
    assert a["messages"][1]["content"][0]["text"] == "A1 (from another model)" and a["max_tokens"] > 0
    g = hub["gemini"].chat_requests()[-1]["json"]
    assert g["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert [c["role"] for c in g["contents"]] == ["user", "model", "user"]
    ol = hub["ollama"].chat_requests()[-1]["json"]["messages"]
    assert [m["role"] for m in ol] == ["system", "user", "assistant", "user"]


def test_anthropic_merges_same_role_and_drops_trailing_assistant(live, hub):
    model = setup(live, "anthropic")
    hub["anthropic"].chunks = sse_anthropic(["ok"])
    msgs = [{"role": "assistant", "content": "hello!"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    chat(live, model, messages=msgs)
    m = hub["anthropic"].chat_requests()[-1]["json"]["messages"]
    assert [x["role"] for x in m] == ["user"] and m[0]["content"][0]["text"] == "a\n\nb"


def test_done_carries_usage_and_speed(live, hub):
    model = setup(live, "ollama")
    hub["ollama"].chunks = ndjson_ollama(["a", "b", "c"])
    done = chat(live, model)[-1]
    assert done["done"] and done["speed"] == 3.0 and done["usage"]["output"] == 3
