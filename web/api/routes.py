"""Epic 85 (84.5 + дельты 84.13/84.14, T-617/T-638) — REST-эндпоинты /api/*.

Все маршруты (кроме /api/health) — за TMA-initData (get_tma_user); права —
requires_permission по 84.14.2. Коды ошибок по 84.5: 400/401/403/404/409/
422/500. Маскировка секретов (84.12.4): значение ключа категории keys без
права на КОНКРЕТНЫЙ ключ → {«configured», «last4»} — никогда в открытую.
"""
import datetime
import json
import logging
from typing import Any, Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aiogram.utils.web_app import WebAppUser

from services import access as access_srv
from services import chat_keys, chat_params, chat_usage, param_catalog
from services import roles as roles_srv
from services.config_cache import (
    ConfigCache,
    ConfigCacheUnavailableError,
    _INFO_KEY,
)
from services.debug_config import (
    build_dump,
    is_pg_only,
    resolve_param_key,
)
from services.param_catalog import (
    CATEGORIES,
    CATEGORY_CONTENT,
    CATEGORY_KEYS,
    CATEGORY_PROMPTS,
    GROUPS,
    get_by_pg_key,
    group_order,
    known_param_keys,
    known_secret_keys,
    known_sections,
    resolve_progressive_level,
)
from services.permissions import (
    ACTION_IDS,
    ACTIONS_TREE,
    Permissions,
    RoleGuardError,
    guard_last_wildcard,
    requires_permission as match_permission,
    validate_permissions,
)
from web.api.deps import (
    can_edit_param,
    can_view_key_value,
    get_cache,
    get_tma_user,
    requires_permission,
)

logger = logging.getLogger(__name__)

api_router = APIRouter()

_RICH_TEXT_LIMIT = 32768   # лимит rich-HTML (53.3, T-447; 84.13.4)

_ACCESS_SECTION_TITLE = "Управление доступом"


# ── Pydantic-модели ─────────────────────────────────────────────────────────

class ConfigItemUpdate(BaseModel):
    key: str
    value: Any


class ConfigUpdateRequest(BaseModel):
    items: list[ConfigItemUpdate]
    # Раунд 10 (F-7 §6): optimistic-метка чата при X-Chat-Id (409-протокол).
    updated_at: str | None = None


class AdminUpsert(BaseModel):
    telegram_id: int
    role_name: str


class AdminRemove(BaseModel):
    telegram_id: int


class RoleUpsert(BaseModel):
    role_name: str = Field(min_length=1, max_length=64)
    permissions: dict[str, Any] = Field(default_factory=dict)
    is_custom: bool | None = None


class InfoUpdate(BaseModel):
    html: str


class ConfigChatDelete(BaseModel):
    key: str


class ChatKeyBody(BaseModel):
    key_name: str
    value: str = ""


class ChatKeyDelete(BaseModel):
    key_name: str


class ChatKeysStatus(BaseModel):
    pass


# ── helpers ─────────────────────────────────────────────────────────────────

def _coerce_value(spec, raw) -> Any:
    """Конвертация значения к типу каталога; неудача → ValueError (422)."""
    if raw is None:
        raise ValueError("value не может быть null")
    if spec.type == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        if isinstance(raw, int) and raw in (0, 1):
            return bool(raw)
        raise ValueError(f"ожидается bool, получено {type(raw).__name__}")
    if spec.type == "int":
        if isinstance(raw, bool):
            raise ValueError("ожидается int, получено bool")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
            return int(raw)
        raise ValueError(f"ожидается int, получено {type(raw).__name__}")
    if spec.type == "float":
        if isinstance(raw, bool):
            raise ValueError("ожидается float, получено bool")
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw.strip())
            except ValueError:
                pass
        raise ValueError(f"ожидается float, получено {type(raw).__name__}")
    if spec.type == "json":
        if isinstance(raw, (dict, list, tuple)):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                return raw
        return raw
    if isinstance(raw, str):
        return raw
    return str(raw)


def _chat_id_or_none(x_chat_id: str | None) -> int | None:
    """X-Chat-Id: прозрачный заголовок; мусор → 422; отсутствует → None
    (ровно старое поведение — глобальный конфиг, F-7 §6)."""
    if x_chat_id is None:
        return None
    try:
        return int(x_chat_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="X-Chat-Id — целое число")


def _mask_secret(value, telegram_id: int, pg_key: str, cache: ConfigCache) -> dict:
    """84.12.4 + ФИКС 2026-09-03: ЕДИНЫЙ контракт — секреты ВСЕГДА отдаются
    как {"configured": bool, "last4": str|None}; полное значение (даже для
    admin/wildcard) в фронт НЕ отдаём — замена только через POST /api/config."""
    if not value:
        return {"configured": False, "last4": None}
    if isinstance(value, dict) and set(value) <= {"configured", "last4"}:
        return {"configured": bool(value.get("configured")),
                "last4": value.get("last4")}
    return {"configured": True, "last4": str(value)[-4:]}


# ── Health / me ─────────────────────────────────────────────────────────────

@api_router.get("/health")
async def health():
    """84.5: без auth (ngrok/мониторинг)."""
    return {"status": "ok"}


@api_router.get("/me")
async def me(request: Request, user: Annotated[WebAppUser, Depends(get_tma_user)]):
    """84.5: {telegram_id, username, first_name, last_name, photo_url,
    role_name, permissions, is_custom} (UI-полировка: + last_name/photo_url)."""
    cache: ConfigCache = get_cache(request)
    role_name = cache.get_role(user.id)
    if role_name is None:
        role_name = "user"
    role = cache.roles().get(role_name)
    permissions = (role or {}).get("permissions", {})
    is_custom = bool((role or {}).get("is_custom", False))
    return {
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        # UI-полировка TMA: last_name/photo_url (WebAppUser-поля initData;
        # photo_url может быть None — фронт тогда берёт /api/avatar/user/*)
        "last_name": user.last_name,
        "photo_url": user.photo_url,
        "role_name": role_name,
        "permissions": permissions,
        "is_custom": is_custom,
    }


# ── Config ──────────────────────────────────────────────────────────────────

@api_router.get("/config")
async def get_config(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """84.5: любая роль; секреты маскируются (84.12.4 + 2026-09-03: всегда
    {configured,last4}). Плюс title/type из param_catalog — фронту для
    рендера форм (84.7). 84.24 (02.09.2026): groups[] + group/description
    в items; сортировка (category, group.order, title_ru).
    Раунд 10 (F-7 §6): X-Chat-Id → слой чата: per-param фильтры
    (can_view_param: hidden_from_local/min-роль view; keys-секция для
    локального админа — полностью исключается), значения = chat_params
    (overrides) → глобал → дефолт; 403 «нет доступа к чату»."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    ctx = None
    chat_root: dict = {}
    db_overrides: dict = {}
    try:
        db_overrides = await access_srv.db_override_map(cache.pg)
    except Exception:
        db_overrides = {}
    if chat_id is not None:
        ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
        if not access_srv.can_access_chat(ctx):
            raise HTTPException(status_code=403, detail="нет доступа к чату")
        chat_root = await chat_params.get_all_chat_params(chat_id)
    else:
        # F-7 §1.2-2: глобальный путь тоже требует роль-контекст — иначе
        # секрет-ключи (в т.ч. {configured,last4} global key) были видны
        # любой TMA-роли (фикс S1).
        ctx = await roles_srv.access_for(user.id, cache=cache)
    items = []
    for key, value in sorted(cache.get_all().items()):
        spec = get_by_pg_key(key)
        category = spec.category if spec else key.split(".")[0]
        secret = bool(spec.secret) if spec else category == CATEGORY_KEYS
        if chat_id is not None and ctx is not None:
            # F-7 §6: фильтр видимости per-chat (hidden/min-роль view);
            # keys-секция: локальному админу — полностью исключается
            if secret and not ctx.is_global_admin:
                continue
            matrix = access_srv.effective_matrix(
                key, db_overrides.get(key),
                (chat_root.get("perm_overrides") or {}).get(key))
            if not access_srv.can_view_param(ctx, matrix):
                continue
        elif ctx is not None:
            # ФИКС S1 (F-7 §1.2-2/§3.1): на ГЛОБАЛЬНОМ пути ключи-секреты
            # отдаются только глобальному админу; local/moderator/user не
            # видят глобальный ключ НИ в каком виде (в т.ч. без last4).
            if secret and not ctx.is_global_admin:
                continue
        chat_source = ""
        matrix = access_srv.effective_matrix(
            key, db_overrides.get(key),
            (chat_root.get("perm_overrides") or {}).get(key)
            if chat_id is not None else None)
        if secret:
            value = _mask_secret(value, user.id, key, cache)
        elif chat_id is not None:
            overrides = chat_root.get("overrides") or {}
            if key in overrides:
                is_per_chat = bool(spec.per_chat) if spec else False
                if is_per_chat:
                    value = overrides[key]
                    chat_source = "chat"
        items.append({"key": key, "value": value, "category": category,
                      "secret": secret,
                      "chat_source": chat_source,
                      "title": spec.title_ru if spec else key,
                      "type": spec.type if spec else "str",
                      # F7: updated_at из PG; in-memory/деградация — null
                      "updated_at": cache.get_updated_at(key),
                      # 84.24: группа и простое описание (для ключей без
                      # spec — пустые; фронт складывает в «Прочее»)
                      "group": spec.group if spec else "",
                      "description": spec.description if spec else "",
                      # Эпик 04.09.2026 (3.1/FR-28): виджет рендера (""
                      # дефолт | "keyvalue" — KV-редактор пар)
                      "widget": spec.widget if spec else "",
                      # Раунд 10 (F-7 §4.4/F-11 §4.1): per-chat-граница и
                      # уровень прогрессивного раскрытия (без значений)
                      "per_chat": bool(spec.per_chat) if spec else False,
                      "progressive_level":
                          resolve_progressive_level(spec) if spec else "basic",
                      # min-роли (эффективная матрица) — для роль-пикера TMA
                      "view_min_role": matrix.get("view_min_role", "user"),
                      "edit_min_role": matrix.get("edit_min_role",
                                                  "moderator"),
                      "hidden_from_local": bool(
                          matrix.get("hidden_from_local", False)),
                      "chat_updated_at": chat_root.get("meta", {}).get(
                          "updated_at") if chat_id is not None else None})
    # 84.24.3: сортировка (category, group.order, title_ru)
    items.sort(key=lambda it: (it["category"], group_order(it["group"]),
                               it["title"]))
    # 84.24.3: метаданные групп для категорий, присутствующих в items
    present = {it["category"] for it in items}
    groups = [
        {"id": g.id, "category": g.category, "title": g.title_ru,
         "description": g.description, "order": g.order}
        for g in GROUPS if g.category in present
    ]
    groups.sort(key=lambda g: g["order"])
    out = {"items": items, "groups": groups}
    if chat_id is not None:
        out["chat_id"] = chat_id
        out["updated_at"] = await chat_params.get_chat_updated_at(chat_id)
        out["ctx"] = {
            "role_chat": ctx.role_chat if ctx else None,
            "is_local_admin": bool(ctx and ctx.is_local_admin),
            "is_global_admin": bool(ctx and ctx.is_global_admin),
        }
    return out


@api_router.post("/config")
async def post_config(
    request: Request,
    payload: ConfigUpdateRequest,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """84.5: право — на КАЖДЫЙ ключ (param./key.<категория>.<ключ> покрывается
    секцией категории / конкретным правом; пустая роль → 403 на каждый ключ).

    Раунд 10 (F-7 §6): X-Chat-Id → запись в chat_params (атомарная, в ОДНУ
    операцию set_chat_params с полной валидацией ДО записи): keys.* → 422
    (это путь chat_keys, не сюда); per_chat=False → 422 «ключ нельзя
    переносить на уровень чата»; per-param min-роли (can_edit_param по
    матрице чата: local admin/moderator — per-параметры, global admin —
    всё); optimistic 409; hidden_from_local запись локальным → 403."""
    cache: ConfigCache = get_cache(request)
    if not payload.items:
        raise HTTPException(status_code=422, detail="items пуст")
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return await _post_config_global(request, payload, user)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not access_srv.can_access_chat(ctx):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    try:
        db_overrides = await access_srv.db_override_map(cache.pg)
    except Exception:
        db_overrides = {}
    root = await chat_params.get_all_chat_params(chat_id)
    chat_overrides = dict(root.get("perm_overrides") or {})
    patch_overrides = {}
    for item in payload.items:
        spec = get_by_pg_key(item.key)
        if spec is None or spec.category is None:
            raise HTTPException(status_code=422,
                                detail=f"неизвестный ключ: {item.key}")
        if spec.category == CATEGORY_KEYS:
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: ключ-секрет задаётся через "
                       "/api/config/keys/own (BYOK-путь)")
        if not spec.per_chat:
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: ключ нельзя переносить на уровень чата")
        matrix = access_srv.effective_matrix(
            item.key, db_overrides.get(item.key),
            chat_overrides.get(item.key))
        if not access_srv.can_edit_param(ctx, matrix):
            raise HTTPException(status_code=403,
                                detail=f"нет права на {item.key}")
        if matrix.get("hidden_from_local") and not ctx.is_global_admin:
            raise HTTPException(status_code=403,
                                detail=f"{item.key} скрыт от локальных админов")
        try:
            value = _coerce_value(spec, item.value)
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail=f"{item.key}: {exc}")
        if spec.type == "str" and spec.category in (CATEGORY_PROMPTS,
                                                    CATEGORY_CONTENT):
            if not isinstance(value, str) or not value.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"{item.key}: промпт не может быть пустым")
        patch_overrides[item.key] = value
    if not patch_overrides:
        raise HTTPException(status_code=422, detail="items пуст")
    new_overrides = dict(chat_overrides)
    new_overrides.update(patch_overrides)
    meta = dict(root.get("meta") or {})
    meta["updated_by"] = user.id
    try:
        new_root = await chat_params.set_chat_params(
            chat_id, {"overrides": new_overrides, "meta": meta},
            changed_by=user.id, pg=cache.pg,
            expected_updated_at=payload.updated_at)
    except chat_params.ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    logger.info("[api] config chat updated | chat=%s | keys=%d | by=%s",
                chat_id, len(patch_overrides), user.id)
    return {"updated": sorted(patch_overrides),
            "chat_id": chat_id,
            "updated_at": await chat_params.get_chat_updated_at(chat_id)}


@api_router.get("/config/params-meta")
async def get_params_meta(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Раунд 10 (F-7 §4.4): мета-каталог {pg_key: {per_chat,
    progressive_level, group, title, type, secret_mask}} — без значений
    секретов (для TMA-витрины и F-11 прогрессивного раскрытия)."""
    items = {}
    for spec_key in sorted(param_catalog.REGISTRY):
        spec = param_catalog.REGISTRY[spec_key]
        if spec.category is None:
            continue
        items[spec.pg_key] = {
            "per_chat": bool(spec.per_chat),
            "progressive_level": resolve_progressive_level(spec),
            "group": spec.group,
            "title": spec.title_ru,
            "type": spec.type,
            "secret_mask": bool(spec.secret or spec.category == CATEGORY_KEYS),
        }
    return {"items": items}


@api_router.get("/config/keys/own")
async def config_keys_own(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): маски СОБСТВЕННЫХ ключей чата (R17: никогда raw).
    Права: local admin чата / global admin."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not (ctx.is_global_admin or ctx.is_local_admin):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    return {"keys": await chat_keys.list_own_keys(cache.pg, chat_id)}


@api_router.put("/config/keys/own")
async def config_keys_own_put(
    request: Request,
    payload: ChatKeyBody,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): запись BYOK-ключа чата (insert-or-replace).
    422 key_name вне whitelist; 403 чужие права; маска в ответе (R17)."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not (ctx.is_global_admin or ctx.is_local_admin):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    try:
        mask = await chat_keys.set_chat_key(cache.pg, chat_id,
                                            payload.key_name, payload.value,
                                            changed_by=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    logger.info("[api] chat key upsert | chat=%s | key=%s | by=%s",
                chat_id, payload.key_name, user.id)
    return mask


@api_router.delete("/config/keys/own/{key_name}")
async def config_keys_own_delete(
    key_name: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): удаление BYOK-ключа чата."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not (ctx.is_global_admin or ctx.is_local_admin):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    try:
        removed = await chat_keys.delete_chat_key(cache.pg, chat_id,
                                                  key_name, changed_by=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"removed": removed}


@api_router.get("/config/keys/status")
async def config_keys_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): статусы ключей чата. Глобальный ключ в поле
    `global` — ТОЛЬКО для global admin (локальный его НЕ видит — §1.2-2)."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not access_srv.can_access_chat(ctx):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    root = await chat_params.get_all_chat_params(chat_id)
    own = {r["key_name"]: r for r in
           await chat_keys.list_own_keys(cache.pg, chat_id)}
    allow_global = bool((root.get("keys") or {}).get("allow_global", True))
    global_key_value = cache.get_all().get("keys.llm_api_key")
    out = {
        "own": own,
        "allow_global": allow_global,
        "budgets": await chat_usage.key_status(cache.pg, chat_id),
    }
    if ctx.is_global_admin:
        out["global"] = _mask_secret(global_key_value, user.id,
                                     "keys.llm_api_key", cache)
    return out


@api_router.delete("/config/chat/{key}")
async def delete_chat_param(
    key: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): сброс override чата на глобальный
    (jsonb_remove('overrides', key)); 404 — override отсутствует;
    403 — чужие права; 409 optimistic."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not (ctx.is_global_admin or ctx.is_local_admin):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    root = await chat_params.get_all_chat_params(chat_id)
    overrides = dict(root.get("overrides") or {})
    if key not in overrides:
        raise HTTPException(status_code=404,
                            detail=f"нет override: {key}")
    overrides.pop(key, None)
    try:
        await chat_params.set_chat_params(
            chat_id, {"overrides": overrides,
                      "meta": {"updated_by": user.id}},
            changed_by=user.id, pg=cache.pg)
    except chat_params.ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    logger.info("[api] chat param reset | chat=%s | key=%s | by=%s",
                chat_id, key, user.id)
    return {"reset": key, "chat_id": chat_id}


async def _post_config_global(request: Request, payload: ConfigUpdateRequest,
                              user: WebAppUser) -> dict:
    """Старый глобальный путь (no X-Chat-Id) — без изменений ровно."""
    cache: ConfigCache = get_cache(request)
    updated = []
    for item in payload.items:
        spec = get_by_pg_key(item.key)
        if spec is None or spec.category is None:
            raise HTTPException(status_code=422,
                                detail=f"неизвестный ключ: {item.key}")
        if spec.category == CATEGORY_KEYS:
            allowed = can_view_key_value(cache, user.id, item.key)
        else:
            allowed = can_edit_param(cache, user.id, item.key)
        if not allowed:
            raise HTTPException(status_code=403,
                                detail=f"нет права на {item.key}")
        if not cache.pg_available:
            raise HTTPException(status_code=503,
                                detail="PostgreSQL недоступен (R6)")
        try:
            value = _coerce_value(spec, item.value)
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail=f"{item.key}: {exc}")
        if spec.type == "str" and spec.category in (CATEGORY_PROMPTS,
                                                    CATEGORY_CONTENT):
            if not isinstance(value, str) or not value.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"{item.key}: промпт не может быть пустым")
        await cache.set(item.key, value, spec.category)
        updated.append(item.key)
        logger.info("[api] config updated | key=%s | by=%s", item.key, user.id)
    return {"updated": updated}


# ── Admins ──────────────────────────────────────────────────────────────────

@api_router.get("/admins")
async def get_admins(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.5 + F7: полные карточки (added_by/created_at; при деградации — null)."""
    cache: ConfigCache = get_cache(request)
    return {"admins": cache.admins_full()}


@api_router.post("/admins")
async def post_admins(
    request: Request,
    payload: AdminUpsert,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.5: upsert; несуществующая роль → 422; added_by = текущий юзер."""
    cache: ConfigCache = get_cache(request)
    if payload.role_name not in cache.roles():
        raise HTTPException(status_code=422,
                            detail=f"несуществующая роль: {payload.role_name}")
    try:
        await cache.upsert_admin(payload.telegram_id, payload.role_name,
                                 added_by=user.id)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    return {"telegram_id": payload.telegram_id, "role_name": payload.role_name}


@api_router.post("/admins/remove")
async def remove_admin(
    request: Request,
    payload: AdminRemove,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.5: {removed:true}; guard'ы: последний админ в списке → 409 (F8),
    последний wildcard-админ → 409 (84.14.4)."""
    cache: ConfigCache = get_cache(request)
    target_role = cache.get_role(payload.telegram_id)
    if target_role is None:
        raise HTTPException(status_code=404, detail="админ не найден")
    if len(cache.admins()) <= 1:
        # F8: нельзя оставить систему без единого админа вообще
        raise HTTPException(
            status_code=409,
            detail="нельзя удалить последнего админа")
    target_perms = cache.get_permissions(target_role) or Permissions.from_dict({})
    if target_perms.wildcard:
        other_wildcard = any(
            tg != payload.telegram_id
            and (cache.get_permissions(cache.get_role(tg) or "") or
                 Permissions.from_dict({})).wildcard
            for tg in cache.admins()
        )
        if not other_wildcard:
            raise HTTPException(
                status_code=409,
                detail="нельзя удалить последнего админа с полным доступом")
    try:
        removed = await cache.remove_admin(payload.telegram_id)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    return {"removed": removed}


# ── Roles ───────────────────────────────────────────────────────────────────

@api_router.get("/roles")
async def get_roles(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    cache: ConfigCache = get_cache(request)
    return {
        "roles": [
            {"role_name": name, "permissions": role["permissions"],
             "is_custom": role["is_custom"]}
            for name, role in sorted(cache.roles().items())
        ]
    }


@api_router.post("/roles")
async def post_roles(
    request: Request,
    payload: RoleUpsert,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.14.4: upsert ЛЮБОЙ роли (включая системные); guard последней
    wildcard → 409; неизвестный id права → 422; is_custom — флаг
    происхождения (для новой роли из запроса/дефолт true, для существующей
    сохраняется)."""
    cache: ConfigCache = get_cache(request)
    try:
        validate_permissions(
            payload.permissions,
            known_sections=known_sections(),
            known_params=known_param_keys(),
            known_keys=known_secret_keys(),
            known_actions=ACTION_IDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    existing = cache.roles().get(payload.role_name)
    new_perms = Permissions.from_dict(payload.permissions)
    if existing is not None:
        old_perms = Permissions.from_dict(existing["permissions"])
        if old_perms.wildcard and not new_perms.wildcard:
            try:
                guard_last_wildcard(
                    {name: Permissions.from_dict(r["permissions"])
                     for name, r in cache.roles().items()},
                    payload.role_name, new_perms)
            except RoleGuardError as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc))
        is_custom = bool(existing["is_custom"])   # сервер сохраняет флаг (84.14.4)
    else:
        is_custom = payload.is_custom if payload.is_custom is not None else True

    try:
        await cache.upsert_role(payload.role_name, new_perms.to_dict(), is_custom)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    logger.info("[api] role upserted | role=%s | by=%s", payload.role_name, user.id)
    return {"role_name": payload.role_name, "permissions": new_perms.to_dict(),
            "is_custom": is_custom}


@api_router.get("/roles/tree")
async def get_roles_tree(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
    role_name: str | None = Query(default=None),
):
    """84.14.4 (бэкенд-часть T-640): дерево доступных прав из param_catalog +
    ACTIONS_TREE; checked — отметки прав роли (для чекбокс-конструктора)."""
    cache: ConfigCache = get_cache(request)
    target_perms: Permissions | None = None
    if role_name:
        target_perms = cache.get_permissions(role_name)
        if target_perms is None:
            raise HTTPException(status_code=404,
                                detail=f"роль не найдена: {role_name}")

    def checked(required: str) -> bool:
        if target_perms is None:
            return False
        return match_permission(target_perms, required)

    sections = []
    for category in CATEGORIES:
        specs = param_catalog.by_category(category)
        if not specs:
            continue
        params = []
        keys = []
        for spec in sorted(specs, key=lambda s: s.pg_key):
            node = {"key": spec.pg_key, "title": spec.title_ru,
                    "type": spec.type, "secret": spec.secret,
                    "checked": checked(f"param.{spec.pg_key}")}
            if category == CATEGORY_KEYS:
                node["checked"] = checked(f"key.{spec.pg_key}")
                keys.append(node)
            else:
                params.append(node)
        sections.append({
            "id": category,
            "title": _category_title(category),
            "checked": checked(f"section.{category}"),
            "params": params,
            "keys": keys,
        })
    sections.append({
        "id": "access",
        "title": _ACCESS_SECTION_TITLE,
        "checked": checked("section.access"),
        "params": [],
        "keys": [],
    })
    actions = [
        {"id": action["id"], "title": action["title"],
         "checked": checked(f"action.{action['id']}")}
        for action in ACTIONS_TREE
    ]
    return {"sections": sections, "actions": actions}


# ── Info («Как это работает», 84.13) ────────────────────────────────────────

@api_router.get("/info")
async def get_info(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """84.13.4: публичный (TMA-auth, ЛЮБАЯ роль, без requires_permission)."""
    cache: ConfigCache = get_cache(request)
    value = cache.get(_INFO_KEY)
    if isinstance(value, dict):
        return {
            "key": _INFO_KEY,
            "html": value.get("html", ""),
            "updated_at": value.get("updated_at"),
            "updated_by": value.get("updated_by"),
        }
    return {"key": _INFO_KEY, "html": value or "", "updated_at": None,
            "updated_by": None}


@api_router.post("/info")
async def post_info(
    request: Request,
    payload: InfoUpdate,
    user: Annotated[WebAppUser, Depends(requires_permission("edit_info"))],
):
    """84.13.4: право edit_info (по сиду — только admin через wildcard);
    лимит 32768 (прецедент _RICH_TEXT_LIMIT 53.3); пусто → 422.
    F5: запись через InfoService.save_text() (файл legacy-зеркало + PG) —
    при PG down файл-фолбек не устаревает. F18: PG down → 503 (не 200)."""
    cache: ConfigCache = get_cache(request)
    html = payload.html
    if not html.strip():
        raise HTTPException(status_code=422, detail="html пуст")
    if len(html) > _RICH_TEXT_LIMIT:
        raise HTTPException(status_code=422,
                            detail=f"html превышает {_RICH_TEXT_LIMIT} символов")
    if not cache.pg_available:
        # F18: без PG значение не персистентно — честный 503
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    try:
        from services.info_service import InfoService
        InfoService().save_text(html)          # файл + кэш (84.13.3, F5)
    except OSError:
        logger.exception("[api] info file save failed | by=%s", user.id)
        raise HTTPException(status_code=500, detail="сохранение файла не удалось")
    value = {
        "html": html,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "updated_by": user.id,
    }
    try:
        await cache.set(_INFO_KEY, value, "content")
    except Exception:
        logger.exception("[api] info save failed | by=%s", user.id)
        raise HTTPException(status_code=500, detail="сохранение не удалось")
    logger.info("[api] info updated | by=%s | chars=%d", user.id, len(html))
    return {"key": _INFO_KEY, "updated_at": value["updated_at"],
            "updated_by": user.id}


def _category_title(category: str) -> str:
    return {
        "prompts": "Промпты",
        "models": "Модели и провайдеры",
        "keys": "API-ключи",
        "limits": "Лимиты и кулдауны",
        "flags": "Флаги модулей",
        "reactions": "Реакции и персоны",
        "content": "Контент",
        "memory": "Память",
    }.get(category, category)


# ── Status (84.11.4, T-631): публично для любого валидного TMA-юзера ────────

@api_router.get("/status")
async def get_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сводка bot/server/llm/uptime. БЕЗ requires_permission (84.11 —
    RBAC-исключение); ключи LLM — только configured/last4 для global admin,
    {configured} для остальных (фикс S2, F-7 §1.2-2). X-Chat-Id (опц.) —
    F-9 §6 телеметрия PERMsoc для контекста чата."""
    from services.status_service import status
    from services import roles as roles_srv
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    ctx = None
    try:
        ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    except Exception:
        ctx = None
    return await status.build_snapshot(cache, ctx=ctx, chat_id=chat_id)


@api_router.get("/status/logs")
async def get_status_logs(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    level: str = Query(default="INFO"),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Логи из ring-buffer (84.11.4): публично; секреты замаскированы уже
    в буфере (84.11.1). level: DEBUG|INFO|WARNING|ERROR|CRITICAL|ALL
    (дефолт INFO = INFO и выше); от новых к старым."""
    from services.log_ring import get_log_ring
    entries = get_log_ring().get_entries(level=level, limit=limit)
    return {"count": len(entries), "logs": entries}


# ── Control (84.15, T-641): POST /api/control/restart|stop|start ────────────

async def _run_control(request: Request, action: str, user: WebAppUser) -> dict:
    from services.control_service import (
        ControlDebouncedError,
        ControlStartUnavailableError,
    )
    control = getattr(request.app.state, "control", None)
    if control is None:
        raise HTTPException(status_code=503, detail="control недоступен")
    try:
        return await control.request(action, user.id)
    except ControlDebouncedError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ControlStartUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@api_router.post("/control/restart", status_code=202)
async def control_restart(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.control.restart"))],
):
    return await _run_control(request, "restart", user)


@api_router.post("/control/stop", status_code=202)
async def control_stop(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.control.stop"))],
):
    return await _run_control(request, "stop", user)


@api_router.post("/control/start", status_code=202)
async def control_start(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.control.start"))],
):
    return await _run_control(request, "start", user)


# ── In-Memory State Dump (84.18.5, T-656): GET /api/debug/config ────────────

@api_router.get("/debug/config")
async def get_debug_config(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.debug.config"))],
    key: str | None = Query(default=None),
):
    """84.20.4: JSON-дамп RAM-кэша (не PostgreSQL). key принимает env-имя
    (case-insensitive), settings_field и pg-ключ — через resolve_param_key;
    неизвестный ключ → 404. Право action.debug.config; 401/403 — штатно."""
    cache: ConfigCache = get_cache(request)
    if key:
        spec = resolve_param_key(key)
        if spec is None:
            raise HTTPException(status_code=404,
                                detail=f"не найден: {key}")
        dump = build_dump(cache, key=spec.pg_key)
        item = dump["item"]
        item["name"] = spec.env_name or spec.settings_field or item["key"]
        if is_pg_only(spec):
            item["pg_only"] = True
        return {"meta": dump["meta"], "item": item}
    dump = build_dump(cache)
    for item in dump["items"]:
        spec = get_by_pg_key(item["key"])
        if spec is None:
            item["name"] = item["key"]
            continue
        item["name"] = spec.env_name or spec.settings_field or item["key"]
        if is_pg_only(spec):
            item["pg_only"] = True
    return dump
