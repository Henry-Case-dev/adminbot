"""ASAP 8 v6 P1 — D09 остаток: broad memory freshness (§18F.3/M10) +
GraphRAG run outcomes (§18F.5/M12) на реальном in-memory SQLite.

M10 (18F.3): идентичность «широкого фона» (L2) — по диапазону источника
(window_end_ts + raw_count prev-L1), НЕ по размеру окна: новое равное по
размеру окно с новым контентом обновляет L2; точный повтор диапазона не
создаёт работу; устаревший диапазон не перезаписывает свежий.

M12 (18F.5): исход прогона фактов — из ФАКТИЧЕСКОЙ персистенции:
persisted / all_duplicates / text_only_vector_deferred / partial /
write_failed / no_new_facts различимы; неудачная запись получает bounded
retry; дубликаты не считаются потерей.

TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D09
"""
import asyncio
import json

import pytest

from services.database import DatabaseService
from services.summary_memory import MemoryManager

CHAT_ID = -100


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _CompressLLM:
    def __init__(self):
        self.calls = 0

    async def generate(self, messages):
        self.calls += 1
        return f"конспект версии {self.calls}"


class _FactsLLM:
    def __init__(self, response):
        self.response = response

    async def generate(self, messages):
        return self.response


def _l2_row(db):
    async def _read():
        cursor = await db.db.execute(
            "SELECT summary, msg_count_highwater FROM chat_summary_levels "
            "WHERE chat_id = ? AND level = 2", (CHAT_ID,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    return _read


class TestBroadContextFreshness:
    @pytest.mark.asyncio
    async def test_equal_window_new_content_rebuilds(self, db):
        """M10: новое окно ТОГО ЖЕ размера (500 сообщений), но с новым
        контентом (window_end_ts дальше) — широкий фон ОБНОВЛЯЕТСЯ
        (старый код пропускал: 500 >= 500)."""
        llm = _CompressLLM()
        memory = MemoryManager(db, llm)
        build = memory._build_level2
        await build(CHAT_ID, {"raw_count": 500, "window_end_ts": 1000,
                              "summary": "исходник v1"})
        row = await _l2_row(db)()
        assert row is not None and row["msg_count_highwater"] == 500
        first_summary = row["summary"]
        assert llm.calls == 1
        # то же число сообщений, НОВЫЙ диапазон → rebuild
        await build(CHAT_ID, {"raw_count": 500, "window_end_ts": 2000,
                              "summary": "исходник v2"})
        row2 = await _l2_row(db)()
        assert llm.calls == 2
        assert row2["summary"] != first_summary

    @pytest.mark.asyncio
    async def test_exact_repeat_no_extra_work(self, db):
        """M10: точный повтор диапазона — LLM-вызова нет (no extra work)."""
        llm = _CompressLLM()
        memory = MemoryManager(db, llm)
        build = memory._build_level2
        await build(CHAT_ID, {"raw_count": 500, "window_end_ts": 2000,
                              "summary": "исходник"})
        assert llm.calls == 1
        await build(CHAT_ID, {"raw_count": 500, "window_end_ts": 2000,
                              "summary": "исходник"})
        assert llm.calls == 1           # повтор не создаёт работу
        row = await _l2_row(db)()
        assert row is not None

    @pytest.mark.asyncio
    async def test_stale_range_does_not_overwrite(self, db):
        """M10: устаревший (меньший) диапазон не перезаписывает свежий
        широкий фон."""
        llm = _CompressLLM()
        memory = MemoryManager(db, llm)
        build = memory._build_level2
        await build(CHAT_ID, {"raw_count": 500, "window_end_ts": 5000,
                              "summary": "свежий исходник"})
        assert llm.calls == 1
        fresh = (await _l2_row(db)())["summary"]
        await build(CHAT_ID, {"raw_count": 400, "window_end_ts": 1000,
                              "summary": "старый исходник"})
        assert llm.calls == 1           # свежий не перезаписан
        assert (await _l2_row(db)())["summary"] == fresh

    @pytest.mark.asyncio
    async def test_legacy_count_guard_when_no_version(self, db):
        """Легаси-совместимость: нет durable-версии → прежний count-гард."""
        llm = _CompressLLM()
        memory = MemoryManager(db, llm)
        build = memory._build_level2
        await build(CHAT_ID, {"raw_count": 500, "window_end_ts": 2000,
                              "summary": "исходник"})
        assert llm.calls == 1
        # стереть версию источника → легаси-гард по msg_count_highwater
        await db.db.execute(
            "DELETE FROM task_jobs WHERE job_id LIKE "
            "'summary_l2_source_version:%'")
        await db.db.commit()
        await build(CHAT_ID, {"raw_count": 500, "window_end_ts": 3000,
                              "summary": "исходник v2"})
        assert llm.calls == 1           # легаси-гард: 500 >= 500
        await build(CHAT_ID, {"raw_count": 600, "window_end_ts": 3000,
                              "summary": "исходник v3"})
        assert llm.calls == 2           # большее окно перестраивает


_FACTS_TWO = json.dumps([
    {"subject": "вася", "predicate": "любит", "object": "кофе"},
    {"subject": "петя", "predicate": "любит", "object": "чай"},
], ensure_ascii=False)


class TestGraphRagOutcomes:
    def _events(self, name="FACTS_EXTRACT"):
        from services import mca_events as me
        return [dict(e) for e in me._pending
                if e.get("event_name") == name]

    def _usage(self, ev: dict) -> dict:
        raw = ev.get("usage_json")
        return json.loads(raw) if raw else {}

    @pytest.mark.asyncio
    async def test_all_duplicates_neutral_success(self, db, caplog):
        """M12: повтор тех же фактов — all_duplicates, нейтральный исход
        (не потеря, не ошибка)."""
        memory = MemoryManager(db, _FactsLLM(_FACTS_TWO))
        memory._vec_available = False
        await memory.memorize_facts(CHAT_ID, "вася любит кофе, петя чай",
                                    "chat_history")
        await memory.memorize_facts(CHAT_ID, "вася любит кофе, петя чай",
                                    "chat_history")
        evs = self._events()
        assert [e["outcome"] for e in evs] == ["success", "success"]
        assert self._usage(evs[1]).get("outcome") == "all_duplicates"
        assert self._usage(evs[1]).get("deduped") == 2

    @pytest.mark.asyncio
    async def test_write_failed_honest_terminal(self, db, monkeypatch):
        """M12: все записи упали → write_failed (честный failed), а НЕ
        success с нулём сохранённых фактов."""

        async def _boom(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(db, "insert_graph_fact", _boom)
        memory = MemoryManager(db, _FactsLLM(_FACTS_TWO))
        memory._vec_available = False
        await memory.memorize_facts(CHAT_ID, "текст с фактами",
                                    "chat_history")
        evs = self._events()
        assert evs, "терминальный FACTS_EXTRACT отсутствует"
        ev = evs[-1]
        assert ev["outcome"] == "failed"
        assert ev.get("reason_code") == "writer_failed"
        assert ev.get("level") == "WARN"
        assert self._usage(ev).get("outcome") == "write_failed"

    @pytest.mark.asyncio
    async def test_bounded_write_retry_no_loss(self, db, monkeypatch):
        """M12: одиночный сбой записи → 1 retry, факт НЕ теряется
        (saved=2, skipped=0, исход success)."""
        calls = {"n": 0}
        real = db.insert_graph_fact

        async def _flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return await real(*a, **kw)

        monkeypatch.setattr(db, "insert_graph_fact", _flaky)
        memory = MemoryManager(db, _FactsLLM(_FACTS_TWO))
        memory._vec_available = False
        await memory.memorize_facts(CHAT_ID, "текст с фактами",
                                    "chat_history")
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE chat_id = ?",
            (CHAT_ID,))
        assert (await cursor.fetchone())["c"] == 2
        evs = self._events()
        assert evs[-1]["outcome"] == "success"
        assert self._usage(evs[-1]).get("skipped") == 0

    @pytest.mark.asyncio
    async def test_partial_persistence_distinguishable(self, db, monkeypatch):
        """M12: одна запись упала (с retry), другая успешна → partial
        (не success и не write_failed)."""
        real = db.insert_graph_fact

        async def _half(*a, **kw):
            if "вася" in str(a[1]):
                raise RuntimeError("db down")
            return await real(*a, **kw)

        monkeypatch.setattr(db, "insert_graph_fact", _half)
        memory = MemoryManager(db, _FactsLLM(_FACTS_TWO))
        memory._vec_available = False
        await memory.memorize_facts(CHAT_ID, "текст с фактами",
                                    "chat_history")
        evs = self._events()
        ev = evs[-1]
        assert ev["outcome"] == "success"       # частичная персистенция
        assert ev.get("reason_code") == "run_partial"
        assert ev.get("level") == "WARN"
        usage = self._usage(ev)
        assert usage.get("outcome") == "partial"
        assert usage.get("saved") == 1 and usage.get("skipped") == 1

    @pytest.mark.asyncio
    async def test_text_only_vector_deferred_distinguishable(self, db,
                                                             monkeypatch):
        """M12: факты персистированы текстом, векторы отложены — исход
        text_only_vector_deferred виден в терминале."""
        memory = MemoryManager(db, _FactsLLM(_FACTS_TWO))
        memory._vec_available = True

        async def _defer(*a, **kw):
            batch = kw.get("batch")
            if batch is not None:
                batch.text_only += 1

        monkeypatch.setattr(memory, "_save_graph_fact_embedding", _defer)
        await memory.memorize_facts(CHAT_ID, "текст с фактами",
                                    "chat_history")
        evs = self._events()
        ev = evs[-1]
        assert ev["outcome"] == "success"
        assert ev.get("reason_code") == "embed_deferred"
        assert self._usage(ev).get(
            "outcome") == "text_only_vector_deferred"
