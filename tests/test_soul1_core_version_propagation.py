"""SOUL-1 (W2) — версии Core: hot apply, изоляция чатов, снапшот хода.

Доказывает (SOUL-15.5, SOUL-02.7/02.8, шов 1 контракта композера):

* правка документа Core действует со следующего ответа (hot, без рестарта) и
  меняет ревизию слоя/`manifest_id`;
* per-chat переопределение видно как `source=chat` и НЕ меняет глобальное ядро
  (локальный чат не подменяет глобальное молча);
* начатый ход держит immutable snapshot: вторая стадия того же хода получает
  ТУ ЖЕ ревизию `identity`/Core, даже если владелец сохранил правку в середине.

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/W2 (SOUL-15.5, SOUL-03.6)
"""
from __future__ import annotations

import pytest

from services import chat_params
from services import hot_config as hot
from services import prompt_composer as pc

CORE_GLOBAL = ("Ты — живой участник чата: наблюдательный и язвительный. "
               "ЯДРО_ГЛОБАЛЬНОЕ")
CORE_A = "Ты — живой участник чата, но в этом чате мягче. ЯДРО_ЧАТА_А"
BASE = "КАНАЛ"
IDENTITY_1 = "<Persona>\nИмя: Бот.\n</Persona>"
IDENTITY_2 = "<Persona>\nИмя: Бот.\n</Persona>\n\n<Character_Rules>\nбез ИИ\n</Character_Rules>"


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes: list = []

    def get(self, key, default=None):
        if key in self.values:
            return self.values[key]
        return default

    def set(self, key, value):
        self.writes.append(("set", key))

    def set_many(self, items):
        self.writes.append(("set_many", len(items)))


class FakeChatCache:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})
        self.writes: list = []

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None

    async def set_chat_params(self, *args, **kwargs):
        self.writes.append(("set_chat_params", args))


def core_doc(revision: int, text: str, *, enabled: bool = True) -> dict:
    return {"revision": revision, "enabled": enabled, "full_text": text,
            "compact_text": text, "compact_words": len(text.split()),
            "detail_level": "compact", "origin": "owner_edit",
            "updated_at": "2026-10-16T00:00:00Z", "updated_by": 1}


@pytest.fixture
def fake_config():
    pc.reset_state()
    holder = {"hot": FakeHot({"character.core": core_doc(3, CORE_GLOBAL)}),
              "chat": FakeChatCache({})}
    hot.set_config_cache(holder["hot"])
    chat_params.set_chat_params_cache(holder["chat"])
    yield holder
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


@pytest.mark.asyncio
async def test_core_edit_hot_applies_and_changes_manifest(fake_config):
    first = await pc.resolve_core_ref(101)
    assert first.text == CORE_GLOBAL
    assert first.revision.startswith("r3.")
    assert first.source == "global"
    manifest_a = pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=101,
        base_prompt=BASE, core=first,
        gates=pc.GateState(unified_composer_enabled=True)))
    assert first.text in manifest_a.system
    # Владелец сохранил правку ядра — следующий ответ берёт новую ревизию.
    fake_config["hot"].values["character.core"] = core_doc(
        4, CORE_GLOBAL + " ПРАВКА")
    second = await pc.resolve_core_ref(101)
    assert second.revision.startswith("r4.")
    assert second.text == CORE_GLOBAL + " ПРАВКА"
    manifest_b = pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=101,
        base_prompt=BASE, core=second,
        gates=pc.GateState(unified_composer_enabled=True)))
    assert manifest_b.manifest_id != manifest_a.manifest_id
    assert manifest_b.versions["core"] != manifest_a.versions["core"]
    # Смена модели/провайдера версию НЕ меняет (инвариант I-2): в версиях нет
    # ни модели, ни провайдера.
    assert "model" not in manifest_b.versions
    assert "provider" not in manifest_b.versions


@pytest.mark.asyncio
async def test_core_two_chats_isolated_and_visible_source(fake_config):
    fake_config["chat"].overrides[202] = {
        "character.core": core_doc(9, CORE_A)}
    chat_a = await pc.resolve_core_ref(202)
    chat_b = await pc.resolve_core_ref(101)
    assert chat_a.source == "chat" and chat_a.text == CORE_A
    assert chat_b.source == "global" and chat_b.text == CORE_GLOBAL
    assert chat_a.revision != chat_b.revision
    assert chat_a.source == "chat"
    # Правка глобального ядра не переписывает чат-переопределение.
    fake_config["hot"].values["character.core"] = core_doc(
        5, CORE_GLOBAL + " НОВОЕ")
    assert (await pc.resolve_core_ref(202)).text == CORE_A
    assert (await pc.resolve_core_ref(101)).text == CORE_GLOBAL + " НОВОЕ"
    # Каждый чат видит ровно один Core и не «подтягивает» чужие черты.
    manifest_a = pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=202,
        base_prompt=BASE, core=await pc.resolve_core_ref(202),
        gates=pc.GateState(unified_composer_enabled=True)))
    assert manifest_a.system.count(CORE_A) == 1
    assert CORE_GLOBAL not in manifest_a.system


@pytest.mark.asyncio
async def test_in_flight_snapshot_immutable(fake_config):
    snap_1 = await pc.turn_snapshot(101, "run-1")
    assert snap_1.core.revision.startswith("r3.")
    fake_config["hot"].values["character.core"] = core_doc(4, CORE_GLOBAL + "!")
    in_flight = await pc.turn_snapshot(101, "run-1")
    assert in_flight.core.revision == snap_1.core.revision, \
        "правка в середине хода расколола сборку"
    assert in_flight.core.text == CORE_GLOBAL
    next_turn = await pc.turn_snapshot(101, "run-2")
    assert next_turn.core.revision.startswith("r4.")


@pytest.mark.asyncio
async def test_identity_rendered_once_per_turn_with_shared_version(fake_config):
    from services.direct_chat_service import DirectChatService as D

    class Stub:
        _compose_speech_system = D._compose_speech_system
        _composer_gates = None

    svc = Stub()
    gates = pc.GateState(unified_composer_enabled=True)
    _sys1, m1 = await D._compose_speech_system(
        svc, chat_id=101, writer="tool_phase", run_id="run-9",
        base_prompt=BASE, base_key="prompts.direct_chat_system_prompt",
        base_default=BASE, gates=gates, include_mode_block=False,
        identity_text=IDENTITY_1)
    # Вторая стадия того же хода: текст личности другой, но ревизия/рендер
    # берутся из снапшота хода (SOUL-03.6: в одном ходу личность одна).
    _sys2, m2 = await D._compose_speech_system(
        svc, chat_id=101, writer="l2_writer", run_id="run-9",
        base_prompt=BASE, base_key="prompts.direct_chat_system_prompt",
        base_default=BASE, gates=gates, include_mode_block=False,
        identity_text=IDENTITY_2)
    assert m1.versions["identity"] == m2.versions["identity"]
    assert m1.system.count(IDENTITY_1) == 1
    assert IDENTITY_2 not in m2.system, "личность перерисована вторым вызовом"
    trace1 = [t for t in m1.layers if t.layer == "identity"][0]
    trace2 = [t for t in m2.layers if t.layer == "identity"][0]
    assert trace1.revision == trace2.revision
    assert trace1.chars == trace2.chars
    # Новый ход — новый рендер.
    _sys3, m3 = await D._compose_speech_system(
        svc, chat_id=101, writer="l2_writer", run_id="run-10",
        base_prompt=BASE, base_key="prompts.direct_chat_system_prompt",
        base_default=BASE, gates=gates, include_mode_block=False,
        identity_text=IDENTITY_2)
    assert m3.versions["identity"] != m1.versions["identity"]


@pytest.mark.asyncio
async def test_core_absent_is_visible_state_not_error(fake_config):
    fake_config["hot"].values.pop("character.core")
    ref = await pc.resolve_core_ref(101)
    assert ref.text == "" and ref.skip_reason == "core_absent"
    manifest = pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=101,
        base_prompt=BASE, core=ref, include_mode_block=False,
        gates=pc.GateState(unified_composer_enabled=True)))
    core = [t for t in manifest.layers if t.layer == "core"][0]
    assert core.rendered is False and core.skip_reason == "core_absent"
    assert manifest.system == BASE
