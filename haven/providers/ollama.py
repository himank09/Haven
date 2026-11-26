"""Ollama native API (ported from v0.9 server.py; docs checked 2026-11-26).

* /api/tags lists models; /api/show gives `capabilities` (completion, vision, thinking, embedding…) and the
  context length (architecture-prefixed key). /api/show results are cached per model digest.
* /api/chat streams NDJSON; `think` is only sent to models that can think.
* "-cloud" models are hidden: they aren't private, so they must never get the Private badge.
"""
from __future__ import annotations

import asyncio
import base64
from typing import AsyncIterator, Dict, List, Optional, Tuple

import httpx

from . import filters
from .base import (ModelInfo, NDJSONParser, ProviderConfig, ProviderError, client, network_error, stream_lines)

_SHOW: Dict[str, dict] = {}  # digest -> {"caps": [...], "context": int|None}


async def _show(cfg: ProviderConfig, name: str, digest: str, timeout: float) -> dict:
    if digest and digest in _SHOW:
        return _SHOW[digest]
    info = {"caps": None, "context": None, "think_values": None}
    try:
        r = await client(True).post(cfg.base_url + "/api/show", json={"model": name}, timeout=timeout)
        if r.status_code == 200:
            j = r.json()
            info["caps"] = j.get("capabilities")
            for k, v in (j.get("model_info") or {}).items():
                if k.endswith(".context_length") and isinstance(v, int):
                    info["context"] = v
            th = j.get("thinking")
            if isinstance(th, dict):
                info["think_values"] = th.get("values")
            if digest:
                _SHOW[digest] = info
    except Exception:
        pass
    return info


async def list_models(cfg: ProviderConfig, timeout: float = 5.0) -> List[ModelInfo]:
    try:
        r = await client(True).get(cfg.base_url + "/api/tags", timeout=timeout)
    except httpx.HTTPError as e:
        raise ProviderError("Ollama is not running.", 0, "network") if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)) \
            else network_error(e, cfg.name, True)
    if r.status_code != 200:
        raise ProviderError(f"Ollama returned {r.status_code}.", r.status_code, "server")
    models = [m for m in (r.json().get("models") or []) if not str(m.get("name", "")).endswith("cloud")]
    infos = await asyncio.gather(*[_show(cfg, m["name"], m.get("digest", ""), max(timeout, 3)) for m in models])
    out = []
    for m, info in zip(models, infos):
        name = m["name"]
        caps = info["caps"]
        if caps is not None and "completion" not in caps:
            continue  # embedding-only models
        if caps is None and not filters.is_chat_model(name):
            continue
        vision = ("vision" in caps) if caps is not None else filters.guess_vision(name)
        if caps is not None:
            can_think = "thinking" in caps
        elif info["think_values"] is not None:
            can_think = info["think_values"] != [False]
        else:
            can_think = filters.guess_reasoning(name)
        size = (m.get("details") or {}).get("parameter_size") or ""
        out.append(ModelInfo(id=name, label=name, provider=cfg.id, kind="ollama", vision=bool(vision), context=info["context"],
                             think="toggle" if can_think else "no", local=True, preview=False,
                             extra={"size": size, "digest": m.get("digest", "")}))
    out.sort(key=lambda x: x.id.lower())
    return out


async def validate(cfg: ProviderConfig, timeout: float = 1.5) -> Tuple[bool, str]:
    try:
        models = await asyncio.wait_for(list_models(cfg, timeout), timeout + 3)
    except asyncio.TimeoutError:
        return False, "not running"
    except ProviderError as e:
        return False, "not running" if e.kind == "network" else e.message
    return True, f"{len(models)} models"


def build_messages(model: ModelInfo, messages, files) -> Tuple[list, list]:
    notes = []
    msgs = [{"role": m["role"], "content": m.get("content", "") or ""} for m in messages if m.get("role") in ("user", "assistant", "system")]
    images = []
    for f in files or []:
        if f["type"] == "image":
            if model.vision:
                images.append(base64.b64encode(f["data"]).decode())
            else:
                notes.append(f"{model.id} can't see images, so '{f['name']}' was left out. Pick a vision model (eye icon).")
        elif f["type"] == "pdf":
            notes.append(f"{model.id} can't read '{f['name']}' directly.")
    if images:
        for m in reversed(msgs):
            if m["role"] == "user":
                m["images"] = images
                break
    return msgs, notes


async def stream_chat(cfg: ProviderConfig, model: ModelInfo, messages, files, system, think,
                      cancel: Optional[asyncio.Event] = None) -> AsyncIterator[dict]:
    msgs, notes = build_messages(model, messages, files)
    if system:
        msgs = [{"role": "system", "content": system}] + msgs
    for n in notes:
        yield {"note": n}
    body = {"model": model.id, "messages": msgs, "stream": True}
    if model.think != "no":
        body["think"] = bool(think)
    try:
        async with client(True).stream("POST", cfg.base_url + "/api/chat", json=body) as r:
            if r.status_code != 200:
                err = (await r.aread()).decode("utf-8", "replace")
                try:
                    import json

                    err = json.loads(err).get("error", err)
                except Exception:
                    pass
                if "does not support" in err and "image" in err:
                    raise ProviderError("This local model can't read images. Pick a vision model.", r.status_code, "bad_request")
                if r.status_code == 404:
                    raise ProviderError(f"Model not available: {model.id} isn't installed in Ollama.", 404, "not_found")
                if "context" in err and ("length" in err or "too long" in err):
                    raise ProviderError("Too long for this model. Remove a file or start a new chat.", r.status_code, "too_long")
                raise ProviderError(f"Ollama: {str(err)[:200]}", r.status_code, "server")
            async for j in stream_lines(r, NDJSONParser()):
                if cancel is not None and cancel.is_set():
                    return
                if j.get("error"):
                    raise ProviderError(f"Ollama: {str(j['error'])[:200]}", 0, "server")
                msg = j.get("message") or {}
                if msg.get("thinking"):
                    yield {"thinking": msg["thinking"]}
                if msg.get("content"):
                    yield {"content": msg["content"]}
                if j.get("done"):
                    done = {"done": True}
                    if j.get("eval_count") and j.get("eval_duration"):
                        done["speed"] = round(j["eval_count"] / (j["eval_duration"] / 1e9), 1)
                        done["usage"] = {"input": j.get("prompt_eval_count"), "output": j["eval_count"]}
                    if j.get("done_reason") == "length":
                        yield {"note": "The answer was cut off (length limit)."}
                    yield done
                    return
    except httpx.HTTPError as e:
        if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
            raise ProviderError("Ollama is not running. Open Ollama from the Start menu and try again.", 0, "network")
        raise network_error(e, cfg.name, True)
    yield {"done": True}


async def unload(cfg: ProviderConfig, model: str):
    try:
        await client(True).post(cfg.base_url + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
    except Exception:
        pass
