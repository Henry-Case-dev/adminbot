"""Раунд 10 (multi-chat-rbac-byok, F-7 §6, E1) — REST-модуль /api/access/*.

Матрица доступа — services/roles.access_for (глобальный срез + гранты
chat_admins); per-param права — services/access (default_matrix ⊕
DB-overrides ⊕ chat-переопределения). Все эндпоинты — под
Depends(get_tma_user) (401 без initData); менеджмент грантов и
param_permissions — ТОЛЬКО global admin (403 иначе); 404 — профиль/ключ
не найден; 422 — домен ролей/мусор; 409 — конфликт optimistic (нет в
этом модуле — запись chat_params идёт через F-7 set_chat_params).
"""
import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from services import access as access_srv
from services import chat_params, chat_keys, chat_usage
from services import roles as roles_srv
from services.roles import (
    ROLE_LOCAL_ADMIN,
    ROLE_MODERATOR,
)
from web.api.avatars import chat_display_info
from web.api.deps import get_cache, get_tma_user

logger = logging.getLogger(__name__)

access_router = APIRouter()

_CHAT_ROLE_DOMAIN = frozenset({ROLE_LOCAL_ADMIN, ROLE_MODERATOR})
_ROLETYPE_DOMAIN = frozenset(access_srv.ROLE_TYPES)
_FLAG_ROLE_DOMAIN = frozenset(access_srv.FLAG_ROLE_DOMAIN)

PROFILE_EXISTS_SQL = "SELECT 1 FROM chat_profiles WHERE chat_id = $1 LIMIT 1"
UPSERT_CHAT_ADMIN_SQL = (
    "INSERT INTO chat_admins (chat_id, telegram_id, role_name, added_by) "
    "VALUES ($1, $2, $3, $4) "
    "ON CONFLICT (chat_id, telegram_id) DO UPDATE "
    "SET role_name = EXCLUDED.role_name, added_by = EXCLUDED.added_by"
)
DELETE_CHAT_ADMIN_SQL = (
    "DELETE FROM chat_admins WHERE chat_id = $1 AND telegram_id = $2"
)
CHATS_FOR_USER_SQL = (
    "SELECT p.chat_id, p.is_active, a.role_name AS chat_role "
    "FROM chat_profiles p "
    "LEFT JOIN chat_admins a "
    "ON a.chat_id = p.chat_id AND a.telegram_id = $1 "
    "WHERE p.chat_id < 0 "          # F-14 (П.1): DM-строки не из PG — синтез ниже
    "ORDER BY p.chat_id"
)
ADMIN_EFF_SQL = (
    "INSERT INTO param_permissions (key, value) VALUES ($1, $2::jsonb) "
    "ON CONFLICT (key) DO NOTHING"
)
INSERT_HISTORY_SQL = (
    "INSERT INTO chat_lore_history (chat_id, field, changed_by, old_value, "
    "new_value) VALUES ($1, $2, $3, $4, $5)"
)


def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None


def _require_pg(cache) -> None:
    if _pool(cache) is None:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")


async def _profile_exists(conn, chat_id: int) -> bool:
    row = await conn.fetchrow(PROFILE_EXISTS_SQL, chat_id)
    return row is not None


class ChatAdminBody(BaseModel):
    telegram_id: int = Field(gt=0)
    role_name: str


class ParamPermissionBody(BaseModel):
    """Ре-дизайн 10.2, BUG-6 (spec §3.2.2/§3.2.4): НОВАЯ форма
    {view_roles: [..], edit_roles: [..]} (массивы доменных ролей; global_admin
    в массивах → 422) ЛИБО legacy {view_min_role, edit_min_role,
    hidden_from_local} (нормализуется сервером; БД-строки не трогаем —
    миграция на чтении)."""
    view_roles: list[str] | None = None
    edit_roles: list[str] | None = None
    view_min_role: str | None = None
    edit_min_role: str | None = None
    hidden_from_local: bool | None = None


class ChatParamPermissionBody(BaseModel):
    view_roles: list[str] | None = None
    edit_roles: list[str] | None = None
    view_min_role: str | None = None
    edit_min_role: str | None = None
    hidden_from_local: bool | None = None


def _value_from_payload(payload) -> dict:
    """Новая форма → {view_roles, edit_roles} (валидация домена: global_admin
    в массивах → 422; view_roles := view_roles ∪ edit_roles — «запись
    подразумевает чтение», spec §3.2.4). Legacy-поля → как есть (нормализуются
    на чтении)."""
    value = {}
    if payload.view_roles is not None or payload.edit_roles is not None:
        view_roles = list(payload.view_roles or [])
        edit_roles = list(payload.edit_roles or [])
        for role in (*view_roles, *edit_roles):
            if role not in _FLAG_ROLE_DOMAIN:
                raise HTTPException(
                    status_code=422,
                    detail=f"флаг-роль вне домена: {role}")
        allowed = set(view_roles) | set(edit_roles)
        value["view_roles"] = [
            r for r in access_srv.FLAG_ROLE_DOMAIN if r in allowed]
        value["edit_roles"] = edit_roles
    else:
        if payload.view_min_role is not None:
            if payload.view_min_role not in _ROLETYPE_DOMAIN:
                raise HTTPException(
                    status_code=422,
                    detail=f"role вне домена: {payload.view_min_role}")
            value["view_min_role"] = payload.view_min_role
        if payload.edit_min_role is not None:
            if payload.edit_min_role not in _ROLETYPE_DOMAIN:
                raise HTTPException(
                    status_code=422,
                    detail=f"role вне домена: {payload.edit_min_role}")
            value["edit_min_role"] = payload.edit_min_role
        if payload.hidden_from_local is not None:
            value["hidden_from_local"] = bool(payload.hidden_from_local)
    return value


def _chat_id_or_none(x_chat_id: str | None) -> int | None:
    if x_chat_id is None:
        return None
    try:
        return int(x_chat_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="X-Chat-Id — целое число")


@access_router.get("/me")
async def access_me(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Текущий доступ юзера: глобальная роль, роль в активном чате, список
    доступных чатов {chat_id, role} (spec §6)."""
    cache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    rows = []
    pool = _pool(cache)
    try:
        async with pool.acquire() as conn:
            db = await conn.fetch(CHATS_FOR_USER_SQL, user.id)
    except Exception:
        db = []
    for r in db:
        role = None
        if ctx.is_global_admin:
            role = roles_srv.ROLE_GLOBAL_ADMIN
        elif r.get("chat_role") in _CHAT_ROLE_DOMAIN:
            role = r["chat_role"]
        else:
            continue
        rows.append({"chat_id": r["chat_id"], "role": role})
    # F-14 (§3.2, П.1): синтез DM-строки для ЛЮБОГО авторизованного
    # (включая global admin) — свои ЛС настраиваются отдельно (AC-4).
    rows.append({"chat_id": user.id, "role": "dm"})
    return {
        "role_global": ctx.role_global,
        "role_chat": ctx.role_chat,
        "is_global_admin": ctx.is_global_admin,
        "is_local_admin": ctx.is_local_admin,
        "rank": ctx.rank,
        "chats": rows,
    }


@access_router.get("/chats")
async def access_chats(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Список чатов для TMA-селектора (spec §6): title best-effort (кэш
    chat_display_info), is_active, access"""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    pool = _pool(cache)
    try:
        async with pool.acquire() as conn:
            db = await conn.fetch(CHATS_FOR_USER_SQL, user.id)
    except Exception:
        db = []
    out = []
    for r in db:
        if ctx.is_global_admin:
            access = "global_admin"
        elif r.get("chat_role") in _CHAT_ROLE_DOMAIN:
            access = r["chat_role"]
        else:
            continue
        info = {}
        try:
            info = await chat_display_info(r["chat_id"])
        except Exception:
            pass
        out.append({
            "chat_id": r["chat_id"],
            "title": info.get("title") or f"Чат {r['chat_id']}",
            "photo_file_id": info.get("photo_file_id"),
            "is_active": bool(r["is_active"]),
            "access": access,
        })
    # F-14 (§3.2, П.1): DM-строка — селектор TMA (запись «Личные
    # сообщения», access:'dm'); title синтезирован (chat_display_info НЕ
    # зовём — ЛС нет в Bot API-кэше групп).
    out.append({
        "chat_id": user.id,
        "title": "Личные сообщения",
        "photo_file_id": None,
        "is_active": True,
        "access": "dm",
        "is_dm": True,
    })
    return out


@access_router.post("/chats/{chat_id}/admins")
async def chat_admins_add(
    chat_id: int,
    request: Request,
    payload: ChatAdminBody,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Только global admin: upsert chat_admins + роль (domain local_admin/
    moderator; 422 иначе) + история field='chat_admin'; 404 — нет профиля."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403, detail="доступ только для global admin")
    if payload.role_name not in _CHAT_ROLE_DOMAIN:
        raise HTTPException(status_code=422,
                            detail=f"роль вне домена: {payload.role_name}")
    _require_pg(cache)
    try:
        async with _pool(cache).acquire() as conn:
            async with conn.transaction():
                if not await _profile_exists(conn, chat_id):
                    raise HTTPException(status_code=404,
                                        detail="профиль чата не найден")
                exists = await conn.fetchrow(
                    "SELECT role_name FROM chat_admins "
                    "WHERE chat_id = $1 AND telegram_id = $2",
                    chat_id, payload.telegram_id)
                old_role = exists["role_name"] if exists else None
                await conn.execute(UPSERT_CHAT_ADMIN_SQL, chat_id,
                                   payload.telegram_id, payload.role_name,
                                   user.id)
                await conn.execute(
                    INSERT_HISTORY_SQL, chat_id, "chat_admin", user.id,
                    old_role or "", payload.role_name)
    except HTTPException:
        raise
    except Exception:
        logger.exception("[access] admin upsert failed | chat=%s", chat_id)
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    logger.info("[access] chat admin upsert | chat=%s tg=%s role=%s by=%s",
                chat_id, payload.telegram_id, payload.role_name, user.id)
    return {"chat_id": chat_id, "telegram_id": payload.telegram_id,
            "role_name": payload.role_name}


@access_router.delete("/chats/{chat_id}/admins/{telegram_id}")
async def chat_admins_remove(
    chat_id: int,
    telegram_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Только global admin: удаление гранта + история."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403, detail="доступ только для global admin")
    _require_pg(cache)
    try:
        async with _pool(cache).acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchrow(
                    "SELECT role_name FROM chat_admins "
                    "WHERE chat_id = $1 AND telegram_id = $2",
                    chat_id, telegram_id)
                await conn.execute(DELETE_CHAT_ADMIN_SQL, chat_id, telegram_id)
                if exists is not None:
                    await conn.execute(
                        INSERT_HISTORY_SQL, chat_id, "chat_admin", user.id,
                        exists["role_name"] or "", "")
    except Exception:
        logger.exception("[access] admin remove failed | chat=%s", chat_id)
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    logger.info("[access] chat admin removed | chat=%s tg=%s by=%s",
                chat_id, telegram_id, user.id)
    return {"removed": True}


@access_router.get("/param_permissions")
async def param_permissions_list(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Эффективная матрица key → {view_roles, edit_roles, default} (новая
    форма; hidden_from_local БОЛЬШЕ не отдаётся) — ТОЛЬКО global admin;
    дефолт ⊕ перекрытия (строки таблицы НЕ сидятся, см. services/access.py)."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403, detail="доступ только для global admin")
    db = await access_srv.db_override_map(cache.pg)
    from services.param_catalog import (
        CONFIG_TAB_TITLES,
        GROUPS,
        REGISTRY,
        group_tab,
    )
    groups_by_id = {g.id: (g.title_ru, g.category, g.order) for g in GROUPS}
    items = {}
    for spec_key in sorted(REGISTRY):
        spec = REGISTRY[spec_key]
        if spec.category is None:
            continue
        matrix = access_srv.effective_matrix(spec.pg_key, db.get(spec.pg_key))
        matrix["default"] = spec.pg_key not in db
        # OD10/T-1130: метаданные группировки матрицы по СЕКЦИЯМ мини-аппа
        # (config-вкладки TAB_RULES), а не по внутренним категориям каталога.
        gtitle, gcat, gorder = groups_by_id.get(
            spec.group, (spec.group, spec.category, 999))
        tab = group_tab(spec.group)
        matrix["category"] = spec.category
        matrix["group"] = spec.group
        matrix["group_title"] = gtitle
        matrix["group_order"] = gorder
        matrix["tab"] = tab
        matrix["tab_title"] = CONFIG_TAB_TITLES.get(tab) if tab else None
        matrix["title"] = spec.title_ru
        matrix["secret"] = spec.secret
        items[spec.pg_key] = matrix
    return {"items": items}


@access_router.put("/param_permissions/{key}")
async def param_permissions_put(
    key: str,
    request: Request,
    payload: ParamPermissionBody,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Только global admin: перекрытие дефолта (INSERT ON CONFLICT).
    Принимает ОБЕ формы (новая/legacy), ответ — нормализованная новая."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403, detail="доступ только для global admin")
    value = _value_from_payload(payload)
    if not value:
        raise HTTPException(status_code=422, detail="пустое тело — нечего сохранить")
    _require_pg(cache)
    try:
        await access_srv.upsert_param_permission(cache.pg, key, value)
    except Exception:
        logger.exception("[access] param_permission upsert failed | key=%s", key)
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    logger.info("[access] param_permission upsert | key=%s by=%s", key, user.id)
    return {"key": key, **access_srv._normalize_perms(value)}


@access_router.delete("/param_permissions/{key}")
async def param_permissions_delete(
    key: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Только global admin (spec §3.2.4): удаляет строку-оверрайд (404 — нет
    строки) → ключ возвращается к DEFAULT_MATRIX."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403, detail="доступ только для global admin")
    _require_pg(cache)
    try:
        removed = await access_srv.delete_param_permission(cache.pg, key)
    except Exception:
        logger.exception("[access] param_permission delete failed | key=%s", key)
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    if not removed:
        raise HTTPException(status_code=404,
                            detail=f"нет override-строки: {key}")
    logger.info("[access] param_permission reset | key=%s by=%s", key, user.id)
    return {"key": key, "reset": True}


@access_router.post("/chats/{chat_id}/param_permissions/{key}")
async def chat_param_permission_put(
    chat_id: int,
    key: str,
    request: Request,
    payload: ChatParamPermissionBody,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Только global admin: чат-скоуп прав в chat_params.perm_overrides
    (не дублируется в таблицу — spec §4.2; запись через set_chat_params)."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403, detail="доступ только для global admin")
    value = _value_from_payload(payload)
    if not value:
        raise HTTPException(status_code=422, detail="пустое тело — нечего сохранить")
    _require_pg(cache)
    try:
        root = await chat_params.set_chat_params(
            chat_id,
            {"perm_overrides": {key: value}},
            changed_by=user.id,
            pg=cache.pg)
    except chat_params.ChatParamsConflict as exc:
        raise HTTPException(status_code=409,
                            detail={"code": "conflict",
                                    "current_updated_at": exc.current_updated_at})
    except Exception:
        logger.exception("[access] chat param_permission failed | chat=%s | key=%s",
                         chat_id, key)
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    logger.info("[access] chat param_permission upsert | chat=%s key=%s by=%s",
                chat_id, key, user.id)
    return {"chat_id": chat_id, "key": key, **access_srv._normalize_perms(value)}
