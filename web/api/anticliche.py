"""F4 (T-2132, ADR-1023-4 D6) — API мониторинга/управления анти-клише кэшем.

RBAC — глобальный админ (как `/api/workers/budget`). Эндпоинты:
  * GET  /api/anticliche           — метаданные + список паттернов (для UI F8);
  * POST /api/anticliche/refresh    — форс-обновление (ручной запуск воркера);
  * PUT  /api/anticliche            — ручная правка списка.

R17: ответы админу содержат фразы (нужны UI), в логи не пишутся; возвращаемые
статусы — коды/числа/идентификаторы источника.
"""
from __future__ import annotations

import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services import anticliche_cache
from services import anticliche_worker
from services import roles as roles_srv
from services.anticliche_worker import build_patterns
from web.api.deps import get_cache, get_tma_user

logger = logging.getLogger(__name__)

anticliche_router = APIRouter()

_MANUAL_INPUT_CAP = 200


class PatternIn(BaseModel):
    phrase: str = ""
    origin: str = ""


class ManualPatternsBody(BaseModel):
    patterns: list[PatternIn] = Field(default_factory=list)


async def _require_global_admin(request: Request, user: WebAppUser):
    """403 — не глобальный админ; возвращает ConfigCache."""
    cache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403, detail="permission denied")
    return cache


def _pattern_view(patterns) -> list[dict]:
    out = []
    for item in patterns or []:
        if not isinstance(item, dict):
            continue
        out.append({"code": str(item.get("code") or ""),
                    "phrase": str(item.get("phrase") or ""),
                    "origin": str(item.get("origin") or "")})
    return out


@anticliche_router.get("/anticliche")
async def anticliche_get(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Статус кэша: метаданные (дата/источник/версия) + список паттернов."""
    cache = await _require_global_admin(request, user)
    data = await anticliche_cache.fetch_cache(cache.pg)
    patterns = data.get("patterns") or []
    return {
        "updated_at": data.get("updated_at"),
        "fetched_at": data.get("fetched_at"),
        "source": str(data.get("source") or ""),
        "source_url": str(data.get("source_url") or ""),
        "version": int(data.get("version") or 0),
        "last_status": str(data.get("last_status") or "never"),
        "count": len(patterns) if isinstance(patterns, (list, tuple)) else 0,
        "max_patterns": anticliche_cache.ANTICLICHE_MAX_PATTERNS,
        "patterns": _pattern_view(patterns),
    }


@anticliche_router.post("/anticliche/refresh")
async def anticliche_refresh(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Форс-обновление кэша (ручной запуск недельного воркера)."""
    cache = await _require_global_admin(request, user)
    worker = anticliche_worker.get_runtime_worker()
    if worker is None:
        raise HTTPException(status_code=503,
                            detail="воркер анти-клише недоступен")
    result = await worker.refresh()
    logger.info("[anticliche] manual refresh | status=%s | count=%s",
                result.get("status"), result.get("count"))
    return {
        "status": str(result.get("status") or ""),
        "count": int(result.get("count") or 0),
        "version": int(result.get("version") or 0),
        "source": str(result.get("source") or ""),
    }


@anticliche_router.put("/anticliche")
async def anticliche_put(
    payload: ManualPatternsBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Ручная правка списка (нормализация/дедуп/лимит на сервере)."""
    cache = await _require_global_admin(request, user)
    if len(payload.patterns) > _MANUAL_INPUT_CAP:
        raise HTTPException(
            status_code=422,
            detail=f"слишком много паттернов (>{_MANUAL_INPUT_CAP})")
    entries = [{"phrase": p.phrase, "origin": p.origin}
               for p in payload.patterns]
    patterns = build_patterns(entries)
    try:
        version = await anticliche_cache.write_patterns(
            cache.pg, patterns, source="manual", source_url="")
    except Exception:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    logger.info("[anticliche] manual edit | count=%d | version=%d",
                len(patterns), version)
    return {"status": "ok", "count": len(patterns), "version": version,
            "source": "manual"}
