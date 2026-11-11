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
import copy
import json
import os
import re
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
    # UR-F шаг 3 (§4): присутствие стадий — bool, UI не угадывает по пустым
    # объектам. Все семь стадий есть → все секции обязаны отрендериться.
    "stages": {"context": True, "writer": True, "delivery": True,
               "selection": True, "search": True, "tool_phase": True,
               "style": True},
    # UR-20.4: кто отвечал и кому. Длинные id (12 цифр) не обрезаются.
    "source": {"message_id": 987654321012, "author_id": 777,
               "author_alias": "Анна",
               "message_ts": 1792229900,
               "reply_to_id": 987654321000, "reply_to_author_id": 555,
               # Время сообщения-родителя (раньше его не было в событии).
               "reply_to_ts": 1792229400,
               "reply_to_alias": "Борис"},
    # UR-20.8: расширение существующего clock (плюс стадии часов).
    "clock": {"timezone": TZ,
              "as_of_utc": "2026-11-06T12:00:00+00:00",
              "timezone_source": "chat",
              "config_version": "2026-11-06T08:00:00+00:00",
              "stages": ["l1", "tool", "l2"]},
    # UR-20.5/20.6: снимок выбора (7 блоков → сворачивание после 5-го).
    "selection": {
        "policy_version": "ur-c/selection/v1",
        "counts": {"available_messages": 25, "included_messages": 12,
                   "window_messages": 40},
        "budget": {"slot": "direct.primary", "window": 128000,
                   "window_source": "model_map", "output_reserve": 12800,
                   "available": 110000, "budget": 16000,
                   "policy_mode": "dynamic", "payload_tokens": 5400,
                   "fallback_window": None},
        "blocks": [
            {"kind": "global_tail", "role": "p1", "rendered": True,
             "source_ids": ["msg:987654321012", "msg:987654321013"],
             "first_ts": 1792228800, "last_ts": 1792229900, "tokens": 800},
            {"kind": "thread", "role": "p1", "rendered": True,
             "source_ids": ["msg:987654321000"],
             "first_ts": 1792228200, "last_ts": 1792228299, "tokens": 320},
            {"kind": "rag", "role": "p2", "rendered": True,
             "source_ids": ["fact:42", "summary:-100500:2"],
             "first_ts": 1792000000, "last_ts": 1792100000, "tokens": 640},
            {"kind": "global_head", "role": "p2", "rendered": True,
             "source_ids": [], "first_ts": 1792000000,
             "last_ts": 1792050000, "tokens": 512},
            {"kind": "episode", "role": "p0", "rendered": True,
             "source_ids": ["episode:7"],
             "first_ts": 1791000000, "last_ts": 1791003600, "tokens": 480},
            {"kind": "protected", "role": "p0", "rendered": True,
             "source_ids": [], "first_ts": 0, "last_ts": 0, "tokens": 120},
            # Неизвестный код: UI обязан показать «код: mystery_kind».
            {"kind": "mystery_kind", "role": "p3", "rendered": False,
             "skip_reason": "budget_exceeded", "source_ids": [],
             "first_ts": 0, "last_ts": 0, "tokens": 0},
        ],
        "dropped": [{"reason_code": "budget_exceeded", "kind": "global_middle",
                     "count": 3},
                    {"reason_code": "duplicate_source", "kind": "thread",
                     "count": 1}],
        "dropped_total": 9,
        "self_outputs": [{"source_id": "bot_output:42",
                          "tg_message_id": 4242, "ts": 1792229800}],
        "truncated": True,
    },
    # UR-20.7: решение о поиске + ссылки выдачи (4 ссылки → «показать ещё»).
    "search": {
        "decision": "required", "called": True, "status": "ok",
        "skip_reason": "", "evidence_class": "web", "required": True,
        "source_count": 5,
        "source_ids": ["web:1", "web:2"],
        "links": [
            {"source_id": "web:1",
             "source_url": "https://example.test/very/long/path/" + "a" * 90,
             "source_title": "Длинный заголовок источника выдачи",
             "published_at": "2026-11-01"},
            {"source_id": "web:2",
             "source_url": "https://example.test/second",
             "source_title": "Второй источник", "published_at": None},
            {"source_id": "web:3",
             "source_url": "https://example.test/third",
             "source_title": "Третий источник", "published_at": "2026-10-20"},
            {"source_id": "web:4",
             "source_url": "https://example.test/fourth",
             "source_title": "Четвёртый источник",
             "published_at": "2026-10-10"},
        ],
    },
    # UR-20.8: правила стиля (6 правил → сворачивание после 4-го).
    "style": {
        "revision": "sp-2026-11-06", "source": "chat", "applied": True,
        "counts": {"pass": 4, "repaired": 2},
        "rules": [
            {"rule_id": "dash.hard.factory", "kind": "dash",
             "status": "repaired", "reason": "dash_replaced",
             "source": "factory"},
            {"rule_id": "quotes.hard.factory", "kind": "quotation_marks",
             "status": "pass", "reason": "", "source": "factory"},
            {"rule_id": "extent.check", "kind": "extent", "status": "pass",
             "reason": "", "source": "chat"},
            {"rule_id": "emoji.soft", "kind": "emoji", "status": "exempted",
             "reason": "protected_verbatim", "source": "chat"},
            {"rule_id": "line.breaks", "kind": "line_breaks",
             "status": "conflict", "reason": "line_breaks_exceeded",
             "source": "chat"},
            # Неизвестная причина: UI обязан показать «код: mystery_reason».
            {"rule_id": "one.word", "kind": "one_word", "status": "failed",
             "reason": "mystery_reason", "source": "chat"},
        ],
    },
    "context": {
        "outcome": "success", "ts": 1792230000, "flow": "direct",
        "trigger": "force_keyword",
        # UR-20.6: слот/модель ПЛАНИРОВАНИЯ L1 — выделенный слот
        # (`SlotBudgetMeta.slot`), а не «слот не зафиксирован».
        "l1": {"action": "reply", "model": "test-model-8b",
               "slot": "l1_slot",
               "fallback": "test-model-8b-fallback",
               "plan_source": "l1_slot"},
        "tool_rounds": 1, "tool_degraded": False, "tool_reason": "",
        # Имя инструмента и код ошибки — служебные значения: карточка обязана
        # назвать их словами (UR-20.7: реальный tool call), а не токенами.
        "tools": [{"tool": "execute_web_search", "status": "timeout",
                   "error": "search_timeout",
                   "out_chars": 800, "truncated": False, "attempt": 1,
                   "refs": 3}],
        "coverage": {"sources": 3, "delivered": 2, "capacity_chars": 12000,
                     "delivered_chars": 900, "limits": 0},
        # Карта счётчиков LLM-вызовов: раньше печаталась JSON'ом целиком.
        "llm_calls": {"planning": 1, "tool": 1, "final": 1,
                      "continuation": 0, "provider_retry": 1},
        "idempotency_key": "direct:-100:1:r1:-",
        "clock": {"timezone": TZ,
                  "as_of_utc": "2026-11-06T12:00:00+00:00",
                  "timezone_source": "chat",
                  "config_version": "2026-11-06T08:00:00+00:00",
                  "stages": ["l1", "tool", "l2"]},
        "stop_reason": "l1_silent",
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
                    "fallback_model": "test-model-8b-fallback",
                    "max_output_tokens": 4096},
        "completion": {"finish_reason": "stop", "metadata_available": True,
                       "completed": True, "is_truncated": False, "attempt": 1,
                       "fallback_used": False, "usage": {"total_tokens": 980},
                       "max_output_tokens_sent": 4096,
                       "chars": 420, "continuation_calls": 0,
                       "text_source": "source_restored",
                       # Находки проверок: код form-гарда + настоящие нули —
                       # всё это раньше печаталось JSON'ом (UR-20.8).
                       "checks": {"form_guard": "form_guard_leak_blocked",
                                  "protected_facts_mismatch": False,
                                  "needs_clarification": False,
                                  "numeric_mismatch": 0,
                                  "cliche_observed": 2,
                                  "format_observed": 0}},
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


def _delivery_variant(*, outcome: str, reason: str) -> dict:
    """Тот же ход, но с итогом доставки — для проверки строки причины.

    Карточка обязана назвать причину словами (и «код: …» для неизвестной),
    поэтому нужны три состояния: успех, известная причина, неизвестная."""
    data = copy.deepcopy(TURN_DIAG_STUB)
    data["delivery"]["outcome"] = outcome
    data["delivery"]["digest_match"] = False
    data["delivery"]["delivery"]["outcome"] = outcome
    data["delivery"]["delivery"]["reason"] = reason
    data["delivery"]["delivery"].pop("tg_message_ids", None)
    return data


#: `?turn=N` → вариант стаба (1 — успешная доставка, 2 — известная причина,
#: 3 — неизвестная причина: карточка обязана дать «код: …»).
TURN_DIAG_BY_TURN = {
    2: _delivery_variant(outcome="failed", reason="html_fallback"),
    3: _delivery_variant(outcome="failed", reason="mystery_delivery"),
}


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
            turn = 1
            found = re.search(r"[?&]turn=(\d+)", route.request.url)
            if found:
                turn = int(found.group(1))
            data = TURN_DIAG_BY_TURN.get(turn, TURN_DIAG_STUB)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(data))
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

PROBE_INSPECTOR_STEP3 = r"""
async () => {
  const q = (s) => document.querySelector(s);
  const all = (s) => Array.from(document.querySelectorAll(s));
  const wrap = q('[data-turn-inspector]');
  if (!wrap) return {ok: false, why: 'no inspector'};
  const flat = (node) => ((node && node.textContent) || '')
    .replace(/\s+/g, ' ').trim();
  const text = flat(wrap);
  const cards = all('[data-turn-stage]');
  const rects = cards.map((c) => {
    const r = c.getBoundingClientRect();
    return {left: Math.round(r.left), top: Math.round(r.top),
            width: Math.round(r.width)};
  });
  // «Ни одного неизвестного кода»: сырой код допустим ТОЛЬКО в скобках сразу
  // после подписи или после «код: ». Всё остальное — утечка токена в UI.
  const rawCodes = ['global_tail', 'thread', 'rag', 'global_head', 'episode',
    'protected', 'budget_exceeded', 'duplicate_source', 'required',
    'not_applicable', 'repaired', 'exempted', 'conflict', 'failed',
    'model_map', 'dynamic', 'reply_to_bot', 'dash', 'quotation_marks',
    'line_breaks', 'one_word', 'dash_replaced', 'line_breaks_exceeded',
    'protected_verbatim', 'l2_writer', 'p0', 'p1', 'p2', 'p3',
    // UR-20.3/20.6/20.7/20.8: коды LLM-вызовов, остановки, источника текста,
    // проверок, инструмента, его ошибки и причины недоставки — та же норма.
    'l1_silent', 'source_restored', 'execute_web_search', 'search_timeout',
    'planning', 'final', 'provider_retry', 'continuation',
    'form_guard', 'form_guard_leak_blocked', 'numeric_mismatch',
    'cliche_observed', 'html_fallback'];
  const unexplained = [];
  rawCodes.forEach((code) => {
    let at = text.indexOf(code);
    while (at >= 0) {
      const before = text.slice(Math.max(0, at - 80), at);
      const inParens = /\(\s*$/.test(before);
      const prefixed = /код:\s*$/.test(before);
      if (!inParens && !prefixed) {
        unexplained.push(code + ' ← ' + before.slice(-28));
      }
      at = text.indexOf(code, at + code.length);
    }
  });
  // Обрезка запрещена: ни `truncate`-класса, ни ellipsis, ни вылезания.
  const clipped = [];
  wrap.querySelectorAll('*').forEach((el) => {
    const st = getComputedStyle(el);
    if (st.textOverflow === 'ellipsis') clipped.push('ellipsis:' + el.className);
  });
  const out = {
    ok: true,
    titles: cards.map((c) => flat(c.querySelector('.font-semibold'))),
    cardRects: rects,
    sourceLine: flat(q('[data-turn-source]')),
    clockLine: flat(q('[data-turn-clock-line]')),
    clockStages: flat(q('[data-turn-clock-stages]')),
    modelL1: flat(q('[data-turn-model-l1]')),
    modelL2: flat(q('[data-turn-model-l2]')),
    blockSummaries: all('[data-turn-block-summary]').map(flat)
      .filter(Boolean),
    budget: flat(q('[data-turn-budget]')),
    counts: flat(q('[data-turn-counts]')),
    truncNote: flat(q('[data-turn-truncated]')),
    blockRows: all('[data-turn-block-row]').length,
    blockFirst: flat(all('[data-turn-block-row]')[0]),
    dropped: all('[data-turn-dropped] > div').map(flat).filter(Boolean),
    selfOutputs: all('[data-turn-self-outputs] > div').map(flat)
      .filter(Boolean),
    searchDecision: flat(q('[data-turn-search-decision]')),
    searchAction: flat(q('[data-turn-search-action]')),
    linkRows: all('[data-turn-link-row]').length,
    linkFirst: flat(all('[data-turn-link-row]')[0]),
    styleHead: flat(q('[data-turn-style-head]')),
    styleCounts: flat(q('[data-turn-style-counts]')),
    ruleRows: all('[data-turn-rule-row]').length,
    ruleFirst: flat(all('[data-turn-rule-row]')[0]),
    // UR-20.3/20.6/20.7/20.8: строки, которые раньше печатали значения
    // как есть.
    stopLine: flat(q('[data-turn-stop]')),
    llmCalls: flat(q('[data-turn-llm-calls]')),
    checksLine: flat(q('[data-turn-checks]')),
    textSourceLine: flat(q('[data-turn-text-source]')),
    toolFirst: flat(all('[data-turn-tool-row]')[0]),
    unexplained: unexplained,
    clipped: clipped,
    truncateClass: wrap.querySelectorAll('.truncate').length,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
    vw: window.innerWidth,
  };
  // Сворачивание: по умолчанию НЕ раскрыто, кнопка «показать ещё» работает.
  out.collapsedByDefault = out.blockRows === 5 && out.linkRows === 3
    && out.ruleRows === 4;
  const more = ['[data-turn-more-blocks]', '[data-turn-more-links]',
    '[data-turn-more-rules]'].map(q);
  out.moreButtons = more.filter(Boolean).length;
  more.forEach((b) => { if (b) b.click(); });
  await new Promise((r) => setTimeout(r, 250));
  // Неизвестные коды (block kind / reason) лежат в свёрнутых списках —
  // проверяем отрисовку после раскрытия: «код: <значение>», а не токен.
  const expandedText = flat(wrap);
  out.hasUnknownFallback = expandedText.indexOf('код: mystery_kind') >= 0
    && expandedText.indexOf('код: mystery_reason') >= 0;
  out.afterExpand = {
    blocks: all('[data-turn-block-row]').length,
    links: all('[data-turn-link-row]').length,
    rules: all('[data-turn-rule-row]').length,
    buttonsLeft: ['[data-turn-more-blocks]', '[data-turn-more-links]',
      '[data-turn-more-rules]'].filter(q).length,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
  // ── Строка доставки: успех, известная причина и неизвестная причина
  // (последняя обязана прийти как «код: …», а не сырым токеном бэкенда).
  const lineAtTurn = async (turn) => {
    const btn = q('[data-turn-btn="' + turn + '"]');
    if (btn) {
      btn.click();
      await new Promise((r) => setTimeout(r, 500));
    }
    return flat(q('[data-turn-delivery-line]'));
  };
  out.deliveryLineFailed = await lineAtTurn(2);
  out.deliveryLineUnknown = await lineAtTurn(3);
  await lineAtTurn(1);
  if (!out.deliveryLine) {
    out.deliveryLine = flat(q('[data-turn-delivery-line]'));
  }
  return out;
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


def _other_screens(page, base, label, results, out_dir):
    """Остальные экраны волны UR-F (не инспектор): прежние приёмки."""
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

    page.goto(base + "#/modules/direct")
    try:
        page.wait_for_selector("[data-direct-modes]", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(500)
    results["modes-" + label] = page.evaluate(PROBE_MODES)
    _shoot(page, "urf-modes-" + label, out_dir)


def main() -> int:
    out_dir = DEFAULT_SHOTS
    if "--out" in sys.argv:
        out_dir = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
    #: Узкий прогон: только инспектор хода (шаг 3). Остальные экраны волны
    #: проверяются полным прогоном; pytest гоняет узкий, чтобы не дублировать
    #: чужие приёмки.
    only_inspector = "--only-inspector" in sys.argv
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
            if not only_inspector:
                _other_screens(page, base, label, results, out_dir)

            page.goto(base + "#/modules/direct/inspector")
            try:
                page.wait_for_selector('[data-turn-stage="l1"]', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            # Свёрнутый вид снимаем ДО раскрытия списков (шаг 3 §5).
            _shoot(page, "urf-inspector-step3-collapsed-" + label, out_dir)
            # Карточки по отдельности: на телефоне в окно влезает одна-две.
            for stage in ("l1", "tools", "writer", "delivery"):
                try:
                    page.locator('[data-turn-stage="%s"]' % stage).screenshot(
                        path=os.path.join(
                            out_dir, "urf-inspector-step3-%s-%s.png"
                            % (stage, label)))
                except Exception:
                    pass
            results["inspector-" + label] = page.evaluate(PROBE_INSPECTOR)
            _shoot(page, "urf-inspector-" + label, out_dir)
            results["inspector3-" + label] = page.evaluate(
                PROBE_INSPECTOR_STEP3)
            _shoot(page, "urf-inspector-step3-expanded-" + label, out_dir)
            ctx.close()
        browser.close()

    results["console_errors"] = console_errors[:20]
    results["console_error_count"] = len(console_errors)
    out_json = os.path.join(out_dir, "urf-visual-report.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)

    # ── Приёмочные инварианты (fail = ненулевой exit) ─────────────────────
    failures = []
    if only_inspector:
        labels_other = ()
    else:
        labels_other = ("time-desktop-1440", "time-mobile-390")
    for label in labels_other:
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
    for label in (() if only_inspector else ("direct-settings-desktop-1440",
                  "direct-settings-mobile-390")):
        r = results.get(label) or {}
        if r.get("deadFound"):
            failures.append(label + ": dead keys visible "
                            + json.dumps(r["deadFound"]))
        if (r.get("honest") or {}).get("machineFlagsPanel"):
            failures.append(label + ": панель машинных флагов")
        if r.get("hScroll"):
            failures.append(label + ": horizontal scroll")
    for label in (() if only_inspector
                  else ("direct-limits-desktop-1440",
                        "direct-limits-mobile-390")):
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
    for label in (() if only_inspector
                  else ("checkup-limits-desktop-1440",
                        "checkup-limits-mobile-390")):
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
    # ── UR-F шаг 3 (§5): карточки, расшифровка кодов, сворачивание, мобильный
    titles = ["Планирование (L1)", "Инструменты и поиск", "Что видел ответ",
              "Операции и доставка"]
    for label in ("inspector3-desktop-1440", "inspector3-mobile-390"):
        r = results.get(label) or {}
        if not r.get("ok"):
            failures.append(label + ": step-3 probe failed")
            continue
        if r.get("titles") != titles:
            failures.append(label + ": card titles " + json.dumps(
                r.get("titles"), ensure_ascii=False))
        if "отвечал:" not in (r.get("sourceLine") or ""):
            failures.append(label + ": source (кто отвечал) not rendered")
        if "в ответ на:" not in (r.get("sourceLine") or ""):
            failures.append(label + ": source (на что ответ) not rendered")
        if "часы поданы на этапах" not in (r.get("clockStages") or ""):
            failures.append(label + ": clock stages line missing")
        # ── UR-20.4/20.5/20.6/20.8 (доработка шага 1): реальные строки карточек
        src_line = r.get("sourceLine") or ""
        if not re.search(r"в ответ на: .*сообщение 987654321000, "
                         r"\d{2}\.\d{2} \d{2}:\d{2}\)", src_line):
            failures.append(label + ": reply parent time missing: " + src_line)
        clock_line = r.get("clockLine") or ""
        for part in ("Europe/Moscow", "местное время",
                     "часы на этапах:", "L1"):
            if part not in clock_line:
                failures.append(label + ": clock line lacks " + part
                                + ": " + clock_line)
        if not re.search(r"\(\+\d{2}:\d{2}\)", clock_line):
            failures.append(label + ": clock line has no UTC offset: "
                            + clock_line)
        if "2026-11-06T12:00:00+00:00" not in clock_line:
            failures.append(label + ": clock line lost as_of_utc: " + clock_line)
        model_l1 = r.get("modelL1") or ""
        for part in ("L1: модель test-model-8b",
                     "слот: выделенный планировщик (l1_slot)",
                     "fallback: test-model-8b-fallback",
                     "запас на ответ 12 800"):
            if part not in model_l1:
                failures.append(label + ": L1 model line lacks " + part
                                + ": " + model_l1)
        model_l2 = r.get("modelL2") or ""
        for part in ("L2: api.example / test-model-8b",
                     "слот запроса: основной ответ (direct.primary)",
                     "отправлено max output tokens: 4 096"):
            if part not in model_l2:
                failures.append(label + ": L2 model line lacks " + part
                                + ": " + model_l2)
        if not any("конспект до" in line
                   for line in (r.get("blockSummaries") or [])):
            failures.append(label + ": summary date line missing "
                            + json.dumps(r.get("blockSummaries"),
                                         ensure_ascii=False))
        budget = r.get("budget") or ""
        for part in ("окно модели", "запас на ответ", "из бюджета", "режим:"):
            if part not in budget:
                failures.append(label + ": budget line lacks " + part)
        counts = r.get("counts") or ""
        if "доступно сообщений" not in counts \
                or "вошло в запрос" not in counts:
            failures.append(label + ": counts line wrong: " + counts)
        if "показаны первые" not in (r.get("truncNote") or ""):
            failures.append(label + ": truncated explanation missing")
        if not r.get("collapsedByDefault"):
            failures.append(label + ": lists not collapsed by default "
                            + json.dumps({"b": r.get("blockRows"),
                                          "l": r.get("linkRows"),
                                          "r": r.get("ruleRows")}))
        after = r.get("afterExpand") or {}
        if after.get("blocks") != 7 or after.get("links") != 4 \
                or after.get("rules") != 6:
            failures.append(label + ": expand broken " + json.dumps(after))
        if after.get("hScroll"):
            failures.append(label + ": horizontal scroll after expand")
        if not r.get("selfOutputs"):
            failures.append(label + ": own replies list missing")
        if not any("не образец стиля" in line
                   for line in (r.get("selfOutputs") or [])):
            failures.append(label + ": own replies disclaimer missing")
        if "поиск" not in (r.get("searchDecision") or ""):
            failures.append(label + ": search decision not in words")
        if not r.get("linkRows"):
            failures.append(label + ": links missing")
        if "сработало правило" not in (r.get("ruleFirst") or ""):
            failures.append(label + ": style rule line missing")
        # ── UR-20.3/20.6/20.7/20.8: карточка не печатает значения как есть.
        stop_line = r.get("stopLine") or ""
        for part in ("Ход остановлен:", "решение L1 — промолчать (l1_silent)"):
            if part not in stop_line:
                failures.append(label + ": stop line lacks " + part
                                + ": " + stop_line)
        calls_line = r.get("llmCalls") or ""
        for part in ("планирование L1 (planning): 1",
                     "продолжение ответа (continuation): 0",
                     "повтор у провайдера (provider_retry): 1"):
            if part not in calls_line:
                failures.append(label + ": llm calls line lacks " + part
                                + ": " + calls_line)
        if "{" in calls_line or "}" in calls_line or '"' in calls_line:
            failures.append(label + ": llm calls dumped as JSON: " + calls_line)
        checks_line = r.get("checksLine") or ""
        for part in ("форма ответа", "form_guard_leak_blocked",
                     "замечены клише: 2"):
            if part not in checks_line:
                failures.append(label + ": checks line lacks " + part
                                + ": " + checks_line)
        if checks_line.count("{") or '"' in checks_line:
            failures.append(label + ": checks dumped as JSON: " + checks_line)
        if "исходный текст вместо правки (форма не сохранена) (source_restored)" \
                not in (r.get("textSourceLine") or ""):
            failures.append(label + ": text source not labelled: "
                            + (r.get("textSourceLine") or ""))
        tool_line = r.get("toolFirst") or ""
        for part in ("поиск в интернете (execute_web_search)",
                     "источник не ответил вовремя (search_timeout)"):
            if part not in tool_line:
                failures.append(label + ": tool line lacks " + part
                                + ": " + tool_line)
        # Причина недоставки — словами, код в скобках; неизвестная — «код: …».
        delivery_line = r.get("deliveryLine") or ""
        if "доставлен как написан" not in delivery_line:
            failures.append(label + ": successful delivery line missing: "
                            + delivery_line)
        failed_line = r.get("deliveryLineFailed") or ""
        for part in ("без доставки текста:",
                     "разметка для Telegram не прошла",
                     "(html_fallback)"):
            if part not in failed_line:
                failures.append(label + ": delivery line lacks " + part
                                + ": " + failed_line)
        unknown_line = r.get("deliveryLineUnknown") or ""
        if "код: mystery_delivery" not in unknown_line:
            failures.append(label + ": unknown delivery reason not labelled: "
                            + unknown_line)
        if r.get("unexplained"):
            failures.append(label + ": raw code without label "
                            + json.dumps(r.get("unexplained"),
                                         ensure_ascii=False))
        if not r.get("hasUnknownFallback"):
            failures.append(label + ": unknown code fallback missing")
        if r.get("clipped") or r.get("truncateClass"):
            failures.append(label + ": ids/dates clipped "
                            + json.dumps(r.get("clipped")[:3],
                                         ensure_ascii=False))
        if r.get("hScroll"):
            failures.append(label + ": horizontal scroll")
        rects = r.get("cardRects") or []
        if len(rects) == 4:
            if label.endswith("mobile-390"):
                lefts = {row.get("left") for row in rects}
                if len(lefts) != 1:
                    failures.append(label + ": cards not single column "
                                    + json.dumps(rects))
            else:
                if rects[0].get("left") == rects[1].get("left"):
                    failures.append(label + ": cards not two columns "
                                    + json.dumps(rects))
    for label in (() if only_inspector
                  else ("modes-desktop-1440", "modes-mobile-390")):
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
