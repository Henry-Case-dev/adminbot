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
import logging
import math
import os
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

def _tma_auth_max_age() -> float:
    """Максимальная свежесть initData в секундах (фин. доработка DevOps):
    TMA_AUTH_MAX_AGE из env, default 86400 (24 ч); 0/отрицательное — НЕ
    проверять свежесть (отладка/безопасные окружения); nan/inf/мусор →
    default (ревью-LOW)."""
    raw = os.getenv("TMA_AUTH_MAX_AGE")
    if raw is None:
        return 86400.0
    try:
        value = float(raw)
    except ValueError:
        logger.warning("[tma-auth] TMA_AUTH_MAX_AGE кривой (%r) → default 86400",
                       raw)
        return 86400.0
    if not math.isfinite(value):
        logger.warning("[tma-auth] TMA_AUTH_MAX_AGE не конечное (%r) → "
                       "default 86400", raw)
        return 86400.0
    return value

logger = logging.getLogger(__name__)


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
        _tma_trace(valid=False, err="missing init data",
                   init_data_len=0, src="none",
                   path=request.url.path)
        raise HTTPException(status_code=401, detail="missing init data")
    try:
        parsed = safe_parse_webapp_init_data(
            token=settings.API_TOKEN, init_data=init_data)
    except ValueError:
        _tma_trace(valid=False, err="invalid init data",
                   init_data_len=len(init_data),
                   src=_init_data_src(request, x_telegram_init_data),
                   path=request.url.path)
        raise HTTPException(status_code=401, detail="invalid init data")
    if parsed.user is None:
        _tma_trace(valid=False, err="no user in init data",
                   init_data_len=len(init_data),
                   src=_init_data_src(request, x_telegram_init_data),
                   path=request.url.path)
        raise HTTPException(status_code=401, detail="no user in init data")
    auth_date = parsed.auth_date
    auth_ts = auth_date.timestamp() if hasattr(auth_date, "timestamp") \
        else (auth_date or 0)
    age = time.time() - auth_ts
    max_age = _tma_auth_max_age()
    if max_age > 0 and age > max_age:
        _tma_trace(valid=False, err="expired", age=age,
                   init_data_len=len(init_data),
                   src=_init_data_src(request, x_telegram_init_data),
                   path=request.url.path)
        raise HTTPException(status_code=401, detail="init data expired")
    src = _init_data_src(request, x_telegram_init_data)
    role = None
    perm = None
    cache_attr = getattr(request.app.state, "cache", None)
    if cache_attr is not None:
        role = cache_attr.get_role(parsed.user.id) or "user"
        perms = _user_permissions(cache_attr, parsed.user.id)
        perm = "wildcard" if perms.wildcard else (
            "actions" if perms.actions else
            ("sections" if perms.sections else "none"))
    _tma_trace(valid=True, user=parsed.user.id,
               age=age, init_data_len=len(init_data),
               src=src, role=role, perm=perm)
    return parsed.user


def _init_data_src(request: Request, header_value: str | None) -> str:
    """Источник initData для диагностического трейса (84.21.4)."""
    if header_value:
        return "header"
    if request.query_params.get("initData"):
        return "query"
    return "body"


def _tma_trace(valid: bool, err: str | None = None, user: int | None = None,
               role: str | None = None, age: float | None = None,
               init_data_len: int = 0, src: str = "?",
               perm: str | None = None, path: str | None = None) -> None:
    """84.21.4: диагностический лог авторизации ЗА ФЛАГОМ DEBUG_TMA_TRACE.
    БЕЗ содержимого initData (R17): только длина/результат; роль/пермишены —
    для диагностики «прав нет»; path — без query (секреты/initData не
    логировать)."""
    if os.getenv("DEBUG_TMA_TRACE") != "1":
        return
    if valid:
        logger.info(
            "[tma-auth] src=%s user=%s role=%s perm=%s valid=True age=%ss "
            "init_data_len=%s", src, user, role or "?",
            perm or "-", round(age, 1) if age is not None else "?",
            init_data_len)
    else:
        logger.info(
            "[tma-auth] src=%s valid=False reason=%r age=%s init_data_len=%s "
            "path=%s", src, err, round(age, 1) if age is not None else "?",
            init_data_len, path or "-")


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
