"""SOUL-1 / W4 — SOUL-AMD.2.6: Core + жанровые правила для авторских текстов.

Уточнение владельца §2.1: сны, глубокий сон, рассказы о них, ностальгия, лор,
истории и воспоминания — публичная речь бота, а не служебный нейтральный
текст. Здесь проверяется: жанровые рамки зарегистрированы как заводские
редакции, композер ON даёт Core + жанр, OFF — прежний канон байт-в-байт, а
публикующий путь «Ностальгия» реально использует собранную строку.

TEST-LIFECYCLE: CONTRACT owner=soul-1/W4
"""
from types import SimpleNamespace

import pytest

from services import mca_authorial_speech as au
from services import prompt_composer as pc
from services import prompt_registry as pr
from services.nostalgia_prompts import NOSTALGIA_PROMPT
from services.nostalgia_worker import NostalgiaWorker


CORE = "ТЫ — ХАРАКТЕР ВЛАДЕЛЬЦА."


class _Hot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        return None

    def set_many(self, items):
        return None


class _Chat:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None


def test_genre_blocks_are_registered_factory_editions():
    for genre, block_id in au.GENRE_BLOCK_IDS.items():
        spec = pr.block(block_id)
        assert spec is not None, block_id
        assert spec.owner_lane == "W4" and spec.speech is True
        assert pr.factory_text(block_id) == au.genre_rules(genre)
        assert pr.factory_revision(block_id).startswith(pr.FACTORY_PREFIX)
        assert pr.FACTORY_REVISION_LABELS[block_id].startswith("genre-")
    assert pr.factory_text("genre.dream.rules")


def test_genre_rules_never_invent_facts_or_break_contracts():
    for genre in au.GENRES:
        text = au.genre_rules(genre).casefold()
        assert "не выдумывай" in text or "не выдавай" in text \
            or "не подменяй" in text, genre
    nostalgia = au.genre_rules("nostalgia").casefold()
    assert "служебное слово отказа" in nostalgia      # UNCHANGED остаётся
    assert "UNCHANGED" in NOSTALGIA_PROMPT


@pytest.mark.asyncio
async def test_composer_off_returns_legacy_canon_byte_for_byte(monkeypatch):
    """Паритет: выключенный композер не меняет ни одного байта канона."""
    from services import hot_config
    monkeypatch.delenv("UNIFIED_COMPOSER_ENABLED", raising=False)
    hot_config.set_config_cache(_Hot())
    try:
        system, manifest = await au.authorial_system(
            chat_id=-100, writer="nostalgia_writer", genre="nostalgia",
            legacy_canon=NOSTALGIA_PROMPT.format(max_words=60))
        assert manifest is None
        assert system == NOSTALGIA_PROMPT.format(max_words=60)
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_composer_on_adds_core_and_genre_rules(monkeypatch):
    from services import chat_params, hot_config
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot_config.set_config_cache(_Hot({
        "flags.unified_composer_enabled": True,
        "character.core": {"revision": 2, "enabled": True,
                           "full_text": CORE, "compact_text": CORE}}))
    chat_params.set_chat_params_cache(_Chat())
    pc.reset_state()
    try:
        system, manifest = await au.authorial_system(
            chat_id=-100, writer="nostalgia_writer", genre="nostalgia",
            legacy_canon=NOSTALGIA_PROMPT.format(max_words=60))
        assert manifest is not None
        assert CORE in system
        assert au.genre_rules("nostalgia") in system
        assert NOSTALGIA_PROMPT.format(max_words=60) in system
        core_layer = [t for t in manifest.layers if t.layer == "core"][0]
        assert core_layer.rendered is True
        assert manifest.writer == "nostalgia_writer"
        assert system.count(CORE) == 1
    finally:
        hot_config.set_config_cache(None)
        chat_params.set_chat_params_cache(None)
        pc.reset_state()


@pytest.mark.asyncio
async def test_unknown_genre_keeps_legacy_path():
    system, manifest = await au.authorial_system(
        chat_id=-100, writer="x", genre="unknown_genre",
        legacy_canon="КАНОН")
    assert system == "КАНОН" and manifest is None


@pytest.mark.asyncio
async def test_nostalgia_path_uses_composed_system(monkeypatch):
    """Реальная публикация «Ностальгии» получает Core + жанровую рамку."""
    from services import chat_params, hot_config

    class _LLM:
        def __init__(self):
            self.messages = None

        async def generate(self, messages, **kwargs):
            self.messages = messages
            return "кстати, помню эту историю"

    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot_config.set_config_cache(_Hot({
        "flags.unified_composer_enabled": True,
        "character.core": {"revision": 3, "enabled": True,
                           "full_text": CORE, "compact_text": CORE}}))
    chat_params.set_chat_params_cache(_Chat())
    pc.reset_state()

    class _Store:
        async def get_profile(self, chat_id):
            return SimpleNamespace(manual_lore="", auto_lore="")

    class _Db:
        async def list_chat_memes(self, chat_id, ts, limit=10):
            return []

    llm = _LLM()
    worker = NostalgiaWorker(_Db(), store=_Store(), llm=llm)
    candidate = {"text": "давний факт", "kind": "year_back",
                 "year_lines": ["[Кто-то 2025]: шутка"], "golden_lines": []}
    try:
        text = await worker._llm_once(candidate, -100)
        assert text == "кстати, помню эту историю"
        system_message = llm.messages[0]["content"]
        assert CORE in system_message
        assert au.genre_rules("nostalgia") in system_message
        assert "UNCHANGED" in system_message
        manifest = pc.get_manifest(-100, writer="nostalgia_writer")
        assert manifest is not None
    finally:
        hot_config.set_config_cache(None)
        chat_params.set_chat_params_cache(None)
        pc.reset_state()


@pytest.mark.asyncio
async def test_nostalgia_path_parity_when_composer_off(monkeypatch):
    from services import hot_config
    monkeypatch.delenv("UNIFIED_COMPOSER_ENABLED", raising=False)
    hot_config.set_config_cache(_Hot())

    class _LLM:
        def __init__(self):
            self.messages = None

        async def generate(self, messages, **kwargs):
            self.messages = messages
            return "UNCHANGED"

    class _Store:
        async def get_profile(self, chat_id):
            return None

    class _Db:
        async def list_chat_memes(self, chat_id, ts, limit=10):
            return []

    llm = _LLM()
    worker = NostalgiaWorker(_Db(), store=_Store(), llm=llm)
    try:
        await worker._llm_once({"text": "факт", "kind": "year_back",
                                "year_lines": ["[Имя 2025]: текст"],
                                "golden_lines": []}, -100)
        assert llm.messages[0]["content"] == NOSTALGIA_PROMPT.format(
            max_words=60)                       # байт-в-байт прежний канон
    finally:
        hot_config.set_config_cache(None)


def test_wired_and_pending_paths_are_visible_in_registry_notes():
    """Честная граница: проводка снов/лора/историй — следующий слайс."""
    dream = pr.block("genre.dream.rules")
    assert "следующий" in (dream.note or "") or "следующим" in (dream.note or "")
    lore = pr.block("genre.lore.rules")
    assert "следующим" in (lore.note or "") or "следующий" in (lore.note or "")
    nostalgia = pr.block("genre.nostalgia.rules")
    assert any("nostalgia_worker" in c for c in nostalgia.consumers)
