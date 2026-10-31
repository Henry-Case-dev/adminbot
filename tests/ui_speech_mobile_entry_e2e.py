# -*- coding: utf-8 -*-
"""FIX-SPEECH-MOBILE — «Речь и характер» реально достижима на мобильном.

Живой дефект владельца (18.10): на мобильном раздел «Речь и характер»
отсутствовал — на хабе «ИИ» не было ни одной двери с этим именем
(единственный вход жил внутри «Личность и стиль», persona-таб).

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(route-стабы `/api/*` — прецедент `tools/ui_asap8_w2_shell_e2e.py`,
`tests/ui_soul1_glass_tiera_e2e.py`; Telegram SDK — route-mock):

  1. мобильные 320×640 и 390×844: путь владельца «Ещё» → «ИИ» даёт ЯВНУЮ
     строку-вход `[data-speech-hub-entry]` с именем «Речь и характер»;
  2. она видима в вьюпорте, высота ≥ 44px, страница без горизонтального
     скролла; клик ведёт на существующий `#/ai/speech`;
  3. экран речи открывается: `.speech-screen` + витрина разделов;
  4. НАВИГАЦИЯ НЕ ПЕРЕДЕЛАНА: на хабе по-прежнему ровно 5 карточек
     (`hub-card`) в прежнем порядке и вторая дверь в persona-табе
     (`[data-speech-entry]`) жива;
  5. desktop 1280×900 (контроль): тот же вход на хабе.

Запуск:
  .venv/Scripts/python.exe tests/ui_speech_mobile_entry_e2e.py
  .venv/Scripts/python.exe tests/ui_speech_mobile_entry_e2e.py --webroot <dir>
      (для RED-демонстрации на пре-фиксном дереве)
  --shots <dir>  — скриншоты каждого шага; --json <path> — машинный отчёт.

TEST-LIFECYCLE: CONTRACT owner=FIX-SPEECH-MOBILE (§6.3: полный список
редакторов «Речи и характера» реально достижим на мобильном через
«Ещё» → «ИИ»); REGRESSION owner=FIX-SPEECH-MOBILE (18.10: на хабе «ИИ»
двери с именем «Речь и характер» не было — владелец не мог найти раздел).
"""
import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import ui_round1025_matrix as M  # noqa: E402  (базовые /api-стабы)

PORT = 8859
BASE = "http://127.0.0.1:%d" % PORT

# Telegram SDK — route-mock (прецедент ui_asap8_w2_shell_e2e.py §4.2.1).
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

# Минимальная витрина «Речи и характера»: контракт входа не зависит от
# полноты секционных payload'ов (глубокие разделы/сохранение — предмет
# tools/ui_soul1_w6_speech_e2e.py); здесь — честная форма overview.
SPEECH_OVERVIEW = {
    "scope": "global",
    "chat_id": None,
    "inheritance": "global",
    "gates": {"character_core_enabled": True},
    "sections": [
        {"id": "core", "icon": "badge", "title": "Характер",
         "subtitle": "Персональный Core", "detail": "", "state": "custom"},
        {"id": "style", "icon": "edit_note", "title": "Стиль письма",
         "subtitle": "Правила формы", "detail": "", "state": "custom"},
        {"id": "expression", "icon": "record_voice_over", "title": "Выражение",
         "subtitle": "Привычки подачи", "detail": "", "state": "custom"},
    ],
    "advanced": [],
    "registry": {"blocks": 0, "version": "stub", "factory_set": "stub"},
    "can_edit": True,
    "can_view_inspector": True,
}

HUB_ORDER = ["Библиотека промптов", "Модели и подключения", "Личность и стиль",
             "Имена и алиасы", "Умный кэш"]


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
            if path.endswith("/api/speech/overview"):
                self._json(SPEECH_OVERVIEW)
                return
            if path.startswith("/api/"):
                self._json(M._stub_for(self.path))
                return
            return super().do_GET()

        def log_message(self, *args):  # тихо
            pass
    return _Handler


def serve(port, webroot):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(webroot))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


STRIP_JS = ("(s) => (s || '').replace(/[\\uE000-\\uF8FF]/g, '')"
            ".replace(/\\s+/g, ' ').trim()")

PROBE = """
(() => {
  const strip = %s;
  const vis = (el) => !!el && el.offsetParent !== null
    && el.getBoundingClientRect().width > 0;
  const rect = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return { x: Math.round(b.x), y: Math.round(b.y),
             w: Math.round(b.width), h: Math.round(b.height),
             bottom: Math.round(b.bottom) }; };
  const entry = document.querySelector('[data-speech-hub-entry]');
  const personaEntry = document.querySelector('[data-speech-entry]');
  return {
    hash: location.hash,
    // ASAP-UI-02 §2.1: разделы на телефоне — в drawer (нижней панели нет).
    topnav: Array.from(document.querySelectorAll('.app-drawer .sidebar-link'))
      .map((x) => strip(x.textContent)),
    navBtn: !!document.querySelector('[data-drawer-trigger]'),
    hubCards: Array.from(document.querySelectorAll('.hub-card'))
      .map((x) => strip(x.querySelector('.hub-card-title') ?
        x.querySelector('.hub-card-title').textContent : x.textContent)),
    hubEntryPresent: !!entry,
    hubEntryVisible: vis(entry),
    hubEntryText: entry ? strip(entry.textContent) : null,
    hubEntryRect: rect(entry),
    personaEntryVisible: vis(personaEntry),
    screenVisible: vis(document.querySelector('.speech-screen')),
    screenTitle: strip((document.querySelector('.speech-title') || {}).textContent),
    sectionCards: document.querySelectorAll('[data-speech-card]').length,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
})()
""" % STRIP_JS

failures = []
notes = []


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


def check(label, page, shots_dir=None, tag=""):
    data = page.evaluate(PROBE)
    notes.append({"label": label, "probe": data})
    if data["overflow"] > 1:
        fail(label, "горизонтальный overflow: %d px" % data["overflow"])
    if shots_dir:
        page.screenshot(path=os.path.join(shots_dir, "entry_%s.png" % tag))
    return data


def run_viewport(page, width, height, label, shots_dir=None):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(BASE + "/#/", wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_timeout(600)

    mobile = width < 768
    if mobile:
        # Путь владельца: навигация (drawer) → «ИИ».
        page.click("[data-drawer-trigger]")
        page.wait_for_selector(".app-drawer.open", state="visible")
        data = check("%s/drawer" % label, page, shots_dir, "drawer_%s" % label)
        clicked = page.evaluate(
            "(() => { const s = %s; const b = Array.from("
            "document.querySelectorAll('.app-drawer .sidebar-link')).find((x) => "
            "s(x.textContent) === 'ИИ'); if (!b) return false; b.click(); "
            "return true; })()" % STRIP_JS)
        if not clicked:
            fail(label, "пункт «ИИ» не найден в drawer")
        page.wait_for_timeout(700)
    else:
        page.goto(BASE + "/#/ai", wait_until="load")
        page.wait_for_timeout(600)

    hub = check("%s/hub" % label, page, shots_dir, "hub_%s" % label)
    if hub["hash"] != "#/ai":
        fail(label, "ожидался хаб #/ai, получен %s" % hub["hash"])
    if hub["hubCards"] != HUB_ORDER:
        fail(label, "состав карточек хаба изменился: %s" % hub["hubCards"])
    if not hub["hubEntryPresent"]:
        fail(label, "НЕТ явного входа [data-speech-hub-entry] на хабе «ИИ»")
        return
    if not hub["hubEntryVisible"]:
        fail(label, "вход [data-speech-hub-entry] не виден")
    if "Речь и характер" not in (hub["hubEntryText"] or ""):
        fail(label, "текст входа не содержит «Речь и характер»: %s"
             % hub["hubEntryText"])
    if hub["hubEntryRect"] and hub["hubEntryRect"]["h"] < 44:
        fail(label, "тач-цель входа < 44px: %s" % hub["hubEntryRect"]["h"])
    if hub["hubEntryRect"] and hub["hubEntryRect"]["bottom"] > height + 1:
        notes.append({"label": label,
                      "note": "вход ниже первого экрана (%d > %d)"
                              % (hub["hubEntryRect"]["bottom"], height)})

    page.click("[data-speech-hub-entry]")
    page.wait_for_selector(".speech-screen", state="visible")
    page.wait_for_timeout(500)
    screen = check("%s/speech" % label, page, shots_dir, "speech_%s" % label)
    if screen["hash"] != "#/ai/speech":
        fail(label, "вход не привёл на #/ai/speech: %s" % screen["hash"])
    if screen["screenTitle"] != "Речь и характер":
        fail(label, "заголовок экрана: %r" % screen["screenTitle"])
    if screen["sectionCards"] < 3:
        fail(label, "витрина разделов пуста: %d карточек"
             % screen["sectionCards"])

    # Вторая дверь (persona-таб) жива — навигация не переделана.
    page.goto(BASE + "/#/ai/persona", wait_until="load")
    page.wait_for_selector("[data-speech-entry]", state="visible")
    page.wait_for_timeout(300)
    persona = check("%s/persona" % label, page, shots_dir, "persona_%s" % label)
    if not persona["personaEntryVisible"]:
        fail(label, "вход в persona-табе пропал (навигация переделана?)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    shots_dir = args.shots or ""
    if shots_dir:
        os.makedirs(shots_dir, exist_ok=True)
    serve(PORT, os.path.abspath(args.webroot))
    print("[entry-e2e] webroot =", os.path.abspath(args.webroot))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            for (w, h, label) in ((320, 640, "320"), (390, 844, "390"),
                                  (1280, 900, "1280")):
                ctx = browser.new_context(
                    viewport={"width": w, "height": h},
                    is_mobile=w <= 430, has_touch=w <= 430)
                page = ctx.new_page()
                page.set_default_timeout(15000)
                page.on("dialog", lambda d: d.accept())
                try:
                    print("== viewport", label)
                    run_viewport(page, w, h, label, shots_dir)
                finally:
                    ctx.close()

    report = {"webroot": os.path.abspath(args.webroot),
              "failures": failures,
              "notes": [n for n in notes if "probe" not in n],
              "probes": [n for n in notes if "probe" in n]}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n== ИТОГ: failures=%d" % len(failures))
    for row in failures:
        print("  -", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
