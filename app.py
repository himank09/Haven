"""Haven desktop app: starts the local server and shows it in a native window."""
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path


def _log_dir() -> Path:
    # From source: keep the log next to the code (easy to find). Frozen .exe: %APPDATA%\Haven
    if not getattr(sys, "frozen", False):
        return Path(__file__).parent
    d = Path(os.environ.get("APPDATA") or Path.home()) / "Haven"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quiet_streams():
    # pythonw / PyInstaller --noconsole have no console: send output to a log file
    if sys.stdout is None or sys.stderr is None:
        log = open(_log_dir() / "haven.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def _pick_port(preferred: int = 47321) -> int:
    # A fixed port keeps the page origin stable, so chat history (localStorage) survives restarts
    for port in (preferred, 0):
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError("No free port")


ICON = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "icon.ico"


def _windows_identity():
    # Give the app its own taskbar identity so Windows doesn't group it under Python
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Haven.App")
        except Exception:
            pass


def _set_window_icon(window):
    # Running from source the process is pythonw.exe, so set our icon on the window itself
    if sys.platform != "win32" or not ICON.exists():
        return
    try:
        import clr

        clr.AddReference("System.Drawing")
        from System import Action
        from System.Drawing import Icon

        form = window.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(ICON)))))
    except Exception as e:
        print("icon:", e)


def main():
    _quiet_streams()
    _windows_identity()
    token = secrets.token_urlsafe(24)
    os.environ["HAVEN_TOKEN"] = token
    os.environ["HAVEN_LOG_DIR"] = str(_log_dir())  # must be set before the server module is imported
    import uvicorn
    import webview

    from haven import server

    port = _pick_port()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_config=None, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):  # wait up to 10 s for the server
        if srv.started:
            break
        time.sleep(0.1)

    window = None

    class Api:
        """Functions the web page can call through window.pywebview.api."""

        def save_result(self, rid):
            item = server.RESULTS.get(rid)
            if not item:
                return {"error": "Result expired, run the tool again"}
            name, data = item
            dialog = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
            downloads = str(Path.home() / "Downloads")
            path = window.create_file_dialog(dialog, directory=downloads, save_filename=name)
            if not path:
                return {"cancelled": True}
            path = path[0] if isinstance(path, (list, tuple)) else path
            Path(path).write_bytes(data)
            server.RESULTS.pop(rid, None)
            return {"path": path}

        def save_text(self, name, text):
            rid = secrets.token_hex(8)
            server.RESULTS[rid] = (name, text.encode("utf-8"))
            return self.save_result(rid)

        def open_url(self, url):
            import webbrowser

            if str(url).startswith("https://"):
                webbrowser.open(url)
            return True

        def open_folder(self, path):
            if path and os.path.exists(path) and sys.platform == "win32":
                os.startfile(os.path.dirname(path))
            return True

    window = webview.create_window(
        "Haven",
        f"http://127.0.0.1:{port}/?t={token}",
        js_api=Api(),
        width=1280,
        height=820,
        min_size=(800, 600),
        background_color="#F5F7FC",
    )
    window.events.shown += lambda: _set_window_icon(window)
    data_dir = Path(os.environ.get("APPDATA") or Path.home()) / "Haven" / "webview"
    webview.start(private_mode=False, storage_path=str(data_dir))
    srv.should_exit = True


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        (_log_dir() / "haven.log").open("a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
        raise
