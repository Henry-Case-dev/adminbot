"""SOUL-1 (W2) — сохранённые владельческие значения ЦЕЛЫ (data safety).

Уточнение владельца (`source-architectural-clarification.md` §1.2/§4.6,
карта `requirements-map-amendment.json`: SOUL-AMD.1.2 / SOUL-AMD.8.4)
**отменило** прежние SOUL-04.4/15.3: legacy speech-кастомы
(`prompts.direct_chat_verbalizer_system_prompt` / `prompts.direct_chat_system_prompt`)
НЕ должны быть активным слоем, а удаление — отдельный слайс-amendment с
backup (§7.2). Поэтому здесь доказывается только retention:

* аксессоры Core/Style Policy и композер — READ-ONLY: ни одной записи в
  `bot_settings`/`chat_params` при резолве и сборке;
* сохранённое значение читается БАЙТ-В-БАЙТ (backup retrievability до
  миграции W1) и не нормализуется/не мутируется чтением;
* детерминированная вычистка известных legacy-слепков остаётся в своём
  владельце (`response_extent.scrub_for_plan`) и не задваивается в композере;
* повторный резолв/сборка не меняет сохранённый документ (idempotent read).

BLOCKER (review-w2 F1; маркер в `plans/features/soul-1/w2-composer-report.md`):
`UNIFIED_COMPOSER_ENABLED` НЕ включать до слайса-amendment, который уберёт
legacy speech-кастомы из effective-слоя (backup §7.2, SOUL-AMD.1.2/8.4):
до этого ON рендерит старый кастом слоем `channel_contract`.

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/W2 (SOUL-AMD.1.2/8.4 retention;
SOUL-16.4.1 — один владелец нормализации)
"""
from __future__ import annotations

import inspect
import json

import pytest

from services import chat_params
from services import hot_config as hot
from services import prompt_composer as pc
from services import response_extent as _extent

CUSTOM_BASE = ("МОЙ РУЧНОЙ КАНАЛ:  двойные  пробелы, «елочки» и — тире — "
               "сохранены как есть.\n\nВТОРАЯ СТРОКА КАСТОМА")
CUSTOM_CORE = "РУЧНОЙ ЯДЕРНЫЙ ТЕКСТ владельца с двойным  пробелом"
CUSTOM_POLICY_SOFT = "не ставить точки в конце коротких фраз"


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

    def set_default(self, key, value):
        self.writes.append(("set_default", key))


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


@pytest.fixture
def custom_config():
    pc.reset_state()
    hot_cache = FakeHot({
        "prompts.direct_chat_verbalizer_system_prompt": CUSTOM_BASE,
        "character.core": {"revision": 11, "enabled": True,
                           "full_text": CUSTOM_CORE,
                           "compact_text": CUSTOM_CORE,
                           "detail_level": "compact", "origin": "owner_edit"},
        "style.policy": {"revision": 2, "rules": [],
                         "soft_instructions": [{"id": "s1", "enabled": True,
                                                "text": CUSTOM_POLICY_SOFT}]},
    })
    chat_cache = FakeChatCache({})
    hot.set_config_cache(hot_cache)
    chat_params.set_chat_params_cache(chat_cache)
    yield {"hot": hot_cache, "chat": chat_cache}
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


@pytest.mark.asyncio
async def test_resolve_and_compose_never_write(custom_config):
    core = await pc.resolve_core_ref(303)
    policy = await pc.resolve_style_policy_ref(303)
    await pc.turn_snapshot(303, "run-1")
    pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=303,
        base_prompt=CUSTOM_BASE, core=core, style_policy=policy,
        gates=pc.GateState(unified_composer_enabled=True,
                           humor_library_enabled=True)))
    assert custom_config["hot"].writes == []
    assert custom_config["chat"].writes == []


@pytest.mark.asyncio
async def test_stored_custom_base_is_retrievable_but_not_active_layer(
        custom_config):
    """F1 (review-w2): retention кастома БЕЗ утверждения «эффект сохранён».

    Прежний `test_custom_base_goes_to_prompt_byte_for_byte` доказывал, что
    кастом присутствует в effective prompt, — уточнение владельца это отменило.
    Отсюда остаётся только то, что требуется сейчас: сохранённое значение
    доступно байт-в-байт (его можно забэкапить/вернуть в слайсе-amendment),
    сборка его не перезаписывает и не нормализует.
    """
    from services.prompt_style_blocks import resolve_prompt_with_source
    text, source = resolve_prompt_with_source(
        "prompts.direct_chat_verbalizer_system_prompt", "КОД-КАНОН")
    assert text == CUSTOM_BASE, "сохранённый кастом недоступен (потеря данных)"
    assert source == "global"
    before = json.dumps(custom_config["hot"].values, sort_keys=True,
                        ensure_ascii=False)
    pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=303,
        base_prompt=text, base_source=source, include_mode_block=False,
        gates=pc.GateState(unified_composer_enabled=True)))
    after = json.dumps(custom_config["hot"].values, sort_keys=True,
                       ensure_ascii=False)
    assert before == after, "сборка изменила сохранённый документ"
    assert custom_config["hot"].writes == []
    again, source_again = resolve_prompt_with_source(
        "prompts.direct_chat_verbalizer_system_prompt", "КОД-КАНОН")
    assert again == CUSTOM_BASE and source_again == "global"



@pytest.mark.asyncio
async def test_custom_core_document_not_normalized(custom_config):
    core = await pc.resolve_core_ref(303)
    assert core.text == CUSTOM_CORE           # без strip/нормализации
    assert core.source == "global" and core.document_revision == "11"
    manifest = pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=303,
        base_prompt="КАНАЛ", core=core,
        gates=pc.GateState(unified_composer_enabled=True)))
    assert manifest.system.count(CUSTOM_CORE) == 1


@pytest.mark.asyncio
async def test_known_legacy_scrub_stays_with_response_extent_owner(
        custom_config):
    """Композер НЕ занимается нормализацией старого кап-текста сам."""
    source = inspect.getsource(pc)
    assert "strip_cap_phrases" not in source, \
        "второй владелец нормализации запрещён (SOUL-16.4.1)"
    assert "scrub_for_plan(" not in source, \
        "второй владелец нормализации запрещён (SOUL-16.4.1)"
    # Владелец скраба — response_extent: точное ожидаемое поведение.
    assert _extent.scrub_for_plan(CUSTOM_BASE, None) == (CUSTOM_BASE, 0)
    plan = _extent.ResponsePlan(task_kind="explanation", extent="longform",
                                structure="answer", delivery_hint="plain")
    # Кастом без известных cap-фраз владелец НЕ трогает (0 удалений).
    assert _extent.scrub_for_plan(CUSTOM_BASE, plan) == (CUSTOM_BASE, 0)
    # Известная legacy-фраза удаляется ровно один раз и только под план.
    cap = "Ты должен отвечать ОЧЕНЬ коротко."
    with_cap = f"КАНАЛ.\n\n{cap}\n\nХвост."
    cleaned, removed = _extent.scrub_for_plan(with_cap, plan)
    assert removed == 1 and cap not in cleaned
    assert _extent.scrub_for_plan(with_cap, None) == (with_cap, 0)
    assert _extent.scrub_for_plan(cleaned, plan) == (cleaned, 0)  # идемпотентно


@pytest.mark.asyncio
async def test_repeated_resolve_does_not_mutate_stored_custom(custom_config):
    before = json.dumps(custom_config["hot"].values, sort_keys=True,
                        ensure_ascii=False)
    for _ in range(3):
        core = await pc.resolve_core_ref(303)
        policy = await pc.resolve_style_policy_ref(303)
        _sys, manifest = None, pc.compose_prompt(pc.PromptPlan(
            profile="speech_plain", writer="l2_writer", chat_id=303,
            base_prompt=CUSTOM_BASE, core=core, style_policy=policy,
            gates=pc.GateState(unified_composer_enabled=True)))
        assert manifest.versions["core"].startswith("r11.")
    after = json.dumps(custom_config["hot"].values, sort_keys=True,
                       ensure_ascii=False)
    assert before == after, "чтение изменило сохранённый документ"
    assert custom_config["hot"].writes == []
    assert custom_config["chat"].writes == []
