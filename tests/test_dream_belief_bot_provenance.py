"""P0-HA RELEVANCE (source-2026-10-29.md §10) — bot-источники в «сне».

Директива §10: собственные повторные пересказы бота не увеличивают
значимость события. Консолидация beliefs (DreamWorker._write_belief):
Σ-важность belief набирают ТОЛЬКО источники не от бота (provenance по
origin-колонке, REUSE `_BOT_GENERATED_ORIGINS` read-path summary_memory);
bot-источники дают в сумму 0, provenance evidence сохраняется. Пользовательские
факты считаются как прежде; входы без bot-источников — байт-паритет прежнего
поведения. LLM замокан; конвенции — tests/test_dream_worker.py.
"""
import asyncio
import inspect
import json
import re

import pytest

from services import hot_config as hot
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT_ID = -100


@pytest.fixture
def db():
    """In-memory SQLite (миграции v1..v8) — база для всех кейсов."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _hot_cache(monkeypatch, values):
    """hot-кэш-заглушка (прецедент test_dream_worker)."""

    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeLLM:
    """Мок облачного LLMClient: очередь ответов."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        if self._answers:
            return self._answers.pop(0)
        return '{"beliefs":[]}'


def _worker(db, llm, monkeypatch):
    _hot_cache(monkeypatch, {"memory.dream_enabled": True})
    return DreamWorker(db, memory=None, llm=llm)


async def _add_fact(db, text, *, origin="chat_history", importance=4):
    """Факт чата с явной важностью (свежий created_at)."""
    return await db.insert_graph_fact(CHAT_ID, text, origin, None,
                                      importance=importance)


async def _belief_rows(db):
    cursor = await db.db.execute(
        "SELECT id, fact, origin, kind, importance, weight, source_ids, "
        "belief_meta, status, expires_at, supersedes "
        "FROM graph_facts WHERE kind = 'belief' ORDER BY id")
    return await cursor.fetchall()


def _answer(text, ids):
    return ('{"beliefs":[{"text":"%s","evidence":[%s]}]}'
            % (text, ",".join(str(i) for i in ids)))


class TestBotOnlySources:
    @pytest.mark.asyncio
    async def test_bot_only_sources_no_independent_importance(
            self, db, monkeypatch):
        """§10(a): кластер только из bot-источников (bot_direct_reply входит
        в _DREAM_SOURCE_ORIGINS) — belief получает no-source floor: важность
        не превышает Σ пустого набора независимых источников (= 0)."""
        ids = [await _add_fact(db, f"мария переехала в питер навсегда {i}",
                               origin="bot_direct_reply", importance=5)
               for i in (1, 2, 3)]
        llm = _FakeLLM(_answer("мария переехала в питер окончательно", ids))
        worker = _worker(db, llm, monkeypatch)
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        beliefs = await _belief_rows(db)
        assert len(beliefs) == 1
        # прежнее поведение: min(10, 5+5+5) = 10 — bot-пересказы накапливали
        # важность; теперь bot-источники не независимое доказательство:
        # Σ по не-bot источникам = 0 → no-source floor (insert_graph_fact
        # клампит важность 1..10, database.py: «явный importance — clamp
        # 1..10»), тот же исход, что у belief без независимых источников
        assert beliefs[0]["importance"] == 1


class TestMixedSources:
    @pytest.mark.asyncio
    async def test_user_sources_count_bot_adds_nothing(self, db, monkeypatch):
        """§10(b): пользовательские источники считаются как прежде
        (Σ = 3+3 = 6), bot-источники (10+10) в Σ не попадают → важность 6,
        а не min(10, 26) = 10. Provenance evidence не теряется."""
        user_ids = [await _add_fact(db,
                                    f"мария переехала в питер навсегда {i}",
                                    origin="chat_history", importance=3)
                    for i in (1, 2)]
        bot_ids = [await _add_fact(
            db, f"мария переехала в питер окончательно {i}",
            origin="bot_direct_reply", importance=10) for i in (1, 2)]
        all_ids = user_ids + bot_ids
        llm = _FakeLLM(_answer("мария переехала в питер окончательно",
                               all_ids))
        worker = _worker(db, llm, monkeypatch)
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        beliefs = await _belief_rows(db)
        assert len(beliefs) == 1
        b = beliefs[0]
        # evidence-проvenance полон: все 4 источника в source_ids/sources_count
        assert json.loads(b["source_ids"]) == sorted(all_ids)
        meta = json.loads(b["belief_meta"])
        assert meta["sources_count"] == 4
        # Σ только по user-источникам: min(10, 3+3) = 6
        assert b["importance"] == 6


class TestNoBotParity:
    @pytest.mark.asyncio
    async def test_no_bot_sources_outcome_unchanged(self, db, monkeypatch):
        """§10(c): входы без bot-источников — исход консолидации байт-в-байт
        прежний: importance=min(10, Σ всех источников), belief-строка, метаданные,
        аудит и watermark не меняются."""
        ids = [await _add_fact(db, f"вася платит в {i} раз в баре подряд",
                               origin="chat_history", importance=4)
               for i in (1, 2, 3)]
        llm = _FakeLLM(_answer("вася всегда платит за всех в баре", ids))
        worker = _worker(db, llm, monkeypatch)
        res = await worker.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert res["distilled"] == 1
        beliefs = await _belief_rows(db)
        assert len(beliefs) == 1
        b = beliefs[0]
        assert b["kind"] == "belief"
        assert b["origin"] == "derived_belief"
        assert b["fact"] == "вася всегда платит за всех в баре"
        assert b["importance"] == 10         # min(10, 4+4+4) — как прежде
        assert b["weight"] == 0.6
        assert b["status"] == "confirmed"
        assert b["expires_at"] is None
        assert b["supersedes"] is None
        assert json.loads(b["source_ids"]) == sorted(ids)
        cursor = await db.db.execute(
            "SELECT run_at FROM memory_dream_log WHERE kind = 'distilled'")
        run_at = (await cursor.fetchone())["run_at"]
        meta = json.loads(b["belief_meta"])
        assert meta == {
            "confidence": 1.0,
            "sources_count": 3,
            "distilled_at": run_at,
            "cluster_id": 1,
            "base_weight": 0.6,
            "last_reinforced_fact_id": max(ids),
            "decay_months": 0,
        }
        # аудит: run + distilled; watermark — до MAX обработанного
        cursor = await db.db.execute(
            "SELECT kind, status FROM memory_dream_log ORDER BY id")
        rows = await cursor.fetchall()
        assert [(r["kind"], r["status"]) for r in rows] == \
            [("run", "ok"), ("distilled", "ok")]
        state = await db.get_dream_state(CHAT_ID)
        assert state["last_processed_fact_id"] == max(ids)
        assert state["last_run_at"] > 0


class TestProvenanceMechanism:
    def test_exclusion_is_provenance_set_not_topic_list(self):
        """§10(d): исключение — по provenance-набору origin'ов (та же
        константа read-path summary_memory, REUSE не копия), без списков
        тем/имён: в коде _write_belief нет строковых литералов кириллицы."""
        import services.dream_worker as dw
        from services.summary_memory import _BOT_GENERATED_ORIGINS as read_path
        # REUSE той же константы (не копия), provenance-набор origin-колонки
        assert dw._BOT_GENERATED_ORIGINS is read_path
        assert set(read_path) == {"bot_self_reply", "bot_direct_reply"}
        src = inspect.getsource(dw.DreamWorker._write_belief)
        assert "_BOT_GENERATED_ORIGINS" in src
        # docstring (первый triple-quote-блок) вырезаем — проверяем
        # исполняемый код; построчно срезаем комментарии
        code = re.sub(r'"""[\s\S]*?"""', "", src, count=1)
        for line in code.splitlines():
            code_line = line.split("#", 1)[0]
            assert not re.search(r'["\'][^"\']*[а-яё][^"\']*["\']', code_line,
                                 re.IGNORECASE), line
