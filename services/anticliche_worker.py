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
from services import anticliche_sources as sources_registry
from services import hot_config as hot
from services import worker_budget
from services.agentic_events import emit_agentic_event
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
# Стабильный id локального источника в реестре (§3.1): ручные выражения и
# owner pinned. HTTP-статуса у него нет.
_SOURCE_ID_MANUAL = "local/manual"
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
    """F0.3 (§4.4) + A9 (ADR-1026-22 D11): структурированное событие
    ``event=ANTI_CLICHE_*`` через единую R17-safe обёртку ``emit_agentic_event``
    (второй логгер/канал не создаётся; kill-switch ``AGENTIC_EVENTS_ENABLED``).

    R17: логируем только коды/числа/идентификаторы и НИКОГДА — фразы/секреты."""
    emit_agentic_event(name, **fields)


# ── MCA-17 (группа «Фоновые воркеры сна/памяти»): событие anticliche.run ────
# Существующий agentic_events-контракт (ANTI_CLICHE_* выше) НЕ затрагивается:
# здесь только пары start+терминал через единый `emit_mca_event` (mca-13),
# не более одного терминала на refresh-цикл (без шума по раундам).
_ANTICLICHE_COMPONENT = "anticliche.run"

# Маппинг статуса `refresh` → (outcome §17.1, reason_code §17.2) — только
# существующие коды словаря; отсутствующего кода не изобретаем.
_ANTICLICHE_TERMINAL = {
    "ok": ("success", None),
    "partial_success": ("success", "provider_unavailable"),
    "empty": ("skipped", "no_new_contribution"),
    "unchanged": ("skipped", "stage_skipped"),
    "fresh": ("skipped", "cooldown"),
    "disabled": ("skipped", "disabled"),
    "budget_skip": ("skipped", "budget_exceeded"),
    "fetch_error": ("failed", "provider_unavailable"),
    "llm_error": ("failed", "model_unavailable"),
    "parse_error": ("failed", "parse_error"),
    "write_error": ("failed", None),
}


def _emit(event_name: str, outcome: str, *, level: str = "INFO",
          **fields) -> None:
    """Fail-open эмиссия события контракта §17.1 (REUSE `emit_mca_event`,
    mca-13; паттерн `graphrag_rebuild._emit`). R17: только коды/числа —
    без фраз/секретов."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(event_name, outcome=outcome, level=level, **fields)
    except Exception:      # контракт не рвёт поток воркера
        pass


def _normalize_stored(patterns) -> list[dict]:
    """F0.3: уже сохранённые паттерны → нормализованный список (для merge).

    Сохраняет `code`/`origin`/`added_at` и аддитивный провенанс AC-DATA
    (`source`/`source_revision`) как есть; дедуп по нормализованной фразе.
    НЕ применяет вместимость (её контролирует цикл добора)."""
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
        entry = {
            "code": item.get("code") or dynamic_rule_code(phrase),
            "phrase": phrase,
            "origin": _safe_origin(item.get("origin")),
            "added_at": item.get("added_at") or _now_iso(),
        }
        # AC-DATA §3.1: провенанс источника не теряется при слиянии.
        for key in ("source", "source_revision", "status", "strategy",
                    "family_id", "scope", "evidence"):
            value = item.get(key)
            if value not in (None, "", [], {}):
                entry[key] = value
        out.append(entry)
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


def _check_brief(check: dict) -> dict:
    """Краткая R17-safe выжимка проверки для ответа воркера/логов.

    Никаких тел документов и фраз — только коды/числа/идентификаторы.
    """
    return {
        "source_id": str(check.get("source_id") or ""),
        "check_id": str(check.get("check_id") or ""),
        "status": str(check.get("status") or ""),
        "http_status": check.get("http_status"),
        "content_status": str(check.get("content_status") or ""),
        "docs_fetched": int(check.get("docs_fetched") or 0),
        "docs_parsed": int(check.get("docs_parsed") or 0),
        "revision": str(check.get("revision") or ""),
        "changed": bool(check.get("changed")),
        "error_code": str(check.get("error_code") or ""),
        "next_attempt_at": check.get("next_attempt_at"),
        "paused_reason": str(check.get("paused_reason") or ""),
    }


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
    """Скачать текст источника (Wikipedia action API JSON → extract).

    Транспорт один — `anticliche_sources.fetch_document`; здесь сохранена
    прежняя сигнатура/поведение (текст или исключение) для совместимости.
    """
    text = await sources_registry.fetch_source_text(url)
    return text[:MAX_SOURCE_CHARS]


class AntiClicheWorker:
    """Недельный фоновый обновлятор динамического анти-клише кэша."""

    def __init__(self, *, llm=None, pg=None, fetch=None, scheduler=None,
                 source_id: str = SOURCE_ID_DEFAULT,
                 source_url: str = SOURCE_URL_DEFAULT,
                 sources=None, transport=None):
        self._llm = llm
        self._pg = pg
        # `fetch` — legacy-инъекция «url → текст» (тесты). Новый транспорт
        # отдаёт TransportResponse со статусом/заголовками.
        self._fetch = fetch or fetch_source
        self._transport = transport if transport is not None else fetch
        self._sources = tuple(sources) if sources is not None else None
        self._scheduler = scheduler
        self._source_id = source_id
        self._source_url = source_url

    def _registry(self):
        return self._sources or sources_registry.all_sources()

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
        """Полный цикл обновления (MCA-17 `anticliche.run`): событие start +
        ОДИН терминальный outcome на refresh-цикл (не на раунд добора).
        Существующий agentic_events-контракт (`ANTI_CLICHE_*`) не затронут.
        R17: только коды/числа. Тело — `_refresh_impl` (без изменений);
        контракт возврата прежний, метод по-прежнему никогда не бросает."""
        started = time.monotonic()
        _emit("anticliche_run", "start", component=_ANTICLICHE_COMPONENT)
        try:
            result = await self._refresh_impl(source=source, force=force)
        except Exception:
            _emit("anticliche_run", "failed",
                  component=_ANTICLICHE_COMPONENT,
                  duration_ms=int((time.monotonic() - started) * 1000))
            raise
        outcome, reason = _ANTICLICHE_TERMINAL.get(
            str((result or {}).get("status") or ""), ("failed", None))
        _emit("anticliche_run", outcome,
              component=_ANTICLICHE_COMPONENT, reason_code=reason,
              duration_ms=int((time.monotonic() - started) * 1000))
        return result

    # ── Stage A: независимые проверки источников (§3.3, §4.2) ──────────────

    def _analysis_allowed(self, source_id: str | None) -> bool:
        """Права/лицензия разрешают автоматический анализ этого источника."""
        source = next((item for item in self._registry()
                       if item.source_id == source_id), None)
        return bool(source is not None and source.analysis_eligible)

    def _due_sources(self, states: dict[str, dict]) -> tuple[list, list]:
        """Кому разрешена попытка прямо сейчас (анти-storm на 403/429)."""
        due: list = []
        paused: list[dict] = []
        for src in self._registry():
            if not src.auto_check:
                continue
            state = states.get(src.source_id)
            if not sources_registry.state_enabled(src, state):
                continue
            decision = sources_registry.attempt_decision(
                state, policy=src.retry)
            if decision.get("allowed"):
                due.append(src)
            else:
                paused.append({"source_id": src.source_id,
                               "reason": str(decision.get("reason") or ""),
                               "wait_seconds": decision.get("wait_seconds")})
        return due, paused

    async def check_one(self, source_id: str, *, manual: bool = True,
                        pg=None, trace_id: str | None = None) -> dict:
        """Явная проверка ОДНОГО источника: без LLM и без публикации.

        «Проверить доступ» ≠ «Загрузить и проанализировать» (§3.3): этот путь
        не вызывает модель, не меняет опубликованный набор и не обходит
        robot-policy (тот же User-Agent, адрес и транспорт).
        """
        source = sources_registry.get_source(source_id)
        if source is None:
            source = next((item for item in self._registry()
                           if item.source_id == source_id), None)
        if source is None:
            return {"source_id": str(source_id), "status": "unknown_source",
                    "error_code": "unknown_source"}
        target_pg = pg if pg is not None else (
            self._pg if self._pg is not None
            else anticliche_cache.get_runtime_pg())
        states = await sources_registry.fetch_states(target_pg)
        previous = states.get(source.source_id)
        check = await sources_registry.check_source(
            source, transport=self._transport, pg=target_pg,
            state=previous, manual=manual)
        await sources_registry.record_check(
            target_pg, check, source=source, previous=previous)
        sources_registry.emit_check_event(check, trace_id=trace_id)
        trace_step(
            logger, component="anticliche", step="source_check",
            status="ok" if sources_registry.is_success(check.get("status"))
            else "error",
            reason=str(check.get("status") or ""),
            extra={"source": source.source_id,
                   "http": check.get("http_status"),
                   "manual": bool(manual)})
        return check

    async def _refresh_impl(self, *, source: str | None = None,
                            force: bool = False) -> dict:
        """Источники → LLM-анализ → запись набора (LKG при любой ошибке).

        F7/ADR-1024-3 D2: при `force=False` и свежем `fetched_at` (младше
        REFRESH_DAYS) прогон пропускается без fetch/LLM (`status="fresh"`).

        Источники независимы: сбой одного не блокирует остальные; 403 policy
        не ретраится автоматически; 429 уважает `Retry-After`. Ошибка
        источника/LLM/PG оставляет активный набор и возвращает его РЕАЛЬНУЮ
        версию (не ложный ``0``).

        Возврат (R17-safe: коды/числа/идентификаторы источника):
        ``{status, count, version, rules, source, sources, checks, paused}``;
        ``status`` — ``ok|partial_success|empty|unchanged|fetch_error|
        llm_error|parse_error|budget_skip|disabled|write_error|fresh``.
        """
        source_hint = source or self._source_id
        pg = self._pg if self._pg is not None else anticliche_cache.get_runtime_pg()
        # AC-INV-08: действующий банк читается ДО гейтов — ранние выходы
        # (kill-switch/freshness-skip) обязаны отдавать РЕАЛЬНЫЕ version/rules,
        # а не ложные нули при целом опубликованном наборе (§1 п.8).
        stored = await anticliche_cache.fetch_cache(pg)
        current_version = int((stored or {}).get("version") or 0)
        current_rules = len(_normalize_stored((stored or {}).get("patterns")))
        bank = {"source": source_hint, "version": current_version,
                "rules": current_rules}

        if not anticliche_cache.enabled():
            trace_step(logger, component="anticliche", step="gate",
                       status="skip", reason="disabled",
                       extra={"source": source_hint,
                              "version": current_version})
            return {"status": "disabled", "count": 0, **bank}

        # F7/ADR-1024-3 D2: freshness-skip (рестарт-устойчиво, без job store).
        if not force and _is_fresh((stored or {}).get("fetched_at")):
            logger.info("[anticliche] skip: cache fresh | version=%s",
                        current_version)
            trace_step(logger, component="anticliche", step="gate",
                       status="skip", reason="fresh",
                       extra={"source": source_hint,
                              "version": current_version})
            return {"status": "fresh", "count": 0, **bank}

        # ── Stage A: SOURCE_FETCH — по источнику, независимо ────────────────
        states = await sources_registry.fetch_states(pg)
        due, paused = self._due_sources(states)
        checks: list[dict] = []
        if due:
            checks = await sources_registry.check_sources(
                due, transport=self._transport, pg=pg, states=states,
                manual=False)
        counts = sources_registry.summarize_checks(checks)
        usable = [c for c in checks
                  if c.get("changed")
                  and c.get("status") == sources_registry.STATUS_AVAILABLE
                  and str(c.get("text") or "").strip()
                  and self._analysis_allowed(c.get("source_id"))]
        unchanged = [c for c in checks
                     if c.get("status") == sources_registry.STATUS_UNCHANGED]
        problems = [c for c in checks
                    if sources_registry.is_problem(c.get("status"))]
        base = {
            **bank,
            "sources": counts,
            "checks": [_check_brief(c) for c in checks],
            "paused": paused,
        }

        if not due and not paused:
            # Нет ни одного включённого источника, участвующего в автоопросе.
            trace_step(logger, component="anticliche", step="gate",
                       status="skip", reason="no_enabled_sources",
                       extra={"source": source_hint})
            return {"status": "disabled", "count": 0, **base}

        if not usable:
            if unchanged:
                await anticliche_cache.mark_status(pg, "unchanged")
                logger.info("[anticliche] sources unchanged — LLM не "
                            "вызывалась | version=%s", current_version)
                trace_step(logger, component="anticliche", step="fetch",
                           status="skip", reason="unchanged",
                           extra={"sources": counts,
                                  "version": current_version})
                return {"status": "unchanged", "count": 0, **base}
            if not checks:
                # Все источники на cooldown (403 policy / Retry-After).
                logger.info("[anticliche] all sources paused | paused=%d",
                            len(paused))
                trace_step(logger, component="anticliche", step="gate",
                           status="skip", reason="sources_paused",
                           extra={"paused": len(paused)})
                return {"status": "fresh", "count": 0,
                        "paused_count": len(paused), **base}
            # Ни одного пригодного источника: LKG остаётся, версия не врёт.
            await anticliche_cache.mark_status(pg, "sources_unavailable")
            logger.warning("[anticliche] no usable source | problems=%d",
                           len(problems))
            trace_step(logger, component="anticliche", step="fetch",
                       status="error", reason="sources_unavailable",
                       extra={"problems": len(problems),
                              "version": current_version})
            return {"status": "fetch_error", "count": 0, **base}

        # ── Stage C-выход: bounded добор до ВМЕСТИМОСТИ, бюджет провайдера ──
        capacity = anticliche_cache.max_patterns()
        per_run = max_patterns_per_run()
        rounds_limit = max_rounds()
        merged = _normalize_stored((stored or {}).get("patterns"))
        initial_count = len(merged)
        seen = {p["phrase"] for p in merged}
        new_total = 0
        duplicates_total = 0
        candidates_total = 0
        applied_limit = 0
        rounds = 0
        no_new = False
        budget_stop = False
        contributing: list[str] = []
        started = time.monotonic()
        _event("ANTI_CLICHE_UPDATE_START", capacity=capacity, per_run=per_run,
               initial_count=initial_count, source=source_hint,
               sources=len(usable))

        for item in usable:
            if len(merged) >= capacity or rounds >= rounds_limit or budget_stop:
                break
            src_id = str(item.get("source_id") or "")
            revision = str(item.get("revision") or "")
            text = str(item.get("text") or "")[:MAX_SOURCE_CHARS]
            produced = 0
            while len(merged) < capacity and rounds < rounds_limit:
                want = min(per_run, capacity - len(merged))
                # Review iter1 (L5): call списывается ровно перед LLM-вызовом.
                try:
                    allowed = await worker_budget.consume(
                        pg, "global", worker_budget.METRIC_CALLS)
                except Exception:
                    allowed = True
                if not allowed:
                    budget_stop = True
                    break
                _event("ANTI_CLICHE_MODEL_REQUEST", round=rounds + 1,
                       per_run=per_run, applied_limit=want,
                       model=self._model_label(), source=src_id)
                t0 = time.monotonic()
                try:
                    raw = await self._call_llm(text, limit=want)
                except Exception as exc:
                    await anticliche_cache.mark_status(pg, "llm_error")
                    logger.warning("[anticliche] llm failed | error=%s",
                                   type(exc).__name__, exc_info=True)
                    trace_step(logger, component="anticliche", step="llm",
                               status="error", reason="llm_error",
                               extra={"source": src_id,
                                      "error": type(exc).__name__})
                    _event("ANTI_CLICHE_UPDATE_FAILED", status="llm_error",
                           reason="llm_error", model=self._model_label(),
                           source=src_id)
                    return {"status": "llm_error", "count": 0, **base}
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
                               extra={"source": src_id,
                                      "raw_len": len(str(raw or ""))})
                    _event("ANTI_CLICHE_PARSE_ERROR", round=rounds + 1,
                           raw_len=len(str(raw or "")), source=src_id)
                    _event("ANTI_CLICHE_UPDATE_FAILED", status="parse_error",
                           reason="parse_error", model=self._model_label(),
                           source=src_id)
                    return {"status": "parse_error", "count": 0, **base}
                candidates = build_patterns(entries, max_patterns=want)
                candidates_total += len(candidates)
                _event("ANTI_CLICHE_MODEL_RESPONSE", round=rounds + 1,
                       candidates=len(candidates), duration_ms=duration_ms,
                       model=self._model_label(), source=src_id)
                round_new = [p for p in candidates
                             if p["phrase"] not in seen]
                round_dups = max(0, len(candidates) - len(round_new))
                duplicates_total += round_dups
                _event("ANTI_CLICHE_DEDUP_COMPLETE", candidates=len(candidates),
                       duplicates=round_dups, source=src_id)
                if not round_new:
                    no_new = True        # «нет новых» — валидный успех
                    break
                for p in round_new:
                    p["source"] = src_id
                    if revision:
                        p["source_revision"] = revision
                    seen.add(p["phrase"])
                    merged.append(p)
                new_total += len(round_new)
                produced += len(round_new)
                applied_limit = want
                rounds += 1
                if len(candidates) < want:
                    # модель вернула меньше запрошенного → источник исчерпан
                    break
            if produced:
                contributing.append(src_id)

        if new_total == 0:
            # Вырожденный/пустой результат НЕ затирает кэш (только ручной PUT).
            version = current_version
            status = ("budget_skip" if budget_stop
                      else "empty" if no_new else "ok")
            if status == "empty":
                await anticliche_cache.mark_status(pg, "empty")
                logger.warning(
                    "[anticliche] no new patterns — cache kept | version=%s",
                    version)
                trace_step(logger, component="anticliche", step="empty",
                           status="empty", reason="no_new",
                           extra={"source": source_hint, "version": version})
            _event("ANTI_CLICHE_UPDATE_COMPLETE", status=status,
                   initial_count=initial_count, final_count=len(merged),
                   candidates=candidates_total, duplicates=duplicates_total,
                   saved=0, rounds=rounds,
                   duration_ms=int((time.monotonic() - started) * 1000))
            return {**base, "status": status, "count": 0,
                    "final_count": len(merged)}

        source_label = ",".join(sorted(set(contributing))) or source_hint
        try:
            version = await anticliche_cache.write_patterns(
                pg, merged, source=source_label, source_url=self._source_url,
                fetched_at=datetime.datetime.now(datetime.timezone.utc))
        except Exception as exc:
            logger.warning("[anticliche] write failed | error=%s (cache kept)",
                           type(exc).__name__, exc_info=True)
            trace_step(logger, component="anticliche", step="write",
                       status="error", reason="write_error",
                       extra={"source": source_label,
                              "error": type(exc).__name__})
            _event("ANTI_CLICHE_UPDATE_FAILED", status="write_error",
                   reason="write_error", model=self._model_label())
            return {**base, "status": "write_error", "count": 0}
        _event("ANTI_CLICHE_SAVE_COMPLETE", saved=new_total,
               final_count=len(merged), version=version, rounds=rounds,
               sources=len(contributing))
        # partial_success — честный итог, когда часть источников недоступна,
        # но опубликованный набор пополнен (§4.3).
        final_status = "partial_success" if problems else "ok"
        if problems:
            await anticliche_cache.mark_status(pg, "partial_success")
        _event("ANTI_CLICHE_UPDATE_COMPLETE", status=final_status,
               initial_count=initial_count, final_count=len(merged),
               candidates=candidates_total, duplicates=duplicates_total,
               saved=new_total, applied_limit=applied_limit, rounds=rounds,
               capacity=capacity, per_run=per_run,
               duration_ms=int((time.monotonic() - started) * 1000))
        return {**base, "status": final_status, "count": new_total,
                "final_count": len(merged), "version": version,
                "published": True, "source": source_label}

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
