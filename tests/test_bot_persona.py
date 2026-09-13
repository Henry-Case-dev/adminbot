"""Раунд 10.14 (F2 persona-storage-core) — тесты services/bot_persona.py.

Покрытие (spec F2 §7): scope-резолв (per-chat → global → empty; PG down →
empty), бизнес-логика приложения (dedup/cap/FIFO/провенанс), health-метрики,
name-cache. PG — stateful-фейк пула (без реального PostgreSQL).
"""
import datetime
from types import SimpleNamespace

import pytest

from services import bot_persona as bp


class _FakeConn:
    """Мини-эмуляция asyncpg-соединения для персона-SQL (dict-строки)."""

    def __init__(self, db):
        self.db = db

    async def fetchrow(self, sql, *args):
        self.db.queries.append((sql, args))
        if "FROM personas" in sql:
            if "is_global = false" in sql:
                return self.db.personas.get(int(args[0]))
            if "is_global = true" in sql:
                return self.db.personas.get(None)
        if "INSERT INTO personas" in sql:      # H1: UPSERT ... RETURNING
            await self.execute(sql, *args)
            if "VALUES (NULL, true" in sql:
                return self.db.personas.get(None)
            return self.db.personas.get(int(args[0]))
        if "COUNT(*) AS traits_count" in sql:
            last = self.db.traits[-1]["created_at"] if self.db.traits else None
            return {"traits_count": len(self.db.traits), "last_trait_at": last}
        if "FROM persona_state" in sql:
            return dict(self.db.state)
        return None

    async def fetch(self, sql, *args):
        self.db.queries.append((sql, args))
        if "SELECT trait FROM persona_traits" in sql:
            return [{"trait": t["trait"]} for t in self.db.traits]
        if "FROM persona_traits" in sql:
            rows = list(self.db.traits)
            if "WHERE chat_id = $1" in sql and args:
                rows = [t for t in rows if t["chat_id"] == args[0]]
            return list(reversed(rows))       # DESC по вставке (последние сверху)
        return []

    async def execute(self, sql, *args):
        self.db.queries.append((sql, args))
        if "INSERT INTO personas" in sql:
            if "VALUES (NULL, true" in sql:
                self.db.personas[None] = {
                    "name": args[0], "biography": args[1],
                    "system_prompt_overrides": args[2], "is_aware_ai": args[3],
                    "updated_at": datetime.datetime(2026, 9, 13, 12, 0, 0)}
            else:
                self.db.personas[int(args[0])] = {
                    "name": args[1], "biography": args[2],
                    "system_prompt_overrides": args[3], "is_aware_ai": args[4],
                    "updated_at": datetime.datetime(2026, 9, 13, 12, 0, 0)}
            return "INSERT 0 1"
        if "INSERT INTO persona_traits" in sql:
            self.db._next += 1
            self.db.traits.append({
                "id": self.db._next, "chat_id": args[0], "trait": args[1],
                "source": args[2],
                "created_at": datetime.datetime(2026, 9, 13, 12, 0, 0)})
            return "INSERT 0 1"
        if "DELETE FROM persona_traits" in sql:
            cap = int(args[0])
            # FIFO: оставляем последние cap (по вставке)
            self.db.traits = self.db.traits[-cap:]
            return f"DELETE {len(self.db.traits)}"
        if "DELETE FROM personas" in sql:
            return "DELETE 1" if self.db.personas.pop(int(args[0]), None) else "DELETE 0"
        if "INSERT INTO persona_state" in sql:
            self.db.state["last_trait_status"] = args[0]
            self.db.state["last_trait_at"] = datetime.datetime(2026, 9, 13, 12, 0, 0)
            return "INSERT 0 1"
        return "INSERT 0 1"


class _FakeDB:
    def __init__(self):
        self.personas: dict = {}
        self.traits: list[dict] = []
        self._next = 0
        self.queries: list = []
        self.state = {"last_extract_status": "never", "last_extract_at": None,
                      "last_trait_status": "never", "last_trait_at": None}

    def conn(self):
        return _FakeConn(self)


class _FakePool:
    def __init__(self, db):
        self._db = db

    def acquire(self):
        db = self._db

        class _CM:
            async def __aenter__(self):
                return db.conn()

            async def __aexit__(self, *exc):
                return False

        return _CM()


@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture
def pool(fake_db, monkeypatch):
    p = _FakePool(fake_db)
    bp.set_persona_pool(p)
    yield p
    bp.reset_persona_pool()


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    """Каталог-флаг persona_enabled ON (дефолт UPD п.2)."""
    monkeypatch.setattr(bp.hot, "get",
                        lambda key, default=None: True)


# ── Промпт-блок ─────────────────────────────────────────────────────────────

class TestPromptBlock:
    def test_empty_persona_no_block(self):
        assert bp.build_persona_prompt_block(bp.BotPersona.empty()) == ""

    def test_flag_off_no_block(self, monkeypatch):
        monkeypatch.setattr(bp.hot, "get", lambda key, default=None: False)
        persona = bp.BotPersona(name="Костик", biography="дворовый кот")
        assert bp.build_persona_prompt_block(persona) == ""

    def test_exact_block_bytes(self):
        persona = bp.BotPersona(name="Костик", biography="дворовый кот",
                                overrides="язвительный")
        block = bp.build_persona_prompt_block(persona, ["шутит про грибы",
                                                        "стал циничнее"])
        assert block == (
            "<Persona>\n"
            "Имя: Костик\n"
            "Биография: дворовый кот\n"
            "Характер: язвительный\n"
            "Черты, которые ты приобрёл: • шутит про грибы • стал циничнее\n"
            "</Persona>")

    def test_empty_sections_omitted(self):
        persona = bp.BotPersona(name="Костик")
        assert bp.build_persona_prompt_block(persona) == (
            "<Persona>\nИмя: Костик\n</Persona>")

    def test_no_ai_disclosure_appended(self):
        persona = bp.BotPersona(name="Костик", is_aware_ai=False)
        block = bp.build_persona_prompt_block(persona)
        assert block == ("<Persona>\nИмя: Костик\n</Persona>\n"
                         + bp._NO_AI_DISCLOSURE_BLOCK)

    def test_aware_ai_has_no_prohibition(self):
        persona = bp.BotPersona(name="Костик", is_aware_ai=True)
        assert bp._NO_AI_DISCLOSURE_BLOCK not in bp.build_persona_prompt_block(persona)


# ── Name-cache ──────────────────────────────────────────────────────────────

class TestNameCache:
    def test_set_and_get(self, monkeypatch):
        monkeypatch.setattr(bp, "_global_name", "")
        bp.set_global_name_cache("  Костик  ")
        assert bp.get_cached_global_name() == "Костик"

    @pytest.mark.asyncio
    async def test_load_global_cache(self, pool, fake_db):
        fake_db.personas[None] = {
            "name": "Костик", "biography": "", "system_prompt_overrides": "",
            "is_aware_ai": True, "updated_at": None}
        await bp.load_global_cache()
        assert bp.get_cached_global_name() == "Костик"
        bp.set_global_name_cache("")


# ── Scope-резолв ────────────────────────────────────────────────────────────

class TestResolveScope:
    @pytest.mark.asyncio
    async def test_pg_down_returns_empty(self, monkeypatch):
        monkeypatch.setattr(bp, "_pool_override", None)
        monkeypatch.setattr(bp.hot, "get_config_cache", lambda: None)
        persona = await bp.resolve_bot_persona(-100)
        assert persona == bp.BotPersona.empty()

    @pytest.mark.asyncio
    async def test_per_chat_overrides_global(self, pool, fake_db):
        fake_db.personas[None] = {"name": "Global", "biography": "g",
                                  "system_prompt_overrides": "",
                                  "is_aware_ai": True, "updated_at": None}
        fake_db.personas[-100] = {"name": "Local", "biography": "",
                                  "system_prompt_overrides": "локальный",
                                  "is_aware_ai": False, "updated_at": None}
        persona = await bp.resolve_bot_persona(-100)
        assert persona.name == "Local"
        assert persona.scope_chat_id == -100
        assert persona.is_global is False
        assert persona.is_aware_ai is False

    @pytest.mark.asyncio
    async def test_falls_back_to_global(self, pool, fake_db):
        fake_db.personas[None] = {"name": "Global", "biography": "g",
                                  "system_prompt_overrides": "",
                                  "is_aware_ai": True, "updated_at": None}
        persona = await bp.resolve_bot_persona(-100)
        assert persona.name == "Global"
        assert persona.is_global is True
        assert persona.scope_chat_id is None

    @pytest.mark.asyncio
    async def test_no_rows_empty(self, pool):
        persona = await bp.resolve_bot_persona(None)
        assert persona == bp.BotPersona.empty()


# ── Запись ──────────────────────────────────────────────────────────────────

class TestSaveDelete:
    @pytest.mark.asyncio
    async def test_save_global_sets_name_cache(self, pool, fake_db, monkeypatch):
        monkeypatch.setattr(bp, "_global_name", "")
        persona = await bp.save_persona(None, {"name": "Костик",
                                               "is_aware_ai": False})
        assert persona.name == "Костик" and persona.is_aware_ai is False
        assert fake_db.personas[None]["name"] == "Костик"
        assert bp.get_cached_global_name() == "Костик"

    @pytest.mark.asyncio
    async def test_save_chat_partial_keeps_existing(self, pool, fake_db,
                                                    monkeypatch):
        monkeypatch.setattr("services.chat_params.ensure_scope_profile",
                            _async_noop)
        fake_db.personas[-100] = {"name": "Old", "biography": "bio",
                                  "system_prompt_overrides": "хар",
                                  "is_aware_ai": True, "updated_at": None}
        persona = await bp.save_persona(-100, {"name": "New"})
        assert persona.name == "New"
        assert persona.biography == "bio"
        assert persona.overrides == "хар"

    @pytest.mark.asyncio
    async def test_save_returns_updated_at_token(self, pool, fake_db):
        """H1: save_persona возвращает optimistic-токен; свежий токен не
        конфликтует, устаревший — PersonaConflict (см. тест выше)."""
        persona = await bp.save_persona(None, {"name": "Костик"})
        assert persona.updated_at is not None
        token = persona.updated_at
        ok = await bp.save_persona(None, {"name": "Другой"},
                                   expected_updated_at=token)
        assert ok.name == "Другой"

    @pytest.mark.asyncio
    async def test_optimistic_conflict(self, pool, fake_db):
        fake_db.personas[-100] = {"name": "Old", "biography": "",
                                  "system_prompt_overrides": "",
                                  "is_aware_ai": True,
                                  "updated_at": "2026-09-13T12:00:00+00:00"}
        with pytest.raises(bp.PersonaConflict) as exc:
            await bp.save_persona(-100, {"name": "New"},
                                  expected_updated_at="2000-01-01T00:00:00")
        assert exc.value.current_updated_at == "2026-09-13T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_delete_removes_chat_row(self, pool, fake_db):
        fake_db.personas[-100] = {"name": "x"}
        assert await bp.delete_persona(-100) is True
        assert -100 not in fake_db.personas

    @pytest.mark.asyncio
    async def test_save_without_pool_raises(self, monkeypatch):
        monkeypatch.setattr(bp, "_pool_override", None)
        monkeypatch.setattr(bp.hot, "get_config_cache", lambda: None)
        with pytest.raises(bp.PersonaUnavailable):
            await bp.save_persona(None, {"name": "x"})


async def _async_noop(*args, **kwargs):
    return False


# ── Трейты ──────────────────────────────────────────────────────────────────

class TestTraits:
    @pytest.mark.asyncio
    async def test_append_dedup_cap_and_provenance(self, pool, fake_db,
                                                   monkeypatch):
        monkeypatch.setattr(bp, "settings", SimpleNamespace(
            PERSONA_TRAITS_MAX=2, PERSONA_TRAIT_MAX_CHARS=5,
            PERSONA_ENABLED=True))
        inserted = await bp.append_traits(
            ["длинное-наблюдение", "корот", "КОРОТ", "  ", "ещё01"],
            chat_id=-100, source="deep_sleep")
        assert inserted == 3
        # cap 5 символов; дедуп casefold ("корот" vs "КОРОТ"); FIFO-cap
        # PERSONA_TRAITS_MAX=2 → остались только последние две вставленные.
        assert [t["trait"] for t in fake_db.traits] == ["корот", "ещё01"]
        assert all(t["chat_id"] == -100 for t in fake_db.traits)
        assert all(t["source"] == "deep_sleep" for t in fake_db.traits)

    @pytest.mark.asyncio
    async def test_get_traits_shape_and_filter(self, pool, fake_db):
        await bp.append_traits(["a", "b"], chat_id=-100)
        await bp.append_traits(["c"], chat_id=-200)
        all_traits = await bp.get_traits(limit=10)
        assert {t["text"] for t in all_traits} == {"a", "b", "c"}
        filtered = await bp.get_traits(limit=10, chat_id=-200)
        assert [t["text"] for t in filtered] == ["c"]
        assert filtered[0]["ts"] is not None
        assert filtered[0]["source"] == "deep_sleep"

    @pytest.mark.asyncio
    async def test_health(self, pool, fake_db):
        await bp.append_traits(["черта"], chat_id=None)
        fake_db.state.update({"last_extract_status": "ok",
                              "last_extract_at": datetime.datetime(
                                  2026, 9, 13, 11, 0, 0),
                              "last_trait_status": "ok"})
        health = await bp.get_persona_health()
        assert health["traits_count"] == 1
        assert health["last_trait_at"] is not None
        assert health["extractor_status"] == "ok"
        assert health["extractor_last_at"] is not None
