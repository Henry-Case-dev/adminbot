# -*- coding: utf-8 -*-
"""ASAP3 §1.3/§1.5 — лимиты подсказки Style Policy и честный Inspector.

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(route-стабы `/api/*` в playwright) и РЕАЛЬНЫЙ серверный клей
`web/api/speech.py` (без HTTP: прямые вызовы сборки).

Сценарии:

  1. Оба лимита OFF (по умолчанию): чекбоксы выключены, видно
     «Без ограничения», нет предупреждения о потере инструкций.
  2. Лимит включён: предупреждение называет НЕ вошедшие правила, показывает
     «N из M», кнопка «Отключить лимит» пишет явный `hint_limits` в документ
     (OFF для слоя) через существующий `POST /api/speech/style`.
  3. Inspector: карточка «Стиль письма в сборке» показывает доступно/включено,
     источник, лимит, причину исключения и ТОЧНУЮ редакцию попавших в payload
     инструкций; при OFF — «Без ограничения» и отсутствие исключений.
  4. Адаптивность: 390px и 1280px без горизонтального overflow, тач-цели ≥44px.
  5. Сервер: предпросмотр собирает ОБА слоя `style.policy` (global+chat), а не
     один; витрина отдаёт собственные поля лимита каждого слоя.

TEST-LIFECYCLE: CONTRACT owner=ASAP3-S3/S9 (§1.3 видимость превышения,
§1.5 Inspector = фактическая сборка); REGRESSION owner=ASAP3-S9 (предпросмотр
раньше собирал только один слой Style Policy).

Запуск:
  .venv/Scripts/python.exe tests/ui_asap3_hint_speech_e2e.py
  ... --shots <dir> --json <path>
"""
import argparse
import asyncio
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

PORT = 8862
BASE = "http://127.0.0.1:%d" % PORT
CHAT = -100500

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

STATE = {"mode": "off"}          # off | limited
POSTS = []

RULE = {"id": "trailing_period.hard.strip", "kind": "trailing_period",
        "strictness": "hard", "scope": "global", "enabled": True,
        "params": {"ellipsis": "strip"}, "source": "global"}
SOFT = [
    {"id": "soft.g1", "text": "Пиши живо, без канцелярита",
     "scope": "global", "enabled": True, "source": "global"},
    {"id": "soft.g2", "text": "В этом чате короче", "scope": "chat",
     "enabled": True, "source": "chat"},
]
EXCLUDED = [{
    "key": "soft.g2", "kind": "soft_instruction", "reason": "user_limit",
    "reason_label": "лимит владельца", "title": "Мягкая привычка",
    "text": "В этом чате короче",
}]


def style_payload():
    limited = STATE["mode"] == "limited"
    limits = {"max_chars": 0, "max_items": 0, "sources": {},
              "off": True, "current_chars": 0,
              "layers": {"global": {}, "chat": {}}}
    render = {"total_items": 3, "included_items": 3, "excluded": [],
              "overflow": False, "limited_by": "", "truncated": False}
    if limited:
        limits = {"max_chars": 0, "max_items": 2,
                  "sources": {"max_items": "chat"}, "off": False,
                  "current_chars": 180,
                  "layers": {"global": {}, "chat": {"max_items": 2}}}
        render = {"total_items": 3, "included_items": 2,
                  "excluded": list(EXCLUDED), "overflow": True,
                  "limited_by": "items", "truncated": False}
    return {
        "scope": "chat", "chat_id": CHAT, "can_edit": True,
        "context": "regular", "source": "chat", "revision": "g3.c2",
        "skip_reason": "", "conflicts": [], "precedence": ["safety_facts"],
        "hint": ("<Style_Policy_Hint>\n- Пиши живо, без канцелярита\n"
                 "- Защищённый текст не переписывай\n</Style_Policy_Hint>"),
        "hint_tokens": 30,
        "hint_limits": limits,
        "hint_render": render,
        "document": {"global_present": True, "chat_present": True,
                     "global_revision": 3, "chat_revision": 2,
                     "global_issues": [], "chat_issues": [],
                     "inheritance": "chat"},
        "rules": [dict(RULE)],
        "soft_instructions": [dict(row) for row in SOFT],
        "rule_kinds": [{"kind": "trailing_period",
                        "title_ru": "Точка в конце сообщения",
                        "purpose": "Убирать завершающую точку.",
                        "hard_effect": "точка снимается",
                        "soft_effect": "инструкция Writer"}],
        "available_presets": [{"id": "no_trailing_period",
                               "title_ru": "Без точек на конце",
                               "description": "шаблон"}],
        "preset_documents": {"no_trailing_period": {
            "rules": [dict(RULE)], "soft_instructions": []}},
        "history": [],
    }


def style_build():
    limited = STATE["mode"] == "limited"
    build = {
        "source": "chat",
        "limits": {"max_chars": 0, "max_items": 0, "off": True,
                   "sources": {}},
        "total_items": 3, "included_items": 3, "excluded": [],
        "limited_by": "",
        "hint_chars": 190,
        "hint_text": ("<Style_Policy_Hint>\n- Пиши живо, без канцелярита\n"
                      "- В этом чате короче\n- Защищённый текст не переписывай"
                      "\n</Style_Policy_Hint>"),
        "layer": {"state": "rendered", "rendered": True, "skip_reason": "",
                  "chars": 190, "tokens": 48, "revision": "g3.c2"},
        "payload_included": True,
        "documents": {"global_present": True, "chat_present": True,
                      "global_revision": 3, "chat_revision": 2,
                      "global_issues": [], "chat_issues": []},
    }
    if limited:
        build.update({
            "limits": {"max_chars": 0, "max_items": 2, "off": False,
                       "sources": {"max_items": "chat"}},
            "included_items": 2, "excluded": list(EXCLUDED),
            "limited_by": "items", "hint_chars": 120,
            "hint_text": ("<Style_Policy_Hint>\n- Пиши живо, без канцелярита"
                          "\n- Защищённый текст не переписывай\n"
                          "</Style_Policy_Hint>"),
            "layer": {"state": "rendered", "rendered": True,
                      "skip_reason": "", "chars": 120, "tokens": 30,
                      "revision": "g3.c2"},
        })
    return build


def inspector_payload():
    return {
        "chat_id": CHAT, "last_run_present": False, "last_run_note": "",
        "retention": "in-memory", "masked": True, "sent": {},
        "preview": {
            "manifest_id": "m1", "tokens_total": 50,
            "layer_order": ["style_policy_hint"], "versions": {},
            "conflicts": [],
            "layers": [{"layer": "style_policy_hint", "source": "chat",
                        "revision": "g3.c2", "rendered": True, "tokens": 30,
                        "skip_reason": ""}],
            "system_masked": "(payload)", "preview_note": "",
            "style": style_build(),
        },
        "core": {"level": "compact", "reason": "owner_setting",
                 "active_revision": "r1", "chars": 10,
                 "factory_revisions": {}},
    }


def overview_payload():
    return {
        "scope": "chat", "chat_id": CHAT, "inheritance": "chat",
        "gates": {"speech_style_policy_enabled": True},
        "sections": [
            {"id": "style", "icon": "format_quote", "title": "Стиль письма",
             "subtitle": "Правила формы", "state": "custom", "detail": "",
             "ready": True},
        ],
        "advanced": [
            {"id": "inspector", "icon": "fact_check",
             "title": "Effective Prompt Inspector",
             "subtitle": "технический раздел", "ready": True},
        ],
        "registry": {"blocks": 1, "version": "r1", "factory_set": "f"},
        "can_edit": True,
    }


def api_handler(route):
    req = route.request
    url = req.url.split("?")[0]
    method = req.method

    def ok(payload):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload, ensure_ascii=False))

    if url.endswith("/api/speech/overview"):
        ok(overview_payload())
        return
    if url.endswith("/api/speech/inspector"):
        ok(inspector_payload())
        return
    if "/api/speech/style" in url:
        name = url.rsplit("/api/speech/style", 1)[1]
        if method == "POST":
            body = {}
            try:
                body = json.loads(req.post_data or "{}")
            except Exception:  # noqa: BLE001
                body = {"raw": req.post_data}
            POSTS.append({"path": "style" + name, "body": body})
            if name.endswith("/preview"):
                ok({"context": "regular", "candidate_present": True,
                    "candidate_revision": "c1", "current_revision": "g3",
                    "candidate_hint": style_build(),
                    "current_hint": style_build(), "rows": []})
                return
            ok({"ok": True, "result": {"applied": True},
                "view": style_payload()})
            return
        if name.endswith("/reset-chat"):
            ok({"ok": True, "result": {"applied": True},
                "view": style_payload()})
            return
        ok(style_payload())
        return
    if url.endswith("/api/access/me"):
        ok({"is_global_admin": True, "effective_permissions": None})
        return
    if url.endswith("/api/access/chats"):
        ok([{"chat_id": CHAT, "title": "Чат A", "is_dm": False,
             "access": "admin", "is_active": True}])
        return
    ok(M._stub_for(req.url))


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


# ── 1. Серверная сборка: оба слоя, лимит, точная редакция ───────────────────

GLOBAL_DOC = {
    "rules": [dict(RULE)],
    "soft_instructions": [
        {"id": "soft.g1", "text": "Пиши живо, без канцелярита",
         "enabled": True},
        {"id": "soft.g2", "text": "Без канцелярита и штампов",
         "enabled": True},
    ],
}
CHAT_DOC = {
    "hint_limits": {"max_items": 2},
    "soft_instructions": [
        {"id": "soft.c1", "text": "В этом чате короче", "enabled": True},
    ],
}


class _Cache:
    def __init__(self, data):
        self.data = dict(data)

    def get(self, key, default=None):
        return self.data.get(key, default)


def api_checks():
    from web.api import speech as S
    from services import style_policy as sp

    cache = _Cache({"style.policy": GLOBAL_DOC})
    global_doc, chat_doc = S._style_layer_documents(
        cache, CHAT, {"style.policy": CHAT_DOC})
    if global_doc is not GLOBAL_DOC or chat_doc is not CHAT_DOC:
        fail("api/layers", "предпросмотр теряет один из слоёв style.policy")
    policy = sp.effective_policy_sync(global_doc, chat_doc)
    if policy.hint_limits.get("max_items") != 2:
        fail("api/limits", "лимит чата не применился: %s"
             % (policy.hint_limits,))
    keys = {str(row.get("key")) for row in (policy.hint_excluded or ())}
    if not {"soft.g1", "soft.g2", "soft.c1"} <= keys:
        fail("api/excluded", "исключены не все слои: %s" % sorted(keys))
    summary = S._style_build_summary(policy, [])
    if summary["included_items"] != 2 or summary["total_items"] != 5:
        fail("api/summary", "состав подсказки неверен: %s из %s"
             % (summary["included_items"], summary["total_items"]))
    if not all(row.get("reason") == "user_limit"
               and row.get("reason_label") for row in summary["excluded"]):
        fail("api/reason", "исключения без человеческой причины: %s"
             % summary["excluded"])
    if summary["limits"]["off"] is not False:
        fail("api/off", "лимит помечен выключенным при max_items=2")

    async def _overrides(chat_id):
        return {"style.policy": CHAT_DOC}

    original = S._chat_overrides
    S._chat_overrides = _overrides
    try:
        view = asyncio.run(S._style_payload(cache, CHAT))
        layers = (view.get("hint_limits") or {}).get("layers") or {}
        if layers.get("chat") != {"max_items": 2} or layers.get("global"):
            fail("api/own_limits", "собственные поля слоёв неверны: %s"
                 % (layers,))
        excluded = (view.get("hint_render") or {}).get("excluded") or []
        if not any(row.get("text") == "В этом чате короче"
                   for row in excluded):
            fail("api/labels", "исключение без текста инструкции: %s"
                 % excluded)
        preview = asyncio.run(S._preview_manifest(cache, CHAT, text="привет"))
        build = preview.get("style") or {}
        if build.get("total_items") != 5 or build.get("included_items") != 2:
            fail("api/preview", "Inspector-предпросмотр собрал не те слои: %s"
                 % {k: build.get(k) for k in
                    ("total_items", "included_items", "source")})
        docs = build.get("documents") or {}
        if not (docs.get("global_present") and docs.get("chat_present")):
            fail("api/preview_docs", "провенанс слоёв потерян: %s" % (docs,))
        if not build.get("payload_included") or not build.get("hint_text"):
            fail("api/preview_payload", "нет фактической редакции подсказки")
    finally:
        S._chat_overrides = original
    notes.append({"label": "api", "summary": summary})


# ── 2. UI (Playwright) ──────────────────────────────────────────────────────

PROBE = r"""
(() => {
  const host = document.querySelector('[data-speech-hint-limits]');
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  if (!host) return { present: false };
  const toggles = Array.from(
    host.querySelectorAll('[data-speech-hint-limit-toggle]')).map((el) => ({
      field: el.getAttribute('data-speech-hint-limit-toggle'),
      checked: !!el.checked,
    }));
  const inputs = Array.from(host.querySelectorAll('input[type=number]'))
    .map((el) => ({ field: el.getAttribute('data-speech-hint-limit-input'),
                    value: el.value, h: Math.round(
                      el.getBoundingClientRect().height) }));
  const small = [];
  let minTap = null;
  host.querySelectorAll('button, input, label').forEach((el) => {
    const target = (el.tagName === 'INPUT' && el.type === 'checkbox')
      ? (el.closest('label') || el) : el;
    const r = target.getBoundingClientRect();
    if (!r.width && !r.height) return;
    const m = Math.min(r.width, r.height);
    minTap = (minTap === null) ? m : Math.min(minTap, m);
    if (r.height < 44 || r.width < 44) small.push({
      t: strip(el.textContent).slice(0, 30), w: Math.round(r.width),
      h: Math.round(r.height) });
  });
  return {
    present: true,
    text: strip(host.textContent),
    toggles,
    inputs,
    excluded: Array.from(
      host.querySelectorAll('[data-speech-hint-excluded]'))
      .map((el) => strip(el.textContent)),
    warning: !!host.querySelector('[data-speech-hint-overflow]'),
    complete: !!host.querySelector('[data-speech-hint-complete]'),
    current: strip((host.querySelector('[data-speech-hint-current]') || {})
      .textContent || ''),
    minTap: minTap === null ? null : Math.round(minTap),
    small,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
})()
"""

INSPECTOR_PROBE = r"""
(() => {
  const card = document.querySelector('[data-speech-inspector-style]');
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  if (!card) return { present: false };
  const hint = card.querySelector('[data-speech-inspector-style-hint]');
  return {
    present: true,
    text: strip(card.textContent),
    hintText: hint ? hint.textContent : '',
    excluded: Array.from(
      card.querySelectorAll('[data-speech-inspector-style-excluded] div'))
      .map((el) => strip(el.textContent)),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
})()
"""


def new_page(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430, has_touch=width <= 430)
    ctx.add_init_script(
        "try { localStorage.setItem('adminbot.active_chat_id', '%s'); }"
        " catch (e) {}" % CHAT)
    ctx.route("**/api/**", api_handler)
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


def open_style(page):
    page.goto(BASE + "/#/ai/speech", wait_until="load")
    page.wait_for_selector(".speech-screen", state="visible")
    page.wait_for_timeout(500)
    page.click("[data-speech-card='style']")
    page.wait_for_selector("[data-speech-hint-limits]", state="visible")
    page.wait_for_timeout(300)


def run_style_off(browser, shots):
    label = "style-off"
    STATE["mode"] = "off"
    ctx, page = new_page(browser, 390, 844)
    try:
        open_style(page)
        data = page.evaluate(PROBE)
        if not data.get("present"):
            fail(label, "блок «Ограничения подсказки» не отрисован")
            return
        if [t["checked"] for t in data["toggles"]] != [False, False]:
            fail(label, "по умолчанию лимиты включены: %s" % data["toggles"])
        if "Без ограничения" not in data["current"]:
            fail(label, "нет статуса «Без ограничения»: %s" % data["current"])
        if data["warning"]:
            fail(label, "при OFF показано предупреждение об исключении")
        if not data["complete"]:
            fail(label, "нет честной строки «все инструкции входят»")
        if data["overflow"] > 1:
            fail(label, "горизонтальный overflow: %d" % data["overflow"])
        if data["minTap"] is not None and data["minTap"] < 44:
            fail(label, "тач-цель < 44px: %s" % data["small"])
        snap(page, shots, "style_off_390")
        notes.append({"label": label, "probe": data})
    finally:
        ctx.close()


def run_style_limited(browser, shots):
    label = "style-limited"
    STATE["mode"] = "limited"
    POSTS[:] = []
    ctx, page = new_page(browser, 390, 844)
    try:
        open_style(page)
        data = page.evaluate(PROBE)
        if [t["checked"] for t in data["toggles"]] != [False, True]:
            fail(label, "состояние чекбоксов не совпадает с лимитом: %s"
                 % data["toggles"])
        if not data["warning"]:
            fail(label, "превышение лимита не показано")
        if not any("В этом чате короче" in row for row in data["excluded"]):
            fail(label, "предупреждение не называет исключённое правило: %s"
                 % data["excluded"])
        if "2 из 3" not in data["text"]:
            fail(label, "нет фактического «2 из 3» в блоке")
        if "до 2 инструкций" not in data["text"]:
            fail(label, "нет установленного значения лимита")
        if data["overflow"] > 1:
            fail(label, "горизонтальный overflow: %d" % data["overflow"])
        if data["minTap"] is not None and data["minTap"] < 44:
            fail(label, "тач-цель < 44px: %s" % data["small"])
        snap(page, shots, "style_limited_390")

        page.click("[data-speech-hint-disable]")
        page.wait_for_timeout(200)
        after = page.evaluate(PROBE)
        if [t["checked"] for t in after["toggles"]] != [False, False]:
            fail(label, "«Отключить лимит» не снял чекбоксы: %s"
                 % after["toggles"])
        page.click(".speech-section .btn-accent")
        page.wait_for_timeout(700)
        posts = [p for p in POSTS if p["path"] == "style"]
        if not posts:
            fail(label, "сохранение не ушло в существующий POST /style")
        else:
            limits = (posts[-1]["body"].get("document") or {}).get(
                "hint_limits") or {}
            if limits.get("max_chars") != 0 or limits.get("max_items") != 0:
                fail(label, "в документ не записан явный OFF-лимит: %s"
                     % (limits,))
        notes.append({"label": label, "probe": data, "after": after,
                      "posts": [p["path"] for p in POSTS]})
    finally:
        ctx.close()


def run_inspector(browser, width, height, label, mode, shots):
    STATE["mode"] = mode
    ctx, page = new_page(browser, width, height)
    try:
        page.goto(BASE + "/#/ai/speech", wait_until="load")
        page.wait_for_selector(".speech-screen", state="visible")
        page.wait_for_timeout(500)
        page.click("[data-speech-card='inspector']")
        page.wait_for_selector("[data-speech-inspector-style]",
                               state="visible")
        page.wait_for_timeout(300)
        data = page.evaluate(INSPECTOR_PROBE)
        if not data.get("present"):
            fail(label, "карточка Style Policy в Inspector не отрисована")
            return
        if mode == "limited":
            if "до 2 инструкций" not in data["text"]:
                fail(label, "Inspector не показывает действующий лимит")
            if not any("В этом чате короче" in row
                       for row in data["excluded"]):
                fail(label, "Inspector не называет исключённое правило: %s"
                     % data["excluded"])
            if "В этом чате короче" in data["hintText"]:
                fail(label, "Inspector показывает исключённое правило как "
                            "включённое в payload")
            if "Пиши живо, без канцелярита" not in data["hintText"]:
                fail(label, "Inspector не показывает точную редакцию "
                            "включённых инструкций")
        else:
            if "Без ограничения" not in data["text"]:
                fail(label, "при OFF Inspector не показывает «Без ограничения»")
            if data["excluded"]:
                fail(label, "при OFF показаны исключения: %s" % data["excluded"])
            if "В этом чате короче" not in data["hintText"]:
                fail(label, "при OFF не все инструкции в фактической редакции")
        if data["overflow"] > 1:
            fail(label, "горизонтальный overflow: %d" % data["overflow"])
        snap(page, shots, "inspector_%s_%s" % (mode, label))
        notes.append({"label": label, "probe": data})
    finally:
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    api_checks()
    serve_static(PORT, os.path.abspath(args.webroot))
    print("[asap3-hint-e2e] webroot =", os.path.abspath(args.webroot))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            run_style_off(browser, args.shots)
            run_style_limited(browser, args.shots)
            run_inspector(browser, 390, 844, "390", "limited", args.shots)
            run_inspector(browser, 1280, 900, "desktop", "limited", args.shots)
            run_inspector(browser, 390, 844, "390", "off", args.shots)
            run_inspector(browser, 1280, 900, "desktop", "off", args.shots)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"failures": failures, "notes": notes}, fh,
                      ensure_ascii=False, indent=2)
    if failures:
        print("[asap3-hint-e2e] FAILURES: %d" % len(failures))
        for row in failures:
            print("  -", row)
        return 1
    print("[asap3-hint-e2e] PASS: %d проверок" % len(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
