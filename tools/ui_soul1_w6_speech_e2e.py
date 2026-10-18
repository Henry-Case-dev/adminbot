"""SOUL-1 / W6 — Playwright e2e «Речь и характер» (#/ai/speech).

Гоняет РЕАЛЬНЫЕ web/index.html + web/app.js + web/static/app.css; /api/* —
route-стабы: формы ответов берутся из `api-fixture.json`, сгенерированного
настоящим слоем `web/api/speech.py` (plans/features/soul-1/evidence/w6/
dump_api_fixture.py), а не выдуманы в тесте. Telegram SDK — route-mock
(прецедент ui_asap8_w2_shell_e2e).

Проверяет на 320/360/390/430/768/1024/1440 + landscape:
  * витрину разделов и вход «Речь и характер» внутри «Личности и стиля»;
  * отсутствие горизонтального overflow страницы и скролл длинных строк
    ВНУТРИ компонентов;
  * тач-цели ≥44px, паддинги ≥12px, одну колонку ≤599px;
  * один экран за раз + «Назад»; сохранность черновика и каретки при
    обновлении данных и при навигации;
  * реальные POST-вызовы разделов (сохранение характера/стиля/выражения,
    предпросмотр стиля, «Попробовать», «Все инструкции», Inspector,
    «Возможности бота»).

Запуск: .venv/Scripts/python.exe tools/ui_soul1_w6_speech_e2e.py
"""
import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (базовые /api-стабы)

EVIDENCE = REPO / "plans" / "features" / "soul-1" / "evidence" / "w6"
SHOTS = EVIDENCE / "shots"
FIXTURE = json.loads((EVIDENCE / "api-fixture.json").read_text(encoding="utf-8"))
PORT = 8815
BASE = "http://127.0.0.1:%d" % PORT

SDK_STUB = """
try { sessionStorage.setItem('adminbot.initData',
  'user=%7B%22id%22%3A5885953495%7D&hash=audit'); } catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  platform: 'android', version: '9.0', colorScheme: 'dark', themeParams: {},
  get viewportStableHeight() { return Math.max(0, (window.innerHeight || 800) - 56); },
  isExpanded: true, isFullscreen: false,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, close() {},
  setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
  requestFullscreen() {}, exitFullscreen() {},
  disableVerticalSwipes() {}, enableClosingConfirmation() {},
  onEvent() {}, offEvent() {},
  openLink() {}, openTelegramLink() {}, showAlert() {}, showConfirm() {},
  BackButton: { isVisible: false, show() {}, hide() {}, onClick() {}, offClick() {} },
  MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
  HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
} };
"""

PROBE = r"""
(() => {
  const root = document.querySelector('.speech-screen');
  const vw = window.innerWidth, vh = window.innerHeight;
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const rect = (el) => { const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height),
             x: Math.round(r.x), right: Math.round(r.right) }; };
  const tap = [];
  const small = [];
  // Чекбокс/радио — цель это его label (сам input — только маркер).
  const target = (el) => (el.tagName === 'INPUT'
      && (el.type === 'checkbox' || el.type === 'radio'))
    ? (el.closest('label') || el) : el;
  if (root) {
    root.querySelectorAll('button, select, input, textarea, summary, [role="tab"]')
      .forEach((el) => {
        const r = rect(target(el));
        if (r.w === 0 && r.h === 0) return;
        tap.push(Math.min(r.w, r.h));
        if (r.h < 44) small.push({ tag: el.tagName, t: strip(el.textContent).slice(0, 40),
                                   h: r.h, aria: el.getAttribute('aria-label') });
      });
  }
  const grid = document.querySelector('.speech-grid');
  const cols = grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0;
  const split = document.querySelector('.speech-split');
  const splitCols = split
    ? getComputedStyle(split).gridTemplateColumns.split(' ').length : 0;
  const pres = Array.from(document.querySelectorAll('.speech-pre, .speech-scrollable'));
  const preOverflow = pres.filter((p) => p.scrollWidth > p.clientWidth + 1).length;
  const head = document.querySelector('.speech-head');
  const pad = root ? getComputedStyle(root).paddingLeft : null;
  const sectionOpen = !!document.querySelector('.speech-section');
  const showcase = document.querySelectorAll('[data-speech-card]').length > 0;
  return {
    vw, vh,
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body ? document.body.scrollWidth : null,
    pageOverflow: document.documentElement.scrollWidth - vw,
    hasScreen: !!root, sectionOpen, showcase,
    minTap: tap.length ? Math.min.apply(null, tap) : null,
    tapCount: tap.length,
    smallTargets: small.slice(0, 8),
    gridCols: cols, splitCols,
    preCount: pres.length, preOverflow,
    headH: head ? rect(head).h : null,
    paddingLeft: pad,
    cards: Array.from(document.querySelectorAll('[data-speech-card]')).map((c) => ({
      id: c.getAttribute('data-speech-card'), ...rect(c) })),
    title: (document.querySelector('.speech-title') || {}).textContent || '',
    backVisible: !!Array.from(document.querySelectorAll('.speech-back'))
      .filter((b) => b.offsetParent !== null).length,
  };
})()
"""

METRICS = {
    "320": (320, 640), "360": (360, 780), "390": (390, 844), "430": (430, 932),
    "768": (768, 1024), "1024": (1024, 768), "1440": (1440, 900),
    "landscape": (667, 375),
}

SECTIONS = ("core", "style", "expression", "humor", "examples", "try",
            "learning", "all", "inspector", "capabilities")

failures: list = []
notes: list = []
posted: list = []
dialogs: list = []
INSPECTOR_STATE = {"calls": 0}


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


def make_api_handler():
    def _handler(route):
        req = route.request
        url = req.url.split("?")[0]
        method = req.method
        if "/api/memory/lessons/action" in url:
            posted.append(method + " " + url)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "status": "suspended"}))
            return
        if "/api/speech/" in url:
            name = url.rsplit("/api/speech/", 1)[1]
            if method == "POST":
                posted.append(method + " " + name)
                body = _post_body(name, req)
            else:
                body = _get_body(name)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(body, ensure_ascii=False))
            return
        body = M._stub_for(req.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body, ensure_ascii=False))
    return _handler


def _get_body(name):
    if name == "overview":
        return FIXTURE["overview"]
    if name == "inspector":
        # Две ветки Inspector проверяются подряд: сначала «в памяти только
        # предпросмотр», затем — со снимком хода (writer Direct L2), чтобы
        # различение «предпросмотр vs фактически отправлено» было видно.
        INSPECTOR_STATE["calls"] += 1
        if INSPECTOR_STATE["calls"] % 2 == 1:
            return FIXTURE["inspector"]
        return FIXTURE["inspector_with_run"]
    if name == "core":
        return FIXTURE["core"]
    if name == "style":
        return FIXTURE["style"]
    if name == "expression":
        return FIXTURE["expression"]
    if name == "humor":
        return FIXTURE["humor"]
    if name == "examples":
        return FIXTURE["examples"]
    if name == "learning":
        return FIXTURE["learning"]
    if name == "capabilities":
        return FIXTURE["capabilities"]
    if name == "inspector":
        return FIXTURE["inspector"]
    if name == "blocks":
        return FIXTURE["blocks"]
    if name.startswith("block/"):
        return FIXTURE["block_detail"]
    return {"ok": False, "unknown": name}


def _post_body(name, req):
    if name == "style":
        return {"ok": True, "result": {"applied": True, "revision": 2,
                                       "scope": "global"},
                "view": FIXTURE["style"]}
    if name == "style/preview":
        return FIXTURE["style_preview"]
    if name == "style/reset-chat":
        return {"ok": True, "view": FIXTURE["style"]}
    if name == "expression":
        return {"ok": True, "view": FIXTURE["expression"]}
    if name == "expression/reset-chat":
        return {"ok": True, "view": FIXTURE["expression"]}
    if name == "core/meta":
        return {"ok": True, "result": {"applied": True, "revision": 2}}
    if name == "try":
        return FIXTURE["try"]
    if name.endswith("/reset"):
        # Реальный ответ prompt_factory.plan_factory_reset, снятый настоящим
        # эндпоинтом (evidence/w6/dump_api_fixture.py): applies/changed +
        # current_chars/factory_chars + diff{added_lines,removed_lines}.
        # Рукописного стаба здесь нет — иначе форма ответа снова разойдётся с
        # рантаймом (review-w6 F3).
        plan = FIXTURE.get("factory_reset_plan")
        if not plan:
            fail("fixture", "factory_reset_plan отсутствует: перегенерируйте "
                            "plans/features/soul-1/evidence/w6/api-fixture.json")
            return {"ok": False, "reason": "fixture_missing"}
        return plan
    if name.endswith("/rollback"):
        return {"ok": True, "rolled_back_to": "deadbeef1234"}
    if name.startswith("block/"):
        return {"ok": True,
                "result": {"applied": True, "scope": "global",
                           "revision": "act:deadbeef1234",
                           "provenance": {"kind": "owner_edit"}}}
    return {"ok": True}


def make_handler(webroot):
    class _Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):  # noqa: N802
            p = path.split("?")[0]
            if p.startswith("/static/"):
                rel = "static/" + p[len("/static/"):]
            elif p.startswith("/web/"):
                rel = p[len("/web/"):]
            elif p in ("/", "", "/index.html"):
                rel = "index.html"
            else:
                rel = p.lstrip("/")
            return os.path.join(webroot, rel.replace("/", os.sep))

        def _json(self, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path.endswith("/static/vendor/telegram-web-app.js"):
                body = SDK_STUB.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/api/speech/"):
                self._json(_get_body(path.rsplit("/api/speech/", 1)[1]))
                return
            if path.startswith("/api/"):
                self._json(M._stub_for(self.path))
                return
            return super().do_GET()

        def do_POST(self):  # noqa: N802
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if path.startswith("/api/speech/"):
                posted.append("POST " + path.rsplit("/api/speech/", 1)[1])
                self._json(_post_body(path.rsplit("/api/speech/", 1)[1], None))
                return
            if path.startswith("/api/memory/lessons/action"):
                posted.append("POST " + path)
                self._json({"ok": True, "status": "suspended"})
                return
            self._json({"ok": True})

        def log_message(self, *args):  # тихо
            pass
    return _Handler


def serve(port, webroot):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(webroot))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def new_page(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430, has_touch=width <= 430)
    ctx.route("**/api/**", make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(status=200,
                                          content_type="application/javascript",
                                          body=SDK_STUB))
    page = ctx.new_page()
    page.set_default_timeout(15000)
    # D13 (§18I.4): уход с «грязной» страницы (в харнессе — конфиг/личность из
    # route-стабов) защищён confirm'ом владельца. Клик по «Открыть» и есть
    # намерение уйти — подтверждаем и записываем текст в отчёт.
    page.on("dialog", lambda d: (dialogs.append(d.message[:200]), d.accept()))
    return ctx, page


def open_screen(page, label, route="#/ai/speech"):
    page.goto(BASE + route, wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_selector(".speech-screen", state="visible")
    page.wait_for_timeout(700)


def snap(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / (name + ".png")
    page.screenshot(path=str(path))
    return str(path)


def check_viewport(page, label):
    probe = page.evaluate(PROBE)
    notes.append({"label": label, "probe": probe})
    if probe["pageOverflow"] > 1:
        fail(label, "горизонтальный overflow страницы: %s px"
             % probe["pageOverflow"])
    if not probe["hasScreen"]:
        fail(label, "экран «Речь и характер» не отрисован")
    if probe["minTap"] is not None and probe["minTap"] < 44:
        fail(label, "тач-цель < 44px: %s" % probe["smallTargets"])
    if probe["paddingLeft"] and int(probe["paddingLeft"].replace("px", "")) < 12:
        fail(label, "паддинг < 12px: %s" % probe["paddingLeft"])
    return probe


def section_key(label, viewport):
    return "%s_%s" % (label, viewport)


def toast_texts(page):
    """Все видимые тосты (до 3): сортировка по приоритету, не по времени."""
    return page.evaluate(
        "(() => Array.from(document.querySelectorAll('.toast, [class*=toast]'))"
        ".map((t) => t.textContent.replace(/\\s+/g,' ').trim()).filter((s) => s))()")


def open_section_menu(page, section):
    """P0A-UX §4-C4: второстепенные действия раздела — в ⋯-меню."""
    page.click("[data-speech-menu='%s']" % section)
    page.wait_for_selector(".speech-menu-panel", state="visible")
    page.wait_for_timeout(150)


def click_menu_item(page, text):
    page.locator(".speech-menu-panel .more-menu-item",
                 has_text=text).first.click()
    page.wait_for_timeout(200)


def unchecked_rule_count(page):
    return page.evaluate(
        "(() => Array.from(document.querySelectorAll('.speech-rule input[type=checkbox]'))"
        ".filter((c) => !c.checked).length)()")


def run_viewport(browser, viewport, shots, deep):
    width, height = METRICS[viewport]
    ctx, page = new_page(browser, width, height)
    try:
        open_screen(page, viewport)
        probe = check_viewport(page, viewport)
        width_cols = probe["gridCols"]
        # P0A-UX §4-C1 (осознанное изменение контракта витрины): 320px —
        # 1 колонка; 360–599px — ровно 2 (4 группы видны без простыни);
        # ≥600px — авто-сетка (≥2 колонок).
        if width < 360 and width_cols > 1:
            fail(viewport, "витрина в %d колонки при ширине %d"
                 % (width_cols, width))
        if 360 <= width <= 599 and width_cols != 2:
            fail(viewport, "витрина не в 2 колонки при ширине %d (%d колонки)"
                 % (width, width_cols))
        if width >= 600 and width_cols < 2:
            note = "витрина в 1 колонку при ширине %d (плотность, не ошибка)" % width
            notes.append({"label": viewport, "note": note})
        if shots:
            snap(page, "entry_%s" % viewport)
        # Вход внутрь «ИИ» → «Личность и стиль» → «Речь и характер».
        page.goto(BASE + "#/ai", wait_until="load")
        page.wait_for_selector("#/ai" and ".hub-card, .card", state="attached")
        page.wait_for_timeout(400)
        page.goto(BASE + "#/ai/persona", wait_until="load")
        page.wait_for_selector("[data-speech-entry]", state="visible")
        persona_probe = page.evaluate(
            "(() => ({ overflow: document.documentElement.scrollWidth - window.innerWidth,"
            " entryH: (document.querySelector('[data-speech-entry]') || {})"
            ".getBoundingClientRect ? Math.round(document.querySelector"
            "('[data-speech-entry]').getBoundingClientRect().height) : null }))()")
        if persona_probe["overflow"] > 1:
            fail(viewport, "горизонтальный overflow на «Личности» (вход в раздел): %s px"
                 % persona_probe["overflow"])
        if persona_probe["entryH"] and persona_probe["entryH"] < 44:
            fail(viewport, "кнопка входа < 44px: %s" % persona_probe["entryH"])
        if shots:
            snap(page, "persona_entry_%s" % viewport)
        page.click("[data-speech-entry]")
        page.wait_for_selector(".speech-screen", state="visible")
        page.wait_for_timeout(500)
        if page.evaluate("location.hash") != "#/ai/speech":
            fail(viewport, "карточка входа не привела на #/ai/speech")
        if not deep:
            return
        # Разделы: каждый открывается, «Назад» возвращает витрину.
        for section in SECTIONS:
            page.click("[data-speech-card='%s']" % section)
            page.wait_for_selector(".speech-section", state="visible")
            page.wait_for_timeout(450)
            probe = check_viewport(page, "%s/%s" % (viewport, section))
            if probe["sectionOpen"] and probe["showcase"]:
                fail(viewport, "%s: одновременно витрина и раздел" % section)
            if shots and section in ("core", "style", "try", "inspector",
                                     "all", "capabilities", "learning"):
                snap(page, "section_%s_%s" % (section, viewport))
            page.click(".speech-back")
            page.wait_for_selector(".speech-grid", state="visible")
            page.wait_for_timeout(250)
    finally:
        ctx.close()


def run_interactions(browser, viewport, shots):
    """Реальные действия: сохранение, предпросмотр, черновик/каретка."""
    INSPECTOR_STATE["calls"] = 0   # детерминизм: 1-й GET — предпросмотр, 2-й — ход
    width, height = METRICS[viewport]
    ctx, page = new_page(browser, width, height)
    try:
        open_screen(page, viewport)
        # ── Характер: правка + черновик переживает навигацию и обновление ──
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(400)
        editor = page.locator(".speech-section .speech-editor").first
        editor.click()
        editor.press("End")
        marker = "\nПроверка W6: правка из MiniApp."
        editor.type(marker, delay=5)
        value_before = editor.input_value()
        sel_before = page.evaluate(
            "(() => { const t = document.querySelector('.speech-section .speech-editor');"
            " return t.selectionStart; })()")
        # обновление данных из API не должно затирать черновик/каретку
        page.click(".speech-refresh")
        page.wait_for_timeout(900)
        value_after = page.evaluate(
            "document.querySelector('.speech-section .speech-editor').value")
        sel_after = page.evaluate(
            "(() => { const t = document.querySelector('.speech-section .speech-editor');"
            " return t.selectionStart; })()")
        if value_after != value_before:
            fail(viewport, "черновик потерян при обновлении данных")
        if sel_after != sel_before:
            fail(viewport, "каретка сброшена при обновлении (%s → %s)"
                 % (sel_before, sel_after))
        if "dirty" not in page.evaluate(
                "document.querySelector('.speech-section .speech-editor')"
                ".className"):
            fail(viewport, "редактор не помечает несохранённый черновик")
        # навигация «Назад» → витрина → снова раздел: черновик жив
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-section .speech-editor",
                               state="visible")
        page.wait_for_timeout(300)
        if page.evaluate("document.querySelector('.speech-section .speech-editor')"
                         ".value") != value_before:
            fail(viewport, "черновик потерян при навигации по разделам")
        # сохранение через API реестра
        page.click(".speech-section .btn-accent")
        page.wait_for_timeout(900)
        if not any(p.endswith("core.personality") for p in posted):
            fail(viewport, "сохранение характера не ушло в API (POST %s)"
                 % posted[-3:])
        if shots:
            snap(page, "core_saved_%s" % viewport)
        # diff и заводской предпросмотр (P0A-UX §4-C4: кнопки — в ⋯-меню;
        # два клика: план → подтверждение). Форма ответа — РЕАЛЬНАЯ
        # (FIXTURE["factory_reset_plan"]), поэтому «undefined» = провал
        # (review-w6 F3).
        open_section_menu(page, "core")
        click_menu_item(page, "Показать diff с заводским")
        page.wait_for_selector("[data-speech-diff]", state="visible")
        open_section_menu(page, "core")
        click_menu_item(page, "Вернуть заводской")
        page.wait_for_timeout(600)
        plan_row = (FIXTURE.get("factory_reset_plan") or {}).get("plan") or {}
        plan_expected = "было %s → станет %s зн." % (
            plan_row.get("current_chars"), plan_row.get("factory_chars"))
        plan_toasts = toast_texts(page)
        if any("undefined" in t for t in plan_toasts):
            fail(viewport, "заводской сброс: диалог показывает «undefined» (%s)"
                 % plan_toasts)
        if not any(plan_expected in t for t in plan_toasts):
            fail(viewport, "заводской сброс: в диалоге нет реальных чисел "
                           "«%s» → %s" % (plan_expected, plan_toasts))
        notes.append({"label": viewport + "/factory_plan", "toasts": plan_toasts,
                      "expected": plan_expected})
        if shots:
            snap(page, "factory_plan_%s" % viewport)
        # второй клик по той же кнопке = подтверждение (apply=true)
        open_section_menu(page, "core")
        click_menu_item(page, "Вернуть заводской")
        page.wait_for_timeout(900)
        if not any(p.endswith("/reset") for p in posted):
            fail(viewport, "подтверждение заводского сброса не ушло в API (%s)"
                 % posted[-3:])
        applied = toast_texts(page)
        if not any("возвращён" in t for t in applied):
            fail(viewport, "подтверждение заводского сброса не подтвердилось "
                           "тостом (%s)" % applied)
        notes.append({"label": viewport + "/factory_apply", "toasts": applied})

        # ── Стиль письма: черновик правил переживает обновление данных ──
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='style']")
        page.wait_for_selector(".speech-rule", state="visible")
        page.wait_for_timeout(300)
        rules_before = page.locator(".speech-rule").count()
        page.click(".speech-rule input[type=checkbox]")
        page.wait_for_timeout(200)
        page.click(".speech-refresh")
        page.wait_for_timeout(900)
        rules_after = page.locator(".speech-rule").count()
        unchecked = unchecked_rule_count(page)
        if rules_after != rules_before or unchecked == 0:
            fail(viewport, "черновик правил стиля потерян при обновлении данных")

        # ── review-w6 F2: редактор рендерится ИЗ ЧЕРНОВИКА ─────────────────
        # (а) toggle → вышел из раздела → вернулся: правка на месте и помечена.
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='style']")
        page.wait_for_selector(".speech-rule", state="visible")
        page.wait_for_timeout(400)
        if page.locator(".speech-rule").count() != rules_after:
            fail(viewport, "F2: список правил после возврата в раздел разошёлся "
                           "с черновиком")
        if unchecked_rule_count(page) != unchecked:
            fail(viewport, "F2: снятая галка не пережила выход из раздела "
                           "(снято %s → %s)" % (unchecked, unchecked_rule_count(page)))
        if not page.locator("[data-speech-style-dirty]").count():
            fail(viewport, "F2: черновик правил не помечен как несохранённый")
        if "черновик" not in page.inner_text(".speech-section"):
            fail(viewport, "F2: в разделе нет пометки «черновик»")
        if shots:
            snap(page, "style_draft_%s" % viewport)
        notes.append({"label": viewport + "/style_f2_draft",
                      "rules": rules_after, "unchecked": unchecked,
                      "dirty_badge": True})

        # (б) добавление шаблона меняет ВИДИМЫЙ список сразу (без Save)
        page.locator(".speech-section button.btn-ghost",
                     has_text="Без точек на конце").first.click()
        page.wait_for_timeout(400)
        after_add = page.locator(".speech-rule").count()
        if after_add != rules_after + 1:
            fail(viewport, "F2: «+ Без точек на конце» не изменил список "
                           "(%d → %d)" % (rules_after, after_add))
        if ("%d правил" % after_add) not in page.inner_text(
                ".speech-section .speech-row"):
            fail(viewport, "F2: счётчик правил не следует за черновиком")
        # P0A-UX §3 (TJ-5): человеческий заголовок виден сразу, сырой id —
        # в свёрнутых «Технических параметрах правила» (раскрываем).
        added_rule = page.locator(".speech-rule").last
        if "Точка в конце сообщения" not in added_rule.inner_text():
            fail(viewport, "TJ-5: у правила нет человеческого заголовка")
        added_rule.locator("details summary").first.click()
        page.wait_for_timeout(200)
        if "trailing_period.hard.strip" not in added_rule.inner_text():
            fail(viewport, "TJ-5: сырой id правила недоступен даже в деталях")
        if shots:
            snap(page, "style_added_%s" % viewport)

        # (в) действия по индексу остаются валидными после смены длины черновика
        last_rule = page.locator(".speech-rule").nth(after_add - 1)
        last_box = last_rule.locator("input[type=checkbox]")
        state_before = last_box.is_checked()
        last_box.click()
        page.wait_for_timeout(300)
        if last_box.is_checked() == state_before:
            fail(viewport, "F2: toggle по индексу не сработал после смены длины "
                           "черновика")
        last_rule.locator("select").select_option("chat")
        page.wait_for_timeout(300)
        if last_rule.locator("select").input_value() != "chat":
            fail(viewport, "F2: смена области правила по индексу не применилась")

        # (г) «Убрать» меняет список сразу, действие по индексу после удаления
        page.locator(".speech-rule").first.locator("button.btn-ghost").click()
        page.wait_for_timeout(300)
        after_remove = page.locator(".speech-rule").count()
        if after_remove != after_add - 1:
            fail(viewport, "F2: «Убрать» не изменил список (%d → %d)"
                 % (after_add, after_remove))
        if ("%d правил" % after_remove) not in page.inner_text(
                ".speech-section .speech-row"):
            fail(viewport, "F2: счётчик правил не уменьшился после «Убрать»")
        left_box = page.locator(".speech-rule").first.locator("input[type=checkbox]")
        left_before = left_box.is_checked()
        left_box.click()
        page.wait_for_timeout(300)
        if left_box.is_checked() == left_before:
            fail(viewport, "F2: toggle по индексу не сработал после удаления")

        # (д) мягкие привычки: add/remove видны сразу
        page.fill("textarea[aria-label='Мягкая привычка']",
                  "Пиши короче, без канцелярита.")
        soft_before = page.locator(".speech-soft").count()
        page.locator(".speech-section button.btn-ghost",
                     has_text="Добавить привычку").first.click()
        page.wait_for_timeout(300)
        if page.locator(".speech-soft").count() != soft_before + 1:
            fail(viewport, "F2: «Добавить привычку» не изменил список")
        page.locator(".speech-soft").last.locator("button.btn-ghost").click()
        page.wait_for_timeout(300)
        if page.locator(".speech-soft").count() != soft_before:
            fail(viewport, "F2: «Убрать» у привычки не изменил список")
        notes.append({"label": viewport + "/style_f2_mutations",
                      "rules": [rules_after, after_add, after_remove],
                      "soft": [soft_before, soft_before + 1, soft_before]})

        open_section_menu(page, "style")
        click_menu_item(page, "Предпросмотр на примерах")
        page.wait_for_selector("[data-speech-style-preview]", state="visible")
        rows = page.locator("[data-speech-style-preview] .speech-preview-row").count()
        if rows < 3:
            fail(viewport, "предпросмотр стиля показал %d примеров" % rows)
        if shots:
            snap(page, "style_preview_%s" % viewport)
        page.click(".speech-section .btn-accent")
        page.wait_for_timeout(800)
        if not any(p == "POST style" for p in posted):
            fail(viewport, "сохранение стиля не ушло в API")

        # ── Выражение: контролы + предпросмотр слоя ──
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='expression']")
        page.wait_for_selector("[data-speech-expression-preview]",
                               state="visible")
        page.select_option(".speech-section select[aria-label='Остроумие']",
                           "high")
        preview = page.inner_text("[data-speech-expression-preview]")
        if "Остроумие" not in preview:
            fail(viewport, "предпросмотр выражения не обновился")
        page.click(".speech-section .btn-accent")
        page.wait_for_timeout(800)
        if not any(p == "POST expression" for p in posted):
            fail(viewport, "сохранение выражения не ушло в API")
        if shots:
            snap(page, "expression_%s" % viewport)

        # ── Попробовать ──
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='try']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.fill("textarea[aria-label='Сообщение для теста']",
                  "Проверь «цитату», версию 1.2.3 и https://example.org/a")
        page.click(".speech-section .btn-accent")
        page.wait_for_selector("[data-speech-try-cost]", state="visible")
        if not any(p == "POST try" for p in posted):
            fail(viewport, "«Попробовать» не вызвал API")
        if shots:
            snap(page, "try_%s" % viewport)

        # ── Все инструкции: поиск + карточка блока + сохранение ──
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='all']")
        page.wait_for_selector(".speech-block-row", state="visible")
        total = page.locator(".speech-block-row").count()
        page.fill("input[aria-label='Поиск по блокам']", "direct")
        page.wait_for_timeout(300)
        filtered = page.locator(".speech-block-row").count()
        if filtered >= total or filtered == 0:
            fail(viewport, "поиск по блокам не фильтрует (%d → %d)"
                 % (total, filtered))
        page.locator(".speech-block-row").first.click()
        page.wait_for_selector("[data-speech-block-detail]", state="visible")
        page.click("[data-speech-block-detail] .btn-accent")
        page.wait_for_timeout(900)
        if not any(p.startswith("POST block/") for p in posted):
            fail(viewport, "сохранение блока не ушло в API")
        page.click("[data-speech-block-detail] .btn-ghost:text('Заводской вариант')")
        page.wait_for_selector("[data-speech-factory]", state="visible")
        # F3: карточка блока читает ту же реальную форму ответа
        detail_plan = (FIXTURE["block_detail"].get("factory_plan") or {})
        detail_expected = "было %s → станет %s зн." % (
            detail_plan.get("current_chars"), detail_plan.get("factory_chars"))
        detail_text = page.inner_text("[data-speech-factory-plan]")
        if "undefined" in detail_text:
            fail(viewport, "F3: карточка блока показывает «undefined» (%s)"
                 % detail_text)
        if detail_expected not in detail_text:
            fail(viewport, "F3: в карточке блока нет реальных чисел «%s» → «%s»"
                 % (detail_expected, detail_text))
        notes.append({"label": viewport + "/block_factory_plan",
                      "text": detail_text, "expected": detail_expected})
        if shots:
            snap(page, "all_block_%s" % viewport)

        # ── Inspector ──
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='inspector']")
        page.wait_for_selector("[data-speech-preview-payload]", state="visible")
        status = page.inner_text(".speech-head")
        payload = page.inner_text("[data-speech-preview-payload]")
        if len(payload) < 200:
            fail(viewport, "payload предпросмотра пуст")
        # Ветка 1: в памяти процесса только предпросмотр — так и написано.
        if not FIXTURE["inspector"].get("last_run_present"):
            if "только предпросмотр" not in page.inner_text(".speech-section"):
                fail(viewport, "Inspector: нет пометки «только предпросмотр»")
            if page.locator("[data-speech-sent-system]").count():
                fail(viewport, "Inspector выдал предпросмотр за снимок хода")
        # вторая ветка: снимок хода (маскированный) + отличие от предпросмотра
        page.click(".speech-refresh")
        page.wait_for_timeout(1000)
        if page.locator("[data-speech-sent-system]").count():
            sent_payload = page.inner_text("[data-speech-sent-system]")
            if len(sent_payload) < 200:
                fail(viewport, "payload снимка хода пуст")
            expected = (FIXTURE.get("inspector_with_run", {}).get("sent") or {})
            expected_system = str(expected.get("system_masked") or "")
            if expected_system and expected_system[:200] not in sent_payload:
                fail(viewport, "UI показывает НЕ маскированный payload снимка")
            if "маскировка" not in page.inner_text(".speech-section"):
                fail(viewport, "нет пометки о маскировке в Inspector")
            # F1: снимок РЕАЛЬНОГО хода (run_id=uuid) доходит до витрины
            section_text = page.inner_text(".speech-section")
            if "есть снимок реального хода" not in section_text:
                fail(viewport, "Inspector: нет пометки «есть снимок реального хода»")
            expected_run = str(expected.get("run_id") or "")
            if expected_run and expected_run not in section_text:
                fail(viewport, "Inspector не показал run_id снимка хода (%s)"
                     % expected_run)
            if shots:
                snap(page, "inspector_sent_%s" % viewport)
        else:
            fail(viewport, "Inspector: снимок хода не показан")

        notes.append({"label": viewport + "/inspector",
                      "sent_branch": bool(page.locator(
                          "[data-speech-sent-system]").count()),
                      "head": status[:120]})
        if shots:
            snap(page, "inspector_%s" % viewport)

        # ── Возможности бота ──
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='capabilities']")
        page.wait_for_selector(".speech-cap-row", state="visible")
        caps = page.locator(".speech-cap-row").count()
        if caps < 5:
            fail(viewport, "список возможностей короткий: %d" % caps)
        if shots:
            snap(page, "capabilities_%s" % viewport)
        _ = status
    finally:
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--serve-only", action="store_true",
                    help="только поднять демо-сервер (для живой визуальной "
                         "проверки в реальном браузере) и ждать")
    args = ap.parse_args()
    shots = not args.no_shots
    serve(PORT, str(REPO / "web"))
    if args.serve_only:
        print("demo server: %s/web/#/ai/speech (Ctrl+C — стоп)" % BASE)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            for viewport in METRICS:
                if args.only and viewport != args.only:
                    continue
                print("== viewport", viewport)
                run_viewport(browser, viewport, shots=shots, deep=True)
            print("== interactions")
            run_interactions(browser, "390", shots=shots)
            run_interactions(browser, "1440", shots=shots)

    report = {
        "viewports": {k: {"width": v[0], "height": v[1]}
                      for k, v in METRICS.items()},
        "failures": failures,
        "post_calls": posted,
        "notes": [n for n in notes if "probe" not in n],
        "dialogs": dialogs,
        "probes": [{"label": n["label"], "probe": {
            k: v for k, v in n["probe"].items()
            if k in ("vw", "vh", "scrollWidth", "pageOverflow", "minTap",
                     "gridCols", "splitCols", "preCount", "preOverflow",
                     "headH", "paddingLeft", "tapCount")}}
            for n in notes if "probe" in n],
        "shots": sorted(str(p.name) for p in SHOTS.glob("*.png")) if shots else [],
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "ui-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n== ИТОГ: failures=%d, POST=%d, shots=%d"
          % (len(failures), len(posted), len(report["shots"])))
    for row in failures:
        print("  -", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
