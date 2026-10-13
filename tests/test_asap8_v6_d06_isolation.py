"""v6 D06 — hard chat isolation в vector retrieval/dedup (§9A.3, §18F.4).

Контракт: chat-scope ДО effective top-K/rank/dedup. vec0 0.1.9 не умеет
фильтр auxiliary-колонки внутри KNN-запроса (проба: OperationalError «illegal
WHERE constraint … auxiliary column»), DDL partition key — вне слайса →
доказанная staged overfetch-стратегия: k растёт ×4 до жёсткого cap, пока
после chat-фильтра не наберётся нужное число фактов СВОЕГО чата либо не
исчерпается индекс; исчерпание — честное «в чате меньше фактов», cap при
заполненном K — partial (телеметрия + WARNING, не пустой молча).

U13/§9A.5: два чата с одинаковым user_id и конфликтующими фактами
(«работает в X» vs «работает в Y») — чужие кандидаты не вытесняют свой чат
ни в archive-KNN (float и int8), ни в dedup.

TEST-LIFECYCLE: CONTRACT owner=D06 (v6 remediation §C)
R17: только синтетические векторы/факты, никаких реальных переписок.
"""
import asyncio
import json
import time

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.summary_memory import MemoryManager

CHAT_A = -100
CHAT_B = -200
DIM = 8  # фикстурная dim (initialize берёт её из probe-эмбедда заглушки)


def _unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i % DIM] = 1.0
    return v


def _mix(a: float, b: float) -> list[float]:
    """[a, b, 0…] (≈unit) — косинус к e0 = a при |v|≈1."""
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
        raise AssertionError("generate не нужен в D06-тестах")


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
    """MemoryManager на реальной SQLite+sqlite-vec. Путь фиксируется пробой
    vec_quantize_int8 ДО initialize: int8=True → int8-DDL, иначе float-only
    DDL (флаг после initialize не переключаем — vec0 int8-колонка NOT NULL,
    float-INSERT на int8-DDL невозможен)."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        pytest.skip("sqlite-vec not installed")
    assert monkeypatch is not None

    async def _probe_fixed(self):
        return bool(int8)

    monkeypatch.setattr(MemoryManager, "_probe_vec_int8", _probe_fixed)
    memory = MemoryManager(db, llm)
    # фоновые backfill'ы initialize — fire_and_forget писатели; для
    # детерминизма сидирования гасим их (тест сам вставляет vec-строки)
    async def _noop_backfill() -> int:
        return 0

    memory.backfill_archive_vectors = _noop_backfill
    memory.backfill_graph_fact_vectors = _noop_backfill
    ok = await memory.initialize()
    if not ok:
        pytest.skip("sqlite-vec extension could not be loaded")
    assert memory._vec_int8 is bool(int8)
    return memory


async def _seed_archive(db, memory, facts):
    """facts: [(chat_id, text, vector)] → smart_archive_facts + vec-строки."""
    for chat_id, text, vector in facts:
        fid = await db.save_archive_fact(chat_id, text, int(time.time()))
        memory.llm.vec_map[text] = vector
        await memory._save_archive_embedding(chat_id, fid, text)


async def _seed_graph_vec(memory, fact_id, chat_id, vector, expires_at=None,
                          origin="chat_history"):
    await memory._insert_graph_vec_row(fact_id, chat_id, "факт", origin,
                                       expires_at, vector)


# ── Archive KNN: chat-scope до top-K ─────────────────────────────────────────


class TestArchiveKnnIsolation:
    async def _seed_conflicting_chats(self, db, memory):
        # U13/§9A.5: один user («Алекс»), конфликтующие факты; эмбеддинг B
        # СТРОГО ближе к запросу из A (одинаковое имя ≈ почти тот же вектор),
        # свои факты A — чуть дальше. 6 чужих заполняют весь лимит 5.
        qa = _unit(0)
        vec_a = _mix(0.98, 0.2)      # cosine(qa, a) ≈ 0.98 → distance ≈ 0.02
        vec_b = _unit(0)             # distance 0 — чужое ближе своего
        facts_a = [f"Алекс работает в компании X #{i}" for i in range(2)]
        facts_b = [f"Алекс работает в компании Y #{i}" for i in range(6)]
        await _seed_archive(
            db, memory,
            [(CHAT_A, t, vec_a) for t in facts_a]
            + [(CHAT_B, t, vec_b) for t in facts_b])
        memory.llm.vec_map["где работает алекс"] = qa
        return facts_a, facts_b

    @pytest.mark.asyncio
    async def test_float_path_foreign_chat_cannot_displace_own(
            self, db, monkeypatch):
        """§18F.4: float-путь раньше брал k=limit РОВНО глобально → 6 чужих
        фактов вытесняли свои (false-empty). Теперь per-chat гарантия."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        assert memory._vec_int8 is False               # float-only DDL
        facts_a, facts_b = await self._seed_conflicting_chats(db, memory)

        facts, tele = await memory._search_archive_knn_scoped(
            CHAT_A, memory.llm.vec_map["где работает алекс"], 5)
        assert set(facts) == set(facts_a)          # только свой чат
        assert not any("Y" in f for f in facts)
        assert tele["own"] == 2
        assert tele["want"] == 5
        assert tele["partial"] is False
        assert tele["filtered_other_chat"] == 6

        # публичный путь vector_search — тот же контракт
        facts = await memory.vector_search(CHAT_A, "где работает алекс", 5)
        assert set(facts) == set(facts_a)

        # обратная сторона: запрос из B → только B-факты (симметрия U13);
        # limit=5 → ровно 5 ближайших СВОИХ из 6 (без утечки A)
        memory.llm.vec_map["работа алекса"] = _unit(0)
        facts, tele = await memory._search_archive_knn_scoped(
            CHAT_B, memory.llm.vec_map["работа алекса"], 5)
        assert len(facts) == 5
        assert set(facts) <= set(facts_b)
        assert not any("X" in f for f in facts)
        assert tele["own"] >= 5          # свои набраны до want — добора нет

    @pytest.mark.asyncio
    async def test_int8_path_foreign_chat_cannot_displace_own(
            self, db, monkeypatch):
        """§18F.4: int8-путь (k=limit×4 глобально → фильтр в Python) — чужие
        не должны занимать весь effective top-K."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=True)
        assert memory._vec_int8 is True
        facts_a, facts_b = await self._seed_conflicting_chats(db, memory)

        facts, tele = await memory._search_archive_knn_scoped(
            CHAT_A, memory.llm.vec_map["где работает алекс"], 5)
        assert set(facts) == set(facts_a)
        assert not any("Y" in f for f in facts)
        assert tele["own"] == 2

        facts = await memory.vector_search(CHAT_A, "где работает алекс", 5)
        assert set(facts) == set(facts_a)

    @pytest.mark.asyncio
    async def test_small_chat_exhausted_is_not_partial(self, db, monkeypatch):
        """Исчерпание индекса (строк < k) — честное «в чате меньше фактов»,
        НЕ partial (§18F.4 honest degradation различает эти случаи)."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        await _seed_archive(db, memory, [(CHAT_A, "свой факт А", _unit(0))])

        facts, tele = await memory._search_archive_knn_scoped(CHAT_A, _unit(0), 5)
        assert facts == ["свой факт А"]
        assert tele["own"] == 1
        assert tele["exhausted"] is True
        assert tele["partial"] is False

    @pytest.mark.asyncio
    async def test_overfetch_cap_marks_partial_not_silent(self, db, monkeypatch):
        """Чужих больше cap: результат частичный и ПОМЕЧЕН (tele.partial +
        WARNING), не пустой молча (§18F.4). 7 чужих ближе cap'а, свой факт
        добирается 8-м — неполный (1 из 2), но не пустой и не тихий."""
        monkeypatch.setattr("services.summary_memory._KNN_SCOPE_K_CAP", 8)
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        await _seed_archive(
            db, memory,
            [(CHAT_A, "свой факт про дроны", _mix(0.98, 0.2))]          # dist 0.02
            + [(CHAT_B, f"чужой точный факт #{i}", _unit(0)) for i in range(7)]
            + [(CHAT_B, f"чужой дальний факт #{i}", _unit(1)) for i in range(5)])

        facts, tele = await memory._search_archive_knn_scoped(
            CHAT_A, _unit(0), 2)
        assert facts == ["свой факт про дроны"]    # частичный, НЕ пустой
        assert tele["partial"] is True
        assert tele["own"] == 1
        assert tele["want"] == 2
        assert tele["exhausted"] is False
        assert tele["attempts"] == 1               # k_first ужат cap'ом (8)
        assert tele["filtered_other_chat"] == 7    # чужие рядом, добора нет

    @pytest.mark.asyncio
    async def test_staged_refill_recovers_own_facts(self, db, monkeypatch):
        """Стадийный добор (attempts > 1): чужие заполнили k_first, но индекс
        НЕ исчерпан → k растёт ×4, свои факты добираются; overfetch_used=True
        (телеметрия добора)."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        await _seed_archive(
            db, memory,
            [(CHAT_A, f"свой факт #{i}", _mix(0.98, 0.2)) for i in range(2)]
            + [(CHAT_B, f"чужой факт #{i}", _unit(0)) for i in range(12)])

        facts, tele = await memory._search_archive_knn_scoped(
            CHAT_A, _unit(0), 2)
        assert set(facts) == {"свой факт #0", "свой факт #1"}
        assert tele["attempts"] == 2               # 8 → 32 (индекс исчерпан)
        assert tele["overfetch_used"] is True
        assert tele["exhausted"] is True           # дочитали до конца — честно
        assert tele["partial"] is False


# ── Dedup: chat-scope до top-K ───────────────────────────────────────────────


class TestDedupKnnIsolation:
    @pytest.mark.asyncio
    async def test_foreign_candidates_cannot_hide_own_duplicate(
            self, db, monkeypatch):
        """§9A.3 dedup: 3 чужих кандидата ближе реального дубликата своего
        чата. Старый k=3 ГЛОБАЛЬНО возвращал только чужих → дубликат
        пропускался; теперь добор до 3 СВОИХ живых кандидатов."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        now = int(time.time())
        a_id = await db.insert_graph_fact(
            CHAT_A, "озон поставляет быстрее чем wildberries", "search_fact",
            now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
        b_ids = []
        for i in range(3):
            b_ids.append(await db.insert_graph_fact(
                CHAT_B, f"сосед доставляет быстрее чем amazon #{i}",
                "search_fact", now + 1000,
                weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE))
        # чужие СТРОГО ближе (distance 0) своего дубликата (distance 0.04)
        for fid in b_ids:
            await _seed_graph_vec(memory, fid, CHAT_B, _unit(0), now + 1000)
        await _seed_graph_vec(memory, a_id, CHAT_A, _mix(0.96, 0.28), now + 1000)

        rows = await memory._dedup_knn(CHAT_A, _unit(0))
        assert [r["fact_id"] for r in rows] == [a_id]   # чужие не проникли
        assert all(r["chat_id"] == CHAT_A for r in rows)

    @pytest.mark.asyncio
    async def test_no_foreign_leak_when_own_absent(self, db, monkeypatch):
        """Чужие кандидаты не возвращаются никогда (в т.ч. когда своих нет)."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        now = int(time.time())
        for i in range(4):
            b_id = await db.insert_graph_fact(
                CHAT_B, f"факт чужого чата #{i}", "search_fact", now + 1000,
                weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
            await _seed_graph_vec(memory, b_id, CHAT_B, _unit(0), now + 1000)

        rows = await memory._dedup_knn(CHAT_A, _unit(0))
        assert rows == []

    @pytest.mark.asyncio
    async def test_expired_own_excluded_no_foreign_substitute(
            self, db, monkeypatch):
        """TTL-liveness сохранён: просроченный свой не кандидат; чужой живой
        НЕ подставляется вместо него (было возможно при k=3 глобально)."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        now = int(time.time())
        a_id = await db.insert_graph_fact(
            CHAT_A, "устаревший факт своего чата", "search_fact",
            now - 10, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
        b_id = await db.insert_graph_fact(
            CHAT_B, "живой факт чужого чата", "search_fact", now + 1000,
            weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
        await _seed_graph_vec(memory, a_id, CHAT_A, _unit(0), now - 10)
        await _seed_graph_vec(memory, b_id, CHAT_B, _unit(0), now + 1000)

        rows = await memory._dedup_knn(CHAT_A, _unit(0))
        assert rows == []

    @pytest.mark.asyncio
    async def test_decision_foreign_crowd_no_longer_misses_duplicate(
            self, db, monkeypatch):
        """Интеграция _dedup_decide + реальный _dedup_knn: чужая толпа ближе
        реального дубликата своего чата. Старый код: near=3 чужих → пара
        сущностей не совпала → add (дубликат ПРОПУЩЕН). Теперь: свой дубликат
        найден → noop (cosine 0.96 ≥ HIGH 0.95)."""
        memory = await _init_memory(db, VecLLM(), monkeypatch, int8=False)
        memory._vec_available = True
        now = int(time.time())
        a_id = await db.insert_graph_fact(
            CHAT_A, "озон поставляет быстрее чем wildberries", "search_fact",
            now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
        b_ids = []
        for i in range(3):
            b_ids.append(await db.insert_graph_fact(
                CHAT_B, f"сосед доставляет быстрее чем amazon #{i}",
                "search_fact", now + 1000,
                weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE))
        for fid in b_ids:
            await _seed_graph_vec(memory, fid, CHAT_B, _unit(0), now + 1000)
        # cosine(дубль-кандидат, запрос) = 0.96 ≥ GRAPH_DEDUP_SIMILARITY_HIGH
        await _seed_graph_vec(memory, a_id, CHAT_A, _mix(0.96, 0.28), now + 1000)

        decision = await memory._dedup_decide(
            CHAT_A,
            {"subject": "озон", "predicate": "поставляет",
             "object": "wildberries"},
            "озон поставляет быстрее чем wildberries — контекст",
            _unit(0))
        assert decision == {"action": "noop", "old_id": a_id,
                            "old_text": "озон поставляет быстрее чем wildberries"}
