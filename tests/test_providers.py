"""§8.2 Key detection & provider management."""
import json
import time

import pytest

from haven.providers import keystore, registry
from tests.fakes import keys as K

REJECT = '{"error": {"message": "Incorrect API key provided"}}'


# ---------------- prefixes ----------------
@pytest.mark.parametrize("key,expected", [
    (K.ANTHROPIC, ["anthropic"]),
    ("sk-ant-x123", ["anthropic"]),
    (K.OPENROUTER, ["openrouter"]),
    ("sk-or-abc", ["openrouter"]),
    (K.OPENAI, ["openai"]),
    ("sk-proj-abc", ["openai"]),
    (K.GEMINI, ["gemini"]),
    (K.GROQ, ["groq"]),
    (K.XAI, ["xai"]),
    (K.FIREWORKS, ["fireworks"]),
    (K.CEREBRAS, ["cerebras"]),
    (K.HF, ["huggingface"]),
    (K.SK_AMBIG, ["openai", "deepseek"]),
    (K.PLAIN, ["mistral", "together"]),
])
def test_prefix_candidates(key, expected):
    assert registry.candidates(key) == expected


@pytest.mark.parametrize("key", [K.ANTHROPIC, "sk-ant-abc", K.OPENROUTER, "sk-or-v1-zzz"])
def test_specific_prefixes_never_openai(key):
    assert "openai" not in registry.candidates(key)
    assert "deepseek" not in registry.candidates(key)


@pytest.mark.parametrize("raw", [
    f"  {K.OPENAI}  ", f"{K.OPENAI}\n", f"\n{K.OPENAI}\r\n", f'"{K.OPENAI}"', f"'{K.OPENAI}'",
    f"Bearer {K.OPENAI}", f"bearer {K.OPENAI}", f' "Bearer {K.OPENAI}"\n', f"`{K.OPENAI}`",
])
def test_clean_key(raw):
    assert registry.clean_key(raw) == K.OPENAI


@pytest.mark.parametrize("raw", ["", "   ", "\n", "sk-abc def", "sk-abc\ndef", '""'])
def test_clean_key_rejects(raw):
    with pytest.raises(ValueError):
        registry.clean_key(raw)


@pytest.mark.parametrize("url,expected", [
    ("http://localhost:8000", "http://localhost:8000/v1"),
    ("http://localhost:8000/", "http://localhost:8000/v1"),
    ("http://localhost:8000/v1", "http://localhost:8000/v1"),
    ("http://localhost:8000/v1/", "http://localhost:8000/v1"),
    ("localhost:8000", "http://localhost:8000/v1"),
    ("llm.company.com", "https://llm.company.com/v1"),
    ("https://gw.example.com/openai/v1/chat/completions", "https://gw.example.com/openai/v1"),
    ("https://gw.example.com/api/v2/", "https://gw.example.com/api/v2"),
])
def test_normalize_base(url, expected):
    assert registry.normalize_base(url) == expected


# ---------------- probing ----------------
async def test_ambiguous_sk_key_picks_the_one_that_works(hub):
    hub["openai"].models_status = 401
    hub["openai"].models_body = REJECT
    hub["deepseek"].models = {"object": "list", "data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}
    d = await registry.detect_provider(K.SK_AMBIG)
    assert d.ok and d.kind == "deepseek"
    assert [m.id for m in d.models] == ["deepseek-chat", "deepseek-reasoner"]
    assert len(hub["openai"].requests) == 1 and len(hub["deepseek"].requests) == 1  # both probed
    assert hub["deepseek"].requests[0]["headers"]["authorization"] == f"Bearer {K.SK_AMBIG}"


async def test_ambiguous_both_reject(hub):
    for k in ("openai", "deepseek"):
        hub[k].models_status = 401
        hub[k].models_body = REJECT
    d = await registry.detect_provider(K.SK_AMBIG)
    assert not d.ok
    assert d.message == "Key rejected by OpenAI and DeepSeek"


async def test_ambiguous_both_work_prefers_table_order(hub):
    d = await registry.detect_provider(K.SK_AMBIG)
    assert d.ok and d.kind == "openai"


async def test_unknown_format_goes_to_manual_choice(hub):
    for k in ("mistral", "together"):
        hub[k].models_status = 401
    d = await registry.detect_provider(K.PLAIN)
    assert not d.ok and d.unrecognised
    assert "Couldn't recognise this key" in d.message


async def test_plain_key_detected_as_together_bare_array(hub):
    hub["mistral"].models_status = 401
    d = await registry.detect_provider(K.PLAIN)
    assert d.ok and d.kind == "together"
    assert d.models[0].id == "meta-llama/Llama-3.3-70B-Instruct-Turbo"


async def test_manual_provider_override(hub):
    d = await registry.detect_provider(K.SK_AMBIG, kind="deepseek")
    assert d.ok and d.kind == "deepseek"
    assert len(hub["openai"].requests) == 0


async def test_custom_base_url(hub):
    # base with a trailing slash; a non-root path is kept as-is (only a bare host gets /v1 added)
    d = await registry.detect_provider(K.CUSTOM, kind="custom", base=hub.url("custom") + "/")
    assert d.ok and d.kind == "custom"
    assert hub["custom"].requests[0]["path"] == "/v1/models"


async def test_probe_timeout_does_not_delay_beyond_6s(hub):
    hub["openai"].models_delay = 30  # hangs
    t0 = time.monotonic()
    d = await registry.detect_provider(K.SK_AMBIG)
    took = time.monotonic() - t0
    assert d.ok and d.kind == "deepseek"
    assert took < 6.5, took


async def test_openrouter_validates_with_authenticated_endpoint(hub):
    hub["openrouter"].models = {"data": [{"id": "openai/gpt-5", "name": "OpenAI: GPT-5",
                                          "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                                          "supported_parameters": ["reasoning"], "context_length": 400000}]}
    d = await registry.detect_provider(K.OPENROUTER)
    assert d.ok and d.kind == "openrouter"
    assert hub["openrouter"].requests[0]["path"] == "/api/v1/models/user"
    m = d.models[0]
    assert m.vision and m.think == "toggle" and m.context == 400000 and m.label == "OpenAI: GPT-5"


# ---------------- API: add / duplicate / delete ----------------
def add(client, key, **kw):
    return client.post("/api/providers", json={"key": key, **kw})


def test_add_key_via_api_returns_models_and_hint(client, hub):
    r = add(client, f'  "{K.ANTHROPIC}"\n', label="Work")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["provider"]["kind"] == "anthropic" and j["provider"]["id"] == "anthropic"
    assert j["provider"]["hint"] == "…0003" and j["provider"]["label"] == "Work"
    assert j["models"][0]["full_id"] == "anthropic:claude-test-1"
    assert K.ANTHROPIC not in r.text
    assert hub["anthropic"].requests[0]["headers"]["x-api-key"] == K.ANTHROPIC
    assert hub["anthropic"].requests[0]["headers"]["anthropic-version"]


def test_same_key_twice_is_rejected(client):
    assert add(client, K.GEMINI).status_code == 200
    r = add(client, " " + K.GEMINI + " ")
    assert r.status_code == 409 and "already added" in r.json()["detail"]
    assert len([p for p in client.get("/api/providers").json()["providers"] if p["kind"] == "gemini"]) == 1


def test_two_keys_same_provider_get_distinct_ids(client, hub):
    assert add(client, K.OPENAI, label="Personal").status_code == 200
    assert add(client, "sk-proj-TESTKEYsecondopenai000000000014", label="Work").status_code == 200
    ids = [p["id"] for p in client.get("/api/providers").json()["providers"] if p["kind"] == "openai"]
    assert ids == ["openai", "openai-2"]
    models = client.get("/api/models").json()["models"]
    assert {"openai:openai-chat-1", "openai-2:openai-chat-1"} <= {m["full_id"] for m in models}


def test_add_rejected_key_gives_human_message(client, hub):
    hub["anthropic"].models_status = 401
    r = add(client, K.ANTHROPIC)
    assert r.status_code == 400
    assert r.json()["detail"] == "Key rejected by Anthropic"
    assert keystore.saved() == []


def test_add_unrecognised_key_flags_manual_path(client, hub):
    hub["mistral"].models_status = 401
    hub["together"].models_status = 403
    r = add(client, K.PLAIN)
    assert r.status_code == 400 and r.json()["unrecognised"] is True


def test_delete_provider_removes_keyring_settings_models(client, hub):
    from tests.conftest import MemoryKeyring

    assert add(client, K.GROQ).status_code == 200
    assert any(v == K.GROQ for v in MemoryKeyring.store.values())
    assert any(m["provider"] == "groq" for m in client.get("/api/models").json()["models"])
    assert client.delete("/api/providers/groq").json() == {"ok": True}
    assert not any(v == K.GROQ for v in MemoryKeyring.store.values())
    assert keystore.saved() == []
    assert not any(m["provider"] == "groq" for m in client.get("/api/models").json()["models"])
    r = client.post("/api/chat", json={"model": "groq:groq-chat-1", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400 and r.json()["detail"] == "Model no longer available, pick another"


def test_patch_provider(client):
    add(client, K.XAI)
    r = client.patch("/api/providers/xai", json={"label": "Grok", "enabled": False})
    assert r.status_code == 200 and r.json()["label"] == "Grok" and r.json()["enabled"] is False
    assert not any(m["provider"] == "xai" for m in client.get("/api/models").json()["models"])
    client.patch("/api/providers/xai", json={"enabled": True})
    assert any(m["provider"] == "xai" for m in client.get("/api/models").json()["models"])
    assert client.patch("/api/providers/nope", json={"label": "x"}).status_code == 404


def test_custom_provider_via_api(client, hub):
    base = hub.url("custom")  # .../custom/v1
    r = add(client, K.CUSTOM, provider="custom", base_url=base + "/chat/completions", label="Company vLLM")
    assert r.status_code == 200, r.text
    p = r.json()["provider"]
    assert p["kind"] == "custom" and p["base_url"] == base


# ---------------- keys never leak ----------------
def test_keys_never_in_api_responses(client, hub):
    add(client, K.OPENAI)
    add(client, K.GEMINI)
    for url in ("/api/providers", "/api/models", "/api/settings", "/api/status", "/api/models?refresh=1"):
        body = client.get(url).text
        for k in (K.OPENAI, K.GEMINI):
            assert k not in body, url
            assert k[-12:] not in body, url


def test_key_echoed_by_provider_is_redacted(client, hub, test_home):
    hub["openai"].models = {"data": [{"id": "gpt-test"}]}
    add(client, K.ECHOED)
    hub["openai"].chat_status = 400
    hub["openai"].chat_body = json.dumps({"error": {"message": f"Bad request for key {K.ECHOED}: invalid parameter"}})
    r = client.post("/api/chat", json={"model": "openai:gpt-test", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert K.ECHOED not in r.text and "[key]" in r.text
    assert '"error"' in r.text and "Traceback" not in r.text


# ---------------- storage ----------------
def test_migration_from_v09_settings(client, test_home):
    from tests.conftest import MemoryKeyring

    (test_home / "Haven" / "settings.json").write_text(json.dumps({"gemini_key": K.GEMINI, "gemini_model": "gemini-2.5-pro"}))
    provs = client.get("/api/providers").json()["providers"]
    g = [p for p in provs if p["kind"] == "gemini"]
    assert len(g) == 1 and g[0]["id"] == "gemini" and g[0]["source"] == "keyring"
    raw = json.loads((test_home / "Haven" / "settings.json").read_text())
    assert "gemini_key" not in raw and raw["gemini_model"] == "gemini-2.5-pro"
    assert K.GEMINI not in (test_home / "Haven" / "settings.json").read_text()
    assert K.GEMINI in MemoryKeyring.store.values()
    # the old UI keeps working: status + settings + legacy model id
    assert client.get("/api/status").json()["gemini"] is True
    assert client.get("/api/settings").json()["key_hint"] == "…0004"


def test_legacy_settings_endpoint_saves_gemini_key(client):
    r = client.post("/api/settings", json={"gemini_key": f" {K.GEMINI}\n"})
    assert r.status_code == 200 and r.json()["has_key"] is True
    assert [p["kind"] for p in keystore.saved()] == ["gemini"]
    client.post("/api/settings", json={"clear_key": True})
    assert keystore.saved() == []


def test_keyring_unavailable_falls_back_to_file(client, monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))  # its own folder, so the key-grep test stays meaningful
    monkeypatch.setattr(keystore, "_keyring", lambda: None)
    r = add(client, K.FALLBACK_ONLY)
    assert r.status_code == 200, r.text
    assert r.json()["provider"]["source"] == "file"
    j = client.get("/api/providers").json()
    assert j["storage"] == "file" and j["storage_note"] == "Stored in a plain file on this PC"
    assert K.FALLBACK_ONLY in (tmp_path / "Haven" / "settings.json").read_text()  # documented behaviour
    assert K.FALLBACK_ONLY not in json.dumps(j)
    assert registry.find_config("openai").key == K.FALLBACK_ONLY


def test_environment_keys_are_read_only(client, monkeypatch, hub):
    monkeypatch.setenv("XAI_API_KEY", K.XAI)
    provs = client.get("/api/providers").json()["providers"]
    x = [p for p in provs if p["kind"] == "xai"]
    assert len(x) == 1 and x[0]["source"] == "env" and x[0]["id"] == "xai-env"
    assert "XAI_API_KEY" in x[0]["label"]
    assert client.delete("/api/providers/xai-env").status_code == 404
    assert any(m["provider"] == "xai-env" for m in client.get("/api/models").json()["models"])
    assert K.XAI not in client.get("/api/providers").text
