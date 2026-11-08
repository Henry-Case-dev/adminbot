"""UNIFIED-REPLY UR-C-SCHED — per-chat расписание (arch contract §4).

Покрывает строки карты UR-RES-09 / UR-28 / UR-28.2 / UR-28.3 / UR-28.5 /
UR-BAN-06:

  * два чата в разных поясах на одном тик-свипе — каждый стреляет в СВОЁ
    локальное время (один процесс/тикер, второй планировщик не создаётся);
  * DST-переход (Europe/Berlin, spring 2026-03-29): слоты переходного дня
    стреляют ровно один раз на корректных UTC-instant — не два и не ноль;
    fold/gap-математика фиксируется юнит-тестами чистой функции;
  * идемпотентность одного локального дня: повторный тик и «рестарт»
    (новый инстанс сервиса, та же БД) дубль не создают; claim
    атомарен (INSERT OR IGNORE по PK kind+chat+date+slot);
  * просроченный слот — честный skip `missed_slot_expired` ровно один
    раз (coalescing, UR-28.3); вне due-окна генератор не запускается;
  * GOODMORNING_TIME остаётся часом рассылки, пояс каждого чата —
    ChatClock (UR-28.5); per-chat gate сохранён и не съедает слот;
  * миграция v42 `slot_claims` создаёт таблицу, повтор — no-op;
  * наблюдаемость: [sched_slot] логирует резолвнутый пояс/источник/слот
    решения, без текстов чата (R17).

Мутация «весь свип по wall-clock UTC вместо пояса чата» делает тесты
классов TestPerChatTimezones/TestDstBerlinSpring/TestGoodmorningPerChat
красными (проверено; runbook в evidence среза).

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-C-SCHED
"""
import datetime
import logging
import zoneinfo
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.chat_params as chat_params
from config.settings import settings
from services.database import DatabaseService
from services import slot_claims
from services.goodmorning_scheduler import GoodmorningSchedulerService
from services.summary_scheduler import SummarySchedulerService
from services.slot_claims import (
    SLOT_CLAIMS_TABLE,
    SqliteSlotClaimStore,
    claim_slot_if_due,
    latest_slot,
    slot_instant_for,
)

pytestmark = pytest.mark.system2

UTC = datetime.timezone.utc
YEKA = zoneinfo.ZoneInfo("Asia/Yekaterinburg")     # UTC+5, без DST
BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")

CHAT_YEKA = -1002001     # глобальный пояс (Asia/Yekaterinburg, legacy-слой)
CHAT_BERLIN = -1003003   # per-chat override Europe/Berlin

#: 18:00:30 локального Asia/Yekaterinburg = 13:00:30 UTC (в due-окне).
DUE_YEKA_18 = datetime.datetime(2026, 1, 15, 13, 0, 30, tzinfo=UTC)
#: 18:00:30 локального Berlin (зима, +1) = 17:00:30 UTC (в due-окне).
DUE_BERLIN_18 = datetime.datetime(2026, 1, 15, 17, 0, 30, tzinfo=UTC)

_ROOTS_BY_CHAT: dict[int, dict] = {}


class FakeCache:
    """chat_params-кэш с per-chat overrides (root-лейаут; как в
    test_ur_c_clock — переиспользование паттерна, не копия кода)."""

    def __init__(self, roots_by_chat):
        self._roots = dict(roots_by_chat or {})

    async def get_chat_params(self, chat_id):
        return self._roots.get(int(chat_id), {})

    async def get_chat_params_full(self, chat_id):
        return self._roots.get(int(chat_id), {}), "2026-11-06T00:00:00Z"


def set_chat_override(chat_id, overrides: dict) -> None:
    _ROOTS_BY_CHAT[int(chat_id)] = {"overrides": dict(overrides)}
    chat_params._chat_params_cache = FakeCache(_ROOTS_BY_CHAT)


@pytest.fixture(autouse=True)
def sched_env(monkeypatch):
    """Изоляция слоёв пояса (frozen settings + env) и in-memory дедупа.

    Глобальный слой по умолчанию — Asia/Yekaterinburg (settings.SUMMARY_
    TIMEZONE, legacy-слой цепочки UR-24.3); per-chat override через
    FakeCache даёт 'chat'-источник."""
    slot_claims.reset_in_memory_claims()
    _ROOTS_BY_CHAT.clear()
    chat_params._chat_params_cache = FakeCache(_ROOTS_BY_CHAT)
    for name in ("GOODMORNING_TZ", "SUMMARY_TIMEZONE", "CHAT_TIMEZONE"):
        monkeypatch.delenv(name, raising=False)
    object.__setattr__(settings, "SUMMARY_TIMEZONE", "Asia/Yekaterinburg")
    object.__setattr__(settings, "CHAT_TIMEZONE", "")
    yield
    slot_claims.reset_in_memory_claims()
    _ROOTS_BY_CHAT.clear()
    chat_params._chat_params_cache = None


@pytest.fixture()
def claims_db(tmp_path):
    """Реальная SQLite-БД с миграциями (v42 создаёт slot_claims)."""
    svc = DatabaseService(str(tmp_path / "ur-c-sched.db"))

    async def _ready():
        await svc.initialize()
        return svc

    return _ready


def _make_summary_service(db, targets, chat_ids_for_db=None):
    generator = MagicMock()
    generator.generate_and_send = AsyncMock()
    db_mock = MagicMock()
    db_mock.get_smart_chat_ids = AsyncMock(
        return_value=list(chat_ids_for_db or targets))
    svc = SummarySchedulerService(generator, db if db is not None else db_mock)
    return svc, generator, db_mock


def _targets_patch(targets):
    from dataclasses import replace
    mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=tuple(targets))
    return patch("services.summary_scheduler.settings", mod)


# ── UR-28 / UR-RES-09: два пояса — один свип ───────────────────────────────


class TestPerChatTimezones:
    @pytest.mark.asyncio
    async def test_two_chats_fire_at_own_local_time_same_sweep(self, claims_db):
        """Каждый чат стреляет в СВОЁ 18:00 локальное время в рамках ОДНОГО
        процесса/тикера: Yekaterinburg в 13:00 UTC, Berlin в 17:00 UTC."""
        db = await claims_db()
        set_chat_override(CHAT_BERLIN,
                          {"limits.chat_timezone": "Europe/Berlin"})
        svc, gen, _ = _make_summary_service(
            db, targets=(CHAT_YEKA, CHAT_BERLIN))
        with _targets_patch((CHAT_YEKA, CHAT_BERLIN)):
            await svc._tick(now_utc=DUE_YEKA_18)
            assert [c.args[0] for c in gen.generate_and_send.await_args_list] \
                == [CHAT_YEKA], "18:00 Yeka стреляет в 13:00 UTC; Berlin — нет"
            await svc._tick(now_utc=DUE_BERLIN_18)
            assert [c.args[0] for c in gen.generate_and_send.await_args_list] \
                == [CHAT_YEKA, CHAT_BERLIN], "18:00 Berlin стреляет в 17:00 UTC"
        await db.close()

    @pytest.mark.asyncio
    async def test_chat_local_slot_instant_is_chat_tz_not_wallclock_utc(
            self, claims_db):
        """Защита от мутации «wall-clock UTC»: слот чата Berlin вычислен в
        его поясе (18:00 local = 17:00 UTC), а не в UTC (18:00 UTC)."""
        db = await claims_db()
        set_chat_override(CHAT_BERLIN,
                          {"limits.chat_timezone": "Europe/Berlin"})
        store = SqliteSlotClaimStore(db.db_path)
        verdict = await claim_slot_if_due(
            kind="summary", db=db, chat_id=CHAT_BERLIN,
            now_utc=DUE_BERLIN_18, slot_seq=((0, 0), (6, 0), (12, 0), (18, 0)),
            due_window_s=slot_claims.SUMMARY_DUE_WINDOW_SECONDS)
        assert verdict.action == "fire"
        assert verdict.iana == "Europe/Berlin"
        assert verdict.slot.slot_utc == datetime.datetime(
            2026, 1, 15, 17, 0, 0, tzinfo=UTC)
        row = store.lookup(kind="summary", chat_id=CHAT_BERLIN,
                           local_date="2026-01-15", local_slot="18:00")
        assert row is not None and row["fired"] == 1
        assert row["slot_utc_instant"] == int(datetime.datetime(
            2026, 1, 15, 17, 0, 0, tzinfo=UTC).timestamp())
        await db.close()


# ── UR-28.2: DST Berlin spring — ровно один запуск на слот ─────────────────


class TestDstBerlinSpring:
    @pytest.mark.asyncio
    async def test_spring_transition_day_fires_once_not_twice_zero(
            self, claims_db):
        """Переходный день Berlin (2026-03-29, CET→CEST в 01:00 UTC): слоты
        локальной шкалы стреляют ровно один раз на своих UTC-instant —
        включая смену календарной даты чата (00:00 CET = 23:00 UTC prev day)
        и «сжатый» интервал 00:00→06:00 (5 ч реального времени)."""
        db = await claims_db()
        set_chat_override(CHAT_BERLIN,
                          {"limits.chat_timezone": "Europe/Berlin"})
        svc, gen, _ = _make_summary_service(db, targets=(CHAT_BERLIN,))
        sweep = [
            # (utc-момент тика, ожидаемое действие слота)
            datetime.datetime(2026, 3, 28, 11, 0, 30, tzinfo=UTC),   # 12:00 CET
            datetime.datetime(2026, 3, 28, 17, 0, 30, tzinfo=UTC),   # 18:00 CET
            datetime.datetime(2026, 3, 28, 23, 0, 30, tzinfo=UTC),   # 00:00 CET (Mar29)
            datetime.datetime(2026, 3, 29, 0, 30, 30, tzinfo=UTC),   # вне окна → skip
            datetime.datetime(2026, 3, 29, 2, 0, 30, tzinfo=UTC),    # сразу после перехода
            datetime.datetime(2026, 3, 29, 4, 0, 30, tzinfo=UTC),    # 06:00 CEST (=04:00Z)
            datetime.datetime(2026, 3, 29, 10, 0, 30, tzinfo=UTC),   # 12:00 CEST
        ]
        fired_slots = []
        with _targets_patch((CHAT_BERLIN,)):
            for now in sweep:
                before = gen.generate_and_send.await_count
                await svc._tick(now_utc=now)
                if gen.generate_and_send.await_count > before:
                    fired_slots.append(now)
        assert len(fired_slots) == 5, (
            "DST-день: ровно 5 слотов (12/18 CET, 00 CET, 06/12 CEST), "
            "не два и не ноль")
        assert [t.hour for t in fired_slots] == [11, 17, 23, 4, 10], (
            "каждый слот стреляет на своём UTC-instant переходного дня")
        # Слоты переходного дня заняты ровно один раз каждая (date+slot PK).
        store = SqliteSlotClaimStore(db.db_path)
        rows = store.lookup(kind="summary", chat_id=CHAT_BERLIN,
                            local_date="2026-03-29", local_slot="00:00")
        assert rows is not None and rows["fired"] == 1
        assert rows["slot_utc_instant"] == int(datetime.datetime(
            2026, 3, 28, 23, 0, 0, tzinfo=UTC).timestamp())
        await db.close()

    def test_slot_math_gap_and_fold_deterministic(self):
        """Чистая математика §4.3: gap → первый валидный instant того же
        дня; fold → раннее появление (один запуск на слот)."""
        # Spring gap Berlin 2026-03-29: 02:00 не существует → 03:00 local.
        instant, mode = slot_instant_for(datetime.date(2026, 3, 29), 2, 0,
                                         BERLIN)
        assert mode == "gap_shifted"
        assert instant == datetime.datetime(2026, 3, 29, 1, 0, tzinfo=UTC)
        # 06:00 CEST существует → 04:00 UTC.
        instant, mode = slot_instant_for(datetime.date(2026, 3, 29), 6, 0,
                                         BERLIN)
        assert mode == "normal"
        assert instant == datetime.datetime(2026, 3, 29, 4, 0, tzinfo=UTC)
        # Fall fold Berlin 2026-10-25: 02:00 повторяется → раннее (CEST).
        instant, mode = slot_instant_for(datetime.date(2026, 10, 25), 2, 0,
                                         BERLIN)
        assert mode == "fold_earlier"
        assert instant == datetime.datetime(2026, 10, 25, 0, 0, tzinfo=UTC)

    def test_latest_slot_crosses_chat_local_midnight(self):
        """Шкала непрерывна: сразу после локальной полуночи чата текущим
        становится слот 00:00 НОВОЙ локальной даты (смена даты чата не
        теряет слоты; instant принадлежит прежнему UTC-дню)."""
        now = datetime.datetime(2026, 1, 15, 23, 30, tzinfo=UTC)  # 00:30 Berlin Jan16
        ref = latest_slot(now, BERLIN, ((0, 0), (6, 0), (12, 0), (18, 0)))
        assert ref.local_date == datetime.date(2026, 1, 16)
        assert ref.label == "00:00"
        assert ref.slot_utc == datetime.datetime(2026, 1, 15, 23, 0, tzinfo=UTC)

# ── UR-28.2 / UR-RES-09: идемпотентность одного локального дня ─────────────


class TestSameDateDedup:


    @pytest.mark.asyncio
    async def test_timezone_change_recomputes_future_slots_only(
            self, claims_db):
        """Смена пояса (UR-28.2/§4.5): прошедшие слоты не перепубликуются,
        БУДУЩИЕ слоты пересчитываются на новый пояс чата (12:00 Berlin
        стреляет в 11:00 UTC вместо 07:00 UTC)."""
        db = await claims_db()
        svc, gen, _ = _make_summary_service(db, targets=(CHAT_YEKA,))
        with _targets_patch((CHAT_YEKA,)):
            # До смены: 12:00 YEKA (07:00 UTC) уже вне due-окна → skip, без
            # запуска; будущие слоты ещё не наступили.
            before = datetime.datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)
            await svc._tick(now_utc=before)
            assert gen.generate_and_send.await_count == 0
            # Владелец переносит чат в Europe/Berlin.
            set_chat_override(CHAT_YEKA,
                              {"limits.chat_timezone": "Europe/Berlin"})
            after = datetime.datetime(2026, 1, 15, 11, 0, 30, tzinfo=UTC)
            await svc._tick(now_utc=after)
        assert gen.generate_and_send.await_count == 1, (
            "будущий слот 12:00 пересчитан в новый пояс (11:00 UTC) и "
            "запущен один раз")
        store = SqliteSlotClaimStore(db.db_path)
        row = store.lookup(kind="summary", chat_id=CHAT_YEKA,
                           local_date="2026-01-15", local_slot="12:00")
        assert row is not None and row["fired"] == 1
        assert row["slot_utc_instant"] == int(datetime.datetime(
            2026, 1, 15, 11, 0, 0, tzinfo=UTC).timestamp())
        await db.close()

    @pytest.mark.asyncio
    async def test_same_slot_fires_once_across_ticks_and_restart(
            self, claims_db):
        """Повторный тик и «рестарт» (новый инстанс сервиса, та же БД)
        не создают дубль публикации того же слота."""
        db = await claims_db()
        svc, gen, _ = _make_summary_service(db, targets=(CHAT_YEKA,))
        with _targets_patch((CHAT_YEKA,)):
            await svc._tick(now_utc=DUE_YEKA_18)
            await svc._tick(now_utc=DUE_YEKA_18 + datetime.timedelta(seconds=60))
            # Рестарт: свежий сервис/генератор, общая БД claim'ов.
            svc2, gen2, _ = _make_summary_service(db, targets=(CHAT_YEKA,))
            await svc2._tick(now_utc=DUE_YEKA_18
                             + datetime.timedelta(seconds=80))
        assert gen.generate_and_send.await_count == 1
        assert gen2.generate_and_send.await_count == 0
        await db.close()

    @pytest.mark.asyncio
    async def test_claim_is_atomic_single_winner(self, claims_db):
        """Атомарность claim: INSERT OR IGNORE по PK — второй претендент
        (конкурентный воркер/повторный тик) слот не получает."""
        db = await claims_db()
        store = SqliteSlotClaimStore(db.db_path)
        slot_instant = int(datetime.datetime(
            2026, 1, 15, 17, 0, 0, tzinfo=UTC).timestamp())
        first = store.try_claim(
            kind="summary", chat_id=CHAT_YEKA, local_date="2026-01-15",
            local_slot="18:00", slot_utc_instant=slot_instant,
            config_version="cv1", claimed_at=slot_instant + 30, fired=True)
        second = store.try_claim(
            kind="summary", chat_id=CHAT_YEKA, local_date="2026-01-15",
            local_slot="18:00", slot_utc_instant=slot_instant,
            config_version="cv2", claimed_at=slot_instant + 60, fired=True)
        assert first is True and second is False
        row = store.lookup(kind="summary", chat_id=CHAT_YEKA,
                           local_date="2026-01-15", local_slot="18:00")
        assert row["config_version"] == "cv1", (
            "первый победитель сохранён; fold/смена пояса не пере-claim'уют")
        await db.close()


# ── UR-28.3: просроченный слот — честный skip, не пачка ────────────────────


class TestMissedSlotExpired:
    @pytest.mark.asyncio
    async def test_expired_slot_skipped_once_with_reason(self, claims_db,
                                                         caplog):
        db = await claims_db()
        svc, gen, _ = _make_summary_service(db, targets=(CHAT_YEKA,))
        late = datetime.datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)
        with _targets_patch((CHAT_YEKA,)), caplog.at_level(
                logging.INFO, logger="services.slot_claims"):
            await svc._tick(now_utc=late)
            await svc._tick(now_utc=late + datetime.timedelta(minutes=1))
        assert gen.generate_and_send.await_count == 0, (
            "вне due-окна саммари не запускается (нет пачки просроченных)")
        store = SqliteSlotClaimStore(db.db_path)
        row = store.lookup(kind="summary", chat_id=CHAT_YEKA,
                           local_date="2026-01-15", local_slot="18:00")
        assert row is not None and row["fired"] == 0
        assert row["reason_code"] == "missed_slot_expired"
        skip_logs = [r for r in caplog.records
                     if "action=skip_expired" in r.getMessage()]
        assert len(skip_logs) == 1, "честный skip фиксируется ровно один раз"
        await db.close()


# ── UR-28.5: Goodmorning — GOODMORNING_TIME + ChatClock чата ───────────────


class TestGoodmorningPerChat:
    def _service(self, db, chat_ids, targets):
        relay = MagicMock()
        relay.send_goodmorning = AsyncMock(return_value=True)
        svc = GoodmorningSchedulerService(
            relay=relay, time_str="07:30", target_chat_ids=targets, db=db)
        return svc, relay

    @pytest.mark.asyncio
    async def test_goodmorning_time_hour_semantics_per_chat_tz(
            self, claims_db):
        """GOODMORNING_TIME 07:30 остаётся часом рассылки; каждый чат
        получает его в СВОЁМ поясе (Yeka 02:30 UTC, Berlin 06:30 UTC);
        дедуп: второе «утро» того же дня не отправляется."""
        db = await claims_db()
        set_chat_override(CHAT_BERLIN,
                          {"limits.chat_timezone": "Europe/Berlin"})
        svc, relay = self._service(db, None, (CHAT_YEKA, CHAT_BERLIN))
        gm_yeka = datetime.datetime(2026, 1, 15, 2, 30, 30, tzinfo=UTC)
        gm_berlin = datetime.datetime(2026, 1, 15, 6, 30, 30, tzinfo=UTC)
        await svc._tick(now_utc=gm_yeka)
        calls = [c.args[0] for c in relay.send_goodmorning.await_args_list]
        assert calls == [CHAT_YEKA]
        await svc._tick(now_utc=gm_berlin)
        calls = [c.args[0] for c in relay.send_goodmorning.await_args_list]
        assert calls == [CHAT_YEKA, CHAT_BERLIN]
        # Дедуп: повторный тик того же дня — без повторной отправки.
        await svc._tick(now_utc=gm_berlin + datetime.timedelta(seconds=60))
        calls = [c.args[0] for c in relay.send_goodmorning.await_args_list]
        assert calls == [CHAT_YEKA, CHAT_BERLIN]
        await db.close()

    @pytest.mark.asyncio
    async def test_goodmorning_gate_preserved_and_slot_not_consumed(
            self, claims_db, monkeypatch):
        """Per-chat gate «Расписания» (permsoc) сохранён; гейт стоит ДО
        claim: выключенный чат не съедает слот дня (нет строки claim)."""
        from services import permsoc
        db = await claims_db()
        async def _off(chat_id, block):
            return False
        monkeypatch.setattr(permsoc, "block_enabled", _off)
        svc, relay = self._service(db, None, (CHAT_YEKA,))
        gm_yeka = datetime.datetime(2026, 1, 15, 2, 30, 30, tzinfo=UTC)
        await svc._tick(now_utc=gm_yeka)
        relay.send_goodmorning.assert_not_called()
        store = SqliteSlotClaimStore(db.db_path)
        assert store.lookup(kind="goodmorning", chat_id=CHAT_YEKA,
                            local_date="2026-01-15",
                            local_slot="07:30") is None
        await db.close()

    @pytest.mark.asyncio
    async def test_goodmorning_expired_morning_no_night_catchup(
            self, claims_db):
        """Дедуп/семантика прежнего cron: после due-окна GOODMORNING_TIME
        «утро» не догоняется ночью (честный skip missed_slot_expired)."""
        db = await claims_db()
        svc, relay = self._service(db, None, (CHAT_YEKA,))
        late = datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        await svc._tick(now_utc=late)
        relay.send_goodmorning.assert_not_called()
        store = SqliteSlotClaimStore(db.db_path)
        row = store.lookup(kind="goodmorning", chat_id=CHAT_YEKA,
                           local_date="2026-01-15", local_slot="07:30")
        assert row is not None and row["fired"] == 0
        assert row["reason_code"] == "missed_slot_expired"
        await db.close()


# ── Миграция v42 (аддитивный seam БД) ──────────────────────────────────────


class TestSlotClaimsMigrationV42:
    @pytest.mark.asyncio
    async def test_v42_creates_table_and_repeat_is_noop(self, tmp_path):
        path = str(tmp_path / "v42.db")
        db = DatabaseService(path)
        await db.initialize()
        cursor = await db.db.execute("PRAGMA user_version")
        # Хвост схемы: v42 (эта полоса) + v43 (MEMORY-02, mca_entity_canonical)
        # + v44 (MEMORY-07, mca_community_*) + v45 (VMQ-V, transcript revision).
        latest = max(s.version for s in DatabaseService.migration_steps())
        assert (await cursor.fetchone())[0] == latest == 45
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (SLOT_CLAIMS_TABLE,))
        assert (await cursor.fetchone()) is not None
        await db.close()
        # Повторный init — no-op.
        db2 = DatabaseService(path)
        await db2.initialize()
        cursor = await db2.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == latest == 45
        await db2.close()


# ── Наблюдаемость решения (R17: без текстов чата) ──────────────────────────


class TestSchedSlotObservability:
    @pytest.mark.asyncio
    async def test_fire_log_contains_resolved_zone_and_slot(self, claims_db,
                                                            caplog):
        db = await claims_db()
        set_chat_override(CHAT_BERLIN,
                          {"limits.chat_timezone": "Europe/Berlin"})
        svc, gen, _ = _make_summary_service(db, targets=(CHAT_BERLIN,))
        with _targets_patch((CHAT_BERLIN,)), caplog.at_level(
                logging.INFO, logger="services.slot_claims"):
            await svc._tick(now_utc=DUE_BERLIN_18)
        texts = [r.getMessage() for r in caplog.records
                 if "[sched_slot]" in r.getMessage()]
        assert any("action=fire" in t for t in texts)
        rec = next(t for t in texts if "action=fire" in t)
        assert "tz=Europe/Berlin" in rec
        assert "tz_source=chat" in rec
        assert "local_date=2026-01-15" in rec
        assert "slot=18:00" in rec
        assert "slot_utc=2026-01-15T17:00:00Z" in rec
        await db.close()


# ── next_due_utc (для UI «Следующий запуск», UR-28.4/UR-29 — later wave) ───


class TestNextDue:
    @pytest.mark.asyncio
    async def test_next_due_uses_chat_zone(self, monkeypatch):
        set_chat_override(CHAT_BERLIN,
                          {"limits.chat_timezone": "Europe/Berlin"})
        now = datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)  # 13:00 Berlin
        nxt = await slot_claims.next_due_utc(
            CHAT_BERLIN, ((0, 0), (6, 0), (12, 0), (18, 0)), now_utc=now)
        assert nxt == datetime.datetime(2026, 1, 15, 17, 0, 0, tzinfo=UTC)
