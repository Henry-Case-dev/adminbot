"""F4 (T-2128, ADR-1023-4 D6) — недельный воркер динамического анти-клише кэша.

Раз в неделю забирает источник (по умолчанию — статья «Wikipedia:Signs of AI
writing» через action API), просит LLM извлечь до ~20 популярных ИИ-паттернов
строгим JSON-контрактом, нормализует/дедуплицирует и кладёт в PG-таблицу
``anticliche_cache``. Динамические правила питают **детектор** (validator-loop),
а не scrubber и не промпт (ADR-1023-4 D1).

Устойчивость: сбой источника/LLM/parse → предыдущий кэш сохраняется, пишется
R17-safe ``last_status`` (коды/класс ошибки; сырьё и фразы НЕ логируются).
"""
from __future__ import annotations

import datetime
import json
import logging
from urllib.parse import urlsplit

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from services import anticliche_cache
from services import hot_config as hot
from services import worker_budget
from services.anticliche_cache import ANTICLICHE_MAX_PATTERNS
from services.external_log import log_external_api, trace_step
from services.negative_constraints import (
    DEFAULT_ENABLED_RULES,
    dynamic_rule_code,
    find_forbidden_cliches,
    normalize_dynamic_phrase,
)

logger = logging.getLogger(__name__)

_JOB_ID = "anticliche_cache_refresh"

# Идентификатор/URL источника по умолчанию (дефолт — код-константа, Δ каталога=0).
SOURCE_ID_DEFAULT = "wikipedia"
SOURCE_URL_DEFAULT = (
    "https://en.wikipedia.org/w/api.php?action=query&prop=extracts"
    "&explaintext=1&format=json&redirects=1"
    "&titles=Wikipedia%3ASigns_of_AI_writing"
)
_SOURCE_ID_MANUAL = "manual"
MAX_SOURCE_CHARS = 60000
REFRESH_DAYS = 7

# Промпт извлечения паттернов — код-константа, НЕ перечисляет сами клише
# (иначе grep-тест тропов поймал бы запрет; ADR-1023-4 D4). Динамические
# фразы из PG в промпты никогда не подставляются.
EXTRACT_SYSTEM_PROMPT = (
    "Ты — редактор-аналитик. Тебе дан текст-справочник о признаках "
    "шаблонного машинного письма.\n"
    "Извлеки из него до {max} наиболее частых и узнаваемых шаблонных фраз "
    "(штампов), которые выдают машинно-сгенерированный текст.\n"
    "Правила:\n"
    "- фраза — короткая литеральная строка (2–120 символов) на русском языке;\n"
    "- без регулярных выражений, скобок и служебных символов;\n"
    "- каждая фраза уникальна;\n"
    "- верни СТРОГО JSON без пояснений: "
    '{{"patterns":[{{"phrase":"...","origin":"..."}}]}}\n'
    "- origin — короткая пометка, откуда шаблон (например, название раздела)."
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _host_label(url: str) -> str:
    """Host источника для лога (R17-safe: без query/кредов)."""
    try:
        return urlsplit(str(url or "")).hostname or "source"
    except Exception:  # pragma: no cover — defensive
        return "source"


def _refresh_level(status: str) -> int:
    """Штатные исходы (успех/пусто/скип по бюджету) → INFO, сбои → ERROR."""
    if status in ("ok", "empty", "budget_skip", "disabled"):
        return logging.INFO
    return logging.ERROR


def parse_patterns(raw) -> list[dict] | None:
    """Строгий разбор LLM-ответа → список ``{phrase, origin}``.

    Снимает markdown-fences и извлекает первый JSON-объект. ``None`` — ответ
    невалиден/усечён (воркер пишет ``parse_error`` и НЕ трогает кэш)."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    patterns = data.get("patterns")
    if not isinstance(patterns, list):
        return None
    out: list[dict] = []
    for item in patterns:
        if isinstance(item, dict):
            out.append({"phrase": item.get("phrase"),
                        "origin": item.get("origin")})
        elif isinstance(item, str):
            out.append({"phrase": item, "origin": ""})
    return out


def _safe_origin(value) -> str:
    try:
        return " ".join(str(value or "").split())[:120]
    except Exception:  # pragma: no cover - defensive
        return ""


def build_patterns(entries, *,
                   max_patterns: int = ANTICLICHE_MAX_PATTERNS) -> list[dict]:
    """Нормализация/дедуп/лимит/фильтр хардкод-дублей → список паттернов.

    Дедуп: по нормализованной фразе (внутри динамики) и против
    захардкоженных правил (фраза, которую уже ловит детектор, пропускается).
    """
    out: list[dict] = []
    seen: set[str] = set()
    if not isinstance(entries, (list, tuple)):
        return out
    for entry in entries:
        raw = entry.get("phrase") if isinstance(entry, dict) else entry
        origin = entry.get("origin") if isinstance(entry, dict) else ""
        phrase = normalize_dynamic_phrase(raw)
        if not phrase or phrase in seen:
            continue
        if find_forbidden_cliches(phrase, DEFAULT_ENABLED_RULES):
            continue
        seen.add(phrase)
        out.append({
            "code": dynamic_rule_code(phrase),
            "phrase": phrase,
            "origin": _safe_origin(origin),
            "added_at": _now_iso(),
        })
        if len(out) >= max(1, int(max_patterns)):
            break
    return out


async def fetch_source(url: str) -> str:
    """Скачать текст источника (Wikipedia action API JSON → extract)."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(
            url, headers={"User-Agent": "adminbot-anticliche/1.0"})
        status = int(getattr(response, "status_code", 0))
        if status != 200:
            # F2/ADR-1024-1: статус + усечённое тело ошибки источника.
            log_external_api(
                logger, provider=_host_label(url), method="GET", url=url,
                status=status, reason="fetch_http",
                body=getattr(response, "text", ""), level=logging.ERROR)
            response.raise_for_status()
        text = response.text
        try:
            data = response.json()
        except ValueError:
            data = None
    if isinstance(data, dict):
        pages = (data.get("query") or {}).get("pages") or {}
        if isinstance(pages, dict):
            for page in pages.values():
                extract = page.get("extract") if isinstance(page, dict) else None
                if isinstance(extract, str) and extract.strip():
                    return extract[:MAX_SOURCE_CHARS]
    return str(text or "")[:MAX_SOURCE_CHARS]


class AntiClicheWorker:
    """Недельный фоновый обновлятор динамического анти-клише кэша."""

    def __init__(self, *, llm=None, pg=None, fetch=None, scheduler=None,
                 source_id: str = SOURCE_ID_DEFAULT,
                 source_url: str = SOURCE_URL_DEFAULT):
        self._llm = llm
        self._pg = pg
        self._fetch = fetch or fetch_source
        self._scheduler = scheduler
        self._source_id = source_id
        self._source_url = source_url

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Регистрация недельного джоба — только при активном флаге."""
        if not anticliche_cache.enabled():
            logger.info("AntiClicheWorker disabled "
                        "(DYNAMIC_ANTICLICHE_ENABLED=False)")
            return
        if self._scheduler is None:
            tz = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
            self._scheduler = AsyncIOScheduler(timezone=tz)
        self._scheduler.add_job(
            self.tick,
            IntervalTrigger(days=REFRESH_DAYS, jitter=3600,
                            timezone=hot.get("limits.summary_timezone",
                                             settings.SUMMARY_TIMEZONE)),
            id=_JOB_ID, replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=3600)
        # Review iter1 (L8): не запускаем уже работающий внешний планировщик.
        if not getattr(self._scheduler, "running", False):
            self._scheduler.start()
        logger.info("AntiClicheWorker started | interval_days=%d", REFRESH_DAYS)
        trace_step(logger, component="anticliche", step="schedule", status="ok",
                   reason="started",
                   extra={"interval_days": REFRESH_DAYS,
                          "next_run_time": self._next_run_time() or "n/a"})

    def _next_run_time(self):
        """Ближайшее время прогона джоба (None — планировщик недоступен)."""
        try:
            scheduler = self._scheduler
            if scheduler is None:
                return None
            job = scheduler.get_job(_JOB_ID)
            return getattr(job, "next_run_time", None)
        except Exception:  # pragma: no cover — defensive
            return None

    async def stop(self) -> None:
        """Идемпотентная остановка планировщика."""
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler is None or not getattr(scheduler, "running", False):
            logger.info("AntiClicheWorker was not running — nothing to stop")
            return
        try:
            scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover - defensive
            logger.warning("[anticliche] scheduler shutdown failed", exc_info=True)
        logger.info("AntiClicheWorker stopped")

    async def tick(self) -> None:
        """Обёртка джоба: обновление кэша, ошибка не роняет тик (fail-open)."""
        try:
            result = await self.refresh()
            logger.info(
                "[anticliche] refresh | status=%s | count=%s | source=%s",
                result.get("status"), result.get("count"),
                result.get("source"))
            trace_step(
                logger, component="anticliche", step="refresh",
                status=result.get("status"), reason=result.get("source"),
                level=_refresh_level(str(result.get("status"))),
                extra={"count": result.get("count"),
                       "version": result.get("version"),
                       "next_run_time": self._next_run_time() or "n/a"})
        except Exception:
            logger.warning("[anticliche] tick failed (fail-open)",
                           exc_info=True)
            trace_step(
                logger, component="anticliche", step="refresh",
                status="error", reason="tick_exception",
                extra={"next_run_time": self._next_run_time() or "n/a"})

    # ── обновление ─────────────────────────────────────────────────────────

    async def refresh(self, *, source: str | None = None) -> dict:
        """Полный цикл забора источника → LLM → запись. Никогда не бросает.

        Возврат (R17-safe: коды/числа/идентификаторы источника):
        ``{status, count, version, source}``; ``status`` — ``ok|empty|
        fetch_error|llm_error|parse_error|budget_skip|disabled|write_error``.
        """
        source_id = source or self._source_id
        if not anticliche_cache.enabled():
            trace_step(logger, component="anticliche", step="gate",
                       status="skip", reason="disabled",
                       extra={"source": source_id})
            return {"status": "disabled", "count": 0, "version": 0,
                    "source": source_id}
        pg = self._pg if self._pg is not None else anticliche_cache.get_runtime_pg()

        try:
            text = await self._fetch(self._source_url)
        except Exception as exc:
            await anticliche_cache.mark_status(pg, "fetch_error")
            logger.warning("[anticliche] fetch failed | error=%s",
                           type(exc).__name__, exc_info=True)
            trace_step(logger, component="anticliche", step="fetch",
                       status="error", reason="fetch_error",
                       extra={"source": source_id,
                              "error": type(exc).__name__})
            return {"status": "fetch_error", "count": 0, "version": 0,
                    "source": source_id}

        # Review iter1 (L5): call списывается ровно перед LLM-вызовом
        # (неудачный fetch LLM-call не расходует).
        try:
            allowed = await worker_budget.consume(
                pg, "global", worker_budget.METRIC_CALLS)
        except Exception:
            allowed = True
        if not allowed:
            logger.info("[anticliche] skip: worker budget exhausted")
            trace_step(logger, component="anticliche", step="budget",
                       status="skip", reason="budget_skip",
                       extra={"source": source_id})
            return {"status": "budget_skip", "count": 0, "version": 0,
                    "source": source_id}

        try:
            raw = await self._call_llm(text)
        except Exception as exc:
            await anticliche_cache.mark_status(pg, "llm_error")
            logger.warning("[anticliche] llm failed | error=%s",
                           type(exc).__name__, exc_info=True)
            trace_step(logger, component="anticliche", step="llm",
                       status="error", reason="llm_error",
                       extra={"source": source_id,
                              "error": type(exc).__name__})
            return {"status": "llm_error", "count": 0, "version": 0,
                    "source": source_id}

        # Review iter1 (L5): токены — сразу после ответа LLM, независимо от
        # исхода разбора (вызов уже состоялся).
        try:
            await worker_budget.consume(
                pg, "global", worker_budget.METRIC_TOKENS,
                worker_budget.estimate_tokens(text)
                + worker_budget.estimate_tokens(raw))
        except Exception:
            pass

        entries = parse_patterns(raw)
        if entries is None:
            await anticliche_cache.mark_status(pg, "parse_error")
            logger.warning("[anticliche] parse failed — cache kept")
            trace_step(logger, component="anticliche", step="parse",
                       status="error", reason="parse_error",
                       extra={"source": source_id,
                              "raw_len": len(str(raw or ""))})
            return {"status": "parse_error", "count": 0, "version": 0,
                    "source": source_id}

        patterns = build_patterns(entries)
        # Review iter1 (H1): вырожденный (но валидный) ответ — эхо хардкода,
        # пустой список и т.п. — НЕ затирает предыдущий кэш. Пустая запись
        # допустима только через явный ручной PUT (`apply_manual`).
        if not patterns:
            data = await anticliche_cache.fetch_cache(pg)
            version = int((data or {}).get("version") or 0)
            await anticliche_cache.mark_status(pg, "empty")
            logger.warning(
                "[anticliche] empty result — cache kept | version=%s", version)
            trace_step(logger, component="anticliche", step="empty",
                       status="empty", reason="empty_result",
                       extra={"source": source_id, "version": version})
            return {"status": "empty", "count": 0, "version": version,
                    "source": source_id}

        try:
            version = await anticliche_cache.write_patterns(
                pg, patterns, source=source_id, source_url=self._source_url,
                fetched_at=datetime.datetime.now(datetime.timezone.utc))
        except Exception as exc:
            logger.warning("[anticliche] write failed | error=%s (cache kept)",
                           type(exc).__name__, exc_info=True)
            trace_step(logger, component="anticliche", step="write",
                       status="error", reason="write_error",
                       extra={"source": source_id,
                              "error": type(exc).__name__})
            return {"status": "write_error", "count": 0, "version": 0,
                    "source": source_id}
        return {"status": "ok", "count": len(patterns), "version": version,
                "source": source_id}

    async def _call_llm(self, source_text: str) -> str:
        if self._llm is None:
            raise RuntimeError("anticliche: LLM недоступен")
        messages = [
            {"role": "system",
             "content": EXTRACT_SYSTEM_PROMPT.format(max=ANTICLICHE_MAX_PATTERNS)},
            {"role": "user", "content": str(source_text or "")[:MAX_SOURCE_CHARS]},
        ]
        return await self._llm.generate_worker("background", messages)


async def apply_manual(pg, entries) -> dict:
    """Единый путь ручной правки (review iter1 L2): build + write.

    Нормализация/дедуп/лимит серверные; пустая запись допустима (ручная
    очистка); ``fetched_at`` не трогается (review iter1 L3). Используется и
    API `PUT /api/anticliche` — одна реализация бизнес-логики."""
    patterns = build_patterns(entries)
    version = await anticliche_cache.write_patterns(
        pg, patterns, source=_SOURCE_ID_MANUAL, source_url="", fetched_at=None)
    return {"status": "ok", "count": len(patterns), "version": version,
            "source": _SOURCE_ID_MANUAL}


# ── runtime-держатель воркера (DI для API ручного запуска/правки) ────────────
_runtime_worker: AntiClicheWorker | None = None


def set_runtime_worker(worker: AntiClicheWorker | None) -> None:
    global _runtime_worker
    _runtime_worker = worker


def get_runtime_worker() -> AntiClicheWorker | None:
    return _runtime_worker
