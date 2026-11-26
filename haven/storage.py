"""Conversations in SQLite (%APPDATA%\\Haven\\haven.db, WAL mode, stdlib sqlite3).

Tables: conversations(id, title, created, updated, model) and
        messages(id, conv_id, role, content, thinking, model, meta_json, created, seq).
Attachments are stored as names and sizes only (in meta), never file bytes.
Full-text search uses FTS5 when SQLite has it, otherwise LIKE.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from haven.providers import keystore

ROLES = {"user", "assistant", "tool"}
TITLE_LEN = 40

_STORE: Optional["Store"] = None
_LOCK = threading.Lock()


def make_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= TITLE_LEN:
        return t or "New chat"
    cut = t[:TITLE_LEN]
    if " " in cut[20:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations(
            id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
            model TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS messages(
            id TEXT PRIMARY KEY, conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', thinking TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '', meta_json TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, seq INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv_id, seq);
        CREATE INDEX IF NOT EXISTS conversations_updated ON conversations(updated);
        """)
        self.fts = self._setup_fts()

    def _setup_fts(self) -> bool:
        try:
            self.db.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content='messages', content_rowid='rowid');
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
              INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content); END;
            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
              INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content); END;
            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF content ON messages BEGIN
              INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
              INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content); END;
            """)
            return True
        except sqlite3.OperationalError:
            return False

    def close(self):
        with self.lock:
            try:
                self.db.close()
            except Exception:
                pass

    # ---------------- conversations ----------------
    @staticmethod
    def _conv(r) -> dict:
        return {"id": r["id"], "title": r["title"], "created": r["created"], "updated": r["updated"], "model": r["model"]}

    def list_convs(self) -> List[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM conversations ORDER BY updated DESC").fetchall()
        return [self._conv(r) for r in rows]

    def create_conv(self, title: str = "", model: str = "", cid: Optional[str] = None) -> dict:
        now = time.time()
        cid = cid or uuid.uuid4().hex
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO conversations(id, title, created, updated, model) VALUES (?,?,?,?,?)",
                            (cid, (title or "")[:200], now, now, model or ""))
            r = self.db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        return self._conv(r)

    def get_conv(self, cid: str) -> Optional[dict]:
        with self.lock:
            r = self.db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            if not r:
                return None
            msgs = self.db.execute("SELECT * FROM messages WHERE conv_id=? ORDER BY seq", (cid,)).fetchall()
        return {"conversation": self._conv(r), "messages": [self._msg(m) for m in msgs]}

    def update_conv(self, cid: str, title: Optional[str] = None, model: Optional[str] = None) -> Optional[dict]:
        with self.lock:
            if title is not None:
                self.db.execute("UPDATE conversations SET title=? WHERE id=?", (title.strip()[:200] or "New chat", cid))
            if model is not None:
                self.db.execute("UPDATE conversations SET model=? WHERE id=?", (model, cid))
            r = self.db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        return self._conv(r) if r else None

    def delete_conv(self, cid: str) -> bool:
        with self.lock:
            self.db.execute("BEGIN")
            self.db.execute("DELETE FROM messages WHERE conv_id=?", (cid,))
            n = self.db.execute("DELETE FROM conversations WHERE id=?", (cid,)).rowcount
            self.db.execute("COMMIT")
        return n > 0

    # ---------------- messages ----------------
    @staticmethod
    def _msg(r) -> dict:
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except ValueError:
            meta = {}
        return {"id": r["id"], "conv_id": r["conv_id"], "role": r["role"], "content": r["content"], "thinking": r["thinking"],
                "model": r["model"], "meta": meta, "created": r["created"]}

    def upsert_message(self, cid: str, m: dict) -> dict:
        role = m.get("role")
        if role not in ROLES:
            raise ValueError("role must be user, assistant or tool")
        mid = m.get("id") or uuid.uuid4().hex
        now = time.time()
        meta = json.dumps(m.get("meta") or {}, ensure_ascii=False)
        with self.lock:
            self.db.execute("BEGIN")
            try:
                conv = self.db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
                if not conv:
                    self.db.execute("INSERT INTO conversations(id, title, created, updated, model) VALUES (?,?,?,?,?)",
                                    (cid, "", now, now, m.get("model") or ""))
                    conv = self.db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
                old = self.db.execute("SELECT conv_id, created FROM messages WHERE id=?", (mid,)).fetchone()
                if old and old["conv_id"] != cid:
                    raise ValueError("message belongs to another conversation")
                if old:
                    self.db.execute("UPDATE messages SET role=?, content=?, thinking=?, model=?, meta_json=? WHERE id=?",
                                    (role, m.get("content") or "", m.get("thinking") or "", m.get("model") or "", meta, mid))
                else:
                    seq = self.db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conv_id=?", (cid,)).fetchone()[0]
                    self.db.execute("INSERT INTO messages(id, conv_id, role, content, thinking, model, meta_json, created, seq) "
                                    "VALUES (?,?,?,?,?,?,?,?,?)",
                                    (mid, cid, role, m.get("content") or "", m.get("thinking") or "", m.get("model") or "", meta,
                                     float(m.get("created") or now), seq))
                sets, args = ["updated=?"], [now]
                if not conv["title"] and role == "user" and (m.get("content") or "").strip():
                    sets.append("title=?")
                    args.append(make_title(m["content"]))
                if role == "assistant" and m.get("model"):
                    sets.append("model=?")
                    args.append(m["model"])
                self.db.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE id=?", (*args, cid))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            r = self.db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        return self._msg(r)

    def truncate(self, cid: str, from_id: str) -> int:
        """Delete `from_id` and every later message of the conversation (edit / regenerate)."""
        with self.lock:
            r = self.db.execute("SELECT seq FROM messages WHERE id=? AND conv_id=?", (from_id, cid)).fetchone()
            if not r:
                return 0
            n = self.db.execute("DELETE FROM messages WHERE conv_id=? AND seq>=?", (cid, r["seq"])).rowcount
            self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (time.time(), cid))
        return n

    def import_conv(self, title: str, messages: List[dict], model: str = "") -> dict:
        conv = self.create_conv(title, model)
        with self.lock:
            self.db.execute("BEGIN")
            now = time.time()
            for i, m in enumerate(messages):
                if m.get("role") not in ROLES:
                    continue
                self.db.execute("INSERT INTO messages(id, conv_id, role, content, thinking, model, meta_json, created, seq) "
                                "VALUES (?,?,?,?,?,?,?,?,?)",
                                (uuid.uuid4().hex, conv["id"], m["role"], m.get("content") or "", m.get("thinking") or "",
                                 m.get("model") or "", json.dumps(m.get("meta") or {}, ensure_ascii=False), now - len(messages) + i, i + 1))
            self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, conv["id"]))
            self.db.execute("COMMIT")
        return self.get_conv(conv["id"])["conversation"]

    # ---------------- search ----------------
    def search(self, q: str, limit: int = 50) -> List[dict]:
        q = (q or "").strip()
        if not q:
            return []
        out: Dict[str, dict] = {}
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self.lock:
            for r in self.db.execute("SELECT * FROM conversations WHERE title LIKE ? ESCAPE '\\' ORDER BY updated DESC LIMIT ?", (like, limit)):
                out[r["id"]] = {**self._conv(r), "snippet": ""}
            rows = []
            if self.fts:
                terms = [t for t in re.findall(r"\w+", q, re.UNICODE)]
                if terms:
                    match = " ".join('"' + t.replace('"', '""') + '"*' for t in terms)
                    try:
                        rows = self.db.execute(
                            "SELECT m.conv_id AS cid, snippet(messages_fts, 0, '[', ']', '…', 12) AS snip "
                            "FROM messages_fts JOIN messages m ON m.rowid = messages_fts.rowid "
                            "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?", (match, limit * 4)).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
            if not rows and not self.fts:
                rows = self.db.execute("SELECT conv_id AS cid, substr(content, 1, 120) AS snip FROM messages "
                                       "WHERE content LIKE ? ESCAPE '\\' LIMIT ?", (like, limit * 4)).fetchall()
            for r in rows:
                if r["cid"] in out:
                    if not out[r["cid"]]["snippet"]:
                        out[r["cid"]]["snippet"] = r["snip"]
                    continue
                c = self.db.execute("SELECT * FROM conversations WHERE id=?", (r["cid"],)).fetchone()
                if c:
                    out[r["cid"]] = {**self._conv(c), "snippet": r["snip"]}
                if len(out) >= limit:
                    break
        return list(out.values())[:limit]


def get() -> Store:
    global _STORE
    path = keystore.config_dir() / "haven.db"
    with _LOCK:
        if _STORE is None or _STORE.path != path:
            if _STORE is not None:
                _STORE.close()
            _STORE = Store(path)
        return _STORE


def close():
    global _STORE
    with _LOCK:
        if _STORE is not None:
            _STORE.close()
            _STORE = None
