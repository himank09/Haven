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
from haven.shield import Shield
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


CITE_SYSTEM = ("The user attached document(s) with [Page N] markers. Cite the pages you used like (p. 12) or (pp. 3–5). "
               "If the answer isn't in the provided pages, say so plainly instead of guessing.")


class Prepared:
    def __init__(self):
        self.parts: list = []        # images / native PDFs for the adapter
        self.blocks: list = []       # document text to put in the prompt
        self.notes: list = []
        self.pages = 0               # highest page count among attached text PDFs (for citation chips)
        self.previews: dict = {}     # "N" -> first ~200 chars of that page
        self.uncheckable: list = []  # names the Privacy Shield can't look inside (images, scans)
        self.cited = False


def prepare(cfg: ProviderConfig, model: ModelInfo, files: List[dict], question: str = "", whole: bool = False) -> Prepared:
    """Attachments -> what the adapter sends, what goes into the prompt, and notes for the user."""
    out = Prepared()
    budget = docs.budget_for(model)
    pdf_ok = model.pdf and not cfg.local
    loaded = []  # (file, Doc | None, text | None)
    for f in files:
        name, mime = f["name"], f["mime"]
        if mime == "application/pdf":
            try:
                loaded.append((f, docs.extract(f["data"]), None))
            except docs.UnreadablePDF as e:
                out.notes.append(f"'{name}' couldn't be read ({e}).")
        elif mime == "text/plain":
            loaded.append((f, None, f["data"].decode("utf-8", "ignore")))
        else:
            loaded.append((f, None, None))
    # fair budget split between text documents
    text_docs = [(i, d, t) for i, (_f, d, t) in enumerate(loaded) if (d is not None and not docs.is_scanned(d.pages)) or t is not None]
    needs = [len(docs.marked(d.pages)) if d is not None else len(t) for _i, d, t in text_docs]
    shares = dict(zip([i for i, _d, _t in text_docs], docs.allocate(needs, budget)))
    for i, (f, doc, text) in enumerate(loaded):
        name, mime = f["name"], f["mime"]
        if mime.startswith("image/"):
            try:
                img = media.normalize_image(f["data"])
            except Exception:
                out.notes.append(f"'{name}' isn't an image Haven can read.")
                continue
            out.parts.append({"type": "image", "name": name, "mime": media.image_mime(img), "data": img})
            out.uncheckable.append(name)
        elif doc is not None and docs.is_scanned(doc.pages):  # scans: unchanged behaviour (page images / native PDF)
            if pdf_ok:
                out.parts.append({"type": "pdf", "name": name, "mime": "application/pdf", "data": f["data"]})
                out.uncheckable.append(name)
            elif model.vision:
                n = SCAN_PAGES_LOCAL if cfg.local else SCAN_PAGES_CLOUD
                imgs = media.render_pdf_pages(f["data"], max_pages=n)
                out.parts += [{"type": "image", "name": f"{name} p{k + 1}", "mime": "image/jpeg", "data": b} for k, b in enumerate(imgs)]
                out.notes.append(f"'{name}' looks scanned; the model sees images of its first {len(imgs)} page(s).")
                out.uncheckable.append(name)
            else:
                out.notes.append(f"'{name}' looks scanned and {model.id} can't see images. Pick a vision model (eye icon).")
        elif doc is not None:
            sel = docs.select(name, doc, shares.get(i, budget), question, whole)
            if sel.note:
                out.notes.append(sel.note)
            out.blocks.append(f"<document name=\"{name}\" pages=\"{len(doc.pages)}\">\n{sel.text}\n</document>")
            out.pages = max(out.pages, len(doc.pages))
            for k, v in docs.previews(doc, sel.pages).items():
                out.previews.setdefault(k, v)
            out.cited = True
        elif text is not None:
            each = shares.get(i, budget)
            if len(text) > each:
                out.notes.append(f"'{name}' is long; the model sees the first ~{max(1, each // 1000)}k characters.")
                text = text[:each]
            out.blocks.append(f"<document name=\"{name}\">\n{text}\n</document>")
        else:
            out.notes.append(f"'{name}' type isn't supported (convert it to PDF first).")
    return out


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
        from haven.providers import catalog

        hit = catalog.find(model_id)
        if hit and hit[0] != "ollama":  # a suggested model whose provider has no key yet
            name = registry.name_of(hit[0])
            art = "an" if name[0] in "AEIOU" or name == "xAI" else "a"
            raise HTTPException(400, f"{hit[1][1]} needs {art} {name} API key. Add it in Settings → Models & keys.")
        raise HTTPException(400, "Model no longer available, pick another")
    return cfg, model


SAVE_EVERY = 2.0  # seconds: a crash loses at most this much of a streaming answer
RETRY_BUSY_AFTER = 2.0  # seconds before the one automatic retry of an overloaded model


class Saver:
    """Writes the assistant message to SQLite while it streams (every ~2 s and at the end).

    The page passes {"save": {"conversation_id", "message_id"}}; the server owns the write, so a chat the
    user switched away from keeps saving into its own conversation and nowhere else."""

    def __init__(self, save: dict, model_full_id: str):
        self.cid = str((save or {}).get("conversation_id") or "")
        self.mid = str((save or {}).get("message_id") or "")
        self.on = bool(self.cid and self.mid)
        self.model = model_full_id
        self.content, self.thinking, self.notes, self.error = [], [], [], ""
        self.meta: dict = {}
        self.shield = None  # set when the Privacy Shield masked this request: answers are saved with real values
        self.t0 = time.monotonic()
        self.last = 0.0

    def add(self, ev: dict):
        if "content" in ev:
            self.content.append(ev["content"])
        if "thinking" in ev:
            self.thinking.append(ev["thinking"])
        if "note" in ev:
            self.notes.append(ev["note"])
        if "error" in ev:
            self.error = ev["error"]

    def write(self, final: bool = False, stopped: bool = False):
        if not self.on:
            return
        now = time.monotonic()
        if not final and now - self.last < SAVE_EVERY:
            return
        self.last = now
        text = "".join(self.content)
        thinking = "".join(self.thinking)
        if self.shield:
            text, thinking = self.shield.unmask(text), self.shield.unmask(thinking)
        if self.error:
            text = (text + "\n\n" if text else "") + self.error
        meta = {**self.meta, "notes": self.notes, "error": bool(self.error), "elapsed": round(now - self.t0, 2),
                "live": not final}
        if stopped:
            meta["stopped"] = True
        try:
            from haven import storage

            storage.get().upsert_message(self.cid, {"id": self.mid, "role": "assistant", "content": text,
                                                    "thinking": thinking, "model": self.model, "meta": meta})
        except Exception:
            log_error(traceback.format_exc())


STYLE = {"concise": "Keep answers short and to the point.",
         "detailed": "Give thorough, detailed answers with examples where they help.", "balanced": ""}


def profile_prompt(default_system: bool = True) -> str:
    """The user's profile (Settings -> Profile), added to the instructions when they switched it on."""
    p = keystore.get_setting("profile") or {}
    if not p or not p.get("use_in_chats", True):
        return ""
    bits = []
    call = (p.get("call") or p.get("name") or "").strip()
    if call:
        bits.append(f"The user's name is {call}; use it when it feels natural.")
    if (p.get("about") or "").strip():
        bits.append("What the user wants you to know about them: " + p["about"].strip())
    if default_system and STYLE.get(p.get("style", "balanced")):  # tool actions (e.g. OCR) keep their own format
        bits.append(STYLE[p["style"]])
    if (p.get("language") or "").strip():
        bits.append(f"Reply in {p['language'].strip()} unless the user asks otherwise.")
    return ("\n\n" + "\n".join(bits)) if bits else ""


def shield_enabled() -> bool:
    return bool(keystore.get_setting("shield", True))


async def stream(cfg: ProviderConfig, model: ModelInfo, payload: dict) -> AsyncIterator[str]:
    files = media.decode_files(payload.get("files"))
    messages = clean_history(payload.get("messages"))
    system = (payload.get("system") or DEFAULT_SYSTEM) + profile_prompt(default_system=not payload.get("system"))
    think = bool(payload.get("think", False))
    whole = bool(payload.get("whole", False))
    question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    adapter = registry.ADAPTERS[cfg.style]
    done = {"done": True}
    saver = Saver(payload.get("save"), model.full_id)
    finished = False
    shield_on = not cfg.local and shield_enabled()

    def out(ev: dict) -> str:
        saver.add(ev)
        saver.write()
        return json.dumps(ev, ensure_ascii=False) + "\n"

    try:
        prep = await asyncio.to_thread(prepare, cfg, model, files, question, whole)
        if shield_on and prep.uncheckable and not payload.get("shield_ok"):
            # ask once per conversation; nothing was sent and nothing is saved
            names = ", ".join(f"'{n}'" for n in prep.uncheckable[:3])
            finished = True
            saver.on = False
            yield line(confirm=f"{names} can't be checked for personal details (images and scans can't be read by the "
                               f"Privacy Shield). Send to {cfg.name} anyway?")
            yield json.dumps(done) + "\n"
            return
        saver.write(final=False)  # the row exists from the first moment
        if prep.pages:
            saver.meta.update({"pages": prep.pages, "previews": prep.previews})
            yield out({"docs": {"pages": prep.pages, "previews": prep.previews}})
        for n in prep.notes:
            yield out({"note": n})
        if prep.blocks:
            for m in reversed(messages):
                if m["role"] == "user":
                    m["content"] = "\n\n".join(prep.blocks) + "\n\n" + m["content"]
                    break
        if prep.cited:
            system = system + "\n\n" + CITE_SYSTEM
        parts = prep.parts
        if shield_on:
            sh = Shield()
            messages = [{**m, "content": sh.mask(m["content"])} for m in messages]
            system = sh.mask(system)
            saver.shield = sh
            summary = sh.summary(cfg.name)
            if summary:  # the map stays on this PC: the page (localhost) uses it to show real values
                yield out({"note": summary, "unmask": sh.values})
            if prep.uncheckable:
                yield out({"note": f"Sent without checking (Privacy Shield can't read images or scans): {', '.join(prep.uncheckable)}."})
        elif not cfg.local:
            yield out({"note": f"Privacy Shield is off: messages and files go to {cfg.name} as written."})
        for attempt in (1, 2):
            got_text = False
            try:
                async for ev in adapter.stream_chat(cfg, model, messages, parts, system, think):
                    if ev.get("done"):
                        done = ev
                        continue
                    if "content" in ev or "thinking" in ev:
                        got_text = True
                    yield out(ev)
                registry.HEALTH.pop(model.full_id, None)  # it answered: forget any earlier problem
                break
            except ProviderError as e:
                if attempt == 1 and e.kind == "busy" and not got_text:  # brief overload: one quiet retry
                    yield out({"note": f"{model.label or model.id} is busy; trying once more…"})
                    await asyncio.sleep(RETRY_BUSY_AFTER)
                    continue
                if e.kind in registry.HEALTH_KINDS:
                    registry.mark(model.full_id, e.kind)
                yield out({"error": redact(e.message, cfg.secrets())})
                break
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as e:
                log_error(traceback.format_exc(), cfg.secrets())
                yield out({"error": f"Something went wrong ({type(e).__name__}). Details are in errors.log."})
                break
        saver.meta.update({k: done[k] for k in ("speed", "usage") if k in done})
        saver.write(final=True)
        finished = True
        yield json.dumps(done, ensure_ascii=False) + "\n"
    finally:
        if not finished:  # stopped by the user (or the window closed): keep what arrived
            saver.write(final=True, stopped=True)


async def image_stream(payload: dict) -> AsyncIterator[str]:
    """Make a picture with a Gemini image model. Same NDJSON contract plus {"image": "<file name>"}."""
    from haven import images

    prompt = next((m.get("content", "") for m in reversed(payload.get("messages") or []) if m.get("role") == "user"), "").strip()
    gem = next((c for _e, c in registry.configured() if c.kind == "gemini"), None)
    saver = Saver(payload.get("save"), "")
    finished = False

    def out(ev: dict) -> str:
        saver.add(ev)
        if "image" in ev:
            saver.meta.setdefault("images", []).append(ev["image"])
        return json.dumps(ev, ensure_ascii=False) + "\n"

    try:
        if not gem:
            yield out({"error": "Making images needs a Google Gemini key. Add one in Settings → Providers."})
        elif not prompt:
            yield out({"error": "Describe the picture you want."})
        else:
            saver.write(final=False)
            sent = prompt
            if shield_enabled():
                sh = Shield()
                sent = sh.mask(prompt)
                summary = sh.summary(gem.name)
                if summary:
                    yield out({"note": summary})
            try:
                names = await images.image_models(gem)
                if not names:
                    raise ProviderError("This Gemini key can't see any image models.", 404, "not_found")
                model = payload.get("image_model") if payload.get("image_model") in names else names[0]
                saver.model = f"{gem.id}:{model}"
                pics, text = await images.generate(gem, model, sent, str(payload.get("aspect") or ""))
                if not pics:
                    raise ProviderError("Gemini answered without a picture. Try describing it differently.", 0, "server")
                for data, mime in pics:
                    yield out({"image": await asyncio.to_thread(images.save, data, mime)})
                if text:
                    yield out({"content": text})
                yield out({"note": f"Made with {model}. Google adds an invisible SynthID watermark."})
            except ProviderError as e:
                yield out({"error": redact(e.message, gem.secrets())})
            except Exception as e:
                log_error(traceback.format_exc(), gem.secrets())
                yield out({"error": f"Something went wrong ({type(e).__name__}). Details are in errors.log."})
        saver.write(final=True)
        finished = True
        yield json.dumps({"done": True, "model": saver.model}) + "\n"
    finally:
        if not finished:
            saver.write(final=True, stopped=True)
