# -*- coding: utf-8 -*-
"""PVR-S4 — единый компонент контроля версий промпта (реальный UI).

Проверяет ОДИН переиспользуемый компонент `prompt-version-card` на всех
редакторах промптов и его поведение против настоящих HTTP-контрактов
(`GET /api/prompts/{key}/versions` с `entries[]`/`page.next_cursor`,
`/revisions/{id}/source`, `/revisions/diff`, `/activate`, `/baseline`,
`/baseline/restore`, `/factory/restore`, `/revisions/{id}/copy-to-global`).

Что утверждается (контракт EPIC-PROMPT-VERSIONING-UX-01 §2.1/§2.2/§6):

  * карточка показывает человеческое состояние (без act:/fac:/sha/id);
  * «История версий» открывается панелью (боковая на десктопе, полноэкранная
    на мобильном), список листается дальше 50 записей по `page.next_cursor`;
  * «Посмотреть» отдаёт дословный полный текст и НЕ пересохраняет промпт;
  * diff «было → стало» красит только изменённые строки;
  * «Применить» существует лишь при непустом revision_id и actionable;
    иначе видна причина (нет прав / code-only / несовместима / retired /
    журнал недоступен);
  * «Назначить базовой» не меняет действующий текст и говорит об этом;
  * «Снять назначение», «Восстановить базовую», «Вернуть исходную из кода»
    (с подтверждением) и «Скопировать глобально» бьют в свои endpoints;
  * 503 журнала — честное сообщение, черновик остаётся в поле;
  * черновик защищён подтверждением при смене чата;
  * два промпта мемов рядом на широком экране и столбиком на мобильном;
    подсказка `{joke}` человеческая в трёх режимах (0/1/2), без «{joke}: N»;
  * нет горизонтального скролла страницы: 1536/1366/768/390/360.

Запуск:
  py -3 tests/ui_prompt_version_card_e2e.py
  ... --shots <dir> --json <path> --webroot <dir>

TEST-LIFECYCLE: CONTRACT owner=EPIC-PROMPT-VERSIONING-UX-01 (PVR-S4).
"""
import argparse
import json
import os
import re
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

import ui_round1025_matrix as M  # noqa: E402  (существующий /api-стаб)

PORT = 8875
BASE = "http://127.0.0.1:%d" % PORT
CHAT_A = -100500
CHAT_B = -100777

PROMPT_KEY = "prompts.meme_joke"
LONG_BODY = ("строка один\nстрока два\nстрока три\n"
             + ("очень длинный хвост без обрезки " * 6).strip()
             + "\nКОНЕЦ-ТЕЛА")
TOTAL_ENTRIES = 130          # > 50: проверяем досье целиком, а не «последние N»

STATE = {
    "entries": [],           # объединённая лента журнала (новые сверху)
    "entries_page_size": 50,
    "journal_down": False,
    "code_only": False,
    "posts": [],             # все POST/DELETE с путём и телом
    "gets": [],
    "active": "rev-manual-2",
    "baseline": None,        # revision_id или None
    "baseline_cleared": False,
    "factory_restored": False,
    "meme_placeholders": 0,
    "prompt_joke": "СТАРЫЙ ПРИКОЛ",   # действующий текст (не меняется тестом)
    # Speech/Character «Характер»: два prompt-поля одного документа.
    "core_text": {
        "full": "ПОЛНЫЙ ХАРАКТЕР: спокойный, точный, без пафоса.",
        "compact": "КОМПАКТНЫЙ ХАРАКТЕР: спокойный и точный.",
    },
}


def _body(rev_id):
    if rev_id == "rev-active-src":
        return LONG_BODY
    return "текст версии %s\nвторая строка" % rev_id


def build_entries():
    """Лента: 130 записей, среди них retired/несовместимая/событие."""
    rows = []
    for i in range(1, TOTAL_ENTRIES + 1):
        rev = "rev-%03d" % i
        status = "active" if rev == STATE["active"] else "inactive"
        actionable = True
        reason_text = ""
        if i == 7:
            status, actionable = "retired", False
            reason_text = ("Версия снята с регистрации (retired): её можно "
                           "читать и сравнивать, но нельзя применить.")
        if i == 9:
            status, actionable = "incompatible", False
            reason_text = ("Несовместима с текущей схемой <2>: читать и "
                           "сравнивать можно, применять нельзя.")
        rows.append({
            "entry_type": "revision",
            "order": i,
            "created_at": "2026-11-03T%02d:%02d:00+00:00" % (10 + (i % 10), i % 60),
            "revision_id": rev,
            "event_id": None,
            "source": "manual",
            "source_label": "ручная",
            "origin": "manual",
            "kind": "manual_edit",
            "outcome": "applied",
            "detail_code": "",
            "actor": "" if i % 3 else "77",
            "scope": "chat",
            "chat_id": CHAT_A,
            "status": status,
            "status_label": {"active": "активная", "inactive": "неактивная",
                             "retired": "снята с регистрации",
                             "incompatible": "несовместимая"}[status],
            "actionable": actionable,
            "reason": "",
            "reason_text": reason_text,
            "body_available": True,
            "chars": len(_body(rev)),
            "sha256_12": "%012d" % i,
            "release_id": "",
            "factory_revision": "",
            "schema_compat": "2" if i == 9 else "",
            "retired": i == 7,
        })
    # событие без текста: «Применить» не должно появляться
    rows.insert(2, {
        "entry_type": "activation", "order": 0,
        "created_at": "2026-11-03T09:00:00+00:00", "revision_id": "",
        "event_id": "act-1", "source": "restored",
        "source_label": "назначена базовая", "origin": "", "kind":
        "baseline_assign", "outcome": "recorded", "detail_code": "",
        "actor": "77", "scope": "chat", "chat_id": CHAT_A, "status": "inactive",
        "status_label": "неактивная", "actionable": True, "reason": "",
        "reason_text": "", "body_available": False, "chars": 0,
        "sha256_12": "", "release_id": "", "factory_revision": "",
        "schema_compat": "", "retired": False,
    })
    # Объединённая лента: порядковый номер = ранг в ленте, начиная с 1
    # (реальный API не отдаёт «0» и не оставляет дыр).
    for idx, row in enumerate(rows):
        row["order"] = idx + 1
    return rows


def _block_for(key):
    """Реестровые id/ключи: у Speech «Характера» два блока на один pg_key."""
    key = key or PROMPT_KEY
    if key.startswith("core.personality"):
        return {"block_id": key, "pg_key": "character.core"}
    return {"block_id": "initiative.meme.joke", "pg_key": PROMPT_KEY}


def _versions_payload(url, key=""):
    qs = url.split("?")[1] if "?" in url else ""
    params = {}
    for part in qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    size = min(int(params.get("page_size", 50) or 50), 200)
    start = int(params.get("cursor", 0) or 0)
    rows = STATE["entries"]
    page = rows[start:start + size]
    nxt = start + size
    has_more = nxt < len(rows)
    baseline = None
    if STATE["baseline"]:
        baseline = {
            "revision_id": STATE["baseline"], "assigned_at":
            "2026-11-03T21:00:00+00:00", "assigned_by": "77",
            "detail_code": "baseline:manual", "origin": "manual",
            "available": True, "is_active": STATE["baseline"] == STATE["active"],
            "sha256_12": "aaaa", "chars": 10, "retired": False,
            "schema_compat": "", "compatible": True, "factory_revision": "",
            "created_at": "2026-11-03T20:00:00+00:00",
        }
    return {
        "known": True,
        "block_id": _block_for(key)["block_id"],
        "pg_key": _block_for(key)["pg_key"],
        "scope": "chat",
        "chat_id": CHAT_A,
        "hidden": False,
        "manageable": not STATE["code_only"],
        "journal_available": True,
        "can_activate": not STATE["code_only"],
        "factory_revision": "fac:deadbeefcafe",
        "sealed_revision": "fac:deadbeefcafe",
        "factory_matches_active": False,
        "active": {
            "revision_id": STATE["active"], "origin": "manual",
            "sha256_12": "123456789abc", "chars": len(LONG_BODY),
            "created_at": "2026-11-03T23:42:00+00:00", "source": "manual",
            "factory_revision_applied": "fac:deadbeefcafe",
        },
        "baseline": {
            "block_id": "initiative.meme.joke", "pg_key": PROMPT_KEY,
            "scope": "chat", "chat_id": CHAT_A,
            "source": "owner" if STATE["baseline"] else "factory",
            "baseline": baseline,
            "cleared_at": ("2026-11-03T21:30:00+00:00"
                           if STATE["baseline_cleared"] else None),
            "cleared_by": "77" if STATE["baseline_cleared"] else "",
        },
        "capabilities": {
            "can_assign_baseline": not STATE["code_only"],
            "can_clear_baseline": bool(STATE["baseline"]),
            "can_restore_baseline": bool(STATE["baseline"]),
            "can_copy_to_global": True,
        },
        "entries": page,
        "page": {"page_size": size, "order": "newest_first",
                 "next_cursor": str(nxt) if has_more else "",
                 "has_more": has_more, "returned": len(page),
                 "rank_start": start + 1, "total_known": None},
        "revisions": [], "activations": [],
        "supported_schema_compat": ["1", "2"],
    }


def _speech_overview():
    """Витрина «Речь и характер»: нужна, чтобы кликнуть карточку «Характер»."""
    return {
        "scope": "chat", "chat_id": CHAT_A, "inheritance": "chat",
        "gates": {"character_core_enabled": True,
                  "unified_composer_enabled": True,
                  "speech_style_policy_enabled": True},
        "sections": [
            {"id": "core", "icon": "psychology", "title": "Характер",
             "subtitle": "Постоянный характер", "state": "owner",
             "detail": "действует ваша редакция", "ready": True},
            {"id": "style", "icon": "format_quote", "title": "Стиль письма",
             "subtitle": "Правила формы", "state": "owner",
             "detail": "правил 0", "ready": True},
        ],
        "advanced": [],
        "registry": {"blocks": 12, "version": "reg-1", "factory_set": "fs"},
        "can_edit": True,
    }


def _speech_core():
    """`/api/speech/core` в форме действующего API (block_ids/editions/history)."""
    def edition(level):
        return {
            "text": STATE["core_text"][level],
            "source": "chat",
            "scope_label": "этот чат",
            "revision": "act:core" + level,
            "factory_revision": "fac:core-" + level,
            "differs_from_factory": True,
            "withheld": False,
            "withheld_class": "",
            "withheld_reason": "",
            "diagnostics": [],
            "chars": len(STATE["core_text"][level]),
        }
    return {
        "block_ids": {"full": "core.personality",
                      "compact": "core.personality.compact"},
        "doc_key": "character.core",
        "scope": "chat",
        "chat_id": CHAT_A,
        "inheritance": "chat",
        "global_present": True,
        "chat_present": True,
        "permanent_note": "Core — постоянный характер, действует постоянно.",
        "selection": {"level": "full", "reason": "owner_setting",
                      "revision": "act:corefull"},
        "factory": {"full_text": "заводской полный",
                    "compact_text": "заводской компактный",
                    "full_chars": 16, "compact_chars": 19,
                    "full_revision": "fac:core-full",
                    "compact_revision": "fac:core-compact"},
        "document": {"revision": 3, "enabled": True, "detail_level": "full",
                     "origin": "owner",
                     "updated_at": "2026-11-03T20:00:00+00:00",
                     "present": True},
        "editions": {"full": edition("full"), "compact": edition("compact")},
        "diff": {
            "full": {"same": False, "before_chars": 16, "after_chars": 10,
                     "delta_chars": -6,
                     "changed": {"before": "заводской", "after": "наш"}},
            "compact": {"same": False, "before_chars": 19, "after_chars": 9,
                        "delta_chars": -10,
                        "changed": {"before": "заводской", "after": "наш"}},
        },
        "history": [],
        "history_source": "journal",
        "history_available": True,
        "history_pages": {},
        "inspection": {},
        "gates": {},
        "can_edit": True,
    }


def make_api_handler():
    def _handler(route):
        req = route.request
        url = req.url
        path = url.split("?")[0]
        method = req.method
        try:
            body = json.loads(req.post_data or "{}")
        except Exception:  # noqa: BLE001
            body = {}

        def send(payload, status=200):
            route.fulfill(status=status, content_type="application/json",
                          body=json.dumps(payload, ensure_ascii=False))

        if "/api/prompts/" in path:
            if method in ("POST", "DELETE"):
                STATE["posts"].append({"method": method, "path": path,
                                       "body": body})
            else:
                STATE["gets"].append(path)
            if path.endswith("/versions"):
                if STATE["journal_down"]:
                    return send({"detail": "журнал версий недоступен "
                                           "(нет PostgreSQL)"}, 503)
                key = path.split("/api/prompts/", 1)[1][: -len("/versions")]
                return send(_versions_payload(url, key))
            if path.endswith("/source"):
                rev = path.split("/revisions/", 1)[1][: -len("/source")]
                return send({"known": True, "revision_id": rev,
                             "block_id": "initiative.meme.joke",
                             "body": _body(rev), "chars": len(_body(rev)),
                             "created_at": "2026-11-03T20:00:00+00:00",
                             "scope": "chat", "chat_id": CHAT_A,
                             "origin": "manual", "actor": "77", "reason": "",
                             "retired": False, "schema_compat": "",
                             "sha256_12": "123456789abc",
                             "source": "manual", "source_label": "ручная",
                             "status": "inactive", "status_label": "неактивная",
                             "actionable": True, "reason_text": "",
                             "body_available": True})
            if path.endswith("/diff"):
                qs = url.split("?")[1] if "?" in url else ""
                a = re.search(r"(?:^|&)a=([^&]+)", qs)
                b = re.search(r"(?:^|&)b=([^&]+)", qs)
                a = a.group(1) if a else ""
                b = b.group(1) if b else ""
                diff = ["--- %s" % a, "+++ %s" % b,
                        "@@ -1,2 +1,2 @@",
                        "-текст версии %s" % a,
                        "+текст версии %s" % b,
                        " вторая строка"]
                return send({"known": True, "diff": diff, "added_lines": 1,
                             "removed_lines": 1,
                             "statuses": {"a": "inactive", "b": "active"},
                             "reason_text": "", "actionable": True})
            if path.endswith("/activate"):
                rev = str(body.get("revision_id") or "")
                STATE["active"] = rev
                for row in STATE["entries"]:
                    if row["status"] in ("retired", "incompatible"):
                        continue        # статус-гейт журнала не перетирается
                    row["status"] = ("active" if row["revision_id"] == rev
                                     else "inactive")
                    row["status_label"] = ("активная"
                                           if row["revision_id"] == rev
                                           else "неактивная")
                key = path.split("/api/prompts/", 1)[1][: -len("/activate")]
                if "core.personality.compact" in key:
                    STATE["core_text"]["compact"] = _body(rev)
                elif "core.personality" in key:
                    STATE["core_text"]["full"] = _body(rev)
                return send({"applied": True, "revision_id": rev,
                             "outcome": "applied", "reason_text": ""})
            if path.endswith("/baseline/restore"):
                STATE["active"] = STATE["baseline"]
                return send({"applied": True, "outcome": "applied",
                             "revision_id": STATE["baseline"],
                             "reason_text": ""})
            if path.endswith("/baseline"):
                if method == "DELETE":
                    STATE["baseline"] = None
                    STATE["baseline_cleared"] = True
                    return send({"applied": True, "reason_text": ""})
                STATE["baseline"] = str(body.get("revision_id") or "")
                STATE["baseline_cleared"] = False
                return send({"applied": True, "reason_text": "",
                             "revision_id": STATE["baseline"]})
            if path.endswith("/factory/restore"):
                STATE["factory_restored"] = True
                return send({"applied": True, "outcome": "applied",
                             "reason_text": ""})
            if path.endswith("/copy-to-global"):
                return send({"applied": True, "created": True,
                             "reason_text": ""})
            return send({"detail": "not stubbed"}, 404)
        if path.endswith("/api/speech/overview"):
            return send(_speech_overview())
        if path.endswith("/api/speech/core"):
            return send(_speech_core())
        if path.endswith("/api/initiative/meme-settings"):
            return send(_meme_settings())
        if path.endswith("/api/access/me"):
            return send({"is_global_admin": True, "is_local_admin": True,
                         "effective_permissions": None})
        if path.endswith("/api/access/chats"):
            return send([
                {"chat_id": CHAT_A, "title": "Чат A", "is_dm": False,
                 "photo_file_id": None, "access": "admin", "is_active": True},
                {"chat_id": CHAT_B, "title": "Чат B", "is_dm": False,
                 "photo_file_id": None, "access": "admin", "is_active": True},
            ])
        if path.endswith("/api/config"):
            payload = M._stub_for(url)
            if req.method == "POST":
                STATE["posts"].append({"method": "POST", "path": path,
                                       "body": body})
                return send({"ok": True, "applied": [], "skipped_same": [],
                             "rejected": [], "prompt_snapshots": [],
                             "journal_recorded": True})
            return send(payload)
        return send(M._stub_for(url))
    return _handler


def _meme_settings():
    joke = STATE["prompt_joke"]
    ph = STATE["meme_placeholders"]
    template = {"0": "Шаблон без метки", "1": "Шаблон {joke} тут",
                "2": "a {joke} b {joke}"}[str(ph)]
    valid = ph < 2
    return {
        "chat_id": CHAT_A, "generated_at": 1800000000,
        "settings": {"enabled": True, "window_messages": 500, "daily_limit": 3,
                     "cooldown_seconds": 21600, "min_messages": 8,
                     "summarizer_model": "", "quiet_hours": "",
                     "length_admin": None},
        "availability": {"available": True, "reason": "ok",
                         "initiative_enabled": True, "image": {"available": True}},
        "quota": {"available": True, "reason": "ok", "limit": 3, "spent": 1,
                  "remaining": 2, "timezone_name": "Europe/Moscow",
                  "next_reset": "2026-11-04T00:00:00+03:00"},
        "day": {"bucket": "2026-11-03", "timezone_name": "Europe/Moscow",
                "timezone_source": "chat",
                "next_reset": "2026-11-04T00:00:00+03:00"},
        "length_limit": {"ceiling": 800, "source": "model_capability",
                         "template_chars": len(template), "joke_budget": 700,
                         "known": True, "placeholder":
                         {0: "append", 1: "slot", 2: "invalid"}[ph],
                         "candidates": []},
        "template": {"text": template, "source": "chat", "placeholders": ph,
                     "valid": valid,
                     "error": "" if valid else
                     "шаблон: допускается не более одного {joke} (найдено 2)"},
        "prompts": {
            "joke": {"block_id": "initiative.meme.joke", "text": joke,
                     "source": "chat", "differs_from_factory": True,
                     "factory_revision": "fac:deadbeefcafe", "revision": 2,
                     "setting_key": PROMPT_KEY},
            "image": {"block_id": "initiative.meme.image", "text": template,
                      "source": "chat", "differs_from_factory": True,
                      "factory_revision": "fac:image", "revision": 1,
                      "setting_key": "prompts.meme_image"},
            "summary": {"block_id": "initiative.meme.summary", "text": "s",
                        "source": "factory", "differs_from_factory": False,
                        "setting_key": "prompts.meme_summary"},
        },
        "image_prefix": "", "schema_present": True,
        "analytics": {"counters": {}, "skip_reasons": {}, "events": [],
                      "coverage": ""},
        "delivery": {"stages": [], "events": [], "skip_reasons": {}},
        "defaults": {"enabled": True, "window_messages": 500, "daily_limit": 3},
    }


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

        def log_message(self, *args):  # noqa: D401
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


SDK_STUB = """
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A77%2C%22first_name%22%3A%22A%22%7D&hash=x',
  initDataUnsafe: { user: { id: 77, first_name: 'A' } },
  ready() {}, expand() {}, close() {}, colorScheme: 'dark',
  themeParams: {}, isExpanded: true, viewportHeight: 900,
  viewportStableHeight: 900, onEvent() {}, offEvent() {},
  setHeaderColor() {}, setBackgroundColor() {}, sendData() {},
  openLink() {}, isVersionAtLeast() { return true; }, platform: 'web',
  disableVerticalSwipes() {}, enableClosingConfirmation() {},
  disableClosingConfirmation() {}, showAlert() {}, showConfirm() {}
} };
"""

failures = []
notes = []
DIALOGS = []
DIALOG_MODE = {"mode": "accept"}


def _on_dialog(dialog):
    DIALOGS.append(dialog.message or "")
    try:
        if DIALOG_MODE["mode"] == "accept":
            dialog.accept()
        else:
            dialog.dismiss()
    except Exception:  # noqa: BLE001
        pass


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


def check(cond, label, msg):
    if not cond:
        fail(label, msg)
    return bool(cond)


def new_page(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430, has_touch=width <= 430)
    ctx.route("**/api/**", make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(status=200,
                                          content_type="application/javascript",
                                          body=SDK_STUB))
    ctx.add_init_script(
        "try { localStorage.setItem('adminbot.active_chat_id', '%d'); }"
        " catch (e) {}" % CHAT_A)
    page = ctx.new_page()
    page.set_default_timeout(20000)
    page.on("dialog", _on_dialog)
    return ctx, page


def shot(page, shots, name):
    if not shots:
        return
    os.makedirs(shots, exist_ok=True)
    try:
        page.screenshot(path=os.path.join(shots, name + ".png"),
                        full_page=True)
    except Exception:  # noqa: BLE001
        pass


def open_prompt_editor(page):
    """Открыть библиотечный редактор промпта через существующий роутер."""
    page.goto(BASE + "/#/", wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_timeout(600)
    target = page.evaluate(r"""
        () => {
          const vm = window.__adminbotVm;
          const m = (vm.modules || []).find(
            (x) => vm.workspacePromptItems(x).length > 0);
          if (!m) return null;
          const slug = vm.routeSlugOf(m);
          const it = vm.workspacePromptItems(m)[0];
          const route = '#/ai/prompts/' + slug + (it.stage ? '/' + it.stage : '')
            + '/' + it.key;
          vm.navigateTo(route);
          return {key: it.key, route: route};
        }
    """)
    page.wait_for_selector("[data-prompt-history-toggle]", state="visible")
    page.wait_for_timeout(500)
    return target


def card_text(page):
    return page.evaluate(
        "() => ((document.querySelector('[data-prompt-editor] ') || {})"
        ".textContent || '').trim()")


def open_panel(page):
    page.click("[data-prompt-history-toggle]")
    page.wait_for_selector("[data-pv-panel]", state="visible")
    page.wait_for_timeout(400)


def panel_rows(page):
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
        ".map((el) => ({order: el.getAttribute('data-pv-order'),"
        " status: el.getAttribute('data-pv-status'),"
        " text: (el.textContent || '').replace(/\\s+/g, ' ').trim()}))")


def hscroll(page):
    return page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth")


def row_rev(page, idx):
    return page.evaluate(
        "(i) => { const r = document.querySelectorAll('[data-pv-row]')[i];"
        " return r ? r.getAttribute('data-prompt-history-revision') : null; }",
        idx)


def click_row(page, idx, sel):
    page.evaluate(
        "([i, s]) => { const r = document.querySelectorAll('[data-pv-row]')[i];"
        " const b = r && r.querySelector(s); if (b) b.click(); }",
        [idx, sel])


def run_editor(label, page, shots, width):
    target = open_prompt_editor(page)
    check(target and target.get("key"), label, "редактор промпта не открылся")
    page.wait_for_function(
        "() => { const c = document.querySelector('[data-prompt-editor]');"
        " return !!(c && c.querySelector('[data-pv-state]')"
        " && (c.querySelector('[data-pv-state]').textContent || '').trim()); }")
    # 1) карточка: одна на редактор, человеческое состояние, без сырых id
    card = page.evaluate(r"""
        () => {
          const ed = document.querySelector('[data-prompt-editor]');
          if (!ed) return null;
          const tx = (el) => ((el && el.textContent) || '')
            .replace(/\s+/g, ' ').trim();
          const ta = ed.querySelector('textarea');
          return {
            cards: ed.querySelectorAll('[data-prompt-history]').length,
            state: tx(ed.querySelector('[data-pv-state]')),
            text: ta ? ta.value : null,
            hasRaw: /act:\d|fac:[0-9a-f]{8}|rev:[0-9a-f]|sha256/.test(tx(ed)),
            historyBtn: !!ed.querySelector('[data-prompt-history-toggle]'),
            moreBtn: !!ed.querySelector('[data-pv-more-toggle]'),
            save: !!ed.querySelector('[data-pv-save]'),
            discard: !!ed.querySelector('[data-pv-discard]'),
            detailsCollapsed: (function () {
              const d = ed.querySelector('[data-prompt-editor-meta]');
              return d ? d.tagName === 'DETAILS' && !d.open : false;
            })(),
          };
        }
    """)
    check(card and card["cards"] == 1, label,
          "карточка версий не одна в редакторе: %r" % (card,))
    check("изменён вручную" in (card["state"] or ""), label,
          "состояние не человеческое: %r" % (card["state"],))
    check(card["hasRaw"] is False, label,
          "в карточке остались сырые act:/fac:/sha")
    check(card["historyBtn"] and card["moreBtn"], label,
          "нет кнопок «История версий» / «⋯»")
    check(card["save"] and card["discard"], label,
          "нет «Сохранить» / «Отменить несохранённое»")
    check(card["detailsCollapsed"], label,
          "технические подробности не свёрнуты")
    shot(page, shots, "card_%s" % label)

    # 1b) B2 (§2.2 п.8): «Подробности и диагностика» реально раскрывает
    # постоянный блок, а не просто закрывает меню. В свёрнутом виде сырых
    # id в DOM нет (они появляются только в раскрытом блоке).
    check(page.evaluate(
        "() => document.querySelectorAll('[data-pv-detail-line]').length") == 0,
        label, "технические строки отрисованы в свёрнутой карточке")
    page.click("[data-prompt-editor] [data-pv-more-toggle]")
    page.wait_for_selector("[data-pv-more-menu]", state="visible")
    page.click("[data-pv-more-details]")
    page.wait_for_timeout(350)
    det = page.evaluate(
        "() => { const d = document.querySelector('[data-prompt-editor]"
        " [data-pv-details]');"
        " return {menu: !!document.querySelector('[data-pv-more-menu]'),"
        " open: !!(d && d.open),"
        " lines: document.querySelectorAll('[data-pv-detail-line]').length,"
        " text: d ? (d.textContent || '').replace(/\\s+/g, ' ').trim() : ''}; }")
    check(det["menu"] is False, label, "меню не закрылось после пункта «Подробности»")
    check(det["open"] is True, label,
          "пункт «Подробности и диагностика» не раскрыл блок: %r" % (det,))
    check(det["lines"] >= 3, label,
          "в блоке подробностей нет технических строк: %r" % (det,))
    for needle in ("блок:", "ключ:", "область:", "действующая ревизия:"):
        check(needle in det["text"], label,
              "в подробностях нет %r: %r" % (needle, det["text"][:200]))
    shot(page, shots, "details_%s" % label)
    page.click("[data-prompt-editor] [data-pv-details] > summary")
    page.wait_for_timeout(250)
    check(page.evaluate(
        "() => document.querySelectorAll('[data-pv-detail-line]').length") == 0,
        label, "свёрнутые подробности продолжают держать сырые id в DOM")

    # 2) панель истории: заголовок, мета, первая страница, листание >50
    open_panel(page)
    meta = page.evaluate(
        "() => ({meta: (document.querySelector('[data-pv-panel-meta]') || {})"
        ".textContent || '', rows:"
        " document.querySelectorAll('[data-pv-row]').length,"
        " end: !!document.querySelector('[data-pv-end]'),"
        " more: !!document.querySelector('[data-pv-load-more]')})")
    meta_txt = (meta["meta"] or "").replace("\n", " ")
    for needle in ("действует", "исходный из кода", "базовый по выбору владельца"):
        check(needle in meta_txt, label,
              "в шапке панели нет %r: %r" % (needle, meta_txt[:200]))
    check(meta["rows"] == 50, label,
          "первая страница не 50 записей: %d" % meta["rows"])
    orders = [r["order"] for r in panel_rows(page)]
    check(orders[0] == "1", label,
          "порядок строк не начинается с 1: %r" % (orders[:3],))
    shot(page, shots, "history_%s" % label)
    page.click("[data-pv-load-more]")
    page.wait_for_timeout(500)
    rows2 = panel_rows(page)
    check(len(rows2) > 50, label,
          "история не листается дальше 50: %d" % len(rows2))
    check(len(rows2) == 100, label,
          "вторая страница не догрузила ровно 50: %d" % len(rows2))
    check([r["order"] for r in rows2][-1] == "100", label,
          "порядковые номера после догрузки не непрерывны")

    # 3) «Посмотреть» — полный дословный текст, без пересохранения
    posts_before = len(STATE["posts"])
    rev0 = row_rev(page, 0)
    click_row(page, 0, "[data-pv-row-view]")
    page.wait_for_selector("[data-pv-view-body]", state="visible")
    view = page.evaluate(
        "() => (document.querySelector('[data-pv-view-body]') || {}).textContent")
    check((view or "").strip() == _body(rev0).strip(), label,
          "текст версии показан не дословно/обрезан: %r" % (view,))
    check(len(STATE["posts"]) == posts_before, label,
          "просмотр текста сделал запись (пересохранение)")

    # 4) diff «было → стало»: красный/зелёный только на изменённых строках
    click_row(page, 3, "[data-pv-row-compare]")
    page.wait_for_selector("[data-prompt-history-diff]", state="visible")
    diff = page.evaluate(
        "() => ({add: document.querySelectorAll('.pv-diff__add').length,"
        " del: document.querySelectorAll('.pv-diff__del').length,"
        " ctx: document.querySelectorAll('.pv-diff__ctx').length,"
        " text: (document.querySelector('[data-prompt-history-diff]') || {})"
        ".textContent || ''})")
    check(diff["add"] >= 1 and diff["del"] >= 1, label,
          "diff без красных/зелёных строк изменений: %r" % (diff,))
    check(diff["ctx"] >= 1, label, "контекст diff не отрисован")
    check("вторая строка" in diff["text"], label, "diff не содержит текста версий")

    # 5) недоступные действия: причина вместо кнопки
    reasons = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
        ".map((el) => ({status: el.getAttribute('data-pv-status'),"
        " rev: el.getAttribute('data-prompt-history-revision') || '',"
        " activate: !!el.querySelector('[data-pv-row-activate]'),"
        " reason: ((el.querySelector('[data-pv-row-reason]') || {})"
        ".textContent || '').trim()}))")
    retired = [r for r in reasons if r["status"] == "retired"][0]
    check(retired["activate"] is False and "retired" in retired["reason"], label,
          "у retired-версии есть активная кнопка или нет причины: %r" % (retired,))
    incompat = [r for r in reasons if r["status"] == "incompatible"]
    check(bool(incompat), label, "несовместимой версии нет в ленте")
    if incompat:
        check(incompat[0]["activate"] is False
              and "Несовместима" in incompat[0]["reason"], label,
              "у несовместимой версии нет честной причины: %r" % (incompat[0],))
    # строка-событие без revision_id — «Применить» не рисуется
    events = [r for r in reasons if not r["rev"]]
    check(bool(events), label, "событий журнала нет в ленте")
    if events:
        check(events[0]["activate"] is False, label,
              "у события журнала есть кнопка «Применить»")

    # 6) «Применить эту версию»: server-confirmed, не оптимистично
    target_rev = row_rev(page, 4)
    click_row(page, 4, "[data-pv-row-activate]")
    page.wait_for_timeout(1200)
    activated = [p for p in STATE["posts"] if p["path"].endswith("/activate")]
    check(activated and activated[-1]["body"].get("revision_id") == target_rev,
          label, "активация не отправлена/не тем revision_id: %r" % (activated,))
    after = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
        ".filter((el) => el.getAttribute('data-pv-status') === 'active')"
        ".map((el) => el.getAttribute('data-prompt-history-revision'))")
    check(target_rev in after, label,
          "после активации активная версия не перечитана с сервера: %r" % (after,))
    # B4 (§2.2 п.6/§6 п.8): подтверждение успеха переживает перечитывание
    # состояния (`resetPanel` по reloadToken не имеет права его стирать).
    page.wait_for_timeout(1500)
    result_after_refresh = page.evaluate(
        "() => { const el = document.querySelector('[data-prompt-history-result]');"
        " return el ? (el.textContent || '').replace(/\\s+/g, ' ').trim() : ''; }")
    check("Сервер подтвердил" in result_after_refresh, label,
          "подтверждение «Применить» стёрто перечитыванием: %r"
          % (result_after_refresh,))

    # 7) «Назначить базовой» не меняет действующий текст
    text_before = page.evaluate(
        "() => (document.querySelector('[data-prompt-editor] textarea') || {})"
        ".value")
    active_before = page.evaluate(
        "() => { const el = document.querySelector('[data-pv-row]"
        "[data-pv-status=\"active\"]');"
        " return el ? el.getAttribute('data-prompt-history-revision') : ''; }")
    activates_before = len([p for p in STATE["posts"]
                            if p["path"].endswith("/activate")])
    baseline_rev = row_rev(page, 5)
    click_row(page, 5, "[data-pv-row-baseline]")
    page.wait_for_timeout(900)
    result = page.evaluate(
        "() => ((document.querySelector('[data-prompt-history-result]') || {})"
        ".textContent || '').trim()")
    check("Базовая версия изменена, действующий текст пока прежний" in result,
          label, "нет честного сообщения о назначении базовой: %r" % (result,))
    text_after = page.evaluate(
        "() => (document.querySelector('[data-prompt-editor] textarea') || {})"
        ".value")
    check(text_before == text_after, label,
          "назначение базовой изменило действующий текст")
    check(any(p["method"] == "POST" and p["path"].endswith("/baseline")
              and p["body"].get("revision_id") == baseline_rev
              for p in STATE["posts"]), label,
          "POST /baseline не отправлен с выбранной версией")
    # B3 (§2.2 п.6, PVR-BASE-05): назначение базовой — ОТДЕЛЬНОЕ действие.
    # Мутация «assign дополнительно активирует» обязана падать здесь.
    activates_after = [p for p in STATE["posts"]
                       if p["path"].endswith("/activate")]
    check(len(activates_after) == activates_before, label,
          "«Назначить базовой» отправил POST /activate: %r"
          % (activates_after[activates_before:],))
    active_after = page.evaluate(
        "() => { const el = document.querySelector('[data-pv-row]"
        "[data-pv-status=\"active\"]');"
        " return el ? el.getAttribute('data-prompt-history-revision') : ''; }")
    check(active_after == active_before and active_after != baseline_rev,
          label,
          "назначение базовой сменило активную ревизию: %r -> %r"
          % (active_before, active_after))

    # 8) снятие назначения и восстановление базовой
    page.click("[data-pv-clear-baseline]")
    page.wait_for_timeout(700)
    check(any(p["method"] == "DELETE" and p["path"].endswith("/baseline")
              for p in STATE["posts"]), label, "DELETE /baseline не отправлен")
    click_row(page, 6, "[data-pv-row-baseline]")
    page.wait_for_timeout(800)
    page.click("[data-pv-restore-baseline]")
    page.wait_for_timeout(900)
    check(any(p["path"].endswith("/baseline/restore") for p in STATE["posts"]),
          label, "POST /baseline/restore не отправлен")

    # 9) возврат исходной из кода — с подтверждением
    page.click("[data-pv-factory-restore]")
    page.wait_for_timeout(700)
    check(any(p["path"].endswith("/factory/restore") for p in STATE["posts"]),
          label, "POST /factory/restore не отправлен")
    check(STATE["factory_restored"], label, "фабричный возврат не применён")

    # 10) «Скопировать глобально» в чатовой области
    copied = page.evaluate(
        "() => { const b = document.querySelector('[data-pv-row-copy-global]');"
        " if (!b) return false; b.click(); return true; }")
    check(copied, label, "кнопки «Скопировать глобально» нет в чатовой области")
    page.wait_for_timeout(900)
    check(any(p["path"].endswith("/copy-to-global") for p in STATE["posts"]),
          label, "POST /copy-to-global не отправлен")

    page.click("[data-pv-panel-close]")
    page.wait_for_timeout(300)

    # 11) черновик: индикатор, подтверждение при смене чата, сохранение
    ta = page.locator("[data-prompt-editor] textarea").first
    ta.click()
    ta.type(" ДОПИСАНО", delay=2)
    page.wait_for_timeout(300)
    check(page.evaluate(
        "() => !!document.querySelector('[data-prompt-editor]"
        " [data-pv-dirty]')"), label, "нет индикатора несохранённого черновика")
    shot(page, shots, "dirty_%s" % label)
    page.click(".scope-trigger")
    page.wait_for_selector(".scope-panel", state="visible")
    DIALOG_MODE["mode"] = "dismiss"
    page.locator(".scope-option", has_text="Чат B").first.click()
    page.wait_for_timeout(600)
    DIALOG_MODE["mode"] = "accept"
    check(any("сохран" in d.lower() for d in DIALOGS), label,
          "смена чата не спросила подтверждение: %r" % (DIALOGS,))
    value = page.evaluate(
        "() => (document.querySelector('[data-prompt-editor] textarea') || {})"
        ".value")
    check("ДОПИСАНО" in (value or ""), label,
          "после отмены подтверждения черновик потерян: %r" % (value,))

    # 12) журнал недоступен: честный 503-текст, черновик остаётся
    STATE["journal_down"] = True
    page.click("[data-prompt-history-toggle]")
    page.wait_for_selector("[data-pv-panel-error]", state="visible")
    err = page.evaluate(
        "() => ((document.querySelector('[data-pv-panel-error]') || {})"
        ".textContent || '').trim()")
    check("Журнал версий недоступен" in err, label,
          "503 журнала не показан честно: %r" % (err,))
    check(page.evaluate(
        "() => document.querySelectorAll('[data-pv-row-activate]').length") == 0,
        label, "при недоступном журнале рисуются кнопки действий")
    page.click("[data-pv-panel-close]")
    STATE["journal_down"] = False
    value2 = page.evaluate(
        "() => (document.querySelector('[data-prompt-editor] textarea') || {})"
        ".value")
    check("ДОПИСАНО" in (value2 or ""), label,
          "после отказа журнала черновик потерян")

    # 13) горизонтальный скролл страницы
    check(hscroll(page) <= 1, label,
          "горизонтальный скролл в редакторе: %d px" % hscroll(page))
    return True


def run_memes(label, page, shots, width):
    page.goto(BASE + "/#/modules/initiative/memes", wait_until="load")
    page.wait_for_selector("[data-ini-prompt='joke']", state="visible")
    page.wait_for_timeout(900)
    geo = page.evaluate(r"""
        () => {
          const r = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const b = el.getBoundingClientRect();
            return {top: Math.round(b.top), left: Math.round(b.left),
                    w: Math.round(b.width)};
          };
          return {joke: r("[data-ini-prompt='joke']"),
                  image: r("[data-ini-prompt='image']"),
                  cards: document.querySelectorAll(
                    "[data-ini-prompt] [data-prompt-history]").length,
                  raw: /\\{joke\\}:\\s*\\d/.test(document.body.textContent || "")};
        }
    """)
    check(geo["cards"] == 2, label,
          "у двух промптов мемов не по карточке версий: %r" % (geo,))
    check(geo["raw"] is False, label, "сырой счётчик «{joke}: 0» остался на экране")
    if width >= 1024:
        check(geo["joke"]["top"] == geo["image"]["top"], label,
              "на широком экране промпты мемов не рядом: %r" % (geo,))
    else:
        check(geo["image"]["top"] > geo["joke"]["top"], label,
              "на мобильном промпты мемов не столбиком: %r" % (geo,))
    shot(page, shots, "memes_%s" % label)
    check(hscroll(page) <= 1, label,
          "горизонтальный скролл в мемах: %d px" % hscroll(page))

    # три режима {joke}: 0 → append, 1 → slot, 2 → ошибка конфигурации
    for ph, needle in ((0, "добавится после шаблона"),
                       (1, "в отмеченное место"),
                       (2, "не более одного {joke}")):
        STATE["meme_placeholders"] = ph
        page.reload(wait_until="load")
        page.wait_for_selector("[data-meme-prompt-image]", state="visible")
        page.wait_for_timeout(800)
        body = page.evaluate(
            "() => (document.body.textContent || '').replace(/\\s+/g, ' ')")
        check(needle in body, label,
              "подсказка {joke} для режима %d не найдена (%r)" % (ph, needle))
        check(("{joke}: %d" % ph) not in body, label,
              "сырой «{joke}: %d» всё ещё виден" % ph)
    STATE["meme_placeholders"] = 0
    return True


DIALOGS = []


def run_speech_core(label, page, shots, width):
    """B1 (§2 / §2.2 п.1): раздел «Характер» — единый компонент версий.

    Проверяется в реальном UI: одна карточка компонента, кнопка «История
    версий», полная пагинация журнала (>50) и отсутствие прежнего
    bounded-списка с сырым sha и отдельным «Откатить». Плюс «Применить»
    перечитывает серверный текст редакции, а подтверждение успеха остаётся
    видимым (B4) — тот же компонент, то же поведение, что у промптов мемов.
    """
    page.goto(BASE + "/#/ai/speech", wait_until="load")
    page.wait_for_selector(".speech-screen", state="visible")
    page.wait_for_timeout(700)
    # Реальный путь владельца: «Правила и источники» → «Редактор Core».
    page.click("[data-speech-area='rules']")
    page.wait_for_selector("[data-speech-rules-link='core']", state="visible")
    page.click("[data-speech-rules-link='core']")
    page.wait_for_selector("[data-speech-core-versions] [data-prompt-history-toggle]",
                           state="visible")
    page.wait_for_timeout(600)
    info = page.evaluate(r"""
        () => {
          const tx = (el) => ((el && el.textContent) || '')
            .replace(/\s+/g, ' ').trim();
          const card = document.querySelector(
            '[data-speech-core-versions] [data-prompt-history]');
          const sec = document.querySelector('.speech-section');
          return {
            cards: document.querySelectorAll(
              '[data-speech-core-versions] [data-prompt-history]').length,
            key: card ? card.getAttribute('data-pv-key') : null,
            variant: card ? card.getAttribute('data-pv-variant') : null,
            state: tx(document.querySelector(
              '[data-speech-core-versions] [data-pv-state]')),
            legacy: !!document.querySelector('[data-speech-core-more]'),
            rollback: /Откатить/.test(tx(sec)),
            rawInCard: /sha256|sha [0-9a-f]{8}|act:[0-9a-f]{6}/.test(tx(card)),
            textarea: (document.querySelector(
              '.speech-section textarea.speech-editor') || {}).value,
          };
        }
    """)
    check(info["cards"] == 1, label,
          "в «Характере» не одна карточка версий: %r" % (info,))
    check(info["key"] == "core.personality", label,
          "карточка «Характера» привязана не к активной редакции: %r" % (info,))
    check(info["variant"] == "bar", label,
          "карточка «Характера» не компактная полоса компонента: %r" % (info,))
    check(info["legacy"] is False, label,
          "legacy-блок «Дополнительно: версии и откат» остался в DOM")
    check(info["rollback"] is False, label,
          "отдельный «Откатить» остался в разделе «Характер»")
    check(info["rawInCard"] is False, label,
          "в карточке «Характера» видны сырые id/sha: %r" % (info["state"],))
    check(bool(info["state"]), label, "состояние версий не показано")
    shot(page, shots, "speech_core_%s" % label)

    # B1: «Характер» — два prompt-поля одного документа. Карточка следует за
    # активной редакцией, поэтому история каждой редакции — своя (не хардкод).
    page.locator(".speech-tab", has_text="Компактная").first.click()
    page.wait_for_timeout(700)
    key_compact = page.evaluate(
        "() => { const c = document.querySelector("
        "'[data-speech-core-versions] [data-prompt-history]');"
        " return c ? c.getAttribute('data-pv-key') : null; }")
    check(key_compact == "core.personality.compact", label,
          "карточка «Характера» не переключилась на компактную редакцию: %r"
          % (key_compact,))
    page.locator(".speech-tab", has_text="Полная").first.click()
    page.wait_for_timeout(600)
    key_full = page.evaluate(
        "() => { const c = document.querySelector("
        "'[data-speech-core-versions] [data-prompt-history]');"
        " return c ? c.getAttribute('data-pv-key') : null; }")
    check(key_full == "core.personality", label,
          "карточка «Характера» не вернулась к полной редакции: %r" % (key_full,))

    open_panel(page)
    rows = panel_rows(page)
    check(len(rows) == 50, label,
          "первая страница истории «Характера» не 50 записей: %d" % len(rows))
    page.click("[data-pv-load-more]")
    page.wait_for_timeout(600)
    rows2 = panel_rows(page)
    check(len(rows2) > 50, label,
          "история «Характера» не листается дальше 50: %d" % len(rows2))
    shot(page, shots, "speech_history_%s" % label)

    # B4 + честное перечитывание: «Применить» меняет серверный текст, редактор
    # перечитывает раздел, а сообщение сервера остаётся видимым.
    target = row_rev(page, 0)
    click_row(page, 0, "[data-pv-row-activate]")
    page.wait_for_timeout(1800)
    res = page.evaluate(
        "() => ((document.querySelector('[data-prompt-history-result]') || {})"
        ".textContent || '').replace(/\\s+/g, ' ').trim()")
    check("Сервер подтвердил" in res, label,
          "подтверждение «Применить» в «Характере» не видно после "
          "перечитывания: %r" % (res,))
    value = page.evaluate(
        "() => (document.querySelector('.speech-section textarea.speech-editor')"
        " || {}).value")
    check((value or "").strip() == _body(target).strip(), label,
          "редактор «Характера» не перечитал применённый текст: %r"
          % ((value or "")[:120],))
    page.click("[data-pv-panel-close]")
    page.wait_for_timeout(300)
    check(hscroll(page) <= 1, label,
          "горизонтальный скролл в «Характере»: %d px" % hscroll(page))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--port", type=int, default=0)
    args, _ = ap.parse_known_args()

    global PORT, BASE
    if args.port:
        PORT = args.port
        BASE = "http://127.0.0.1:%d" % PORT
    STATE["entries"] = build_entries()
    serve_static(PORT, os.path.abspath(args.webroot))
    print("[pvr-s4-e2e] webroot = %s" % os.path.abspath(args.webroot))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        matrix = [(1536, 900, "1536"), (390, 844, "390"),
                  (1366, 768, "1366"), (768, 1024, "768"),
                  (360, 780, "360")]
        for width, height, label in matrix:
            DIALOGS.clear()
            STATE["posts"] = []
            STATE["gets"] = []
            STATE["active"] = "rev-manual-2"
            STATE["baseline"] = None
            STATE["factory_restored"] = False
            STATE["journal_down"] = False
            STATE["core_text"] = {
                "full": "ПОЛНЫЙ ХАРАКТЕР: спокойный, точный, без пафоса.",
                "compact": "КОМПАКТНЫЙ ХАРАКТЕР: спокойный и точный.",
            }
            ctx, page = new_page(browser, width, height)
            try:
                if width >= 768:
                    run_editor(label, page, args.shots, width)
                    run_memes(label, page, args.shots, width)
                else:
                    # мобильный полноэкранный вариант панели
                    run_editor(label, page, args.shots, width)
                    run_memes(label, page, args.shots, width)
                run_speech_core(label, page, args.shots, width)
                check(hscroll(page) <= 1, label,
                      "горизонтальный скролл итог: %d px" % hscroll(page))
            except Exception as exc:  # noqa: BLE001
                fail(label, "исключение: %s" % str(exc)[:300])
            finally:
                ctx.close()
        browser.close()

    print("\n== Итог: failures=%d" % len(failures))
    for f in failures:
        print("  - %s" % f)
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"failures": failures, "notes": notes}, fh,
                      ensure_ascii=False, indent=2)
    if failures:
        sys.exit(1)
    print("PVR-S4-OK")


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright  # noqa: F401
    main()
