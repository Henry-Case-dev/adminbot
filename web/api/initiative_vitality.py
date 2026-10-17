"""SOUL-1 W5 (SOUL-18.4/18.5/18.6) — диагностика инициативы для MiniApp.

Два endpoint'а на собственном роутере (прецедент memory_overview/stories;
`routes.py` и чужие роутеры не затрагиваются):

* ``GET /api/memory/initiative-vitality?chat_id=&hours=24|48`` — ЕДИНОЕ
  место чтения диагностики инициативы: воронка наблюдателя (durable
  checkpoint + оконные события), честный вердикт «health ≠ outcome»
  (возможности есть, а сообщений нет — это предупреждение, а не «здорово»),
  реальное состояние ворот чата (что мешает СЕЙЧАС), последние решения/
  отказы и доставленные сообщения с ``message_id`` и ревизиями Core/Style.
* ``POST /api/memory/initiative-check`` — безопасная проверка «Проверить
  инициативу»: полный trace до mock send БЕЗ публикации в рабочую группу
  по умолчанию (реальная отправка — только при включённой оси
  ``flags.initiative_diagnostics_publish_enabled`` И явном
  ``confirm_publish=true``).

Права: ТОЛЬКО глобальный admin (`_require_global_admin`). R17-safe: коды,
числа, ID и ревизии; сырой текст чата в ответ не попадает. Исключение —
``mock_send.preview`` (последний сгенерированный текст) — он принадлежит
владельцу, не пишется в события/логи и ограничен ``PREVIEW_CHARS``.
Fail-open: ошибка данных → честный ``available:false`` в секции, не 500.
"""
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from web.api.deps import get_tma_user
from web.api.memory_agi import _db_or_503, _require_global_admin

logger = logging.getLogger(__name__)

initiative_vitality_router = APIRouter()

#: Кэш диагностики (30 с): панель Статуса не должна сканировать события на
#: каждый тик; вердикт за такой интервал не меняется.
_VITALITY_TTL = 30.0
_vitality_cache: dict = {}
#: Оконный блок воронки (совместимая форма с /memory/intel-funnels).
_EVENTS_TTL = 60.0
_events_cache: dict = {}


class InitiativeCheckRequest(BaseModel):
    """Тело проверки инициативы (по умолчанию — только mock)."""

    chat_id: int
    hours: int = Field(default=24, ge=1, le=48)
    #: Реальная отправка — только вместе с confirm_publish=true И осью.
    publish: bool = False
    confirm_publish: bool = False


def _now() -> int:
    return int(time.time())


def _cached(bucket: dict, key: str, db, ttl: float):
    entry = bucket.get(key)
    if not entry:
        return None
    c_db, ts, payload = entry
    if c_db is db and (time.monotonic() - ts) < ttl:
        return payload
    return None


def _store(bucket: dict, key: str, db, payload) -> None:
    bucket[key] = (db, time.monotonic(), payload)


async def _funnel_block(db, chat_id: int | None) -> dict:
    """Воронка в форме, совместимой с `/memory/intel-funnels` (одно место UI).

    Считается существующими helper'ами W3-STATUS: durable-задача
    `initiative.observe` + оконные события 24ч/7д + liveness-штамп тика."""
    import web.api.memory_overview as mo
    cached = _cached(_events_cache, "funnel", db, _EVENTS_TTL)
    if cached is not None and cached.get("chat_id") == chat_id:
        return cached
    now = _now()
    events: dict = {}
    for key, days in (("24h", 1), ("7d", 7)):
        events[key] = await mo._events_counts(
            db, mo._INITIATIVE_EVENTS, now - days * 86400, chat_id)
    try:
        job = await mo._latest_job_async(db, mo._OBSERVE_JOB_KIND)
    except Exception:
        logger.warning("[w5] observe job read failed", exc_info=True)
        job = None
    liveness: dict = {}
    try:
        from services import memory_maintenance as mm
        liveness = dict(getattr(mm, "_initiative_observer_last_tick", {}) or {})
    except Exception:
        liveness = {}
    payload = {
        "available": job is not None or bool(events.get("24h")),
        "job": job,
        "liveness": {
            "ts": liveness.get("ts"),
            "status": liveness.get("status"),
            "observed": liveness.get("observed"),
            "opportunities": liveness.get("opportunities"),
        },
        "events": events,
        "chat_id": chat_id,
    }
    _store(_events_cache, "funnel", db, payload)
    return payload


async def _writer_and_llm():
    """Существующий Direct-контур (Writer+L1) — тот же, что у наблюдателя.

    Ничего не создаём: берём singleton сервиса из maintenance-контура
    (прецедент `_tick_initiative_observer`). Нет сервиса → честные None."""
    try:
        from services import memory_maintenance as mm
        service = mm._direct_chat_service_singleton()
    except Exception:
        service = None
    llm = getattr(service, "llm", None) if service is not None else None
    return service, llm


@initiative_vitality_router.get("/memory/initiative-vitality")
async def memory_initiative_vitality(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    hours: Annotated[int, Query(ge=1, le=48)] = 24,
):
    """SOUL-18.5: где инициатива остановилась — и что это значит честно.

    Нули показываются нулями; «heartbeat ok» и «25 jobs» НЕ выдаются за
    отправку: вердикт ``activity`` отделяет техническое здоровье от факта
    доставки и объясняет причины молчания."""
    _require_global_admin(request, user)
    db = _db_or_503()
    cache_key = "vitality:%s:%s" % (chat_id, hours)
    cached = _cached(_vitality_cache, cache_key, db, _VITALITY_TTL)
    if cached is not None:
        return cached
    from services import initiative_diagnostics as diag
    service, llm = await _writer_and_llm()
    liveness: dict = {}
    try:
        from services import memory_maintenance as mm
        liveness = dict(getattr(mm, "_initiative_observer_last_tick", {}) or {})
    except Exception:
        liveness = {}
    payload = await diag.collect_vitality(
        db, chat_id=chat_id, hours=hours, liveness=liveness,
        llm_available=llm is not None, writer_available=service is not None)
    payload["funnel"] = await _funnel_block(db, chat_id)
    payload["engine"] = {
        "writer": "direct_l2" if service is not None else "",
        "llm_available": llm is not None,
        "writer_available": service is not None,
    }
    _store(_vitality_cache, cache_key, db, payload)
    return payload


@initiative_vitality_router.post("/memory/initiative-check")
async def memory_initiative_check(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    payload: InitiativeCheckRequest | None = None,
):
    """SOUL-18.4: безопасная проверка инициативы.

    По умолчанию — mock: цепочка проходится целиком (ворота → окно →
    оценка → решение → Writer → форма → recheck), но ни одного сообщения в
    рабочую группу не уходит, а воронка не подменяется. Реальная отправка
    включается только осью владельца + ``confirm_publish``."""
    _require_global_admin(request, user)
    db = _db_or_503()
    body = payload or InitiativeCheckRequest(chat_id=0)
    from services import initiative_diagnostics as diag
    service, llm = await _writer_and_llm()
    bot = None
    if body.publish:
        try:
            from services import web_runtime
            bot = web_runtime.get_web_bot()
        except Exception:
            logger.warning("[w5] web bot unavailable for publish", exc_info=True)
            bot = None
    result = await diag.run_check(
        db, chat_id=int(body.chat_id), hours=int(body.hours or 24),
        publish=bool(body.publish), confirm_publish=bool(body.confirm_publish),
        writer_service=service, llm=llm, bot=bot)
    # Проверка не должна попадать в кэш панели: сбрасываем, чтобы владелец
    # сразу увидел её влияние (маркер-событие читается панелью отдельно).
    _vitality_cache.clear()
    return result
