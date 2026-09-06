"""Раунд 9 (AGI Memory, T-819/B4, spec §3.1.4/Q3) — инжект <user_relations>
в direct_chat.

Проверки: блок СРАЗУ ПОСЛЕ <Target_User> (kind "relations" в uncuttable —
бюджет-урезание его не трогает); гейты: флаг flags.relations_tone_enabled
off → блока нет; per-chat relations_enabled=false (PG-профиль) → нет;
RelationsService не установлен/ошибка/relation None → нет (fail-open);
только группы (chat_id < 0); формат карточки ЦЕЛЕВОГО собеседника (D-14):
«{Имя}: {стадия_ru}, в чате с {first_seen:ГГГГ-ММ}, {msg30} сообщ. за 30
дней» + суффикс «(ручная пометка админа)» при manual-стадии + «| пометка:
{note}»; cap limits.relations_inject_max_chars (600) с маркером
«…[обрезано]»; XML-экранирование заметки. (Канон R9 описан в
tests/test_direct_chat_prompts.py.)
"""
from unittest.mock import MagicMock

import pytest

from services import hot_config as hot
from services import lore_runtime
from services.direct_chat_service import DirectChatService
from services.lore_cache import LoreProfile
from services.summary_aliases import AliasResolver

CHAT_ID = -1002661910336


def make_profile(*, relations_enabled: bool = True,
                 chat_id: int = CHAT_ID) -> LoreProfile:
    return LoreProfile(
        chat_id=chat_id, manual_lore="", auto_lore="",
        auto_enabled=True, auto_period_hours=24,
        auto_window_hours=24, is_active=True,
        last_auto_at=None, updated_at="2026-09-06T10:00:00+00:00",
        relations_enabled=relations_enabled)


class FakeMemory:
    async def get_window_messages(self, chat_id):
        return []

    async def get_rag_facts(self, chat_id, query, *,
                            include_direct_reply=False):
        return []

    async def get_rag_context(self, chat_id, query, *,
                              sort_by_timestamp=False, include_direct_reply=False):
        return ""


class FakeLoreCache:
    """ChatLoreCache-заглушка: профили по chat_id; сбой — настраиваемо."""

    def __init__(self, profiles=None, error=None):
        self.profiles = dict(profiles or {})
        self.error = error

    async def get(self, chat_id):
        if self.error is not None:
            raise self.error
        return self.profiles.get(chat_id)


class FakeDB:
    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return None

    async def set_user_tone_preset(self, chat_id, user_id, preset):
        pass

    async def clear_direct_dialogue(self, chat_id, target_user):
        return 0

    async def forget_direct_facts(self, chat_id, target_user, phrase, now_ts):
        return 0

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return None

    async def get_persona_card(self, chat_id, canon, limit, now):
        return {"facts": [], "links": []}


class FakeRelations:
    """RelationsService-заглушка: карточка по user_id; сбой — настраиваемо."""

    def __init__(self, relation=None, error=None):
        self.relation = relation
        self.error = error
        self.calls = []

    async def get_user_relation(self, chat_id, user_id):
        self.calls.append((chat_id, int(user_id)))
        if self.error is not None:
            raise self.error
        return dict(self.relation) if self.relation else None


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


def _message(text="привет, бот"):
    m = MagicMock()
    m.text = text
    m.message_id = 100
    return m


def _service(db=None, cache=None):
    return DirectChatService(
        FakeMemory(), db or FakeDB(), MagicMock(), AliasResolver("{}"),
        bot_id=12345, bot_username="test_bot",
        breaker=None, cache=None, chat_lore_cache=cache)


async def _build(service, chat_id=CHAT_ID, target_user_id=10):
    return [b for b in await service._build_user_content(
        chat_id, _message(), "Вася", target_user_id=target_user_id) if b]


def _relation(uid=10, stage="veteran", stage_manual=None, note=None,
              score=12.34, first_seen=1730505600, msg30=214):
    """Карточка RelationsService (D-14: инжект = карточка целевого юзера с
    first_seen/msg30; 1730505600 = 2024-11-02)."""
    return {"user_id": uid, "stage": stage, "stage_auto": stage,
            "stage_manual": stage_manual, "activity_score": score,
            "first_seen": first_seen, "msg30": msg30,
            "note": note}


def _with_runtime(relations):
    lore_runtime.set_lore_components(relations=relations)


def _cleanup_runtime():
    lore_runtime.reset_lore_runtime()


class TestRelationsInject:
    @pytest.mark.asyncio
    async def test_block_right_after_target_user(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(_relation()))
        try:
            blocks = await _build(_service(cache=cache))
            ti = next(i for i, b in enumerate(blocks)
                      if b.startswith("<Target_User>"))
            ri = next(i for i, b in enumerate(blocks)
                      if b.startswith("<user_relations>"))
            assert ri == ti + 1
            block = blocks[ri]
            # D-14: карточка ЦЕЛЕВОГО собеседника — spec-формат строки
            assert ("<user_relations>Вася: ветеран, в чате с 2024-11, "
                    "214 сообщ. за 30 дней</user_relations>" == block)
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_flag_off_no_block(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": False})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(_relation()))
        try:
            blocks = await _build(_service(cache=cache))
            assert not any(b.startswith("<user_relations>") for b in blocks)
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_per_chat_disabled_no_block(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache(
            {CHAT_ID: make_profile(relations_enabled=False)})
        _with_runtime(FakeRelations(_relation()))
        try:
            blocks = await _build(_service(cache=cache))
            assert not any(b.startswith("<user_relations>") for b in blocks)
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_no_profile_no_block(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache({})                  # PG-профиля нет
        _with_runtime(FakeRelations(_relation()))
        try:
            blocks = await _build(_service(cache=cache))
            assert not any(b.startswith("<user_relations>") for b in blocks)
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_relations_service_missing_fail_open(self, monkeypatch):
        """RelationsService не установлен (lore_runtime пуст) → блока нет,
        0 влияния на поведение (сообщение ещё разбирается)."""
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _cleanup_runtime()
        blocks = await _build(_service(cache=cache))
        assert not any(b.startswith("<user_relations>") for b in blocks)
        assert any(b.startswith("<Target_User>") for b in blocks)

    @pytest.mark.asyncio
    async def test_relation_error_fail_open(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(_relation(), error=RuntimeError("pg down")))
        try:
            blocks = await _build(_service(cache=cache))
            assert not any(b.startswith("<user_relations>") for b in blocks)
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_relation_missing_no_block(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(None))        # юзера нет в users_meta
        try:
            blocks = await _build(_service(cache=cache))
            assert not any(b.startswith("<user_relations>") for b in blocks)
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_private_chat_no_block(self, monkeypatch):
        """D-12: инжект тона — только группы (chat_id < 0)."""
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache(
            {12345: make_profile(relations_enabled=True, chat_id=12345)})
        _with_runtime(FakeRelations(_relation()))
        try:
            blocks = await _build(_service(cache=cache), chat_id=12345)
            assert not any(b.startswith("<user_relations>") for b in blocks)
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_manual_stage_and_note_in_line(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(_relation(
            stage="veteran", stage_manual="veteran", note="самый свой")))
        try:
            blocks = await _build(_service(cache=cache))
            block = next(b for b in blocks if b.startswith("<user_relations>"))
            assert "Вася: ветеран (ручная пометка админа)" in block
            assert "| пометка: самый свой" in block
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_xml_escaping_of_note(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.relations_tone_enabled": True})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(_relation(note="с <тегом> & амперсандом")))
        try:
            blocks = await _build(_service(cache=cache))
            block = next(b for b in blocks if b.startswith("<user_relations>"))
            assert "| пометка: с &lt;тегом&gt; &amp; амперсандом" in block
            assert "<тегом>" not in block
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_cap_truncates_with_marker(self, monkeypatch):
        _hot_cache(monkeypatch, {
            "flags.relations_tone_enabled": True,
            "limits.relations_inject_max_chars": 100})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(_relation(
            note="очень длинная заметка админа " * 20)))
        try:
            blocks = await _build(_service(cache=cache))
            block = next(b for b in blocks if b.startswith("<user_relations>"))
            assert len(block) <= 100
            assert block.endswith("</user_relations>")
            assert "…[обрезано]" in block
        finally:
            _cleanup_runtime()

    @pytest.mark.asyncio
    async def test_relations_not_touched_by_context_budget(self, monkeypatch):
        """kind relations в uncuttable: даже при жёстком контекст-бюджете
        блок <user_relations> остаётся целым (кап — только свой, 600)."""
        _hot_cache(monkeypatch, {
            "flags.relations_tone_enabled": True,
            "flags.chat_context_budgets_enabled": True,
            "limits.chat_context_budget_tokens": 150})
        cache = FakeLoreCache({CHAT_ID: make_profile(relations_enabled=True)})
        _with_runtime(FakeRelations(_relation(note="заметка админа")))
        try:
            blocks = await _build(_service(cache=cache))
            block = next(b for b in blocks if b.startswith("<user_relations>"))
            assert ("<user_relations>Вася: ветеран, в чате с 2024-11, "
                    "214 сообщ. за 30 дней | пометка: заметка админа"
                    "</user_relations>" == block)
        finally:
            _cleanup_runtime()
