"""Haven - local server behind the desktop window.

* Listens on 127.0.0.1 only; every /api call needs the per-launch token,
  so websites open in your browser cannot talk to it.
* AI goes to whichever provider you pick: local ones (Ollama, LM Studio) never leave this PC;
  cloud keys live in Windows Credential Manager (see haven/providers/keystore.py).
* Files are processed on this PC and never uploaded (except to a cloud model you explicitly pick).
"""
import asyncio
import glob
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import traceback
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pypdf import PdfReader, PdfWriter

from haven import chat, storage
from haven import convert as conv
from haven.media import TEXT_EXT, decode_files, guess_mime, normalize_image, render_pdf_pages  # noqa: F401 (re-exported)
from haven.providers import keystore, registry
from haven.providers import ollama as ollama_adapter
from haven.providers.base import ProviderError, redact

try:  # optional: iPhone HEIC photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

VERSION = "1.0.0"
WEB = Path(__file__).parent / "web"
TOKEN = os.environ.get("HAVEN_TOKEN", "")  # set by app.py for each launch
RESULTS = {}  # id -> (filename, bytes): finished files waiting for the native Save dialog


@asynccontextmanager
async def lifespan(_app):
    task = None
    if not os.environ.get("HAVEN_NO_POLL"):
        task = asyncio.ensure_future(registry.poll_forever())  # local providers, every 20 s, never blocks
    yield
    if task:
        task.cancel()
    storage.close()


app = FastAPI(title="Haven", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def log_error(text: str):
    chat.log_error(text)


@app.exception_handler(Exception)
async def show_error(request: Request, exc: Exception):
    log_error(traceback.format_exc())
    return JSONResponse({"detail": redact(f"{type(exc).__name__}: {exc}")}, status_code=500)


app.mount("/fonts", StaticFiles(directory=WEB / "fonts"), name="fonts")
app.mount("/web", StaticFiles(directory=WEB), name="web")  # app.js, md.js (no CDN: everything is local)


# ---------------- settings ----------------
def config_dir() -> Path:
    return keystore.config_dir()


def load_settings() -> dict:
    return keystore.load()


def save_settings(s: dict):
    keystore.save_raw(s)


def gemini_entry():
    """The first enabled Gemini provider (saved or from the environment), or None."""
    for e, cfg in registry.configured():
        if cfg.kind == "gemini":
            return e, cfg
    return None


def gemini_key() -> str:
    g = gemini_entry()
    return g[1].key if g else ""


# ---------------- security + desktop save ----------------
class Guard:
    """Pure ASGI middleware: token check, error safety net, and the X-Desk-Store result cache.
    (Pure ASGI rather than @app.middleware so streaming responses see client disconnects at once.)"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        hdrs = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if scope["path"].startswith("/api/") and TOKEN and hdrs.get("x-desk-token") != TOKEN:
            return await JSONResponse({"detail": "Forbidden"}, status_code=403)(scope, receive, send)
        store = hdrs.get("x-desk-store") == "1"
        started = False
        captured = {"status": 0, "headers": [], "body": []}

        async def send_wrapped(msg):
            nonlocal started
            if store:
                if msg["type"] == "http.response.start":
                    captured["status"], captured["headers"] = msg["status"], msg.get("headers", [])
                elif msg["type"] == "http.response.body":
                    captured["body"].append(msg.get("body", b""))
                return
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, receive, send_wrapped)
        except Exception as exc:  # never show a bare "Internal Server Error"
            log_error(traceback.format_exc())
            if started:
                return
            return await JSONResponse({"detail": redact(f"{type(exc).__name__}: {exc}")}, status_code=500)(scope, receive, send)
        if not store:
            return
        body = b"".join(captured["body"])
        rh = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in captured["headers"]}
        if captured["status"] != 200:
            await send({"type": "http.response.start", "status": captured["status"], "headers": captured["headers"]})
            await send({"type": "http.response.body", "body": body})
            return
        # In the desktop window, finished files are kept here and saved via a native Save dialog
        cd = rh.get("content-disposition", "")
        name = cd.split('filename="')[-1].rstrip('"') if "filename=" in cd else "result"
        rid = uuid.uuid4().hex
        RESULTS[rid] = (name, body)
        while len(RESULTS) > 10:
            RESULTS.pop(next(iter(RESULTS)))
        await JSONResponse({"id": rid, "name": name, "size": len(body), "info": rh.get("x-info", "")})(scope, receive, send)


app.add_middleware(Guard)


# ---------------- helpers ----------------
def find_exe(names, patterns):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for pat in patterns:
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return None


def ghostscript():
    return find_exe(["gswin64c", "gswin32c", "gs"],
                    [r"C:\Program Files\gs\*\bin\gswin64c.exe", r"C:\Program Files (x86)\gs\*\bin\gswin32c.exe"])


def libreoffice():
    return find_exe(["soffice"],
                    [r"C:\Program Files\LibreOffice\program\soffice.exe",
                     r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"])


def stem(name: str) -> str:
    return Path(name or "file").stem or "file"


def send_bytes(data: bytes, filename: str, media: str) -> Response:
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def zip_files(items) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in items:
            z.writestr(name, data)
    return buf.getvalue()


def parse_pages(spec: str, total: int) -> List[int]:
    """'1,3-5,8' -> zero-based indexes, validated."""
    out = []
    for part in (spec or "").replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                a = int(a) if a else 1
                b = int(b) if b else total
            else:
                a = b = int(part)
        except ValueError:
            raise HTTPException(400, f"'{part}' is not a page number or range")
        if a < 1 or b > total or a > b:
            raise HTTPException(400, f"Page range '{part}' is outside 1-{total}")
        out.extend(range(a - 1, b))
    if not out:
        raise HTTPException(400, "No pages given")
    return out


def open_pdf(data: bytes, name: str = "file") -> PdfReader:
    try:
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted and not r.decrypt(""):  # needs a password we don't have
            raise ValueError("encrypted")
        len(r.pages)  # fail here (clean 400) rather than later in the tool (500)
        return r
    except Exception:
        raise HTTPException(400, f"'{name}' is not a readable PDF (or it is password-protected)")


async def read_pdf(f: UploadFile) -> PdfReader:
    return open_pdf(await f.read(), f.filename)


def pdf_bytes(writer: PdfWriter) -> bytes:
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------- pages + status ----------------
@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/status")
async def status():
    local = await registry.CACHE.local_status()
    oll = local.get("ollama", {})
    s = load_settings()
    return {
        "version": VERSION,
        "ollama": bool(oll.get("ok")),
        "models": [m.id for m in oll.get("models", [])],
        "lmstudio": bool(local.get("lmstudio", {}).get("ok")),
        "gemini": bool(gemini_entry()),
        "gemini_model": s.get("gemini_model", "gemini-2.5-flash"),
        "ghostscript": bool(ghostscript()),
        "libreoffice": bool(libreoffice()),
        "ffmpeg": bool(conv.ffmpeg_exe()),
    }


@app.get("/api/settings")
def get_settings():
    s, g = load_settings(), gemini_entry()
    k = g[1].key if g else ""
    return {
        "has_key": bool(k),
        "key_hint": keystore.hint(k),
        "key_from_env": bool(g and g[0].get("storage") == "env"),
        "gemini_model": s.get("gemini_model", "gemini-2.5-flash"),
        "config_path": str(config_dir() / "settings.json"),
        "storage": keystore.storage_mode(),
        "shield": s.get("shield", True),
    }


@app.post("/api/settings")
def set_settings(payload: dict):
    if payload.get("clear_key"):
        for p in keystore.saved():
            if p["kind"] == "gemini":
                keystore.remove(p["id"])
                registry.CACHE.drop(p["id"])
    if payload.get("gemini_key"):
        try:
            key = registry.clean_key(payload["gemini_key"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not keystore.find_duplicate(key):
            for p in keystore.saved():  # v0.9 had one Gemini key: replacing it keeps that behaviour
                if p["kind"] == "gemini":
                    keystore.remove(p["id"])
                    registry.CACHE.drop(p["id"])
            keystore.add("gemini", key, label="Gemini")
    if payload.get("gemini_model"):
        keystore.set_setting("gemini_model", payload["gemini_model"].replace("models/", ""))
    if "shield" in payload:
        keystore.set_setting("shield", bool(payload["shield"]))
    return get_settings()


@app.get("/api/gemini/models")
async def gemini_models():
    g = gemini_entry()
    if not g:
        raise HTTPException(400, "No Gemini API key saved")
    try:
        models = await registry.ADAPTERS["gemini"].list_models(g[1])
    except ProviderError as e:
        raise HTTPException(400, e.message)
    return {"models": [m.id for m in models]}


# ---------------- providers + models ----------------
def provider_view(e: dict, cfg) -> dict:
    st = registry.CACHE.mem.get(cfg.id, {})
    return {"id": cfg.id, "kind": cfg.kind, "name": registry.name_of(cfg.kind), "label": e.get("label", ""),
            "base_url": cfg.base_url if cfg.kind == "custom" or e.get("base_url") else "", "enabled": e.get("enabled", True),
            "hint": e.get("hint", ""), "source": e.get("storage", "keyring"), "local": False,
            "status": ("unavailable" if st.get("error") else "ok") if st else "unknown", "message": st.get("error", ""),
            "model_count": len(st.get("models", []))}


@app.get("/api/providers")
async def providers_list():
    registry.CACHE._load_disk()
    local = await registry.CACHE.local_status()
    out = []
    for cfg in registry.local_configs():
        st = local.get(cfg.id, {})
        out.append({"id": cfg.id, "kind": cfg.kind, "name": cfg.name, "label": "", "base_url": cfg.base_url, "enabled": True,
                    "hint": "", "source": "local", "local": True, "status": "ok" if st.get("ok") else "not running",
                    "message": st.get("error", ""), "model_count": len(st.get("models", []))})
    out += [provider_view(e, cfg) for e, cfg in registry.configured(include_disabled=True)]
    mode = keystore.storage_mode()
    return {"providers": out, "storage": mode,
            "storage_note": "Stored in Windows Credential Manager" if mode == "keyring" else "Stored in a plain file on this PC",
            "kinds": [{"kind": k, "name": n} for k, n, _s, _b, _p, loc in registry.TABLE if not loc]}


@app.post("/api/providers")
async def providers_add(payload: dict):
    raw, kind = payload.get("key", ""), payload.get("provider") or None
    base = payload.get("base_url", "") or ""
    try:
        key = registry.clean_key(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if kind == "custom":
        try:
            base = registry.normalize_base(base)
        except ValueError as e:
            raise HTTPException(400, str(e))
    dup = keystore.find_duplicate(key, base if kind == "custom" else "")
    if dup:
        raise HTTPException(409, f"This key is already added ({registry.name_of(dup['kind'])}{', ' + dup['label'] if dup.get('label') else ''}).")
    det = await registry.detect_provider(key, kind, base)
    if not det.ok:
        return JSONResponse({"detail": det.message, "unrecognised": det.unrecognised, "tried": det.tried}, status_code=400)
    entry = keystore.add(det.kind, key, label=payload.get("label", "") or "", base_url=base if det.kind == "custom" else "")
    cfg = registry.make_config(entry, key)
    for m in det.models:  # the probe ran under the provider type's id; stamp this saved instance's id
        m.provider = cfg.id
    registry.CACHE.mem[cfg.id] = {"ts": time.time(), "sig": registry.CACHE.sig(cfg), "models": det.models, "error": ""}
    registry.CACHE._save_disk()
    return {"provider": provider_view(entry, cfg), "models": [m.to_dict() for m in det.models], "message": det.message}


@app.patch("/api/providers/{pid}")
async def providers_patch(pid: str, payload: dict):
    changes = {k: payload.get(k) for k in ("label", "enabled", "extra_models")}
    if payload.get("base_url") is not None:
        try:
            changes["base_url"] = registry.normalize_base(payload["base_url"]) if payload["base_url"] else ""
        except ValueError as e:
            raise HTTPException(400, str(e))
    if changes.get("extra_models") is not None:
        changes["extra_models"] = [str(x).strip() for x in changes["extra_models"] if str(x).strip()]
    if not keystore.update(pid, **changes):
        raise HTTPException(404, "No such provider")
    registry.CACHE.drop(pid)
    for ent, cfg in registry.configured(include_disabled=True):
        if cfg.id == pid:
            return provider_view(ent, cfg)
    raise HTTPException(404, "No such provider")


@app.delete("/api/providers/{pid}")
async def providers_delete(pid: str):
    if not keystore.remove(pid):
        raise HTTPException(404, "No such provider (keys from environment variables can't be removed here)")
    registry.CACHE.drop(pid)
    return {"ok": True}


@app.get("/api/models")
async def models(refresh: int = 0):
    return await registry.all_models(bool(refresh))


# ---------------- conversations (SQLite) ----------------
def _store():
    return storage.get()


@app.get("/api/conversations")
def conv_list():
    return {"conversations": _store().list_convs()}


@app.post("/api/conversations")
def conv_create(payload: dict):
    return _store().create_conv(str(payload.get("title") or ""), str(payload.get("model") or ""), payload.get("id") or None)


@app.get("/api/conversations/search")
def conv_search(q: str = ""):
    return {"results": _store().search(q)}


@app.post("/api/conversations/import")
def conv_import(payload: dict):
    msgs = payload.get("messages") or []
    if not isinstance(msgs, list):
        raise HTTPException(400, "messages must be a list")
    return _store().import_conv(str(payload.get("title") or "Earlier chats"), msgs)


@app.get("/api/conversations/{cid}")
def conv_get(cid: str):
    c = _store().get_conv(cid)
    if not c:
        raise HTTPException(404, "Conversation not found")
    return c


@app.patch("/api/conversations/{cid}")
def conv_patch(cid: str, payload: dict):
    c = _store().update_conv(cid, payload.get("title"), payload.get("model"))
    if not c:
        raise HTTPException(404, "Conversation not found")
    return c


@app.delete("/api/conversations/{cid}")
def conv_delete(cid: str):
    if not _store().delete_conv(cid):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.post("/api/conversations/{cid}/messages")
def conv_message(cid: str, payload: dict):
    try:
        return _store().upsert_message(cid, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/conversations/{cid}/truncate")
def conv_truncate(cid: str, payload: dict):
    return {"ok": True, "removed": _store().truncate(cid, str(payload.get("from_id") or ""))}


# ---------------- AI ----------------
@app.post("/api/chat")
async def chat_endpoint(payload: dict):
    cfg, model = await chat.resolve_or_400(payload.get("model", ""))
    return chat.LiveStream(chat.stream(cfg, model, payload), media_type="application/x-ndjson")


@app.post("/api/unload")
async def unload(payload: dict):
    model = payload.get("model", "")
    if model.startswith("ollama:"):
        await ollama_adapter.unload(registry.local_configs()[0], model[7:])
    return {"ok": True}


# ---------------- PDF ----------------
@app.post("/api/pdf/merge")
async def pdf_merge(files: List[UploadFile] = File(...)):
    if len(files) < 2:
        raise HTTPException(400, "Pick at least 2 PDFs to merge")
    w = PdfWriter()
    for f in files:
        for p in (await read_pdf(f)).pages:
            w.add_page(p)
    return send_bytes(pdf_bytes(w), "merged.pdf", "application/pdf")


@app.post("/api/pdf/split")
async def pdf_split(file: UploadFile = File(...), ranges: str = Form("")):
    r = await read_pdf(file)
    n, base, items = len(r.pages), stem(file.filename), []
    if not ranges.strip():
        for i, p in enumerate(r.pages, 1):
            w = PdfWriter()
            w.add_page(p)
            items.append((f"{base}_page{i}.pdf", pdf_bytes(w)))
    else:
        for group in [g.strip() for g in ranges.split(",") if g.strip()]:
            w = PdfWriter()
            for i in parse_pages(group, n):
                w.add_page(r.pages[i])
            items.append((f"{base}_{group}.pdf", pdf_bytes(w)))
    return send_bytes(zip_files(items), f"{base}_split.zip", "application/zip")


@app.post("/api/pdf/extract")
async def pdf_extract(file: UploadFile = File(...), pages: str = Form(...)):
    r = await read_pdf(file)
    w = PdfWriter()
    for i in parse_pages(pages, len(r.pages)):
        w.add_page(r.pages[i])
    return send_bytes(pdf_bytes(w), f"{stem(file.filename)}_pages.pdf", "application/pdf")


@app.post("/api/pdf/delete")
async def pdf_delete(file: UploadFile = File(...), pages: str = Form(...)):
    r = await read_pdf(file)
    drop = set(parse_pages(pages, len(r.pages)))
    if len(drop) >= len(r.pages):
        raise HTTPException(400, "That would delete every page")
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i not in drop:
            w.add_page(p)
    return send_bytes(pdf_bytes(w), f"{stem(file.filename)}_edited.pdf", "application/pdf")


@app.post("/api/pdf/rotate")
async def pdf_rotate(file: UploadFile = File(...), angle: int = Form(90), pages: str = Form("")):
    r = await read_pdf(file)
    which = set(parse_pages(pages, len(r.pages))) if pages.strip() else set(range(len(r.pages)))
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        w.add_page(p)
        if i in which:
            w.pages[-1].rotate(angle)
    return send_bytes(pdf_bytes(w), f"{stem(file.filename)}_rotated.pdf", "application/pdf")


STEPS = [  # (ghostscript dpi, jpeg quality, max image side) - best quality first
    (300, 85, 3000), (200, 75, 2400), (150, 65, 2000), (120, 55, 1600),
    (96, 45, 1300), (72, 35, 1000), (60, 25, 800), (50, 18, 600), (40, 12, 450),
]
LEVEL_STEP = {"printer": 1, "ebook": 2, "screen": 5}


def basic_compress(data: bytes, quality: int, max_side: int) -> bytes:
    """Built-in compression (no Ghostscript): recompress images, then streams.
    Steps that hit something unusual are skipped instead of failing."""
    try:
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    except Exception:
        raise HTTPException(400, "Not a readable PDF (or it is password-protected)")
    for page in w.pages:
        try:
            for img in page.images:
                try:
                    im = img.image
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")
                    if max(im.size) > max_side:
                        im.thumbnail((max_side, max_side))
                    img.replace(im, quality=quality)
                except Exception:
                    continue
        except Exception:
            pass
        try:
            page.compress_content_streams()
        except Exception:
            pass
    try:
        w.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    except Exception:
        pass
    try:
        return pdf_bytes(w)
    except Exception:
        return data


def gs_compress(data: bytes, dpi: int):
    gs = ghostscript()
    if not gs:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.pdf"), os.path.join(d, "out.pdf")
        Path(src).write_bytes(data)
        res = subprocess.run([gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5", "-dPDFSETTINGS=/ebook",
                              "-dDownsampleColorImages=true", "-dDownsampleGrayImages=true", "-dDownsampleMonoImages=true",
                              f"-dColorImageResolution={dpi}", f"-dGrayImageResolution={dpi}", f"-dMonoImageResolution={dpi * 2}",
                              "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={dst}", src],
                             capture_output=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if res.returncode == 0 and os.path.exists(dst):
            return Path(dst).read_bytes()
    return None


def pdf_step(data: bytes, i: int) -> bytes:
    dpi, q, side = STEPS[i]
    outs = [basic_compress(data, q, side)]
    g = gs_compress(data, dpi)
    if g:
        outs.append(g)
    return min(outs, key=len)


def size_info(before: int, after: int, target: int = 0, note: str = "") -> str:
    return json.dumps({"before": before, "after": after, "target": target, "note": note})


@app.post("/api/pdf/compress")
async def pdf_compress(file: UploadFile = File(...), level: str = Form("ebook"), target_kb: int = Form(0)):
    data = await file.read()
    target = max(0, target_kb) * 1024
    note = ""
    if target:
        best = data
        out = None
        for i in range(len(STEPS)):
            cand = pdf_step(data, i)
            if len(cand) < len(best):
                best = cand
            if len(cand) <= target:
                out = cand
                break
        if out is None:
            out = best
            note = "smallest possible"
    else:
        out = pdf_step(data, LEVEL_STEP.get(level, 2))
    if len(out) >= len(data):
        out, note = data, note or "already as small as it gets"
    resp = send_bytes(out, f"{stem(file.filename)}_compressed.pdf", "application/pdf")
    resp.headers["X-Info"] = size_info(len(data), len(out), target, note)
    return resp


def _encode_image(im: Image.Image, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    else:
        im.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


@app.post("/api/image/compress")
async def image_compress(files: List[UploadFile] = File(...), level: str = Form("ebook"), target_kb: int = Form(0)):
    target = max(0, target_kb) * 1024
    items, tb, ta, notes = [], 0, 0, set()
    for f in files:
        raw = await f.read()
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
        except Exception:
            raise HTTPException(400, f"'{f.filename}' is not an image I can read")
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        alpha = im.mode in ("RGBA", "LA", "P") and "transparency" in im.info or im.mode in ("RGBA", "LA")
        fmt, ext = ("WEBP", "webp") if alpha else ("JPEG", "jpg")
        im = im.convert("RGBA" if alpha else "RGB")
        if target:
            best, work = None, im
            for _ in range(10):  # shrink dimensions only if quality alone can't reach the target
                lo, hi, found = 10, 95, None
                while lo <= hi:
                    q = (lo + hi) // 2
                    b = _encode_image(work, fmt, q)
                    if len(b) <= target:
                        found, lo = b, q + 1
                    else:
                        hi = q - 1
                    if best is None or len(b) < len(best):
                        best = b
                if found:
                    best = found
                    break
                if min(work.size) < 64:
                    break
                work = work.resize((max(1, int(work.width * 0.8)), max(1, int(work.height * 0.8))), Image.LANCZOS)
            out = best
            if len(out) > target:
                notes.add("smallest possible")
        else:
            q, side = {"printer": (88, 4000), "ebook": (75, 2400), "screen": (55, 1600)}.get(level, (75, 2400))
            work = im.copy()
            if max(work.size) > side:
                work.thumbnail((side, side), Image.LANCZOS)
            out = _encode_image(work, fmt, q)
        if len(out) >= len(raw) and ext == ext_of_name(f.filename):
            out = raw
        tb, ta = tb + len(raw), ta + len(out)
        items.append((f"{stem(f.filename)}_compressed.{ext}", out))
    if len(items) == 1:
        resp = send_bytes(items[0][1], items[0][0], f"image/{items[0][0].rsplit('.', 1)[-1]}")
    else:
        resp = send_bytes(zip_files(items), "compressed_images.zip", "application/zip")
    resp.headers["X-Info"] = size_info(tb, ta, target, ", ".join(sorted(notes)))
    return resp


def ext_of_name(name: str) -> str:
    e = Path(name or "").suffix.lower().lstrip(".")
    return "jpg" if e == "jpeg" else e


@app.post("/api/pdf/to-images")
async def pdf_to_images(file: UploadFile = File(...), fmt: str = Form("png"), dpi: int = Form(150)):
    import pypdfium2 as pdfium

    data = await file.read()
    try:
        doc = pdfium.PdfDocument(data)
    except Exception:
        raise HTTPException(400, "Not a readable PDF")
    fmt = "jpeg" if fmt.lower() in ("jpg", "jpeg") else "png"
    ext = "jpg" if fmt == "jpeg" else "png"
    base, items = stem(file.filename), []
    for i in range(len(doc)):
        im = doc[i].render(scale=max(36, min(dpi, 400)) / 72).to_pil()
        buf = io.BytesIO()
        (im.convert("RGB") if fmt == "jpeg" else im).save(buf, fmt.upper(), quality=90)
        items.append((f"{base}_page{i + 1}.{ext}", buf.getvalue()))
    doc.close()
    if len(items) == 1:
        return send_bytes(items[0][1], items[0][0], f"image/{fmt}")
    return send_bytes(zip_files(items), f"{base}_images.zip", "application/zip")


@app.post("/api/pdf/from-images")
async def pdf_from_images(files: List[UploadFile] = File(...)):
    pages = []
    for f in files:
        try:
            im = Image.open(io.BytesIO(await f.read()))
            im.load()
        except Exception:
            raise HTTPException(400, f"'{f.filename}' is not an image I can read")
        pages.append(im.convert("RGB"))
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return send_bytes(buf.getvalue(), "images.pdf", "application/pdf")


@app.post("/api/pdf/text")
async def pdf_text(file: UploadFile = File(...)):
    """Plain text from a PDF that has a text layer (no AI needed)."""
    r = await read_pdf(file)
    text = "\n\n".join(f"--- Page {i + 1} ---\n{(p.extract_text() or '').strip()}" for i, p in enumerate(r.pages))
    return send_bytes(text.encode("utf-8"), f"{stem(file.filename)}.txt", "text/plain")


# ---------------- images ----------------
@app.post("/api/image/convert")
async def image_convert(files: List[UploadFile] = File(...), fmt: str = Form("jpg"),
                        quality: int = Form(85), max_width: int = Form(0)):
    pil_fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}.get(fmt.lower())
    if not pil_fmt:
        raise HTTPException(400, "Format must be jpg, png or webp")
    ext = "jpg" if pil_fmt == "JPEG" else fmt.lower()
    items = []
    for f in files:
        try:
            im = Image.open(io.BytesIO(await f.read()))
            im.load()
        except Exception:
            raise HTTPException(400, f"'{f.filename}' is not an image I can read")
        if max_width and im.width > max_width:
            im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
        if pil_fmt == "JPEG" and im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, "white")
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        buf = io.BytesIO()
        im.save(buf, pil_fmt, quality=max(1, min(quality, 100)), optimize=True)
        items.append((f"{stem(f.filename)}.{ext}", buf.getvalue()))
    if len(items) == 1:
        return send_bytes(items[0][1], items[0][0], f"image/{ext}")
    return send_bytes(zip_files(items), "converted_images.zip", "application/zip")


# ---------------- office ----------------
@app.post("/api/office/to-pdf")
async def office_to_pdf(file: UploadFile = File(...)):
    so = libreoffice()
    if not so:
        raise HTTPException(400, "LibreOffice is not installed. Install it (free) and this will work.")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "input" + Path(file.filename or "x.pptx").suffix)
        Path(src).write_bytes(await file.read())
        res = subprocess.run([so, "--headless", "--norestore", f"-env:UserInstallation=file:///{d.replace(os.sep, '/')}/lo",
                              "--convert-to", "pdf", "--outdir", d, src],
                             capture_output=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = os.path.join(d, "input.pdf")
        if not os.path.exists(out):
            raise HTTPException(500, "Conversion failed: " + res.stderr.decode(errors="ignore")[-300:])
        data = Path(out).read_bytes()
    return send_bytes(data, f"{stem(file.filename)}.pdf", "application/pdf")


# ---------------- convert anything ----------------
@app.get("/api/convert/formats")
def convert_formats(exts: str = ""):
    """Targets available for each given extension, e.g. ?exts=pdf,jpg"""
    so = bool(libreoffice())
    want = [e.strip().lower().lstrip(".") for e in exts.split(",") if e.strip()]
    return {"libreoffice": so, "ffmpeg": bool(conv.ffmpeg_exe()), "targets": {e: conv.targets(e, so) for e in want}}


@app.post("/api/convert")
async def convert_files(files: List[UploadFile] = File(...), to: str = Form(...)):
    so = libreoffice()
    items = []
    for f in files:
        try:
            items += conv.convert_one(f.filename or "file", await f.read(), to, so)
        except conv.ConvertError as e:
            raise HTTPException(400, str(e))
    name, data = conv.bundle(items)
    media = "application/zip" if name.endswith(".zip") else "application/octet-stream"
    return send_bytes(data, name, media)
