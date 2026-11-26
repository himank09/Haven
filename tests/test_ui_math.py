"""Math in answers ($..$, $$..$$, \\(..\\), \\[..\\]) rendered with the vendored KaTeX, offline and safely."""
import time

import pytest

from tests.fakes.hub import ndjson_ollama
from tests.ui import new_page, open_app, send, wait_done

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def pg(browser, live):
    ctx, page = new_page(browser, live)
    yield page
    assert page.errors == [], page.errors
    ctx.close()


def answer(pg, hub, *pieces, delay=0.0):
    hub["ollama"].chunks = ndjson_ollama(list(pieces))
    hub["ollama"].delay = delay
    send(pg, "q")
    wait_done(pg)
    return "#thread > .a:last-child .body"


def test_the_screenshot_text_renders_as_math(pg, live, hub):
    open_app(pg, live)
    b = answer(pg, hub, "- **Slow Sorts (Bubble, Selection, Insertion):** $O(n^2)$ worst-case.\n"
                        "- **Fast Sorts (Merge, Quick, Heap):** $O(n \\log n)$ average/worst-case.")
    assert pg.locator(f"{b} .math .katex").count() == 2
    text = pg.inner_text(b)
    assert "$" not in text and "\\log" not in text  # no raw LaTeX left on screen
    assert pg.locator(f"{b} .math .msupsub").count() >= 1  # n² is a real superscript
    assert "log" in text


def test_display_and_bracket_forms(pg, live, hub):
    open_app(pg, live)
    b = answer(pg, hub, "Quadratic formula:\n\n$$\nx = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}\n$$\n\n"
                        "Also \\(a^2 + b^2 = c^2\\) and\n\n\\[\n\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}\n\\]\n\nand $$E = mc^2$$ inline.")
    assert pg.locator(f"{b} .math-block .katex-display").count() == 3
    assert pg.locator(f"{b} .math .katex").count() == 1
    assert pg.locator(f"{b} .katex .mfrac").count() >= 2
    assert "\\frac" not in pg.inner_text(b) and "$$" not in pg.inner_text(b)


def test_prices_and_escaped_dollars_stay_text(pg, live, hub):
    open_app(pg, live)
    b = answer(pg, hub, "It costs $5 and $10 per month, or \\$20 a year. Budget: $ 300.")
    assert pg.locator(f"{b} .katex").count() == 0
    t = pg.inner_text(b)
    assert "$5 and $10 per month" in t and "$20 a year" in t and "$ 300" in t


def test_math_inside_code_is_untouched(pg, live, hub):
    open_app(pg, live)
    b = answer(pg, hub, "Use `$x$` in LaTeX.\n\n```python\nprice = '$5'  # $O(n)$\n```")
    assert pg.locator(f"{b} .katex").count() == 0
    assert "$x$" in pg.inner_text(f"{b} :not(pre) > code")
    assert "$O(n)$" in pg.inner_text(f"{b} pre code")


def test_formula_streamed_in_pieces(pg, live, hub):
    open_app(pg, live)
    b = answer(pg, hub, "Half:\n\n$$\n\\frac{1}", "{2}\n$$\n\nand $a", "^2$ done.", delay=0.05)
    assert pg.locator(f"{b} .math-block .mfrac").count() == 1
    assert pg.locator(f"{b} .math .katex").count() == 1
    assert pg.locator(f"{b} .math-pending").count() == 0


def test_broken_latex_does_not_break_the_answer(pg, live, hub):
    open_app(pg, live)
    b = answer(pg, hub, "Bad: $\\frac{1}{$ and good: $x^2$ after.")
    assert "after." in pg.inner_text(b)
    assert pg.locator(f"{b} .katex").count() >= 1


MATH_ATTACKS = [
    "$\\href{javascript:window.__xss=1}{click me}$",
    "$\\url{https://evil.example/track}$",
    "$\\includegraphics{https://evil.example/pixel.png}$",
    "$\\htmlStyle{background:url(https://evil.example/x)}{styled}$",
    "$\\htmlClass{x}{y}\\htmlId{z}{w}\\htmlData{a=b}{c}$",
    "$$\\def\\a{\\a\\a}\\a$$",  # macro bomb
    "$<img src=x onerror=window.__xss=1>$",
    "$\\text{<script>window.__xss=1</script>}$",
]


@pytest.mark.parametrize("payload", MATH_ATTACKS)
def test_math_cannot_add_links_images_styles_or_scripts(pg, live, hub, payload):
    open_app(pg, live)
    t0 = time.time()
    b = answer(pg, hub, f"Look: {payload} end")
    assert time.time() - t0 < 10  # no freeze
    for a in pg.locator(f"{b} a, {b} .lnk").all():
        a.click()
    time.sleep(0.2)
    assert pg.evaluate("window.__xss") is None
    assert pg.locator(f"{b} [href], {b} img, {b} script, {b} iframe").count() == 0
    assert pg.evaluate("window.__opened") == []
    styled = pg.evaluate(f"[...document.querySelectorAll('{b} [style]')].map(e => e.getAttribute('style')).filter(s => /url\\(|expression|javascript/i.test(s))")
    assert styled == []
    outside = [u for u in pg.requests if not u.startswith(live.base) and not u.startswith("data:")]
    assert outside == []


def test_katex_files_are_local_and_fonts_load(pg, live, hub):
    open_app(pg, live)
    answer(pg, hub, "$\\int_0^1 x^2\\,dx = \\tfrac{1}{3}$")
    time.sleep(0.3)
    assert any("/web/vendor/katex/katex.min.js" in u for u in pg.requests)
    assert any("/web/vendor/katex/fonts/" in u and u.endswith(".woff2") for u in pg.requests)
    assert all(u.startswith(live.base) or u.startswith("data:") for u in pg.requests)
    fam = pg.evaluate("getComputedStyle(document.querySelector('.katex .mord')).fontFamily")
    assert "KaTeX" in fam
