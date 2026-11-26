"""§4.3 storage: SQLite conversations + server-side saving of streamed answers (§8.4 'message is saved')."""
import json
import threading
import time

import httpx
import pytest

from haven import storage
from tests.fakes import keys as K
from tests.fakes.hub import sse_openai

H = {"X-Desk-Token": "test-token"}


def test_conversation_crud_and_auto_title(client):
    c = client.post("/api/conversations", json={"model": "ollama:qwen3:4b"}).json()
    assert c["title"] == "" and c["model"] == "ollama:qwen3:4b"
    long = "Please explain how photosynthesis works in plants and why chlorophyll is green"
    m = client.post(f"/api/conversations/{c['id']}/messages", json={"role": "user", "content": long, "meta": {"files": [{"name": "a.pdf", "size": 12}]}}).json()
    assert m["role"] == "user" and m["meta"]["files"][0]["name"] == "a.pdf"
    conv = client.get(f"/api/conversations/{c['id']}").json()
    title = conv["conversation"]["title"]
    assert title.startswith("Please explain how photosynthesis") and len(title) <= 41 and title.endswith("…")
    client.post(f"/api/conversations/{c['id']}/messages", json={"role": "user", "content": "second message"})
    assert client.get(f"/api/conversations/{c['id']}").json()["conversation"]["title"] == title  # only the first sets it
    assert client.patch(f"/api/conversations/{c['id']}", json={"title": "Biology"}).json()["title"] == "Biology"
    assert [x["id"] for x in client.get("/api/conversations").json()["conversations"]] == [c["id"]]
    assert client.delete(f"/api/conversations/{c['id']}").json() == {"ok": True}
    assert client.get(f"/api/conversations/{c['id']}").status_code == 404
    assert client.get("/api/conversations").json()["conversations"] == []


def test_messages_upsert_order_and_truncate(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    ids = []
    for i, role in enumerate(["user", "assistant", "user", "assistant", "tool"]):
        ids.append(client.post(f"/api/conversations/{cid}/messages", json={"id": f"m{i}", "role": role, "content": f"c{i}"}).json()["id"])
    client.post(f"/api/conversations/{cid}/messages", json={"id": "m1", "role": "assistant", "content": "c1 edited"})  # upsert keeps position
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert [m["id"] for m in msgs] == ids and msgs[1]["content"] == "c1 edited"
    r = client.post(f"/api/conversations/{cid}/truncate", json={"from_id": "m2"}).json()
    assert r["removed"] == 3
    assert [m["id"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]] == ["m0", "m1"]
    assert client.post(f"/api/conversations/{cid}/messages", json={"role": "system", "content": "x"}).status_code == 400


def test_search_finds_text_inside_messages(client):
    a = client.post("/api/conversations", json={"title": "Trip plans"}).json()["id"]
    b = client.post("/api/conversations", json={"title": "Taxes"}).json()["id"]
    client.post(f"/api/conversations/{a}/messages", json={"role": "user", "content": "Book the train to Jaipur on Friday"})
    client.post(f"/api/conversations/{b}/messages", json={"role": "assistant", "content": "Section 80C lets you deduct up to 1.5 lakh"})
    r = client.get("/api/conversations/search", params={"q": "jaipur"}).json()["results"]
    assert [x["id"] for x in r] == [a] and "[Jaipur]" in r[0]["snippet"]
    assert [x["id"] for x in client.get("/api/conversations/search", params={"q": "deduct lakh"}).json()["results"]] == [b]
    assert [x["id"] for x in client.get("/api/conversations/search", params={"q": "taxe"}).json()["results"]] == [b]  # title + prefix
    assert client.get("/api/conversations/search", params={"q": '"); DROP TABLE x; --'}).status_code == 200


def test_import_v09_thread(client):
    msgs = [{"role": "user", "content": "old q"}, {"role": "assistant", "content": "old a", "meta": {"info": "qwen · 1.2s"}},
            {"role": "tool", "content": "", "meta": {"act": "compress", "state": "done", "title": "x_compressed.pdf"}}]
    c = client.post("/api/conversations/import", json={"title": "Earlier chats", "messages": msgs}).json()
    got = client.get(f"/api/conversations/{c['id']}").json()
    assert got["conversation"]["title"] == "Earlier chats"
    assert [m["role"] for m in got["messages"]] == ["user", "assistant", "tool"]


def test_wal_mode_and_db_location(client, test_home):
    client.post("/api/conversations", json={})
    s = storage.get()
    assert s.path == test_home / "Haven" / "haven.db"
    assert s.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_search_1000_conversations_under_100ms(client):
    s = storage.get()
    for i in range(1000):
        cid = f"c{i:04d}"
        s.create_conv(f"Conversation {i}", "", cid)
        s.upsert_message(cid, {"role": "user", "content": f"question number {i} about topic{i % 37} and more words"})
        s.upsert_message(cid, {"role": "assistant", "content": f"answer {i} mentioning zebra{i}" if i == 777 else f"answer {i}"})
    t0 = time.perf_counter()
    r = client.get("/api/conversations/search", params={"q": "zebra777"}).json()["results"]
    took = (time.perf_counter() - t0) * 1000
    assert [x["id"] for x in r] == ["c0777"]
    t0 = time.perf_counter()
    lst = client.get("/api/conversations").json()["conversations"]
    took_list = (time.perf_counter() - t0) * 1000
    print(f"\nsearch over 1,000 conversations: {took:.1f} ms; list: {took_list:.1f} ms")
    assert len(lst) == 1000 and took < 100 and took_list < 100


# ---------------- server-side saving during streams ----------------
def setup_openai(live):
    assert httpx.post(live.base + "/api/providers", json={"key": K.OPENAI}, headers=H, timeout=30).status_code == 200
    return "openai:openai-chat-1"


def run_chat(live, model, cid, mid, abort_after=None):
    body = {"model": model, "messages": [{"role": "user", "content": "hi"}], "save": {"conversation_id": cid, "message_id": mid}}
    got = []
    with httpx.Client(timeout=30) as c:
        with c.stream("POST", live.base + "/api/chat", json=body, headers=H) as r:
            for ln in r.iter_lines():
                if ln.strip():
                    got.append(json.loads(ln))
                    if abort_after and sum(1 for e in got if "content" in e) >= abort_after:
                        break
    return got


def db_msg(live, cid, mid):
    msgs = httpx.get(f"{live.base}/api/conversations/{cid}", headers=H).json()["messages"]
    return next((m for m in msgs if m["id"] == mid), None)


def test_completed_answer_is_saved(live, hub):
    model = setup_openai(live)
    hub["openai"].chunks = sse_openai(["Hello ", "world"])
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    run_chat(live, model, cid, "a1")
    m = db_msg(live, cid, "a1")
    assert m["content"] == "Hello world" and m["model"] == model and m["meta"]["live"] is False
    assert m["meta"]["error"] is False and "elapsed" in m["meta"]
    assert httpx.get(f"{live.base}/api/conversations/{cid}", headers=H).json()["conversation"]["model"] == model


def test_error_mid_stream_keeps_text_and_is_saved(live, hub):
    model = setup_openai(live)
    ch = sse_openai(["partial ", "text"])
    hub["openai"].chunks = ch[:3] + [b'data: {"error": {"message": "boom"}}\n\n']
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    run_chat(live, model, cid, "a2")
    m = db_msg(live, cid, "a2")
    assert m["content"].startswith("partial text") and "boom" in m["content"] and m["meta"]["error"] is True


def test_stopped_answer_partial_is_saved(live, hub):
    model = setup_openai(live)
    hub["openai"].infinite = lambda i: sse_openai([f"t{i} "], usage=False, done=False)[1]
    hub["openai"].delay = 0.02
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    run_chat(live, model, cid, "a3", abort_after=3)
    for _ in range(50):
        m = db_msg(live, cid, "a3")
        if m and m["meta"].get("stopped"):
            break
        time.sleep(0.02)
    assert m["meta"]["stopped"] is True and m["content"].startswith("t0 t1 t2")


def test_saves_every_2s_during_streaming(live, hub):
    model = setup_openai(live)
    hub["openai"].chunks = sse_openai([f"w{i} " for i in range(30)])
    hub["openai"].delay = 0.12  # ~3.6 s total
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    t = threading.Thread(target=run_chat, args=(live, model, cid, "a4"))
    t.start()
    time.sleep(2.8)
    mid = db_msg(live, cid, "a4")
    assert mid is not None and mid["meta"]["live"] is True and mid["content"].startswith("w0 w1 ")  # crash now loses <= 2 s
    t.join(15)
    assert db_msg(live, cid, "a4")["content"] == "".join(f"w{i} " for i in range(30))


def test_two_chats_streaming_never_cross_write(live, hub):
    hub["openai"].models = {"data": [{"id": "m-one"}, {"id": "m-two"}]}
    setup_openai(live)
    hub["openai"].chunk_fn = lambda body: sse_openai([f"{body['model']}:{i} " for i in range(25)])
    hub["openai"].delay = 0.01
    c1 = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    c2 = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    ts = [threading.Thread(target=run_chat, args=(live, "openai:m-one", c1, "x1")),
          threading.Thread(target=run_chat, args=(live, "openai:m-two", c2, "x2"))]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    assert db_msg(live, c1, "x1")["content"] == "".join(f"m-one:{i} " for i in range(25))
    assert db_msg(live, c2, "x2")["content"] == "".join(f"m-two:{i} " for i in range(25))
    assert db_msg(live, c1, "x2") is None and db_msg(live, c2, "x1") is None


def test_message_id_of_other_conversation_rejected(client):
    a = client.post("/api/conversations", json={}).json()["id"]
    b = client.post("/api/conversations", json={}).json()["id"]
    client.post(f"/api/conversations/{a}/messages", json={"id": "same", "role": "user", "content": "x"})
    assert client.post(f"/api/conversations/{b}/messages", json={"id": "same", "role": "user", "content": "y"}).status_code == 400
