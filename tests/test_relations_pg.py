"""Раунд 9 (AGI Memory, T-818, spec §3.1.3, D-2/D-3) — PG relations.

Покрытие: два аддитивных ALTER в DDL_STATEMENTS (идемпотентность на
существующей и новой БД), store-методы get_relations/put_relation/
delete_relation/set_relation_manual/set_relations_enabled (Python-merge +
UPDATE с optimistic-WHERE → 409), аудит updated_by/updated_at внутри JSONB,
NOTIFY, ensure-семантика при отсутствии профиля, LoreProfile (+relations/
relations_enabled). Пул — in-memory фейк (прецедент test_chat_lore_store).
"""
import pytest

from services import pg_db as pg_mod
from services.chat_lore_store import (
    ChatLoreConflict,
    ChatLoreStore,
    MANUAL_STAGES,
)
from services.lore_cache import LoreProfile
from services.pg_db import DDL_STATEMENTS
from tests.test_chat_lore_store import _FakeConn, make_store

# ── DDL-проверки ────────────────────────────────────────────────────────────


class TestRelationsDdl:
    def test_two_idempotent_alters_present(self):
        alters = [s for s in DDL_STATEMENTS if "ALTER TABLE chat_profiles" in s]
        assert len(alters) == 2
        assert "ADD COLUMN IF NOT EXISTS relations JSONB NOT NULL DEFAULT" \
            in alters[0]
        assert "ADD COLUMN IF NOT EXISTS relations_enabled BOOLEAN" \
            in alters[1]
        assert "NOT NULL DEFAULT FALSE" in alters[1]

    def test_create_does_not_claim_new_columns(self):
        """CREATE chat_profiles без relations — колонки даёт только ALTER
        (идемпотентен и на существующей БД, и на новой: PG ADD COLUMN IF
        NOT EXISTS выполняется на старте для всех)."""
        create = next(s for s in DDL_STATEMENTS
                      if "CREATE TABLE IF NOT EXISTS chat_profiles" in s)
        assert "relations" not in create

    def test_alters_are_idempotent_and_applyable(self):
        """Тексты операторов — идемпотентные ADD COLUMN IF NOT EXISTS
        (применяются на старте вместе со всеми DDL_STATEMENTS, pg_db init)."""
        import re
        for statement in DDL_STATEMENTS:
            if not statement.lstrip().startswith("ALTER TABLE chat_profiles"):
                continue
            flat = re.sub(r"\s+", " ", statement).strip()
            assert flat.startswith(
                "ALTER TABLE chat_profiles ADD COLUMN IF NOT EXISTS")


# ── Store: relations (фейк-пул) ─────────────────────────────────────────────


@pytest.fixture
def conn():
    return _FakeConn()


@pytest.fixture
def store(conn):
    return make_store(conn)


class TestPutGetRelations:
    @pytest.mark.asyncio
    async def test_put_relation_creates_profile_and_entry(self, store):
        chat, user = -100, 123456
        profile = await store.put_relation(
            chat, user, stage="regular", note="свой человек",
            updated_by=5885953495)
        assert isinstance(profile, LoreProfile)
        assert profile.relations_enabled is False
        entry = profile.relations[str(user)]
        assert entry["manual_stage"] == "regular"
        assert entry["note"] == "свой человек"
        assert entry["updated_by"] == 5885953495     # аудит в JSONB (D-2)
        assert entry["updated_at"]                    # ISO-метка правки
        assert profile.updated_at                    # optimistic-метка bumped

    @pytest.mark.asyncio
    async def test_get_relations_empty_and_missing_profile(self, store):
        assert await store.get_relations(-100) == {}
        assert await store.get_relation_manual(-100, 1) is None

    @pytest.mark.asyncio
    async def test_python_merge_keeps_other_keys(self, store):
        chat, a, b = -200, 1, 2
        await store.put_relation(chat, a, stage="veteran", note="старик")
        await store.put_relation(chat, b, stage="acquaintance")
        relations = await store.get_relations(chat)
        assert set(relations) == {"1", "2"}
        assert relations["1"]["manual_stage"] == "veteran"
        assert relations["1"]["note"] == "старик"
        assert relations["2"]["manual_stage"] == "acquaintance"

    @pytest.mark.asyncio
    async def test_put_updates_existing_entry_inplace(self, store):
        chat, user = -300, 7
        p1 = await store.put_relation(chat, user, stage="regular",
                                      note="old note", updated_by=1)
        p2 = await store.put_relation(chat, user, stage="veteran",
                                      note=None, updated_by=2,
                                      expected_updated_at=p1.updated_at)
        entry = (await store.get_relations(chat))[str(user)]
        assert entry["manual_stage"] == "veteran"
        assert entry["note"] is None
        assert entry["updated_by"] == 2
        assert p2.updated_at != p1.updated_at

    @pytest.mark.asyncio
    async def test_conflict_on_stale_updated_at(self, store):
        chat, user = -400, 9
        await store.put_relation(chat, user, stage="regular")
        profile = await store.get_profile(chat)
        with pytest.raises(ChatLoreConflict) as exc:
            await store.put_relation(
                chat, user, stage="veteran",
                expected_updated_at="2000-01-01T00:00:00+00:00")
        assert exc.value.chat_id == chat
        assert exc.value.current_updated_at is not None
        # данные не тронуты (409-оптимизм)
        entry = (await store.get_relations(chat))[str(user)]
        assert entry["manual_stage"] == "regular"
        assert (await store.get_profile(chat)).updated_at \
            == profile.updated_at

    @pytest.mark.asyncio
    async def test_put_with_matching_expected_ok(self, store):
        chat, user = -500, 5
        await store.put_relation(chat, user, stage="acquaintance")
        current = (await store.get_profile(chat)).updated_at
        await store.put_relation(chat, user, stage="veteran", note="x",
                                 expected_updated_at=current)
        assert (await store.get_relation_manual(chat, user))["manual_stage"] \
            == "veteran"

    @pytest.mark.asyncio
    async def test_stage_auto_resets_to_auto(self, store):
        chat, user = -600, 3
        await store.put_relation(chat, user, stage="veteran", note="было")
        await store.put_relation(chat, user, stage="auto")
        assert await store.get_relation_manual(chat, user) is None
        # заметка без ручной стадии сохраняется (manual_stage=null)
        await store.put_relation(chat, user, stage=None, note="только заметка")
        entry = await store.get_relation_manual(chat, user)
        assert entry["manual_stage"] is None
        assert entry["note"] == "только заметка"

    @pytest.mark.asyncio
    async def test_delete_relation_removes_key(self, store):
        chat, user = -700, 11
        await store.put_relation(chat, user, stage="veteran", note="x",
                                 updated_by=1)
        profile = await store.delete_relation(chat, user)
        assert str(user) not in profile.relations
        assert str(user) not in await store.get_relations(chat)

    @pytest.mark.asyncio
    async def test_notify_emitted_on_mutations(self, store, conn):
        chat, user = -800, 12
        await store.put_relation(chat, user, stage="regular")
        await store.delete_relation(chat, user)
        await store.set_relations_enabled(chat, True)
        assert conn.notifies.count(str(chat)) == 3

    @pytest.mark.asyncio
    async def test_manual_stages_enum_matches_spec(self):
        assert MANUAL_STAGES == ("stranger", "acquaintance", "regular",
                                 "veteran")


class TestRelationsEnabled:
    @pytest.mark.asyncio
    async def test_toggle_column_and_profile(self, store):
        chat = -900
        await store.set_relations_enabled(chat, True)
        profile = await store.get_profile(chat)
        assert profile.relations_enabled is True
        assert profile.to_dict()["relations_enabled"] is True
        await store.set_relations_enabled(chat, False,
                                          expected_updated_at=profile.updated_at)
        assert (await store.get_profile(chat)).relations_enabled is False

    @pytest.mark.asyncio
    async def test_toggle_conflict_on_stale(self, store):
        chat = -901
        await store.set_relations_enabled(chat, True)
        with pytest.raises(ChatLoreConflict):
            await store.set_relations_enabled(
                chat, False,
                expected_updated_at="1999-01-01T00:00:00+00:00")

    @pytest.mark.asyncio
    async def test_toggle_does_not_wipe_relations(self, store):
        chat = -902
        await store.put_relation(chat, 42, stage="veteran", note="не тронь")
        await store.set_relations_enabled(chat, True)
        assert (await store.get_relations(chat))["42"]["manual_stage"] \
            == "veteran"


class TestAliasAndHelpers:
    @pytest.mark.asyncio
    async def test_set_relation_manual_alias_writes_updated_by(self, store):
        chat, user = -903, 77
        profile = await store.set_relation_manual(
            chat, user, stage_manual="acquaintance", note="алиас",
            changed_by=5885953495)
        entry = profile.relations[str(user)]
        assert entry["manual_stage"] == "acquaintance"
        assert entry["updated_by"] == 5885953495

    @pytest.mark.asyncio
    async def test_lore_profile_defaults_and_to_dict(self):
        p = LoreProfile(chat_id=-1, manual_lore="", auto_lore="",
                        auto_enabled=True, auto_period_hours=24,
                        auto_window_hours=24, is_active=True,
                        last_auto_at=None, updated_at="2026-01-01T00:00:00+00:00")
        assert p.relations == {}
        assert p.relations_enabled is False
        d = p.to_dict()
        assert d["relations"] == {}
        assert d["relations_enabled"] is False
