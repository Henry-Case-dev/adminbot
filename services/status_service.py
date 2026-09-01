"""Epic 85 (84.11.2, T-629) — StatusService: сводка для /api/status.

Singleton `status`. Метрики:
  * bot: started_at (monotonic), uptime_seconds, state
    (starting|polling|polling_error — задача polling done() с exception),
    mode=«polling», version=APP_VERSION, errors_total из log_ring;
  * server: psutil — cpu_percent, virtual_memory, disk_usage(путь проекта),
    getloadavg (Linux; на Windows — None), Process(os.getpid()) →
    rss_mb/threads/cpu;
  * llm: реестр из param_catalog/ConfigCache — deepseek (llm_base_url +
    llm_model_name, фоллбэк LLM_FALLBACK_*), groq, openrouter. Ключи — ТОЛЬКО
    {configured, last4} (решение человека №5: полное значение никогда не
    отдаётся). last_latency_ms — record_llm() из LLMClient/транскриберов;
    health — лёгкий GET {base}/models (таймаут 5с, кэш 60с, ТОЛЬКО по запросу
    /api/status); недоступен → status «unreachable»/«not_configured» —
    запрос НЕ роняется;
  * uptime: последние 24ч из uptime_events → 5-минутные бакеты (≤288 точек)
    + last_heartbeat.

status_service НЕ импортирует llm_client — циклических зависимостей нет.
"""
import asyncio
import datetime
import logging
import os
import time
from typing import Any

import psutil

from config.settings import APP_VERSION, settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

_HEALTH_CACHE_SECONDS = 60.0
_HEALTH_TIMEOUT_SECONDS = 5.0
_UPTIME_WINDOW_SECONDS = 86400   # 24 ч
_UPTIME_BUCKET_SECONDS = 300     # 5 мин


def _mask_key(key: str | None) -> dict:
    """84.11.2 (решение 5): только configured/last4 — полное значение НИКОГДА."""
    value = (key or "").strip()
    return {"configured": bool(value), "last4": value[-4:] if value else None}


class StatusService:
    """Сводка здоровья бота/сервера/LLM/аптайма."""

    def __init__(self) -> None:
        self.started_monotonic = time.monotonic()
        self.started_at = datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        self.state = "starting"
        self.version = APP_VERSION
        self._llm_latency: dict[str, float | None] = {}
        self._health_cache: dict[str, tuple[float, dict]] = {}
        self._health_lock = asyncio.Lock()

    def mark_started(self) -> None:
        """Первая строка main() (84.11.2)."""
        self.started_monotonic = time.monotonic()
        self.started_at = datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        self.state = "starting"

    def set_polling_state(self, state: str) -> None:
        """starting | polling | polling_error."""
        self.state = state

    def record_llm(self, provider: str, latency_ms: float | None = None,
                   error: str | None = None) -> None:
        """Вызывается из LLMClient._post и транскриберов (84.11.2)."""
        self._llm_latency[provider] = latency_ms
        if error:
            logger.info("[status] llm error | provider=%s | error=%s",
                        provider, error)

    # ── реестр LLM (из ConfigCache через hot_config, фолбек settings) ──────

    @staticmethod
    def llm_registry() -> list[dict]:
        """deepseek/groq/openrouter: provider/model/key — из каталога."""
        from SmartModule.transcriber.groq_transcriber import (
            GROQ_TRANSCRIBE_MODEL,
        )
        from SmartModule.transcriber.openrouter_transcriber import (
            OPENROUTER_TRANSCRIBE_MODEL,
        )
        fallback_base = hot.get("models.llm_fallback_base_url",
                                settings.LLM_FALLBACK_BASE_URL)
        fallback_model = hot.get("models.llm_fallback_model",
                                 settings.LLM_FALLBACK_MODEL)
        providers = [
            {
                "provider": "deepseek",
                "base_url": hot.get("models.llm_base_url",
                                    settings.LLM_BASE_URL),
                "model": hot.get("models.llm_model_name",
                                 settings.LLM_MODEL_NAME),
                "key": hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            },
            {
                "provider": "groq",
                "base_url": "https://api.groq.com/openai/v1",
                "model": GROQ_TRANSCRIBE_MODEL,
                "key": hot.get("keys.groq_api_key", settings.GROQ_API_KEY),
            },
            {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "model": OPENROUTER_TRANSCRIBE_MODEL,
                "key": hot.get("keys.openrouter_api_key",
                               settings.OPENROUTER_API_KEY),
            },
        ]
        if fallback_base and fallback_model:
            providers.append({
                "provider": "deepseek_fallback",
                "base_url": fallback_base,
                "model": fallback_model,
                "key": hot.get("keys.llm_fallback_api_key",
                               settings.LLM_FALLBACK_API_KEY),
            })
        return providers

    # ── health-check (84.11.2): GET {base}/models, кэш 60с ─────────────────

    async def _check_health(self, base_url: str, key: str) -> dict:
        now = time.monotonic()
        async with self._health_lock:
            cached = self._health_cache.get(base_url)
            if cached and now - cached[0] < _HEALTH_CACHE_SECONDS:
                return cached[1]
        if not (base_url and key):
            result = {"ok": False, "status": "not_configured",
                      "http_status": None, "latency_ms": None,
                      "checked_at": None}
        else:
            result = await self._ping_models(base_url, key)
        async with self._health_lock:
            self._health_cache[base_url] = (time.monotonic(), result)
        return result

    @staticmethod
    async def _ping_models(base_url: str, key: str) -> dict:
        import httpx
        url = f"{base_url.rstrip('/')}/models"
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_SECONDS) \
                    as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {key}"})
            latency = (time.monotonic() - started) * 1000.0
            ok = resp.status_code == 200
            return {"ok": ok, "status": "ok" if ok else "unreachable",
                    "http_status": resp.status_code,
                    "latency_ms": round(latency, 1),
                    "checked_at": datetime.datetime.now(
                        datetime.timezone.utc).isoformat()}
        except Exception:
            return {"ok": False, "status": "unreachable", "http_status": None,
                    "latency_ms": None,
                    "checked_at": datetime.datetime.now(
                        datetime.timezone.utc).isoformat()}

    # ── psutil-метрики сервера ─────────────────────────────────────────────

    @staticmethod
    def _server_metrics() -> dict:
        try:
            vm = psutil.virtual_memory()
            # F11: на Linux — корень диска, на Windows — диск CWD
            disk_path = "/" if os.name == "posix" else os.getcwd()
            disk = psutil.disk_usage(disk_path)
            proc = psutil.Process(os.getpid())
            loadavg = None
            if hasattr(psutil, "getloadavg"):
                try:
                    loadavg = psutil.getloadavg()
                except (OSError, AttributeError):
                    loadavg = None   # Windows: getloadavg отсутствует → None
            return {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory": {"total": vm.total, "used": vm.used,
                           "percent": vm.percent},
                "disk": {"total": disk.total, "used": disk.used,
                         "percent": disk.percent},
                "loadavg": loadavg,
                "process": {"pid": proc.pid,
                            "rss_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
                            "threads": proc.num_threads(),
                            "cpu": proc.cpu_percent(interval=None)},
            }
        except Exception:
            logger.warning("[status] server metrics failed", exc_info=True)
            return {}

    # ── uptime-бакеты (84.11.3) ────────────────────────────────────────────

    @staticmethod
    def _bucketize(rows: list, bucket_seconds: int = _UPTIME_BUCKET_SECONDS,
                   window_seconds: int = _UPTIME_WINDOW_SECONDS) -> list[dict]:
        """Сырые строки {ts, status} → 5-мин бакеты за 24ч (≤288 точек)."""
        if not rows:
            return []
        now = datetime.datetime.now(datetime.timezone.utc)
        since = now - datetime.timedelta(seconds=window_seconds)
        buckets: dict[int, dict] = {}
        for row in rows:
            ts = row["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            if ts < since:
                continue
            slot = int(ts.timestamp() // bucket_seconds) * bucket_seconds
            buckets[slot] = {
                "ts": datetime.datetime.fromtimestamp(
                    slot, datetime.timezone.utc).isoformat(),
                "status": row.get("status") or "up",
            }
        return sorted(buckets.values(), key=lambda b: b["ts"])[-288:]

    async def fetch_uptime_rows(self, pg) -> list:
        """Последние 24ч из uptime_events (пусто при PG down — R6)."""
        if pg is None or getattr(pg, "pool", None) is None:
            return []
        try:
            async with pg.pool.acquire() as conn:
                return await conn.fetch(
                    "SELECT ts, status FROM uptime_events "
                    "WHERE ts >= now() - interval '24 hours' ORDER BY ts")
        except Exception:
            logger.warning("[status] uptime fetch failed (PG down?) — R6",
                           exc_info=True)
            return []

    # ── полная сводка для /api/status ──────────────────────────────────────

    async def build_snapshot(self, cache=None) -> dict:
        """{bot, server, llm, uptime} по 84.11.4. pg — из cache (если есть)."""
        uptime_rows: list = []
        if cache is not None and hasattr(cache, "pg"):
            uptime_rows = await self.fetch_uptime_rows(cache.pg)
        # F19: health-check'и провайдеров — ПАРАЛЛЕЛЬНО (asyncio.gather),
        # суммарно ≤ max(таймаут 5с, кэш-хиты), а не N×5с.
        providers = self.llm_registry()
        cards = await asyncio.gather(
            *(self._build_llm_card(p) for p in providers))
        from services.log_ring import get_log_ring
        now = datetime.datetime.now(datetime.timezone.utc)
        buckets = self._bucketize(list(uptime_rows))
        # ФИКС (2026-09-03): uptime_events пуст/недоступен (PG down, робот
        # только-только поднялся) → НЕ отдаём пустой список (фронт показывал
        # «Нет данных» и плоский график), а минимально-осмысленные бакеты:
        # два последних 5-мин слота со status='down' (heartbeat не было).
        # + generated_at — момент формирования сводки (диагностика).
        if not buckets:
            bucket_seconds = _UPTIME_BUCKET_SECONDS
            last_slot = int(now.timestamp() // bucket_seconds) * bucket_seconds
            buckets = [
                {"ts": datetime.datetime.fromtimestamp(
                    last_slot - 2 * bucket_seconds,
                    datetime.timezone.utc).isoformat(), "status": "down"},
                {"ts": datetime.datetime.fromtimestamp(
                    last_slot - bucket_seconds,
                    datetime.timezone.utc).isoformat(), "status": "down"},
            ]
        return {
            "bot": {
                "uptime_seconds": round(time.monotonic()
                                        - self.started_monotonic, 1),
                "state": self.state,
                "mode": "polling",
                # F11: local_api — признак локального Bot API (DOWNLOAD_ENABLED)
                "local_api": bool(settings.DOWNLOAD_ENABLED),
                "version": self.version,
                "errors_total": get_log_ring().get_errors_total(),
                "started_at": self.started_at,
            },
            "server": self._server_metrics(),
            "llm": cards,
            "uptime": {
                "buckets": buckets,
                "last_heartbeat": buckets[-1]["ts"] if buckets else None,
                "since": (now - datetime.timedelta(
                    seconds=_UPTIME_WINDOW_SECONDS)).isoformat(),
                "until": now.isoformat(),
                "generated_at": now.isoformat(),
            },
        }

    async def _build_llm_card(self, provider: dict) -> dict:
        """Карточка провайдера: key={configured,last4} + health + latency."""
        health = await self._check_health(provider["base_url"],
                                          provider["key"] or "")
        return {
            "provider": provider["provider"],
            "model": provider["model"],
            "key": _mask_key(provider["key"]),
            "last_latency_ms": self._llm_latency.get(provider["provider"]),
            "health": health,
        }


status = StatusService()
