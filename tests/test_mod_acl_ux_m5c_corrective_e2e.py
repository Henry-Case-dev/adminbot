"""MOD-ACL-UX-01 corrective — поведенческий гейт hit-area (F2/F3).

Зачем: текстовые CSS-проверки проходили и на дефектной базе (22-px кнопка,
`::after ±11px`, обрезанный `overflow: hidden` контейнером). Здесь реальный
Chromium на 390/320 проверяет `document.elementFromPoint`: попадание на
±20 px от центра кнопки tri-state обязано возвращать ТУ ЖЕ кнопку, кнопка
«Открыть» не должна перехватываться, а карточка обязана сохранить высоту
132–164 (layout не сломан).

Стенд — существующий `tools/ui_mod_acl_m4_catalog_e2e.py` (стабы `CONFIG_*`
и `TMA_STUB`), никакого production/записи. Без Playwright/Chromium тест
честно пропускается.

Запуск: pytest tests/test_mod_acl_ux_m5c_corrective_e2e.py -q
"""
import json
import os
import socket
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sync_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright не установлен")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="module")
def stand():
    import tools.ui_mod_acl_m4_catalog_e2e as e2e
    port = _free_port()
    e2e.PORT = port
    httpd = e2e._start_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"port": port, "e2e": e2e}
    finally:
        httpd.shutdown()


def _handler(e2e):
    def route_handler(route, request):
        path = request.url.split("?")[0]
        if path.endswith("/api/config"):
            chat = bool(request.headers.get("x-chat-id"))
            payload = e2e.CONFIG_CHAT if chat else e2e.CONFIG_GLOBAL
            return route.fulfill(status=200,
                                 content_type="application/json",
                                 body=json.dumps(payload))
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(e2e._stub_for(request.url)))
    return route_handler


PROBE_JS = r"""() => {
  const card = document.querySelector('article[data-mod="mod_experience"]');
  if (!card) return {missing: 'card'};
  const btn = card.querySelector('[data-module-chat-tristate="on"]');
  if (!btn) return {missing: 'tristate'};
  btn.scrollIntoView({block: 'center'});
  const box = btn.getBoundingClientRect();
  const cx = box.left + box.width / 2;
  const cy = box.top + box.height / 2;
  const at = (dy) => {
    const el = document.elementFromPoint(cx, cy + dy);
    if (!el) return null;
    const own = el.getAttribute && el.getAttribute('data-module-chat-tristate');
    if (own) return {kind: 'tristate', id: own};
    const open = el.getAttribute && el.getAttribute('data-module-open');
    if (open !== null && open !== undefined) return {kind: 'open'};
    return {kind: 'other',
            tag: el.tagName,
            cls: String(el.className || '').slice(0, 40)};
  };
  const openBtn = card.querySelector('[data-module-open]');
  let openAtCenter = null;
  if (openBtn) {
    const ob = openBtn.getBoundingClientRect();
    const oel = document.elementFromPoint(ob.left + ob.width / 2,
                                          ob.top + ob.height / 2);
    openAtCenter = oel ? {
      open: (oel.getAttribute && oel.getAttribute('data-module-open')) !== null
        && (oel.getAttribute && oel.getAttribute('data-module-open')) !== undefined,
      tag: oel.tagName,
      cls: String(oel.className || '').slice(0, 40),
    } : null;
  }
  return {
    button: {h: Math.round(box.height), w: Math.round(box.width)},
    cardH: Math.round(card.getBoundingClientRect().height),
    probes: {m20: at(-20), m14: at(-14), c: at(0),
             p14: at(14), p20: at(20)},
    openAtCenter,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  };
}"""


@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_mobile_hit_area_reaches_20px(stand, width, height):
    e2e = stand["e2e"]
    port = stand["port"]
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — нет браузера в окружении
            pytest.skip("chromium недоступен: %s" % str(exc)[:120])
        try:
            ctx = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2, is_mobile=True, has_touch=True)
            ctx.add_init_script(e2e.TMA_STUB)
            ctx.route("**/api/**", _handler(e2e))
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)[:200]))
            page.goto("http://127.0.0.1:%d/web/index.html#/modules" % port,
                      wait_until="load")
            page.wait_for_selector(
                'article[data-mod="mod_experience"]', timeout=20000)
            page.wait_for_timeout(700)
            probe = page.evaluate(PROBE_JS)
            ctx.close()
        finally:
            browser.close()

    assert "missing" not in probe, probe
    assert not errors, errors

    # F2: ±20 px от центра — та же кнопка (не подпись/не строка состояния).
    for key in ("m20", "m14", "c", "p14", "p20"):
        hit = probe["probes"][key]
        assert hit and hit.get("kind") == "tristate" and hit.get("id") == "on", (
            "%dpx: %s попал в %r вместо tri-state 'on'" % (width, key, hit))

    # «Открыть» не сломан и не перехватывается расширенной зоной.
    assert probe["openAtCenter"] and probe["openAtCenter"]["open"], (
        "%dpx: кнопка «Открыть» не получает свой центр: %r"
        % (width, probe["openAtCenter"]))

    # Layout не сломан: карточка держит прежнюю высоту, нет гориз. скролла.
    assert 131 <= probe["cardH"] <= 165, (
        "%dpx: высота карточки %s вне 132–164" % (width, probe["cardH"]))
    assert probe["scrollWidth"] <= probe["innerWidth"] + 1, (
        "%dpx: горизонтальный скролл %s > %s"
        % (width, probe["scrollWidth"], probe["innerWidth"]))
