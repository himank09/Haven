"""Attachment helpers shared by the server and the chat pipeline (moved out of server.py unchanged)."""
import base64
import io
from pathlib import Path
from typing import List

from fastapi import HTTPException
from PIL import Image

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


def image_mime(data: bytes) -> str:
    return "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"


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
