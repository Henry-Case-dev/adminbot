"""MCA-12 (round 10.46, ADR-1028-21 D2/§9) — read-сборщик DTO «Истории чата».

Тонкий слой поверх фасада mca-05 (`services/mca_episodes.py`, v21):

* счётчики — SQL-агрегаты `mca_stories` (репозиторий фасада);
* лента — read-проекция `mca_events` по story-типам §16.1 (прецедент
  инкрементальной доставки mca-17a `incident_changes`: cursor/dedup/bounded;
  НЕ второй канал телеметрии — CA-12-2);
* таблица — keyset-пагинация + фильтры (read-only методы репозитория);
* карточка — фасад + версии + хронология эпизодов + противоречия + оригинал;
* мутации — ПРЯМЫЕ вызовы методов фасада mca-05 (CAS `expected_version`), без
  собственной бизнес-логики (CA-12-1); события — только существующие эмиттеры
  mca-05 (`emit_story_event`), новых reason_code нет (D15).

R17/TH-4: наружу — названия, участники-ID, счётчики, статусы, даты; message-
контент и сырые логи не отдаются. Честные состояния: пусто/unknown/не
запускалось различимы, ноль только после успешного расчёта (TH-8).
"""
from __future__ import annotations

import logging
import time

from services import mca_episodes
from services.mca_episodes import (
    EpisodeRepository,
    effective_story,
    emit_story_event,
)

logger = logging.getLogger(__name__)

# §16.1: имена событий ленты фиксированы (контракт mca-05/mca-12).
STORY_EVENT_NAMES = (
    "story_discovered", "story_extended", "source_linked",
    "contradiction_found", "story_rebuilt",
)

#: Фиксированное окно счётчиков «новые/дополненные» (константа UI, не
#: настройка — Δ каталога = 0).
FEED_WINDOW_SECONDS = 24 * 3600

FEED_DEFAULT_LIMIT = 50
FEED_MAX_LIMIT = 200
TABLE_DEFAULT_LIMIT = 20

# Ретенция mca-13 (90d terminal) — лента bounded; честная пометка «история
# ограничена» когда страница выбрана до упора окна.
FEED_BOUNDED_LIMIT = FEED_DEFAULT_LIMIT

_TEXT_LIMIT = 200


def _now(now: int | None) -> int:
    return int(time.time()) if now is None else int(now)


def _json_loads(raw, default):
    return mca_episodes._json_loads(raw, default)


def _clip(value, limit: int = _TEXT_LIMIT) -> str:
    return str(value or "")[:limit]


# ── лента (read-проекция mca_events; cursor/dedup/bounded) ──────────────────

def _feed_item(row: dict, titles: dict[str, str]) -> dict:
    """Публичная форма события (TH-4/R17): refs/id/счётчики/даты, без
    message-контента; entity.summary ≤200 символов (emit_story_event)."""
    entity = _json_loads(row.get("entity_ids"), {})
    story_id = str(entity.get("story_id") or "")
    return {
        "id": int(row.get("id") or 0),
        "ts": int(row.get("ts") or 0),
        "event": str(row.get("event_name") or ""),
        "outcome": str(row.get("outcome") or ""),
        "reason_code": row.get("reason_code"),
        "story_id": story_id,
        "title": titles.get(story_id) or "",
        "text": _clip(entity.get("summary")),
        "episode_ids": [str(e) for e in
                        (entity.get("episode_ids") or ())][:20],
        # Обе даты (A11): период событий vs дата обнаружения.
        "event_start": entity.get("event_start"),
        "event_end": entity.get("event_end"),
        "discovered_at": entity.get("discovered_at"),
        "participants": [str(p) for p in
                         (entity.get("participants") or ())][:50],
    }


async def stories_feed(db, chat_id: int, *, cursor: int = 0,
                       limit: int = FEED_DEFAULT_LIMIT) -> dict:
    """Инкрементальная лента (D4): события строго `id > cursor` (монотонный
    курсор, дедуп по `event_id`); первая страница (cursor=0) — последние N
    (bounded, has_more — честная пометка «история ограничена»)."""
    limit = max(1, min(int(limit or FEED_DEFAULT_LIMIT), FEED_MAX_LIMIT))
    cursor = max(0, int(cursor or 0))
    placeholders = ",".join("?" * len(STORY_EVENT_NAMES))
    try:
        if cursor <= 0:
            sql = (f"SELECT * FROM mca_events WHERE chat_id = ? AND "
                   f"event_name IN ({placeholders}) "
                   "ORDER BY id DESC LIMIT ?")
            rows = await _fetch(db, sql,
                                (int(chat_id), *STORY_EVENT_NAMES, limit + 1))
            rows.reverse()
        else:
            sql = (f"SELECT * FROM mca_events WHERE chat_id = ? AND "
                   f"event_name IN ({placeholders}) AND id > ? "
                   "ORDER BY id ASC LIMIT ?")
            rows = await _fetch(db, sql,
                                (int(chat_id), *STORY_EVENT_NAMES,
                                 cursor, limit + 1))
    except Exception:
        logger.warning("[web_stories] feed read failed — fail-open",
                       exc_info=True)
        return {"enabled": True, "state": "unavailable", "chat_id": int(chat_id),
                "cursor": cursor, "events": [], "has_more": False}
    has_more = len(rows) > limit
    rows = rows[:limit]
    story_ids = [_entity_story_id(r) for r in rows]
    titles = await EpisodeRepository(db).stories_titles(story_ids)
    events = [_feed_item(r, titles) for r in rows]
    # Дедуп по id (защита от дублей на границе курсора) + монотонный курсор.
    seen: set[int] = set()
    deduped: list[dict] = []
    new_cursor = cursor
    for ev in events:
        if ev["id"] in seen or ev["id"] <= cursor:
            continue
        seen.add(ev["id"])
        deduped.append(ev)
        new_cursor = max(new_cursor, ev["id"])
    return {"enabled": True, "state": "ok", "chat_id": int(chat_id),
            "cursor": new_cursor, "events": deduped,
            "has_more": bool(has_more)}


def _entity_story_id(row: dict) -> str:
    entity = _json_loads(row.get("entity_ids"), {})
    return str(entity.get("story_id") or "")


async def _fetch(db, sql: str, params=()) -> list[dict]:
    """Read-only fetch (fail-open → исключение отдаётся вызывающему для
    честного `unavailable`; здесь — тонкая обёртка над курсором)."""
    cursor = await db.db.execute(sql, params)
    return [dict(r) for r in await cursor.fetchall()]


# ── счётчики + прогресс (D5) ────────────────────────────────────────────────

async def _feed_window_counts(db, chat_id: int, since: int) -> dict:
    placeholders = ",".join("?" * len(STORY_EVENT_NAMES))
    rows = await _fetch(
        db, f"SELECT event_name, COUNT(*) AS c FROM mca_events WHERE "
            f"chat_id = ? AND event_name IN ({placeholders}) AND ts >= ? "
            "GROUP BY event_name",
        (int(chat_id), *STORY_EVENT_NAMES, int(since)))
    by_name = {str(r["event_name"]): int(r["c"]) for r in rows}
    return {"new": by_name.get("story_discovered", 0),
            "extended": by_name.get("story_extended", 0),
            "contradictions": by_name.get("contradiction_found", 0)}


async def _build_progress(db, chat_id: int) -> dict:
    """Видимый прогресс архивной обработки и последнее состояние (D5):
    read-рендер статусов существующих процессов `episodes.build` (события
    `episodes_build` mca-17a/mca-05) и `episodes.backfill` (durable
    `task_jobs` mca-01; `backfill_status_from_job` — контракт для mca-12)."""
    build = {"state": "not_run", "last_ts": None, "last_outcome": None,
             "last_reason": None}
    try:
        rows = await _fetch(
            db, "SELECT ts, outcome, reason_code FROM mca_events WHERE "
                "chat_id = ? AND event_name = 'episodes_build' "
                "ORDER BY id DESC LIMIT 1", (int(chat_id),))
        if rows:
            build = {"state": str(rows[0].get("outcome") or "unknown"),
                     "last_ts": int(rows[0].get("ts") or 0) or None,
                     "last_outcome": rows[0].get("outcome"),
                     "last_reason": rows[0].get("reason_code")}
    except Exception:
        logger.warning("[web_stories] build progress read failed",
                       exc_info=True)
    backfill = {"state": "not_run", "active": False, "updated_at": None}
    try:
        from services.mca_episode_jobs import (  # noqa: PLC0415 — ленивый импорт
            backfill_coalesce_key, backfill_status_from_job,
        )
        rows = await _fetch(
            db, "SELECT status, updated_at FROM task_jobs WHERE "
                "coalesce_key = ? ORDER BY created_at DESC LIMIT 1",
            (backfill_coalesce_key(int(chat_id)),))
        if rows:
            backfill = {"state": (backfill_status_from_job(rows[0])
                                  or "unknown"),
                        "active": str(rows[0].get("status") or "") in (
                            "queued", "running"),
                        "updated_at": (int(rows[0].get("updated_at") or 0)
                                       or None)}
    except Exception:
        logger.warning("[web_stories] backfill progress read failed",
                       exc_info=True)
    return {"episodes_build": build, "episodes_backfill": backfill}


async def stories_summary(db, chat_id: int, *, now: int | None = None) -> dict:
    """Счётчики витрины (D5): всего / новые-дополненные за окно / ожидающие
    проверки / прогресс обработки. Пустые состояния различимы вызывающим
    (`state`: ok | empty)."""
    ts = _now(now)
    repo = EpisodeRepository(db)
    counters = await repo.stories_counters(int(chat_id))
    window = await _feed_window_counts(db, chat_id, ts - FEED_WINDOW_SECONDS)
    progress = await _build_progress(db, chat_id)
    state = "ok" if counters["total"] else "empty"
    return {"enabled": True, "state": state, "chat_id": int(chat_id),
            "counters": {
                "total": counters["total"],
                "new_window": window["new"],
                "extended_window": window["extended"],
                "contradictions_window": window["contradictions"],
                "pending_verification": counters["pending_verification"],
                "excluded_from_retrieval": counters["excluded_from_retrieval"],
            },
            "window_hours": FEED_WINDOW_SECONDS // 3600,
            "progress": progress,
            "generated_at": ts}


# ── таблица (D6: keyset + фильтры, серверная валидация на слое роутера) ─────

def _table_row(row: dict) -> dict:
    story = effective_story(row)
    participants = _json_loads(row.get("participants_json"), [])
    claims = _json_loads(row.get("claims_json"), [])
    return {
        "story_id": str(row.get("story_id") or ""),
        "chat_id": int(row.get("chat_id") or 0),
        "title": _clip(story.get("title"), 300),
        "summary": _clip(story.get("summary"), 500),
        "participants": [str(p) for p in participants][:50],
        "claims_count": len(claims),
        "event_start_ts": row.get("event_start_ts"),
        "event_end_ts": row.get("event_end_ts"),
        "discovered_at": int(row.get("discovered_at") or 0) or None,
        "updated_at": int(row.get("updated_at") or 0) or None,
        "outcome": str(row.get("outcome") or ""),
        "state": str(row.get("state") or ""),
        "verification": str(row.get("verification") or ""),
        "excluded_from_retrieval": bool(row.get("excluded_from_retrieval")),
        "expected_version": int(row.get("expected_version") or 1),
        "num_episodes": int(row.get("num_episodes") or 0),
        "has_overrides": any(
            row.get(f"override_{f}")
            for f in ("title", "summary", "outcome", "state",
                      "open_questions")),
    }


async def stories_table(db, chat_id: int, **filters) -> dict:
    """Страница таблицы управления (D6). `filters` — уже валидированные
    роутером значения (client-side trust запрещён — TH-7)."""
    rows, has_more = await EpisodeRepository(db).stories_page(
        int(chat_id), **filters)
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = {"updated_at": int(last["updated_at"] or 0),
                       "story_id": str(last["story_id"])}
    return {"enabled": True, "state": "ok", "chat_id": int(chat_id),
            "items": [_table_row(r) for r in rows],
            "next_cursor": next_cursor, "has_more": bool(has_more)}


# ── карточка (D7) ───────────────────────────────────────────────────────────

def _parse_tg_key(chat_id: int, key: str) -> int | None:
    """Ключ `<chat_id>:tg:<tg_message_id>` → валидированное числовое
    сообщение (TH-3/D14: ссылка Telegram строится ТОЛЬКО из числовых
    метаданных; `…:db:…`/мусор — архивный просмотр). chat_id в ключе
    обязан совпадать с чатом карточки (изоляция)."""
    parts = str(key or "").split(":")
    if len(parts) != 3 or parts[1] != "tg":
        return None
    try:
        if int(parts[0]) != int(chat_id):
            return None
        return int(parts[2])
    except (TypeError, ValueError):
        return None


def _tg_link(chat_id: int, tg_message_id: int) -> str | None:
    """Ссылка на оригинал ТОЛЬКО при достаточных метаданных (T-5165):
    группы/супергруппы (chat_id < 0) → t.me/c/...; ЛС — универсальной
    web-ссылки нет (честный archive_only)."""
    chat = int(chat_id)
    if chat >= 0 or tg_message_id is None or tg_message_id <= 0:
        return None
    internal = str(-chat)
    if internal.startswith("100"):
        internal = internal[3:]
    return f"https://t.me/c/{internal}/{int(tg_message_id)}"


def build_original(chat_id: int, message_keys: list[str]) -> dict:
    """Исходный контекст → состояние оригинала (SC-R2c): available (есть ≥1
    валидная ссылка) / archive_only (ключи есть, ссылок нет — ЛС/канон-ключи)
    / unavailable (ключей нет) — отсутствие не маскируется под ссылку."""
    links: list[dict] = []
    seen: set[int] = set()
    keys = 0
    for key in (message_keys or ())[:200]:
        if not key:
            continue
        keys += 1
        tg = _parse_tg_key(int(chat_id), key)
        if tg is None or tg in seen:
            continue
        seen.add(tg)
        url = _tg_link(int(chat_id), tg)
        if url:
            links.append({"tg_message_id": tg, "url": url})
    if links:
        state = "available"
    elif keys:
        state = "archive_only"
    else:
        state = "unavailable"
    return {"state": state, "links": links[:20], "message_keys": keys}


def _episode_row(row: dict) -> dict:
    participants = _json_loads(row.get("participants_json"), [])
    claims = _json_loads(row.get("claims_json"), [])
    keys = _json_loads(row.get("message_keys_json"), [])
    return {
        "episode_id": str(row.get("episode_id") or ""),
        "title": _clip(row.get("title"), 300),
        "summary": _clip(row.get("summary"), 500),
        "participants": [str(p) for p in participants][:50],
        "claims": [{"text": _clip(c.get("text"), 300),
                    "refs": [str(r) for r in (c.get("refs") or ())][:10]}
                   for c in claims if isinstance(c, dict)][:20],
        "event_start_ts": row.get("event_start_ts"),
        "event_end_ts": row.get("event_end_ts"),
        "discovered_at": int(row.get("discovered_at") or 0) or None,
        "updated_at": int(row.get("updated_at") or 0) or None,
        "outcome": str(row.get("outcome") or ""),
        "open_questions": [str(q) for q in _json_loads(
            row.get("open_questions"), [])][:10],
        "message_keys": [str(k) for k in keys][:50],
        "recheck_pending": bool(row.get("recheck_pending")),
    }


def _version_row(row: dict) -> dict:
    payload = _json_loads(row.get("payload_json"), {})
    return {
        "version_id": str(row.get("version_id") or ""),
        "version_no": int(row.get("version_no") or 0),
        "created_at": int(row.get("created_at") or 0) or None,
        "created_by": str(row.get("created_by") or ""),
        "extractor_version": row.get("extractor_version"),
        "title": _clip(payload.get("title"), 200),
        "summary": _clip(payload.get("summary"), 300),
        "manual": bool(payload.get("manual")),
        "overrides": sorted((payload.get("overrides") or {}).keys()),
    }


def _story_dto(row: dict) -> dict:
    story = effective_story(row)
    claims = _json_loads(row.get("claims_json"), [])
    participants = _json_loads(row.get("participants_json"), [])
    return {
        "story_id": str(row.get("story_id") or ""),
        "chat_id": int(row.get("chat_id") or 0),
        "title": _clip(story.get("title"), 300),
        "summary": _clip(story.get("summary"), 2000),
        "participants": [str(p) for p in participants][:50],
        "claims": [{"text": _clip(c.get("text"), 300),
                    "refs": [str(r) for r in (c.get("refs") or ())][:10]}
                   for c in claims if isinstance(c, dict)][:50],
        "event_start_ts": row.get("event_start_ts"),
        "event_end_ts": row.get("event_end_ts"),
        "discovered_at": int(row.get("discovered_at") or 0) or None,
        "updated_at": int(row.get("updated_at") or 0) or None,
        "outcome": str(story.get("outcome") or ""),
        "state": str(story.get("state") or ""),
        "verification": str(story.get("verification") or ""),
        "open_questions": [str(q) for q in _json_loads(
            story.get("open_questions"), [])][:10],
        "excluded_from_retrieval": bool(row.get("excluded_from_retrieval")),
        "expected_version": int(row.get("expected_version") or 1),
        "override_title": row.get("override_title"),
        "override_summary": row.get("override_summary"),
        "override_outcome": row.get("override_outcome"),
        "override_state": row.get("override_state"),
        "override_open_questions": row.get("override_open_questions"),
    }


async def _story_contradictions(db, chat_id: int, story_id: str) -> list[dict]:
    try:
        rows = await _fetch(
            db, "SELECT ts, entity_ids, reason_code FROM mca_events WHERE "
                "chat_id = ? AND event_name = 'contradiction_found' "
                "ORDER BY id DESC LIMIT 20", (int(chat_id),))
    except Exception:
        return []
    out = []
    for r in rows:
        entity = _json_loads(r.get("entity_ids"), {})
        if story_id and str(entity.get("story_id") or "") != str(story_id):
            continue
        out.append({"ts": int(r.get("ts") or 0) or None,
                    "reason_code": r.get("reason_code"),
                    "event_start": entity.get("event_start"),
                    "event_end": entity.get("event_end"),
                    "discovered_at": entity.get("discovered_at"),
                    "text": _clip(entity.get("summary"))})
    return out


async def story_card(db, chat_id: int, story_id: str) -> dict | None:
    """Карточка (D7): фасад + хронология эпизодов + версии + противоречия +
    оригинал. None — история не найдена ИЛИ чужому чату не принадлежит
    (TH-1: отказ без раскрытия существования)."""
    repo = EpisodeRepository(db)
    resolved = await mca_episodes.resolve_story_id(db, str(story_id))
    redirected = resolved != str(story_id)
    row = await repo.get_story(resolved)
    if row is None or int(row.get("chat_id") or 0) != int(chat_id):
        return None
    episode_rows = await repo.episode_messages_by_ids(
        await repo.story_episode_ids(resolved))
    versions = await repo.list_story_versions(resolved)
    message_keys: list[str] = []
    for ep in episode_rows:
        for key in _json_loads(ep.get("message_keys_json"), []):
            message_keys.append(str(key))
    for claim in _json_loads(row.get("claims_json"), []):
        for ref in (claim.get("refs") or ()):
            message_keys.append(str(ref))
    return {"enabled": True, "state": "ok", "chat_id": int(chat_id),
            "story": _story_dto(row),
            "episodes": [_episode_row(ep) for ep in episode_rows],
            "versions": [_version_row(v) for v in versions],
            "contradictions": await _story_contradictions(
                db, int(chat_id), resolved),
            "redirected": redirected,
            "redirect_target": (resolved if redirected else None),
            "original": build_original(int(chat_id), message_keys),
            # mca-06: прямых связей история↔убеждение в модели нет —
            # честный unknown (не выдуманные связи).
            "related_beliefs": {"available": False,
                                "reason": "direct_links_absent",
                                "items": []}}


# ── действия (D8): прямые вызовы фасада mca-05, CAS, post-commit события ────

class ActionError(Exception):
    """Честный отказ действия: `kind` → HTTP-семантика роутера
    (not_found → 404, invalid → 422, stale → 409 CAS, conflict → 409)."""

    def __init__(self, kind: str, message: str = "", **payload):
        super().__init__(message or kind)
        self.kind = kind
        self.payload = payload


async def story_action(db, chat_id: int, story_id: str, *, action: str,
                       expected_version: int | None = None,
                       title=None, summary=None, outcome=None, state=None,
                       open_questions=None,
                       target_id: str | None = None,
                       episode_ids: list[str] | None = None,
                       now: int | None = None) -> dict:
    """Мутация поверх существующих операций фасада mca-05 (D8). Каждое
    действие — версия mca_story_versions; события — существующие эмиттеры
    (story_rebuilt после ручной правки — post-commit; merge — через
    assemble_stories). StaleUpdateError → ActionError('stale')."""
    ts = _now(now)
    repo = EpisodeRepository(db)
    resolved = await mca_episodes.resolve_story_id(db, str(story_id))
    row = await repo.get_story(resolved)
    if row is None or int(row.get("chat_id") or 0) != int(chat_id):
        raise ActionError("not_found")
    current_version = int(row.get("expected_version") or 1)

    if action == "update":
        if expected_version is None:
            raise ActionError("invalid", "expected_version обязателен")
        if all(v is None for v in (title, summary, outcome, state,
                                   open_questions)):
            raise ActionError("invalid", "нет полей правки")
        try:
            await repo.update_story_manual(
                resolved, int(expected_version), title=title, summary=summary,
                outcome=outcome, state=state, open_questions=open_questions,
                now=ts)
        except KeyError:
            raise ActionError("not_found") from None
        except mca_episodes.StaleUpdateError:
            raise ActionError("stale", "stale update",
                              current_version=current_version) from None
        # Post-commit событие §16.1 (существующий эмиттер mca-05; поля
        # изменились → контракт story_rebuilt «изменились поля/версия»).
        emit_story_event(
            "story_rebuilt", outcome="success", chat_id=int(chat_id),
            story_id=resolved, episode_ids=await repo.story_episode_ids(
                resolved),
            event_start=row.get("event_start_ts"),
            event_end=row.get("event_end_ts"),
            discovered_at=row.get("discovered_at"),
            participants=_json_loads(row.get("participants_json"), []),
            summary="manual edit", stage="web", reason_code=None,
            pipeline_run_id=None)
        fresh = await repo.get_story(resolved)
        return {"ok": True, "action": action, "story_id": resolved,
                "expected_version": int((fresh or {}).get(
                    "expected_version") or current_version + 1)}

    if action == "merge":
        if not target_id:
            raise ActionError("invalid", "target_id обязателен")
        target_resolved = await mca_episodes.resolve_story_id(
            db, str(target_id))
        if target_resolved == resolved:
            raise ActionError("invalid", "merge в себя запрещён")
        target_row = await repo.get_story(target_resolved)
        if target_row is None or int(target_row.get("chat_id") or 0) \
                != int(chat_id):
            raise ActionError("not_found", "target")
        ok = await repo.merge_stories([resolved], target_resolved, now=ts)
        if not ok:
            raise ActionError("conflict", "merge failed")
        # Новая версия target'а — существующий вход пересборки (версия
        # создаётся только при фактическом изменении; no-op не шумит).
        await mca_episodes.EpisodeService(db, llm=None, now=ts) \
            .assemble_stories(int(chat_id), ts)
        return {"ok": True, "action": action,
                "story_id": target_resolved,
                "redirected_from": resolved}

    if action == "split":
        new_id, ok = await repo.split_story(
            resolved, [str(e) for e in (episode_ids or ())], now=ts)
        if not ok:
            raise ActionError("conflict", "not_splittable")
        return {"ok": True, "action": action, "story_id": new_id,
                "source_id": resolved}

    if action in ("exclude", "restore"):
        ok = await repo.set_story_excluded(resolved, action == "exclude")
        if not ok:
            raise ActionError("conflict", "excluded update failed")
        return {"ok": True, "action": action, "story_id": resolved,
                "excluded_from_retrieval": action == "exclude"}

    if action == "rebuild":
        contradictions = await mca_episodes.EpisodeService(
            db, llm=None, now=ts).assemble_stories(int(chat_id), ts)
        fresh = await repo.get_story(resolved)
        return {"ok": True, "action": action, "story_id": resolved,
                "contradictions": int(contradictions or 0),
                "expected_version": int((fresh or {}).get(
                    "expected_version") or current_version)}

    raise ActionError("invalid", f"unknown action: {action}")
