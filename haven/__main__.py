"""Browser/dev mode: python -m haven  ->  http://127.0.0.1:8765"""
import os

import uvicorn

from haven.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("HAVEN_PORT", 8765)), log_level="warning")
