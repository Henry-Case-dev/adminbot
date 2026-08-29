"""Epic 85 (84.6) — FastAPI-зависимости: TMA-initData-валидация + RBAC.

get_tma_user: initData из заголовка X-Telegram-Init-Data (query «initData» /
JSON-тело «initData» — фолбеки), валидация
aiogram.utils.web_app.safe_parse_webapp_init_data (HMAC, ValueError → 401),
свежесть auth_date ≤ 24 ч (401). BOT_TOKEN — из settings.API_TOKEN (R17:
единственный источник, 84.6).

requires_permission(required) — фабрика FastAPI-dependency: роль юзера из
bot_admins (ConfigCache), матчинг services/permissions.py (84.14.2); нет
права → 403. Неизвестный Telegram ID → роль по умолчанию «user» (пустые
права): для /api/me|/api/status — ОК, для POST — 403 (84.6).
"""
import json
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser, safe_parse_webapp_init_data
from fastapi import Depends, Header, HTTPException, Request

from config.settings import settings
from services.config_cache import ConfigCache
from services.permissions import (
    Permissions,
    requires_permission as match_permission,
)

_AUTH_MAX_AGE_SECONDS = 86400   # 24 ч (84.6)


def get_cache(request: Request) -> ConfigCache:
    return request.app.state.cache


def _user_permissions(cache: ConfigCache, telegram_id: int) -> Permissions:
    """Права юзера; неизвестный ID → пустые права (роль user, 84.6)."""
    perms = cache.get_permissions_by_telegram_id(telegram_id)
    if perms is None:
        user_role = cache.get_permissions("user")
        return user_role if user_role is not None else Permissions.from_dict({})
    return perms


async def _init_data_from_json_body(request: Request) -> str | None:
    """JSON-тело {«initData»: ...} — фолбек для нулевых клиентов (84.6)."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        return None
    try:
        raw = await request.body()
        body = json.loads(raw or b"{}")
    except Exception:
        return None
    return body.get("initData") if isinstance(body, dict) else None


async def get_tma_user(
    request: Request,
    x_telegram_init_data: Annotated[str | None, Header()] = None,
) -> WebAppUser:
    """TMA-auth (84.6): валидный initData → WebAppUser; иначе 401."""
    init_data = x_telegram_init_data
    if not init_data:
        init_data = request.query_params.get("initData")
    if not init_data:
        init_data = await _init_data_from_json_body(request)
    if not init_data:
        raise HTTPException(status_code=401, detail="missing init data")
    try:
        parsed = safe_parse_webapp_init_data(
            token=settings.API_TOKEN, init_data=init_data)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid init data")
    if parsed.user is None:
        raise HTTPException(status_code=401, detail="no user in init data")
    auth_date = parsed.auth_date
    auth_ts = auth_date.timestamp() if hasattr(auth_date, "timestamp") \
        else (auth_date or 0)
    if time.time() - auth_ts > _AUTH_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="init data expired")
    return parsed.user


async def tma_context(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
) -> WebAppUser:
    """TMA-контекст: user + роль/права в request.state (для маршрутов)."""
    cache: ConfigCache = get_cache(request)
    role_name = cache.get_role(user.id) or "user"
    request.state.user = user
    request.state.role_name = role_name
    request.state.permissions = _user_permissions(cache, user.id)
    return user


def requires_permission(required: str):
    """Фабрика FastAPI-dependency (84.6): нет права → 403."""

    async def dependency(
        request: Request,
        user: Annotated[WebAppUser, Depends(get_tma_user)],
    ) -> WebAppUser:
        cache: ConfigCache = get_cache(request)
        perms = _user_permissions(cache, user.id)
        if not match_permission(perms, required):
            raise HTTPException(status_code=403, detail="permission denied")
        return user

    return dependency


def can_view_key_value(cache: ConfigCache, telegram_id: int,
                       pg_key: str) -> bool:
    """84.12.4: полное значение ключа видит ТОЛЬКО роль с правом на
    конкретный ключ (key.<cat>.<key>) / секцию keys / wildcard."""
    perms = _user_permissions(cache, telegram_id)
    return match_permission(perms, f"key.{pg_key}")


def can_edit_param(cache: ConfigCache, telegram_id: int,
                   pg_key: str) -> bool:
    """F2 (84.14.2): право на РЕДАКТИРОВАНИЕ параметра (POST /api/config).
    Для категорий кроме keys — param.<category>.<key> (конкретное право в
    params или покрытие секцией категории); для keys — key.<category>.<key>."""
    perms = _user_permissions(cache, telegram_id)
    return match_permission(perms, f"param.{pg_key}")
