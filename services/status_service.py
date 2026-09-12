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

# ADR-109-3: кэш health по module_id — 2xx 60с, ошибки 10с (никакого stale-200).
_HEALTH_CACHE_SECONDS = 60.0
_HEALTH_ERROR_CACHE_SECONDS = 10.0
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

    # Функциональные группы блока «Доступность ключей» (порядок рендера).
    GROUP_LLM = ("llm_functions", "Основные функции ИИ")
    GROUP_STT = ("transcription", "Транскрибация")
    GROUP_VIDEO = ("video_summary", "Саммаризация видео")
    GROUP_EMB = ("embeddings", "Эмбеддинги")

    @staticmethod
    def _host(base_url: str) -> str:
        """Реальный провайдер = host из base_url (без хардкода имён)."""
        import urllib.parse
        raw = (base_url or "").strip()
        try:
            host = urllib.parse.urlsplit(raw).hostname
        except ValueError:
            host = None
        return (host or raw or "—").lower()

    @staticmethod
    def _display(pg_key: str, settings_field: str, fallback: str) -> str:
        """Кастомное имя модели (ADR-109-1) → fallback, если пусто."""
        default = getattr(settings, settings_field, "")
        value, _src = StatusService._resolve(pg_key, default)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    @staticmethod
    def _model_from(cache_key: str, default: str):
        """(model, source): data-driven модель из ConfigCache либо дефолт.

        ``_resolve`` уже возвращает source ∈ {"config", "code"} — отдельная
        legacy-ветка не нужна (LOW-5)."""
        return StatusService._resolve(cache_key, default)

    @staticmethod
    def llm_registry() -> list[dict]:
        """8 записей по функциям: main/fb, stt groq/or, video, emb main+2fb.

        Провайдер — host из base_url (ноль хардкода имён). Каждая запись несёт
        group_id/group_title/display_name для единого блока «Доступность
        ключей» и kind (chat|stt|embeddings) для реального probe (ADR-109-3)."""
        from SmartModule.transcriber.groq_transcriber import (
            GROQ_BASE_URL,
            GROQ_TRANSCRIBE_MODEL,
        )
        from SmartModule.transcriber.openrouter_transcriber import (
            OPENROUTER_BASE_URL,
            OPENROUTER_TRANSCRIBE_MODEL,
        )

        main_base, _ = StatusService._resolve(
            "models.llm_base_url", settings.LLM_BASE_URL)
        main_model, main_src = StatusService._model_from(
            "models.llm_model_name", settings.LLM_MODEL_NAME)
        fallback_base, _ = StatusService._resolve(
            "models.llm_fallback_base_url", settings.LLM_FALLBACK_BASE_URL)
        fallback_model, _ = StatusService._resolve(
            "models.llm_fallback_model", settings.LLM_FALLBACK_MODEL)
        groq_base, _ = StatusService._resolve(
            "models.groq_base_url", GROQ_BASE_URL)
        groq_model, groq_src = StatusService._model_from(
            "models.groq_transcribe_model", GROQ_TRANSCRIBE_MODEL)
        or_base, _ = StatusService._resolve(
            "models.openrouter_base_url", OPENROUTER_BASE_URL)
        or_model, or_src = StatusService._model_from(
            "models.openrouter_transcribe_model", OPENROUTER_TRANSCRIBE_MODEL)
        video_model, _ = StatusService._resolve(
            "models.video_primary_model", settings.VIDEO_PRIMARY_MODEL)
        emb_model, _ = StatusService._resolve(
            "models.embedding_model_name", settings.EMBEDDING_MODEL_NAME)
        # Раунд 10.12 (ADR-1012-1 D1): адрес primary-эмбеддингов — НЕ main_base.
        emb_base, _ = StatusService._resolve(
            "models.embedding_base_url", settings.EMBEDDING_BASE_URL)

        llm_key = hot.get("keys.llm_api_key", settings.LLM_API_KEY)
        # OD-1: отдельный ключ эмбеддингов; пусто → основной ключ.
        emb_key = (hot.get("keys.embedding_api_key", settings.EMBEDDING_API_KEY)
                   or llm_key)
        or_key = hot.get("keys.openrouter_api_key", settings.OPENROUTER_API_KEY)

        g_llm_id, g_llm_title = StatusService.GROUP_LLM
        g_stt_id, g_stt_title = StatusService.GROUP_STT
        g_vid_id, g_vid_title = StatusService.GROUP_VIDEO
        g_emb_id, g_emb_title = StatusService.GROUP_EMB

        def _entry(module_id, module_title, group, display_name, base_url,
                   model, key, latency_key, kind, model_source="code"):
            return {
                "module_id": module_id,
                "module_title": module_title,
                "group_id": group[0],
                "group_title": group[1],
                "display_name": display_name,
                "provider": StatusService._host(base_url),
                "base_url": base_url,
                "model": model,
                "model_source": model_source,
                "key": key,
                "latency_key": latency_key,
                "kind": kind,
            }

        providers = [
            _entry("llm_main", "Прямые ответы", (g_llm_id, g_llm_title),
                   StatusService._display(
                       "models.llm_display_name", "LLM_DISPLAY_NAME",
                       "Основная модель"),
                   main_base, main_model, llm_key, "deepseek", "chat",
                   main_src),
        ]
        if fallback_base and fallback_model:
            providers.append(_entry(
                "llm_fallback", "Фолбэк", (g_llm_id, g_llm_title),
                StatusService._display(
                    "models.llm_fallback_display_name",
                    "LLM_FALLBACK_DISPLAY_NAME", "Фолбэк-модель"),
                fallback_base, fallback_model,
                hot.get("keys.llm_fallback_api_key",
                        settings.LLM_FALLBACK_API_KEY),
                "deepseek", "chat"))
        providers.append(_entry(
            "stt_groq", "Распознавание речи", (g_stt_id, g_stt_title),
            StatusService._display(
                "models.groq_display_name", "GROQ_DISPLAY_NAME",
                "Транскрибация"),
            groq_base, groq_model,
            hot.get("keys.groq_api_key", settings.GROQ_API_KEY),
            "groq", "stt", groq_src))   # ADR-109-3: POST /audio/transcriptions
        providers.append(_entry(
            "stt_openrouter", "Распознавание речи (резерв)",
            (g_stt_id, g_stt_title),
            StatusService._display(
                "models.openrouter_transcribe_display_name",
                "OPENROUTER_TRANSCRIBE_DISPLAY_NAME",
                "Транскрибация (резерв)"),
            # OpenRouter-расшифровка идёт через chat.completions с
            # input_audio (openrouter_transcriber), поэтому kind="chat".
            or_base, or_model, or_key, "openrouter", "chat", or_src))
        providers.append(_entry(
            "video_openrouter", "Саммаризация видео",
            (g_vid_id, g_vid_title),
            StatusService._display(
                "models.openrouter_display_name", "OPENROUTER_DISPLAY_NAME",
                "Саммаризация видео"),
            or_base, video_model, or_key, "openrouter", "chat"))
        providers.append(_entry(
            "emb_main", "Основная модель памяти", (g_emb_id, g_emb_title),
            StatusService._display(
                "models.embedding_display_name", "EMBEDDING_DISPLAY_NAME",
                "Основная модель памяти"),
            emb_base, emb_model, emb_key, None, "embeddings"))
        # 10.11 (ADR-1011-2): embed-фоллбэк — first-class каталог (hot.get);
        # дефолт = settings → паритет без кэша (R1). Значения не логируются.
        # Scanner LOW: семантика fb_model ДОЛЖНА совпадать с runtime
        # (`llm_client._embed_fallback_model`): hot.get → пустая строка →
        # ГЛАВНАЯ embed-модель. Прежний `or settings.EMBEDDING_FALLBACK_MODEL`
        # при ПУСТОМ значении в PG (не отсутствующем) возвращал env-модель,
        # тогда как рантайм брал главную.
        fb_base = (hot.get("models.embedding_fallback_base_url",
                           settings.EMBEDDING_FALLBACK_BASE_URL) or "").strip()
        fb_model = ((hot.get("models.embedding_fallback_model",
                             settings.EMBEDDING_FALLBACK_MODEL) or "").strip()
                    or emb_model)
        fb_key1 = (hot.get("keys.embedding_fallback_api_key",
                           settings.EMBEDDING_FALLBACK_API_KEY) or "").strip()
        fb_key2 = (hot.get("keys.embedding_fallback_api_key_2",
                           settings.EMBEDDING_FALLBACK_API_KEY_2) or "").strip()
        if fb_base and fb_key1:
            providers.append(_entry(
                "emb_fallback", "Запасная модель памяти",
                (g_emb_id, g_emb_title),
                StatusService._display(
                    "models.embedding_fallback_display_name",
                    "EMBEDDING_FALLBACK_DISPLAY_NAME",
                    "Запасная модель памяти"),
                fb_base, fb_model, fb_key1,
                None, "embeddings"))
        if fb_base and fb_key2:
            providers.append(_entry(
                "emb_fallback2", "Запасная модель памяти 2",
                (g_emb_id, g_emb_title),
                StatusService._display(
                    "models.embedding_fallback2_display_name",
                    "EMBEDDING_FALLBACK2_DISPLAY_NAME",
                    "Запасная модель памяти 2"),
                fb_base, fb_model, fb_key2,
                None, "embeddings"))
        return providers

    # ── health-check (ADR-109-3): реальный POST, кэш по module_id ──────────

    async def _check_health(self, module_id: str, base_url: str, key: str,
                            model: str = "", kind: str = "chat") -> dict:
        """Реальный probe (ADR-109-3): 2xx кэш 60с, ошибки 10с.

        Никакого stale-200: при ошибке старый ok не отдаётся, а результат
        живёт лишь 10 секунд."""
        now = time.monotonic()
        async with self._health_lock:
            cached = self._health_cache.get(module_id)
            if cached:
                ttl = (_HEALTH_CACHE_SECONDS if cached[1].get("ok")
                       else _HEALTH_ERROR_CACHE_SECONDS)
                if now - cached[0] < ttl:
                    return cached[1]
        if not (base_url and key):
            result = {"ok": False, "status": "not_configured",
                      "http_status": None, "latency_ms": None,
                      "checked_at": None}
        else:
            result = await self._ping_provider(base_url, key, model, kind)
        async with self._health_lock:
            self._health_cache[module_id] = (time.monotonic(), result)
        return result

    @staticmethod
    async def _ping_provider(base_url: str, key: str, model: str = "",
                             kind: str = "chat") -> dict:
        """Провайдер через ``llm_probe.probe_openai`` (ленивый импорт)."""
        checked_at = datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        try:
            from services import llm_probe
            res = await llm_probe.probe_openai(
                base_url, key, model, kind=kind,
                timeout=_HEALTH_TIMEOUT_SECONDS)
        except Exception:
            logger.warning("[status] probe_openai failed", exc_info=True)
            return {"ok": False, "status": "unreachable", "http_status": None,
                    "latency_ms": None, "checked_at": checked_at}
        return {
            "ok": bool(res.get("ok")),
            "status": res.get("status") or "unreachable",
            "http_status": res.get("http_status"),
            "latency_ms": res.get("latency_ms"),
            "checked_at": checked_at,
        }

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
                # F6 (T-1460): число ядер — для нормализации loadavg на фронте
                # (EKG-пульс = loadavg[0]/cpu_count; Windows → CPU/RAM-фолбэк).
                "cpu_count": (psutil.cpu_count()
                              if hasattr(psutil, "cpu_count") else None) or 1,
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
        # F5 (cognition-dashboard-round1013, spec §3.6/F5-Q4): аддитивное поле
        # context — in-memory accounting последнего собранного контекста
        # (оценка токенов, cap, признак урезания). R17-safe: только числа;
        # данных нет (рестарт/контекст не собирался) → used=null, фронт «—».
        try:
            from services.direct_chat_service import get_process_accounting
            acct = get_process_accounting()
        except Exception:
            logger.warning("[status] context accounting unavailable", exc_info=True)
            acct = {}
        ctx_cap = hot.get("limits.chat_context_budget_tokens",
                          settings.CHAT_CONTEXT_BUDGET_TOKENS)
        context_field = {
            "used": acct.get("context_used"),
            "limit": acct.get("context_limit") or ctx_cap,
            "truncated": bool(acct.get("context_truncated")),
        }
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
            "context": context_field,
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
        """Карточка провайдера: group/display + key-маска + реальный health.

        ADR-109-3: health — POST probe, кэш по module_id. B1/OD8: module_id/
        module_title/model_source + запись сэмпла в leak-safe историю."""
        module_id = provider.get("module_id") or provider["provider"]
        health = await self._check_health(
            module_id, provider["base_url"], provider["key"] or "",
            provider.get("model") or "", provider.get("kind", "chat"))
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
            "group_id": provider.get("group_id", ""),
            "group_title": provider.get("group_title", ""),
            "display_name": provider.get("display_name", ""),
            "provider": provider["provider"],
            "model": provider["model"],
            "model_source": provider.get("model_source", "code"),
            "key": _mask_key_for_role(provider["key"], is_global_admin),
            "last_latency_ms": self._llm_latency.get(
                provider.get("latency_key") or ""),
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
