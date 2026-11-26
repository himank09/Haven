"""OpenAI Chat Completions style: OpenAI, LM Studio, OpenRouter, Groq, xAI, DeepSeek, Mistral, Together,
Fireworks, Cerebras, Hugging Face and any custom OpenAI-compatible server.

Differences between those providers (verified against their docs, see PLAN.md §2) live in small
`kind` switches here: model metadata fields, how "Think" is requested, and where reasoning text arrives.
"""
from __future__ import annotations

import asyncio
import base64
import time
from typing import AsyncIterator, List, Optional, Tuple

import httpx

from . import filters
from .base import (ModelInfo, ProviderConfig, ProviderError, SSEParser, ThinkSplitter, client, human_error,
                   network_error, raise_for_status, sse_json, stream_lines)

USAGE_KINDS = {"openai", "groq", "xai", "deepseek", "together", "fireworks", "cerebras", "openrouter"}
NATIVE_PDF_KINDS = {"openai"}
NON_CHAT_TYPES = {"embedding", "embeddings", "image", "images", "audio", "transcribe", "rerank", "moderation",
                  "video", "tts", "stt", "classifier"}


def headers(cfg: ProviderConfig) -> dict:
    h = {"Content-Type": "application/json", **cfg.headers}
    if cfg.key:
        h["Authorization"] = f"Bearer {cfg.key}"
    if cfg.kind == "openrouter":
        h.setdefault("X-OpenRouter-Title", "Haven")
        h.setdefault("HTTP-Referer", "https://github.com/himank09/haven")
    return h


def _root(base: str) -> str:
    return base[:-3] if base.rstrip("/").endswith("/v1") else base


# ---------------- models ----------------
def _items(j) -> list:
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for k in ("data", "models", "items"):
            if isinstance(j.get(k), list):
                return j[k]
    return []


def parse_model(cfg: ProviderConfig, it) -> Optional[ModelInfo]:
    if isinstance(it, str):
        it = {"id": it}
    if not isinstance(it, dict):
        return None
    mid = str(it.get("id") or it.get("key") or it.get("model") or it.get("name") or "").strip()
    if not mid or not filters.is_chat_model(mid):
        return None
    typ = str(it.get("type") or "").lower()
    if typ in NON_CHAT_TYPES:
        return None
    if it.get("active") is False:  # Groq: retired models
        return None
    caps = it.get("capabilities") if isinstance(it.get("capabilities"), dict) else {}
    if caps and caps.get("completion_chat") is False:  # Mistral
        return None
    arch = it.get("architecture") if isinstance(it.get("architecture"), dict) else {}
    in_mod = arch.get("input_modalities") or it.get("input_modalities") or []
    out_mod = arch.get("output_modalities") or it.get("output_modalities") or []
    if out_mod and "text" not in out_mod:
        return None
    if it.get("deprecation") and it.get("deprecation_replacement_model"):
        pass  # still usable until removed; kept
    vision = None
    if in_mod:
        vision = "image" in in_mod
    elif "vision" in caps:
        vision = bool(caps.get("vision"))
    elif typ == "vlm":
        vision = True
    if vision is None:
        vision = filters.guess_vision(mid)
    # thinking
    reasoning = None
    if "reasoning" in caps:
        reasoning = bool(caps.get("reasoning"))
    elif isinstance(it.get("supported_parameters"), list):
        reasoning = "reasoning" in it["supported_parameters"] or "include_reasoning" in it["supported_parameters"]
    elif it.get("effort") or it.get("reasoning"):
        reasoning = True
    if reasoning is None:
        reasoning = filters.guess_reasoning(mid)
    think = "no"
    if reasoning:
        think = "always" if cfg.kind == "xai" else "toggle"
    top = it.get("top_provider") if isinstance(it.get("top_provider"), dict) else {}
    ctx = it.get("context_length") or it.get("context_window") or it.get("max_context_length") or top.get("context_length")
    try:
        ctx = int(ctx) if ctx else None
    except (TypeError, ValueError):
        ctx = None
    created = it.get("created")
    label = str(it.get("display_name") or it.get("name") or mid) if cfg.kind in ("openrouter", "lmstudio") else mid
    return ModelInfo(id=mid, label=label, provider=cfg.id, kind=cfg.kind, vision=bool(vision), context=ctx, think=think,
                     local=cfg.local, created=created if isinstance(created, int) else None,
                     preview=filters.is_preview(mid), pdf=cfg.kind in NATIVE_PDF_KINDS and bool(vision))


async def _get(cfg: ProviderConfig, url: str, timeout: float) -> httpx.Response:
    try:
        return await client(cfg.local).get(url, headers=headers(cfg), timeout=timeout)
    except httpx.HTTPError as e:
        raise network_error(e, cfg.name, cfg.local)


async def list_models(cfg: ProviderConfig, timeout: float = 15.0) -> List[ModelInfo]:
    items = None
    if cfg.kind == "lmstudio":  # native API has type + vision + reasoning metadata
        try:
            r = await _get(cfg, _root(cfg.base_url) + "/api/v1/models", timeout)
            if r.status_code == 200:
                items = _items(r.json())
        except ProviderError:
            raise
        except Exception:
            items = None
    if items is None:
        url = cfg.base_url + ("/models/user" if cfg.kind == "openrouter" else "/models")
        r = await _get(cfg, url, timeout)
        if r.status_code == 404 and cfg.kind == "openrouter":
            r = await _get(cfg, cfg.base_url + "/models", timeout)
        if r.status_code == 404 and cfg.extra_models:
            items = []
        elif r.status_code == 404 and cfg.kind == "fireworks":
            raise ProviderError("Fireworks doesn't list models for this key. Add a model id in Settings.", 404, "not_found")
        else:
            await raise_for_status(r, cfg)
            try:
                items = _items(r.json())
            except ValueError:
                raise ProviderError(f"{cfg.name} sent a model list Haven couldn't read.", 200, "bad_request")
    out, seen = [], set()
    for it in items:
        m = parse_model(cfg, it)
        if m and m.id not in seen:
            seen.add(m.id)
            out.append(m)
    for mid in cfg.extra_models:
        if mid not in seen:
            m = parse_model(cfg, {"id": mid}) or ModelInfo(id=mid, label=mid, provider=cfg.id, kind=cfg.kind, local=cfg.local)
            out.append(m)
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


# ---------------- chat ----------------
def think_params(cfg: ProviderConfig, model: ModelInfo, think: bool) -> dict:
    if model.think == "no":
        return {}
    k = cfg.kind
    if k == "openai":
        return {"reasoning_effort": "high"} if think else {}
    if k == "openrouter":
        return {"reasoning": {"enabled": True}} if think else {}
    if k in ("groq", "cerebras"):
        return {"reasoning_format": "parsed" if think else "hidden"}
    if k == "deepseek":
        return {"thinking": {"type": "enabled" if think else "disabled"}}
    if k == "xai":
        return {"reasoning_effort": "high"} if think else {}
    if k == "together":
        return {"reasoning": {"enabled": bool(think)}}
    return {}


def build_messages(cfg: ProviderConfig, model: ModelInfo, messages, files, system) -> Tuple[list, list]:
    notes = []
    msgs = ([{"role": "system", "content": system}] if system else [])
    msgs += [{"role": m["role"], "content": m.get("content", "") or ""} for m in messages if m.get("role") in ("user", "assistant", "system")]
    parts = []
    for f in files or []:
        if f["type"] == "image":
            if model.vision:
                parts.append({"type": "image_url", "image_url": {"url": f"data:{f['mime']};base64,{base64.b64encode(f['data']).decode()}"}})
            else:
                notes.append(f"{model.id} can't see images, so '{f['name']}' was left out. Pick a model with the eye icon.")
        elif f["type"] == "pdf":
            if cfg.kind in NATIVE_PDF_KINDS:
                parts.append({"type": "file", "file": {"filename": f["name"],
                                                        "file_data": "data:application/pdf;base64," + base64.b64encode(f["data"]).decode()}})
            else:
                notes.append(f"{cfg.name} can't read '{f['name']}' directly.")
    if parts:
        for m in reversed(msgs):
            if m["role"] == "user":
                m["content"] = parts + [{"type": "text", "text": m["content"]}]
                break
    return msgs, notes


def parse_chunk(j: dict, splitter: ThinkSplitter, state: dict) -> List[dict]:
    out: List[dict] = []
    if j.get("error"):
        e = j["error"]
        msg = e.get("message") if isinstance(e, dict) else str(e)
        raise ProviderError(f"{state['name']} stopped with an error: {str(msg)[:200]}", 0, "server")
    for ch in j.get("choices") or []:
        d = ch.get("delta") or ch.get("message") or {}
        r = d.get("reasoning_content") or d.get("reasoning")
        if not r and isinstance(d.get("reasoning_details"), list):
            r = "".join(str(x.get("text") or x.get("summary") or "") for x in d["reasoning_details"] if isinstance(x, dict))
        if isinstance(r, str) and r:
            out.append({"thinking": r})
        c = d.get("content")
        if isinstance(c, list):  # Mistral content chunks
            for part in c:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "thinking":
                    for t in part.get("thinking") or []:
                        if isinstance(t, dict) and t.get("text"):
                            out.append({"thinking": t["text"]})
                elif part.get("type") == "text" and part.get("text"):
                    out.append({"content": part["text"]})
        elif isinstance(c, str) and c:
            for kind, piece in splitter.feed(c):
                out.append({kind: piece})
        fr = ch.get("finish_reason")
        if fr == "length":
            state["note"] = "The answer was cut off (length limit)."
        elif fr == "content_filter":
            state["note"] = "The provider's safety filter stopped the answer."
        elif fr == "error":
            raise ProviderError(f"{state['name']} stopped with an error.", 0, "server")
    u = j.get("usage")
    if isinstance(u, dict) and u:
        state["usage"] = {"input": u.get("prompt_tokens"), "output": u.get("completion_tokens")}
    return out


async def stream_chat(cfg: ProviderConfig, model: ModelInfo, messages, files, system, think,
                      cancel: Optional[asyncio.Event] = None) -> AsyncIterator[dict]:
    msgs, notes = build_messages(cfg, model, messages, files, system)
    for n in notes:
        yield {"note": n}
    optional = dict(think_params(cfg, model, think))
    if cfg.kind in USAGE_KINDS:
        optional["stream_options"] = {"include_usage": True}
    body = {"model": model.id, "messages": msgs, "stream": True}
    state = {"name": cfg.name}
    splitter = ThinkSplitter()
    t_first = None
    n_chunks = 0
    for attempt in (1, 2):
        req = {**body, **optional}
        try:
            async with client(cfg.local).stream("POST", cfg.base_url + "/chat/completions", json=req, headers=headers(cfg)) as r:
                if r.status_code != 200:
                    raw = (await r.aread()).decode("utf-8", "replace")
                    if attempt == 1 and optional and r.status_code in (400, 422) and any(k in raw for k in optional):
                        optional = {}  # model doesn't accept an optional parameter: retry plain
                        continue
                    raise human_error(r.status_code, cfg.name, raw, r.headers.get("retry-after"), cfg.secrets(), model.id)
                async for _ev, data in stream_lines(r, SSEParser()):
                    if cancel is not None and cancel.is_set():
                        return
                    j = sse_json(data)
                    if j is None:
                        continue
                    for ev in parse_chunk(j, splitter, state):
                        if t_first is None:
                            t_first = time.perf_counter()
                        n_chunks += 1
                        yield ev
        except httpx.HTTPError as e:
            raise network_error(e, cfg.name, cfg.local)
        break
    for kind, piece in splitter.close():
        yield {kind: piece}
    if state.get("note"):
        yield {"note": state["note"]}
    done = {"done": True}
    u = state.get("usage")
    if u:
        done["usage"] = u
        if t_first and u.get("output"):
            dt = time.perf_counter() - t_first
            if dt > 0.05:
                done["speed"] = round(u["output"] / dt, 1)
    yield done
