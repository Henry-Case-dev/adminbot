"""Раунд 7 (chat-lore-management-v2, T-784, H2.3) — инжект PG-лора в
direct_chat (spec §3.9/Q1 + F1).

Проверки: при активном PG-лоре контекст содержит `<chat_lore>` СРАЗУ после
`<protected_facts>` (manual + `---` + auto); cap 3000 (auto режется первым,
маркер «…[обрезано]», manual цел); auto_enabled=false НЕ влияет на инжект
(текст остаётся); при активном PG-лоре protected собирается с
include_chat_level=False (SQLite chat-level канал исключён — дедуп), без
PG-лора — ровно старое поведение (include_chat_level=True, блока нет);
профиль есть/лоры пусты → блока нет; флаг flags.lore_inject_enabled=false →
старое поведение; PG-ошибка/cache-None → fail-open пусто; XML-экранирование;
persona-карточка: PG-лор первой «строкой», счётчик +1, legacy-канал исключён.
"""
from unittest.mock import MagicMock

import pytest

from services import hot_config as hot
from services.direct_chat_service import DirectChatService
from services.lore_cache import LoreProfile
from services.summary_aliases import AliasResolver

CHAT_ID = -1002661910336

_LONG_AUTO = "абзац авто-лора: " + "очень длинный контент про историю чата, " * 200


def make_profile(manual: str = "ручной лор: конфа с нулевых",
                 auto: str = "авто лор: все живы", *,
                 auto_enabled: bool = True, is_active: bool = True,
                 chat_id: int = CHAT_ID) -> LoreProfile:
    return LoreProfile(
        chat_id=chat_id, manual_lore=manual, auto_lore=auto,
        auto_enabled=auto_enabled, auto_period_hours=24,
        auto_window_hours=24, is_active=is_active,
        last_auto_at=None, updated_at="2026-09-06T10:00:00+00:00")


class FakeMemory:
    async def get_window_messages(self, chat_id):
        return []

    async def get_rag_context(self, chat_id, query, *,
                              sort_by_timestamp=False, include_direct_reply=False):
        return ""


class FakeLoreCache:
    """ChatLoreCache-заглушка: профили по chat_id; сбой — настраиваемо."""

    def __init__(self, profiles=None, error=None):
        self.profiles = dict(profiles or {})
        self.error = error
        self.calls = []

    async def get(self, chat_id):
        self.calls.append(chat_id)
        if self.error is not None:
            raise self.error
        return self.profiles.get(chat_id)


class FakeDB:
    """DatabaseService-заглушка: protected-факты + запись include_chat_level."""

    def __init__(self, user_facts=(), chat_facts=()):
        self.user_facts = list(user_facts)
        self.chat_facts = list(chat_facts)      # chat-level (user_name NULL)
        self.protected_calls = []               # (include_chat_level, ...)

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        self.protected_calls.append(
            (chat_id, user_name, bool(include_chat_level)))
        facts = list(self.user_facts)
        if include_chat_level:
            facts = self.chat_facts + facts
        return facts

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


async def _build(service):
    """user-контент: список блоков в порядке сборки."""
    return [b for b in await service._build_user_content(
        CHAT_ID, _message(), "Вася") if b]


class TestInjectDirectChat:
    @pytest.mark.asyncio
    async def test_lore_block_after_protected(self):
        db = FakeDB(chat_facts=["легаси-константа чата раунда 5"],
                    user_facts=["факт про Васю"])
        cache = FakeLoreCache({CHAT_ID: make_profile()})
        blocks = await _build(_service(db, cache))
        kinds = [b.split("\n", 1)[0] for b in blocks]
        pi = kinds.index("<protected_facts>")
        li = kinds.index("<chat_lore>")
        assert li == pi + 1                       # сразу после protected (Q1)
        assert "важные факты" in blocks[pi]
        block = blocks[li]
        assert "ручной лор: конфа с нулевых" in block
        assert "\n---\n" in block
        assert "авто лор: все живы" in block
        assert block.startswith("<chat_lore>\n")
        assert block.endswith("\n</chat_lore>")

    @pytest.mark.asyncio
    async def test_lore_block_omitted_when_no_text(self):
        cache = FakeLoreCache({CHAT_ID: make_profile(manual="", auto="")})
        blocks = await _build(_service(FakeDB(), cache))
        assert not any(b.startswith("<chat_lore>") for b in blocks)

    @pytest.mark.asyncio
    async def test_no_profile_legacy_behavior(self):
        db = FakeDB(chat_facts=["легаси-факт"])
        cache = FakeLoreCache({})                  # профиля нет
        blocks = await _build(_service(db, cache))
        assert not any(b.startswith("<chat_lore>") for b in blocks)
        assert db.protected_calls[-1][2] is True   # include_chat_level=True
        assert any("легаси-факт" in b for b in blocks)

    @pytest.mark.asyncio
    async def test_pg_lore_dedup_include_chat_level_false(self):
        db = FakeDB(chat_facts=["легаси-константа"],
                    user_facts=["факт про Васю"])
        cache = FakeLoreCache({CHAT_ID: make_profile()})
        blocks = await _build(_service(db, cache))
        _, name, include_chat_level = db.protected_calls[-1]
        assert include_chat_level is False         # SQLite chat-level исключён
        protected = next(b for b in blocks
                         if b.startswith("<protected_facts>"))
        assert "легаси-константа" not in protected  # нет дубля (Q1)
        assert "факт про Васю" in protected
        assert any(b.startswith("<chat_lore>") for b in blocks)

    @pytest.mark.asyncio
    async def test_flag_off_legacy_behavior(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.lore_inject_enabled": False})
        db = FakeDB(chat_facts=["легаси-факт"])
        cache = FakeLoreCache({CHAT_ID: make_profile()})
        blocks = await _build(_service(db, cache))
        assert not any(b.startswith("<chat_lore>") for b in blocks)
        assert db.protected_calls[-1][2] is True   # старое поведение целиком

    @pytest.mark.asyncio
    async def test_cache_none_disables_feature(self):
        db = FakeDB(chat_facts=["легаси-факт"])
        blocks = await _build(_service(db, cache=None))
        assert not any(b.startswith("<chat_lore>") for b in blocks)
        assert db.protected_calls[-1][2] is True

    @pytest.mark.asyncio
    async def test_pg_error_fail_open(self):
        db = FakeDB(chat_facts=["легаси-факт"])
        cache = FakeLoreCache({CHAT_ID: make_profile()},
                              error=RuntimeError("pg down"))
        blocks = await _build(_service(db, cache))
        assert not any(b.startswith("<chat_lore>") for b in blocks)
        assert any("легаси-факт" in b for b in blocks)   # SQLite-fallback жив

    @pytest.mark.asyncio
    async def test_inactive_profile_no_block(self):
        cache = FakeLoreCache(
            {CHAT_ID: make_profile(is_active=False)})
        blocks = await _build(_service(FakeDB(), cache))
        assert not any(b.startswith("<chat_lore>") for b in blocks)

    @pytest.mark.asyncio
    async def test_auto_disabled_does_not_block_inject(self):
        cache = FakeLoreCache(
            {CHAT_ID: make_profile(auto_enabled=False)})
        blocks = await _build(_service(FakeDB(), cache))
        # тумблер авто-генерации НЕ влияет на инжект (D-инвариант №1)
        assert any(b.startswith("<chat_lore>") for b in blocks)

    @pytest.mark.asyncio
    async def test_xml_escaping(self):
        manual = "текст с & амперсандом <и> скобками"
        cache = FakeLoreCache({CHAT_ID: make_profile(manual=manual, auto="")})
        blocks = await _build(_service(FakeDB(), cache))
        block = next(b for b in blocks if b.startswith("<chat_lore>"))
        assert "&amp;" in block
        assert "& амперсандом" not in block.replace("&amp;", "")

    @pytest.mark.asyncio
    async def test_cap_truncates_auto_keeps_manual(self, monkeypatch):
        cache = FakeLoreCache({CHAT_ID: make_profile(auto=_LONG_AUTO)})
        blocks = await _build(_service(FakeDB(), cache))
        block = next(b for b in blocks if b.startswith("<chat_lore>"))
        assert len(block) <= 3000                  # cap limits.lore_inject_
        # max_chars (3000)
        assert "ручной лор: конфа с нулевых" in block   # manual цел
        assert "обрезано" in block                 # маркер присутствует
        assert _LONG_AUTO not in block             # auto урезан

    @pytest.mark.asyncio
    async def test_cap_applies_to_total_block(self, monkeypatch):
        _hot_cache(monkeypatch, {"limits.lore_inject_max_chars": 500})
        cache = FakeLoreCache({
            CHAT_ID: make_profile(
                manual="м " * 400, auto="a " * 400)})
        blocks = await _build(_service(FakeDB(), cache))
        block = next(b for b in blocks if b.startswith("<chat_lore>"))
        assert len(block) <= 500
        assert "обрезано" in block


class TestPersonaLore:
    @pytest.mark.asyncio
    async def test_persona_with_pg_lore_first_line(self):
        db = FakeDB(chat_facts=["легаси-факт"],
                    user_facts=["факт: любит чай"])
        cache = FakeLoreCache({CHAT_ID: make_profile(
            manual="лор чата", auto="")})
        service = _service(db, cache)
        card = await service.build_persona_card(CHAT_ID, "Вася")
        assert card is not None
        lines = card.split("\n")
        assert lines[0] == "карточка: Вася"
        assert lines[1].startswith("знаю о тебе: ")
        # лор — первой «строкой» (+1 к счётчику), legacy chat-level исключён
        assert "лор чата" in lines[2]
        assert "факт: любит чай" in card
        assert "легаси-факт" not in card
        assert "2 фактов" in lines[1]          # факт юзера + лор (+1)
        _, _, include_chat_level = db.protected_calls[-1]
        assert include_chat_level is False

    @pytest.mark.asyncio
    async def test_persona_without_pg_lore_legacy(self):
        db = FakeDB(chat_facts=["легаси-факт"],
                    user_facts=["факт: любит чай"])
        cache = FakeLoreCache({})                  # PG-профиля нет
        service = _service(db, cache)
        card = await service.build_persona_card(CHAT_ID, "Вася")
        assert "легаси-факт" in card
        assert "лор чата" not in card
        assert db.protected_calls[-1][2] is True   # как в раунде 5

    @pytest.mark.asyncio
    async def test_persona_flag_off_legacy(self, monkeypatch):
        _hot_cache(monkeypatch, {"flags.lore_inject_enabled": False})
        db = FakeDB(chat_facts=["легаси-факт"])
        cache = FakeLoreCache({CHAT_ID: make_profile(manual="лор")})
        service = _service(db, cache)
        card = await service.build_persona_card(CHAT_ID, "Вася")
        assert "легаси-факт" in card
        assert "лор чата" not in card
