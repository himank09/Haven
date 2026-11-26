"""Where API keys live.

* Keys go to Windows Credential Manager through `keyring` (encrypted per user with DPAPI).
* settings.json only holds non-secret metadata: id, kind, label, base URL, key_id, enabled, a short
  fingerprint (to spot duplicates) and a 4-character hint.
* If keyring is unavailable, the key is written into settings.json and the app says so ("plain file").
* *_API_KEY environment variables appear as read-only providers.
* v0.9 `gemini_key` is migrated automatically on first load.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

SERVICE = "Haven"
_LOCK = threading.RLock()

ENV_KEYS = [  # (env var, kind) in priority order; first hit per kind wins
    ("OPENAI_API_KEY", "openai"), ("ANTHROPIC_API_KEY", "anthropic"), ("GEMINI_API_KEY", "gemini"),
    ("GOOGLE_API_KEY", "gemini"), ("OPENROUTER_API_KEY", "openrouter"), ("GROQ_API_KEY", "groq"),
    ("XAI_API_KEY", "xai"), ("DEEPSEEK_API_KEY", "deepseek"), ("MISTRAL_API_KEY", "mistral"),
    ("TOGETHER_API_KEY", "together"), ("FIREWORKS_API_KEY", "fireworks"), ("CEREBRAS_API_KEY", "cerebras"),
    ("HF_TOKEN", "huggingface"),
]


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "Haven"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load_raw() -> dict:
    try:
        s = json.loads(settings_path().read_text("utf-8"))
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def save_raw(s: dict):
    p = settings_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), "utf-8")
    os.replace(tmp, p)


def fingerprint(key: str) -> str:
    return hashlib.sha256(("haven:" + key).encode()).hexdigest()[:16]


def hint(key: str) -> str:
    return ("…" + key[-4:]) if key and len(key) > 8 else ("…" if key else "")


# ---------------- keyring ----------------
def _keyring():
    """The keyring module if a real (non-fail) backend is available, else None."""
    if os.environ.get("HAVEN_NO_KEYRING"):
        return None
    try:
        import keyring
        from keyring.backends import fail

        kr = keyring.get_keyring()
        if isinstance(kr, fail.Keyring):
            return None
        chain = getattr(kr, "backends", None)
        if chain is not None and not chain:
            return None
        return keyring
    except Exception:
        return None


def storage_mode() -> str:
    return "keyring" if _keyring() else "file"


def _kr_set(key_id: str, secret: str) -> bool:
    kr = _keyring()
    if not kr:
        return False
    try:
        kr.set_password(SERVICE, key_id, secret)
        return True
    except Exception:
        return False


def _kr_get(key_id: str) -> str:
    kr = _keyring()
    if not kr:
        return ""
    try:
        return kr.get_password(SERVICE, key_id) or ""
    except Exception:
        return ""


def _kr_del(key_id: str):
    kr = _keyring()
    if not kr:
        return
    try:
        kr.delete_password(SERVICE, key_id)
    except Exception:
        pass


# ---------------- providers in settings ----------------
def _migrate(s: dict) -> bool:
    """v0.9 -> v1. Returns True if settings changed."""
    changed = False
    if "providers" not in s:
        s["providers"] = []
        changed = True
    old = (s.pop("gemini_key", "") or "").strip()
    if old:
        changed = True
        if not any(p.get("fp") == fingerprint(old) for p in s["providers"]):
            _add_entry(s, "gemini", old, label="Gemini", base_url="")
    return changed


def load() -> dict:
    with _LOCK:
        s = load_raw()
        if _migrate(s):
            save_raw(s)
        return s


def _new_id(s: dict, kind: str) -> str:
    used = {p["id"] for p in s.get("providers", [])}
    if kind not in used:
        return kind
    n = 2
    while f"{kind}-{n}" in used:
        n += 1
    return f"{kind}-{n}"


def _add_entry(s: dict, kind: str, key: str, label: str = "", base_url: str = "") -> dict:
    key_id = uuid.uuid4().hex
    entry = {"id": _new_id(s, kind), "kind": kind, "label": label or "", "base_url": base_url or "",
             "key_id": key_id, "enabled": True, "fp": fingerprint(key) if key else "", "hint": hint(key),
             "storage": "keyring", "extra_models": []}
    if key and not _kr_set(key_id, key):
        entry["storage"] = "file"
        entry["key"] = key
    if not key:
        entry["storage"] = "none"
    s.setdefault("providers", []).append(entry)
    return entry


def find_duplicate(key: str, base_url: str = "") -> Optional[dict]:
    fp = fingerprint(key)
    for p in load().get("providers", []):
        if p.get("fp") == fp and (p.get("base_url", "") or "") == (base_url or ""):
            return p
    return None


def add(kind: str, key: str, label: str = "", base_url: str = "") -> dict:
    with _LOCK:
        s = load()
        e = _add_entry(s, kind, key, label, base_url)
        save_raw(s)
        return e


def update(pid: str, **changes) -> Optional[dict]:
    with _LOCK:
        s = load()
        for p in s.get("providers", []):
            if p["id"] == pid:
                for k in ("label", "enabled", "base_url", "extra_models"):
                    if k in changes and changes[k] is not None:
                        p[k] = changes[k]
                save_raw(s)
                return p
    return None


def remove(pid: str) -> bool:
    with _LOCK:
        s = load()
        keep, gone = [], None
        for p in s.get("providers", []):
            (keep if p["id"] != pid else []).append(p)
            if p["id"] == pid:
                gone = p
        if not gone:
            return False
        _kr_del(gone.get("key_id", ""))
        s["providers"] = keep
        save_raw(s)
        return True


def secret(entry: dict) -> str:
    if entry.get("storage") == "file":
        return entry.get("key", "")
    if entry.get("storage") == "keyring":
        return _kr_get(entry.get("key_id", ""))
    return ""


def saved() -> List[dict]:
    """Saved providers (metadata only; no key)."""
    return [{k: v for k, v in p.items() if k != "key"} for p in load().get("providers", [])]


def saved_with_secrets() -> List[dict]:
    out = []
    for p in load().get("providers", []):
        q = {k: v for k, v in p.items() if k != "key"}
        q["secret"] = secret(p)
        out.append(q)
    return out


def env_providers() -> List[dict]:
    seen: Dict[str, dict] = {}
    for var, kind in ENV_KEYS:
        v = (os.environ.get(var) or "").strip()
        if v and kind not in seen:
            seen[kind] = {"id": f"{kind}-env", "kind": kind, "label": f"from environment ({var})", "base_url": "",
                          "enabled": True, "fp": fingerprint(v), "hint": hint(v), "storage": "env", "secret": v,
                          "env_var": var, "extra_models": []}
    return list(seen.values())


def get_setting(name: str, default=None):
    return load().get(name, default)


def set_setting(name: str, value):
    with _LOCK:
        s = load()
        s[name] = value
        save_raw(s)
