"""§8.5 Long PDFs: retrieval instead of truncation, page citations."""
import base64
import json
import random
import time

import httpx
import pytest

from haven import docs
from tests.fakes import keys as K
from tests.fakes.hub import ndjson_ollama
from tests.helpers import image_pdf, make_pdf

H = {"X-Desk-Token": "test-token"}
VOCAB = ("river mountain budget energy village market teacher garden window bridge harvest monsoon station ledger "
         "copper canvas lantern orbit meadow signal timber valley harbor quartz pepper cotton saffron rail ferry "
         "festival clinic tribunal invoice warranty mineral turbine estuary plateau granary").split()


def covers(note, page):
    """True if the note's page list ('p. 1, 14-16, 88.') includes `page`."""
    lst = note.split("p. ", 1)[1].rstrip(".")
    for part in lst.split(", "):
        a, _, b = part.partition("-")
        if part != "…" and int(a) <= page <= int(b or a):
            return True
    return False


def filler_pages(n, fact_page=None, fact="", chars=1400, seed=7):
    rnd = random.Random(seed)
    pages = []
    for i in range(1, n + 1):
        words, size = [], 0
        while size < chars:
            w = rnd.choice(VOCAB)
            words.append(w)
            size += len(w) + 1
        lines = [" ".join(words[k:k + 12]) + "." for k in range(0, len(words), 12)]
        if i == fact_page:
            lines.insert(len(lines) // 2, fact)
        pages.append(f"Chapter page {i}\n" + "\n".join(lines))
    return pages


FACT = "The secret launch code is ZEBRA-42-ALPHA and it was approved by the night auditor."


@pytest.fixture(scope="module")
def pdf300():
    return make_pdf(filler_pages(300, 217, FACT))


# ---------------- unit: chunking, BM25, spread, budget ----------------
def test_chunking_keeps_page_numbers_and_size():
    pages = ["short page", "\n\n".join(["para " * 100] * 8), "", "x" * 5000]
    ch = docs.chunk_pages(pages)
    assert {p for p, _ in ch} == {0, 1, 3}  # empty page skipped
    assert all(len(t) <= docs.CHUNK for _, t in ch)
    assert sum(1 for p, _ in ch if p == 1) >= 2 and sum(1 for p, _ in ch if p == 3) >= 3


def test_bm25_finds_unique_fact_on_page_217():
    doc = docs.Doc(pages=filler_pages(300, 217, FACT))
    doc.chunks = docs.chunk_pages(doc.pages)
    top = docs.bm25(doc, "What is the secret launch code?")
    assert doc.chunks[top[0][0]][0] + 1 == 217
    sel = docs.select("big.pdf", doc, 20_000, "What is the secret launch code?")
    assert sel.retrieved and 217 in sel.pages and 1 in sel.pages
    assert "ZEBRA-42-ALPHA" in sel.text and "[Page 217]" in sel.text
    assert len(sel.text) <= 20_000
    # re-sorted into page order
    order = [int(x) for x in __import__("re").findall(r"\[Page (\d+)\]", sel.text)]
    assert order == sorted(order)
    assert sel.note.startswith("'big.pdf' has 300 pages; read the most relevant: p. 1, ") and covers(sel.note, 217)


def test_short_pdf_sent_whole_without_note():
    doc = docs.Doc(pages=filler_pages(3, chars=500))
    doc.chunks = docs.chunk_pages(doc.pages)
    sel = docs.select("short.pdf", doc, 20_000, "anything")
    assert not sel.retrieved and sel.note is None and sel.pages == [1, 2, 3]
    assert sel.text == docs.marked(doc.pages)


def test_whole_document_action_spreads_across_the_document():
    doc = docs.Doc(pages=filler_pages(300))
    doc.chunks = docs.chunk_pages(doc.pages)
    sel = docs.select("big.pdf", doc, 20_000, "Summarise", whole=True)
    assert min(sel.pages) <= 3 and max(sel.pages) >= 295
    deciles = {(p - 1) * 10 // 300 for p in sel.pages}
    assert deciles == set(range(10)), sorted(sel.pages)
    assert "read pages spread across it" in sel.note


def test_fair_budget_allocation():
    assert docs.allocate([100, 100], 1000) == [100, 100]
    assert docs.allocate([100, 5000, 5000], 1000) == [100, 450, 450]
    assert docs.allocate([5000, 5000], 1000) == [500, 500]
    assert sum(docs.allocate([10, 20, 9999, 9999, 5], 3000)) <= 3000


def test_page_ranges_format():
    assert docs.page_ranges([1, 14, 15, 16, 88]) == "1, 14-16, 88"
    assert docs.page_ranges([3]) == "3"


def test_edge_cases_no_crash():
    for pages in ([""], ["", "", ""], ["only page"], ["a", "", "", "b"] * 50):
        doc = docs.Doc(pages=pages)
        doc.chunks = docs.chunk_pages(pages)
        docs.select("e.pdf", doc, 50, "question about b")
        docs.select("e.pdf", doc, 50, "", whole=True)


def test_retrieval_on_2000_pages_under_1_5s():
    pages = filler_pages(2000, 1999, FACT, chars=1500)
    t0 = time.perf_counter()
    doc = docs.Doc(pages=pages)
    doc.chunks = docs.chunk_pages(pages)
    sel = docs.select("huge.pdf", doc, 20_000, "secret launch code")
    took = time.perf_counter() - t0
    print(f"\nchunk + index + retrieve over 2,000 pages: {took * 1000:.0f} ms")
    assert 1999 in sel.pages and took < 1.5
    t0 = time.perf_counter()
    docs.select("huge.pdf", doc, 20_000, "night auditor approved")  # index is reused
    assert time.perf_counter() - t0 < 0.3


# ---------------- end to end: a fake model that echoes what it was given ----------------
def echo(body):
    msgs = body.get("messages") or []
    user = [m for m in msgs if m.get("role") == "user"][-1]["content"]
    sysm = " ".join(m["content"] for m in msgs if m.get("role") == "system")
    return ndjson_ollama([json.dumps({"user": user, "system": sysm})])


def ask(live, files, question="What is the secret launch code?", whole=False, model="ollama:qwen3:4b"):
    body = {"model": model, "messages": [{"role": "user", "content": question}], "files": files, "whole": whole}
    events = []
    with httpx.Client(timeout=120) as c:
        with c.stream("POST", live.base + "/api/chat", json=body, headers=H) as r:
            assert r.status_code == 200
            for ln in r.iter_lines():
                if ln.strip():
                    events.append(json.loads(ln))
    content = "".join(e.get("content", "") for e in events)
    return events, (json.loads(content) if content.startswith("{") else content)


def f(name, data, mime="application/pdf"):
    return {"name": name, "mime": mime, "data": base64.b64encode(data).decode()}


def test_e2e_question_retrieves_page_217_and_cites(live, hub, pdf300):
    hub["ollama"].chunk_fn = echo
    events, seen = ask(live, [f("report.pdf", pdf300)])
    assert "ZEBRA-42-ALPHA" in seen["user"] and "[Page 217]" in seen["user"]
    assert len(seen["user"]) < 22_000  # local budget, not the whole 420k document
    assert "(p. N)" in seen["system"] or "(p. 12)" in seen["system"]
    notes = [e["note"] for e in events if "note" in e]
    assert any(n.startswith("'report.pdf' has 300 pages; read the most relevant: p. 1,") and covers(n, 217) for n in notes)
    d = [e["docs"] for e in events if "docs" in e][0]
    assert d["pages"] == 300 and d["previews"]["217"].startswith("Chapter page 217")  # first ~200 chars of the page
    assert len(d["previews"]["217"]) <= 201


def test_e2e_short_pdf_whole_text_no_note(live, hub):
    hub["ollama"].chunk_fn = echo
    events, seen = ask(live, [f("one.pdf", make_pdf(["Total due: 4,500 rupees by 30 June."]))], "How much is due?")
    assert "[Page 1]\nTotal due: 4,500 rupees by 30 June." in seen["user"]
    assert not any("pages;" in e.get("note", "") for e in events)


def test_e2e_summary_action_spreads(live, hub, pdf300):
    hub["ollama"].chunk_fn = echo
    events, seen = ask(live, [f("report.pdf", pdf300)], "Summarise this.", whole=True)
    import re
    pages = [int(x) for x in re.findall(r"\[Page (\d+)\]", seen["user"])]
    assert min(pages) <= 3 and max(pages) >= 295
    assert any("spread across it" in e.get("note", "") for e in events)


def test_e2e_scanned_pdf_keeps_image_path(live, hub):
    hub["ollama"].models = {"models": [{"name": "llava:7b", "digest": "v1"}]}
    hub["ollama"].show = {"llava:7b": {"capabilities": ["completion", "vision"]}}
    hub["ollama"].chunks = ndjson_ollama(["saw it"])
    events, _ = ask(live, [f("scan.pdf", image_pdf(600, 800))], "Read this", model="ollama:llava:7b")
    req = hub["ollama"].chat_requests()[-1]["json"]
    assert len(req["messages"][-1]["images"]) == 1
    assert any("looks scanned" in e.get("note", "") for e in events)
    assert not any("docs" in e for e in events)


def test_e2e_edge_pdfs_no_crash(live, hub):
    hub["ollama"].chunk_fn = echo
    for data in (make_pdf(["", "real text on page two " * 30, ""]), make_pdf(["single page"]), image_pdf(200, 200)):
        events, _ = ask(live, [f("e.pdf", data)], "what?")
        assert events[-1]["done"] and not any("error" in e for e in events)


@pytest.mark.slow
def test_e2e_2000_page_pdf_no_crash(live, hub):
    hub["ollama"].chunk_fn = echo
    data = make_pdf(filler_pages(2000, 1500, FACT, chars=300))
    t0 = time.perf_counter()
    events, seen = ask(live, [f("huge.pdf", data)])
    first = time.perf_counter() - t0
    t0 = time.perf_counter()
    events, seen = ask(live, [f("huge.pdf", data)])  # cached extraction
    second = time.perf_counter() - t0
    print(f"\n2,000-page PDF: first question {first:.1f}s (includes text extraction), follow-up {second:.2f}s")
    assert "ZEBRA-42-ALPHA" in seen["user"] and second < 1.5


def test_e2e_multiple_long_pdfs_share_budget(live, hub):
    hub["ollama"].chunk_fn = echo
    a = make_pdf(filler_pages(120, 50, FACT, seed=1))
    b = make_pdf(filler_pages(120, seed=2))
    events, seen = ask(live, [f("a.pdf", a), f("b.pdf", b)])
    import re
    blocks = re.findall(r'<document name="(\w\.pdf)" pages="120">\n(.*?)\n</document>', seen["user"], re.S)
    assert [n for n, _ in blocks] == ["a.pdf", "b.pdf"]
    la, lb = len(blocks[0][1]), len(blocks[1][1])
    assert 7_000 < la <= 10_000 and 7_000 < lb <= 10_000, (la, lb)  # 20k local budget split evenly
    notes = [e["note"] for e in events if "note" in e]
    assert sum(1 for n in notes if n.startswith("'a.pdf' has 120 pages")) == 1
    assert sum(1 for n in notes if n.startswith("'b.pdf' has 120 pages")) == 1
    assert "ZEBRA-42-ALPHA" in blocks[0][1]


def test_cloud_budget_uses_model_context(live, hub, pdf300):
    hub["anthropic"].chunk_fn = lambda body: __import__("tests.fakes.hub", fromlist=["x"]).sse_anthropic(["ok"])
    assert httpx.post(live.base + "/api/providers", json={"key": K.ANTHROPIC}, headers=H, timeout=30).status_code == 200
    ask(live, [f("report.pdf", pdf300)], model="anthropic:claude-test-1")
    body = hub["anthropic"].chat_requests()[-1]["json"]
    sent = body["messages"][-1]["content"][-1]["text"]
    assert len(sent) > 300_000  # 200k-token model: the whole ~420k-char document fits the 400k cap mostly
    assert "ZEBRA-42-ALPHA" in sent and "Cite the pages" in body["system"]
