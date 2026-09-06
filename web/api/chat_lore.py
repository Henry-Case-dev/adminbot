"""Раунд 7 (chat-lore-management-v2, T-779, E1) — REST «Лор чатов» /api/chat_lore.

Раунд 9 (AGI Memory, spec §3.6.1, T-828/F1/F2) — relations-эндпоинты в этом
же модуле (общие helpers _components/can_access_chat/_conflict; отдельный
файл НЕ заводим — D-решение §3.6.1): GET список участников (SQLite-скоры
users_meta через RelationsService из lore_runtime — Q2 + PG manual из
chat_profiles.relations), PUT/DELETE ручной пометки юзера (optimistic 409
по updated_at профиля), PUT тумблер relations_enabled. История правок —
внутри JSONB (D-2), НЕ в chat_lore_history.

APIRouter (включение в web/app.py рядом с api_router, prefix="/api"); ВСЕ
эндпоинты под `Depends(get_tma_user)` + матрица доступа Q6 (spec §3.8):

  * глобальный admin (роль admin/wildcard/ADMIN_USER_ID) — все чаты и все
    операции (включая remap и CRUD chat_admins);
  * остальные — чат доступен ТОЛЬКО при строке (telegram_id, chat_id) в
    chat_admins (moderator/custom с секцией chat_lore — тоже только свои
    строки; секция на сервере не расширяет список);
  * remap и POST/DELETE chat_admins — только глобальный admin (403 иначе).

Коды ошибок по конвенции 84.5: 401 (нет initData) / 403 / 404 / 409
(optimistic-метка, auto_disabled, locked) / 422 (валидация) / 503 (PG down,
fail-open лора: ChatLorePgUnavailable → 503, не 500).

DI: store/cache/worker — из services.lore_runtime (set_lore_components в
bot.py on_startup); компонент не установлен / PG недоступен → 503.
"""
import logging
import time
from typing import Annotated, Literal

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config.settings import settings
from services import lore_runtime
from services.chat_lore_store import ChatLoreConflict, ChatLorePgUnavailable
from services.permissions import Permissions
from web.api.deps import get_cache, get_tma_user
# UI-полировка TMA: RAM-кэши обогащения (title/фото чата, username/фото
# участника) — те же TTL-словари, что у аватар-прокси (web/api/avatars.py).
from web.api.avatars import chat_display_info, user_display_info

logger = logging.getLogger(__name__)

chat_lore_router = APIRouter()

_MANUAL_MAX_CHARS = 4000            # FR-2: cap ручной правки (422)
_PERIOD_MIN = 1                     # auto_period_hours/auto_window_hours
_PERIOD_MAX = 720                   # валидация 1..720 (422; spec §3.8)
_PREVIEW_CHARS = 80                 # превью в списке чатов
_RELATION_NOTE_MAX = 4000           # F2: cap заметки отношений (422)
_RELATIONS_LIST_MAX = 100           # F2: потолок строк списка отношений
_RELATIONS_ENRICH_TOP = 30          # UI-полировка: Bot API-обогащение
# (username/фото) только для первых 30 строк (топ по activity); остальным —
# null (UI показывает строку без аватара). Кэши 1ч.


# ── Pydantic-модели ─────────────────────────────────────────────────────────

class ManualLoreUpdate(BaseModel):
    manual_lore: str = Field(max_length=_MANUAL_MAX_CHARS)
    updated_at: str                  # Q8: optimistic-метка ОБЯЗАТЕЛЬНА в теле


class SettingsUpdate(BaseModel):
    auto_enabled: bool | None = None
    auto_period_hours: int | None = Field(
        default=None, ge=_PERIOD_MIN, le=_PERIOD_MAX)
    auto_window_hours: int | None = Field(
        default=None, ge=_PERIOD_MIN, le=_PERIOD_MAX)
    # Раунд 9 (F2, spec §3.6.1/D-3): per-chat тумблер тона по стадиям —
    # колонка relations_enabled; история НЕ пишется (D-2).
    relations_enabled: bool | None = None
    updated_at: str                  # Q8: обязательна в теле


# ── Раунд 9 (T-828/F2, spec §3.6.1): relations ──────────────────────────────
# Ручная пометка {manual_stage, note} живёт в PG chat_profiles.relations
# (Q1); правки — store-методами с optimistic-409 по updated_at профиля.
# stage_manual: 'auto' → сброс на авто (удаление ключа при пустой заметке);
# иначе стадия из MANUAL_STAGES (422 вне enum).
RelationStage = Literal["auto", "stranger", "acquaintance", "regular",
                        "veteran"]


class RelationUpsert(BaseModel):
    """PUT /chat_lore/{chat_id}/relations — user_id в теле (сессионная
    форма F2); сегментный вариант PUT /{user_id} — RelationStageBody."""
    user_id: int | None = Field(default=None, gt=0)
    stage_manual: RelationStage | None = None
    note: str | None = Field(default=None, max_length=_RELATION_NOTE_MAX)
    updated_at: str


class RelationStageBody(BaseModel):
    """PUT /chat_lore/{chat_id}/relations/{user_id} (spec §3.6.1/T-828)."""
    stage_manual: RelationStage | None = None
    note: str | None = Field(default=None, max_length=_RELATION_NOTE_MAX)
    updated_at: str


class RelationRemove(BaseModel):
    """DELETE — user_id в теле (сессионная форма); сегментный вариант —
    только updated_at."""
    user_id: int | None = Field(default=None, gt=0)
    updated_at: str


class RelationStageRemove(BaseModel):
    """DELETE /chat_lore/{chat_id}/relations/{user_id} (spec §3.6.1)."""
    updated_at: str


class RelationsEnabledBody(BaseModel):
    """PUT /chat_lore/{chat_id}/relations_enabled {enabled, updated_at}."""
    enabled: bool
    updated_at: str


class RemapRequest(BaseModel):
    new_chat_id: int


class ChatAdminAdd(BaseModel):
    chat_id: int
    telegram_id: int


# ── helpers: права и компоненты ─────────────────────────────────────────────

def _user_permissions(cache, telegram_id: int) -> Permissions:
    """Права юзера; неизвестный ID → пустые (прецедент web/api/deps.py)."""
    perms = cache.get_permissions_by_telegram_id(telegram_id)
    if perms is None:
        role = cache.get_permissions("user")
        return role if role is not None else Permissions.from_dict({})
    return perms


def _is_global_admin(cache, telegram_id: int) -> bool:
    """Глобальный admin: роль admin / wildcard / settings.ADMIN_USER_ID."""
    if telegram_id == settings.ADMIN_USER_ID:
        return True
    perms = _user_permissions(cache, telegram_id)
    if perms.wildcard:
        return True
    return cache.get_role(telegram_id) == "admin"


async def can_access_chat(cache, store, telegram_id: int,
                          chat_id: int) -> bool:
    """Матрица Q6: глобальный admin ИЛИ строка chat_admins (telegram_id,
    chat_id). Ошибки PG — НЕ глотаем (наверх 503)."""
    if _is_global_admin(cache, telegram_id):
        return True
    return await store.is_chat_admin(telegram_id, chat_id)


def _components() -> tuple:
    """(store, cache, worker) из lore_runtime; отсутствие → 503."""
    store = lore_runtime.get_lore_store()
    if store is None:
        raise HTTPException(status_code=503,
                            detail="chat lore недоступен (не инициализирован)")
    return store, lore_runtime.get_lore_cache(), lore_runtime.get_lore_worker()


def _pg_guard(exc: Exception) -> HTTPException:
    """ChatLorePgUnavailable и прочие PG-сбои → 503 (fail-open по конвенции
    routes.py: PostgreSQL недоступен (R6))."""
    return HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")


async def _store_call(awaitable):
    """Выполнить store-вызов; ChatLorePgUnavailable → 503 (fail-open)."""
    try:
        return await awaitable
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc


def _conflict(exc: ChatLoreConflict) -> HTTPException:
    """409 optimistic-метки: {"detail": {"code": "conflict",
    "current_updated_at": …}} (Q8)."""
    return HTTPException(status_code=409, detail={
        "code": "conflict",
        "current_updated_at": exc.current_updated_at,
    })


async def _require_chat(cache, store, user: WebAppUser,
                        chat_id: int) -> int:
    """Резолв chat_id + матрица доступа → доступный (резолвнутый) id.
    403 — нет доступа; 503 — PG недоступен."""
    try:
        resolved = await store.resolve_chat_id(chat_id)
        allowed = await can_access_chat(cache, store, user.id, resolved)
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    if not allowed:
        raise HTTPException(status_code=403, detail="permission denied")
    return resolved


async def _profile_or_404(store, chat_id: int):
    """Профиль чата (резолв внутри store); нет → 404."""
    profile = await _store_call(store.get_profile(chat_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="профиль чата не найден")
    return profile


def _preview(text: str) -> str:
    text = str(text or "")
    return text[:_PREVIEW_CHARS] + ("…" if len(text) > _PREVIEW_CHARS else "")


# ── GET /chat_lore/chats ────────────────────────────────────────────────────

@chat_lore_router.get("/chat_lore/chats")
async def list_chats(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Список доступных чатов (Q6): admin — все профили; остальные — только
    свои (строки chat_admins). Неактивные включены с пометкой is_active=false
    (диагностика; spec §3.8)."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    try:
        profiles = await store.list_profiles()
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    if not _is_global_admin(cache, user.id):
        accessible = []
        for profile in profiles:
            try:
                if await store.is_chat_admin(user.id, profile.chat_id):
                    accessible.append(profile)
            except ChatLorePgUnavailable as exc:
                raise _pg_guard(exc) from exc
        profiles = accessible
    # UI-полировка TMA: title/photo_file_id — best-effort через Bot API
    # (RAM-кэш 1ч в web/api/avatars.py); ошибка/нет бота → None-поля.
    enriched = []
    for p in profiles:
        info = await chat_display_info(p.chat_id)
        enriched.append({
            "chat_id": p.chat_id,
            "title": info["title"],
            "photo_file_id": info["photo_file_id"],
            "manual_preview": _preview(p.manual_lore),
            "auto_preview": _preview(p.auto_lore),
            "has_manual": bool((p.manual_lore or "").strip()),
            "has_auto": bool((p.auto_lore or "").strip()),
            "auto_enabled": p.auto_enabled,
            "is_active": p.is_active,
            "updated_at": p.updated_at,
        })
    return enriched


# ── /chat_lore/admins (только глобальный admin на POST/DELETE) ──────────────
# ВАЖНО: регистрируются ДО GET /chat_lore/{chat_id} — иначе литеральный
# сегмент "admins" съедался бы generic-роутом (422 int-парсинг).

@chat_lore_router.get("/chat_lore/admins")
async def list_admins(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int, Query()],
):
    """Список telegram_id админов чата (для доступного чата)."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    try:
        admins = await store.list_chat_admins(chat_id)
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return admins


@chat_lore_router.post("/chat_lore/admins")
async def add_admin(
    payload: ChatAdminAdd,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Добавить админа чата — ТОЛЬКО глобальный admin (D8/Q6; история
    field='chat_admin', new_value=str(telegram_id))."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    if not _is_global_admin(cache, user.id):
        raise HTTPException(status_code=403, detail="permission denied")
    try:
        added = await store.add_chat_admin(
            payload.chat_id, payload.telegram_id, added_by=user.id)
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return {"added": bool(added)}


@chat_lore_router.delete("/chat_lore/admins")
async def remove_admin(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int, Query()],
    telegram_id: Annotated[int, Query()],
):
    """Удалить админа чата — ТОЛЬКО глобальный admin (история
    field='chat_admin', old_value=str(telegram_id))."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    if not _is_global_admin(cache, user.id):
        raise HTTPException(status_code=403, detail="permission denied")
    try:
        removed = await store.remove_chat_admin(chat_id, telegram_id)
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return {"removed": bool(removed)}


# ── GET /chat_lore/{chat_id} ────────────────────────────────────────────────

@chat_lore_router.get("/chat_lore/{chat_id}")
async def get_profile(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Профиль чата (полный объект, поля §3.2); 403/404 по матрице."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    profile = await _profile_or_404(store, chat_id)
    return profile.to_dict()


# ── PUT /chat_lore/{chat_id} (manual) ───────────────────────────────────────

@chat_lore_router.put("/chat_lore/{chat_id}")
async def update_manual(
    chat_id: int,
    payload: ManualLoreUpdate,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Ручная правка manual_lore (FR-2): ≤ 4000 символов (422); история
    field='manual', changed_by=telegram_id; optimistic-метка `updated_at` из
    тела (Q8) → 409 {"detail": {"code": "conflict", "current_updated_at"}}."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    try:
        profile = await store.set_manual(
            chat_id, payload.manual_lore,
            changed_by=user.id, expected_updated_at=payload.updated_at)
    except ChatLoreConflict as exc:
        raise _conflict(exc) from exc
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return profile.to_dict()


# ── PUT /chat_lore/{chat_id}/settings ───────────────────────────────────────

@chat_lore_router.put("/chat_lore/{chat_id}/settings")
async def update_settings(
    chat_id: int,
    payload: SettingsUpdate,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Настройки авто-генерации (по-полевая история; 409 optimistic;
    period/window 1..720 → 422). Раунд 9 (F2/§3.6.1): relations_enabled —
    per-chat тумблер тона по стадиям (БЕЗ истории, D-2; 409 по updated_at)."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    try:
        profile = await store.update_settings(
            chat_id,
            auto_enabled=payload.auto_enabled,
            auto_period_hours=payload.auto_period_hours,
            auto_window_hours=payload.auto_window_hours,
            relations_enabled=payload.relations_enabled,
            changed_by=user.id,
            expected_updated_at=payload.updated_at)
    except ChatLoreConflict as exc:
        raise _conflict(exc) from exc
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return profile.to_dict()


# ── POST /chat_lore/{chat_id}/generate ──────────────────────────────────────

@chat_lore_router.post("/chat_lore/{chat_id}/generate")
async def generate_now(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """«Сгенерировать сейчас» (FR-4): синхронный generate_for_chat(manual=
    True); auto_enabled=false → 409 {"detail": {"code": "auto_disabled"}}."""
    cache = get_cache(request)
    store, _cache_c, worker = _components()
    await _require_chat(cache, store, user, chat_id)
    profile = await _profile_or_404(store, chat_id)
    if not profile.auto_enabled:
        raise HTTPException(status_code=409, detail={"code": "auto_disabled"})
    if worker is None:
        raise HTTPException(status_code=503,
                            detail="chat lore воркер недоступен")
    try:
        result = await worker.generate_for_chat(chat_id, manual=True)
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    status = result.get("status")
    if status == "ok":
        return {"status": "ok", "changed": bool(result.get("changed"))}
    if result.get("reason") in ("auto_disabled", "locked"):
        raise HTTPException(status_code=409,
                            detail={"code": result["reason"]})
    if status in ("failed", "error"):
        raise HTTPException(status_code=500,
                            detail="генерация не удалась (fail-open)")
    return result                        # skipped: quiet_window/no_profile/...


# ── POST /chat_lore/{chat_id}/clear_auto ────────────────────────────────────

@chat_lore_router.post("/chat_lore/{chat_id}/clear_auto")
async def clear_auto(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Очистка auto_lore: история field='auto' old=текст new='';
    last_auto_at=NULL (следующий авто-прогон не ждёт период)."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    try:
        profile = await store.clear_auto(chat_id, changed_by=user.id)
    except ChatLoreConflict as exc:
        raise _conflict(exc) from exc
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return profile.to_dict()


# ── POST /chat_lore/{chat_id}/remap ─────────────────────────────────────────

@chat_lore_router.post("/chat_lore/{chat_id}/remap")
async def remap_chat(
    chat_id: int,
    payload: RemapRequest,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Перепривязка chat_id (D5/Q9): ТОЛЬКО глобальный admin (иначе 403);
    merge-семантика (409 на занятый new НЕ возвращаем); 404 — профиля нет."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    if not _is_global_admin(cache, user.id):
        raise HTTPException(status_code=403, detail="permission denied")
    if payload.new_chat_id == chat_id:
        raise HTTPException(status_code=422, detail="new_chat_id == chat_id")
    await _profile_or_404(store, chat_id)
    try:
        result = await store.migrate_profile(
            old_chat_id=chat_id, new_chat_id=payload.new_chat_id,
            changed_by=user.id)
        profile = await store.get_profile(payload.new_chat_id)
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="профиль чата не найден")
    return {"status": "ok", "moved": bool(result.get("moved")),
            "merged": bool(result.get("merged")), "profile": profile.to_dict()}


# ── GET /chat_lore/{chat_id}/history ────────────────────────────────────────

@chat_lore_router.get("/chat_lore/{chat_id}/history")
async def get_history(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Timeline DESC: created_at ISO, field, changed_by, is_ai (changed_by
    NULL = бот/воркер), old_value, new_value (полные — фронт режет на рендер)."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    try:
        rows = await store.history(chat_id, limit=limit)
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return [
        {
            "created_at": r["created_at"],
            "field": r["field"],
            "changed_by": r["changed_by"],
            "is_ai": r["changed_by"] is None,
            "old_value": r["old_value"],
            "new_value": r["new_value"],
        }
        for r in rows
    ]


# ═══ Раунд 9 (AGI Memory, spec §3.6.1/Q2, T-828/F2): relations ═════════════

def _db_component() -> tuple:
    """(db, relations_service) из lore_runtime (Q2): db None → SQLite-часть
    пуста (fail-open); None-компоненты ловят вызывающие."""
    return lore_runtime.get_lore_db(), lore_runtime.get_relations_service()


@chat_lore_router.get("/chat_lore/{chat_id}/relations")
async def list_relations(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Список участников чата с отношениями (spec §3.6.1): SQLite-скоры/
    авто-стадии (users_meta через RelationsService — refresh топ-N по
    limits.relations_api_max_users) + PG manual-стадии/заметки (relations
    JSONB, мерж по str(user_id)); имя — каскад aliases. Сортировка —
    activity_score DESC (None/0 в конце), cap _RELATIONS_LIST_MAX (100).
    Права — can_access_chat; 404 — профиля чата нет; PG down → 503."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    profile = await _profile_or_404(store, chat_id)
    db, relations_service = _db_component()
    users: list = []
    if relations_service is not None and db is not None:
        try:
            names = await _participant_names(db, chat_id)
            snapshot = await relations_service.get_relations_snapshot(
                chat_id, names=names or None)
            users = [dict(u) for u in snapshot]
        except Exception:
            logger.warning(
                "[relations] SQLite-чтение не удалось — список пуст | "
                "chat_id=%s", chat_id, exc_info=True)
            users = []
    users.sort(key=lambda u: (not bool(u.get("activity_score")),
                              -(float(u.get("activity_score") or 0.0)),
                              int(u.get("user_id") or 0)))
    # UI-полировка TMA: username/photo_file_id — Bot API-обогащение ТОЛЬКО
    # для первых _RELATIONS_ENRICH_TOP строк списка (топ по activity;
    # get_chat_member + getUserProfilePhotos, RAM-кэши 1ч); остальным — null
    # (UI покажет строку без аватара). Никаких 100 одновременных вызовов.
    for u in users[:_RELATIONS_ENRICH_TOP]:
        meta = await user_display_info(chat_id, int(u.get("user_id") or 0))
        u["username"] = meta["username"]
        u["photo_file_id"] = meta["photo_file_id"]
    for u in users[_RELATIONS_ENRICH_TOP:]:
        u["username"] = None
        u["photo_file_id"] = None
    return {
        "chat_id": chat_id,
        "relations_enabled": bool(profile.relations_enabled),
        "users": users[:_RELATIONS_LIST_MAX],
    }


async def _participant_names(db, chat_id: int) -> dict | None:
    """{user_id: display} из последних авторов сообщений чата (best-effort;
    поверх — каскад aliases в RelationsService; пусто → None = uid)."""
    try:
        rows = await db.get_active_participants(
            chat_id, int(time.time()) - 30 * 86400, 200)
        names = {int(r["user_id"]): str(r["author_name"]).strip()
                 for r in rows if r.get("user_id") and str(
                     r.get("author_name") or "").strip()}
    except Exception:
        logger.warning(
            "[relations] имена участников недоступны — uid fallback | "
            "chat_id=%s", chat_id, exc_info=True)
        return None
    return names or None


async def _save_relation(cache, store, user, chat_id: int,
                         user_id: int, stage_manual, note: str | None,
                         updated_at: str) -> dict:
    """Общая реализация PUT relations: stage_manual 'auto'/None → сброс на
    авто (удаление ключа при пустой заметке — store.put_relation);
    иначе — ручная стадия + заметка (updated_by=telegram_id в JSONB-аудит,
    D-2). 409 optimistic → _conflict; 503 PG."""
    await _require_chat(cache, store, user, chat_id)
    stage = None if stage_manual in (None, "auto") else stage_manual
    try:
        profile = await store.put_relation(
            chat_id, user_id, stage=stage, note=note,
            expected_updated_at=updated_at, updated_by=user.id)
    except ChatLoreConflict as exc:
        raise _conflict(exc) from exc
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return profile.to_dict()


# PUT /chat_lore/{chat_id}/relations — user_id в теле (форма F2-сессии)
@chat_lore_router.put("/chat_lore/{chat_id}/relations")
async def put_relation_body(
    chat_id: int,
    payload: RelationUpsert,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Ручная пометка юзера {user_id, stage_manual, note} (форма F2)."""
    if payload.user_id is None:
        raise HTTPException(status_code=422, detail="user_id обязателен")
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    return await _save_relation(cache, store, user, chat_id,
                                payload.user_id, payload.stage_manual,
                                payload.note, payload.updated_at)


# PUT /chat_lore/{chat_id}/relations/{user_id} (spec §3.6.1/T-828)
@chat_lore_router.put("/chat_lore/{chat_id}/relations/{user_id}")
async def put_relation_path(
    chat_id: int,
    user_id: int,
    payload: RelationStageBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Ручная пометка юзера {stage_manual, note, updated_at} — сегментная
    форма (spec). user_id вне (0, …] → 422."""
    if user_id <= 0:
        raise HTTPException(status_code=422, detail="user_id вне диапазона")
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    return await _save_relation(cache, store, user, chat_id, user_id,
                                payload.stage_manual, payload.note,
                                payload.updated_at)


# DELETE /chat_lore/{chat_id}/relations — user_id в теле (форма F2)
@chat_lore_router.delete("/chat_lore/{chat_id}/relations")
async def delete_relation_body(
    chat_id: int,
    payload: RelationRemove,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Сброс юзера на авто (удаление ключа relations; 409 optimistic)."""
    if payload.user_id is None:
        raise HTTPException(status_code=422, detail="user_id обязателен")
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    return await _delete_relation(cache, store, user, chat_id,
                                  payload.user_id, payload.updated_at)


# DELETE /chat_lore/{chat_id}/relations/{user_id} (spec §3.6.1/T-828)
@chat_lore_router.delete("/chat_lore/{chat_id}/relations/{user_id}")
async def delete_relation_path(
    chat_id: int,
    user_id: int,
    payload: RelationStageRemove,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Сброс юзера на авто — сегментная форма (spec)."""
    if user_id <= 0:
        raise HTTPException(status_code=422, detail="user_id вне диапазона")
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    return await _delete_relation(cache, store, user, chat_id, user_id,
                                  payload.updated_at)


async def _delete_relation(cache, store, user, chat_id: int, user_id: int,
                           updated_at: str) -> dict:
    await _require_chat(cache, store, user, chat_id)
    try:
        profile = await store.delete_relation(
            chat_id, user_id, expected_updated_at=updated_at)
    except ChatLoreConflict as exc:
        raise _conflict(exc) from exc
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return profile.to_dict()


# PUT /chat_lore/{chat_id}/relations_enabled (D-3/§3.6.1: тумблер per-chat)
@chat_lore_router.put("/chat_lore/{chat_id}/relations_enabled")
async def set_relations_enabled(
    chat_id: int,
    payload: RelationsEnabledBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Включение/выключение тона по стадиям для чата (БЕЗ истории, D-2;
    optimistic 409 по updated_at профиля). Профиля нет → ensure-профиль
    (store.set_relations_enabled). Ответ — обновлённый профиль."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    try:
        profile = await store.set_relations_enabled(
            chat_id, payload.enabled, expected_updated_at=payload.updated_at)
    except ChatLoreConflict as exc:
        raise _conflict(exc) from exc
    except ChatLorePgUnavailable as exc:
        raise _pg_guard(exc) from exc
    return profile.to_dict()

