"""Раунд 9 (AGI Memory, spec §3.4, T-824/T-825) — DreamWorker: «сон» (beliefs).

Фоновый SQLite-воркер (каркас memory_maintenance.py/lore_worker.py, БЕЗ
PG-lock: состояние — SQLite dream_state/memory_dream_log, NFR-7).

F7 (settings-worker-sync, ADR-1018-7): тик-джоб регистрируется ВСЕГДА, а
решение «работать/не работать» принимается внутри тика/чата через единый
accessor `worker_settings` с приоритетом per-chat DB → глобальный DB →
env-дефолт. Это даёт реактивность без рестарта и закрывает рассинхрон
«UI ON в scope чата, бэкенд OFF». Пороги/лимиты в `_process_chat` резолвятся
по конкретному чату (`_key_for`). Запуск в bot.py on_startup после
lore-блока (fail-open); ручной run_once(chat_id) — для F2-API, окно диалогов
игнорирует (D-5), бюджеты/пороги — по чату.

Тик чата (§3.4.2–3.4.6, D-13):
1. чаты-кандидаты по dream_state-watermark (Q9: для чатов БЕЗ строки — окно
   прогрева limits.dream_initial_window_hours=168ч; новых ≥
   dream_min_new_facts_per_chat; «не пик» — нет сообщений за
   dream_quiet_check_minutes=30);
2. кандидаты: новые confirmed kind='fact' (id > watermark/окно), живые,
   источники «жизни чата» (chat_history/history_import/bot_direct_reply/
   user_memory), гейт protected-семантики (текст факта не входит в тексты
   protected_facts чата);
3. кластеризация БЕЗ LLM (D-4): жадные кластеры по значимым токенам (len≥5,
   не стоп) и именам участников (алиасы/roster, casefold);
4. в дистилляцию — кластеры с членами ≥ dream_repeat_threshold (3) И
   Σ importance ≥ dream_importance_sum_threshold (12), топ-K
   (dream_max_clusters_per_run=5) по Σ importance DESC;
5. дистилляция — 1 облачный LLM-вызов на кластер (llm.generate,
   temperature=0.3; DREAM_DISTILL_PROMPT): только в окне [4, 6) local
   (иначе window_skip, тик жив, watermark НЕ двигается); бюджеты в сутки —
   дистилляции (dream_distillations_per_day) и токены (dream_tokens_per_day,
   оценка по memory_dream_log.tokens) — стоп тика (WARNING); «почти у
   предела» (<5 дистилляций/<5000 токенов) — завершение заранее;
6. запись beliefs: insert_graph_fact(origin='derived_belief', kind='belief',
   weight=_DREAM_BELIEF_WEIGHT, importance=min(10, Σ источников),
   source_ids=JSON, belief_meta=JSON, expires_at=None); belief без ≥2 реальных
   source_ids НЕ пишется (анти-галлюцинации); supersede: новый belief
   supersedes старый того же чата с тем же якорным токеном темы (D-6,
   UPDATE supersedes, status НЕ меняется); эмбеддинг — боевой embed-путь
   (неудача → факт живёт текстом+FTS);
7. аудит memory_dream_log: строка kind='run' на тик-чат + строка на попытку
   дистилляции (distilled/skipped/error; window_skip в status);
   watermark (dream_state) двигается ТОЛЬКО по успеху полного тик-батча
   чата; при LLM-ошибке — НЕ двигается мимо упавшего кластера (повтор на
   следующем тике); при window/budget-стопе — не двигается вовсе.

Fail-open (NFR-4): ошибка чата — WARNING, тик жив; бот не падает.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import math
import re
import time

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo

from config.settings import settings
from services import hot_config as hot
from services.worker_settings import resolve_setting_cached
from services.database import parse_belief_meta, row_get
from services.dream_prompts import (
    DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT,
    DREAM_DISTILL_PROMPT,
    build_bridge_user,
    build_dream_user,
    order_dream_rows,
    parse_bridge_answer,
    parse_distill_answer,
)


def _tick_jitter(base_minutes: int) -> int:
    """Случайный сдвиг тика (worker_budget.jitter_safe ≤ interval/3);
    0 — если jitter явно не задан (тесты/конфиг без ключа)."""
    import random
    try:
        from services import worker_budget
        if not worker_budget.jitter_active():
            return 0
        return random.randint(0, worker_budget.jitter_safe(base_minutes))
    except Exception:
        return 0


async def _dream_budget_ok(chat_id: int, user_text: str, *,
                           manual: bool = False) -> bool:
    """F-10 §5: consume до LLM-вызова дистилляции — global + chat:<id>
    (calls 1 + tokens est); любое False → budget-скип. Fail-open внутри
    consume (PG down → True). ФИКС R4: приоритетная деградация по
    global-лимиту (dream падает первым до consume — allowed_workers).

    F2 (ADR-1018-2 D2, spec §4.2, T-1715/T-1767): `manual=True` — ручной
    запуск обходит экономические гейты БЕЗУСЛОВНО (деградация/лимит не
    отклоняют), но расход `worker_budget.consume` всё равно записывается
    (fail-open учёт стоимости). Никаких фича-флагов."""
    from services import worker_budget
    degraded = not await worker_budget.global_degradation_allows("dream")
    if degraded:
        if not manual:
            logger.warning(
                "[dream] skip: global budget exhausted — degradation dream | "
                "chat=%s", chat_id)
            return False
        logger.warning(
            "[dream] manual override: global budget degradation | chat=%s",
            chat_id)
    est = worker_budget.estimate_tokens(user_text)
    if manual:
        # D3/T-1771: при manual все 4 consume выполняются НЕЗАВИСИМО (иначе
        # короткое замыкание цепочки теряло бы часть per-chat статистики),
        # verdict не применяется — ручной запуск приоритетен (UPD п.5).
        await worker_budget.consume(None, "global", "llm_calls", 1)
        await worker_budget.consume(None, "global", "llm_tokens", est)
        await worker_budget.consume(None, f"chat:{chat_id}", "llm_calls", 1)
        await worker_budget.consume(None, f"chat:{chat_id}", "llm_tokens", est)
        return True
    ok = await worker_budget.consume(None, "global", "llm_calls", 1)
    if ok:
        ok = await worker_budget.consume(None, "global", "llm_tokens", est)
    if ok:
        ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                         "llm_calls", 1)
    if ok:
        ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                         "llm_tokens", est)
    return ok

logger = logging.getLogger(__name__)

_DREAM_BELIEF_WEIGHT = 0.6       # spec §3.4.6: вес belief (константа)
_DREAM_MAX_BELIEFS = 2           # spec §3.4.5: 0–2 убеждения на кластер
_DREAM_MAX_USER_FACTS = 25       # user-блок дистилляции: до 25 фактов
_DREAM_NEAR_LIMIT_DIST = 5       # §3.4.4: «почти у предела» дистилляций
_DREAM_NEAR_LIMIT_TOKENS = 5000  # §3.4.4: «почти у предела» токенов
_DREAM_PARTICIPANT_WINDOW_DAYS = 7  # окно имён участников (roster)
_DREAM_PARTICIPANT_CAP = 150     # потолок имён/участников на чат

# ── F2 (cognition-belief-decay, spec §4.1/§4.3): охлаждение + реаниматор ────
BELIEF_DECAY_INTERVAL_DAYS = 3   # шаг пересмотра — не чаще раз в 3 дня
_REANIMATE_ARCHIVE_CAP = 50      # потолок архивных beliefs на сверку сна

# ── F3 (cognition-deep-sleep, spec §2–§4): «глубокий сон» (парадигмы) ──────
_DEEP_SLEEP_LOOKBACK_HOURS = 12      # окно «свежей активности» (spec §2)
_DEEP_SLEEP_SUMMARY_MAX_CHARS = 6000  # потолок выжимки 12ч (spec §2)
_DEEP_SLEEP_MIN_ANCHOR_AGE_DAYS = 90  # «историческим» считается якорь старше
_DEEP_SLEEP_MIN_HISTORICAL = 2        # меньше 2 исторических опор — skip
_DEEP_SLEEP_MIN_INTERVAL_HOURS = 20   # cooldown против наложений/циклов
_DEEP_SLEEP_WEIGHT = 0.55             # вес парадигмы в контексте (0.5–0.6)
# F2 persona-storage-core (spec §3.4): окно свежих self-фактов для анализа
# эволюции характера бота.
_PERSONA_SELF_LOOKBACK_DAYS = 30
_DEEP_SLEEP_USER_JOB_ID = "deep_sleep_tick"
# R10.18-5: кап deep-прогонов при manual-каскаде БЕЗ явной цели — не более
# одного чата (а не до max_chats_per_run LLM-прогонов за один клик).
_MANUAL_DEEP_CASCADE_MAX = 1
# S10.18-23: срок жизни маркера РУЧНОГО прогона (совпадает с таймаутом бейджа
# `_DREAM_RUN_TIMEOUT_SECONDS=900` в memory_agi) — API отличает ручной запуск
# от транзиентного авто-тика вне окна по этому маркеру, а не по `!in_window`.
_MANUAL_RUN_MARKER_SECONDS = 900

# ── F3 (sleep-unblock-diagnostics-round1015, spec §3): fallback-пороги ──────
# «0 убеждений за N дней» → временно снижаем требования гейта (код-константы,
# каталог-Δ=0). Базовые memory.dream_repeat_threshold/importance_sum_threshold
# НЕ меняются; fallback самоотключается при первом же синтезе.
# S10.18-24: после F2 (дефолты repeat=2/sum=8) `_FALLBACK_MIN_IMPORTANCE_SUM`
# опущен 8→6 — иначе fallback стал бы no-op (оба порога равны дефолтам).
# Размер кластера НЕ опускаем ниже 2: одиночный факт — мусор
# (`test_single_fact_rejected_even_in_fallback`), поэтому fallback ослабляет
# только Σ-важность (6 < дефолтных 8).
_FALLBACK_WINDOW_DAYS = 3            # окно «тишины» синтеза, дней
_FALLBACK_MIN_CLUSTER_SIZE = 2       # min_cluster_size в fallback (= дефолт 2)
_FALLBACK_MIN_IMPORTANCE_SUM = 6     # min_importance_sum в fallback (< деф. 8)

# Источники «жизни чата» для дистилляции (обсуждение кандидатов §3.4.3:
# только переписка/личное; производные контенты (search/web/youtube/voice/
# video) и сами beliefs НЕ передистиллируются — не создаём рекурсию).
_DREAM_SOURCE_ORIGINS = ("chat_history", "history_import",
                         "bot_direct_reply", "user_memory")

_WORD_RE = re.compile(r"[a-zа-яё]{5,}", re.IGNORECASE)


def significant_tokens(text: str) -> list[str]:
    """Значимые токены факта (§3.4.3): слова len≥5 (стоп-слова списка spec
    короче 5 символов — отсекаются длиной), casefold."""
    return [m.group(0).casefold()
            for m in _WORD_RE.finditer(str(text or ""))]


def _now_ts() -> int:
    """Текущее unix-время (обёртка — тесты подменяют день для бюджетов)."""
    return int(time.time())


def _deep_result(status: str, *, paradigms: int = 0, tokens: int = 0,
                 traits: int = 0) -> dict:
    """D7/T-1771: единая форма результата шага глубокого сна — все ранние
    return'ы несут одинаковый набор ключей (status/paradigms/tokens/traits).
    `_run_deep_all`/`run_once(deep=True)` больше не получают dict без
    `traits`."""
    return {"status": status, "paradigms": int(paradigms),
            "tokens": int(tokens), "traits": int(traits)}


def _hot_number(key: str, default, cast):
    """S10.13-7: чтение числового hot-ключа с честным учётом нуля.

    `hot.get(key, default) or default` подменял валидный 0 (отключить
    кап/декай/cooldown) дефолтом. Здесь None/'' → default, иначе cast(val)."""
    val = hot.get(key, None)
    if val is None or val == "":
        return cast(default)
    try:
        return cast(val)
    except (TypeError, ValueError):
        return cast(default)


def _day_start_ts(now_ts: int, tz_name: str | None = None) -> int:
    """Начало local-суток (полночь в timezone сна) — для бюджетов §3.4.4."""
    try:
        zone = ZoneInfo(str(tz_name)) if tz_name else None
    except Exception:
        zone = None
    local = datetime.datetime.fromtimestamp(now_ts, zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


def _local_hour(now_ts: int, tz_name: str | None = None) -> int:
    """Текущий local-час в timezone сна (окно дистилляций §3.4.2/D-5)."""
    try:
        zone = ZoneInfo(str(tz_name)) if tz_name else None
    except Exception:
        zone = None
    return datetime.datetime.fromtimestamp(now_ts, zone).hour


def greedy_cluster_facts(rows: list, *, overlap_tokens: int = 2,
                         extra_terms=()) -> list[list]:
    """Жадная кластеризация БЕЗ LLM (spec §3.4.3/D-4): факты по id ASC;
    факт входит в ПЕРВЫЙ кластер с ≥ `overlap_tokens` общими значимыми
    токенами (слово len≥5 ИЛИ имя-участник из extra_terms, встреченное в
    тексте); иначе — новый кластер. Чистая функция (тесты группировки)."""
    extra = sorted({str(t).casefold() for t in extra_terms if str(t).strip()})
    clusters: list[list] = []
    cluster_tokens: list[set] = []
    for row in rows:
        low = str(row.get("fact") or "").casefold()
        toks = set(significant_tokens(low))
        for term in extra:
            if term in low:
                toks.add(term)
        placed = False
        for idx in range(len(clusters)):
            if len(toks & cluster_tokens[idx]) >= max(1, int(overlap_tokens)):
                clusters[idx].append(row)
                cluster_tokens[idx] |= toks
                placed = True
                break
        if not placed:
            clusters.append([row])
            cluster_tokens.append(toks)
    return clusters


class DreamWorker:
    """Фоновый синтез убеждений из повторяющихся фактов чата («сон»)."""

    JOB_DREAM_ID = "dream_tick"

    def __init__(self, db, memory=None, llm=None) -> None:
        self.db = db
        self.memory = memory          # MemoryManager (эмбеддинг beliefs)
        self.llm = llm                # облачный LLMClient (NFR-1)
        self._run_lock = asyncio.Lock()
        # F3 (cognition-deep-sleep): отдельный лок глубокого сна — не
        # блокирует обычный тик и наоборот; 1 прогон одновременно.
        self._deep_lock = asyncio.Lock()
        self._last_chat_ids: list[int] = []      # чаты последнего _run
        self._last_run_started: int = 0          # старт последнего обычного сна
        # S10.18-23: настоящий признак РУЧНОГО прогона (выставляется только в
        # `run_once`), а не вывод «running вне окна». API отдаёт `manual` из
        # него и не растягивает `active_until` для авто-тика вне окна.
        self._manual_run_until: int = 0
        self._manual_deep_until: int = 0
        # S10.18-29: идёт ли РУЧНОЙ deep-прогон прямо сейчас. Прогон длиннее
        # `_MANUAL_RUN_MARKER_SECONDS` (15 мин) не теряет `manual` до своего
        # конца: `manual_deep_active` = флаг ИЛИ TTL-маркер.
        self._manual_deep_run: bool = False
        tz = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
        self._tz_name = str(tz or "UTC")
        # S10.13-8 (spec F3 §3): сутки/час глубокого сна считаются в
        # WORKER_BUDGET_TZ (как worker_budget), не в SUMMARY_TIMEZONE.
        deep_tz = hot.get("limits.worker_budget_tz", settings.WORKER_BUDGET_TZ)
        self._deep_tz_name = str(deep_tz or "UTC")
        self._scheduler = AsyncIOScheduler(timezone=self._tz_name)

    # ── ключи (hot с фолбэком settings; категория memory, spec §3.6.4) ──

    def _key(self, name: str, default):
        """Глобальный helper (обратная совместимость): hot.get → default.
        Для per-chat резолва — `_key_for(chat_id, ...)`."""
        return hot.get(f"memory.dream_{name}", default)

    async def _key_for(self, chat_id: int, name: str, default):
        """F7: per-chat резолв `memory.dream_<name>` (chat DB → global DB →
        env-дефолт). Fail-open внутри accessor."""
        return await resolve_setting_cached(
            f"memory.dream_{name}", chat_id=chat_id, default=default)

    async def _dream_master_on(self) -> bool:
        """F7/S10.18-4: глобальный master-флаг Сна (`memory.dream_enabled`,
        chat_id=None → global DB → env). Гейтит глобальный шаг decay."""
        return bool(await resolve_setting_cached(
            "memory.dream_enabled", default=settings.DREAM_ENABLED))

    # ── F3 (sleep-unblock-diagnostics-round1015, spec §3): fallback ──────

    async def _sleep_fallback_active(self, now: int) -> bool:
        """«0 убеждений за `_FALLBACK_WINDOW_DAYS` дней» (глобально).

        Источник — memory_dream_log kind='distilled' через существующий
        `db.last_run_at` (не таблица beliefs: не зависит от статуса). Нет
        строки ИЛИ последняя старше окна → True (fallback-пороги 2/8).
        Fail-safe: ошибка БД → False (работаем на базовых порогах)."""
        try:
            last = await self.db.last_run_at(("distilled",), chat_id=None)
        except Exception:
            logger.warning("[dream] fallback detect failed — base thresholds",
                           exc_info=True)
            return False
        if last is None:
            return True
        return int(last) < int(now) - _FALLBACK_WINDOW_DAYS * 86400

    # ── служебное (F2-API, spec §3.6.2) ──────────────────────────────────

    @property
    def running(self) -> bool:
        """Идёт ли прогон (ручной run_once/тик/глубокий сон) — анти-рейс
        409 в API."""
        return self._run_lock.locked() or self._deep_lock.locked()

    @property
    def dream_running(self) -> bool:
        """F5/§3.2: идёт ли ОБЫЧНЫЙ сон (бейдж [🌙 Сон активен])."""
        return self._run_lock.locked()

    @property
    def deep_running(self) -> bool:
        """F5/§3.2: идёт ли ГЛУБОКИЙ сон (бейдж [🌌 Глубокий сон активен])."""
        return self._deep_lock.locked()

    @property
    def manual_run_active(self) -> bool:
        """S10.18-23: был ли недавно явный РУЧНОЙ прогон обычного сна.

        Маркер выставляет только `run_once` (на `_MANUAL_RUN_MARKER_SECONDS`);
        авто-тик его не трогает. API (`memory_agi.cognition_status`) использует
        это для поля `dream.manual` — «running вне окна» больше не трактуется
        как ручной запуск."""
        return int(self._manual_run_until) > _now_ts()

    @property
    def manual_deep_active(self) -> bool:
        """S10.18-23/S10.18-29: идёт ли/был ли недавно явный РУЧНОЙ прогон
        глубокого сна. Флаг `_manual_deep_run` держит `manual` на протяжении
        всего прогона (в т.ч. >15 мин), TTL-маркер — для бейджа после него."""
        if self._manual_deep_run:
            return True
        return int(self._manual_deep_until) > _now_ts()

    # ── планировщик ───────────────────────────────────────────────

    def start(self) -> None:
        """F7 (ADR-1018-7 D4): джобы dream_tick и deep_sleep_tick
        регистрируются **ВСЕГДА** (независимо от текущего значения флага);
        решение «работать/не работать» принимается ВНУТРИ тика по резолву
        (chat → global → default). Поэтому переключение тумблера в админке
        действует без `systemctl restart`. Повторный start — идемпотентен
        (replace_existing).

        Интервал тика (`memory.dream_tick_minutes`) и jitter фиксируются на
        старте (IntervalTrigger создаётся один раз): изменение интервала
        применяется при рестарте — это осознанная граница (фиксируется в
        логе маркером `applies on restart`).

        F3/T-1435: отдельный джоб deep_sleep_tick обслуживает режим
        trigger='fixed' (свой local-час); режим after_sleep запускается
        хуком после обычного `_run`."""
        # Раунд 10 (F-10 §5.2): jitter тика (случайный сдвиг ≤ интервал/3)
        # — ТОЛЬКО при явном ключе worker_budget_jitter_minutes.
        base_minutes = int(self._key("tick_minutes",
                                     settings.DREAM_TICK_MINUTES) or 60)
        tick_minutes = base_minutes + _tick_jitter(base_minutes)
        self._scheduler.add_job(
            self._tick,
            IntervalTrigger(minutes=tick_minutes, timezone=self._tz_name),
            id=self.JOB_DREAM_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        logger.info(
            "DreamWorker job registered (enabled resolved per-tick) | "
            "tick_minutes=%s (applies on restart)", base_minutes)
        self._scheduler.add_job(
            self._deep_tick,
            IntervalTrigger(minutes=tick_minutes, timezone=self._tz_name),
            id=_DEEP_SLEEP_USER_JOB_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        logger.info(
            "DeepSleep job registered (enabled resolved per-tick) | "
            "tick_minutes=%s (applies on restart)", base_minutes)
        if not self._scheduler.running:
            self._scheduler.start()

    async def stop(self) -> None:
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("DreamWorker stopped")
        except SchedulerNotRunningError:
            logger.info("DreamWorker was not running — nothing to stop")

    # ── точки входа ───────────────────────────────────────────────

    async def _tick(self) -> None:
        """Scheduler-джоб: тик «сна». Окно дистилляций [4,6) соблюдается;
        анти-рейс с ручным run_once — _run_lock. F3: после завершения
        обычного сна — хук глубокого сна (режим after_sleep).

        F7 (ADR-1018-7 D4): джоб зарегистрирован ВСЕГДА, поэтому раннего
        выхода «по глобальному флагу» здесь НЕТ — глобальный OFF не отменяет
        тик: у конкретного чата может быть явный per-chat override ON (это и
        есть симптом владельца). Итоговое решение «работать/не работать»
        принимается ПО КАЖДОМУ чату в `_process_chat` (через `_key_for` →
        `resolve_setting_cached`, с логом `source=`). Выключение on-the-fly
        не прерывает активный прогон (уважает `_run_lock`)."""
        if self._run_lock.locked():
            return
        stats = None
        async with self._run_lock:
            try:
                stats = await self._run(manual=False)
            except Exception:
                logger.warning("[dream] tick failed — fail-open", exc_info=True)
        try:
            await self._maybe_deep_after_sleep(stats, manual=False)
        except Exception:
            logger.warning("[dream] deep sleep after tick failed — fail-open",
                           exc_info=True)

    async def run_once(self, chat_id: int | None = None, *,
                       deep: bool = False) -> dict:
        """Ручной запуск «синтеза сейчас» (F2-API): окно диалогов НЕ
        применяется (D-5), а kill-switch и суточные бюджеты/near-limit
        обходятся БЕЗУСЛОВНО (ADR-1018-2 D2, T-1715/T-1767) — расход
        `worker_budget.consume` при этом всё равно пишется. Идущий прогон →
        immediate {"status": "already_running"} (409-паттерн API).
        Возвращает аддитивный `stats["cascade"] = {"deep":…, "traits":…}`.

        F3/T-1435: deep=True — ручной запуск ГЛУБОКОГО сна (staged rollout
        §8: POST /api/memory/dream/run?deep=1); игнорирует cooldown/флаг
        автозапуска и суточный deep-кап (явное действие админа)."""
        # S10.18-23: маркер ручного прогона — API отличает ручной запуск от
        # транзиентного авто-тика вне окна по нему, а не по `!in_window`.
        # Ставим маркер только если прогон реально стартует (не 409).
        if deep:
            if self._deep_lock.locked():
                return {"status": "already_running"}
            self._manual_deep_until = _now_ts() + _MANUAL_RUN_MARKER_SECONDS
            try:
                stats = await self._run_deep_all(
                    [chat_id] if chat_id is not None else None, manual=True)
            except Exception:
                logger.warning("[dream] deep run_once failed — fail-open",
                               exc_info=True)
                return {"status": "error"}
            return {"status": "ok", **stats}
        if self._run_lock.locked():
            return {"status": "already_running"}
        self._manual_run_until = _now_ts() + _MANUAL_RUN_MARKER_SECONDS
        async with self._run_lock:
            try:
                stats = await self._run(manual=True, only_chat=chat_id)
            except Exception:
                logger.warning("[dream] run_once failed — fail-open",
                               exc_info=True)
                return {"status": "error"}
        # F2 (T-1716): manual-каскад Сон → Глубокий сон → Личность. Результат
        # аддитивно кладём в stats["cascade"] (контракт 202 не ломается).
        deep_stats = {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 0,
                      "traits": 0}
        try:
            deep_stats = await self._maybe_deep_after_sleep(
                stats, manual=True, only_chat=chat_id)
        except Exception:
            logger.warning("[dream] deep sleep after run_once failed — "
                           "fail-open", exc_info=True)
        stats["cascade"] = {
            "deep": deep_stats,
            "traits": {"written": int(deep_stats.get("traits") or 0)},
        }
        return {"status": "ok", **stats}

    # ── тик ───────────────────────────────────────────────────────

    async def _run(self, *, manual: bool,
                   only_chat: int | None = None) -> dict:
        now = _now_ts()
        self._last_run_started = now
        stats = {"chats": 0, "clusters": 0, "distilled": 0, "unchanged": 0,
                 "errors": 0, "window_skips": 0, "budget_stop": False}
        # F2/T-1425 (spec §6): шаг охлаждения убеждений — ПЕРЕД обработкой
        # чатов, под флагом flags.belief_decay_enabled; fail-open.
        # F7/S10.18-4: decay — ГЛОБАЛЬНЫЙ этап цикла Сна (охлаждает beliefs
        # всех чатов), поэтому дополнительно гейтится глобальным master-флагом
        # `memory.dream_enabled`. Иначе «джоб всегда зарегистрирован» (D4)
        # сделал бы decay достижимым при выключенном Сне — побочный эффект,
        # которого до 10.18 не было. Per-chat резолв здесь неприменим.
        if await self._dream_master_on():
            try:
                await self._maybe_decay(now)
            except Exception:
                logger.warning("[dream] belief decay failed — fail-open",
                               exc_info=True)
        if only_chat is not None:
            chats = [{"chat_id": int(only_chat), "new_count": 0,
                      "max_fact_id": 0}]
        else:
            chats = await self.db.get_dream_candidate_chats(
                now,
                origins=_DREAM_SOURCE_ORIGINS,
                initial_window_hours=int(self._key(
                    "initial_window_hours",
                    settings.DREAM_INITIAL_WINDOW_HOURS) or 168),
                min_new_facts=int(self._key(
                    "min_new_facts_per_chat",
                    settings.DREAM_MIN_NEW_FACTS_PER_CHAT) or 5),
                max_chats=int(self._key(
                    "max_chats_per_run",
                    settings.DREAM_MAX_CHATS_PER_RUN) or 10),
                quiet_after_ts=now - int(self._key(
                    "quiet_check_minutes",
                    settings.DREAM_QUIET_CHECK_MINUTES) or 30) * 60)
        # F3/T-1435: запоминаем чаты прогона — хук after_sleep запустит по ним
        # глубокий сон сразу после завершения обычного (spec §3).
        self._last_chat_ids = [int(c["chat_id"]) for c in chats]
        if not chats:
            logger.info("[dream] tick: no candidate chats")
            return stats
        # F3 (spec §9): детект fallback — ОДИН раз на тик (не на чат).
        fallback_active = await self._sleep_fallback_active(now)
        for chat in chats:
            result = await self._process_chat(chat["chat_id"], now,
                                              manual=manual,
                                              fallback_active=fallback_active)
            stats["chats"] += 1
            stats["clusters"] += result["clusters"]
            stats["distilled"] += result["distilled"]
            stats["unchanged"] += result["unchanged"]
            stats["errors"] += result["errors"]
            stats["window_skips"] += result["window_skips"]
            if result["budget_stop"]:
                stats["budget_stop"] = True
                logger.warning(
                    "[dream] daily budget reached — tick stopped | "
                    "chat_id=%s | distilled_today=%d",
                    chat["chat_id"],
                    await self.db.count_dream_log(
                        _day_start_ts(now, self._tz_name), kind="distilled",
                        chat_id=int(chat["chat_id"])))
                break
        return stats

    # ── обработка чата ────────────────────────────────────────────

    async def _process_chat(self, chat_id: int, now: int, *,
                            manual: bool, fallback_active: bool = False) -> dict:
        """Один тик-батч чата: кандидаты → кластеры → дистилляции →
        watermark/аудит. Возвращает счётчики (fail-open: ошибка → WARNING,
        watermark не двигается)."""
        out = {"clusters": 0, "distilled": 0, "unchanged": 0, "errors": 0,
               "window_skips": 0, "budget_stop": False}
        # F7 (ADR-1018-7 D3): рубильник резолвится по КОНКРЕТНОМУ чату
        # (chat DB → global DB → env-дефолт). Авто-тик пропускает чат,
        # выключенный именно для него; ручной запуск гейт игнорирует
        # (решение владельца: manual обходит гейты/тайминги/бюджеты).
        enabled = bool(await self._key_for(chat_id, "enabled",
                                           settings.DREAM_ENABLED))
        if not manual and not enabled:
            logger.debug("[dream] chat skipped (dream off) | chat_id=%s",
                         chat_id)
            return out
        try:
            rows = await self._candidates(chat_id, now)
        except Exception:
            logger.warning("[dream] candidates failed — chat skipped | "
                           "chat_id=%s", chat_id, exc_info=True)
            return out
        if not rows:
            logger.info("[dream] no new facts | chat_id=%s", chat_id)
            return out
        protected = await self.db.get_chat_protected_texts(chat_id)
        if protected:
            gate = [str(t).strip().casefold()
                    for t in protected if str(t).strip()]
            kept = [r for r in rows
                    if not any(str(r["fact"]).strip().casefold() == p
                               or str(r["fact"]).strip().casefold() in p
                               for p in gate)]
            if not kept:
                # все кандидаты защищены — дистиллировать нечего; фиксируем
                # факты обработанными, чтобы чат не висел в кандидатах вечно
                logger.info(
                    "[dream] all candidates protected — chat finished | "
                    "chat_id=%s", chat_id)
                await self._finish_chat(chat_id, now, rows)
                return out
            rows = kept
        terms = await self._participant_terms(chat_id)
        clusters = greedy_cluster_facts(
            rows,
            overlap_tokens=int(await self._key_for(
                chat_id, "cluster_overlap_tokens",
                settings.DREAM_CLUSTER_OVERLAP_TOKENS) or 2),
            extra_terms=terms)
        repeat_min = int(await self._key_for(
            chat_id, "repeat_threshold",
            settings.DREAM_REPEAT_THRESHOLD) or 3)
        sum_min = int(await self._key_for(
            chat_id, "importance_sum_threshold",
            settings.DREAM_IMPORTANCE_SUM_THRESHOLD) or 12)
        # F3 (spec §3/§4): «0 убеждений за 3 дня» → временно 2/8 (fallback).
        if fallback_active:
            repeat_min = _FALLBACK_MIN_CLUSTER_SIZE
            sum_min = _FALLBACK_MIN_IMPORTANCE_SUM
        qualified = [
            cl for cl in clusters
            if len(cl) >= repeat_min
            and sum(int(r["importance"] or 0) for r in cl) >= sum_min
        ]
        qualified.sort(
            key=lambda cl: (sum(int(r["importance"] or 0) for r in cl),
                            cl[0]["id"]),
            reverse=True)
        top = qualified[: int(await self._key_for(
            chat_id, "max_clusters_per_run",
            settings.DREAM_MAX_CLUSTERS_PER_RUN) or 5)]
        run_at = now
        await self.db.log_dream_event(chat_id, run_at, kind="run",
                                      status="ok")
        # F3 (spec §5): пре-гейт-диагностика — «Max importance» = макс. Σ
        # importance по ВСЕМ кластерам до гейта (R17: только числа).
        max_importance = max(
            (sum(int(r["importance"] or 0) for r in cl) for cl in clusters),
            default=0)
        if not top:
            # WARNING — гарантированно видно в дефолтном фильтре «Логи»
            # (ERROR+WARNING, 10.13 F6). Спам ограничен `_finish_chat`:
            # факты помечаются обработанными → повтор только с новыми.
            logger.warning(
                "[Sleep] Chunks: %d, Clusters formed: %d, Max importance: %d "
                "-> Skipped (threshold %d)",
                len(rows), len(clusters), max_importance, sum_min)
            await self._finish_chat(chat_id, now, rows)   # все факты отобраны
            return out
        logger.info(
            "[Sleep] Chunks: %d, Clusters formed: %d, Max importance: %d "
            "-> Passed (threshold %d)",
            len(rows), len(clusters), max_importance, sum_min)
        # Раунд 10 (F-10 §6): тяжёлый гейт dream — kill-switch
        # (chat gates[dream] → глобальный флаг → False); skip-аудит —
        # memory_dream_log status='budget_skip' (прецедент). ФИКС R5:
        # гейт применяется и к ручному run_once (F-10 §6 БЕЗ carve-out) —
        # kill-switch останавливает и ручные запуски.
        try:
            from services.feature_gates import gates_enabled
            # F7: явный gates[dream] — kill-switch; иначе fallback — уже
            # разрешённый per-chat memory.dream_enabled (chat → global).
            gate_ok = await gates_enabled(chat_id, "dream", fallback=enabled)
            if not gate_ok and not manual:
                logger.warning(
                    "[dream] WARNING skip: gate dream | chat_id=%s",
                    chat_id)
                await self.db.log_dream_event(
                    chat_id, run_at, kind="skipped", status="budget_skip")
                return out
            if not gate_ok and manual:
                # F2 (ADR-1018-2 D2, spec §4.2, T-1715/T-1767): ручной запуск
                # обходит kill-switch БЕЗУСЛОВНО — базовая логика без
                # фича-флагов. Аудит — существующая memory_dream_log
                # (status='gate_override' — строка, не каталог; Δ=0, R17-safe).
                logger.warning(
                    "[dream] manual override: gate dream | chat_id=%s",
                    chat_id)
                await self.db.log_dream_event(
                    chat_id, run_at, kind="skipped", status="gate_override")
        except Exception:
            logger.warning("[dream] gate check failed — fail-open | "
                           "chat_id=%s", chat_id, exc_info=True)
        day_start = _day_start_ts(now, self._tz_name)
        # F7/S10.18-1: суточный расход считается ПО ЧАТУ (chat_id) — per-chat
        # override лимита не должен сравниваться с чужим/общим расходом.
        distilled_today = await self.db.count_dream_log(
            day_start, kind="distilled", chat_id=chat_id)
        tokens_today = await self.db.sum_dream_log_tokens(
            day_start, chat_id=chat_id)
        abnormal = None                     # 'error' | 'window' | 'budget'
        failed_cluster = None
        # F2 (ADR-1018-2 D2, spec §4.2, T-1715/T-1767): manual-запуск обходит
        # суточные бюджеты и near-limit БЕЗУСЛОВНО (решение «запускать/не
        # запускать»). Расход всё равно учитывается. Факт обхода — в аудите
        # (status='budget_override'; строка в существующей memory_dream_log).
        if manual:
            override_reason = await self._budget_reason_for(
                chat_id, distilled_today, tokens_today)
            if override_reason:
                logger.warning(
                    "[dream] manual override: budget %s | chat_id=%s",
                    override_reason, chat_id)
                await self.db.log_dream_event(
                    chat_id, run_at, kind="skipped",
                    status="budget_override")
        # D8/T-1771: суточные лимиты резолвятся ОДИН раз ДО цикла кластеров
        # (per-chat резолв стабилен на протяжении тика — незачем ходить в БД
        # на каждую итерацию). Расход (distilled_today/tokens_today) растёт
        # внутри цикла и сравнивается с уже разрешёнными лимитами.
        dist_max = await self._daily_limit_for(
            chat_id, "distillations_per_day",
            settings.DREAM_DISTILLATIONS_PER_DAY)
        tok_max = await self._daily_limit_for(
            chat_id, "tokens_per_day", settings.DREAM_TOKENS_PER_DAY)
        for cluster_id, cluster in enumerate(top, 1):
            if not manual and not await self._window_open_for(chat_id, now):
                # §3.4.2/D-5: вне окна — только отбор/кластеризация,
                # дистилляции window_skip (деньги не тратятся)
                await self.db.log_dream_event(
                    chat_id, run_at, kind="skipped",
                    cluster_id=cluster_id,
                    source_ids=json.dumps(
                        [int(r["id"]) for r in cluster], ensure_ascii=False),
                    tokens=0, status="window_skip")
                out["window_skips"] += 1
                abnormal = "window"
                break
            # суточные бюджеты (§3.4.4) — стоп тика заранее (per-chat);
            # manual их игнорирует (см. budget_override выше). Лимиты уже
            # разрешены ДО цикла (D8/T-1771) — здесь только сравнение.
            if not manual:
                reason = None
                if dist_max and distilled_today >= dist_max:
                    reason = "distillations"
                elif tok_max and tokens_today >= tok_max:
                    reason = "tokens"
                if reason:
                    logger.warning(
                        "[dream] budget %s reached — tick stopped | "
                        "chat_id=%s", reason, chat_id)
                    out["budget_stop"] = True
                    abnormal = "budget"
                    break
                # S10.18-25: `0` = «без лимита» (как в `_budget_reason_for`) —
                # near-limit при нулевом лимите не должен останавливать чат.
                near_dist = bool(dist_max) and (
                    dist_max - distilled_today) < _DREAM_NEAR_LIMIT_DIST
                near_tok = bool(tok_max) and (
                    tok_max - tokens_today) < _DREAM_NEAR_LIMIT_TOKENS
                if near_dist or near_tok:
                    logger.warning(
                        "[dream] near daily limit — tick finished early | "
                        "chat_id=%s", chat_id)
                    out["budget_stop"] = True
                    abnormal = "budget"
                    break
            outcome, tokens_used, unchanged = await self._distill_cluster(
                chat_id, run_at, cluster, cluster_id, manual=manual)
            out["clusters"] += 1
            tokens_today += tokens_used
            if outcome == "budget":
                out["budget_stop"] = True     # F-10: day-budget скип чата
                abnormal = "budget"
                break
            if outcome == "error":
                out["errors"] += 1
                abnormal = "error"
                failed_cluster = cluster
                break
            if unchanged:
                out["unchanged"] += 1
            elif outcome == "distilled":
                out["distilled"] += 1
                distilled_today += 1        # строка kind='distilled' записана
        if abnormal == "error" and failed_cluster:
            # watermark — НЕ мимо упавшего кластера (§3.4.2 «по успеху
            # батча»): фиксируем до первого факта упавшего кластера
            frozen = min(int(r["id"]) for r in failed_cluster) - 1
            await self.db.set_dream_state(
                chat_id, last_run_at=now,
                last_processed_fact_id=max(0, frozen))
        elif abnormal is None:
            await self._finish_chat(chat_id, now, rows)
        return out

    async def _finish_chat(self, chat_id: int, now: int, rows: list) -> None:
        """Успешный тик-батч чата: watermark = MAX(id) обработанного."""
        await self.db.set_dream_state(
            chat_id, last_run_at=now,
            last_processed_fact_id=int(rows[-1]["id"]))
        logger.info(
            "[dream] chat done | chat_id=%s | processed=%d | wm=%s",
            chat_id, len(rows), int(rows[-1]["id"]))

    async def _candidates(self, chat_id: int, now: int) -> list:
        """Новые факты чата (watermark-строка есть → id >; нет → окно)."""
        state = await self.db.get_dream_state(chat_id)
        if state:
            return await self.db.get_dream_candidates(
                chat_id, now, origins=_DREAM_SOURCE_ORIGINS,
                since_id=int(state["last_processed_fact_id"] or 0))
        return await self.db.get_dream_candidates(
            chat_id, now, origins=_DREAM_SOURCE_ORIGINS,
            since_ts=now - int(await self._key_for(
                chat_id, "initial_window_hours",
                settings.DREAM_INITIAL_WINDOW_HOURS) or 168) * 3600)

    async def _participant_terms(self, chat_id: int) -> list[str]:
        """Имена участников чата для кластеризации (§3.4.3): последние
        author_name (roster окна) + канон-имена через aliases (casefold)."""
        terms: set[str] = set()
        aliases = (getattr(self.memory, "aliases", None)
                   if self.memory is not None else None)
        try:
            since = _now_ts() - _DREAM_PARTICIPANT_WINDOW_DAYS * 86400
            rows = await self.db.get_active_participants(
                chat_id, since, _DREAM_PARTICIPANT_CAP)
            for row in rows:
                raw = str(row["author_name"] or "").strip()
                if not raw:
                    continue
                terms.add(raw.casefold())
                if aliases is not None:
                    try:
                        canon = aliases.resolve(int(row["user_id"]), raw, None)
                        if canon:
                            terms.add(str(canon).casefold())
                    except Exception:
                        continue
        except Exception:
            logger.warning("[dream] participant roster failed — words only | "
                           "chat_id=%s", chat_id, exc_info=True)
        return sorted(terms)

    # ── окно и бюджеты ────────────────────────────────────────────

    async def _window_open_for(self, chat_id: int, now_ts: int) -> bool:
        """Local-час в окне [start, end) дистилляций (D-5; дефолт 4–6).
        F7: границы окна резолвятся по чату."""
        start = int(await self._key_for(
            chat_id, "window_start_hour",
            settings.DREAM_WINDOW_START_HOUR) or 4)
        end = int(await self._key_for(
            chat_id, "window_end_hour",
            settings.DREAM_WINDOW_END_HOUR) or 6)
        hour = _local_hour(now_ts, self._tz_name)
        return start <= hour < end

    async def _daily_limit_for(self, chat_id: int, name: str, default) -> int:
        """F7: суточный лимит по чату (chat DB → global DB → env)."""
        return int(await self._key_for(chat_id, name, default) or 0)

    async def _budget_reason_for(self, chat_id: int, distilled_today: int,
                                 tokens_today: int) -> str | None:
        """Суточные бюджеты §3.4.4 (per-chat): дистилляции/токены. None —
        можно работать."""
        dist_max = await self._daily_limit_for(
            chat_id, "distillations_per_day",
            settings.DREAM_DISTILLATIONS_PER_DAY)
        tok_max = await self._daily_limit_for(
            chat_id, "tokens_per_day", settings.DREAM_TOKENS_PER_DAY)
        if dist_max and distilled_today >= dist_max:
            return "distillations"
        if tok_max and tokens_today >= tok_max:
            return "tokens"
        return None

    # ── дистилляция ───────────────────────────────────────────────

    async def _distill_cluster(self, chat_id: int, run_at: int,
                               cluster: list, cluster_id: int, *,
                               manual: bool = False) -> tuple:
        """Один LLM-вызов на кластер (§3.4.5): возвращает
        (outcome, tokens_used, unchanged):
        outcome 'distilled' | 'unchanged' | 'error'; кривой JSON — 1 retry;
        evidence вне списка — отброс; belief с <2 реальными source_ids НЕ
        пишется. НИКОГДА не бросает (fail-open, NFR-4)."""
        cluster_rows = [dict(r) for r in cluster]
        # F1/T-1421 (spec §6): evidence-нумерация user-блока — по позиции в
        # ХРОНОЛОГИЧЕСКОМ порядке (тот же порядок, что рендерит build_dream_user).
        source_ids = [int(r["id"]) for r in order_dream_rows(
            cluster_rows, max_facts=_DREAM_MAX_USER_FACTS)]
        # F2/T-1428 (spec §4.3, Сон-Реаниматор): ДО LLM-синтеза сверяем
        # кластер свежих фактов с архивом чата; сильное совпадение → синтез
        # отменяется (экономия), старый belief воскрешается с новой датой.
        if hot.get("flags.belief_decay_enabled",
                   settings.BELIEF_DECAY_ENABLED):
            try:
                reanimated = await self._try_reanimate(
                    chat_id, run_at, cluster_rows, cluster_id, source_ids)
            except Exception:
                logger.warning("[dream] reanimator failed — synthesis goes on | "
                               "chat_id=%s", chat_id, exc_info=True)
                reanimated = False
            if reanimated:
                return "unchanged", 0, True
        user_text = build_dream_user(cluster_rows,
                                     max_facts=_DREAM_MAX_USER_FACTS)
        prompt_text = DREAM_DISTILL_PROMPT + "\n" + user_text
        messages = [{"role": "system", "content": DREAM_DISTILL_PROMPT},
                    {"role": "user", "content": user_text}]
        # Раунд 10 (F-10 §5/§6): consume до LLM-вызова дистилляции
        # (global + chat:<id>); False → memory_dream_log status='budget_skip'.
        # F2: при manual=True гейт не отклоняет, но расход учитывается.
        if not await _dream_budget_ok(chat_id, user_text, manual=manual):
            await self.db.log_dream_event(
                chat_id, run_at, kind="skipped", cluster_id=cluster_id,
                source_ids=json.dumps(source_ids, ensure_ascii=False),
                tokens=0, status="budget_skip")
            logger.warning(
                "[dream] WARNING skip: budget dream | chat_id=%s "
                "| cluster=%d", chat_id, cluster_id)
            return "budget", 0, False
        raw, tokens = await self._llm_once(messages, prompt_text)
        if raw is None:
            await self.db.log_dream_event(
                chat_id, run_at, kind="error", cluster_id=cluster_id,
                source_ids=json.dumps(source_ids, ensure_ascii=False),
                tokens=tokens, status="error")
            return "error", tokens, False
        try:
            beliefs = parse_distill_answer(raw, source_ids)
        except ValueError:
            # 1 retry (кривой JSON/исключение — §3.4.5)
            raw2, tokens2 = await self._llm_once(messages, prompt_text)
            tokens = tokens + tokens2
            if raw2 is None:
                await self.db.log_dream_event(
                    chat_id, run_at, kind="error", cluster_id=cluster_id,
                    source_ids=json.dumps(source_ids, ensure_ascii=False),
                    tokens=tokens, status="error")
                return "error", tokens, False
            try:
                beliefs = parse_distill_answer(raw2, source_ids)
            except ValueError:
                await self.db.log_dream_event(
                    chat_id, run_at, kind="error", cluster_id=cluster_id,
                    source_ids=json.dumps(source_ids, ensure_ascii=False),
                    tokens=tokens, status="error")
                logger.warning(
                    "[dream] distill parse failed twice — cluster error | "
                    "chat_id=%s cluster=%d", chat_id, cluster_id)
                return "error", tokens, False
        if not beliefs:
            await self.db.log_dream_event(
                chat_id, run_at, kind="skipped", cluster_id=cluster_id,
                source_ids=json.dumps(source_ids, ensure_ascii=False),
                tokens=tokens, status="unchanged")
            return "unchanged", tokens, True
        by_id = {int(r["id"]): r for r in cluster}
        written = []
        for belief in beliefs[:_DREAM_MAX_BELIEFS]:
            sources = [by_id[fid] for fid in belief["evidence"]
                       if fid in by_id]
            if not sources:
                continue
            fact_id = await self._write_belief(chat_id, belief, sources,
                                               cluster_id, run_at)
            if fact_id:
                written.append(fact_id)
        if not written:
            # beliefs пришли, но ни одно не прошло гейт реальных источников
            await self.db.log_dream_event(
                chat_id, run_at, kind="skipped", cluster_id=cluster_id,
                source_ids=json.dumps(source_ids, ensure_ascii=False),
                tokens=tokens, status="unchanged")
            return "unchanged", tokens, True
        await self.db.log_dream_event(
            chat_id, run_at, kind="distilled", cluster_id=cluster_id,
            source_ids=json.dumps(source_ids, ensure_ascii=False),
            belief_id=written[0],
            tokens=tokens, status="ok")
        return "distilled", tokens, False

    async def _worker_llm(self, role: str, messages: list,
                          temperature: float | None = None):
        """F3/T-1439 (spec §5): выделенная LLM роли воркера через
        `generate_worker` с фоллбэком на `generate` (моки/старые клиенты
        без роутера). Пустые ключи/ошибка dedicated → фоллбэк на основную
        модель выполняется самим llm_client (нулевой регресс)."""
        worker_fn = getattr(self.llm, "generate_worker", None)
        if callable(worker_fn):
            return await worker_fn(role, messages, temperature=temperature)
        return await self.llm.generate(messages, temperature=temperature)

    async def _llm_once(self, messages: list, prompt_text: str):
        """Один облачный LLM-вызов (NFR-1: только LLMClient-путь бота).
        F3/T-1439: синтез «сна» — выделенная LLM роли background (пустые
        ключи → основная). Возвращает (content | None, оценка токенов
        max(1, len/4))."""
        try:
            raw = await self._worker_llm("background", messages,
                                         temperature=0.3)
        except Exception as exc:
            logger.warning("[dream] LLM call failed — cluster error | "
                           "error=%s", exc)
            return None, _estimate_tokens(prompt_text)
        content = str(raw or "")
        return content, _estimate_tokens(prompt_text, content)

    async def _write_belief(self, chat_id: int, belief: dict,
                            sources: list, cluster_id: int,
                            run_at: int) -> int | None:
        """Запись одного belief (§3.4.6): origin='derived_belief',
        kind='belief', weight=0.6, importance=min(10, Σ источников),
        source_ids JSON, belief_meta JSON, expires_at None; supersede по
        якорному токену (D-6); эмбеддинг боевым путём (fail-open)."""
        text = " ".join(str(belief["text"] or "").split())
        if not text:
            return None
        old_id = await self._find_supersede_old(chat_id, text)
        importance = min(10, sum(int(r["importance"] or 0)
                                 for r in sources))
        # F2/T-1425 (spec §2): base_weight — база для декай-формулы (не
        # инкремент), last_reinforced_fact_id — стартовая точка подкрепления
        # (факты-источники уже учтены), decay_months — счётчик просрочки.
        meta = json.dumps({
            "confidence": 1.0,
            "sources_count": len(sources),
            "distilled_at": run_at,
            "cluster_id": cluster_id,
            "base_weight": _DREAM_BELIEF_WEIGHT,
            "last_reinforced_fact_id": max(
                (int(r["id"]) for r in sources), default=0),
            "decay_months": 0,
        }, ensure_ascii=False)
        fact_id = await self.db.insert_graph_fact(
            chat_id, text, "derived_belief", None,
            weight=_DREAM_BELIEF_WEIGHT, importance=importance,
            source_ids=json.dumps([int(r["id"]) for r in sources],
                                  ensure_ascii=False),
            kind="belief", belief_meta=meta)
        if old_id is not None and fact_id:
            await self.db.mark_belief_superseded(old_id, fact_id)
        if fact_id and self.memory is not None \
                and getattr(self.memory, "_vec_available", False):
            try:
                await self.memory._save_graph_fact_embedding(
                    fact_id, chat_id, text, "derived_belief", None)
            except Exception:
                logger.warning(
                    "[dream] belief embed failed — fact lives text+FTS | "
                    "belief_id=%d", fact_id, exc_info=True)
        logger.info(
            "[dream] belief distilled | chat_id=%s | belief_id=%s | "
            "importance=%d | sources=%d | supersedes_old=%s",
            chat_id, fact_id, importance, len(sources), old_id)
        return fact_id

    # ── F2 (cognition-belief-decay, spec §4.1): охлаждение убеждений ────────

    @staticmethod
    def _belief_meta(row) -> dict:
        """belief_meta строки belief → dict (битое/пустое → {}).

        S10.13-13: делегирует единому `parse_belief_meta` (database) — формат
        разбирается идентично read-path summary_memory."""
        return parse_belief_meta(row_get(row, "belief_meta"))

    async def _maybe_decay(self, now: int) -> None:
        """Интервальный гейт (раз в BELIEF_DECAY_INTERVAL_DAYS) + маркер
        прогона memory_dream_log(kind='decay_run', chat_id=0 — глобальное
        событие, нулевой DDL). Идемпотентность обеспечивает цель-вес от
        базы, а не инкремент (spec §4.1)."""
        if not hot.get("flags.belief_decay_enabled",
                       settings.BELIEF_DECAY_ENABLED):
            return
        last = await self.db.last_decay_run()
        if last is not None and (
                now - int(last)) < BELIEF_DECAY_INTERVAL_DAYS * 86400:
            return
        stats = await self._decay_step(now)
        await self.db.log_dream_event(0, now, kind="decay_run",
                                      tokens=0, status="ok")
        logger.info(
            "[dream] belief decay run | checked=%d | decayed=%d | "
            "archived=%d | reinforced=%d",
            stats["checked"], stats["decayed"], stats["archived"],
            stats["reinforced"])

    async def _decay_step(self, now: int) -> dict:
        """Декай-шаг (§4.1): для confirmed beliefs без подкрепления > порога
        — weight = base − step × просроченных месяцев; target < threshold →
        archived_belief (+archived_at/decay_months). Возвращает счётчики."""
        inact = _hot_number("limits.belief_inactivity_days",
                            settings.BELIEF_INACTIVITY_DAYS, int)
        step = _hot_number("limits.belief_decay_per_month",
                           settings.BELIEF_DECAY_PER_MONTH, float)
        arch = _hot_number("limits.belief_archive_threshold",
                           settings.BELIEF_ARCHIVE_THRESHOLD, float)
        stats = {"checked": 0, "decayed": 0, "archived": 0, "reinforced": 0}
        beliefs = await self.db.list_confirmed_beliefs()
        for belief in beliefs:
            stats["checked"] += 1
            try:
                meta = self._belief_meta(belief)
                base = float(meta.get("base_weight") or _DREAM_BELIEF_WEIGHT)
                last_id = int(meta.get("last_reinforced_fact_id") or 0)
                anchor = next(iter(significant_tokens(belief["fact"])), None)
                if await self._reinforce(belief, anchor, last_id, now, base):
                    stats["reinforced"] += 1
                    continue
                last = (belief.get("last_confirmed_at")
                        or belief.get("created_at") or now)
                age_days = (now - int(last)) / 86400.0
                if age_days <= inact:
                    continue
                # 30-дн. интервалы (spec §4.1/F2-Q5, тест-план §9.1): первый
                # просроченный день = первый месяц простоя (ceil), иначе
                # int()-флор даёт 0 месяцев на 181-й день.
                months_overdue = int(
                    math.ceil((age_days - inact) / 30.0))
                target = max(0.0, base - step * months_overdue)
                if target >= arch:
                    if abs(target - float(belief.get("weight") or 0.0)) > 1e-9:
                        await self.db.set_belief_status(
                            int(belief["id"]), "confirmed", weight=target)
                        stats["decayed"] += 1
                else:
                    await self.db.set_belief_status(
                        int(belief["id"]), "archived_belief",
                        weight=max(target, 0.0),
                        belief_meta_patch={
                            "archived_at": now,
                            "decay_months": months_overdue})
                    stats["decayed"] += 1
                    stats["archived"] += 1
                    logger.info(
                        "[dream] belief archived | belief_id=%s | chat=%s | "
                        "weight=%.3f | months=%d",
                        belief["id"], belief.get("chat_id"), target,
                        months_overdue)
            except Exception:
                logger.warning(
                    "[dream] belief decay item failed — skipped | "
                    "belief_id=%s", belief.get("id"), exc_info=True)
        return stats

    async def _reinforce(self, belief, anchor, last_id: int, now: int,
                         base: float) -> bool:
        """Подкрепление (§2/F2-Q2): новый confirmed-факт чата (kind='fact',
        id > last_reinforced_fact_id) с якорным токеном belief → сброс
        last_confirmed_at=now, weight=base, last_reinforced_fact_id=max id."""
        if not anchor:
            return False
        try:
            new_facts = await self.db.list_new_confirmed_facts(
                int(belief["chat_id"]), int(last_id), now_ts=now)
        except Exception:
            logger.warning("[dream] reinforce scan failed — belief kept | "
                           "belief_id=%s", belief.get("id"), exc_info=True)
            return False
        hits = [int(r["id"]) for r in new_facts
                if anchor in str(r["fact"] or "").casefold()]
        if not hits:
            return False
        await self.db.reinforce_belief(
            int(belief["id"]), base, now, max(hits))
        logger.info(
            "[dream] belief reinforced | belief_id=%s | chat=%s | new_facts=%d",
            belief["id"], belief.get("chat_id"), len(hits))
        return True

    # ── F2 (cognition-belief-decay, spec §4.3): Сон-Реаниматор ──────────────

    async def _try_reanimate(self, chat_id: int, run_at: int, cluster_rows,
                             cluster_id: int, source_ids: list) -> bool:
        """Перед синтезом: векторная сверка кластера свежих фактов с архивом
        чата. cosine ≥ belief_resonance_threshold → синтез ОТМЕНЁН, старый
        belief воскрешён с обновлённой датой (текст стабилен, новый id НЕ
        создаётся); аудит kind='resurrect'/status='resurrected' (S10.13-4 —
        единый счётчик воскрешений). Fail-open:
        нет vec/архива/ошибка → False (синтез идёт как раньше)."""
        if self.memory is None or not getattr(
                self.memory, "_vec_available", False):
            return False
        archived = await self.db.list_archived_beliefs(
            chat_id=chat_id, limit=_REANIMATE_ARCHIVE_CAP)
        if not archived:
            return False
        cluster_text = " ".join(
            str(r["fact"]) for r in cluster_rows if str(r.get("fact") or ""))
        if not cluster_text.strip():
            return False
        try:
            vectors = await self.memory._embed(
                [cluster_text] + [str(a["fact"]) for a in archived])
        except Exception:
            logger.warning("[dream] reanimator embed failed — synthesis goes "
                           "on | chat_id=%s", chat_id, exc_info=True)
            return False
        if not vectors or len(vectors) != len(archived) + 1:
            return False
        from services.summary_memory import _cosine
        threshold = _hot_number("limits.belief_resonance_threshold",
                                settings.BELIEF_RESONANCE_THRESHOLD, float)
        best = None
        for idx, belief in enumerate(archived, start=1):
            cosine = _cosine(vectors[0], vectors[idx])
            if cosine >= threshold and (best is None or cosine > best[1]):
                best = (belief, cosine)
        if best is None:
            return False
        target = best[0]
        base = float(self._belief_meta(target).get("base_weight")
                     or _DREAM_BELIEF_WEIGHT)
        await self.db.resurrect_belief(int(target["id"]), base, run_at)
        # S10.13-4: тот же kind='resurrect', что и у векторного резонанса
        # (summary_memory._resurrect_resonant) — иначе реаниматор невидим в
        # resurrections_total/health/Timeline.
        await self.db.log_dream_event(
            chat_id, run_at, kind="resurrect", cluster_id=cluster_id,
            source_ids=json.dumps([int(i) for i in source_ids],
                                  ensure_ascii=False),
            belief_id=int(target["id"]), tokens=0, status="resurrected")
        logger.info(
            "[dream] reanimator: synthesis cancelled, belief resurrected | "
            "belief_id=%s | chat=%s | cosine=%.3f", target["id"], chat_id,
            best[1])
        return True

    async def _find_supersede_old(self, chat_id: int, text: str) -> int | None:
        """D-6: старый belief того же чата, в тексте которого есть «якорный
        токен» (первый значимый токен нового текста) — кандидат на замену."""
        anchor = next(iter(significant_tokens(text)), None)
        if not anchor:
            return None
        try:
            for row in await self.db.list_beliefs_for_supersede(chat_id):
                if anchor in str(row["fact"] or "").casefold():
                    return int(row["id"])
        except Exception:
            logger.warning("[dream] supersede scan failed — skipped | "
                           "chat_id=%s", chat_id, exc_info=True)
        return None

    # ── F3 (cognition-deep-sleep, spec §3/§4): «глубокий сон» ──────────────
    # «Поиск по якорям»: свежие beliefs + выжимка 12ч → векторный RAG по всей
    # базе → «Мост времени» (LLM history) → парадигмы (kind='belief',
    # belief_meta.type='paradigm', weight=0.55) без DDL.

    async def _maybe_deep_after_sleep(self, stats: dict | None, *,
                                      manual: bool = False,
                                      only_chat: int | None = None) -> dict:
        """Хук after_sleep (spec §3): запускает глубокий сон по чатам только
        что завершившегося обычного сна.

        F7 (ADR-1018-7 D3): при авто-режиме флаг `flags.deep_sleep_enabled` и
        триггер `memory.deep_sleep_trigger` резолвятся ПО КАЖДОМУ чату из
        `self._last_chat_ids` (per-chat DB → global DB → env); прогоняются
        только чаты с флагом ON и триггером 'after_sleep'.

        R10.18-10 (ADR-1018-2 D2): при `manual=True` (ручное «уснуть сейчас»)
        флаг и триггер НЕ гейтят каскад — явное действие оператора обходит
        экономические/тайминговые гейты. `_run_deep_once(manual=True)` также
        пропускает cooldown/суточный лимит.

        R10.18-5: manual-каскад идёт прежде всего по ЦЕЛЕВОМУ чату
        (`only_chat`), а не по всем чатам прогона; если цели нет — не более
        `_MANUAL_DEEP_CASCADE_MAX` чатов (а не до `max_chats_per_run` LLM-
        прогонов).

        F2 (T-1716): возвращает аддитивную статистику каскада
        (deep/traits) — `run_once` кладёт её в `stats["cascade"]` (контракт
        202 не ломается)."""
        empty = {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 0,
                 "traits": 0}
        if not stats:
            return dict(empty)
        if not (int(stats.get("distilled") or 0) > 0
                or int(stats.get("chats") or 0) > 0):
            return dict(empty)
        if only_chat is not None:
            # Явная цель (кнопка «Сон сейчас» для чата) — только этот чат.
            chats = [int(only_chat)]
        else:
            chats = list(self._last_chat_ids or [])
        if not chats:
            return dict(empty)
        eligible: list[int] = []
        for cid in chats:
            if not manual:
                enabled = bool(await resolve_setting_cached(
                    "flags.deep_sleep_enabled", chat_id=cid,
                    default=settings.DEEP_SLEEP_ENABLED))
                if not enabled:
                    continue
                trigger = str(await resolve_setting_cached(
                    "memory.deep_sleep_trigger", chat_id=cid,
                    default=settings.DEEP_SLEEP_TRIGGER) or "after_sleep")
                if trigger != "after_sleep":
                    continue
            eligible.append(int(cid))
        if not eligible:
            return dict(empty)
        if manual and only_chat is None:
            # R10.18-5: без явной цели — жёсткий кап ручного каскада.
            eligible = eligible[:_MANUAL_DEEP_CASCADE_MAX]
        return await self._run_deep_all(eligible,
                                        since_ts=self._last_run_started,
                                        manual=manual)

    async def _deep_tick(self) -> None:
        """Scheduler-джоб deep_sleep_tick: режим trigger='fixed' — запуск в
        свой local-час (memory.deep_sleep_hour) с cooldown/лимитом суток.

        F7 (ADR-1018-7 D4): джоб зарегистрирован всегда; решение — здесь.
        R10.18-2: триггер И час резолвятся ПО КАЖДОМУ чату-кандидату (chat DB
        → global DB → env) — per-chat `trigger='fixed'` исполним при
        глобальном `'after_sleep'` (и наоборот, per-chat `'after_sleep'` не
        получает deep в чужой фиксированный час).
        S10.18-21: предгейт R10.18-17 (`_deep_fixed_possible`) УДАЛЁН — он
        опирался на прогретость in-memory `ChatParamsCache` и при глобальном
        `after_sleep` + незагруженном чате с per-chat `fixed` молча хоронил
        фиксированный прогон (частичный откат R10.18-2). Цена — 1 дешёвый
        SQL-запрос кандидатов в час, что ниже риска потерять прогон."""
        if self._deep_lock.locked():
            return
        now = _now_ts()
        try:
            candidates = await self._deep_candidate_chat_ids(now)
        except Exception:
            logger.warning("[deep_sleep] candidate chats failed — fail-open",
                           exc_info=True)
            return
        hour = _local_hour(now, self._deep_tz_name)
        eligible: list[int] = []
        for cid in candidates:
            try:
                trigger = str(await resolve_setting_cached(
                    "memory.deep_sleep_trigger", chat_id=cid,
                    default=settings.DEEP_SLEEP_TRIGGER) or "after_sleep")
                if trigger != "fixed":
                    continue
                target = int(await resolve_setting_cached(
                    "memory.deep_sleep_hour", chat_id=cid,
                    default=settings.DEEP_SLEEP_HOUR) or 7)
            except Exception:
                continue
            if hour == target:
                eligible.append(int(cid))
        if not eligible:
            return
        try:
            await self._run_deep_all(eligible, manual=False)
        except Exception:
            logger.warning("[dream] deep tick failed — fail-open",
                           exc_info=True)

    async def _deep_candidate_chat_ids(self, now: int) -> list[int]:
        """R10.18-2: чаты-кандидаты глубокого сна (свежая активность за
        `_DEEP_SLEEP_LOOKBACK_HOURS`); общий путь для `_deep_tick` и
        `_run_deep_all(None)`."""
        candidates = await self.db.get_dream_candidate_chats(
            now, origins=_DREAM_SOURCE_ORIGINS,
            initial_window_hours=_DEEP_SLEEP_LOOKBACK_HOURS,
            min_new_facts=1,
            max_chats=int(self._key(
                "max_chats_per_run",
                settings.DREAM_MAX_CHATS_PER_RUN) or 10))
        return [int(c["chat_id"]) for c in candidates]

    async def _run_deep_all(self, chat_ids=None, *, since_ts: int | None = None,
                            manual: bool = False) -> dict:
        """Прогон глубокого сна по набору чатов (None → кандидаты 12ч).
        Анти-наложение — _deep_lock/max_instances=1; авто-режим останавливается
        после первого успешного прогона (лимиты стоимости spec §4)."""
        if self._deep_lock.locked():
            # D7/T-1771: единая форма stats (в т.ч. ключ `traits`).
            return {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 1,
                    "traits": 0}
        async with self._deep_lock:
            # S10.18-29: ручной deep-прогон (в т.ч. каскад из
            # `run_once(deep=False)`) выставляет маркер `manual_deep_active`
            # на всё время прогона (`_manual_deep_run`) + TTL `…_until` после
            # него — бейдж глубокого сна не «теряет» фазу.
            if manual:
                self._manual_deep_run = True
                self._manual_deep_until = _now_ts() + _MANUAL_RUN_MARKER_SECONDS
            try:
                if chat_ids is None:
                    now = _now_ts()
                    try:
                        chat_ids = await self._deep_candidate_chat_ids(now)
                    except Exception:
                        logger.warning("[deep_sleep] candidate chats failed — "
                                       "fail-open", exc_info=True)
                        chat_ids = []
                stats = {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 0,
                         "traits": 0}
                for cid in chat_ids:
                    try:
                        out = await self._run_deep_once(
                            int(cid), since_ts=since_ts, manual=manual)
                    except Exception:
                        logger.warning("[deep_sleep] deep run failed — "
                                       "fail-open | chat_id=%s", cid,
                                       exc_info=True)
                        out = _deep_result("error")
                    stats["chats"] += 1
                    stats["paradigms"] += int(out.get("paradigms") or 0)
                    stats["traits"] += int(out.get("traits") or 0)
                    if out.get("status") == "ok":
                        stats["ran"] += 1
                        if not manual:
                            break      # авто: 1 успешный прогон за раз
                    else:
                        stats["skipped"] += 1
                return stats
            finally:
                if manual:
                    self._manual_deep_run = False
                    self._manual_deep_until = (
                        _now_ts() + _MANUAL_RUN_MARKER_SECONDS)

    async def _run_deep_once(self, chat_id: int, *, since_ts: int | None = None,
                             manual: bool = False) -> dict:
        """Один прогон «Поиска по якорям» + «Моста времени» для чата (spec
        §4). Никогда не бросает (fail-open): ошибка RAG/LLM/записи → skip."""
        now = _now_ts()
        if not manual:
            deep_on = bool(await resolve_setting_cached(
                "flags.deep_sleep_enabled", chat_id=chat_id,
                default=settings.DEEP_SLEEP_ENABLED))
            if not deep_on:
                return _deep_result("disabled")
        if not manual:
            try:
                # S10.13-2: суточный лимит и cooldown учитывают и неуспешные
                # попытки (deep_skip), иначе no_anchors/unchanged/duplicate/
                # error повторялись бы каждый тик/after_sleep.
                if await self.db.count_deep_attempts(
                        _day_start_ts(now, self._deep_tz_name)) >= 1:
                    return _deep_result("daily_limit")
                last = await self.db.last_deep_attempt(chat_id)
            except Exception:
                logger.warning("[deep_sleep] cooldown read failed — skip | "
                               "chat_id=%s", chat_id, exc_info=True)
                return _deep_result("error")
            cooldown = _hot_number(
                "memory.deep_sleep_min_interval_hours",
                _DEEP_SLEEP_MIN_INTERVAL_HOURS, int)
            if last is not None and (now - int(last)) < cooldown * 3600:
                return _deep_result("cooldown")
        if self.memory is None:
            return _deep_result("no_memory")
        try:
            packet = await self._build_deep_packet(chat_id, now, since_ts)
        except Exception:
            logger.warning("[deep_sleep] packet build failed — skip | "
                           "chat_id=%s", chat_id, exc_info=True)
            return _deep_result("error")
        if not packet["beliefs"] and not packet["recent"]:
            return _deep_result("no_context")
        query = " ".join(
            [str(b.get("fact") or "") for b in packet["beliefs"][:20]]
            + [str(r.get("fact") or "") for r in packet["recent"]])
        try:
            anchors = await self.memory.get_rag_facts(chat_id, query)
        except Exception:
            logger.warning("[deep_sleep] RAG failed — skip | chat_id=%s",
                           chat_id, exc_info=True)
            return _deep_result("error")
        top_k = _hot_number("limits.deep_sleep_top_k",
                            settings.DEEP_SLEEP_TOP_K, int)
        anchors = list(anchors or [])[: max(1, top_k)]
        historical = [a for a in anchors if _anchor_is_old(a, now)]
        if len(historical) < _DEEP_SLEEP_MIN_HISTORICAL:
            await self._log_deep_skip(chat_id, now, "no_anchors", 0)
            return _deep_result("no_anchors")
        user_text = build_bridge_user(packet, historical)
        messages = [
            {"role": "system", "content": DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        if not await self._deep_budget_ok(
                chat_id, DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT + user_text,
                manual=manual):
            await self._log_deep_skip(chat_id, now, "budget_skip", 0)
            return _deep_result("budget")
        raw, tokens = await self._deep_llm_once(messages, user_text)
        if raw is None:
            await self._log_deep_skip(chat_id, now, "error", tokens)
            return _deep_result("error")
        try:
            paradigms = parse_bridge_answer(raw,
                                            anchor_count=len(historical),
                                            min_anchors=2)
        except ValueError:
            # 1 retry на кривой JSON (не более 1 — spec §4 «без ретраев»)
            # S10.13-2: перед retry перепроверяем токен-кап с учётом уже
            # потраченных токенов первой попытки.
            if not await self._deep_budget_ok(
                    chat_id, user_text, extra_tokens=tokens, manual=manual):
                await self._log_deep_skip(chat_id, now, "budget_skip", tokens)
                return _deep_result("budget")
            raw2, tokens2 = await self._deep_llm_once(messages, user_text)
            tokens += tokens2
            if raw2 is None:
                await self._log_deep_skip(chat_id, now, "error", tokens)
                return _deep_result("error")
            try:
                paradigms = parse_bridge_answer(
                    raw2, anchor_count=len(historical), min_anchors=2)
            except ValueError:
                await self._log_deep_skip(chat_id, now, "error", tokens)
                return _deep_result("error")
        if not paradigms:
            await self._log_deep_skip(chat_id, now, "unchanged", tokens)
            return _deep_result("unchanged")
        try:
            existing = await self._paradigm_dedup_keys(chat_id)
        except Exception:
            existing = set()
        max_paradigms = _hot_number(
            "limits.deep_sleep_max_paradigms_per_run",
            settings.DEEP_SLEEP_MAX_PARADIGMS, int)
        written = 0
        for item in paradigms[: max(1, max_paradigms)]:
            anchor_items = [historical[i - 1] for i in item["anchors"]
                            if 1 <= i <= len(historical)]
            key = _deep_dedup_key(item["text"], anchor_items)
            if key in existing:
                continue
            try:
                fact_id = await self._write_paradigm(
                    chat_id, item["text"], packet, anchor_items,
                    packet["source_ids"], key, now)
            except Exception:
                logger.warning("[deep_sleep] paradigm write failed | "
                               "chat_id=%s", chat_id, exc_info=True)
                fact_id = None
            if fact_id:
                written += 1
                existing.add(key)
        if written:
            try:
                await self.db.log_dream_event(chat_id, now, kind="deep_run",
                                              tokens=tokens, status="ok")
            except Exception:
                logger.warning("[deep_sleep] log failed | chat_id=%s",
                               chat_id, exc_info=True)
            logger.info(
                "[deep_sleep] paradigms written | chat_id=%s | count=%d | "
                "anchors=%d | tokens=%d", chat_id, written, len(historical),
                tokens)
        else:
            await self._log_deep_skip(chat_id, now, "duplicate", tokens)
        # ── F2 persona-storage-core (spec §3.4): после прогона парадигм
        # «Глубокий сон» анализирует эволюцию характера бота и пишет
        # dynamic_traits (persona_traits). Гейт — flags.persona_enabled
        # (deep_sleep уже проверен в начале). Fail-open: ошибка не влияет.
        # H3-фикс: гейт резолвится per-chat (override → global → default).
        from services.chat_params import get_chat_param as _persona_gate
        persona_enabled = await _persona_gate(
            chat_id, "flags.persona_enabled",
            hot.get("flags.persona_enabled", settings.PERSONA_ENABLED))
        traits_written = 0
        if persona_enabled:
            try:
                traits_stats = await self._run_persona_traits_once(
                    chat_id, now=now, manual=manual)
                traits_written = int(traits_stats.get("traits") or 0)
            except Exception:
                logger.warning(
                    "[persona_traits] run failed — fail-open | chat_id=%s",
                    chat_id, exc_info=True)
        else:
            # F2 (ADR-1018-2 D3, spec §4.2a/§4.4, T-1770): persona — контентный
            # гейт владельца, запись traits НЕ обходим даже при manual. Но
            # каскад не «глушим молча»: явная причина в логах (R17-safe —
            # только chat_id, без текстов).
            logger.warning(
                "[persona_traits] skip | reason=persona_disabled | "
                "chat_id=%s", chat_id)
        return {"status": "ok" if written else "duplicate",
                "paradigms": written, "tokens": tokens,
                "traits": traits_written}

    async def _build_deep_packet(self, chat_id: int, now: int,
                                 since_ts: int | None) -> dict:
        """Пакет «Поиска по якорям» (spec §2): свежие beliefs (обычного сна)
        + выжимка 12ч (свежие graph_facts по importance, до 6000 символов).
        source_ids — id опор (beliefs + фактов) для `source_ids` парадигмы."""
        recent_since = now - _DEEP_SLEEP_LOOKBACK_HOURS * 3600
        facts = await self.db.get_dream_candidates(
            chat_id, now, origins=_DREAM_SOURCE_ORIGINS,
            since_ts=recent_since, limit=200)
        try:
            rows = await self.db.list_recent_beliefs(
                chat_id=chat_id, limit=100, status="confirmed",
                belief_type="belief")
        except Exception:
            rows = []
        beliefs_since = int(since_ts) if since_ts else recent_since
        fresh = [b for b in rows
                 if int(b.get("created_at") or 0) >= beliefs_since]
        recent: list[dict] = []
        used = 0
        for row in sorted(facts,
                          key=lambda r: int(r.get("importance") or 0),
                          reverse=True):
            text = str(row.get("fact") or "").strip()
            if not text:
                continue
            if used + len(text) > _DEEP_SLEEP_SUMMARY_MAX_CHARS:
                break
            recent.append({"fact": text,
                           "importance": int(row.get("importance") or 0)})
            used += len(text) + 1
        for row in fresh:
            text = str(row.get("fact") or "").strip()
            if not text:
                continue
            if used + len(text) > _DEEP_SLEEP_SUMMARY_MAX_CHARS:
                break
            recent.append({"fact": text,
                           "importance": int(row.get("importance") or 0)})
            used += len(text) + 1
        source_ids = ([int(b["id"]) for b in fresh]
                      + [int(r["id"]) for r in facts])
        return {"beliefs": fresh, "recent": recent,
                "source_ids": source_ids[:50]}

    async def _deep_llm_once(self, messages: list, prompt_text: str):
        """Один вызов выделенной LLM роли history через роутер воркеров
        (F3/T-1439); возвращает (content | None, оценка токенов)."""
        try:
            raw = await self._worker_llm("history", messages,
                                         temperature=0.3)
        except Exception as exc:
            logger.warning("[deep_sleep] LLM call failed | error=%s", exc)
            return None, _estimate_tokens(prompt_text)
        content = str(raw or "")
        return content, _estimate_tokens(prompt_text, content)

    async def _deep_budget_ok(self, chat_id: int, prompt_text: str, *,
                              extra_tokens: int = 0,
                              manual: bool = False) -> bool:
        """Суточный токен-кап глубокого сна (limits.deep_sleep_tokens_per_day,
        40000) + worker_budget.consume (worker='deep_sleep'); fail-open.

        S10.13-2: кап считает токены и успешных (`deep_run`), и скип-прогонов
        (`deep_skip`) — иначе error/unchanged/duplicate обходили лимит.
        R10.14-2: сюда же входят токены traits (`deep_traits`) — LLM-вызов
        эволюции характера больше не идёт вне суточного капа.
        `extra_tokens` — уже потраченные токены текущей попытки (retry).

        F2/D1 (ADR-1018-2 D2, T-1771): `manual=True` — ручной каскад «уснуть
        сейчас» НЕ отклоняется суточным капом и деградацией (безусловный
        приоритет); расход consume всё равно пишется для учёта, но verdict
        не применяется. Без кап-обхода Личность была недостижима при
        исчерпанном `deep_sleep_tokens_per_day`."""
        from services import worker_budget
        cap = _hot_number("limits.deep_sleep_tokens_per_day",
                          settings.DEEP_SLEEP_TOKENS_PER_DAY, int)
        est = worker_budget.estimate_tokens(prompt_text)
        day_start = _day_start_ts(_now_ts(), self._deep_tz_name)
        try:
            used = await self.db.sum_dream_log_tokens(day_start, kind="deep_run")
            used += await self.db.sum_dream_log_tokens(day_start,
                                                       kind="deep_skip")
            used += await self.db.sum_dream_log_tokens(day_start,
                                                       kind="deep_traits")
        except Exception:
            used = 0
        if cap and used + int(extra_tokens or 0) + est > cap:
            if not manual:
                logger.warning(
                    "[deep_sleep] daily token cap reached — skip | chat_id=%s "
                    "| used=%d | cap=%d", chat_id, used, cap)
                return False
            logger.warning(
                "[deep_sleep] manual override: daily token cap | chat_id=%s | "
                "used=%d | cap=%d", chat_id, used, cap)
        try:
            if not await worker_budget.global_degradation_allows(
                    worker_budget.WORKER_DEEP_SLEEP):
                if not manual:
                    logger.warning(
                        "[deep_sleep] global budget degradation — skip | "
                        "chat_id=%s", chat_id)
                    return False
                logger.warning(
                    "[deep_sleep] manual override: global budget degradation "
                    "| chat_id=%s", chat_id)
        except Exception:
            pass
        if manual:
            # D1/T-1771: все 4 consume независимо, verdict не применяется.
            await worker_budget.consume(None, "global", "llm_calls", 1)
            await worker_budget.consume(None, "global", "llm_tokens", est)
            await worker_budget.consume(None, f"chat:{chat_id}",
                                        "llm_calls", 1)
            await worker_budget.consume(None, f"chat:{chat_id}",
                                        "llm_tokens", est)
            return True
        ok = await worker_budget.consume(None, "global", "llm_calls", 1)
        if ok:
            ok = await worker_budget.consume(None, "global", "llm_tokens", est)
        if ok:
            ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                             "llm_calls", 1)
        if ok:
            ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                             "llm_tokens", est)
        return ok

    async def _log_deep_skip(self, chat_id: int, now: int, status: str,
                             tokens: int) -> None:
        """Аудит скипа глубокого сна (kind='deep_skip'; success — 'deep_run')."""
        try:
            await self.db.log_dream_event(chat_id, now, kind="deep_skip",
                                          tokens=tokens, status=status)
        except Exception:
            logger.warning("[deep_sleep] skip log failed — fail-open | "
                           "chat_id=%s", chat_id, exc_info=True)

    async def _log_persona_traits_tokens(self, chat_id: int, now: int,
                                         tokens: int, status: str) -> None:
        """R10.14-2: аудит токенов traits (kind='deep_traits') — учитывается
        `_deep_budget_ok` в суточном капе. Fail-open."""
        try:
            await self.db.log_dream_event(chat_id, now, kind="deep_traits",
                                          tokens=tokens, status=status)
        except Exception:
            logger.warning("[persona_traits] token log failed — fail-open | "
                           "chat_id=%s", chat_id, exc_info=True)

    async def _run_persona_traits_once(self, chat_id: int, *,
                                       now: int | None = None,
                                       manual: bool = False) -> dict:
        """F2 persona-storage-core (spec §3.4): «Как изменился характер бота?».

        Источники: свежие self-факты (origin='bot_self_reply') + убеждения
        чата. LLM-роль background → JSON-массив наблюдений → дедуп/cap/FIFO
        (bot_persona.append_traits) → persona_state.last_trait_*. Fail-open:
        любая ошибка → status='error'/'empty', прогон глубокого сна не рушится.
        """
        from services import bot_persona
        from services.dream_prompts import (
            PERSONA_EVOLUTION_PROMPT,
            build_persona_user,
            parse_persona_traits,
        )
        now = _now_ts() if now is None else int(now)
        try:
            self_facts = await self.db.get_dream_candidates(
                chat_id, now, origins=("bot_self_reply",),
                since_ts=now - _PERSONA_SELF_LOOKBACK_DAYS * 86400,
                limit=50)
        except Exception:
            self_facts = []
        try:
            beliefs = await self.db.list_recent_beliefs(
                chat_id=chat_id, limit=20, status="confirmed")
        except Exception:
            beliefs = []
        # Характер бота оценивается по его СОБСТВЕННЫМ наблюдениям (self-факты
        # origin='bot_self_reply'); без них убеждений чата недостаточно —
        # не подменяем личность общечатовым лором (fail-safe empty).
        if not self_facts:
            # F2 (spec §4.4, T-1717/T-1770): явная причина «0 черт» — нет
            # self-фактов (origin='bot_self_reply') за окно. R17-safe.
            logger.warning(
                "[persona_traits] skip | reason=no_self_facts | chat_id=%s",
                chat_id)
            await bot_persona.record_trait_status("empty")
            return {"status": "empty", "traits": 0}
        user_text = build_persona_user(self_facts, beliefs)
        messages = [
            {"role": "system", "content": PERSONA_EVOLUTION_PROMPT},
            {"role": "user", "content": user_text},
        ]
        prompt_text = PERSONA_EVOLUTION_PROMPT + user_text
        # R10.14-2 (spec F2 §3.4 п.5): traits-LLM идёт через тот же учёт, что
        # и прочие фоновые вызовы — суточный кап + worker_budget. Fail-safe:
        # превышение → skip без вызова, прогон глубокого сна не рушится.
        if not await self._deep_budget_ok(chat_id, prompt_text,
                                          manual=manual):
            logger.warning("[persona_traits] skip | reason=budget_skip | "
                           "chat_id=%s", chat_id)
            await bot_persona.record_trait_status("budget_skip")
            await self._log_persona_traits_tokens(chat_id, now, 0,
                                                  "budget_skip")
            return {"status": "budget", "traits": 0}
        try:
            raw = await self._worker_llm("background", messages,
                                         temperature=0.3)
        except Exception:
            await self._log_persona_traits_tokens(
                chat_id, now, _estimate_tokens(prompt_text), "error")
            logger.warning("[persona_traits] LLM call failed | "
                           "reason=llm_error | chat_id=%s", chat_id,
                           exc_info=True)
            await bot_persona.record_trait_status("error")
            return {"status": "error", "traits": 0}
        # Токены traits пишутся в memory_dream_log (kind='deep_traits') —
        # попадают в суточный кап `_deep_budget_ok`.
        await self._log_persona_traits_tokens(
            chat_id, now, _estimate_tokens(prompt_text, str(raw or "")),
            "done")
        try:
            traits = parse_persona_traits(raw)
        except ValueError:
            # F2 (spec §4.4): ошибка JSON промпта — R17-safe (только длина
            # ответа, без текста/промпта).
            logger.warning("[persona_traits] parse failed | "
                           "reason=json_error | chat_id=%s | raw_len=%d",
                           chat_id, len(str(raw or "")))
            await bot_persona.record_trait_status("error")
            return {"status": "error", "traits": 0}
        if not traits:
            logger.info("[persona_traits] empty answer | "
                        "reason=empty_response | chat_id=%s", chat_id)
            await bot_persona.record_trait_status("empty")
            return {"status": "empty", "traits": 0}
        try:
            written = await bot_persona.append_traits(
                traits, chat_id=chat_id, source="deep_sleep")
        except Exception:
            logger.warning("[persona_traits] write failed | "
                           "reason=write_error | chat_id=%s", chat_id,
                           exc_info=True)
            await bot_persona.record_trait_status("error")
            return {"status": "error", "traits": 0}
        status = "ok" if written else "empty"
        await bot_persona.record_trait_status(status)
        if written:
            logger.info("[persona_traits] written | chat_id=%s | count=%d",
                        chat_id, written)
        else:
            # F2 (spec §4.4): все кандидаты оказались дублями (дедуп/cap).
            logger.info("[persona_traits] skip | reason=all_duplicates | "
                        "chat_id=%s | candidates=%d", chat_id, len(traits))
        return {"status": status, "traits": written}

    async def _paradigm_dedup_keys(self, chat_id: int) -> set[str]:
        """dedup_key существующих парадигм чата (анти-дубли, spec §4)."""
        rows = await self.db.list_recent_beliefs(
            chat_id=chat_id, limit=200, belief_type="paradigm")
        keys: set[str] = set()
        for row in rows:
            key = self._belief_meta(row).get("dedup_key")
            if key:
                keys.add(str(key))
        return keys

    async def _write_paradigm(self, chat_id: int, text: str, packet: dict,
                              anchor_items: list, source_ids: list,
                              dedup_key: str, now: int) -> int | None:
        """Запись парадигмы без DDL (spec §2): origin='derived_belief',
        kind='belief', weight=0.55, belief_meta.type='paradigm',
        source_ids — id опор, target_user — ключевая персона якорей."""
        clean = " ".join(str(text or "").split())
        if not clean:
            return None
        if len(clean) > 400:
            clean = clean[:400].rstrip()
        source_ids = [int(i) for i in source_ids]
        importance = min(10, max(1, len(source_ids) or len(anchor_items)))
        target_user = next(
            (_anchor_target(a) for a in anchor_items if _anchor_target(a)), None)
        meta = json.dumps({
            "type": "paradigm",
            "anchors": [(_anchor_text(a) or "")[:200]
                        for a in anchor_items][:20],
            "lookback_hours": _DEEP_SLEEP_LOOKBACK_HOURS,
            "bridge": True,
            "created_at": int(now),
            "sources_count": len(source_ids),
            "dedup_key": dedup_key,
            "base_weight": _DEEP_SLEEP_WEIGHT,
        }, ensure_ascii=False)
        fact_id = await self.db.insert_graph_fact(
            chat_id, clean, "derived_belief", None, target_user=target_user,
            weight=_DEEP_SLEEP_WEIGHT, importance=importance,
            source_ids=json.dumps(source_ids, ensure_ascii=False),
            kind="belief", belief_meta=meta)
        if fact_id and self.memory is not None \
                and getattr(self.memory, "_vec_available", False):
            try:
                await self.memory._save_graph_fact_embedding(
                    fact_id, chat_id, clean, "derived_belief", target_user)
            except Exception:
                logger.warning(
                    "[deep_sleep] paradigm embed failed — fact lives text+FTS "
                    "| id=%s", fact_id, exc_info=True)
        logger.info(
            "[deep_sleep] paradigm | chat_id=%s | id=%s | anchors=%d | "
            "sources=%d", chat_id, fact_id, len(anchor_items), len(source_ids))
        return fact_id


def _anchor_text(item) -> str:
    """Текст якоря (4-кортеж RAG `get_rag_facts` или dict)."""
    if isinstance(item, dict):
        return str(item.get("fact") or "")
    if isinstance(item, (tuple, list)) and len(item) > 1:
        return str(item[1] or "")
    return str(item or "")


def _anchor_ts(item):
    """Дата якоря (unix; dict → rag_ts/created_at)."""
    if isinstance(item, dict):
        return item.get("rag_ts") or item.get("created_at")
    if isinstance(item, (tuple, list)) and len(item) > 2:
        return item[2]
    return None


def _anchor_target(item):
    """Автор (target_user) якоря — ключевая персона парадигмы."""
    if isinstance(item, dict):
        return item.get("target_user")
    if isinstance(item, (tuple, list)) and len(item) > 3:
        return item[3]
    return None


def _anchor_is_old(item, now: int) -> bool:
    """Якорь «исторический» (старше _DEEP_SLEEP_MIN_ANCHOR_AGE_DAYS)?
    Отсутствие даты → не исторический (защита от мусора)."""
    ts = _anchor_ts(item)
    try:
        return (int(ts) > 0
                and (int(now) - int(ts))
                > _DEEP_SLEEP_MIN_ANCHOR_AGE_DAYS * 86400)
    except (TypeError, ValueError):
        return False


def _deep_dedup_key(text: str, anchor_items: list) -> str:
    """Стабильный dedup-ключ парадигмы: hash(текст + отсортированные тексты
    якорей). Анти-дубли прогонов (spec §4)."""
    raw = "|".join([str(text or "").strip().casefold()]
                   + sorted(_anchor_text(a).strip().casefold()
                            for a in anchor_items))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _estimate_tokens(*texts: str) -> int:
    """Оценка токенов LLM-вызова (§3.4.4): max(1, Σ len(texts)/4) —
    консервативная (потолок ceil)."""
    return max(1, (sum(len(str(t)) for t in texts) + 3) // 4)
