"""The chat pipeline: request -> attachments -> provider adapter -> NDJSON lines for the page.

NDJSON contract (unchanged from v0.9): {"content"}, {"thinking"}, {"note"}, {"error"}, and always a final
{"done": true, "speed"?, "usage"?}.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from pathlib import Path
from typing import AsyncIterator, List, Tuple

import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from haven import docs, media
from haven.providers import keystore, registry
from haven.providers.base import ModelInfo, ProviderConfig, ProviderError, redact

DEFAULT_SYSTEM = "Be helpful, accurate and concise. Short answers unless asked for detail. Never invent facts that are not in the user's files."
SCAN_PAGES_LOCAL, SCAN_PAGES_CLOUD = 3, 8


def line(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False) + "\n"


def log_error(text: str, secrets=()):
    try:
        d = Path(os.environ.get("HAVEN_LOG_DIR") or keystore.config_dir())
        (d / "errors.log").open("a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + redact(text, secrets) + "\n")
    except Exception:
        pass


class LiveStream(StreamingResponse):
    """A StreamingResponse that always watches for the client going away and cancels the generator
    immediately (Starlette only does this for ASGI < 2.4). Cancelling closes the upstream HTTP stream."""

    async def __call__(self, scope, receive, send):
        async with anyio.create_task_group() as tg:
            async def run():
                try:
                    await self.stream_response(send)
                except OSError:
                    pass
                tg.cancel_scope.cancel()

            tg.start_soon(run)
            await self.listen_for_disconnect(receive)
            tg.cancel_scope.cancel()


def prepare(cfg: ProviderConfig, model: ModelInfo, files: List[dict]) -> Tuple[list, list, list]:
    """Attachments -> (parts for the adapter, document blocks to put in the prompt, notes for the user)."""
    parts, blocks, notes = [], [], []
    budget = docs.budget_for(model)
    pdf_ok = model.pdf and not cfg.local
    n_docs = max(1, sum(1 for f in files if f["mime"] in ("application/pdf", "text/plain")))
    each = budget // n_docs
    for f in files:
        name, mime = f["name"], f["mime"]
        if mime.startswith("image/"):
            try:
                img = media.normalize_image(f["data"])
            except Exception:
                notes.append(f"'{name}' isn't an image Haven can read.")
                continue
            parts.append({"type": "image", "name": name, "mime": media.image_mime(img), "data": img})
        elif mime == "application/pdf":
            try:
                pages = docs.extract_pages(f["data"])
            except docs.UnreadablePDF as e:
                notes.append(f"'{name}' couldn't be read ({e}).")
                continue
            if docs.is_scanned(pages):
                if pdf_ok:
                    parts.append({"type": "pdf", "name": name, "mime": "application/pdf", "data": f["data"]})
                elif model.vision:
                    n = SCAN_PAGES_LOCAL if cfg.local else SCAN_PAGES_CLOUD
                    imgs = media.render_pdf_pages(f["data"], max_pages=n)
                    parts += [{"type": "image", "name": f"{name} p{i + 1}", "mime": "image/jpeg", "data": b} for i, b in enumerate(imgs)]
                    notes.append(f"'{name}' looks scanned; the model sees images of its first {len(imgs)} page(s).")
                else:
                    notes.append(f"'{name}' looks scanned and {model.id} can't see images. Pick a vision model (eye icon).")
                continue
            text, note = docs.document_text(name, pages, each)
            if note:
                notes.append(note)
            blocks.append(f"<document name=\"{name}\" pages=\"{len(pages)}\">\n{text}\n</document>")
        elif mime == "text/plain":
            text = f["data"].decode("utf-8", "ignore")
            if len(text) > each:
                notes.append(f"'{name}' is long; the model sees the first ~{each // 1000}k characters.")
                text = text[:each]
            blocks.append(f"<document name=\"{name}\">\n{text}\n</document>")
        else:
            notes.append(f"'{name}' type isn't supported (convert it to PDF first).")
    return parts, blocks, notes


def clean_history(messages) -> list:
    out = []
    for m in messages or []:
        role = m.get("role")
        if role in ("user", "assistant") and isinstance(m.get("content", ""), str):
            out.append({"role": role, "content": m.get("content", "")})
    return out


async def resolve_or_400(model_id: str) -> Tuple[ProviderConfig, ModelInfo]:
    pid, _, name = (model_id or "").partition(":")
    if not pid or not name:
        raise HTTPException(400, "Pick a model first")
    cfg, model = await registry.resolve(model_id)
    if not cfg or not model:
        raise HTTPException(400, "Model no longer available, pick another")
    return cfg, model


async def stream(cfg: ProviderConfig, model: ModelInfo, payload: dict) -> AsyncIterator[str]:
    files = media.decode_files(payload.get("files"))
    messages = clean_history(payload.get("messages"))
    system = payload.get("system") or DEFAULT_SYSTEM
    think = bool(payload.get("think", False))
    adapter = registry.ADAPTERS[cfg.style]
    done = {"done": True}
    try:
        parts, blocks, notes = await asyncio.to_thread(prepare, cfg, model, files)
        for n in notes:
            yield line(note=n)
        if blocks:
            for m in reversed(messages):
                if m["role"] == "user":
                    m["content"] = "\n\n".join(blocks) + "\n\n" + m["content"]
                    break
        async for ev in adapter.stream_chat(cfg, model, messages, parts, system, think):
            if ev.get("done"):
                done = ev
                continue
            yield json.dumps(ev, ensure_ascii=False) + "\n"
    except ProviderError as e:
        yield line(error=redact(e.message, cfg.secrets()))
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception as e:
        log_error(traceback.format_exc(), cfg.secrets())
        yield line(error=f"Something went wrong ({type(e).__name__}). Details are in errors.log.")
    yield json.dumps(done, ensure_ascii=False) + "\n"
