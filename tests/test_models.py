"""§8.3 Model listing: parsing, filtering, partial failure, caching, local polling, big lists."""
import asyncio
import json
import statistics
import time

import pytest

from haven.providers import filters, keystore, openai_compat, registry
from haven.providers.base import ProviderConfig
from tests.fakes import keys as K

# ---------------- the chat filter (table-driven, real-looking ids) ----------------
CHAT = [
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-5", "gpt-5-mini", "o3", "o4-mini", "chatgpt-4o-latest",
    "claude-sonnet-4-5", "claude-opus-4-1-20250805", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-pro-preview",
    "llama-3.3-70b-versatile", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "mistral-large-latest", "magistral-medium-latest",
    "pixtral-large-latest", "deepseek-chat", "deepseek-reasoner", "grok-4", "grok-4.20-0309-non-reasoning",
    "qwen/qwen3-32b", "openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct", "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "qwen3:4b", "llama3.2-vision:11b", "gemma3:12b", "Qwen/Qwen2.5-VL-7B-Instruct:novita",
]
NOT_CHAT = [
    "text-embedding-3-small", "text-embedding-ada-002", "nomic-embed-text", "mxbai-embed-large", "gemini-embedding-001",
    "tts-1", "tts-1-hd", "gpt-4o-mini-tts", "whisper-1", "whisper-large-v3-turbo", "gpt-4o-transcribe",
    "dall-e-3", "gpt-image-1", "imagen-4.0-generate-001", "gemini-2.5-flash-image-preview", "grok-imagine-image",
    "grok-imagine-video-1.5", "veo-3.0-generate-preview", "sora-2", "omni-moderation-latest", "text-moderation-latest",
    "gpt-4o-realtime-preview", "gpt-realtime", "gpt-4o-audio-preview", "meta-llama/llama-prompt-guard-2-86m",
    "llama-guard-4-12b", "openai/gpt-oss-safeguard-20b", "canopylabs/orpheus-v1-english", "rerank-2", "BAAI/bge-large-en-v1.5",
    "mistral-ocr-latest", "gemini-2.0-flash-live-001", "gemini-2.5-flash-native-audio", "babbage-002", "davinci-002",
    "gpt-3.5-turbo-instruct", "black-forest-labs/FLUX.1-schnell", "stabilityai/stable-diffusion-xl-base-1.0",
]


@pytest.mark.parametrize("mid", CHAT)
def test_filter_keeps_chat_models(mid):
    assert filters.is_chat_model(mid)


@pytest.mark.parametrize("mid", NOT_CHAT)
def test_filter_drops_non_chat_models(mid):
    assert not filters.is_chat_model(mid)


def test_filter_table_is_big_enough():
    assert len(CHAT) + len(NOT_CHAT) >= 30


@pytest.mark.parametrize("mid,vision", [("gpt-4o", True), ("gpt-3.5-turbo", False), ("claude-sonnet-4-5", True),
                                         ("llama3.2-vision:11b", True), ("qwen3:4b", False), ("pixtral-12b", True),
                                         ("deepseek-chat", False), ("gemma3:4b", True), ("Qwen/Qwen2.5-VL-7B-Instruct", True)])
def test_vision_heuristic(mid, vision):
    assert filters.guess_vision(mid) is vision


@pytest.mark.parametrize("mid,think", [("o3", True), ("o4-mini", True), ("gpt-5", True), ("gpt-4o", False),
                                        ("deepseek-reasoner", True), ("qwen3:4b", True), ("llama3.1:8b", False),
                                        ("grok-4.20-0309-non-reasoning", False), ("gpt-oss:20b", True)])
def test_reasoning_heuristic(mid, think):
    assert filters.guess_reasoning(mid) is think


def cfg(kind="openai", pid=None):
    row = registry.KINDS[kind]
    return ProviderConfig(id=pid or kind, kind=kind, name=row[1], style=row[2], base_url="http://x", local=row[5])


def test_parse_openai_style_data_wrapper():
    j = {"object": "list", "data": [{"id": "gpt-5", "created": 2}, {"id": "whisper-1"}, {"id": "gpt-4o", "created": 1}]}
    ms = [openai_compat.parse_model(cfg(), it) for it in openai_compat._items(j)]
    assert [m.id for m in ms if m] == ["gpt-5", "gpt-4o"]


def test_parse_together_bare_array_with_types():
    j = [{"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "type": "chat", "context_length": 131072},
         {"id": "BAAI/bge-base-en", "type": "embedding"}, {"id": "black-forest-labs/FLUX.1-dev", "type": "image"},
         {"id": "Salesforce/Llama-Rank-V1", "type": "rerank"}]
    ms = [m for m in (openai_compat.parse_model(cfg("together"), it) for it in openai_compat._items(j)) if m]
    assert [m.id for m in ms] == ["meta-llama/Llama-3.3-70B-Instruct-Turbo"] and ms[0].context == 131072


def test_parse_mistral_capabilities():
    j = {"data": [{"id": "mistral-large-latest", "capabilities": {"completion_chat": True, "vision": False}, "max_context_length": 131072},
                  {"id": "pixtral-large-latest", "capabilities": {"completion_chat": True, "vision": True}},
                  {"id": "magistral-medium-latest", "capabilities": {"completion_chat": True, "reasoning": True}},
                  {"id": "codestral-embed", "capabilities": {"completion_chat": False}}]}
    ms = {m.id: m for m in (openai_compat.parse_model(cfg("mistral"), it) for it in j["data"]) if m}
    assert set(ms) == {"mistral-large-latest", "pixtral-large-latest", "magistral-medium-latest"}
    assert ms["pixtral-large-latest"].vision and not ms["mistral-large-latest"].vision
    assert ms["magistral-medium-latest"].think == "toggle" and ms["mistral-large-latest"].think == "no"


def test_parse_lmstudio_native(hub):
    hub["lmstudio"].native_models = {"models": [
        {"type": "llm", "key": "qwen2.5-vl-7b", "display_name": "Qwen2.5 VL 7B", "max_context_length": 32768,
         "capabilities": {"vision": True, "reasoning": False}},
        {"type": "embedding", "key": "nomic-embed-text-v1.5"}]}
    ms = asyncio.run(openai_compat.list_models(registry.local_configs()[1]))
    assert [m.id for m in ms] == ["qwen2.5-vl-7b"] and ms[0].vision and ms[0].local and ms[0].label == "Qwen2.5 VL 7B"


def test_sort_stable_before_preview_newest_first():
    ms = [openai_compat.parse_model(cfg(), {"id": i, "created": c}) for i, c in
          [("gpt-a-preview", 9), ("gpt-old", 1), ("gpt-new", 5)]]
    assert [m.id for m in sorted(ms, key=filters.sort_key)] == ["gpt-new", "gpt-old", "gpt-a-preview"]


# ---------------- /api/models ----------------
def add(client, key):
    r = client.post("/api/providers", json={"key": key})
    assert r.status_code == 200, r.text


def test_one_provider_failing_does_not_hide_others(client, hub):
    add(client, K.GROQ)
    add(client, K.XAI)
    hub["groq"].models_status = 500
    j = client.get("/api/models?refresh=1").json()
    st = {p["id"]: p for p in j["providers"]}
    assert st["groq"]["status"] == "unavailable" and "Provider error" in st["groq"]["message"]
    assert st["xai"]["status"] == "ok"
    assert any(m["provider"] == "xai" for m in j["models"])
    assert client.get("/api/providers").json()["providers"][-2]["status"] in ("unavailable", "ok")


def test_cache_second_call_makes_no_http_calls(client, hub):
    add(client, K.GROQ)
    registry.CACHE.mem.clear()
    registry.CACHE._loaded = True  # simulate a fresh process with nothing cached
    client.get("/api/models")
    n = hub.total_requests()
    for _ in range(3):
        j = client.get("/api/models").json()
    assert hub.total_requests() == n  # zero new HTTP calls (local providers come from the poll cache)
    assert any(m["provider"] == "groq" for m in j["models"])
    client.get("/api/models?refresh=1")
    assert len(hub["groq"].requests) > 1  # refresh bypasses the cache


def test_cache_on_disk_survives_restart_and_corrupt_file_is_rebuilt(client, hub, test_home):
    add(client, K.CEREBRAS)
    path = test_home / "Haven" / "models_cache.json"
    assert "cerebras-chat-1" in path.read_text()
    assert K.CEREBRAS not in path.read_text()
    # "restart": memory gone, disk cache used without HTTP
    registry.CACHE.mem.clear()
    registry.CACHE._loaded = False
    before = len(hub["cerebras"].requests)
    assert any(m["provider"] == "cerebras" for m in client.get("/api/models").json()["models"])
    assert len(hub["cerebras"].requests) == before
    # corrupt file: ignored and rebuilt
    path.write_text("{not json")
    registry.CACHE.mem.clear()
    registry.CACHE._loaded = False
    assert any(m["provider"] == "cerebras" for m in client.get("/api/models").json()["models"])
    assert json.loads(path.read_text())["providers"]["cerebras"]["models"][0]["id"] == "cerebras-chat-1"


def test_stale_cache_served_then_refreshed_in_background(client, hub):
    add(client, K.FIREWORKS)
    registry.CACHE.mem["fireworks"]["ts"] -= registry.CACHE_TTL + 1
    before = len(hub["fireworks"].requests)
    j = client.get("/api/models").json()  # answered from the stale cache straight away
    assert any(m["provider"] == "fireworks" for m in j["models"])
    for _ in range(50):
        if len(hub["fireworks"].requests) > before:
            break
        time.sleep(0.02)
    assert len(hub["fireworks"].requests) == before + 1


def test_ollama_down_is_fast_and_marked_not_running(client, hub, monkeypatch):
    monkeypatch.setenv("HAVEN_BASE_OLLAMA", "http://127.0.0.1:9")  # nothing listens there
    t0 = time.monotonic()
    asyncio.run(registry.CACHE.poll_local())
    j = client.get("/api/models").json()
    assert time.monotonic() - t0 < 3
    st = {p["id"]: p for p in j["providers"]}
    assert st["ollama"]["status"] == "not running"
    assert not any(m["provider"] == "ollama" for m in j["models"])


def test_ollama_appears_after_one_poll(client, hub, monkeypatch):
    monkeypatch.setenv("HAVEN_BASE_OLLAMA", "http://127.0.0.1:9")
    asyncio.run(registry.CACHE.poll_local())
    assert client.get("/api/status").json()["ollama"] is False
    monkeypatch.setenv("HAVEN_BASE_OLLAMA", hub.url("ollama"))  # Ollama starts
    hub["ollama"].show = {"qwen3:4b": {"capabilities": ["completion", "thinking"], "model_info": {"qwen3.context_length": 40960}}}
    monkeypatch.setattr(registry, "LOCAL_POLL", 0.05)

    async def one_poll_cycle():
        task = asyncio.ensure_future(registry.poll_forever())
        await asyncio.sleep(0.3)
        task.cancel()

    asyncio.run(one_poll_cycle())
    s = client.get("/api/status").json()
    assert s["ollama"] is True and s["models"] == ["qwen3:4b"]
    m = [m for m in client.get("/api/models").json()["models"] if m["provider"] == "ollama"][0]
    assert m["local"] and m["think"] == "toggle" and m["context"] == 40960 and not m["vision"]


def test_ollama_hides_cloud_and_embedding_models(hub):
    hub["ollama"].models = {"models": [{"name": "qwen3:4b", "digest": "a"}, {"name": "gpt-oss:120b-cloud", "digest": "b"},
                                       {"name": "nomic-embed-text:latest", "digest": "c"}, {"name": "llava:7b", "digest": "d"}]}
    hub["ollama"].show = {"nomic-embed-text:latest": {"capabilities": ["embedding"]},
                          "llava:7b": {"capabilities": ["completion", "vision"]}}
    ms = asyncio.run(registry.ADAPTERS["ollama"].list_models(registry.local_configs()[0]))
    assert [m.id for m in ms] == ["llava:7b", "qwen3:4b"]
    assert ms[0].vision and ms[1].think == "no"


def test_2000_openrouter_models_served_fast_from_cache(client, hub):
    hub["openrouter"].models = {"data": [{"id": f"vendor{i % 40}/model-{i}", "name": f"Vendor {i % 40}: Model {i}",
                                          "context_length": 128000, "created": 1700000000 + i,
                                          "architecture": {"input_modalities": ["text", "image"] if i % 3 == 0 else ["text"],
                                                           "output_modalities": ["text"]},
                                          "supported_parameters": ["reasoning"] if i % 5 == 0 else []} for i in range(2000)]}
    add(client, K.OPENROUTER)
    client.get("/api/models")  # warm
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        j = client.get("/api/models").json()
        times.append((time.perf_counter() - t0) * 1000)
    assert len([m for m in j["models"] if m["provider"] == "openrouter"]) == 2000
    med = statistics.median(times)
    print(f"\n/api/models with 2,000 OpenRouter models: median {med:.1f} ms, max {max(times):.1f} ms")
    assert med < 150, times
