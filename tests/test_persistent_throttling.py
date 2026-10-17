"""Epic 60 Фаза A (Section 63.1/63.6, T-460) — персистентный троттлинг.

PersistentCooldownTracker + PersistentThrottle поверх таблицы
throttle_state: состояние переживает рестарт (стена time.time), атомарный
UPSERT (refill+consume одним стейтментом, RETURNING), fail-open при ошибке
БД, изоляция scope/chat/user. Тест-план 63.6 #3/#4.
"""
import asyncio
import logging

import pytest

from services.database import DatabaseService
from services.persistent_throttling import (
    PersistentCooldownTracker,
    PersistentThrottle,
    make_cooldown,
    normalize_direct_chat_limits,
    resolve_direct_chat_limits,
    throttle_refresh,
)
from services.smartmodule_throttling import CooldownTracker

CHAT_ID = -1001234567890
# TEST-LIFECYCLE: REGRESSION owner=CFG-01/F1..F7 (§01.1–§01.5)


@pytest.fixture
def fake_wall(monkeypatch):
    """Заменяем time.time() в persistent_throttling на управляемую стену."""
    state = {"now": 1_800_000_000.0}

    class FakeTime:
        @staticmethod
        def time():
            return state["now"]

    monkeypatch.setattr("services.persistent_throttling.time", FakeTime)
    return state


class _FakeHotCache:
    """ConfigCache-двойник (глобальный слой; POST /api/config → hot-reload)."""

    def __init__(self, values):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


def _fake_hot_cache(monkeypatch, values):
    from services import hot_config as hot
    fake = _FakeHotCache(values)
    monkeypatch.setattr(hot, "_cache", fake)
    return fake


def _fake_chat_params(monkeypatch, overrides_by_chat):
    """Per-chat слой (chat_params) — только override'ы указанных чатов.

    Хранит словарь ПО ССЫЛКЕ: тест может менять слой (удаление override,
    reset to inherited) и наблюдать поведение без рестарта."""
    from services import chat_params

    class _FakeChatParamsCache:
        def __init__(self, by_chat):
            self._by_chat = by_chat if by_chat is not None else {}

        async def get_chat_params(self, chat_id):
            return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}

    fake = _FakeChatParamsCache(overrides_by_chat)
    monkeypatch.setattr(chat_params, "_chat_params_cache", fake)
    return fake


class BrokenDB:
    """Заглушка мёртвой БД для fail-open-тестов (операции бросают)."""

    class Conn:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("db is dead")

        async def commit(self):
            raise RuntimeError("db is dead")

    def __init__(self):
        self.db = self.Conn()


async def _new_db(path):
    d = DatabaseService(str(path))
    await d.initialize()
    return d


class TestPersistentCooldownTracker:
    """63.6 #3: семантики CooldownTracker сохранены + рестарт не сбрасывает
    кулдаун (стена)."""

    @pytest.mark.asyncio
    async def test_remaining_zero_before_touch(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "c0.db")
        tracker = PersistentCooldownTracker(300.0, "search", d)
        assert await tracker.remaining(CHAT_ID, 10) == 0.0
        await d.close()

    @pytest.mark.asyncio
    async def test_remaining_positive_after_touch(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "c1.db")
        tracker = PersistentCooldownTracker(300.0, "search", d)
        await tracker.touch(CHAT_ID, 10)
        fake_wall["now"] += 30
        assert await tracker.remaining(CHAT_ID, 10) == pytest.approx(270.0)
        await d.close()

    @pytest.mark.asyncio
    async def test_expires_after_ttl(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "c2.db")
        tracker = PersistentCooldownTracker(300.0, "search", d)
        await tracker.touch(CHAT_ID, 10)
        fake_wall["now"] += 301
        assert await tracker.remaining(CHAT_ID, 10) == 0.0
        await d.close()

    @pytest.mark.asyncio
    async def test_remaining_never_negative(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "c3.db")
        tracker = PersistentCooldownTracker(300.0, "search", d)
        await tracker.touch(CHAT_ID, 10)
        fake_wall["now"] += 99999
        assert await tracker.remaining(CHAT_ID, 10) == 0.0
        await d.close()

    @pytest.mark.asyncio
    async def test_key_is_chat_and_user(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "c4.db")
        tracker = PersistentCooldownTracker(300.0, "search", d)
        await tracker.touch(CHAT_ID, 10)
        assert await tracker.remaining(CHAT_ID, 10) > 0
        assert await tracker.remaining(CHAT_ID + 1, 10) == 0.0
        assert await tracker.remaining(CHAT_ID, 11) == 0.0
        await d.close()

    @pytest.mark.asyncio
    async def test_touch_updates_slot(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "c5.db")
        tracker = PersistentCooldownTracker(300.0, "search", d)
        await tracker.touch(CHAT_ID, 10)
        fake_wall["now"] += 200
        await tracker.touch(CHAT_ID, 10)   # повторный валидный триггер продлевает окно
        fake_wall["now"] += 200
        assert await tracker.remaining(CHAT_ID, 10) > 0
        await d.close()

    @pytest.mark.asyncio
    async def test_scopes_isolated_in_same_table(self, tmp_path, fake_wall):
        """Два scope в одной таблице throttle_state не мешают друг другу."""
        d = await _new_db(tmp_path / "c6.db")
        search = PersistentCooldownTracker(300.0, "search", d)
        factcheck = PersistentCooldownTracker(300.0, "factcheck", d)
        await search.touch(CHAT_ID, 10)
        assert await search.remaining(CHAT_ID, 10) > 0
        assert await factcheck.remaining(CHAT_ID, 10) == 0.0
        await d.close()

    @pytest.mark.asyncio
    async def test_touch_survives_restart(self, tmp_path, fake_wall):
        """63.6 #3: новый инстанс на той же БД — кулдаун НЕ сброшен."""
        path = tmp_path / "restart.db"
        d1 = await _new_db(path)
        tracker = PersistentCooldownTracker(300.0, "search", d1)
        await tracker.touch(CHAT_ID, 10)
        await d1.close()

        d2 = await _new_db(path)                       # «рестарт»
        tracker2 = PersistentCooldownTracker(300.0, "search", d2)
        assert await tracker2.remaining(CHAT_ID, 10) == pytest.approx(300.0)
        fake_wall["now"] += 100.0
        assert await tracker2.remaining(CHAT_ID, 10) == pytest.approx(200.0)
        fake_wall["now"] += 200.0
        assert await tracker2.remaining(CHAT_ID, 10) == 0.0
        await d2.close()


class TestPersistentThrottle:
    """Token Bucket (R50-7) поверх throttle_state: те же семантики, что у
    DirectChatThrottle, + переживает рестарт."""

    @pytest.mark.asyncio
    async def test_burst_limit_exhausted(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "t0.db")
        t = PersistentThrottle(3, 300.0, "direct_chat", d)
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) == 0.0
        denied = await t.allow(CHAT_ID, 10)
        assert denied == 300.0                # ceil-по-остатку, ничего не прошло
        await d.close()

    @pytest.mark.asyncio
    async def test_denied_does_not_spend_charges(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "t1.db")
        t = PersistentThrottle(1, 300.0, "direct_chat", d)
        assert await t.allow(CHAT_ID, 10) == 0.0
        fake_wall["now"] += 10
        assert await t.allow(CHAT_ID, 10) > 0
        fake_wall["now"] += 10
        assert await t.allow(CHAT_ID, 10) > 0   # по-прежнему denied (заряд не списан)
        await d.close()

    @pytest.mark.asyncio
    async def test_full_refill_after_cooldown(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "t2.db")
        t = PersistentThrottle(3, 300.0, "direct_chat", d)
        for _ in range(3):
            assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) > 0
        fake_wall["now"] += 300.0             # cooldown прошёл → полное восстановление
        assert await t.allow(CHAT_ID, 10) == 0.0
        await d.close()

    @pytest.mark.asyncio
    async def test_remaining_is_ceiled_cooldown_elapsed(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "t3.db")
        t = PersistentThrottle(1, 300.0, "direct_chat", d)
        assert await t.allow(CHAT_ID, 10) == 0.0
        fake_wall["now"] += 100.0
        assert await t.allow(CHAT_ID, 10) == 200.0
        await d.close()

    @pytest.mark.asyncio
    async def test_isolation_per_chat_and_user(self, tmp_path, fake_wall):
        d = await _new_db(tmp_path / "t4.db")
        t = PersistentThrottle(3, 300.0, "direct_chat", d)
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 20) == 0.0      # другой юзер — свой слот
        assert await t.allow(CHAT_ID - 1, 10) == 0.0  # другой чат — свой слот
        await d.close()

    @pytest.mark.asyncio
    async def test_bucket_survives_restart(self, tmp_path, fake_wall):
        """63.6 #5: заряды НЕ восстанавливаются рестартом; полный refill —
        только по истечении cooldown."""
        path = tmp_path / "t_restart.db"
        d1 = await _new_db(path)
        t1 = PersistentThrottle(3, 300.0, "direct_chat", d1)
        for _ in range(3):
            assert await t1.allow(CHAT_ID, 10) == 0.0
        await d1.close()

        d2 = await _new_db(path)                       # «рестарт»
        t2 = PersistentThrottle(3, 300.0, "direct_chat", d2)
        assert await t2.allow(CHAT_ID, 10) > 0         # кулдаун не сброшен
        fake_wall["now"] += 300.0
        assert await t2.allow(CHAT_ID, 10) == 0.0      # refill после кулдауна
        await d2.close()

    @pytest.mark.asyncio
    async def test_concurrent_allows_atomic(self, tmp_path, fake_wall):
        """63.6 #4: N конкурентных await-ов не дают лишних зарядов — РОВНО
        capacity допусков (UPSERT RETURNING атомарен, SELECT-then-UPDATE нет)."""
        d = await _new_db(tmp_path / "atomic.db")
        t = PersistentThrottle(3, 300.0, "direct_chat", d)
        results = await asyncio.gather(
            *(t.allow(CHAT_ID, 10) for _ in range(10)))
        assert sorted(results) == [0.0, 0.0, 0.0] + [300.0] * 7
        cursor = await d.db.execute(
            "SELECT burst_left, last_ts FROM throttle_state "
            "WHERE scope = 'direct_chat' AND chat_id = ? AND user_id = ?",
            (CHAT_ID, 10))
        row = await cursor.fetchone()
        assert row["burst_left"] == 0                  # бакет исчерпан ровно до 0
        assert row["last_ts"] == fake_wall["now"]      # последний допуск — стена
        await d.close()


class TestFailOpen:
    """63.1: ошибки БД → WARNING + пропуск кулдауна (fail-open — троттлинг
    НЕ роняет хендлер; прецедент SmartCache)."""

    @pytest.mark.asyncio
    async def test_remaining_fail_open(self, caplog):
        tracker = PersistentCooldownTracker(300.0, "search", BrokenDB())
        with caplog.at_level(logging.WARNING):
            assert await tracker.remaining(CHAT_ID, 10) == 0.0
        assert any("fail-open" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_touch_fail_open_no_raise(self, caplog):
        tracker = PersistentCooldownTracker(300.0, "search", BrokenDB())
        with caplog.at_level(logging.WARNING):
            await tracker.touch(CHAT_ID, 10)           # не бросает
        assert any("fail-open" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_allow_fail_open(self, caplog):
        throttle = PersistentThrottle(3, 300.0, "direct_chat", BrokenDB())
        with caplog.at_level(logging.WARNING):
            assert await throttle.allow(CHAT_ID, 10) == 0.0
        assert any("fail-open" in r.message for r in caplog.records)


class TestMakeCooldown:
    """63.1: рубильник THROTTLE_PERSISTENT_ENABLED."""

    def test_enabled_with_db_returns_persistent(self, monkeypatch):
        import config.settings as settings_module
        monkeypatch.setattr(
            "services.persistent_throttling.settings",
            settings_module.Settings(THROTTLE_PERSISTENT_ENABLED=True))
        tracker = make_cooldown("search", 300.0, object())
        assert isinstance(tracker, PersistentCooldownTracker)

    def test_disabled_returns_in_memory(self, monkeypatch):
        import config.settings as settings_module
        monkeypatch.setattr(
            "services.persistent_throttling.settings",
            settings_module.Settings(THROTTLE_PERSISTENT_ENABLED=False))
        tracker = make_cooldown("search", 300.0, object())
        assert isinstance(tracker, CooldownTracker)
        assert not isinstance(tracker, PersistentCooldownTracker)

    def test_enabled_without_db_returns_in_memory(self, monkeypatch):
        import config.settings as settings_module
        monkeypatch.setattr(
            "services.persistent_throttling.settings",
            settings_module.Settings(THROTTLE_PERSISTENT_ENABLED=True))
        tracker = make_cooldown("search", 300.0, None)
        assert isinstance(tracker, CooldownTracker)


class TestCfg01EffectiveLimits:
    """CFG-01 (§01.1–§01.5): effective-лимиты Direct Chat — hot-reload
    (per-chat override → global ConfigCache → factory), кламп зарядов без
    сброса состояния, документированные границы. TEST-LIFECYCLE: REGRESSION
    owner=CFG-01 (§01.2/§01.4/§01.5)."""

    def test_normalize_bounds(self):
        """§01.4: единицы/границы — burst ≥ 1 (0/-1/мусор → 1, вечного лока
        нет), cooldown ≥ 0 сек (0 = без паузы, отрицательные/NaN → 0)."""
        assert normalize_direct_chat_limits(10, 300.0) == (10, 300.0)
        assert normalize_direct_chat_limits("10", "300") == (10, 300.0)
        assert normalize_direct_chat_limits(0, -5) == (1, 0.0)
        assert normalize_direct_chat_limits(-1, float("nan")) == (1, 0.0)
        assert normalize_direct_chat_limits(None, None) == (1, 0.0)
        assert normalize_direct_chat_limits(2, 0) == (2, 0.0)

    @pytest.mark.asyncio
    async def test_resolve_source_factory_without_layers(self, monkeypatch):
        """§01.1: слоёв нет (нет кэшей) → settings-дефолт, source='factory'."""
        _fake_hot_cache(monkeypatch, {})
        _fake_chat_params(monkeypatch, {})
        limit, cooldown, source = await resolve_direct_chat_limits(CHAT_ID)
        from config.settings import settings
        assert (limit, cooldown) == (settings.CHAT_BURST_LIMIT,
                                     settings.CHAT_COOLDOWN_SECONDS)
        assert source == "factory"

    @pytest.mark.asyncio
    async def test_resolve_global_then_chat_then_inherit(self, monkeypatch):
        """§01.3: override меняет ТОЛЬКО свой чат; удаление override
        возвращает наследование глобального значения (без рестарта)."""
        _fake_hot_cache(monkeypatch, {
            "limits.chat_burst_limit": 10,
            "limits.chat_cooldown_seconds": 300.0,
        })
        chat_overrides = {CHAT_ID: {"limits.chat_burst_limit": 2,
                                    "limits.chat_cooldown_seconds": 60.0}}
        _fake_chat_params(monkeypatch, chat_overrides)

        assert await resolve_direct_chat_limits(CHAT_ID) == (2, 60.0, "chat")
        # другой чат не затронут override'ом первого
        assert await resolve_direct_chat_limits(CHAT_ID - 1) == (
            10, 300.0, "global")

        chat_overrides.clear()                     # reset to inherited
        assert await resolve_direct_chat_limits(CHAT_ID) == (
            10, 300.0, "global")

    @pytest.mark.asyncio
    async def test_resolve_mixed_sources_reported(self, monkeypatch):
        """§01.6: источник показывается по КАЖДОМУ ключу (chat/global)."""
        _fake_hot_cache(monkeypatch, {"limits.chat_cooldown_seconds": 120.0})
        _fake_chat_params(monkeypatch, {
            CHAT_ID: {"limits.chat_burst_limit": 2}})
        limit, cooldown, source = await resolve_direct_chat_limits(CHAT_ID)
        assert (limit, cooldown) == (2, 120.0)
        assert source == "chat/global"

    @pytest.mark.asyncio
    async def test_fail_open_on_resolver_error(self, monkeypatch, caplog):
        """§01.5: ошибка резолва → settings-дефолты, ход не падает."""
        from services import chat_params

        class _Boom:
            async def get_chat_params(self, chat_id):
                raise RuntimeError("pg is dead")

        monkeypatch.setattr(chat_params, "_chat_params_cache", _Boom())
        with caplog.at_level(logging.WARNING):
            limit, cooldown, source = await resolve_direct_chat_limits(CHAT_ID)
        assert limit >= 1 and cooldown >= 0.0 and source == "factory"

    @pytest.mark.asyncio
    async def test_refresh_hot_reload_clamps_persistent_bucket(
            self, tmp_path, fake_wall):
        """AC1/§01.2 (RED→GREEN): burst 10 → 2 без рестарта — после смены
        лимита доступны ровно 2 обращения, третье ограничено; накопленные
        заряды старого лимита НЕ дают бонуса."""
        d = await _new_db(tmp_path / "reload.db")
        t = PersistentThrottle(10, 300.0, "direct_chat", d)
        for _ in range(5):                          # 5 из 10 израсходовано
            assert await t.allow(CHAT_ID, 10) == 0.0

        t.refresh(2, 300.0)                         # MiniApp: 10 → 2
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) == 0.0
        denied = await t.allow(CHAT_ID, 10)
        assert denied > 0                           # третий — ограничен
        assert denied <= 300.0                      # остаток не превышает паузу

        fake_wall["now"] += 301.0                   # пауза истекла
        assert await t.allow(CHAT_ID, 10) == 0.0    # новое окно по лимиту 2
        await d.close()

    @pytest.mark.asyncio
    async def test_refresh_new_cooldown_applies_to_active_state(
            self, tmp_path, fake_wall):
        """§01.2: смена паузы не сбрасывает состояние — она пересчитывает
        остаток активного кулдауна (документированная политика, не
        случайный сброс)."""
        d = await _new_db(tmp_path / "cooldown.db")
        t = PersistentThrottle(1, 300.0, "direct_chat", d)
        assert await t.allow(CHAT_ID, 10) == 0.0
        fake_wall["now"] += 100.0
        assert await t.allow(CHAT_ID, 10) == 200.0   # пауза 300 → остаток 200

        t.refresh(1, 120.0)                          # пауза 300 → 120
        assert await t.allow(CHAT_ID, 10) == 20.0    # состояние не сброшено
        fake_wall["now"] += 21.0
        assert await t.allow(CHAT_ID, 10) == 0.0     # новая пауза истекла
        await d.close()

    @pytest.mark.asyncio
    async def test_refresh_limit_increase_no_bonus_in_window(
            self, tmp_path, fake_wall):
        """§01.2: увеличение лимита не выдаёт заряды до конца текущего окна
        (полное восстановление — по обычному правилу)."""
        d = await _new_db(tmp_path / "grow.db")
        t = PersistentThrottle(1, 300.0, "direct_chat", d)
        assert await t.allow(CHAT_ID, 10) == 0.0
        t.refresh(10, 300.0)
        assert await t.allow(CHAT_ID, 10) > 0        # бонуса нет
        fake_wall["now"] += 301.0
        assert await t.allow(CHAT_ID, 10) == 0.0     # новое окно открылось
        allowed = 1
        while allowed < 20 and await t.allow(CHAT_ID, 10) == 0.0:
            allowed += 1
        assert allowed == 10                         # окно = 10, не больше
        await d.close()

    @pytest.mark.asyncio
    async def test_throttle_refresh_tolerates_foreign_throttle(self):
        """§01.2: инъектированный throttle без `refresh` (DI-двойник) не
        ломается — helper молча пропускает."""
        class Foreign:
            def allow(self, chat_id, user_id):
                return 0.0

        throttle_refresh(Foreign(), 2, 60.0)         # не бросает
