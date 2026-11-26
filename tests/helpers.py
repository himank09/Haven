"""Small builders for test files (PDFs with real text, images)."""
import io
import random

from PIL import Image


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(pages, size=(612, 792)) -> bytes:
    """A real PDF with one text page per item in `pages` (strings; lines split on \n).

    Each page is extractable with pypdf, so tests can check order and content.
    An int means that many pages labelled 'Page 1', 'Page 2', ...
    """
    if isinstance(pages, int):
        pages = [f"Page {i}" for i in range(1, pages + 1)]
    objs = []  # index 0 -> object 1

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    catalog = add(b"")  # placeholder, filled later
    pages_id = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for text in pages:
        lines = str(text).split("\n")
        ops = ["BT", "/F1 11 Tf", "14 TL", f"40 {size[1] - 50} Td"]
        for ln in lines:
            ops.append(f"({_esc(ln)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_id, size[0], size[1], font, content)))
    objs[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objs[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, xref))
    return out.getvalue()


def noisy_image(w=1600, h=1200, mode="RGB", seed=1) -> Image.Image:
    """Hard-to-compress photo-like image (random noise over gradients)."""
    rnd = random.Random(seed)
    im = Image.effect_noise((w, h), 80).convert("L")
    grad = Image.linear_gradient("L").resize((w, h))
    rgb = Image.merge("RGB", (im, grad, Image.eval(im, lambda v: (v * 3 + rnd.randint(0, 2)) % 256)))
    return rgb.convert(mode) if mode != "RGB" else rgb


def image_pdf(w=1600, h=1200) -> bytes:
    """A PDF made of one high-quality photo-like image (compressible)."""
    buf = io.BytesIO()
    noisy_image(w, h).save(buf, "PDF", resolution=150, quality=95)
    return buf.getvalue()


def png_rgba(w=64, h=64) -> bytes:
    im = Image.new("RGBA", (w, h), (255, 0, 0, 255))
    for x in range(w // 2):  # left half fully transparent
        for y in range(h):
            im.putpixel((x, y), (0, 0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def img_bytes(fmt="PNG", size=(64, 48), color="blue") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def encrypted_pdf(n=2) -> bytes:
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(n))))
    w.encrypt("secret")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()
