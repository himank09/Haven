"""Haven - local server behind the desktop window.

* Listens on 127.0.0.1 only; every /api call needs the per-launch token,
  so websites open in your browser cannot talk to it.
* Local AI goes to Ollama on this PC. Gemini is used only when you pick it,
  with the key stored in %APPDATA%\\Haven\\settings.json (never in the code).
* Files are processed on this PC and never uploaded (except to Gemini when
  you explicitly choose a Gemini model).
"""
import base64
import glob
import io
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import List

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pypdf import PdfReader, PdfWriter

from haven import convert as conv

try:  # optional: iPhone HEIC photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

VERSION = "0.9.0"
WEB = Path(__file__).parent / "web"
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
GEMINI = os.environ.get("GEMINI_BASE", "https://generativelanguage.googleapis.com")
TOKEN = os.environ.get("HAVEN_TOKEN", "")  # set by app.py for each launch
LOCAL_TEXT_LIMIT = 20000  # chars of PDF text sent to the small local model (~5k tokens)
GEMINI_INLINE_LIMIT = 18 * 1024 * 1024
RESULTS = {}  # id -> (filename, bytes): finished files waiting for the native Save dialog

app = FastAPI(title="Haven", docs_url=None, redoc_url=None, openapi_url=None)
@app.exception_handler(Exception)
async def show_error(request: Request, exc: Exception):
    import traceback

    try:
        (Path(os.environ.get("HAVEN_LOG_DIR") or config_dir()) / "errors.log").open("a", encoding="utf-8").write(traceback.format_exc() + "\n")
    except Exception:
        pass
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


app.mount("/fonts", StaticFiles(directory=WEB / "fonts"), name="fonts")


# ---------------- settings ----------------
def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "Haven"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_settings() -> dict:
    try:
        return json.loads((config_dir() / "settings.json").read_text("utf-8"))
    except Exception:
        return {}


def save_settings(s: dict):
    (config_dir() / "settings.json").write_text(json.dumps(s, indent=2), "utf-8")


def gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or load_settings().get("gemini_key", "")


# ---------------- security + desktop save ----------------
@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and TOKEN and request.headers.get("x-desk-token") != TOKEN:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    try:
        response = await call_next(request)
    except Exception as exc:  # never show a bare "Internal Server Error"
        import traceback

        try:
            (Path(os.environ.get("HAVEN_LOG_DIR") or config_dir()) / "errors.log").open("a", encoding="utf-8").write(traceback.format_exc() + "\n")
        except Exception:
            pass
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)
    # In the desktop window, finished files are kept here and saved via a native Save dialog
    if request.headers.get("x-desk-store") == "1" and response.status_code == 200:
        body = b"".join([chunk async for chunk in response.body_iterator])
        cd = response.headers.get("content-disposition", "")
        name = cd.split('filename="')[-1].rstrip('"') if "filename=" in cd else "result"
        rid = uuid.uuid4().hex
        RESULTS[rid] = (name, body)
        while len(RESULTS) > 10:
            RESULTS.pop(next(iter(RESULTS)))
        return JSONResponse({"id": rid, "name": name, "size": len(body), "info": response.headers.get("x-info", "")})
    return response


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


def render_pdf_pages(data: bytes, max_pages: int = 4, scale: float = 1.5) -> List[bytes]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    out = []
    for i in range(min(len(doc), max_pages)):
        im = doc[i].render(scale=scale).to_pil().convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        out.append(buf.getvalue())
    doc.close()
    return out


TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".sql", ".tex", ".log", ".xml", ".yaml", ".yml"}


def guess_mime(name: str, mime: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext in (".png", ".webp", ".gif", ".heic", ".heif"):
        return "image/" + ext[1:]
    if ext in TEXT_EXT:
        return "text/plain"
    return mime or "application/octet-stream"


def decode_files(files) -> List[dict]:
    out = []
    for f in files or []:
        try:
            data = base64.b64decode(f.get("data", ""))
        except Exception:
            raise HTTPException(400, f"Could not read attachment {f.get('name')}")
        out.append({"name": f.get("name", "file"), "mime": guess_mime(f.get("name", ""), f.get("mime", "")), "data": data})
    return out


def normalize_image(data: bytes) -> bytes:
    """Any image (incl. HEIC/WebP) -> JPEG/PNG bytes most models accept."""
    im = Image.open(io.BytesIO(data))
    im.load()
    if max(im.size) > 2000:
        im.thumbnail((2000, 2000))
    buf = io.BytesIO()
    if im.mode in ("RGBA", "LA", "P"):
        im.convert("RGBA").save(buf, "PNG")
    else:
        im.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ---------------- providers ----------------
def ollama_messages(messages, files):
    """Attach files to the last user message in Ollama's format."""
    msgs = [{"role": m["role"], "content": m.get("content", "")} for m in messages]
    if not files:
        return msgs, []
    notes, images, extra_text = [], [], []
    for f in files:
        if f["mime"].startswith("image/"):
            images.append(base64.b64encode(normalize_image(f["data"])).decode())
        elif f["mime"] == "application/pdf":
            r = open_pdf(f["data"], f["name"])
            text = "\n\n".join(f"[Page {i + 1}]\n{(p.extract_text() or '').strip()}" for i, p in enumerate(r.pages))
            if len(text.replace("[Page", "").strip()) < 40 * max(1, len(r.pages)):  # scanned PDF -> look at it
                pages = render_pdf_pages(f["data"], max_pages=3)
                images += [base64.b64encode(p).decode() for p in pages]
                notes.append(f"'{f['name']}' looks scanned; the model sees images of its first {len(pages)} page(s).")
            else:
                if len(text) > LOCAL_TEXT_LIMIT:
                    notes.append(f"'{f['name']}' is long; the local model only sees the first ~{LOCAL_TEXT_LIMIT // 1000}k characters. Use Gemini for the full document.")
                    text = text[:LOCAL_TEXT_LIMIT]
                extra_text.append(f"<document name=\"{f['name']}\">\n{text}\n</document>")
        elif f["mime"] == "text/plain":
            extra_text.append(f"<document name=\"{f['name']}\">\n{f['data'].decode('utf-8', 'ignore')[:LOCAL_TEXT_LIMIT]}\n</document>")
        else:
            notes.append(f"'{f['name']}' type isn't supported (convert it to PDF first).")
    for m in reversed(msgs):
        if m["role"] == "user":
            if extra_text:
                m["content"] = "\n\n".join(extra_text) + "\n\n" + m["content"]
            if images:
                m["images"] = images
            break
    return msgs, notes


def gemini_body(messages, files, system, think):
    contents = []
    for m in messages:
        contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m.get("content", "") or " "}]})
    if files:
        total = sum(len(f["data"]) for f in files)
        if total > GEMINI_INLINE_LIMIT:
            raise HTTPException(400, "Attachments are over ~18 MB. Compress the PDF first.")
        parts = []
        for f in files:
            if f["mime"].startswith("image/"):
                img = normalize_image(f["data"])
                mt = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
                parts.append({"inline_data": {"mime_type": mt, "data": base64.b64encode(img).decode()}})
            elif f["mime"] == "application/pdf":
                parts.append({"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(f["data"]).decode()}})
            elif f["mime"] == "text/plain":
                parts.append({"text": f"<document name=\"{f['name']}\">\n{f['data'].decode('utf-8', 'ignore')}\n</document>"})
        for c in reversed(contents):
            if c["role"] == "user":
                c["parts"] = parts + c["parts"]
                break
    body = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if think:
        body["generationConfig"] = {"thinkingConfig": {"includeThoughts": True}}
    return body


def line(**kw) -> str:
    return json.dumps(kw) + "\n"


async def stream_ollama(model, messages, files, system, think):
    msgs, notes = ollama_messages(messages, files)
    if system:
        msgs = [{"role": "system", "content": system}] + msgs
    for n in notes:
        yield line(note=n)
    body = {"model": model, "messages": msgs, "think": bool(think), "stream": True}
    try:
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("POST", f"{OLLAMA}/api/chat", json=body) as r:
                if r.status_code != 200:
                    err = (await r.aread()).decode(errors="ignore")
                    if "does not support" in err and "image" in err:
                        err = "This local model can't read images. Pick a vision model or use Gemini."
                    yield line(error=err or f"Ollama returned {r.status_code}")
                    return
                async for ln in r.aiter_lines():
                    if not ln.strip():
                        continue
                    j = json.loads(ln)
                    msg = j.get("message", {})
                    out = {}
                    if msg.get("thinking"):
                        out["thinking"] = msg["thinking"]
                    if msg.get("content"):
                        out["content"] = msg["content"]
                    if j.get("done"):
                        out["done"] = True
                        if j.get("eval_count") and j.get("eval_duration"):
                            out["speed"] = round(j["eval_count"] / (j["eval_duration"] / 1e9), 1)
                    if out:
                        yield line(**out)
    except httpx.ConnectError:
        yield line(error="Ollama is not running. Open Ollama from the Start menu and try again.")


async def stream_gemini(model, messages, files, system, think):
    key = gemini_key()
    if not key:
        yield line(error="No Gemini API key yet. Add it in Settings.")
        return
    model = model if model.startswith("models/") else f"models/{model}"
    url = f"{GEMINI}/v1beta/{model}:streamGenerateContent?alt=sse"
    body = gemini_body(messages, files, system, think)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15)) as c:
            for attempt in (1, 2):
                async with c.stream("POST", url, json=body, headers=headers) as r:
                    if r.status_code != 200:
                        raw = (await r.aread()).decode(errors="ignore")
                        if r.status_code == 400 and "generationConfig" in body and attempt == 1:
                            body.pop("generationConfig")  # model doesn't support thought summaries
                            continue
                        try:
                            msg = json.loads(raw)["error"]["message"]
                        except Exception:
                            msg = raw[:300]
                        if r.status_code in (401, 403):
                            msg = "Gemini rejected the API key. Check it in Settings. (" + msg + ")"
                        elif r.status_code == 429:
                            msg = "Gemini free-tier limit reached. Wait a minute or switch to the local model. (" + msg + ")"
                        yield line(error=msg)
                        return
                    async for ln in r.aiter_lines():
                        if not ln.startswith("data:"):
                            continue
                        try:
                            j = json.loads(ln[5:].strip())
                        except Exception:
                            continue
                        for cand in j.get("candidates", [])[:1]:
                            for p in cand.get("content", {}).get("parts", []):
                                if "text" in p:
                                    yield line(**({"thinking": p["text"]} if p.get("thought") else {"content": p["text"]}))
                            if cand.get("finishReason") not in (None, "STOP", "MAX_TOKENS"):
                                yield line(note=f"Gemini stopped: {cand['finishReason']}")
                    yield line(done=True)
                    return
    except httpx.ConnectError:
        yield line(error="Can't reach Gemini. Check your internet connection.")
    except httpx.ReadTimeout:
        yield line(error="Gemini took too long to answer. Try again.")


# ---------------- pages + status ----------------
@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/status")
async def status():
    ollama_ok, models = False, []
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{OLLAMA}/api/tags")
            ollama_ok = r.status_code == 200
            models = [m["name"] for m in r.json().get("models", []) if not m["name"].endswith("cloud")]
    except Exception:
        pass
    s = load_settings()
    return {
        "version": VERSION,
        "ollama": ollama_ok,
        "models": models,
        "gemini": bool(gemini_key()),
        "gemini_model": s.get("gemini_model", "gemini-2.5-flash"),
        "ghostscript": bool(ghostscript()),
        "libreoffice": bool(libreoffice()),
        "ffmpeg": bool(conv.ffmpeg_exe()),
    }


@app.get("/api/settings")
def get_settings():
    s, k = load_settings(), gemini_key()
    return {
        "has_key": bool(k),
        "key_hint": ("..." + k[-4:]) if k else "",
        "key_from_env": bool(os.environ.get("GEMINI_API_KEY")),
        "gemini_model": s.get("gemini_model", "gemini-2.5-flash"),
        "config_path": str(config_dir() / "settings.json"),
    }


@app.post("/api/settings")
def set_settings(payload: dict):
    s = load_settings()
    if payload.get("clear_key"):
        s.pop("gemini_key", None)
    if payload.get("gemini_key"):
        s["gemini_key"] = payload["gemini_key"].strip()
    if payload.get("gemini_model"):
        s["gemini_model"] = payload["gemini_model"].replace("models/", "")
    save_settings(s)
    return get_settings()


@app.get("/api/gemini/models")
async def gemini_models():
    key = gemini_key()
    if not key:
        raise HTTPException(400, "No Gemini API key saved")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{GEMINI}/v1beta/models", params={"pageSize": 200}, headers={"x-goog-api-key": key})
    except httpx.HTTPError:
        raise HTTPException(502, "Can't reach Gemini. Check your internet connection.")
    if r.status_code != 200:
        raise HTTPException(400, "Gemini rejected the key: " + r.text[:200])
    skip = ("embedding", "tts", "image-generation", "native-audio", "live", "aqa", "imagen", "veo", "robotics", "computer-use")
    names = [m["name"].replace("models/", "") for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m["name"]
             and not any(s in m["name"] for s in skip)]
    names.sort(key=lambda n: (0 if "flash" in n else 1, "preview" in n or "exp" in n, n), reverse=False)
    return {"models": names}


# ---------------- AI ----------------
@app.post("/api/chat")
async def chat(payload: dict):
    model = payload.get("model", "")
    provider, _, name = model.partition(":")
    if provider not in ("ollama", "gemini") or not name:
        raise HTTPException(400, "Pick a model first")
    files = decode_files(payload.get("files"))
    messages = payload.get("messages", [])
    args = (name, messages, files, payload.get("system"), payload.get("think", False))
    gen = stream_ollama(*args) if provider == "ollama" else stream_gemini(*args)
    return StreamingResponse(gen, media_type="application/x-ndjson")


@app.post("/api/unload")
async def unload(payload: dict):
    model = payload.get("model", "")
    if model.startswith("ollama:"):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{OLLAMA}/api/generate", json={"model": model[7:], "keep_alive": 0})
        except Exception:
            pass
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
