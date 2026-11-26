"""§8.10 Live smoke test against real providers. NOT part of the normal run.

Runs only with HAVEN_RUN_LIVE=1 and a key per provider, e.g. (PowerShell):

    $env:HAVEN_RUN_LIVE = "1"; $env:HAVEN_LIVE_OPENAI_KEY = "sk-..."
    .venv\\Scripts\\python.exe -m pytest -q -rs tests/live_smoke.py

Ollama / LM Studio are tested when they are running (no key needed): HAVEN_LIVE_OLLAMA=1, HAVEN_LIVE_LMSTUDIO=1.
Every provider without a key is SKIPPED with the reason "NOT RUN (no key)": never reported as passed.
Per provider: list chat models, stream a one-sentence answer, and cancel a long answer.
"""
import asyncio
import os
import time

import pytest

from haven.providers import base, registry

PROVIDERS = ["openai", "anthropic", "gemini", "openrouter", "groq", "xai", "deepseek", "mistral", "together",
             "fireworks", "cerebras", "huggingface", "ollama", "lmstudio"]
PREFER = {  # cheap, fast models when present
    "openai": ["gpt-4o-mini", "gpt-5-mini"], "anthropic": ["claude-haiku"], "gemini": ["gemini-2.5-flash", "flash"],
    "openrouter": ["openai/gpt-4o-mini", "mini"], "groq": ["llama-3.1-8b", "8b"], "xai": ["mini", "grok"],
    "deepseek": ["deepseek-chat"], "mistral": ["mistral-small", "small"], "together": ["8B", "Llama"],
    "cerebras": ["llama3.1-8b", "8b"], "huggingface": ["8B"], "fireworks": ["8b"],
}


def config(kind):
    if not os.environ.get("HAVEN_RUN_LIVE"):
        pytest.skip("NOT RUN (set HAVEN_RUN_LIVE=1 and HAVEN_LIVE_<PROVIDER>_KEY)")
    if kind in ("ollama", "lmstudio"):
        if not os.environ.get(f"HAVEN_LIVE_{kind.upper()}"):
            pytest.skip(f"NOT RUN ({kind} not requested: set HAVEN_LIVE_{kind.upper()}=1)")
        return registry.make_config({"id": kind, "kind": kind})
    key = os.environ.get(f"HAVEN_LIVE_{kind.upper()}_KEY")
    if not key:
        pytest.skip("NOT RUN (no key)")
    return registry.make_config({"id": kind, "kind": kind}, key)


def pick(kind, models):
    for want in PREFER.get(kind, []):
        for m in models:
            if want.lower() in m.id.lower() and m.think == "no":
                return m
    return next((m for m in models if m.think == "no"), models[0])


@pytest.mark.live
@pytest.mark.parametrize("kind", PROVIDERS)
def test_live_provider(kind):
    cfg = config(kind)
    adapter = registry.ADAPTERS[cfg.style]

    async def go():
        models = await adapter.list_models(cfg)
        assert models, "no chat models listed"
        m = pick(kind, models)
        print(f"\n{kind}: {len(models)} chat models; using {m.id}")
        text, done = "", None
        async for ev in adapter.stream_chat(cfg, m, [{"role": "user", "content": "Reply with one short sentence about the sea."}], [], None, False):
            text += ev.get("content", "")
            if ev.get("done"):
                done = ev
        assert text.strip() and done, "no answer"
        print(f"  answer: {text.strip()[:120]!r} done={done}")
        # cancel a long answer after a few tokens: the upstream stream must close promptly
        gen = adapter.stream_chat(cfg, m, [{"role": "user", "content": "Count slowly from 1 to 400, one number per line."}], [], None, False)
        n = 0
        async for ev in gen:
            if ev.get("content"):
                n += 1
                if n >= 3:
                    break
        t0 = time.perf_counter()
        await gen.aclose()
        took = time.perf_counter() - t0
        print(f"  cancelled after {n} chunks; closed in {took * 1000:.0f} ms")
        assert took < 2
        await base.close_clients()

    asyncio.run(go())
