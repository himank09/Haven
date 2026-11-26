# Haven tests

One command runs everything (from the repo root, with the venv):

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Setup once: `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt` and
`.venv\Scripts\python.exe -m playwright install chromium` (for the UI tests).

- Tests never touch your real `%APPDATA%\Haven`: `conftest.py` points `APPDATA` at a temp folder
  and removes any `*_API_KEY` variables from the environment before the app is imported.
- `tests/fakes/` holds fake AI providers (local servers with controllable streaming, delays and errors).
- `tests/live_smoke.py` talks to real providers only when `HAVEN_RUN_LIVE=1` and `HAVEN_LIVE_<PROVIDER>_KEY` are set;
  otherwise every test there is skipped and reported as NOT RUN.
