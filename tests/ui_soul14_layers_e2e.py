# -*- coding: utf-8 -*-
"""SOUL-14.1 — диаграмма влияния слоёв «Как рождается ответ» в «Речь и характер».

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(прецедент `tests/ui_p0a_ux_speech_compact_e2e.py`: route-стабы `/api/*`,
Telegram SDK — route-mock).

Контракт (ТЗ §15 SOUL-14, строка карты SOUL-14.1):

  1. На витрине «Речи и характера» — диаграмма `[data-speech-layers]`:
     ровно 7 узлов в порядке Core → SelfModel → L1 → lessons → examples →
     humor → Writer (`data-speech-layer`), человеческие подписи «какой
     режим / почему одно слово / приём юмора / проверка фактов», это карта
     сборки, а не журнал внутренних событий.
  2. Статусы честные: только реальные оси `/api/speech/overview`
     (gates/sections/layers). Нет данных (ключа `layers` нет,
     `available:false`, `enabled:null`) → бейдж ровно «—», никаких
     выдуманных чисел.
  3. Навигация: узлы с разделами (core/lessons/examples/humor) — кнопки,
     открывают существующие разделы; узлы без раздела (self_model/l1/
     writer) — не кнопки.
  4. Адаптивность: 360/390px — без горизонтального overflow, тач-цели
     ≥44px; desktop 1280 — карточка во всю ширину сетки.
  5. Витрина не переделана: 4 группы и состав карточек прежние.

Запуск:
  .venv/Scripts/python.exe tests/ui_soul14_layers_e2e.py
  ... --shots <dir>  --json <path>

TEST-LIFECYCLE: CONTRACT owner=SOUL-14.1 (§15 ТЗ: понятная диаграмма
влияния слоёв в «Речь и характер» без второй аналитической стены).
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

PORT = 8867
BASE = "http://127.0.0.1:%d" % PORT
CHAT_A = -100500

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

SECTIONS = [
    ("core", "psychology", "Характер", "Постоянный характер", "custom"),
    ("style", "format_quote", "Стиль письма", "Правила формы", "custom"),
    ("expression", "tune", "Выражение", "Привычки подачи", "custom"),
    ("humor", "theater_comedy", "Юмор", "Приёмы шуток", "enabled"),
    ("examples", "library_books", "Примеры", "Карточки примеров", "ready"),
    ("try", "science", "Попробовать", "Сравнение вариантов", "ready"),
    ("learning", "school", "Обучение", "Что бот подхватывает", "ready"),
]
ADVANCED = [
    ("all", "list_alt", "Все инструкции"),
    ("inspector", "fact_check", "Effective Prompt Inspector"),
    ("capabilities", "extension", "Возможности бота"),
]

#: Управляемое состояние стаба overview: ключ `layers` и оси гейтов.
STATE = {
    "layers": {
        "l1": {"available": True, "enabled": True, "fallback": True},
        "self_model": {"available": True, "enabled": True, "applied": 2,
                       "rejected": 1, "stale": False, "fallback": False},
    },
    "gates": {"character_core_enabled": True,
              "unified_composer_enabled": True,
              "experience_lessons_enabled": True,
              "humor_library_enabled": True},
    "with_layers": True,
}


def _overview():
    ov = {
        "scope": "global",
        "chat_id": None,
        "inheritance": "global",
        "gates": dict(STATE["gates"]),
        "sections": [
            {"id": sid, "icon": icon, "title": title, "subtitle": sub,
             "state": state,
             "detail": ("Действует компактная редакция · 120 зн."
                        if sid == "core" else
                        "карточек: 3 · эталонов: 2 · черновиков: 1"
                        if sid == "examples" else
                        "уроки опыта и реакции на шутки включены"
                        if sid == "learning" else
                        "библиотека включена" if sid == "humor" else
                        "человеческая строка"),
             "ready": True}
            for (sid, icon, title, sub, state) in SECTIONS],
        "advanced": [
            {"id": sid, "icon": icon, "title": title,
             "subtitle": "технический раздел", "ready": True}
            for (sid, icon, title) in ADVANCED],
        "registry": {"blocks": 12, "version": "reg-1", "factory_set": "fs"},
        "can_edit": True,
    }
    if STATE["with_layers"]:
        ov["layers"] = json.loads(json.dumps(STATE["layers"]))
    return ov


def _core():
    return {
        "scope": "global", "chat_id": None, "inheritance": "global",
        "can_edit": True, "doc_key": "character.core",
        "permanent_note": "Постоянный характер задаётся здесь.",
        "block_ids": {"full": "core.personality",
                      "compact": "core.personality.compact"},
        "selection": {"level": "compact", "reason": "owner_setting",
                      "revision": "r7.abcdef012345"},
        "document": {"enabled": True, "detail_level": "compact",
                     "revision": 7, "updated_at": ""},
        "factory": {"full_revision": "fac:040",
                    "compact_revision": "fac:041"},
        "editions": {
            "full": {"text": "ГЛОБАЛЬНЫЙ ХАРАКТЕР.", "withheld": False,
                     "source": "global", "differs_from_factory": False,
                     "factory_revision": "fac:040"},
            "compact": {"text": "ГЛОБАЛЬНЫЙ ХАРАКТЕР.", "withheld": False,
                        "source": "global", "differs_from_factory": False,
                        "factory_revision": "fac:041"},
        },
        "history": [], "diff": {},
    }


def payload_for(name):
    if name == "overview":
        return _overview()
    if name == "core":
        return _core()
    if name == "access/me":
        return {"is_global_admin": True, "effective_permissions": None}
    if name == "access/chats":
        return [{"chat_id": CHAT_A, "title": "Чат A", "is_dm": False,
                 "access": "admin", "is_active": True}]
    return {}


def make_api_handler():
    def _handler(route):
        req = route.request
        url = req.url.split("?")[0]
        if "/api/speech/" in url:
            name = url.rsplit("/api/speech/", 1)[1]
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload_for(name),
                                          ensure_ascii=False))
            return
        if url.endswith("/api/access/me") or url.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload_for(
                              url.rsplit("/api/", 1)[-1]),
                              ensure_ascii=False))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url),
                                      ensure_ascii=False))
    return _handler


def serve_static(port, webroot):
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

        def log_message(self, *args):  # тихо
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


failures = []
notes = []


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


def new_page(browser, width, height, shots=None):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430,
                              has_touch=width <= 430)
    ctx.route("**/api/**", make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(
                  status=200, content_type="application/javascript",
                  body=SDK_STUB))
    page = ctx.new_page()
    page.set_default_timeout(15000)
    return ctx, page


def snap(page, shots, name):
    if shots:
        os.makedirs(shots, exist_ok=True)
        page.screenshot(path=os.path.join(shots, name + ".png"))


def open_speech(page):
    page.goto(BASE + "/#/ai/speech", wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_selector(".speech-screen", state="visible")
    page.wait_for_selector("[data-speech-layers]", state="visible")
    page.wait_for_timeout(400)


PROBE = r"""
(() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const layers = document.querySelector('[data-speech-layers]');
  const grid = document.querySelector('.speech-grid');
  const rows = Array.from(
    document.querySelectorAll('[data-speech-layer-flow] [data-speech-layer]'))
    .map((el) => ({
      key: el.getAttribute('data-speech-layer'),
      tag: el.tagName,
      badge: strip((el.querySelector('.badge') || {}).textContent),
      title: strip((el.querySelector('.speech-layer-title') || {})
        .textContent),
      desc: strip((el.querySelector('.speech-layer-desc') || {})
        .textContent),
      detail: strip((el.querySelector('.speech-layer-detail') || {})
        .textContent),
      h: Math.round(el.getBoundingClientRect().height),
      w: Math.round(el.getBoundingClientRect().width),
    }));
  const small = [];
  if (layers) {
    layers.querySelectorAll('button').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      if (r.height < 44 || r.width < 44) small.push({
        t: strip(el.textContent).slice(0, 40),
        h: Math.round(r.height), w: Math.round(r.width) });
    });
  }
  return {
    present: !!layers,
    title: strip((document.querySelector('.speech-layers-title') || {})
      .textContent),
    note: strip((document.querySelector('.speech-layers-note') || {})
      .textContent),
    rows,
    small: small.slice(0, 6),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    layerW: layers ? Math.round(layers.getBoundingClientRect().width) : null,
    gridW: grid ? Math.round(grid.getBoundingClientRect().width) : null,
    groups: Array.from(document.querySelectorAll('.speech-group-title'))
      .map((x) => strip(x.textContent)),
    cards: Array.from(document.querySelectorAll('[data-speech-card]'))
      .map((x) => x.getAttribute('data-speech-card')),
    sectionOpen: !!document.querySelector('.speech-section'),
  };
})()
"""


def check_store_intact(label, data):
    """Диаграмма не переделала витрину: 4 группы, прежний состав карточек."""
    if len(data["groups"]) != 4:
        fail(label, "групп витрины: %d (%s)" % (len(data["groups"]),
                                                data["groups"]))
    if sorted(data["cards"]) != sorted([s[0] for s in SECTIONS]
                                       + [a[0] for a in ADVANCED]):
        fail(label, "состав карточек витрины изменился: %s" % data["cards"])


def check_common(label, data):
    if data["overflow"] > 1:
        fail(label, "горизонтальный overflow: %d px" % data["overflow"])
    if not data["present"]:
        fail(label, "диаграмма [data-speech-layers] не отрисована")
        return False
    if data["small"]:
        fail(label, "тач-цель < 44px в диаграмме: %s" % data["small"])
    check_store_intact(label, data)
    return True


EXPECTED_KEYS = ["core", "self_model", "l1", "lessons", "examples",
                 "humor", "writer"]
SECTION_KEYS = {"core", "lessons", "examples", "humor"}


def check_rows(label, data):
    keys = [r["key"] for r in data["rows"]]
    if keys != EXPECTED_KEYS:
        fail(label, "узлы диаграммы: %s (ожидалось %s)"
             % (keys, EXPECTED_KEYS))
        return
    for r in data["rows"]:
        if not r["title"] or not r["desc"]:
            fail(label, "узел «%s»: нет заголовка или объяснения" % r["key"])
        is_btn = r["tag"] == "BUTTON"
        if is_btn != (r["key"] in SECTION_KEYS):
            fail(label, "узел «%s»: tag=%s, ожидался %s"
                 % (r["key"], r["tag"],
                    "BUTTON" if r["key"] in SECTION_KEYS else "DIV"))
        if r["h"] < 44:
            fail(label, "узел «%s»: высота %dpx < 44" % (r["key"], r["h"]))


def run_full_layers(browser, width, height, label, shots):
    """Сценарий 1: слои с данными — честные статусы и человеческий текст."""
    ctx, page = new_page(browser, width, height, shots)
    try:
        open_speech(page)
        data = page.evaluate(PROBE)
        notes.append({label: data})
        if not check_common(label, data):
            return
        check_rows(label, data)
        by = {r["key"]: r for r in data["rows"]}
        # Честные статусы из стаба: l1/self_model включены, core вкл.
        for key in ("core", "self_model", "l1", "lessons", "humor"):
            if by[key]["badge"] != "вкл":
                fail(label, "узел «%s»: бейдж %r, ожидался «вкл»"
                     % (key, by[key]["badge"]))
        if by["writer"]["badge"] != "активен":
            fail(label, "Writer: бейдж %r, ожидался «активен»"
                 % by["writer"]["badge"])
        if by["writer"]["detail"] != "сборка: единый композер":
            fail(label, "Writer: деталь %r" % by["writer"]["detail"])
        if by["examples"]["badge"] != "готово":
            fail(label, "examples: бейдж %r, ожидался «готово»"
                 % by["examples"]["badge"])
        # Человеческий текст контракта (без чтения JSON):
        # режим/одно слово/юмор/факты.
        human = " ".join(r["desc"] + " " + r["title"] for r in data["rows"]) \
          + " " + data["note"]
        for want in ("ответить, поставить реакцию или промолчать",
                     "одного слова", "приём", "характер",
                     "Планировщик (L1)", "SelfModel", "Writer",
                     "Почему реплика — одно слово"):
            if want not in human:
                fail(label, "нет человеческого текста %r" % want)
        # Реальные числа из API показываются, выдуманных нет:
        if "правил о себе сейчас: 2" not in by["self_model"]["detail"]:
            fail(label, "self_model: нет реального числа правил: %r"
                 % by["self_model"]["detail"])
        if by["l1"]["detail"]:
            fail(label, "l1: неожиданная деталь %r" % by["l1"]["detail"])
        if "Действует компактная редакция" not in by["core"]["detail"]:
            fail(label, "core: нет детализации из overview: %r"
                 % by["core"]["detail"])
        # Навигация: узел с разделом открывает его; узел без раздела — нет.
        page.click("[data-speech-layer='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(250)
        if not page.locator(".speech-section").count():
            fail(label, "узел «core» не открыл раздел «Характер»")
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        snap(page, shots, "layers_%s" % label)
    finally:
        ctx.close()


def run_no_layers(browser, width, height, label, shots):
    """Сценарий 2: старый стаб БЕЗ ключа layers — честные «—», без выдумок."""
    STATE["with_layers"] = False
    try:
        ctx, page = new_page(browser, width, height, shots)
        try:
            open_speech(page)
            data = page.evaluate(PROBE)
            notes.append({label: data})
            if not check_common(label, data):
                return
            check_rows(label, data)
            by = {r["key"]: r for r in data["rows"]}
            for key in ("self_model", "l1"):
                if by[key]["badge"] != "—":
                    fail(label, "узел «%s» без данных: бейдж %r, ожидался «—»"
                         % (key, by[key]["badge"]))
                if by[key]["detail"]:
                    fail(label, "узел «%s» без данных придумал деталь: %r"
                         % (key, by[key]["detail"]))
            snap(page, shots, "layers_%s" % label)
        finally:
            ctx.close()
    finally:
        STATE["with_layers"] = True


def run_unknown_states(browser, width, height, label, shots):
    """Сценарий 3: available:false / enabled:null / выключенные слои."""
    STATE["layers"] = {
        "l1": {"available": False, "enabled": None, "fallback": None},
        "self_model": {"available": True, "enabled": False,
                       "applied": None, "rejected": None,
                       "stale": None, "fallback": None},
    }
    STATE["gates"]["character_core_enabled"] = False
    STATE["gates"]["experience_lessons_enabled"] = False
    STATE["gates"]["humor_library_enabled"] = False
    STATE["gates"]["unified_composer_enabled"] = False
    try:
        ctx, page = new_page(browser, width, height, shots)
        try:
            open_speech(page)
            data = page.evaluate(PROBE)
            notes.append({label: data})
            if not check_common(label, data):
                return
            check_rows(label, data)
            by = {r["key"]: r for r in data["rows"]}
            for key in ("core", "lessons", "humor"):
                if by[key]["badge"] != "выкл":
                    fail(label, "узел «%s»: бейдж %r, ожидался «выкл»"
                         % (key, by[key]["badge"]))
            if by["l1"]["badge"] != "—":
                fail(label, "l1 unavailable: бейдж %r, ожидался «—»"
                     % by["l1"]["badge"])
            if by["self_model"]["badge"] != "выкл":
                fail(label, "self_model off: бейдж %r, ожидался «выкл»"
                     % by["self_model"]["badge"])
            if "правил о себе сейчас" in by["self_model"]["detail"]:
                fail(label, "self_model off придумал число правил: %r"
                     % by["self_model"]["detail"])
            if by["writer"]["detail"] != "сборка: прежняя композиция":
                fail(label, "Writer legacy: деталь %r" % by["writer"]["detail"])
            snap(page, shots, "layers_%s" % label)
        finally:
            ctx.close()
    finally:
        STATE["gates"].update({"character_core_enabled": True,
                               "experience_lessons_enabled": True,
                               "humor_library_enabled": True,
                               "unified_composer_enabled": True})
        STATE["layers"] = {
            "l1": {"available": True, "enabled": True, "fallback": True},
            "self_model": {"available": True, "enabled": True,
                           "applied": 2, "rejected": 1,
                           "stale": False, "fallback": False},
        }


def run_full_width_desktop(browser, shots):
    """Desktop 1280: диаграмма во всю ширину сетки (grid-column: 1/-1)."""
    label = "desktop"
    ctx, page = new_page(browser, 1280, 900, shots)
    try:
        open_speech(page)
        data = page.evaluate(PROBE)
        notes.append({label: data})
        if not check_common(label, data):
            return
        if data["layerW"] is None or data["gridW"] is None:
            fail(label, "нет замеров ширины")
        elif abs(data["layerW"] - data["gridW"]) > 2:
            fail(label, "диаграмма не во всю ширину сетки: %s vs %s"
                 % (data["layerW"], data["gridW"]))
        snap(page, shots, "layers_desktop")
    finally:
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    serve_static(PORT, os.path.abspath(args.webroot))
    print("[soul14-layers-e2e] webroot =", os.path.abspath(args.webroot))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            run_full_layers(browser, 360, 740, "360", args.shots)
            run_full_layers(browser, 390, 844, "390", args.shots)
            run_no_layers(browser, 390, 844, "no-layers-390", args.shots)
            run_unknown_states(browser, 360, 740, "unknown-360", args.shots)
            run_full_width_desktop(browser, args.shots)

    report = {"webroot": os.path.abspath(args.webroot),
              "failures": failures, "notes": notes}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n== Итог: failures=%d" % len(failures))
    for row in failures:
        print("  -", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
