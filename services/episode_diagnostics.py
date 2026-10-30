"""EVOL-021 — «истории памяти»: что бот реально помнит об эпизодах.

Наблюдение владельца (plans/current_task.md, EVOL-021): лента показывает
десятки заголовков «Не удалось восстановить сюжет», при этом записи помечены
«новая история», содержат диапазон старых событий, момент обнаружения и
десятки участников; в деталях — «Эпизод 1780282318», «исход неизвестен»,
«Исходных сообщений: 200+». Администратор не понимает, что произошло и зачем
эта история нужна.

Принцип этого модуля:

* **история** = эпизод с подтверждённым описанием того, что происходило.
  Незавершённые/нечитаемые записи остаются в архиве, но НЕ выдаются за
  готовую «новую историю»: они уходят в отдельную группу «Требуют
  восстановления» с настоящей причиной и числом затронутых записей;
* техническая заглушка («Эпизод 1780…») никогда не переименовывается в
  красивый заголовок: заголовок берётся только из фактически доступного
  контекста, иначе `title = None` + честный статус;
* старые эпизоды, впервые обнаруженные сегодня, помечаются `discovered`
  («обнаружено»), а НЕ как событие сегодняшнего дня;
* ни одного нового LLM-вызова на открытие витрины: только чтение
  существующих строк (`mca_episodes`, `mca_stories`,
  `mca_story_episode_links`, прогресс уже существующих процессов);
* два чата изолированы: каждый запрос фильтруется по `chat_id`.

UI-слой (роут/лента/карточка) — отдельная полоса: здесь только данные.
"""
from __future__ import annotations

import logging
import time

from services import mca_episodes as me

logger = logging.getLogger(__name__)

#: Статусы полноты эпизода (закрытый набор).
COMPLETENESS_READY = "ready"
COMPLETENESS_PARTIAL = "partial"
COMPLETENESS_EMPTY = "empty"

COMPLETENESS_LABELS = {
    COMPLETENESS_READY: "Сюжет восстановлен",
    COMPLETENESS_PARTIAL: "Сюжет восстановлен частично",
    COMPLETENESS_EMPTY: "Сюжет не восстановлен",
}

#: Статусы группы «Требуют восстановления».
RECOVERY_UNRECOVERABLE = "unrecoverable"
RECOVERY_PENDING = "pending_rebuild"

#: Причины незавершённости — по фактическим полям строки, не по догадке.
REASON_NO_SOURCE_MESSAGES = "no_source_messages"
REASON_NO_SUBSTANTIVE_TEXT = "no_substantive_text"
REASON_SUMMARY_NOT_BUILT = "summary_not_built"
REASON_TITLE_STUB_ONLY = "title_stub_only"

REASON_LABELS = {
    REASON_NO_SOURCE_MESSAGES: (
        "Нет связанных исходных сообщений: ключи источников не сохранены"),
    REASON_NO_SUBSTANTIVE_TEXT: (
        "Исходники есть, но содержательный текст не восстановлен"),
    REASON_SUMMARY_NOT_BUILT: (
        "Исходники есть — сюжет ещё не собран (ожидает пересборки)"),
    REASON_TITLE_STUB_ONLY: (
        "Вместо заголовка только техническая заглушка"),
}

#: Метки происхождения даты: событие vs обнаружение (EVOL-021 §данные).
DISCOVERY_TODAY = "new_event_today"
DISCOVERY_OLD_EVENT = "discovered_old_event"
DISCOVERY_ARCHIVE = "archive"
DISCOVERY_LABELS = {
    DISCOVERY_TODAY: "Событие сегодня",
    DISCOVERY_OLD_EVENT: "Обнаружено сегодня (событие ранее)",
    DISCOVERY_ARCHIVE: "Архив",
}

_DAY = 86400
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_PRIMARY_PARTICIPANTS = me.PRIMARY_PARTICIPANTS_MAX
_WHAT_HAPPENED_MAX = 240
_TITLE_MAX = 160


def _now(now: int | None) -> int:
    return int(time.time()) if now is None else int(now)


def _opt_ts(value):
    """0/мусор → None (честное «нет данных», а не 1970)."""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None


def _clean(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


async def _fetch_all(db, sql: str, params=()) -> list[dict]:
    cursor = await db.db.execute(sql, params)
    return [dict(r) for r in await cursor.fetchall()]


async def _story_context(db, episode_ids: list[str]) -> dict[str, dict]:
    """Связь эпизод → истории + их проверка/доступность (одна выборка на
    страницу, без N+1). Ошибка чтения → пустая карта (честное «не связано»)."""
    ids = [str(e) for e in (episode_ids or ()) if e][:400]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    try:
        links = await _fetch_all(
            db,
            "SELECT episode_id, story_id, order_no FROM "
            f"mca_story_episode_links WHERE episode_id IN ({placeholders}) "
            "ORDER BY order_no",
            tuple(ids))
    except Exception:
        logger.warning("[episode_diag] links недоступны", exc_info=True)
        return {}
    story_ids = [str(r.get("story_id")) for r in links if r.get("story_id")]
    stories: dict[str, dict] = {}
    if story_ids:
        marks = ",".join("?" * len(story_ids))
        try:
            rows = await _fetch_all(
                db,
                "SELECT story_id, title, summary, state, verification, "
                "excluded_from_retrieval FROM mca_stories "
                f"WHERE story_id IN ({marks})",
                tuple(story_ids))
            stories = {str(r.get("story_id")): r for r in rows}
        except Exception:
            logger.warning("[episode_diag] stories недоступны", exc_info=True)
            stories = {}
    out: dict[str, dict] = {}
    for link in links:
        episode_id = str(link.get("episode_id") or "")
        story_id = str(link.get("story_id") or "")
        if not episode_id:
            continue
        out.setdefault(episode_id, {"story_ids": []})["story_ids"].append(
            story_id)
    for episode_id, info in out.items():
        ids_for_episode = info.get("story_ids") or []
        primary = stories.get(ids_for_episode[0]) if ids_for_episode else {}
        info["story"] = primary or {}
        info["story_count"] = len(ids_for_episode)
    return out


def _participants(row: dict) -> tuple[list[str], int]:
    people = [str(p).strip() for p in
              (me._json_loads(row.get("participants_json"), []) or [])
              if str(p or "").strip()]
    primary = people[:_PRIMARY_PARTICIPANTS]
    return primary, max(0, len(people) - len(primary))


def _claims(row: dict) -> list[dict]:
    claims = me._json_loads(row.get("claims_json"), [])
    return [c for c in claims if isinstance(c, dict)
            and str(c.get("text") or "").strip()]


def _message_keys(row: dict) -> list[str]:
    keys = me._json_loads(row.get("message_keys_json"), [])
    return [str(k) for k in keys if str(k or "").strip()]


def _title_of(row: dict, claims: list[dict]) -> tuple[str | None, str]:
    """Заголовок ТОЛЬКО из фактического контекста.

    Порядок: человеческий заголовок строки → первый содержательный claim.
    Техническая цифровая заглушка («Эпизод 1780…») заголовком не считается.
    Нет контекста → `None` (витрина покажет честный статус, не выдумку)."""
    raw = _clean(row.get("title"), _TITLE_MAX)
    if raw and not me.is_auto_stub_title(raw):
        return raw, "pipeline"
    for claim in claims:
        text = _clean(claim.get("text"), _TITLE_MAX)
        if text:
            return text, "first_claim"
    return None, "none"


def _what_happened(row: dict, claims: list[dict]) -> tuple[str | None, str]:
    """1–2 строки «что произошло» из восстановленного сюжета/утверждений."""
    summary = ""
    if me.episode_content_status(row) == me.CONTENT_READY:
        summary = _clean(row.get("summary"), _WHAT_HAPPENED_MAX)
    if summary:
        return summary, "summary"
    if claims:
        joined = "; ".join(_clean(c.get("text"), 90) for c in claims[:3])
        return _clean(joined, _WHAT_HAPPENED_MAX), "claims"
    return None, "none"


def _completeness(row: dict, claims: list[dict], keys: list[str]) -> str:
    if me.episode_content_status(row) == me.CONTENT_READY and claims:
        return COMPLETENESS_READY
    if claims or keys:
        return COMPLETENESS_PARTIAL
    return COMPLETENESS_EMPTY


def _recovery_reason(row: dict, claims: list[dict], keys: list[str],
                     completeness: str, title: str | None) -> str | None:
    """Настоящая причина незавершённости (None — эпизод полноценный)."""
    if completeness == COMPLETENESS_READY and title:
        return None
    if not keys:
        return REASON_NO_SOURCE_MESSAGES
    if not claims:
        return REASON_SUMMARY_NOT_BUILT
    if not title:
        return REASON_TITLE_STUB_ONLY
    if completeness != COMPLETENESS_READY:
        return REASON_NO_SUBSTANTIVE_TEXT
    return None


def _discovery_kind(row: dict, now: int) -> str:
    """Событие было сегодня — или эпизод просто обнаружен сегодня."""
    end = _opt_ts(row.get("event_end_ts")) or _opt_ts(row.get("event_start_ts"))
    discovered = _opt_ts(row.get("discovered_at"))
    if end and end >= now - _DAY:
        return DISCOVERY_TODAY
    if discovered and discovered >= now - _DAY:
        return DISCOVERY_OLD_EVENT
    return DISCOVERY_ARCHIVE


def _period(row: dict) -> dict:
    start = _opt_ts(row.get("event_start_ts"))
    end = _opt_ts(row.get("event_end_ts"))
    return {"start": start, "end": end,
            "known": bool(start or end),
            "label": ("период не определён" if not (start or end) else None)}


def _verification(row: dict, story_ctx: dict) -> dict:
    """Проверка — только если есть связанная история с реальным состоянием."""
    story = (story_ctx or {}).get("story") or {}
    if not story:
        return {"status": "not_linked", "source": "none",
                "label": "Не связано с историей — не проверено"}
    verification = str(story.get("verification") or "unknown")
    state = str(story.get("state") or "")
    labels = {"verified": "История проверена",
              "tentative": "История предварительная",
              "unknown": "Проверка истории не выполнялась"}
    return {"status": verification, "state": state, "source": "story",
            "label": labels.get(verification, "Состояние проверки неизвестно")}


def episode_summary(row: dict, *, story_ctx: dict | None = None,
                    now: int | None = None) -> dict:
    """Компактная семантическая карточка эпизода (без raw JSON)."""
    ts = _now(now)
    claims = _claims(row)
    keys = _message_keys(row)
    completeness = _completeness(row, claims, keys)
    title, title_source = _title_of(row, claims)
    happened, happened_source = _what_happened(row, claims)
    primary, others = _participants(row)
    reason = _recovery_reason(row, claims, keys, completeness, title)
    story = (story_ctx or {}).get("story") or {}
    discovery_kind = _discovery_kind(row, ts)
    return {
        "episode_id": str(row.get("episode_id") or ""),
        "chat_id": int(row.get("chat_id") or 0),
        "title": title,
        "title_source": title_source,
        "what_happened": happened,
        "what_happened_source": happened_source,
        "event_period": _period(row),
        "discovered_at": _opt_ts(row.get("discovered_at")),
        "processed_at": _opt_ts(row.get("updated_at")),
        "discovery_kind": discovery_kind,
        "discovery_label": DISCOVERY_LABELS[discovery_kind],
        "participants": {"primary": primary, "others_count": others,
                         "count": len(primary) + others},
        "participants_coherence": {
            "state": "unknown",
            "note": ("Авторство исходных сообщений по ключам не "
                     "восстанавливается — связность участников не проверена"),
        },
        "linked_messages": {
            "count": len(keys),
            "known": bool(keys),
            "capped": len(keys) >= 200,
            "label": (f"исходных сообщений: {len(keys)}" if keys
                      else "исходные сообщения не сохранены"),
        },
        "claims_count": len(claims),
        "completeness": completeness,
        "completeness_label": COMPLETENESS_LABELS[completeness],
        "verification": _verification(row, story_ctx or {}),
        "story": {
            "linked": bool(story),
            "story_id": str(story.get("story_id") or "") or None,
            "count": int((story_ctx or {}).get("story_count") or 0),
            "title": _clean(story.get("title"), _TITLE_MAX) or None,
            "excluded_from_retrieval": bool(
                story.get("excluded_from_retrieval")),
        },
        "retrievable": (None if not story else
                        not bool(story.get("excluded_from_retrieval"))),
        "needs_recovery": reason is not None,
        "recovery": (None if reason is None else {
            "status": (RECOVERY_PENDING
                       if reason in (REASON_SUMMARY_NOT_BUILT,
                                     REASON_TITLE_STUB_ONLY)
                       else RECOVERY_UNRECOVERABLE),
            "reason": reason,
            "reason_label": REASON_LABELS.get(reason, ""),
        }),
    }


async def _last_build(db, chat_id: int) -> dict:
    """Последняя сборка эпизодов/backfill — из существующих процессов.

    Источник — уже опубликованный Витриной прогресс (`web_stories.
    stories_summary`): второй агрегатор состояний не создаётся."""
    try:
        from services import web_stories
        summary = await web_stories.stories_summary(db, int(chat_id))
        progress = summary.get("progress") or {}
        build = progress.get("episodes_build") or {}
        backfill = progress.get("episodes_backfill") or {}
        return {
            "last_build_at": _opt_ts(build.get("last_ts")),
            "last_build_state": build.get("state"),
            "last_build_reason": build.get("last_reason"),
            "backfill_state": backfill.get("state"),
            "backfill_active": bool(backfill.get("active")),
            "backfill_updated_at": _opt_ts(backfill.get("updated_at")),
        }
    except Exception:
        logger.warning("[episode_diag] прогресс сборки недоступен",
                       exc_info=True)
        return {"last_build_at": None, "last_build_state": None,
                "last_build_reason": None, "backfill_state": None,
                "backfill_active": False, "backfill_updated_at": None}


async def episode_feed(db, chat_id: int, *, limit: int = _DEFAULT_LIMIT,
                       now: int | None = None) -> dict:
    """Лента готовых смысловых эпизодов + сводка группы восстановления.

    В ленту попадают ТОЛЬКО эпизоды с восстановленным описанием: пустые
    технические записи не маскируются под «новые истории» (они видны через
    `requires_recovery` и `recovery_group`)."""
    ts = _now(now)
    limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    try:
        rows = await me.EpisodeRepository(db).list_episodes(
            int(chat_id), limit=_MAX_LIMIT)
    except Exception:
        logger.warning("[episode_diag] эпизоды недоступны", exc_info=True)
        return {"scope": f"chat:{int(chat_id)}", "chat_id": int(chat_id),
                "state": "unavailable", "generated_at": ts, "items": [],
                "requires_recovery": None, "last_build": None,
                "message": "Эпизоды недоступны: чтение архива не удалось"}
    contexts = await _story_context(db, [r.get("episode_id") for r in rows])
    items: list[dict] = []
    recovery: list[dict] = []
    for row in rows:
        item = episode_summary(row, story_ctx=contexts.get(
            str(row.get("episode_id"))), now=ts)
        (recovery if item["needs_recovery"] else items).append(item)
    items.sort(key=lambda r: -(r["event_period"]["end"]
                               or r["discovered_at"] or 0))
    by_reason: dict[str, int] = {}
    for item in recovery:
        reason = str((item.get("recovery") or {}).get("reason") or "")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    state = "ok" if items else "empty"
    return {
        "scope": f"chat:{int(chat_id)}",
        "chat_id": int(chat_id),
        "generated_at": ts,
        "state": state,
        "items": items[:limit],
        "total_ready": len(items),
        "total_episodes": len(rows),
        "requires_recovery": {
            "count": len(recovery),
            "by_reason": [
                {"reason": reason, "reason_label": REASON_LABELS.get(reason,
                                                                    ""),
                 "count": count}
                for reason, count in sorted(by_reason.items(),
                                            key=lambda kv: -kv[1])
            ],
            "note": ("Незавершённые эпизоды сохранены, но не выдаются за "
                     "готовые истории; сюжет для них не выдумывается"),
        },
        "last_build": await _last_build(db, chat_id),
    }


async def recovery_group(db, chat_id: int, *, limit: int = _DEFAULT_LIMIT,
                         now: int | None = None) -> dict:
    """Группа «Требуют восстановления»: настоящая причина + затронутое число.

    Каждый элемент получает `status` (`unrecoverable` — восстановить нечего,
    `pending_rebuild` — исходники есть, сюжет ждёт пересборки) и причину.
    Никакого нового заголовка/сюжета здесь не создаётся."""
    ts = _now(now)
    limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    try:
        rows = await me.EpisodeRepository(db).list_episodes(
            int(chat_id), limit=_MAX_LIMIT)
    except Exception:
        logger.warning("[episode_diag] эпизоды недоступны", exc_info=True)
        return {"scope": f"chat:{int(chat_id)}", "chat_id": int(chat_id),
                "generated_at": ts, "state": "unavailable",
                "count": 0, "items": [], "by_reason": []}
    contexts = await _story_context(db, [r.get("episode_id") for r in rows])
    items: list[dict] = []
    for row in rows:
        item = episode_summary(row, story_ctx=contexts.get(
            str(row.get("episode_id"))), now=ts)
        if not item["needs_recovery"]:
            continue
        items.append({
            "episode_id": item["episode_id"],
            "chat_id": item["chat_id"],
            "status": item["recovery"]["status"],
            "reason": item["recovery"]["reason"],
            "reason_label": item["recovery"]["reason_label"],
            "event_period": item["event_period"],
            "discovered_at": item["discovered_at"],
            "discovery_kind": item["discovery_kind"],
            "linked_messages": item["linked_messages"],
            "completeness": item["completeness"],
            "completeness_label": item["completeness_label"],
            "title": item["title"],
        })
    by_reason: dict[str, dict] = {}
    for item in items:
        bucket = by_reason.setdefault(
            str(item["reason"]),
            {"reason": item["reason"],
             "reason_label": item["reason_label"],
             "status": item["status"], "count": 0})
        bucket["count"] += 1
    return {
        "scope": f"chat:{int(chat_id)}",
        "chat_id": int(chat_id),
        "generated_at": ts,
        "state": "ok" if items else "empty",
        "group": "requires_recovery",
        "group_label": "Требуют восстановления",
        "count": len(items),
        "by_reason": sorted(by_reason.values(), key=lambda b: -b["count"]),
        "items": items[:limit],
        "truncated": len(items) > limit,
        "note": ("Архив не удаляется; эпизоды остаются доступными в "
                 "технической диагностике. Новые сюжеты не генерируются."),
    }


async def episode_card(db, chat_id: int, episode_id: str,
                       now: int | None = None) -> dict | None:
    """Карточка ОДНОГО эпизода выбранного чата (не «общий каталог»).

    Возвращает `None`, если эпизод не найден ИЛИ принадлежит другому чату —
    изоляция чатов не зависит от вызывающего слоя."""
    ts = _now(now)
    try:
        row = await me.EpisodeRepository(db).get_episode(str(episode_id))
    except Exception:
        logger.warning("[episode_diag] эпизод недоступен", exc_info=True)
        return None
    if not row or int(row.get("chat_id") or 0) != int(chat_id):
        return None
    contexts = await _story_context(db, [row.get("episode_id")])
    item = episode_summary(row, story_ctx=contexts.get(str(episode_id)),
                           now=ts)
    item["generated_at"] = ts
    return item
