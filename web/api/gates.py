"""Раунд 10 (feature-gates-worker-budget, F-10 §7, D3) — gates/budget API.

GET /api/chat/{chat_id}/gates — global admin; local admin/moderator чата —
чтение; чужой чат → 403. Ответ: {chat_id, opt_in, gates{...},
who_can_toggle, updated_at}.
PUT /api/chat/{chat_id}/gates {feature, enabled} — global admin (любые),
local admin своего чата (только тяжёлые); 422 feature ∉ домена; 403
локальный-на-permsoc; 409 optimistic; ответ {feature, enabled, opt_in}.
GET /api/workers/budget — global admin (раздел) или local admin с
фильтром global + свой чат.
"""
import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from services import chat_params, feature_gates, worker_budget
from services import roles as roles_srv
from services.chat_params import ChatParamsConflict
from web.api.deps import get_cache, get_tma_user

logger = logging.getLogger(__name__)

gates_router = APIRouter()
budget_router = APIRouter()

HEAVY = feature_gates.HEAVY_FEATURES
ALL = feature_gates.ALL_GATED_FEATURES


class GateBody(BaseModel):
    feature: str
    enabled: bool


def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None


def _require_pg(cache) -> None:
    if _pool(cache) is None:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")


@gates_router.get("/chat/{chat_id}/gates")
async def gates_get(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Состояние гейтов чата (F-10 §7): global admin / локальные — чтение;
    чужой чат → 403."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not ctx.is_global_admin and ctx.role_chat not in (
            "local_admin", "moderator"):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    root = await chat_params.get_all_chat_params(chat_id)
    gates = {f: await feature_gates.gates_enabled(chat_id, f, root=root)
             for f in sorted(ALL)}
    opt_in = await feature_gates.has_opt_in(chat_id, cache.pg,
                                            root=root)
    who = {}
    for f in sorted(ALL):
        who[f] = "global" if f == "permsoc" else (
            "global" if ctx.is_global_admin else "local")
    return {
        "chat_id": chat_id,
        "opt_in": opt_in,
        "gates": gates,
        "who_can_toggle": who,
        "updated_at": await chat_params.get_chat_updated_at(chat_id),
    }


@gates_router.put("/chat/{chat_id}/gates")
async def gates_put(
    chat_id: int,
    request: Request,
    payload: GateBody,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Единая точка записи гейта (F-7 set_feature_gate: история field
    'gates' + NOTIFY + auto_opt_in; 409 optimistic; 422 фича вне домена;
    локальный админ — только тяжёлые; permsoc — только global admin)."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if payload.feature not in ALL:
        raise HTTPException(status_code=422,
                            detail=f"неизвестная фича: {payload.feature}")
    if not ctx.is_global_admin:
        if payload.feature == "permsoc":
            raise HTTPException(status_code=403,
                                detail="permsoc — только global admin")
        if payload.feature in HEAVY and ctx.role_chat == "local_admin":
            pass                            # локальному — можно (Q3)
        else:
            raise HTTPException(status_code=403,
                                detail="нет права на гейт этого чата")
    _require_pg(cache)
    try:
        root = await feature_gates.set_feature_gate(
            chat_id, payload.feature, payload.enabled,
            changed_by=user.id, pg=cache.pg)
    except ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    opt_in = await feature_gates.has_opt_in(chat_id, cache.pg, root=root)
    logger.info("[gates] set | chat=%s feature=%s enabled=%s by=%s",
                chat_id, payload.feature, payload.enabled, user.id)
    return {"feature": payload.feature, "enabled": bool(payload.enabled),
            "opt_in": opt_in}


async def _admin_grant_chat_ids(cache, telegram_id: int) -> set[int]:
    """chat_id'ы, на которые у юзера есть грант chat_admins (F-10 §7)."""
    pool = _pool(cache)
    if pool is None:
        return set()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT chat_id FROM chat_admins WHERE telegram_id = $1 "
                "AND role_name IN ('local_admin', 'moderator')", telegram_id)
        return {int(r["chat_id"]) for r in rows}
    except Exception:
        logger.warning("[gates] chat_admins недоступны — fail-open no grants",
                       exc_info=True)
        return set()


@budget_router.get("/workers/budget")
async def workers_budget_get(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Сводка дневного бюджета фона (F-10 §7): global admin видит всё;
    local admin/moderator-грант — global + свои чаты. Не-админ без
    грантов → 403 (фикс R2)."""
    cache = get_cache(request)
    summary = await worker_budget.get_day_summary(cache.pg)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        grant_ids = await _admin_grant_chat_ids(cache, user.id)
        if not grant_ids:
            raise HTTPException(status_code=403,
                                detail="нет доступа к бюджету")
        chats = []
        for entry in summary.get("chats", []):
            scope = entry["scope"]
            if not scope.startswith("chat:"):
                continue
            chat_id = int(scope.split(":", 1)[1])
            if chat_id not in grant_ids:
                continue
            chat_ctx = await roles_srv.access_for(user.id, chat_id,
                                                  cache=cache)
            if chat_ctx.role_chat in ("local_admin", "moderator"):
                chats.append(entry)
        summary["chats"] = chats
    return summary
