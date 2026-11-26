# Haven 1.0: plan (Phase 0 output)

Branch: `haven-1.0`, created from `main` @ `99e68d3`. Nothing else has changed yet.

## 1. What I found in the repo (vs the brief's summary)

The brief's §1 summary is accurate. Details that matter for the plan:

- `server.py` has one big module: settings, token guard middleware, the `X-Desk-Store` result cache, Ollama and Gemini streaming, and all file tools. `convert.py` is self-contained.
- The guard middleware buffers the **whole** response body when `X-Desk-Store: 1` is set. That only applies to file tools, so it doesn't affect streaming, but `/api/chat` must never be called with that header.
- The page owns the chat stream (`fetch` + `ReadableStream`). Its markdown is a 6-regex mini-renderer that escapes everything first, so it's safe today but very limited.
- `app.py` pins port 47321 so `localStorage` survives restarts. The `thread6` migration depends on this, so the port must stay. Window `min_size=(900, 600)`.
- The venv is Python 3.12.10 and has **none of**: `pytest`, `pytest-asyncio`, `respx`, `playwright`, `keyring`, `psutil`.
- **Bug found while probing (§8.1 conflict):** an encrypted PDF (user password) returns **500 `FileNotDecryptedError`** from merge, split, extract, rotate and text. Only compress returns 400. `open_pdf()` calls `decrypt("")` but ignores the result. See §6, Q1.
- Empty and zero-byte files already return clean 400s (checked for to-images and image/convert).

## 2. Provider docs vs this brief (fetched 2026-11-26; the docs win)

| Provider | What differs from the brief / what to do |
|---|---|
| **OpenAI** | `/v1/models` returns only `id/created/owned_by` (no capabilities), so vision and reasoning come from a **name heuristic** (documented in `filters.py`). Chat Completions **does not expose reasoning text**: Think maps to `reasoning_effort` and no `{thinking}` events appear. Reasoning models need `max_completion_tokens`, and I'll send no `temperature` to them. **PDF input is supported in Chat Completions** (`{"type":"file","file":{"filename","file_data":"data:application/pdf;base64,…"}}`, 50 MB). Usage comes via `stream_options.include_usage` (final chunk with empty `choices`). The docs I read didn't cover `retry-after`; I'll read it if present. |
| **Anthropic** | `GET /v1/models` now returns **`capabilities`** (image_input, pdf_input, thinking.types, effort) and `max_input_tokens`, so no heuristics are needed. Paginated (`limit` up to 1000, `after_id`, `has_more`). Thinking: **`{"type":"enabled","budget_tokens"}` is rejected (400) on Claude 4.7+.** Use `{"type":"adaptive"}` + `output_config.effort` when the model lists `adaptive`, otherwise `enabled`. A final assistant message (prefill) is rejected on 4.6+, so the history must end on a user turn. Consecutive same-role turns are merged by the API, but I'll merge them myself anyway. `anthropic-version`: the docs examples show a newer date than `2023-06-01`, but I couldn't confirm which value is required. It goes in one constant, verified when I write the adapter. Errors: 529 `overloaded_error` → "Provider busy"; a mid-stream `event: error` must be handled. PDF limits: 600 pages, 32 MB request. |
| **Gemini** | Models carry a **`thinking` bool** and `inputTokenLimit`, so the Think toggle comes from metadata. **Thinking cannot be turned off** on 2.5 Pro / 3.x / 4.x, so for those Think is "always on" and only controls whether thoughts are shown (`includeThoughts`). Newer models use `thinkingLevel`, older ones `thinkingBudget`. I'll keep the existing "drop `generationConfig` on a 400 and retry" fallback. PDFs: 50 MB, 1,000 pages. ai.google.dev now redirects to aistudio.google.com. |
| **Ollama** | `/api/show` returns `capabilities` (`completion`, `vision`, …) and a `thinking {values, default}` object, so I'll call it once per model (cached by digest) for vision, think and context. `model_info` context length is architecture-prefixed (`llama.context_length`). `think` can be bool or a level string. |
| **LM Studio** | Use native **`GET /api/v1/models`** (type `llm`/`embedding`, `capabilities.vision`, `capabilities.reasoning`, `max_context_length`, `loaded_instances`), falling back to `/v1/models`. No auth by default; an optional token is supported via the "Custom" key path. The name of the streamed reasoning field is unverified, so the generic parser below handles it. |
| **OpenRouter** | **`/models` does not need auth, so it can't validate a key.** Validate with `GET /api/v1/models/user` (auth required), which also lists only models the key can use. Reasoning is streamed in `delta.reasoning` / `delta.reasoning_details`. Send `X-OpenRouter-Title: Haven`. SSE has `: OPENROUTER PROCESSING` comments. A mid-stream error comes as a top-level `error` plus `finish_reason:"error"`. |
| **Groq** | `/models` has `active` and `context_window`. Filter must drop `whisper*`, `orpheus*`, `*prompt-guard*` and `*safeguard*`. Reasoning: send `reasoning_format:"parsed"`, which gives `delta.reasoning`. |
| **xAI** | Reasoning **can't be disabled** on reasoning models, and they reject `presence_penalty`, `frequency_penalty` and `stop` (we don't send those). The filter must drop `grok-imagine-*`. The REST field name `reasoning_content` is unverified, so the generic parser handles it. |
| **DeepSeek** | Base URL is **`https://api.deepseek.com`** (no `/v1` in the docs). `/models` now has `input_modalities` and `context_window`, and `deepseek-flash` **does support images**. Thinking is on by default (`thinking:{type:enabled|disabled}`), streamed as `delta.reasoning_content`. |
| **Mistral** | `/v1/models` has `capabilities.completion_chat / vision / reasoning`, `max_context_length` and `deprecation`, so I'll filter on `completion_chat`. Thinking arrives as `{"type":"thinking"}` content chunks. |
| **Together** | Base URL is **`https://api.together.ai/v1`** (brief says `.xyz`). The bare-array response is unverified, so I'll parse both shapes. Some reasoning models emit `<think>…</think>` inside `content`. |
| **Fireworks** | **The documented list endpoint is `GET /v1/accounts/{account_id}/models`, not `/inference/v1/models`.** Plan: try `/inference/v1/models` first. If it fails, validate the key with a tiny chat call and let the user type a model id. Risk: Fireworks listing may be weaker than the others. |
| **Cerebras** | `/v1/models` has id only. Reasoning comes as **`delta.reasoning`** (not `reasoning_content`), with `reasoning_format:"parsed"`. |
| **Hugging Face** | `/v1/models` exists, but its schema isn't documented in the pages I read. Model ids look like `org/model[:provider]`. Token is `hf_…`. |

The docs pages I read didn't confirm these key prefixes: `gsk_`, `xai-`, `fw_`, `csk-`, `sk-or-v1-`. They're well known, and every detection result is validated by a real `/models` call before saving, so a wrong prefix hint only costs a probe.

**Generic reasoning parser (all OpenAI-style providers):** `delta.reasoning_content` → `delta.reasoning` → `delta.reasoning_details[].text` → Mistral `thinking` chunks → `<think>…</think>` tags split out of `content`. All of these map to `{thinking}`.

## 3. Files to add / change

```
haven/providers/
  __init__.py
  base.py          ModelInfo, ProviderError → human message map (§3.6), timeouts, shared httpx clients,
                   robust SSE parser (bytes in → events out), think-tag splitter
  openai_compat.py OpenAI-style adapter (all openai-style rows + Custom + LM Studio)
  anthropic.py     Messages API adapter
  gemini.py        ported from server.py
  ollama.py        ported from server.py (+ /api/show capability cache)
  filters.py       ONE chat-model filter + vision/reasoning name heuristics (unit-tested)
  registry.py      provider table, detect_provider(), probing, model list cache (mem + disk, 6 h), local polling
  keystore.py      keyring (Windows Credential Manager) + plain-file fallback + env vars + v0.9 migration
haven/storage.py   SQLite (WAL, FTS5 with LIKE fallback): conversations, messages
haven/docs.py      per-page PDF text extraction (cached by sha256), chunking, BM25, budget + spread sampling
haven/shield.py    Privacy Shield detectors, placeholder map, tolerant unmask
haven/chat.py      orchestration: history → shield → retrieval → adapter → NDJSON; server-side persistence
haven/server.py    file tools untouched; AI code moves out; new routes; open_pdf fix (see Q1)
haven/web/index.html   new layout (sidebar, picker, message actions), same design tokens
haven/web/md.js        hand-written safe markdown renderer (see Q4)
app.py             min_size → (800, 600) (Q2); expose open_url as-is (https only already)
tests/             conftest.py, fakes/ (fake provider servers), test_*.py, README.md
requirements.txt   + keyring;  requirements-dev.txt: pytest, pytest-asyncio, respx, playwright, psutil
build.bat + release.yml  --collect-submodules keyring --hidden-import keyring.backends.Windows --collect-all win32ctypes
```

### Key design decisions (tell me if you disagree)

1. **Persistence happens on the server.** `/api/chat` gets `conversation_id` and builds history from SQLite. The server writes the assistant message every ~2 s and at the end. So a switched-away chat keeps streaming into **its own** conversation and can never write into the wrong one; the page just stops painting it. This also lets the server store **unmasked** text (Privacy Shield). The old payload shape (`messages`, no conversation) still works for tests and back-compat.
2. **Cancellation:** Starlette cancels the generator when the client disconnects. Each adapter does `async with client.stream(...)` inside `try/finally`, so cancellation closes the upstream socket immediately. One shared `httpx.AsyncClient` per base URL gives bounded pools, which makes the leak tests measurable.
3. **Model ids:** `{provider_id}:{model}`, split on the **first** colon (Ollama names contain colons). Provider ids: `ollama`, `lmstudio`, then `openai`, `openai-2`, … per saved key. The old `gemini:x` in `localStorage.model2` maps to the migrated Gemini provider.
4. **Documents and citations:** for PDFs with a text layer, Haven always sends **`[Page N]` text** (full text if it fits, BM25 retrieval otherwise) to every provider, so citations behave the same everywhere and the shield can mask it. Native PDF upload (Anthropic `document`, Gemini `inline_data`, OpenAI `file`) is used only for **scanned PDFs to cloud models with the shield off**. Scanned PDFs to local models keep today's page-image path. (Q3)
5. **2,000-page budget:** pypdf extraction of 2,000 pages alone takes far more than 1.5 s, so the "< 1.5 s" budget applies to **retrieval only**. Extracted pages are cached per file hash, so follow-up questions skip extraction.
6. **UI streaming:** only the live message re-renders, once per animation frame. Long threads render the last ~60 messages first, then the rest on scroll-up.

## 4. Risks

- **Scope vs "tonight".** A–D plus the full §8 suite (~150 checks, including Playwright perf) is a lot. I'll keep the phase order so the app ships after each phase. The most likely items to land as `NOT RUN` or reduced are §8.9 memory (30 min → I'll run a shortened 3 min version and label it that way), real-laptop window timing, and live keys.
- **Playwright runs Chromium, not WebView2.** They're the same engine family but not identical. pywebview-specific behaviour (`save_result`, `open_url`) is tested by injecting a fake `window.pywebview.api`.
- **No real API keys here.** Every provider is tested against fakes built from the docs above. Real-provider quirks (exact field names marked "unverified") will only show up in `tests/live_smoke.py`, which you'd run with your own keys.
- **PyInstaller build** is not run here unless you want me to (it takes minutes and downloads PyInstaller). I'll update the flags and report it as NOT RUN otherwise.
- **Contrast check** is automated with a small WCAG luminance function in Playwright on key text only, not a full a11y audit.

## 5. Brief items that are unclear or contradictory

1. §0.3 / Phase 1 says regression tests must pass on current code, but §8.1 expects **400 for an encrypted PDF**, and current code returns 500 (see §1).
2. §8.7 tests the window at **800×600**, but `app.py` sets `min_size=(900, 600)`.
3. §8.7 lists `Ctrl+K`, which today opens **tool search**. The brief doesn't say whether it should change.
4. §3.2 says "first 200 wins" and also "if several succeed, prefer table order". I'll wait for all candidates (each capped at 6 s), then pick by table order.
5. §3.3 "recommended/newest first": almost no provider exposes "recommended". I'll use `created` when present, then a small per-provider preference list, with preview/exp after stable.
6. §8.2 grep test vs §3.4 fallback: in fallback mode the key **is** written to `settings.json` by design. The grep test will exclude that one intended file in the fallback test's own temp dir and use a different fake key there.
7. Attachments: §4.3 stores only names and sizes, so after a reload the PDF must be re-attached to ask more about it (same as today). The extracted-text cache is in memory only.

## 6. Decisions (answered at Checkpoint 1, 2026-11-26)

All six answered with the recommended option: Q1 fix after a failing test, in its own commit · Q2 min_size 800×600 · Q3 text with page markers, native PDF only for scans to cloud with the shield off · Q4 hand-written markdown renderer · Q5 Ctrl+K tools / Ctrl+M picker / Ctrl+N new chat / Ctrl+Shift+F chat search · Q6 install all.

### Original questions

- **Q1** (encrypted PDF): write the §8.1 test, watch it fail, then fix `open_pdf()` (raise 400 when `decrypt("")` fails) as a separate commit in Phase 1, before any other change? *(Recommended.)*
- **Q2:** lower the window `min_size` to 800×600 so §8.7 can pass? *(Recommended.)*
- **Q3:** OK with design decision 4 (text with page markers for text PDFs on all providers, native PDF only for scanned PDFs to cloud with the shield off)?
- **Q4** (markdown): **hand-written renderer** that escapes everything and only emits whitelisted tags (safe by construction, nothing to download), **or** vendor `marked` + `DOMPurify` (~60 KB, needs downloading from npm)? *(Recommend hand-written.)*
- **Q5** (shortcuts): keep `Ctrl+K` = tool search, `Ctrl+M` = model picker, `Ctrl+N` = new chat, and focus the sidebar search with `Ctrl+Shift+F`?
- **Q6** (installs; these are downloads, so I need your OK): `pip install keyring pytest pytest-asyncio respx psutil playwright` into `.venv`, plus `python -m playwright install chromium` (~150 MB from Microsoft's CDN).
