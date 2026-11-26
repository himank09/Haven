"""Google Gemini API (ported from v0.9 server.py; docs checked 2026-11-26).

* Header `x-goog-api-key`. Models report `thinking` (bool) and `inputTokenLimit`.
* Thinking can't be switched off on 2.5 Pro / 3.x / 4.x ("always"); Think then only shows the thoughts.
* If a model rejects our generationConfig (older/newer thinking fields), retry once without it (as v0.9 did).
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
from typing import AsyncIterator, List, Optional, Tuple

import httpx

from . import filters
from .base import (ModelInfo, ProviderConfig, ProviderError, SSEParser, client, human_error, network_error,
                   raise_for_status, sse_json, stream_lines)

ALWAYS_THINKS = re.compile(r"gemini-(2\.5-pro|[3-9])", re.I)
SKIP = ("embedding", "tts", "image-generation", "native-audio", "live", "aqa", "imagen", "veo", "robotics", "computer-use")


def headers(cfg: ProviderConfig) -> dict:
    return {"x-goog-api-key": cfg.key, "Content-Type": "application/json", **cfg.headers}


def parse_model(cfg: ProviderConfig, it: dict) -> Optional[ModelInfo]:
    name = str(it.get("name") or "").replace("models/", "")
    if "gemini" not in name or any(s in name for s in SKIP) or not filters.is_chat_model(name):
        return None
    if "generateContent" not in (it.get("supportedGenerationMethods") or ["generateContent"]):
        return None
    thinking = it.get("thinking")
    if thinking is None:
        thinking = bool(re.search(r"gemini-(2\.5|[3-9])", name))
    think = "no"
    if thinking:
        think = "always" if ALWAYS_THINKS.search(name) else "toggle"
    return ModelInfo(id=name, label=str(it.get("displayName") or name), provider=cfg.id, kind=cfg.kind, vision=True,
                     context=it.get("inputTokenLimit"), think=think, local=False, preview=filters.is_preview(name), pdf=True)


async def list_models(cfg: ProviderConfig, timeout: float = 15.0) -> List[ModelInfo]:
    out, token = [], None
    for _ in range(10):
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        try:
            r = await client().get(cfg.base_url + "/models", params=params, headers=headers(cfg), timeout=timeout)
        except httpx.HTTPError as e:
            raise network_error(e, cfg.name)
        await raise_for_status(r, cfg)
        j = r.json()
        for it in j.get("models") or []:
            m = parse_model(cfg, it)
            if m:
                out.append(m)
        token = j.get("nextPageToken")
        if not token:
            break
    for mid in cfg.extra_models:
        if mid not in {m.id for m in out}:
            out.append(parse_model(cfg, {"name": mid}) or ModelInfo(id=mid, provider=cfg.id, kind=cfg.kind, vision=True))
    out.sort(key=lambda m: (0 if "flash" in m.id else 1,) + filters.sort_key(m))
    return out


async def validate(cfg: ProviderConfig, timeout: float = 6.0) -> Tuple[bool, str]:
    try:
        models = await asyncio.wait_for(list_models(cfg, timeout), timeout)
    except asyncio.TimeoutError:
        return False, "Took too long"
    except ProviderError as e:
        return False, e.message
    return True, f"{len(models)} chat models"


def build_body(model: ModelInfo, messages, files, system, think) -> Tuple[dict, list]:
    notes = []
    contents = []
    for m in messages:
        if m.get("role") not in ("user", "assistant"):
            continue
        role = "model" if m["role"] == "assistant" else "user"
        text = m.get("content", "") or " "
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n\n" + text
        else:
            contents.append({"role": role, "parts": [{"text": text}]})
    parts = []
    for f in files or []:
        if f["type"] in ("image", "pdf"):
            parts.append({"inline_data": {"mime_type": f["mime"], "data": base64.b64encode(f["data"]).decode()}})
    if parts:
        for c in reversed(contents):
            if c["role"] == "user":
                c["parts"] = parts + c["parts"]
                break
    body = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if model.think != "no":
        if think:
            body["generationConfig"] = {"thinkingConfig": {"includeThoughts": True}}
        elif model.think == "toggle":
            body["generationConfig"] = {"thinkingConfig": {"thinkingBudget": 0}}
    return body, notes


async def stream_chat(cfg: ProviderConfig, model: ModelInfo, messages, files, system, think,
                      cancel: Optional[asyncio.Event] = None) -> AsyncIterator[dict]:
    body, notes = build_body(model, messages, files, system, think)
    for n in notes:
        yield {"note": n}
    url = f"{cfg.base_url}/models/{model.id}:streamGenerateContent?alt=sse"
    usage, t_first, finish = {}, None, None
    try:
        for attempt in (1, 2):
            async with client().stream("POST", url, json=body, headers=headers(cfg)) as r:
                if r.status_code != 200:
                    raw = (await r.aread()).decode("utf-8", "replace")
                    if r.status_code == 400 and "generationConfig" in body and attempt == 1:
                        body.pop("generationConfig")  # model doesn't take these thinking options
                        continue
                    raise human_error(r.status_code, cfg.name, raw, r.headers.get("retry-after"), cfg.secrets(), model.id)
                async for _ev, data in stream_lines(r, SSEParser()):
                    if cancel is not None and cancel.is_set():
                        return
                    j = sse_json(data)
                    if j is None:
                        continue
                    if j.get("error"):
                        e = j["error"]
                        raise ProviderError(f"{cfg.name} stopped with an error: {str(e.get('message') if isinstance(e, dict) else e)[:200]}", 0, "server")
                    pf = j.get("promptFeedback") or {}
                    if pf.get("blockReason"):
                        raise ProviderError(f"Gemini blocked this request ({pf['blockReason']}).", 400, "bad_request")
                    for cand in (j.get("candidates") or [])[:1]:
                        for p in (cand.get("content") or {}).get("parts") or []:
                            if p.get("text"):
                                t_first = t_first or time.perf_counter()
                                yield {"thinking": p["text"]} if p.get("thought") else {"content": p["text"]}
                        finish = cand.get("finishReason") or finish
                    u = j.get("usageMetadata")
                    if u:
                        usage = {"input": u.get("promptTokenCount"), "output": u.get("candidatesTokenCount")}
            break
    except httpx.HTTPError as e:
        raise network_error(e, cfg.name)
    if finish == "MAX_TOKENS":
        yield {"note": "The answer was cut off (length limit)."}
    elif finish not in (None, "STOP", "FINISH_REASON_UNSPECIFIED"):
        yield {"note": f"Gemini stopped: {finish}"}
    done = {"done": True}
    if usage:
        done["usage"] = usage
        if t_first and usage.get("output"):
            dt = time.perf_counter() - t_first
            if dt > 0.05:
                done["speed"] = round(usage["output"] / dt, 1)
    yield done
