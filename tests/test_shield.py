"""§8.6 Privacy Shield."""
import base64
import json

import httpx
import pytest

from haven.shield import Shield, luhn, unmask
from tests.fakes import keys as K
from tests.fakes.hub import ndjson_ollama, sse_openai
from tests.helpers import image_pdf, img_bytes, make_pdf

H = {"X-Desk-Token": "test-token"}


def luhn_complete(prefix: str, length: int) -> str:
    body = prefix + "0" * (length - len(prefix) - 1)
    for d in "0123456789":
        if luhn(body + d):
            return body + d


VISA = "4111 1111 1111 1111"
MASTERCARD = "5555-5555-5555-4444"
RUPAY = " ".join(luhn_complete("6070", 16)[i:i + 4] for i in range(0, 16, 4))
AMEX15 = luhn_complete("3782", 15)

POSITIVE = [
    ("+91 98765 43210", "PHONE"), ("09876543210", "PHONE"), ("9876543210", "PHONE"), ("98765-43210", "PHONE"),
    ("+919876543210", "PHONE"), ("91 98765 43210", "PHONE"), ("6123456789", "PHONE"),
    ("ABCDE1234F", "PAN"), ("2345 6789 0123", "AADHAAR"), ("2345-6789-0123", "AADHAAR"), ("999941057058", "AADHAAR"),
    (VISA, "CARD"), (MASTERCARD, "CARD"), (RUPAY, "CARD"), ("4111111111111111", "CARD"), (AMEX15, "CARD"),
    ("name.surname+tag@mail.co.in", "EMAIL"), ("someone@example.com", "EMAIL"),
    ("SBIN0001234", "IFSC"), ("HDFC0ABC123", "IFSC"),
    ("user@okhdfcbank", "UPI"), ("9876543210@ybl", "UPI"), ("my.name@oksbi", "UPI"),
]
NEGATIVE = [
    "12-11-2026", "2026", "the year 1999", "INV-2026-00123", "Invoice no. 4567891234", "1234 5678 9012 3456",
    "page 217", "p. 12", "₹98,765.43", "Rs 1,23,45,678", "ME23B142", "v1.2.3", "version 10.0.19045",
    "5123456789", "0123456789", "4987654321", "13.5 g/dL", "HbA1c 6.2 %", "10:30 AM", "2023-24", "call 1800-123-4567",
    "ISBN 978-3-16-148410-0", "PIN 560001", "abcde1234f",  # lower-case is not a PAN
]


@pytest.mark.parametrize("value,kind", POSITIVE)
def test_true_positives(value, kind):
    s = Shield()
    out = s.mask(f"My detail is {value}, thanks.")
    assert value not in out
    assert out == f"My detail is [{kind}_1], thanks."
    assert s.values[f"[{kind}_1]"] == value


@pytest.mark.parametrize("text", NEGATIVE)
def test_true_negatives(text):
    s = Shield()
    assert s.mask(f"x {text} y") == f"x {text} y"
    assert s.values == {}


def test_brief_aadhaar_sample_masked_but_plain_12_digits_need_checksum():
    s = Shield()
    assert s.mask("2345 6789 0123") == "[AADHAAR_1]"        # grouped 4-4-4: masked (brief's own sample)
    assert Shield().mask("234567890123") == "234567890123"  # ungrouped and fails Verhoeff: left alone
    assert Shield().mask("999941057058") == "[AADHAAR_1]"   # ungrouped but passes Verhoeff


def test_same_value_same_placeholder_and_numbering():
    s = Shield()
    a = s.mask("Call 9876543210 or +91 98765 43210. Backup: 9123456780. Mail a@b.co and A@B.CO")
    assert a == "Call [PHONE_1] or [PHONE_1]. Backup: [PHONE_2]. Mail [EMAIL_1] and [EMAIL_1]"
    b = s.mask("Again 98765-43210")  # stable across all texts of one request
    assert b == "Again [PHONE_1]"


def test_summary_note():
    s = Shield()
    s.mask("9876543210, 9123456780, ABCDE1234F")
    assert s.summary("OpenAI") == "Privacy Shield hid 2 phone numbers and 1 PAN before sending to OpenAI."
    assert Shield().summary("OpenAI") == ""


@pytest.mark.parametrize("echoed", ["[PHONE_1]", "[PHONE 1]", "PHONE_1", "[phone_1]", "PHONE-1", "[ PHONE_1 ]"])
def test_tolerant_unmask(echoed):
    s = Shield()
    s.mask("9876543210")
    assert s.unmask(f"Your number is {echoed}.") == "Your number is 9876543210."


def test_unmask_leaves_unknown_placeholders():
    assert unmask("[PHONE_9] and [EMAIL_1]", {"[EMAIL_1]": "a@b.co"}) == "[PHONE_9] and a@b.co"


# ---------------- end to end ----------------
SECRETS = ["9876543210", "ABCDE1234F", "ravi.kumar@mail.co.in", "2345 6789 0123", "SBIN0001234", "ravi@okicici", VISA]


def setup_openai(live):
    r = httpx.post(live.base + "/api/providers", json={"key": K.OPENAI}, headers=H, timeout=30)
    assert r.status_code == 200, r.text


def run(live, model, messages, files=None, save=None, shield_ok=False):
    body = {"model": model, "messages": messages, "files": files or [], "shield_ok": shield_ok}
    if save:
        body["save"] = save
    ev = []
    with httpx.Client(timeout=60) as c:
        with c.stream("POST", live.base + "/api/chat", json=body, headers=H) as r:
            for ln in r.iter_lines():
                if ln.strip():
                    ev.append(json.loads(ln))
    return ev


def b64(data):
    return base64.b64encode(data).decode()


def test_cloud_request_contains_no_original_values(live, hub):
    setup_openai(live)
    hub["openai"].chunk_fn = lambda body: sse_openai(["Saved [PHONE_1] for ", "[EMAIL 1]", " and PAN PAN_1."])
    pdf = make_pdf(["Customer KYC form", f"Aadhaar: {SECRETS[3]}\nIFSC: {SECRETS[4]}\nUPI: {SECRETS[5]}\nCard: {SECRETS[6]}"])
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    history = [{"role": "user", "content": f"My phone is {SECRETS[0]} and PAN {SECRETS[1]}"},
               {"role": "assistant", "content": f"Noted {SECRETS[0]}."},
               {"role": "user", "content": f"Email me at {SECRETS[2]}. Check the attached form."}]
    ev = run(live, "openai:openai-chat-1", history, [{"name": "kyc.pdf", "mime": "application/pdf", "data": b64(pdf)}],
             save={"conversation_id": cid, "message_id": "ans1"})
    sent = json.dumps(hub["openai"].chat_requests()[-1]["json"], ensure_ascii=False)
    for v in SECRETS:
        assert v not in sent, v
        assert v.replace(" ", "") not in sent.replace(" ", "")
    assert "[PHONE_1]" in sent and "[AADHAAR_1]" in sent and "[CARD_1]" in sent
    notes = [e for e in ev if "note" in e]
    sh = [e for e in notes if e["note"].startswith("Privacy Shield hid")][0]
    assert "1 phone number" in sh["note"] and "1 PAN" in sh["note"] and "1 Aadhaar number" in sh["note"] and "OpenAI" in sh["note"]
    assert sh["unmask"]["[PHONE_1]"] == SECRETS[0]
    streamed = "".join(e.get("content", "") for e in ev)
    assert streamed == "Saved [PHONE_1] for [EMAIL 1] and PAN PAN_1."  # the page swaps these back (UI test)
    assert unmask(streamed, sh["unmask"]) == f"Saved {SECRETS[0]} for {SECRETS[2]} and PAN {SECRETS[1]}."
    saved = [m for m in httpx.get(f"{live.base}/api/conversations/{cid}", headers=H).json()["messages"] if m["id"] == "ans1"][0]
    assert saved["content"] == f"Saved {SECRETS[0]} for {SECRETS[2]} and PAN {SECRETS[1]}."  # DB keeps real values
    assert "unmask" not in saved["meta"]  # what was sent (placeholders and the map) is not stored


def test_local_providers_get_everything_as_written(live, hub):
    hub["ollama"].chunks = ndjson_ollama(["ok"])
    ev = run(live, "ollama:qwen3:4b", [{"role": "user", "content": f"My phone is {SECRETS[0]}"}])
    sent = json.dumps(hub["ollama"].chat_requests()[-1]["json"])
    assert SECRETS[0] in sent and "[PHONE" not in sent
    assert not any("Privacy Shield" in e.get("note", "") for e in ev)


def test_shield_off_masks_nothing_and_says_so(live, hub, client):
    setup_openai(live)
    client.post("/api/settings", json={"shield": False})
    hub["openai"].chunks = sse_openai(["ok"])
    ev = run(live, "openai:openai-chat-1", [{"role": "user", "content": f"My phone is {SECRETS[0]}"}])
    sent = json.dumps(hub["openai"].chat_requests()[-1]["json"])
    assert SECRETS[0] in sent
    assert any(e.get("note") == "Privacy Shield is off: messages and files go to OpenAI as written." for e in ev)
    assert client.get("/api/settings").json()["shield"] is False


@pytest.mark.parametrize("name,data,mime", [("photo.jpg", img_bytes("JPEG", (40, 40)), "image/jpeg"),
                                             ("scan.pdf", image_pdf(400, 500), "application/pdf")])
def test_uncheckable_attachment_needs_confirmation(live, hub, name, data, mime):
    hub["openai"].models = {"data": [{"id": "gpt-4o"}]}
    setup_openai(live)
    hub["openai"].chunks = sse_openai(["seen"])
    msgs = [{"role": "user", "content": "What is this?"}]
    cid = httpx.post(live.base + "/api/conversations", json={}, headers=H).json()["id"]
    ev = run(live, "openai:gpt-4o", msgs, [{"name": name, "mime": mime, "data": b64(data)}], save={"conversation_id": cid, "message_id": "m1"})
    assert [list(e) for e in ev] == [["confirm"], ["done"]]
    assert name in ev[0]["confirm"] and "Send to OpenAI anyway?" in ev[0]["confirm"]
    assert hub["openai"].chat_requests() == []  # nothing left the PC
    assert httpx.get(f"{live.base}/api/conversations/{cid}", headers=H).json()["messages"] == []  # nothing saved
    ev = run(live, "openai:gpt-4o", msgs, [{"name": name, "mime": mime, "data": b64(data)}], shield_ok=True)
    assert "".join(e.get("content", "") for e in ev) == "seen"
    assert any(name in e.get("note", "") and "without checking" in e.get("note", "") for e in ev)


def test_text_pdf_is_sent_as_masked_text_not_the_file(live, hub):
    setup_openai(live)
    hub["openai"].chunks = sse_openai(["ok"])
    pdf = make_pdf([f"Statement for account holder. Mobile {SECRETS[0]}. " * 3])
    ev = run(live, "openai:openai-chat-1", [{"role": "user", "content": "Summarise"}], [{"name": "s.pdf", "mime": "application/pdf", "data": b64(pdf)}])
    req = hub["openai"].chat_requests()[-1]["json"]
    sent = json.dumps(req)
    assert "application/pdf" not in sent and SECRETS[0] not in sent and "[PHONE_1]" in sent
    assert not any("confirm" in e for e in ev)
