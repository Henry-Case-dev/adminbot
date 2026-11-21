"""MOD-ACL-UX-01 M4B B3 — «Опыт/Память/Случайность»: Playwright e2e.

Проверяет РЕАЛЬНЫЕ served-байты `web/index.html` + `web/app.js` +
`web/static/app.css` (все `/api/*` — детерминированные стабы; R17: только
идентификаторы/числа/тексты фикстуры, секретов и текстов сообщений нет):

  * MAC-S7-FEED-04: на «Статусе» 5 ключевых стадий + ссылка на аналитику;
    аналитика «Опыта» несёт полные 8 стадий;
  * MAC-S7-FEED-01/02/03 + AC-18: одна живая лента в карточке «Опыт»,
    фильтр Всё/Опыт/Уроки, высота 112–160 px, нет h-скролла, деталь в
    существующем окне записи, «действует» только для applied;
  * MAC-S15-04: ручной wheel/touch ставит паузу без сброса в начало,
    reduced-motion не двигает ленты;
  * MAC-S15-05: 1000 эпизодов/0 кандидатов (доказательства) ≠ backlog worker;
  * MAC-S15-11: 503 на /api/status → «неизвестно» + последний успешный ответ;
  * MAC-S6-308/MEM-01: 5 индикаторов памяти, техсчётчики в <details>,
    ссылки к причинам/истории; «0» ≠ «недоступно»;
  * MAC-S6-REST-01: «последний успех» = реальный батч; только откат — без
    слова «успех»; нет батча — «—»; детали MCA-10a/10b не удалены;
  * MAC-S6-310: порядок сон → последний вызов → бюджеты, разные высоты;
  * MAC-S6-311: ровно один экземпляр каждого блока на экране;
  * MAC-S6-SCN-01: 1920/1440/390/360 без h-overflow; скриншот привязан к
    sha256 served-байт + scope + снимку API (JSON-хеш в отчёте).

Production-derived snapshot: если задан `MOD_ACL_M4B3_SNAPSHOT` (JSON-файл,
read-only снимок `/api/status` и `/api/memory/*` с прода), он используется
ВМЕСТО стаба и его sha256 попадает в отчёт. Без файла — синтетический стаб,
и это честно записано в `limitations`; SSH/прод не трогаются.

Запуск: .venv\\Scripts\\python.exe tools\\ui_mod_acl_m4b3_status_e2e.py
Артефакты: plans/features/mod-acl-ux-01/evidence/m4b/b3/shots/ +
           plans/features/mod-acl-ux-01/evidence/m4b/b3/e2e-report.json
"""
import copy
import hashlib
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA/config-стабы — reuse)

PORT = int(os.environ.get("MOD_ACL_M4B3_PORT", "8858"))
SHOTS = os.environ.get(
    "MOD_ACL_M4B3_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4b", "b3", "shots"))
REPORT = os.environ.get(
    "MOD_ACL_M4B3_REPORT",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4b", "b3", "e2e-report.json"))
SNAPSHOT_FILE = os.environ.get("MOD_ACL_M4B3_SNAPSHOT", "")

NOW = 1791900000
CHAT = -1001234567890
CHAT_TITLE = "Audit Chat"
PROD_VERSION = "2.58.228"

# ── Фикстуры (детерминированные; только числа/коды/короткие подписи) ──────
EXPERIENCE_ITEMS = [
    {"kind": "applied", "ts": NOW - 60, "lesson_id": "L-201", "type": "tool_usage",
     "scope": "chat", "summary": "Сначала проверять тип файла",
     "status": "applied", "outcome": "success", "measurement": {"delta": 1},
     "label": "урок применён"},
    {"kind": "applied", "ts": NOW - 900, "lesson_id": "L-202",
     "type": "social_preference", "scope": "chat",
     "summary": "Учитывать предпочтение к краткости", "status": "applied",
     "outcome": "unknown", "measurement": None, "label": "урок применён"},
    {"kind": "activated", "ts": NOW - 1800, "lesson_id": "L-203",
     "type": "tool_usage", "scope": "chat", "summary": "Правило в работе",
     "status": "active", "label": "исправлен способ действия"},
    {"kind": "suspended", "ts": NOW - 3600, "lesson_id": "L-204",
     "type": "tool_usage", "scope": "global", "summary": "Приостановлено",
     "status": "suspended", "label": "урок приостановлен"},
]
LESSONS = [
    {"lesson_id": "L-201", "version": 2, "type": "tool_usage", "scope": "chat",
     "scope_chat_id": CHAT, "recommendation": "Сначала проверять тип файла",
     "status": "active", "applied": True, "unverified": False,
     "historical": False, "grounds_count": 4, "applications_count": 2,
     "created_at": NOW - 5000, "updated_at": NOW - 100},
    {"lesson_id": "L-202", "version": 1, "type": "social_preference",
     "scope": "chat", "scope_chat_id": CHAT,
     "recommendation": "Учитывать предпочтение к краткости",
     "status": "active", "applied": True, "unverified": False,
     "historical": False, "grounds_count": 2, "applications_count": 1,
     "created_at": NOW - 6000, "updated_at": NOW - 900},
    {"lesson_id": "L-204", "version": 1, "type": "tool_usage", "scope": "global",
     "scope_chat_id": None, "recommendation": "Приостановленное правило",
     "status": "suspended", "applied": False, "unverified": False,
     "historical": False, "grounds_count": 1, "applications_count": 0,
     "created_at": NOW - 9000, "updated_at": NOW - 3600},
    {"lesson_id": "L-205", "version": 1, "type": "tool_usage", "scope": "chat",
     "scope_chat_id": CHAT, "recommendation": "Непроверенная гипотеза",
     "status": "candidate", "applied": False, "unverified": True,
     "historical": False, "grounds_count": 1, "applications_count": 0,
     "created_at": NOW - 8000, "updated_at": NOW - 4000},
    # Чужой чат: сервер не должен его отдавать при chat_id=CHAT; фикстура
    # проверяет, что UI тем более не покажет его активным (S15-07).
    {"lesson_id": "L-901", "version": 1, "type": "tool_usage", "scope": "chat",
     "scope_chat_id": -1007777777, "recommendation": "Чужое правило",
     "status": "active", "applied": True, "unverified": False,
     "historical": False, "grounds_count": 9, "applications_count": 9,
     "created_at": NOW - 1000, "updated_at": NOW - 100},
]
PIPELINE = {
    "scope": "global", "chat_id": None, "generated_at": NOW, "enabled": True,
    "state": "idle", "state_label": "Простаивает: достойных уроков пока нет",
    "reason": "no_worthy_lessons",
    "reason_label": "Нет активных уроков — применять нечего (это не ошибка)",
    "cadence": {"name": "daily", "seconds": 86400},
    "job": {"status": "completed"}, "counters": {}, "definitions": {},
    "reason_details": [],
    "order": ["observation", "candidate", "validation", "activation",
              "retrieval", "application", "outcome", "utility"],
    "stages": {},
}
_STAGE_LABELS = {
    "observation": "Наблюдение (эпизоды опыта и feedback)",
    "candidate": "Кандидат в урок",
    "validation": "Проверка урока",
    "activation": "Активация урока",
    "retrieval": "Отбор урока в контекст",
    "application": "Применение урока",
    "outcome": "Измеренный исход",
    "utility": "Полезность (счётчики)",
}
for _idx, _key in enumerate(PIPELINE["order"]):
    PIPELINE["stages"][_key] = {
        "key": _key, "label": _STAGE_LABELS[_key],
        "enabled": True, "state": "working" if _idx < 3 else "idle",
        "state_label": "Работает: есть свежие результаты цепочки"
        if _idx < 3 else "Простаивает: запускается, но уроков пока нет",
        "reason": "", "reason_label": "",
        "last_run_at": NOW - 600 - _idx, "last_success_at": NOW - 600 - _idx,
        "total": 10 - _idx,
        "windows": {"24h": 3, "7d": 7, "30d": 10 - _idx},
        "skip_reasons": [], "excluded_reasons": [],
    }

STATUS = copy.deepcopy(M.STATUS_STUB)
STATUS["bot"] = {"uptime_seconds": 3600, "state": "running",
                 "errors_total": 0, "version": PROD_VERSION}
STATUS["uptime"] = {"buckets": [], "last_heartbeat": NOW - 30,
                    "until": "2026-11-20T12:00:00+00:00",
                    "generated_at": "2026-11-20T12:00:00+00:00"}
STATUS["intents"] = {"enabled": True, "state": "not_run", "active": 0,
                     "top": [], "last_action": None}
STATUS["experience"] = {
    "enabled": True, "state": "implemented",
    "items": copy.deepcopy(EXPERIENCE_ITEMS),
    "counters": {"lessons": 4, "active": 2, "suspended": 1,
                 "applications": 2, "success": 1, "failure": 0, "unknown": 1},
    "improvement": {"measured": False,
                    "note": "измеренного улучшения нет — нужен исход"},
}
STATUS["random"] = {
    "ready": True, "enabled": True, "available": True,
    "selected_source": "anu", "effective_source": "anu",
    "quantum_active": True, "key_present": True, "anu_state": "active",
    "reserve_remaining": 512, "buffer_max": 1024, "low_watermark": 128,
    "last_batch": {"created_at": NOW - 120, "length": 8, "provider_id": "anu",
                   "config_matches": True},
    "last_fallback_reason": None, "last_fallback_at": None,
    "primary_provider": "anu", "primary_setting_raw": "anu",
    "primary_setting_state": "configured", "resolved_primary": "anu",
    "effective_provider": "anu", "entropy_class": "quantum",
    "prng_active": False, "prng_setting": False, "fallback_enabled": True,
    "fallback_order": ["ibm_quantum", "lfdr"], "fallback_order_state": "ok",
    "effective_order": ["ibm_quantum", "lfdr"],
    "providers": [], "provider_reserve": {}, "provider_quarantined": {},
    "reserve_quarantined": 0, "recent_draws": [], "recent_draws_scope": "",
    "uses": {"enabled": True, "events": [], "cursor": None, "scope": ""},
    "plan": "free", "policy_version": "v1",
}
HEALTH = {
    "beliefs_active": 4, "beliefs_archived": 2, "resurrections_total": 0,
    "decay_runs_total": 3, "last_decay_at": NOW - 4000,
    "facts_overdue": 1, "facts_unconfirmed": 5, "smart_messages_total": 420,
    "storage": {"db_size_bytes": 1048576, "db_size_mb": 1.0,
                "disk_free_bytes": 1073741824},
}
EXPIRED = {
    "available": True, "now_ts": NOW, "expired_total": 7,
    "expired_searchable": 5, "needs_recheck": 3, "superseded_total": 1,
    "infinite_retention": True,
    # D6 (M4B B3): аддитивные метрики активных фактов.
    "facts_confirmed": 42, "facts_last_created_at": NOW - 300,
    "facts_last_24h": 6, "facts_last_7d": 19,
}
COGNITION = {
    "dream": {"running": False, "enabled": True, "effective": True,
              "active": False, "active_until": None, "manual": False,
              "last_run_at": NOW - 7200, "next_wake_at": NOW + 3600,
              "state": "sleep",
              "budget": {"distilled_today": 1, "distilled_limit": 5,
                         "tokens_today": 100, "tokens_limit": 2000}},
    "deep_sleep": {"running": False, "enabled": True, "active": False,
                   "active_until": None, "manual": False,
                   "last_run_at": NOW - 3600, "next_run_at": NOW + 7200,
                   "paradigms_status": "ok"},
    "generated_at": NOW,
}
DEEP_SLEEP = {"paradigms_status": "ok", "gate": True, "effective": True}
# Один и тот же прогон отдаёт либо «недостаточно доказательств» (evidence),
# либо «техническое молчание worker» (pending>0 + failed) — по mode.
FUNNELS_EVIDENCE = {
    "available": True, "now_ts": NOW, "chat_scoped_events": True,
    "initiative": {"available": True, "job": {"status": "completed"},
                   "events": {"24h": {}, "7d": {}}},
    "experience": {
        "available": True,
        "job": {"status": "completed", "updated_at": NOW - 1000,
                "counters": {"semantic_scanned": 1000,
                             "semantic_extracted": 0,
                             "semantic_candidates": 0,
                             "semantic_rejected": 40,
                             "semantic_duplicates": 12,
                             "semantic_llm_unavailable": 3}},
        "semantic_lag": {"watermark": 9000, "max_message_id": 9000,
                         "pending": 0, "lag_rows": 0},
        "events": {"24h": {}, "7d": {}},
    },
}
FUNNELS_WORKER = copy.deepcopy(FUNNELS_EVIDENCE)
FUNNELS_WORKER["experience"]["job"] = {
    "status": "failed", "reason_code": "llm_timeout", "updated_at": NOW - 600,
    "counters": {"semantic_scanned": 1000, "semantic_extracted": 0,
                 "semantic_candidates": 0, "semantic_rejected": 0,
                 "semantic_duplicates": 0},
}
FUNNELS_WORKER["experience"]["semantic_lag"] = {
    "watermark": 9000, "max_message_id": 9250, "pending": 250, "lag_rows": 250,
}
LOGS = {"logs": [], "levels": [], "count": 0, "counts": {}}

# B3-R1-01: задержка ТОЛЬКО ленты уроков — наблюдаемое состояние «загружаются».
DELAY_LESSONS_FETCH = """
(() => {
  const orig = window.fetch;
  window.fetch = function (input, init) {
    const url = String(input && input.url ? input.url : input);
    if (url.indexOf('/api/memory/lessons') >= 0) {
      return new Promise((resolve, reject) => {
        setTimeout(() => {
          orig.call(window, input, init).then(resolve, reject);
        }, 2500);
      });
    }
    return orig.call(window, input, init);
  };
})();
"""

ALLOWED_CHAT = str(CHAT)
# Счётчик для сценария «сначала успешный /api/status, затем 503» (S15-11).
_FAIL_STATE = {"status_calls": 0}
# B3-R1-01: управляемый отказ ленты уроков после успешного ответа.
_LESSON_STATE = {"fail": False}

# Реестр модулей для `/api/config.modules` (реальный прод отдаёт DTO
# `registry_for_frontend`): без него `#/modules/<slug>` остаётся отложенным
# адресом, и аналитика «Опыта» не открывается. Только идентификаторы/подписи.
MODULES_DTO = [
    {"id": slug, "title": title,
     "permissions": {"can_read": True, "can_edit": True},
     "catalog_order": order, "catalog_group": group,
     "visibility": "visible", "kind": "product_module"}
    for order, (slug, title, group) in enumerate([
        ("experience", "Опыт", "memory"),
        ("sleep", "Сон", "memory"),
        ("nostalgia", "Ностальгия", "memory"),
        ("summary", "Сводки", "memory"),
        ("random", "Случайность", "memory"),
        ("factcheck", "Фактчек", "intelligence"),
        ("search", "Поиск", "intelligence"),
        ("checkup", "Обследование", "intelligence"),
        ("direct", "Прямые ответы", "intelligence"),
        ("video_summary", "Выжимка видео", "intelligence"),
        ("transcribe", "Транскрипция", "intelligence"),
        ("web", "Веб", "intelligence"),
        ("initiative", "Инициатива", "intelligence"),
        ("vision", "Зрение", "media"),
        ("images", "Изображения", "media"),
        ("media_download", "Скачивание медиа", "media"),
        ("budgets", "Бюджеты", "platform"),
        ("time", "Время", "platform"),
    ], start=1)
]


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _api_handler(route, mode="data"):
    """mode: data | empty | fail | worker | fallback | none."""
    req = route.request
    parsed = urlparse(req.url)
    path = parsed.path
    method = req.method
    hdrs = {str(k).lower(): v for k, v in req.headers.items()}

    if path.endswith("/api/status") and mode == "fail":
        route.fulfill(status=503, content_type="application/json",
                      body=json.dumps({"detail": "temporarily unavailable"}))
        return

    def fail():
        route.fulfill(status=503, content_type="application/json",
                      body=json.dumps({"detail": "temporarily unavailable"}))

    if path.endswith("/api/status") and mode == "fail_after_first":
        _FAIL_STATE["status_calls"] += 1
        if _FAIL_STATE["status_calls"] > 1:
            fail()
            return

    if path.endswith("/api/access/chats"):
        body = [{"chat_id": CHAT, "title": CHAT_TITLE, "is_dm": False,
                 "photo_file_id": None, "access": "admin"}]
    elif path.endswith("/api/oversight/summary"):
        body = {"chats": [{"chat_id": CHAT, "title": CHAT_TITLE}], "totals": {}}
    elif path.endswith("/api/oversight/dossier_feed"):
        body = {"items": []}
    elif path.endswith("/api/memory/cognition/status"):
        body = COGNITION
    elif path.endswith("/api/memory/deep-sleep"):
        body = DEEP_SLEEP
    elif path.endswith("/api/memory/health"):
        body = HEALTH
    elif path.endswith("/api/memory/expired-overview"):
        body = copy.deepcopy(EXPIRED)
        if mode == "empty":
            body.update({"facts_confirmed": None, "facts_last_created_at": None,
                         "facts_last_24h": None, "facts_last_7d": None})
    elif path.endswith("/api/memory/intel-funnels"):
        body = copy.deepcopy(
            FUNNELS_WORKER if mode == "worker" else FUNNELS_EVIDENCE)
    elif path.endswith("/api/memory/lessons"):
        raw = copy.deepcopy(LESSONS)
        cid = (parse_qs(parsed.query).get("chat_id") or [None])[0]
        rows = []
        for lesson in raw:
            if lesson["scope"] == "global":
                rows.append(lesson)
            elif cid is not None and str(lesson["scope_chat_id"]) == str(cid):
                rows.append(lesson)
        if mode == "lesson503":
            fail()
            return
        if mode == "lessonline" and _LESSON_STATE["fail"]:
            fail()
            return
        if mode == "lessonempty" or mode in ("empty", "worker"):
            body = {"enabled": True, "state": "not_run", "count": 0,
                    "lessons": []}
        else:
            body = {"enabled": True, "state": "implemented" if rows
                    else "not_run", "count": len(rows), "lessons": rows}
    elif path.endswith("/api/experience/pipeline"):
        body = copy.deepcopy(PIPELINE)
        if mode == "empty":
            body["state"] = "not_run"
            body["state_label"] = "Ещё не запускалось"
    elif path.endswith("/api/status/logs"):
        body = LOGS
    elif path.endswith("/api/status"):
        body = copy.deepcopy(STATUS)
        if mode in ("empty", "worker"):
            body["experience"]["items"] = []
            body["experience"]["counters"] = {
                "lessons": 0, "active": 0, "suspended": 0,
                "applications": 0, "success": 0, "failure": 0, "unknown": 0}
            body["experience"]["state"] = "not_run"
        if mode == "fallback":
            body["random"]["quantum_active"] = False
            body["random"]["last_batch"] = None
            body["random"]["last_fallback_reason"] = "provider_unavailable"
            body["random"]["last_fallback_at"] = NOW - 240
            body["random"]["effective_source"] = "prng"
            body["random"]["effective_provider"] = None
            body["random"]["prng_active"] = True
        if mode == "none":
            body["random"]["last_batch"] = None
            body["random"]["last_fallback_at"] = None
    elif path.endswith("/api/config"):
        base = (M.CONFIG_STUB_CHAT
                if hdrs.get("x-chat-id") == ALLOWED_CHAT else M.CONFIG_STUB)
        body = copy.deepcopy(base)
        body["modules"] = copy.deepcopy(MODULES_DTO)
    elif path.endswith("/api/persona"):
        body = {"dynamic_traits": [], "traits_status": "ok"}
    elif path.endswith("/api/memory/dream/beliefs"):
        body = []
    elif path.endswith("/api/analytics/usage/latest"):
        body = {"correlation_id": "m4b3", "ts": "2026-11-20T12:00:00+00:00",
                "steps": [], "total": {"input_tokens": 100, "output_tokens": 20,
                                       "cost_usd": 0.001, "calls": 1}}
    else:
        body = M._stub_for(req.url)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body, ensure_ascii=False))


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _probe(page):
    return page.evaluate(
        """() => {
          const q = (sel) => document.querySelector(sel);
          const qa = (sel) => Array.from(document.querySelectorAll(sel));
          const feed = q('[data-experience-sfeed]');
          const rows = qa('[data-experience-feed-row]');
          const inds = qa('[data-memory-indicator]');
          const expBlock = q('[data-expired-block]');
          const expRows = qa('[data-expired-block] .mem-kv__row');
          const tech = q('details[data-memory-tech]');
          const sleep = q('[data-status-sleep]');
          const exec = q('[data-exec-preview]');
          const budgets = qa('.status-grid .card')
            .find((c) => c.textContent.indexOf('Бюджеты интеллекта') >= 0);
          const rect = (el) => el ? el.getBoundingClientRect() : null;
          const rSleep = rect(sleep), rExec = rect(exec);
          const stageKeys = qa('[data-experience-pipeline-stages] '
            + '[data-experience-stage]')
            .map((el) => el.getAttribute('data-experience-stage'));
          const nestedScrollers = (el) => {
            let n = 0;
            let p = el ? el.parentElement : null;
            while (p && p !== document.body) {
              const s = getComputedStyle(p);
              if (/(auto|scroll)/.test(s.overflowY)
                  && p.scrollHeight > p.clientHeight + 1) n += 1;
              p = p.parentElement;
            }
            return n;
          };
          const chainKeys = qa('[data-experience-chain-stages] '
            + '[data-experience-chain-stage]')
            .map((el) => el.getAttribute('data-experience-chain-stage'));
          const link = q('[data-experience-pipeline-expand]');
          const last = q('[data-random-last-success]');
          return {
            pageNoH: document.documentElement.scrollWidth
              <= window.innerWidth + 1,
            feedBox: feed ? {h: Math.round(feed.getBoundingClientRect().height),
              noH: feed.scrollWidth <= feed.clientWidth + 1} : null,
            feedRows: rows.length,
            tracks: rows.map((el) => el.getAttribute('data-experience-feed-row')),
            feedText: feed ? feed.innerText : '',
            expTexts: rows.filter((el) => el.getAttribute(
              'data-experience-feed-row') === 'experience')
              .map((el) => el.innerText.replace(/\\n/g, ' · ')),
            lessonTexts: rows.filter((el) => el.getAttribute(
              'data-experience-feed-row') === 'lesson')
              .map((el) => el.innerText.replace(/\\n/g, ' · ')),
            empty: q('[data-experience-feed-empty]')
              ? q('[data-experience-feed-empty]').innerText : '',
            emptyKind: q('[data-experience-feed-empty]')
              ? q('[data-experience-feed-empty]')
                .getAttribute('data-experience-feed-empty-kind') : null,
            unknown: q('[data-experience-unknown]')
              ? q('[data-experience-unknown]').innerText : '',
            indCount: inds.length,
            indKeys: inds.map((el) => el.getAttribute('data-memory-indicator')),
            indText: inds.map((el) => el.innerText.replace(/\\n/g, ' · ')),
            techOpen: tech ? tech.hasAttribute('open') : null,
            techHasRows: tech ? tech.querySelectorAll('.mem-kv__row').length : 0,
            expRows: expRows.length,
            expLedgerFolded: expRows.length > 0 && expRows.every((el) => {
              const d = el.closest('details');
              return !!d && !d.getAttribute('open');
            }),
            memLinks: qa('[data-memory-link]').map((a) => a.getAttribute('href')),
            lastSuccess: last ? {text: last.innerText, kind:
              last.getAttribute('data-random-last-success-kind')} : null,
            feedNestedScrollers: feed ? nestedScrollers(feed) : null,
            memNestedScrollers: q('[data-memory-indicators]')
              ? nestedScrollers(q('[data-memory-indicators]')) : null,
            randomDetailsLink: q('[data-random-details-link]')
              ? q('[data-random-details-link]').getAttribute('href') : null,
            hasRandomDetails: !!q('[data-random-details]'),
            hasRandomUses: !!q('[data-random-uses]'),
            order: {sleep: rSleep ? Math.round(rSleep.top) : null,
                    exec: rExec ? Math.round(rExec.top) : null,
                    budgets: budgets ? Math.round(
                      budgets.getBoundingClientRect().top) : null},
            heights: {sleep: rSleep ? Math.round(rSleep.height) : null,
                      exec: rExec ? Math.round(rExec.height) : null},
            stageKeys: stageKeys,
            chainKeys: chainKeys,
            expandHref: link ? link.getAttribute('href') : null,
            stageCount: qa('[data-experience-stage]').length,
            statusError: q('[data-status-error]')
              ? q('[data-status-error]').innerText : '',
            lastOk: q('[data-status-last-ok]')
              ? q('[data-status-last-ok]').innerText : '',
            bodyText: document.body.innerText.slice(0, 20000),
            counters: {
              experience: qa('[data-experience]').length,
              random: qa('[data-random-source]').length,
              expired: qa('[data-expired-block]').length,
              logs: qa('#status-logs').length,
              feed: qa('[data-experience-feed]').length,
              chain: qa('[data-experience-chain="full"]').length,
            },
          };
        }""")


def _feed_modal_text(page):
    return page.evaluate(
        """() => {
          const m = document.querySelector('[data-sfeed-modal]');
          return m ? m.innerText : '';
        }""")


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    served = {
        "app.js": _sha256_file(os.path.join(REPO, "web", "app.js")),
        "index.html": _sha256_file(os.path.join(REPO, "web", "index.html")),
        "app.css": _sha256_file(os.path.join(REPO, "web", "static",
                                             "app.css")),
    }
    snapshot_source = "synthetic_stub"
    snapshot_hash = hashlib.sha256(
        json.dumps({"status": STATUS, "expired": EXPIRED, "health": HEALTH,
                    "lessons": LESSONS, "pipeline": PIPELINE},
                   ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if SNAPSHOT_FILE and os.path.isfile(SNAPSHOT_FILE):
        # Read-only production-derived snapshot (файл создаётся ВНЕ этого
        # прогона; скрипт его не запрашивает и SSH не трогает).
        snapshot_source = "production_derived_file"
        snapshot_hash = _sha256_file(SNAPSHOT_FILE)

    result = {
        "candidate_served_bytes": served,
        "snapshot_source": snapshot_source,
        "snapshot_sha256": snapshot_hash,
        "api_snapshot": {
            "status_version": PROD_VERSION,
            "status_checked_at": STATUS["uptime"]["generated_at"],
            "experience_state": STATUS["experience"]["state"],
            "experience_items": len(EXPERIENCE_ITEMS),
            "lessons_count": len(LESSONS),
            "facts_confirmed": EXPIRED["facts_confirmed"],
            "funnel_kind": "evidence(1000/0,rej40,dup12)",
            "random_last_batch_at": STATUS["random"]["last_batch"]["created_at"],
            "scope": "global → chat",
        },
        "checks": {}, "viewports": {}, "console": [], "screenshots": [],
    }
    failures = []

    def check(name, value):
        result["checks"][name] = bool(value)
        if not value:
            failures.append(name)

    httpd = _start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    api_calls = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def new_page(width, height, mode="data", reduced=False,
                         delay_lessons=False):
                ctx = browser.new_context(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce" if reduced else "no-preference")
                ctx.add_init_script(M.TMA_STUB)
                if delay_lessons:
                    ctx.add_init_script(DELAY_LESSONS_FETCH)
                ctx.route("**/api/**",
                          lambda route: _api_handler(route, mode))
                page = ctx.new_page()
                errors = []

                def on_console(m):
                    if m.type != "error":
                        return
                    text = m.text[:200]
                    if mode in ("fail", "lesson503", "lessonline") and (
                            "Failed to load resource" in text
                            or "503" in text):
                        return
                    errors.append(text)

                page.on("console", on_console)
                page.on("pageerror", lambda e: errors.append(
                    "pageerror: " + str(e)[:200]))
                page.goto(base + "#/", wait_until="load")
                page.wait_for_selector('[data-experience]', timeout=15000)
                page.wait_for_timeout(900)
                return ctx, page, errors

            # ── 1. Четыре viewport: лента/индикаторы/стадии/порядок ──────
            PLAN = [(1920, 1080, "desktop_1920"), (1440, 900, "desktop_1440"),
                    (390, 844, "mobile_390"), (360, 640, "mobile_360")]
            for width, height, name in PLAN:
                ctx, page, errors = new_page(width, height)
                pr = _probe(page)
                result["viewports"][name] = pr
                check(name + "_no_h_overflow", pr["pageNoH"])
                check(name + "_no_nested_scrolls",
                      pr["feedNestedScrollers"] is not None
                      and pr["feedNestedScrollers"] <= 1
                      and pr["memNestedScrollers"] is not None
                      and pr["memNestedScrollers"] <= 1)
                check(name + "_feed_window", pr["feedBox"] is not None
                      and 112 <= pr["feedBox"]["h"] <= 160
                      and pr["feedBox"]["noH"])
                check(name + "_feed_rows_both_tracks",
                      pr["feedRows"] >= 3
                      and "experience" in pr["tracks"]
                      and "lesson" in pr["tracks"])
                check(name + "_experience_rows_are_applied",
                      bool(pr["expTexts"]) and all(
                        "· тип:" in t and "· исход:" in t
                        for t in pr["expTexts"]))
                check(name + "_lesson_rows_have_grounds",
                      bool(pr["lessonTexts"]) and all(
                        "оснований:" in t for t in pr["lessonTexts"]))
                check(name + "_lesson_hidden_foreign",
                      "Чужое правило" not in pr["feedText"])
                check(name + "_five_indicators", pr["indCount"] == 5
                      and pr["indKeys"] == ["facts", "needs_recheck",
                                            "expired", "beliefs", "updated"])
                check(name + "_facts_numbers", "42" in pr["indText"][0]
                      and "24ч: 6" in pr["indText"][0]
                      and "7д: 19" in pr["indText"][0])
                check(name + "_tech_in_details",
                      pr["techOpen"] is False and pr["techHasRows"] >= 3)
                check(name + "_no_right_number_ledger", pr["expLedgerFolded"])
                check(name + "_memory_links",
                      pr["memLinks"] == ["#/memory/rag", "#/oversight?tab=runs"])
                check(name + "_random_last_success",
                      pr["lastSuccess"] is not None
                      and "последний квантовый батч" in pr["lastSuccess"]["text"]
                      and pr["lastSuccess"]["kind"] == "batch")
                check(name + "_random_details_kept",
                      pr["hasRandomDetails"]
                      and pr["randomDetailsLink"] == "#/modules/random")
                check(name + "_five_key_stages",
                      pr["stageKeys"] == ["observation", "candidate",
                                          "validation", "application",
                                          "outcome"],
                      )
                check(name + "_expand_link",
                      pr["expandHref"] == "#/modules/experience")
                check(name + "_order_sleep_exec_budgets",
                      pr["order"]["sleep"] is not None
                      and pr["order"]["exec"] > pr["order"]["sleep"]
                      and pr["order"]["budgets"] > pr["order"]["exec"])
                check(name + "_dynamic_heights",
                      pr["heights"]["exec"] is not None
                      and pr["heights"]["sleep"] is not None
                      and abs(pr["heights"]["exec"] - pr["heights"]["sleep"]) > 8)
                check(name + "_single_blocks",
                      pr["counters"]["experience"] == 1
                      and pr["counters"]["random"] == 1
                      and pr["counters"]["expired"] == 1
                      and pr["counters"]["logs"] == 1
                      and pr["counters"]["feed"] == 1
                      and pr["counters"]["chain"] == 0)
                shot = os.path.join(SHOTS, "b3-status-%s.png" % name)
                page.screenshot(path=shot, full_page=True)
                result["screenshots"].append(
                    os.path.relpath(shot, REPO).replace(os.sep, "/"))
                if errors:
                    result["console"].append({"viewport": name,
                                              "errors": errors[:8]})
                    failures.append(name + "_console_clean")
                ctx.close()

            # ── 2. Фильтр дорожек + деталь в существующем окне ───────────
            ctx, page, errors = new_page(1440, 900)
            page.click('[data-experience-track="lesson"]')
            page.wait_for_timeout(300)
            only = page.evaluate(
                """() => Array.from(
                    document.querySelectorAll('[data-experience-feed-row]'))
                    .map((el) => el.getAttribute('data-experience-feed-row'))""")
            check("track_lesson_only", bool(only)
                  and all(t == "lesson" for t in only))
            check("track_lesson_applied_only",
                  page.evaluate(
                      """() => {
                        const rows = Array.from(document.querySelectorAll(
                          '[data-experience-feed-row="lesson"]'));
                        return rows.some((r) => r.innerText.indexOf('действует') >= 0)
                          && rows.some((r) => r.innerText.indexOf('не проверен') >= 0)
                          && !rows.some((r) => r.innerText.indexOf('Чужое правило') >= 0);
                      }"""))
            page.click('[data-experience-track="experience"]')
            page.wait_for_timeout(250)
            only2 = page.evaluate(
                """() => Array.from(
                    document.querySelectorAll('[data-experience-feed-row]'))
                    .map((el) => el.getAttribute('data-experience-feed-row'))""")
            check("track_experience_only", bool(only2)
                  and all(t == "experience" for t in only2))
            page.click('[data-experience-track="all"]')
            page.wait_for_timeout(200)
            page.click('[data-experience-sfeed] [data-sfeed-row]')
            page.wait_for_selector('[data-sfeed-modal]', timeout=4000)
            modal = _feed_modal_text(page)
            result["feed_modal"] = modal[:600]
            check("detail_full_text", "Сначала проверять тип файла" in modal)
            check("detail_provenance", "Первоисточники" in modal)
            check("detail_status_field", "Статус" in modal
                  or "Статус применения" in modal)
            page.click('[data-sfeed-modal] .modal-close')
            page.wait_for_timeout(250)
            check("detail_closed", not page.is_visible('[data-sfeed-modal]'))
            check("track_console_clean", not errors)
            page.locator('[data-experience-feed]').screenshot(
                path=os.path.join(SHOTS, "b3-feed-tracks-1440.png"))
            ctx.close()

            # ── 3. Пауза ручного скролла / resume / touch ────────────────
            ctx, page, errors = new_page(1440, 900)
            sel = '[data-experience-sfeed]'
            page.wait_for_function(
                "() => { const v = document.querySelector('%s');"
                " return v && v.scrollHeight > v.clientHeight + 10; }" % sel,
                timeout=8000)
            start = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            page.wait_for_timeout(1500)
            moved = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            check("feed_autoplay_runs", moved > start)
            page.evaluate(
                "(() => { const v = document.querySelector('%s');"
                " v.dispatchEvent(new WheelEvent('wheel', {deltaY: 30,"
                " bubbles: true})); })()" % sel)
            page.wait_for_timeout(250)
            paused = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            page.wait_for_timeout(1000)
            still = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            check("feed_wheel_pauses", abs(still - paused) <= 1)
            page.evaluate(
                "(() => { const v = document.querySelector('%s');"
                " v.dispatchEvent(new TouchEvent('touchstart', {bubbles: true}));"
                " v.dispatchEvent(new TouchEvent('touchmove', {bubbles: true}));"
                " })()" % sel)
            page.wait_for_timeout(300)
            touched = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            page.wait_for_timeout(700)
            after_touch = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            check("feed_touch_pauses", abs(after_touch - touched) <= 1)
            check("feed_no_jump_to_start",
                  page.evaluate("document.querySelector('%s').scrollTop" % sel)
                  > 0)
            page.wait_for_timeout(3400)
            resumed = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            check("feed_resumes", resumed >= after_touch - 1)
            check("feed_motion_console_clean", not errors)
            ctx.close()

            # ── 4. Reduced motion: ленты не двигаются, данные на месте ───
            ctx, page, errors = new_page(1440, 900, reduced=True)
            page.wait_for_selector('[data-experience-sfeed] [data-sfeed-row]')
            before = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            page.wait_for_timeout(1500)
            after = page.evaluate("document.querySelector('%s').scrollTop" % sel)
            check("reduced_motion_no_motion", abs(after - before) <= 0)
            check("reduced_motion_rows_present",
                  page.evaluate(
                      "document.querySelectorAll("
                      "'[data-experience-feed-row]').length") >= 3)
            check("reduced_motion_console_clean", not errors)
            ctx.close()

            # ── 4b. B3-R1-01: дорожка «Уроки» — честные состояния ───────
            # (a) 503 с первого запроса: «неизвестно», не «нет уроков».
            ctx, page, errors = new_page(1440, 900, mode="lesson503")
            page.click('[data-experience-track="lesson"]')
            page.wait_for_timeout(700)
            pr = _probe(page)
            result["lesson_503"] = {"kind": pr["emptyKind"],
                                    "text": pr["empty"][:300]}
            check("lesson_503_kind", pr["emptyKind"] == "unavailable")
            check("lesson_503_unknown_title",
                  "Состояние уроков неизвестно" in pr["empty"])
            check("lesson_503_no_false_empty",
                  "Уроков пока нет" not in pr["empty"])
            check("lesson_503_never_ok",
                  "успешных ответов ленты уроков ещё не было" in pr["empty"])
            check("lesson_503_console_clean", not errors)
            shot = os.path.join(SHOTS, "b3-lessons-503.png")
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(
                os.path.relpath(shot, REPO).replace(os.sep, "/"))
            ctx.close()

            # (b) загрузка (busy): «Уроки загружаются…», не «нет уроков».
            ctx, page, errors = new_page(1440, 900, delay_lessons=True)
            page.click('[data-experience-track="lesson"]')
            page.wait_for_timeout(350)
            pr = _probe(page)
            result["lesson_loading"] = {"kind": pr["emptyKind"],
                                        "text": pr["empty"][:300]}
            check("lesson_loading_kind", pr["emptyKind"] == "loading")
            check("lesson_loading_title",
                  "Уроки загружаются" in pr["empty"])
            check("lesson_loading_no_false_empty",
                  "Уроков пока нет" not in pr["empty"])
            check("lesson_loading_last_ok_absent",
                  "успешных ответов ленты уроков ещё не было" in pr["empty"])
            page.wait_for_timeout(3200)          # запрос уроков завершился
            check("lesson_loading_resolves",
                  page.evaluate(
                      "document.querySelectorAll("
                      "'[data-experience-feed-row=\"lesson\"]').length") >= 1)
            shot = os.path.join(SHOTS, "b3-lessons-loading.png")
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(
                os.path.relpath(shot, REPO).replace(os.sep, "/"))
            ctx.close()

            # (c) успешный ПУСТОЙ ответ: только здесь «Уроков пока нет».
            ctx, page, errors = new_page(1440, 900, mode="lessonempty")
            page.click('[data-experience-track="lesson"]')
            page.wait_for_timeout(600)
            pr = _probe(page)
            result["lesson_empty"] = {"kind": pr["emptyKind"],
                                      "text": pr["empty"][:300]}
            check("lesson_empty_kind", pr["emptyKind"] == "empty")
            check("lesson_empty_title", "Уроков пока нет" in pr["empty"])
            check("lesson_empty_reason",
                  "активных или проверенных уроков нет" in pr["empty"])
            check("lesson_empty_no_error_word",
                  "недоступны" not in pr["empty"])
            page.screenshot(path=os.path.join(SHOTS,
                                             "b3-lessons-empty-ok.png"),
                            full_page=True)
            result["screenshots"].append(
                "plans/features/mod-acl-ux-01/evidence/m4b/b3/shots/"
                "b3-lessons-empty-ok.png")
            ctx.close()

            # (d) 503 ПОСЛЕ успеха в ТЕКУЩЕМ scope: unknown + время успеха.
            _LESSON_STATE["fail"] = False
            ctx, page, errors = new_page(1440, 900, mode="lessonline")
            page.wait_for_timeout(1500)          # initial loads + chat scope
            seed_rows = page.evaluate(
                "document.querySelectorAll("
                "'[data-experience-feed-row=\"lesson\"]').length")
            check("lesson_after_ok_seed_rows", seed_rows >= 1)
            _LESSON_STATE["fail"] = True
            page.click('[data-experience-track="lesson"]')
            page.click('[data-experience-feed-refresh]')
            page.wait_for_timeout(1200)
            pr = _probe(page)
            _LESSON_STATE["fail"] = False
            result["lesson_after_ok"] = {"kind": pr["emptyKind"],
                                         "text": pr["empty"][:300]}
            check("lesson_after_ok_kind", pr["emptyKind"] == "unavailable")
            check("lesson_after_ok_last_ok",
                  "последний успешный ответ ленты уроков:" in pr["empty"])
            check("lesson_after_ok_no_false_empty",
                  "Уроков пока нет" not in pr["empty"])
            check("lesson_after_ok_console_clean", not errors)
            shot = os.path.join(SHOTS, "b3-lessons-503-after-ok.png")
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(
                os.path.relpath(shot, REPO).replace(os.sep, "/"))
            ctx.close()

            # ── 5. 503 /api/status: unknown + последний успешный ответ ──
            _FAIL_STATE["status_calls"] = 0
            ctx, page, errors = new_page(1440, 900, mode="fail_after_first")
            page.wait_for_selector('[data-experience-sfeed]', timeout=8000)
            page.click('[data-key-strip] button')
            page.wait_for_selector('[data-status-error]', timeout=6000)
            pr = _probe(page)
            result["fail_state"] = {"error": pr["statusError"][:300],
                                    "last_ok": pr["lastOk"][:300]}
            check("fail_unknown_state", "503" in pr["statusError"])
            check("fail_last_success_time",
                  "последний успешный ответ экрана" in pr["lastOk"])
            check("fail_not_zero_experience",
                  "Записей опыта пока нет" not in pr["bodyText"])
            page.screenshot(path=os.path.join(SHOTS, "b3-status-503.png"),
                            full_page=True)
            ctx.close()

            # ── 6. 1000/0: доказательства ≠ молчание worker ─────────────
            ctx, page, errors = new_page(1440, 900, mode="empty")
            pr = _probe(page)
            result["empty_state"] = {"empty": pr["empty"][:300]}
            check("empty_evidence_reason",
                  "недостаточно доказательств" in pr["empty"]
                  and "отклонено: 40" in pr["empty"])
            check("empty_has_no_rows", pr["feedRows"] == 0)
            check("empty_unknown_not_zero", "—" in pr["indText"][0],
                  )
            page.screenshot(path=os.path.join(SHOTS, "b3-feed-evidence-empty.png"),
                            full_page=True)
            ctx.close()

            ctx, page, errors = new_page(1440, 900, mode="worker")
            pr = _probe(page)
            result["worker_state"] = {"empty": pr["empty"][:300]}
            check("worker_backlog_reason",
                  "semantic backlog 250" in pr["empty"]
                  and "worker" in pr["empty"]
                  and "llm_timeout" in pr["empty"])
            check("worker_not_evidence_reason",
                  "недостаточно доказательств" not in pr["empty"])
            page.screenshot(path=os.path.join(SHOTS, "b3-feed-worker-backlog.png"),
                            full_page=True)
            ctx.close()

            # ── 6b. Детали случайности НЕ удалены (MCA-10a/10b) ─────────
            ctx, page, errors = new_page(1440, 900)
            page.click('[data-random-details] summary')
            page.wait_for_timeout(200)
            page.click('[data-random-details] '
                       'button:has-text("Последние решения")')
            page.wait_for_timeout(250)
            draws = page.evaluate(
                "document.querySelectorAll('[data-random-draws]').length")
            page.click('[data-random-details] button:has-text("Применения")')
            page.wait_for_timeout(250)
            uses = page.evaluate(
                "document.querySelectorAll('[data-random-uses]').length")
            check("random_draws_panel_kept", draws == 1)
            check("random_uses_panel_kept", uses == 1)
            check("random_details_console_clean", not errors)
            page.locator('[data-random-source]').screenshot(
                path=os.path.join(SHOTS, "b3-random-details-open.png"))
            ctx.close()

            # ── 7. QRNG: только fallback / нет батча ────────────────────
            ctx, page, errors = new_page(1440, 900, mode="fallback")
            pr = _probe(page)
            result["fallback_state"] = pr["lastSuccess"]
            check("fallback_label_honest",
                  pr["lastSuccess"] is not None
                  and "последний откат" in pr["lastSuccess"]["text"]
                  and "успех" not in pr["lastSuccess"]["text"])
            page.locator('[data-random-source]').screenshot(
                path=os.path.join(SHOTS, "b3-random-fallback.png"))
            ctx.close()

            ctx, page, errors = new_page(1440, 900, mode="none")
            pr = _probe(page)
            check("none_last_success_dash", pr["lastSuccess"] is not None
                  and "—" in pr["lastSuccess"]["text"])
            ctx.close()

            # ── 8. Аналитика «Опыта»: полные 8 стадий ───────────────────
            ctx, page, errors = new_page(1440, 900)
            page.evaluate("window.location.hash = '#/modules/experience'")
            page.wait_for_selector('[data-experience-chain="full"]',
                                   timeout=12000)
            page.wait_for_timeout(900)
            chain = page.evaluate(
                """() => {
                  const rows = Array.from(document.querySelectorAll(
                    '[data-experience-chain-stage]'));
                  return {keys: rows.map((r) => r.getAttribute(
                    'data-experience-chain-stage')),
                    noH: document.documentElement.scrollWidth
                      <= window.innerWidth + 1,
                    text: (document.querySelector(
                      '[data-experience-chain="full"]') || {}).innerText || ''};
                }""")
            result["chain"] = {"keys": chain["keys"]}
            check("analytics_full_chain", chain["keys"] == PIPELINE["order"])
            check("analytics_no_h_overflow", chain["noH"])
            check("analytics_server_labels",
                  "Простаивает" in chain["text"]
                  and "Работает" in chain["text"])
            page.screenshot(path=os.path.join(SHOTS, "b3-experience-chain.png"),
                            full_page=True)
            ctx.close()

            # ── 9. Scope: чат → lessons с chat_id, данные не смешаны ────
            ctx, page, errors = new_page(1440, 900)
            page.click(".scope-trigger")
            page.click(".scope-option:has-text('%s')" % CHAT_TITLE)
            page.wait_for_timeout(1500)
            scoped = _probe(page)
            result["scope"] = {
                "rows": scoped["feedRows"],
                "expanded": "чат" in scoped["feedText"],
            }
            check("scope_chat_named", scoped["feedRows"] >= 3
                  and "чат " in scoped["feedText"])
            check("scope_no_foreign_lesson",
                  "Чужое правило" not in scoped["feedText"])
            check("scope_console_clean", not errors)
            page.screenshot(path=os.path.join(SHOTS, "b3-status-chat-scope.png"),
                            full_page=True)
            ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    result["failures"] = failures
    result["ok"] = not failures
    result["limitations"] = [
        "Synthetic Playwright API stub; candidate served bytes are loaded "
        "locally, not a live TMA session.",
        "Production-derived snapshot is used only when "
        "MOD_ACL_M4B3_SNAPSHOT points to a read-only file; no SSH/prod "
        "connection was made by this tool.",
        "503/backlog/fallback/empty states are deterministic fixtures, not "
        "natural production events.",
        "No backend/DDL/flags/prompts changed: only D6 additive read-only "
        "fields on the existing /api/memory/expired-overview.",
    ]
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": result["ok"], "checks": len(result["checks"]),
                      "failures": failures, "screenshots":
                      len(result["screenshots"])}, ensure_ascii=False))
    print("report:", REPORT)
    print("M4B-B3-STATUS-E2E-OK" if result["ok"] else "M4B-B3-STATUS-E2E-FAIL")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
