"""In the chat: asking for a picture shows the generated image with Save/Copy (fake Gemini image model)."""
import pytest

from tests.fakes import keys as K
from tests.test_images import IMG_MODELS
from tests.ui import add_key, new_page, open_app, send, wait_done

pytestmark = pytest.mark.ui
SHOTS = None


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def pg(browser, live, hub):
    hub["gemini"].models = IMG_MODELS
    add_key(live, K.GEMINI)
    ctx, page = new_page(browser, live)
    yield page
    assert page.errors == [], page.errors
    ctx.close()


def check_image(pg):
    img = pg.locator("#thread > .a:last-child .pics img")
    img.wait_for(timeout=15000)
    pg.wait_for_function("() => { const i = document.querySelector('#thread > .a:last-child .pics img');"
                         " return i && i.complete && i.naturalWidth > 0; }", timeout=10000)
    assert pg.locator("#thread > .a:last-child [data-pact=save]").count() == 1
    assert pg.locator("#thread > .a:last-child [data-pact=copy]").count() == 1


def test_auto_detect_makes_an_image(pg, live, hub):
    open_app(pg, live)
    pg.on("dialog", lambda d: d.accept())  # "This looks like a request for a picture..." -> OK
    send(pg, "draw a red fox in the snow")
    wait_done(pg)
    check_image(pg)
    if SHOTS:
        pg.screenshot(path=SHOTS)


def test_image_button(pg, live, hub):
    open_app(pg, live)
    pg.click("#imgmode")
    assert pg.get_attribute("#imgmode", "aria-pressed") == "true"
    send(pg, "a lighthouse at dusk")
    wait_done(pg)
    check_image(pg)


def test_cancel_gives_text_answer(pg, live, hub):
    open_app(pg, live)
    pg.on("dialog", lambda d: d.dismiss())
    before = len([r for r in hub["gemini"].requests if r["kind"] == "image"])
    send(pg, "draw a cat")
    wait_done(pg)
    assert len([r for r in hub["gemini"].requests if r["kind"] == "image"]) == before
    assert pg.locator("#thread > .a:last-child .pics").count() == 0
