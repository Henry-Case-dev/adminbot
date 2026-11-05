# -*- coding: utf-8 -*-
"""UR-F (UNIFIED-REPLY UI-волна + BGS-06 UI half) — визуальный Playwright-E2E.

Детерминированная проверка НАСТОЯЩЕГО `web/index.html` + `web/app.js`
(сервер — переиспользование `tools/ui_round1025_matrix.py`; API — честные
стабы эффективного конфига/часов/трассы хода; секретов нет, живая отправка
в Telegram не выполняется).

Проверки:
  * «Модули → Время» (UR-29.1/29.2): редактор с полным IANA-справочником
    (поиск по подстроке), серверные часы (не браузерные), источник,
    наследование; без h-скролла на 390 и 1440;
  * мёртвые ключи (UR-14.2/UR-21.13/UR-21.17): стилевые якоря/настроение/
    Anchors-доля/Response-доля отсутствуют в рабочем UI «Прямых ответов»;
  * честные подписи (UR-21.23/BGS-06.3): «Свобода формулировок» + пометка
    про игнор temperature; «Частота участия»; «История того, кому бот уже
    отвечал»;
  * диагностика одного ответа (R-ADM.5/UR-20.3): инспектор «Что бот видел»
    рендерит L1/tools/Writer/ops/delivery из полей трассы;
  * «Как бот отвечает» (UR-20.2): режимы из effective-config;
  * консоль браузера чиста на всех проверенных экранах.

Запуск: .venv/Scripts/python.exe tools/ui_urf_visual_e2e.py [--out DIR]
Артефакты по умолчанию: plans/features/unified-reply/evidence/urf/
"""
import datetime
import json
import os
import sys
import threading
import zoneinfo
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8852
DEFAULT_SHOTS = os.path.join(REPO, "plans", "features", "unified-reply",
                             "evidence", "urf")
CHAT_ID = -1001234567890

DEAD_KEYS = (
    "flags.chat_style_anchors_enabled", "limits.chat_style_anchors_count",
    "limits.chat_style_anchor_max_chars", "limits.chat_budget_anchors_ratio",
    "flags.chat_mood_enabled", "reactions.chat_mood_positive_words",
    "reactions.chat_mood_negative_words", "limits.chat_budget_response_ratio",
    "limits.chat_lock_max_entries",
)

TZ = "Europe/Moscow"


def _tz_state(*, configured="Europe/Moscow", source="chat", chat_id=None):
    """Честный payload /api/config/time — всё считает сервер (zoneinfo)."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    local = now_utc.astimezone(zoneinfo.ZoneInfo(TZ))
    offset = local.utcoffset() or datetime.timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    offset_str = "%s%02d:%02d" % (sign, total // 3600, (total % 3600) // 60)
    dst = offset.dst() if hasattr(offset, "dst") else None
    return {
        "chat_id": chat_id,
        "iana": TZ,
        "source": source,
        "config_version": "2026-11-06T08:00:00+00:00",
        "configured": configured,
        "now_local": local.isoformat(),
        "as_of_utc": now_utc.isoformat(),
        "utc_offset": offset_str,
        "is_dst": bool(dst),
        "weekday": ["понедельник", "вторник", "среда", "четверг", "пятница",
                    "суббота", "воскресенье"][local.weekday()],
        "utc_fallback": False,
    }


def _config_stub() -> dict:
    """/api/config из реального каталога + effective-поля UR-22.1.

    Мёртвые ключи (hidden) НЕ приходят — как из продового routes.py."""
    from services import param_catalog as pc
    items = []
    demo_eff = {
        # UR-21.23: пометка про reasoning-модель (честный display-кейс).
        "limits.chat_temperature_preset_default": {
            "status": "inactive",
            "active_consumer": "сэмплинг модели ответов",
            "units": "",
            "reason_inactive": "Текущая модель ответов относится к "
                "reasoning-семейству: провайдер принимает, но игнорирует "
                "temperature — режим «Свобода формулировок» на неё не влияет.",
        },
        "limits.anticliche_max_patterns": {
            "status": "legacy",
            "active_consumer": "детектор клише (только диагностика)",
            "units": "паттернов",
            "reason_inactive": "Лимит детектора; повторную генерацию не "
                "обещает.",
        },
    }
    for key, spec in sorted(pc.REGISTRY.items()):
        if getattr(spec, "hidden", False):
            continue
        pg_key = getattr(spec, "pg_key", None) or key
        secret = bool(getattr(spec, "secret", False))
        widget = getattr(spec, "widget", "") or ""
        stype = getattr(spec, "type", "str") or "str"
        if secret:
            value = {"configured": True, "last4": "0000"}
        elif widget == "keyvalue":
            value = {}
        elif stype == "bool":
            value = False
        elif stype in ("int", "float"):
            value = 1
        elif widget == "select" and getattr(spec, "select_options", None):
            value = list(spec.select_options)[0]
        else:
            value = ""
        eff = dict(demo_eff.get(pg_key) or {})
        eff.setdefault("status", "active")
        eff.setdefault("active_consumer", "")
        eff.setdefault("units", "")
        eff.setdefault("reason_inactive", "")
        # Честный 3-статус источника: одна явная global-строка для демо.
        source = "default"
        if pg_key in ("limits.search_max_symbols",
                      "limits.chat_temperature_preset_default"):
            source = "global"
        items.append({
            "key": pg_key, "value": value, "category": spec.category,
            "secret": secret, "chat_source": "", "global_value": None,
            "effective_value": value, "source": source, "eff": eff,
            "title": getattr(spec, "title_ru", key) or key, "type": stype,
            "updated_at": ("2026-08-30T01:00:00+00:00"
                           if source == "global" else None),
            "group": getattr(spec, "group", "") or "",
            "description": getattr(spec, "description", "") or "",
            "widget": widget,
            "select_options": list(spec.select_options)
            if widget == "select" and getattr(spec, "select_options", None)
            else None,
            "select_labels": list(spec.select_labels)
            if widget == "select" and getattr(spec, "select_labels", None)
            else None,
            "per_chat": bool(getattr(spec, "per_chat", False)),
            "progressive_level": "basic",
            "stage": getattr(spec, "stage", None),
            "view_roles": [], "edit_roles": [], "chat_updated_at": None,
        })
    present = {it["category"] for it in items}
    groups = [{"id": g.id, "category": g.category, "title": g.title_ru,
               "description": g.description, "order": g.order}
              for g in pc.GROUPS if g.category in present]
    groups.sort(key=lambda g: g["order"])
    return {"items": items, "groups": groups}


TURN_DIAG_STUB = {
    "chat_id": CHAT_ID, "available": True, "trace_id": "corr-urf-1",
    "turns": [{"trace_id": "corr-urf-1", "ts": 1792230000,
               "trigger": "turn_context"}],
    "context": {
        "outcome": "success", "ts": 1792230000, "flow": "direct",
        "trigger": "botword",
        "l1": {"action": "reply", "model": "test-model-8b",
               "plan_source": "l1_slot"},
        "tool_rounds": 1, "tool_degraded": False, "tool_reason": "",
        "tools": [{"tool": "web_search", "status": "success", "error": "",
                   "out_chars": 800, "truncated": False, "attempt": 1,
                   "refs": 3}],
        "coverage": {"sources": 3, "delivered": 2, "capacity_chars": 12000,
                     "delivered_chars": 900, "limits": 0},
        "llm_calls": {"planning": 1, "final": 1},
        "idempotency_key": "direct:-100:1:r1:-",
        "clock": {"timezone": TZ,
                  "as_of_utc": "2026-11-06T12:00:00+00:00",
                  "timezone_source": "chat",
                  "config_version": "2026-11-06T08:00:00+00:00"},
        "stop_reason": "",
    },
    "writer": {
        "outcome": "success", "ts": 1792230001,
        "manifest": {"manifest_id": "mf-1", "writer": "l2_writer",
                     "composer": True, "tokens_total": 6400,
                     "blocks": [{"block": "ctx:thread", "rendered": True,
                                 "skip": ""},
                                {"block": "evidence:web", "rendered": True,
                                 "skip": ""}],
                     "revisions": {"prompts.direct_chat_verbalizer_"
                                   "system_prompt": "v7"}},
        "request": {"provider": "api.example", "model": "test-model-8b",
                    "fallback_model": "", "max_output_tokens": 4096},
        "completion": {"finish_reason": "stop", "metadata_available": True,
                       "completed": True, "is_truncated": False, "attempt": 1,
                       "fallback_used": False, "usage": {"total_tokens": 980},
                       "chars": 420, "continuation_calls": 0,
                       "text_source": "author"},
        "semantic_rewrite_count": 0, "llm_calls": {"final": 1},
    },
    "delivery": {
        "outcome": "success", "ts": 1792230002,
        "ops": [{"op": "telegram_chunk", "digest": "ab12cd34", "chars": 420,
                 "changed": False, "chunks": 1}],
        "raw_final_digest": "ab12cd34", "delivered_digest": "ab12cd34",
        "digest_match": True, "divergence_reason": "",
        "semantic_rewrite_count": 0,
        "delivery": {"outcome": "success", "channel": "reply",
                     "tg_message_ids": [42],
                     "idempotency_key": "direct:-100:1:r1:-"},
    },
    "ts": 1792230002,
}


class _Handler(M._Handler):
    pass


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _routes():
    config_data = _config_stub()

    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps([
                              {"chat_id": CHAT_ID, "title": "Audit Chat",
                               "type": "supergroup", "is_dm": False,
                               "photo_file_id": None, "access": "admin"}]))
            return
        if url.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(config_data))
            return
        if url.endswith("/api/config/timezones"):
            zones = sorted(zoneinfo.available_timezones())
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"zones": zones,
                                           "count": len(zones)}))
            return
        if url.endswith("/api/config/time"):
            # Scope-aware: как реальный backend — X-Chat-Id → состояние чата.
            chat_hdr = (route.request.headers or {}).get("x-chat-id")
            if chat_hdr:
                payload = _tz_state(configured="Europe/Moscow",
                                    source="chat", chat_id=CHAT_ID)
            else:
                payload = _tz_state(configured=None, source="global",
                                    chat_id=None)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))
            return
        if url.endswith("/api/direct/turn-diagnostics"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(TURN_DIAG_STUB))
            return
        payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))

    return _route


PROBE_TIME = r"""
() => {
  const q = (s) => document.querySelector(s);
  const editor = q('[data-time-editor]');
  if (!editor) return {ok: false, why: 'no editor'};
  const input = q('[data-time-zone-input]');
  if (!input) return {ok: false, why: 'no input'};
  // Поиск по полному справочнику: подстрока 'lon' → список с London.
  input.value = 'lon';
  input.dispatchEvent(new Event('input', {bubbles: true}));
  return new Promise((resolve) => {
    setTimeout(() => {
      const list = document.querySelectorAll('[data-time-zone-list] button');
      const clock = q('[data-time-clock]');
      const source = q('[data-time-source-line]');
      const r = editor.getBoundingClientRect();
      resolve({
        ok: true,
        matches: Array.from(list).slice(0, 6).map((b) => b.textContent.trim()),
        matchCount: list.length,
        fullListHint: !!q('[data-time-zone-list]'),
        clock: clock ? clock.textContent.trim() : '',
        clockLive: !!(clock && /\d{2}:\d{2}:\d{2}/.test(clock.textContent)),
        sourceLine: source ? source.textContent.trim() : '',
        tzBadge: (q('[data-time-tz-badge]') || {}).textContent || '',
        offsetLine: (q('[data-time-offset]') || {}).textContent || '',
        scopeLine: (q('[data-time-scope-line]') || {}).textContent || '',
        hasSave: !!Array.from(document.querySelectorAll('[data-time-actions] button'))
          .find((b) => /Сохранить/.test(b.textContent)),
        hasReset: !!Array.from(document.querySelectorAll('[data-time-actions] button'))
          .find((b) => /Вернуть общую настройку/.test(b.textContent)),
        editorRect: {left: Math.round(r.left), right: Math.round(r.right)},
        vw: window.innerWidth,
        hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
      });
    }, 150);
  });
}
"""

PROBE_DIRECT_SETTINGS = r"""
() => {
  const txt = document.body.textContent || '';
  // Мёртвые ключи (UR-14.2/UR-21.13/UR-21.17): hidden-ключи НЕ приходят
  // из /api/config → их карточки нигде не рендерятся.
  const deadTitles = ['Стилевые якоря', 'Определение настроения собеседника',
    'Доля бюджета: Anchors', 'Число стилевых якорей', 'CSV позитивных слов',
    'Доля бюджета: Response'];
  const found = deadTitles.filter((t) => txt.indexOf(t) >= 0);
  const honest = {
    speech: txt.indexOf('Свобода формулировок') >= 0,
    temperatureNote: txt.indexOf('игнорирует temperature') >= 0,
    participation: txt.indexOf('Частота участия') >= 0,
    replyHistory: txt.indexOf('История того, кому бот уже отвечал') >= 0,
    expertCap: txt.indexOf('экспертный') >= 0,
    serviceGroup: txt.indexOf('Служебное') >= 0,
    machineFlagsPanel: txt.indexOf('privacy score') >= 0
      || txt.indexOf('safety guard') >= 0,
  };
  const groups = document.querySelectorAll('[data-config-group]');
  return {ok: true, deadFound: found, groups: groups.length, honest: honest,
          vw: window.innerWidth,
          hScroll: document.documentElement.scrollWidth
            > window.innerWidth + 1};
}
"""

PROBE_INSPECTOR = r"""
() => {
  const q = (s) => document.querySelector(s);
  const wrap = q('[data-turn-inspector]');
  if (!wrap) return {ok: false, why: 'no inspector'};
  const t = wrap.textContent || '';
  const stages = {
    l1: !!q('[data-turn-stage="l1"]'),
    tools: !!q('[data-turn-stage="tools"]'),
    writer: !!q('[data-turn-stage="writer"]'),
    delivery: !!q('[data-turn-stage="delivery"]'),
  };
  return {
    ok: true, stages: stages,
    l1Action: (q('[data-turn-l1-action]') || {}).textContent || '',
    clockLine: (q('[data-turn-clock-line]') || {}).textContent || '',
    toolRow: (document.querySelector('[data-turn-tool-row]') || {})
      .textContent || '',
    completion: (q('[data-turn-writer-completion]') || {}).textContent || '',
    opRow: (document.querySelector('[data-turn-op-row]') || {})
      .textContent || '',
    deliveryLine: (q('[data-turn-delivery-line]') || {}).textContent || '',
    turnButtons: document.querySelectorAll('[data-turn-btn]').length,
    traceId: (q('[data-turn-meta]') || {}).textContent || '',
    hasToolWord: t.indexOf('web_search') >= 0,
    hasWriterWord: t.indexOf('l2_writer') >= 0,
    deliveredAsWritten: t.indexOf('как написан') >= 0,
    vw: window.innerWidth,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
}
"""

PROBE_MODES = r"""
() => {
  const wrap = document.querySelector('[data-direct-modes]');
  if (!wrap) return {ok: false, why: 'no modes card'};
  const rows = Array.from(document.querySelectorAll('[data-mode-row]'));
  return {
    ok: true,
    titles: rows.map((r) => (r.querySelector('[data-mode-badge]')
      ? r.getAttribute('data-mode-row') : r.getAttribute('data-mode-row'))),
    badges: rows.map((r) => {
      const b = r.querySelector('[data-mode-badge]');
      return b ? b.textContent.trim() : '';
    }),
    speechNote: (wrap.textContent || '').indexOf('игнорирует temperature') >= 0,
    vw: window.innerWidth,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
}
"""


def _shoot(page, name, out_dir):
    page.screenshot(path=os.path.join(out_dir, name + ".png"), full_page=False)


def main() -> int:
    out_dir = DEFAULT_SHOTS
    if "--out" in sys.argv:
        out_dir = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
    os.makedirs(out_dir, exist_ok=True)
    _start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    results = {}
    console_errors = []

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, width, height in (("desktop-1440", 1440, 900),
                                     ("mobile-390", 390, 844)):
            ctx = browser.new_context(viewport={"width": width,
                                                "height": height},
                                      device_scale_factor=1)
            page = ctx.new_page()
            page.on("console", lambda msg: console_errors.append(
                msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: console_errors.append(
                str(exc)))
            # API-стабы: /api/** отвечает _routes() (честные данные UR-F).
            page.route("**/api/**", _routes())
            page.add_init_script(M.TMA_STUB)
            # «Модули → Время» (UR-29.1/29.2): ждём РЕАЛЬНОЕ состояние
            # (часы/список зон — из ответов API), не фиксированную паузу.
            page.goto(base + "#/modules/time")
            try:
                page.wait_for_selector("[data-time-clock]", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            results["time-" + label] = page.evaluate(PROBE_TIME)
            _shoot(page, "urf-time-" + label, out_dir)

            page.goto(base + "#/modules/direct/settings")
            try:
                page.wait_for_selector(
                    '[data-config-group="flags_chat_behavior"]',
                    timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            results["direct-settings-" + label] = page.evaluate(
                PROBE_DIRECT_SETTINGS)
            _shoot(page, "urf-direct-settings-" + label, out_dir)

            # Честные подписи действующих ключей (UR-21.x) живут на вкладке
            # «Лимиты» workspace (workspaceGroupTab: limits → 'limits').
            page.goto(base + "#/modules/direct/limits")
            try:
                page.wait_for_selector(
                    '[data-config-group="limits_temperature"]',
                    timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            results["direct-limits-" + label] = page.evaluate(
                PROBE_DIRECT_SETTINGS)
            _shoot(page, "urf-direct-limits-" + label, out_dir)

            # UR-21.20: технические ожидания очереди — «Служебное» на вкладке
            # «Диагностика» (= «Технические ограничения» BGS-06.2).
            page.goto(base + "#/modules/checkup/limits")
            try:
                page.wait_for_selector(
                    '[data-config-group="limits_service"]', timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            results["checkup-limits-" + label] = page.evaluate(
                PROBE_DIRECT_SETTINGS)
            _shoot(page, "urf-checkup-limits-" + label, out_dir)

            page.goto(base + "#/modules/direct/inspector")
            try:
                page.wait_for_selector('[data-turn-stage="l1"]', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            results["inspector-" + label] = page.evaluate(PROBE_INSPECTOR)
            _shoot(page, "urf-inspector-" + label, out_dir)

            page.goto(base + "#/modules/direct")
            try:
                page.wait_for_selector("[data-direct-modes]", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            results["modes-" + label] = page.evaluate(PROBE_MODES)
            _shoot(page, "urf-modes-" + label, out_dir)
            ctx.close()
        browser.close()

    results["console_errors"] = console_errors[:20]
    results["console_error_count"] = len(console_errors)
    out_json = os.path.join(out_dir, "urf-visual-report.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)

    # ── Приёмочные инварианты (fail = ненулевой exit) ─────────────────────
    failures = []
    for label in ("time-desktop-1440", "time-mobile-390"):
        r = results.get(label) or {}
        if not r.get("ok"):
            failures.append(label + ": editor missing")
            continue
        if not r.get("clockLive"):
            failures.append(label + ": server clock not ticking")
        if r.get("matchCount", 0) < 1:
            failures.append(label + ": zone search empty")
        if "Europe/London" not in (r.get("matches") or []) and \
                "Atlantic/Canary" not in (r.get("matches") or []):
            failures.append(label + ": zone search wrong results "
                            + json.dumps(r.get("matches")))
        if not r.get("sourceLine"):
            failures.append(label + ": source line missing")
        if not r.get("hasSave") or not r.get("hasReset"):
            failures.append(label + ": save/reset buttons missing")
        if r.get("hScroll"):
            failures.append(label + ": horizontal scroll")
    for label in ("direct-settings-desktop-1440",
                  "direct-settings-mobile-390"):
        r = results.get(label) or {}
        if r.get("deadFound"):
            failures.append(label + ": dead keys visible "
                            + json.dumps(r["deadFound"]))
        if (r.get("honest") or {}).get("machineFlagsPanel"):
            failures.append(label + ": панель машинных флагов")
        if r.get("hScroll"):
            failures.append(label + ": horizontal scroll")
    for label in ("direct-limits-desktop-1440", "direct-limits-mobile-390"):
        r = results.get(label) or {}
        if r.get("deadFound"):
            failures.append(label + ": dead keys visible "
                            + json.dumps(r["deadFound"]))
        h = r.get("honest") or {}
        if not h.get("speech"):
            failures.append(label + ": «Свобода формулировок» отсутствует")
        if not h.get("temperatureNote"):
            failures.append(label + ": honest temperature note missing")
        if not h.get("participation"):
            failures.append(label + ": «Частота участия» отсутствует")
        if not h.get("replyHistory"):
            failures.append(label + ": «История того, кому бот уже отвечал»")
        if (h.get("machineFlagsPanel")):
            failures.append(label + ": панель машинных флагов")
        if r.get("hScroll"):
            failures.append(label + ": horizontal scroll")
    for label in ("checkup-limits-desktop-1440", "checkup-limits-mobile-390"):
        r = results.get(label) or {}
        if not (r.get("honest") or {}).get("serviceGroup"):
            failures.append(label + ": «Служебное» (lock waits) отсутствует")
        if r.get("hScroll"):
            failures.append(label + ": horizontal scroll")
    for label in ("inspector-desktop-1440", "inspector-mobile-390"):
        r = results.get(label) or {}
        stages = r.get("stages") or {}
        for stage in ("l1", "tools", "writer", "delivery"):
            if not stages.get(stage):
                failures.append(label + ": stage card missing " + stage)
        if not r.get("hasToolWord") or not r.get("hasWriterWord"):
            failures.append(label + ": trace fields not rendered")
        if not r.get("deliveredAsWritten"):
            failures.append(label + ": honest delivery line missing")
        if r.get("hScroll"):
            failures.append(label + ": horizontal scroll")
    for label in ("modes-desktop-1440", "modes-mobile-390"):
        r = results.get(label) or {}
        if not r.get("ok"):
            failures.append(label + ": modes card missing")
        elif len(r.get("titles") or []) < 5:
            failures.append(label + ": fewer than 5 modes")
    if results.get("console_error_count"):
        failures.append("console errors: "
                        + json.dumps(results["console_errors"][:5],
                                     ensure_ascii=False))

    print(json.dumps({k: v for k, v in results.items()
                      if k != "console_errors"}, ensure_ascii=False,
                     indent=1)[:4000])
    if failures:
        print("URF-VISUAL FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("URF-VISUAL-OK shots:", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
