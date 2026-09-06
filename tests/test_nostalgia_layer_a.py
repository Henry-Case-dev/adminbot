"""Раунд 9 (AGI Memory, spec §3.5.1, T-826/E1, G3) — слой A ностальгии:
маркер «золотых» в direct-пути (0 добавочных LLM-вызовов).

Полный путь: реальный SQLite (v8) + MemoryManager (FTS; vec не
инициализируется → FTS-путь) + DirectChatService._build_user_content.
Проверки: маркер `nostalgia_hint: вспомни и вплети, если уместно:
[ГГГГ-ММ-ДД] текст` добавляется только для «золотых» (важность ≥ порога И
давность ≥ порога по COALESCE(message_timestamp, created_at), тема-матч);
факт уже в RAG-kept → маркера нет (нет нового сигнала); флаг
memory.nostalgia_layer_a_enabled off → маркера нет; личка (chat_id > 0) →
нет; максимум 1 маркер на ответ; фикс-кап nostalgia_hint_max_chars;
позиция в user-контенте — после <Target_User>, до <Current_Question>;
RAG-путь/контекст не ломаются.
"""
import asyncio
import re
import time
from unittest.mock import MagicMock

import pytest

from services import hot_config as hot
from services import lore_runtime
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver
from services.summary_memory import MemoryManager

CHAT_ID = -1002661910336
PRIVATE_CHAT = 100500
BOT_ID = 12345
NOW = int(time.time())

HINT_RE = re.compile(
    r"nostalgia_hint: вспомни и вплети, если уместно: "
    r"\[\d{4}-\d{2}-\d{2}\] ")


@pytest.fixture
def db():
    """In-memory SQLite (миграции v1..v8)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


@pytest.fixture(autouse=True)
def _cleanup_runtime():
    yield
    lore_runtime.reset_lore_runtime()


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


def _message(text):
    m = MagicMock()
    m.text = text
    m.message_id = 777
    return m


def _service(db):
    memory = MemoryManager(db, MagicMock(), aliases=AliasResolver("{}"))
    return DirectChatService(
        memory, db, MagicMock(), memory.aliases,
        bot_id=BOT_ID, bot_username="test_bot",
        breaker=None, cache=None, chat_lore_cache=None)


async def _add_fact(db, text, *, days_ago, importance):
    """Факт чата с датой события (message_timestamp) и важностью v8."""
    return await db.insert_graph_fact(
        CHAT_ID, text, "chat_history", None,
        importance=importance,
        message_timestamp=NOW - int(days_ago) * 86400)


async def _fill_rag_topic(db, n=10):
    """n свежих фактов по теме «василий переезд» — занимают RAG-kept
    (свежие + weight 1.0 → гарантированно выше «золотого» в сортировке
    w_eff; лимит RAG-фактов default 10), чтобы «золотой» факт НЕ оказался
    в kept (spec: золотой уже в kept → маркера нет)."""
    for i in range(n):
        await db.insert_graph_fact(
            CHAT_ID, f"василий переезд обсуждение номер {i}",
            "chat_history", None, weight=1.0, importance=1)


async def _build_content(db, service, chat_id=CHAT_ID, text=None):
    """Полный user-контент ответа (реальный путь RAG → маркер)."""
    blocks = await service._build_user_content(
        chat_id, _message(text or "василий переезд"), "Вася",
        target_user_id=10)
    return [b for b in blocks if b]


def _hints(content: list) -> list:
    return [line for block in content for line in block.splitlines()
            if line.startswith("nostalgia_hint:")]


class TestLayerA:
    @pytest.mark.asyncio
    async def test_golden_marker_appears_for_old_important_fact(
            self, db, monkeypatch):
        """«Золотой» (давность ≥60д, importance ≥5, тема-матч) вне RAG-kept
        → маркер в user-контенте; RAG-блок на месте."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": True})
        await _fill_rag_topic(db)
        golden_id = await _add_fact(
            db, "василий переезд в москву занял целый месяц",
            days_ago=400, importance=8)
        service = _service(db)
        content = await _build_content(db, service)
        joined = "\n".join(content)
        hints = _hints(content)
        assert len(hints) == 1
        assert HINT_RE.match(hints[0])
        assert "переезд" in hints[0]
        assert "<RAG_Memory>" in joined
        # позиция: после Target_User, до Current_Question
        assert joined.index("<Target_User>") < joined.index("nostalgia_hint:")
        assert joined.index("nostalgia_hint:") < \
            joined.index("<Current_Question>")
        row = await db.db.execute(
            "SELECT id FROM graph_facts WHERE id = ?", (golden_id,))
        assert await row.fetchone() is not None

    @pytest.mark.asyncio
    async def test_fresh_fact_no_marker(self, db, monkeypatch):
        """Свежий факт (давность < 60д) — не «золотой» → маркера нет."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": True})
        await _fill_rag_topic(db)
        await _add_fact(db, "василий переезд в москву занял месяц",
                        days_ago=30, importance=8)
        content = await _build_content(db, _service(db))
        assert _hints(content) == []

    @pytest.mark.asyncio
    async def test_low_importance_fact_no_marker(self, db, monkeypatch):
        """Важность < порога (5) → не «золотой» → маркера нет."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": True})
        await _fill_rag_topic(db)
        await _add_fact(db, "василий переезд упоминался вскользь",
                        days_ago=400, importance=2)
        content = await _build_content(db, _service(db))
        assert _hints(content) == []

    @pytest.mark.asyncio
    async def test_flag_off_no_marker(self, db, monkeypatch):
        """Флаг memory.nostalgia_layer_a_enabled off → 0 влияния."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": False})
        await _fill_rag_topic(db)
        await _add_fact(db, "василий переезд в москву занял месяц",
                        days_ago=400, importance=8)
        content = await _build_content(db, _service(db))
        assert _hints(content) == []
        assert any("<RAG_Memory>" in b for b in content)   # RAG жив

    @pytest.mark.asyncio
    async def test_no_flag_key_marker_absent_by_default(self, db,
                                                        monkeypatch):
        """hot без ключа → settings-дефолт (False) → маркера нет."""
        _hot_cache(monkeypatch, {})
        await _fill_rag_topic(db)
        await _add_fact(db, "василий переезд в москву занял месяц",
                        days_ago=400, importance=8)
        content = await _build_content(db, _service(db))
        assert _hints(content) == []

    @pytest.mark.asyncio
    async def test_private_chat_no_marker(self, db, monkeypatch):
        """Личка (chat_id > 0) — слой A не работает (D-12)."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": True})
        await db.insert_graph_fact(
            PRIVATE_CHAT, "василий переезд в москву занял месяц",
            "chat_history", None, importance=8,
            message_timestamp=NOW - 400 * 86400)
        service = _service(db)
        content = await _build_content(db, service, chat_id=PRIVATE_CHAT)
        assert _hints(content) == []

    @pytest.mark.asyncio
    async def test_fact_already_in_rag_kept_no_marker(self, db,
                                                      monkeypatch):
        """Золотой факт уже попал в RAG-kept → маркера нет (нет нового
        сигнала, spec §3.5.1)."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": True})
        await _add_fact(db, "василий переезд в москву занял месяц",
                        days_ago=400, importance=8)
        content = await _build_content(db, _service(db))
        assert _hints(content) == []
        assert any("<RAG_Memory>" in b for b in content)

    @pytest.mark.asyncio
    async def test_at_most_one_marker(self, db, monkeypatch):
        """Два «золотых» по теме — максимум 1 маркер (layer_a_max_hints=1)."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": True})
        await _fill_rag_topic(db)
        await _add_fact(db, "василий переезд в москву занял месяц",
                        days_ago=400, importance=8)
        await _add_fact(db, "василий переезд решился весной",
                        days_ago=300, importance=7)
        content = await _build_content(db, _service(db))
        assert len(_hints(content)) == 1

    @pytest.mark.asyncio
    async def test_marker_capped_at_hint_max_chars(self, db, monkeypatch):
        """Фикс-кап memory.nostalgia_hint_max_chars ДО инжекта."""
        _hot_cache(monkeypatch, {
            "memory.nostalgia_layer_a_enabled": True,
            "memory.nostalgia_hint_max_chars": 80})
        await _fill_rag_topic(db)
        await _add_fact(
            db, "василий переезд в москву занял " + "очень " * 300,
            days_ago=400, importance=8)
        content = await _build_content(db, _service(db))
        hints = _hints(content)
        assert len(hints) == 1
        assert len(hints[0]) <= 80
        assert hints[0].startswith("nostalgia_hint:")

    @pytest.mark.asyncio
    async def test_rag_error_fail_open_no_crash(self, db, monkeypatch):
        """Любая ошибка «золотого» поиска → маркера нет, диалог жив."""
        _hot_cache(monkeypatch, {"memory.nostalgia_layer_a_enabled": True})
        await _fill_rag_topic(db)
        await _add_fact(db, "василий переезд в москву занял месяц",
                        days_ago=400, importance=8)
        service = _service(db)

        async def _broken_golden(*a, **kw):
            raise RuntimeError("golden boom")

        service.memory.fetch_golden_facts = _broken_golden
        content = await _build_content(db, service)
        assert _hints(content) == []
        assert any("<RAG_Memory>" in b for b in content)
