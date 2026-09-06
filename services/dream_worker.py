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
import json
import logging
import re
import time

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo

from config.settings import settings
from services import hot_config as hot
from services.dream_prompts import (
    DREAM_DISTILL_PROMPT,
    build_dream_user,
    parse_distill_answer,
)

logger = logging.getLogger(__name__)

_DREAM_BELIEF_WEIGHT = 0.6       # spec §3.4.6: вес belief (константа)
_DREAM_MAX_BELIEFS = 2           # spec §3.4.5: 0–2 убеждения на кластер
_DREAM_MAX_USER_FACTS = 25       # user-блок дистилляции: до 25 фактов
_DREAM_NEAR_LIMIT_DIST = 5       # §3.4.4: «почти у предела» дистилляций
_DREAM_NEAR_LIMIT_TOKENS = 5000  # §3.4.4: «почти у предела» токенов
_DREAM_PARTICIPANT_WINDOW_DAYS = 7  # окно имён участников (roster)
_DREAM_PARTICIPANT_CAP = 150     # потолок имён/участников на чат

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
        tz = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
        self._tz_name = str(tz or "UTC")
        self._scheduler = AsyncIOScheduler(timezone=self._tz_name)

    # ── ключи (hot с фолбэком settings; категория memory, spec §3.6.4) ──

    def _key(self, name: str, default):
        return hot.get(f"memory.dream_{name}", default)

    # ── служебное (F2-API, spec §3.6.2) ──────────────────────────────────

    @property
    def running(self) -> bool:
        """Идёт ли прогон (ручной run_once/тик) — анти-рейс 409 в API."""
        return self._run_lock.locked()

    # ── планировщик ───────────────────────────────────────────────

    def start(self) -> None:
        """Регистрирует джоб dream_tick ТОЛЬКО при memory.dream_enabled
        (default false). Повторный start — идемпотентен (replace_existing).
        Фикс-раунд (major-6/D-20): тик МИНУТНЫЙ (dream_tick_minutes, 60) —
        первый тик внутри окна [4, 6) local дистиллирует при старте в любое
        время суток (водяной знак вне окна не двигается, см. D-5/D-13)."""
        if not self._key("enabled", settings.DREAM_ENABLED):
            logger.info("DreamWorker disabled (memory.dream_enabled off)")
            return
        self._scheduler.add_job(
            self._tick,
            IntervalTrigger(
                minutes=self._key("tick_minutes",
                                  settings.DREAM_TICK_MINUTES),
                timezone=self._tz_name),
            id=self.JOB_DREAM_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        if not self._scheduler.running:
            self._scheduler.start()
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
        анти-рейс с ручным run_once — _run_lock."""
        if self._run_lock.locked():
            return
        async with self._run_lock:
            try:
                await self._run(manual=False)
            except Exception:
                logger.warning("[dream] tick failed — fail-open", exc_info=True)

    async def run_once(self, chat_id: int | None = None) -> dict:
        """Ручной запуск «синтеза сейчас» (F2-API): окно диалогов НЕ
        применяется (D-5), бюджеты соблюдаются. Идущий прогон → immediate
        {"status": "already_running"} (409-паттерн API)."""
        if self._run_lock.locked():
            return {"status": "already_running"}
        async with self._run_lock:
            try:
                stats = await self._run(manual=True, only_chat=chat_id)
            except Exception:
                logger.warning("[dream] run_once failed — fail-open",
                               exc_info=True)
                return {"status": "error"}
        return {"status": "ok", **stats}

    # ── тик ───────────────────────────────────────────────────────

    async def _run(self, *, manual: bool,
                   only_chat: int | None = None) -> dict:
        now = _now_ts()
        stats = {"chats": 0, "clusters": 0, "distilled": 0, "unchanged": 0,
                 "errors": 0, "window_skips": 0, "budget_stop": False}
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
        source_ids = [int(r["id"]) for r in cluster]
        user_text = build_dream_user([dict(r) for r in cluster],
                                     max_facts=_DREAM_MAX_USER_FACTS)
        prompt_text = DREAM_DISTILL_PROMPT + "\n" + user_text
        messages = [{"role": "system", "content": DREAM_DISTILL_PROMPT},
                    {"role": "user", "content": user_text}]
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

    async def _llm_once(self, messages: list, prompt_text: str):
        """Один облачный LLM-вызов (NFR-1: только LLMClient-путь бота).
        Возвращает (content | None, оценка токенов max(1, len/4))."""
        try:
            raw = await self.llm.generate(messages, temperature=0.3)
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
        meta = json.dumps({
            "confidence": 1.0,
            "sources_count": len(sources),
            "distilled_at": run_at,
            "cluster_id": cluster_id,
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


def _estimate_tokens(*texts: str) -> int:
    """Оценка токенов LLM-вызова (§3.4.4): max(1, Σ len(texts)/4) —
    консервативная (потолок ceil)."""
    return max(1, (sum(len(str(t)) for t in texts) + 3) // 4)
