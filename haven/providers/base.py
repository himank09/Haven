"""Shared pieces for all provider adapters.

* ModelInfo / ProviderConfig: what the rest of the app knows about a model / a saved provider.
* ProviderError + human_error(): every failure becomes one short sentence (no stack traces, no keys).
* SSEParser / NDJSONParser: byte-level stream parsers that survive chunks split anywhere
  (mid-line, mid-UTF-8 character), CRLF, comments, blank data lines and missing terminators.
* ThinkSplitter: separates <think>...</think> text that some models put inside normal content.
* client(): shared httpx clients (bounded pools) with the timeouts from the brief.
"""
from __future__ import annotations

import asyncio
import codecs
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

# ---------------- data ----------------


@dataclass
class ModelInfo:
    id: str                      # the provider's own model id
    label: str = ""              # what the picker shows
    provider: str = ""           # provider instance id, e.g. "openai" or "openai-2"
    kind: str = ""               # provider type from the registry table
    vision: bool = False
    context: Optional[int] = None  # input tokens, when known
    think: str = "no"            # "no" | "toggle" | "always" (always thinks; toggle only shows/hides it)
    local: bool = False
    created: Optional[int] = None
    preview: bool = False
    pdf: bool = False            # accepts native PDF input
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def full_id(self) -> str:
        return f"{self.provider}:{self.id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["full_id"] = self.full_id
        d.pop("extra", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ModelInfo":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        if not isinstance(known.get("extra", {}), dict):
            known.pop("extra")
        return cls(**known)


@dataclass
class ProviderConfig:
    id: str
    kind: str
    name: str                    # display name of the provider type ("OpenAI")
    style: str                   # adapter: openai | anthropic | gemini | ollama
    base_url: str
    key: str = ""                # secret; lives only in memory, never serialised to the page
    label: str = ""
    local: bool = False
    headers: Dict[str, str] = field(default_factory=dict)
    quirks: Dict[str, Any] = field(default_factory=dict)
    extra_models: List[str] = field(default_factory=list)

    def secrets(self) -> List[str]:
        return [self.key] if self.key else []


# ---------------- errors ----------------


class ProviderError(Exception):
    """A failure already turned into a human sentence (safe to show)."""

    def __init__(self, message: str, status: int = 0, kind: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.kind = kind  # "auth" | "not_found" | "too_long" | "rate" | "server" | "network" | "timeout" | "bad_request"


KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|AIza[0-9A-Za-z_\-]{10,}|gsk_[A-Za-z0-9]{6,}|xai-[A-Za-z0-9]{6,}|"
                     r"hf_[A-Za-z0-9]{6,}|fw_[A-Za-z0-9]{6,}|csk-[A-Za-z0-9]{6,}|Bearer\s+\S+)")


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove anything that looks like an API key (and the known keys) from text shown to the user."""
    text = str(text or "")
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "[key]")
    return KEYLIKE.sub("[key]", text)


TOO_LONG = re.compile(r"context.{0,30}(length|window|limit)|too (long|large|many tokens)|maximum context|max_tokens|"
                      r"prompt is too long|exceeds?.{0,30}(token|limit|context)|input.{0,20}too long|request.{0,10}too large", re.I)


def provider_message(body: str) -> str:
    """Best-effort short message from a provider error body (any of the usual JSON shapes)."""
    try:
        j = json.loads(body)
    except Exception:
        return body.strip()[:200]
    if isinstance(j, list) and j:
        j = j[0]
    if isinstance(j, dict):
        e = j.get("error", j)
        if isinstance(e, dict):
            return str(e.get("message") or e.get("msg") or e.get("type") or "")[:200]
        if isinstance(e, str):
            return e[:200]
        if "detail" in j:
            return str(j["detail"])[:200]
        if "message" in j:
            return str(j["message"])[:200]
    return body.strip()[:200]


def human_error(status: int, name: str, body: str = "", retry_after: Optional[str] = None,
                secrets: Iterable[str] = (), model: str = "") -> ProviderError:
    """Map an HTTP status from a provider to one short sentence (brief §3.6)."""
    msg = redact(provider_message(body), secrets)
    low = (msg or "").lower()
    who = model or "This model"
    if status in (401, 403):
        return ProviderError(f"Key rejected by {name}. Check it in Settings.", status, "auth")
    if status == 404:
        if "no longer available" in low or "retired" in low or "deprecated" in low or "discontinued" in low:
            return ProviderError(f"Model not available on this key: {name} has retired {who} for new keys. Pick a newer model.", status, "retired")
        return ProviderError("Model not available on this key" + (f" ({model})" if model else "") + ". Pick another model.", status, "not_found")
    if status == 413 or (status in (400, 422) and TOO_LONG.search(msg or "")):
        return ProviderError("Too long for this model. Remove a file or start a new chat.", status, "too_long")
    if status == 429:
        if "quota" in low and ("plan" in low or "billing" in low or "limit: 0" in low or "free" in low):
            return ProviderError(f"{who} isn't included in your {name} plan (quota exceeded). Pick another model, "
                                 f"or check billing with {name}.", status, "quota")
        secs = _retry_seconds(retry_after)
        return ProviderError(f"Rate limited, try again in {secs}s." if secs else "Rate limited, try again shortly.", status, "rate")
    if status in (503, 529) or "high demand" in low or "overloaded" in low:
        return ProviderError(f"Provider error: {who} is overloaded right now ({name} reports high demand). "
                             f"Try again in a minute, or pick another model.", status, "busy")
    if status >= 500:
        return ProviderError(f"Provider error: {name} had a problem ({status}). Try again.", status, "server")
    return ProviderError(f"{name} refused the request" + (f": {msg}" if msg else f" ({status})."), status, "bad_request")


def _retry_seconds(v: Optional[str]) -> Optional[int]:
    if not v:
        return None
    try:
        return max(1, int(float(v)))
    except ValueError:
        pass
    try:  # HTTP date
        from email.utils import parsedate_to_datetime
        import time

        return max(1, int(parsedate_to_datetime(v).timestamp() - time.time()))
    except Exception:
        return None


def network_error(exc: BaseException, name: str, local: bool = False) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, httpx.TimeoutException) or isinstance(exc, asyncio.TimeoutError):
        if isinstance(exc, httpx.ConnectTimeout) and local:
            return ProviderError(f"Can't reach {name}. Is it running?", 0, "network")
        if isinstance(exc, httpx.ConnectTimeout):
            return ProviderError(f"Can't reach {name}. Check internet.", 0, "network")
        return ProviderError(f"Took too long: {name} didn't answer in time. The model may be overloaded; "
                             f"try again, or pick another model.", 0, "timeout")
    if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError,
                        httpx.NetworkError, httpx.UnsupportedProtocol)):
        if local:
            return ProviderError(f"Can't reach {name}. Is it running?", 0, "network")
        return ProviderError(f"Can't reach {name}. Check internet.", 0, "network")
    return ProviderError(f"Something went wrong talking to {name}.", 0, "network")


async def raise_for_status(r: httpx.Response, cfg: ProviderConfig, model: str = ""):
    if r.status_code == 200:
        return
    try:
        body = (await r.aread()).decode("utf-8", "replace")
    except Exception:
        body = ""
    raise human_error(r.status_code, cfg.name, body, r.headers.get("retry-after"), cfg.secrets(), model)


# ---------------- stream parsers ----------------


class _Lines:
    """Bytes in -> complete text lines out. Handles split UTF-8 and \\n, \\r\\n, \\r endings."""

    def __init__(self):
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""

    def feed(self, data: bytes) -> List[str]:
        self._buf += self._dec.decode(data)
        out = []
        while True:
            m = re.search(r"\r\n|\n|\r", self._buf)
            if not m:
                break
            if m.group() == "\r" and m.end() == len(self._buf):
                break  # might be the first half of \r\n
            out.append(self._buf[:m.start()])
            self._buf = self._buf[m.end():]
        return out

    def close(self) -> List[str]:
        self._buf += self._dec.decode(b"", final=True)
        rest, self._buf = self._buf, ""
        return [ln for ln in re.split(r"\r\n|\n|\r", rest) if ln != ""] if rest else []


class SSEParser:
    """Server-Sent Events. feed(bytes) -> [(event, data)]; close() flushes an event cut off by a clean close."""

    def __init__(self):
        self._lines = _Lines()
        self._event = ""
        self._data: List[str] = []

    def _line(self, ln: str, out: list):
        if ln == "":
            if self._data:
                out.append((self._event or "message", "\n".join(self._data)))
            self._event, self._data = "", []
            return
        if ln.startswith(":"):
            return  # comment / keep-alive
        f, _, v = ln.partition(":")
        if v.startswith(" "):
            v = v[1:]
        if f == "data":
            self._data.append(v)
        elif f == "event":
            self._event = v

    def feed(self, data: bytes) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        for ln in self._lines.feed(data):
            self._line(ln, out)
        return out

    def close(self) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        for ln in self._lines.close():
            self._line(ln, out)
        self._line("", out)
        return out


class NDJSONParser:
    """Newline-delimited JSON (Ollama). Malformed lines are skipped."""

    def __init__(self):
        self._lines = _Lines()

    @staticmethod
    def _parse(lines):
        out = []
        for ln in lines:
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
        return out

    def feed(self, data: bytes) -> List[dict]:
        return self._parse(self._lines.feed(data))

    def close(self) -> List[dict]:
        return self._parse(self._lines.close())


def sse_json(data: str) -> Optional[dict]:
    """Parse one SSE data payload; None for [DONE], empty or malformed JSON (skipped, never fatal)."""
    data = data.strip()
    if not data or data == "[DONE]":
        return None
    try:
        j = json.loads(data)
    except ValueError:
        return None
    return j if isinstance(j, dict) else None


class ThinkSplitter:
    """Split '<think>…</think>' inside streamed content into thinking vs content, tags split across chunks included."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.inside = False
        self._hold = ""
        self._seen_text = False

    def feed(self, text: str) -> List[Tuple[str, str]]:
        s = self._hold + text
        self._hold = ""
        out: List[Tuple[str, str]] = []
        while s:
            tag = self.CLOSE if self.inside else self.OPEN
            i = s.find(tag)
            if i >= 0:
                self._emit(out, s[:i])
                s = s[i + len(tag):]
                self.inside = not self.inside
                continue
            # keep a possible partial tag at the end for the next chunk
            keep = 0
            for k in range(min(len(tag) - 1, len(s)), 0, -1):
                if tag.startswith(s[-k:]):
                    keep = k
                    break
            self._emit(out, s[:len(s) - keep] if keep else s)
            self._hold = s[len(s) - keep:] if keep else ""
            break
        return out

    def _emit(self, out, piece):
        if not piece:
            return
        kind = "thinking" if self.inside else "content"
        if kind == "content" and not self._seen_text:
            if not piece.strip():
                return  # whitespace between </think> and the answer
            piece = piece.lstrip("\n")
            self._seen_text = True
        out.append((kind, piece))

    def close(self) -> List[Tuple[str, str]]:
        rest, self._hold = self._hold, ""
        if not rest:
            return []
        return [("thinking" if self.inside else "content", rest)]


# ---------------- http clients ----------------

_CLIENTS: Dict[Tuple[int, bool], httpx.AsyncClient] = {}
_LOOPS: Dict[Tuple[int, bool], "weakref.ref"] = {}
LIMITS = httpx.Limits(max_connections=32, max_keepalive_connections=8, keepalive_expiry=30)


def timeouts(local: bool) -> httpx.Timeout:
    # connect 10 s; first byte 60 s cloud / 180 s local (model loading); then the same per-chunk read timeout,
    # which means no overall cap while tokens keep arriving
    return httpx.Timeout(connect=10.0, read=180.0 if local else 60.0, write=60.0, pool=10.0)


def client(local: bool = False) -> httpx.AsyncClient:
    """One shared client per event loop and kind (local/cloud), so connections are pooled and countable.

    The loop is checked by identity (weak reference), not just id(): a new loop can reuse a dead loop's
    address, and a client bound to a closed loop must never be handed out."""
    import weakref

    loop = asyncio.get_running_loop()
    key = (id(loop), local)
    c = _CLIENTS.get(key)
    ref = _LOOPS.get(key)
    if c is None or c.is_closed or ref is None or ref() is not loop:
        c = httpx.AsyncClient(timeout=timeouts(local), limits=LIMITS, follow_redirects=False)
        _CLIENTS[key] = c
        _LOOPS[key] = weakref.ref(loop)
    return c


async def close_clients():
    loop = asyncio.get_running_loop()
    for key in [k for k in _CLIENTS if k[0] == id(loop)]:
        c = _CLIENTS.pop(key)
        await c.aclose()


def open_connections() -> int:
    """Number of open pooled connections across all clients (used by the leak tests)."""
    n = 0
    for c in _CLIENTS.values():
        pool = getattr(getattr(c, "_transport", None), "_pool", None)
        conns = getattr(pool, "connections", None) or []
        n += sum(1 for x in conns if not x.is_closed())
    return n


async def stream_lines(resp: httpx.Response, parser):
    """Feed raw bytes of a response into a parser, yielding parsed items as they complete."""
    async for chunk in resp.aiter_bytes():  # bytes (gzip undone), not text: split UTF-8 is handled by the parser
        for item in parser.feed(chunk):
            yield item
    for item in parser.close():
        yield item
