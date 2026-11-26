"""Image generation with Google's Gemini image models ("Nano Banana"). Files are kept on disk, not in the database.

Request: POST {base}/models/{model}:generateContent with generationConfig.responseModalities ["TEXT", "IMAGE"];
images come back as candidates[0].content.parts[].inlineData {mimeType, data (base64)}.
All Gemini images carry Google's invisible SynthID watermark.
"""
from __future__ import annotations

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
