# -*- coding: utf-8 -*-
"""P0 Vision — UI-контракт секции Vision: D10–D12 + §4 (Android).

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(route-стабы `/api/*` в Playwright, Telegram SDK — route-mock; прецедент
`tests/ui_p0a_ux_speech_compact_e2e.py`, `tools/ui_soul1_w6_speech_e2e.py`).

Сценарии (карта P0V-UI-*, источник §4 директивы):

  A. `#/ai/llm` — секция Vision («LLM Провайдеры»):
     * P0V-UI-NATIVE (D10): артефакта `function () { [native code] }` нет ни
       до загрузки state, ни после, ни после пробы (источник — computed, без
       CSS/скрипт-маскировки);
     * P0V-UI-DISPLAY (D12): факты ФАКТИЧЕСКОГО подключения из
       `GET /api/vision/state` — провайдер, модель, тип подключения, результат
       проверки (+R17-safe `detail`); после ответа пробы обновляются;
     * P0V-UI-REASONS (D11): тост/inline-статус — понятная причина для всех
       классов (авторизация/лимит/модальность/таймаут/5xx/пустой ответ/конфиг/
       нет модели/плохое изображение); внутренние коды (`vision_unavailable`,
       `http_401`, `image_modality_unsupported`, …) наружу не печатаются;
     * P0V-UI-SECRETS: значение ключа не попадает в DOM (только маска/last4),
       поле ввода не засеяно секретом.
  B. `#/modules/vision/models` — карточка модуля: те же факты; раскрытые
     настройки — та же компоновка; статус-бейдж не рвёт карточку.
  C. P0V-UI-OVERFLOW: 320/360/390/430 portrait + 640×360/844×390 landscape +
     крупный системный шрифт Android (root 20/24px, Telegram «Размер текста»):
     ни `documentElement`, ни `main.scroll-area` не имеют горизонтального
     переполнения; элементы формы внутри блока; подпись и поле не
     пересекаются; действия достижимы (right ≤ viewport).

Запуск:
  .venv/Scripts/python.exe tools/ui_vision_ui_e2e.py
  .venv/Scripts/python.exe tools/ui_vision_ui_e2e.py --shots <dir> --json <path>
  .venv/Scripts/python.exe tools/ui_vision_ui_e2e.py --serve-only --port 8874
    (стенд с теми же API-стабами — для реальной визуальной проверки Browser Use)

TEST-LIFECYCLE: CONTRACT owner=P0V-UI-NATIVE/DISPLAY/REASONS/SECRETS/OVERFLOW
(§4 директивы плюс D10–D12 recon).
"""
import argparse
import copy
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import ui_round1025_matrix as M  # noqa: E402  (базовые /api-стабы)

PORT = 8874
BASE = "http://127.0.0.1:%d" % PORT

# R17: секрет-значение, которое НЕ должно появиться в DOM (в ответах только
# маска {configured,last4}, как в реальном /api/config).
SECRET_LAST4 = "9f3c"
SECRET_SENTINEL = "vision-secret-should-never-render"

MODEL = "google/gemma-4-31b-it:free"
PROVIDER = "openrouter.ai"
API_TYPE = "openai_compatible"

# ── управляемые ответы стабов ───────────────────────────────────────────────
STATE = {}
PROBE = {}


def _vision_state(**over):
    """`runtime_snapshot`-контракт (services/mca_vision.runtime_snapshot)."""
    st = {
        "requested": True,
        "effective_enabled": False,
        "reason": "vision_unavailable",
        "visible_reason": "Провайдер временно недоступен (ошибка сервера)",
        "source": "dedicated",
        "model": MODEL,
        "base_url": "https://openrouter.ai/api/v1",
        "api_type": API_TYPE,
        "provider": PROVIDER,
        "capability": "unavailable",
        "detail": "http_5xx",
        "config_revision": "rev-p0v-ui",
        "checked_at": 1777000000.0,
        "stages": [],
        "process": "vision.media",
        "process_version": "1",
        "queue": {"queued": 0, "running": 0},
        "last": None,
    }
    st.update(over)
    return st


def _probe(**over):
    """Ответ POST /api/vision/test (routes.post_vision_test).

    `state` — свежий `runtime_snapshot` после пробы: тот же вердикт
    (capability/reason/detail/visible_reason), иначе UI показал бы факты от
    прежней конфигурации."""
    st_over = {k: v for k, v in over.items()
               if k in ("capability", "reason", "detail", "visible_reason")}
    st_over["effective_enabled"] = bool(over.get("ok"))
    st = _vision_state(**st_over)
    p = {
        "ok": False,
        "capability": "unavailable",
        "image_input": False,
        "status_code": None,
        "latency_ms": None,
        "model": MODEL,
        "reason": "vision_unavailable",
        "detail": "http_5xx",
        "visible_reason": "Провайдер временно недоступен (ошибка сервера)",
        "provider": PROVIDER,
        "api_type": API_TYPE,
        "source": "dedicated",
        "state": st,
    }
    p.update(over)
    p["state"] = st
    return p


def _config_stub():
    """Реальный /api/config из каталога + значения Vision (без секретов)."""
    data = copy.deepcopy(M.CONFIG_STUB)
    for it in data.get("items", []):
        key = it.get("key")
        if key == "models.vision_api_base_url":
            it["value"] = "https://openrouter.ai/api/v1"
        elif key == "models.vision_api_type":
            it["value"] = API_TYPE
        elif key == "models.vision_model":
            it["value"] = MODEL
        elif key == "keys.vision_api_key":
            it["value"] = {"configured": True, "last4": SECRET_LAST4}
            it["secret"] = True
    data.setdefault("updated_at", None)
    return data


CONFIG_STUB = _config_stub()


def make_api_handler():
    """Стабы: Vision-эндпоинты управляемые, остальное — матрица."""

    def _handler(route):
        req = route.request
        url = req.url.split("?")[0]
        method = req.method
        if url.endswith("/api/vision/state"):
            if STATE is None:
                route.fulfill(status=200, content_type="application/json",
                              body="null")
                return
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(STATE, ensure_ascii=False))
            return
        if url.endswith("/api/vision/test") and method == "POST":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(PROBE, ensure_ascii=False))
            return
        if url.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(CONFIG_STUB, ensure_ascii=False))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url), ensure_ascii=False))
    return _handler


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


def _api_stub_response(path, method):
    """Ответ API-стаба для стенда (--serve-only): те же данные, что в
    Playwright-маршрутах; None → это не API-путь."""
    url = path.split("?")[0]
    if not url.startswith("/api/"):
        return None
    if url.endswith("/api/vision/state"):
        if STATE is None:
            return 200, "null"
        return 200, json.dumps(STATE, ensure_ascii=False)
    if url.endswith("/api/vision/test") and method == "POST":
        return 200, json.dumps(PROBE, ensure_ascii=False)
    if url.endswith("/api/config"):
        return 200, json.dumps(CONFIG_STUB, ensure_ascii=False)
    return 200, json.dumps(M._stub_for(url), ensure_ascii=False)


def serve_static(port, webroot, api_stubs=False):
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

        def _stub(self):
            res = _api_stub_response(self.path, self.command)
            if res is None:
                return False
            status, body = res
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True

        def do_GET(self):  # noqa: N802
            if api_stubs and self._stub():
                return
            super().do_GET()

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if api_stubs and self._stub():
                return
            self.send_error(404, "File not found")

        def log_message(self, *args):  # тихо
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


PROBE_JS = r"""
(() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const de = document.documentElement;
  const main = document.querySelector('main.scroll-area')
    || document.querySelector('main');
  const rr = (el) => {
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { x: Math.round(b.x), right: Math.round(b.right),
             top: Math.round(b.top), bottom: Math.round(b.bottom),
             w: Math.round(b.width), h: Math.round(b.height) };
  };
  // Пересечение прямоугольников (только по-настоящему): в стек-компоновке
  // подпись НАД полем пересечения нет (bottom подписи <= top поля).
  const inter = (a, b) => {
    if (!a || !b) return 0;
    const w = Math.min(a.right, b.right) - Math.max(a.x, b.x);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return (w > 0 && h > 0) ? Math.round(Math.min(w, h)) : 0;
  };
  const block = document.querySelector('[data-block="vision"]');
  const rows = Array.from(block ? block.querySelectorAll('.prov-row') : []);
  const rowIssues = [];
  let layout = null;
  if (rows.length) {
    const first = rows[0];
    const fl = rr(first.querySelector('.prov-label'));
    const fb = rr(first.querySelector('.flex-1'));
    layout = (fl && fb && fl.bottom <= fb.top + 1) ? 'stack' : 'row';
    rows.forEach((row, i) => {
      const rowR = rr(row);
      const lr = rr(row.querySelector('.prov-label'));
      const br = rr(row.querySelector('.flex-1'));
      if (inter(lr, br) > 0) {
        rowIssues.push('label/body overlap#' + i + '=' + inter(lr, br));
      }
      if (rowR && rowR.right > window.innerWidth + 1) {
        rowIssues.push('row#' + i + ' right ' + rowR.right);
      }
      if (br) {
        Array.from(row.querySelectorAll('input, .secret-field, .secret-field__row'))
          .forEach((el) => {
            const ir = rr(el);
            if (ir && ir.right > br.right + 1) {
              rowIssues.push('inner#' + i + ' right ' + ir.right
                + ' > body ' + br.right);
            }
          });
      }
    });
  }
  const controls = Array.from(block
    ? block.querySelectorAll('button, input, select, textarea')
    : []).filter((el) => {
      const b = el.getBoundingClientRect();
      return b.width > 0 || b.height > 0;
    });
  const controlIssues = [];
  const controlRects = controls.map((el) => {
    const b = el.getBoundingClientRect();
    const t = strip(el.textContent).slice(0, 40)
      || el.getAttribute('placeholder') || el.type || el.tagName;
    if (b.right > window.innerWidth + 1) {
      controlIssues.push(t + ' right ' + Math.round(b.right));
    }
    if (b.left < -1) controlIssues.push(t + ' left ' + Math.round(b.left));
    return { t: t, w: Math.round(b.width), h: Math.round(b.height),
             right: Math.round(b.right) };
  });
  const eff = document.querySelector('[data-vision-effective-line]');
  const factsRoot = document.querySelector('[data-vision-facts]');
  const facts = {};
  if (factsRoot) {
    factsRoot.querySelectorAll('[data-vision-fact]').forEach((row) => {
      const l = row.querySelector('.conn-fact-label');
      const v = row.querySelector('.conn-fact-value');
      facts[row.getAttribute('data-vision-fact')] =
        (l ? strip(l.textContent) + ' ' : '') + (v ? strip(v.textContent) : '');
    });
  }
  const status = block ? block.querySelector('.prov-test-status') : null;
  const toastTexts = Array.from(
    document.querySelectorAll('.toast-wrap .toast .toast-text'))
    .map((el) => strip(el.textContent));
  const bodyText = strip(document.body.innerText);
  return {
    innerWidth: window.innerWidth,
    docScrollWidth: de.scrollWidth,
    mainScrollWidth: main ? main.scrollWidth : null,
    mainClientWidth: main ? main.clientWidth : null,
    overflow: de.scrollWidth > window.innerWidth + 1,
    mainOverflow: main ? (main.scrollWidth > main.clientWidth + 1) : false,
    nativeText: bodyText.indexOf('[native code]') >= 0,
    block: rr(block),
    layout: layout,
    rows: rows.length,
    rowIssues: rowIssues,
    controls: controlRects,
    controlIssues: controlIssues,
    effLine: eff ? strip(eff.textContent) : null,
    factsPresent: !!factsRoot,
    facts: facts,
    statusText: status ? strip(status.textContent) : null,
    toastTexts: toastTexts,
    hasRawSecret: bodyText.indexOf('vision-secret') >= 0,
    secretInputs: Array.from(
      document.querySelectorAll('[data-block="vision"] .secret-field__input'))
      .map((el) => el.value),
    bodyTextSample: bodyText.slice(0, 400),
  };
})()
"""

failures = []
notes = []
CASES = {}


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


def note(label, msg):
    notes.append("%s: %s" % (label, msg))
    print("  note %s: %s" % (label, msg))


def snap(page, shots, name, full=False):
    if not shots:
        return
    os.makedirs(shots, exist_ok=True)
    page.screenshot(path=os.path.join(shots, name + ".png"), full_page=full)


def focus_block(page, selector='[data-block="vision"]'):
    """Скролл к секции Vision — скриншот фиксирует саму форму, не шапку."""
    try:
        page.eval_on_selector(
            selector, "el => el.scrollIntoView({block: 'start'})")
        page.wait_for_timeout(250)
    except Exception:  # noqa: BLE001
        pass


def new_page(browser, width, height, font_px=None):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430, has_touch=width <= 430,
                              device_scale_factor=2)
    ctx.route("**/api/**", make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(
                  status=200, content_type="application/javascript",
                  body=SDK_STUB))
    page = ctx.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on("console",
            lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    if font_px:
        # Telegram Android «Размер текста»: системный масштаб шрифта WebView.
        page.add_init_script(
            "document.addEventListener('DOMContentLoaded', function () {"
            "document.documentElement.style.fontSize = '%dpx'; });" % font_px)
    return ctx, page, errors


def check_layout(label, probe):
    if probe["overflow"]:
        fail(label, "documentElement.scrollWidth %d > innerWidth %d"
             % (probe["docScrollWidth"], probe["innerWidth"]))
    if probe["mainOverflow"]:
        fail(label, "main.scroll-area scrollWidth %d > clientWidth %d"
             % (probe["mainScrollWidth"], probe["mainClientWidth"]))
    if probe["rowIssues"]:
        fail(label, "строки формы: " + "; ".join(probe["rowIssues"]))
    if probe["controlIssues"]:
        fail(label, "действия вне viewport: " + "; ".join(probe["controlIssues"]))
    if probe["nativeText"]:
        fail(label, "в DOM есть артефакт `[native code]` (D10/P0V-UI-NATIVE)")
    if probe["hasRawSecret"]:
        fail(label, "значение ключа в DOM (P0V-UI-SECRETS)")
    if any(v for v in probe["secretInputs"] if v):
        fail(label, "secret-поле засеяно значением: %r"
             % (probe["secretInputs"],))


def check_facts(label, probe, expect_detail=True):
    if not probe["factsPresent"]:
        fail(label, "нет блока фактов [data-vision-facts] (D12)")
        return
    facts = probe["facts"]
    checks = {
        "provider": "Провайдер: " + PROVIDER,
        "model": "Модель: " + MODEL,
        "api_type": "Тип подключения: OpenAI-совместимый",
        "result": "Результат проверки: " + STATE["visible_reason"],
    }
    for key, want in checks.items():
        got = facts.get(key, "")
        if not got.startswith(want):
            fail(label, "факт %s = %r, ожидалось начало %r"
                 % (key, got, want))
    if expect_detail and STATE.get("detail"):
        got = facts.get("detail", "")
        if STATE["detail"] not in got:
            fail(label, "факт detail = %r, нет %r (D12)"
                 % (got, STATE["detail"]))


def check_human(label, probe, human, raw_codes):
    texts = []
    if probe.get("statusText"):
        texts.append(probe["statusText"])
    texts.extend(probe.get("toastTexts") or [])
    if not texts:
        fail(label, "нет ни inline-статуса, ни тоста после пробы")
        return
    if not any(human in t for t in texts):
        fail(label, "человеческой причины %r нет в %r" % (human, texts))
    for t in texts:
        for code in raw_codes:
            if code in t:
                fail(label, "внутренний код %r виден в тексте %r" % (code, t))


def run(browser, width, height, label, path, *, font_px=None, shots=None,
        click_probe=False, expect_layout=None):
    ctx = None
    try:
        ctx, page, errors = new_page(browser, width, height, font_px)
        page.goto(BASE + path, wait_until="load")
        page.wait_for_timeout(1600)
        pre = page.evaluate(PROBE_JS)
        if click_probe:
            btn = page.query_selector(
                '[data-block="vision"] button.prov-test-btn')
            if not btn:
                fail(label, "нет кнопки «Проверить подключение»")
                return None
            btn.click()
            page.wait_for_timeout(900)
        probe = page.evaluate(PROBE_JS)
        probe["consoleErrors"] = errors
        probe["case"] = label
        CASES[label] = probe
        check_layout(label, probe)
        if expect_layout and probe["layout"] != expect_layout:
            # Компоновка — следствие ширины КОНТЕЙНЕРА, не viewport; фиксируем
            # фактическую, чтобы регресс был виден в отчёте.
            note(label, "layout=%r (ожидался %r)" % (probe["layout"],
                                                     expect_layout))
        if errors:
            fail(label, "console_errors=%r" % (errors[:3],))
        focus_block(page)
        snap(page, shots, label)
        return {"pre": pre, "after": probe}
    except Exception as exc:  # noqa: BLE001
        fail(label, "исключение: %r" % (exc,))
        return None
    finally:
        if ctx:
            ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--serve-only", action="store_true")
    args = ap.parse_args()

    global BASE
    BASE = "http://127.0.0.1:%d" % args.port
    STATE.clear()
    STATE.update(_vision_state())
    PROBE.clear()
    PROBE.update(_probe())
    serve_static(args.port, os.path.abspath(args.webroot),
                 api_stubs=args.serve_only)
    print("[p0v-ui] webroot =", os.path.abspath(args.webroot))

    if args.serve_only:
        print("[p0v-ui] стенд:", BASE, "(Ctrl+C — остановить)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            return 0
        return 0

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            # ── A. LLM Провайдеры: стабильный state + факты (D12) ─────────
            for (w, h, tag) in [(320, 640, "320x640"), (360, 740, "360x740"),
                                (390, 844, "390x844"), (430, 932, "430x932"),
                                (640, 360, "640x360-land"),
                                (844, 390, "844x390-land")]:
                res = run(browser, w, h, "llm-%s" % tag, "/#/ai/llm",
                          shots=args.shots)
                if res:
                    check_facts("llm-%s" % tag, res["after"])

            # ── A2. Состояния «state нет» (200 null): линия/факты скрыты,
            # техмусора нет ни до, ни после загрузки (D10).
            saved_state = STATE
            globals()["STATE"] = None
            res = run(browser, 360, 740, "llm-no-state", "/#/ai/llm",
                      shots=args.shots)
            globals()["STATE"] = saved_state
            if res:
                if res["after"]["factsPresent"]:
                    fail("llm-no-state", "факты показаны без state")
                if res["after"]["effLine"]:
                    fail("llm-no-state", "линия показана без state: %r"
                         % res["after"]["effLine"])

            # ── B. Модуль «Распознавание изображений» → «Модели» ──────────
            for (w, h, tag) in [(320, 640, "320x640"), (360, 740, "360x740"),
                                (390, 844, "390x844"),
                                (640, 360, "640x360-land")]:
                res = run(browser, w, h, "mod-%s" % tag,
                          "/#/modules/vision/models", shots=args.shots)
                if res:
                    check_facts("mod-%s" % tag, res["after"])

            # Раскрытые настройки карточки модуля (форма внутри карточки).
            try:
                ctx, page, errors = new_page(browser, 360, 740)
                page.goto(BASE + "/#/modules/vision/models", wait_until="load")
                page.wait_for_timeout(1400)
                page.click('[data-connection-card="vision"] [data-conn-configure]')
                page.wait_for_timeout(500)
                probe = page.evaluate(PROBE_JS)
                probe["consoleErrors"] = errors
                probe["case"] = "mod-settings-360x740"
                CASES["mod-settings-360x740"] = probe
                check_layout("mod-settings-360x740", probe)
                if not probe["rows"]:
                    fail("mod-settings-360x740", "раскрытая форма без .prov-row")
                if errors:
                    fail("mod-settings-360x740", "console_errors=%r" % (errors[:3],))
                focus_block(page, '[data-connection-card="vision"]')
                snap(page, args.shots, "mod-settings-360x740")
                ctx.close()
            except Exception as exc:  # noqa: BLE001
                fail("mod-settings-360x740", "исключение: %r" % (exc,))

            # ── C. Android font scale: 20/24px root (Telegram «Размер
            # текста») — overflow, компоновка, доступность действий.
            for (w, h, font, tag) in [(320, 640, 20, "320x640-font20"),
                                      (360, 740, 24, "360x740-font24"),
                                      (390, 844, 20, "390x844-font20")]:
                res = run(browser, w, h, "llm-%s" % tag, "/#/ai/llm",
                          font_px=font, shots=args.shots)
                if res:
                    check_facts("llm-%s" % tag, res["after"])

            # ── D. D11: классы причин — человеческий текст, без кодов ─────
            reasons = [
                ("auth", dict(capability="access_error",
                              reason="vision_unavailable", detail="http_401",
                              visible_reason="Неверный ключ: провайдер "
                                             "отклонил авторизацию"),
                 ["vision_unavailable", "http_401"]),
                ("rate", dict(capability="rate_limited",
                              reason="vision_rate_limited", detail="http_429",
                              visible_reason="Превышен лимит запросов "
                                             "провайдера"),
                 ["vision_rate_limited", "http_429"]),
                ("modality", dict(capability="no_vision",
                                  reason="vision_unsupported",
                                  detail="image_modality_unsupported/http_400",
                                  visible_reason="Модель не принимает "
                                                 "изображения"),
                 ["vision_unsupported", "image_modality_unsupported"]),
                ("timeout", dict(detail="timeout",
                                 visible_reason="Провайдер не ответил вовремя "
                                                "(таймаут)"),
                 ["vision_unavailable", "timeout"]),
                ("server5xx", dict(detail="http_5xx",
                                   visible_reason="Провайдер временно "
                                                  "недоступен (ошибка сервера)"),
                 ["vision_unavailable", "http_5xx"]),
                ("empty", dict(detail="empty_completion",
                               visible_reason="Провайдер вернул пустой ответ"),
                 ["vision_unavailable", "empty_completion"]),
                ("config", dict(detail="api_type_unsupported",
                                visible_reason="Тип подключения не "
                                               "поддерживается (доступен "
                                               "OpenAI-совместимый)"),
                 ["vision_unavailable", "api_type_unsupported"]),
                ("model-missing", dict(detail="model_not_found/http_404",
                                       visible_reason="Модель не найдена на "
                                                      "этом адресе (проверьте "
                                                      "имя модели)"),
                 ["vision_unavailable", "model_not_found"]),
                ("bad-image", dict(detail="image_rejected/http_400",
                                   visible_reason="Модель доступна, но "
                                                  "изображение не принято"),
                 ["vision_unavailable", "image_rejected"]),
                # Клиентский страховочный маппинг: visible_reason пуст →
                # категория распознана по reason/detail, коды не печатаются.
                ("fallback-auth", dict(capability="access_error",
                                       reason="vision_unavailable",
                                       detail="http_403",
                                       visible_reason=""),
                 ["vision_unavailable", "http_403"]),
            ]
            for (tag, over, raw_codes) in reasons:
                PROBE.clear()
                PROBE.update(_probe(**over))
                label = "probe-%s" % tag
                res = run(browser, 360, 740, label, "/#/ai/llm",
                          shots=args.shots, click_probe=True)
                if not res:
                    continue
                human = over.get("visible_reason")
                if not human:
                    human = "Неверный ключ: провайдер отклонил авторизацию"
                check_human(label, res["after"], human, raw_codes)
                # state из ответа пробы — факты обновились (D12).
                if over.get("visible_reason"):
                    got = res["after"]["facts"].get("result", "")
                    if human not in got:
                        fail(label, "факты после пробы: %r (нет %r)"
                             % (got, human))
            PROBE.clear()
            PROBE.update(_probe())

            # ── E. Успешная проба: «изображение поддерживается» ───────────
            PROBE.clear()
            PROBE.update(_probe(ok=True, capability="ok", image_input=True,
                                reason="", detail="",
                                visible_reason="Распознавание работает",
                                state=_vision_state(
                                    effective_enabled=True,
                                    capability="ok", reason="",
                                    detail="",
                                    visible_reason="Распознавание работает")))
            res = run(browser, 360, 740, "probe-ok", "/#/ai/llm",
                      shots=args.shots, click_probe=True)
            if res:
                check_human("probe-ok", res["after"],
                            "изображение поддерживается", [])
                if res["after"]["effLine"] != "Распознавание работает":
                    note("probe-ok", "линия после успеха: %r"
                         % res["after"]["effLine"])
            PROBE.clear()
            PROBE.update(_probe())

    report = {"webroot": os.path.abspath(args.webroot),
              "failures": failures, "notes": notes, "cases": CASES}
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".",
                    exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n== ИТОГ P0V-UI: failures=%d, cases=%d" % (len(failures),
                                                       len(CASES)))
    for row in failures:
        print("  -", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
