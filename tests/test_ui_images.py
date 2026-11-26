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
    send(pg, "draw a cat")
    wait_done(pg)
    assert hub.img_requests == [] and not [r for r in hub["gemini"].requests if r["kind"] == "image"]
    assert pg.locator("#thread > .a:last-child .pics").count() == 0


def test_settings_images_tab(pg, live, hub):
    open_app(pg, live)
    pg.click("#me-gear") if pg.locator("#me-gear").is_visible() else pg.keyboard.press("Control+Comma")
    pg.click(".tab[data-tab=images]")
    pg.wait_for_selector("#imgsvc", state="visible")
    assert pg.is_checked("#img-poll")
    pg.fill("#img-hf", "hf_FAKEtoken1234567890")
    pg.click("[data-imgsave=hf]")
    pg.wait_for_function("() => document.querySelector('#img-hf-st').textContent.includes('7890')")
    assert pg.input_value("#img-hf") == ""  # the token is never shown again
    if SHOTS:
        pg.screenshot(path=SHOTS.replace(".png", "_settings.png"))


def test_model_picker_and_retry(pg, live, hub):
    open_app(pg, live)
    assert pg.locator("#imgmodel").is_hidden()
    pg.click("#imgmode")
    pg.wait_for_function("() => document.querySelectorAll('#imgmodel option').length > 4")
    texts = pg.locator("#imgmodel option").all_inner_texts()
    assert texts[0].startswith("Automatic") and any("Nano Banana 2 Lite" in t for t in texts)
    assert any(t.startswith("FLUX.1 schnell · Hugging Face Space · Free") for t in texts)
    pg.select_option("#imgmodel", "gemini:gemini-3.1-flash-lite-image")
    hub["gemini"].chat_status = 429
    send(pg, "a lighthouse at dusk")
    wait_done(pg)
    pg.wait_for_selector("#thread > .a:last-child .retry button")
    body = pg.inner_text("#thread > .a:last-child .body")
    assert "Couldn't make the picture with Nano Banana 2 Lite" in body
    if SHOTS:
        pg.screenshot(path=SHOTS.replace(".png", "_retry.png"))
    pg.click("#thread > .a:last-child [data-retry-img=hfspace]")
    wait_done(pg)
    check_image(pg)
    assert "FLUX.1 schnell" in pg.inner_text("#thread > .a:last-child .meta")
    if SHOTS:
        pg.screenshot(path=SHOTS.replace(".png", "_picker.png"))
