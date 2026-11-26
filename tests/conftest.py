"""Shared test setup.

The server reads HAVEN_TOKEN and APPDATA at import time, so they are set here,
before anything imports `haven.server`. APPDATA points at a throwaway folder so
tests never touch the real %APPDATA%/Haven.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_HOME = Path(tempfile.mkdtemp(prefix="haven-test-"))
os.environ["APPDATA"] = str(TEST_HOME)
os.environ["HAVEN_LOG_DIR"] = str(TEST_HOME / "Haven")
os.environ["HAVEN_TOKEN"] = "test-token"
for k in list(os.environ):  # real keys on the dev machine must never leak into tests
    if k.endswith("_API_KEY") or k.startswith("HAVEN_LIVE_"):
        if not os.environ.get("HAVEN_RUN_LIVE"):
            os.environ.pop(k)

import pytest  # noqa: E402

TOKEN = "test-token"
H = {"X-Desk-Token": TOKEN}


@pytest.fixture(scope="session")
def test_home() -> Path:
    return TEST_HOME


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from haven import server

    with TestClient(server.app, raise_server_exceptions=False) as c:
        c.headers.update(H)
        yield c
