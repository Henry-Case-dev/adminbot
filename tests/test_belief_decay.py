"""F2 `cognition-belief-decay-round1013` (spec §4/§9) — охлаждение убеждений
(Belief Decay) + воскрешение (Resurrection).

Покрытие (T-1431):
  * decay на границе: 180 дней → нет; 181 → −0.1; 211 → −0.2; вес ровно на
    пороге не архивируется, ниже — `archived_belief`; идемпотентность;
  * подкрепление новым сырым фактом с якорным токеном (сброс даты/веса);
  * изоляция архива: FTS/сон его не видят, KNN видит с пенальти;
  * резонанс: cosine ≥ порога → воскрешение (status confirmed, вес base);
  * реаниматор сна: сильное совпадение кластера → синтез отменён, старый
    belief восстановлен (новый id НЕ создан);
  * граф-активация: связка 2–3 узлов ≥ 3 раз в L1 → архив в горячий кэш;
  * телеметрия: счётчики R17-safe.
"""
import asyncio
import json
import time

import pytest

from config.settings import settings
from services import hot_config as hot
from services.database import DatabaseService
from services.dream_worker import DreamWorker
from services.summary_memory import MemoryManager, build_fts_query

CHAT_ID = -100
_DAY = 86400


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
    """hot-кэш-заглушка: заданные ключи; отсутствующие → settings-дефолты."""
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return '{"beliefs":[]}'


class _FakeMemory:
    """Мини-мок MemoryManager для реаниматора/граф-активации."""

    def __init__(self, vectors=None):
        self._vec_available = True
        self.aliases = None
        self._vectors = vectors
        self.embed_calls = 0
        self.saved_embeddings = []

    async def _embed(self, texts):
        self.embed_calls += 1
        if self._vectors is not None:
            return self._vectors
        return [[0.1, 0.0] for _ in texts]

    async def _save_graph_fact_embedding(self, *args, **kwargs):
        self.saved_embeddings.append(args)


async def _insert_belief(db, text, *, chat_id=CHAT_ID, weight=0.6,
                         status="confirmed", base_weight=0.6,
                         last_confirmed_at=None, last_reinforced=None,
                         target_user=None, origin="derived_belief",
                         meta_extra=None):
    meta = {"base_weight": base_weight, "decay_months": 0,
            "last_reinforced_fact_id": int(last_reinforced or 0)}
    if meta_extra:
        meta.update(meta_extra)
    belief_id = await db.insert_graph_fact(
        chat_id, text, origin, None, weight=weight, importance=5,
        kind="belief", status=status, target_user=target_user,
        belief_meta=json.dumps(meta, ensure_ascii=False))
    if last_confirmed_at is not None:
        await db.db.execute(
            "UPDATE graph_facts SET last_confirmed_at = ? WHERE id = ?",
            (int(last_confirmed_at), belief_id))
        await db.db.commit()
    return belief_id


async def _add_fact(db, text, *, chat_id=CHAT_ID, origin="chat_history",
                    importance=4, created_at=None):
    fact_id = await db.insert_graph_fact(
        chat_id, text, origin, None, importance=importance)
    if created_at is not None:
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ? WHERE id = ?",
            (int(created_at), fact_id))
        await db.db.commit()
    return fact_id


async def _belief(db, belief_id):
    cursor = await db.db.execute(
        "SELECT status, weight, last_confirmed_at, belief_meta "
        "FROM graph_facts WHERE id = ?", (belief_id,))
    return dict(await cursor.fetchone())


def _worker(db, *, memory=None, llm=None, monkeypatch=None):
    worker = DreamWorker(db, memory=memory, llm=llm or _FakeLLM())
    _hot_cache(monkeypatch, {
        "flags.belief_decay_enabled": True,
        "memory.dream_enabled": True,
    })
    return worker


# ── 1. Декай-шаг: границы и идемпотентность ─────────────────────────────────

class TestDecayStep:
    @pytest.mark.asyncio
    async def test_180_days_no_decay(self, db, monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   last_confirmed_at=now - 180 * _DAY)
        worker = _worker(db, monkeypatch=monkeypatch)
        await worker._decay_step(now)
        row = await _belief(db, bid)
        assert row["status"] == "confirmed"
        assert row["weight"] == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_181_days_minus_0_1(self, db, monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   last_confirmed_at=now - 181 * _DAY)
        worker = _worker(db, monkeypatch=monkeypatch)
        await worker._decay_step(now)
        row = await _belief(db, bid)
        assert row["status"] == "confirmed"
        assert row["weight"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_211_days_minus_0_2(self, db, monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   last_confirmed_at=now - 211 * _DAY)
        worker = _worker(db, monkeypatch=monkeypatch)
        await worker._decay_step(now)
        row = await _belief(db, bid)
        assert row["weight"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_threshold_exact_not_archived(self, db, monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   weight=0.4, base_weight=0.4,
                                   last_confirmed_at=now - 181 * _DAY)
        worker = _worker(db, monkeypatch=monkeypatch)
        await worker._decay_step(now)
        row = await _belief(db, bid)
        assert row["weight"] == pytest.approx(0.3)
        assert row["status"] == "confirmed"      # ровно порог — НЕ архив

    @pytest.mark.asyncio
    async def test_below_threshold_archived(self, db, monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   weight=0.4, base_weight=0.4,
                                   last_confirmed_at=now - 211 * _DAY)
        worker = _worker(db, monkeypatch=monkeypatch)
        stats = await worker._decay_step(now)
        row = await _belief(db, bid)
        assert row["status"] == "archived_belief"
        assert row["weight"] == pytest.approx(0.2)
        meta = json.loads(row["belief_meta"])
        assert meta["archived_at"] == now
        assert meta["decay_months"] == 2
        assert stats["archived"] == 1

    @pytest.mark.asyncio
    async def test_idempotent_second_run(self, db, monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   last_confirmed_at=now - 211 * _DAY)
        worker = _worker(db, monkeypatch=monkeypatch)
        await worker._decay_step(now)
        first = await _belief(db, bid)
        await worker._decay_step(now)
        second = await _belief(db, bid)
        assert first["weight"] == second["weight"]
        assert second["weight"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_paradigms_excluded_from_decay(self, db, monkeypatch):
        """S10.13-3: F3-парадигмы (belief_meta.type='paradigm') не охлаждаются
        общей формулой — «вечный» исторический слой переживает 400 дней."""
        now = int(time.time())
        pid = await _insert_belief(
            db, "чат прошёл путь от флуда к осмысленной памяти",
            last_confirmed_at=now - 400 * _DAY,
            meta_extra={"type": "paradigm"})
        worker = _worker(db, monkeypatch=monkeypatch)
        stats = await worker._decay_step(now)
        assert stats["checked"] == 0
        row = await _belief(db, pid)
        assert row["status"] == "confirmed"
        assert row["weight"] == pytest.approx(0.6)


# ── 2. Подкрепление ─────────────────────────────────────────────────────────

class TestReinforcement:
    @pytest.mark.asyncio
    async def test_anchor_fact_resets_weight_and_date(self, db, monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   last_confirmed_at=now - 200 * _DAY)
        fact_id = await _add_fact(db, "толян снова угостил всех друзей")
        worker = _worker(db, monkeypatch=monkeypatch)
        stats = await worker._decay_step(now)
        row = await _belief(db, bid)
        assert stats["reinforced"] == 1
        assert row["weight"] == pytest.approx(0.6)
        assert row["status"] == "confirmed"
        meta = json.loads(row["belief_meta"])
        assert meta["last_reinforced_fact_id"] == fact_id
        assert int(row["last_confirmed_at"]) == now

    @pytest.mark.asyncio
    async def test_fact_without_anchor_does_not_reinforce(self, db,
                                                          monkeypatch):
        now = int(time.time())
        bid = await _insert_belief(db, "толян всегда платит за всех",
                                   last_confirmed_at=now - 200 * _DAY)
        await _add_fact(db, "петруха уехал в другой город навсегда")
        worker = _worker(db, monkeypatch=monkeypatch)
        stats = await worker._decay_step(now)
        row = await _belief(db, bid)
        assert stats["reinforced"] == 0
        assert row["weight"] < 0.6   # декай прошёл


# ── 3. Изоляция архива ──────────────────────────────────────────────────────

class TestArchiveIsolation:
    @pytest.mark.asyncio
    async def test_fts_hides_archived_belief(self, db, monkeypatch):
        now = int(time.time())
        archived = await _insert_belief(db, "толян закрепил литрбол",
                                        status="archived_belief", weight=0.2)
        bid = await _insert_belief(db, "толян закрепил литрбол",
                                   status="confirmed")
        match = build_fts_query(["литрбол"])
        rows = await db.search_graph_facts_fts(CHAT_ID, match, 10, now)
        ids = [r["id"] for r in rows]
        assert bid in ids
        assert archived not in ids

    @pytest.mark.asyncio
    async def test_dig_into_lore_includes_archived(self, db, monkeypatch):
        now = int(time.time())
        archived = await _insert_belief(db, "толян закрепил литрбол",
                                        status="archived_belief", weight=0.2)
        match = build_fts_query(["литрбол"])
        rows = await db.search_graph_facts_fts(
            CHAT_ID, match, 10, now, include_archived=True)
        assert archived in [r["id"] for r in rows]

    @pytest.mark.asyncio
    async def test_dream_candidates_exclude_archived(self, db, monkeypatch):
        now = int(time.time())
        await _add_fact(db, "свежий факт чата для сна")
        await _insert_belief(db, "толян закрепил литрбол",
                             status="archived_belief", weight=0.2)
        rows = await db.get_dream_candidates(
            CHAT_ID, now, origins=("chat_history",),
            since_ts=now - 3600)
        assert rows
        assert all(r["fact"] != "толян закрепил литрбол" for r in rows)


# ── 4. Векторный резонанс ───────────────────────────────────────────────────

def _prep_knn(monkeypatch):
    _hot_cache(monkeypatch, {
        "flags.belief_decay_enabled": True,
        "flags.graph_mmr_enabled": False,
        "flags.graph_fact_touch_enabled": False,
        "flags.graph_time_decay_enabled": False,
    })


class TestVectorResonance:
    @pytest.mark.asyncio
    async def test_archived_visible_with_penalty(self, db, monkeypatch):
        now = int(time.time())
        archived = await _insert_belief(db, "толян закрепил литрбол",
                                        status="archived_belief", weight=0.6,
                                        last_confirmed_at=now)
        confirmed = await _add_fact(db, "обычный подтверждённый факт")
        _prep_knn(monkeypatch)
        memory = MemoryManager(db, _FakeLLM())

        async def _candidates(chat_id, vector, fetch_k, *a, **kw):
            return [(confirmed, 0.5, None), (archived, 0.5, None)]

        memory._vec_candidates = _candidates
        rows = await memory._knn_graph_facts(CHAT_ID, [0.1, 0.0], 2)
        texts = [r[1] for r in rows]
        # Архив НЕ исключён; пенальти ставит его после активного.
        assert "толян закрепил литрбол" in texts
        assert texts[0] == "обычный подтверждённый факт"
        # cosine 0.5 < 0.78 → воскрешения нет.
        assert (await _belief(db, archived))["status"] == "archived_belief"

    @pytest.mark.asyncio
    async def test_resonance_resurrects(self, db, monkeypatch):
        now = int(time.time())
        archived = await _insert_belief(db, "толян закрепил литрбол",
                                        status="archived_belief", weight=0.2,
                                        last_confirmed_at=now)
        _prep_knn(monkeypatch)
        memory = MemoryManager(db, _FakeLLM())

        async def _candidates(chat_id, vector, fetch_k, *a, **kw):
            return [(archived, 0.90, None)]

        memory._vec_candidates = _candidates
        rows = await memory._knn_graph_facts(CHAT_ID, [0.1, 0.0], 2)
        assert rows and rows[0][1] == "толян закрепил литрбол"
        row = await _belief(db, archived)
        assert row["status"] == "confirmed"
        assert row["weight"] == pytest.approx(0.6)
        assert int(row["last_confirmed_at"]) == pytest.approx(now, abs=5)
        meta = json.loads(row["belief_meta"])
        assert meta["resurrections"] == 1
        assert await db.count_dream_log(0, kind="resurrect") == 1


# ── 5. Сон-Реаниматор ───────────────────────────────────────────────────────

class TestDreamReanimator:
    @pytest.mark.asyncio
    async def test_strong_match_cancels_synthesis(self, db, monkeypatch):
        now = int(time.time())
        archived = await _insert_belief(db, "толян закрепил литрбол",
                                        status="archived_belief", weight=0.2,
                                        last_confirmed_at=now - 300 * _DAY)
        for i in range(3):
            await _add_fact(db, f"толян и костя снова литрбол в {i + 1} раз")
        memory = _FakeMemory(vectors=[[1.0, 0.0], [1.0, 0.0]])
        llm = _FakeLLM()
        worker = DreamWorker(db, memory=memory, llm=llm)
        _hot_cache(monkeypatch, {
            "flags.belief_decay_enabled": True,
            "memory.dream_enabled": True,
        })
        res = await worker.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert llm.calls == []                      # синтез отменён
        row = await _belief(db, archived)
        assert row["status"] == "confirmed"
        assert int(row["last_confirmed_at"]) > now - 100 * _DAY
        # новый belief НЕ создан — только старый (он же единственный)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 1
        log = await db.recent_dream_log(limit=5)
        # S10.13-4: реанимация пишется kind='resurrect' — видна в телеметрии
        # (resurrections_total/health/Timeline), а не как безмолвный skipped.
        assert any(r["kind"] == "resurrect" and r["status"] == "resurrected"
                   and r["belief_id"] == archived for r in log)
        assert await db.count_dream_log(0, kind="resurrect") == 1

    @pytest.mark.asyncio
    async def test_no_match_keeps_synthesis(self, db, monkeypatch):
        now = int(time.time())
        await _insert_belief(db, "толян закрепил литрбол",
                             status="archived_belief", weight=0.2,
                             last_confirmed_at=now - 300 * _DAY)
        for i in range(3):
            await _add_fact(db, f"толян и костя снова литрбол в {i + 1} раз")
        memory = _FakeMemory(vectors=[[1.0, 0.0], [0.0, 1.0]])
        llm = _FakeLLM('{"beliefs":[]}')
        worker = DreamWorker(db, memory=memory, llm=llm)
        _hot_cache(monkeypatch, {
            "flags.belief_decay_enabled": True,
            "memory.dream_enabled": True,
        })
        await worker.run_once(CHAT_ID)
        assert llm.calls                        # синтез не отменён


# ── 6. Активация по графу ───────────────────────────────────────────────────

class TestGraphActivation:
    async def _l1_with_pair(self, db, chat_id, hits):
        now = int(time.time())
        for i in range(hits):
            await db.save_smart_message(
                1, chat_id, f"толян и костя снова вместе в {i + 1} раз",
                None, now - (10 - i), "text", "юзер")
        await db.upsert_node(chat_id, "Толян", "user")
        await db.upsert_node(chat_id, "Костя", "user")

    @pytest.mark.asyncio
    async def test_hot_pair_injects_archived(self, db, monkeypatch):
        _hot_cache(monkeypatch, {"flags.belief_decay_enabled": True})
        await self._l1_with_pair(db, CHAT_ID, 3)
        bid = await _insert_belief(db, "толян закрепил литрбол",
                                   status="archived_belief", weight=0.2)
        memory = MemoryManager(db, _FakeLLM())
        facts = await memory.graph_activation_facts(CHAT_ID)
        assert len(facts) == 1
        assert facts[0][1] == "толян закрепил литрбол"
        # показ не восстанавливает вес/статус (только горячий кэш)
        assert (await _belief(db, bid))["status"] == "archived_belief"

    @pytest.mark.asyncio
    async def test_cold_pair_no_inject(self, db, monkeypatch):
        _hot_cache(monkeypatch, {"flags.belief_decay_enabled": True})
        await self._l1_with_pair(db, CHAT_ID, 2)
        await _insert_belief(db, "толян закрепил литрбол",
                             status="archived_belief", weight=0.2)
        memory = MemoryManager(db, _FakeLLM())
        assert await memory.graph_activation_facts(CHAT_ID) == []

    @pytest.mark.asyncio
    async def test_flag_off_no_inject(self, db, monkeypatch):
        _hot_cache(monkeypatch, {"flags.belief_decay_enabled": False})
        await self._l1_with_pair(db, CHAT_ID, 3)
        await _insert_belief(db, "толян закрепил литрбол",
                             status="archived_belief", weight=0.2)
        memory = MemoryManager(db, _FakeLLM())
        assert await memory.graph_activation_facts(CHAT_ID) == []


# ── 7. Телеметрия (R17-safe) ────────────────────────────────────────────────

class TestTelemetry:
    @pytest.mark.asyncio
    async def test_counters_and_health_line(self, db, monkeypatch):
        now = int(time.time())
        await _insert_belief(db, "толян закрепил литрбол")
        await _insert_belief(db, "костя уехал навсегда",
                             status="archived_belief", weight=0.2)
        # S10.13-3/-6: парадигма не считается «убеждением» в телеметрии.
        await _insert_belief(db, "чат вырос в осмысленную память",
                             meta_extra={"type": "paradigm"})
        await db.log_dream_event(0, now, kind="decay_run",
                                 tokens=0, status="ok")
        await db.log_dream_event(-100, now, kind="resurrect",
                                 belief_id=1, tokens=0, status="resurrected")
        counts = await db.count_beliefs_by_status()
        assert counts["confirmed"] == 1
        assert counts["archived_belief"] == 1
        assert await db.count_dream_log(0, kind="resurrect") == 1
        assert await db.last_decay_run() == now

        from services.memory_health import collect_metrics
        text = await collect_metrics(db, memory=None)
        assert "убеждения: активных 1, в архиве 1, воскрешений 1" in text

    def test_belief_out_archived_r17_safe(self):
        from web.api.memory_agi import _belief_out
        row = {
            "id": 7, "chat_id": -100, "fact": "толян закрепил литрбол",
            "weight": 0.2, "importance": 5, "source_ids": None,
            "belief_meta": json.dumps(
                {"base_weight": 0.6, "archived_at": 1719000000}),
            "status": "archived_belief", "supersedes": None,
            "created_at": 1710000000,
        }
        out = _belief_out(row)
        assert out["archived"] is True
        assert out["base_weight"] == 0.6
        assert out["archived_at"] == 1719000000
        # R17: никаких эмбеддингов/ключей
        assert "embedding" not in out and "api_key" not in out
