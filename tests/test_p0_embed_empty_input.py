"""P0-EMBED-EMPTY (R247-DEP-N1): пустой текст не является embed-запросом.

Прод-сигнал 2.58.247: медиа-сообщение без текста (`message.text is None`) →
`_build_rag_block` → `retrieve(query="")` → векторный канал →
`_search_graph_facts("")` → `_embed([""])` → POST /embeddings с пустым
`input` → 400 у всех трёх ног → каждая нога в 60-секундном cooldown →
`EmbeddingNoUsableCredential` → последующие факты пишутся text-only.

Контракт (наблюдаемый):
  * пустой/пробельный текст НЕ уходит провайдеру ни на одной ноге;
  * элемент деградирует детерминированно: запрос — лексический путь,
    факт — text-only (существующая семантика), без парковки credential'ов;
  * непустой текст обслуживается ровно как раньше (один вызов, те же векторы).

R17: только синтетические тексты, никаких реальных переписок.
"""
import asyncio

import pytest

from services import hot_config as hot
from services import mca_retrieval_context as mrc
from services.database import DatabaseService
from services.summary_memory import MemoryManager, _EmbedBatchState

CHAT = -100
DIM = 8


class RecordingLLM:
    """Считает фактические embed-вызовы (что именно ушло бы провайдеру)."""

    def __init__(self, dim: int = DIM):
        self.dim = dim
        self.embed_calls: list[list[str]] = []

    async def embed(self, texts):
        self.embed_calls.append(list(texts))
        return [[0.1] * self.dim for _ in texts]

    async def generate(self, messages):  # pragma: no cover
        raise AssertionError("generate в этих тестах не нужен")


class _FakeHotCache:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _hot(monkeypatch, values: dict | None = None):
    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


async def _memory(db, monkeypatch, llm):
    """MemoryManager на реальной SQLite; vec-гейты открыты точечно, чтобы
    тест проверял именно embed-границу, а не admission индекса."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        pytest.skip("sqlite-vec not installed")

    async def _probe_fixed(self):
        return False

    monkeypatch.setattr(MemoryManager, "_probe_vec_int8", _probe_fixed)
    memory = MemoryManager(db, llm)

    async def _noop_backfill() -> int:
        return 0

    memory.backfill_archive_vectors = _noop_backfill
    memory.backfill_graph_fact_vectors = _noop_backfill
    if not await memory.initialize():
        pytest.skip("sqlite-vec extension could not be loaded")

    async def _vec_retry_ok(self):
        return True

    async def _generation_ok(self, index_name):
        return True

    async def _write_allowed(self, index_name):
        return True

    async def _serving_allowed(self, index_name):
        return True

    monkeypatch.setattr(MemoryManager, "_ensure_vec_retry", _vec_retry_ok)
    monkeypatch.setattr(MemoryManager, "_index_generation_ok", _generation_ok)
    monkeypatch.setattr(MemoryManager, "_vec_write_allowed", _write_allowed)
    monkeypatch.setattr(MemoryManager, "_serving_route_write_allowed",
                        _serving_allowed)
    # `initialize()` сам делает dim-пробу («probe»); записываем только вызовы
    # проверяемого действия.
    llm.embed_calls.clear()
    return memory


def _assert_no_blank_reached_provider(llm):
    sent = [t for call in llm.embed_calls for t in call]
    blanks = [t for t in sent if not str(t or "").strip()]
    assert blanks == [], f"пустой текст ушёл провайдеру: {llm.embed_calls!r}"


class TestEmptyQueryDoesNotReachProvider:
    @pytest.mark.asyncio
    async def test_empty_query_search_graph_facts(self, db, monkeypatch):
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)

        rows = await memory._search_graph_facts(CHAT, "", 5)

        assert rows == []
        _assert_no_blank_reached_provider(llm)
        assert llm.embed_calls == [], "пустой запрос не требует embed-вызова"

    @pytest.mark.asyncio
    async def test_whitespace_query_search_graph_facts(self, db, monkeypatch):
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)

        rows = await memory._search_graph_facts(CHAT, "   \n\t ", 5)

        assert rows == []
        assert llm.embed_calls == []

    @pytest.mark.asyncio
    async def test_empty_query_through_unified_retrieve(self, db, monkeypatch):
        """Прод-цепочка: `_build_rag_block` (text=None) → `retrieve("")`."""
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)

        result = await mrc.retrieve(db, memory, mrc.RetrievalRequest(
            chat_id=CHAT, query="", purpose="reply", mode="auto",
            channels=("vector",), include_self=True,
            include_direct_reply=True))

        assert result is not None
        assert llm.embed_calls == []

    @pytest.mark.asyncio
    async def test_empty_query_period_fill(self, db, monkeypatch):
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)
        stats: dict = {}

        rows = await memory.period_fill_candidates(CHAT, "", k=8, stats=stats)

        assert rows == []
        assert llm.embed_calls == []


class TestBlankFactIsTextOnly:
    @pytest.mark.asyncio
    async def test_blank_fact_vec_write_is_text_only(self, db, monkeypatch):
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)
        batch = _EmbedBatchState()

        written = await memory._save_graph_fact_embedding(
            1, CHAT, "   ", "chat_history", None, batch=batch)

        assert written is False
        assert batch.text_only == 1
        assert llm.embed_calls == []

    @pytest.mark.asyncio
    async def test_blank_archive_fact_embedding_is_skipped(self, db,
                                                           monkeypatch):
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)

        await memory._save_archive_embedding(CHAT, 1, " \t ")

        assert llm.embed_calls == []


class TestNonEmptyUnchanged:
    @pytest.mark.asyncio
    async def test_non_empty_query_still_embedded_once(self, db, monkeypatch):
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)

        await memory._search_graph_facts(CHAT, "кофе", 5)

        assert llm.embed_calls == [["кофе"]], "непустой запрос — ровно один вызов"

    @pytest.mark.asyncio
    async def test_non_empty_fact_vec_write_embeds(self, db, monkeypatch):
        _hot(monkeypatch)
        llm = RecordingLLM()
        memory = await _memory(db, monkeypatch, llm)
        batch = _EmbedBatchState()

        written = await memory._save_graph_fact_embedding(
            1, CHAT, "вася любит кофе", "chat_history", None, batch=batch)

        assert written is True
        assert batch.text_only == 0
        assert llm.embed_calls == [["вася любит кофе"]]
