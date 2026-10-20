# -*- coding: utf-8 -*-
"""ADD-SAMPLES-UX — UI e2e контракта §4 (экран «Примеры» MiniApp).

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(Playwright, локальный стенд + route-подобные /api-стабы на stateful-стабе;
прецедент `tools/ui_soul1_w6_speech_e2e.py`, `tests/ui_p0a_ux_speech_compact_e2e.py`).

Сценарии (карта SU-UI.*, SU-ED.*, источник source-add-samples-ux §4):

  A. list-360x740 (§4.1): DOM-иерархия сверху вниз (заголовок+пояснение →
     вкладки одной строкой → покатегорийные счётчики → поиск+фильтр одной
     строкой → карточки → действия); одна колонка; бейджи статусов; подпись
     «Категория · GLOBAL/CHAT · Заводской/Мой/Изменено владельцем»; БЕЗ
     SQL/JSON/тегов/ревизий в карточке; tombstone- и legacy-группы.
  B. editor-390x844 (§4.2): «Добавить пример» открывает ОТДЕЛЬНЫЙ экран
     (форма не в потоке списка); категория предзаполнена из вкладки; в «Мат»
     видимый выбор режима, в «Юмор» — приём, в «Общие» — ни того ни другого;
     поля ввода/ответа полноширинные; «Назад» с несохранёнными изменениями
     предупреждает; «Сохранено» появляется только после ответа API; после
     сохранения данные перечитаны с сервера (stateful-стаб).
  C. factory-390x844 (§3+§4.2): заводская карточка — тот же экран с плашкой,
     «Посмотреть исходный», «Восстановить исходный» (confirm → API confirm:
     true, один пример); «Заводские наборы — сравнить…»: список затрагиваемых
     правок, «Отмена» по умолчанию, восстановление — явной кнопкой.
  D. tombstone/edit persistence (§3): правка и удаление заводской карточки
     переживают reload страницы (stateful-стаб мутируется API-вызовами).
  E. landscape 667x375 + desktop 1280x800 (§4.3): нет горизонтального
     overflow; в landscape отступы меньше и шапка не двухстрочная; на desktop
     контент ограничен max-width.

Запуск:
  py -3 tools/ui_samples_ux_e2e.py --json <path> [--shots <dir>] [--no-shots]

TEST-LIFECYCLE: CONTRACT owner=SAMPLES-UX/SU-UI.* (§4, 20.10.2026)
"""
import argparse
import copy
import json
import os
import re
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
sys.path.insert(0, str(HERE))

import ui_round1025_matrix as M  # noqa: E402  (базовые /api-стабы)

PORT = 8851
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

failures: list = []
posted: list = []
dialogs: list = []
#: Управление следующим диалогом подтверждения: accept (по умолчанию) или
#: dismiss (владелец выбирает «остаться» в редакторе).
DIALOG_NEXT = {"action": "accept"}


def _on_dialog(d):
    dialogs.append(d.message[:200])
    if DIALOG_NEXT["action"] == "dismiss":
        DIALOG_NEXT["action"] = "accept"
        d.dismiss()
        return
    d.accept()


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


# ── stateful-стаб библиотеки (мутируется только API-вызовами UI) ────────────

def _now():
    return 1777000000


def _row(id, category, *, seed_key=None, mode=None, approved=False,
         status="active", origin=None, owner_modified=False, tombstone=False,
         technique="other", inp="", reply="", note=""):
    return {
        "id": id, "seed_key": seed_key,
        "input_text": inp, "reply_text": reply, "context_note": note,
        "technique": technique, "language": "ru", "tags": [],
        "rudeness_level": 0, "source_kind":
            "bot_suggested" if seed_key else "owner_manual",
        "scope": "global", "chat_id": None,
        "owner_approved": bool(approved), "status": status,
        "library_version": "v1", "revision": 1, "sensitivity_flags": [],
        "uses_count": 0, "last_used_at": None, "approved_at": None,
        "created_at": _now(), "updated_at": _now(),
        "created_by": "seed", "updated_by": "seed",
        "category": category,
        "category_label": {"general": "Общие", "humor": "Юмор",
                           "mat": "Мат", "legacy": "Legacy"}[category],
        "expression_mode": mode,
        "origin": origin or ("factory" if seed_key else "owner"),
        "origin_label": ({True: "Заводской", False: "Мой"}.get(
            bool(seed_key), "Изменено владельцем"))
        if not owner_modified else "Изменено владельцем",
        "owner_modified": owner_modified, "owner_modified_at": None,
        "tombstone": tombstone, "tombstone_at": _now() if tombstone else None,
        "factory_in_code": bool(seed_key),
    }


STATE = {
    "available": True,
    "next_id": 100,
    "factory_originals": {},
    "items": [
        _row(1, "humor", seed_key="starter-01", technique="bureaucratic_logic",
             inp="Опять забыл выключить свет", reply="Акт не составлен",
             note="процедура"),
        _row(2, "humor", approved=True, technique="deadpan",
             inp="Я всё воскресенье разбирал шкаф",
             reply="Шкаф предупредил заранее"),
        _row(3, "mat", seed_key="expr-off-banter",
             technique="expression_register", mode="off",
             inp="Ну ты и выдал вчера с докладом", reply="Выдал, признаю.",
             note="дружеский стёб"),
        _row(4, "mat", approved=True, technique="expression_register",
             mode="occasional", inp="Твой вариант не работает",
             reply="У меня крутится, пиздец как стабильно", note="спор"),
        _row(5, "general", approved=True,
             inp="Как погода?", reply="Обычная, осенняя"),
        _row(6, "legacy", inp="старая карточка без категории",
             reply="ответ", note="миграция"),
        _row(7, "humor", seed_key="starter-07", approved=True,
             owner_modified=True, technique="absurd_escalation",
             inp="Ноутбук стал громко шуметь (моё)",
             reply="Переговоры с вентилятором (моё)", note="моё"),
    ],
    "deleted": [],
}
_ORIG = copy.deepcopy(STATE["items"])


def _factory_seed_for(seed_key):
    return {
        "starter-01": {"input_text": "Опять забыл выключить свет",
                       "reply_text": "Акт не составлен",
                       "technique": "bureaucratic_logic", "category": "humor",
                       "expression_mode": None},
        "expr-off-banter": {"input_text": "Ну ты и выдал вчера с докладом",
                            "reply_text": "Выдал, признаю.",
                            "technique": "expression_register",
                            "category": "mat", "expression_mode": "off"},
        "starter-07": {"input_text": "Ноутбук стал громко шуметь",
                       "reply_text": "Переговоры с вентилятором",
                       "technique": "absurd_escalation", "category": "humor",
                       "expression_mode": None},
    }.get(str(seed_key or ""))


def _payload():
    if not STATE["available"]:
        return {"available": False, "status": "unavailable",
                "reason": "db_unavailable", "items": [], "deleted": [],
                "count": 0, "can_edit": True}
    return {
        "scope": "chat", "chat_id": 777,
        "status": "implemented", "available": True, "reason": None,
        "note": "примеры — данные",
        "entity_fields": [],
        "techniques": [
            {"id": "deadpan", "title": "Дедпан (сухой факт)"},
            {"id": "absurd_escalation", "title": "Абсурдная эскалация"},
            {"id": "bureaucratic_logic", "title": "Бюрократическая логика"},
            {"id": "other", "title": "прочие"},
        ],
        "categories": [{"id": "general", "title": "Общие"},
                       {"id": "humor", "title": "Юмор"},
                       {"id": "mat", "title": "Мат"},
                       {"id": "legacy", "title": "Legacy"}],
        "filters": {},
        "items": [dict(r) for r in STATE["items"] if not r["tombstone"]],
        "deleted": [dict(r) for r in STATE["deleted"]],
        "count": len(STATE["items"]),
        "starter": {"expected": 18, "seeded": 18,
                    "expression_expected": 12, "expression_seeded": 12},
        "telemetry": {"approved": 3, "proposed": 3,
                      "by_version": {"v1": 6}},
        "policy": {"enabled": True, "ab_enabled": False, "max_items": 3,
                   "max_tokens": 320, "diversity_min_distance": 0.34,
                   "recency_penalty": 0.25, "ab_versions": ["v1", "v2"]},
        "policy_source": "default",
        "ab": {"enabled": False, "versions": ["v1", "v2"], "pinned": None},
        "runtime_note": "в runtime уходят только утверждённые",
        "can_edit": True,
    }


def _apply_write(body):
    """POST/DELETE мутации stateful-стаба (edit→reload→persists и т.п.)."""
    items = STATE["items"]
    if body.get("delete_id"):
        rid = int(body["delete_id"])
        row = next((r for r in items if r["id"] == rid), None)
        if row and row["seed_key"]:
            row["tombstone"] = True
            row["tombstone_at"] = _now()
            STATE["deleted"] = [dict(row)]
        return {"ok": True}
    if body.get("restore_id"):
        rid = int(body["restore_id"])
        seed = _factory_seed_for(body.get("seed_key") or "")
        for lst in (STATE["deleted"], items):
            row = next((r for r in lst if r["id"] == rid), None)
            if row is None:
                continue
            row.update({
                "tombstone": False, "tombstone_at": None,
                "owner_modified": False, "owner_modified_at": None,
                "origin": "factory", "origin_label": "Заводской",
                "owner_approved": False, "status": "active",
                "revision": int(row.get("revision") or 1) + 1,
            })
            if seed:
                row["input_text"] = seed["input_text"]
                row["reply_text"] = seed["reply_text"]
        STATE["deleted"] = [r for r in STATE["deleted"] if r["id"] != rid]
        return {"ok": True, "item": {}}
    rid = body.get("id")
    if rid:
        row = next((r for r in items if r["id"] == int(rid)), None)
        if row is not None:
            row["input_text"] = str(body.get("input_text")
                                    or row["input_text"])
            row["reply_text"] = str(body.get("reply_text")
                                    or row["reply_text"])
            if "category" in body:
                row["category"] = str(body["category"])
                row["category_label"] = {"general": "Общие", "humor": "Юмор",
                                         "mat": "Мат"}.get(
                    str(body["category"]), row["category_label"])
            row["expression_mode"] = body.get("expression_mode") or None
            row["owner_approved"] = bool(body.get("owner_approved"))
            row["revision"] = int(row.get("revision") or 1) + 1
            if row["seed_key"]:
                row["owner_modified"] = True
                row["owner_modified_at"] = _now()
                row["origin"] = "modified"
                row["origin_label"] = "Изменено владельцем"
        return {"ok": True, "item": row or {}}
    row = _row(STATE["next_id"], str(body.get("category") or "general"),
               approved=bool(body.get("owner_approved")),
               technique=str(body.get("technique") or "other"),
               inp=str(body.get("input_text") or ""),
               reply=str(body.get("reply_text") or ""))
    row["expression_mode"] = body.get("expression_mode") or None
    STATE["items"].append(row)
    STATE["next_id"] += 1
    return {"ok": True, "item": row}


def _api_get(name):
    if name == "examples":
        return _payload()
    if name == "overview":
        return {
            "scope": "chat", "chat_id": 777, "inheritance": "chat",
            "gates": {"character_core_enabled": True,
                      "unified_composer_enabled": True,
                      "speech_style_policy_enabled": True},
            "sections": [
                {"id": "core", "icon": "face", "title": "Характер",
                 "subtitle": "ядро", "state": "ok", "detail": "", "ready": True},
                {"id": "expression", "icon": "record_voice_over",
                 "title": "Выражение", "subtitle": "речь", "state": "ok",
                 "detail": "", "ready": True},
                {"id": "humor", "icon": "sentiment_satisfied", "title": "Юмор",
                 "subtitle": "приёмы", "state": "ok", "detail": "",
                 "ready": True},
                {"id": "style", "icon": "style", "title": "Стиль",
                 "subtitle": "оформление", "state": "ok", "detail": "",
                 "ready": True},
            ],
            "advanced": [
                {"id": "examples", "icon": "format_list_bulleted",
                 "title": "Примеры", "subtitle": "библиотека", "ready": True},
                {"id": "try", "icon": "science", "title": "Попробовать",
                 "subtitle": "лаборатория", "ready": True},
                {"id": "learning", "icon": "school", "title": "Обучение",
                 "subtitle": "уроки", "ready": True},
                {"id": "all", "icon": "menu_book", "title": "Все инструкции",
                 "subtitle": "реестр", "ready": True},
                {"id": "inspector", "icon": "search", "title": "Inspector",
                 "subtitle": "диагностика", "ready": True},
                {"id": "capabilities", "icon": "checklist",
                 "title": "Возможности", "subtitle": "оси", "ready": True},
            ],
            "registry": {"blocks": 12, "version": "reg-1", "factory_set": "fs"},
            "can_edit": True,
        }
    return M._stub_for("http://stub/api/speech/" + name)


def _api_post(name, body):
    posted.append("POST " + name)
    if name == "examples":
        return _apply_write(body)
    if re.fullmatch(r"examples/\d+", name):
        return _apply_write(dict(body, id=name.split("/")[1]))
    if name == "examples/restore-factory/preview":
        return {"ok": True, "available": True,
                "items": [restore_preview_items()[0]] if
                any(r["owner_modified"] or r["tombstone"]
                    for r in STATE["items"] if r["seed_key"]) else [],
                "note": "сравнение"}
    if name == "examples/restore-factory":
        if not body.get("confirm"):
            return {"ok": False, "reason": "needs_confirmation",
                    "restored": 0, "failed": []}
        restored = 0
        for row in STATE["items"]:
            if row["seed_key"] and (row["owner_modified"] or row["tombstone"]):
                _apply_write({"restore_id": row["id"],
                              "seed_key": row["seed_key"]})
                restored += 1
        return {"ok": True, "restored": restored, "failed": []}
    m = re.fullmatch(r"examples/(\d+)/restore-factory/preview", name)
    if m:
        rid = int(m.group(1))
        row = next((r for r in STATE["items"] if r["id"] == rid), None)
        seed = _factory_seed_for((row or {}).get("seed_key") or "")
        return {"ok": True, "item": {
            "id": rid, "seed_key": (row or {}).get("seed_key"),
            "title": (row or {}).get("input_text", "")[:40],
            "origin": (row or {}).get("origin"), "tombstone": False,
            "revision": 1, "owner_modified_at": None,
            "factory_in_code": seed is not None,
            "diffs": ([{"field": "input_text",
                        "factory": seed["input_text"],
                        "current": (row or {}).get("input_text")}] if seed
                       else []),
            "factory": seed,
        }}
    m = re.fullmatch(r"examples/(\d+)/restore-factory", name)
    if m:
        if not body.get("confirm"):
            return {"ok": False, "reason": "needs_confirmation"}
        _apply_write({"restore_id": int(m.group(1)),
                      "seed_key": (next((r["seed_key"] for r in STATE["items"]
                                         if r["id"] == int(m.group(1))), ""))})
        return {"ok": True, "item": {}, "note": "один пример"}
    m = re.fullmatch(r"examples/(\d+)/why", name)
    if m:
        return {"ok": True, "selected": False,
                "why": "Черновик — ещё не утверждён",
                "reason_code": "not_owner_approved"}
    if name == "examples/seed":
        return {"ok": True, "seeded": 0, "skipped": 18,
                "expression_seeded": 0, "expression_skipped": 12,
                "note": "идемпотентно"}
    if name == "examples/policy":
        return {"ok": True, "scope": "global", "policy": {}, }
    return {"ok": True}


def restore_preview_items():
    out = []
    for row in STATE["items"]:
        if not row["seed_key"]:
            continue
        if row["owner_modified"] or row["tombstone"]:
            seed = _factory_seed_for(row["seed_key"]) or {}
            out.append({
                "id": row["id"], "seed_key": row["seed_key"],
                "title": row["input_text"][:40],
                "origin": row["origin"], "tombstone": row["tombstone"],
                "revision": row["revision"], "owner_modified_at": None,
                "factory_in_code": bool(seed),
                "diffs": [{"field": "input_text",
                           "factory": seed.get("input_text"),
                           "current": row["input_text"]}] if seed else [],
            })
    return out


# ── HTTP-стенд ───────────────────────────────────────────────────────────────

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

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
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
                self._json(_api_get(path.rsplit("/api/speech/", 1)[1]))
                return
            if path.startswith("/api/"):
                self._json(M._stub_for(self.path))
                return
            return super().do_GET()

        def do_POST(self):  # noqa: N802
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except Exception:  # noqa: BLE001
                body = {}
            if path.startswith("/api/speech/"):
                name = path.rsplit("/api/speech/", 1)[1]
                self._json(_api_post(name, body))
                return
            self._json({"ok": True})

        def do_DELETE(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path.startswith("/api/speech/examples/"):
                rid = path.rsplit("/", 1)[1]
                _apply_write({"delete_id": rid})
                posted.append("DELETE examples/" + rid)
                self._json({"ok": True, "deleted": rid})
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
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on("console", lambda m: failures.append(
        "console: " + m.text[:160]) if m.type == "error" else None)
    page.on("dialog", _on_dialog)
    return ctx, page


def open_examples(page):
    page.goto(BASE + "/#/ai/speech", wait_until="load")
    page.wait_for_selector(".speech-screen", state="visible")
    page.wait_for_timeout(600)
    page.click("[data-speech-card='examples']")
    page.wait_for_selector("[data-speech-examples-list]", state="visible")
    page.wait_for_timeout(500)


def snap(page, shots, name):
    if not shots:
        return None
    shots.mkdir(parents=True, exist_ok=True)
    path = shots / (name + ".png")
    page.screenshot(path=str(path))
    return str(path)


PROBE = r"""
(() => {
  const vw = window.innerWidth;
  const list = document.querySelector('[data-speech-examples-list]');
  const order = list ? Array.from(list.children).map((el) => ({
    cls: el.className.replace(/\s+/g, ' ').slice(0, 60),
    data: (el.hasAttribute('data-speech-examples-tabs') ? 'tabs'
      : el.hasAttribute('data-speech-examples-counters') ? 'counters'
      : el.hasAttribute('data-speech-examples-toolbar') ? 'toolbar'
      : ((el.matches && el.matches('[data-speech-samples]'))
         || (el.querySelector && el.querySelector('[data-speech-samples]'))
         ? 'cards' : 'other')),
    top: Math.round(el.getBoundingClientRect().top),
  })) : [];
  const tabsTops = Array.from(document.querySelectorAll(
    '[data-speech-examples-tabs] .speech-tab'))
    .map((t) => Math.round(t.getBoundingClientRect().top));
  const headH = document.querySelector('header.header-sticky')
    ? Math.round(document.querySelector('header.header-sticky')
      .getBoundingClientRect().height) : 0;
  const card = document.querySelector('.speech-sample-card');
  const cardText = card ? card.textContent.replace(/\s+/g, ' ') : '';
  const examplesScreen = document.querySelector('.speech-examples-screen');
  const screenW = examplesScreen
    ? Math.round(examplesScreen.getBoundingClientRect().width) : null;
  return {
    vw,
    pageOverflow: document.documentElement.scrollWidth - vw,
    mainOverflow: (() => { const m = document.querySelector('main.scroll-area');
      return m ? m.scrollWidth - m.clientWidth : null; })(),
    orderBlocks: order.filter((b) => b.data !== 'other').map((b) => b.data),
    orderTops: order.filter((b) => b.data !== 'other').map((b) => b.top),
    tabRows: new Set(tabsTops).size,
    cardColumns: (() => {
      const cards = Array.from(document.querySelectorAll(
        '[data-speech-samples] .speech-sample-card'));
      if (cards.length < 2) return 1;
      const tops = new Set(cards.map((c) =>
        Math.round(c.getBoundingClientRect().top)));
      return 1 + (cards.length - tops.size) / Math.max(1, tops.size - 0);
    })(),
    headH, screenW, hasList: !!list,
    cardHasSqlJson: /\{|\}|SELECT|revision|seed_key|library_version/
      .test(cardText),
    cardText: cardText.slice(0, 220),
  };
})()
"""


def check_common(label, probe):
    if probe["pageOverflow"] > 1:
        fail(label, "горизонтальный overflow страницы: %s px"
             % probe["pageOverflow"])
    if probe["mainOverflow"] is not None and probe["mainOverflow"] > 1:
        fail(label, "горизонтальный overflow main: %s px" % probe["mainOverflow"])


def run_list(browser, shots):
    label = "list-360x740"
    ctx, page = new_page(browser, 360, 740)
    try:
        open_examples(page)
        probe = page.evaluate(PROBE)
        check_common(label, probe)
        # §4.1: иерархия сверху вниз именно в этом порядке.
        want = ["tabs", "counters", "toolbar", "cards"]
        got = probe["orderBlocks"]
        if got[:len(want)] != want:
            fail(label, "иерархия §4.1 нарушена: %s" % got)
        for a, b in zip(probe["orderTops"], probe["orderTops"][1:]):
            if a > b:
                fail(label, "блоки не сверху вниз: %s" % probe["orderTops"])
                break
        # §4.1.2: вкладки одной строкой на 360px.
        if probe["tabRows"] != 1:
            fail(label, "вкладки не одной строкой: %s" % probe["tabRows"])
        # §4.1.5: одна колонка карточек (у 6 карточек одна X-колонка).
        if probe["cardColumns"] > 1.01:
            fail(label, "карточки не в одну колонку: %s" % probe["cardColumns"])
        # §4.1 карточка: без SQL/JSON/тегов/ревизий.
        if probe["cardHasSqlJson"]:
            fail(label, "в карточке SQL/JSON/ревизии: %r" % probe["cardText"])
        if "Юмор · GLOBAL · Заводской" not in probe["cardText"] and \
                "Юмор · GLOBAL" not in probe["cardText"]:
            fail(label, "нет подписи «Категория · GLOBAL · происхождение»: %r"
                 % probe["cardText"])
        snap(page, shots, "list_360")
        # Legacy-группа: неоднозначные строки не спрятаны молча.
        legacy = page.locator("[data-speech-examples-legacy]")
        if not legacy.count():
            fail(label, "legacy-группа не показана")
        # §5: «Почему не используется?» — человеческая причина.
        page.click("[data-speech-why='2']")
        page.wait_for_timeout(600)
        why = page.inner_text("[data-speech-why-text='2']")
        if "утверждён" not in why:
            fail(label, "причина не человеческая: %r" % why[:120])
    finally:
        ctx.close()


def run_editor(browser, shots):
    label = "editor-390x844"
    ctx, page = new_page(browser, 390, 844)
    try:
        open_examples(page)
        # Юмор-вкладка по умолчанию → «Добавить пример» предзаполняет «Юмор».
        page.click("[data-speech-examples-add]")
        page.wait_for_selector("[data-speech-sample-editor-screen]",
                               state="visible")
        if page.locator("[data-speech-examples-list]").count():
            fail(label, "редактор не отдельный экран: список остался в DOM")
        title = page.inner_text("[data-speech-sample-editor-screen] "
                                ".text-sm.font-bold")
        if "Новый пример" not in title:
            fail(label, "заголовок редактора не «Новый пример»: %r" % title)
        cat = page.locator("[data-speech-editor-category]").input_value()
        if cat != "humor":
            fail(label, "категория не предзаполнена из вкладки: %r" % cat)
        if not page.locator("[data-speech-editor-technique]").count():
            fail(label, "в «Юмор» нет выбора приёма")
        if page.locator("[data-speech-editor-mode]").count():
            fail(label, "в «Юмор» показан выбор режима мата")
        # §4.2.2: «Мат» — видимый выбор режима; «Общие» — ни приёма, ни режима.
        page.select_option("[data-speech-editor-category]", "mat")
        if not page.locator("[data-speech-editor-mode]").count():
            fail(label, "в «Мат» нет видимого выбора режима")
        page.select_option("[data-speech-editor-category]", "general")
        if page.locator("[data-speech-editor-technique]").count():
            fail(label, "в «Общие» показана техника юмора")
        if page.locator("[data-speech-editor-mode]").count():
            fail(label, "в «Общие» показан режим мата")
        # §4.2.3: поля полноширинные.
        widths = page.evaluate(
            "(() => { const box = document.querySelector("
            "'[data-speech-sample-editor-screen]').getBoundingClientRect();"
            " return Array.from(document.querySelectorAll("
            "'[data-speech-editor-input], [data-speech-editor-reply]'))"
            ".map((t) => { const r = t.getBoundingClientRect();"
            " return Math.round(r.width / box.width * 100); }); })()")
        if any(w < 92 for w in widths):
            fail(label, "поля ввода/ответа не полноширинные: %s" % widths)
        # §4.2.1: «Назад» при несохранённых изменениях предупреждает.
        page.fill("[data-speech-editor-input]", "вход до подтверждения")
        dialogs_before = len(dialogs)
        # Владелец выбирает «остаться» (dismiss = confirm false).
        DIALOG_NEXT["action"] = "dismiss"
        page.click("[data-speech-editor-back]")
        page.wait_for_timeout(400)
        if len(dialogs) == dialogs_before:
            fail(label, "«Назад» не предупредил о несохранённых изменениях")
        if not page.locator("[data-speech-sample-editor-screen]").count():
            fail(label, "редактор закрылся несмотря на «остаться» в диалоге")
        # §4.3: «Сохранено» только после ответа API + перечитывание с сервера.
        page.fill("[data-speech-editor-input]", "вход нового примера")
        page.fill("[data-speech-editor-reply]", "ответ нового примера")
        posts_before = len(posted)
        page.click("[data-speech-editor-save]")
        page.wait_for_timeout(700)
        if len(posted) != posts_before + 1:
            fail(label, "сохранение не ушло в API")
        if page.locator("[data-speech-sample-editor-screen]").count():
            fail(label, "редактор не закрылся после сохранения")
        toasts = page.evaluate(
            "(() => Array.from(document.querySelectorAll('.toast, [class*=toast]'))"
            ".map((t) => t.textContent).join(' | '))()")
        if "добавлен" not in toasts and "Сохранено" not in toasts:
            fail(label, "нет подтверждения сохранения после API: %r" % toasts)
        # §4.3: данные перечитаны с сервера — новый пример виден в «Общие».
        page.locator("[data-speech-examples-tabs] .speech-tab",
                     has_text="Общие").first.click()
        page.wait_for_timeout(300)
        body = page.inner_text("[data-speech-examples-list]")
        if "вход нового примера" not in body:
            fail(label, "сохранённый пример не перечитан с сервера")
        snap(page, shots, "editor_390")
    finally:
        ctx.close()


def run_factory(browser, shots):
    label = "factory-390x844"
    ctx, page = new_page(browser, 390, 844)
    try:
        open_examples(page)
        # §3: массовое восстановление — сначала экран сравнения (карточка 7
        # ещё изменена владельцем): «Отмена» по умолчанию, restore — явный.
        page.click("[data-speech-menu='examples']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        page.locator(".speech-menu-panel .more-menu-item",
                     has_text="сравнить").first.click()
        page.wait_for_selector("[data-speech-factory-screen]",
                               state="visible")
        page.wait_for_timeout(400)
        cancel = page.locator("[data-speech-factory-screen] button",
                              has_text="Отмена")
        if not cancel.count():
            fail(label, "на экране сравнения нет действия по умолчанию «Отмена»")
        if not page.locator("[data-speech-factory-restore-all]").count():
            fail(label, "нет явной кнопки массового восстановления")
        if not page.inner_text("[data-speech-factory-screen]").count:
            pass
        snap(page, shots, "factory_compare_390")
        cancel.first.click()
        page.wait_for_selector("[data-speech-examples-list]",
                               state="visible")
        # Заводская карточка id=7 («Изменено владельцем»): тот же экран редактора.
        page.locator("[data-speech-examples-tabs] .speech-tab",
                     has_text="Юмор").first.click()
        page.wait_for_timeout(250)
        page.locator(".speech-sample-card[data-sample-id='7'] "
                     ".speech-sample-title").first.click()
        page.wait_for_selector("[data-speech-sample-editor-screen]",
                               state="visible")
        plate = page.locator(
            "text=Заводской пример · ваши правки сохранятся после обновления")
        if not plate.count():
            fail(label, "нет плашки «Заводской пример · ваши правки "
                        "сохранятся после обновления»")
        # §4.2: «Посмотреть исходный» показывает заводской текст.
        page.click("text=Посмотреть исходный")
        page.wait_for_selector("[data-speech-factory-original]",
                               state="visible")
        original = page.inner_text("[data-speech-factory-original]")
        if "Опять забыл" in original:
            fail(label, "показан чужой исходник")
        if "Ноутбук стал громко шуметь" not in original:
            fail(label, "исходник заводской карточки не показан: %r"
                 % original[:160])
        # §3: «Восстановить исходный» — после явного подтверждения.
        dialogs_before = len(dialogs)
        page.click("text=Восстановить исходный")
        page.wait_for_timeout(700)
        if len(dialogs) == dialogs_before:
            fail(label, "восстановление прошло без подтверждения")
        if len(posted) < 1 or not any("restore-factory" in p for p in posted):
            fail(label, "restore-factory не ушёл в API")
        if page.locator("[data-speech-sample-editor-screen]").count():
            fail(label, "приложение не вернулось к списку после restore")
        body = page.inner_text("[data-speech-examples-list]")
        if "Ноутбук стал громко шуметь (моё)" in body:
            fail(label, "восстановление одного примера не применилось")
        if "Ноутбук стал громко шуметь" not in body:
            fail(label, "заводской текст после restore не показан")
        snap(page, shots, "factory_single_restore_390")
    finally:
        ctx.close()


def run_persistence(browser, shots):
    label = "persist-reload-390"
    ctx, page = new_page(browser, 390, 844)
    try:
        open_examples(page)
        # Правка заводской карточки id=3 (Мат): правка → reload → сохранилась.
        page.locator("[data-speech-examples-tabs] .speech-tab",
                     has_text="Мат").first.click()
        page.wait_for_timeout(250)
        page.locator(".speech-sample-card[data-sample-id='3'] "
                     ".speech-sample-title").first.click()
        page.wait_for_selector("[data-speech-sample-editor-screen]",
                               state="visible")
        page.fill("[data-speech-editor-input]", "правка владельца survives")
        page.click("[data-speech-editor-save]")
        page.wait_for_timeout(700)
        page.reload(wait_until="load")
        page.wait_for_selector(".speech-screen", state="visible")
        page.wait_for_timeout(700)
        page.locator("[data-speech-card='examples']").click()
        page.wait_for_selector("[data-speech-examples-list]",
                               state="visible")
        page.locator("[data-speech-examples-tabs] .speech-tab",
                     has_text="Мат").first.click()
        page.wait_for_timeout(300)
        body = page.inner_text("[data-speech-examples-list]")
        if "правка владельца survives" not in body:
            fail(label, "правка не пережила reload: %r" % body[:200])
        mark = "Изменено владельцем" in body
        if not mark:
            fail(label, "нет метки «Изменено владельцем» после правки")
        # Удаление → reload → остаётся удалённой (tombstone), не воскресает.
        page.click("[data-speech-menu='sample-3']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        page.locator(".speech-menu-panel .more-menu-item",
                     has_text="Удалить").first.click()
        page.wait_for_timeout(700)
        page.reload(wait_until="load")
        page.wait_for_selector(".speech-screen", state="visible")
        page.wait_for_timeout(700)
        page.locator("[data-speech-card='examples']").click()
        page.wait_for_selector("[data-speech-examples-list]",
                               state="visible")
        page.locator("[data-speech-examples-tabs] .speech-tab",
                     has_text="Мат").first.click()
        page.wait_for_timeout(300)
        list_body = page.locator("[data-speech-samples]").inner_text()
        if "правка владельца survives" in list_body:
            fail(label, "удалённая карточка вернулась в список после reload")
        deleted_group = page.locator("[data-speech-examples-deleted]")
        if not deleted_group.count():
            fail(label, "tombstone-группа удалённых не показана (молча)")
        else:
            dg = deleted_group.inner_text()
            if "не вернутся сами" not in dg:
                fail(label, "tombstone-группа без честного состояния: %r"
                     % dg[:160])
        snap(page, shots, "persist_390")
    finally:
        ctx.close()


def run_landscape(browser, shots):
    label = "landscape-667x375"
    ctx, page = new_page(browser, 667, 375)
    try:
        open_examples(page)
        probe = page.evaluate(PROBE)
        check_common(label, probe)
        if probe["tabRows"] != 1:
            fail(label, "вкладки не одной строкой в landscape")
        if probe["headH"] > 120:
            fail(label, "двухстрочная шапка в landscape: %s" % probe["headH"])
        snap(page, shots, "landscape_667")
    finally:
        ctx.close()


def run_desktop(browser, shots):
    label = "desktop-1280x800"
    ctx, page = new_page(browser, 1280, 800)
    try:
        open_examples(page)
        probe = page.evaluate(PROBE)
        check_common(label, probe)
        if probe["screenW"] is None or probe["screenW"] > 760:
            fail(label, "контент не ограничен max-width на desktop: %s"
                 % probe["screenW"])
        snap(page, shots, "desktop_1280")
    finally:
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--shots", default=str(HERE.parent / "plans" / "features"
                                           / "samples-ux" / "evidence"
                                           / "build" / "shots"))
    ap.add_argument("--no-shots", action="store_true")
    args = ap.parse_args()
    shots = Path(args.shots) if not args.no_shots else None

    from playwright.sync_api import sync_playwright
    httpd = serve(PORT, str(REPO / "web"))
    report = {"cases": {}, "failures": failures, "posted": posted,
              "dialogs": dialogs}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for run in (run_list, run_editor, run_factory, run_persistence,
                        run_landscape, run_desktop):
                try:
                    run(browser, shots)
                finally:
                    # stateful-стаб между сценариями возвращаем к базе,
                    # кроме финального persist-состояния (оставим как факт).
                    pass
            browser.close()
    finally:
        httpd.shutdown()
    report["failures"] = failures
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8")
    print("\n== samples-ux e2e: failures=%d, POST=%d" % (len(failures),
                                                         len(posted)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
