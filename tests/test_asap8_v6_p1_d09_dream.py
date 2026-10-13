"""ASAP 8 v6 P1 — D09 остаток: Dream groups (§18F.1/M8) + Deep Sleep stage
truth (§18F.6/M13) на реальном in-memory SQLite.

M8 (18F.1): eligible-групп сверх dream_max_clusters_per_run НЕ помечаются
завершёнными — watermark останавливается перед их фактами, группа попадает
в durable-очередь (memory_dream_log status='cluster_deferred') и обрабатывается
следующим прогоном; каждая eligible группа дистиллируется РОВНО ОДИН РАЗ
несмотря на лимит и порядок ранжирования.

M13 (18F.6): стадии прогона Deep Sleep честные — model-call/validate/persist;
no-response и all-write-failed НЕ помечают стадию succeeded; «нет новых
выводов» — нейтральный исход.

TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D09
"""
import asyncio
import json

import pytest

from services import hot_config as hot
from services.database import DatabaseService
from services.dream_worker import DreamWorker

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


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeLLM:
    """Мок LLM: ответ = шаблон с индексом вызова (различает кластеры)."""

    def __init__(self):
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append(messages)
        n = len(self.calls)
        return json.dumps(
            {"beliefs": [{"text": f"убеждение номер {n}",
                          "evidence": [1, 2, 3]}]},
            ensure_ascii=False)


def _worker(db, llm, monkeypatch, values=None):
    _hot_cache(monkeypatch, dict(values or {}) | {"memory.dream_enabled": True})
    return DreamWorker(db, memory=None, llm=llm)


async def _add_batch(db, n, topic_words, importance=4):
    ids = []
    for i in range(n):
        ids.append(await db.insert_graph_fact(
            CHAT_ID,
            f"{topic_words[0]} {topic_words[1]} в {i + 1} раз "
            f"{topic_words[2]} подряд",
            "chat_history", None, importance=importance))
    return ids


async def _deferred_rows(db):
    cursor = await db.db.execute(
        "SELECT id, source_ids FROM memory_dream_log "
        "WHERE status = 'cluster_deferred' ORDER BY id")
    return await cursor.fetchall()


class TestDeferredGroups:
    @pytest.mark.asyncio
    async def test_three_runs_process_every_group_exactly_once(
            self, db, monkeypatch):
        """M8 acceptance: 3+ прогона обрабатывают ВСЕ eligible группы ровно
        по одному разу при лимите 2 группы/прогон; watermark не проходит
        мимо необработанных eligible групп; очередь не дублируется."""
        llm = _FakeLLM()
        worker = _worker(db, llm, monkeypatch, {
            "memory.dream_max_clusters_per_run": 2,
        })
        topics = (("вася", "платит", "бар"),
                  ("петя", "ходит", "четвергам"),
                  ("ольга", "вяжет", "свитер"),
                  ("костя", " бегает", "стадион"),
                  ("дима", "читает", "книги"),
                  ("сюю", "рисует", "акварель"),
                  ("марк", "готовит", " ужин"))
        all_ids = []
        for t in topics:
            all_ids.extend(await _add_batch(db, 3, t))

        # Прогон 1: 2 группы дистиллированы, остальные — в deferred-очереди;
        # watermark НЕ доходит до фактов необработанных групп.
        res1 = await worker.run_once(CHAT_ID)
        assert res1["distilled"] == 2
        assert res1["deferred"] == 5
        assert len(llm.calls) == 2
        state = await db.get_dream_state(CHAT_ID)
        deferred = await _deferred_rows(db)
        assert len(deferred) == 5
        deferred_min = min(
            min(int(i) for i in json.loads(r["source_ids"]))
            for r in deferred)
        assert state["last_processed_fact_id"] < deferred_min, (
            "watermark пометил необработанные eligible группы завершёнными")

        # Прогон 2: следующие 2 группы (приоритет очереди), уже обработанные
        # НЕ передистиллируются (exactly-once), очередь не дублируется.
        res2 = await worker.run_once(CHAT_ID)
        assert res2["distilled"] == 2
        assert res2["deferred"] == 0
        assert len(llm.calls) == 4
        assert len(await _deferred_rows(db)) == 5   # без дублей очереди
        state2 = await db.get_dream_state(CHAT_ID)
        deferred2 = await _deferred_rows(db)
        remaining_min = min(
            min(int(i) for i in json.loads(r["source_ids"]))
            for r in deferred2)
        assert state2["last_processed_fact_id"] < remaining_min

        # Прогон 3: ещё 2 группы из очереди (лимит 2/прогон); хвост уже
        # в очереди — НОВЫХ отложений нет (очередь не дублируется).
        res3 = await worker.run_once(CHAT_ID)
        assert res3["distilled"] == 2
        assert res3["deferred"] == 0
        assert len(llm.calls) == 6
        assert len(await _deferred_rows(db)) == 5

        # Прогон 4: хвост очереди; все 7 групп обработаны ровно по разу.
        res4 = await worker.run_once(CHAT_ID)
        assert res4["distilled"] == 1
        assert res4["deferred"] == 0
        assert len(llm.calls) == 7                  # ровно 7 LLM-вызовов
        state4 = await db.get_dream_state(CHAT_ID)
        assert state4["last_processed_fact_id"] == max(all_ids)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 7

        # Прогон 5: новых фактов нет — ни одной повторной дистилляции.
        res5 = await worker.run_once(CHAT_ID)
        assert res5["distilled"] == 0
        assert len(llm.calls) == 7

    @pytest.mark.asyncio
    async def test_budget_stop_then_resume_no_redistill(self, db, monkeypatch):
        """Бюджет-стоп между прогонами: обработанные группы не
        передистиллируются (exactly-once переживает stop/resume)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 5)
        llm = _FakeLLM()
        worker = _worker(db, llm, monkeypatch, {
            "memory.dream_distillations_per_day": 0,  # 0 = без лимита
            "memory.dream_tokens_per_day": 5000,      # near-limit после 1-го
        })
        await _add_batch(db, 3, ("вася", "платит", "бар"))
        await _add_batch(db, 3, ("петя", "ходит", "четвергам"))
        # Плановый прогон: 1 дистилляция → near-limit стоп (остаток < 5).
        res1 = await worker._run(manual=False, only_chat=CHAT_ID)
        assert res1["distilled"] == 1
        assert res1["budget_stop"] is True
        assert len(llm.calls) == 1
        assert await db.get_dream_state(CHAT_ID) is None  # wm не двигался
        # «Новый день»: вторая группа дистиллируется; первая — НЕТ.
        real_now = dw._now_ts()
        monkeypatch.setattr(dw, "_now_ts", lambda: real_now + 3 * 86400)
        res2 = await worker._run(manual=False, only_chat=CHAT_ID)
        assert res2["distilled"] == 1
        assert len(llm.calls) == 2
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 2

    @pytest.mark.asyncio
    async def test_llm_error_retry_does_not_double_distill(self, db,
                                                           monkeypatch):
        """Ошибка LLM на первом прогоне + успех на втором: упавший кластер
        дистиллируется ровно один раз (без дублей убеждений)."""
        class _FailOnceLLM:
            def __init__(self):
                self.calls = 0

            async def generate(self, messages, temperature=None):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("llm down")
                return json.dumps(
                    {"beliefs": [{"text": "единственное убеждение",
                                  "evidence": [1, 2, 3]}]},
                    ensure_ascii=False)

        llm = _FailOnceLLM()
        worker = _worker(db, llm, monkeypatch)
        ids = await _add_batch(db, 3, ("вася", "платит", "бар"))
        res1 = await worker.run_once(CHAT_ID)
        assert res1["errors"] == 1
        state = await db.get_dream_state(CHAT_ID)
        assert state["last_processed_fact_id"] == min(ids) - 1
        res2 = await worker.run_once(CHAT_ID)
        assert res2["distilled"] == 1
        assert llm.calls == 2
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 1
        state2 = await db.get_dream_state(CHAT_ID)
        assert state2["last_processed_fact_id"] == max(ids)


class TestSafeWatermarkUnit:
    def test_safe_watermark_blocks_before_unprocessed(self):
        from services.dream_worker import _safe_watermark
        rows_a = [{"id": 5}, {"id": 9}]
        rows_b = [{"id": 12}]
        assert _safe_watermark([rows_a, rows_b], fallback=30, floor=0) == 4
        assert _safe_watermark([], fallback=30, floor=0) == 30
        # назад не двигаем; лимит не превышает fallback
        assert _safe_watermark([rows_a], fallback=7, floor=6) == 6

    def test_cluster_key_stable_and_capped(self):
        from services.dream_prompts import order_dream_rows
        from services.dream_worker import _cluster_key, _cluster_source_ids
        rows = [{"id": 3, "created_at": 3}, {"id": 1, "created_at": 1},
                {"id": 2, "created_at": 2}]
        assert [r["id"] for r in order_dream_rows(rows)] == [1, 2, 3]
        ids = _cluster_source_ids(rows)
        assert ids == [1, 2, 3]              # хронологический порядок
        assert _cluster_key(ids) == "1,2,3"
