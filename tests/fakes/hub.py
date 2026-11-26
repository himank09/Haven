"""A real local HTTP server that pretends to be every AI provider at once.

Each provider lives under its own path prefix, e.g. http://127.0.0.1:PORT/openai/v1/models or
http://127.0.0.1:PORT/ollama/api/chat. Tests script each provider's behaviour:

    hub.reset()
    p = hub["openai"]
    p.models = {"data": [{"id": "gpt-x"}]}
    p.chunks = sse_openai(["Hel", "lo"])      # raw bytes sent one by one
    p.delay = 0.01                            # seconds between chunks
    p.chat_status = 429; p.chat_headers = {"retry-after": "7"}

and inspect what Haven sent (`p.requests`) and whether the client hung up (`p.disconnected_at`).
"""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

KINDS = ["ollama", "lmstudio", "openai", "anthropic", "gemini", "openrouter", "groq", "xai", "deepseek", "mistral",
         "together", "fireworks", "cerebras", "huggingface", "custom"]
BASE_PATH = {"ollama": "", "lmstudio": "/v1", "gemini": "/v1beta", "deepseek": "", "groq": "/openai/v1",
             "fireworks": "/inference/v1", "openrouter": "/api/v1"}


@dataclass
class FakeProvider:
    kind: str
    models: Any = None                 # JSON for the model list (None -> a small default)
    models_status: int = 200
    models_delay: float = 0.0
    models_body: Optional[str] = None  # raw body overrides `models`
    native_models: Any = None          # LM Studio /api/v1/models
    show: Dict[str, dict] = field(default_factory=dict)  # Ollama /api/show per model
    chunks: List[bytes] = field(default_factory=list)
    chunk_fn: Optional[Callable[[dict], List[bytes]]] = None  # build chunks from the request body
    infinite: Optional[Callable[[int], bytes]] = None          # endless stream: i -> chunk
    delay: float = 0.0
    first_delay: float = 0.0
    chat_status: int = 200
    chat_body: str = ""
    chat_headers: Dict[str, str] = field(default_factory=dict)
    drop_after: Optional[int] = None   # close the connection abruptly after N chunks
    reject_if: Optional[Callable[[dict], Optional[tuple]]] = None  # body -> (status, body) to refuse that request
    requests: List[dict] = field(default_factory=list)
    disconnected_at: Optional[float] = None
    finished: int = 0
    sent: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def chat_requests(self):
        return [r for r in self.requests if r["kind"] == "chat"]


class Hub:
    def __init__(self):
        self.providers: Dict[str, FakeProvider] = {}
        self.reset()
        self.app = Starlette(routes=[Route("/{path:path}", self.handle, methods=["GET", "POST"])])
        self.port = 0
        self.thread = None
        self.server = None

    def reset(self):
        self.providers = {k: FakeProvider(k) for k in KINDS}
        self.img_status = {"hf": 200, "cf": 200, "poll": 200, "space": 200}  # free image services (Hugging Face, Cloudflare, Pollinations)
        self.img_requests = []

    def __getitem__(self, kind) -> FakeProvider:
        return self.providers[kind]

    def url(self, kind: str) -> str:
        return f"http://127.0.0.1:{self.port}/{kind}{BASE_PATH.get(kind, '/v1')}"

    def total_requests(self) -> int:
        return sum(len(p.requests) for p in self.providers.values())

    # ---------------- HTTP ----------------
    async def handle(self, request: Request):
        path = "/" + request.path_params["path"]
        kind = path.split("/")[1]
        if kind == "img":
            return await self._image_service(request, path.split("/")[2])
        p = self.providers.get(kind)
        if not p:
            return JSONResponse({"error": "no such fake"}, 404)
        rest = path[len(kind) + 1:]
        body = None
        if request.method == "POST":
            raw = await request.body()
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = None
        rec = {"method": request.method, "path": rest, "headers": dict(request.headers), "json": body,
               "query": dict(request.query_params), "t": time.monotonic()}
        if rest.endswith("/api/show"):
            rec["kind"] = "show"
            p.requests.append(rec)
            name = (body or {}).get("model", "")
            return JSONResponse(p.show.get(name, {"capabilities": ["completion"], "model_info": {}}))
        if rest.endswith("/api/v1/models") or (kind == "lmstudio" and rest == "/api/v1/models"):
            rec["kind"] = "models"
            p.requests.append(rec)
            if p.native_models is None:
                return JSONResponse({"error": "not found"}, 404)
            return JSONResponse(p.native_models)
        if rest.endswith("/models") or rest.endswith("/models/user") or rest.endswith("/api/tags"):
            rec["kind"] = "models"
            p.requests.append(rec)
            if p.models_delay:
                await asyncio.sleep(p.models_delay)
            if p.models_status != 200:
                return Response(p.models_body or json.dumps({"error": {"message": f"fake {p.models_status}"}}),
                                p.models_status, media_type="application/json")
            if p.models_body is not None:
                return Response(p.models_body, 200, media_type="application/json")
            return JSONResponse(p.models if p.models is not None else default_models(kind))
        if ":generateContent" in rest:  # Gemini image models (non-streaming)
            rec["kind"] = "image"
            p.requests.append(rec)
            if p.chat_status != 200:
                return Response(p.chat_body or json.dumps({"error": {"message": f"fake error {p.chat_status}"}}),
                                p.chat_status, media_type="application/json")
            png = base64.b64encode(FAKE_PNG).decode()
            return JSONResponse({"candidates": [{"content": {"parts": [{"text": "Here you go."},
                                 {"inlineData": {"mimeType": "image/png", "data": png}}]}, "finishReason": "STOP"}]})
        if rest.endswith("/chat/completions") or rest.endswith("/messages") or ":streamGenerateContent" in rest \
                or rest.endswith("/api/chat"):
            rec["kind"] = "chat"
            p.requests.append(rec)
            if p.reject_if:
                rej = p.reject_if(body or {})
                if rej:
                    return Response(rej[1], rej[0], media_type="application/json")
            if p.chat_status != 200:
                return Response(p.chat_body or json.dumps({"error": {"message": f"fake error {p.chat_status}"}}),
                                p.chat_status, headers=p.chat_headers, media_type="application/json")
            chunks = p.chunk_fn(body or {}) if p.chunk_fn else list(p.chunks)
            return StreamingResponse(self._gen(p, chunks), media_type="text/event-stream")
        return JSONResponse({"error": "unknown fake path " + rest}, 404)

    async def _image_service(self, request: Request, svc: str):
        raw = await request.body()
        self.img_requests.append({"svc": svc, "path": request.url.path, "query": dict(request.query_params),
                                  "headers": dict(request.headers), "json": json.loads(raw) if raw else None})
        st = self.img_status.get(svc, 404)
        if svc == "space":  # Gradio API of the free FLUX Space: POST call -> event id -> SSE -> file URL
            path = request.url.path
            if path.endswith("/file.png"):
                return Response(FAKE_PNG, 200, media_type="image/png")
            if request.method == "POST":
                return JSONResponse({"event_id": "ev1"}) if st == 200 else JSONResponse({"error": "down"}, st)
            if st == 429:
                body = 'event: error\ndata: "You have exceeded your free GPU quota"\n\n'
            elif st != 200:
                body = "event: error\ndata: null\n\n"
            else:
                url = f"http://127.0.0.1:{self.port}/img/space/file.png"
                body = 'event: heartbeat\ndata: null\n\nevent: complete\ndata: [{"url": "' + url + '"}]\n\n'
            return Response(body, 200, media_type="text/event-stream")
        if st != 200:
            return JSONResponse({"error": f"fake {svc} {st}"}, st)
        if svc == "cf":
            return JSONResponse({"success": True, "result": {"image": base64.b64encode(FAKE_PNG).decode()}})
        return Response(FAKE_PNG, 200, media_type="image/png")

    async def _gen(self, p: FakeProvider, chunks):
        done = False
        try:
            if p.first_delay:
                await asyncio.sleep(p.first_delay)
            i = 0
            while True:
                if p.infinite is not None:
                    chunk = p.infinite(i)
                elif i < len(chunks):
                    chunk = chunks[i]
                else:
                    break
                if p.drop_after is not None and i >= p.drop_after:
                    raise ConnectionAbortedError("fake drop")
                yield chunk
                p.sent += 1
                i += 1
                if p.delay:
                    await asyncio.sleep(p.delay)
                else:
                    await asyncio.sleep(0)
            done = True
            p.finished += 1
        finally:
            if not done and p.disconnected_at is None:
                p.disconnected_at = time.monotonic()

    # ---------------- lifecycle ----------------
    def start(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        cfg = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error", lifespan="off")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return
            time.sleep(0.02)
        raise RuntimeError("fake hub did not start")

    def stop(self):
        if self.server:
            self.server.should_exit = True
            self.thread.join(5)


FAKE_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000""1f15c4890000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082")


def default_models(kind: str):
    if kind == "ollama":
        return {"models": [{"name": "qwen3:4b", "digest": "d1", "details": {"parameter_size": "4B"}}]}
    if kind == "anthropic":
        return {"data": [{"id": "claude-test-1", "display_name": "Claude Test", "max_input_tokens": 200000,
                          "capabilities": {"image_input": True, "pdf_input": True, "thinking": {"types": ["enabled"]}}}],
                "has_more": False}
    if kind == "gemini":
        return {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"],
                            "inputTokenLimit": 1000000, "thinking": True}]}
    if kind == "together":
        return [{"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "type": "chat", "context_length": 131072}]
    return {"object": "list", "data": [{"id": f"{kind}-chat-1", "created": 1700000000}]}


# ---------------- stream builders ----------------
def sse(objs, done=True, sep=b"\n\n") -> List[bytes]:
    out = [b"data: " + json.dumps(o, ensure_ascii=False).encode() + sep for o in objs]
    if done:
        out.append(b"data: [DONE]" + sep)
    return out


def sse_openai(pieces, reasoning=None, field="reasoning_content", usage=True, done=True) -> List[bytes]:
    objs = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}]
    for r in reasoning or []:
        objs.append({"choices": [{"index": 0, "delta": {field: r}}]})
    for t in pieces:
        objs.append({"choices": [{"index": 0, "delta": {"content": t}}]})
    objs.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if usage:
        objs.append({"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": len(pieces)}})
    return sse(objs, done)


def sse_anthropic(pieces, thinking=None) -> List[bytes]:
    def ev(name, obj):
        return f"event: {name}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()

    out = [ev("message_start", {"type": "message_start", "message": {"id": "m1", "usage": {"input_tokens": 5, "output_tokens": 1}}})]
    idx = 0
    if thinking:
        out.append(ev("content_block_start", {"type": "content_block_start", "index": idx, "content_block": {"type": "thinking", "thinking": ""}}))
        for t in thinking:
            out.append(ev("content_block_delta", {"type": "content_block_delta", "index": idx, "delta": {"type": "thinking_delta", "thinking": t}}))
        out.append(ev("content_block_delta", {"type": "content_block_delta", "index": idx, "delta": {"type": "signature_delta", "signature": "sig"}}))
        out.append(ev("content_block_stop", {"type": "content_block_stop", "index": idx}))
        idx += 1
    out.append(ev("content_block_start", {"type": "content_block_start", "index": idx, "content_block": {"type": "text", "text": ""}}))
    out.append(b"event: ping\ndata: {\"type\": \"ping\"}\n\n")
    for t in pieces:
        out.append(ev("content_block_delta", {"type": "content_block_delta", "index": idx, "delta": {"type": "text_delta", "text": t}}))
    out.append(ev("content_block_stop", {"type": "content_block_stop", "index": idx}))
    out.append(ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": len(pieces)}}))
    out.append(ev("message_stop", {"type": "message_stop"}))
    return out


def sse_gemini(pieces, thoughts=None) -> List[bytes]:
    objs = []
    for t in thoughts or []:
        objs.append({"candidates": [{"content": {"role": "model", "parts": [{"text": t, "thought": True}]}}]})
    for t in pieces:
        objs.append({"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}}]})
    objs.append({"candidates": [{"content": {"role": "model", "parts": []}, "finishReason": "STOP"}],
                 "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": len(pieces)}})
    return [b"data: " + json.dumps(o, ensure_ascii=False).encode() + b"\r\n\r\n" for o in objs]


def ndjson_ollama(pieces, thinking=None) -> List[bytes]:
    out = []
    for t in thinking or []:
        out.append(json.dumps({"message": {"role": "assistant", "content": "", "thinking": t}, "done": False}, ensure_ascii=False).encode() + b"\n")
    for t in pieces:
        out.append(json.dumps({"message": {"role": "assistant", "content": t}, "done": False}, ensure_ascii=False).encode() + b"\n")
    out.append(json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                           "eval_count": len(pieces), "eval_duration": 1_000_000_000, "prompt_eval_count": 5}).encode() + b"\n")
    return out


def stream_for(style: str, pieces, thinking=None) -> List[bytes]:
    return {"openai": lambda: sse_openai(pieces, thinking), "anthropic": lambda: sse_anthropic(pieces, thinking),
            "gemini": lambda: sse_gemini(pieces, thinking), "ollama": lambda: ndjson_ollama(pieces, thinking)}[style]()


def rechunk(chunks: List[bytes], size: int) -> List[bytes]:
    """Join everything and cut into fixed-size byte pieces (splits lines, JSON and UTF-8 characters)."""
    raw = b"".join(chunks)
    return [raw[i:i + size] for i in range(0, len(raw), size)]
