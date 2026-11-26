"""Anthropic Messages API (docs checked 2026-11-26, see PLAN.md §2).

* Auth: `x-api-key` + `anthropic-version`. `max_tokens` is required; `system` is top-level.
* GET /v1/models is paginated and reports capabilities (image_input, pdf_input, thinking types).
* Thinking: models listing "adaptive" get {"type": "adaptive"}; older ones {"type": "enabled", budget_tokens}.
  ("enabled" is rejected on Claude 4.7+.)
* History must alternate and end with a user turn (assistant prefill is rejected on 4.6+).
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import AsyncIterator, List, Optional, Tuple

import httpx

from . import filters
from .base import (ModelInfo, ProviderConfig, ProviderError, SSEParser, client, human_error, network_error,
                   raise_for_status, stream_lines)

API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 16000
THINK_BUDGET = 8000


def headers(cfg: ProviderConfig) -> dict:
    return {"x-api-key": cfg.key, "anthropic-version": API_VERSION, "content-type": "application/json", **cfg.headers}


def parse_model(cfg: ProviderConfig, it: dict) -> Optional[ModelInfo]:
    mid = str(it.get("id") or "")
    if not mid or not filters.is_chat_model(mid):
        return None
    caps = it.get("capabilities") if isinstance(it.get("capabilities"), dict) else {}
    th = caps.get("thinking") if isinstance(caps.get("thinking"), dict) else {}
    types = th.get("types") or []
    if isinstance(types, dict):
        types = [k for k, v in types.items() if v]
    if caps:
        vision = bool(caps.get("image_input", True))
        pdf = bool(caps.get("pdf_input", vision))
        can_think = bool(set(types) & {"enabled", "adaptive"})
    else:  # older API without capabilities: everything since Claude 3 sees images; 3.7+/4+ can think
        vision, pdf = True, True
        can_think = filters.guess_reasoning(mid) or any(x in mid for x in ("3-7", "-4", "4-", "opus-4", "sonnet-4"))
    created = None
    if it.get("created_at"):
        try:
            from datetime import datetime

            created = int(datetime.fromisoformat(str(it["created_at"]).replace("Z", "+00:00")).timestamp())
        except Exception:
            created = None
    return ModelInfo(id=mid, label=str(it.get("display_name") or mid), provider=cfg.id, kind=cfg.kind, vision=vision,
                     context=it.get("max_input_tokens"), think="toggle" if can_think else "no", local=False,
                     created=created, preview=filters.is_preview(mid), pdf=pdf,
                     extra={"adaptive": "adaptive" in types, "max_tokens": it.get("max_tokens")})


async def list_models(cfg: ProviderConfig, timeout: float = 15.0) -> List[ModelInfo]:
    out, after = [], None
    for _ in range(20):  # pagination guard
        params = {"limit": 1000}
        if after:
            params["after_id"] = after
        try:
            r = await client().get(cfg.base_url + "/models", params=params, headers=headers(cfg), timeout=timeout)
        except httpx.HTTPError as e:
            raise network_error(e, cfg.name)
        await raise_for_status(r, cfg)
        j = r.json()
        for it in j.get("data") or []:
            m = parse_model(cfg, it)
            if m:
                out.append(m)
        if not j.get("has_more") or not j.get("last_id"):
            break
        after = j["last_id"]
    for mid in cfg.extra_models:
        if mid not in {m.id for m in out}:
            out.append(parse_model(cfg, {"id": mid}) or ModelInfo(id=mid, provider=cfg.id, kind=cfg.kind))
    out.sort(key=filters.sort_key)
    return out


async def validate(cfg: ProviderConfig, timeout: float = 6.0) -> Tuple[bool, str]:
    try:
        models = await asyncio.wait_for(list_models(cfg, timeout), timeout)
    except asyncio.TimeoutError:
        return False, "Took too long"
    except ProviderError as e:
        return False, e.message
    return True, f"{len(models)} chat models"


def build_messages(model: ModelInfo, messages, files) -> Tuple[list, list]:
    notes = []
    msgs: list = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        text = m.get("content", "") or ""
        if msgs and msgs[-1]["role"] == role:  # merge same-role turns
            msgs[-1]["content"][0]["text"] += "\n\n" + text
        else:
            msgs.append({"role": role, "content": [{"type": "text", "text": text}]})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    while msgs and msgs[-1]["role"] != "user":
        msgs.pop()
    for m in msgs:  # empty text blocks are rejected
        for b in m["content"]:
            if not b["text"].strip():
                b["text"] = "(empty)"
    blocks = []
    for f in files or []:
        if f["type"] == "image":
            if model.vision:
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": f["mime"], "data": base64.b64encode(f["data"]).decode()}})
            else:
                notes.append(f"{model.id} can't see images, so '{f['name']}' was left out.")
        elif f["type"] == "pdf":
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                           "data": base64.b64encode(f["data"]).decode()}})
    if blocks and msgs:
        msgs[-1]["content"] = blocks + msgs[-1]["content"]
    return msgs, notes


async def stream_chat(cfg: ProviderConfig, model: ModelInfo, messages, files, system, think,
                      cancel: Optional[asyncio.Event] = None) -> AsyncIterator[dict]:
    msgs, notes = build_messages(model, messages, files)
    for n in notes:
        yield {"note": n}
    if not msgs:
        raise ProviderError("Nothing to send yet.", 400, "bad_request")
    max_tokens = min(int(model.extra.get("max_tokens") or DEFAULT_MAX_TOKENS), 32000)
    body = {"model": model.id, "max_tokens": max_tokens, "messages": msgs, "stream": True}
    if system:
        body["system"] = system
    if think and model.think != "no":
        if model.extra.get("adaptive"):
            body["thinking"] = {"type": "adaptive"}
        else:
            body["max_tokens"] = max(max_tokens, THINK_BUDGET + 4000)
            body["thinking"] = {"type": "enabled", "budget_tokens": THINK_BUDGET}
    usage = {}
    t_first = None
    stop = None
    try:
        async with client().stream("POST", cfg.base_url + "/messages", json=body, headers=headers(cfg)) as r:
            if r.status_code != 200:
                raw = (await r.aread()).decode("utf-8", "replace")
                raise human_error(r.status_code, cfg.name, raw, r.headers.get("retry-after"), cfg.secrets(), model.id)
            async for ev, data in stream_lines(r, SSEParser()):
                if cancel is not None and cancel.is_set():
                    return
                try:
                    j = json.loads(data) if data.strip() else None
                except ValueError:
                    continue
                if not isinstance(j, dict):
                    continue
                t = j.get("type") or ev
                if t == "content_block_delta":
                    d = j.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        t_first = t_first or time.perf_counter()
                        yield {"content": d["text"]}
                    elif d.get("type") == "thinking_delta" and d.get("thinking"):
                        t_first = t_first or time.perf_counter()
                        yield {"thinking": d["thinking"]}
                elif t == "message_start":
                    u = (j.get("message") or {}).get("usage") or {}
                    usage["input"] = u.get("input_tokens")
                elif t == "message_delta":
                    u = j.get("usage") or {}
                    if u.get("output_tokens") is not None:
                        usage["output"] = u["output_tokens"]
                    stop = (j.get("delta") or {}).get("stop_reason") or stop
                elif t == "error":
                    e = j.get("error") or {}
                    if e.get("type") == "overloaded_error":
                        raise ProviderError(f"Provider error: {cfg.name} is overloaded. Try again in a moment.", 529, "server")
                    raise ProviderError(f"{cfg.name} stopped with an error: {str(e.get('message') or '')[:200]}", 0, "server")
                elif t == "message_stop":
                    break
    except httpx.HTTPError as e:
        raise network_error(e, cfg.name)
    if stop == "max_tokens":
        yield {"note": "The answer was cut off (length limit)."}
    elif stop == "refusal":
        yield {"note": "Claude declined to answer this."}
    done = {"done": True}
    if usage:
        done["usage"] = usage
        if t_first and usage.get("output"):
            dt = time.perf_counter() - t_first
            if dt > 0.05:
                done["speed"] = round(usage["output"] / dt, 1)
    yield done
