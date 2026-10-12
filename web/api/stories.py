"""MCA-12 (round 10.46, ADR-1028-21 D2/§7.5) — REST API «Истории чата».

5 маршрутов (санкция §7.5; роутер — отдельный файл зон, прецедент
memory_agi/oversight; `web/api/routes.py` не меняется — byte-freeze
ROUTES_SHA256_F11 держится, hash re-pin не требуется, см. evidence):

* GET  /api/stories/summary          — счётчики + прогресс обработки;
* GET  /api/stories/feed             — лента (cursor/dedup/bounded, D4);
* GET  /api/stories                  — таблица (keyset+фильтры+LIKE, D6);
* GET  /api/stories/{story_id}       — карточка (D7);
* POST /api/stories/{story_id}/action — мутации через фасад mca-05, CAS (D8).

RBAC/chat-scope (D13/TH-1/TH-2, A25): все маршруты — под TMA-auth
(get_tma_user); чат — ТОЛЬКО из заголовка X-Chat-Id (прецедент /api/status),
аргументом подставить чужой чат нельзя; доступ — существующая матрица
`roles.access_for` + `access.can_access_chat`; мутации — права правки памяти
(прецедент мутаций «Памяти» — global admin, memory_agi) + серверная проверка
каждого действия + CAS. K1 `MCA_STORIES_VITRINA_ENABLED`: OFF → read — честный
disabled (не 404). K2 `MCA_STORIES_MANAGE_ENABLED`: OFF → POST → 409 disabled.
Параметры/фильтры валидируются НА СЕРВЕРЕ (TH-7). R17: наружу — названия/
счётчики/статусы/display-names участников (F7: серверный резолв, raw ID —
служебное поле под Developer details); message-контент и сырые логи не
отдаются (TH-4); заголовки/initData не логируются (TH-5).

F7 (ASAP 8 §14): feed/card получают `display_names` — серверный резолв
участников (канон-ID → человекочитаемое имя): имена авторов чата
(`get_active_participants`, тот же источник/окно, что
`web/api/chat_lore.py::_participant_names` и oversight) + AliasResolver
(`limits.summary_aliases`, существующий механизм). Никаких выдуманных имён:
неразрешённый числовой участник → честный «Участник N»; одинаковые имена
двух РАЗНЫХ участников не склеиваются — оба помечены `ambiguous`.
"""
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services import access as access_srv
from services import lore_runtime
from services import mca_gates
from services import roles as roles_srv
from services import summary_aliases
from services import web_stories
from services.database import row_get
from web.api.deps import get_cache, get_tma_user, user_is_global_admin

logger = logging.getLogger(__name__)

stories_router = APIRouter()


def _chat_id_or_none(x_chat_id: str | None) -> int | None:
    """X-Chat-Id: мусор → 422; отсутствует → None (прецедент routes.py)."""
    if x_chat_id is None:
        return None
    try:
        return int(x_chat_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="X-Chat-Id — целое число") from None


async def _require_chat_access(request: Request, user: WebAppUser,
                               chat_id: int) -> None:
    """Chat scope (TH-1/A25): доступ к чату — существующая матрица
    (`can_access_chat`); чужой чат → 403 без раскрытия существования."""
    cache = get_cache(request)
    try:
        ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    except Exception:
        raise HTTPException(status_code=403,
                            detail="permission denied") from None
    if not access_srv.can_access_chat(ctx, chat_id):
        raise HTTPException(status_code=403, detail="permission denied")


def _require_memory_editor(request: Request, user: WebAppUser) -> None:
    """Права правки памяти для мутаций (TH-2): прецедент мутаций «Памяти» —
    global admin (memory_agi lessons/dream). Server-side проверка КАЖДОГО
    действия; фасад mca-05 сам web-роли не проверяет."""
    if not user_is_global_admin(get_cache(request), user.id):
        raise HTTPException(status_code=403, detail="permission denied")


def _summary_disabled() -> dict:
    """Честный disabled (K1 OFF): не 404-заглушка, структура та же."""
    return {"enabled": False, "state": "disabled", "chat_id": None,
            "counters": None, "progress": None, "window_hours": 24,
            "manage_enabled": bool(mca_gates.stories_manage_enabled()),
            "generated_at": None}


def _db_or_unavailable():
    """SQLite DatabaseService из lore_runtime; None → честный unavailable
    (не имитировать нули — TH-8)."""
    return lore_runtime.get_lore_db()


# ── F7 (ASAP 8 §14): серверный резолв display names участников ──────────────
# Источник — тот же, что у chat_lore/oversight: `get_active_participants`
# (окно 30 дней, cap 200), поверх — AliasResolver (алиасы limits.summary_-
# aliases). Резолв СЕРВЕРНЫЙ и общий для ленты/карточки: JS-дубликата нет.

_PARTICIPANT_WINDOW_DAYS = 30
_PARTICIPANT_CAP = 200


async def _participant_names(db, chat_id: int) -> dict[int, str]:
    """{user_id: author_name} активных участников чата (best-effort;
    fail-open → {} = fallback «Участник N», не выдуманные имена)."""
    try:
        rows = await db.get_active_participants(
            int(chat_id),
            int(time.time()) - _PARTICIPANT_WINDOW_DAYS * 86400,
            _PARTICIPANT_CAP)
    except Exception:
        logger.warning("[stories] имена участников недоступны — fallback "
                       "«Участник N» | chat=%s", chat_id, exc_info=True)
        return {}
    names: dict[int, str] = {}
    for r in rows:
        try:
            uid = int(row_get(r, "user_id"))
        except (TypeError, ValueError):
            continue
        author = str(row_get(r, "author_name") or "").strip()
        if uid and author:
            names[uid] = author
    return names


async def _names_ctx(db, chat_id: int) -> tuple:
    """(имена, alias-резолвер) одним проходом на запрос (прецедент
    oversight._feed_user_index: кэш резолва на запрос, не на строку)."""
    names = await _participant_names(db, chat_id)
    try:
        resolver = await summary_aliases.build_alias_resolver(int(chat_id))
    except Exception:
        logger.warning("[stories] alias-резолв не удался — имена как есть "
                       "| chat=%s", chat_id, exc_info=True)
        resolver = None
    return names, resolver


def _display_entries(participants, names: dict, resolver) -> list[dict]:
    """Контракт F7: [{id, name, ambiguous}] в порядке `participants`.

    Наружу — имя; канон-ID остаётся служебным полем `id` (R17: raw IDs
    главный UI не показывает — только под Developer details). Одинаковые
    имена разных участников НЕ склеиваются: обе записи остаются, честная
    пометка `ambiguous` (различие — по `id`)."""
    entries: list[dict] = []
    for raw in (participants or ())[:50]:
        pid = str(raw or "").strip()
        if not pid:
            continue
        name = ""
        if pid.lstrip("-").isdigit():
            uid = int(pid)
            candidate = names.get(uid, "")
            if resolver is not None:
                try:
                    resolved = resolver.resolve(uid, candidate or None, None)
                except Exception:
                    resolved = candidate or None
                if resolved and str(resolved).strip() \
                        and str(resolved) != pid:
                    candidate = str(resolved).strip()
            if candidate and candidate != pid:
                name = candidate
        else:
            # не-числовой участник (историческое канон-имя из LLM-пути
            # mca-05) — уже человеческое, наружу как есть (без чистки —
            # тот же принцип, что chat_lore::_participant_names).
            name = pid
        entries.append({"id": pid, "name": name or f"Участник {pid}",
                        "ambiguous": False})
    counts: dict[str, int] = {}
    for e in entries:
        key = e["name"].casefold()
        counts[key] = counts.get(key, 0) + 1
    for e in entries:
        if counts[e["name"].casefold()] > 1:
            e["ambiguous"] = True
    return entries


def _annotate_feed(payload, names: dict, resolver) -> dict:
    """Контракт F7: каждое событие `ok`-ленты получает `display_names`.
    Не-`ok` состояния (disabled/unavailable/no_chat) возвращаются как есть —
    честные состояния не обогащаются."""
    if isinstance(payload, dict) and payload.get("state") == "ok":
        for ev in payload.get("events") or ():
            if isinstance(ev, dict):
                ev["display_names"] = _display_entries(
                    ev.get("participants"), names, resolver)
    return payload


def _annotate_card(card, names: dict, resolver) -> dict:
    """Контракт F7: `display_names` на истории и каждом эпизоде карточки."""
    if not isinstance(card, dict) or card.get("state") != "ok":
        return card
    story = card.get("story")
    if isinstance(story, dict):
        story["display_names"] = _display_entries(
            story.get("participants"), names, resolver)
    for ep in card.get("episodes") or ():
        if isinstance(ep, dict):
            ep["display_names"] = _display_entries(
                ep.get("participants"), names, resolver)
    return card


# ── 1. GET /api/stories/summary ─────────────────────────────────────────────

@stories_router.get("/stories/summary")
async def stories_summary(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Счётчики витрины + прогресс архивной обработки (D5). Без чата —
    честный `no_chat` (не нули); чужой чат → 403 (A25)."""
    if not mca_gates.stories_vitrina_enabled():
        return _summary_disabled()
    db = _db_or_unavailable()
    if db is None:
        return {"enabled": True, "state": "unavailable", "chat_id": None,
                "counters": None, "progress": None, "window_hours": 24,
                "manage_enabled": bool(mca_gates.stories_manage_enabled()),
                "generated_at": None}
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return {"enabled": True, "state": "no_chat", "chat_id": None,
                "counters": None, "progress": None, "window_hours": 24,
                "manage_enabled": bool(mca_gates.stories_manage_enabled()),
                "generated_at": None}
    await _require_chat_access(request, user, chat_id)
    summary = await web_stories.stories_summary(db, chat_id)
    summary["manage_enabled"] = bool(mca_gates.stories_manage_enabled())
    return summary


# ── 2. GET /api/stories/feed ────────────────────────────────────────────────

@stories_router.get("/stories/feed")
async def stories_feed(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """Лента событий историй (D4): инкрементальный курсор `id > cursor`,
    дедуп по event_id, bounded-страница (`has_more` — «история ограничена»).
    Обе даты (A11) — в entity каждого события."""
    if not mca_gates.stories_vitrina_enabled():
        return {"enabled": False, "state": "disabled", "chat_id": None,
                "cursor": int(cursor), "events": [], "has_more": False}
    db = lore_runtime.get_lore_db()
    if db is None:
        return {"enabled": True, "state": "unavailable", "chat_id": None,
                "cursor": int(cursor), "events": [], "has_more": False}
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return {"enabled": True, "state": "no_chat", "chat_id": None,
                "cursor": int(cursor), "events": [], "has_more": False}
    await _require_chat_access(request, user, chat_id)
    payload = await web_stories.stories_feed(db, chat_id, cursor=cursor,
                                             limit=limit)
    names, resolver = await _names_ctx(db, chat_id)
    return _annotate_feed(payload, names, resolver)


# ── 3. GET /api/stories (таблица) ───────────────────────────────────────────

@stories_router.get("/stories")
async def stories_table(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before_updated_at: Annotated[int | None, Query(ge=0)] = None,
    before_story_id: Annotated[str | None, Query(max_length=64)] = None,
    title: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    participant: Annotated[str | None, Query(max_length=64)] = None,
    event_from: Annotated[int | None, Query(ge=0)] = None,
    event_to: Annotated[int | None, Query(ge=0)] = None,
    discovered_from: Annotated[int | None, Query(ge=0)] = None,
    discovered_to: Annotated[int | None, Query(ge=0)] = None,
    updated_from: Annotated[int | None, Query(ge=0)] = None,
    updated_to: Annotated[int | None, Query(ge=0)] = None,
    min_episodes: Annotated[int | None, Query(ge=0, le=1000)] = None,
    max_episodes: Annotated[int | None, Query(ge=0, le=1000)] = None,
    state: Annotated[str | None, Query(
        pattern="^(open|closed|uncertain)$")] = None,
    verification: Annotated[str | None, Query(
        pattern="^(unknown|tentative|rejected|confirmed)$")] = None,
):
    """Таблица управления (D6): серверная keyset-пагинация
    `(updated_at, story_id)` + фильтры на существующих колонках v21 + поиск
    LIKE title/summary/claims (параметризованный, TH-7). Все параметры
    валидированы выше (Query-ограничения) — client-side trust запрещён."""
    if not mca_gates.stories_vitrina_enabled():
        return {"enabled": False, "state": "disabled", "chat_id": None,
                "items": [], "next_cursor": None, "has_more": False,
                "manage_enabled": bool(mca_gates.stories_manage_enabled())}
    db = lore_runtime.get_lore_db()
    if db is None:
        return {"enabled": True, "state": "unavailable", "chat_id": None,
                "items": [], "next_cursor": None, "has_more": False,
                "manage_enabled": bool(mca_gates.stories_manage_enabled())}
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return {"enabled": True, "state": "no_chat", "chat_id": None,
                "items": [], "next_cursor": None, "has_more": False,
                "manage_enabled": bool(mca_gates.stories_manage_enabled())}
    await _require_chat_access(request, user, chat_id)
    page = await web_stories.stories_table(
        db, chat_id, limit=limit, before_updated_at=before_updated_at,
        before_story_id=before_story_id, title=title, q=q,
        participant=participant, event_from=event_from, event_to=event_to,
        discovered_from=discovered_from, discovered_to=discovered_to,
        updated_from=updated_from, updated_to=updated_to,
        min_episodes=min_episodes, max_episodes=max_episodes,
        state=state, verification=verification)
    page["manage_enabled"] = bool(mca_gates.stories_manage_enabled())
    return page


# ── 4. GET /api/stories/{story_id} (карточка) ───────────────────────────────

@stories_router.get("/stories/{story_id}")
async def story_card(
    request: Request,
    story_id: str,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Карточка истории (D7). Story валидируется на принадлежность
    разрешённому чату ДО чтения (TH-1); чужой/несуществующий → 404 без
    раскрытия существования; redirect-источник резолвится фасадом."""
    if not mca_gates.stories_vitrina_enabled():
        return {"enabled": False, "state": "disabled"}
    db = lore_runtime.get_lore_db()
    if db is None:
        return {"enabled": True, "state": "unavailable"}
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return {"enabled": True, "state": "no_chat"}
    await _require_chat_access(request, user, chat_id)
    card = await web_stories.story_card(db, chat_id, str(story_id))
    if card is None:
        raise HTTPException(status_code=404, detail="история не найдена")
    card["manage_enabled"] = bool(mca_gates.stories_manage_enabled())
    names, resolver = await _names_ctx(db, chat_id)
    return _annotate_card(card, names, resolver)


# ── 5. POST /api/stories/{story_id}/action (мутации, CAS) ───────────────────

class StoryActionBody(BaseModel):
    """Тело действия (D8): правка — CAS `expected_version`; merge — target;
    split — отделяемые эпизоды. Длина полей ограничена сервером (TH-7)."""
    action: str = Field(min_length=1, max_length=32)
    expected_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=2000)
    outcome: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=16)
    open_questions: list[str] | None = Field(default=None, max_length=20)
    target_id: str | None = Field(default=None, max_length=64)
    episode_ids: list[str] | None = Field(default=None, max_length=50)


_ACTION_ERROR_STATUS = {
    "not_found": 404,
    "invalid": 422,
    "stale": 409,
    "conflict": 409,
}

#: Whitelist действий (D8): только существующие операции фасада mca-05.
_STORY_ACTIONS = ("update", "merge", "split", "exclude", "restore", "rebuild")


@stories_router.post("/stories/{story_id}/action")
async def story_action(
    request: Request,
    story_id: str,
    body: StoryActionBody,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Мутация поверх существующих операций фасада mca-05 (D8). Гейт K2 OFF
    → 409 disabled (честный, D15). Порядок проверок: K2 → права правки
    памяти → chat scope → действие (CAS внутри фасада; StaleUpdateError →
    409 stale с текущей версией — UI не затирает чужие правки, A13)."""
    if not mca_gates.stories_manage_enabled():
        raise HTTPException(status_code=409, detail={
            "code": "disabled",
            "reason": "MCA_STORIES_MANAGE_ENABLED=OFF (только просмотр)"})
    action = str(body.action or "").strip()
    if action not in _STORY_ACTIONS:
        raise HTTPException(status_code=422,
                            detail={"code": "invalid",
                                    "reason": f"unknown action: {action}"})
    _require_memory_editor(request, user)
    db = lore_runtime.get_lore_db()
    if db is None:
        raise HTTPException(status_code=503,
                            detail="база памяти недоступна")
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422,
                            detail="нужен X-Chat-Id (контекст чата)")
    await _require_chat_access(request, user, chat_id)
    state = body.state
    if state is not None and state not in ("open", "closed", "uncertain"):
        raise HTTPException(status_code=422, detail="недопустимое state")
    try:
        return await web_stories.story_action(
            db, chat_id, str(story_id), action=action,
            expected_version=body.expected_version, title=body.title,
            summary=body.summary, outcome=body.outcome, state=state,
            open_questions=body.open_questions, target_id=body.target_id,
            episode_ids=body.episode_ids)
    except web_stories.ActionError as exc:
        raise HTTPException(
            status_code=_ACTION_ERROR_STATUS.get(exc.kind, 409),
            detail=dict(exc.payload, code=exc.kind)) from None
