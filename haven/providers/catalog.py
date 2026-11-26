"""Popular models shown in the picker before a provider is connected, plus per-provider info for Settings.

These are *suggestions* only (ids checked against the providers' model pages on 2026-11-26). As soon as a
key is added, the provider's own live model list replaces them, so an outdated id here can never be used
by mistake: it just becomes "needs a key" -> real list.
"""
from typing import Dict, List

# kind -> [(model id, display name, short note, sees images, can think)]
# The FIRST model of each provider is the default Haven picks after you add a key: the everyday model,
# never the most expensive one, and for Gemini one that works on Google's free plan.
CATALOG: Dict[str, List[tuple]] = {
    "openai": [
        ("gpt-6.2-sol", "GPT-6.2 Sol", "Everyday default", True, True),
        ("gpt-6.2-astra", "GPT-6.2 Astra", "Flagship, hardest problems", True, True),
        ("gpt-6.1-terra", "GPT-6.1 Terra", "Fast", True, True),
        ("gpt-6-luna", "GPT-6 Luna", "Cheapest", True, False),
    ],
    "anthropic": [
        ("claude-sonnet-5-5", "Claude Sonnet 5.5", "Everyday default", True, True),
        ("claude-opus-5-5", "Claude Opus 5.5", "Most capable", True, True),
        ("claude-haiku-5-5", "Claude Haiku 5.5", "Fast and cheap", True, True),
        ("claude-fable-5-2", "Claude Fable 5.2", "Writing and stories", True, True),
    ],
    "gemini": [
        ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "Fast, works on the free plan", True, False),
        ("gemini-4-hydrogen", "Gemini 4 Hydrogen", "Everyday, may be busy on the free plan", True, True),
        ("gemini-4-argon", "Gemini 4 Argon", "Efficient reasoning (paid plan)", True, True),
        ("gemini-4-carbon", "Gemini 4 Carbon", "Strongest reasoning (paid plan)", True, True),
    ],
    "xai": [
        ("grok-4.3", "Grok 4.3", "Everyday, 1M context", True, True),
        ("grok-4.7", "Grok 4.7", "Most capable", True, True),
    ],
    "deepseek": [
        ("deepseek-flash", "DeepSeek Flash", "Cheap and fast", True, True),
        ("deepseek-v4-pro", "DeepSeek V4 Pro", "Flagship", False, True),
    ],
    "groq": [
        ("openai/gpt-oss-120b", "GPT OSS 120B", "Very fast open model", False, True),
        ("llama-3.3-70b-versatile", "Llama 3.3 70B", "General chat", False, False),
        ("llama-3.1-8b-instant", "Llama 3.1 8B", "Instant answers", False, False),
    ],
    "mistral": [
        ("mistral-medium-latest", "Mistral Medium", "Everyday default", True, False),
        ("devstral-latest", "Devstral", "Coding", False, False),
    ],
}

# Local models to suggest when Ollama has none (pull names from ollama.com/library)
OLLAMA_SUGGESTED = [
    ("qwen3.5:4b", "Qwen 3.5 4B", "Good all-rounder for laptops (~3 GB)", True, True),
    ("gemma3:4b", "Gemma 3 4B", "Reads images too (~3 GB)", True, False),
    ("gpt-oss:20b", "GPT-OSS 20B", "Stronger, needs 16 GB RAM (~13 GB)", False, True),
]

INFO: Dict[str, dict] = {
    "ollama": {"desc": "Free models that run on this PC", "url": "https://ollama.com/download", "url_label": "Get Ollama"},
    "lmstudio": {"desc": "Run downloaded models with LM Studio", "url": "https://lmstudio.ai", "url_label": "Get LM Studio"},
    "openai": {"desc": "GPT models", "url": "https://platform.openai.com/api-keys"},
    "anthropic": {"desc": "Claude models", "url": "https://console.anthropic.com/settings/keys"},
    "gemini": {"desc": "Gemini models, free tier available", "url": "https://aistudio.google.com/apikey"},
    "openrouter": {"desc": "One key for hundreds of models", "url": "https://openrouter.ai/settings/keys"},
    "groq": {"desc": "Very fast open models", "url": "https://console.groq.com/keys"},
    "xai": {"desc": "Grok models", "url": "https://console.x.ai"},
    "deepseek": {"desc": "DeepSeek models", "url": "https://platform.deepseek.com/api_keys"},
    "mistral": {"desc": "Mistral models", "url": "https://console.mistral.ai/api-keys"},
    "together": {"desc": "Open models in the cloud", "url": "https://api.together.ai/settings/api-keys"},
    "fireworks": {"desc": "Open models in the cloud", "url": "https://fireworks.ai/account/api-keys"},
    "cerebras": {"desc": "Very fast open models", "url": "https://cloud.cerebras.ai"},
    "huggingface": {"desc": "Inference Providers router", "url": "https://huggingface.co/settings/tokens"},
    "custom": {"desc": "vLLM, LiteLLM or a company server", "url": ""},
}


def suggestions(kind: str, local: bool = False) -> List[dict]:
    rows = OLLAMA_SUGGESTED if kind == "ollama" else CATALOG.get(kind, [])
    return [{"id": mid, "label": label, "note": note, "provider": kind, "kind": kind, "vision": vis,
             "think": "toggle" if think else "no", "local": local, "created": None, "preview": False, "pdf": False,
             "context": None, "locked": True, "full_id": f"{kind}:{mid}"} for mid, label, note, vis, think in rows]


def find(full_id: str):
    kind, _, mid = (full_id or "").partition(":")
    rows = OLLAMA_SUGGESTED if kind == "ollama" else CATALOG.get(kind, [])
    for r in rows:
        if r[0] == mid:
            return kind, r
    return None
