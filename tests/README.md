# Haven tests

One command runs everything (from the repo root, with the venv):

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Setup once:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m playwright install chromium
```

Takes about 5 minutes. No keys, no internet.

- **Isolation.** `conftest.py` points `APPDATA` at a temp folder, uses an in-memory keyring and removes `*_API_KEY` variables
  before the app is imported, so your real settings, chats and Credential Manager are never touched. Files the app writes
  are archived per test, and `test_zz_key_grep.py` (runs last) checks that no fake key ended up in any of them.
- **Fakes.** `tests/fakes/hub.py` is a real local HTTP server that pretends to be every provider (OpenAI-style SSE,
  Anthropic events, Gemini SSE, Ollama NDJSON), with scripted chunks, delays, errors, dropped connections and
  disconnect detection.
- **UI tests** (`test_ui*.py`, `test_perf.py`) drive Chromium with Playwright against the real server, with a fake
  `window.pywebview` bridge. `-m "not ui"` skips them.

| File | Brief section |
|---|---|
| `test_regression_files.py` | 8.1 existing file tools |
| `test_providers.py` | 8.2 key detection, provider management, key storage |
| `test_models.py` | 8.3 model listing, filter, cache, local polling |
| `test_streaming.py` | 8.4 streaming for every adapter, errors, cancel, leaks |
| `test_storage.py` | 4.3 SQLite chats, saving answers while streaming |
| `test_citations.py` | 8.5 long PDFs, retrieval, citations |
| `test_shield.py` | 8.6 Privacy Shield |
| `test_ui.py`, `test_ui_phase4.py` | 8.7 chat UI, 8.8 security, citation chips, shield in the page |
| `test_perf.py` | 8.9 performance budgets (prints the measured numbers) |
| `test_zz_key_grep.py` | 8.2 no key in any written file |

## Live smoke test (optional, real keys)

`tests/live_smoke.py` isn't collected by the normal run. With keys:

```powershell
$env:HAVEN_RUN_LIVE = "1"; $env:HAVEN_LIVE_OPENAI_KEY = "sk-..."; $env:HAVEN_LIVE_ANTHROPIC_KEY = "sk-ant-..."
.venv\Scripts\python.exe -m pytest -q -rs -s tests/live_smoke.py
```

`HAVEN_LIVE_<PROVIDER>_KEY` works for OPENAI, ANTHROPIC, GEMINI, OPENROUTER, GROQ, XAI, DEEPSEEK, MISTRAL, TOGETHER,
FIREWORKS, CEREBRAS and HUGGINGFACE; `HAVEN_LIVE_OLLAMA=1` / `HAVEN_LIVE_LMSTUDIO=1` test the local servers. Per provider
it lists models, streams a one-sentence answer and cancels a long one. Providers without a key are reported as
**SKIPPED: NOT RUN (no key)**, never as passed.
