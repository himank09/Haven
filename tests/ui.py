"""Playwright helpers shared by the UI test modules (real server, fake providers, fake pywebview bridge)."""
import json
import time

import httpx

H = {"X-Desk-Token": "test-token"}

FAKE_PYWEBVIEW = """
window.__opened = []; window.__saved = [];
window.pywebview = {api: {
  open_url: u => { window.__opened.push(u); return Promise.resolve(true); },
  save_text: (n, t) => { window.__saved.push([n, t]); return Promise.resolve({path: 'C:/Users/me/Downloads/' + n}); },
  save_result: id => Promise.resolve({path: 'C:/Users/me/Downloads/result-' + id.slice(0, 6) + '.pdf'}),
  open_folder: p => Promise.resolve(true)}};
"""


def new_page(browser, live, width=1280, height=800, scheme=None):
    # bypass_csp: Playwright's wait_for_function needs eval. It also means the XSS tests prove the renderer is safe
    # by itself, without the page's Content-Security-Policy as a second line of defence.
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme or "light", bypass_csp=True)
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=live.base)
    ctx.add_init_script(FAKE_PYWEBVIEW)
    pg = ctx.new_page()
    pg.errors = []
    pg.requests = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("request", lambda r: pg.requests.append(r.url))
    return ctx, pg


def open_app(pg, live):
    pg.goto(live.base + "/?t=test-token")
    pg.wait_for_selector("html[data-ready='1']")
    pg.wait_for_function("window.haven && window.haven.modelsLoaded")


def send(pg, text):
    pg.fill("#input", text)
    pg.keyboard.press("Enter")


def wait_done(pg, timeout=15000):
    pg.wait_for_function("!document.querySelector('#send').classList.contains('stop') && "
                         "document.querySelector('#thread > .a:last-child .tools .meta')", timeout=timeout)


def last_answer(pg):
    return pg.inner_text("#thread > .a:last-child .body")


def api_get(live, path):
    return httpx.get(live.base + path, headers=H, timeout=10).json()


def add_key(live, key):
    r = httpx.post(live.base + "/api/providers", json={"key": key}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def wait_until(fn, timeout=5.0, step=0.02):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


CONTRAST_JS = """
(sel) => {
  const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const parse = s => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {c: p.slice(0, 3), a: p.length > 3 ? p[3] : 1}; };
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
    const fg = parse(getComputedStyle(el).color);
    let bg = null, n = el;
    while (n && n.nodeType === 1) { const b = parse(getComputedStyle(n).backgroundColor); if (b && b.a > 0.5) { bg = b; break; } n = n.parentElement; }
    if (!bg) bg = parse(getComputedStyle(document.body).backgroundColor);
    const L1 = lum(fg.c), L2 = lum(bg.c);
    out.push({sel, text: (el.innerText || el.placeholder || '').slice(0, 30), ratio: (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)});
  }
  return out;
}
"""
