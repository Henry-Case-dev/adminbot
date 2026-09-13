"""Раунд 10.14 (F1 anti-echo-self-reply, ADR-1014-2 D4/D9, spec §3.1).

LLM-экстрактор СУТИ собственного ответа бота (НЕ rule-based — прямое
требование владельца, UPD п.3). Перед записью self-факта в граф ответ бота
сжимается до одной короткой фразы формата
``[Бот] <решил|посоветовал|заявил>: <суть>``.

Модель: выделенная роль воркера ``reflection`` (регистрируется F8) через
``LLMClient.generate_worker``; если роль/подключение не заданы или упали —
фоллбэк на основную модель (``generate``). Любая ошибка/пусто → '' (fail-safe:
self-факт НЕ пишется, ответ пользователю не рушится).

``SELF_REFLECTION_PROMPT`` — КОД-КОНСТАНТА вне PG-канона (ADR-1013-3): канон
промптов/FACT_EXTRACT_PROMPT не меняются.
"""
import logging

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# Формат ответа жёстко задан (одна фраза, без пояснений/кавычек/списков).
SELF_REFLECTION_PROMPT = (
    "Ты — модуль саморефлексии бота. Ниже — только что отправленный ответ бота. "
    "Верни РОВНО одну короткую фразу-суть в формате: "
    "[Бот] <решил|посоветовал|заявил>: <суть (≤300 симв.)>. "
    "Без пояснений, без кавычек, без списков. Если сути нет — верни пустую строку."
)

# UPSERT singleton-строки persona_state (PG; DDL владеет F1 — pg_db.py).
_UPSERT_PERSONA_STATUS_SQL = """
    INSERT INTO persona_state (id, last_extract_at, last_extract_status,
                               last_error, updated_at)
    VALUES (true, now(), $1, $2, now())
    ON CONFLICT (id) DO UPDATE SET
        last_extract_at = now(),
        last_extract_status = EXCLUDED.last_extract_status,
        last_error = EXCLUDED.last_error,
        updated_at = now()
"""

_STATUS_CAP = 16
_ERROR_CAP = 500


def _normalize_essence(raw) -> str:
    """Нормализация ответа LLM: strip + схлопывание whitespace/переносов, cap
    settings.SELF_ESSENCE_MAX_CHARS (300). Пусто/кривой → ''."""
    text = " ".join(str(raw or "").split())
    if not text:
        return ""
    try:
        cap = int(getattr(settings, "SELF_ESSENCE_MAX_CHARS", 300) or 300)
    except (TypeError, ValueError):
        cap = 300
    return text[:max(1, cap)].strip()


def _persona_pool():
    """Пул PG для записи метрик persona_state (None — PG недоступен/не поднят)."""
    cache = hot.get_config_cache()
    pg = getattr(cache, "pg", None) if cache is not None else None
    return getattr(pg, "pool", None)


async def record_extractor_status(status: str, error: str | None = None) -> None:
    """best-effort UPSERT режима экстрактора в persona_state (D9). НИКОГДА не
    бросает и не роняет ответ; без PG/пула — тихий no-op. R17: значения
    секретов не логируются (error обрезается; в лог не попадает)."""
    try:
        pool = _persona_pool()
        if pool is None:
            return
        status = str(status or "never")[:_STATUS_CAP]
        err = str(error)[:_ERROR_CAP] if error else None
        async with pool.acquire() as conn:
            await conn.execute(_UPSERT_PERSONA_STATUS_SQL, status, err)
    except Exception:
        logger.debug("[self_reflection] persona_state write failed", exc_info=True)


async def _report(on_status, status: str) -> None:
    """Оповестить об исходе best-effort (сам сбой колбэка игнорируется)."""
    if on_status is None:
        return
    try:
        await on_status(status)
    except Exception:
        logger.debug("[self_reflection] on_status callback failed", exc_info=True)


async def extract_self_essence(llm, answer: str, *, chat_id: int | None = None,
                               on_status=None) -> str:
    """Суть ответа бота ТОЛЬКО через LLM (ADR-1014-2 D4).

    Порядок: ``generate_worker('reflection', …)`` → при любой ошибке (в т.ч.
    ValueError, если роль ещё не зарегистрирована — F8 не влит) фоллбэк на
    ``llm.generate(…)`` (основная модель) → при ошибке и там → ''.

    ``on_status`` — опциональный async-callback статуса ('ok'|'empty'|'error')
    для метрик persona_state (обычно :func:`record_extractor_status`)."""
    text = " ".join(str(answer or "").split())
    if not text:
        await _report(on_status, "empty")
        return ""
    messages = [
        {"role": "system", "content": SELF_REFLECTION_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = None
    worker_fn = getattr(llm, "generate_worker", None)
    if callable(worker_fn):
        try:
            raw = await worker_fn("reflection", messages, chat_id=chat_id)
        except Exception as exc:
            # Роль не зарегистрирована (F8) / dedicated-сбой → основная модель.
            logger.info(
                "[self_reply] reflection worker fallback → main | error=%s",
                type(exc).__name__)
            raw = None
    if raw is None:
        try:
            raw = await llm.generate(messages, chat_id=chat_id)
        except Exception as exc:
            logger.warning(
                "[self_reply] essence extraction failed — skip self fact | "
                "error=%s", type(exc).__name__)
            await _report(on_status, "error")
            return ""
    essence = _normalize_essence(raw)
    await _report(on_status, "ok" if essence else "empty")
    return essence
