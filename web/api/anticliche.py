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
from services import anticliche_sources
from services import anticliche_worker
from services import roles as roles_srv
from services.negative_constraints import DYNAMIC_PHRASE_MAX
from web.api.deps import get_cache, get_tma_user

logger = logging.getLogger(__name__)

anticliche_router = APIRouter()

def _manual_input_cap() -> int:
    """Абсолютный потолок входного списка ручной правки (review iter1 High).

    Привязан к защитному код-потолку `ANTICLICHE_MAX_PATTERNS_HARD_CEILING`
    (1000), а не к текущему резолвленному лимиту: список длиннее лимита
    нормализуется/усекается `build_patterns()` до `max_patterns()`, а не
    отбивается 422. Устраняет «мёртвую ручку» при лимите 201..1000."""
    return int(anticliche_cache.ANTICLICHE_MAX_PATTERNS_HARD_CEILING)


class PatternIn(BaseModel):
    # T-2488 (ADR-1025-7 D2): канон длины фразы — 2…120 (`DYNAMIC_PHRASE_MIN/
    # MAX`). Длинная фраза → понятная 422 (не тихий дроп при нормализации);
    # «лимит длины фразы» (120) отделён от «числа паттернов» (вместимость).
    phrase: str = Field(default="", max_length=DYNAMIC_PHRASE_MAX)
    origin: str = Field(default="", max_length=200)


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
        "max_patterns": anticliche_cache.max_patterns(),
        # F0.3 (ADR-1025-3 D1): размер партии за обновление (≤ per_run) —
        # отдельно от вместимости max_patterns. Аддитивно (R16).
        "per_run": anticliche_worker.max_patterns_per_run(),
        "max_rounds": anticliche_worker.max_rounds(),
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
    result = await worker.refresh(force=True)
    logger.info("[anticliche] manual refresh | status=%s | count=%s",
                result.get("status"), result.get("count"))
    return {
        "status": str(result.get("status") or ""),
        "count": int(result.get("count") or 0),
        # AC-INV-08: при ошибке возвращается РЕАЛЬНАЯ действующая версия,
        # а не ложный 0 (нули показываются только когда набора правда нет).
        "version": int(result.get("version") or 0),
        "rules": int(result.get("rules") or 0),
        "source": str(result.get("source") or ""),
        "sources": result.get("sources") or {},
        "paused": result.get("paused") or [],
        "published": bool(result.get("published")),
    }


# ── AC-DATA: read-only поверхность шести вкладок (UI — отдельный пакет) ─────
async def _sources_payload(cache) -> dict:
    """Единая сборка честного состояния источников (без выдуманных нулей)."""
    states = await anticliche_sources.fetch_states(cache.pg)
    views = anticliche_sources.build_views(
        states, freshness_days=anticliche_worker.REFRESH_DAYS)
    active = await anticliche_cache.read_active_version(cache.pg)
    summary = anticliche_sources.summarize(views)
    return {
        "now": anticliche_sources.utc_now().isoformat(),
        "freshness_days": anticliche_worker.REFRESH_DAYS,
        "summary": summary,
        "denominators": summary["denominators"],
        "health": anticliche_sources.build_health(
            views, active_version=active,
            enabled=anticliche_cache.enabled(),
            compiler=anticliche_sources.compiler_probe()),
        "active_version": {
            "status": active.get("status"),
            "version": active.get("version"),
            "rules": active.get("rules"),
            "published_at": active.get("published_at"),
            "bank_source": active.get("bank_source"),
            "reason": active.get("reason"),
        },
        "sources": [v for v in views if v.get("counts_as_live")],
        "local_sources": [v for v in views
                          if v.get("transport") == "local"],
        "references": [v for v in views
                       if v.get("kind") == anticliche_sources.KIND_BIBLIO],
        "lineage": anticliche_sources.independent_confirmations(),
    }


@anticliche_router.get("/anticliche/sources")
async def anticliche_sources_list(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Вкладка «Источники»: статусы, свежесть, LKG-версия, четыре вида здоровья.

    Read-only: проверки/правки — отдельные операции (AC-API).
    """
    cache = await _require_global_admin(request, user)
    return await _sources_payload(cache)


@anticliche_router.get("/anticliche/sources/{source_id}")
async def anticliche_source_detail(
    source_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Детали одного источника: пути, лицензия, retry policy, свежесть."""
    cache = await _require_global_admin(request, user)
    source = anticliche_sources.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="неизвестный источник")
    states = await anticliche_sources.fetch_states(cache.pg)
    view = anticliche_sources.source_view(
        source, states.get(source.source_id),
        freshness_days=anticliche_worker.REFRESH_DAYS)
    return view


@anticliche_router.get("/anticliche/health")
async def anticliche_health(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Четыре независимых вида здоровья (§2.2), не один ``ok/error``."""
    cache = await _require_global_admin(request, user)
    states = await anticliche_sources.fetch_states(cache.pg)
    views = anticliche_sources.build_views(
        states, freshness_days=anticliche_worker.REFRESH_DAYS)
    active = await anticliche_cache.read_active_version(cache.pg)
    return {
        "health": anticliche_sources.build_health(
            views, active_version=active,
            enabled=anticliche_cache.enabled(),
            compiler=anticliche_sources.compiler_probe()),
        "active_version": active,
        "summary": anticliche_sources.summarize(views),
    }


@anticliche_router.put("/anticliche")
async def anticliche_put(
    payload: ManualPatternsBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Ручная правка списка (нормализация/дедуп/лимит на сервере)."""
    cache = await _require_global_admin(request, user)
    input_cap = _manual_input_cap()
    if len(payload.patterns) > input_cap:
        raise HTTPException(
            status_code=422,
            detail=f"слишком много паттернов (>{input_cap})")
    entries = [{"phrase": p.phrase, "origin": p.origin}
               for p in payload.patterns]
    try:
        # Единый путь ручной правки (review iter1 L2): серверная
        # нормализация/дедуп/лимит + запись source='manual'.
        result = await anticliche_worker.apply_manual(cache.pg, entries)
    except Exception:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    # T-2491 (ADR-1025-7 D2): честный лог без фраз (R17) — только числа/коды.
    dropped = result.get("dropped") or {}
    logger.info(
        "[anticliche] manual edit | saved=%d | dropped={invalid=%d hardcoded=%d "
        "duplicate=%d over_limit=%d} | version=%d",
        result["count"], len(dropped.get("invalid") or []),
        len(dropped.get("hardcoded") or []),
        len(dropped.get("duplicate") or []),
        len(dropped.get("over_limit") or []),
        result["version"])
    return result
