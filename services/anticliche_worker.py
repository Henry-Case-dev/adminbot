"""F4 (T-2128, ADR-1023-4 D6) — недельный воркер динамического анти-клише кэша.

Раз в неделю забирает источник (по умолчанию — статья «Wikipedia:Signs of AI
writing» через action API), просит LLM извлечь паттерны до резолвленного лимита
(дефолт 200, регулируется ключом каталога ``limits.anticliche_max_patterns``;
ADR-1024-3 D1) строгим JSON-контрактом, нормализует/дедуплицирует и кладёт в
PG-таблицу ``anticliche_cache``. Динамические правила питают **детектор**
(validator-loop), а не scrubber и не промпт (ADR-1023-4 D1).

Устойчивость: сбой источника/LLM/parse → предыдущий кэш сохраняется, пишется
R17-safe ``last_status`` (коды/класс ошибки; сырьё и фразы НЕ логируются).
"""
from __future__ import annotations

import datetime
import json
import logging
import time
from urllib.parse import urlsplit

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from services import anticliche_cache
from services import hot_config as hot
from services import worker_budget
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
# F0.3 (раунд 10.25, ADR-1025-3 D2): bounded-цикл добора до ВМЕСТИМОСТИ.
# Лимит раундов — env-only `settings.ANTICLICHE_MAX_ROUNDS` (default 3).
_MAX_ROUNDS_DEFAULT = 3


def max_patterns_per_run() -> int:
    """F0.3: размер ПАРТИИ за один LLM-вызов (env-only, default 40).

    Отдельно от ВМЕСТИМОСТИ `anticliche_cache.max_patterns()` (сколько держим
    в БД). Clamp: `[1, capacity]` — партия не больше вместимости."""
    default = 40
    try:
        value = int(getattr(settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN",
                            default))
    except (TypeError, ValueError):  # pragma: no cover — defensive
        value = default
    return max(1, min(value, anticliche_cache.max_patterns()))


def max_rounds() -> int:
    """F0.3: лимит раундов добора (env-only, default 3; ≥1)."""
    try:
        value = int(getattr(settings, "ANTICLICHE_MAX_ROUNDS",
                            _MAX_ROUNDS_DEFAULT))
    except (TypeError, ValueError):  # pragma: no cover — defensive
        value = _MAX_ROUNDS_DEFAULT
    return max(1, value)


def _event(name: str, **fields) -> None:
    """F0.3 (§4.4): структурированное событие `event=ANTI_CLICHE_*`.

    R17: логируем только коды/числа/идентификаторы и НИКОГДА — фразы/секреты."""
    parts = " | ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("[anticliche] event=%s | %s", name, parts)


def _normalize_stored(patterns) -> list[dict]:
    """F0.3: уже сохранённые паттерны → нормализованный список (для merge).

    Сохраняет `code`/`origin`/`added_at` как есть; дедуп по нормализованной
    фразе. НЕ применяет вместимость (её контролирует цикл добора)."""
    out: list[dict] = []
    seen: set[str] = set()
    if not isinstance(patterns, (list, tuple)):
        return out
    for item in patterns:
        if not isinstance(item, dict):
            continue
        phrase = normalize_dynamic_phrase(item.get("phrase"))
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        out.append({
            "code": item.get("code") or dynamic_rule_code(phrase),
            "phrase": phrase,
            "origin": _safe_origin(item.get("origin")),
            "added_at": item.get("added_at") or _now_iso(),
        })
    return out

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
    """Штатные исходы (успех/пусто/скип) → INFO, сбои → ERROR."""
    if status in ("ok", "empty", "budget_skip", "disabled", "fresh", "skip"):
        return logging.INFO
    return logging.ERROR


def _first_run_delay_minutes() -> int:
    """Задержка первого прогона крона после старта (env-only, default 5)."""
    try:
        return max(0, int(getattr(settings, "ANTICLICHE_FIRST_RUN_DELAY_MINUTES",
                                 5)))
    except Exception:  # pragma: no cover — конфиг не должен ронять старт
        return 5


def _is_fresh(fetched_at, *, now=None) -> bool:
    """Свежесть кэша: `fetched_at` младше REFRESH_DAYS → refresh не нужен.

    Рестарт-устойчиво (источник истины — `fetched_at` в PG, без job store).
    Принимает `datetime` (asyncpg) или ISO-строку (тесты/фронт); None/мусор →
    не свежо (fail-open: прогон состоится)."""
    if fetched_at is None:
        return False
    moment = fetched_at
    if isinstance(moment, str):
        try:
            moment = datetime.datetime.fromisoformat(
                moment.strip().replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
    if not isinstance(moment, datetime.datetime):
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    current = now or datetime.datetime.now(datetime.timezone.utc)
    return (current - moment) < datetime.timedelta(days=REFRESH_DAYS)


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


def _safe_phrase(value) -> str:
    """R17-safe представление входной фразы для отчёта об отбросе.

    Отчёт отдаётся админу (не в лог): показываем, ЧТО именно не сохранилось,
    чтобы UI мог предупредить («Сохранено N из M»). Длина ограничена."""
    try:
        return str(value or "")[:200]
    except Exception:  # pragma: no cover - defensive
        return ""


def build_patterns_report(entries, *,
                          max_patterns: int | None = None,
                          manual: bool = False) -> dict:
    """Честная разбивка нормализации/дедупа/лимита (T-2489/T-2490).

    Возвращает ``{"saved": [...], "dropped": {"invalid", "hardcoded",
    "duplicate", "over_limit"}, "count": N, "hardcoded_flagged": [...],
    "total": M}`` — вместо молчаливого дропа. ``manual=True`` (ручная правка
    пользователя) **НЕ фильтрует** ``find_forbidden_cliches``: пользователь
    добавляет фразы осознанно, поэтому они сохраняются, а совпавшие с
    захардкод-клише лишь помечаются в ``hardcoded_flagged``. Ограничения
    ручного ввода — только длина/дубли/cap. ``max_patterns=None`` →
    резолвленный лимит ``anticliche_cache.max_patterns()`` (default 200).
    """
    dropped: dict[str, list[str]] = {
        "invalid": [], "hardcoded": [], "duplicate": [], "over_limit": []}
    flagged: list[str] = []
    out: list[dict] = []
    seen: set[str] = set()
    if not isinstance(entries, (list, tuple)):
        return {"saved": [], "dropped": dropped, "count": 0,
                "hardcoded_flagged": flagged, "total": 0}
    limit = (max_patterns if max_patterns is not None
             else anticliche_cache.max_patterns())
    limit = max(1, int(limit))
    for entry in entries:
        raw = entry.get("phrase") if isinstance(entry, dict) else entry
        origin = entry.get("origin") if isinstance(entry, dict) else ""
        phrase = normalize_dynamic_phrase(raw)
        if not phrase:
            dropped["invalid"].append(_safe_phrase(raw))
            continue
        if phrase in seen:
            dropped["duplicate"].append(phrase)
            continue
        hardcoded = bool(find_forbidden_cliches(phrase, DEFAULT_ENABLED_RULES))
        if hardcoded and not manual:
            dropped["hardcoded"].append(phrase)
            continue
        if len(out) >= limit:
            dropped["over_limit"].append(phrase)
            continue
        seen.add(phrase)
        if hardcoded:
            flagged.append(phrase)
        out.append({
            "code": dynamic_rule_code(phrase),
            "phrase": phrase,
            "origin": _safe_origin(origin),
            "added_at": _now_iso(),
        })
    return {"saved": out, "dropped": dropped, "count": len(out),
            "hardcoded_flagged": flagged, "total": len(entries)}


def build_patterns(entries, *,
                   max_patterns: int | None = None) -> list[dict]:
    """Нормализация/дедуп/лимит/фильтр хардкод-дублей → список паттернов.

    Тонкая обёртка над :func:`build_patterns_report` (авто-семантика:
    хардкод-клише отбрасываются). ``max_patterns=None`` → резолвленный лимит
    ``anticliche_cache.max_patterns()`` (default 200, регулируемый)."""
    return build_patterns_report(entries, max_patterns=max_patterns)["saved"]


async def fetch_source(url: str) -> str:
    """Скачать текст источника (Wikipedia action API JSON → extract)."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(
            url, headers={"User-Agent": "adminbot-anticliche/1.0"})
        status = int(getattr(response, "status_code", 0))
        if status >= 400:
            # F2/ADR-1024-1: статус + усечённое тело ошибки источника.
            log_external_api(
                logger, provider=_host_label(url), method="GET", url=url,
                status=status, reason="fetch_http",
                body=getattr(response, "text", ""), level=logging.ERROR)
        elif not 200 <= status < 300:
            # R1024F2-07: успешные 2xx (201/204…) ERROR'ом не шумим.
            log_external_api(
                logger, provider=_host_label(url), method="GET", url=url,
                status=status, reason="fetch_unexpected",
                body=getattr(response, "text", ""), level=logging.WARNING)
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
        """Регистрация недельного джоба — только при активном флаге.

        F7/ADR-1024-3 D2: первый прогон — **вскоре после старта**
        (`next_run_time = now + ANTICLICHE_FIRST_RUN_DELAY_MINUTES`), далее
        недельный `IntervalTrigger`. Рестарты не сдвигают окно: лишний запуск
        отсекает freshness-skip по `fetched_at` (см. `refresh`)."""
        if not anticliche_cache.enabled():
            logger.info("AntiClicheWorker disabled "
                        "(DYNAMIC_ANTICLICHE_ENABLED=False)")
            return
        tz_name = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler(timezone=tz_name)
        delay_minutes = _first_run_delay_minutes()
        next_run_time = (datetime.datetime.now(datetime.timezone.utc)
                         + datetime.timedelta(minutes=delay_minutes))
        self._scheduler.add_job(
            self.tick,
            IntervalTrigger(days=REFRESH_DAYS, jitter=3600,
                            timezone=tz_name),
            id=_JOB_ID, replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=3600,
            next_run_time=next_run_time)
        # Review iter1 (L8): не запускаем уже работающий внешний планировщик.
        if not getattr(self._scheduler, "running", False):
            self._scheduler.start()
        logger.info("AntiClicheWorker started | interval_days=%d | "
                    "first_run_delay_min=%d | next_run_time=%s",
                    REFRESH_DAYS, delay_minutes, next_run_time)
        trace_step(logger, component="anticliche", step="schedule", status="ok",
                   reason="started",
                   extra={"interval_days": REFRESH_DAYS,
                          "first_run_delay_min": delay_minutes,
                          "next_run_time": self._next_run_time()
                          or next_run_time.isoformat()})

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

    async def tick(self, *, force: bool = False) -> None:
        """Обёртка джоба: обновление кэша, ошибка не роняет тик (fail-open).

        ``force=False`` (штатный крон) → freshness-skip при свежем `fetched_at`;
        ``force=True`` — ручной прогон. Причина/итог/фаза — в лог (F2)."""
        try:
            result = await self.refresh(force=force)
            status = str(result.get("status"))
            skipped = status in ("fresh", "skip")
            logger.info(
                "[anticliche] refresh | status=%s | count=%s | source=%s",
                status, result.get("count"), result.get("source"))
            trace_step(
                logger, component="anticliche", step="refresh",
                status="skip" if skipped else status,
                reason="fresh" if status == "fresh" else result.get("source"),
                level=_refresh_level(status),
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

    async def refresh(self, *, source: str | None = None,
                      force: bool = False) -> dict:
        """Полный цикл забора источника → LLM → запись. Никогда не бросает.

        F7/ADR-1024-3 D2: при `force=False` и свежем `fetched_at` (младше
        REFRESH_DAYS) прогон пропускается без fetch/LLM (`status="fresh"`).

        Возврат (R17-safe: коды/числа/идентификаторы источника):
        ``{status, count, version, source}``; ``status`` — ``ok|empty|
        fetch_error|llm_error|parse_error|budget_skip|disabled|write_error|
        fresh``.
        """
        source_id = source or self._source_id
        if not anticliche_cache.enabled():
            trace_step(logger, component="anticliche", step="gate",
                       status="skip", reason="disabled",
                       extra={"source": source_id})
            return {"status": "disabled", "count": 0, "version": 0,
                    "source": source_id}
        pg = self._pg if self._pg is not None else anticliche_cache.get_runtime_pg()

        # F7/ADR-1024-3 D2: freshness-skip (рестарт-устойчиво, без job store).
        if not force:
            data = await anticliche_cache.fetch_cache(pg)
            if _is_fresh((data or {}).get("fetched_at")):
                version = int((data or {}).get("version") or 0)
                logger.info("[anticliche] skip: cache fresh | version=%s",
                            version)
                trace_step(logger, component="anticliche", step="gate",
                           status="skip", reason="fresh",
                           extra={"source": source_id, "version": version})
                return {"status": "fresh", "count": 0, "version": version,
                        "source": source_id}

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

        # F0.3 (ADR-1025-3 D2): пакетное bounded-пополнение до ВМЕСТИМОСТИ.
        # Партия за вызов ≤ per_run (в пределах выходного лимита модели);
        # дедуп против уже сохранённых + внутри партии; «0 новых» = успех.
        capacity = anticliche_cache.max_patterns()
        per_run = max_patterns_per_run()
        rounds_limit = max_rounds()
        stored = await anticliche_cache.fetch_cache(pg)
        merged = _normalize_stored((stored or {}).get("patterns"))
        initial_count = len(merged)
        seen = {p["phrase"] for p in merged}
        new_total = 0
        duplicates_total = 0
        candidates_total = 0
        final_status = "ok"
        applied_limit = 0
        rounds = 0
        started = time.monotonic()
        _event("ANTI_CLICHE_UPDATE_START", capacity=capacity, per_run=per_run,
               initial_count=initial_count, source=source_id)

        while len(merged) < capacity and rounds < rounds_limit:
            want = min(per_run, capacity - len(merged))
            # Review iter1 (L5): call списывается ровно перед LLM-вызовом.
            try:
                allowed = await worker_budget.consume(
                    pg, "global", worker_budget.METRIC_CALLS)
            except Exception:
                allowed = True
            if not allowed:
                final_status = "budget_skip"
                break
            _event("ANTI_CLICHE_MODEL_REQUEST", round=rounds + 1,
                   per_run=per_run, applied_limit=want,
                   model=self._model_label())
            t0 = time.monotonic()
            try:
                raw = await self._call_llm(text, limit=want)
            except Exception as exc:
                await anticliche_cache.mark_status(pg, "llm_error")
                logger.warning("[anticliche] llm failed | error=%s",
                               type(exc).__name__, exc_info=True)
                trace_step(logger, component="anticliche", step="llm",
                           status="error", reason="llm_error",
                           extra={"source": source_id,
                                  "error": type(exc).__name__})
                _event("ANTI_CLICHE_UPDATE_FAILED", status="llm_error",
                       reason="llm_error", model=self._model_label())
                return {"status": "llm_error", "count": 0, "version": 0,
                        "source": source_id}
            duration_ms = int((time.monotonic() - t0) * 1000)
            # Review iter1 (L5): токены — сразу после ответа LLM.
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
                _event("ANTI_CLICHE_PARSE_ERROR", round=rounds + 1,
                       raw_len=len(str(raw or "")))
                _event("ANTI_CLICHE_UPDATE_FAILED", status="parse_error",
                       reason="parse_error", model=self._model_label())
                return {"status": "parse_error", "count": 0, "version": 0,
                        "source": source_id}
            candidates = build_patterns(entries, max_patterns=want)
            candidates_total += len(candidates)
            _event("ANTI_CLICHE_MODEL_RESPONSE", round=rounds + 1,
                   candidates=len(candidates), duration_ms=duration_ms,
                   model=self._model_label())
            round_new = [p for p in candidates if p["phrase"] not in seen]
            round_dups = max(0, len(candidates) - len(round_new))
            duplicates_total += round_dups
            _event("ANTI_CLICHE_DEDUP_COMPLETE", candidates=len(candidates),
                   duplicates=round_dups)
            if not round_new:
                final_status = "empty"          # «нет новых» — валидный успех
                break
            for p in round_new:
                seen.add(p["phrase"])
                merged.append(p)
            new_total += len(round_new)
            applied_limit = want
            rounds += 1
            if len(candidates) < want:
                # модель вернула меньше запрошенного → источник исчерпан
                break
        if (new_total == 0 and rounds == 0 and final_status == "ok"
                and len(merged) >= capacity):
            # кэш уже полон — добор не нужен (не ошибка)
            final_status = "ok"

        if new_total == 0:
            # Вырожденный/пустой результат НЕ затирает кэш (только ручной PUT).
            version = int((stored or {}).get("version") or 0)
            if final_status == "empty":
                await anticliche_cache.mark_status(pg, "empty")
                logger.warning(
                    "[anticliche] no new patterns — cache kept | version=%s",
                    version)
                trace_step(logger, component="anticliche", step="empty",
                           status="empty", reason="no_new",
                           extra={"source": source_id, "version": version})
            _event("ANTI_CLICHE_UPDATE_COMPLETE", status=final_status,
                   initial_count=initial_count, final_count=len(merged),
                   candidates=candidates_total, duplicates=duplicates_total,
                   saved=0, rounds=rounds,
                   duration_ms=int((time.monotonic() - started) * 1000))
            return {"status": final_status, "count": 0, "version": version,
                    "final_count": len(merged), "source": source_id}

        try:
            version = await anticliche_cache.write_patterns(
                pg, merged, source=source_id, source_url=self._source_url,
                fetched_at=datetime.datetime.now(datetime.timezone.utc))
        except Exception as exc:
            logger.warning("[anticliche] write failed | error=%s (cache kept)",
                           type(exc).__name__, exc_info=True)
            trace_step(logger, component="anticliche", step="write",
                       status="error", reason="write_error",
                       extra={"source": source_id,
                              "error": type(exc).__name__})
            _event("ANTI_CLICHE_UPDATE_FAILED", status="write_error",
                   reason="write_error", model=self._model_label())
            return {"status": "write_error", "count": 0, "version": 0,
                    "source": source_id}
        _event("ANTI_CLICHE_SAVE_COMPLETE", saved=new_total,
               final_count=len(merged), version=version, rounds=rounds)
        _event("ANTI_CLICHE_UPDATE_COMPLETE", status="ok",
               initial_count=initial_count, final_count=len(merged),
               candidates=candidates_total, duplicates=duplicates_total,
               saved=new_total, applied_limit=applied_limit, rounds=rounds,
               capacity=capacity, per_run=per_run,
               duration_ms=int((time.monotonic() - started) * 1000))
        return {"status": "ok", "count": new_total,
                "final_count": len(merged), "version": version,
                "source": source_id}

    def _model_label(self) -> str:
        """F0.3: метка модели для события (R17-safe: не секрет/не фраза)."""
        llm = self._llm
        for attr in ("model", "model_name", "_model"):
            value = getattr(llm, attr, None)
            if isinstance(value, str) and value:
                return value
        return ""

    async def _call_llm(self, source_text: str, *, limit: int | None = None) -> str:
        if self._llm is None:
            raise RuntimeError("anticliche: LLM недоступен")
        # F0.3 (ADR-1025-3 D1): просим РАЗМЕР ПАРТИИ (≤ per_run), а НЕ
        # вместимость (200) — иначе ответ обрезается выходным лимитом модели.
        count = max_patterns_per_run() if not limit else max(1, int(limit))
        messages = [
            {"role": "system",
             "content": EXTRACT_SYSTEM_PROMPT.format(max=count)},
            {"role": "user", "content": str(source_text or "")[:MAX_SOURCE_CHARS]},
        ]
        return await self._llm.generate_worker("background", messages)


async def apply_manual(pg, entries) -> dict:
    """Единый путь ручной правки (review iter1 L2): build + write.

    Нормализация/дедуп/лимит серверные; пустая запись допустима (ручная
    очистка); ``fetched_at`` не трогается (review iter1 L3). Используется и
    API ``PUT /api/anticliche`` — одна реализация бизнес-логики.

    T-2490/T-2491 (ADR-1025-7 D2): ручные фразы **НЕ** фильтруются
    хардкод-правилами (``manual=True``) — пользователь добавляет их осознанно;
    совпавшие лишь помечаются в ``hardcoded_flagged``. Наружу отдаётся
    честный отчёт ``saved``/``dropped``/``count`` (200 ≠ «всё сохранено»)."""
    report = build_patterns_report(entries, manual=True)
    patterns = report["saved"]
    version = await anticliche_cache.write_patterns(
        pg, patterns, source=_SOURCE_ID_MANUAL, source_url="", fetched_at=None)
    return {"status": "ok", "count": len(patterns), "version": version,
            "source": _SOURCE_ID_MANUAL,
            "saved": report["saved"],
            "dropped": report["dropped"],
            "hardcoded_flagged": report["hardcoded_flagged"]}


# ── runtime-держатель воркера (DI для API ручного запуска/правки) ────────────
_runtime_worker: AntiClicheWorker | None = None


def set_runtime_worker(worker: AntiClicheWorker | None) -> None:
    global _runtime_worker
    _runtime_worker = worker


def get_runtime_worker() -> AntiClicheWorker | None:
    return _runtime_worker
