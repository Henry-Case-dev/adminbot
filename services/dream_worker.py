"""Раунд 9 (AGI Memory, spec §3.4, T-824/T-825) — DreamWorker: «сон» (beliefs).

Фоновый SQLite-воркер (каркас memory_maintenance.py/lore_worker.py, БЕЗ
PG-lock: состояние — SQLite dream_state/memory_dream_log, NFR-7).
Тик IntervalTrigger(minutes=memory.dream_tick_minutes=60) регистрируется
ТОЛЬКО при hot.get("memory.dream_enabled", settings.DREAM_ENABLED) (default
false, Q12). Запуск в bot.py on_startup после lore-блока (fail-open); ручной
run_once(chat_id) — для F2-API, окно диалогов игнорирует (D-5), бюджеты
соблюдает.

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


async def _dream_budget_ok(chat_id: int, user_text: str) -> bool:
    """F-10 §5: consume до LLM-вызова дистилляции — global + chat:<id>
    (calls 1 + tokens est); любое False → budget-скип. Fail-open внутри
    consume (PG down → True). ФИКС R4: приоритетная деградация по
    global-лимиту (dream падает первым до consume — allowed_workers)."""
    from services import worker_budget
    if not await worker_budget.global_degradation_allows("dream"):
        logger.warning(
            "[dream] skip: global budget exhausted — degradation dream | "
            "chat=%s", chat_id)
        return False
    est = worker_budget.estimate_tokens(user_text)
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
_DEEP_SLEEP_USER_JOB_ID = "deep_sleep_tick"

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
        tz = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
        self._tz_name = str(tz or "UTC")
        # S10.13-8 (spec F3 §3): сутки/час глубокого сна считаются в
        # WORKER_BUDGET_TZ (как worker_budget), не в SUMMARY_TIMEZONE.
        deep_tz = hot.get("limits.worker_budget_tz", settings.WORKER_BUDGET_TZ)
        self._deep_tz_name = str(deep_tz or "UTC")
        self._scheduler = AsyncIOScheduler(timezone=self._tz_name)

    # ── ключи (hot с фолбэком settings; категория memory, spec §3.6.4) ──

    def _key(self, name: str, default):
        return hot.get(f"memory.dream_{name}", default)

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

    # ── планировщик ───────────────────────────────────────────────

    def start(self) -> None:
        """Регистрирует джоб dream_tick ТОЛЬКО при memory.dream_enabled
        (default false). Повторный start — идемпотентен (replace_existing).
        Фикс-раунд (major-6/D-20): тик МИНУТНЫЙ (dream_tick_minutes, 60) —
        первый тик внутри окна [4, 6) local дистиллирует при старте в любое
        время суток (водяной знак вне окна не двигается, см. D-5/D-13).

        F3/T-1435: при flags.deep_sleep_enabled регистрируется отдельный
        минутный джоб deep_sleep_tick (режим trigger='fixed' — проверка
        своего часа local; режим after_sleep запускается хуком после _run)."""
        enabled = bool(self._key("enabled", settings.DREAM_ENABLED))
        deep_on = bool(hot.get("flags.deep_sleep_enabled",
                               settings.DEEP_SLEEP_ENABLED))
        if not enabled and not deep_on:
            logger.info("DreamWorker disabled (memory.dream_enabled off)")
            return
        # Раунд 10 (F-10 §5.2): jitter тика (случайный сдвиг ≤ интервал/3)
        # — ТОЛЬКО при явном ключе worker_budget_jitter_minutes.
        base_minutes = int(self._key("tick_minutes",
                                     settings.DREAM_TICK_MINUTES) or 60)
        tick_minutes = base_minutes + _tick_jitter(base_minutes)
        if enabled:
            self._scheduler.add_job(
                self._tick,
                IntervalTrigger(
                    minutes=tick_minutes,
                    timezone=self._tz_name),
                id=self.JOB_DREAM_ID, replace_existing=True,
                max_instances=1, coalesce=True)
            logger.info(
                "DreamWorker started (tick=%sm, window=%s-%s, "
                "clusters=%s/distillations=%s/day)",
                self._key("tick_minutes", settings.DREAM_TICK_MINUTES),
                self._key("window_start_hour", settings.DREAM_WINDOW_START_HOUR),
                self._key("window_end_hour", settings.DREAM_WINDOW_END_HOUR),
                self._key("max_clusters_per_run",
                          settings.DREAM_MAX_CLUSTERS_PER_RUN),
                self._key("distillations_per_day",
                          settings.DREAM_DISTILLATIONS_PER_DAY))
        if deep_on:
            self._scheduler.add_job(
                self._deep_tick,
                IntervalTrigger(
                    minutes=tick_minutes,
                    timezone=self._tz_name),
                id=_DEEP_SLEEP_USER_JOB_ID, replace_existing=True,
                max_instances=1, coalesce=True)
            logger.info(
                "DeepSleep started (tick=%sm, trigger=%s, top_k=%s, "
                "max_paradigms=%s/day)",
                tick_minutes,
                hot.get("memory.deep_sleep_trigger",
                        settings.DEEP_SLEEP_TRIGGER),
                hot.get("limits.deep_sleep_top_k", settings.DEEP_SLEEP_TOP_K),
                hot.get("limits.deep_sleep_max_paradigms_per_run",
                        settings.DEEP_SLEEP_MAX_PARADIGMS))
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
        обычного сна — хук глубокого сна (режим after_sleep)."""
        if self._run_lock.locked():
            return
        stats = None
        async with self._run_lock:
            try:
                stats = await self._run(manual=False)
            except Exception:
                logger.warning("[dream] tick failed — fail-open", exc_info=True)
        try:
            await self._maybe_deep_after_sleep(stats)
        except Exception:
            logger.warning("[dream] deep sleep after tick failed — fail-open",
                           exc_info=True)

    async def run_once(self, chat_id: int | None = None, *,
                       deep: bool = False) -> dict:
        """Ручной запуск «синтеза сейчас» (F2-API): окно диалогов НЕ
        применяется (D-5), бюджеты соблюдаются. Идущий прогон → immediate
        {"status": "already_running"} (409-паттерн API).

        F3/T-1435: deep=True — ручной запуск ГЛУБОКОГО сна (staged rollout
        §8: POST /api/memory/dream/run?deep=1); игнорирует cooldown/флаг
        автозапуска (явное действие админа), но соблюдает лимиты стоимости."""
        if deep:
            if self._deep_lock.locked():
                return {"status": "already_running"}
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
        async with self._run_lock:
            try:
                stats = await self._run(manual=True, only_chat=chat_id)
            except Exception:
                logger.warning("[dream] run_once failed — fail-open",
                               exc_info=True)
                return {"status": "error"}
        try:
            await self._maybe_deep_after_sleep(stats)
        except Exception:
            logger.warning("[dream] deep sleep after run_once failed — "
                           "fail-open", exc_info=True)
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
        for chat in chats:
            result = await self._process_chat(chat["chat_id"], now,
                                              manual=manual)
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
                    "distilled_today=%d",
                    await self.db.count_dream_log(
                        _day_start_ts(now, self._tz_name), kind="distilled"))
                break
        return stats

    # ── обработка чата ────────────────────────────────────────────

    async def _process_chat(self, chat_id: int, now: int, *,
                            manual: bool) -> dict:
        """Один тик-батч чата: кандидаты → кластеры → дистилляции →
        watermark/аудит. Возвращает счётчики (fail-open: ошибка → WARNING,
        watermark не двигается)."""
        out = {"clusters": 0, "distilled": 0, "unchanged": 0, "errors": 0,
               "window_skips": 0, "budget_stop": False}
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
            overlap_tokens=int(self._key(
                "cluster_overlap_tokens",
                settings.DREAM_CLUSTER_OVERLAP_TOKENS) or 2),
            extra_terms=terms)
        repeat_min = int(self._key("repeat_threshold",
                                   settings.DREAM_REPEAT_THRESHOLD) or 3)
        sum_min = int(self._key("importance_sum_threshold",
                                settings.DREAM_IMPORTANCE_SUM_THRESHOLD) or 12)
        qualified = [
            cl for cl in clusters
            if len(cl) >= repeat_min
            and sum(int(r["importance"] or 0) for r in cl) >= sum_min
        ]
        qualified.sort(
            key=lambda cl: (sum(int(r["importance"] or 0) for r in cl),
                            cl[0]["id"]),
            reverse=True)
        top = qualified[: int(self._key(
            "max_clusters_per_run",
            settings.DREAM_MAX_CLUSTERS_PER_RUN) or 5)]
        run_at = now
        await self.db.log_dream_event(chat_id, run_at, kind="run",
                                      status="ok")
        if not top:
            logger.info("[dream] no qualifying clusters | chat_id=%s "
                        "| facts=%d", chat_id, len(rows))
            await self._finish_chat(chat_id, now, rows)   # все факты отобраны
            return out
        # Раунд 10 (F-10 §6): тяжёлый гейт dream — kill-switch
        # (chat gates[dream] → глобальный флаг → False); skip-аудит —
        # memory_dream_log status='budget_skip' (прецедент). ФИКС R5:
        # гейт применяется и к ручному run_once (F-10 §6 БЕЗ carve-out) —
        # kill-switch останавливает и ручные запуски.
        try:
            from services.feature_gates import gates_enabled
            if not await gates_enabled(chat_id, "dream"):
                logger.warning(
                    "[dream] WARNING skip: gate dream | chat_id=%s",
                    chat_id)
                await self.db.log_dream_event(
                    chat_id, run_at, kind="skipped", status="budget_skip")
                return out
        except Exception:
            logger.warning("[dream] gate check failed — fail-open | "
                           "chat_id=%s", chat_id, exc_info=True)
        day_start = _day_start_ts(now, self._tz_name)
        distilled_today = await self.db.count_dream_log(
            day_start, kind="distilled")
        tokens_today = await self.db.sum_dream_log_tokens(day_start)
        abnormal = None                     # 'error' | 'window' | 'budget'
        failed_cluster = None
        for cluster_id, cluster in enumerate(top, 1):
            if not manual and not self._window_open(now):
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
            # суточные бюджеты (§3.4.4) — стоп тика заранее
            reason = self._budget_reason(distilled_today, tokens_today)
            if reason:
                logger.warning(
                    "[dream] budget %s reached — tick stopped | chat_id=%s",
                    reason, chat_id)
                out["budget_stop"] = True
                abnormal = "budget"
                break
            if (self._daily_limit("distillations_per_day",
                                  settings.DREAM_DISTILLATIONS_PER_DAY)
                    - distilled_today < _DREAM_NEAR_LIMIT_DIST
                    or (self._daily_limit(
                        "tokens_per_day", settings.DREAM_TOKENS_PER_DAY)
                        - tokens_today) < _DREAM_NEAR_LIMIT_TOKENS):
                logger.warning(
                    "[dream] near daily limit — tick finished early | "
                    "chat_id=%s", chat_id)
                out["budget_stop"] = True
                abnormal = "budget"
                break
            outcome, tokens_used, unchanged = await self._distill_cluster(
                chat_id, run_at, cluster, cluster_id)
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
            since_ts=now - int(self._key(
                "initial_window_hours",
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

    def _window_open(self, now_ts: int) -> bool:
        """Local-час в окне [start, end) дистилляций (D-5; дефолт 4–6)."""
        start = int(self._key("window_start_hour",
                              settings.DREAM_WINDOW_START_HOUR) or 4)
        end = int(self._key("window_end_hour",
                            settings.DREAM_WINDOW_END_HOUR) or 6)
        hour = _local_hour(now_ts, self._tz_name)
        return start <= hour < end

    def _daily_limit(self, name: str, default) -> int:
        return int(self._key(name, default) or 0)

    def _budget_reason(self, distilled_today: int,
                       tokens_today: int) -> str | None:
        """Суточные бюджеты §3.4.4 (глобально): дистилляции/токены. None —
        можно работать."""
        dist_max = self._daily_limit("distillations_per_day",
                                     settings.DREAM_DISTILLATIONS_PER_DAY)
        tok_max = self._daily_limit("tokens_per_day",
                                    settings.DREAM_TOKENS_PER_DAY)
        if dist_max and distilled_today >= dist_max:
            return "distillations"
        if tok_max and tokens_today >= tok_max:
            return "tokens"
        return None

    # ── дистилляция ───────────────────────────────────────────────

    async def _distill_cluster(self, chat_id: int, run_at: int,
                               cluster: list, cluster_id: int) -> tuple:
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
        if not await _dream_budget_ok(chat_id, user_text):
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
        """belief_meta строки belief → dict (битое/пустое → {})."""
        raw = row.get("belief_meta") if hasattr(row, "get") else None
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            loaded = json.loads(str(raw))
        except (ValueError, TypeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

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

    async def _maybe_deep_after_sleep(self, stats: dict | None) -> None:
        """Хук after_sleep (spec §3): если флаг включён и триггер
        'after_sleep' — запускает глубокий сон по чатам только что
        завершившегося обычного сна."""
        if not hot.get("flags.deep_sleep_enabled",
                       settings.DEEP_SLEEP_ENABLED):
            return
        trigger = str(hot.get("memory.deep_sleep_trigger",
                              settings.DEEP_SLEEP_TRIGGER) or "after_sleep")
        if trigger != "after_sleep":
            return
        if not stats:
            return
        if not (int(stats.get("distilled") or 0) > 0
                or int(stats.get("chats") or 0) > 0):
            return
        chats = list(self._last_chat_ids or [])
        if not chats:
            return
        await self._run_deep_all(chats, since_ts=self._last_run_started,
                                 manual=False)

    async def _deep_tick(self) -> None:
        """Scheduler-джоб deep_sleep_tick: режим trigger='fixed' — запуск в
        свой local-час (memory.deep_sleep_hour) с cooldown/лимитом суток."""
        if not hot.get("flags.deep_sleep_enabled",
                       settings.DEEP_SLEEP_ENABLED):
            return
        trigger = str(hot.get("memory.deep_sleep_trigger",
                              settings.DEEP_SLEEP_TRIGGER) or "after_sleep")
        if trigger != "fixed":
            return
        now = _now_ts()
        target = int(hot.get("memory.deep_sleep_hour",
                             settings.DEEP_SLEEP_HOUR) or 7)
        if _local_hour(now, self._deep_tz_name) != target:
            return
        if self._deep_lock.locked():
            return
        try:
            await self._run_deep_all(None, manual=False)
        except Exception:
            logger.warning("[dream] deep tick failed — fail-open",
                           exc_info=True)

    async def _run_deep_all(self, chat_ids=None, *, since_ts: int | None = None,
                            manual: bool = False) -> dict:
        """Прогон глубокого сна по набору чатов (None → кандидаты 12ч).
        Анти-наложение — _deep_lock/max_instances=1; авто-режим останавливается
        после первого успешного прогона (лимиты стоимости spec §4)."""
        if self._deep_lock.locked():
            return {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 1}
        async with self._deep_lock:
            if chat_ids is None:
                now = _now_ts()
                try:
                    candidates = await self.db.get_dream_candidate_chats(
                        now, origins=_DREAM_SOURCE_ORIGINS,
                        initial_window_hours=_DEEP_SLEEP_LOOKBACK_HOURS,
                        min_new_facts=1,
                        max_chats=int(self._key(
                            "max_chats_per_run",
                            settings.DREAM_MAX_CHATS_PER_RUN) or 10))
                except Exception:
                    logger.warning("[deep_sleep] candidate chats failed — "
                                   "fail-open", exc_info=True)
                    candidates = []
                chat_ids = [int(c["chat_id"]) for c in candidates]
            stats = {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 0}
            for cid in chat_ids:
                try:
                    out = await self._run_deep_once(
                        int(cid), since_ts=since_ts, manual=manual)
                except Exception:
                    logger.warning("[deep_sleep] deep run failed — fail-open "
                                   "| chat_id=%s", cid, exc_info=True)
                    out = {"status": "error", "paradigms": 0}
                stats["chats"] += 1
                stats["paradigms"] += int(out.get("paradigms") or 0)
                if out.get("status") == "ok":
                    stats["ran"] += 1
                    if not manual:
                        break          # авто: 1 успешный прогон за раз
                else:
                    stats["skipped"] += 1
            return stats

    async def _run_deep_once(self, chat_id: int, *, since_ts: int | None = None,
                             manual: bool = False) -> dict:
        """Один прогон «Поиска по якорям» + «Моста времени» для чата (spec
        §4). Никогда не бросает (fail-open): ошибка RAG/LLM/записи → skip."""
        now = _now_ts()
        if not manual and not hot.get("flags.deep_sleep_enabled",
                                      settings.DEEP_SLEEP_ENABLED):
            return {"status": "disabled", "paradigms": 0}
        if not manual:
            try:
                # S10.13-2: суточный лимит и cooldown учитывают и неуспешные
                # попытки (deep_skip), иначе no_anchors/unchanged/duplicate/
                # error повторялись бы каждый тик/after_sleep.
                if await self.db.count_deep_attempts(
                        _day_start_ts(now, self._deep_tz_name)) >= 1:
                    return {"status": "daily_limit", "paradigms": 0}
                last = await self.db.last_deep_attempt(chat_id)
            except Exception:
                logger.warning("[deep_sleep] cooldown read failed — skip | "
                               "chat_id=%s", chat_id, exc_info=True)
                return {"status": "error", "paradigms": 0}
            cooldown = _hot_number(
                "memory.deep_sleep_min_interval_hours",
                _DEEP_SLEEP_MIN_INTERVAL_HOURS, int)
            if last is not None and (now - int(last)) < cooldown * 3600:
                return {"status": "cooldown", "paradigms": 0}
        if self.memory is None:
            return {"status": "no_memory", "paradigms": 0}
        try:
            packet = await self._build_deep_packet(chat_id, now, since_ts)
        except Exception:
            logger.warning("[deep_sleep] packet build failed — skip | "
                           "chat_id=%s", chat_id, exc_info=True)
            return {"status": "error", "paradigms": 0}
        if not packet["beliefs"] and not packet["recent"]:
            return {"status": "no_context", "paradigms": 0}
        query = " ".join(
            [str(b.get("fact") or "") for b in packet["beliefs"][:20]]
            + [str(r.get("fact") or "") for r in packet["recent"]])
        try:
            anchors = await self.memory.get_rag_facts(chat_id, query)
        except Exception:
            logger.warning("[deep_sleep] RAG failed — skip | chat_id=%s",
                           chat_id, exc_info=True)
            return {"status": "error", "paradigms": 0}
        top_k = _hot_number("limits.deep_sleep_top_k",
                            settings.DEEP_SLEEP_TOP_K, int)
        anchors = list(anchors or [])[: max(1, top_k)]
        historical = [a for a in anchors if _anchor_is_old(a, now)]
        if len(historical) < _DEEP_SLEEP_MIN_HISTORICAL:
            await self._log_deep_skip(chat_id, now, "no_anchors", 0)
            return {"status": "no_anchors", "paradigms": 0}
        user_text = build_bridge_user(packet, historical)
        messages = [
            {"role": "system", "content": DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        if not await self._deep_budget_ok(
                chat_id, DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT + user_text):
            await self._log_deep_skip(chat_id, now, "budget_skip", 0)
            return {"status": "budget", "paradigms": 0}
        raw, tokens = await self._deep_llm_once(messages, user_text)
        if raw is None:
            await self._log_deep_skip(chat_id, now, "error", tokens)
            return {"status": "error", "paradigms": 0}
        try:
            paradigms = parse_bridge_answer(raw,
                                            anchor_count=len(historical),
                                            min_anchors=2)
        except ValueError:
            # 1 retry на кривой JSON (не более 1 — spec §4 «без ретраев»)
            # S10.13-2: перед retry перепроверяем токен-кап с учётом уже
            # потраченных токенов первой попытки.
            if not await self._deep_budget_ok(chat_id, user_text,
                                              extra_tokens=tokens):
                await self._log_deep_skip(chat_id, now, "budget_skip", tokens)
                return {"status": "budget", "paradigms": 0}
            raw2, tokens2 = await self._deep_llm_once(messages, user_text)
            tokens += tokens2
            if raw2 is None:
                await self._log_deep_skip(chat_id, now, "error", tokens)
                return {"status": "error", "paradigms": 0}
            try:
                paradigms = parse_bridge_answer(
                    raw2, anchor_count=len(historical), min_anchors=2)
            except ValueError:
                await self._log_deep_skip(chat_id, now, "error", tokens)
                return {"status": "error", "paradigms": 0}
        if not paradigms:
            await self._log_deep_skip(chat_id, now, "unchanged", tokens)
            return {"status": "unchanged", "paradigms": 0}
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
        return {"status": "ok" if written else "duplicate",
                "paradigms": written, "tokens": tokens}

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
                              extra_tokens: int = 0) -> bool:
        """Суточный токен-кап глубокого сна (limits.deep_sleep_tokens_per_day,
        40000) + worker_budget.consume (worker='deep_sleep'); fail-open.

        S10.13-2: кап считает токены и успешных (`deep_run`), и скип-прогонов
        (`deep_skip`) — иначе error/unchanged/duplicate обходили лимит.
        `extra_tokens` — уже потраченные токены текущей попытки (retry)."""
        from services import worker_budget
        cap = _hot_number("limits.deep_sleep_tokens_per_day",
                          settings.DEEP_SLEEP_TOKENS_PER_DAY, int)
        est = worker_budget.estimate_tokens(prompt_text)
        day_start = _day_start_ts(_now_ts(), self._deep_tz_name)
        try:
            used = await self.db.sum_dream_log_tokens(day_start, kind="deep_run")
            used += await self.db.sum_dream_log_tokens(day_start,
                                                       kind="deep_skip")
        except Exception:
            used = 0
        if cap and used + int(extra_tokens or 0) + est > cap:
            logger.warning(
                "[deep_sleep] daily token cap reached — skip | chat_id=%s | "
                "used=%d | cap=%d", chat_id, used, cap)
            return False
        try:
            if not await worker_budget.global_degradation_allows(
                    worker_budget.WORKER_DEEP_SLEEP):
                logger.warning(
                    "[deep_sleep] global budget degradation — skip | "
                    "chat_id=%s", chat_id)
                return False
        except Exception:
            pass
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
