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
счётчики/статусы/участники-ID; message-контент и сырые логи не отдаются
(TH-4); заголовки/initData не логируются (TH-5).
"""
import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services import access as access_srv
from services import lore_runtime
from services import mca_gates
from services import roles as roles_srv
from services import web_stories
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
    return await web_stories.stories_feed(db, chat_id, cursor=cursor,
                                          limit=limit)


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
    return card


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
