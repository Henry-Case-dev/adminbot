"""Раунд 7 (chat-lore-management-v2, T-775/T-776, C1/C2) — авто-лор воркер.

`LoreWorker(store, cache, db, llm, bot_id=None, ...)` — генерация авто-лора
чата из окна SQLite `smart_messages` (SQLite-ЧТЕНИЕ, RUNTIME WARNING: только
чтение; сигнатуры services/database.py не меняются — прямые `db.db.execute`).

Поток генерации (`generate_for_chat`, spec §3.5):
  1. профиль (резолв chat_id внутри store): нет/не активен → skip;
  2. `auto_enabled=false` (профиль) → строгий skip `auto_disabled` — токены
     НЕ тратим (тумблер; manual тоже отсекается — на API это 409);
  3. авто-тик дополнительно: `flags.lore_auto_enabled`; период
     (`last_auto_at` + auto_period_hours ≤ now; NULL = можно); cooldown
     (in-memory, manual игнорирует);
  4. pg_advisory-lock на ОТДЕЛЬНОМ соединении на время прогона (не из пула —
     LLM-вызов занимает минуты): `pg_try_advisory_lock(chat_id)`; занят →
     skip `locked`; unlock+close в finally;
  5. окно: `COUNT(*)` «осмысленных» (spec §3.5/Q5: text непуст после trim,
     длина ≥ limits.lore_min_message_chars, не начинается с '/',
     user_id != bot_id; импортированные user_id NULL — считаются) →
     < limits.lore_min_messages → skip `quiet_window` БЕЗ last_auto_at
     (тихие дни не сдвигают период; следующий тик сделает дешёвый COUNT);
     выборка строк DESC LIMIT lore_window_max_messages → ASC;
  6. merge-контекст (канон §3.6): auto_lore пуст → INIT-промпт, иначе MERGE;
     окно форматируется `[YYYY-MM-DD HH:MM] автор: текст`, бюджет
     lore_window_max_chars (свежий конец сохраняется); чат-уровневые
     protected-факты (`user_name IS NULL`) БЕЗ legacy-константы
     CHAT_LORE_2661910336 (она же в manual PG-профиля после сида);
  7. LLM-вызов: `llm.generate([system, user])` — temperature None, таймауты/
     ретраи/фолбэк внутри llm_client (Q4); `limits.lore_max_words` —
     в текст промпта;
  8. запись: ответ == "UNCHANGED" (после strip, регистронезависимо) →
     `mark_auto_done` (метка периода без истории); пустой ответ/LLM-ошибка →
     WARNING + `{"status":"error"}` (профиль не тронут); иначе нормализация
     (normalize_lore) → изменился → `store.set_auto` (история field='auto',
     changed_by NULL, NOTIFY); идентичен текущему → `mark_auto_done`.

Цикл (C2): `start()`/`stop()` — AsyncIOScheduler (tz как memory_maintenance),
`IntervalTrigger(minutes=limits.lore_tick_minutes, max_instances=1,
coalesce=True)`; джоб регистрируется и планировщик стартует ТОЛЬКО при
`hot.get("flags.lore_worker_enabled", settings.LORE_WORKER_ENABLED)`. Тик —
`list_active_chats()` → последовательные `generate_for_chat` (per-chat try:
ошибка чата не роняет тик; fail-open WARNING).
"""
import asyncio
import inspect
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from services import hot_config as hot
from services.chat_lore import CHAT_LORE_2661910336
from services.dossier_prompts import (
    DOSSIER_SYSTEM_PROMPT,
    LAYER_A_SYSTEM_PROMPT,
    LAYER_B_SYSTEM_PROMPT,
    build_dossier_user,
    build_layer_a_user,
    build_layer_b_user,
    filter_layer_a_candidates,
    parse_dossier_answer,
    parse_layer_a,
    parse_layer_b,
    validate_layer_b,
)
from services.llm_client import LLMError


def _jitter(base_minutes: int) -> int:
    """Случайный сдвиг тика от limits.worker_budget_jitter_minutes
    (капнуто ≤ interval/3 — worker_budget.jitter_safe); 0 — если jitter
    явно не задан (тесты/конфиг без ключа)."""
    try:
        from services import worker_budget
        if not worker_budget.jitter_active():
            return 0
        return random.randint(0, worker_budget.jitter_safe(base_minutes))
    except Exception:
        return 0


async def _budget_ok(chat_id: int, tokens_estimate: int,
                     worker_id: str = "lore", calls: int = 1) -> bool:
    """F-10 §5: consume global (calls + tokens) и chat:<id>; любое False →
    скип. Fail-open сам consume (PG down → True). ФИКС R4: приоритетная
    деградация по global-лимиту (allowed_workers) до consume.

    F1 (multilayer): `calls` — число LLM-вызовов в прогнозе (двухслойный
    пайплайн передаёт 2: Слой А + Слой Б); дефолт 1 сохраняет путь 10.20
    байт-совместимым."""
    from services import worker_budget
    if not await worker_budget.global_degradation_allows(worker_id):
        logger.warning(
            "[lore_worker] skip: global budget exhausted — degradation %s | "
            "chat=%s", worker_id, chat_id)
        return False
    n_calls = max(1, int(calls))
    ok = await worker_budget.consume(None, "global", "llm_calls", n_calls)
    if ok:
        ok = await worker_budget.consume(None, "global", "llm_tokens",
                                         tokens_estimate)
    if ok:
        ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                         "llm_calls", n_calls)
    if ok:
        ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                         "llm_tokens", tokens_estimate)
    return ok


async def _budget_extra_calls(chat_id: int, calls: int = 1) -> bool:
    """F1 fix-round 10.21: добрать ФАКТИЧЕСКИЙ расход LLM-вызовов на
    retry/fallback сверх прогноза A+B (spec §3.2/§8.6). Учитываются только
    `llm_calls` (токены уже покрыты прогнозом); fail-open — не блокирует
    прогон, лишь фиксирует расход."""
    from services import worker_budget
    n = max(1, int(calls))
    ok = await worker_budget.consume(None, "global", "llm_calls", n)
    if ok:
        ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                         "llm_calls", n)
    return ok
from services.lore_prompts import (
    LORE_INIT_SYSTEM_PROMPT,
    LORE_MERGE_SYSTEM_PROMPT,
    build_init_user,
    build_merge_user,
    is_unchanged_response,
    normalize_lore,
)

logger = logging.getLogger(__name__)

_WINDOW_TS_FORMAT = "%Y-%m-%d %H:%M"

# Фильтр «осмысленности» (spec §3.5/Q5). `?`-плейсхолдеры (aiosqlite):
#   1 — chat_id, 2 — since_ts, 3 — min_message_chars, 4 — bot_id-исключение.
_MEANINGFUL_FILTER = (
    "text IS NOT NULL AND length(trim(text)) >= ? "
    "AND substr(trim(text), 1, 1) <> '/' "
    "AND (user_id IS NULL OR user_id <> ?)"
)
_COUNT_WINDOW_SQL = (
    "SELECT COUNT(*) FROM smart_messages "
    "WHERE chat_id = ? AND timestamp >= ? AND " + _MEANINGFUL_FILTER
)
_WINDOW_SQL = (
    "SELECT user_id, author_name, text, timestamp FROM smart_messages "
    "WHERE chat_id = ? AND timestamp >= ? AND " + _MEANINGFUL_FILTER + " "
    "ORDER BY timestamp DESC, id DESC LIMIT ?"
)
# Чат-уровневые protected-факты (user_name IS NULL) БЕЗ legacy-константы:
# текст константы продублирован в manual PG-профиля (сид) — в контекст
# воркера он не нужен (spec §3.5).
_FACTS_SQL = (
    "SELECT fact FROM protected_facts "
    "WHERE chat_id = ? AND user_name IS NULL AND fact <> ? "
    "ORDER BY created_at ASC, id ASC"
)

_JOB_ID = "lore_worker_tick"
_NEVER_USER_ID = -1  # bot_id=None → фильтр «не бот» не накладывается


def _due_at(iso: str | None, period_hours: int, now_utc: datetime) -> bool:
    """True — период прошёл (last_auto_at пуст ИЛИ + period ≤ now)."""
    if not iso:
        return True
    try:
        parsed = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return True                     # мусорная метка — не блокируем прогон
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed + timedelta(hours=max(0, int(period_hours))) <= now_utc


def _line_ts(ts) -> str:
    """Unix-timestamp строки smart_messages → [%Y-%m-%d %H:%M]."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
            _WINDOW_TS_FORMAT)
    except (TypeError, ValueError, OSError):
        return "?"


def _row_get(row, name: str, index: int):
    """aiosqlite.Row/dict (по имени) либо tuple (по позиции) — единый доступ."""
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        pass
    try:
        return row[index]
    except (IndexError, TypeError):
        return None


def _cancel_requested(cancel_cb) -> bool:
    """F8: кооперативная отмена между чанками/стадиями (fail-open — ошибка
    колбэка НЕ считается отменой)."""
    if cancel_cb is None:
        return False
    try:
        return bool(cancel_cb())
    except Exception:
        return False


async def _emit_progress(progress_cb, processed, total, stage) -> None:
    """F8: fail-open вызов `progress_cb` (sync/async) — прогресс не роняет
    пересборку."""
    if progress_cb is None:
        return
    try:
        result = progress_cb(processed, total, stage)
        if inspect.isawaitable(result):
            await result
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug("[lore_worker] progress callback failed (fail-open)")


class LoreWorker:
    """Фоновый генератор авто-лора чатов (spec §3.5, Q3/Q4/Q5)."""

    def __init__(self, store, cache=None, db=None, llm=None,
                 bot_id: int | None = None, *, pg=None,
                 lock_connector=None, lock_dsn: str | None = None,
                 scheduler=None, aliases=None):
        self._store = store
        self._cache = cache                       # опционально (интерфейс B4)
        self._db = db
        self._llm = llm
        self.bot_id = bot_id
        self._aliases = aliases                   # F8: канонизация target (canon_name)
        self._pg = pg if pg is not None else getattr(store, "pg", None)
        self._lock_dsn = lock_dsn
        self._lock_connector = lock_connector or self._default_lock_connector
        # Q4: in-memory cooldown (mono-время последнего ЗАВЕРШЁННОГО прогона);
        # сбрасывается рестартом процесса. Manual его игнорирует.
        self._completed: dict[int, float] = {}
        self._scheduler = scheduler
        self._owns_scheduler = scheduler is None
        self._warn_lock_mono = 0.0

    # ── lifecycle (C2) ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Регистрация тик-джоба и старт планировщика — ТОЛЬКО при
        flags.lore_worker_enabled (иначе тик-джоб не зарегистрирован, AC-2)."""
        if not hot.get("flags.lore_worker_enabled",
                       settings.LORE_WORKER_ENABLED):
            logger.info("LoreWorker disabled (flags.lore_worker_enabled=False)")
            return
        if self._scheduler is None:
            tz = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
            self._scheduler = AsyncIOScheduler(timezone=tz)
        # Раунд 10 (F-10 §5.2): jitter тика — случайный сдвиг ≤ interval/3
        # (риск 10.4: шире интервала → частота падает вдвое).
        base_minutes = int(hot.get("limits.lore_tick_minutes",
                                   settings.LORE_TICK_MINUTES) or 30)
        tick_minutes = base_minutes + _jitter(base_minutes)
        self._scheduler.add_job(
            self.tick,
            IntervalTrigger(
                minutes=tick_minutes,
                timezone=hot.get("limits.summary_timezone",
                                 settings.SUMMARY_TIMEZONE)),
            id=_JOB_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        self._scheduler.start()
        logger.info(
            "LoreWorker started | tick_minutes=%s | chats=auto loop",
            hot.get("limits.lore_tick_minutes", settings.LORE_TICK_MINUTES))

    async def stop(self) -> None:
        """Остановка планировщика (идемпотентно)."""
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler is None or not getattr(scheduler, "running", False):
            logger.info("LoreWorker was not running — nothing to stop")
            return
        try:
            scheduler.shutdown(wait=False)
            await asyncio.sleep(0)
            logger.info("LoreWorker stopped")
        except SchedulerNotRunningError:
            logger.info("LoreWorker was not running — nothing to stop")

    # ── тик (C2) ───────────────────────────────────────────────────────────

    async def tick(self) -> None:
        """Обход активных чатов: последовательные generate_for_chat; ошибка
        одного чата не роняет тик (fail-open WARNING)."""
        try:
            chats = await self._store.list_active_chats()
        except Exception:
            logger.warning(
                "[lore_worker] tick: list_active_chats failed (PG down?) — "
                "следующий тик", exc_info=True)
            return
        for chat_id in chats:
            try:
                result = await self.generate_for_chat(chat_id)
                if result.get("status") == "ok":
                    logger.info(
                        "[lore_worker] auto | chat=%s | changed=%s",
                        chat_id, result.get("changed"))
                else:
                    logger.info(
                        "[lore_worker] auto | chat=%s | %s/%s",
                        chat_id, result.get("status"), result.get("reason"))
            except Exception:
                logger.warning(
                    "[lore_worker] tick: chat=%s failed (fail-open)",
                    chat_id, exc_info=True)

    # ── прогон чата (spec §3.5) ────────────────────────────────────────────

    async def generate_for_chat(self, chat_id: int, *,
                                manual: bool = False) -> dict:
        """Полный прогон генерации/обновления авто-лора чата.

        Возврат:
          {"status": "ok", "changed": bool} — запись (set_auto) либо
              UNCHANGED/идентичный текст (mark_auto_done);
          {"status": "skipped", "reason": ...} — no_profile / inactive /
              auto_disabled / auto_flag_disabled / period_not_due / cooldown /
              quiet_window / locked;
          {"status": "error", "reason": ...} — LLM-ошибка/пустой ответ
              (профиль не тронут);
          {"status": "failed"} — непредвиденное исключение
              (в т.ч. PG недоступен на шаге lock/чтений).
        """
        try:
            profile = await self._store.get_profile(chat_id)
        except Exception:
            logger.warning(
                "[lore_worker] get_profile failed | chat=%s (fail-open)",
                chat_id, exc_info=True)
            return {"status": "failed"}
        if profile is None:
            return {"status": "skipped", "reason": "no_profile"}
        if not profile.is_active:
            return {"status": "skipped", "reason": "inactive"}
        if not profile.auto_enabled:
            # строгий скип (тумблер): авто-тик токены не тратит; «Сгенерировать
            # сейчас» при выключенном отсекается на API (409 auto_disabled)
            return {"status": "skipped", "reason": "auto_disabled"}
        # ФИКС R5 (F-10 §6): гейты (глобальный флаг + chat-gate lore_auto)
        # применяются и к РУЧНОМУ запуску «Сгенерировать сейчас» — kill-switch
        # стопит и ручные прогоны (спецификация БЕЗ carve-out).
        if not hot.get("flags.lore_auto_enabled",
                       settings.LORE_AUTO_ENABLED):
            return {"status": "skipped", "reason": "auto_flag_disabled"}
        # Раунд 10 (F-10 §6): префильтр тяжёлого гейта lore_auto
        # (kill-switch override: gates[feature] → глобальный флаг →
        # False); WARNING skip без записи истории.
        try:
            from services.feature_gates import gates_enabled
            if not await gates_enabled(chat_id, "lore_auto"):
                logger.info(
                    "[lore_worker] skip | chat=%s | reason=gate_lore_auto "
                    "(WARNING skip: gate lore_auto)", chat_id)
                return {"status": "skipped", "reason": "gate_lore_auto"}
        except Exception:
            logger.warning(
                "[lore_worker] gate check failed — fail-open | chat=%s",
                chat_id, exc_info=True)
        if not manual:
            if not _due_at(profile.last_auto_at, profile.auto_period_hours,
                           datetime.now(timezone.utc)):
                return {"status": "skipped", "reason": "period_not_due"}
            cooldown = hot.get("limits.lore_generate_cooldown",
                               settings.LORE_GENERATE_COOLDOWN)
            done_mono = self._completed.get(chat_id)
            if done_mono is not None and \
                    time.monotonic() - done_mono < float(cooldown or 0):
                return {"status": "skipped", "reason": "cooldown"}
        # manual: период/cooldown не проверяются (Q4), auto_enabled/гейты —
        # обязательны всегда (R5).

        # Прогон — по АКТУАЛЬНОМУ id (резолв chat_links уже внутри
        # store.get_profile; spec §3.5: окно/запись/лок — по resolved):
        # у «переехавшего» чата SQLite-окно и PG-записи живут под новым id.
        run_chat_id = int(profile.chat_id)
        result = await self._run_locked(run_chat_id, profile, manual=manual)
        self._completed[chat_id] = time.monotonic()
        return result

    # ── advisory-lock + прогон под локом ──────────────────────────────────

    async def _run_locked(self, chat_id: int, profile, *,
                          manual: bool) -> dict:
        """Прогон на ОТДЕЛЬНОМ соединении под pg_advisory_lock(chat_id).
        Lock не взят → skip locked (идёт другой прогон); unlock+close в
        finally (даже при исключениях). Сбой соединения → {"status":
        "failed"} (fail-open, профиль не тронут)."""
        conn = None
        try:
            conn = await self._lock_connector()
            locked = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)", int(chat_id))
            if not locked:
                if self._warn_lock(chat_id):
                    logger.warning(
                        "[lore_worker] advisory lock занят (другой прогон "
                        "идёт) | chat=%s", chat_id)
                return {"status": "skipped", "reason": "locked"}
            return await self._run_generation(chat_id, profile)
        except asyncio.CancelledError:
            raise
        except LLMError as exc:
            logger.warning(
                "[lore_worker] LLM failed | chat=%s | error=%s (профиль не "
                "тронут)", chat_id, exc)
            return {"status": "error", "reason": "llm_error"}
        except Exception:
            logger.warning(
                "[lore_worker] lock/unlock failed — fail-open | chat=%s",
                chat_id, exc_info=True)
            return {"status": "failed"}
        finally:
            if conn is not None:
                try:
                    await conn.execute(
                        "SELECT pg_advisory_unlock($1)", int(chat_id))
                except Exception:
                    logger.debug("[lore_worker] unlock failed | chat=%s",
                                 chat_id, exc_info=True)
                try:
                    await conn.close()
                except Exception:
                    pass

    def _warn_lock(self, chat_id: int) -> bool:
        """Дедуп WARNING «lock занят»: раз в 60 секунд (не спамить)."""
        now = time.monotonic()
        if now - self._warn_lock_mono >= 60.0:
            self._warn_lock_mono = now
            return True
        return False

    async def _default_lock_connector(self):
        """Прямое asyncpg-соединение по DSN (кодеки json — как у пула)."""
        import asyncpg
        from services import pg_db as pg_db_module
        dsn = (self._lock_dsn
               or (getattr(self._pg, "dsn", None) if self._pg else None)
               or os.getenv("POSTGRES_DSN"))
        if not dsn:
            raise RuntimeError("POSTGRES_DSN пуст — advisory lock невозможен")
        # init= у asyncpg есть только у create_pool; кодеки применяем вручную.
        conn = await asyncpg.connect(dsn)
        await pg_db_module._init_connection(conn)
        return conn

    # ── окно + merge-контекст + LLM + запись ──────────────────────────────

    async def _run_generation(self, chat_id: int, profile) -> dict:
        """Окно smart_messages (SQLite-ЧТЕНИЕ), сборка контекста по канону
        §3.6, LLM-вызов и запись результата."""
        window_hours = max(1, int(profile.auto_window_hours or 24))
        min_chars = hot.get("limits.lore_min_message_chars",
                            settings.LORE_MIN_MESSAGE_CHARS)
        bot_exclude = int(self.bot_id) if self.bot_id else _NEVER_USER_ID
        since_ts = int(time.time()) - window_hours * 3600
        db = self._db

        cursor = await db.db.execute(
            _COUNT_WINDOW_SQL,
            (chat_id, since_ts, int(min_chars), bot_exclude))
        row = await cursor.fetchone()
        count = int(row[0]) if row is not None else 0
        min_messages = hot.get("limits.lore_min_messages",
                               settings.LORE_MIN_MESSAGES)
        if count < int(min_messages):
            # порог не набран — skip БЕЗ last_auto_at (тихие дни не сдвигают
            # период; каждый тик — дешёвый COUNT, LLM не тратим)
            return {"status": "skipped", "reason": "quiet_window"}

        cursor = await db.db.execute(
            _WINDOW_SQL,
            (chat_id, since_ts, int(min_chars), bot_exclude,
             int(hot.get("limits.lore_window_max_messages",
                         settings.LORE_WINDOW_MAX_MESSAGES))))
        rows = await cursor.fetchall()
        lines = self._format_window(rows)
        if not lines:
            return {"status": "skipped", "reason": "quiet_window"}

        facts = await self._chat_facts(chat_id)
        max_words = int(hot.get("limits.lore_max_words",
                                settings.LORE_MAX_WORDS) or 150)
        auto_lore = profile.auto_lore or ""
        if auto_lore:
            system = LORE_MERGE_SYSTEM_PROMPT.format(max_words=max_words)
            user = build_merge_user(
                auto_lore, lines, window_hours=window_hours, facts=facts)
        else:
            system = LORE_INIT_SYSTEM_PROMPT.format(max_words=max_words)
            user = build_init_user(lines, window_hours=window_hours,
                                   facts=facts)
        # Раунд 10 (F-10 §5): суточный бюджет фона — consume ДО LLM-вызова
        # (global + chat:<id>); False → skip, история НЕ пишется (WARNING).
        from services import worker_budget
        if not await _budget_ok(chat_id,
                                worker_budget.estimate_tokens(user)):
            logger.warning(
                "[lore_worker] WARNING skip: budget lore_auto | chat=%s",
                chat_id)
            return {"status": "skipped", "reason": "budget_skip"}
        # F3/T-1439 (spec §5): синтез лора — выделенная LLM роли history
        # (пустые ключи/ошибка dedicated → роутер сам фоллбэчит на основную;
        # моки/старые клиенты без generate_worker → прямой generate).
        raw = await self._worker_llm("history", [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        result = await self._apply_result(chat_id, raw, old_auto=auto_lore)
        # F8 (spec §5): иронический фильтр — классификация досье best-effort
        # ПОСЛЕ записи лора (флаг OFF → мгновенный skip, поведение 10.12).
        await self._classify_dossier_safe(chat_id, lines, rows)
        return result

    # ── F8 (cognition-irony-dossier-round1013, spec §5): досье/ирония ──────

    async def _classify_dossier_safe(self, chat_id: int, window: list[str],
                                     rows) -> None:
        """best-effort обёртка классификации (fail-open: ошибка одного шага
        не роняет прогон лора, R16/R17: в логи только chat_id).

        F1 fix-round 2: двухслойный пайплайн (default ON) НЕ гейтится
        историческим `flags.irony_filter_enabled` — он управляется только
        аварийным kill-switch `MULTILAYER_EXTRACTION_ENABLED`. Irony-флаг
        остаётся отдельной функцией и гейтит лишь legacy-путь 10.20
        (kill-switch OFF), его историческое поведение не меняется."""
        try:
            multilayer = bool(getattr(
                settings, "MULTILAYER_EXTRACTION_ENABLED", True))
            if not multilayer and not hot.get(
                    "flags.irony_filter_enabled",
                    settings.IRONY_FILTER_ENABLED):
                return
            names = self._window_names(rows)
            await self._classify_dossier(chat_id, window, names)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[lore_worker] dossier classification failed — fail-open | "
                "chat=%s", chat_id, exc_info=True)

    def _canon(self, name: str) -> str:
        """F8/R16: имя → канон-алиас (aliases.canon_name); нет резолвера —
        имя как есть. Не бросает."""
        text = str(name or "").strip()
        if self._aliases is None:
            return text
        try:
            return str(self._aliases.canon_name(text) or "").strip() or text
        except Exception:
            return text

    def _window_names(self, rows) -> list[str]:
        """Уникальные канон-имена авторов окна (без пустых), порядок окна."""
        names: list[str] = []
        seen: set[str] = set()
        for r in rows:
            author = str(_row_get(r, "author_name", 1) or "").strip()
            if not author:
                continue
            canon = self._canon(author)
            key = canon.casefold()
            if canon and key not in seen:
                seen.add(key)
                names.append(canon)
        return names

    async def _classify_dossier(self, chat_id: int, window: list[str],
                                names: list[str]) -> int:
        """F1/F8: классификация окна досье.

        UPD Human Gate (ADR-1021-1): по умолчанию — двухслойный пайплайн
        Слой А (Thinker) → Python-фильтр → Слой Б (Synthesizer). Только
        аварийный env-only kill-switch `MULTILAYER_EXTRACTION_ENABLED=False`
        возвращает ровно путь 10.20 (байт-совместимость).

        F5: возвращает число записанных `chat_memes` (0 при скипе/ошибке) —
        вызывающий (`rebuild_dossier_for_chat`) кладёт его в отчёт CLI."""
        if bool(getattr(settings, "MULTILAYER_EXTRACTION_ENABLED", True)):
            return await self._classify_dossier_multilayer(chat_id, window,
                                                           names)
        return await self._classify_dossier_legacy(chat_id, window, names)

    async def _classify_dossier_legacy(self, chat_id: int, window: list[str],
                                       names: list[str]) -> int:
        """Путь 10.20 (single-pass), БАЙТ-совместимое поведение F8: один
        LLM-вызов + 1 retry на кривом JSON; запись ТОЛЬКО `chat_memes` как
        `graph_facts.status='chat_meme'` (нулевой DDL), `real_facts` не
        дублируем. Идемпотентность — db.meme_exists."""
        messages = [
            {"role": "system", "content": DOSSIER_SYSTEM_PROMPT},
            {"role": "user", "content": build_dossier_user(window, names)},
        ]
        raw = await self._dossier_llm(messages)
        try:
            items = parse_dossier_answer(raw, canon=self._canon)
        except ValueError:
            logger.info(
                "[lore_worker] dossier answer invalid — 1 retry | chat=%s",
                chat_id)
            # F1 fix-round 2: retry запасного пути — фактический consume
            # (сверх прогноза A+B/fallback), чтобы бюджет не занижался.
            await _budget_extra_calls(chat_id)
            raw = await self._dossier_llm(messages)
            try:
                items = parse_dossier_answer(raw, canon=self._canon)
            except ValueError:
                logger.warning(
                    "[lore_worker] dossier classification skipped (invalid "
                    "JSON after retry) | chat=%s", chat_id)
                return 0
        return await self._write_chat_memes(
            chat_id, items.get("chat_memes") or [])

    async def _classify_dossier_multilayer(self, chat_id: int,
                                           window: list[str],
                                           names: list[str]) -> int:
        """F1 (ADR-1021-1): Слой А (scratchpad) → Python-фильтр → Слой Б.

        Стоимость ×2: единый прогноз A+B через `_budget_ok` (2 вызова).
        Fallback: Слой А невалиден после 1 retry → WARNING + путь 10.20
        (single-pass), память не теряем. Слой Б упал → сохраняем `chat_memes`
        Слоя А (портрет не пишем). R17: логи — только chat_id/counts/kind/
        длины, без текстов сообщений."""
        layer_a_user = build_layer_a_user(window, names)
        layer_a_messages = [
            {"role": "system", "content": LAYER_A_SYSTEM_PROMPT},
            {"role": "user", "content": layer_a_user},
        ]
        from services import worker_budget
        # Прогноз A+B: 2 вызова; токены — по входу A (Слой Б работает над
        # его отфильтрованным подмножеством и шире окна не будет).
        # F1 fix-round 10.21: retry (до +2) и fallback 10.20 (3-й вызов)
        # добираются ФАКТИЧЕСКИ через `_budget_extra_calls` на месте.
        if not await _budget_ok(chat_id,
                                worker_budget.estimate_tokens(layer_a_user),
                                calls=2):
            logger.warning(
                "[lore_worker] WARNING skip: budget dossier (multilayer) | "
                "chat=%s", chat_id)
            return 0
        try:
            parsed_a = await self._layer_a_call(chat_id, layer_a_messages)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[lore_worker] layer A invalid after retry — fallback 10.20 | "
                "chat=%s", chat_id)
            # +1 фактический вызов запасного одиночного пути (10.20).
            await _budget_extra_calls(chat_id)
            return await self._classify_dossier_legacy(chat_id, window, names)
        filtered = filter_layer_a_candidates(parsed_a, names,
                                             canon=self._canon)
        person_facts = filtered["person_facts"]
        memes_a = filtered["memes"]
        discarded = len(filtered["discarded"]) + len(filtered["dropped"])
        logger.info(
            "[lore_worker] layer A | chat=%s | candidates=%s | "
            "person_facts=%s | memes=%s | discarded=%s",
            chat_id, len(parsed_a.get("candidates") or []),
            len(person_facts), len(memes_a), discarded)
        if not person_facts and not memes_a:
            return 0
        layer_b_messages = [
            {"role": "system", "content": LAYER_B_SYSTEM_PROMPT},
            {"role": "user",
             "content": build_layer_b_user(person_facts, memes_a, names)},
        ]
        try:
            parsed_b = await self._layer_b_call(chat_id, layer_b_messages)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[lore_worker] layer B failed — chat_memes Слоя А сохранены | "
                "chat=%s", chat_id)
            return await self._write_chat_memes(chat_id, memes_a)
        validated = validate_layer_b(parsed_b, window)
        if validated.get("rejected"):
            logger.info(
                "[lore_worker] layer B verbatim rejected | chat=%s | "
                "fields=%s", chat_id,
                [r.get("field") for r in validated["rejected"]])
        # Д3: пишем ТОЛЬКО производные (портрет + мемы); ручные
        # persona_dossier_overrides не трогаем (writer их не вызывает).
        await self._write_generated_portraits(
            chat_id, validated.get("portraits") or [], names)
        # S10.21-7: успешный Слой Б — источник истины по мемам, в т.ч. пустой
        # список (Синтезатор сознательно всё отфильтровал). Fallback на
        # `memes_a` — только если ключа `memes` нет в ответе B (исключение B
        # обработано выше).
        memes_b = validated.get("memes") if "memes" in validated else None
        return await self._write_chat_memes(
            chat_id, memes_a if memes_b is None else memes_b)

    async def rebuild_dossier_for_chat(self, chat_id: int, *,
                                       window_hours: int = 168,
                                       limit: int | None = None) -> int:
        """F5 (ADR-1021-5 §4.1 п.2): публичная пересборка досье чата через
        двухслойный пайплайн F1 — БЕЗ store/профиля/флага иронии (операторский
        CLI-путь). Окно `smart_messages` — только ЧТЕНИЕ (инвариант сырой
        истории), формат `_format_window`, ростер `_window_names`. Возвращает
        число записанных `chat_memes` (0 — пустое окно/скип)."""
        db = self._db
        min_chars = hot.get("limits.lore_min_message_chars",
                            settings.LORE_MIN_MESSAGE_CHARS)
        bot_exclude = int(self.bot_id) if self.bot_id else _NEVER_USER_ID
        # F1 round1022 (UPD3): window_hours == 0 → без ограничения по времени
        # (всё в пределах max_msgs); иначе — окно часов назад.
        _hours = int(window_hours or 0)
        since_ts = 0 if _hours <= 0 else int(time.time()) - _hours * 3600
        max_msgs = int(limit or hot.get(
            "limits.lore_window_max_messages",
            settings.LORE_WINDOW_MAX_MESSAGES))
        cursor = await db.db.execute(
            _WINDOW_SQL, (chat_id, since_ts, int(min_chars), bot_exclude,
                          max_msgs))
        rows = await cursor.fetchall()
        lines = self._format_window(rows)
        if not lines:
            logger.info("[lore_worker] rebuild: пустое окно | chat=%s",
                        chat_id)
            return 0
        return await self._classify_dossier(chat_id, lines,
                                            self._window_names(rows))

    async def count_window_messages(self, chat_id: int, *,
                                    window_hours: int = 4320) -> int:
        """F8 (ADR-1022-8 §2.4): дешёвый `COUNT` осмысленных сообщений окна —
        для прогресса «X/Y чанков» без тяжёлого скана. Окно `smart_messages` —
        только ЧТЕНИЕ (инвариант сырой истории)."""
        db = self._db
        min_chars = hot.get("limits.lore_min_message_chars",
                            settings.LORE_MIN_MESSAGE_CHARS)
        bot_exclude = int(self.bot_id) if self.bot_id else _NEVER_USER_ID
        hours = int(window_hours or 0)
        since_ts = 0 if hours <= 0 else int(time.time()) - hours * 3600
        cursor = await db.db.execute(
            _COUNT_WINDOW_SQL,
            (chat_id, since_ts, int(min_chars), bot_exclude))
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def rebuild_dossier_for_user(
            self, chat_id: int, *, target_user: str,
            window_hours: int = 4320, limit: int | None = None,
            chunk_size: int | None = 40, progress_cb=None,
            cancel_cb=None) -> int:
        """F8 (ADR-1022-8 §2.5): аддитивная user-scoped чанковая пересборка
        досье — НЕ меняет поведение `rebuild_dossier_for_chat` (CLI F1).

        Окно `smart_messages` — только ЧТЕНИЕ. `chunk_size=None` → текущее
        одноразовое поведение (совместимость); иначе чанки окна прогоняются
        через Слой А, кандидаты накапливаются и синтезируются Слоем Б один
        раз; пишутся производные ТОЛЬКО для `target_user`. `progress_cb`
        (sync/async) вызывается после каждого чанка/на переходах стадий;
        `cancel_cb() -> bool` проверяется между чанками и стадиями → при True
        поднимается `asyncio.CancelledError` (кооперативный abort)."""
        db = self._db
        min_chars = hot.get("limits.lore_min_message_chars",
                            settings.LORE_MIN_MESSAGE_CHARS)
        bot_exclude = int(self.bot_id) if self.bot_id else _NEVER_USER_ID
        hours = int(window_hours or 0)
        since_ts = 0 if hours <= 0 else int(time.time()) - hours * 3600
        max_msgs = int(limit or hot.get(
            "limits.lore_window_max_messages",
            settings.LORE_WINDOW_MAX_MESSAGES))
        cursor = await db.db.execute(
            _WINDOW_SQL, (chat_id, since_ts, int(min_chars), bot_exclude,
                          max_msgs))
        rows = await cursor.fetchall()
        lines = self._format_window(rows)
        if not lines:
            logger.info("[lore_worker] user rebuild: пустое окно | chat=%s",
                        chat_id)
            return 0
        names = self._window_names(rows)
        target = self._canon(target_user) or str(target_user or "").strip()
        if not chunk_size:
            return await self._classify_dossier(chat_id, lines, names)
        return await self._classify_chunked_user(
            chat_id, lines, names, target=target,
            chunk_size=max(1, int(chunk_size)),
            progress_cb=progress_cb, cancel_cb=cancel_cb)

    async def _classify_chunked_user(
            self, chat_id: int, window: list[str], names: list[str], *,
            target: str, chunk_size: int, progress_cb=None,
            cancel_cb=None) -> int:
        """F8: Layer A по чанкам → накопление кандидатов → один Layer B.

        Пишет `dossier_portrait`/`chat_meme` ТОЛЬКО для `target`."""
        chunks = [window[i:i + chunk_size]
                  for i in range(0, len(window), chunk_size)]
        total = max(1, len(chunks))
        processed = 0
        person_facts: list = []
        memes_a: list = []
        await _emit_progress(progress_cb, 0, total, "extract")
        for chunk in chunks:
            if _cancel_requested(cancel_cb):
                raise asyncio.CancelledError()
            extracted = await self._extract_chunk(chat_id, chunk, names)
            if extracted is None:
                break
            facts, memes = extracted
            person_facts.extend(facts)
            memes_a.extend(memes)
            processed += 1
            await _emit_progress(progress_cb, processed, total, "extract")
        if _cancel_requested(cancel_cb):
            raise asyncio.CancelledError()
        await _emit_progress(progress_cb, processed, total, "synthesize")
        if not person_facts and not memes_a:
            return 0
        layer_b_messages = [
            {"role": "system", "content": LAYER_B_SYSTEM_PROMPT},
            {"role": "user",
             "content": build_layer_b_user(person_facts, memes_a, names)},
        ]
        from services import worker_budget
        try:
            if not await _budget_ok(
                    chat_id,
                    worker_budget.estimate_tokens(layer_b_messages[1]["content"]),
                    calls=1):
                logger.warning(
                    "[lore_worker] WARNING skip: budget dossier (layer B "
                    "user rebuild) | chat=%s", chat_id)
                return await self._write_target_memes(chat_id, memes_a, target)
            parsed_b = await self._layer_b_call(chat_id, layer_b_messages)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[lore_worker] user rebuild layer B failed — мемы A "
                "target-scoped | chat=%s", chat_id)
            return await self._write_target_memes(chat_id, memes_a, target)
        validated = validate_layer_b(parsed_b, window)
        if _cancel_requested(cancel_cb):
            raise asyncio.CancelledError()
        target_key = target.casefold()
        portraits = [
            item for item in (validated.get("portraits") or [])
            if isinstance(item, dict)
            and str(item.get("target") or "").strip().casefold() == target_key]
        written = await self._write_generated_portraits(
            chat_id, portraits, names)
        memes_b = validated.get("memes") if "memes" in validated else None
        written += await self._write_target_memes(
            chat_id, memes_a if memes_b is None else memes_b, target)
        await _emit_progress(progress_cb, processed, total, "write")
        return written

    async def _extract_chunk(self, chat_id: int, lines: list[str],
                             names: list[str]) -> tuple | None:
        """Layer A одного чанка. None — бюджет исчерпан (стоп извлечения);
        ошибка разбора → пустой результат (fail-open, чанк пропущен)."""
        layer_a_user = build_layer_a_user(lines, names)
        messages = [
            {"role": "system", "content": LAYER_A_SYSTEM_PROMPT},
            {"role": "user", "content": layer_a_user},
        ]
        from services import worker_budget
        if not await _budget_ok(
                chat_id, worker_budget.estimate_tokens(layer_a_user), calls=1):
            logger.warning(
                "[lore_worker] WARNING skip: budget dossier (chunk) | "
                "chat=%s", chat_id)
            return None
        try:
            parsed_a = await self._layer_a_call(chat_id, messages)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[lore_worker] layer A chunk failed — skip | chat=%s",
                chat_id)
            return [], []
        filtered = filter_layer_a_candidates(parsed_a, names, canon=self._canon)
        return filtered["person_facts"], filtered["memes"]

    async def _write_target_memes(self, chat_id: int, items,
                                  target: str) -> int:
        """Запись `chat_meme` только для `target` (F8 user-scoped)."""
        key = str(target or "").strip().casefold()
        if not key:
            return await self._write_chat_memes(chat_id, items)
        filtered = [it for it in (items or [])
                    if isinstance(it, dict)
                    and str(it.get("target") or "").strip().casefold() == key]
        return await self._write_chat_memes(chat_id, filtered)

    async def _layer_a_call(self, chat_id: int,
                            messages: list[dict]) -> dict:
        """LLM-вызов Слоя А (temp 0.2, роль background) + 1 retry на
        невалидном JSON; повторная ошибка → ValueError (fallback вызывающего)."""
        raw = await self._dossier_llm(messages)
        try:
            return parse_layer_a(raw, canon=self._canon)
        except ValueError:
            logger.info(
                "[lore_worker] layer A answer invalid — 1 retry | chat=%s",
                chat_id)
            await _budget_extra_calls(chat_id)
            raw = await self._dossier_llm(messages)
            return parse_layer_a(raw, canon=self._canon)

    async def _layer_b_call(self, chat_id: int,
                            messages: list[dict]) -> dict:
        """LLM-вызов Слоя Б (temp 0.2, роль background) + 1 retry на
        невалидном JSON; повторная ошибка → ValueError (fallback вызывающего)."""
        raw = await self._dossier_llm(messages)
        try:
            return parse_layer_b(raw, canon=self._canon)
        except ValueError:
            logger.info(
                "[lore_worker] layer B answer invalid — 1 retry | chat=%s",
                chat_id)
            await _budget_extra_calls(chat_id)
            raw = await self._dossier_llm(messages)
            return parse_layer_b(raw, canon=self._canon)

    async def _write_generated_portraits(self, chat_id: int, portraits,
                                         names) -> int:
        """F1 (spec §3.2.1): запись персональных портретов Слоя Б как
        производных `graph_facts.status='dossier_portrait'` через
        `db.upsert_generated_dossier`. Только `target` из ростера окна;
        пустые портреты (нет portrait/patterns/themes) пропускаем.
        Fail-open на каждый портрет; R17 — в логах только count."""
        roster = {str(n).strip().casefold()
                  for n in (names or []) if str(n).strip()}
        written = 0
        for item in portraits or []:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target") or "").strip()
            if not target:
                continue
            if roster and target.casefold() not in roster:
                continue
            portrait = str(item.get("portrait") or "").strip()
            patterns = [str(x).strip() for x in (item.get("patterns") or [])
                        if str(x).strip()]
            themes = [str(x).strip() for x in (item.get("themes") or [])
                      if str(x).strip()]
            if not portrait and not patterns and not themes:
                continue
            try:
                fact_id = await self._db.upsert_generated_dossier(
                    chat_id, target, portrait, patterns, themes,
                    int(time.time()))
                if fact_id:
                    written += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "[lore_worker] generated portrait write failed — "
                    "fail-open | chat=%s", chat_id, exc_info=True)
        if written:
            logger.info(
                "[lore_worker] dossier portraits written | chat=%s | n=%s",
                chat_id, written)
        return written

    async def _write_chat_memes(self, chat_id: int, items) -> int:
        """Идемпотентная запись `chat_memes` как `graph_facts.status=
        'chat_meme'` (spec §3, нулевой DDL). `real_facts` не дублируем."""
        written = 0
        for item in items or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            target = str(item.get("target") or "").strip()
            if not text or not target:
                continue
            try:
                if await self._db.meme_exists(chat_id, target, text):
                    continue
                await self._db.insert_graph_fact(
                    chat_id, text, "chat_history", None, target_user=target,
                    weight=0.4, status="chat_meme", kind="fact",
                    belief_meta=json.dumps({
                        "meme": True, "source": "dossier",
                        "classified_by": item.get("classified_by", "llm"),
                        "confidence": 0.8, "created_at": int(time.time()),
                    }, ensure_ascii=False))
                written += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "[lore_worker] meme write failed — fail-open | chat=%s",
                    chat_id, exc_info=True)
        if written:
            logger.info(
                "[lore_worker] dossier memes written | chat=%s | n=%s",
                chat_id, written)
        return written

    async def _worker_llm(self, role: str, messages: list[dict],
                          temperature: float | None = None) -> str:
        """F3/T-1439/F8: вызов выделенной LLM роли воркера
        (`generate_worker`) с фоллбэком на `generate` (моки/старые клиенты
        без роутера). R17: ключи логирует только llm_client — здесь их нет."""
        worker_fn = getattr(self._llm, "generate_worker", None)
        if callable(worker_fn):
            return await worker_fn(role, messages, temperature=temperature)
        return await self._llm.generate(messages, temperature=temperature)

    async def _dossier_llm(self, messages: list[dict]) -> str:
        """Вызов LLM воркера досье: роль background (F8/F3-T-1439)."""
        return await self._worker_llm("background", messages, temperature=0.2)

    def _format_window(self, rows) -> list[str]:
        """Строки `[%Y-%m-%d %H:%M] автор: текст` в хронологическом порядке;
        бюджет limits.lore_window_max_chars — свежий конец сохраняется
        (spec §3.5/Q4: сборка от свежих к старым, пока суммарно ≤ лимита)."""
        max_chars = int(hot.get("limits.lore_window_max_chars",
                                settings.LORE_WINDOW_MAX_CHARS) or 0)
        formatted = []
        for r in reversed(rows):                       # DESC-выборка → ASC
            try:
                author = str(_row_get(r, "author_name", 1) or "").strip()
                user_id = _row_get(r, "user_id", 0)
                if not author and user_id is not None:
                    author = str(user_id)
                text = str(_row_get(r, "text", 2) or "").strip()
            except Exception:
                continue
            if not text:
                continue
            if author:
                formatted.append(
                    f"[{_line_ts(_row_get(r, 'timestamp', 3))}] {author}: {text}")
            else:
                # импортированные строки без автора (user_id NULL): без имени
                formatted.append(
                    f"[{_line_ts(_row_get(r, 'timestamp', 3))}] {text}")
        if max_chars <= 0 or not formatted:
            return formatted
        selected = []
        remaining = max_chars
        for line in reversed(formatted):               # свежие → старые
            if remaining <= 0:
                break
            if len(line) <= remaining:
                selected.append(line)
                remaining -= len(line)
            else:
                selected.append(line[:remaining])      # огромная строка —
                remaining = 0                          # свежий кусок цел
        selected.reverse()                             # хронология ASC
        return selected

    async def _chat_facts(self, chat_id: int) -> list[str]:
        """Чат-уровневые protected-факты (user_name IS NULL) БЕЗ
        legacy-константы CHAT_LORE_2661910336 (она же в manual после сида).
        Fail-open → []."""
        try:
            cursor = await self._db.db.execute(
                _FACTS_SQL, (chat_id, CHAT_LORE_2661910336))
            rows = await cursor.fetchall()
            return [str(_row_get(r, "fact", 0)) for r in rows]
        except Exception:
            logger.warning(
                "[lore_worker] chat-level facts read failed — контекст без "
                "фактов | chat=%s", chat_id, exc_info=True)
            return []

    async def _apply_result(self, chat_id: int, raw: str | None,
                            old_auto: str) -> dict:
        """Запись результата (spec §3.5 п.6): UNCHANGED/идентичный текст →
        mark_auto_done (метка периода БЕЗ истории); изменённый →
        set_auto (история field='auto', changed_by NULL, NOTIFY); пусто →
        WARNING + error (профиль не тронут)."""
        if is_unchanged_response(raw):
            await self._store.mark_auto_done(chat_id)
            return {"status": "ok", "changed": False}
        text = normalize_lore(raw or "")
        if not text:
            logger.warning(
                "[lore_worker] пустой ответ LLM — auto_lore не тронут | "
                "chat=%s", chat_id)
            return {"status": "error", "reason": "llm_empty"}
        if text == normalize_lore(old_auto):
            # ответ идентичен текущему авто-лору → только метка (AC-3)
            await self._store.mark_auto_done(chat_id)
            return {"status": "ok", "changed": False}
        await self._store.set_auto(chat_id, text)
        return {"status": "ok", "changed": True}
