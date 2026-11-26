"""Document text for the AI: per-page extraction (cached by content hash) and page-marked context.

Phase 2 sends the whole text when it fits the model's budget and truncates otherwise (as v0.9 did, but
with a model-aware budget). Phase 4 replaces truncation with retrieval (BM25) and page citations.
"""
from __future__ import annotations

import hashlib
import io
import threading
from collections import OrderedDict
from typing import List, Optional, Tuple

LOCAL_BUDGET = 20_000      # chars for local models (~5k tokens)
CLOUD_CAP = 400_000        # chars, upper bound for cloud models
CLOUD_DEFAULT = 100_000    # chars when the context size is unknown
_CACHE: "OrderedDict[str, List[str]]" = OrderedDict()
_LOCK = threading.Lock()


class UnreadablePDF(Exception):
    pass


def extract_pages(data: bytes) -> List[str]:
    """Text of each page (empty string for pages without text). Cached by sha256 (last 16 documents)."""
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
    with _LOCK:
        _CACHE[h] = pages
        while len(_CACHE) > 16:
            _CACHE.popitem(last=False)
    return pages


def is_scanned(pages: List[str]) -> bool:
    total = sum(len(p) for p in pages)
    return total < 40 * max(1, len(pages))


def budget_for(model) -> int:
    if model.local:
        return LOCAL_BUDGET
    if model.context:
        return max(LOCAL_BUDGET, min(CLOUD_CAP, int(model.context * 2.5)))
    return CLOUD_DEFAULT


def marked(pages: List[str], indexes: Optional[List[int]] = None) -> str:
    idx = range(len(pages)) if indexes is None else indexes
    return "\n\n".join(f"[Page {i + 1}]\n{pages[i]}" for i in idx if pages[i])


def document_text(name: str, pages: List[str], budget: int) -> Tuple[str, Optional[str]]:
    """Page-marked text that fits the budget, plus an optional note for the user."""
    text = marked(pages)
    if len(text) <= budget:
        return text, None
    cut = text[:budget]
    last = cut.rfind("[Page ")
    shown = cut[last:].split("]")[0].replace("[Page ", "") if last >= 0 else "?"
    return cut, f"'{name}' is long ({len(pages)} pages); this model only sees about the first {shown} pages."
