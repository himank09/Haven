"""Provider table, key detection, model listing with cache, local-provider polling.

Base URLs can be overridden with environment variables HAVEN_BASE_<KIND> (used by the tests' fake servers
and handy for proxies), e.g. HAVEN_BASE_OPENAI=http://127.0.0.1:9000/v1.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import anthropic, gemini, keystore, ollama, openai_compat
from .base import ModelInfo, ProviderConfig, ProviderError

ADAPTERS = {"openai": openai_compat, "anthropic": anthropic, "gemini": gemini, "ollama": ollama}

# kind, display name, style, base URL, key prefixes (most specific first is handled by sorting), local
TABLE = [
    ("ollama", "Ollama", "ollama", "http://127.0.0.1:11434", (), True),
    ("lmstudio", "LM Studio", "openai", "http://127.0.0.1:1234/v1", (), True),
    ("openai", "OpenAI", "openai", "https://api.openai.com/v1", ("sk-proj-", "sk-svcacct-", "sk-admin-", "sk-"), False),
    ("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1", ("sk-ant-",), False),
    ("gemini", "Google Gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta", ("AIza",), False),
    ("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", ("sk-or-",), False),
    ("groq", "Groq", "openai", "https://api.groq.com/openai/v1", ("gsk_",), False),
    ("xai", "xAI", "openai", "https://api.x.ai/v1", ("xai-",), False),
    ("deepseek", "DeepSeek", "openai", "https://api.deepseek.com", ("sk-",), False),
    ("mistral", "Mistral", "openai", "https://api.mistral.ai/v1", (), False),
    ("together", "Together", "openai", "https://api.together.ai/v1", ("tgp_",), False),
    ("fireworks", "Fireworks", "openai", "https://api.fireworks.ai/inference/v1", ("fw_",), False),
    ("cerebras", "Cerebras", "openai", "https://api.cerebras.ai/v1", ("csk-",), False),
    ("huggingface", "Hugging Face", "openai", "https://router.huggingface.co/v1", ("hf_",), False),
    ("custom", "Custom (OpenAI-compatible)", "openai", "", (), False),
]
KINDS = {row[0]: row for row in TABLE}
ORDER = {row[0]: i for i, row in enumerate(TABLE)}
NO_PREFIX = ["mistral", "together"]  # keys without a recognisable prefix: probe these
PROBE_TIMEOUT = 6.0
CACHE_TTL = 6 * 3600
LOCAL_POLL = float(os.environ.get("HAVEN_LOCAL_POLL", "20"))
LOCAL_TIMEOUT = 1.5


def base_url(kind: str) -> str:
    env = os.environ.get(f"HAVEN_BASE_{kind.upper()}")
    if kind == "ollama":
        env = env or os.environ.get("OLLAMA_URL")
    if kind == "gemini" and not env and os.environ.get("GEMINI_BASE"):  # v0.9 variable (host only)
        env = os.environ["GEMINI_BASE"].rstrip("/") + "/v1beta"
    return (env or KINDS[kind][3]).rstrip("/")


def name_of(kind: str) -> str:
    return KINDS.get(kind, (kind, kind))[1]


# ---------------- keys ----------------
def clean_key(raw: str) -> str:
    k = (raw or "").strip()
    for _ in range(2):
        k = k.strip().strip("\"'`").strip()
        if k.lower().startswith("bearer "):
            k = k[7:]
    k = k.strip()
    if not k:
        raise ValueError("Paste a key first.")
    if re.search(r"\s", k):
        raise ValueError("That doesn't look like a single key (it has spaces or line breaks inside).")
    return k


def candidates(key: str) -> List[str]:
    """Provider kinds a key could belong to, most specific prefix first; ambiguous prefixes give several."""
    pairs = sorted(((p, kind) for kind, *_rest in TABLE for p in KINDS[kind][4]), key=lambda x: -len(x[0]))
    for p, kind in pairs:
        if key.startswith(p):
            plen = len(p)
            return [k for pp, k in pairs if len(pp) == plen and key.startswith(pp)] or [kind]
    return list(NO_PREFIX)


def normalize_base(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        raise ValueError("Enter the server's base URL.")
    if not re.match(r"^https?://", u, re.I):
        local = re.match(r"^(localhost|127\.|\[::1\]|0\.0\.0\.0)", u)
        u = ("http://" if local else "https://") + u
    for tail in ("/chat/completions", "/completions", "/models"):
        if u.lower().endswith(tail):
            u = u[: -len(tail)]
    u = u.rstrip("/")
    from urllib.parse import urlparse

    if urlparse(u).path in ("", "/"):
        u += "/v1"
    return u


def make_config(entry: dict, key: str = "") -> ProviderConfig:
    kind = entry["kind"]
    _k, name, style, _b, _p, local = KINDS[kind]
    url = (entry.get("base_url") or "").rstrip("/") or base_url(kind)
    label = entry.get("label") or ""
    disp = name if kind != "custom" else (label or "Custom server")
    return ProviderConfig(id=entry["id"], kind=kind, name=disp, style=style, base_url=url, key=key, label=label,
                          local=local, extra_models=list(entry.get("extra_models") or []))


@dataclass
class Detection:
    ok: bool
    kind: str = ""
    message: str = ""
    models: List[ModelInfo] = field(default_factory=list)
    unrecognised: bool = False
    tried: List[str] = field(default_factory=list)


async def _probe(kind: str, key: str, base: str = "") -> Tuple[str, bool, str, List[ModelInfo]]:
    cfg = make_config({"id": kind, "kind": kind, "base_url": base}, key)
    adapter = ADAPTERS[cfg.style]
    try:
        models = await asyncio.wait_for(adapter.list_models(cfg, PROBE_TIMEOUT), PROBE_TIMEOUT)
        return kind, True, "", models
    except asyncio.TimeoutError:
        return kind, False, f"{cfg.name} took too long", []
    except ProviderError as e:
        return kind, False, e.message, []
    except Exception:
        return kind, False, f"Couldn't check the key with {cfg.name}", []


async def detect_provider(raw_key: str, kind: Optional[str] = None, base: str = "") -> Detection:
    """Clean the key, work out its provider (probing ambiguous ones in parallel, max 6 s), validate it."""
    try:
        key = clean_key(raw_key)
    except ValueError as e:
        return Detection(False, message=str(e))
    if kind:
        if kind not in KINDS:
            return Detection(False, message="Unknown provider")
        if kind == "custom":
            try:
                base = normalize_base(base)
            except ValueError as e:
                return Detection(False, kind=kind, message=str(e))
        cands = [kind]
    else:
        cands = candidates(key)
    results = await asyncio.gather(*[_probe(k, key, base) for k in cands])
    ok = sorted([r for r in results if r[1]], key=lambda r: ORDER[r[0]])
    if ok:
        k, _, _, models = ok[0]
        return Detection(True, kind=k, models=models, tried=cands, message=f"{name_of(k)}: {len(models)} chat models")
    names = [name_of(k) for k in cands]
    if not kind and cands == NO_PREFIX:
        return Detection(False, unrecognised=True, tried=cands,
                         message="Couldn't recognise this key. Pick the provider, or use Custom with a base URL.")
    if all("rejected" in r[2].lower() for r in results):
        return Detection(False, kind=cands[0] if len(cands) == 1 else "", tried=cands,
                         message=f"Key rejected by {' and '.join(names)}")
    return Detection(False, kind=cands[0] if len(cands) == 1 else "", tried=cands,
                     message="; ".join(r[2] for r in results if r[2]) or "Couldn't check the key")


# ---------------- configured providers ----------------
def configured(include_disabled: bool = False) -> List[Tuple[dict, ProviderConfig]]:
    """Saved + environment providers with their secrets loaded (secrets never leave the server)."""
    out = []
    for e in keystore.saved_with_secrets() + keystore.env_providers():
        if e.get("kind") not in KINDS:
            continue
        if not include_disabled and not e.get("enabled", True):
            continue
        out.append((e, make_config(e, e.pop("secret", ""))))
    return out


def local_configs() -> List[ProviderConfig]:
    return [make_config({"id": "ollama", "kind": "ollama"}), make_config({"id": "lmstudio", "kind": "lmstudio"})]


def find_config(pid: str) -> Optional[ProviderConfig]:
    for cfg in local_configs():
        if cfg.id == pid:
            return cfg
    allc = configured()
    for _e, cfg in allc:
        if cfg.id == pid:
            return cfg
    for _e, cfg in allc:  # v0.9 ids like "gemini:..." when the key came from the environment
        if cfg.kind == pid:
            return cfg
    return None


# ---------------- model cache ----------------
class ModelCache:
    def __init__(self):
        self.mem: Dict[str, dict] = {}   # pid -> {"ts", "sig", "models": [ModelInfo], "error"}
        self.local: Dict[str, dict] = {}  # pid -> {"ts", "ok", "models", "error"}
        self._loaded = False
        self._bg: Optional[asyncio.Task] = None

    @staticmethod
    def path():
        return keystore.config_dir() / "models_cache.json"

    @staticmethod
    def sig(cfg: ProviderConfig) -> str:
        raw = f"{cfg.kind}|{cfg.base_url}|{keystore.fingerprint(cfg.key) if cfg.key else ''}|{','.join(cfg.extra_models)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _load_disk(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            j = json.loads(self.path().read_text("utf-8"))
            for pid, v in (j.get("providers") or {}).items():
                if pid in self.mem:
                    continue  # memory is newer than the disk copy
                self.mem[pid] = {"ts": float(v["ts"]), "sig": v["sig"], "error": v.get("error", ""),
                                 "models": [ModelInfo.from_dict(m) for m in v["models"]]}
        except Exception:
            pass  # corrupt or missing: ignore; it is rebuilt on the next save

    def _save_disk(self):
        from dataclasses import asdict

        data = {"version": 1, "providers": {pid: {"ts": v["ts"], "sig": v["sig"], "error": v.get("error", ""),
                                                  "models": [asdict(m) for m in v["models"]]}
                                            for pid, v in self.mem.items() if v.get("models") is not None}}
        try:
            tmp = self.path().with_suffix(".tmp")
            tmp.write_text(json.dumps(data), "utf-8")
            os.replace(tmp, self.path())
        except Exception:
            pass

    def drop(self, pid: str):
        self._load_disk()
        self.mem.pop(pid, None)
        self._save_disk()

    async def fetch(self, cfg: ProviderConfig):
        adapter = ADAPTERS[cfg.style]
        try:
            models = await adapter.list_models(cfg)
            self.mem[cfg.id] = {"ts": time.time(), "sig": self.sig(cfg), "models": models, "error": ""}
        except ProviderError as e:
            old = self.mem.get(cfg.id)
            keep = old["models"] if old and old.get("sig") == self.sig(cfg) else []
            self.mem[cfg.id] = {"ts": time.time(), "sig": self.sig(cfg), "models": keep, "error": e.message, "failed": True}
        except Exception:
            self.mem[cfg.id] = {"ts": time.time(), "sig": self.sig(cfg), "models": [], "error": "Couldn't list models", "failed": True}

    def _fresh(self, cfg) -> bool:
        v = self.mem.get(cfg.id)
        return bool(v) and v.get("sig") == self.sig(cfg) and time.time() - v["ts"] < CACHE_TTL and not v.get("failed")

    async def cloud(self, refresh: bool = False) -> List[Tuple[dict, ProviderConfig, dict]]:
        self._load_disk()
        provs = configured()
        changed = False
        if refresh:
            await asyncio.gather(*[self.fetch(c) for _e, c in provs])
            changed = bool(provs)
        else:
            missing = [c for _e, c in provs if not (self.mem.get(c.id) and self.mem[c.id].get("sig") == self.sig(c))]
            stale = [c for _e, c in provs if c not in missing and not self._fresh(c)]
            if missing:
                await asyncio.gather(*[self.fetch(c) for c in missing])
                changed = True
            if stale and (self._bg is None or self._bg.done()):
                async def bg():
                    await asyncio.gather(*[self.fetch(c) for c in stale])
                    self._save_disk()
                self._bg = asyncio.ensure_future(bg())
        if changed:
            self._save_disk()
        return [(e, c, self.mem.get(c.id, {"models": [], "error": ""})) for e, c in provs]

    async def poll_local(self, timeout: float = LOCAL_TIMEOUT):
        async def one(cfg):
            adapter = ADAPTERS[cfg.style]
            try:
                models = await asyncio.wait_for(adapter.list_models(cfg, timeout), timeout + 2)
                self.local[cfg.id] = {"ts": time.time(), "ok": True, "models": models, "error": ""}
            except Exception as e:
                self.local[cfg.id] = {"ts": time.time(), "ok": False, "models": [], "error": "not running"}
        await asyncio.gather(*[one(c) for c in local_configs()])

    async def local_status(self):
        if not self.local:
            await self.poll_local()
        return self.local


CACHE = ModelCache()


async def poll_forever():
    while True:
        try:
            await CACHE.poll_local()
        except Exception:
            pass
        await asyncio.sleep(LOCAL_POLL)


async def all_models(refresh: bool = False) -> dict:
    if refresh:
        await CACHE.poll_local()
    local = await CACHE.local_status()
    cloud = await CACHE.cloud(refresh)
    providers, models = [], []
    for cfg in local_configs():
        st = local.get(cfg.id, {"ok": False, "models": [], "error": "not running"})
        providers.append({"id": cfg.id, "kind": cfg.kind, "name": cfg.name, "local": True,
                          "status": "ok" if st["ok"] else "not running", "message": st.get("error", "")})
        models += st["models"]
    for e, cfg, st in sorted(cloud, key=lambda x: (ORDER[x[1].kind], x[1].id)):
        err = st.get("error", "")
        providers.append({"id": cfg.id, "kind": cfg.kind, "name": cfg.name, "label": cfg.label, "local": False,
                          "status": "unavailable" if err else "ok", "message": err})
        models += st.get("models", [])
    # popular models for providers that aren't connected yet (shown locked: "needs a key")
    from . import catalog

    connected = {cfg.kind for _e, cfg, _st in cloud}
    sugg = []
    if not local.get("ollama", {}).get("models"):
        sugg += catalog.suggestions("ollama", local=True)
    kinds = []
    for kind, name, _style, _b, _p, is_local in TABLE:
        info = {"kind": kind, "name": name, "local": is_local, "connected": kind in connected, **catalog.INFO.get(kind, {})}
        kinds.append(info)
        if not is_local and kind != "custom" and kind not in connected:
            sugg += catalog.suggestions(kind)
    return {"providers": providers, "models": [m.to_dict() for m in models], "catalog": sugg, "kinds": kinds}


async def resolve(full_id: str) -> Tuple[Optional[ProviderConfig], Optional[ModelInfo]]:
    pid, _, mid = (full_id or "").partition(":")
    if not pid or not mid:
        return None, None
    cfg = find_config(pid)
    if not cfg:
        return None, None
    pool = []
    if cfg.local:
        pool = (await CACHE.local_status()).get(cfg.id, {}).get("models", [])
    else:
        CACHE._load_disk()
        pool = CACHE.mem.get(cfg.id, {}).get("models", [])
    for m in pool:
        if m.id == mid:
            return cfg, m
    from . import filters  # unknown to the cache (typed id, cache not filled yet): best guess

    return cfg, ModelInfo(id=mid, label=mid, provider=cfg.id, kind=cfg.kind, local=cfg.local,
                          vision=True if cfg.kind == "gemini" else filters.guess_vision(mid),
                          think=("toggle" if filters.guess_reasoning(mid) else "no"), pdf=cfg.kind in ("anthropic", "gemini"))
