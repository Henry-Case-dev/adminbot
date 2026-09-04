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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aiogram.utils.web_app import WebAppUser

from services import param_catalog
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
    """84.5: {telegram_id, username, role_name, permissions, is_custom}."""
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
        "role_name": role_name,
        "permissions": permissions,
        "is_custom": is_custom,
    }


# ── Config ──────────────────────────────────────────────────────────────────

@api_router.get("/config")
async def get_config(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """84.5: любая роль; секреты маскируются (84.12.4 + 2026-09-03: всегда
    {configured,last4}). Плюс title/type из param_catalog — фронту для
    рендера форм (84.7). 84.24 (02.09.2026): groups[] + group/description
    в items; сортировка (category, group.order, title_ru)."""
    cache: ConfigCache = get_cache(request)
    items = []
    for key, value in sorted(cache.get_all().items()):
        spec = get_by_pg_key(key)
        category = spec.category if spec else key.split(".")[0]
        secret = bool(spec.secret) if spec else category == CATEGORY_KEYS
        if secret:
            value = _mask_secret(value, user.id, key, cache)
        items.append({"key": key, "value": value, "category": category,
                      "secret": secret,
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
                      "widget": spec.widget if spec else ""})
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
    return {"items": items, "groups": groups}


@api_router.post("/config")
async def post_config(
    request: Request,
    payload: ConfigUpdateRequest,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """84.5: право — на КАЖДЫЙ ключ (param./key.<категория>.<ключ> покрывается
    секцией категории / конкретным правом; пустая роль → 403 на каждый ключ)."""
    cache: ConfigCache = get_cache(request)
    if not payload.items:
        raise HTTPException(status_code=422, detail="items пуст")
    updated = []
    for item in payload.items:
        spec = get_by_pg_key(item.key)
        if spec is None or spec.category is None:
            raise HTTPException(status_code=422,
                                detail=f"неизвестный ключ: {item.key}")
        # F2: keys-категория — право key.<cat>.<key>; остальные — param.<cat>.<key>
        # (конкретное право в params/keys или покрытие секцией, 84.14.2).
        if spec.category == CATEGORY_KEYS:
            allowed = can_view_key_value(cache, user.id, item.key)
        else:
            allowed = can_edit_param(cache, user.id, item.key)
        if not allowed:
            raise HTTPException(status_code=403,
                                detail=f"нет права на {item.key}")
        if not cache.pg_available:
            # F18: без PG значение не персистентно — честный 503 (как RBAC-опы)
            raise HTTPException(status_code=503,
                                detail="PostgreSQL недоступен (R6)")
        try:
            value = _coerce_value(spec, item.value)
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail=f"{item.key}: {exc}")
        # Раунд 4 (T-719, FR-E2, spec 3.5.2): единая точка валидации пустых
        # prompts/content (защищает ЛЮБЫХ клиентов, не только фронт). Пустая
        # модель/ключ (models/keys/limits/reactions) — легитимна (ступень
        # отключена / очистка ключа), не трогаем.
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
    }.get(category, category)


# ── Status (84.11.4, T-631): публично для любого валидного TMA-юзера ────────

@api_router.get("/status")
async def get_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Сводка bot/server/llm/uptime. БЕЗ requires_permission (84.11 —
    RBAC-исключение); ключи LLM — только configured/last4 (решение 5)."""
    from services.status_service import status
    cache: ConfigCache = get_cache(request)
    return await status.build_snapshot(cache)


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
