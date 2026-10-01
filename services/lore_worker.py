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
from pathlib import Path

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from services import hot_config as hot
from services import mca_gates
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
# mca-04b: фильтр области full rebuild — БЕЗ min_chars (§8.3.3: «короткие
# ответы не отбрасывать механически по длине»: «да» подтверждает факт из
# вопроса). Команды/пустые/бот — по-прежнему не история. Плейсхолдер: 1 —
# bot_id-исключение.
_REBUILD_FILTER = (
    "text IS NOT NULL AND length(trim(text)) > 0 "
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
# ── mca-04b (ADR-1027-9 D1/D4): keyset-проход full rebuild ──────────────────
# Стабильный порядок (timestamp, id) ASC, БЕЗ OFFSET (§8.3: «не OFFSET по
# изменяющимся миллионам строк»). Курсор (last_ts, last_id); граница снимка
# (boundary) — максимум (timestamp, id) области на старте. Плейсхолдеры:
# 1 chat_id, 2 bot_exclude, 3/4 last_ts, 5 last_id,
# 6/7 boundary_ts, 8 boundary_id, 9 batch_limit.
_KEYSET_PAGE_SQL = (
    "SELECT id, user_id, author_name, text, timestamp, tg_message_id, "
    "reply_to_id, chat_id FROM smart_messages "
    "WHERE chat_id = ? AND " + _REBUILD_FILTER + " "
    "AND ((timestamp > ?) OR (timestamp = ? AND id > ?)) "
    "AND ((timestamp < ?) OR (timestamp = ? AND id <= ?)) "
    "ORDER BY timestamp ASC, id ASC LIMIT ?"
)
# COUNT «доступно в диапазоне» (та же область, что и keyset): 1 chat_id,
# 2 bot, 3/4 from_ts, 5/6 boundary_ts, 7 boundary_id.
_RANGE_COUNT_SQL = (
    "SELECT COUNT(*) FROM smart_messages "
    "WHERE chat_id = ? AND " + _REBUILD_FILTER + " "
    "AND ((timestamp > ?) OR (timestamp = ? AND id > 0)) "
    "AND ((timestamp < ?) OR (timestamp = ? AND id <= ?))"
)
# Граница снимка: максимум (timestamp, id) области (те же фильтры).
_RANGE_BOUNDARY_SQL = (
    "SELECT timestamp, id FROM smart_messages "
    "WHERE chat_id = ? AND " + _REBUILD_FILTER + " "
    "AND ((timestamp > ?) OR (timestamp = ? AND id > 0)) "
    "AND ((timestamp < ?) OR (timestamp = ? AND id <= ?)) "
    "ORDER BY timestamp DESC, id DESC LIMIT 1"
)
# Ростер участников области (bounded 500 — те же границы, что name-резолв):
# идентичности всего нужного scope, не только текущего окна (§8.3.3/D6).
_RANGE_ROSTER_SQL = (
    "SELECT user_id, author_name FROM smart_messages "
    "WHERE chat_id = ? AND " + _REBUILD_FILTER + " "
    "AND ((timestamp > ?) OR (timestamp = ? AND id > 0)) "
    "AND ((timestamp < ?) OR (timestamp = ? AND id <= ?)) "
    "ORDER BY id DESC LIMIT 500"
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
# mca-04b: сентинеллы верхней границы области для COUNT/BOUNDARY-запросов
# (timestamp ~1.7e9 / id AUTOINCREMENT; 2**62 заведомо больше любых строк).
_BOUNDARY_MAX_TS = 2 ** 62
_BOUNDARY_MAX_ID = 2 ** 62


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


# ── mca-04b (D11): счётчики/покрытие full rebuild ───────────────────────────
# Разные единицы: available (в диапазоне) / viewed (прочитано строки) /
# sent_to_llm (передано модели строк) / selected (отобрано для субъекта) /
# candidates (извлечено кандидатов Layer A) / accepted (принято личных
# фактов) / rejected_by_reason / unresolved / portraits/memes updated /
# errors / skipped + покрытие по годам/месяцам (прочитанные строки).
_FULL_COUNTER_FIELDS = (
    "available", "viewed", "sent_to_llm", "selected", "candidates",
    "accepted", "unresolved", "portraits_updated", "memes_updated",
    "errors", "skipped",
    # mca-04b H-2 (review round 1): различимые единицы отказов —
    # недоступность модели ≠ parse error (честная финализация, инвариант 2).
    "model_errors", "parse_errors",
)


def _new_rebuild_counters() -> dict:
    counters = {field: 0 for field in _FULL_COUNTER_FIELDS}
    counters["rejected_by_reason"] = {}
    counters["coverage"] = {}
    return counters


def _coverage_bucket(ts) -> str | None:
    """Unix-ts → ключ покрытия 'YYYY-MM' (None — битая метка)."""
    try:
        return datetime.fromtimestamp(
            int(ts), tz=timezone.utc).strftime("%Y-%m")
    except (TypeError, ValueError, OSError):
        return None


def _coverage_add(coverage: dict, ts) -> None:
    bucket = _coverage_bucket(ts)
    if not bucket:
        return
    year, month = bucket.split("-", 1)
    year_row = coverage.setdefault(year, {"total": 0, "months": {}})
    year_row["total"] = int(year_row.get("total") or 0) + 1
    months = year_row.setdefault("months", {})
    months[month] = int(months.get(month) or 0) + 1


def _write_batch_artifact(backlog_dir, batch_no: int, payload: dict) -> str:
    """mca-04b (D4): результат извлечения batch — на диск (backlog, fsync,
    tmp→replace; REUSE `_flush_fsync_and_dir`). R17: только счётчики/курсор.
    Возврат — имя файла."""
    from services.memory_maintenance import _flush_fsync_and_dir
    directory = Path(backlog_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"batch_{int(batch_no):06d}.json"
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
        _flush_fsync_and_dir(fh, directory)
    os.replace(tmp, target)
    return target.name


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
        # MCA-04a FIX п.5 (spec §4.6, D-MCA04A-1): row-bound — локатор
        # `evidence` обязан лежать в границах окна/чанка (номер = строка
        # пронумерованного окна `build_layer_a_user`).
        filtered = filter_layer_a_candidates(parsed_a, names,
                                             canon=self._canon,
                                             row_count=len(window))
        person_facts = filtered["person_facts"]
        memes_a = filtered["memes"]
        discarded = len(filtered["discarded"]) + len(filtered["dropped"])
        logger.info(
            "[lore_worker] layer A | chat=%s | candidates=%s | "
            "person_facts=%s | memes=%s | discarded=%s",
            chat_id, len(parsed_a.get("candidates") or []),
            len(person_facts), len(memes_a), discarded)
        # MCA-04a FIX п.3 (spec §4.6, A86): валидированные person_facts
        # сохраняются НЕЗАВИСИМО от синтеза портрета (до вызова Слоя Б) — при
        # сбое Layer Б личный факт с subject ID + SourceRef остаётся. Пишутся
        # `unconfirmed` (не повышаются до confirmed). Гейт — attribution.
        await self._write_person_facts(chat_id, person_facts)
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

    # ── mca-04b (ADR-1027-9 D1): полный диапазон full rebuild ────────────────

    async def count_range_messages(self, chat_id: int, *,
                                   window_hours: int = 0) -> int:
        """«Доступно в диапазоне» — COUNT сообщений ПОЛНОГО диапазона
        (не bounded window; прогресс full rebuild считается от полного
        диапазона, A87/REQ-MCA04B-10). Фильтр области — без min_chars
        (короткие ответы не отбрасываются по длине, §8.3.3)."""
        db = self._db
        bot_exclude = int(self.bot_id) if self.bot_id else _NEVER_USER_ID
        hours = int(window_hours or 0)
        from_ts = 0 if hours <= 0 else int(time.time()) - hours * 3600
        cursor = await db.db.execute(
            _RANGE_COUNT_SQL,
            (chat_id, bot_exclude, from_ts, from_ts,
             _BOUNDARY_MAX_TS, _BOUNDARY_MAX_TS, _BOUNDARY_MAX_ID))
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def range_boundary(self, chat_id: int, *,
                             window_hours: int = 0) -> tuple[int, int]:
        """Граница снимка: максимум `(timestamp, id)` осмысленной области.
        Возврат `(ts, id)`; `(0, 0)` — область пуста."""
        db = self._db
        bot_exclude = int(self.bot_id) if self.bot_id else _NEVER_USER_ID
        hours = int(window_hours or 0)
        from_ts = 0 if hours <= 0 else int(time.time()) - hours * 3600
        cursor = await db.db.execute(
            _RANGE_BOUNDARY_SQL,
            (chat_id, bot_exclude, from_ts, from_ts,
             _BOUNDARY_MAX_TS, _BOUNDARY_MAX_TS, _BOUNDARY_MAX_ID))
        row = await cursor.fetchone()
        if row is None:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    async def rebuild_dossier_full(
            self, chat_id: int, *, target_user: str, window_hours: int = 0,
            chunk_size: int | None = None, batch_max: int | None = None,
            progress_cb=None, cancel_cb=None, checkpoint_cb=None,
            backlog_dir=None, write_mode: str = "direct",
            resume_cursor: tuple | None = None,
            resume_candidates: list | None = None) -> dict:
        """Единый контракт full rebuild (ADR-1027-9 D1/D4, SC-01/03/05/06).

        Поточный keyset-проход по ПОЛНОМУ диапазону (стабильный порядок
        `(timestamp, id)` ASC, БЕЗ OFFSET; порции ≤ `batch_max` (500) с
        делением на чанки Layer A); результаты извлечения — на диск по
        batch (`backlog_dir`); иерархический синтез Layer B ОДИН раз по
        завершении прохода; новый live-batch обновляет накопленную картину.

        * `checkpoint_cb(cursor_ts, cursor_id, counters, coverage)` —
          продвижение checkpoint ПОСЛЕ фиксации результата batch (дисковый
          артефакт fsync + person_facts записаны); вызывается fail-open;
        * бюджет исчерпан на batch → возврат
          `{"status": "budget_exhausted", "cursor": (ts, id), ...}` —
          **частичный синтез НЕ выполняется** (A89: budget ≠ «всё
          обработано»); неполный диапазон остаётся в очереди у runner'а;
        * `resume_cursor` — продолжение с checkpoint (без дублей: дедуп
          записей + keyset от курсора);
        * `resume_candidates` (H-1, review round 1) — кандидаты прерванного
          прогона, восстановленные runner'ом из staging поколений; сеются в
          накопление ДО прохода, поэтому Layer B синтез при resume видит
          ОБА сегмента (до и после курсора) — портрет полного диапазона;
        * `write_mode`: "direct" — существующие writer'ы сразу (паритет
          baseline-записи, staging OFF); "collect" — кандидаты накапливаются
          и возвращаются (`candidates`) для staging/активации runner'ом;
        * `cancel_cb()` — кооперативная отмена между batch/чанками
          (`asyncio.CancelledError`); старые факты не трогаются.

        Честная финализация (H-2, review round 1; инвариант 2 — «budget/
        модель/ошибка никогда не дают completed»):
        * извлечений 0 ∧ ошибки модели > 0 → `model_unavailable`;
        * извлечений 0 ∧ (только parse errors) → `failed`
          (`reason_code=parse_error`);
        * Layer B: бюджет/исключение → НЕ `completed`
          (`budget_exhausted`/`model_unavailable`/`failed` c
          `failed_stage="synthesize"`); в collect-режиме кандидаты
          возвращаются в отчёте — runner персистит их до паузы;
          нулевой результат при ПОЛНОМ корректном проходе (0 ошибок)
          остаётся валидным `completed` (инвариант 14).

        Возврат: `{"status": "completed"|"budget_exhausted"|
        "model_unavailable"|"failed", "reason_code", "failed_stage",
        "written", "total", "processed", "cursor", "boundary", "counters",
        "coverage", "candidates"}`."""
        db = self._db
        bot_exclude = int(self.bot_id) if self.bot_id else _NEVER_USER_ID
        hours = int(window_hours or 0)
        from_ts = 0 if hours <= 0 else int(time.time()) - hours * 3600
        batch_limit = int(batch_max) if batch_max else \
            mca_gates.dossier_batch_max_messages()
        chunk = max(1, int(chunk_size) if chunk_size else int(
            getattr(settings, "DOSSIER_REBUILD_CHUNK_SIZE", 40) or 40))
        counters = _new_rebuild_counters()
        coverage: dict = {}
        target = self._canon(target_user) or str(target_user or "").strip()

        # Граница снимка (максимум (ts,id) области) + «доступно в диапазоне».
        boundary_ts, boundary_id = await self.range_boundary(
            chat_id, window_hours=hours)
        counters["available"] = await self.count_range_messages(
            chat_id, window_hours=hours)
        total = counters["available"]
        # Ростер всего нужного scope (не только ростер говорящих окна; D6),
        # bounded 500.
        roster = await self._range_roster(chat_id, from_ts=from_ts,
                                          boundary=(boundary_ts, boundary_id),
                                          bot_exclude=bot_exclude)
        names = sorted(roster) if roster else []
        # Курсор: старт от from_ts (все строки ts >= from_ts включаются),
        # либо от checkpoint при resume.
        if resume_cursor:
            last_ts, last_id = int(resume_cursor[0]), int(resume_cursor[1])
        else:
            last_ts, last_id = from_ts, 0
        batch_no = 0
        written = 0
        # H-1: кандидаты прерванного прогона (staging) — в накоплении
        # ДО прохода; Layer B при resume синтезирует по обоим сегментам.
        collected: list = [c for c in (resume_candidates or [])
                           if isinstance(c, dict)]

        def _cursor_tuple(ts: int, row_id: int) -> tuple:
            return (int(ts), int(row_id))

        while True:
            if _cancel_requested(cancel_cb):
                raise asyncio.CancelledError()
            cursor = await db.db.execute(
                _KEYSET_PAGE_SQL,
                (chat_id, bot_exclude, last_ts, last_ts,
                 last_id, boundary_ts, boundary_ts, boundary_id, batch_limit))
            rows = await cursor.fetchall()
            if not rows:
                break
            batch_no += 1
            counters["viewed"] += len(rows)
            for r in rows:
                _coverage_add(coverage, _row_get(r, "timestamp", 3))
            # Порция ≤ batch_max → чанки Layer A (деление по чанкам/эпизодам;
            # архив не грузится в RAM одним списком и не отправляется одним
            # промптом).
            batch_facts: list = []
            batch_memes: list = []
            for start in range(0, len(rows), chunk):
                chunk_rows = rows[start:start + chunk]
                lines = self._format_window(chunk_rows, desc_input=False)
                counters["sent_to_llm"] += len(chunk_rows)
                extracted = await self._extract_chunk(
                    chat_id, lines, names, window_rows=chunk_rows,
                    roster=roster, stats=counters)
                if extracted is None:
                    # Бюджет исчерпан: НЕ синтезируем частичный результат —
                    # возвращаемся с курсором НА НАЧАЛО этого batch (он будет
                    # пере-обработан после resume; person_facts уже
                    # зафиксированных чанков не дублируются — дедуп).
                    report = self._full_report(
                        "budget_exhausted", written, total, counters,
                        coverage, _cursor_tuple(last_ts, last_id),
                        (boundary_ts, boundary_id), collected,
                        failed_stage="extract")
                    return report
                facts, memes = extracted
                batch_facts.extend(facts)
                batch_memes.extend(memes)
                counters["candidates"] += len(facts) + len(memes)
                if _cancel_requested(cancel_cb):
                    raise asyncio.CancelledError()
            # Независимая фиксация личных фактов batch (не ждём синтез;
            # дедуп исключает удвоение при resume — A89). Collect-режим
            # (staging) — факты НЕ пишутся напрямую: уйдут в staging
            # и применятся атомарной активацией.
            if write_mode == "direct":
                written += await self._write_person_facts(chat_id,
                                                          batch_facts)
            collected.extend(batch_facts)
            collected.extend(batch_memes)
            target_selected = sum(
                1 for c in batch_facts if isinstance(c, dict)
                and str(c.get("target") or "").strip().casefold()
                == target.casefold())
            counters["selected"] += target_selected
            counters["accepted"] += target_selected
            # Фиксация результата batch на диск (backlog, fsync) — ДО
            # продвижения checkpoint (checkpoint после фиксации, SC-05).
            if backlog_dir is not None:
                try:
                    await asyncio.to_thread(
                        _write_batch_artifact, Path(backlog_dir), batch_no,
                        {"chat_id": chat_id, "batch_no": batch_no,
                         "cursor": _cursor_tuple(_row_get(rows[-1],
                                                          "timestamp", 3),
                                                 _row_get(rows[-1], "id", 0)),
                         "person_facts": len(batch_facts),
                         "memes": len(batch_memes),
                         "counters": {k: v for k, v in counters.items()
                                      if isinstance(v, int)}})
                except Exception:
                    logger.debug(
                        "[lore_worker] batch artifact write failed "
                        "(fail-open) | chat=%s", chat_id)
            # Курсор — последняя строка batch; checkpoint продвигает runner
            # после фиксации (fail-open callback).
            last_ts = int(_row_get(rows[-1], "timestamp", 3) or 0)
            last_id = int(_row_get(rows[-1], "id", 0) or 0)
            if checkpoint_cb is not None:
                try:
                    result = checkpoint_cb(last_ts, last_id, counters,
                                           coverage)
                    if inspect.isawaitable(result):
                        await result
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.debug(
                        "[lore_worker] checkpoint callback failed "
                        "(fail-open)")
            if progress_cb is not None:
                await _emit_progress(progress_cb, counters["viewed"], total,
                                     "extract")
            if len(rows) < batch_limit:
                break
        if _cancel_requested(cancel_cb):
            raise asyncio.CancelledError()
        # ── H-2 (review round 1): честная финализация extraction-стадии ────
        # Инвариант 2: недоступность модели/parse error никогда не дают
        # `completed`. Нулевой результат при ПОЛНОМ корректном проходе
        # (0 ошибок) остаётся валидным (инвариант 14).
        extracted_total = int(counters.get("candidates") or 0)
        model_errs = int(counters.get("model_errors") or 0)
        parse_errs = int(counters.get("parse_errors") or 0)
        cursor_now = _cursor_tuple(last_ts, last_id)
        boundary_pair = (boundary_ts, boundary_id)
        collect_candidates = collected if write_mode == "collect" else []
        if extracted_total == 0 and model_errs > 0:
            report = self._full_report(
                "model_unavailable", written, total, counters, coverage,
                cursor_now, boundary_pair, collect_candidates,
                reason_code="model_unavailable", failed_stage="extract")
            return report
        if extracted_total == 0 and parse_errs > 0:
            report = self._full_report(
                "failed", written, total, counters, coverage,
                cursor_now, boundary_pair, collect_candidates,
                reason_code="parse_error", failed_stage="extract")
            return report
        # Проход завершён: ОДИН иерархический синтез Layer B по субъекту
        # (кандидаты — отфильтрованное подмножество, а не весь архив;
        # «архив одним промптом» запрещён и не выполняется).
        await _emit_progress(progress_cb, counters["viewed"], total,
                             "synthesize")
        synth_written, portraits, memes_b_final, synth_failure = \
            await self._synthesize_full_candidates(
                chat_id, collected, target, names, counters,
                write_direct=(write_mode == "direct"))
        written += synth_written
        if synth_failure:
            # H-2: бюджет/сбой на Layer B — НЕ completed (инвариант 2).
            # collect-режим: кандидаты в отчёте → runner персистит их в
            # staging ДО паузы (H-1) → resume с `resume_candidates`
            # повторяет синтез по полному набору. direct-режим (паритет
            # baseline, staging OFF): resume не может восстановить набор
            # накопления → честный терминальный `failed` (спека §3.2:
            # сбой Layer B → job не completed).
            if synth_failure == "budget":
                if write_mode == "collect":
                    # pause → resume восстановит набор из staging (H-1)
                    status, reason = ("budget_exhausted",
                                      "dossier_paused_budget")
                else:
                    # direct: resume не восстановит набор накопления —
                    # paused дал бы silent partial (пустой синтез →
                    # completed без портрета). Честный терминальный failed.
                    status, reason = "failed", "dossier_paused_budget"
            elif synth_failure == "model":
                status = "model_unavailable" if write_mode == "collect" \
                    else "failed"
                reason = "model_unavailable"
            else:                       # parse (невалидный JSON Layer B)
                status, reason = "failed", "parse_error"
            report = self._full_report(
                status, written, total, counters, coverage, cursor_now,
                boundary_pair, collect_candidates, reason_code=reason,
                failed_stage="synthesize")
            return report
        report = self._full_report(
            "completed", written, total, counters, coverage,
            cursor_now, boundary_pair,
            collected if write_mode == "collect" else [])
        report["synthesized"] = {"portraits": portraits, "memes":
                                 memes_b_final}
        return report

    async def _range_roster(self, chat_id: int, *, from_ts: int,
                            boundary: tuple, bot_exclude: int) -> set[str]:
        """Канон-имена участников области (bounded 500; D6 — идентичности
        всего scope, включая «бесшумных» в диапазоне)."""
        try:
            cursor = await self._db.db.execute(
                _RANGE_ROSTER_SQL,
                (chat_id, bot_exclude, from_ts, from_ts,
                 boundary[0], boundary[0], boundary[1]))
            rows = await cursor.fetchall()
        except Exception:
            logger.warning("[lore_worker] range roster read failed — "
                           "fallback на имена окна | chat=%s", chat_id,
                           exc_info=True)
            return set()
        roster: set[str] = set()
        for r in rows:
            author = str(_row_get(r, "author_name", 1) or "").strip()
            if not author:
                continue
            roster.add(self._canon(author))
        roster.discard("")
        return roster

    def _full_report(self, status: str, written: int, total: int,
                     counters: dict, coverage: dict, cursor: tuple,
                     boundary: tuple, candidates: list, *,
                     reason_code: str | None = None,
                     failed_stage: str | None = None) -> dict:
        """Итоговый отчёт движка (H-2: честные статус/reason_code/
        failed_stage для любых не-completed исходов)."""
        if reason_code is None:
            reason_code = ("dossier_paused_budget"
                           if status == "budget_exhausted" else None)
        return {
            "status": status,
            "reason_code": reason_code,
            "failed_stage": failed_stage,
            "written": int(written),
            "total": int(total),
            "processed": int(counters.get("viewed") or 0),
            "cursor": cursor,
            "boundary": boundary,
            "counters": counters,
            "coverage": coverage,
            "candidates": candidates,
        }

    async def _synthesize_full_candidates(self, chat_id: int,
                                          candidates: list, target: str,
                                          names: list[str], counters: dict,
                                          *, write_direct: bool = True
                                          ) -> tuple:
        """Иерархический синтез Layer B над накопленными кандидатами:
        портрет/мемы — только для `target`. `write_direct=True` (паритет
        baseline-записи, staging OFF) — портрет/мемы пишутся существующими
        writer'ами; `False` (staging) — синтез возвращается runner'у
        (`(0, portraits, memes, None)`), запись — атомарной активацией.
        Возврат `(written, portraits, memes, failure)`; `failure` —
        H-2 (review round 1): `None` | `"budget"` | `"model"` | `"parse"`.
        Любой failure ≠ completed у вызывающего (инвариант 2)."""
        facts = [c for c in candidates if isinstance(c, dict)
                 and c.get("text") and not c.get("meme")]
        memes = [c for c in candidates if isinstance(c, dict)
                 and c.get("text") and c.get("meme")]
        if not facts and not memes:
            return 0, [], [], None
        layer_b_messages = [
            {"role": "system", "content": LAYER_B_SYSTEM_PROMPT},
            {"role": "user",
             "content": build_layer_b_user(facts, memes, names)},
        ]
        from services import worker_budget
        try:
            if not await _budget_ok(
                    chat_id,
                    worker_budget.estimate_tokens(
                        layer_b_messages[1]["content"]),
                    calls=1):
                logger.warning(
                    "[lore_worker] WARNING skip: budget dossier (layer B "
                    "full rebuild) | chat=%s", chat_id)
                # H-2: бюджет на Layer B — различимый failure (НЕ тихий
                # partial); мемы A target-scoped сохраняются как раньше.
                written = await self._write_target_memes(
                    chat_id, memes, target) if write_direct else 0
                counters["memes_updated"] = int(
                    counters.get("memes_updated") or 0) + written
                return written, [], [], "budget"
            parsed_b = await self._layer_b_call(chat_id, layer_b_messages)
        except asyncio.CancelledError:
            raise
        except ValueError:
            # H-2: невалидный JSON Layer B после retry — parse_error
            # (раньше был неотличим от сбоя модели).
            counters["errors"] = int(counters.get("errors") or 0) + 1
            counters["parse_errors"] = int(counters.get("parse_errors")
                                           or 0) + 1
            logger.warning(
                "[lore_worker] full rebuild layer B invalid answer "
                "(parse_error) — мемы A target-scoped | chat=%s", chat_id)
            written = await self._write_target_memes(
                chat_id, memes, target) if write_direct else 0
            counters["memes_updated"] = int(
                counters.get("memes_updated") or 0) + written
            return written, [], [], "parse"
        except Exception:
            # H-2: сбой модели/транспорта на Layer B — model_unavailable
            # (НЕ неотличимый тихий пропуск синтеза).
            counters["errors"] = int(counters.get("errors") or 0) + 1
            counters["model_errors"] = int(counters.get("model_errors")
                                           or 0) + 1
            logger.warning(
                "[lore_worker] full rebuild layer B failed "
                "(model_unavailable) — мемы A target-scoped | chat=%s",
                chat_id)
            written = await self._write_target_memes(
                chat_id, memes, target) if write_direct else 0
            counters["memes_updated"] = int(
                counters.get("memes_updated") or 0) + written
            return written, [], [], "model"
        window_lines: list[str] = []
        validated = validate_layer_b(parsed_b, window_lines)
        target_key = target.casefold()
        portraits = [
            item for item in (validated.get("portraits") or [])
            if isinstance(item, dict)
            and str(item.get("target") or "").strip().casefold() == target_key]
        memes_b = validated.get("memes") if "memes" in validated else None
        final_memes = memes if memes_b is None else memes_b
        if not write_direct:
            return 0, portraits, final_memes, None
        written = await self._write_generated_portraits(
            chat_id, portraits, names)
        counters["portraits_updated"] = int(
            counters.get("portraits_updated") or 0) + written
        meme_written = await self._write_target_memes(
            chat_id, final_memes, target)
        counters["memes_updated"] = int(
            counters.get("memes_updated") or 0) + meme_written
        return written + meme_written, portraits, final_memes, None

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

        Пишет `dossier_portrait`/`chat_meme` ТОЛЬКО для `target`.
        N-MCA04A-2 (mca-04b/A86): валидированные person_facts сохраняются
        СРАЗУ после чанка (независимо от успеха Слоя Б) — тот же контракт,
        что в оконном multilayer-пути mca-04a; повторная обработка не
        создаёт дублей (`person_fact_exists`)."""
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
            # N-2: личные факты чанка фиксируются сразу (не только портрет/
            # мемы); сбой Слоя Б их не теряет.
            try:
                await self._write_person_facts(chat_id, facts)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "[lore_worker] chunk person_facts write failed — "
                    "fail-open | chat=%s", chat_id, exc_info=True)
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
                             names: list[str], *,
                             window_rows=None,
                             roster=None,
                             stats: dict | None = None) -> tuple | None:
        """Layer A одного чанка. None — бюджет исчерпан (стоп извлечения);
        ошибка разбора → пустой результат (fail-open, чанк пропущен).

        mca-04b врезка п.5 (spec §4.7, T-3904): после row-bound фильтра
        локальные номера evidence переводятся в постоянные SourceRef
        (`provenance.local_evidence_to_source_refs`) СРАЗУ ПОСЛЕ чанка —
        одинаковый номер в разных чанках ≠ один источник (каждый чанк —
        свой `window_rows`). Невалидный кандидат (нет ни одного валидного
        локального номера) → отброшен с `reason_code=evidence_invalid`.
        `roster` — ростер scope для N-1 (name-резолв вне окна не даёт
        ложного resolved). `stats` — счётчики rejected_by_reason (опц.)."""
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
        except ValueError:
            # H-2 (review round 1): невалидный JSON после retry — parse error
            # (fail-open: чанк пропущен; различимо от недоступности модели).
            if stats is not None:
                stats["rejected_by_reason"]["parse_error"] = (
                    stats["rejected_by_reason"].get("parse_error") or 0) + 1
                stats["errors"] = int(stats.get("errors") or 0) + 1
                stats["parse_errors"] = int(stats.get("parse_errors")
                                            or 0) + 1
            logger.warning(
                "[lore_worker] layer A chunk invalid answer — skip "
                "(parse_error) | chat=%s", chat_id)
            return [], []
        except Exception:
            # H-2 (review round 1): сетевые/5xx/timeout LLM-клиента —
            # `model_unavailable` (не неотличимый parse error). Fail-open по
            # извлечению; итоговая честность прохода — на движке
            # (`rebuild_dossier_full`: errors>0 ∧ extracted==0 ≠ completed).
            if stats is not None:
                stats["rejected_by_reason"]["model_unavailable"] = (
                    stats["rejected_by_reason"].get("model_unavailable")
                    or 0) + 1
                stats["errors"] = int(stats.get("errors") or 0) + 1
                stats["model_errors"] = int(stats.get("model_errors")
                                            or 0) + 1
            logger.warning(
                "[lore_worker] layer A chunk failed — skip "
                "(model_unavailable) | chat=%s", chat_id)
            return [], []
        # MCA-04a FIX п.5 (spec §4.6, D-MCA04A-1): границы = строки ЭТОГО
        # чанка (одинаковый локальный номер в разных чанках → разные источники).
        filtered = filter_layer_a_candidates(parsed_a, names, canon=self._canon,
                                             row_count=len(lines))
        if stats is not None:
            for reason in filtered.get("dropped") or []:
                key = str(reason if isinstance(reason, str)
                          else (reason or {}).get("reason") or "invalid")
                stats["rejected_by_reason"][key] = (
                    stats["rejected_by_reason"].get(key) or 0) + 1
        person_facts = filtered["person_facts"]
        memes = filtered["memes"]
        # mca-04b (T-3904): локальные номера → постоянные SourceRef.
        rows = list(window_rows if window_rows is not None else [])
        if rows:
            for cand in person_facts:
                if not isinstance(cand, dict):
                    continue
                evidence = [n for n in (cand.get("evidence") or [])
                            if isinstance(n, (int, str))]
                if not evidence:
                    cand["_evidence_valid"] = False
                    if stats is not None:
                        stats["rejected_by_reason"]["evidence_invalid"] = (
                            stats["rejected_by_reason"].get(
                                "evidence_invalid") or 0) + 1
                    continue
                try:
                    from services import provenance
                    mapped = await provenance.local_evidence_to_source_refs(
                        self._db, chat_id=chat_id, window_rows=rows,
                        local_numbers=evidence)
                except Exception:
                    mapped = []
                valid = [m for m in mapped if m.get("valid")]
                ref_ids = [int(m["source_ref_id"]) for m in valid
                           if m.get("source_ref_id")]
                cand["_source_ref_ids"] = ref_ids
                cand["_evidence_valid"] = bool(ref_ids)
                cand["_roster"] = roster
                if ref_ids:
                    # Автор первой валидной строки evidence — для атрибуции
                    # (self_report vs third_party; §8.3.2).
                    first = rows[int(valid[0]["local"]) - 1]
                    author = str(_row_get(first, "author_name", 1) or
                                 "").strip()
                    cand["_author_name"] = author
                elif stats is not None:
                    stats["rejected_by_reason"]["evidence_invalid"] = (
                        stats["rejected_by_reason"].get(
                            "evidence_invalid") or 0) + 1
        return person_facts, memes

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

    async def _write_person_facts(self, chat_id: int, person_facts, *,
                                  provenance_channel: str = "dossier_layer_a"
                                  ) -> int:
        """MCA-04a FIX п.3 (spec §4.6, A86): запись валидированных person_facts
        Layer A как личных фактов (`subject_ref_id` + SourceRef) НЕЗАВИСИМО от
        синтеза портрета. Статус `unconfirmed` (не повышаем до confirmed).
        Гейт — `MCA_FACT_ATTRIBUTION_ENABLED`; fail-open на каждый факт.

        mca-04b (§8.3.2/A85): атрибуция по автору строки evidence —
        subject == автор → `self_report` («по собственным словам»), иначе
        `third_party` (атрибутированное утверждение). Кандидаты с
        постоянными SourceRef чанка (`_source_ref_ids`, врезка п.5/T-3904)
        получают EvidenceLink `derived_from` per источник (одинаковый
        локальный номер в разных чанках ≠ один источник). Кандидат без
        единого валидного источника не пишется (нет выдуманных ссылок)."""
        if not person_facts:
            return 0
        try:
            from services import provenance
        except Exception:
            return 0
        if not provenance.attribution_enabled():
            return 0
        written = 0
        for cand in person_facts or []:
            if not isinstance(cand, dict):
                continue
            target = str(cand.get("target") or "").strip()
            text = str(cand.get("text") or "").strip()
            if not target or not text:
                continue
            if cand.get("_evidence_valid") is False:
                # Врезка п.5 (T-3904): ни одного валидного постоянного
                # источника → кандидат не подтверждается (без выдуманных
                # ссылок); повторный прогресс может пере-извлечь.
                continue
            ref_ids = [int(r) for r in (cand.get("_source_ref_ids") or [])
                       if r]
            try:
                if await self._db.person_fact_exists(chat_id, text,
                                                     provenance_channel):
                    continue
                ref = await provenance.resolve_subject_ref(
                    self._db, chat_id, target, canon=self._canon,
                    roster=cand.get("_roster"))
                ref_id = await provenance.resolve_source_ref(self._db, ref)
                kind = provenance.classify_assertion_kind(
                    target, text, canon=self._canon, participants=[target])
                author = str(cand.get("_author_name") or "").strip()
                method = ("self_report"
                          if author and self._eq_canon(author, target)
                          else "third_party")
                fact_id = await self._db.insert_graph_fact(
                    chat_id, text, "chat_history", None, target_user=target,
                    status="unconfirmed", kind="fact", subject_ref_id=ref_id,
                    attribution_method=method,
                    assertion_kind=kind if kind in provenance.ASSERTION_KINDS
                    else "unknown",
                    provenance_channel=provenance_channel,
                    extractor_version=provenance.EXTRACTOR_VERSION)
                if fact_id:
                    await provenance.record_fact_provenance(
                        self._db, fact_id=fact_id, chat_id=chat_id,
                        origin="chat_history", target_user=target,
                        assertion_kind=kind, attribution_method=method,
                        provenance_channel=provenance_channel,
                        save_message_link=False)
                    # Постоянные источники чанка → EvidenceLink (§8.3.2).
                    obj_ref = await provenance.resolve_source_ref(
                        self._db, provenance.graph_fact_source_ref(
                            chat_id, fact_id))
                    for source_ref_id in ref_ids:
                        await provenance.add_evidence_link(
                            self._db, provenance.EvidenceLink(
                                subject_ref_id=obj_ref,
                                source_ref_id=int(source_ref_id),
                                link_type="derived_from",
                                method="direct_reference",
                                verification="verified",
                                independence="independent",
                                extractor_version=provenance.EXTRACTOR_VERSION,
                                basis="dossier chunk evidence"))
                    written += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "[lore_worker] person_fact write failed — fail-open | "
                    "chat=%s", chat_id, exc_info=True)
        if written:
            logger.info(
                "[lore_worker] dossier person_facts written | chat=%s | n=%s",
                chat_id, written)
        return written

    def _eq_canon(self, a: str, b: str) -> bool:
        """canon-равенство имён (без исключений)."""
        ca = self._canon(a).casefold()
        cb = self._canon(b).casefold()
        return bool(ca) and ca == cb

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

    def _format_window(self, rows, *, desc_input: bool = True) -> list[str]:
        """Строки `[%Y-%m-%d %H:%M] автор: текст` в хронологическом порядке;
        бюджет limits.lore_window_max_chars — свежий конец сохраняется
        (spec §3.5/Q4: сборка от свежих к старым, пока суммарно ≤ лимита).

        mca-04b: `desc_input=False` — строки УЖЕ в хронологическом (ASC)
        порядке (keyset-проход full rebuild); разворот не выполняется.
        Дефолт True — байт-паритет legacy-вызовов (_WINDOW_SQL DESC)."""
        max_chars = int(hot.get("limits.lore_window_max_chars",
                                settings.LORE_WINDOW_MAX_CHARS) or 0)
        formatted = []
        for r in (reversed(rows) if desc_input else rows):
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
