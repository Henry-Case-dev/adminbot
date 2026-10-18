# -*- coding: utf-8 -*-
"""P0A-UX — «Речь и характер»: компактная витрина, сохранение, изоляция чатов.

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(route-стабы `/api/*` в playwright, Telegram SDK — route-mock; прецедент
`tools/ui_soul1_w6_speech_e2e.py`, `tests/ui_speech_mobile_entry_e2e.py`).

Сценарии (UX-план §9, строки P0A-UX-COMPACT/-HIER/-SAVE/-SCOPE):

  1. Витрина §2/§4-C1: 4 группы (Характер / Манера речи / Правила письма /
     Дополнительно); 10 карточек; 320px — 1 колонка, 360–412px — ровно 2;
     landscape и desktop — без горизонтального скролла; тач-цели ≥44px.
  2. §5.5/§4-C6: редактор Core — dirty-рамка, sticky «Не сохранено», разворот
     на мобиле (ввод не теряется), сохранение → POST + «Сохранено ✓».
  3. §5.2 (19/20/21): 409-валидация — человеческий текст как есть и без
     «конфликта версии», черновик на месте; 503 — «Повторить сохранение»
     и ввод не потерян; технический код (`write_error`) не показывается.
  4. §6.3: цель сохранения — на раздел (смена в «Характере» не меняет
     «Правила письма»); сохранение уходит с выбранным scope.
  5. §6.4 (22): смена чата с черновиком — подтверждение, раздел СБРОШЕН на
     витрину, правки чата A не показываются/не отправляются в чат B.

Запуск:
  .venv/Scripts/python.exe tests/ui_p0a_ux_speech_compact_e2e.py
  ... --shots <dir>  --json <path>

TEST-LIFECYCLE: CONTRACT owner=P0A-UX-COMPACT/-HIER/-SAVE (§2/§4/§5);
REGRESSION owner=P0A-UX-SCOPE (§6.4: изоляция чатов — данные и черновики
чужого чата не переносятся).
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

PORT = 8861
BASE = "http://127.0.0.1:%d" % PORT
CHAT_A = -100500
CHAT_B = -100600

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
    ("examples", "library_books", "Примеры", "Карточки примеров", "factory"),
    ("try", "science", "Попробовать", "Сравнение вариантов", "ready"),
    ("learning", "school", "Обучение", "Что бот подхватывает", "ready"),
]
ADVANCED = [
    ("all", "list_alt", "Все инструкции"),
    ("inspector", "fact_check", "Effective Prompt Inspector"),
    ("capabilities", "extension", "Возможности бота"),
]
CORE_TEXT = {
    str(CHAT_A): "КОНТЕНТ ЧАТА A — держим тон.",
    str(CHAT_B): "КОНТЕНТ ЧАТА B — другой чат.",
    "global": "ГЛОБАЛЬНЫЙ ХАРАКТЕР (заводской).",
}

POSTS = []          # реальные записи: (path, headers, body)
DIALOGS = []        # тексты подтверждений (guard при смене чата)
# Управляемые отказы: section → (status, detail)
FAIL = {"core": None, "style": None}
# Управляемое состояние стабов (сценарии «сохранить всё» §9.1).
STATE = {"examples_available": False, "can_edit": True,
         "learning_enabled": False, "style_rules": True}

EXAMPLE_ROW = {
    "id": 11, "technique": "deadpan", "input_text": "привет",
    "reply_text": "привет-привет", "owner_approved": False,
    "status": "active", "source_kind": "owner_manual", "scope": "global",
    "rudeness_level": 1, "library_version": "A", "uses_count": 2,
    "tags": ["тест"], "revision": 1, "context_note": "",
}

LESSON_ROW = {
    "lesson_id": "L1", "version": 2, "type": "humor_pref",
    "applied": True, "status": "active", "applications_count": 3,
    "confidence": {"trusted": True},
    "counters": {"success": 2, "failure": 0, "unknown": 1},
    "recommendation": "реже шутить в серьёзных темах",
    "applicability": "серьёзный контекст",
    "sources": {"policy": "p1", "proposal": "pr1", "validator": "v1"},
}


def _core(chat_key):
    text = CORE_TEXT[chat_key]
    return {
        "scope": "global" if chat_key == "global" else "chat",
        "chat_id": None if chat_key == "global" else int(chat_key),
        "inheritance": "global" if chat_key == "global" else "chat",
        "can_edit": STATE["can_edit"],
        "doc_key": "character.core",
        "permanent_note": "Постоянный характер задаётся здесь.",
        "block_ids": {"full": "core.personality",
                      "compact": "core.personality.compact"},
        "selection": {"level": "compact", "reason": "owner_setting",
                      "revision": "r7.abcdef012345"},
        "document": {"enabled": True, "detail_level": "compact", "revision": 7,
                     "updated_at": "2026-10-18T10:00:00+00:00"},
        "factory": {"full_revision": "fac:040", "compact_revision": "fac:041"},
        "editions": {
            "full": {"text": CORE_TEXT[chat_key], "withheld": False,
                     "source": "global" if chat_key == "global" else "chat",
                     "differs_from_factory": True,
                     "factory_revision": "fac:040"},
            "compact": {"text": CORE_TEXT[chat_key], "withheld": False,
                        "source": "global" if chat_key == "global" else "chat",
                        "differs_from_factory": True,
                        "factory_revision": "fac:041"},
        },
        "history": [{"kind": "owner_edit", "scope": "global", "chars": 30,
                     "sha256_12": "aaaaaaaaaaaa",
                     "updated_at": "2026-10-17T21:55:00+00:00",
                     "revision": "r7.abcdef012345"}],
        "diff": {"compact": {"changed": {"before": "было", "after": "стало"},
                             "same": False},
                 "full": {"changed": {"before": "", "after": ""}, "same": True}},
    }


def _style(chat_key):
    return {
        "scope": "global" if chat_key == "global" else "chat",
        "chat_id": None if chat_key == "global" else int(chat_key),
        "can_edit": STATE["can_edit"],
        "revision": 3,
        "context": "regular", "source": "owner",
        "skip_reason": "style_policy_absent",
        "conflicts": [], "precedence": ["safety_facts_channel"],
        "hint": "", "hint_tokens": 0,
        "document": {"global_present": True,
                     "chat_present": chat_key != "global",
                     "global_revision": 3, "chat_revision": 1,
                     "global_issues": [], "chat_issues": [],
                     "inheritance": "chat" if chat_key != "global" else "global"},
        "rules": [] if not STATE["style_rules"] else [
            {"id": "trailing_period.hard.strip", "kind": "trailing_period",
             "strictness": "hard", "scope": "global", "enabled": True,
             "params": {"ellipsis": "keep"},
             "reason": "владелец просил"}],
        "soft_instructions": [],
        "rule_kinds": [{"kind": "trailing_period",
                        "title_ru": "Точка в конце сообщения",
                        "purpose": "Убирать завершающую точку.",
                        "params": {"ellipsis": "keep|strip"},
                        "hard_effect": "точка снимается детерминированно",
                        "soft_effect": "инструкция Writer"}],
        "available_presets": [{"id": "no_trailing_period",
                               "title_ru": "Без точек на конце",
                               "description": "шаблон"}],
        "preset_documents": {
            "no_trailing_period": {
                "rules": [{"id": "trailing_period.hard.strip",
                           "kind": "trailing_period",
                           "strictness": "hard", "scope": "global",
                           "enabled": True,
                           "params": {"ellipsis": "strip"}}],
                "soft_instructions": []}},
        "history": [],
    }


def _expression(chat_key):
    options = [{"value": "inherit", "label": "как настроено"},
               {"value": "high", "label": "чаще"},
               {"value": "off", "label": "выключено"}]
    return {
        "scope": "global" if chat_key == "global" else "chat",
        "chat_id": None if chat_key == "global" else int(chat_key),
        "inheritance": "chat" if chat_key != "global" else "global",
        "notes": "Мягкая настройка подачи.", "runtime_wired": True,
        "runtime_note": "", "can_edit": STATE["can_edit"],
        "values": {"wit": "inherit", "sharpness": "inherit",
                   "profanity": "inherit", "verbosity": "inherit"},
        "note": "",
        "controls": [{"id": "wit", "label": "Остроумие", "question": "сколько?",
                      "effect": "мягко", "options": options},
                     {"id": "sharpness", "label": "Резкость", "question": "?"},
                     {"id": "profanity", "label": "Мат", "question": "?"},
                     {"id": "verbosity", "label": "Развёрнутость", "question": "?"}],
    }


def _humor(chat_key):
    return {
        "scope": "global" if chat_key == "global" else "chat",
        "can_edit": STATE["can_edit"],
        "craft": {"gate": True, "enabled": True, "note": "ремесло",
                  "source": "global", "revision": 2},
        "gates": {"humor_library_enabled": True,
                  "humor_feedback_enabled": STATE["learning_enabled"]},
        "library": {"note": "примеры шуток"},
        "techniques": [{"id": "deadpan", "title": "Дедпан", "enabled": True,
                        "samples": 3, "layer_tokens": 40,
                        "description": "ровный тон", "reason": "humor_ready",
                        "owner_enabled": True}],
        "technique_preview_note": "проверка без модели",
    }


def _examples(chat_key):
    available = STATE["examples_available"]
    items = [dict(EXAMPLE_ROW)] if available else []
    return {
        "scope": "global" if chat_key == "global" else "chat",
        "available": available,
        "status": ("implemented" if available
                   else "unavailable"),
        "count": len(items),
        "note": "библиотека примеров",
        "reason": None if available else "read_error",
        "techniques": [{"id": "deadpan", "title": "Дедпан"},
                       {"id": "other", "title": "прочие"}],
        "items": items,
        "telemetry": {"approved": 0, "proposed": len(items),
                      "by_version": {"A": len(items)}},
        "starter": {"expected": 5, "seeded": 0},
        "ab": {"pinned": "A"},
        "policy": {"enabled": True, "ab_enabled": True, "max_items": 2,
                   "max_tokens": 300, "diversity_min_distance": 0.3,
                   "recency_penalty": 0.2, "ab_versions": ["A", "B"]},
        "policy_source": "owner",
        "runtime_note": "примеры попадают в слои только по правилам отбора",
        "entity_fields": [], "can_edit": STATE["can_edit"],
    }


def _learning(chat_key):
    enabled = STATE["learning_enabled"]
    return {
        "note": "обучение по наблюдениям", "can_manage": True,
        "humor_feedback": {
            "enabled": enabled,
            "available": enabled,
            "reason": None if enabled else "humor_feedback_disabled",
            "paused": False,
            "note": "контур выключен",
            "sends": 4 if enabled else 0,
            "unknown_windows": 1 if enabled else 0,
            "policy": "owner" if enabled else "",
            "signals": ({"praise": 2, "laugh": 1} if enabled else {}),
            "decay_note": "свежесть учитывается",
            "entries": ([{"lesson_id": "H1", "technique": "deadpan",
                          "direction": "weaken", "status": "active",
                          "decay": 0.5, "influence": "реже"}]
                        if enabled else []),
            "can_manage": STATE["can_edit"], "scenarios": []},
        "lessons": {"state": "implemented", "count": 1,
                    "items": [dict(LESSON_ROW)]},
    }


def _overview(chat_key):
    chat_id = None if chat_key == "global" else int(chat_key)
    return {
        "scope": "global" if chat_key == "global" else "chat",
        "chat_id": chat_id,
        "inheritance": "global" if chat_key == "global" else "chat",
        "gates": {"character_core_enabled": True,
                  "unified_composer_enabled": True,
                  "speech_style_policy_enabled": True},
        "sections": [
            {"id": sid, "icon": icon, "title": title, "subtitle": sub,
             "state": state, "detail": "человеческая строка", "ready": True}
            for (sid, icon, title, sub, state) in SECTIONS],
        "advanced": [
            {"id": sid, "icon": icon, "title": title,
             "subtitle": "технический раздел", "ready": True}
            for (sid, icon, title) in ADVANCED],
        "registry": {"blocks": 12, "version": "reg-1", "factory_set": "fs"},
        "can_edit": True,
    }


def payload_for(name, chat_key):
    if name == "overview":
        return _overview(chat_key)
    if name == "core":
        return _core(chat_key)
    if name == "style":
        return _style(chat_key)
    if name == "expression":
        return _expression(chat_key)
    if name == "humor":
        return _humor(chat_key)
    if name == "examples":
        return _examples(chat_key)
    if name == "learning":
        return _learning(chat_key)
    if name == "blocks":
        return {"blocks": [], "families": [], "stale_values": 0}
    if name == "capabilities":
        return {"capabilities": [], "trace": [], "trace_note": "пусто",
                "trace_not_chosen": [], "chat_id": None}
    if name == "inspector":
        return {"last_run_present": False, "last_run_note": "",
                "retention": "retention", "masked": True,
                "preview": {"manifest_id": "m1", "tokens_total": 5,
                            "layer_order": True, "versions": {},
                            "conflicts": [], "layers": [],
                            "system_masked": "masked", "preview_note": ""},
                "sent": {},
                "core": {"level": "compact", "reason": "", "active_revision": "",
                         "chars": 0, "factory_revisions": {}}}
    if name == "access/me":
        return {"is_global_admin": True, "effective_permissions": None}
    if name == "access/chats":
        return [{"chat_id": CHAT_A, "title": "Чат A", "is_dm": False,
                 "access": "admin", "is_active": True},
                {"chat_id": CHAT_B, "title": "Чат B", "is_dm": False,
                 "access": "admin", "is_active": True}]
    return {}


def make_api_handler():
    def _handler(route):
        req = route.request
        url = req.url.split("?")[0]
        method = req.method
        chat_header = (req.headers or {}).get("x-chat-id")
        chat_key = chat_header if chat_header else "global"
        if "/api/memory/lessons/action" in url and method == "POST":
            body = {}
            try:
                body = json.loads(req.post_data or "{}")
            except Exception:  # noqa: BLE001
                body = {"raw": req.post_data}
            POSTS.append({"path": "memory/lessons/action",
                          "chat": chat_key, "body": body})
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "status": "suspended"}))
            return
        if "/api/speech/" in url:
            name = url.rsplit("/api/speech/", 1)[1]
            if method in ("POST", "DELETE"):
                body = {}
                try:
                    body = json.loads(req.post_data or "{}")
                except Exception:  # noqa: BLE001
                    body = {"raw": req.post_data}
                POSTS.append({"path": name,
                              "chat": chat_key,
                              "method": method,
                              "body": body})
                fail = None
                if name.startswith("block/") and FAIL.get("core"):
                    fail = FAIL["core"]
                elif name == "style" and FAIL.get("style"):
                    fail = FAIL["style"]
                if fail:
                    status, detail = fail
                    route.fulfill(status=status,
                                  content_type="application/json",
                                  body=json.dumps({"detail": detail},
                                                  ensure_ascii=False))
                    return
                if name.startswith("block/"):
                    route.fulfill(
                        status=200, content_type="application/json",
                        body=json.dumps({"ok": True, "block_id": name,
                                         "result": {"applied": True,
                                                    "revision": "act:1"}}))
                    return
                if name == "humor/craft":
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"ok": True}))
                    return
                if name == "humor/technique/test":
                    route.fulfill(
                        status=200, content_type="application/json",
                        body=json.dumps({
                            "ok": True, "title": "Дедпан",
                            "extra_llm_calls": 0,
                            "selection_reason": "humor_ready",
                            "layer_tokens": 40, "layer_revision": "r1",
                            "source": "global",
                            "layer_text_masked": "слой (masked)",
                            "note": "модель не вызывалась"}))
                    return
                if name == "examples/why":
                    route.fulfill(
                        status=200, content_type="application/json",
                        body=json.dumps({
                            "ok": True, "selected": [], "excluded": [],
                            "tokens_estimate": 0, "library_version": "A",
                            "policy_source": "owner"}))
                    return
                if name.startswith("examples"):
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"ok": True, "seeded": 5,
                                                   "skipped": 0}))
                    return
                if name == "style":
                    route.fulfill(
                        status=200, content_type="application/json",
                        body=json.dumps({"ok": True,
                                         "view": payload_for("style",
                                                             chat_key)}))
                    return
                if name == "expression":
                    route.fulfill(
                        status=200, content_type="application/json",
                        body=json.dumps({"ok": True,
                                         "view": payload_for("expression",
                                                             chat_key)}))
                    return
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"ok": True}))
                return
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload_for(name, chat_key),
                                          ensure_ascii=False))
            return
        if url.endswith("/api/access/me") or url.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload_for(
                              url.rsplit("/api/", 1)[-1], chat_key),
                              ensure_ascii=False))
            return
        # остальные разделы MiniApp — базовые стабы матрицы (как в
        # ui_speech_mobile_entry_e2e / ui_soul1_w6_speech_e2e).
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url), ensure_ascii=False))
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


def new_page(browser, width, height, shots=None, chat=None):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430, has_touch=width <= 430)
    if chat is not None:
        ctx.add_init_script(
            "try { localStorage.setItem('adminbot.active_chat_id', '%s'); }"
            " catch (e) {}" % chat)
    ctx.route("**/api/**", make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(
                  status=200, content_type="application/javascript",
                  body=SDK_STUB))
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on("dialog", lambda d: (DIALOGS.append(d.message[:300]), d.accept()))
    return ctx, page


def snap(page, shots, name):
    if shots:
        os.makedirs(shots, exist_ok=True)
        page.screenshot(path=os.path.join(shots, name + ".png"))


PROBE = r"""
(() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const grid = document.querySelector('.speech-grid');
  const cols = grid
    ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0;
  const root = document.querySelector('.speech-screen');
  const small = [];
  let minTap = null;
  if (root) {
    const target = (el) => (el.tagName === 'INPUT'
      && (el.type === 'checkbox' || el.type === 'radio'))
      ? (el.closest('label') || el) : el;
    root.querySelectorAll('button, select, input, textarea, summary, [role="tab"]')
      .forEach((el) => {
        const r = target(el).getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return;
        const m = Math.min(r.width, r.height);
        minTap = (minTap === null) ? m : Math.min(minTap, m);
        if (r.height < 44 || r.width < 44) small.push({
          t: strip(el.textContent).slice(0, 40), h: Math.round(r.height),
          w: Math.round(r.width), aria: el.getAttribute('aria-label') });
      });
  }
  return {
    hash: location.hash,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    groups: Array.from(document.querySelectorAll('.speech-group-title'))
      .map((x) => strip(x.textContent)),
    cards: Array.from(document.querySelectorAll('[data-speech-card]'))
      .map((x) => x.getAttribute('data-speech-card')),
    cols,
    minTap: minTap === null ? null : Math.round(minTap),
    small: small.slice(0, 6),
    screenVisible: !!root && root.offsetParent !== null,
    sectionOpen: !!document.querySelector('.speech-section'),
  };
})()
"""


def check_layout(page, label, width, exp_cols):
    data = page.evaluate(PROBE)
    notes.append({"label": label, "probe": data})
    if data["overflow"] > 1:
        fail(label, "горизонтальный overflow: %d px" % data["overflow"])
    if not data["screenVisible"]:
        fail(label, "экран «Речь и характер» не отрисован")
    if data["hash"] != "#/ai/speech":
        fail(label, "не на #/ai/speech: %s" % data["hash"])
    if len(data["groups"]) != 4:
        fail(label, "групп витрины: %d (%s)" % (len(data["groups"]),
                                                data["groups"]))
    else:
        for want in ("1. Характер", "2. Манера речи", "3. Правила письма",
                     "4. Дополнительно"):
            if not any(want in g for g in data["groups"]):
                fail(label, "нет группы «%s»: %s" % (want, data["groups"]))
    if sorted(data["cards"]) != sorted([s[0] for s in SECTIONS]
                                       + [a[0] for a in ADVANCED]):
        fail(label, "состав карточек витрины изменился: %s" % data["cards"])
    if exp_cols == "one" and data["cols"] > 1:
        fail(label, "ожидалась 1 колонка, получено %d" % data["cols"])
    if exp_cols == "two" and data["cols"] != 2:
        fail(label, "ожидалось ровно 2 колонки, получено %d" % data["cols"])
    if exp_cols == "auto" and data["cols"] < 2:
        fail(label, "ожидалось ≥2 колонок, получено %d" % data["cols"])
    if data["minTap"] is not None and data["minTap"] < 44:
        fail(label, "тач-цель < 44px: %s" % data["small"])
    return data


def open_speech(page):
    page.goto(BASE + "/#/ai/speech", wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_selector(".speech-screen", state="visible")
    page.wait_for_timeout(600)


def run_layout(browser, width, height, label, exp_cols, shots):
    ctx, page = new_page(browser, width, height, shots)
    try:
        open_speech(page)
        check_layout(page, label, width, exp_cols)
        snap(page, shots, "store_%s" % label)
        # Открываемся в раздел «Характер» — редактор и меню на месте.
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(300)
        data = page.evaluate(PROBE)
        notes.append({"label": label + "/core", "probe": data})
        if data["overflow"] > 1:
            fail(label + "/core", "overflow в разделе: %d" % data["overflow"])
        if data["minTap"] is not None and data["minTap"] < 44:
            fail(label + "/core", "тач-цель < 44px: %s" % data["small"])
        snap(page, shots, "core_%s" % label)
        # ⋯-меню раздела открывается и закрывается по пункту/backdrop.
        page.click("[data-speech-menu='core']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        items = page.evaluate(
            "(() => Array.from(document.querySelectorAll"
            "('.speech-menu-panel .more-menu-item'))"
            ".map((x) => x.textContent.replace(/\\s+/g, ' ').trim()))()")
        notes.append({"label": label + "/menu", "items": items})
        for want in ("Показать diff с заводским", "Обновить",
                     "Вернуть заводской"):
            if not any(want in it for it in items):
                fail(label, "в ⋯-меню нет пункта «%s»: %s" % (want, items))
        snap(page, shots, "menu_%s" % label)
        page.click(".speech-menu-backdrop", position={"x": 5, "y": 5})
        page.wait_for_timeout(200)
        if page.locator(".speech-menu-panel").count():
            fail(label, "⋯-меню не закрылось по backdrop")
        # §4-C6: «Развернуть» — на мобиле/landscape, скрыт на десктопе.
        expand_visible = page.evaluate(
            "(() => { const b = document.querySelector('.speech-expand-btn');"
            " return !!b && b.offsetParent !== null; })()")
        expect_expand = width <= 599 or (width > height and height <= 480)
        if expand_visible != expect_expand:
            fail(label, "«Развернуть»: видимость %s, ожидалось %s"
                 % (expand_visible, expect_expand))
        if expect_expand:
            page.click(".speech-expand-btn")
            page.wait_for_selector(".speech-fullscreen", state="visible")
            page.fill(".speech-fullscreen textarea", "строка из полного экрана")
            page.click(".speech-fullscreen .btn-ghost")
            page.wait_for_timeout(200)
            if page.locator(".speech-fullscreen").count():
                fail(label, "полноэкранный редактор не закрылся")
            val = page.input_value(".speech-section .speech-editor")
            if "строка из полного экрана" not in val:
                fail(label, "ввод из полноэкранного редактора потерян")
            snap(page, shots, "fullscreen_%s" % label)
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
    finally:
        ctx.close()


def run_save_flows(browser, shots):
    label = "save-390"
    ctx, page = new_page(browser, 390, 844, shots, chat=CHAT_A)
    try:
        open_speech(page)
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(300)
        # §5.3: правка → dirty-рамка, «черновик — … редакция», savebar.
        editor = page.locator(".speech-section .speech-editor").first
        editor.click()
        editor.type("\nПроверка P0A-UX.", delay=3)
        if "dirty" not in page.evaluate(
                "document.querySelector('.speech-section .speech-editor')"
                ".className"):
            fail(label, "редактор без dirty-рамки после ввода")
        if not page.locator("[data-speech-core-dirty]").count():
            fail(label, "нет бейджа «черновик» у редакции")
        if not page.locator("[data-speech-savebar]").count():
            fail(label, "нет sticky-save панели при dirty")
        savebar_box = page.locator("[data-speech-savebar]").bounding_box()
        if savebar_box and savebar_box["y"] + savebar_box["height"] > 844 + 1:
            fail(label, "savebar уехал за вьюпорт: %s" % savebar_box)
        if not page.locator(".speech-head [data-speech-dirty-count]").count():
            fail(label, "в шапке нет бейджа «Есть несохранённые изменения»")
        snap(page, shots, "dirty_390")

        # §5.5: успешное сохранение → POST с scope «этот чат» (активен чат A),
        # dirty гаснет, появляется «Сохранено ✓».
        before = len(POSTS)
        page.click("[data-speech-savebar] .btn-accent")
        page.wait_for_timeout(800)
        if len(POSTS) != before + 1:
            fail(label, "сохранение не ушло в API (%d → %d)"
                 % (before, len(POSTS)))
        else:
            rec = POSTS[-1]
            if rec["body"].get("scope") != "chat":
                fail(label, "scope сохранения не «chat»: %s" % rec["body"])
            if rec["chat"] != str(CHAT_A):
                fail(label, "POST ушёл не в чат A: %s" % rec["chat"])
        if page.locator("[data-speech-core-dirty]").count():
            fail(label, "dirty не погас после успеха")
        if not page.locator("[data-speech-saved]").count():
            fail(label, "нет строки «Сохранено ✓» после успеха")
        if not page.locator("[data-speech-savebar]").count():
            fail(label, "savebar исчез вместе с «Сохранено ✓» (10 с)")
        snap(page, shots, "saved_390")

        # §5.2/503: тост человеческий, ввод и «Повторить сохранение» на месте.
        FAIL["core"] = (503, "не удалось сохранить: постоянное хранилище "
                             "недоступно, попробуйте позже")
        editor = page.locator(".speech-section .speech-editor").first
        editor.click()
        editor.type(" ещё раз", delay=3)
        value_before = page.evaluate(
            "document.querySelector('.speech-section .speech-editor').value")
        page.click("[data-speech-savebar] .btn-accent")
        page.wait_for_timeout(800)
        toasts = page.evaluate(
            "(() => Array.from(document.querySelectorAll"
            "('.toast, [class*=toast]'))"
            ".map((t) => t.textContent.replace(/\\s+/g,' ').trim()))()")
        if not any("постоянное хранилище недоступно" in t for t in toasts):
            fail(label, "503: нет человеческого текста в тосте: %s" % toasts)
        if not page.locator("[data-speech-savebar] .btn-ghost").count():
            fail(label, "503: нет «Повторить сохранение»")
        value_after = page.evaluate(
            "document.querySelector('.speech-section .speech-editor').value")
        if value_after != value_before:
            fail(label, "503: черновик потерян")
        snap(page, shots, "error503_390")
        # Повтор после восстановления хранилища.
        FAIL["core"] = None
        before = len(POSTS)
        page.click("[data-speech-savebar] .btn-ghost")
        page.wait_for_timeout(800)
        if len(POSTS) != before + 1:
            fail(label, "«Повторить сохранение» не отправил запрос")

        # TJ-21: технический код не показывается как текст ошибки.
        FAIL["core"] = (500, "write_error")
        editor = page.locator(".speech-section .speech-editor").first
        editor.click()
        editor.type(" x", delay=3)
        page.click("[data-speech-savebar] .btn-accent")
        page.wait_for_timeout(800)
        toasts = page.evaluate(
            "(() => Array.from(document.querySelectorAll"
            "('.toast, [class*=toast]'))"
            ".map((t) => t.textContent.replace(/\\s+/g,' ').trim()))()")
        if any("write_error" in t for t in toasts):
            fail(label, "TJ-21: код write_error утёк в тост: %s" % toasts)
        if not any("постоянное хранилище недоступно" in t for t in toasts):
            fail(label, "TJ-21: нет человеческой причины для write_error: %s"
                 % toasts)
        FAIL["core"] = None

        # §5.2/409: валидация — текст detail как есть, БЕЗ «конфликта версии»,
        # черновик и форма на месте.
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='style']")
        page.wait_for_selector(".speech-rule", state="visible")
        page.wait_for_timeout(300)
        page.click(".speech-rule input[type=checkbox]")
        FAIL["style"] = (409, "документ не прошёл проверку: неизвестный kind")
        page.click(".speech-section .btn-accent")
        page.wait_for_timeout(800)
        section_text = page.inner_text(".speech-section")
        toasts = page.evaluate(
            "(() => Array.from(document.querySelectorAll"
            "('.toast, [class*=toast]'))"
            ".map((t) => t.textContent.replace(/\\s+/g,' ').trim()))()")
        if not any("документ не прошёл проверку" in t for t in toasts):
            fail(label, "409: нет текста валидации сервера: %s" % toasts)
        if any("конфликт версии" in t.lower() for t in toasts):
            fail(label, "409-валидация названа «конфликтом версии»: %s" % toasts)
        if not page.locator("[data-speech-style-dirty]").count():
            fail(label, "409: черновик правил сброшен")
        if "черновик" not in section_text:
            fail(label, "409: в разделе пропала пометка черновика")
        FAIL["style"] = None
        snap(page, shots, "error409_390")
    finally:
        ctx.close()


def run_scope_and_chat_isolation(browser, shots):
    label = "scope-390"
    ctx, page = new_page(browser, 390, 844, shots, chat=CHAT_A)
    try:
        open_speech(page)
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(400)
        # §6.3: при активном чате дефолт цели — «Только этот чат»; смена
        # в «Характере» НЕ меняет цель в «Правилах письма».
        core_scope = page.input_value(
            ".speech-section select[aria-label='Куда сохранить правку характера']")
        if core_scope != "chat":
            fail(label, "дефолт scope в «Характере»: %s (ожидался chat)"
                 % core_scope)
        page.select_option(
            ".speech-section select[aria-label='Куда сохранить правку характера']",
            "global")
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='style']")
        page.wait_for_selector(".speech-rule", state="visible")
        page.wait_for_timeout(300)
        style_scope = page.evaluate(
            "(() => { const s = document.querySelector('.speech-section "
            "select[aria-label=\"Куда сохранить правку стиля\"]'); "
            "return s ? s.value : null; })()")
        if style_scope != "chat":
            fail(label, "смена scope в «Характере» изменила «Правила письма»: %s"
                 % style_scope)
        # Сохранение стиля уходит с scope чата, несмотря на выбор в Характере.
        page.click(".speech-rule input[type=checkbox]")
        before = len(POSTS)
        page.click(".speech-section .btn-accent")
        page.wait_for_timeout(800)
        if len(POSTS) != before + 1:
            fail(label, "сохранение стиля не ушло (%d → %d)"
                 % (before, len(POSTS)))
        else:
            rec = POSTS[-1]
            if rec["body"].get("scope") != "chat":
                fail(label, "стиль сохранён с чужим scope: %s" % rec["body"])

        # §6.4 (REGRESSION): смена чата с черновиком — подтверждение, сброс
        # раздела, чужие данные не показываются/не отправляются.
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(300)
        editor = page.locator(".speech-section .speech-editor").first
        editor.click()
        editor.type(" ЧЕРНОВИК A", delay=3)
        posts_before = len(POSTS)
        dialogs_before = len(DIALOGS)
        page.click(".scope-trigger")
        page.wait_for_selector(".scope-panel", state="visible")
        page.locator(".scope-option", has_text="Чат B").first.click()
        page.wait_for_timeout(900)
        if len(DIALOGS) == dialogs_before:
            fail(label, "смена чата с черновиком прошла без подтверждения")
        elif "несохран" not in DIALOGS[-1].lower():
            fail(label, "текст подтверждения не про несохранённые правки: %s"
                 % DIALOGS[-1])
        if len(POSTS) != posts_before:
            fail(label, "при смене чата ушёл POST: %s" % POSTS[posts_before:])
        if not page.locator(".speech-grid").count():
            fail(label, "после смены чата раздел не сброшен на витрину")
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(500)
        text_b = page.evaluate(
            "document.querySelector('.speech-section .speech-editor').value")
        if "ЧЕРНОВИК A" in text_b:
            fail(label, "черновик чата A показан в чате B")
        if "КОНТЕНТ ЧАТА B" not in text_b:
            fail(label, "в чате B показан не его текст: %s" % text_b[:80])
        snap(page, shots, "chat_switch_390")
    finally:
        ctx.close()


def click_menu_item(page, text):
    page.locator(".speech-menu-panel .more-menu-item",
                 has_text=text).first.click()
    page.wait_for_timeout(250)


def run_core_extras(browser, shots):
    """§9.1 п.2/3/5: раздельные черновики редакций, meta-selects, откат."""
    label = "core-extras"
    ctx, page = new_page(browser, 390, 844, shots, chat=CHAT_A)
    try:
        open_speech(page)
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(300)
        # §5.4: каждая редакция — свой черновик; ввод не теряется (§9.1 п.2).
        # Стартуем с «Полной редакции» (payload открывает компактную).
        page.locator(".speech-tab", has_text="Полная редакция").first.click()
        page.wait_for_timeout(300)
        page.locator(".speech-section .speech-editor").first.fill("ПОЛНАЯ-ПРАВКА")
        page.locator(".speech-tab", has_text="Компактная").first.click()
        page.wait_for_timeout(300)
        compact_val = page.input_value(".speech-section .speech-editor")
        if "ПОЛНАЯ-ПРАВКА" in compact_val:
            fail(label, "черновик полной редакции протёк в компактную")
        page.locator(".speech-section .speech-editor").first.fill("КОМПАКТНАЯ-ПРАВКА")
        page.locator(".speech-tab", has_text="Полная").first.click()
        page.wait_for_timeout(300)
        if page.input_value(".speech-section .speech-editor") != "ПОЛНАЯ-ПРАВКА":
            fail(label, "черновик полной редакции потерян при переключении")
        page.locator(".speech-tab", has_text="Компактная").first.click()
        page.wait_for_timeout(300)
        if page.input_value(".speech-section .speech-editor") != "КОМПАКТНАЯ-ПРАВКА":
            fail(label, "черновик компактной редакции потерян при переключении")
        badge = page.inner_text("[data-speech-core-dirty]")
        if "полная" not in badge or "компактная" not in badge:
            fail(label, "бейдж черновика не называет редакции: %s" % badge)
        snap(page, shots, "per_edition_draft_390")
        # §9.1 п.3: режим по умолчанию и «Core включён» → POST core/meta.
        before = len(POSTS)
        page.select_option(
            ".speech-section select[aria-label='Редакция по умолчанию']", "full")
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "core/meta" \
                or POSTS[-1]["body"].get("detail_level") != "full":
            fail(label, "смена режима по умолчанию не ушла в core/meta: %s"
                 % (POSTS[before:]))
        before = len(POSTS)
        page.locator(".speech-section input[type=checkbox]").first.set_checked(False)
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "core/meta" \
                or POSTS[-1]["body"].get("enabled") is not False:
            fail(label, "выключение Core не ушло в core/meta: %s"
                 % (POSTS[before:]))
        # §9.1 п.5: история версий и «Откатить» — в «Дополнительно».
        page.locator("details summary",
                     has_text="Дополнительно: версии и откат").first.click()
        page.wait_for_timeout(200)
        before = len(POSTS)
        page.locator("details button", has_text="Откатить").first.click()
        page.wait_for_timeout(800)
        if len(POSTS) != before + 1 or not POSTS[-1]["path"].endswith("/rollback") \
                or POSTS[-1]["body"].get("sha256_12") != "aaaaaaaaaaaa":
            fail(label, "откат не ушёл в API: %s" % (POSTS[before:]))
        snap(page, shots, "core_history_390")
    finally:
        ctx.close()


def run_humor_and_learning(browser, shots):
    """§9.1 п.11/14: ремесло/приёмы/проверка приёма; реакции и уроки."""
    label = "humor-learning"
    STATE["learning_enabled"] = True
    ctx, page = new_page(browser, 390, 844, shots, chat=CHAT_A)
    try:
        open_speech(page)
        page.click("[data-speech-card='humor']")
        page.wait_for_selector("[data-speech-techniques]", state="visible")
        page.wait_for_timeout(400)
        before = len(POSTS)
        page.locator(".speech-section button", has_text="Выключить ремесло").first.click()
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "humor/craft" \
                or POSTS[-1]["body"].get("enabled") is not False:
            fail(label, "ремесло юмора не ушло в API: %s" % (POSTS[before:]))
        before = len(POSTS)
        page.locator(".speech-section button", has_text="Выключить приём").first.click()
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or "deadpan" not in (
                POSTS[-1]["body"].get("disabled_techniques") or []):
            fail(label, "отключение приёма не ушло в API: %s" % (POSTS[before:]))
        before = len(POSTS)
        page.locator(".speech-section button", has_text="Проверить приём").first.click()
        page.wait_for_timeout(800)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "humor/technique/test":
            fail(label, "проверка приёма не ушла в API: %s" % (POSTS[before:]))
        if not page.locator("[data-speech-humor-probe]").count():
            fail(label, "результат проверки приёма не показан (диагностика)")
        snap(page, shots, "humor_probe_390")
        # Обучение: пауза сбора реакций и пауза урока.
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='learning']")
        page.wait_for_selector("[data-speech-humor-feedback]", state="visible")
        page.wait_for_timeout(500)
        before = len(POSTS)
        page.locator(".speech-section button", has_text="Пауза сбора").first.click()
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or POSTS[-1]["body"].get("action") != "pause":
            fail(label, "пауза реакций не ушла в API: %s" % (POSTS[before:]))
        if not page.locator(".speech-lesson").count():
            fail(label, "уроки опыта не показаны")
        before = len(POSTS)
        page.locator(".speech-lesson button", has_text="Пауза").first.click()
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 \
                or POSTS[-1]["path"] != "memory/lessons/action" \
                or POSTS[-1]["body"].get("action") != "suspend":
            fail(label, "пауза урока не ушла в API: %s" % (POSTS[before:]))
        snap(page, shots, "learning_390")
    finally:
        STATE["learning_enabled"] = False
        ctx.close()


def run_examples_crud(browser, shots):
    """§9.1 п.12: примеры — добавить/эталон/архив/удалить, подборка, отбор,
    политика (полный CRUD сохранён при переносе в «Дополнительно»)."""
    label = "examples"
    STATE["examples_available"] = True
    ctx, page = new_page(browser, 390, 844, shots, chat=CHAT_A)
    try:
        open_speech(page)
        page.click("[data-speech-card='examples']")
        page.wait_for_selector("[data-speech-samples]", state="visible")
        page.wait_for_timeout(400)
        page.click("[data-speech-menu='sample-11']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        items = page.evaluate(
            "(() => Array.from(document.querySelectorAll"
            "('.speech-menu-panel .more-menu-item'))"
            ".map((x) => x.textContent.replace(/\\s+/g, ' ').trim()))()")
        for want in ("Сделать эталоном", "Изменить", "В архив", "Удалить"):
            if not any(want in it for it in items):
                fail(label, "в меню примера нет «%s»: %s" % (want, items))
        snap(page, shots, "examples_menu_390")
        page.click(".speech-menu-backdrop", position={"x": 5, "y": 5})
        page.wait_for_timeout(200)
        page.locator(".speech-section button", has_text="Добавить пример").first.click()
        page.wait_for_selector("[data-speech-sample-editor]", state="visible")
        page.fill("textarea[aria-label='Вход примера']", "вход из e2e")
        page.fill("textarea[aria-label='Ответ примера']", "ответ из e2e")
        before = len(POSTS)
        page.locator("[data-speech-sample-editor] .btn-accent").first.click()
        page.wait_for_timeout(800)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "examples":
            fail(label, "добавление примера не ушло в API: %s" % (POSTS[before:]))
        page.click("[data-speech-menu='sample-11']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        before = len(POSTS)
        click_menu_item(page, "Сделать эталоном")
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or "approve" not in POSTS[-1]["path"]:
            fail(label, "эталон не ушёл в API: %s" % (POSTS[before:]))
        page.click("[data-speech-menu='sample-11']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        before = len(POSTS)
        click_menu_item(page, "В архив")
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or "archive" not in POSTS[-1]["path"]:
            fail(label, "архив не ушёл в API: %s" % (POSTS[before:]))
        page.click("[data-speech-menu='sample-11']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        dialogs_before = len(DIALOGS)
        before = len(POSTS)
        click_menu_item(page, "Удалить")   # dialog — accept в new_page
        page.wait_for_timeout(700)
        if len(DIALOGS) == dialogs_before or "Удалить пример" not in DIALOGS[-1]:
            fail(label, "удаление прошло без подтверждения")
        if len(POSTS) != before + 1 or POSTS[-1].get("method") != "DELETE" \
                or POSTS[-1]["path"] != "examples/11":
            fail(label, "удаление не ушло в API: %s" % (POSTS[before:]))
        page.click("[data-speech-menu='examples']")
        page.wait_for_selector(".speech-menu-panel", state="visible")
        before = len(POSTS)
        click_menu_item(page, "Заводская подборка")
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "examples/seed":
            fail(label, "заводская подборка не ушла в API: %s" % (POSTS[before:]))
        page.fill("input[aria-label='Сообщение для отбора']", "привет")
        before = len(POSTS)
        page.locator(".speech-section button", has_text="Показать отбор").first.click()
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "examples/why":
            fail(label, "«Почему выбраны» не ушло в API: %s" % (POSTS[before:]))
        page.locator("details summary",
                     has_text="Дополнительно: отбор и A/B").first.click()
        page.wait_for_timeout(200)
        before = len(POSTS)
        page.locator("[data-speech-examples-policy] .btn-accent").first.click()
        page.wait_for_timeout(700)
        if len(POSTS) != before + 1 or POSTS[-1]["path"] != "examples/policy" \
                or POSTS[-1]["body"].get("scope") != "chat":
            fail(label, "политика не ушла в API/scope: %s" % (POSTS[before:]))
        snap(page, shots, "examples_policy_390")
    finally:
        STATE["examples_available"] = False
        ctx.close()


def run_readonly(browser):
    """§9.1 п.25: без can_edit редакторы read-only, сохранение disabled."""
    label = "readonly"
    STATE["can_edit"] = False
    ctx, page = new_page(browser, 390, 844, None, chat=CHAT_A)
    try:
        open_speech(page)
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-editor", state="visible")
        page.wait_for_timeout(400)
        ro = page.evaluate(
            "(() => { const t = document.querySelector('.speech-section "
            ".speech-editor'); return t ? t.readOnly : null; })()")
        if ro is not True:
            fail(label, "редактор без can_edit не read-only (readOnly=%s)" % ro)
        dis = page.evaluate(
            "(() => { const b = document.querySelector('.speech-section "
            ".btn-accent'); return b ? b.disabled : null; })()")
        if dis is not True:
            fail(label, "кнопка сохранения не disabled без can_edit (%s)" % dis)
        page.click(".speech-back")
        page.wait_for_selector(".speech-grid", state="visible")
        page.click("[data-speech-card='style']")
        page.wait_for_selector(".speech-section", state="visible")
        page.wait_for_timeout(400)
        dis_style = page.evaluate(
            "(() => { const b = document.querySelector('.speech-section "
            ".btn-accent'); return b ? b.disabled : null; })()")
        if dis_style is not True:
            fail(label, "сохранение правил не disabled без can_edit (%s)"
                 % dis_style)
    finally:
        STATE["can_edit"] = True
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    serve_static(PORT, os.path.abspath(args.webroot))
    print("[p0a-ux-e2e] webroot =", os.path.abspath(args.webroot))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            run_layout(browser, 320, 640, "320", "one", args.shots)
            run_layout(browser, 360, 740, "360", "two", args.shots)
            run_layout(browser, 390, 844, "390", "two", args.shots)
            run_layout(browser, 412, 915, "412", "two", args.shots)
            run_layout(browser, 844, 390, "landscape", "auto", args.shots)
            run_layout(browser, 1280, 900, "desktop", "auto", args.shots)
            run_save_flows(browser, args.shots)
            run_scope_and_chat_isolation(browser, args.shots)
            run_core_extras(browser, args.shots)
            run_humor_and_learning(browser, args.shots)
            run_examples_crud(browser, args.shots)
            run_readonly(browser)

    report = {"webroot": os.path.abspath(args.webroot),
              "failures": failures, "notes": notes,
              "post_calls": POSTS, "dialogs": DIALOGS}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n== ИТОГ: failures=%d, POST=%d" % (len(failures), len(POSTS)))
    for row in failures:
        print("  -", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
