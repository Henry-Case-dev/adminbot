"""P0-HA RELEVANCE (source-2026-10-29.md §9-§11) — важность ≠ релевантность.

Покрытие (карта: REQ-HA-NO-SELF-AMPLIFY / REQ-HA-KEEP-PROVENANCE-SELFECHO /
REQ-HA-IMPORTANCE-VS-RELEVANCE / REQ-HA-P06-NO-MEMORY-DELETIONS /
REQ-HA-P07-NO-GLOBAL-OFF / REQ-HA-P08-NO-TOPIC-EXCEPTIONS):

  H23: собственные пересказы бота не усиливают значимость события — факты с
       provenance «порождены выходом бота» (origin bot_self_reply /
       bot_direct_reply) НЕ получают touch-продление TTL от RAG-хитов
       («используется — живёт»); пользовательские origin живут как раньше;
  §10/§11: повторные подачи того же факта в ответы затухают — bounded-штраф
       релевантности (не удаление, не обнуление);
  H24: явный запрос о старом событии находит долговременную память несмотря
       на штраф; GraphRAG/Lore не выключаются, память не удаляется;
  §11: высокая историческая важность без смысловой связи с запросом не
       включает событие в ответ;
  H29/H30: поведение одинаково для любых синтетических тем при равных
       условиях; в модуле ранжирования нет литералов тем/имён (grep-
       проверка источника + provenance-набор origin);

Все темы/имена в тесте — синтетические; никаких живых чатов.
"""
import asyncio
import time

import pytest

from services import hot_config as hot
from services.database import DatabaseService
from services.summary_memory import (
    _BOT_GENERATED_ORIGINS,
    MemoryManager,
    _RAG_USAGE_PENALTY_CAP,
    _RAG_USAGE_WINDOW_SEC,
)

CHAT_ID = -100

# Синтетические темы (не существуют в реальном мире; только этот тест).
_TOPIC_A = "кузнечиково"
_TOPIC_B = "синегорье"
_TOPIC_C = "верблюжатник"


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
    async def generate(self, messages, temperature=None):
        raise AssertionError("relevance tests must not call LLM")


def _base_flags() -> dict:
    """Детерминированная база: RAG включён (P07: глобально НЕ выключается),
    декай/воскрешение/MMR off (чистая проверка ранга), touch — по тесту."""
    return {
        "flags.graph_rag_enabled": True,
        "flags.graph_time_decay_enabled": False,
        "flags.belief_decay_enabled": False,
        "flags.graph_mmr_enabled": False,
        "flags.memory_archive_retrieval": False,
        "flags.bot_self_awareness_enabled": True,
    }


async def _add_fact(db, text, *, origin="chat_history", importance=4,
                    weight=0.5, kind="fact", status="confirmed") -> int:
    fid = await db.insert_graph_fact(
        CHAT_ID, text, origin, None, weight=weight, importance=importance,
        kind=kind, status=status)
    return fid


def _fact_ids(facts) -> list[int]:
    """fact-id из выдачи get_rag_facts (item_id «fact:<id>»)."""
    ids = []
    for f in facts:
        item_id = str(f[4] or "") if isinstance(f, (tuple, list)) else ""
        if item_id.startswith("fact:"):
            ids.append(int(item_id[5:]))
    return ids


# ── H23: собственные пересказы бота не продлевают TTL (§10) ────────────────

class TestSelfAmplify:
    @pytest.mark.asyncio
    async def test_touch_skips_bot_generated_origins(self, db, monkeypatch):
        """H23: touch («используется — живёт») от RAG-хитов не продлевает TTL
        фактов с provenance «порождены ботом»; пользовательские — продлевает
        как раньше (существующий механизм сохранён)."""
        _hot_cache(monkeypatch, {
            **_base_flags(),
            "flags.graph_fact_touch_enabled": True,
        })
        user_fid = await _add_fact(db, f"обсуждение {_TOPIC_A} длилось всю ночь")
        bot_reply_fid = await _add_fact(
            db, f"экскурсия в {_TOPIC_A} обсуждалась",
            origin="bot_direct_reply")
        self_fid = await _add_fact(
            db, f"я рассказывал про {_TOPIC_A}",
            origin="bot_self_reply")
        memory = MemoryManager(db, _FakeLLM())
        touched: list[int] = []
        orig_touch = memory.db.touch_graph_facts

        async def _spy_touch(ids, *a, **k):
            touched.extend(int(i) for i in ids)
            return await orig_touch(ids, *a, **k)

        monkeypatch.setattr(memory.db, "touch_graph_facts", _spy_touch)
        facts = await memory.get_rag_facts(
            CHAT_ID, _TOPIC_A, include_direct_reply=True, include_self=True)
        # Все три факта видимы direct-пути (provenance/ingest не тронуты).
        texts = {f[1] for f in facts}
        assert len(facts) == 3
        assert any(_TOPIC_A in t for t in texts)
        # TTL-продление получил ТОЛЬКО пользовательский факт.
        assert user_fid in touched
        assert bot_reply_fid not in touched
        assert self_fid not in touched

    @pytest.mark.asyncio
    async def test_knn_touch_skips_bot_generated_origins(
            self, db, monkeypatch):
        """H23 (KNN-путь): то же правило provenance на векторном пути."""
        _hot_cache(monkeypatch, {
            **_base_flags(),
            "flags.graph_fact_touch_enabled": True,
        })
        user_fid = await _add_fact(db, f"тема {_TOPIC_B} из старых планов")
        bot_fid = await _add_fact(
            db, f"продолжение темы {_TOPIC_B}", origin="bot_direct_reply")
        memory = MemoryManager(db, _FakeLLM())

        async def _candidates(chat_id, vector, fetch_k, *a, **kw):
            return [(user_fid, 0.9, None), (bot_fid, 0.8, None)]

        monkeypatch.setattr(memory, "_vec_candidates", _candidates)
        touched: list[int] = []
        orig_touch = memory.db.touch_graph_facts

        async def _spy_touch(ids, *a, **k):
            touched.extend(int(i) for i in ids)
            return await orig_touch(ids, *a, **k)

        monkeypatch.setattr(memory.db, "touch_graph_facts", _spy_touch)
        rows = await memory._knn_graph_facts(
            CHAT_ID, [0.1, 0.0], 5, include_direct_reply=True)
        assert len(rows) == 2
        assert user_fid in touched
        assert bot_fid not in touched

    @pytest.mark.asyncio
    async def test_bot_generated_origin_set_is_provenance_only(self):
        """Provenance-механизм: набор состоит ТОЛЬКО из origin-меток бота,
        без тем/имён/исключений (H29/H30)."""
        assert _BOT_GENERATED_ORIGINS == {"bot_self_reply", "bot_direct_reply"}
        for entry in _BOT_GENERATED_ORIGINS:
            assert entry.startswith("bot_")


# ── §10/§11: повторные подачи затухают (bounded) ────────────────────────────

class TestRepeatDampening:
    @pytest.mark.asyncio
    async def test_repeated_delivery_dampens_ranking_knn(
            self, db, monkeypatch):
        """Факт, многократно подававшийся в ответы, теряет верх релевантности
        против равного по смысловому совпадению факта (штраф ограничен)."""
        _hot_cache(monkeypatch, _base_flags())
        fid_a = await _add_fact(db, f"поездка в {_TOPIC_A} весной")
        fid_b = await _add_fact(db, f"поездка в {_TOPIC_A} осенью")
        memory = MemoryManager(db, _FakeLLM())

        async def _candidates(chat_id, vector, fetch_k, *a, **kw):
            return [(fid_a, 0.9, None), (fid_b, 0.88, None)]

        monkeypatch.setattr(memory, "_vec_candidates", _candidates)
        rows = await memory._knn_graph_facts(CHAT_ID, [0.1], 5)
        assert _fact_ids(rows) == [fid_a, fid_b]  # сильнее совпадение — выше

        # Симуляция «бот пять раз пересказал»: факты подавались в ответы.
        now = int(time.time())
        memory._mark_rag_usage(CHAT_ID, [fid_a] * 5, now)
        rows2 = await memory._knn_graph_facts(CHAT_ID, [0.1], 5)
        assert _fact_ids(rows2)[0] == fid_b             # затухание: b выше
        assert {r for r in _fact_ids(rows2)} == {fid_a, fid_b}  # удалений нет (P06)

    @pytest.mark.asyncio
    async def test_penalty_is_bounded_not_zeroing(self, db, monkeypatch):
        """Штраф ограничен потолком даже при десятках подач; факт остаётся
        в выдаче при сильном смысловом совпадении (не обнуление, H24)."""
        _hot_cache(monkeypatch, _base_flags())
        fid = await _add_fact(db, f"{_TOPIC_C} и старый договор")
        competitor = await _add_fact(db, f"новости про {_TOPIC_C}")
        memory = MemoryManager(db, _FakeLLM())
        memory._mark_rag_usage(CHAT_ID, [fid] * 50, int(time.time()))
        penalty = memory._rag_usage_penalty(CHAT_ID, fid, int(time.time()))
        assert 0.0 < penalty <= _RAG_USAGE_PENALTY_CAP

        async def _candidates(chat_id, vector, fetch_k, *a, **kw):
            return [(fid, 0.98, None), (competitor, 0.5, None)]

        monkeypatch.setattr(memory, "_vec_candidates", _candidates)
        rows = await memory._knn_graph_facts(CHAT_ID, [0.1], 5)
        ids = set(_fact_ids(rows))
        assert fid in ids and competitor in ids         # оба находимы

    @pytest.mark.asyncio
    async def test_penalty_resets_after_silence_window(self, db):
        """Молчание дольше окна → штраф 0 (затухание обратимо, память не
        помечается навсегда)."""
        memory = MemoryManager(db, _FakeLLM())
        now = int(time.time())
        memory._mark_rag_usage(CHAT_ID, [7] * 10, now)
        assert memory._rag_usage_penalty(CHAT_ID, 7, now) > 0.0
        stale = now + _RAG_USAGE_WINDOW_SEC + 1
        assert memory._rag_usage_penalty(CHAT_ID, 7, stale) == 0.0

    @pytest.mark.asyncio
    async def test_direct_path_marks_usage_tool_path_does_not(
            self, db, monkeypatch):
        """Учёт подач ведёт ТОЛЬКО direct-путь (include_self=True — уникальный
        признак ambient-инжекта); явные tool-запросы не штрафуются."""
        _hot_cache(monkeypatch, _base_flags())
        await _add_fact(db, f"факт про {_TOPIC_A}")
        memory = MemoryManager(db, _FakeLLM())
        await memory.get_rag_facts(CHAT_ID, _TOPIC_A)
        assert memory._rag_usage.get(CHAT_ID) in (None, {})
        await memory.get_rag_facts(
            CHAT_ID, _TOPIC_A, include_direct_reply=True, include_self=True)
        per_chat = memory._rag_usage.get(CHAT_ID)
        assert per_chat and sum(e[0] for e in per_chat.values()) >= 1

    @pytest.mark.asyncio
    async def test_usage_cache_is_bounded(self, db):
        """Process-local кэш ограничен (вытеснение, без роста без предела)."""
        from services.summary_memory import (
            _RAG_USAGE_MAX_CHATS,
            _RAG_USAGE_MAX_PER_CHAT,
        )
        memory = MemoryManager(db, _FakeLLM())
        now = int(time.time())
        memory._mark_rag_usage(CHAT_ID, list(range(2000)), now)
        assert len(memory._rag_usage[CHAT_ID]) <= _RAG_USAGE_MAX_PER_CHAT
        for chat in range(_RAG_USAGE_MAX_CHATS + 10):
            memory._mark_rag_usage(-500 - chat, [1], now)
        assert len(memory._rag_usage) <= _RAG_USAGE_MAX_CHATS


# ── H24: явный запрос находит старое; память не удаляется ──────────────────

class TestExplicitAskStillFinds:
    @pytest.mark.asyncio
    async def test_explicit_query_finds_dampened_memory(self, db,
                                                        monkeypatch):
        """H24: после многих подач явный вопрос о старой теме находит
        долговременный факт (FTS-путь, штраф не обнуляет выборку)."""
        _hot_cache(monkeypatch, _base_flags())
        fid = await _add_fact(db, f"{_TOPIC_B} помнили и обсуждали")
        memory = MemoryManager(db, _FakeLLM())
        memory._mark_rag_usage(CHAT_ID, [fid] * 6, int(time.time()))
        facts = await memory.get_rag_facts(
            CHAT_ID, f"что было в {_TOPIC_B}?",
            include_direct_reply=True, include_self=True)
        assert fid in _fact_ids(facts)

    @pytest.mark.asyncio
    async def test_no_memory_deleted_by_repeated_use(self, db, monkeypatch):
        """P06: повторные подачи НЕ удаляют и не скрывают память: строки
        graph_facts живы и находятся прямым FTS."""
        _hot_cache(monkeypatch, _base_flags())
        fid = await _add_fact(db, f"{_TOPIC_A} старая запись")
        memory = MemoryManager(db, _FakeLLM())
        memory._mark_rag_usage(CHAT_ID, [fid] * 30, int(time.time()))
        rows = await db.search_graph_facts_fts(
            CHAT_ID, _TOPIC_A, 10, int(time.time()))
        assert fid in [r["id"] for r in rows]


# ── §11: важность ≠ включение в любой ответ ────────────────────────────────

class TestImportanceVsRelevance:
    @pytest.mark.asyncio
    async def test_high_importance_without_semantic_link_not_included(
            self, db, monkeypatch):
        """Очень важный старый факт (importance 10) по теме A НЕ входит в
        ответ на запрос по несвязанной теме B; по запросу о теме A — входит
        (важность не подменяет релевантность, H29/H30-симметрия)."""
        _hot_cache(monkeypatch, _base_flags())
        await _add_fact(db, f"{_TOPIC_A} великое событие прошлого",
                        importance=10, weight=1.0)
        await _add_fact(db, f"{_TOPIC_B} обычная запись", importance=4,
                        weight=0.5)
        memory = MemoryManager(db, _FakeLLM())
        facts_b = await memory.get_rag_facts(
            CHAT_ID, _TOPIC_B, include_direct_reply=True, include_self=True)
        assert facts_b and all(
            _TOPIC_A not in str(f[1]) for f in facts_b)
        facts_a = await memory.get_rag_facts(
            CHAT_ID, _TOPIC_A, include_direct_reply=True, include_self=True)
        assert facts_a and any(_TOPIC_A in str(f[1]) for f in facts_a)


# ── §9: граф-активация — повторные инжекты затухают ────────────────────────

class TestGraphActivationDampening:
    async def _l1_with_pair(self, db):
        now = int(time.time())
        for i in range(3):
            await db.save_smart_message(
                1, CHAT_ID, f"марево и засургуч снова вместе {i + 1}",
                None, now - (10 - i), "text", "юзер")
        await db.upsert_node(CHAT_ID, "Марево", "user")
        await db.upsert_node(CHAT_ID, "Засургуч", "user")

    @pytest.mark.asyncio
    async def test_repeated_activation_rotates_belief_out(self, db,
                                                          monkeypatch):
        """Belief, многократно инжектировавшийся активацией, уступает слот
        равному по связи соседу; сам остаётся в памяти и находим по явному
        запросу (H24)."""
        _hot_cache(monkeypatch, {
            **_base_flags(),
            "flags.belief_decay_enabled": True,
        })
        await self._l1_with_pair(db)
        bid_old = await db.insert_graph_fact(
            CHAT_ID, "марево и засургуч закрепились давно",
            "derived_belief", None, weight=0.2, importance=5, kind="belief",
            status="archived_belief",
            belief_meta='{"base_weight":0.6,"decay_months":0}')
        bid_other = await db.insert_graph_fact(
            CHAT_ID, "марево и засургуч другой эпизод",
            "derived_belief", None, weight=0.2, importance=5, kind="belief",
            status="archived_belief",
            belief_meta='{"base_weight":0.6,"decay_months":0}')
        memory = MemoryManager(db, _FakeLLM())
        first = await memory.graph_activation_facts(CHAT_ID, limit=1)
        # Пустой учёт → прежний порядок id DESC: свежий belief первым.
        assert first and first[0][1] == "марево и засургуч другой эпизод"

        # Симуляция навязчивых повторных инжектов того же belief.
        now = int(time.time())
        memory._mark_rag_usage(CHAT_ID, [bid_other] * 6, now)
        second = await memory.graph_activation_facts(CHAT_ID, limit=1)
        # Затухание: повторно использованный belief уступает слот соседу.
        assert second[0][1] == "марево и засургуч закрепились давно"
        # Память жива, записи не удалялись.
        rows = await db.search_graph_facts_fts(
            CHAT_ID, "марево", 10, now, include_archived=True)
        assert {bid_old, bid_other} <= {r["id"] for r in rows}


# ── H29/H30: симметрия тем + отсутствие литералов в новой логике ───────────

class TestNoTopicHardcodes:
    @pytest.mark.asyncio
    async def test_two_synthetic_topics_treated_identically(
            self, db, monkeypatch):
        """Равные условия для двух синтетических тем → одинаковый штраф и
        одинаковый порядок (никаких особых исключений)."""
        _hot_cache(monkeypatch, _base_flags())
        fid_a = await _add_fact(db, f"{_TOPIC_A} первая тема")
        fid_b = await _add_fact(db, f"{_TOPIC_B} вторая тема")
        memory = MemoryManager(db, _FakeLLM())
        now = int(time.time())
        memory._mark_rag_usage(CHAT_ID, [fid_a] * 4, now)
        memory._mark_rag_usage(CHAT_ID, [fid_b] * 4, now)
        assert (memory._rag_usage_penalty(CHAT_ID, fid_a, now)
                == memory._rag_usage_penalty(CHAT_ID, fid_b, now))
        rank_a = await memory.get_rag_facts(
            CHAT_ID, f"напомни {_TOPIC_A}",
            include_direct_reply=True, include_self=True)
        rank_b = await memory.get_rag_facts(
            CHAT_ID, f"напомни {_TOPIC_B}",
            include_direct_reply=True, include_self=True)
        assert len(rank_a) == len(rank_b)
        assert fid_a in _fact_ids(rank_a)
        assert fid_b in _fact_ids(rank_b)

    def test_ranking_module_has_no_topic_or_name_literals(self):
        """Grep-проверка: в модуле ранжирования нет литералов тем/имён из
        тестов и из известной реальной темы (без нового хардкода)."""
        with open("services/summary_memory.py", encoding="utf-8") as fh:
            source = fh.read().casefold()
        for literal in (_TOPIC_A, _TOPIC_B, _TOPIC_C,
                        "марево", "засургуч", "внуково"):
            assert literal.casefold() not in source
