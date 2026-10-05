"""MCA-18 `mca-18-self-model` — focused-тесты блока A (T-5075/T-5076).

Покрытие (ADR-1028-18 D1/D2; §28.2 `:1513–1527`; A58 `:939`):
  * v31 DDL: 4 таблицы (`mca_self_identity` + сид/`mca_trait_observations`/
    `mca_behavior_rules`/`mca_adoption_links`), книга, идемпотентность,
    v30→v31 simulation + backup read-back, PG no-op;
  * SelfModelSnapshot: поля §28.2, версионирование (persona_version = хеш
    СОДЕРЖИМОГО; смена модели/токена НЕ сбрасывает — R2d/I-2);
  * три настройки: `persona_enabled`/`is_aware_ai`/`bot_self_awareness_`
    `enabled` — `False`/`null-наследовать`/`ошибка` — три разных состояния,
    global/chat effective + источник наследования (прецедент mca-06);
  * пустая персона True/False — различимое поведение (A58/R2a);
  * OFF persona ≠ отмена авторства (R2c-рамка);
  * ошибки не маскируются (identity read fail → SelfModelSnapshotError +
    событие `self_model_snapshot_error`; K1 OFF → `self_model_disabled`);
  * capabilities из реестра инструментов (не из биографии); «могу» ≠
    «посмотрел» ≠ «помню всё» (I-3).
"""
import json
import sqlite3

import pytest

from services import mca_events, mca_gates
from services import mca_self_model as sm
from services.database import (DatabaseService,
                               _SCHEMA_VERSION_RANDOM_USES,
                               _SCHEMA_VERSION_SELF_MODEL)

CHAT = -100500

V31_TABLES = ("mca_self_identity", "mca_trait_observations",
              "mca_behavior_rules", "mca_adoption_links")


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture
def events(monkeypatch):
    recorded: list = []

    def _fake(name, **kw):
        recorded.append((name, kw))
        return {"event_name": name}

    monkeypatch.setattr(mca_events, "emit_mca_event", _fake)
    return recorded


async def _db(tmp_path, name="mca18_a.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _count(db, sql, params=()) -> int:
    cur = await db.db.execute(sql, params)
    row = await cur.fetchone()
    return int(row["c"])


# ═══ v31 DDL ═════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_v31_fresh_schema_book_seed_and_idempotent_reinit(tmp_path):
    db = await _db(tmp_path)
    try:
        cur = await db.db.execute("PRAGMA user_version")
        # (mca-18): frontier глобальной схемы — свежая БД приземляется на
        # актуальный frontier (≥ 31), v31-метка в книге.
        assert (await cur.fetchone())[0] >= _SCHEMA_VERSION_SELF_MODEL == 31
        for table in V31_TABLES:
            assert await _count(
                db, "SELECT COUNT(*) AS c FROM sqlite_master WHERE "
                    "type='table' AND name=?", (table,)) == 1
        cur = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND "
            "(name LIKE 'idx_mca_trait_obs_%' OR name LIKE "
            "'idx_mca_behavior_rules_%' OR name = "
            "'idx_graph_facts_kind_status' OR name = "
            "'idx_graph_facts_subject_entity') ORDER BY name")
        names = [r["name"] for r in await cur.fetchall()]
        assert names == [
            "idx_graph_facts_kind_status",
            "idx_graph_facts_subject_entity",
            "idx_mca_behavior_rules_agent_status_dim",
            "idx_mca_behavior_rules_scope_status",
            "idx_mca_trait_obs_agent_observed",
            "idx_mca_trait_obs_chat_observed",
        ]
        # graph_facts: 9 v31-колонок на месте.
        cols = await db._table_columns("graph_facts")
        for name in ("subject_entity_id", "speaker_entity_id", "perspective",
                     "memory_kind", "scope", "valid_from", "valid_to",
                     "confidence_basis", "revision"):
            assert name in cols
        # Сид субъекта self: ровно одна строка, agent_id — UUID.
        assert await _count(
            db, "SELECT COUNT(*) AS c FROM mca_self_identity") == 1
        identity = await db.get_self_identity()
        assert identity and identity["agent_id"]
        assert len(identity["agent_id"]) >= 32       # uuid4-канон
        assert await _count(
            db, "SELECT COUNT(*) AS c FROM schema_migrations WHERE "
                "version = 31") == 1
    finally:
        await db.close()
    # Повторный прогон — no-op (0 дублей; agent_id стабилен).
    db2 = DatabaseService(str(tmp_path / "mca18_a.db"))
    await db2.initialize()
    try:
        assert await _count(
            db2, "SELECT COUNT(*) AS c FROM schema_migrations WHERE "
                 "version = 31") == 1
        assert await _count(
            db2, "SELECT COUNT(*) AS c FROM mca_self_identity") == 1
        identity2 = await db2.get_self_identity()
        assert identity2["agent_id"] == identity["agent_id"]
    finally:
        await db2.close()


@pytest.mark.asyncio
async def test_v31_upgrade_from_v30_simulated_with_backup_readback(tmp_path):
    """v30→v31: пересоздание удалённых v31-объектов; backup-guard пишет
    `pre_migration_*.db`; read-back — user_version=30 и данные целы."""
    path = str(tmp_path / "mca18_upgrade.db")
    db = DatabaseService(path)
    await db.initialize()
    # Репрезентативные данные ДО апгрейда.
    fid = await db.save_typed_fact(chat_id=CHAT, fact="Вася стал грубее",
                                   memory_kind="world_fact", scope="chat")
    assert fid is not None
    await db.db.execute("DELETE FROM schema_migrations WHERE version = 31")
    for table in V31_TABLES:
        await db.db.execute(f"DROP TABLE IF EXISTS {table}")
    await db.db.execute(
        f"PRAGMA user_version = {_SCHEMA_VERSION_RANDOM_USES}")
    await db.db.commit()
    await db.close()

    db2 = DatabaseService(path)
    await db2.initialize()
    try:
        cur = await db2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 31
        for table in V31_TABLES:
            assert await _count(
                db2, "SELECT COUNT(*) AS c FROM sqlite_master WHERE "
                     "type='table' AND name=?", (table,)) == 1
        fact = await db2.get_typed_fact(fid)
        assert fact is not None and fact["memory_kind"] == "world_fact"
    finally:
        await db2.close()
    # Backup-guard + read-back: свежий бэкап открывается, версия/данные целы.
    backups = sorted(tmp_path.glob("pre_migration_*.db"))
    assert backups, "backup-guard"
    raw = sqlite3.connect(backups[-1])
    try:
        read_version = raw.execute("PRAGMA user_version").fetchone()[0]
        facts = raw.execute(
            "SELECT COUNT(*) FROM graph_facts WHERE id = ?",
            (fid,)).fetchone()[0]
    finally:
        raw.close()
    assert read_version == _SCHEMA_VERSION_RANDOM_USES
    assert facts == 1


def test_v31_pg_noop():
    """PG DDL = 0 (GEN-R4): pg_db.py не содержит SelfModel-объектов."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = (root / "services" / "pg_db.py").read_text(encoding="utf-8")
    for token in ("mca_self_identity", "mca_trait_observations",
                  "mca_behavior_rules", "mca_adoption_links",
                  "subject_entity_id"):
        assert token not in src


# ═══ Идентичность: rebind — явное действие ══════════════════════════════════

@pytest.mark.asyncio
async def test_rebind_keeps_agent_id(tmp_path):
    db = await _db(tmp_path)
    try:
        before = await db.get_self_identity()
        updated = await db.rebind_self_identity(
            bot_user_id=4242, note="explicit owner action")
        assert updated["agent_id"] == before["agent_id"]
        assert updated["bot_user_id"] == 4242
        assert updated["note"] == "explicit owner action"
        # Повтор — тот же агент, обновляется только привязка.
        again = await db.rebind_self_identity(bot_user_id=4243)
        assert again["agent_id"] == before["agent_id"]
        assert again["bot_user_id"] == 4243
    finally:
        await db.close()


# ═══ Три настройки: False / null-наследовать / ошибка ═══════════════════════

@pytest.mark.asyncio
async def test_persona_enabled_states(monkeypatch):
    from services import chat_params, hot_config as hot

    def _fake_param(overrides):
        """Единый фейк модульного резолва: override → hot → default (как
        `_resolve_from_root`, но с инжектируемым root)."""
        async def _resolve(chat_id, key, default=None):
            if key in overrides:
                return overrides[key]
            return hot.get(key, default)
        return _resolve

    monkeypatch.setattr(hot, "get",
                        lambda key, default=None: default)
    monkeypatch.setattr(chat_params, "get_all_chat_params",
                        async_returns({"overrides": {}}))
    monkeypatch.setattr(chat_params, "get_chat_param", _fake_param({}))
    # default (нет override, нет hot).
    state = await sm.resolve_persona_enabled(CHAT)
    assert (state.value, state.source) == (True, "default")
    assert state.is_error is False
    # chat override False — явное False, не «наследовать».
    monkeypatch.setattr(
        chat_params, "get_all_chat_params",
        async_returns({"overrides": {"flags.persona_enabled": False}}))
    monkeypatch.setattr(
        chat_params, "get_chat_param",
        _fake_param({"flags.persona_enabled": False}))
    state = await sm.resolve_persona_enabled(CHAT)
    assert (state.value, state.source) == (False, "chat")
    assert state.effective() is False
    # global (hot) — наследование с источником.
    monkeypatch.setattr(chat_params, "get_all_chat_params",
                        async_returns({"overrides": {}}))
    monkeypatch.setattr(chat_params, "get_chat_param", _fake_param({}))
    monkeypatch.setattr(hot, "get",
                        lambda key, default=None: True
                        if key == "flags.persona_enabled" else default)
    state = await sm.resolve_persona_enabled(CHAT)
    assert (state.value, state.source) == (True, "global")
    monkeypatch.setattr(hot, "get",
                        lambda key, default=None: False
                        if key == "flags.persona_enabled" else default)
    state = await sm.resolve_persona_enabled(CHAT)
    assert (state.value, state.source) == (False, "global")
    # Ошибка загрузки — третье состояние (не False, не null).
    async def _boom(chat_id):
        raise RuntimeError("pg down")
    monkeypatch.setattr(chat_params, "get_all_chat_params", _boom)
    state = await sm.resolve_persona_enabled(CHAT)
    assert state.is_error is True
    assert state.value is None
    assert state.error == "RuntimeError"
    # Глобальный scope (chat_id=None) — без chat-ветки, honest default.
    state = await sm.resolve_persona_enabled(None)
    assert state.source in ("default", "global")


@pytest.mark.asyncio
async def test_is_aware_ai_states(monkeypatch):
    from services import bot_persona

    class _Conn:
        def __init__(self, chat_row, global_row):
            self._chat = chat_row
            self._global = global_row

        async def fetchrow(self, sql, *args):
            if "is_global = false" in sql:
                return self._chat
            return self._global

    class _Pool:
        def __init__(self, chat_row, global_row):
            self._conn = _Conn(chat_row, global_row)

        def acquire(self):
            return _Ctx(self._conn)

    class _Ctx:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(bot_persona, "_persona_pool",
                        lambda: _Pool({"is_aware_ai": 0}, None))
    state = await sm.resolve_is_aware_ai(CHAT)
    assert (state.value, state.source) == (False, "chat")
    monkeypatch.setattr(bot_persona, "_persona_pool",
                        lambda: _Pool(None, {"is_aware_ai": 1}))
    state = await sm.resolve_is_aware_ai(CHAT)
    assert (state.value, state.source) == (True, "global")
    # Нет строк — null-наследовать (не False).
    monkeypatch.setattr(bot_persona, "_persona_pool",
                        lambda: _Pool(None, None))
    state = await sm.resolve_is_aware_ai(CHAT)
    assert (state.value, state.source) == (None, "default")
    # PG недоступен — ошибка, не False.
    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: None)
    state = await sm.resolve_is_aware_ai(CHAT)
    assert state.is_error and state.error == "pg_unavailable"

    class _BrokenPool:
        def acquire(self):
            raise RuntimeError("broken")

    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: _BrokenPool())
    state = await sm.resolve_is_aware_ai(CHAT)
    assert state.is_error and state.value is None


def async_returns(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


# ═══ Snapshot: поля/версии/пустая персона/OFF-authorship ════════════════════

def _patch_settings_resolvers(monkeypatch, *, persona=None, aware=None):
    from services import bot_persona
    persona = persona or bot_persona.BotPersona.empty()
    monkeypatch.setattr(bot_persona, "resolve_bot_persona",
                        async_returns(persona))
    if aware is not None:
        monkeypatch.setattr(sm, "resolve_is_aware_ai",
                            async_returns(aware))


@pytest.mark.asyncio
async def test_snapshot_fields_and_versioning(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        identity = await db.get_self_identity()
        persona = bot_persona_for(name="Костик", biography="дворовый кот",
                                  overrides="циник", aware=False)
        _patch_settings_resolvers(
            monkeypatch, persona=persona,
            aware=sm.SettingState(key="personas.is_aware_ai", value=False,
                                  source="global"))
        snap = await sm.resolve_self_model(db, CHAT, bot_user_id=4242)
        assert snap.agent_id == identity["agent_id"]
        assert snap.bot_user_id == 4242
        assert snap.identity_binding == "runtime"
        assert snap.scope_chat_id == CHAT
        assert snap.name == "Костик"
        assert snap.self_presentation_mode == sm.MODE_IN_CHARACTER
        assert snap.capabilities.tool_names          # из реестра, не пусто
        assert snap.persona_version == sm.persona_version_hash(
            name="Костик", biography="дворовый кот", overrides="циник",
            is_aware_ai=False, updated_at=None)
        assert snap.style_version == sm.style_version_hash("циник")
        assert snap.version and len(snap.version) == 32
        # version — производный токен: детерминирован при тех же входах.
        snap2 = await sm.resolve_self_model(db, CHAT, bot_user_id=4242)
        assert snap2.version == snap.version
    finally:
        await db.close()


def bot_persona_for(*, name, biography, overrides, aware):
    from services import bot_persona
    return bot_persona.BotPersona(
        name=name, biography=biography, overrides=overrides,
        is_aware_ai=aware, is_global=True)


@pytest.mark.asyncio
async def test_persona_version_stable_across_model_change(tmp_path,
                                                          monkeypatch):
    """R2d/I-2: смена токена/модели/bot_user_id НЕ меняет persona_version;
    смена содержимого (biography) — меняет."""
    db = await _db(tmp_path)
    try:
        persona = bot_persona_for(name="Костик", biography="кот",
                                  overrides="", aware=True)
        _patch_settings_resolvers(
            monkeypatch, persona=persona,
            aware=sm.SettingState(key="personas.is_aware_ai", value=True,
                                  source="global"))
        snap_a = await sm.resolve_self_model(db, None, bot_user_id=111)
        snap_b = await sm.resolve_self_model(db, None, bot_user_id=222)
        assert snap_a.persona_version == snap_b.persona_version
        assert snap_a.agent_id == snap_b.agent_id
        persona2 = bot_persona_for(name="Костик", biography="другой кот",
                                   overrides="", aware=True)
        _patch_settings_resolvers(
            monkeypatch, persona=persona2,
            aware=sm.SettingState(key="personas.is_aware_ai", value=True,
                                  source="global"))
        snap_c = await sm.resolve_self_model(db, None, bot_user_id=111)
        assert snap_c.persona_version != snap_a.persona_version
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_empty_persona_distinct_true_false_and_authorship(
        tmp_path, monkeypatch):
    """A58/R2a: пустая персона True/False — различимое поведение; OFF
    persona не отменяет авторство (R2c-рамка)."""
    db = await _db(tmp_path)
    try:
        _patch_settings_resolvers(
            monkeypatch, persona=None,
            aware=sm.SettingState(key="personas.is_aware_ai", value=True,
                                  source="default"))
        snap_true = await sm.resolve_self_model(db, CHAT)
        assert snap_true.persona_is_empty
        assert snap_true.self_presentation_mode == sm.MODE_AWARE
        assert snap_true.authorship["agent_id"]
        assert snap_true.capabilities.tool_names

        _patch_settings_resolvers(
            monkeypatch, persona=None,
            aware=sm.SettingState(key="personas.is_aware_ai", value=False,
                                  source="global"))
        snap_false = await sm.resolve_self_model(db, CHAT)
        assert snap_false.persona_is_empty
        assert snap_false.self_presentation_mode == sm.MODE_IN_CHARACTER
        # Различимое поведение при обоих значениях (не одна пустая строка).
        assert snap_true.self_presentation_mode \
            != snap_false.self_presentation_mode

        # persona_enabled=False (OFF) — авторство и тех-идентичность живы.
        monkeypatch.setattr(
            sm, "resolve_persona_enabled",
            async_returns(sm.SettingState(key="flags.persona_enabled",
                                          value=False, source="chat")))
        snap_off = await sm.resolve_self_model(db, CHAT)
        assert snap_off.persona_enabled.value is False
        assert snap_off.authorship["agent_id"]
        assert snap_off.authorship["bot_user_id"] is None \
            or isinstance(snap_off.authorship["bot_user_id"], int)
        assert snap_off.capabilities.tool_names
        assert snap_off.agent_id == snap_true.agent_id
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_snapshot_error_not_masked(tmp_path, events, monkeypatch):
    """Ошибка чтения идентичности — честный отказ + событие, не пустота."""
    db = await _db(tmp_path)
    try:
        async def _broken_identity():
            raise RuntimeError("db gone")
        monkeypatch.setattr(db, "get_self_identity", _broken_identity)
        _patch_settings_resolvers(monkeypatch)
        with pytest.raises(sm.SelfModelSnapshotError):
            await sm.resolve_self_model(db, CHAT)
        assert any(kw.get("reason_code") == "self_model_snapshot_error"
                   for _, kw in events)
        # Отсутствие строки идентичности — тоже ошибка.
        monkeypatch.setattr(db, "get_self_identity", async_returns(None))
        with pytest.raises(sm.SelfModelSnapshotError):
            await sm.resolve_self_model(db, CHAT)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_k1_off_disabled_no_reads(tmp_path, events, monkeypatch):
    """K1 OFF: SelfModelDisabled + `self_model_disabled`; v31 не читается."""
    db = await _db(tmp_path)
    try:
        calls = {"n": 0}
        original = db.get_self_identity

        async def _counting():
            calls["n"] += 1
            return await original()
        monkeypatch.setattr(db, "get_self_identity", _counting)
        monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: False)
        _patch_settings_resolvers(monkeypatch)
        with pytest.raises(sm.SelfModelDisabled):
            await sm.resolve_self_model(db, CHAT)
        assert calls["n"] == 0                     # v31 не читается
        assert any(kw.get("reason_code") == "self_model_disabled"
                   for _, kw in events)
    finally:
        await db.close()


# ═══ T-5076: capabilities из реестра инструментов ═══════════════════════════

def test_capabilities_from_tool_registry_not_biography():
    from services import tool_schemas
    caps = sm.build_capabilities()
    expected = sorted(t["function"]["name"]
                      for t in tool_schemas.active_tools())
    assert caps.tool_names == tuple(expected)
    assert caps.source == "tool_registry"
    # I-3: до mca-19 vision-инструментов нет → «посмотреть изображение»
    # не заявляется, даже если биография утверждает обратное.
    assert caps.can_analyze_images is False
    assert caps.did_analyze_images is False
    assert sm.capability_claim_allowed("analyze_image", caps) is False
    assert sm.capability_claim_allowed("image_analyzed", caps) is False
    # «Помню всё» — всегда False (память ограничена доступной областью).
    assert caps.can_remember_everything is False
    assert sm.capability_claim_allowed("remember_everything", caps) is False
    # «Могу» по фактическому доступу к инструментам.
    assert sm.capability_claim_allowed("use_tools", caps) \
        is bool(caps.tool_names)
    # «Посмотрел» — только runtime-доказательство; без vision-пути не
    # появляется даже с evidence-флагом.
    hard = sm.build_capabilities(image_analysis_evidence=True)
    assert hard.did_analyze_images is False
    assert sm.capability_claim_allowed("image_analyzed", hard) is False


# ═══ Kill-switches: ровно 3, регистрация, defaults ══════════════════════════

def test_kill_switches_registered_and_default_on():
    from config.settings import settings
    for name in ("MCA_SELF_MODEL_ENABLED", "MCA_TRAIT_RULES_ENABLED",
                 "MCA_LEGACY_TRAITS_MIGRATION_ENABLED"):
        assert name in mca_gates.KILL_SWITCHES
        assert mca_gates.KILL_SWITCHES[name][0] is True
        assert getattr(settings, name) is True
    assert mca_gates.self_model_enabled() is True
    assert mca_gates.trait_rules_enabled() is True
    assert mca_gates.legacy_traits_migration_enabled() is True
    assert mca_gates.mood_ttl_seconds() == 6 * 3600
    # Причина-коды блоков A/B в едином словаре (mca_events).
    for code in ("self_model_disabled", "self_model_snapshot_error",
                 "trait_attribution_ambiguous"):
        assert code in mca_events.REASON_CODES


def test_off_parity_bot_persona_untouched():
    """OFF-паритет: K1 OFF → frame-путь не активен (тесты
    `test_resolve_character_context_legacy_on_error`/K1-OFF), legacy-ветка
    `build_persona_prompt_block` байт-в-байт. Проводка T-5081 — ЧЕРЕЗ швы
    mca-08 (seam `:368`/`:237`), не вторым контуром."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = (root / "services" / "bot_persona.py").read_text(encoding="utf-8")
    # Проводка — только внутри санкционированных швов (resolve_character_
    # context / build_persona_prompt_block).
    assert "mca_self_model" in src
    # Legacy-ветка сохранена: старый запрет-блок на месте (OFF-семантика).
    assert "_NO_AI_DISCLOSURE_BLOCK" in src
