"""Раунд 9 (AGI Memory, spec §3.6.2, T-829/F2) — REST «Сон»/«Ностальгия».

APIRouter (prefix="/api"): эндпоинты аудита и ручного запуска воркеров
памяти. DI — services.lore_runtime (Q2): SQLite-часть через get_lore_db(),
воркеры — get_dream_worker()/get_nostalgia_worker() (компонент не
установлен → 503, fail-open NFR-4).

Права (spec §3.6.2, консервативно): ручной запуск/мягкое удаление/protect —
ТОЛЬКО глобальный admin (роль admin / wildcard / ADMIN_USER_ID — паттерн
`_is_global_admin` web/api/chat_lore.py); GET-логи/списки — глобальный
admin (moderator-выдачи НЕ расширяем, известные роли не трогаем).

Коды по конвенции 84.5: 401 (нет initData) / 403 / 404 (belief нет/не
kind='belief') / 409 (already_running — воркер уже бежит) / 422
(валидация) / 503 (PG/компонент/БД недоступны — fail-open).

Контракт (spec §3.6.2; D-8: POST /api/memory/nostalgia/test НЕ реализуем):
  * POST /api/memory/dream/run {chat_id?} → 202 {status: started} |
    409 {detail:{code: already_running}} — ручной run_once: окно 4–6
    игнорирует (D-5), флаг memory.dream_enabled НЕ требуется, бюджеты
    соблюдаются; асинхронный ответ (до 5 кластеров × минуты — таймаут
    API не ждём);
  * GET  /api/memory/dream/beliefs?chat_id=&limit= → последние beliefs;
  * DELETE /api/memory/dream/beliefs/{id} → мягкое удаление (D-7);
  * POST /api/memory/dream/beliefs/{id}/protect → в protected_facts чата;
  * GET  /api/memory/dream/log?limit= → строки memory_dream_log (аудит);
  * GET  /api/memory/nostalgia/log?chat_id=&limit= → nostalgia_log.
Плоские алиасы формы F2-сессии: POST /api/memory/dream (как /dream/run),
GET /api/memory/dream?limit= (beliefs+log одним ответом).
"""
import asyncio
import json
import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.settings import settings
from services import lore_runtime
from web.api.deps import get_cache, get_tma_user

logger = logging.getLogger(__name__)

memory_router = APIRouter()

_DREAM_LOG_LIMIT_MAX = 500     # потолок строк лога «снов» (422-гейт Query)
_NOSTALGIA_LOG_LIMIT_MAX = 500
_BELIEF_LIMIT_MAX = 200


# ── Pydantic-модели ─────────────────────────────────────────────────────────

class DreamRunRequest(BaseModel):
    """POST /api/memory/dream/run: chat_id None → все чаты-кандидаты."""
    chat_id: int | None = Field(default=None)


# ── helpers: права и компоненты ─────────────────────────────────────────────

def _user_permissions(cache, telegram_id: int):
    perms = cache.get_permissions_by_telegram_id(telegram_id)
    if perms is None:
        role = cache.get_permissions("user")
        return role if role is not None else type(perms)()
    return perms


def _is_global_admin(cache, telegram_id: int) -> bool:
    """Глобальный admin: роль admin / wildcard / settings.ADMIN_USER_ID
    (паттерн web/api/chat_lore.py — единая матрица доступа)."""
    if telegram_id == settings.ADMIN_USER_ID:
        return True
    perms = _user_permissions(cache, telegram_id)
    if getattr(perms, "wildcard", False):
        return True
    return cache.get_role(telegram_id) == "admin"


def _require_global_admin(request: Request, user: WebAppUser) -> None:
    """403 — юзер не глобальный admin (spec §3.6.2: только admin)."""
    if not _is_global_admin(get_cache(request), user.id):
        raise HTTPException(status_code=403, detail="permission denied")


def _db_or_503():
    """SQLite DatabaseService из lore_runtime (Q2); None → 503."""
    db = lore_runtime.get_lore_db()
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="база памяти недоступна (не инициализирована)")
    return db


def _json_list(value) -> list:
    """JSON-строка/None → list (source_ids; кривое — пусто, fail-open)."""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        loaded = json.loads(str(value))
    except (ValueError, TypeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _json_dict(value) -> dict:
    """JSON-строка/None → dict (belief_meta/meta; кривое — пусто)."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except (ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _belief_out(row: dict) -> dict:
    """Нормализация строки belief для TMA (source_ids/belief_meta — JSON)."""
    return {
        "id": int(row["id"]),
        "chat_id": int(row["chat_id"]),
        "fact": row["fact"],
        "weight": float(row["weight"] or 0.0),
        "importance": int(row["importance"] or 0),
        "source_ids": _json_list(row.get("source_ids")),
        "belief_meta": _json_dict(row.get("belief_meta")),
        "status": row.get("status"),
        "supersedes": row.get("supersedes"),
        "created_at": int(row["created_at"] or 0),
    }


def _dream_log_out(row: dict) -> dict:
    """Строка memory_dream_log для TMA (source_ids — JSON-массив id)."""
    return {
        "id": int(row["id"]),
        "chat_id": int(row["chat_id"]),
        "run_at": int(row["run_at"] or 0),
        "kind": row.get("kind"),
        "cluster_id": row.get("cluster_id"),
        "source_ids": _json_list(row.get("source_ids")),
        "belief_id": row.get("belief_id"),
        "tokens": int(row.get("tokens") or 0),
        "status": row.get("status"),
    }


def _nostalgia_log_out(row: dict) -> dict:
    """Строка nostalgia_log для TMA (meta — JSON-объект с reason)."""
    return {
        "id": int(row["id"]),
        "chat_id": int(row["chat_id"]),
        "ts": int(row["ts"] or 0),
        "kind": row.get("kind"),
        "fact_id": row.get("fact_id"),
        "status": row.get("status"),
        "meta": _json_dict(row.get("meta")),
    }


# ── POST /api/memory/dream/run (ручной запуск «синтеза сейчас») ─────────────

def _launch_dream(chat_id: int | None):
    """Запуск DreamWorker.run_once в фоне: воркер не установлен → 503;
    уже бежит → 409 {code: already_running}; иначе 202 {status: started}
    (асинхронный ответ — LLM-прогон до 5 кластеров занимает минуты)."""
    worker = lore_runtime.get_dream_worker()
    if worker is None:
        raise HTTPException(status_code=503,
                            detail="DreamWorker недоступен (не инициализирован)")
    if getattr(worker, "running", False):
        raise HTTPException(status_code=409,
                            detail={"code": "already_running"})
    asyncio.create_task(worker.run_once(chat_id))
    return JSONResponse(status_code=202, content={"status": "started"})


@memory_router.post("/memory/dream/run")
async def dream_run(
    payload: DreamRunRequest | None = None,
    request: Request = None,
    user: Annotated[WebAppUser, Depends(get_tma_user)] = None,
):
    """Ручной запуск «сна» (spec §3.6.2): 202/409; только глобальный admin."""
    _require_global_admin(request, user)
    chat_id = payload.chat_id if payload is not None else None
    return _launch_dream(chat_id)


# POST /api/memory/dream (плоский алиас формы F2: body {chat_id?})
@memory_router.post("/memory/dream")
async def dream_run_flat(
    payload: DreamRunRequest | None = None,
    request: Request = None,
    user: Annotated[WebAppUser, Depends(get_tma_user)] = None,
):
    """Алиас POST /api/memory/dream/run (тело {chat_id?: int|null})."""
    _require_global_admin(request, user)
    chat_id = payload.chat_id if payload is not None else None
    return _launch_dream(chat_id)


# ── GET /api/memory/dream/beliefs ───────────────────────────────────────────

@memory_router.get("/memory/dream/beliefs")
async def dream_beliefs(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_BELIEF_LIMIT_MAX)] = 50,
):
    """Последние beliefs (kind='belief', DESC по id; spec §3.6.2):
    chat_id — фильтр чата, limit — потолок строк."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        rows = await db.list_recent_beliefs(chat_id=chat_id, limit=limit)
    except Exception:
        logger.warning("[memory_api] beliefs read failed — fail-open (пусто)",
                       exc_info=True)
        rows = []
    return [_belief_out(r) for r in rows]


# GET /api/memory/dream?limit= (плоский алиас формы F2: beliefs + log)
@memory_router.get("/memory/dream")
async def dream_overview(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    limit: Annotated[int, Query(ge=1, le=_DREAM_LOG_LIMIT_MAX)] = 20,
):
    """Сводка «сна» одним ответом (форма F2-сессии): последние beliefs +
    последние строки memory_dream_log (DESC по id, limit на каждую часть)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        beliefs = [dict(r) for r in
                   await db.list_recent_beliefs(chat_id=None, limit=limit)]
        log = [dict(r) for r in await db.recent_dream_log(limit=limit)]
    except Exception:
        logger.warning("[memory_api] dream overview failed — fail-open",
                       exc_info=True)
        return {"beliefs": [], "log": []}
    return {"beliefs": [_belief_out(r) for r in beliefs],
            "log": [_dream_log_out(r) for r in log]}


# ── DELETE/POST beliefs/{id} (мягкое удаление D-7 / protect §3.4.8) ─────────

@memory_router.delete("/memory/dream/beliefs/{fact_id}")
async def dream_belief_delete(
    fact_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Мягкое удаление belief (spec §3.6.2/D-7): status='unconfirmed',
    last_confirmed_at=NULL; исключается из RAG, вычищается review-воркером.
    404 — id нет / не belief."""
    _require_global_admin(request, user)
    db = _db_or_503()
    deleted = await db.soft_delete_belief(fact_id)
    if not deleted:
        raise HTTPException(status_code=404,
                            detail="belief не найден (или не belief)")
    logger.info("[memory_api] belief soft-deleted | fact_id=%s", fact_id)
    return {"status": "ok", "deleted": True, "id": fact_id}


@memory_router.post("/memory/dream/beliefs/{fact_id}/protect")
async def dream_belief_protect(
    fact_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """«Сделать protected» (spec §3.4.8/§3.6.2): текст belief → protected_facts
    чата (chat-level); belief остаётся в графе, гейт «сна» его не тронет."""
    _require_global_admin(request, user)
    db = _db_or_503()
    row = await db.get_graph_fact(fact_id)
    if row is None or str(row.get("kind") or "") != "belief":
        raise HTTPException(status_code=404,
                            detail="belief не найден (или не belief)")
    inserted = await db.protect_belief_text(
        int(row["chat_id"]), str(row["fact"] or ""))
    logger.info("[memory_api] belief protected | fact_id=%s | chat_id=%s "
                "| inserted=%s", fact_id, row["chat_id"], inserted)
    return {"status": "ok", "protected": bool(inserted), "id": fact_id}


# ── GET /api/memory/dream/log ───────────────────────────────────────────────

@memory_router.get("/memory/dream/log")
async def dream_log(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_DREAM_LOG_LIMIT_MAX)] = 100,
):
    """Строки memory_dream_log (аудит «снов»; TMA «последние сны»)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        rows = await db.recent_dream_log(limit=limit, chat_id=chat_id)
    except Exception:
        logger.warning("[memory_api] dream log read failed — fail-open",
                       exc_info=True)
        rows = []
    return [_dream_log_out(r) for r in rows]


# ── GET /api/memory/nostalgia/log ───────────────────────────────────────────

@memory_router.get("/memory/nostalgia/log")
async def nostalgia_log(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_NOSTALGIA_LOG_LIMIT_MAX)] = 100,
):
    """Строки nostalgia_log (последние срабатывания: sent/skipped/error +
    meta-reason; spec §3.6.2)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        rows = await db.recent_nostalgia_log(chat_id=chat_id, limit=limit)
    except Exception:
        logger.warning("[memory_api] nostalgia log read failed — fail-open",
                       exc_info=True)
        rows = []
    return [_nostalgia_log_out(r) for r in rows]
