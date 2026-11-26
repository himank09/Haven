"""Shared test setup.

The server reads HAVEN_TOKEN at import time and settings live under APPDATA, so both are set here,
before anything imports `haven.server`. APPDATA points at a throwaway folder and keyring uses an
in-memory backend, so tests never touch the real %APPDATA%/Haven or Windows Credential Manager.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_HOME = Path(tempfile.mkdtemp(prefix="haven-test-"))
os.environ["APPDATA"] = str(TEST_HOME)
os.environ["HAVEN_LOG_DIR"] = str(TEST_HOME / "Haven")
os.environ["HAVEN_TOKEN"] = "test-token"
os.environ["HAVEN_NO_POLL"] = "1"
for k in list(os.environ):  # real keys on the dev machine must never leak into tests
    if (k.endswith("_API_KEY") or k in ("HF_TOKEN", "OLLAMA_URL", "GEMINI_BASE") or k.startswith("HAVEN_BASE_")) \
            and not os.environ.get("HAVEN_RUN_LIVE"):
        os.environ.pop(k)

import keyring  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402


class MemoryKeyring(KeyringBackend):
    priority = 1
    store = {}

    def set_password(self, service, username, password):
        MemoryKeyring.store[(service, username)] = password

    def get_password(self, service, username):
        return MemoryKeyring.store.get((service, username))

    def delete_password(self, service, username):
        MemoryKeyring.store.pop((service, username), None)


keyring.set_keyring(MemoryKeyring())

from tests.fakes.hub import KINDS, Hub  # noqa: E402

HUB = Hub()
HUB.start()
if not os.environ.get("HAVEN_RUN_LIVE"):  # the live smoke test talks to the real providers
    for _k in KINDS:
        if _k != "custom":
            os.environ[f"HAVEN_BASE_{_k.upper()}"] = HUB.url(_k)

import pytest  # noqa: E402

TOKEN = "test-token"
H = {"X-Desk-Token": TOKEN}


@pytest.fixture(scope="session")
def test_home() -> Path:
    return TEST_HOME


@pytest.fixture(scope="session")
def hub() -> Hub:
    return HUB


@pytest.fixture(autouse=True)
def clean_state(request):
    """Fresh settings, model cache, keyring and fake providers for every test."""
    from haven import storage
    from haven.providers import ollama, registry

    storage.close()  # release haven.db so it can be archived

    d = TEST_HOME / "Haven"
    d.mkdir(parents=True, exist_ok=True)
    archive = TEST_HOME / "archive"  # keep every file the app wrote, so the final key-grep test can scan them all
    archive.mkdir(exist_ok=True)
    for f in ("settings.json", "models_cache.json", "haven.db", "haven.db-wal", "haven.db-shm"):
        p = d / f
        for _try in range(40):  # a stream from the previous test may still be finishing and reopen the DB
            if not p.exists():
                break
            try:
                p.replace(archive / f"{len(list(archive.iterdir()))}-{f}")
                break
            except OSError:
                storage.close()
                time.sleep(0.05)
    registry.CACHE.mem.clear()
    registry.CACHE.local.clear()
    registry.CACHE._loaded = False
    ollama._SHOW.clear()
    MemoryKeyring.store.clear()
    HUB.reset()
    from haven import images  # free image services -> the fake hub (tests never reach the real sites)
    base = f"http://127.0.0.1:{HUB.port}/img"
    images.HF_URL, images.CF_URL, images.POLL_URL = base + "/hf/flux", base + "/cf/{acct}/flux", base + "/poll/{prompt}"
    images.SPACE_URL = base + "/space/gradio_api"
    yield


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from haven import server

    with TestClient(server.app, raise_server_exceptions=False) as c:
        c.headers.update(H)
        yield c


@pytest.fixture(scope="session")
def live():
    """The real Haven app served by uvicorn on a random port (for streaming/cancel tests over real sockets)."""
    import socket

    import uvicorn

    from haven import server

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.02)
    srv.base = f"http://127.0.0.1:{port}"
    srv.thread_obj = t
    yield srv
    srv.should_exit = True
    t.join(5)
