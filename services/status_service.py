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
from services.key_history import KeyHistory

logger = logging.getLogger(__name__)

# OD12/OD19 (T-1140/T-1148): персистентная (in-memory ring + JSON-снимок)
# история доступности ключей. Ленивая загрузка — без I/O на import.
key_history = KeyHistory()

_HEALTH_CACHE_SECONDS = 60.0
_HEALTH_TIMEOUT_SECONDS = 5.0
_UPTIME_WINDOW_SECONDS = 86400   # 24 ч
_UPTIME_BUCKET_SECONDS = 300     # 5 мин


def _mask_key(key: str | None) -> dict:
    """84.11.2 (решение 5): только configured/last4 — полное значение НИКОГДА."""
    value = (key or "").strip()
    return {"configured": bool(value), "last4": value[-4:] if value else None}


def _mask_key_for_role(key: str | None, is_global_admin: bool) -> dict:
    """ФИКС S2 (F-7 §1.2-2): глобальный admin — {configured,last4};
    local admin/moderator/user — {configured} БЕЗ last4 (маску не отдаём)."""
    if is_global_admin:
        return _mask_key(key)
    value = bool((key or "").strip())
    return {"configured": value}


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
    def _resolve(key: str, default) -> tuple[Any, str]:
        """(value, source): source='config' — ключ есть в bot_settings,
        'code' — используется дефолт (литерал/константа код-канона)."""
        cache = hot.get_config_cache()
        if cache is not None:
            try:
                sentinel = object()
                value = cache.get(key, sentinel)
                if value is not sentinel and value is not None:
                    return value, "config"
            except Exception:
                pass
        return default, "code"

    @staticmethod
    def llm_registry() -> list[dict]:
        """deepseek/groq/openrouter(+fallback): provider/model/key + module_id.

        OD11/OD16 (T-1139): НОЛЬ активных хардкодов — STT-модели и base_url
        читаются через ``hot.get(pg_key, <сегодняшний литерал>)``; литерал
        остаётся документированным дефолтом (safe migration: status.llm[]
        до/после идентичен)."""
        from SmartModule.transcriber.groq_transcriber import (
            GROQ_BASE_URL,
            GROQ_TRANSCRIBE_MODEL,
        )
        from SmartModule.transcriber.openrouter_transcriber import (
            OPENROUTER_BASE_URL,
            OPENROUTER_TRANSCRIBE_MODEL,
        )
        fallback_base, _fs = StatusService._resolve(
            "models.llm_fallback_base_url", settings.LLM_FALLBACK_BASE_URL)
        fallback_model, _fm = StatusService._resolve(
            "models.llm_fallback_model", settings.LLM_FALLBACK_MODEL)
        groq_base, _gb = StatusService._resolve(
            "models.groq_base_url", GROQ_BASE_URL)
        groq_model, groq_model_src = StatusService._resolve(
            "models.groq_transcribe_model", GROQ_TRANSCRIBE_MODEL)
        or_base, _ob = StatusService._resolve(
            "models.openrouter_base_url", OPENROUTER_BASE_URL)
        or_model, or_model_src = StatusService._resolve(
            "models.openrouter_transcribe_model", OPENROUTER_TRANSCRIBE_MODEL)
        providers = [
            {
                "module_id": "llm_main",
                "module_title": "Прямые ответы",
                "provider": "deepseek",
                "base_url": hot.get("models.llm_base_url",
                                    settings.LLM_BASE_URL),
                "model": hot.get("models.llm_model_name",
                                 settings.LLM_MODEL_NAME),
                "model_source": "config" if hot.get(
                    "models.llm_model_name") else "code",
                "key": hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            },
            {
                "module_id": "stt_groq",
                "module_title": "Транскрипт (Groq)",
                "provider": "groq",
                "base_url": groq_base,
                "model": groq_model,
                "model_source": groq_model_src,
                "key": hot.get("keys.groq_api_key", settings.GROQ_API_KEY),
            },
            {
                "module_id": "stt_openrouter",
                "module_title": "Выжимка видео / STT (OpenRouter)",
                "provider": "openrouter",
                "base_url": or_base,
                "model": or_model,
                "model_source": or_model_src,
                "key": hot.get("keys.openrouter_api_key",
                               settings.OPENROUTER_API_KEY),
            },
        ]
        if fallback_base and fallback_model:
            providers.append({
                "module_id": "llm_fallback",
                "module_title": "Фолбэк",
                "provider": "deepseek_fallback",
                "base_url": fallback_base,
                "model": fallback_model,
                "model_source": "config",
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
        """Сырые строки {ts, status} → непрерывная 5-мин сетка за 24ч (≤288).

        10.7 (2b): пропущенные слоты (нет heartbeat ⇒ процесс не писал 'up')
        заполняются status='down'. Иначе фронт рисовал непрерывную линию
        из одних 'up' — «плоский график».
        """
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
        # Синтез непрерывной сетки: от самого раннего слота (в окне) до
        # текущего; слот без строк = простой ('down').
        if not buckets:
            return []          # все строки старше окна → как раньше, пусто
        now_slot = int(now.timestamp() // bucket_seconds) * bucket_seconds
        first_slot = min(buckets)
        slot = first_slot
        while slot <= now_slot:
            if slot not in buckets:
                buckets[slot] = {
                    "ts": datetime.datetime.fromtimestamp(
                        slot, datetime.timezone.utc).isoformat(),
                    "status": "down",
                }
            slot += bucket_seconds
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

    async def build_snapshot(self, cache=None, *, ctx=None,
                             chat_id: int | None = None) -> dict:
        """{bot, server, llm, uptime, permsoc} по 84.11.4 + F-9 §6.

        ФИКС S2 (F-7 §1.2-2): маска ключей зависит от роли — `ctx`
        (AccessCtx): is_global_admin видит {configured,last4}, остальные —
        только {configured}. ctx=None (fail-open) → НЕ отдаём last4."""
        is_global_admin = bool(ctx is not None and ctx.is_global_admin)
        uptime_rows: list = []
        if cache is not None and hasattr(cache, "pg"):
            uptime_rows = await self.fetch_uptime_rows(cache.pg)
        # F19: health-check'и провайдеров — ПАРАЛЛЕЛЬНО (asyncio.gather),
        # суммарно ≤ max(таймаут 5с, кэш-хиты), а не N×5с.
        providers = self.llm_registry()
        cards = await asyncio.gather(
            *(self._build_llm_card(p, is_global_admin=is_global_admin)
              for p in providers))
        key_history.maybe_save()   # T-1140: атомарный снимок раз в 5 мин
        permsoc = await self.permsoc_telemetry(chat_id)
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
                "local_api": bool(hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED)),
                "version": self.version,
                "errors_total": get_log_ring().get_errors_total(),
                "started_at": self.started_at,
            },
            "server": self._server_metrics(),
            "llm": cards,
            "permsoc": permsoc,
            "uptime": {
                "buckets": buckets,
                # 10.7 (2b): ts последнего 'up'-бакета, иначе None (не
                # buckets[-1].ts — после gap-fill последний слот часто 'down').
                "last_heartbeat": next(
                    (b["ts"] for b in reversed(buckets) if b["status"] == "up"),
                    None),
                "since": (now - datetime.timedelta(
                    seconds=_UPTIME_WINDOW_SECONDS)).isoformat(),
                "until": now.isoformat(),
                "generated_at": now.isoformat(),
            },
        }

    async def _build_llm_card(self, provider: dict, *,
                              is_global_admin: bool = False) -> dict:
        """Карточка провайдера: key={configured[,last4]} + health + latency.
        Маска — по роли (фикс S2; last4 только глобальному админу).
        B1/OD8: также module_id/module_title/model_source + запись сэмпла в
        leak-safe историю доступности (T-1140)."""
        health = await self._check_health(provider["base_url"],
                                          provider["key"] or "")
        module_id = provider.get("module_id") or provider["provider"]
        key_history.record(
            module_id=module_id,
            provider=provider["provider"],
            model=provider["model"] or "",
            ok=bool(health.get("ok")),
            http_status=health.get("http_status"),
            module_title=provider.get("module_title", ""),
        )
        return {
            "module_id": module_id,
            "module_title": provider.get("module_title", ""),
            "provider": provider["provider"],
            "model": provider["model"],
            "model_source": provider.get("model_source", "code"),
            "key": _mask_key_for_role(provider["key"], is_global_admin),
            "last_latency_ms": self._llm_latency.get(provider["provider"]),
            "health": health,
        }

    @staticmethod
    async def permsoc_telemetry(chat_id: int | None = None) -> dict:
        """F-9 §6: телеметрия «N из M» модулей PERMsoc для текущего чат-контекста
        (без секретов/ключей). Реестр модулей — PERMSOC_MODULES; состояние —
        эффективное (master AND под-флаг; модули без под-флага — derived от
        master). Решение по alan не затрагивается: считаем по текущему
        effective-режиму реестра."""
        try:
            from services import permsoc
        except Exception:
            return {"master": False, "enabled": 0, "total": 0,
                    "modules": {}}
        modules = permsoc.PERMSOC_MODULES
        states: dict[str, bool] = {m.module_id: False for m in modules}
        master = False
        try:
            if chat_id is not None:
                master = await permsoc.master_enabled(chat_id)
                for m in modules:
                    if master:
                        states[m.module_id] = bool(
                            await permsoc.module_enabled(chat_id, m.module_id))
            else:
                from services import hot_config as hot
                master = bool(hot.get("flags.permsoc_enabled",
                                      permsoc.master_flag_default()))
                for m in modules:
                    if not master:
                        continue
                    if m.sub_flag_key is None:
                        states[m.module_id] = True
                    else:
                        states[m.module_id] = bool(hot.get(
                            m.sub_flag_key,
                            permsoc.DEFAULT_SUB_FLAGS.get(
                                m.sub_flag_key, False)))
        except Exception:
            logger.warning(
                "[status] permsoc telemetry failed — fail-open zeros",
                exc_info=True)
            master = False
        enabled = sum(1 for v in states.values() if v)
        return {"master": master, "enabled": enabled,
                "total": len(states), "modules": states}


status = StatusService()
