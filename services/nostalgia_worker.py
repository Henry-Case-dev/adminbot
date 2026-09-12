"""Раунд 9 (AGI Memory, spec §3.5, T-827/E2) — NostalgiaWorker: ностальгия
слой B (проактивные «кстати...» в тихих группах).

Фоновый SQLite-воркер по каркасу dream_worker (AsyncIOScheduler +
IntervalTrigger(minutes=limits.nostalgia_tick_minutes=60, timezone=…) +
max_instances=1 + coalesce), БЕЗ PG-lock. Джоб `nostalgia_tick`
регистрируется ТОЛЬКО при hot memory.nostalgia_enabled (default false,
Q12). Запуск в bot.py on_startup ПОСЛЕ DreamWorker (fail-open); ручной
run_once(chat_id) — для будущего F2-API (D-8: test-эндпоинт НЕ в v1).

Тик (spec §3.5.3/§3.5.4; чаты — ТОЛЬКО активные PG-профили
ChatLoreStore.list_active_chat_ids, Q13; PG down/пусто → no-op WARNING):
дешёвые гейты чата (skip = WARNING без строк в nostalgia_log):
  1. флаг ON (тик), chat_id < 0, is_active-профиль;
  2. тишина: последнее юзерское сообщение старше nostalgia_min_silence_minutes;
     истории нет вовсе → no_history;
  3. quiet hours: local-час (timezone summary_timezone) >= start ИЛИ < end
     (пересечение полуночи);
  4. cooldown: прошло ≥ nostalgia_cooldown_hours с последнего sent;
  5. дневной лимит: status='sent' за local-сутки < nostalgia_max_per_day;
  6. Q14 (анти-спам): среди последних sent чата за окно
     nostalgia_pause_hours (24 ч) нет подряд nostalgia_unanswered_max
     неотвеченных (юзерские сообщения после ts отправки — smart_messages,
     user_id NOT NULL и != bot_id); стоп → skip, чат молчит, пока окно
     pause_hours не пройдёт ИЛИ юзер не ответит (D-17: пауза неявная —
     то же условие повторяется на следующих тиках).
Дорогие шаги (строки в nostalgia_log):
  кандидаты (§3.5.2): «год назад» (строки smart_messages в окне
  now − 365д ± nostalgia_year_back_days_window, ≤3, вес набора 0.7) и/или
  «золотые» по последней теме (ключи последних 5 юзерских сообщений →
  memory.fetch_golden_facts, ≤2 факта; вес факта 0.3 + 0.05*importance);
  кандидат = максимум веса (равенство → «год назад»). Порог 0.3 +
  nostalgia_aggressiveness*0.5 (дефолт 0.3 → 0.45) → ниже skip threshold;
  LLM (1 облачный вызов, NOSTALGIA_PROMPT): UNCHANGED → skipped unchanged
  (дневной лимит не тратится); текст: trim + cap nostalgia_max_send_chars,
  пустой → skipped empty; отправка bot.send_message (plain, Q13);
  сбой → status='error'; успех → status='sent'.

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
from services.nostalgia_prompts import (
    NOSTALGIA_PROMPT,
    build_nostalgia_user,
    clean_llm_text,
    format_golden_line,
    format_year_back_line,
    is_unchanged_response,
)

logger = logging.getLogger(__name__)

_YEAR_SECONDS = 365 * 86400
_MAX_YEAR_BACK_LINES = 3       # spec §3.5.2: ≤3 строки «[Имя дата]: текст»
_GOLDEN_FACT_LIMIT = 2         # spec §3.5.2: 1–2 факта по последней теме
_YEAR_BACK_WEIGHT = 0.7        # spec §3.5.2: вес набора «год назад»
_TOPIC_MESSAGES = 5            # spec §3.5.2: ключи последних 5 юзерских
_TOPIC_KEYWORDS_CAP = 40       # потолок значимых слов FTS-матча «темы»
_FALLBACK_WINDOW_HOURS = 24    # фолбэк окна неотвеченных (D-17: окно =
                               # nostalgia_pause_hours, дефолт 24 ч)
_MAX_WORDS = 60                # промпт-канон: максимум слов в ответе
_KIND_NONE = "none"            # kind лога при «кандидатов нет»
_STATUS_SENT = "sent"
_STATUS_SKIPPED = "skipped"
_STATUS_ERROR = "error"

_TOPIC_WORD_RE = re.compile(r"[а-яёa-z0-9]{5,}", re.IGNORECASE)


def _now_ts() -> int:
    """Текущее unix-время (обёртка — тесты подменяют для гейтов/окон)."""
    return int(time.time())


def _day_start_ts(now_ts: int, tz_name: str | None = None) -> int:
    """Начало local-суток (полночь в timezone ностальгии) — дневной лимит
    §3.5.3 п.5 (edge 20: окна/сутки — local summary_timezone)."""
    zone = _zone(tz_name)
    local = datetime.datetime.fromtimestamp(now_ts, zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


def _local_hour(now_ts: int, tz_name: str | None = None) -> int:
    """Текущий local-час в timezone ностальгии (quiet hours)."""
    return datetime.datetime.fromtimestamp(now_ts, _zone(tz_name)).hour


def _zone(tz_name: str | None):
    try:
        return ZoneInfo(str(tz_name)) if tz_name else None
    except Exception:
        return None


class NostalgiaWorker:
    """Проактивная ностальгия тихих групп (слой B, spec §3.5)."""

    JOB_NOSTALGIA_ID = "nostalgia_tick"

    def __init__(self, db, memory=None, store=None, llm=None, bot=None,
                 bot_id: int | None = None) -> None:
        self.db = db
        self.memory = memory          # MemoryManager (fetch_golden_facts)
        self.store = store            # ChatLoreStore (list_active_chat_ids)
        self.llm = llm                # облачный LLMClient (NFR-1)
        self.bot = bot                # aiogram Bot (Q13: send_message)
        self.bot_id = int(bot_id or 0)
        self._run_lock = asyncio.Lock()
        self._tz_name = str(hot.get("limits.summary_timezone",
                                    settings.SUMMARY_TIMEZONE) or "UTC")
        self._scheduler = AsyncIOScheduler(timezone=self._tz_name)

    # ── ключи (hot с фолбэком settings; категория memory, spec §3.6.4) ──

    def _key(self, name: str, default):
        return hot.get(f"memory.nostalgia_{name}", default)

    def _limit(self, name: str, default) -> int:
        return int(self._key(name, default) or 0)

    def _flag(self, name: str, default) -> bool:
        return bool(self._key(name, default))

    # ── служебное (F2-API, spec §3.6.2) ──────────────────────────────────

    @property
    def running(self) -> bool:
        """Идёт ли прогон (ручной run_once/тик) — анти-рейс 409 в API."""
        return self._run_lock.locked()

    # ── планировщик ───────────────────────────────────────────────

    def start(self) -> None:
        """Регистрирует джоб nostalgia_tick ТОЛЬКО при
        memory.nostalgia_enabled (default false). Повторный start —
        идемпотентен (replace_existing)."""
        if not self._flag("enabled", settings.NOSTALGIA_ENABLED):
            logger.info("NostalgiaWorker disabled (memory.nostalgia_enabled "
                        "off)")
            return
        # Раунд 10 (F-10 §5.2): jitter тика (случайный сдвиг ≤ интервал/3);
        # 0 — если jitter явно не задан (тесты/конфиг без ключа).
        base_minutes = int(self._limit("tick_minutes",
                                       settings.NOSTALGIA_TICK_MINUTES) or 60)
        import random
        try:
            from services import worker_budget
            tick_minutes = base_minutes + (
                random.randint(0, worker_budget.jitter_safe(base_minutes))
                if worker_budget.jitter_active() else 0)
        except Exception:
            tick_minutes = base_minutes
        self._scheduler.add_job(
            self._tick,
            IntervalTrigger(
                minutes=tick_minutes,
                timezone=self._tz_name),
            id=self.JOB_NOSTALGIA_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        if not self._scheduler.running:
            self._scheduler.start()
        logger.info(
            "NostalgiaWorker started (tick=%smin, silence=%smin, "
            "max_per_day=%s, aggressiveness=%s)",
            self._limit("tick_minutes", settings.NOSTALGIA_TICK_MINUTES),
            self._limit("min_silence_minutes",
                        settings.NOSTALGIA_MIN_SILENCE_MINUTES),
            self._limit("max_per_day", settings.NOSTALGIA_MAX_PER_DAY),
            self._key("aggressiveness",
                      settings.NOSTALGIA_AGGRESSIVENESS))

    async def stop(self) -> None:
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("NostalgiaWorker stopped")
        except SchedulerNotRunningError:
            logger.info("NostalgiaWorker was not running — nothing to stop")

    # ── точки входа ───────────────────────────────────────────────

    async def _tick(self) -> None:
        """Scheduler-джоб: полный тик по активным PG-чатам. Анти-рейс с
        ручным run_once — _run_lock (одновременно не отправляем)."""
        if self._run_lock.locked():
            return
        async with self._run_lock:
            try:
                await self._run(manual=False)
            except Exception:
                logger.warning(
                    "[nostalgia] tick failed — fail-open", exc_info=True)

    async def run_once(self, chat_id: int | None = None) -> dict:
        """Ручной запуск «сейчас» (будущий F2-API): флаг
        memory.nostalgia_enabled НЕ требуется (прецедент dream run_once),
        но все гейты чата соблюдаются (тишина/quiet hours/cooldown/лимиты/
        Q14 — анти-спам ручным запуском не обходится). Идущий прогон →
        {"status": "already_running"}."""
        if self._run_lock.locked():
            return {"status": "already_running"}
        async with self._run_lock:
            try:
                stats = await self._run(manual=True, only_chat=chat_id)
            except Exception:
                logger.warning("[nostalgia] run_once failed — fail-open",
                               exc_info=True)
                return {"status": "error"}
        return {"status": "ok", **stats}

    # ── тик ───────────────────────────────────────────────────────

    async def _run(self, *, manual: bool,
                   only_chat: int | None = None) -> dict:
        now = _now_ts()
        stats = {"chats": 0, "candidates": 0, "sent": 0, "skipped": 0,
                 "errors": 0}
        if only_chat is not None:
            chats: list = [int(only_chat)]
        elif self.store is None:
            logger.warning(
                "[nostalgia] tick: store отсутствует (PG-лор) — чатов нет "
                "(no-op, Q13)")
            return stats
        else:
            try:
                chats = [int(c) for c in
                         await self.store.list_active_chat_ids()]
            except Exception:
                logger.warning(
                    "[nostalgia] tick: PG down/список чатов недоступен — "
                    "no-op (Q13)", exc_info=True)
                return stats
            if not chats:
                logger.info("[nostalgia] tick: нет активных чатов (no-op)")
                return stats
        for chat_id in chats:
            result = await self._process_chat(chat_id, now, manual=manual)
            stats["chats"] += 1
            stats["candidates"] += result["candidates"]
            stats["sent"] += result["sent"]
            stats["skipped"] += result["skipped"]
            stats["errors"] += result["errors"]
        return stats

    # ── обработка чата ────────────────────────────────────────────

    async def _process_chat(self, chat_id: int, now: int, *,
                            manual: bool) -> dict:
        """Тик одного чата: гейты → кандидаты → порог → LLM → отправка →
        аудит nostalgia_log. Возвращает счётчики; fail-open (NFR-4)."""
        out = {"candidates": 0, "sent": 0, "skipped": 0, "errors": 0}
        try:
            # гейт 1: только группы/супергруппы (chat_id < 0, D-12).
            if chat_id >= 0:
                logger.info("[nostalgia] skip | chat=%s | reason=not_group",
                            chat_id)
                return out
            # ФИКС R5: глобальный гейт-флаг применяется и к ручному
            # run_once (F-10 §6: gate ⊇ manual — kill-switch стопит ручные
            # запуски; run_once-докс «без флага» устарел).
            if not self._flag("enabled", settings.NOSTALGIA_ENABLED):
                logger.info("[nostalgia] skip | chat=%s | reason=flag_off",
                            chat_id)
                return out
            # Раунд 10 (F-10 §6): тяжёлый гейт nostalgia (kill-switch:
            # gates[nostalgia] → глобальный флаг → False); ФИКС R5 — и для
            # ручного run_once; skip — nostalgia_log status='budget_skip'.
            try:
                from services.feature_gates import gates_enabled
                if not await gates_enabled(chat_id, "nostalgia"):
                    logger.warning(
                        "[nostalgia] WARNING skip: gate nostalgia | "
                        "chat=%s", chat_id)
                    await self._log(chat_id, now, "none", None,
                                    "budget_skip",
                                    {"reason": "gate_nostalgia"})
                    return out
            except Exception:
                logger.warning(
                    "[nostalgia] gate check failed — fail-open | "
                    "chat=%s", chat_id, exc_info=True)
            # гейт 2: тишина (юзерские сообщения; истории нет → no_history).
            last_ts = await self.db.get_last_user_message_ts(chat_id,
                                                             self.bot_id)
            if last_ts is None:
                logger.info(
                    "[nostalgia] skip | chat=%s | reason=no_history", chat_id)
                return out
            silence_min = int(self._limit(
                "min_silence_minutes",
                settings.NOSTALGIA_MIN_SILENCE_MINUTES) or 0) * 60
            if last_ts + silence_min > now:
                logger.info(
                    "[nostalgia] skip | chat=%s | reason=silence_too_short",
                    chat_id)
                return out
            # гейт 3: quiet hours (пересечение полуночи, spec п.3).
            if self._quiet_hours(now):
                logger.info(
                    "[nostalgia] skip | chat=%s | reason=quiet_hours", chat_id)
                return out
            # гейт 4: cooldown между sent (Q14-формула, ключ cooldown).
            last_sent = await self._last_sent_ts(chat_id)
            cooldown = int(self._limit(
                "cooldown_hours", settings.NOSTALGIA_COOLDOWN_HOURS) or 0)
            if last_sent is not None and last_sent + cooldown * 3600 > now:
                logger.info("[nostalgia] skip | chat=%s | reason=cooldown",
                            chat_id)
                return out
            # гейт 5: дневной лимит (status='sent' за local-сутки; лимит
            # тратят ТОЛЬКО sent — unchanged/empty не считаются).
            day_start = _day_start_ts(now, self._tz_name)
            max_day = int(self._limit("max_per_day",
                                      settings.NOSTALGIA_MAX_PER_DAY) or 0)
            if max_day > 0 and await self.db.count_nostalgia_sent_since(
                    chat_id, day_start) >= max_day:
                logger.info("[nostalgia] skip | chat=%s | reason=max_per_day",
                            chat_id)
                return out
            # гейт 6: Q14-стоп после N неотвеченных подряд (+пауза).
            if await self._unanswered_stop(chat_id, now):
                logger.info(
                    "[nostalgia] skip | chat=%s | reason=unanswered (Q14)",
                    chat_id)
                return out
            # ── дорогие шаги: кандидаты → порог → LLM → отправка ─────
            await self._candidate_llm_send(chat_id, now, out)
        except Exception:
            logger.warning(
                "[nostalgia] chat tick failed — WARNING, тик жив | "
                "chat_id=%s", chat_id, exc_info=True)
            out["errors"] += 1
        return out

    def _quiet_hours(self, now: int) -> bool:
        """Quiet hours активны, если local-час >= start ИЛИ < end (23..8,
        пересечение полуночи — spec §3.5.3 п.3, edge 20: local summary_tz)."""
        start = int(self._limit("quiet_start_hour",
                                settings.NOSTALGIA_QUIET_START_HOUR) or 0)
        end = int(self._limit("quiet_end_hour",
                              settings.NOSTALGIA_QUIET_END_HOUR) or 0)
        hour = _local_hour(now, self._tz_name)
        return hour >= start or hour < end

    async def _last_sent_ts(self, chat_id: int) -> int | None:
        """ts последнего status='sent' чата (cooldown/пауза Q14)."""
        rows = await self.db.recent_nostalgia_sent(chat_id, None, 1)
        return int(rows[0]["ts"]) if rows else None

    async def _unanswered_stop(self, chat_id: int, now: int) -> bool:
        """Q14 (§3.5.3 п.6, фикс-раунд major/D-17): последние sent чата за
        окно = memory.nostalgia_pause_hours (24 ч) — если подряд
        nostalgia_unanswered_max из них НЕ отвечены (нет юзерских сообщений
        после ts отправки), стоп. Пауза неявная: пока не пройдёт окно
        pause_hours ИЛИ юзер не ответит, условие повторяется на следующих
        тиках (отправки не будет)."""
        pause = int(self._limit("pause_hours",
                                settings.NOSTALGIA_PAUSE_HOURS) or 0)
        window_hours = pause if pause > 0 else _FALLBACK_WINDOW_HOURS
        window = now - window_hours * 3600
        unanswered_max = int(self._limit(
            "unanswered_max", settings.NOSTALGIA_UNANSWERED_MAX) or 0)
        if unanswered_max <= 0:
            return False
        rows = await self.db.recent_nostalgia_sent(
            chat_id, window, unanswered_max + 1)
        consecutive = 0
        for row in rows:
            if await self.db.count_user_messages_after(
                    chat_id, self.bot_id, int(row["ts"])) > 0:
                break                       # эта и более старые отвечены
            consecutive += 1
            if consecutive >= unanswered_max:
                return True
        return False

    # ── кандидаты → порог → LLM → отправка ─────────────────────────

    async def _candidate_llm_send(self, chat_id: int, now: int,
                                  out: dict) -> None:
        """Дорогой шаг тика (§3.5.2–3.5.4): кандидат, порог агрессивности,
        1 облачный LLM-вызов, отправка. Все исходы — строка в nostalgia_log
        (status sent/skipped/error). Никогда не бросает (fail-open)."""
        candidate = await self._pick_candidate(chat_id, now)
        if candidate is None:
            await self._log(chat_id, now, _KIND_NONE, None, _STATUS_SKIPPED,
                            {"reason": "no_candidates"})
            logger.info("[nostalgia] skip | chat=%s | reason=no_candidates",
                        chat_id)
            return
        out["candidates"] += 1
        threshold = self._threshold()
        if candidate["weight"] < threshold:
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {"reason": "threshold",
                             "weight": round(candidate["weight"], 3),
                             "threshold": round(threshold, 3),
                             "candidate_text": candidate["text"]})
            logger.info(
                "[nostalgia] skip | chat=%s | reason=threshold "
                "(weight=%.2f < %.2f)", chat_id, candidate["weight"],
                threshold)
            return
        # Раунд 10 (F-10 §5): consume до LLM-вызова генерации (global +
        # chat:<id>); False → nostalgia_log status='budget_skip'.
        if not await self._nostalgia_budget_ok(chat_id, candidate["text"]):
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), "budget_skip",
                            {"reason": "budget"})
            out["skipped"] += 1
            logger.warning(
                "[nostalgia] WARNING skip: budget nostalgia | chat=%s",
                chat_id)
            return
        raw = await self._llm_once(candidate)
        if raw is None:
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_ERROR,
                            {"reason": "llm_error"})
            out["errors"] += 1
            return
        text = str(raw or "").strip()
        if is_unchanged_response(text):
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {"reason": "unchanged", "llm_skipped": True,
                             "candidate_text": candidate["text"]})
            out["skipped"] += 1
            logger.info(
                "[nostalgia] LLM UNCHANGED — skip | chat=%s | kind=%s",
                chat_id, candidate["kind"])
            return
        text = clean_llm_text(text, int(self._limit(
            "max_send_chars", settings.NOSTALGIA_MAX_SEND_CHARS) or 400))
        if not text:
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {"reason": "empty", "llm_skipped": True,
                             "candidate_text": candidate["text"]})
            out["skipped"] += 1
            logger.info("[nostalgia] empty LLM text — skip | chat=%s",
                        chat_id)
            return
        meta = {"reason": "sent", "candidate": candidate["kind"],
                "candidate_text": candidate["text"]}
        try:
            if self.bot is None:
                raise RuntimeError("nostalgia: bot instance missing (Q13)")
            await self.bot.send_message(chat_id, text)
        except Exception as exc:
            logger.warning(
                "[nostalgia] send failed — error logged | chat=%s | error=%s",
                chat_id, exc)
            await self._log(
                chat_id, now, candidate["kind"], candidate.get("fact_id"),
                _STATUS_ERROR,
                {"reason": "bot_api", "candidate": candidate["kind"],
                 "candidate_text": candidate["text"]})
            out["errors"] += 1
            return
        await self._log(chat_id, now, candidate["kind"],
                        candidate.get("fact_id"), _STATUS_SENT, meta)
        out["sent"] += 1
        logger.info(
            "[nostalgia] sent | chat=%s | kind=%s | chars=%d",
            chat_id, candidate["kind"], len(text))

    @staticmethod
    async def _nostalgia_budget_ok(chat_id: int, text: str) -> bool:
        """F-10 §5: consume global + chat:<id> (calls 1 + tokens est).
        ФИКС R4: приоритетная деградация по global-лимиту (nostalgia падает
        последней — allowed_workers) до consume."""
        from services import worker_budget
        if not await worker_budget.global_degradation_allows("nostalgia"):
            logger.warning(
                "[nostalgia] skip: global budget exhausted — degradation "
                "nostalgia | chat=%s", chat_id)
            return False
        est = worker_budget.estimate_tokens(text)
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

    def _threshold(self) -> float:
        """Порог срабатывания (§3.5.2): 0.3 + aggressiveness*0.5
        (aggressiveness зажат в [0, 1]; дефолт 0.3 → порог 0.45)."""
        aggr = max(0.0, min(1.0, float(self._key(
            "aggressiveness", settings.NOSTALGIA_AGGRESSIVENESS) or 0.3)))
        return 0.3 + aggr * 0.5

    async def _pick_candidate(self, chat_id: int, now: int) -> dict | None:
        """Лучший кандидат чата (§3.5.2): максимум веса из набора «год назад»
        (вес 0.7, если строки в окне ± window есть) и «золотых» по последней
        теме (вес факта 0.3 + 0.05*importance). Равенство → «год назад»
        (повод «ровно в этот день»; в user-блок LLM попадают ОБА набора —
        память полнее). None — кандидатов нет."""
        year_lines = await self._year_back_lines(chat_id, now)
        golden = await self._golden_rows(chat_id)
        best: dict | None = None
        if year_lines:
            best = {"kind": "year_back", "fact_id": None,
                    "weight": _YEAR_BACK_WEIGHT,
                    "text": year_lines[0]}
        for row in golden:
            weight = 0.3 + 0.05 * max(1, int(row.get("importance") or 0))
            if best is None or weight > best["weight"]:
                best = {"kind": "golden",
                        "fact_id": int(row["id"]),
                        "weight": weight,
                        "text": format_golden_line(row)}
        if best is None:
            return None
        best["year_lines"] = year_lines
        best["golden_lines"] = [format_golden_line(r) for r in golden]
        return best

    async def _year_back_lines(self, chat_id: int, now: int) -> list[str]:
        """Строки «N лет назад в этот день» (§3.5.2): smart_messages чата с
        timestamp в [now−365д ± nostalgia_year_back_days_window], непустой
        текст, ближайшие к точной дате, ≤3. Рендер «[Имя ГГГГ-ММ-ДД]: текст»
        (format_year_back_line). Пусто — набора нет."""
        window_days = int(self._limit(
            "year_back_days_window",
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW) or 0) or 2
        center = now - _YEAR_SECONDS
        rows = await self.db.get_year_back_messages(
            chat_id, center - window_days * 86400,
            center + window_days * 86400, center, _MAX_YEAR_BACK_LINES)
        return [l for l in (format_year_back_line(r) for r in rows) if l]

    async def _golden_rows(self, chat_id: int) -> list:
        """«Золотые» по последней теме (§3.5.2): ключи (слова len≥5) последних
        5 юзерских сообщений → memory.fetch_golden_facts (importance ≥ порога,
        давность ≥ порога; ≤2 факта). memory отсутствует → [] (слабый слой —
        «год назад» достаточно)."""
        if self.memory is None:
            logger.info(
                "[nostalgia] memory недоступен — golden candidates пусты | "
                "chat_id=%s", chat_id)
            return []
        rows = await self.db.get_recent_user_messages(
            chat_id, self.bot_id, _TOPIC_MESSAGES)
        words: list[str] = []
        for row in reversed(rows):               # ASC: старое → свежее
            words.extend(_TOPIC_WORD_RE.findall(
                str(row["text"] or "").lower()))
        seen: set[str] = set()
        keywords = [w for w in words if not (w in seen or seen.add(w))] \
            [:_TOPIC_KEYWORDS_CAP]
        if not keywords:
            return []
        return await self.memory.fetch_golden_facts(
            chat_id, " ".join(keywords),
            min_importance=int(self._limit(
                "golden_min_importance",
                settings.NOSTALGIA_GOLDEN_MIN_IMPORTANCE) or 0),
            min_age_days=int(self._limit(
                "golden_min_days", settings.NOSTALGIA_GOLDEN_MIN_DAYS) or 0),
            limit=_GOLDEN_FACT_LIMIT)

    async def _worker_llm(self, messages: list[dict],
                          temperature: float | None = None) -> str:
        """F3/T-1439 (spec §5, рекомендовано): выделенная LLM роли
        background с фоллбэком на `generate` (моки/старые клиенты)."""
        worker_fn = getattr(self.llm, "generate_worker", None)
        if callable(worker_fn):
            return await worker_fn("background", messages,
                                   temperature=temperature)
        return await self.llm.generate(messages, temperature=temperature)

    async def _llm_once(self, candidate: dict) -> str | None:
        """1 облачный LLM-вызов (NFR-1: только LLMClient-путь бота;
        локальная LLM запрещена — лимит владельца). Возвращает текст ответа
        или None (ошибка/llm отсутствует — fail-open)."""
        if self.llm is None:
            logger.warning("[nostalgia] llm отсутствует — нечего вызвать")
            return None
        user_text = build_nostalgia_user(candidate.get("year_lines") or [],
                                         candidate.get("golden_lines") or [])
        if not user_text:
            return None
        try:
            raw = await self._worker_llm([
                {"role": "system",
                 "content": NOSTALGIA_PROMPT.format(max_words=_MAX_WORDS)},
                {"role": "user", "content": user_text},
            ], temperature=0.7)
        except Exception as exc:
            logger.warning(
                "[nostalgia] LLM call failed — error | error=%s", exc)
            return None
        return str(raw or "")

    async def _log(self, chat_id: int, ts: int, kind: str,
                   fact_id: int | None, status: str, meta: dict) -> None:
        """Строка nostalgia_log (fail-open: сбой лога — WARNING, тик жив)."""
        try:
            await self.db.log_nostalgia(
                chat_id, int(ts), kind=kind, fact_id=fact_id,
                status=status,
                meta=json.dumps(meta, ensure_ascii=False, default=str))
        except Exception:
            logger.warning(
                "[nostalgia] log failed — fail-open | chat_id=%s",
                chat_id, exc_info=True)
