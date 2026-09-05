"""Раунд 7 (chat-lore-management-v2, T-779, E1) — REST «Лор чатов» /api/chat_lore.

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
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config.settings import settings
from services import lore_runtime
from services.chat_lore_store import ChatLoreConflict, ChatLorePgUnavailable
from services.permissions import Permissions
from web.api.deps import get_cache, get_tma_user

logger = logging.getLogger(__name__)

chat_lore_router = APIRouter()

_MANUAL_MAX_CHARS = 4000            # FR-2: cap ручной правки (422)
_PERIOD_MIN = 1                     # auto_period_hours/auto_window_hours
_PERIOD_MAX = 720                   # валидация 1..720 (422; spec §3.8)
_PREVIEW_CHARS = 80                 # превью в списке чатов


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
    updated_at: str                  # Q8: обязательна в теле


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
    return [
        {
            "chat_id": p.chat_id,
            "manual_preview": _preview(p.manual_lore),
            "auto_preview": _preview(p.auto_lore),
            "has_manual": bool((p.manual_lore or "").strip()),
            "has_auto": bool((p.auto_lore or "").strip()),
            "auto_enabled": p.auto_enabled,
            "is_active": p.is_active,
            "updated_at": p.updated_at,
        }
        for p in profiles
    ]


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
    period/window 1..720 → 422)."""
    cache = get_cache(request)
    store, _cache_c, _worker = _components()
    await _require_chat(cache, store, user, chat_id)
    try:
        profile = await store.update_settings(
            chat_id,
            auto_enabled=payload.auto_enabled,
            auto_period_hours=payload.auto_period_hours,
            auto_window_hours=payload.auto_window_hours,
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

