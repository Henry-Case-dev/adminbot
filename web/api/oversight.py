"""Раунд 10 (global-oversight-dashboard, F-12 §4/§5) — API Oversight.

Все эндпоинты: 401 без initData; 403 не-глобальный (requires_global_admin);
404 неизвестный чат; 422 feature ∉ домена; 409 optimistic
{code:'conflict', current_updated_at}. Kill-switch и запрет глобального
ключа — ЕДИНЫЕ пути записи (feature_gates.set_feature_gate /
chat_params.set_chat_params keys.allow_global): приоритет совпадает с
F-7/F-10 (явный chat-гейт > глобальный флаг > False). R17: без сырых
ключей (только статусы own/global/forbidden/none + last4 своего own).
"""
import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from services import chat_params, feature_gates, lore_runtime, oversight
from services.chat_params import ChatParamsConflict
from web.api.deps import get_cache, get_tma_user, requires_global_admin

logger = logging.getLogger(__name__)

oversight_router = APIRouter()


class KillswitchBody(BaseModel):
    feature: str
    enabled: bool
    expected_updated_at: str | None = None


class GlobalKeyBody(BaseModel):
    allow: bool
    expected_updated_at: str | None = None


def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None


async def _require_chat_exists(cache, chat_id: int) -> None:
    """ФИКС S-F12 (spec §4): 404 для неизвестного chat_id (409 остаётся
    только для конфликтов версии; раньше несуществующий чат давал 409)."""
    pool = _pool(cache)
    if pool is None:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM chat_profiles WHERE chat_id = $1", chat_id)
    except Exception:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    if row is None:
        raise HTTPException(status_code=404, detail="чат не найден")


@oversight_router.get("/summary")
async def oversight_summary(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Сводка всех чатов (F-12 §4): кэш сервера 60 с; PG down → errors."""
    cache = get_cache(request)
    data = await oversight.build_summary(cache.pg)
    data["cached"] = "60s-server-cache"      # UI-mark; polling НЕ добавляем
    return data


@oversight_router.get("/chat/{chat_id}")
async def oversight_chat(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Детали чата (модалка): summary + admins + 5 записей истории."""
    cache = get_cache(request)
    store = lore_runtime.get_lore_store()
    details = await oversight.get_chat_details(cache.pg, chat_id,
                                               store=store)
    if details is None:
        raise HTTPException(status_code=404, detail="чат не найден")
    return details


@oversight_router.post("/chat/{chat_id}/killswitch")
async def oversight_killswitch(
    chat_id: int,
    request: Request,
    payload: KillswitchBody,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Kill-switch фичи (F-12 §3): запись gates[feature] через
    set_feature_gate (единый путь с F-10); response {feature, enabled,
    previous, updated_at}; 409 optimistic; 422 feature ∉ домена."""
    cache = get_cache(request)
    if payload.feature not in feature_gates.ALL_GATED_FEATURES:
        raise HTTPException(status_code=422,
                            detail=f"неизвестная фича: {payload.feature}")
    await _require_chat_exists(cache, chat_id)      # 404 неизвестный чат
    root = await chat_params.get_all_chat_params(chat_id)
    previous = bool((root.get("gates") or {}).get(
        payload.feature, await feature_gates.gates_enabled(
            chat_id, payload.feature, root=root)))
    new_root = None
    try:
        new_root = await feature_gates.set_feature_gate(
            chat_id, payload.feature, payload.enabled,
            changed_by=user.id, pg=cache.pg,
            expected_updated_at=payload.expected_updated_at)
    except ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    oversight.invalidate_summary()
    # ФИКС S-F12: updated_at — АКТУАЛЬНАЯ метка профиля (gates-запись
    # идёт через set_chat_params → updated_at chat_profiles; meta.updated_at
    # отсутствует — раньше возвращался вечный None).
    updated_at = await chat_params.get_chat_updated_at(chat_id)
    logger.info(
        "[oversight] killswitch | chat=%s feature=%s enabled=%s "
        "previous=%s by=%s", chat_id, payload.feature, payload.enabled,
        previous, user.id)
    return {"feature": payload.feature, "enabled": payload.enabled,
            "previous": previous,
            "updated_at": updated_at}


@oversight_router.post("/chat/{chat_id}/global_key")
async def oversight_global_key(
    chat_id: int,
    request: Request,
    payload: GlobalKeyBody,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Запрет/разрешение глобального ключа чата: chat_params.keys.
    allow_global (JSONB, F-7 §4.2); собственными ключами не запрещается."""
    cache = get_cache(request)
    await _require_chat_exists(cache, chat_id)      # 404 неизвестный чат
    root = await chat_params.get_all_chat_params(chat_id)
    keys_ns = dict(root.get("keys") or {})
    previous = bool(keys_ns.get("allow_global", True))
    if previous == bool(payload.allow):
        return {"allow": previous, "previous": previous,
                "updated_at": await chat_params.get_chat_updated_at(chat_id),
                "noop": True}
    keys_ns["allow_global"] = bool(payload.allow)
    meta = dict(root.get("meta") or {})
    meta["updated_by"] = user.id
    try:
        new_root = await chat_params.set_chat_params(
            chat_id, {"keys": keys_ns, "meta": meta},
            changed_by=user.id, pg=cache.pg,
            expected_updated_at=payload.expected_updated_at)
    except ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    oversight.invalidate_summary()
    logger.info(
        "[oversight] global_key | chat=%s allow=%s previous=%s by=%s",
        chat_id, payload.allow, previous, user.id)
    return {"allow": payload.allow, "previous": previous,
            "updated_at": await chat_params.get_chat_updated_at(chat_id)}
