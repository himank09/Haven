"""Convert files between formats, all on this PC.

Engines:
  * Pillow / pypdfium2 / pypdf - images and PDFs (always available)
  * ffmpeg (bundled via imageio-ffmpeg) - audio and video
  * LibreOffice (optional, if installed) - Word / Excel / PowerPoint / ODF / HTML
"""
import io
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

IMG_IN = {"jpg", "jpeg", "png", "webp", "heic", "heif", "bmp", "gif", "tif", "tiff", "ico", "avif"}
IMG_OUT = ["jpg", "png", "webp", "pdf", "bmp", "tiff", "gif", "ico"]
AUDIO_IN = {"mp3", "wav", "m4a", "aac", "ogg", "oga", "flac", "opus", "wma", "aiff", "amr"}
AUDIO_OUT = ["mp3", "wav", "m4a", "ogg", "flac"]
VIDEO_IN = {"mp4", "mov", "mkv", "webm", "avi", "m4v", "wmv", "flv", "3gp", "mpeg", "mpg", "ts"}
VIDEO_OUT = ["mp4", "webm", "mov", "mkv", "avi", "gif", "mp3", "wav"]
WRITER_IN = {"doc", "docx", "odt", "rtf", "txt", "html", "htm", "md", "wpd", "pages"}
WRITER_OUT = ["pdf", "docx", "odt", "rtf", "txt", "html"]
CALC_IN = {"xls", "xlsx", "ods", "csv", "tsv"}
CALC_OUT = ["pdf", "xlsx", "ods", "csv", "html"]
IMPRESS_IN = {"ppt", "pptx", "odp", "key"}
IMPRESS_OUT = ["pdf", "pptx", "odp"]

LO_FILTER = {  # explicit export filters where LibreOffice needs them
    "txt": "txt:Text (encoded):UTF8", "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "docx": "docx:MS Word 2007 XML", "xlsx": "xlsx:Calc MS Excel 2007 XML", "pptx": "pptx:Impress MS PowerPoint 2007 XML",
}


class ConvertError(Exception):
    pass


def ext_of(name: str) -> str:
    return Path(name or "").suffix.lower().lstrip(".")


def ffmpeg_exe():
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil

        return shutil.which("ffmpeg")


def targets(ext: str, has_lo: bool) -> list:
    """What a file with this extension can become."""
    e = ext.lower()
    out = []
    if e in IMG_IN:
        out = [x for x in IMG_OUT if x not in (e, "jpeg" if e == "jpg" else "")]
        if e == "gif":
            out += ["mp4", "webm"]
        if e in ("jpeg",):
            out = [x for x in out if x != "jpg"]
    elif e == "pdf":
        out = ["png", "jpg", "webp", "txt", "html", "md"] + (["docx", "odt"] if has_lo else [])
    elif e in AUDIO_IN:
        out = [x for x in AUDIO_OUT if x != e]
    elif e in VIDEO_IN:
        out = [x for x in VIDEO_OUT if x != e]
    elif e == "md":
        out = ["html", "txt"] + (["pdf", "docx", "odt"] if has_lo else [])
    elif e in ("txt",):
        out = ["md", "html"] + (["pdf", "docx", "odt"] if has_lo else [])
    elif e in ("html", "htm"):
        out = ["txt", "md"] + (["pdf", "docx", "odt"] if has_lo else [])
    elif e == "csv" or e == "tsv":
        out = (["xlsx", "ods", "pdf", "html"] if has_lo else []) + ["json"]
    elif e in WRITER_IN and has_lo:
        out = [x for x in WRITER_OUT if x != e]
    elif e in CALC_IN and has_lo:
        out = [x for x in CALC_OUT if x != e]
    elif e in IMPRESS_IN and has_lo:
        out = [x for x in IMPRESS_OUT if x != e] + ["png"]
    if e == "json":
        out = ["csv"]
    seen, res = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            res.append(x)
    return res


# ---------------- engines ----------------
def _img(data: bytes, to: str) -> bytes:
    im = Image.open(io.BytesIO(data))
    im.load()
    buf = io.BytesIO()
    if to == "pdf":
        frames = []
        try:
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                frames.append(im.convert("RGB"))
        except EOFError:
            pass
        frames = frames or [im.convert("RGB")]
        frames[0].save(buf, "PDF", save_all=True, append_images=frames[1:], resolution=150)
        return buf.getvalue()
    fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF", "gif": "GIF", "ico": "ICO"}[to]
    if fmt in ("JPEG", "BMP") and im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, "white")
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    if fmt == "ICO":
        im = im.convert("RGBA")
        im.thumbnail((256, 256))
        im.save(buf, "ICO", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256) if s <= max(im.size)])
    elif fmt == "GIF":
        im.convert("RGBA" if "A" in im.mode else "RGB").save(buf, "GIF")
    else:
        im.save(buf, fmt, quality=90, optimize=True) if fmt in ("JPEG", "WEBP") else im.save(buf, fmt)
    return buf.getvalue()


def _pdf_pages(data: bytes, to: str, stem: str):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    fmt = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}[to]
    items = []
    for i in range(len(doc)):
        im = doc[i].render(scale=150 / 72).to_pil()
        buf = io.BytesIO()
        (im.convert("RGB") if fmt != "PNG" else im).save(buf, fmt, quality=90)
        items.append((f"{stem}_page{i + 1}.{to}", buf.getvalue()))
    doc.close()
    return items


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(data))
    return "\n\n".join((p.extract_text() or "").strip() for p in r.pages)


def _md_to_html(text: str, title: str) -> str:
    import markdown

    body = markdown.markdown(text, extensions=["tables", "fenced_code"])
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head><body>{body}</body></html>"


def _html_to_text(html: str) -> str:
    import re
    from html import unescape

    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def _ffmpeg(data: bytes, src_ext: str, to: str) -> bytes:
    exe = ffmpeg_exe()
    if not exe:
        raise ConvertError("Audio/video converter isn't installed. Run setup again.")
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in." + src_ext), os.path.join(d, "out." + to)
        Path(src).write_bytes(data)
        a = {
            "mp3": ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"],
            "wav": ["-vn", "-c:a", "pcm_s16le"],
            "m4a": ["-vn", "-c:a", "aac", "-b:a", "192k"],
            "ogg": ["-vn", "-c:a", "libvorbis", "-q:a", "5"],
            "flac": ["-vn", "-c:a", "flac"],
            "mp4": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"],
            "mov": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"],
            "mkv": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac"],
            "avi": ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame"],
            "webm": ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus"],
            "gif": ["-vf", "fps=12,scale='min(640,iw)':-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0"],
        }[to]
        res = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", src, *a, dst],
                             capture_output=True, timeout=3600, creationflags=NOWIN)
        if res.returncode != 0 or not os.path.exists(dst):
            raise ConvertError("Conversion failed: " + res.stderr.decode(errors="ignore")[-300:])
        return Path(dst).read_bytes()


def _libreoffice(so: str, data: bytes, src_ext: str, to: str) -> bytes:
    if not so:
        raise ConvertError("This needs LibreOffice (free). See Settings > Add-ons, then try again.")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "input." + src_ext)
        Path(src).write_bytes(data)
        args = [so, "--headless", "--norestore", f"-env:UserInstallation=file:///{d.replace(os.sep, '/')}/lo"]
        if src_ext == "pdf":
            args.append("--infilter=writer_pdf_import")
        args += ["--convert-to", LO_FILTER.get(to, to), "--outdir", os.path.join(d, "out"), src]
        res = subprocess.run(args, capture_output=True, timeout=600, creationflags=NOWIN)
        outs = list(Path(d, "out").glob("input.*")) if Path(d, "out").exists() else []
        if not outs:
            raise ConvertError("Conversion failed: " + res.stderr.decode(errors="ignore")[-300:])
        return outs[0].read_bytes()


def convert_one(name: str, data: bytes, to: str, so: str = None):
    """Returns a list of (filename, bytes)."""
    src = ext_of(name)
    stem = Path(name).stem or "file"
    to = to.lower().lstrip(".")
    if to not in targets(src, bool(so)):
        raise ConvertError(f"Can't convert .{src or '?'} to .{to}" + ("" if so else " (some formats need LibreOffice)"))
    out = f"{stem}.{to}"
    # images
    if src in IMG_IN and to in IMG_OUT:
        return [(out, _img(data, to))]
    if src == "gif" and to in ("mp4", "webm"):
        return [(out, _ffmpeg(data, src, to))]
    # pdf
    if src == "pdf":
        if to in ("png", "jpg", "webp"):
            return _pdf_pages(data, to, stem)
        text = _pdf_text(data)
        if to == "txt":
            return [(out, text.encode("utf-8"))]
        if to == "md":
            return [(out, text.encode("utf-8"))]
        if to == "html":
            return [(out, _md_to_html(text.replace("\n", "  \n"), stem).encode("utf-8"))]
        return [(out, _libreoffice(so, data, "pdf", to))]
    # audio / video
    if src in AUDIO_IN or src in VIDEO_IN:
        return [(out, _ffmpeg(data, src, to))]
    # text family
    if src in ("md", "txt", "html", "htm"):
        text = data.decode("utf-8", "ignore")
        if src == "md" and to == "html":
            return [(out, _md_to_html(text, stem).encode("utf-8"))]
        if src == "txt" and to == "md":
            return [(out, data)]
        if src == "txt" and to == "html":
            return [(out, _md_to_html(text.replace("\n", "  \n"), stem).encode("utf-8"))]
        if src in ("html", "htm") and to in ("txt", "md"):
            return [(out, _html_to_text(text).encode("utf-8"))]
        if src == "md" and to == "txt":
            return [(out, data)]
        # to pdf/docx/odt via LibreOffice (markdown is rendered to HTML first)
        if src == "md":
            data, src = _md_to_html(text, stem).encode("utf-8"), "html"
        return [(out, _libreoffice(so, data, src, to))]
    # csv / json
    if src in ("csv", "tsv") and to == "json":
        import csv
        import json

        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig", "ignore")), delimiter="\t" if src == "tsv" else ","))
        return [(out, json.dumps(rows, indent=2, ensure_ascii=False).encode("utf-8"))]
    if src == "json" and to == "csv":
        import csv
        import json

        rows = json.loads(data.decode("utf-8-sig", "ignore"))
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            raise ConvertError("JSON must be a list of objects to become a CSV")
        keys = list(dict.fromkeys(k for r in rows for k in r))
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
        return [(out, buf.getvalue().encode("utf-8"))]
    # office documents
    if to == "png" and src in IMPRESS_IN:  # slides -> one image per slide
        pdf = _libreoffice(so, data, src, "pdf")
        return _pdf_pages(pdf, "png", stem)
    return [(out, _libreoffice(so, data, src, to))]


def bundle(items):
    if len(items) == 1:
        return items[0]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in items:
            z.writestr(n, b)
    return ("converted.zip", buf.getvalue())
