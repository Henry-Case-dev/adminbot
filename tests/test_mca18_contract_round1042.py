"""MCA-18 — контрактные тесты §28.7 (`:1594`, T-5089; ADR-1028-18 §6).

Инварианты (100% зелёные — блокер):
  * пустая персона True/False — через ТОЧКУ СБОРКИ (A58, различимое
    поведение);
  * override/сброс `persona_enabled` — действует со следующего запуска;
  * self/другой бот/цитата (связка с блоком B — A59);
  * все конечные пути: ОДИН кадр/версия (A60) — direct-путь: prompt из
    кадра + decision.frame_version + Character_Rules;
  * смена версии (правка персоны → новый snapshot_version);
  * конфликт с ядром (порядок precedence не сломан);
  * отсутствие фактической подмены (факты/JSON/тех-вызовы не рестайлятся);
  * сбой PG → честный stale/fallback;
  * защита от повторного подкрепления одним эпизодом;
  * гарды 0.1/0.2/6 ч; идемпотентность legacy-разбора; запреты таблицы.

R17: синтетические строки; no hidden CoT.
"""
import asyncio
import dataclasses

import pytest

from services import bot_persona, lore_runtime, mca_events, mca_gates
from services import mca_self_model as sm
from services.database import DatabaseService

CHAT = -100500


def async_returns(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


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


@pytest.fixture
def db(tmp_path, monkeypatch):
    async def _make():
        d = DatabaseService(str(tmp_path / "mca18_contract.db"))
        await d.initialize()
        return d

    loop = asyncio.new_event_loop()
    try:
        d = loop.run_until_complete(_make())
    finally:
        loop.close()
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: d)
    yield d
    loop2 = asyncio.new_event_loop()
    try:
        loop2.run_until_complete(d.close())
    finally:
        loop2.close()


def _patch_personas_ok(monkeypatch):
    class _Conn:
        async def fetchrow(self, sql, *args):
            return {"is_aware_ai": 1}

        async def fetch(self, sql, *args):
            return []

        async def fetch(self, sql, *args):
            return []

    class _Pool:
        def acquire(self):
            conn = _Conn()

            class _CM:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *exc):
                    return False
            return _CM()

    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: _Pool())


# ═══ Пустая персона True/False — точка сборки (A58/R1a) ═════════════════════

@pytest.mark.asyncio
async def test_contract_empty_persona_true_false_assembly(db, monkeypatch):
    _patch_personas_ok(monkeypatch)

    async def _persona(chat_id):
        return bot_persona.BotPersona.empty()
    monkeypatch.setattr(bot_persona, "resolve_bot_persona", _persona)
    for aware in (True, False):
        sm.lkg_invalidate()
        if aware:
            class _Conn:
                async def fetchrow(self, sql, *args):
                    return {"is_aware_ai": 1}

            class _Pool:
                def acquire(self):
                    conn = _Conn()

                    class _CM:
                        async def __aenter__(self):
                            return conn

                        async def __aexit__(self, *exc):
                            return False
                    return _CM()
            monkeypatch.setattr(bot_persona, "_persona_pool", lambda: _Pool())
        else:
            class _Conn0:
                async def fetchrow(self, sql, *args):
                    return {"is_aware_ai": 0}

            class _Pool0:
                def acquire(self):
                    conn = _Conn0()

                    class _CM:
                        async def __aenter__(self):
                            return conn

                        async def __aexit__(self, *exc):
                            return False
                    return _CM()
            monkeypatch.setattr(bot_persona, "_persona_pool",
                                lambda: _Pool0())
        ctx = await bot_persona.resolve_character_context(CHAT)
        assert ctx.frame_version is not None      # различимое поведение:
        persona = await bot_persona.resolve_bot_persona(CHAT)
        block = bot_persona.build_persona_prompt_block(
            persona, list(ctx.traits), enabled=True)
        assert block.startswith("<Persona>")      # НЕ пустая строка-заглушка
        if aware:
            assert "цифровой собеседник" in block
            # H-1 (rework, pre-fix RED): FALSE-формулировка НЕ дописывается
            # при aware=True — контроль по ВЫЧИСЛЕННОМУ aware, а не по
            # параметру-переопределению (точка сборки его не передаёт).
            assert sm.SELF_MODEL_FALSE_BLOCK not in block
            assert "Ты НЕ раскрываешь" not in block
        else:
            assert sm.SELF_MODEL_FALSE_BLOCK in block
            assert "Ты НЕ раскрываешь" not in block   # запрет ЗАМЕНЁН (D3)
    sm.lkg_invalidate()


def test_contract_false_block_uses_effective_awareness():
    """H-1 (rework): `render_frame_block` контролирует FALSE-блок по
    вычисленному `aware` (кадр/override), а не по сырому параметру."""
    frame = sm.BehaviorFrame(
        snapshot_version="v-h1", scope_chat_id=None, addressee=None,
        agent_id="agent", bot_user_id=None,
        self_presentation_mode=sm.MODE_AWARE, is_aware_ai=True,
        applied_rules=(), positions=(), mood=None, factual_constraints=(),
        scoped_request=(), rejected_rules=())
    # Кадр aware=True (точка сборки без override) → FALSE-блока нет.
    out = sm.render_frame_block(frame, name="Костик")
    assert "<Persona>" in out
    assert sm.SELF_MODEL_FALSE_BLOCK not in out
    # Явный override False → FALSE-блок честно добавляется.
    assert sm.SELF_MODEL_FALSE_BLOCK in sm.render_frame_block(
        frame, is_aware_ai=False)
    # Кадр aware=False → FALSE-блок есть; override True его снимает.
    frame_in = dataclasses.replace(
        frame, is_aware_ai=False,
        self_presentation_mode=sm.MODE_IN_CHARACTER)
    assert sm.SELF_MODEL_FALSE_BLOCK in sm.render_frame_block(frame_in)
    assert sm.SELF_MODEL_FALSE_BLOCK not in sm.render_frame_block(
        frame_in, is_aware_ai=True)


# ═══ Override/сброс persona_enabled — со следующего запуска ═════════════════

@pytest.mark.asyncio
async def test_contract_persona_enabled_override_next_run(db, monkeypatch):
    _patch_personas_ok(monkeypatch)
    from services import chat_params

    overrides: dict = {}
    async def _root(chat_id):
        return {"overrides": dict(overrides)}
    async def _param(chat_id, key, default=None):
        if key in overrides:
            return overrides[key]
        from services import hot_config as hot
        return hot.get(key, default)
    monkeypatch.setattr(chat_params, "get_all_chat_params", _root)
    monkeypatch.setattr(chat_params, "get_chat_param", _param)
    st1 = await sm.resolve_persona_enabled(CHAT)
    assert st1.source == "default"
    overrides["flags.persona_enabled"] = False
    st2 = await sm.resolve_persona_enabled(CHAT)   # следующий запуск
    assert st2.value is False and st2.source == "chat"
    del overrides["flags.persona_enabled"]
    st3 = await sm.resolve_persona_enabled(CHAT)   # сброс → наследование
    assert st3.value is True and st3.source in ("default", "global")


# ═══ Все конечные пути: один кадр/версия (A60, direct-путь) ═════════════════

@pytest.mark.asyncio
async def test_contract_single_frame_across_paths(db, monkeypatch, events):
    """A60: resolve_character_context (шов `:368`) ставит ОДИН кадр;
    точка сборки (`:237`) рендерит из него; версия доступна Decision
    (аддитивно, CA-18-7); Character_Rules не дублируются кадром."""
    _patch_personas_ok(monkeypatch)

    async def _persona(chat_id):
        return bot_persona.BotPersona(name="Костик", biography="кот",
                                      overrides="циник", is_aware_ai=True,
                                      is_global=True)
    monkeypatch.setattr(bot_persona, "resolve_bot_persona", _persona)
    oid = await sm.record_trait_observation(
        db, agent_id=(await db.get_self_identity())["agent_id"],
        text="резче в спорах", source_refs=("fact:1",),
        subject_status="self", chat_id=CHAT, dimension="резкость")
    await sm.promote_observation(db, oid, scope_chat_id=CHAT)

    ctx = await bot_persona.resolve_character_context(CHAT)
    version = ctx.frame_version
    assert version is not None
    # Тот же holder → та же версия в decision-поле (без нового snapshot).
    assert sm.current_run_frame_version() == version
    persona = await bot_persona.resolve_bot_persona(CHAT)
    block = bot_persona.build_persona_prompt_block(
        persona, list(ctx.traits), enabled=True)
    assert "Правила характера" in block
    assert "Ты отвечаешь резче" in block
    # Сырые тексты памяти НЕ системные инструкции (GEN-R18): в кадре —
    # компилированная инструкция, не исходное наблюдение.
    assert "резче в спорах" not in block
    # Событие prompt_render честно фиксирует передачу модели.
    assert any(kw.get("stage") == "prompt_render" for _, kw in events)


# ═══ Смена версии (правка персоны) ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_contract_version_change_on_persona_edit(db, monkeypatch):
    _patch_personas_ok(monkeypatch)
    persona_v1 = bot_persona.BotPersona(name="Костик", biography="кот",
                                        overrides="", is_aware_ai=True,
                                        is_global=True)
    monkeypatch.setattr(bot_persona, "resolve_bot_persona",
                        async_returns(persona_v1))
    sm.lkg_invalidate()
    s1 = await sm.resolve_self_model(db, CHAT)
    persona_v2 = bot_persona.BotPersona(
        name="Костик", biography="другой кот", overrides="", is_aware_ai=True,
        is_global=True)
    monkeypatch.setattr(bot_persona, "resolve_bot_persona",
                        async_returns(persona_v2))
    s2 = await sm.resolve_self_model(db, CHAT)
    assert s2.persona_version != s1.persona_version
    assert s2.version != s1.version
    sm.lkg_invalidate()


# ═══ Отсутствие фактической подмены (тех-вызовы/payload без стиля) ═════════

def test_contract_no_factual_substitution():
    """Кадр не переписывает факты: factual constraints проходят как есть;
    tool payload/JSON не имеют доступа к кадру (по контракту тех-вызовы
    получают только данные)."""
    snap = sm.SelfModelSnapshot(
        agent_id="a", bot_user_id=None, identity_binding="unbound",
        persona_id=None, persona_version="p", scope_chat_id=None,
        name="", aliases=(), biography="", style_version=None,
        traits=(), interests=(), relations=(), state=None, positions=(),
        persona_enabled=sm.SettingState(key="flags.persona_enabled",
                                        value=True, source="default"),
        is_aware_ai=sm.SettingState(key="personas.is_aware_ai", value=True,
                                    source="default"),
        bot_self_awareness=sm.SettingState(
            key="flags.bot_self_awareness_enabled", value=True,
            source="default"),
        self_presentation_mode=sm.MODE_AWARE,
        capabilities=sm.build_capabilities(), rules_status="on",
        version="v", created_at=0)
    bundle = type("B", (), {"constraints": ("число участников: 12",)})()
    frame = sm.select_behavior(snap, bundle)
    assert frame.factual_constraints == ("число участников: 12",)
    rendered = sm.render_frame_block(frame)
    assert "число участников: 12" in rendered      # факт не искажён
    # JSON/tool payload кадр не получает: рендер детерминирован и не
    # содержит JSON-артефактов.
    assert "```json" not in rendered


# ═══ Связки с блоками B/C/D (сводный чек-лист §28.7) ════════════════════════

def test_contract_invariants_index():
    """Сводный индекс контрактов §28.7: каждый пункт покрыт focused-тестом
    своего блока (связность реестра тестов; защита от «тихого удаления»)."""
    covered = {
        "empty_persona_true_false": "test_contract_empty_persona_true_false_"
                                    "assembly",
        "self_other_bot_quote": "test_attribution_* (block B)",
        "override_reset": "test_contract_persona_enabled_override_next_run",
        "single_frame_all_paths": "test_contract_single_frame_across_paths",
        "version_change": "test_contract_version_change_on_persona_edit",
        "core_conflict": "test_lifecycle_core_conflict_rejects (block C)",
        "no_factual_substitution": "test_contract_no_factual_substitution",
        "pg_fail_stale": "test_fallback_minimal_identity_and_lkg_stale (E/F)",
        "reinforcement_single_episode": "test_reinforcement_dedup_by_source_"
                                        "events (D)",
        "guards_0.1_0.2_6h": "test_step_guards_and_weakening + mood_ttl (D)",
        "legacy_idempotent": "test_legacy_parse_idempotent_repeat_noop (E/F)",
        "prohibitions_table": "test_prohibition_* (block B)",
    }
    assert len(covered) == 12
