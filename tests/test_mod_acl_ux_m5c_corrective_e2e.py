"""MOD-ACL-UX-01 corrective — поведенческий гейт (F2/F3, r2).

Три вещи, которые нельзя доказать текстом CSS:

1. hit-area: реальный 44-px контрол — `document.elementFromPoint` на ±20 px
   от центра пилюли обязан возвращать ТУ ЖЕ кнопку (390/320);
2. неинтерактивный текст: тап по подписи контрола и по строке состояния НЕ
   должен приводить к `POST /api/config` (раньше псевдоэлемент ±20 px накрывал
   текст и выключал обучение); положительный контроль — тап по самой пилюле
   POST делает;
3. scope (F1): total журнала — только того же scope, что и страница: вход в
   `#/modules/experience` без чата даёт глобальный total, после
   `setActiveChat` pipeline перезапрашивается с `chat_id`, а total меняется;
   чужой (глобальный) total в чате не показывается.

Стенд — существующий `tools/ui_mod_acl_m4_catalog_e2e.py`; `/api/*` стабятся
здесь же, production не используется, записей в БД нет (POST ловится и
заменяется ответом). Без Playwright/Chromium тест честно пропускается.

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

CHAT = -1004482340693
GLOBAL_TOTAL = 4899
CHAT_TOTAL = 544
GLOBAL_PAGE = 100
CHAT_PAGE = 3


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


class Harness:
    """Маршрутизация стабов + журнал запросов (URL и POST-тела)."""

    def __init__(self, e2e):
        self.e2e = e2e
        self.pipeline_urls = []
        self.posts = []

    def handler(self, route, request):
        e2e = self.e2e
        url = request.url
        path = url.split("?")[0]
        query = url.split("?", 1)[1] if "?" in url else ""
        if request.method == "POST":
            body = ""
            try:
                body = request.post_data_buffer.decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = ""
            self.posts.append({"url": path, "body": body})
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"saved": [], "updated_at": "ts"}))
        if path.endswith("/api/config"):
            chat = bool(request.headers.get("x-chat-id"))
            payload = e2e.CONFIG_CHAT if chat else e2e.CONFIG_GLOBAL
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(payload))
        if path.endswith("/api/memory/lessons"):
            chat = "chat_id=" in query
            count = CHAT_PAGE if chat else GLOBAL_PAGE
            rows = [{"lesson_id": "L%d" % i, "version": 1,
                     "created_at": 1795760000 - i, "type": "tool_usage",
                     "status": "active", "scope": "chat" if chat else "global",
                     "scope_chat_id": CHAT if chat else None}
                    for i in range(count if count <= 5 else 5)]
            return route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"enabled": True, "state": "implemented",
                                 "count": count, "lessons": rows}))
        if path.endswith("/api/experience/pipeline"):
            self.pipeline_urls.append(url)
            chat = "chat_id=" in query
            counters = ({"active": 1, "suspended": 464, "superseded": 79}
                        if chat else
                        {"active": 4000, "suspended": 800, "superseded": 99})
            return route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"enabled": True, "state": "working",
                                 "counters": {"lessons": counters}}))
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(e2e._stub_for(url)))


def _open(stand, width, height, harness, mobile=True):
    e2e = stand["e2e"]
    ctx = stand["_browser"].new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2 if mobile else 1,
        is_mobile=bool(mobile), has_touch=bool(mobile))
    ctx.add_init_script(e2e.TMA_STUB)
    ctx.route("**/api/**", harness.handler)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)[:200]))
    page.goto("http://127.0.0.1:%d/web/index.html#/modules" % stand["port"],
              wait_until="load")
    page.wait_for_selector('article[data-mod="mod_experience"]', timeout=20000)
    page.wait_for_timeout(500)
    return ctx, page, errors


@pytest.fixture(scope="module")
def browser(stand):
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — нет браузера в окружении
            pytest.skip("chromium недоступен: %s" % str(exc)[:120])
        stand["_browser"] = b
        try:
            yield b
        finally:
            b.close()


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
    return {kind: 'other', tag: el.tagName,
            cls: String(el.className || '').slice(0, 40)};
  };
  const label = card.querySelector('.module-control-row__label');
  const state = card.querySelector('.module-state');
  const openBtn = card.querySelector('[data-module-open]');
  const center = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {x: r.left + r.width / 2, y: r.top + r.height / 2,
            w: Math.round(r.width), h: Math.round(r.height)};
  };
  let openCenter = null;
  if (openBtn) {
    const ob = center(openBtn);
    const oel = document.elementFromPoint(ob.x, ob.y);
    openCenter = oel
      ? ((oel.getAttribute && oel.getAttribute('data-module-open') !== null
          && oel.getAttribute('data-module-open') !== undefined) ? 'OPEN' : 'other')
      : null;
  }
  return {
    button: {h: Math.round(box.height), w: Math.round(box.width)},
    cardH: Math.round(card.getBoundingClientRect().height),
    probes: {m20: at(-20), m14: at(-14), c: at(0),
             p14: at(14), p20: at(20)},
    label: center(label),
    state: center(state),
    pill: {x: cx, y: cy},
    openCenter,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  };
}"""


# Контракт дизайна (design-m3 D7 / Visual Preservation Map): карточка
# каталога — natural height 132–164 px. Гейт держит именно контракт.
CARD_MIN_H = 131
CARD_MAX_H = 164


@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_mobile_hit_area_reaches_20px(stand, browser, width, height):
    harness = Harness(stand["e2e"])
    ctx, page, errors = _open(stand, width, height, harness)
    try:
        probe = page.evaluate(PROBE_JS)
    finally:
        ctx.close()
    assert "missing" not in probe, probe
    assert not errors, errors

    assert probe["button"]["h"] >= 44, (
        "%dpx: высота кнопки %s < 44" % (width, probe["button"]["h"]))
    for key in ("m20", "m14", "c", "p14", "p20"):
        hit = probe["probes"][key]
        assert hit and hit.get("kind") == "tristate" and hit.get("id") == "on", (
            "%dpx: %s попал в %r вместо tri-state 'on'" % (width, key, hit))
    assert probe["openCenter"] == "OPEN", (
        "%dpx: «Открыть» не получает свой центр: %r"
        % (width, probe["openCenter"]))
    assert CARD_MIN_H <= probe["cardH"] <= CARD_MAX_H, (
        "%dpx: высота карточки %s вне %d–%d"
        % (width, probe["cardH"], CARD_MIN_H, CARD_MAX_H))
    assert probe["scrollWidth"] <= probe["innerWidth"] + 1, (
        "%dpx: горизонтальный скролл %s > %s"
        % (width, probe["scrollWidth"], probe["innerWidth"]))


@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_non_interactive_text_does_not_write(stand, browser, width, height):
    harness = Harness(stand["e2e"])
    ctx, page, errors = _open(stand, width, height, harness)
    try:
        probe = page.evaluate(PROBE_JS)
        assert "missing" not in probe, probe

        # Положительный контроль: тап по пилюле — это запись настройки.
        page.mouse.click(probe["pill"]["x"], probe["pill"]["y"])
        page.wait_for_timeout(600)
        assert len(harness.posts) >= 1, (
            "%dpx: тап по пилюле не отправил POST — контроль неинформативен"
            % width)

        # Тап по подписи контрола: не должен менять настройку.
        harness.posts.clear()
        page.mouse.click(probe["label"]["x"], probe["label"]["y"])
        page.wait_for_timeout(700)
        assert harness.posts == [], (
            "%dpx: тап по подписи отправил POST: %r"
            % (width, harness.posts))

        # Тап по строке состояния: не должен менять настройку.
        harness.posts.clear()
        page.mouse.click(probe["state"]["x"], probe["state"]["y"])
        page.wait_for_timeout(700)
        assert harness.posts == [], (
            "%dpx: тап по строке состояния отправил POST: %r"
            % (width, harness.posts))
    finally:
        ctx.close()
    assert not errors, errors


def test_journal_total_follows_scope(stand, browser):
    """F1: total журнала — только того же scope, что и страница.

    Стенд стартует в чатовом scope (стаб `/api/access/me` без global-флага),
    поэтому сценарий: чат → «Весь бот» (глобальный снимок) → снова чат.
    До фикса снимок не сбрасывался и глобальный total выдавался за журнал
    чата (и наоборот) — ровно дефект r2.
    """
    harness = Harness(stand["e2e"])
    e2e = stand["e2e"]
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(e2e.TMA_STUB)
    ctx.route("**/api/**", harness.handler)
    page = ctx.new_page()
    page.goto(
        "http://127.0.0.1:%d/web/index.html#/modules/experience" % stand["port"],
        wait_until="load")
    page.wait_for_selector('[data-overview-history-now]', timeout=20000)
    page.wait_for_timeout(2500)

    def counter_text():
        return page.evaluate(
            "() => ((document.querySelector('[data-overview-history-count]')"
            " || {}).innerText || '')")

    # 1) Чатовый scope (стартовый на стенде): total чата.
    chat_text = counter_text()
    assert "всего в журнале: %d" % CHAT_TOTAL in chat_text, (
        "chat scope: ожидался total %d, получено %r"
        % (CHAT_TOTAL, chat_text))

    # 2) Переход в «Весь бот»: pipeline обязан перезапроситься БЕЗ chat_id,
    #    а чатовый total — исчезнуть.
    harness.pipeline_urls.clear()
    page.evaluate("() => window.__adminbotVm.setActiveChat(null)")
    page.wait_for_timeout(3500)
    global_text = counter_text()
    assert any("chat_id=" not in u for u in harness.pipeline_urls), (
        "глобальный scope: pipeline не перезапрошен без chat_id: %r"
        % (harness.pipeline_urls,))
    assert "всего в журнале: %d" % GLOBAL_TOTAL in global_text, (
        "global scope: ожидался total %d, получено %r"
        % (GLOBAL_TOTAL, global_text))
    assert "всего в журнале: %d" % CHAT_TOTAL not in global_text, (
        "global scope показывает чатовый total: %r" % global_text)

    # 3) Возврат в чат: снова 544, глобальный total не показывается.
    harness.pipeline_urls.clear()
    page.evaluate("(chat) => window.__adminbotVm.setActiveChat(chat)", CHAT)
    page.wait_for_timeout(3500)
    chat_text2 = counter_text()
    assert any("chat_id=%d" % CHAT in u for u in harness.pipeline_urls), (
        "после смены чата pipeline не перезапрошен с chat_id: %r"
        % (harness.pipeline_urls,))
    assert "всего в журнале: %d" % CHAT_TOTAL in chat_text2, (
        "chat scope: ожидался total %d, получено %r"
        % (CHAT_TOTAL, chat_text2))
    assert "всего в журнале: %d" % GLOBAL_TOTAL not in chat_text2, (
        "chat scope показывает чужой глобальный total: %r" % chat_text2)
    ctx.close()
