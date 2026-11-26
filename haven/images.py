"""Image generation with Google's Gemini image models ("Nano Banana"). Files are kept on disk, not in the database.

Request: POST {base}/models/{model}:generateContent with generationConfig.responseModalities ["TEXT", "IMAGE"];
images come back as candidates[0].content.parts[].inlineData {mimeType, data (base64)}.
All Gemini images carry Google's invisible SynthID watermark.
"""
from __future__ import annotations

import asyncio
import base64
import re
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

from haven.providers import keystore
from haven.providers.base import ProviderConfig, ProviderError, client, human_error, network_error

# cheapest / most likely to work first; the user's key decides which exist
PREFERRED = ("gemini-3.1-flash-lite-image", "gemini-3.1-flash-image", "gemini-2.5-flash-image",
             "gemini-nano-banana-2.1", "gemini-3-pro-image")
NAME_OK = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp)$")
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
ASK = re.compile(r"^\s*(please\s+)?(can you\s+|could you\s+)?(draw|paint|sketch|illustrate|"
                 r"(generate|create|make|design|render)\s+(me\s+)?(an?\s+|the\s+|some\s+)?"
                 r"(\w+\s+){0,3}(image|picture|pic|photo|drawing|illustration|logo|icon|wallpaper|poster|art(work)?))\b", re.I)


def looks_like_image_request(text: str) -> bool:
    return bool(ASK.search(text or ""))


def folder() -> Path:
    d = Path(keystore.config_dir()) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_of(name: str) -> Optional[Path]:
    if not NAME_OK.match(name or ""):
        return None
    p = folder() / name
    return p if p.is_file() else None


def save(data: bytes, mime: str) -> str:
    name = f"{uuid.uuid4().hex}.{EXT.get(mime, 'png')}"
    (folder() / name).write_bytes(data)
    return name


async def image_models(cfg: ProviderConfig) -> List[str]:
    try:
        r = await client().get(cfg.base_url + "/models", params={"pageSize": 1000},
                               headers={"x-goog-api-key": cfg.key, **cfg.headers}, timeout=15)
    except httpx.HTTPError as e:
        raise network_error(e, cfg.name)
    if r.status_code != 200:
        raise human_error(r.status_code, cfg.name, r.text, r.headers.get("retry-after"), cfg.secrets())
    have = [str(m.get("name", "")).replace("models/", "") for m in r.json().get("models") or []
            if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    have = [n for n in have if "image" in n or "banana" in n]
    return [n for n in PREFERRED if n in have] + [n for n in have if n not in PREFERRED]


async def generate(cfg: ProviderConfig, model: str, prompt: str, aspect: str = "") -> Tuple[List[Tuple[bytes, str]], str]:
    """-> ([(bytes, mime)], text). Raises ProviderError with a readable message."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    if aspect:
        body["generationConfig"]["imageConfig"] = {"aspectRatio": aspect}
    url = f"{cfg.base_url}/models/{model}:generateContent"
    try:
        r = await client().post(url, json=body, headers={"x-goog-api-key": cfg.key, "Content-Type": "application/json",
                                                         **cfg.headers}, timeout=120)
    except httpx.HTTPError as e:
        raise network_error(e, cfg.name)
    if r.status_code != 200:
        if r.status_code == 429:
            raise ProviderError("Google says this key has no image-generation quota (free Gemini keys usually can't make "
                                "images). Turn on billing for the key in Google AI Studio, then try again.", 429, "quota")
        raise human_error(r.status_code, cfg.name, r.text, r.headers.get("retry-after"), cfg.secrets(), model)
    j = r.json()
    block = (j.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise ProviderError(f"Gemini blocked this request ({block}).", 400, "bad_request")
    images, text = [], []
    for cand in (j.get("candidates") or [])[:1]:
        for p in (cand.get("content") or {}).get("parts") or []:
            inline = p.get("inlineData") or p.get("inline_data")
            if inline and inline.get("data"):
                images.append((base64.b64decode(inline["data"]), inline.get("mimeType") or inline.get("mime_type") or "image/png"))
            elif p.get("text") and not p.get("thought"):
                text.append(p["text"])
        if not images and cand.get("finishReason") not in (None, "STOP"):
            raise ProviderError(f"Gemini made no image (it stopped: {cand['finishReason']}). Try rewording the request.", 400, "bad_request")
    return images, "".join(text).strip()


# ---------------- free services ----------------
# Hugging Face: account token, Stable Diffusion 3 Medium via the HF router. Needs pre-paid credits or PRO (checked 2026-11-27).
# Cloudflare Workers AI: free account; account id + API token; daily free allowance.
# Pollinations: no account at all; prompts go to a small third-party service.
HF_URL = "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-3-medium-diffusers"  # FLUX.1-schnell was retired there (410)
CF_URL = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell"
POLL_URL = "https://image.pollinations.ai/prompt/{prompt}"
SERVICES = {"gemini": "Google Gemini", "hf": "Hugging Face", "cf": "Cloudflare Workers AI", "pollinations": "Pollinations"}
ORDER = ("gemini", "hf", "cf", "pollinations")
SIZE = {"": (1024, 1024), "1:1": (1024, 1024), "16:9": (1344, 768), "9:16": (768, 1344), "4:3": (1152, 864), "3:4": (864, 1152)}


def settings() -> dict:
    s = keystore.get_setting("images") or {}
    return {"service": s.get("service", "auto"), "pollinations": s.get("pollinations", True), "cf_account": s.get("cf_account", "")}


def token(service: str) -> str:
    """Saved token for 'hf' or 'cf' (Credential Manager, or the settings file when keyring is unavailable)."""
    t = keystore._kr_get("image-" + service)
    if not t:
        t = (keystore.get_setting("image_tokens") or {}).get(service, "")
    if not t and service == "hf":  # a Hugging Face key added under Models & keys works too
        t = next((e.get("secret", "") for e in keystore.saved_with_secrets()
                  if e.get("kind") == "huggingface" and e.get("enabled", True) and e.get("secret")), "")
    return t


def set_token(service: str, value: str):
    toks = dict(keystore.get_setting("image_tokens") or {})
    toks.pop(service, None)
    if value and not keystore._kr_set("image-" + service, value):
        toks[service] = value
    if not value:
        keystore._kr_del("image-" + service)
    keystore.set_setting("image_tokens", toks)


def status() -> dict:
    s = settings()
    out = {"service": s["service"], "pollinations": s["pollinations"], "cf_account": s["cf_account"], "services": {}}
    for k in ("hf", "cf"):
        t = token(k)
        out["services"][k] = {"saved": bool(t), "hint": keystore.hint(t) if t else ""}
    return out


def chain(gem: Optional[ProviderConfig]) -> List[str]:
    s = settings()
    ok = {"gemini": gem is not None, "hf": bool(token("hf")), "cf": bool(token("cf") and s["cf_account"]),
          "pollinations": bool(s["pollinations"])}
    if s["service"] in ok and s["service"] != "auto":
        return [s["service"]] if ok[s["service"]] else []
    return [k for k in ORDER if ok[k]]


def _raise(r: httpx.Response, name: str, secrets=()):
    if r.status_code in (401, 403):
        raise ProviderError(f"{name} didn't accept the token. Check it in Settings → Images.", r.status_code, "auth")
    if r.status_code == 402 or r.status_code == 429:
        raise ProviderError(f"{name}'s free allowance is used up for now.", r.status_code, "quota")
    raise human_error(r.status_code, name, r.text[:500], r.headers.get("retry-after"), secrets)


def _image_bytes(r: httpx.Response, name: str) -> Tuple[bytes, str]:
    mime = (r.headers.get("content-type") or "").split(";")[0].strip()
    if not mime.startswith("image/") or not r.content:
        raise ProviderError(f"{name} answered without a picture. Try again in a moment.", 0, "server")
    return r.content, mime


async def hf_generate(prompt: str, aspect: str = "") -> Tuple[bytes, str]:
    t = token("hf")
    w, h = SIZE.get(aspect, SIZE[""])
    try:
        r = await client().post(HF_URL, json={"inputs": prompt, "parameters": {"width": w, "height": h}},
                                headers={"Authorization": f"Bearer {t}", "Accept": "image/png"}, timeout=120)
    except httpx.HTTPError as e:
        raise network_error(e, "Hugging Face")
    if r.status_code == 402:
        raise ProviderError("Hugging Face needs pre-paid credits or a PRO plan for images on this account.", 402, "quota")
    if r.status_code != 200:
        _raise(r, "Hugging Face", (t,))
    return _image_bytes(r, "Hugging Face")


async def cf_generate(prompt: str, aspect: str = "") -> Tuple[bytes, str]:
    t, acct = token("cf"), settings()["cf_account"]
    w, h = SIZE.get(aspect, SIZE[""])
    if not re.fullmatch(r"[0-9a-f]{32}", acct or ""):
        raise ProviderError("The Cloudflare account ID looks wrong (it's 32 letters and digits).", 400, "bad_request")
    try:
        r = await client().post(CF_URL.format(acct=acct), json={"prompt": prompt, "steps": 6, "width": w, "height": h},
                                headers={"Authorization": f"Bearer {t}"}, timeout=120)
    except httpx.HTTPError as e:
        raise network_error(e, "Cloudflare")
    if r.status_code != 200:
        _raise(r, "Cloudflare", (t,))
    data = ((r.json() or {}).get("result") or {}).get("image")
    if not data:
        raise ProviderError("Cloudflare answered without a picture.", 0, "server")
    raw = base64.b64decode(data)
    return raw, "image/jpeg" if raw[:2] == b"\xff\xd8" else "image/png"


async def pollinations_generate(prompt: str, aspect: str = "") -> Tuple[bytes, str]:
    from urllib.parse import quote

    w, h = SIZE.get(aspect, SIZE[""])
    for attempt in (1, 2):  # the free service is often briefly overloaded: one quiet retry
        try:
            r = await client().get(POLL_URL.format(prompt=quote(prompt[:1500], safe="")),
                                   params={"width": w, "height": h},  # anonymous tier: extra options (nologo, private, model) are refused with 402
                                   timeout=150, follow_redirects=True)
        except httpx.HTTPError as e:
            raise network_error(e, "Pollinations")
        if r.status_code < 500 or attempt == 2:
            break
        await asyncio.sleep(4)
    if r.status_code == 402:  # free tier: 1 picture every ~45 s per computer
        wait = re.search(r"[Rr]etry after (\d+)\s*s", r.text)
        raise ProviderError("Pollinations allows one free picture every 45 seconds. Try again "
                            + (f"in about {wait.group(1)} seconds." if wait else "in a minute."), 402, "quota")
    if r.status_code >= 500:
        raise ProviderError("Pollinations is busy right now. Try again in a minute.", r.status_code, "busy")
    if r.status_code != 200:
        _raise(r, "Pollinations")
    return _image_bytes(r, "Pollinations")
