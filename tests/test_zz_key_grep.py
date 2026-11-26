"""§8.2 grep test: runs last (file name). After the whole suite, no file the app wrote may contain a fake key.

The only deliberate exception is the keyring-unavailable fallback test, which writes its own key
(keys.FALLBACK_ONLY) to a plain file in a separate temp folder, as documented in the brief (§3.4).
"""
from tests.fakes import keys as K


def test_no_fake_key_in_any_written_file(test_home):
    files = [p for p in test_home.rglob("*") if p.is_file()]
    assert files, "the suite should have written settings/cache/log files"
    hits = []
    for p in files:
        data = p.read_bytes()
        for k in K.ALL:
            if k.encode() in data:
                hits.append((str(p), k[:12] + "…"))
    assert hits == [], hits
    print(f"\nscanned {len(files)} files under {test_home}: no keys")
