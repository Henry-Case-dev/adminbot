"""B03 (v6.3) — просроченная и бессрочная память + D06-остаток.

Контракты:
- B03.4/D06-остаток: chat-scope ДО effective top-K в GraphRAG KNN
  (`_vec_candidates`): большой объём более похожих ЧУЖИХ фактов не
  вытесняет факты своего чата (RED на pre-fix: фиксированный глобальный
  k=fetch_k×2 → фильтр после). Чужие факты никогда не возвращаются.
- B03.1: retrieval eligibility ≠ retention: expired-факт находит
  исторический FTS-запрос (dig, include_archived), обычный RAG его не
  выдаёт как свежий.
- B03.2: fresh-first + архивный top-up с trust-пометкой (expired/as-of);
  supersede: старая версия не удаляется, находится исторически, журнал
  версий пишется, свежая выдача показывает только новую версию.
- B03.3: expired-overview (bounded COUNT-классификация).
- B03.5: в infinite-режиме удалений нет (purge/invalidate — noop или
  UPDATE без потери строк/vec-эмбеддинга); per-chat override независим.

TEST-LIFECYCLE: REGRESSION owner=REQ-B03-CLARIFY/REQ-B03-DOD
R17: только синтетические векторы/факты, никаких реальных переписок.
"""
import asyncio
import json
import time

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.summary_memory import MemoryManager, build_rag_context

CHAT_A = -100
CHAT_B = -200
DIM = 8


def _unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i % DIM] = 1.0
    return v


def _mix(a: float, b: float) -> list[float]:
    v = [0.0] * DIM
    v[0] = a
    v[1] = b
    return v


class VecLLM:
    """embed по карте текст→вектор (синтетика R17); generate не используется."""

    def __init__(self, vec_map=None, default=None):
        self.vec_map = vec_map or {}
        self.default = default or _unit(0)
        self.embed_calls = 0

    async def embed(self, texts):
        self.embed_calls += 1
        return [self.vec_map.get(t, self.default) for t in texts]

    async def generate(self, messages):  # pragma: no cover - не вызывается
        raise AssertionError("generate не нужен в B03-тестах")


class _StubHotCache:
    """hot.get-совместимый кэш-стаб (ключ → значение)."""

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


async def _init_memory(db, llm, monkeypatch=None, int8=False):
    """MemoryManager на реальной SQLite+sqlite-vec (harness D06)."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        pytest.skip("sqlite-vec not installed")
    assert monkeypatch is not None

    async def _probe_fixed(self):
        return bool(int8)

    monkeypatch.setattr(MemoryManager, "_probe_vec_int8", _probe_fixed)
    memory = MemoryManager(db, llm)

    async def _noop_backfill() -> int:
        return 0

    memory.backfill_archive_vectors = _noop_backfill
    memory.backfill_graph_fact_vectors = _noop_backfill
    ok = await memory.initialize()
    if not ok:
        pytest.skip("sqlite-vec extension could not be loaded")
    assert memory._vec_int8 is bool(int8)
    return memory


async def _seed_graph_fact(db, memory, chat_id, text, vector, *,
                           expires_at=None, origin="chat_history",
                           weight=0.5):
    fid = await db.insert_graph_fact(chat_id, text, origin, expires_at,
                                     weight=weight)
    memory.llm.vec_map[text] = vector
    await memory._insert_graph_vec_row(fid, chat_id, text, origin,
                                       expires_at, vector)
    return fid


# ── B03.4: displacement — большой объём чужих фактов (RED/GREEN) ────────────


class TestGraphKnnChatScope:
    async def _seed_displacement(self, db, memory):
        """CHAT_B: 3500 чужих фактов, 400 из них СТРОГО ближе к запросу из
        CHAT_A, чем локальный факт A (cos≈0.95); остальные 3100 — фон ниже.
        Pre-fix KNN (глобальный k=fetch_k×2=20) выдавал только чужие top-20
        → локальный вытеснен (RED). Staged overfetch добирается до 512 →
        локальный найден, чужих в выдаче нет (GREEN)."""
        q = _unit(0)
        local = _mix(0.95, 0.312)
        closer = _mix(0.99, 0.141)
        background = _mix(0.90, 0.436)
        fid_local = await _seed_graph_fact(
            db, memory, CHAT_A, "Алекс работает в компании X", local)
        fids_foreign = set()
        rows = []
        for i in range(400):
            fids_foreign.add(10_000 + i)
            rows.append((10_000 + i, 10_000 + i, CHAT_B, "chat_history",
                         None, json.dumps(closer)))
        for i in range(3100):
            fids_foreign.add(20_000 + i)
            rows.append((20_000 + i, 20_000 + i, CHAT_B, "chat_history",
                         None, json.dumps(background)))
        await db.db.executemany(
            "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
            "expires_at, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows])
        await db.db.commit()
        memory.llm.vec_map["где работает алекс"] = q
        return q, fid_local, fids_foreign

    @pytest.mark.asyncio
    async def test_foreign_volume_does_not_displace_local(
            self, db, monkeypatch):
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        q, fid_local, foreign_ids = await self._seed_displacement(db, memory)

        started = time.monotonic()
        rows = await memory._knn_graph_facts(CHAT_A, q, 5)
        elapsed = time.monotonic() - started

        assert rows, "локальный факт вытеснен чужими (displacement)"
        # чужие факты никогда не возвращаются в выдачу чата A
        foreign_items = {f"fact:{fid}" for fid in foreign_ids}
        assert all(item[4] not in foreign_items for item in rows)
        assert any(item[4] == f"fact:{fid_local}" for item in rows), \
            "свой факт не найден в KNN-выдаче"
        # мягкая latency-граница (3500+ фактов не ломают задержку; CI-safe)
        assert elapsed < 5.0, f"KNN на 3500+ фактов занял {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_scoped_int8_path_never_returns_foreign(
            self, db, monkeypatch):
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=True)
        q = _unit(0)
        local = _mix(0.95, 0.312)
        closer = _mix(0.99, 0.141)
        background = _mix(0.90, 0.436)
        fid_local = await _seed_graph_fact(
            db, memory, CHAT_A, "Алекс работает в компании X", local)
        foreign = set()
        for i in range(400):
            fid = await db.insert_graph_fact(
                CHAT_B, f"Алекс работает в компании Y #{i}", "chat_history",
                None)
            await memory._insert_graph_vec_row(
                fid, CHAT_B, f"Алекс работает в компании Y #{i}",
                "chat_history", None, closer)
            foreign.add(fid)
        for i in range(200):
            fid = await db.insert_graph_fact(
                CHAT_B, f"Алекс работает в компании Z #{i}", "chat_history",
                None)
            await memory._insert_graph_vec_row(
                fid, CHAT_B, f"Алекс работает в компании Z #{i}",
                "chat_history", None, background)
            foreign.add(fid)
        memory.llm.vec_map["где работает алекс"] = q

        rows = await memory._knn_graph_facts(CHAT_A, q, 5)
        assert rows
        assert all(int(str(item[4]).split(":")[1]) not in foreign
                   for item in rows)
        assert any(item[4] == f"fact:{fid_local}" for item in rows)


# ── B03.1: historical eligibility expired-фактов ────────────────────────────


class TestExpiredRetrievalEligibility:
    @pytest.mark.asyncio
    async def test_expired_found_by_historical_query_only(
            self, db, monkeypatch):
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        past = now - 90 * 86400
        fid = await _seed_graph_fact(
            db, memory, CHAT_A, "проект Альфа заморожен в 2022",
            _unit(3), expires_at=past)
        match = '"альфа"*'

        # обычный RAG: expired НЕ выдаётся как свежий
        fresh = await db.search_graph_facts_fts(CHAT_A, match, 10, now)
        assert all(r["id"] != fid for r in fresh)
        # исторический запрос (dig_into_lore, include_archived): найден
        hist = await db.search_graph_facts_fts(
            CHAT_A, match, 10, now, include_archived=True)
        ids = [r["id"] for r in hist]
        assert fid in ids
        row = next(r for r in hist if r["id"] == fid)
        assert row["expires_at"] is not None and row["expires_at"] <= now


# ── B03.2: fresh-first + expired top-up + supersede ─────────────────────────


class TestArchiveTopUpAndVersions:
    @pytest.mark.asyncio
    async def test_expired_topup_marked_with_trust_flag(
            self, db, monkeypatch):
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        past = now - 30 * 86400
        fid = await _seed_graph_fact(
            db, memory, CHAT_A, "сервер Аркадия лежал в марте",
            _unit(0), expires_at=past)
        memory.llm.vec_map["сервер аркадия"] = _unit(0)
        rows = await memory._knn_graph_facts(
            CHAT_A, _unit(0), 5, with_meta=True)
        assert rows, "expired-факт не найден даже архивной стадией"
        top = rows[0]
        assert top["id"] == fid
        assert top["expired"] is True
        assert top["expires_at"] == past
        # 6/7-кортеж: 7-й элемент — expired-флаг; рендер честно помечен
        tuples = await memory._knn_graph_facts(CHAT_A, _unit(0), 5)
        assert tuples[0][6] is True
        ctx = build_rag_context(tuples)
        assert "срок актуальности истёк" in ctx

    @pytest.mark.asyncio
    async def test_fresh_outranks_expired_when_both_match(
            self, db, monkeypatch):
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        past = now - 30 * 86400
        future = now + 30 * 86400
        fid_exp = await _seed_graph_fact(
            db, memory, CHAT_A, "отчёт сдаётся в пятницу",
            _unit(0), expires_at=past)
        fid_fresh = await _seed_graph_fact(
            db, memory, CHAT_A, "отчёт сдаётся в пятницу подтверждено",
            _mix(0.99, 0.1), expires_at=future)
        memory.llm.vec_map["когда отчёт"] = _unit(0)
        rows = await memory._knn_graph_facts(
            CHAT_A, _unit(0), 5, with_meta=True)
        ids = [r["id"] for r in rows]
        assert fid_fresh in ids and fid_exp in ids
        assert ids.index(fid_fresh) < ids.index(fid_exp), \
            "свежий факт должен ранжироваться выше архивного"
        assert rows[ids.index(fid_exp)]["expired"] is True
        assert rows[ids.index(fid_fresh)]["expired"] is False

    @pytest.mark.asyncio
    async def test_archive_flag_off_disables_topup(self, db, monkeypatch):
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        past = now - 30 * 86400
        await _seed_graph_fact(
            db, memory, CHAT_A, "сервер Аркадия лежал в марте",
            _unit(0), expires_at=past)
        memory.llm.vec_map["сервер аркадия"] = _unit(0)
        hot_cache = _StubHotCache({"flags.memory_archive_retrieval": False})

        import services.hot_config as hot_config
        monkeypatch.setattr(hot_config, "_cache", hot_cache)
        rows = await memory._knn_graph_facts(CHAT_A, _unit(0), 5)
        assert rows == []

    @pytest.mark.asyncio
    async def test_supersede_version_crossing(self, db, monkeypatch):
        """Пересечение версий: старая версия не удаляется, свежая выдача
        показывает новую, историческая находит старую с as-of, журнал
        версий содержит supersede; в infinite-режиме vec-строка жива."""
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        future = now + 60 * 86400
        v1 = await _seed_graph_fact(
            db, memory, CHAT_A, "Алекс живёт в Казани", _unit(0),
            expires_at=future)
        # supersede-путь (_memorize_facts_inner): новый факт + инвалидация
        v2 = await db.insert_graph_fact(
            CHAT_A, "Алекс живёт в Самаре", "chat_history", future,
            status="unconfirmed", supersedes=v1)
        memory.llm.vec_map["Алекс живёт в Самаре"] = _mix(0.99, 0.1)
        await memory._insert_graph_vec_row(
            v2, CHAT_A, "Алекс живёт в Самаре", "chat_history", future,
            _mix(0.99, 0.1))
        await db.invalidate_graph_fact(v1, now)
        await db.log_fact_compression(
            CHAT_A, v2, "Алекс живёт в Казани", "Алекс живёт в Самаре",
            "supersede")
        await db.confirm_graph_fact(v2, now, 0.05)

        # vec-строка старой версии удалена (не-infinite) — строка факта ЖИВА
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts WHERE id = ?", (v1,))
        assert (await cursor.fetchone())["n"] == 1
        cursor = await db.db.execute(
            "SELECT expires_at, status FROM graph_facts WHERE id = ?", (v1,))
        row = await cursor.fetchone()
        assert row["expires_at"] is not None and row["expires_at"] <= now

        # свежая выдача: v1 не возвращается (TTL), v2 найден
        memory.llm.vec_map["где живёт алекс"] = _unit(0)
        fresh = await memory._knn_graph_facts(
            CHAT_A, _unit(0), 5, with_meta=True)
        fresh_ids = [r["id"] for r in fresh]
        assert v1 not in fresh_ids
        assert v2 in fresh_ids

        # историческая выдача: старая версия доступна как архив
        hist = await db.search_graph_facts_fts(
            CHAT_A, '"казани"*', 10, now, include_archived=True)
        assert any(r["id"] == v1 for r in hist)
        # журнал версий
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_fact_compressions "
            "WHERE reason = 'supersede' AND fact_id = ?", (v2,))
        assert (await cursor.fetchone())["n"] == 1

    @pytest.mark.asyncio
    async def test_infinite_retention_keeps_vec_row_on_invalidate(
            self, db, monkeypatch):
        import services.hot_config as hot_config
        monkeypatch.setattr(
            hot_config, "_cache",
            _StubHotCache({"memory.infinite_retention": True}))
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        future = now + 60 * 86400
        fid = await _seed_graph_fact(
            db, memory, CHAT_A, "Алекс живёт в Казани", _unit(0),
            expires_at=future)
        await db.invalidate_graph_fact(fid, now)
        # строка факта и vec-строка (embedding) живут; expires_at обновлён
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts WHERE id = ?", (fid,))
        assert (await cursor.fetchone())["n"] == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts_vec WHERE rowid = ?",
            (fid,))
        assert (await cursor.fetchone())["n"] == 1
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts WHERE id = ?", (fid,))
        assert (await cursor.fetchone())["expires_at"] <= now


# ── B03.3: bounded классификация expired ────────────────────────────────────


class TestExpiredOverview:
    @pytest.mark.asyncio
    async def test_overview_counts_bounded(self, db, monkeypatch):
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        past = now - 86400
        future = now + 86400
        await _seed_graph_fact(db, memory, CHAT_A, "старый факт один",
                               _unit(0), expires_at=past)
        await _seed_graph_fact(db, memory, CHAT_A, "старый факт два",
                               _unit(1), expires_at=past)
        await _seed_graph_fact(db, memory, CHAT_A, "свежий факт",
                               _unit(2), expires_at=future)
        overview = await memory.expired_memory_overview(CHAT_A)
        assert overview["expired_total"] == 2
        assert overview["expired_searchable"] == 2
        assert overview["needs_recheck"] == 2
        assert overview["superseded_total"] == 0
        assert overview["infinite_retention"] is False


# ── B03.5: infinite mode без удалений + per-chat независимость ──────────────


async def _seed_expired_raw(db, chat_id, text, now, weight=0.3):
    """Истёкший слабый давно неподтверждённый факт — чистый кандидат purge.

    Создаётся через insert_graph_fact (FTS external-content согласован),
    затем raw-UPDATE стареет факт (created_at/last_confirmed_at/expires_at,
    weight) — прямой INSERT мимо FTS ломает консистентность индекса."""
    fid = await db.insert_graph_fact(chat_id, text, "chat_history", None,
                                     weight=weight)
    await db.db.execute(
        "UPDATE graph_facts SET expires_at = ?, created_at = ?, "
        "last_confirmed_at = ?, weight = ? WHERE id = ?",
        (now - 86400, now - 40 * 86400, now - 40 * 86400, weight, fid))
    await db.db.commit()
    return fid


class TestInfiniteRetentionNoDelete:
    @pytest.mark.asyncio
    async def test_infinite_mode_never_deletes(self, db, monkeypatch):
        import services.hot_config as hot_config
        monkeypatch.setattr(
            hot_config, "_cache",
            _StubHotCache({"memory.infinite_retention": True}))
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        fid = await _seed_expired_raw(db, CHAT_A, "слабый истёкший факт", now)

        assert await db.purge_expired_graph_facts() == 0
        assert await db.purge_unconfirmed_graph_facts(now, 7) == 0
        assert await db.trim_compression_log(float(now), 7) == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts WHERE id = ?", (fid,))
        assert (await cursor.fetchone())["n"] == 1

    @pytest.mark.asyncio
    async def test_per_chat_independent_infinite_override(
            self, db, monkeypatch):
        """Global OFF + per-chat override: A бессрочный (факты живут),
        B обычный (истёкшее удаляется); точечный purge A — 0."""
        import services.chat_params as chat_params
        import services.hot_config as hot_config

        async def _fake_override(chat_id, key, fallback=None):
            return True if chat_id == CHAT_A else fallback

        monkeypatch.setattr(hot_config, "_cache", _StubHotCache({}))
        monkeypatch.setattr(chat_params, "get_chat_param_defaulted",
                            _fake_override)
        memory = await _init_memory(db, VecLLM(), monkeypatch)
        now = int(time.time())
        fid_a = await _seed_expired_raw(db, CHAT_A, "факт чата A", now)
        fid_b = await _seed_expired_raw(db, CHAT_B, "факт чата B", now)

        deleted = await db.purge_expired_graph_facts()
        assert deleted == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts WHERE id = ?", (fid_a,))
        assert (await cursor.fetchone())["n"] == 1, \
            "бессрочный чат не должен чиститься глобальным проходом"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts WHERE id = ?", (fid_b,))
        assert (await cursor.fetchone())["n"] == 0

        assert await db.purge_expired_graph_facts(chat_id=CHAT_A) == 0
        # overview отражает режим чата
        overview = await memory.expired_memory_overview(CHAT_A)
        assert overview["expired_total"] == 1
        assert overview["infinite_retention"] is True
