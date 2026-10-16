"""SOUL-1 / CORE-DOC — реестр, заводские редакции и правка Core через API.

Доказывается (SOUL-AMD.1.1/4.1/4.2/4.3, SOUL-02.7/02.8):

  * ``core.personality`` (полная) и ``core.personality.compact`` (компактная) —
    ДВА блока реестра одного документа ``character.core``; правка любого из
    них через ``prompt_factory.write_speech_value`` меняет эффективный Core и
    НИКОГДА не трогает вторую редакцию;
  * заводской сброс возвращает только правленую редакцию, история/откат — на
    блок (та же машинерия §4, что у остальных речевых блоков);
  * per-chat правка наследует глобальный документ и не меняет глобальное ядро;
  * выбор редакции (полная/компактная) детерминирован и не вызывает LLM:
    причина — из закрытого набора ``CORE_DETAIL_REASONS``;
  * guard ``FACTORY_SET_SHA256_12`` по-прежнему падает при правке канона без
    осознанной регистрации.

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.1.1/4.1–4.3 (soul-1, CORE-DOC)
"""
from __future__ import annotations

import inspect

import pytest

from services import chat_params
from services import hot_config as hot
from services import prompt_composer as pc
from services import prompt_factory as pf
from services import prompt_registry as pr

FULL_NEW = "ПОЛНЫЙ ТЕКСТ ВЛАДЕЛЬЦА: наблюдательный, язвительный, абсурдный."
COMPACT_NEW = "КОМПАКТ ВЛАДЕЛЬЦА: тот же характер, короче."
CHAT_COMPACT = "КОМПАКТ ЭТОГО ЧАТА."


class FakeConfigCache:
    """ConfigCache-подобный слой: глобальные значения + журнал ревизий."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes: list[tuple] = []

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_updated_at(self, key):
        return None

    async def set(self, key, value, category):
        self.values[key] = value
        self.writes.append((key, value, category))


class FakeChatCache:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})
        self.writes: list[tuple] = []

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}

    async def set_chat_params(self, chat_id, patch, **kwargs):
        self.writes.append((int(chat_id), dict(patch)))
        self.overrides[int(chat_id)] = dict(patch.get("overrides") or {})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pr.reset_cache()
    monkeypatch.delenv("UNIFIED_COMPOSER_ENABLED", raising=False)
    monkeypatch.delenv("COMPOSER_LAYER_BUDGET_TOKENS", raising=False)
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    yield
    pr.reset_cache()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


@pytest.fixture
def live_config():
    """Конфиг-слой доступен (в проде это PG): заводская редакция действует."""
    cache = FakeConfigCache({})
    chats = FakeChatCache({})
    hot.set_config_cache(cache)
    chat_params.set_chat_params_cache(chats)
    pc.reset_state()
    return {"cache": cache, "chats": chats}


# ═══ правка каждой редакции через API реестра ═══════════════════════════════

@pytest.mark.asyncio
async def test_editing_full_block_changes_effective_core_only_full(live_config):
    cache = live_config["cache"]
    factory_compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    result = await pf.write_speech_value(pr.CORE_FULL_BLOCK_ID, FULL_NEW,
                                         cache=cache, actor="owner")
    assert result["applied"] is True and result["pg_key"] == pr.CORE_DOC_KEY
    doc = cache.values[pr.CORE_DOC_KEY]
    assert doc["full_text"] == FULL_NEW
    assert "compact_text" not in doc, "правка полной редакции тронула компактную"
    ref = await pc.resolve_core_ref(101)
    assert ref.text == FULL_NEW
    assert ref.detail_level == "full" and ref.detail_reason == "owner_setting"
    assert ref.source == "global"
    # Вторая редакция осталась заводской и видна отдельно.
    compact_row = pr.effective_prompt(pr.CORE_COMPACT_BLOCK_ID,
                                      pg_value=doc)
    assert compact_row.text == factory_compact
    assert compact_row.differs_from_factory is False


@pytest.mark.asyncio
async def test_editing_compact_block_changes_effective_core_only_compact(
        live_config):
    cache = live_config["cache"]
    factory_full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    await pf.write_speech_value(pr.CORE_FULL_BLOCK_ID, FULL_NEW, cache=cache)
    result = await pf.write_speech_value(pr.CORE_COMPACT_BLOCK_ID, COMPACT_NEW,
                                         cache=cache)
    assert result["applied"] is True
    doc = cache.values[pr.CORE_DOC_KEY]
    assert doc["compact_text"] == COMPACT_NEW
    assert doc["compact_words"] == len(COMPACT_NEW.split())
    assert doc["full_text"] == FULL_NEW, "правка компактной тронула полную"
    ref = await pc.resolve_core_ref(101)
    assert ref.text == COMPACT_NEW
    assert ref.detail_level == "compact" and ref.detail_reason == "owner_setting"
    full_row = pr.effective_prompt(pr.CORE_FULL_BLOCK_ID, pg_value=doc)
    assert full_row.text == FULL_NEW
    assert full_row.differs_from_factory is True
    assert pr.effective_prompt(pr.CORE_FULL_BLOCK_ID).text == factory_full


@pytest.mark.asyncio
async def test_factory_reset_restores_only_edited_block_with_history(
        live_config):
    cache = live_config["cache"]
    await pf.write_speech_value(pr.CORE_FULL_BLOCK_ID, FULL_NEW, cache=cache)
    await pf.write_speech_value(pr.CORE_COMPACT_BLOCK_ID, COMPACT_NEW,
                                cache=cache)
    plan = await pf.plan_factory_reset(pr.CORE_FULL_BLOCK_ID, cache=cache)
    assert plan["applies"] is True and plan["changed"] is True
    assert plan["document_field"] == "full_text"
    assert cache.writes[-1][1] != pr.factory_text(pr.CORE_FULL_BLOCK_ID), \
        "предпросмотр сброса записал значение"
    done = await pf.apply_factory_reset(pr.CORE_FULL_BLOCK_ID, cache=cache,
                                        actor="owner")
    assert done["applied"] is True
    doc = cache.values[pr.CORE_DOC_KEY]
    assert doc["full_text"] == pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    assert doc["compact_text"] == COMPACT_NEW, "сброс тронул вторую редакцию"
    history = await pf.history_for(pr.CORE_FULL_BLOCK_ID, cache=cache)
    assert [h["kind"] for h in history] == ["factory_reset"]
    assert history[0]["text"] == FULL_NEW
    assert await pf.history_for(pr.CORE_COMPACT_BLOCK_ID, cache=cache) == []
    # Повторный сброс — идемпотентный no-op.
    again = await pf.apply_factory_reset(pr.CORE_FULL_BLOCK_ID, cache=cache)
    assert again["applied"] is False and again["reason"] == "already_factory"


@pytest.mark.asyncio
async def test_chat_scope_core_edit_inherits_global_and_stays_local(live_config):
    cache = live_config["cache"]
    chats = live_config["chats"]
    await pf.write_speech_value(pr.CORE_FULL_BLOCK_ID, FULL_NEW, cache=cache)
    result = await pf.write_speech_value(pr.CORE_COMPACT_BLOCK_ID, CHAT_COMPACT,
                                         cache=cache, chat_id=777, actor="owner",
                                         get_root=chats.get_chat_params,
                                         set_root=chats.set_chat_params)
    assert result["applied"] is True and result["scope"] == "chat"
    chat_doc = chats.overrides[777][pr.CORE_DOC_KEY]
    assert chat_doc["compact_text"] == CHAT_COMPACT
    assert chat_doc["full_text"] == FULL_NEW, "чат-правка потеряла наследование"
    chat_ref = await pc.resolve_core_ref(777)
    assert chat_ref.source == "chat" and chat_ref.text == CHAT_COMPACT
    global_ref = await pc.resolve_core_ref(101)
    assert global_ref.source == "global" and global_ref.text == FULL_NEW
    # Снятие override возвращает наследование, а не заводской сброс.
    await pf.reset_chat_override(777, pr.CORE_COMPACT_BLOCK_ID,
                                 get_root=chats.get_chat_params,
                                 set_root=chats.set_chat_params)
    assert pr.CORE_DOC_KEY not in chats.overrides[777]
    assert cache.values[pr.CORE_DOC_KEY]["full_text"] == FULL_NEW


# ═══ детерминизм выбора и отсутствие LLM ════════════════════════════════════

def test_core_selection_is_deterministic_and_reasons_are_closed():
    factory_full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    factory_compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    doc = {"revision": 3, "full_text": "ПОЛНАЯ", "compact_text": "КОМПАКТ"}
    first = pr.core_selection(doc, source="global")
    second = pr.core_selection(dict(doc), source="global")
    assert first == second, "выбор редакции не детерминирован"
    assert first["level"] == "compact" and first["reason"] == "document_default"
    assert first["revision"].startswith("r3.")
    cases = [
        (None, None, "factory_default"),
        (doc, None, "document_default"),
        ({**doc, "detail_level": "full"}, None, "owner_setting"),
        ({**doc, "detail_level": "full"}, 1, "context_budget"),
        ({**doc, "detail_level": "full"}, 10 ** 9, "owner_setting"),
        ({"revision": 1, "compact_text": "К"}, None, "document_default"),
    ]
    for payload, budget, reason in cases:
        selection = pr.core_selection(payload, source="global",
                                      budget_tokens=budget)
        assert selection["reason"] == reason, (payload, budget)
        assert selection["reason"] in pr.CORE_DETAIL_REASONS
        assert selection["level"] in pr.CORE_DETAIL_LEVELS
        assert selection["text"].strip()
    # Пустое поле документа наследует заводскую редакцию ИМЕННО ЭТОГО поля.
    inherited = pr.core_selection({"full_text": "ТОЛЬКО ПОЛНАЯ"}, source="global")
    assert inherited["full_text"] == "ТОЛЬКО ПОЛНАЯ"
    assert inherited["compact_text"] == factory_compact
    assert pr.core_selection(None, source="default")["full_text"] == factory_full


def test_core_selection_reports_missing_editor_when_factory_is_gone(monkeypatch):
    """Защитные ветки «редакции нет ни у владельца, ни в заводской».

    Достижимы только при недоступном заводском тексте (сломанный код-канон) —
    тогда выбор честно называет причину, а не молча подставляет другую редакцию
    без объяснения.
    """
    original = pr.factory_text
    blank = {pr.CORE_COMPACT_BLOCK_ID}

    def _patched(block_id):
        return "" if block_id in blank else original(block_id)

    monkeypatch.setattr(pr, "factory_text", _patched)
    # Компактной редакции нет ни у владельца, ни в заводской → действует полная.
    selection = pr.core_selection({"revision": 1, "full_text": "ПОЛНАЯ"})
    assert selection["level"] == "full" and selection["text"] == "ПОЛНАЯ"
    assert selection["reason"] == "compact_text_missing"
    # Полной тоже нет, а владелец просил full → честный даунгрейд на компакт.
    blank.add(pr.CORE_FULL_BLOCK_ID)
    selection_full = pr.core_selection({"revision": 1, "detail_level": "full",
                                        "compact_text": "КОМПАКТ"})
    assert selection_full["level"] == "compact"
    assert selection_full["reason"] == "full_text_missing"
    assert selection_full["text"] == "КОМПАКТ"
    for reason in (selection["reason"], selection_full["reason"]):
        assert reason in pr.CORE_DETAIL_REASONS


def test_core_selection_path_contains_no_llm_call():
    """Компактная редакция не «пересказывается» моделью на каждом ходе.

    Доказательство: функции выбора/вида СИНХРОННЫ (нет ``await`` — нет ни I/O,
    ни обращения к модели), а резолвер композера не ссылается на LLM-клиент.
    """
    for func in (pr.core_selection, pr.core_selection_view):
        source = inspect.getsource(func)
        assert "await " not in source, func.__name__
        assert "async def" not in source, func.__name__
    for func in (pc.resolve_core_ref, pc.core_inspection):
        source = inspect.getsource(func)
        for token in ("llm_client", "llm_gateway", "llm_probe", ".generate(",
                      "aiohttp", "requests."):
            assert token not in source, (func.__name__, token)


@pytest.mark.asyncio
async def test_resolve_core_does_not_write_or_call_llm(live_config):
    cache = live_config["cache"]
    before = dict(cache.values)
    ref = await pc.resolve_core_ref(101)
    assert ref.text == pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert cache.writes == [], "резолв Core записал в конфиг-слой"
    assert dict(cache.values) == before
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12


# ═══ видимость для UI/Inspector и guard реестра ═════════════════════════════

def test_core_blocks_visible_in_registry_view_and_unmanaged_list():
    from services import param_catalog as pcat

    rows = {row["block_id"]: row for row in pr.registry_view()}
    for block_id, field in ((pr.CORE_FULL_BLOCK_ID, "full_text"),
                            (pr.CORE_COMPACT_BLOCK_ID, "compact_text")):
        row = rows[block_id]
        assert row["pg_doc_field"] == field
        assert row["pg_key"] == pr.CORE_DOC_KEY
        assert row["factory_revision"].startswith(pr.FACTORY_PREFIX)
        assert row["speech"] is True
        assert row["provenance_required"] is False, (
            "у Core нет legacy persisted-значений (ключ в проде не существовал): "
            "удерживать нечего, правка документа действует сразу (SOUL-02.7)")
    unmanaged = {row["block_id"] for row in pcat.unmanaged_speech_blocks()}
    assert {pr.CORE_FULL_BLOCK_ID, pr.CORE_COMPACT_BLOCK_ID} <= unmanaged, (
        "Core обязан быть виден UI-слою как блоки без ключа каталога (W6)")


def test_effective_prompt_reads_document_field_and_reports_missing():
    doc = {"revision": 4, "full_text": "ПОЛНАЯ", "compact_text": "КОМПАКТ"}
    full = pr.effective_prompt(pr.CORE_FULL_BLOCK_ID, pg_value=doc)
    assert full.text == "ПОЛНАЯ" and full.source == "global"
    assert full.differs_from_factory is True
    assert full.factory_revision.startswith(pr.FACTORY_PREFIX)
    empty = pr.effective_prompt(pr.CORE_COMPACT_BLOCK_ID, pg_value={"revision": 1})
    assert empty.text == pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert "document_field_absent" in empty.diagnostics


def test_factory_guard_fails_when_canon_edited_without_registration(monkeypatch):
    """Guard SOUL-AMD.3.2 цел: правка канона без бампа ломает отпечаток."""
    import services.chat_prompts as cp

    pr.reset_cache()
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12
    monkeypatch.setattr(cp, "PERSONALITY_CORE_FULL_TEXT",
                        cp.PERSONALITY_CORE_FULL_TEXT + "\n\nПРАВКА БЕЗ РЕГИСТРАЦИИ")
    pr.reset_cache()
    assert pr.factory_set_fingerprint() != pr.FACTORY_SET_SHA256_12, (
        "правка канона Core не отражается в guard-отпечатке")
