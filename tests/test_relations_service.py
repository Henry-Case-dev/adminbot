"""Раунд 9 (AGI Memory, T-817/T-819-частично, spec §3.1.2/§3.1.4) —
RelationsService: manual ?? auto, ленивый пересчёт (TTL + last_recalc_at),
снапшоты, fail-open на PG-части.

Также каталожные счётчики раунда: группы flags_relations/limits_relations
и их ключи (spec §3.6.4) — парные Settings-дефолты.
"""
import asyncio
import time

import pytest

from services import lore_runtime
from services.database import DatabaseService
from services.lore_cache import LoreProfile
from services.user_relations import RelationsService

DAY = 86400
# «сейчас» — реальное время на момент импорта: refresh в ensure_fresh
# использует int(time.time()); пришлось бы смещать иначе (метки в будущее
# относительно БД дают days=0 и «неправильные» кандидаты стадий).
NOW = int(time.time())


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _DbAdapter:
    """Подмена db для подсчёта вызовов refresh (реальная БД — in-memory)."""

    def __init__(self, db):
        self._db = db
        self.refresh_calls: list = []
        self.get_calls: int = 0

    async def get_users_meta(self, chat_id, user_ids=None):
        self.get_calls += 1
        return await self._db.get_users_meta(chat_id, user_ids=user_ids)

    async def refresh_users_meta(self, chat_id, user_ids=None, *, now=None):
        self.refresh_calls.append((chat_id, tuple(user_ids or [])))
        return await self._db.refresh_users_meta(chat_id, user_ids=user_ids,
                                                 now=now)


class _FakeAliases:
    def resolve(self, user_id, nickname=None, username=None):
        return f"Алиас{user_id}"


class _FakeCache:
    def __init__(self, relations=None, enabled=True, error=False):
        self._relations = relations or {}
        self._enabled = enabled
        self._error = error

    async def get(self, chat_id):
        if self._error:
            raise RuntimeError("pg down (fake)")
        return LoreProfile(
            chat_id=chat_id, manual_lore="", auto_lore="",
            auto_enabled=True, auto_period_hours=24, auto_window_hours=24,
            is_active=True, last_auto_at=None,
            updated_at="2026-09-06T10:00:00+00:00",
            relations=dict(self._relations),
            relations_enabled=self._enabled)


class _FakeStore:
    def __init__(self, relations=None, error=False):
        self._relations = relations or {}
        self._error = error

    async def get_relations(self, chat_id):
        if self._error:
            raise RuntimeError("pg down (fake)")
        return dict(self._relations)


async def _add_msgs(db, chat_id, rows):
    for user_id, ts in rows:
        await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, timestamp, "
            "media_type) VALUES (?, ?, ?, 'text')", (user_id, chat_id, ts))
    await db.db.commit()


async def _seed_users(db, chat_id, users):
    """users: {uid: (msg_count, age_days_last)} — по сообщению в день."""
    rows = []
    for uid, (count, last_age) in users.items():
        rows += [(uid, NOW - last_age * DAY + i * DAY) for i in range(count)]
    await _add_msgs(db, chat_id, rows)


def make_service(db, *, cache=None, store=None, aliases=_FakeAliases()):
    return RelationsService(db, aliases=aliases, store=store, cache=cache)


class TestManualPrecedence:
    @pytest.mark.asyncio
    async def test_stage_for_manual_beats_auto(self, db):
        chat, uid = -100, 1
        await _seed_users(db, chat, {uid: (5, 3)})          # авто: stranger
        service = make_service(db, cache=_FakeCache({
            str(uid): {"manual_stage": "veteran", "note": "самый свой"}}))
        await db.refresh_users_meta(chat, [uid], now=NOW)
        assert await service.stage_for(chat, uid) == "veteran"

    @pytest.mark.asyncio
    async def test_get_user_relation_merges_manual(self, db):
        chat, uid = -101, 2
        await _seed_users(db, chat, {uid: (300, 120)})      # авто: regular
        service = make_service(db, cache=_FakeCache({
            str(uid): {"manual_stage": "veteran",
                       "note": "руками", "updated_by": 42}}))
        rel = await service.get_user_relation(chat, uid)
        assert rel["stage_auto"] == "regular"
        assert rel["stage_manual"] == "veteran"
        assert rel["stage"] == "veteran"
        assert rel["note"] == "руками"

    @pytest.mark.asyncio
    async def test_auto_when_no_manual(self, db):
        chat, uid = -102, 3
        await _seed_users(db, chat, {uid: (300, 120)})
        service = make_service(db, cache=_FakeCache({}))
        rel = await service.get_user_relation(chat, uid)
        assert rel["stage_manual"] is None
        assert rel["stage"] == rel["stage_auto"] == "regular"
        assert await service.stage_for(chat, uid) == "regular"

    @pytest.mark.asyncio
    async def test_unknown_user_returns_stranger(self, db):
        service = make_service(db, cache=_FakeCache({}))
        assert await service.stage_for(-103, 999) == "stranger"
        assert await service.get_user_relation(-103, 999) is None


class TestLazyRecalc:
    @pytest.mark.asyncio
    async def test_first_call_refreshes_missing_row(self, db):
        chat, uid = -200, 1
        await _add_msgs(db, chat, [(uid, NOW - 2 * DAY)])
        adapter = _DbAdapter(db)
        service = RelationsService(adapter)
        rows = await service.ensure_fresh(chat, [uid])
        assert uid in rows
        assert len(adapter.refresh_calls) == 1
        assert adapter.refresh_calls[0][1] == (uid,)

    @pytest.mark.asyncio
    async def test_recalc_ttl_gate_skips_fresh_rows(self, db):
        chat, uid = -201, 2
        await _add_msgs(db, chat, [(uid, NOW - 2 * DAY)])
        adapter = _DbAdapter(db)
        service = RelationsService(adapter)
        await service.ensure_fresh(chat, [uid])            # refresh #1
        # метим строку «свежей» (last_recalc_at = now) и сбрасываем RAM-кэш
        await db.db.execute(
            "UPDATE users_meta SET last_recalc_at = ? "
            "WHERE chat_id = ? AND user_id = ?",
            (int(time.time()), chat, uid))
        await db.db.commit()
        await service.invalidate(chat)
        rows = await service.ensure_fresh(chat, [uid])
        assert len(adapter.refresh_calls) == 1             # refresh НЕ вызван
        assert uid in rows

    @pytest.mark.asyncio
    async def test_expired_row_refreshes_again(self, db):
        chat, uid = -202, 3
        await _add_msgs(db, chat, [(uid, NOW - 2 * DAY)])
        adapter = _DbAdapter(db)
        service = RelationsService(adapter)
        await service.ensure_fresh(chat, [uid])            # refresh #1
        await db.db.execute(
            "UPDATE users_meta SET last_recalc_at = 0 "
            "WHERE chat_id = ? AND user_id = ?", (chat, uid))
        await db.db.commit()
        await service.invalidate(chat)
        await service.ensure_fresh(chat, [uid])            # refresh #2
        assert len(adapter.refresh_calls) == 2

    @pytest.mark.asyncio
    async def test_ram_cache_serves_without_db(self, db):
        chat, uid = -203, 4
        await _add_msgs(db, chat, [(uid, NOW - 2 * DAY)])
        adapter = _DbAdapter(db)
        service = RelationsService(adapter)
        await service.ensure_fresh(chat, [uid])
        calls_before = adapter.get_calls
        await service.ensure_fresh(chat, [uid])            # RAM-хит
        assert adapter.get_calls == calls_before
        assert adapter.refresh_calls and True

    @pytest.mark.asyncio
    async def test_chat_wide_fresh_uses_cached(self, db):
        chat = -204
        await _seed_users(db, chat, {1: (12, 3), 2: (12, 3)})
        adapter = _DbAdapter(db)
        service = RelationsService(adapter)
        rows = await service.ensure_fresh(chat)            # топ-N чата
        assert set(rows) == {1, 2}
        before = len(adapter.refresh_calls)
        rows2 = await service.ensure_fresh(chat)
        assert len(adapter.refresh_calls) == before
        assert set(rows2) == {1, 2}


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_fields_and_sorting(self, db):
        chat = -300
        # uid1 — свежий и «знакомый» (20 сообщений, 12+ дней), uid2 — старее
        await _seed_users(db, chat, {1: (20, 12), 2: (20, 60)})
        service = make_service(db, cache=_FakeCache({
            "1": {"manual_stage": "regular", "note": "закреп"}}))
        snap = await service.get_relations_snapshot(
            chat, names={1: "Вася", 2: "Петя"})
        assert [s["user_id"] for s in snap] == [1, 2]      # last_seen DESC
        first = snap[0]
        assert first["name"] == "Вася"                     # roster-каскад
        assert first["stage"] == "regular"                 # manual ?? auto
        assert first["stage_auto"] == "acquaintance"
        assert first["stage_manual"] == "regular"
        assert first["note"] == "закреп"
        assert isinstance(first["activity_score"], float)
        assert first["msg_count"] == 20
        assert first["first_seen"] and first["last_seen"]

    @pytest.mark.asyncio
    async def test_snapshot_names_fallback_alias_then_uid(self, db):
        chat = -301
        await _seed_users(db, chat, {7: (2, 1)})
        service = make_service(db, aliases=_FakeAliases())
        snap = await service.get_relations_snapshot(chat)
        assert snap[0]["name"] == "Алиас7"
        # без алиасов — uid строкой
        service2 = RelationsService(db)
        await db.refresh_users_meta(chat, now=NOW)
        snap2 = await service2.get_relations_snapshot(chat)
        assert snap2[0]["name"] == "7"

    @pytest.mark.asyncio
    async def test_fail_open_when_pg_down(self, db):
        chat, uid = -302, 5
        await _seed_users(db, chat, {uid: (300, 120)})
        service = make_service(db, store=_FakeStore(error=True),
                               cache=None)
        rel = await service.get_user_relation(chat, uid)
        assert rel["stage"] == "regular"                   # авто живёт
        assert rel["stage_manual"] is None
        snap = await service.get_relations_snapshot(chat)
        assert snap[0]["note"] is None

    @pytest.mark.asyncio
    async def test_fail_open_when_cache_errors(self, db):
        chat, uid = -303, 6
        await _seed_users(db, chat, {uid: (300, 120)})
        service = make_service(db, cache=_FakeCache(error=True))
        assert await service.stage_for(chat, uid) == "regular"

    @pytest.mark.asyncio
    async def test_snapshot_manual_blocks_but_keeps_auto_column(self, db):
        """Q5 п.4: manual блокирует авто в инжекте, но relationship_stage/
        last_stage_change в users_meta не трогаются (сброс manual → авто из
        колонки)."""
        chat, uid = -304, 8
        await _seed_users(db, chat, {uid: (5, 3)})
        await db.refresh_users_meta(chat, [uid], now=NOW)
        assert (await db.get_user_meta(chat, uid))["relationship_stage"] \
            == "stranger"
        service = make_service(db, cache=_FakeCache(
            {str(uid): {"manual_stage": "veteran"}}))
        assert await service.stage_for(chat, uid) == "veteran"
        assert (await db.get_user_meta(chat, uid))["relationship_stage"] \
            == "stranger"     # колонка не тронута


class TestLoreRuntimeExtensions:
    @pytest.mark.asyncio
    async def test_set_and_get_db_and_relations(self):
        db_obj = object()
        rel_obj = object()
        lore_runtime.set_lore_components(db=db_obj, relations=rel_obj)
        try:
            assert lore_runtime.get_lore_db() is db_obj
            assert lore_runtime.get_relations_service() is rel_obj
            # старые компоненты не затронуты
            assert lore_runtime.get_lore_store() is None
        finally:
            lore_runtime.reset_lore_runtime()
        assert lore_runtime.get_lore_db() is None
        assert lore_runtime.get_relations_service() is None


class TestRelationsCatalog:
    def test_limits_relations_group_keys(self):
        from config.settings import Settings
        from services import param_catalog as pc
        import dataclasses
        fields = {f.name for f in dataclasses.fields(Settings)}
        expected = {
            "RELATIONS_ACQUAINTANCE_MIN_MSG": 10,
            "RELATIONS_ACQUAINTANCE_MIN_DAYS": 7,
            "RELATIONS_REGULAR_MIN_MSG": 200,
            "RELATIONS_REGULAR_MIN_DAYS": 90,
            "RELATIONS_VETERAN_MIN_MSG": 1000,
            "RELATIONS_VETERAN_MIN_DAYS": 365,
            "RELATIONS_HOLD_ABSENT_DAYS": 60,
            "RELATIONS_STAGE_CHANGE_MIN_DAYS": 30,
            "RELATIONS_DOWNGRADE_MSG_30D": 10,
            "RELATIONS_DECAY_HALF_LIFE_DAYS": 14,
            "RELATIONS_RECALC_TTL_MINUTES": 5,
            "RELATIONS_SCAN_MAX_ROWS": 50000,
            "RELATIONS_INJECT_MAX_CHARS": 600,
            "RELATIONS_API_MAX_USERS": 150,
        }
        # дефолты Settings == spec §3.6.4
        s = Settings()
        for field, default in expected.items():
            assert getattr(s, field) == default, field
        # ровно 14 limits_relations-ключей, все категории limits/группа
        limits_keys = [k for k, spec in pc.REGISTRY.items()
                       if spec.group == "limits_relations"]
        assert len(limits_keys) == 14
        for field in expected:
            spec = pc.get(field)
            assert spec is not None and spec.category == pc.CATEGORY_LIMITS
            assert spec.group == "limits_relations"
        # ровно 1 флаг группы flags_relations (spec Q12: relations_tone_enabled)
        flag_keys = [k for k, spec in pc.REGISTRY.items()
                     if spec.group == "flags_relations"]
        assert flag_keys == ["RELATIONS_TONE_ENABLED"]
        flag = pc.get("RELATIONS_TONE_ENABLED")
        assert flag.category == pc.CATEGORY_FLAGS
        assert s.RELATIONS_TONE_ENABLED is False          # дефолт консервативен
        # группы существуют и разложены по вкладкам (TAB_RULES не менялся)
        group = pc.get_group("limits_relations")
        assert group is not None and group.category == "limits"
        assert pc.get_group("flags_relations") is not None
        assert pc.group_tab("limits_relations") == pc.TAB_LIMITS
        assert pc.group_tab("flags_relations") == pc.TAB_LIMITS
