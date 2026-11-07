# -*- coding: utf-8 -*-
"""PVR-S4 — единый компонент контроля версий промпта (реальный UI).

Проверяет ОДИН переиспользуемый компонент `prompt-version-card` на всех
редакторах промптов и его поведение против настоящих HTTP-контрактов
(`GET /api/prompts/{key}/versions` с плоским состоянием PVR-01
(effective_origin/effective_content_hash/effective_revision_id, journal_*,
baseline/factory, draft_dirty), основным списком `revisions[]`
(`revisions_cursor`), вторичным `activations[]` («была применена»),
`/revisions/{id}/source`, `/revisions/diff`, `/activate`, `/baseline`,
`/baseline/restore`, `/factory/restore`, `/revisions/{id}/copy-to-global`).

Что утверждается (контракт EPIC-PROMPT-VERSIONING-UX-01 §2.1/§2.2/§6 +
PVR-FC-CORRECTIVE-01 PVR-UI):

  * карточка показывает человеческое состояние (без act:/fac:/sha/id);
  * «История версий» открывается панелью (боковая на десктопе, полноэкранная
    на мобильном), список листается дальше 50 записей по `page.next_cursor`;
  * клик по строке открывает экран деталей версии: дословный полный текст
    (GET /source) без пересохранения промпта, «Сравнить с текущей» /
    «Скопировать» в футере, primary «Применить» только если версия отличается,
    «Назначить базовой»/«Скопировать в глобальные» в меню «Действий»;
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
  * нет горизонтального скролла страницы: 1536/1440/1366/768/390/360/320;
  * штампы истории — В ПОЯСЕ ЧАТА из `GET /api/config/time` (PVR-04.2.3),
    без пояса — честная метка «пояс чата недоступен», а не UTC-цифры;
  * read-only статус с причиной виден и на поверхности каталога
    (`variant="history"`, промпт из кода) — PVR-04.1.4.
  * «История N» показывает число только когда список догружен целиком (полнота
    берётся из `revisions_page.has_more`, а не из локального флага — после
    повторного монтирования карточка не выдаёт первую страницу за итог);
  * поиск честно называет свою область: при непрочитанных страницах пустой
    результат — «среди загруженных N совпадений нет», а не «версий не
    существует», и догрузка остаётся доступной из отфильтрованного списка;
  * selection (выбранная строка) переживает «Назад» и не совпадает с active;
  * после «Применить» экран деталей закрывается и возвращается список с
    прилипшим подтверждением сервера.

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
    # PVR-FC-CORRECTIVE-01 (PVR-BACKEND d5ee97ef): основной список панели —
    # ТОЛЬКО revisions (revisions_cursor); события активации — вторичный
    # список «История действий» (activations_cursor), статус «была применена».
    "revisions": [],
    "activations": [],
    "entries_page_size": 50,
    "journal_down": False,
    "code_only": False,
    # Вторичная лента событий: сервер сообщает, что есть ещё страницы
    # (`activations_page.has_more`), хотя загружено только 3 события. Нужно,
    # чтобы проверить честность «нет применений» при непрочитанных страницах.
    "activations_more": False,
    "posts": [],             # все POST/DELETE с путём и телом
    "gets": [],
    # PVR-04.2.3: пояс чата из /api/config/time. `tz_fallback` имитирует
    # серверную деградацию UR-24.4 (зона неизвестна → UTC): UI обязан сказать
    # «пояс чата недоступен», а не печатать UTC-цифры как местное время.
    "tz_fallback": False,
    "tz_requests": [],
    "active": "rev-002",     # сопоставленная действующая ревизия
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


def build_revisions():
    """Ревизии: 130 сохранённых версий, среди них retired/несовместимая.

    Форма строки — как у реального ``list_versions`` (PVR-BACKEND): без
    entry_type/order/event_id/kind/outcome/detail_code, статус «active»
    несёт ревизия, сопоставленная с действующим текстом.
    """
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
            "created_at": "2026-11-03T%02d:%02d:00+00:00" % (10 + (i % 10), i % 60),
            "revision_id": rev,
            "source": "manual",
            # PVR-04.2.3: каноничные подписи источника строки редакции.
            "source_label": "Вручную",
            "origin": "manual",
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
    return rows


def build_activations():
    """События активации (PVR-02.2): «была применена», никогда не active.

    Два события применения ОДНОЙ ревизии (C3.1) + назначение baseline —
    все во вторичном списке, без второй карточки редакции.
    """
    return [
        {"activation_id": 42, "kind": "manual_edit", "outcome": "applied",
         "revision_id": "rev-002", "scope": "chat", "chat_id": CHAT_A,
         "release_id": "", "actor": "77", "detail_code": "",
         "created_at": "2026-11-03T09:00:00+00:00",
         "source": "manual", "source_label": "ручная",
         "status": "was_applied", "status_label": "была применена",
         "actionable": True, "reason_text": "", "body_available": True},
        {"activation_id": 41, "kind": "manual_edit", "outcome": "applied",
         "revision_id": "rev-002", "scope": "chat", "chat_id": CHAT_A,
         "release_id": "", "actor": "77", "detail_code": "",
         "created_at": "2026-11-02T09:00:00+00:00",
         "source": "manual", "source_label": "ручная",
         "status": "was_applied", "status_label": "была применена",
         "actionable": True, "reason_text": "", "body_available": True},
        {"activation_id": 40, "kind": "baseline_assign", "outcome": "recorded",
         "revision_id": "", "scope": "chat", "chat_id": CHAT_A,
         "release_id": "", "actor": "77", "detail_code": "baseline:manual",
         "created_at": "2026-11-01T09:00:00+00:00",
         "source": "restored", "source_label": "назначена базовая",
         "status": "event", "status_label": "событие",
         "actionable": False, "reason_text": "", "body_available": False},
    ]


def _ms_time(iso, offset_hours=3):
    """UTC-метка журнала → время в поясе чата (+03:00, Europe/Moscow)."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=offset_hours)))


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
    # PVR-BACKEND: три независимых курсора — merged-лента (совместимость),
    # revisions (основной список) и activations (вторичный список).
    start = int(params.get("cursor", 0) or 0)
    rev_start = int(params.get("revisions_cursor", 0) or 0)
    act_start = int(params.get("activations_cursor", 0) or 0)
    rows = STATE["revisions"]
    page = rows[start:start + size]
    nxt = start + size
    has_more = nxt < len(rows)
    rev_page = rows[rev_start:rev_start + size]
    rev_nxt = rev_start + size
    rev_more = rev_nxt < len(rows)
    acts = STATE["activations"]
    act_page = acts[act_start:act_start + size]
    act_nxt = act_start + size
    act_more = act_nxt < len(acts) or bool(STATE.get("activations_more"))
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
        # ── PVR-01: плоский контракт эффективного состояния ──
        "effective_origin": "chat_override",
        "effective_origin_label": "локальная версия чата",
        "effective_content_hash": "123456789abc",
        "effective_revision_id": STATE["active"] or None,
        "effective_status": "matched",
        "effective_status_label":
            "Действующий текст совпадает с сохранённой версией",
        "effective_diagnostics": [],
        "journal_last_activation_id": 42,
        "journal_active_revision_id": STATE["active"] or None,
        "baseline_revision_id": STATE["baseline"] or None,
        "factory_revision_id": "fac:deadbeefcafe",
        "draft_dirty": False,
        # Основной список = ревизии; события — вторичный список.
        "revisions": rev_page,
        "revisions_page": {"order": "oldest", "paging": "newest_first",
                           "next_cursor": str(rev_nxt) if rev_more else "",
                           "has_more": rev_more, "returned": len(rev_page)},
        "activations": act_page,
        "activations_page": {"order": "newest_first",
                             "next_cursor": str(act_nxt) if act_more else "",
                             "has_more": act_more, "returned": len(act_page)},
        # merged-лента остаётся в ответе (совместимость с прежним API).
        "entries": page,
        "page": {"page_size": size, "order": "newest_first",
                 "next_cursor": str(nxt) if has_more else "",
                 "has_more": has_more, "returned": len(page),
                 "rank_start": start + 1, "total_known": None},
        "supported_schema_compat": ["1", "2"],
    }


def _time_state():
    """Честный ответ `GET /api/config/time` (UR-29.1): IANA-зона чата.

    Пояс считает СЕРВЕР (zoneinfo), UI только форматирует штампы истории в
    этой зоне (PVR-04.2.3). `tz_fallback` — явная деградация: зона неизвестна.
    """
    fallback = bool(STATE.get("tz_fallback"))
    return {
        "chat_id": CHAT_A,
        "iana": "UTC" if fallback else "Europe/Moscow",
        "source": "utc_fallback" if fallback else "chat",
        "config_version": 1,
        "configured": None,
        "now_local": "2026-11-03T15:10:00+03:00",
        "as_of_utc": "2026-11-03T12:10:00+00:00",
        "utc_offset": "+00:00" if fallback else "+03:00",
        "is_dst": False,
        "weekday": 1,
        "utc_fallback": fallback,
    }


def _prompt_catalog():
    """`GET /api/prompts/catalog` — каталог зарегистрированных промптов.

    Нужен ровно для поверхности `variant="history"`: там `can-edit=false`
    всегда, и именно там PVR-04.1.4 обязан показывать честный read-only
    статус с причиной (промпт из кода / нет прав).
    """
    return {"families": [
        {"id": "initiative", "title": "Инициатива",
         "prompts": [
             {"block_id": "initiative.meme.joke", "pg_key": PROMPT_KEY,
              "purpose": "Промпт прикола"},
         ]},
    ], "count": 1}


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
            if path.endswith("/api/prompts/catalog"):
                return send(_prompt_catalog())
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
                for row in STATE["revisions"]:
                    if row["status"] in ("retired", "incompatible"):
                        continue        # статус-гейт журнала не перетирается
                    row["status"] = ("active" if row["revision_id"] == rev
                                     else "inactive")
                    row["status_label"] = ("активная"
                                           if row["revision_id"] == rev
                                           else "неактивная")
                # Событие применения добавляется в append-only ленту событий
                # (C1.3: одна ревизия в интерфейсе, событие — во вторичной).
                STATE["activations"].insert(0, {
                    "activation_id": 100 + len(STATE["activations"]),
                    "kind": "manual_edit", "outcome": "applied",
                    "revision_id": rev, "scope": "chat", "chat_id": CHAT_A,
                    "release_id": "", "actor": "77", "detail_code": "",
                    "created_at": "2026-11-03T09:30:00+00:00",
                    "source": "manual", "source_label": "ручная",
                    "status": "was_applied", "status_label": "была применена",
                    "actionable": True, "reason_text": "",
                    "body_available": True})
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
        # UR-29.1: уже существующий контракт пояса чата. Именно его читает
        # компонент версий, чтобы печатать штампы в TZ чата (PVR-04.2.3) —
        # аддитивных полей бэкенда не требуется.
        if path.endswith("/api/config/time"):
            STATE["tz_requests"].append(
                {"path": path, "chat": req.headers.get("x-chat-id")})
            return send(_time_state())
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


SDK_STUB_TMPL = """
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A77%2C%22first_name%22%3A%22A%22%7D&hash=x',
  initDataUnsafe: { user: { id: 77, first_name: 'A' } },
  ready() {}, expand() {}, close() {}, colorScheme: 'dark',
  themeParams: {}, isExpanded: true,
  viewportHeight: __VH__, viewportStableHeight: __VH__,
  onEvent() {}, offEvent() {},
  setHeaderColor() {}, setBackgroundColor() {}, sendData() {},
  openLink() {}, isVersionAtLeast() { return true; }, platform: 'web',
  disableVerticalSwipes() {}, enableClosingConfirmation() {},
  disableClosingConfirmation() {}, showAlert() {}, showConfirm() {}
} };
"""


def sdk_stub(height):
    """Стаб SDK обязан отражать РЕАЛЬНУЮ высоту окна контекста: в настоящем
    Telegram `viewportStableHeight` приходит из платформы, и именно из него
    telegram-init считает `--app-usable-height` (геометрия панелей/клавиатуры).
    Хардкод 900 в окне 780 ломал любые fixed-подвалы тестовой среды."""
    return SDK_STUB_TMPL.replace("__VH__", str(int(height)))

failures = []
notes = []
DIALOGS = []
DIALOG_MODE = {"mode": "accept"}
# PVR-04.2.3/04.3.1: измерения для отчёта (высоты, hscroll по ширинам).
MEASURE = {}
# Ошибки консоли/необработанные исключения страницы — обязаны быть пустыми
# на каждом прогоне (раньше «чистая консоль» была словами в README).
CONSOLE_ERRORS = []


def _on_dialog(dialog):
    DIALOGS.append(dialog.message or "")
    try:
        if DIALOG_MODE["mode"] == "accept":
            dialog.accept()
        else:
            dialog.dismiss()
    except Exception:  # noqa: BLE001
        pass


def _on_console(msg):
    """Автоматическая проверка «консоль чистая» (а не утверждение в отчёте)."""
    try:
        if msg.type != "error":
            return
        text = (msg.text or "").strip()
        # 404 статического favicon — не ошибка приложения.
        if "favicon" in text.lower():
            return
        # Сценарий «журнал недоступен» НАМЕРЕННО отдаёт 503 (PVR-05.2);
        # честная деградация проверяется отдельными assertions. Сетевой
        # лог браузера об этом — не ошибка кода приложения.
        loc = msg.location or {}
        where = loc.get("url") or ""
        if ("Failed to load resource" in text and "503" in text
                and "/api/prompts/" in where and "/versions" in where):
            return
        CONSOLE_ERRORS.append("console: %s (%s)" % (text[:240], where[:120]))
    except Exception:  # noqa: BLE001
        pass


def _on_pageerror(exc):
    CONSOLE_ERRORS.append("pageerror: %s" % str(exc)[:240])


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
                                          body=sdk_stub(height)))
    ctx.add_init_script(
        "try { localStorage.setItem('adminbot.active_chat_id', '%d'); }"
        " catch (e) {}" % CHAT_A)
    page = ctx.new_page()
    page.set_default_timeout(20000)
    page.on("dialog", _on_dialog)
    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)
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


def shot_view(page, shots, name):
    """Снимок ВИДИМОГО окна (без full_page).

    Панель истории — `position: fixed`; на полноэкранном снимке она
    отрисовывается в начале документа и не показывает реальное положение
    элементов. Для проверки видимости подтверждения нужен именно вид окна.
    """
    if not shots:
        return
    os.makedirs(shots, exist_ok=True)
    try:
        page.screenshot(path=os.path.join(shots, name + ".png"),
                        full_page=False)
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


def open_panel(page, wait_times=True):
    page.click("[data-prompt-history-toggle]")
    page.wait_for_selector("[data-pv-panel]", state="visible")
    page.wait_for_timeout(400)
    if wait_times:
        # Штампы истории печатаются только после ответа /api/config/time:
        # ждём реальное время строки, а не фиксированный sleep.
        page.wait_for_function(
            "() => { const rows = document.querySelectorAll('[data-pv-row]');"
            " if (!rows.length) return false;"
            " const n = rows[0].querySelector('.pv-row__name');"
            " return !!(n && /\\d{2}\\.\\d{2} \\d{2}:\\d{2}/.test("
            "n.textContent || '')); }", timeout=10000)


def touch_probe(page):
    """Интерактивные элементы внутри панели: видимость и высота (≥44px)."""
    return page.evaluate(r"""
        () => {
          const p = document.querySelector('[data-pv-panel]');
          if (!p) return null;
          const named = ['data-pv-panel-close', 'data-pv-panel-back',
            'data-pv-load-more', 'data-pv-events-toggle',
            'data-pv-actions-toggle', 'data-pv-row-activate',
            'data-pv-result-dismiss', 'data-pv-row-compare',
            'data-pv-row-copy', 'data-pv-factory-restore'];
          const out = [];
          p.querySelectorAll('button, input, select, textarea, a[href],'
            + ' [role="button"]').forEach((el) => {
              if (el.disabled) return;
              const r = el.getBoundingClientRect();
              const st = getComputedStyle(el);
              if (r.width <= 0 || r.height <= 0) return;
              if (st.display === 'none' || st.visibility === 'hidden') return;
              let name = '';
              for (const a of named) {
                if (el.hasAttribute(a)) { name = a; break; }
              }
              if (!name) {
                name = el.tagName.toLowerCase() + ':'
                  + ((el.textContent || '').trim().slice(0, 16));
              }
              out.push({name: name,
                        h: Math.round(r.height * 10) / 10,
                        w: Math.round(r.width * 10) / 10});
            });
          return out;
        }
    """)


def assert_touch_targets(page, label, where):
    """PVR-04.3.1: КАЖДАЯ цель внутри панели ≥44px; цифры — в отчёт."""
    items = touch_probe(page) or []
    bad = [i for i in items if i["h"] < 43.5]
    check(not bad, label,
          "тач-цели панели <44px (%s): %r" % (where, bad[:8]))
    mine = MEASURE.setdefault(label, {})
    touch = mine.setdefault("touch", {})
    touch[where] = {
        "count": len(items),
        "min_h": min([i["h"] for i in items]) if items else None,
        "named": {i["name"]: i["h"] for i in items
                  if i["name"].startswith("data-pv-")},
    }
    return items


def panel_rows(page):
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
        ".map((el) => ({rev: el.getAttribute('data-prompt-history-revision'),"
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


def open_row_detail(page, idx):
    """PVR-04.2.3/04.2.4: клик по строке открывает экран деталей версии."""
    page.evaluate(
        "([i]) => { const r = document.querySelectorAll('[data-pv-row]')[i];"
        " if (r) r.click(); }", [idx])


def panel_geometry(page):
    """Геометрия панели/деталей (PVR-04.2.1/04.3.1).

    Возвращает ширину панели, её левый край, ширину окна, ширину textarea
    редактора (читаемость основного редактора при открытой панели), флаг
    полноэкранности на мобильном и прокручиваемость тела панели.
    """
    return page.evaluate(r"""
        () => {
          const p = document.querySelector('[data-pv-panel]');
          if (!p) return null;
          const b = p.getBoundingClientRect();
          const ta = document.querySelector('[data-prompt-editor] textarea');
          const t = ta ? ta.getBoundingClientRect() : null;
          const body = document.querySelector('.pv-panel__body');
          const row = document.querySelector('[data-pv-row]');
          return {
            w: b.width, left: b.left, right: b.right,
            top: b.top, bottom: b.bottom,
            vw: window.innerWidth, vh: window.innerHeight,
            editorW: t ? t.width : null,
            fullscreen: Math.abs(b.width - window.innerWidth) < 2,
            bodyScrollH: body ? body.scrollHeight : null,
            bodyClientH: body ? body.clientHeight : null,
            rowMinH: row ? parseFloat(getComputedStyle(row).minHeight) : null,
          };
        }
    """)


def result_geometry(page):
    """Геометрия блока подтверждения внутри панели (PVR-S4 B4).

    Возвращает `rect` блока, `body` — видимый прямоугольник прокручиваемого
    тела панели, `scrollTop` тела и признак `hitsCenter`: попадает ли центр
    блока в `elementFromPoint` (то есть ничто его не перекрывает).
    """
    return page.evaluate(r"""
        () => {
          const el = document.querySelector('[data-prompt-history-result]');
          const body = document.querySelector('.pv-panel__body');
          if (!el || !body) return null;
          const b = body.getBoundingClientRect();
          const panel = (document.querySelector('[data-pv-panel]') || body)
            .getBoundingClientRect();
          // Прилипший (sticky) блок измеряем после синхронного layout:
          // rect уже учитывает текущий scrollTop тела.
          const r = el.getBoundingClientRect();
          const cx = (r.left + r.right) / 2;
          const cy = (r.top + r.bottom) / 2;
          const hit = document.elementFromPoint(cx, cy);
          return {
            rect: {top: r.top, bottom: r.bottom,
                   left: r.left, right: r.right,
                   h: r.height, w: r.width},
            body: {top: b.top, bottom: b.bottom,
                   left: b.left, right: b.right},
            panel: {top: panel.top, bottom: panel.bottom,
                    left: panel.left, right: panel.right},
            scrollTop: body.scrollTop,
            scrollHeight: body.scrollHeight,
            clientHeight: body.clientHeight,
            vh: window.innerHeight, vw: window.innerWidth,
            hitsCenter: !!(hit && (el === hit || el.contains(hit))),
          };
        }
    """)


def assert_result_visible(page, label, where):
    """B4: подтверждение обязано быть ЦЕЛИКОМ в видимой области тела панели.

    Проверяется именно геометрия, а не `textContent`: блок, уехавший в конец
    50-строчной ленты, остаётся в DOM (текст есть), но пользователь его не
    видит — ровно этот дефект и был пропущен content-проверкой.
    """
    g = result_geometry(page)
    if not check(g is not None, label,
                 "%s: блока подтверждения нет в DOM" % where):
        return None
    r, b = g["rect"], g["body"]
    check(g["scrollTop"] == 0, label,
          "%s: панель прокручена (scrollTop=%s) — список не должен "
          "прокручиваться действием" % (where, g["scrollTop"]))
    check(r["top"] >= b["top"] - 0.5 and r["bottom"] <= b["bottom"] + 0.5,
          label,
          "%s: подтверждение вне видимой области тела панели: "
          "rect=%s..%s, тело=%s..%s, scrollTop=%s"
          % (where, round(r["top"]), round(r["bottom"]), round(b["top"]),
             round(b["bottom"]), g["scrollTop"]))
    check(r["left"] >= b["left"] - 0.5 and r["right"] <= b["right"] + 0.5,
          label,
          "%s: подтверждение выходит за тело панели по горизонтали: "
          "rect=%s..%s, тело=%s..%s"
          % (where, round(r["left"]), round(r["right"]), round(b["left"]),
             round(b["right"])))
    check(r["top"] >= 0 and r["bottom"] <= g["vh"], label,
          "%s: подтверждение вне окна: rect=%s..%s, окно=%s"
          % (where, round(r["top"]), round(r["bottom"]), g["vh"]))
    check(g["hitsCenter"], label,
          "%s: подтверждение перекрыто другим элементом" % where)
    return g


def assert_result_sticky(page, label, where):
    """B4: подтверждение не уезжает и при прокрутке ленты (sticky).

    Прокручиваем тело панели в самый низ и обратно: блок обязан остаться в
    видимой области тела. Затем возвращаем scrollTop=0 — состояние, в котором
    панель находится после «Применить».
    """
    page.evaluate("() => { const b = document.querySelector('.pv-panel__body');"
                  " if (b) b.scrollTop = b.scrollHeight; }")
    page.wait_for_timeout(120)
    g = result_geometry(page)
    if not check(g is not None, label,
                 "%s: блока подтверждения нет в DOM" % where):
        return
    r, b = g["rect"], g["body"]
    check(g["scrollTop"] > 0, label,
          "%s: тело панели не прокрутилось (scrollHeight=%s clientHeight=%s) — "
          "проверка sticky недостоверна" % (where, g["scrollHeight"],
                                            g["clientHeight"]))
    check(r["top"] >= b["top"] - 0.5 and r["bottom"] <= b["bottom"] + 0.5,
          label,
          "%s: при прокрутке ленты подтверждение уехало: rect=%s..%s, "
          "тело=%s..%s, scrollTop=%s"
          % (where, round(r["top"]), round(r["bottom"]), round(b["top"]),
             round(b["bottom"]), g["scrollTop"]))
    check(g["hitsCenter"], label,
          "%s: при прокрутке подтверждение перекрыто другим элементом"
          % where)
    page.evaluate("() => { const b = document.querySelector('.pv-panel__body');"
                  " if (b) b.scrollTop = 0; }")
    page.wait_for_timeout(80)


def run_editor(label, page, shots, width):
    target = open_prompt_editor(page)
    check(target and target.get("key"), label, "редактор промпта не открылся")
    # PVR-04.2.1: ширина редактора БЕЗ панели — панель истории обязана быть
    # оверлеем и не должна reflow-ить/сужать основной редактор.
    editor_w_before = page.evaluate(
        "() => { const ta = document.querySelector('[data-prompt-editor] textarea');"
        " return ta ? ta.getBoundingClientRect().width : null; }")
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
    check("Действует в этом чате" in (card["state"] or ""), label,
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

    # 2) панель истории: шапка (eyebrow/область/поиск/справка), ОДИН блок
    #    «Сейчас действует», первая страница, листание >50 (PVR-04.2.1/04.2.2)
    open_panel(page)
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
    head = page.evaluate(
        "() => ({eyebrow: (document.querySelector('.pv-panel__eyebrow') || {})"
        ".textContent || '', scope: (document.querySelector"
        "('[data-pv-panel-scope]') || {}).textContent || '',"
        " search: !!document.querySelector('[data-pv-search]'),"
        " hint: ((document.querySelector('[data-pv-panel-hint]') || {})"
        ".textContent || ''),"
        " nowBlocks: document.querySelectorAll('[data-pv-panel-meta]').length,"
        " now: ((document.querySelector('[data-pv-panel-meta]') || {})"
        ".textContent || ''),"
        " active: ((document.querySelector('[data-pv-panel-active]') || {})"
        ".textContent || '')})")
    check("История версий" in head["eyebrow"], label,
          "в шапке панели нет «История версий»: %r" % (head["eyebrow"],))
    check("Этот чат" in head["scope"], label,
          "в шапке панели нет области «Этот чат»: %r" % (head["scope"],))
    check(head["search"], label, "в шапке панели нет поиска по версиям")
    check("глобальную" in head["hint"], label,
          "в шапке панели нет справки о наследовании: %r" % (head["hint"],))
    check(head["nowBlocks"] == 1, label,
          "блок «Сейчас действует» не один: %d" % head["nowBlocks"])
    now_txt = head["now"].replace("\n", " ")
    for needle in ("Сейчас действует", "локальная версия чата",
                   "исходный из кода", "базовый по выбору владельца"):
        check(needle in now_txt, label,
              "в блоке «Сейчас действует» нет %r: %r" % (needle, now_txt[:200]))
    check("03.11 15:02" in head["active"], label,
          "в «Сейчас действует» нет даты сопоставленной ревизии в поясе "
          "чата (+03:00): %r" % (head["active"],))
    check("03.11 12:02" not in head["active"], label,
          "PVR-04.2.3: UTC-цифры выданы за время чата: %r" % (head["active"],))
    saved_txt = page.evaluate(
        "() => ((document.querySelector('[data-pv-saved]') || {})"
        ".textContent || '').replace(/\\s+/g, ' ').trim()")
    check("03.11 15:02" in saved_txt, label,
          "«Сохранено …» не в поясе чата: %r" % (saved_txt,))
    check(not page.evaluate(
        "() => !!document.querySelector('[data-pv-panel-tz-unavailable]')"),
        label, "при доступном поясе чата показана причина недоступности")
    # PVR-04.2.3: час строки журнала = час UTC + 3 (Europe/Moscow), не UTC.
    by_rev = {r["revision_id"]: r for r in STATE["revisions"]}
    rows_shown = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]')).slice(0, 3)"
        ".map((el) => ({rev: el.getAttribute('data-prompt-history-revision'),"
        " name: ((el.querySelector('.pv-row__name') || {}).textContent"
        "   || '').replace(/\\s+/g, ' ').trim()}))")
    tz_checked = 0
    for item in rows_shown:
        match = re.search(r"(\d{2})\.(\d{2}) (\d{2}):(\d{2})", item["name"])
        if not match:
            continue
        exp = _ms_time(by_rev[item["rev"]]["created_at"])
        check((match.group(1), match.group(2), match.group(3), match.group(4))
              == (exp.strftime("%d"), exp.strftime("%m"),
                  exp.strftime("%H"), exp.strftime("%M")), label,
              "время строки %s не в поясе чата: %r, ожидалось %s"
              % (item["rev"], item["name"], exp.strftime("%d.%m %H:%M")))
        tz_checked += 1
    check(tz_checked >= 2, label,
          "не удалось проверить штампы строк в поясе чата: %r" % (rows_shown,))
    if width <= 430:
        # PVR-04.3.1: «Закрыть» / «Показать более ранние версии» /
        # «История действий» были 34px при строках/CTA 44px.
        assert_touch_targets(page, label, "list")
    def set_search(q):
        page.evaluate(
            "(q) => { const el = document.querySelector('[data-pv-search]');"
            " el.value = q; el.dispatchEvent(new Event('input')); }", q)
        page.wait_for_timeout(250)

    meta = page.evaluate(
        "() => ({rows: document.querySelectorAll('[data-pv-row]').length,"
        " end: !!document.querySelector('[data-pv-end]'),"
        " more: !!document.querySelector('[data-pv-load-more]'),"
        " count: (function () { const c = document.querySelector"
        "   ('[data-pv-history-count]');"
        "   return c ? (c.textContent || '').trim() : null; })()})")
    check(meta["rows"] == 50, label,
          "первая страница не 50 записей: %d" % meta["rows"])
    # PVR-04.0: «История N» — только честно известное число. Пока сервер
    # сообщает `has_more`, числа быть не должно (иначе загрузка выдаётся
    # за итог).
    check(meta["count"] is None, label,
          "при непрочитанных страницах у «История» есть число: %r"
          % (meta["count"],))
    revs = [r["rev"] for r in panel_rows(page)]
    check(revs[0] == "rev-001", label,
          "основной список ревизий не начинается с rev-001: %r" % (revs[:3],))
    # PVR-04.2.2: поиск охватывает ЗАГРУЖЕННУЮ часть истории и говорит об
    # этом честно. rev-099 существует, но лежит на непрочитанной странице —
    # «сохранённых версий нет» здесь было бы ложью, а догрузка обязана
    # оставаться доступной прямо из отфильтрованного состояния.
    set_search("rev-099")
    scope = page.evaluate(
        "() => { const empty = document.querySelector('[data-pv-search-empty]');"
        " const sc = document.querySelector('[data-pv-search-scope]');"
        " const more = document.querySelector('[data-pv-load-more]');"
        " return {rows: document.querySelectorAll('[data-pv-row]').length,"
        " text: (empty ? empty.textContent : '').replace(/\\s+/g, ' ').trim(),"
        " scope: (sc ? sc.textContent : '').replace(/\\s+/g, ' ').trim(),"
        " more: !!more, moreEnabled: !!(more && !more.disabled)}; }")
    check(scope["rows"] == 0, label,
          "поиск rev-099 нашёл строку среди загруженных 50: %r" % (scope,))
    check(scope["text"] != "", label,
          "нет честного empty-state поиска при непрочитанных страницах: %r"
          % (scope,))
    check("загруженных" in scope["text"] and "нет" in scope["text"], label,
          "пустой результат поиска не называет загруженную часть: %r"
          % (scope["text"],))
    check("сохранённых версий нет" not in scope["text"], label,
          "поиск утверждает, что версий не существует, хотя страницы не "
          "загружены: %r" % (scope["text"],))
    check("не вся история" in scope["text"] or "ещё не\n" in scope["text"]
          or "ещё не загружены" in scope["text"], label,
          "пустой результат не говорит, что история загружена не полностью: %r"
          % (scope["text"],))
    check("загруженных" in scope["scope"] and "50" in scope["scope"], label,
          "строка области поиска не называет загруженное число: %r"
          % (scope["scope"],))
    check(scope["more"] and scope["moreEnabled"], label,
          "догрузка недоступна при активном фильтре — поиск не сможет дойти "
          "до более ранних версий: %r" % (scope,))
    set_search("")
    # PVR-04.0 (повторное монтирование): карточка восстанавливает состояние
    # из короткого кэша, поэтому число версий не имеет права появиться из
    # первой страницы («История 50», хотя сервер отдаёт has_more=true).
    gets_before = len(STATE["gets"])
    page.click("[data-pv-panel-close]")
    page.wait_for_timeout(250)
    route = (target or {}).get("route")
    check(bool(route), label, "не сохранён маршрут редактора для перемонтирования")
    if route:
        page.evaluate("() => window.__adminbotVm.navigateTo('#/')")
        page.wait_for_timeout(400)
        page.evaluate(
            "(route) => window.__adminbotVm.navigateTo(route)", route)
        page.wait_for_selector("[data-prompt-history-toggle]", state="visible")
        page.wait_for_timeout(600)
    remount_hist = page.evaluate(
        "() => { const c = document.querySelector('[data-pv-history-count]');"
        " return c ? (c.textContent || '').trim() : null; }")
    check(remount_hist is None, label,
          "после повторного монтирования у «История» есть число при "
          "непрочитанных страницах: %r" % (remount_hist,))
    check(len(STATE["gets"]) == gets_before, label,
          "повторное монтирование не использовало кэш состояния (GET "
          "повторился), проверка числа недостоверна: %d новых запросов"
          % (len(STATE["gets"]) - gets_before))
    open_panel(page)
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
    # PVR-04.2.1: панель 420–540 px на desktop, редактор остаётся читаемым,
    # тело панели прокручивается внутри себя.
    geo = panel_geometry(page)
    if width >= 960:
        check(geo and 420 <= geo["w"] <= 540, label,
              "панель истории не 420–540 px на desktop: %r" % (geo,))
        check(geo["editorW"] is not None and editor_w_before is not None
              and abs(geo["editorW"] - editor_w_before) <= 2, label,
              "панель истории reflow-нула основной редактор (было %s, стало %s)"
              % (editor_w_before, geo["editorW"]))
    elif width >= 768:
        # Узкий desktop — центральный диалог (не чрезмерное сужение).
        centered = abs(geo["left"] - (geo["vw"] - geo["w"]) / 2)
        check(geo["w"] <= 522 and centered <= 2, label,
              "на узком desktop панель не центральный диалог: %r (centered=%s)"
              % (geo, centered))
    check(geo["bodyScrollH"] > geo["bodyClientH"], label,
          "тело панели не прокручивается внутри себя: %r" % (geo,))
    shot(page, shots, "history_%s" % label)
    page.click("[data-pv-load-more]")
    page.wait_for_timeout(500)
    rows2 = panel_rows(page)
    check(len(rows2) > 50, label,
          "история не листается дальше 50: %d" % len(rows2))
    check(len(rows2) == 100, label,
          "вторая страница не догрузила ровно 50: %d" % len(rows2))
    revs2 = [r["rev"] for r in rows2]
    check(revs2[-1] == "rev-100", label,
          "после догрузки ревизии непрерывны: %r" % (revs2[-3:],))
    # Блокер 3, вторая половина: как только rev-099 действительно загружен,
    # тот же фильтр его НАХОДИТ — версии не «теряются» молча.
    set_search("rev-099")
    found099 = [r["rev"] for r in panel_rows(page)]
    check(found099 == ["rev-099"], label,
          "поиск rev-099 не нашёл уже загруженную версию: %r" % (found099[:5],))
    set_search("")
    # PVR-04.0: число у «История» появляется только когда список догружен
    # ЦЕЛИКОМ. Проверяем оба края: промежуточная страница — числа нет,
    # последняя — точное число и честный признак конца истории.
    hist_mid = page.evaluate(
        "() => { const c = document.querySelector('[data-pv-history-count]');"
        " return c ? (c.textContent || '').trim() : null; }")
    check(hist_mid is None, label,
          "после второй страницы (остались непрочитанные) у «История» есть "
          "число: %r" % (hist_mid,))
    page.click("[data-pv-load-more]")
    page.wait_for_timeout(500)
    rows3 = panel_rows(page)
    check(len(rows3) == TOTAL_ENTRIES, label,
          "полная догрузка истории не сошлась: %d из %d"
          % (len(rows3), TOTAL_ENTRIES))
    tail = page.evaluate(
        "() => ({end: !!document.querySelector('[data-pv-end]'),"
        " more: !!document.querySelector('[data-pv-load-more]'),"
        " count: (function () { const c = document.querySelector"
        "   ('[data-pv-history-count]');"
        "   return c ? (c.textContent || '').trim() : null; })()})")
    check(tail["end"] and not tail["more"], label,
          "после последней страницы нет честного признака конца истории: %r"
          % (tail,))
    check(tail["count"] == str(TOTAL_ENTRIES), label,
          "полностью загруженная история не показывает точное число версий: %r"
          % (tail["count"],))

    # 2b) PVR-04.2.2: поиск по версиям фильтрует загруженный список; пустой
    #     результат — честный empty-state, без подстановок.
    set_search("rev-010")
    filtered = [r["rev"] for r in panel_rows(page)]
    check(filtered == ["rev-010"], label,
          "поиск «rev-010» не фильтрует список: %r" % (filtered[:5],))
    set_search("Вручную")
    manual_only = panel_rows(page)
    check(len(manual_only) == len(rows3), label,
          "поиск «Вручную» потерял ревизии: %d" % len(manual_only))
    set_search("запрос-без-совпадений")
    check(page.evaluate(
        "() => !!document.querySelector('[data-pv-search-empty]')"), label,
        "нет честного empty-state при пустом результате поиска")
    check(page.evaluate(
        "() => document.querySelectorAll('[data-pv-row]').length") == 0, label,
        "при пустом результате поиска остались чужие строки")
    set_search("")
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")

    # 2c) PVR-04.2.3: строки редакций — максимум один статус; selection
    #     отличается от active; источников «Вручную» в строках.
    badge_counts = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
        ".map((el) => el.querySelectorAll('.pv-row__status').length)")
    check(all(c <= 1 for c in badge_counts), label,
          "у строки редакции больше одного статус-чипа: %r"
          % (badge_counts[:10],))
    source_seen = page.evaluate(
        "() => document.querySelector('[data-pv-row-source]').textContent")
    check("Вручную" in source_seen, label,
          "в строке редакции нет каноничного источника «Вручную»: %r"
          % (source_seen,))
    # Сырой Telegram-id чата (-100500…) — техническая деталь: в строках его
    # нет, область называется словами.
    row_texts = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]')).slice(0, 5)"
        ".map((el) => (el.textContent || '').replace(/\\s+/g, ' ').trim())")
    check(not any(re.search(r"-?\d{6,}", t) for t in row_texts), label,
          "в строках редакций остался сырой id чата: %r" % (row_texts[:2],))
    check(all("этот чат" in t for t in row_texts), label,
          "область строки не названа человеческими словами: %r"
          % (row_texts[:2],))
    check(page.evaluate(
        "() => document.querySelectorAll('[data-pv-row] .pv-row__status')"
        ".length") >= 1, label,
        "активная строка не получила статус «Действует»")
    active_txt = page.evaluate(
        "() => ((document.querySelector('[data-pv-row]"
        "[data-pv-status=\\'active\\'] .pv-row__status') || {}).textContent"
        " || '')")
    check(active_txt == "Действует", label,
          "статус активной строки не «Действует»: %r" % (active_txt,))
    open_row_detail(page, 3)
    page.wait_for_selector("[data-pv-detail]", state="visible")
    if width <= 430:
        assert_touch_targets(page, label, "detail")
    check(page.evaluate(
        "() => !document.querySelector('[data-prompt-history-versions]')"),
        label, "детали версии не открылись отдельным экраном")
    page.click("[data-pv-panel-back]")
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
    # PVR-04.2.3: selection ПЕРЕЖИВАЕТ «Назад» и остаётся видимым в списке,
    # но это НЕ active-строка (selection != active). Само условие rAF-ожидания
    # и есть утверждение: строка rev-004 подсвечена как selected, active —
    # rev-002, и они не совпадают. При регрессии (selectedId сброшен) такое
    # состояние не наступит никогда — таймаут даст красный результат.
    sel_ok = page.wait_for_function(
        """() => {
             const sel = document.querySelector('[data-pv-row].is-selected');
             const act = document.querySelector('[data-pv-row].is-active');
             return !!(sel
               && sel.getAttribute('data-prompt-history-revision') === 'rev-004'
               && act
               && act.getAttribute('data-prompt-history-revision') === 'rev-002'
               && !sel.classList.contains('is-active'));
           }""",
        timeout=4000)
    check(bool(sel_ok), label,
          "selection (rev-004) не пережил «Назад» или не отличается от active"
          " (rev-002)")

    # 3) Просмотр версии (PVR-04.2.4): клик по строке открывает детали с
    #    дословным полным текстом, без пересохранения (GET, не POST).
    posts_before = len(STATE["posts"])
    rev0 = row_rev(page, 0)
    open_row_detail(page, 0)
    page.wait_for_selector("[data-pv-view-body]", state="visible")
    view = page.evaluate(
        "() => (document.querySelector('[data-pv-view-body]') || {}).textContent")
    check((view or "").strip() == _body(rev0).strip(), label,
          "текст версии показан не дословно/обрезан: %r" % (view,))
    check(len(STATE["posts"]) == posts_before, label,
          "просмотр текста сделал запись (пересохранение)")
    detail_head = page.evaluate(
        "() => ((document.querySelector('.pv-panel__title--detail') || {})"
        ".textContent || '')")
    check("Версия от" in detail_head, label,
          "в шапке деталей нет имени «Версия от …»: %r" % (detail_head,))
    page.click("[data-pv-panel-back]")
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")

    # 4) diff «было → стало» из футера деталей: красный/зелёный только на
    #    изменённых строках
    open_row_detail(page, 3)
    page.wait_for_selector("[data-pv-detail-actions]", state="visible")
    page.click("[data-pv-row-compare]")
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
    page.click("[data-pv-panel-back]")
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")

    # 5) недоступные действия (PVR-04.2.4): причина в деталях версии вместо
    #    мёртвой кнопки; у retired нет «Применить» и «Назначить базовой».
    statuses = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
        ".map((el) => ({status: el.getAttribute('data-pv-status'),"
        " rev: el.getAttribute('data-prompt-history-revision') || ''}))")
    retired = [r for r in statuses if r["status"] == "retired"]
    check(bool(retired), label, "retired-версии нет в ленте")
    if retired:
        idx = [r["rev"] for r in statuses].index(retired[0]["rev"])
        open_row_detail(page, idx)
        page.wait_for_selector("[data-pv-detail]", state="visible")
        ret_detail = page.evaluate(
            "() => ({reason: ((document.querySelector('[data-pv-row-reason]')"
            " || {}).textContent || '').trim(),"
            " activate: !!document.querySelector"
            "('[data-pv-detail-actions] [data-pv-row-activate]'),"
            " baselineBtn: !!document.querySelector"
            "('[data-pv-detail-actions] [data-pv-row-baseline]')})")
        check(not ret_detail["activate"] and "retired" in ret_detail["reason"],
              label,
              "у retired-версии есть активная кнопка или нет причины: %r"
              % (ret_detail,))
        check(not ret_detail["baselineBtn"], label,
              "у retired-версии есть «Назначить базовой»")
        page.click("[data-pv-panel-back]")
        page.wait_for_selector("[data-prompt-history-versions]",
                               state="visible")
    incompat = [r for r in statuses if r["status"] == "incompatible"]
    check(bool(incompat), label, "несовместимой версии нет в ленте")
    if incompat:
        idx = [r["rev"] for r in statuses].index(incompat[0]["rev"])
        open_row_detail(page, idx)
        page.wait_for_selector("[data-pv-detail]", state="visible")
        inc_detail = page.evaluate(
            "() => ({reason: ((document.querySelector('[data-pv-row-reason]')"
            " || {}).textContent || '').trim(),"
            " activate: !!document.querySelector"
            "('[data-pv-detail-actions] [data-pv-row-activate]')})")
        check(not inc_detail["activate"]
              and "Несовместима" in inc_detail["reason"], label,
              "у несовместимой версии нет честной причины: %r" % (inc_detail,))
        page.click("[data-pv-panel-back]")
        page.wait_for_selector("[data-prompt-history-versions]",
                               state="visible")
    # События активации — ТОЛЬКО во вторичном «Истории действий» (PVR-02.1/
    # PVR-02.2/C1.2): в основном списке событий нет, статус события —
    # «была применена», своей кнопки «Применить» у событий нет.
    main_list_events = page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'[data-prompt-history-versions] [data-pv-row]'))"
        ".filter((el) => !el.getAttribute('data-prompt-history-revision'))"
        ".length")
    check(main_list_events == 0, label,
          "в основном списке есть строки-события журнала: %d"
          % main_list_events)
    page.click("[data-pv-events-toggle]")
    page.wait_for_selector("[data-pv-events]", state="visible")
    page.wait_for_timeout(200)
    ev = page.evaluate(
        "() => { const block = document.querySelector('[data-pv-events]');"
        " const rows = Array.from(block.querySelectorAll('[data-pv-event-row]'));"
        " return {count: rows.length,"
        " statuses: rows.map((el) => el.getAttribute('data-pv-event-status')),"
        " activateButtons: block.querySelectorAll('[data-pv-row-activate]').length,"
        " baselineButtons: block.querySelectorAll('[data-pv-row-baseline]').length,"
        " text: (block.textContent || '').replace(/\\s+/g, ' ').trim()}; }")
    check(ev["count"] >= 3, label,
          "в «Истории действий» нет событий активации: %r" % (ev,))
    check(all(s != "active" for s in ev["statuses"]), label,
          "МУТАЦИЯ: событие помечено active в списке действий: %r"
          % (ev["statuses"],))
    check(ev["activateButtons"] == 0 and ev["baselineButtons"] == 0, label,
          "у событий есть свои кнопки применения/назначения: %r" % (ev,))
    check("была применена" in ev["text"], label,
          "статус события «была применена» не показан: %r" % (ev["text"][:200],))
    if width <= 430:
        assert_touch_targets(page, label, "events")
    page.click("[data-pv-events-toggle]")
    page.wait_for_timeout(200)

    # 5b) Честность тонкого списка событий применения (PVR-02.2): пока сервер
    # сообщает `activations_page.has_more`, «Применений этой версии в журнале
    # нет» было бы ложью — более ранние события просто не загружены.
    STATE["activations_more"] = True
    page.click("[data-pv-panel-close]")
    page.wait_for_timeout(250)
    open_panel(page)
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
    open_row_detail(page, 2)
    page.wait_for_selector("[data-pv-detail-events]", state="visible")
    ev_empty = page.evaluate(
        "() => { const box = document.querySelector('[data-pv-detail-events]');"
        " const empty = box && box.querySelector('[data-pv-detail-events-empty]');"
        " const more = box && box.querySelector"
        "   ('[data-pv-detail-load-more-events]');"
        " return {text: (empty ? empty.textContent : '')"
        "   .replace(/\\s+/g, ' ').trim(),"
        " more: !!more,"
        " rows: box ? box.querySelectorAll"
        "   ('[data-pv-detail-event-row]').length : -1}; }")
    check(ev_empty["rows"] == 0, label,
          "у rev-003 неожиданно есть события применения: %r" % (ev_empty,))
    check("Применений этой версии в журнале нет" not in ev_empty["text"], label,
          "при непрочитанных страницах событий утверждается, что применений "
          "нет: %r" % (ev_empty["text"],))
    check("более ранние события" in ev_empty["text"]
          and "ещё не" in ev_empty["text"], label,
          "тонкий список событий не говорит, что загружены не все: %r"
          % (ev_empty["text"],))
    check(ev_empty["more"], label,
          "при непрочитанных событиях нет кнопки догрузки: %r" % (ev_empty,))
    page.click("[data-pv-panel-back]")
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
    STATE["activations_more"] = False

    # 6) «Применить» из деталей (PVR-04.2.4): server-confirmed, не оптимистично
    target_rev = row_rev(page, 4)
    open_row_detail(page, 4)
    page.wait_for_selector("[data-pv-detail-actions]", state="visible")
    if width <= 430:
        # PVR-04.3.1: на мобильном главный CTA живёт в фиксированном футере,
        # целиком в вьюпорте и ни чем не перекрыт.
        cta = page.evaluate(
            "() => { const b = document.querySelector('[data-pv-row-activate]');"
            " if (!b) return null; const r = b.getBoundingClientRect();"
            " const hit = document.elementFromPoint((r.left + r.right) / 2,"
            " (r.top + r.bottom) / 2);"
            " return {top: r.top, bottom: r.bottom,"
            " inView: r.top >= 0 && r.bottom <= window.innerHeight,"
            " hits: !!(hit && (b === hit || b.contains(hit)))}; }")
        check(cta and cta["inView"] and cta["hits"], label,
              "мобильный CTA деталей вне вьюпорта или перекрыт: %r" % (cta,))
    page.click("[data-pv-row-activate]")
    page.wait_for_timeout(1200)
    activated = [p for p in STATE["posts"] if p["path"].endswith("/activate")]
    check(activated and activated[-1]["body"].get("revision_id") == target_rev,
          label, "активация не отправлена/не тем revision_id: %r" % (activated,))
    # B4 (§2.2 п.6/§6 п.8): подтверждение успеха переживает перечитывание
    # состояния (`resetPanel` по reloadToken не имеет права его стирать).
    page.wait_for_timeout(1500)
    result_after_refresh = page.evaluate(
        "() => { const el = document.querySelector('[data-prompt-history-result]');"
        " return el ? (el.textContent || '').replace(/\\s+/g, ' ').trim() : ''; }")
    check("Сервер подтвердил" in result_after_refresh, label,
          "подтверждение «Применить» стёрто перечитыванием: %r"
          % (result_after_refresh,))
    # B4: подтверждение должно быть ВИДНО (геометрией), не просто текстом.
    # PVR-04.2.4: после «Применить» экран деталей закрывается — пользователь
    # возвращается к списку, где виден новый активный маркер, а подтверждение
    # сервера остаётся прилипшим к верху тела панели.
    assert_result_visible(page, label, "библиотека/применить")
    shot_view(page, shots, "result_library_%s" % label)
    dclosed = page.evaluate(
        "() => ({detail: !!document.querySelector('[data-pv-detail]'),"
        " list: !!document.querySelector('[data-prompt-history-versions]'),"
        " back: !!document.querySelector('[data-pv-panel-back]'),"
        " result: ((document.querySelector('[data-prompt-history-result]') || {})"
        "   .textContent || '').replace(/\\s+/g, ' ').trim()})")
    check(not dclosed["detail"] and dclosed["list"] and not dclosed["back"],
          label,
          "после «Применить» экран деталей не закрылся / не вернулся список: %r"
          % (dclosed,))
    check("Сервер подтвердил" in dclosed["result"], label,
          "подтверждение «Применить» не видно в вернувшемся списке: %r"
          % (dclosed["result"],))
    # Активная версия перечитана с сервера — проверяем в списке (PVR-04.2.3).
    after = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
        ".filter((el) => el.getAttribute('data-pv-status') === 'active')"
        ".map((el) => el.getAttribute('data-prompt-history-revision'))")
    check(target_rev in after, label,
          "после активации активная версия не перечитана с сервера: %r" % (after,))
    assert_result_sticky(page, label, "библиотека/применить")
    check(page.evaluate(
        "() => { const el = document.querySelector('[data-prompt-history-result]');"
        " const b = el && el.querySelector('[data-pv-result-dismiss]');"
        " if (!b) return false; b.click(); return true; }"), label,
        "у подтверждения нет явной кнопки закрытия")
    page.wait_for_timeout(200)
    check(page.evaluate(
        "() => !document.querySelector('[data-prompt-history-result]')"), label,
        "кнопка × не убрала подтверждение")

    # 7) «Назначить базовой» из меню «Действия» (PVR-04.2.4) не меняет
    #    действующий текст
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
    open_row_detail(page, 5)
    page.wait_for_selector("[data-pv-detail-actions]", state="visible")
    page.click("[data-pv-actions-toggle]")
    page.wait_for_selector("[data-pv-actions-menu]", state="visible")
    page.click("[data-pv-row-baseline]")
    page.wait_for_timeout(900)
    result = page.evaluate(
        "() => ((document.querySelector('[data-prompt-history-result]') || {})"
        ".textContent || '').trim()")
    check("Базовая версия изменена, действующий текст пока прежний" in result,
          label, "нет честного сообщения о назначении базовой: %r" % (result,))
    # B4: следующее действие заменяет прежнее сообщение и остаётся видимым.
    assert_result_visible(page, label, "библиотека/назначить базовой")
    shot_view(page, shots, "result_baseline_%s" % label)
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
    page.click("[data-pv-panel-back]")
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
    active_after = page.evaluate(
        "() => { const el = document.querySelector('[data-pv-row]"
        "[data-pv-status=\"active\"]');"
        " return el ? el.getAttribute('data-prompt-history-revision') : ''; }")
    check(active_after == active_before and active_after != baseline_rev,
          label,
          "назначение базовой сменило активную ревизию: %r -> %r"
          % (active_before, active_after))

    # 8) снятие назначения и восстановление базовой (футер списка)
    page.click("[data-pv-clear-baseline]")
    page.wait_for_timeout(700)
    check(any(p["method"] == "DELETE" and p["path"].endswith("/baseline")
              for p in STATE["posts"]), label, "DELETE /baseline не отправлен")
    open_row_detail(page, 5)
    page.wait_for_selector("[data-pv-detail-actions]", state="visible")
    page.click("[data-pv-actions-toggle]")
    page.wait_for_selector("[data-pv-actions-menu]", state="visible")
    page.click("[data-pv-row-baseline]")
    page.wait_for_timeout(800)
    page.click("[data-pv-panel-back]")
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
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

    # 10) «Скопировать в глобальные» из меню «Действия» в чатовой области
    open_row_detail(page, 5)
    page.wait_for_selector("[data-pv-detail-actions]", state="visible")
    page.click("[data-pv-actions-toggle]")
    page.wait_for_selector("[data-pv-actions-menu]", state="visible")
    copied = page.evaluate(
        "() => { const b = document.querySelector('[data-pv-row-copy-global]');"
        " if (!b) return false; b.click(); return true; }")
    check(copied, label, "кнопки «Скопировать в глобальные» нет в чатовой области")
    page.wait_for_timeout(900)
    check(any(p["path"].endswith("/copy-to-global") for p in STATE["posts"]),
          label, "POST /copy-to-global не отправлен")
    page.click("[data-pv-panel-back]")
    page.wait_for_timeout(200)

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

    # 12) журнал недоступен: честный 503-текст (PVR-05.2), черновик остаётся
    # 12a) перечитывание из ОТКРЫТОГО экрана деталей: списочные действия
    # («Вернуть исходную из кода») не всплывают под экраном деталей.
    open_panel(page)
    page.wait_for_selector("[data-prompt-history-versions]", state="visible")
    open_row_detail(page, 1)
    page.wait_for_selector("[data-pv-detail]", state="visible")
    STATE["journal_down"] = True
    page.evaluate(
        "() => { const b = document.querySelector('[data-prompt-history-toggle]');"
        " if (b) b.click(); }")
    page.wait_for_selector("[data-pv-panel-error]", state="visible")
    refetch = page.evaluate(
        "() => ({error: ((document.querySelector('[data-pv-panel-error]') || {})"
        "   .textContent || '').replace(/\\s+/g, ' ').trim(),"
        " back: !!document.querySelector('[data-pv-panel-back]'),"
        " listFoot: !!document.querySelector('[data-pv-panel-actions]'),"
        " factory: !!document.querySelector('[data-pv-factory-restore]'),"
        " activate: document.querySelectorAll('[data-pv-row-activate]').length})")
    check("История временно недоступна" in refetch["error"], label,
          "503 при перечитывании из деталей не назван честно: %r" % (refetch,))
    check(refetch["back"], label,
          "из экрана деталей при 503 нельзя вернуться («Назад» пропал): %r"
          % (refetch,))
    check(not refetch["factory"] and not refetch["listFoot"], label,
          "при 503 списочный футер («Вернуть исходную из кода») всплыл под "
          "экраном деталей: %r" % (refetch,))
    check(refetch["activate"] == 0, label,
          "при недоступном журнале рисуются кнопки действий")
    page.click("[data-pv-panel-back]")
    page.wait_for_timeout(250)
    page.click("[data-pv-panel-close]")
    STATE["journal_down"] = False
    # 12b) тот же 503, но из списочного состояния (каноничная метка).
    STATE["journal_down"] = True
    page.click("[data-prompt-history-toggle]")
    page.wait_for_selector("[data-pv-panel-error]", state="visible")
    err = page.evaluate(
        "() => ((document.querySelector('[data-pv-panel-error]') || {})"
        ".textContent || '').trim()")
    check("История временно недоступна" in err, label,
          "503 журнала не показан каноничной меткой PVR-05.2: %r" % (err,))
    check("журнал версий недоступен" in err, label,
          "причина недоступности потеряна: %r" % (err,))
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

    # B4 + честное перечитывание: «Применить» из деталей меняет серверный
    # текст, редактор перечитывает раздел, а сообщение сервера остаётся видимым.
    target = row_rev(page, 0)
    open_row_detail(page, 0)
    page.wait_for_selector("[data-pv-detail-actions]", state="visible")
    page.click("[data-pv-row-activate]")
    page.wait_for_timeout(1800)
    res = page.evaluate(
        "() => ((document.querySelector('[data-prompt-history-result]') || {})"
        ".textContent || '').replace(/\\s+/g, ' ').trim()")
    check("Сервер подтвердил" in res, label,
          "подтверждение «Применить» в «Характере» не видно после "
          "перечитывания: %r" % (res,))
    # B4: то же самое, но геометрией — блок обязан быть в видимой области
    # тела панели при scrollTop=0. PVR-04.2.4: после «Применить» экран
    # деталей закрывается, панель возвращается к списку с подтверждением.
    assert_result_visible(page, label, "характер/применить")
    shot_view(page, shots, "result_speech_%s" % label)
    sclosed = page.evaluate(
        "() => ({detail: !!document.querySelector('[data-pv-detail]'),"
        " list: !!document.querySelector('[data-prompt-history-versions]'),"
        " result: ((document.querySelector('[data-prompt-history-result]') || {})"
        "   .textContent || '').replace(/\\s+/g, ' ').trim()})")
    check(not sclosed["detail"] and sclosed["list"]
          and "Сервер подтвердил" in sclosed["result"], label,
          "после «Применить» в «Характере» экран деталей не закрылся или "
          "подтверждение потерялось: %r" % (sclosed,))
    assert_result_sticky(page, label, "характер/применить")
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


def run_catalog_readonly(label, page, shots):
    """PVR-04.1.4: промпт ИЗ КОДА — честный read-only статус с причиной.

    Каталог монтирует тот же компонент с `variant="history"` и
    `can-edit=false`; раньше баннер рисовался только в `variant="card"`,
    поэтому на этой поверхности честного статуса не было вовсе.
    """
    STATE["code_only"] = True
    try:
        page.goto(BASE + "/#/ai/prompts", wait_until="load")
        page.wait_for_selector("header.header-sticky", state="visible")
        page.wait_for_timeout(700)
        page.wait_for_selector("[data-prompt-catalog-toggle]", state="visible")
        page.click("[data-prompt-catalog-toggle]")
        page.wait_for_selector("[data-prompt-catalog-key='%s']" % PROMPT_KEY,
                               state="visible")
        page.click("[data-prompt-catalog-key='%s']" % PROMPT_KEY)
        page.wait_for_function(
            "() => { const b = document.querySelector("
            "'[data-prompt-catalog-history]');"
            " const ro = b && b.querySelector('[data-pv-readonly]');"
            " return !!(ro && /задаётся кодом/.test(ro.textContent || '')); }",
            timeout=10000)
        info = page.evaluate(r"""
            () => {
              const box = document.querySelector('[data-prompt-catalog-history]');
              const ro = box && box.querySelector('[data-pv-readonly]');
              const r = ro ? ro.getBoundingClientRect() : null;
              const st = ro ? getComputedStyle(ro) : null;
              const saves = box
                ? Array.from(box.querySelectorAll('[data-pv-save]')) : [];
              return {
                text: ro ? (ro.textContent || '').replace(/\s+/g, ' ').trim() : '',
                visible: !!(r && r.width > 0 && r.height > 0 && st
                  && st.display !== 'none' && st.visibility !== 'hidden'),
                saves: saves.length,
                enabledSaves: saves.filter((b) => !b.disabled).length,
                textareas: box ? box.querySelectorAll('textarea').length : -1,
                card: box ? !!box.querySelector('[data-prompt-history]') : false,
              };
            }
        """)
        check(info["card"], label, "карточка версий в каталоге не отрисована")
        check(info["visible"], label,
              "read-only статус с причиной не виден в каталоге: %r" % (info,))
        check("Только чтение" in info["text"], label,
              "нет статуса «Только чтение»: %r" % (info["text"],))
        check("задаётся кодом" in info["text"], label,
              "причина read-only не называет код: %r" % (info["text"],))
        check(info["saves"] == 0 and info["enabledSaves"] == 0, label,
              "при read-only доступно сохранение: %r" % (info,))
        check(info["textareas"] == 0, label,
              "read-only промпт показан активным полем ввода: %r" % (info,))
        shot(page, shots, "catalog_readonly_%s" % label)
    finally:
        STATE["code_only"] = False


def run_tz_unavailable(label, page, shots):
    """PVR-04.2.3: без пояса чата время честно НЕ печатается UTC-цифрами."""
    STATE["tz_fallback"] = True
    try:
        open_prompt_editor(page)
        open_panel(page, wait_times=False)
        page.wait_for_selector("[data-pv-panel-tz-unavailable]",
                               state="visible", timeout=10000)
        info = page.evaluate(r"""
            () => {
              const rows = Array.from(document.querySelectorAll('[data-pv-row]'));
              const names = rows.slice(0, 3).map((el) => (
                (el.querySelector('.pv-row__name') || {}).textContent || ''
              ).replace(/\s+/g, ' ').trim());
              return {
                rows: rows.length,
                names: names,
                times: names.filter((n) => /\d{2}\.\d{2} \d{2}:\d{2}/.test(n)),
                note: ((document.querySelector('[data-pv-panel-tz-unavailable]')
                  || {}).textContent || '').trim(),
                saved: !!document.querySelector('[data-pv-saved]'),
                cardNote: ((document.querySelector('[data-pv-tz-unavailable]')
                  || {}).textContent || '').trim(),
              };
            }
        """)
        check(info["rows"] > 0, label, "панель без строк — проверка пуста")
        check(info["times"] == [], label,
              "без пояса чата время нарисовано UTC-цифрами: %r"
              % (info["times"],))
        check("пояс чата недоступен" in info["note"], label,
              "нет честной метки недоступности пояса в панели: %r"
              % (info["note"],))
        check("пояс чата недоступен" in info["cardNote"], label,
              "нет честной метки недоступности пояса в карточке: %r"
              % (info["cardNote"],))
        check(not info["saved"], label,
              "«Сохранено …» показано без известного пояса чата")
        shot(page, shots, "tz_unavailable_%s" % label)
    finally:
        STATE["tz_fallback"] = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--port", type=int, default=0)
    # Кандидат, на котором реально прогнан сьют: отчёт обязан называть SHA,
    # иначе доказательство нельзя привязать к проверенному дереву.
    ap.add_argument("--candidate", default="")
    args, _ = ap.parse_known_args()

    global PORT, BASE
    if args.port:
        PORT = args.port
        BASE = "http://127.0.0.1:%d" % PORT
    STATE["revisions"] = build_revisions()
    STATE["activations"] = build_activations()
    serve_static(PORT, os.path.abspath(args.webroot))
    print("[pvr-s4-e2e] webroot = %s" % os.path.abspath(args.webroot))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # PVR-04.1: владелец назвал desktop 1536/1366/768 и mobile 390/360
        # (+ рабочие 1440/320) — матрица обязана их содержать.
        matrix = [(1536, 960, "1536"), (1440, 900, "1440"),
                  (1366, 768, "1366"), (768, 1024, "768"),
                  (390, 844, "390"), (360, 780, "360"), (320, 780, "320")]
        for width, height, label in matrix:
            DIALOGS.clear()
            CONSOLE_ERRORS.clear()
            STATE["posts"] = []
            STATE["gets"] = []
            STATE["tz_requests"] = []
            STATE["active"] = "rev-002"
            # Свежий журнал на каждый сценарий: статусы не тащат мутации
            # предыдущей ширины (остальное пересобирает /activate).
            STATE["revisions"] = build_revisions()
            STATE["activations"] = build_activations()
            STATE["baseline"] = None
            STATE["factory_restored"] = False
            STATE["journal_down"] = False
            STATE["activations_more"] = False
            STATE["code_only"] = False
            STATE["tz_fallback"] = False
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
                # PVR-04.1.4: read-only статус на поверхности каталога
                # (variant="history", can-edit=false, промпт из кода).
                if width == 1440:
                    run_catalog_readonly(label, page, args.shots)
                # PVR-04.2.3: честная деградация без пояса чата.
                if width == 390:
                    run_tz_unavailable(label, page, args.shots)
                check(hscroll(page) <= 1, label,
                      "горизонтальный скролл итог: %d px" % hscroll(page))
                check(not CONSOLE_ERRORS, label,
                      "ошибки консоли/страницы: %r" % (CONSOLE_ERRORS[:5],))
                mine = MEASURE.setdefault(label, {})
                mine["hscroll"] = hscroll(page)
                mine["tz_requests"] = len(STATE["tz_requests"])
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
        # Путь к снимкам — относительно корня репозитория, чтобы отчёт
        # оставался читаемым вне конкретной машины.
        shots_ref = ""
        if args.shots:
            try:
                shots_ref = os.path.relpath(os.path.abspath(args.shots),
                                            REPO).replace("\\", "/")
            except ValueError:  # другой диск/корень
                shots_ref = os.path.abspath(args.shots)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"candidate": args.candidate,
                       "widths": [m[2] for m in matrix],
                       "shots_dir": shots_ref,
                       "failures": failures, "notes": notes,
                       "measure": MEASURE}, fh,
                      ensure_ascii=False, indent=2)
    if failures:
        sys.exit(1)
    print("PVR-S4-OK")


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright  # noqa: F401
    main()
