"""§8.1 Regression: the existing file tools must keep behaving exactly as in v0.9.0."""
import io
import json
import zipfile

import pytest
from PIL import Image
from pypdf import PdfReader

from tests.helpers import encrypted_pdf, image_pdf, img_bytes, make_pdf, png_rgba


def pages_text(data: bytes):
    return [(p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(data)).pages]


def pdf_file(data, name="doc.pdf"):
    return {"file": (name, data, "application/pdf")}


def zip_members(data: bytes):
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist()}


# ---------------- merge ----------------
@pytest.mark.parametrize("count", [2, 3])
def test_merge_keeps_page_count_and_order(client, count):
    docs = [make_pdf([f"Doc{d} P{p}" for p in range(1, d + 2)]) for d in range(count)]  # 1, 2, 3 pages
    files = [("files", (f"d{i}.pdf", b, "application/pdf")) for i, b in enumerate(docs)]
    r = client.post("/api/pdf/merge", files=files)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    expected = [f"Doc{d} P{p}" for d in range(count) for p in range(1, d + 2)]
    assert pages_text(r.content) == expected


def test_merge_needs_two_files(client):
    r = client.post("/api/pdf/merge", files=[("files", ("a.pdf", make_pdf(1), "application/pdf"))])
    assert r.status_code == 400
    assert "at least 2" in r.json()["detail"]


# ---------------- split ----------------
def test_split_blank_gives_one_file_per_page(client):
    r = client.post("/api/pdf/split", files=pdf_file(make_pdf(4), "report.pdf"), data={"ranges": ""})
    assert r.status_code == 200, r.text
    m = zip_members(r.content)
    assert sorted(m) == [f"report_page{i}.pdf" for i in range(1, 5)]
    for i in range(1, 5):
        assert pages_text(m[f"report_page{i}.pdf"]) == [f"Page {i}"]


def test_split_by_ranges(client):
    r = client.post("/api/pdf/split", files=pdf_file(make_pdf(4), "report.pdf"), data={"ranges": "1-2, 3-4"})
    assert r.status_code == 200, r.text
    m = zip_members(r.content)
    assert sorted(m) == ["report_1-2.pdf", "report_3-4.pdf"]
    assert pages_text(m["report_1-2.pdf"]) == ["Page 1", "Page 2"]
    assert pages_text(m["report_3-4.pdf"]) == ["Page 3", "Page 4"]


# ---------------- keep / remove pages ----------------
@pytest.mark.parametrize("spec,expected", [
    ("1-3, 8", [1, 2, 3, 8]),
    ("2", [2]),
    ("5-", [5, 6, 7, 8]),
    ("-2", [1, 2]),
])
def test_keep_pages(client, spec, expected):
    r = client.post("/api/pdf/extract", files=pdf_file(make_pdf(8)), data={"pages": spec})
    assert r.status_code == 200, r.text
    assert pages_text(r.content) == [f"Page {i}" for i in expected]


@pytest.mark.parametrize("spec,expected", [
    ("2, 5-7", [1, 3, 4, 8]),
    ("5-", [1, 2, 3, 4]),
])
def test_remove_pages(client, spec, expected):
    r = client.post("/api/pdf/delete", files=pdf_file(make_pdf(8)), data={"pages": spec})
    assert r.status_code == 200, r.text
    assert pages_text(r.content) == [f"Page {i}" for i in expected]


@pytest.mark.parametrize("ep", ["/api/pdf/extract", "/api/pdf/delete"])
@pytest.mark.parametrize("spec,msg", [("9", "outside 1-8"), ("0-2", "outside 1-8"), ("4-2", "outside 1-8"), ("abc", "not a page number")])
def test_bad_page_ranges_are_400_with_message(client, ep, spec, msg):
    r = client.post(ep, files=pdf_file(make_pdf(8)), data={"pages": spec})
    assert r.status_code == 400
    assert msg in r.json()["detail"]


def test_remove_all_pages_is_400(client):
    r = client.post("/api/pdf/delete", files=pdf_file(make_pdf(3)), data={"pages": "1-3"})
    assert r.status_code == 400
    assert "every page" in r.json()["detail"]


# ---------------- rotate ----------------
@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotate_all_pages(client, angle):
    r = client.post("/api/pdf/rotate", files=pdf_file(make_pdf(3)), data={"angle": str(angle), "pages": ""})
    assert r.status_code == 200, r.text
    assert [p.rotation for p in PdfReader(io.BytesIO(r.content)).pages] == [angle] * 3


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotate_some_pages(client, angle):
    r = client.post("/api/pdf/rotate", files=pdf_file(make_pdf(4)), data={"angle": str(angle), "pages": "2,4"})
    assert r.status_code == 200, r.text
    assert [p.rotation for p in PdfReader(io.BytesIO(r.content)).pages] == [0, angle, 0, angle]


# ---------------- compress ----------------
@pytest.fixture(scope="module")
def big_pdf():
    return image_pdf(1600, 1200)


def info(r):
    return json.loads(r.headers["x-info"])


@pytest.mark.parametrize("level", ["printer", "ebook", "screen"])
def test_compress_each_level(client, big_pdf, level):
    r = client.post("/api/pdf/compress", files=pdf_file(big_pdf, "scan.pdf"), data={"level": level, "target_kb": "0"})
    assert r.status_code == 200, r.text
    i = info(r)
    assert i["before"] == len(big_pdf)
    assert i["after"] == len(r.content) < len(big_pdf)
    assert len(PdfReader(io.BytesIO(r.content)).pages) == 1
    assert r.headers["content-disposition"] == 'attachment; filename="scan_compressed.pdf"'


def test_compress_levels_are_ordered(client, big_pdf):
    sizes = {}
    for level in ("printer", "ebook", "screen"):
        r = client.post("/api/pdf/compress", files=pdf_file(big_pdf), data={"level": level})
        sizes[level] = len(r.content)
    assert sizes["screen"] <= sizes["ebook"] <= sizes["printer"]


def test_compress_target_reachable(client, big_pdf):
    target_kb = max(20, len(big_pdf) // 1024 // 4)
    r = client.post("/api/pdf/compress", files=pdf_file(big_pdf), data={"target_kb": str(target_kb)})
    assert r.status_code == 200, r.text
    i = info(r)
    assert len(r.content) <= target_kb * 1024
    assert i["target"] == target_kb * 1024 and i["note"] == ""


def test_compress_target_unreachable_says_smallest_possible(client, big_pdf):
    r = client.post("/api/pdf/compress", files=pdf_file(big_pdf), data={"target_kb": "1"})
    assert r.status_code == 200, r.text
    i = info(r)
    assert i["note"] == "smallest possible"
    assert len(r.content) > 1024 and len(r.content) < len(big_pdf)


def test_compress_already_small_returned_unchanged(client):
    small = make_pdf(["tiny"])
    r = client.post("/api/pdf/compress", files=pdf_file(small), data={"level": "screen"})
    assert r.status_code == 200, r.text
    assert r.content == small
    assert info(r)["note"] == "already as small as it gets"


# ---------------- images ----------------
def test_image_compress_png_with_alpha_becomes_webp_with_alpha(client):
    r = client.post("/api/image/compress", files=[("files", ("logo.png", png_rgba(), "image/png"))], data={"level": "ebook"})
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].endswith('logo_compressed.webp"')
    im = Image.open(io.BytesIO(r.content))
    assert im.format == "WEBP" and "A" in im.getbands()
    assert im.convert("RGBA").getpixel((2, 2))[3] == 0  # transparent pixel stays transparent


def test_image_convert_png_alpha_to_webp_keeps_alpha(client):
    r = client.post("/api/image/convert", files=[("files", ("logo.png", png_rgba(), "image/png"))], data={"fmt": "webp"})
    assert r.status_code == 200, r.text
    im = Image.open(io.BytesIO(r.content))
    assert im.format == "WEBP" and im.convert("RGBA").getpixel((2, 2))[3] == 0


def test_image_convert_rgba_to_jpeg_gets_white_background(client):
    r = client.post("/api/image/convert", files=[("files", ("logo.png", png_rgba(), "image/png"))], data={"fmt": "jpg"})
    assert r.status_code == 200, r.text
    im = Image.open(io.BytesIO(r.content))
    assert im.format == "JPEG"
    assert all(c > 245 for c in im.getpixel((2, 2)))  # was transparent -> white
    red = im.getpixel((60, 30))
    assert red[0] > 200 and red[1] < 60


def test_image_compress_jpeg_target(client):
    from tests.helpers import noisy_image

    buf = io.BytesIO()
    noisy_image(1200, 900).save(buf, "JPEG", quality=95)
    r = client.post("/api/image/compress", files=[("files", ("p.jpg", buf.getvalue(), "image/jpeg"))], data={"target_kb": "60"})
    assert r.status_code == 200, r.text
    assert len(r.content) <= 60 * 1024


def test_image_compress_many_returns_zip(client):
    files = [("files", (f"i{i}.png", img_bytes("PNG"), "image/png")) for i in range(2)]
    r = client.post("/api/image/compress", files=files)
    assert r.status_code == 200
    assert sorted(zip_members(r.content)) == ["i0_compressed.jpg", "i1_compressed.jpg"]


def test_heic_input(client):
    pytest.importorskip("pillow_heif")
    buf = io.BytesIO()
    try:
        Image.new("RGB", (40, 30), "green").save(buf, "HEIF")
    except Exception as e:  # encoder not available in this build of pillow-heif
        pytest.skip(f"NOT RUN - pillow-heif cannot encode HEIC here: {e}")
    r = client.post("/api/image/convert", files=[("files", ("photo.heic", buf.getvalue(), "image/heic"))], data={"fmt": "jpg"})
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).size == (40, 30)


# ---------------- images <-> PDF ----------------
def test_images_to_pdf(client):
    files = [("files", (f"p{i}.jpg", img_bytes("JPEG", (200 + i * 10, 100)), "image/jpeg")) for i in range(3)]
    r = client.post("/api/pdf/from-images", files=files)
    assert r.status_code == 200, r.text
    pages = PdfReader(io.BytesIO(r.content)).pages
    assert len(pages) == 3
    widths = [round(float(p.mediabox.width)) for p in pages]
    assert widths == sorted(widths) and widths[0] < widths[2]  # order preserved


def test_pdf_to_images_single_page_returns_image(client):
    r = client.post("/api/pdf/to-images", files=pdf_file(make_pdf(1), "one.pdf"), data={"fmt": "png", "dpi": "72"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (612, 792)


def test_pdf_to_images_many_pages_returns_zip(client):
    r = client.post("/api/pdf/to-images", files=pdf_file(make_pdf(3), "three.pdf"), data={"fmt": "jpg", "dpi": "72"})
    assert r.status_code == 200, r.text
    m = zip_members(r.content)
    assert sorted(m) == ["three_page1.jpg", "three_page2.jpg", "three_page3.jpg"]
    assert Image.open(io.BytesIO(m["three_page1.jpg"])).format == "JPEG"


def test_pdf_text(client):
    r = client.post("/api/pdf/text", files=pdf_file(make_pdf(["Hello world", "Second"]), "t.pdf"))
    assert r.status_code == 200
    assert r.text == "--- Page 1 ---\nHello world\n\n--- Page 2 ---\nSecond"


# ---------------- bad input: clean 400s ----------------
SINGLE_PDF_ENDPOINTS = [
    ("/api/pdf/split", {"ranges": ""}),
    ("/api/pdf/extract", {"pages": "1"}),
    ("/api/pdf/delete", {"pages": "1"}),
    ("/api/pdf/rotate", {"angle": "90"}),
    ("/api/pdf/compress", {"level": "ebook"}),
    ("/api/pdf/to-images", {"fmt": "png"}),
    ("/api/pdf/text", {}),
]


@pytest.mark.parametrize("ep,data", SINGLE_PDF_ENDPOINTS + [("/api/pdf/merge", {})])
def test_encrypted_pdf_without_password_is_clean_400(client, ep, data):
    enc = encrypted_pdf(2)
    if ep == "/api/pdf/merge":
        r = client.post(ep, files=[("files", ("a.pdf", enc, "application/pdf")), ("files", ("b.pdf", make_pdf(1), "application/pdf"))])
    else:
        r = client.post(ep, files=pdf_file(enc, "locked.pdf"), data=data)
    assert r.status_code == 400, f"{ep}: {r.status_code} {r.text}"
    assert "password" in r.json()["detail"].lower() or "readable" in r.json()["detail"].lower()


BAD = {"zero-byte": b"", "corrupt": b"%PDF-1.4\n garbage \x00\x01\x02 not a pdf", "text": b"hello, I am not a PDF"}


@pytest.mark.parametrize("kind", list(BAD))
@pytest.mark.parametrize("ep,data", SINGLE_PDF_ENDPOINTS)
def test_bad_pdf_is_clean_400(client, ep, data, kind):
    r = client.post(ep, files=pdf_file(BAD[kind], "bad.pdf"), data=data)
    assert r.status_code == 400, f"{ep} {kind}: {r.status_code} {r.text}"
    assert r.json()["detail"]


@pytest.mark.parametrize("kind", list(BAD))
def test_bad_pdf_in_merge_is_clean_400(client, kind):
    r = client.post("/api/pdf/merge", files=[("files", ("bad.pdf", BAD[kind], "application/pdf")), ("files", ("ok.pdf", make_pdf(1), "application/pdf"))])
    assert r.status_code == 400, r.text


@pytest.mark.parametrize("ep,data", [("/api/image/compress", {}), ("/api/image/convert", {"fmt": "png"}), ("/api/pdf/from-images", {})])
@pytest.mark.parametrize("payload", [b"", b"\x89PNG\r\n\x1a\n broken"])
def test_bad_image_is_clean_400(client, ep, data, payload):
    r = client.post(ep, files=[("files", ("x.png", payload, "image/png"))], data=data)
    assert r.status_code == 400, f"{ep}: {r.status_code} {r.text}"


@pytest.mark.parametrize("to", ["txt", "png"])
@pytest.mark.parametrize("kind", list(BAD))
def test_bad_pdf_in_convert_is_clean_400(client, to, kind):
    r = client.post("/api/convert", files=[("files", ("bad.pdf", BAD[kind], "application/pdf"))], data={"to": to})
    assert r.status_code == 400, f"{to} {kind}: {r.status_code} {r.text}"


def test_convert_formats_and_simple_conversion(client):
    r = client.get("/api/convert/formats", params={"exts": "pdf,png,csv"})
    assert r.status_code == 200
    t = r.json()["targets"]
    assert "txt" in t["pdf"] and "jpg" in t["png"] and "json" in t["csv"]
    r = client.post("/api/convert", files=[("files", ("t.csv", b"a,b\n1,2\n", "text/csv"))], data={"to": "json"})
    assert r.status_code == 200 and json.loads(r.content) == [{"a": "1", "b": "2"}]


def test_convert_unsupported_target_is_400(client):
    r = client.post("/api/convert", files=[("files", ("t.csv", b"a\n1\n", "text/csv"))], data={"to": "mp3"})
    assert r.status_code == 400


# ---------------- security: token guard ----------------
def test_api_without_token_is_403():
    from fastapi.testclient import TestClient

    from haven import server

    c = TestClient(server.app)
    assert c.get("/api/status").status_code == 403
    assert c.post("/api/pdf/merge").status_code == 403
    assert c.get("/api/settings", headers={"X-Desk-Token": "wrong"}).status_code == 403
    assert c.get("/api/status", headers={"X-Desk-Token": ""}).status_code == 403
    r = c.get("/")
    assert r.status_code == 200 and "<title>Haven</title>" in r.text


def test_no_cors_headers(client):
    r = client.options("/api/status", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ---------------- desktop store flow ----------------
def test_desk_store_returns_id_name_size_info(client):
    from haven import server

    big = image_pdf(800, 600)
    r = client.post("/api/pdf/compress", files=pdf_file(big, "scan.pdf"), data={"level": "screen"}, headers={"X-Desk-Store": "1"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"id", "name", "size", "info"}
    assert j["name"] == "scan_compressed.pdf"
    name, data = server.RESULTS[j["id"]]
    assert name == j["name"] and len(data) == j["size"]
    assert json.loads(j["info"])["after"] == j["size"]


def test_desk_store_errors_pass_through(client):
    r = client.post("/api/pdf/delete", files=pdf_file(make_pdf(2)), data={"pages": "1-2"}, headers={"X-Desk-Store": "1"})
    assert r.status_code == 400 and "every page" in r.json()["detail"]


def test_status_and_settings_still_work(client):
    s = client.get("/api/status").json()
    assert {"version", "ollama", "models", "gemini", "ghostscript", "libreoffice", "ffmpeg"} <= set(s)
    g = client.get("/api/settings").json()
    assert {"has_key", "key_hint", "gemini_model", "config_path"} <= set(g)
