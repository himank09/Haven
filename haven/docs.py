"""Document text for the AI: per-page extraction, chunking and retrieval with page citations (Feature C).

* Text is extracted per page (pypdf) and cached by content hash, so follow-up questions skip extraction.
* If the whole document fits the model's budget it is sent whole, with [Page N] markers.
* Otherwise: questions -> BM25 over ~1,800-character chunks (pure Python), page 1 always included,
  budget filled in rank order, then re-sorted into page order; whole-document actions (summary, key
  points, practice questions) -> chunks spread evenly from start to end.
* Several long documents share the budget fairly: short ones get what they need, the rest is split evenly.
"""
from __future__ import annotations

import hashlib
import io
import math
import re
import threading
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

LOCAL_BUDGET = 20_000      # chars for local models (~5k tokens)
CLOUD_CAP = 400_000        # chars, upper bound for cloud models
CLOUD_DEFAULT = 100_000    # chars when the context size is unknown
CHUNK = 1_800              # target chunk size in characters
PREVIEW = 200              # characters of a page shown when hovering a citation chip

_CACHE: "OrderedDict[str, Doc]" = OrderedDict()
_LOCK = threading.Lock()
WORD = re.compile(r"\w+", re.UNICODE)
STOP = set("""a an and are as at be but by for from has have he her his i if in into is it its of on or our she so that the their
them then there these they this to was we were what when where which who why will with you your do does did can could would
should may might not no yes how about than also any all more most other some such only own same too very just over under
please tell me give find show explain""".split())


class UnreadablePDF(Exception):
    pass


@dataclass
class Doc:
    pages: List[str]
    chunks: List[Tuple[int, str]] = field(default_factory=list)  # (page index, text)
    _index: Optional[dict] = None

    def index(self) -> dict:
        """BM25 index over chunks, built once per document."""
        if self._index is None:
            postings: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
            lengths = []
            for i, (_p, text) in enumerate(self.chunks):
                toks = tokens(text)
                lengths.append(len(toks))
                for t, n in Counter(toks).items():
                    postings[t].append((i, n))
            avg = (sum(lengths) / len(lengths)) if lengths else 1.0
            self._index = {"postings": postings, "lengths": lengths, "avg": avg or 1.0, "n": len(self.chunks)}
        return self._index


def tokens(text: str) -> List[str]:
    return [t for t in WORD.findall(text.lower()) if t not in STOP and (len(t) > 1 or t.isdigit())]


def chunk_pages(pages: List[str], size: int = CHUNK) -> List[Tuple[int, str]]:
    """Split each page into ~size-character chunks on paragraph breaks, keeping the page number."""
    out: List[Tuple[int, str]] = []
    for pi, text in enumerate(pages):
        text = text.strip()
        if not text:
            continue
        if len(text) <= size:
            out.append((pi, text))
            continue
        cur = ""
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            while len(para) > size:  # one huge paragraph: cut at a sentence end (or a space) near the limit
                cut = max(para.rfind(". ", 0, size), para.rfind("\n", 0, size), para.rfind(" ", size // 2, size))
                cut = cut + 1 if cut > size // 3 else size
                piece, para = para[:cut].strip(), para[cut:].strip()
                if cur:
                    out.append((pi, cur))
                    cur = ""
                out.append((pi, piece))
            if not para:
                continue
            if cur and len(cur) + len(para) + 2 > size:
                out.append((pi, cur))
                cur = para
            else:
                cur = (cur + "\n\n" + para) if cur else para
        if cur:
            out.append((pi, cur))
    return out


def extract(data: bytes) -> Doc:
    """Pages + chunks for a PDF. Cached by sha256 (last 16 documents)."""
    h = hashlib.sha256(data).hexdigest()
    with _LOCK:
        if h in _CACHE:
            _CACHE.move_to_end(h)
            return _CACHE[h]
    from pypdf import PdfReader

    try:
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted and not r.decrypt(""):
            raise UnreadablePDF("password-protected")
        pages = []
        for p in r.pages:
            try:
                pages.append((p.extract_text() or "").strip())
            except Exception:
                pages.append("")
    except UnreadablePDF:
        raise
    except Exception:
        raise UnreadablePDF("not a readable PDF")
    doc = Doc(pages=pages, chunks=chunk_pages(pages))
    with _LOCK:
        _CACHE[h] = doc
        while len(_CACHE) > 16:
            _CACHE.popitem(last=False)
    return doc


def extract_pages(data: bytes) -> List[str]:
    return extract(data).pages


def is_scanned(pages: List[str]) -> bool:
    """Little text overall (v0.9 rule) and fewer than half the pages carry a real line of text."""
    total = sum(len(p) for p in pages)
    with_text = sum(1 for p in pages if len(p.strip()) >= 20)
    return total < 40 * max(1, len(pages)) and with_text * 2 < max(1, len(pages))


def budget_for(model) -> int:
    if model.local:
        return LOCAL_BUDGET
    if model.context:
        return max(LOCAL_BUDGET, min(CLOUD_CAP, int(model.context * 2.5)))
    return CLOUD_DEFAULT


def marked(pages: List[str], indexes: Optional[List[int]] = None) -> str:
    idx = range(len(pages)) if indexes is None else indexes
    return "\n\n".join(f"[Page {i + 1}]\n{pages[i]}" for i in idx if pages[i])


def allocate(needs: List[int], budget: int) -> List[int]:
    """Fair split: documents that need less than an equal share get what they need; the rest share the remainder."""
    out = [0] * len(needs)
    left = list(range(len(needs)))
    remaining = budget
    while left:
        share = remaining // len(left)
        small = [i for i in left if needs[i] <= share]
        if not small:
            for i in left:
                out[i] = share
            break
        for i in small:
            out[i] = needs[i]
            remaining -= needs[i]
        left = [i for i in left if i not in small]
    return out


# ---------------- retrieval ----------------
def bm25(doc: Doc, query: str, k1: float = 1.5, b: float = 0.75) -> List[Tuple[int, float]]:
    ix = doc.index()
    n, avg, lengths = ix["n"], ix["avg"], ix["lengths"]
    scores: Dict[int, float] = defaultdict(float)
    for t in set(tokens(query)):
        plist = ix["postings"].get(t)
        if not plist:
            continue
        idf = math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
        for ci, tf in plist:
            scores[ci] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * lengths[ci] / avg))
    return sorted(scores.items(), key=lambda x: -x[1])


def _cost(doc: Doc, ci: int) -> int:
    return len(doc.chunks[ci][1]) + 12  # + "[Page N]\n" marker and spacing


def _render(doc: Doc, chosen: List[int]) -> str:
    out, last_page = [], None
    for ci in sorted(chosen):
        p, text = doc.chunks[ci]
        if p != last_page:
            out.append(f"[Page {p + 1}]\n{text}")
            last_page = p
        else:
            out.append(text)
    return "\n\n".join(out)


def page_ranges(pages: List[int], limit: int = 14) -> str:
    """[1, 14, 15, 16, 88] -> '1, 14-16, 88' (1-based input)."""
    pages = sorted(set(pages))
    parts, i = [], 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        parts.append(str(pages[i]) if i == j else f"{pages[i]}-{pages[j]}")
        i = j + 1
    if len(parts) > limit:
        return ", ".join(parts[:limit]) + ", …"
    return ", ".join(parts)


@dataclass
class Selection:
    text: str
    pages: List[int]          # 1-based pages included
    note: Optional[str]
    retrieved: bool


def select(name: str, doc: Doc, budget: int, question: str = "", whole: bool = False) -> Selection:
    full = marked(doc.pages)
    all_pages = [i + 1 for i, p in enumerate(doc.pages) if p]
    if len(full) <= budget or not doc.chunks:
        return Selection(full, all_pages, None, False)
    chosen: List[int] = []
    used = 0

    def take(ci):
        nonlocal used
        if ci in chosen:
            return
        c = _cost(doc, ci)
        if used + c <= budget:
            chosen.append(ci)
            used += c

    n = len(doc.chunks)
    if whole:  # evenly spread, first and last regions included
        avg = sum(_cost(doc, i) for i in range(n)) / n
        k = max(2, min(n, int(budget // avg)))
        for j in range(k):
            take(round(j * (n - 1) / (k - 1)))
        for ci in range(n):  # fill any space left, in spread order
            if used >= budget * 0.97:
                break
            take(ci)
        how = "read pages spread across it"
    else:
        take(0)  # page 1 always
        ranked = [ci for ci, _s in bm25(doc, question)]
        for ci in ranked:  # 1) everything that matches, best first
            take(ci)
            if used >= budget * 0.97:
                break
        for ci in ranked[:5]:  # 2) the text around the best hits
            for nb in (ci - 1, ci + 1):
                if 0 <= nb < n:
                    take(nb)
        if used < budget * 0.97:  # 3) fill what's left with chunks spread across the document
            avg = sum(_cost(doc, i) for i in range(n)) / n
            k = max(2, min(n, int((budget - used) // avg) + 2))
            for j in range(k):
                take(round(j * (n - 1) / (k - 1)))
                if used >= budget * 0.97:
                    break
        how = "read the most relevant"
    pages = sorted({doc.chunks[ci][0] + 1 for ci in chosen})
    note = f"'{name}' has {len(doc.pages)} pages; {how}: p. {page_ranges(pages)}."
    return Selection(_render(doc, chosen), pages, note, True)


def previews(doc: Doc, pages: List[int]) -> Dict[str, str]:
    """First ~200 characters of each included page, for the citation chip tooltips."""
    out = {}
    for p in pages:
        t = re.sub(r"\s+", " ", doc.pages[p - 1]).strip()
        out[str(p)] = t[:PREVIEW] + ("…" if len(t) > PREVIEW else "")
    return out
