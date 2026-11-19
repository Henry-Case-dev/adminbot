"""VMQ-MEM — три дефекта retrieval, доказанные измерением 2.58.179 на реальном
архиве чата (2 067 222 сообщения, 2022-12-07 … 2026-11-10).

Источник: plans/features/vmq-onto-01/evidence/vmq-mem/measurement-2.58.179.md
§2-§5. Покрытие (CONTRACT/REGRESSION), всё — на настоящем SQLite (in-memory) и
настоящих путях кода (`mca_retrieval_context.retrieve`,
`DirectChatService._build_old_episodes`, `DatabaseService.search_messages_fts`),
без второго retrieval-движка и без подмены тестируемого механизма моком:

(a) `<Old_Episode>` был ПУСТ во всех пяти формулировках: срез истории 8/8
    занимали эпизоды (`history_bias` — первый ключ сортировки), хотя
    `message`-хиты имели score 79-80 против 25 у эпизода, а потребитель берёт
    только `entity_type="message"`;
(b) 6 из 7 дошедших до среза message-кандидатов отбрасывались как
    «tg id unresolved»: их ссылка — `msg:<smart_messages.id>` (импорт истории
    без tg-id), а потребитель понимал только `tg:<tg_message_id>`;
(c) `dig_into_lore(year=…)` не завершался: оконный FTS-запрос шёл rank-планом,
    который читает строку контента для КАЖДОГО совпадения корпуса.
"""
import asyncio
import datetime as _dt
import json
import time
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import direct_context_composer as _composer
from services import direct_chat_service as dcs
from services import mca_gates
from services import mca_retrieval_context as rc
from services.database import DatabaseService
from services.direct_chat_service import (
    DirectChatService,
    _episode_anchor_of_fact_row,
    _episode_anchor_of_ref,
)
from services.summary_aliases import AliasResolver
from services.summary_memory import MemoryManager
from services.tool_router import ToolContext, ToolDeps, ToolRouter

# Тот же чат, что в измерении (реальный архив 5 лет).
CHAT_ID = -1002661910336


# ── fixtures/helpers ──────────────────────────────────────────────────────


class _NoMemory:
    """Минимальный memory-стаб: векторный канал пуст, второго поиска нет."""

    async def retrieve_fact_candidates(self, *a, **k):
        return []


def _ts(year: int, month: int = 6, day: int = 1, hour: int = 12) -> int:
    return int(_dt.datetime(year, month, day, hour,
                            tzinfo=_dt.timezone.utc).timestamp())


def _fmt(ts: int) -> str:
    """Дата в канонической строке контекста (`%d.%m.%Y`)."""
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%d.%m.%Y")


async def _make_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _seed_message(db, text: str, ts: int, *, uid: int = 111,
                        author: str = "Лёха", tg_id: int | None = None) -> int:
    """Строка корпуса; ``tg_id=None`` → импорт истории без tg-id
    (ID-политика отдаёт её как ``msg:<row>``)."""
    return await db.save_smart_message(uid, CHAT_ID, text, None, ts, "text",
                                       author, message_id=tg_id)


async def _seed_episodes(db, count: int, topic: str, *, year: int = 2023) -> None:
    for i in range(count):
        await db.upsert_lore_story(
            CHAT_ID, f"дроны-{i}", topic, f"рассказ {i}", _ts(year, 3, 1))


def _service(db, memory=None) -> DirectChatService:
    router = ToolRouter(ToolDeps(search=MagicMock(),
                                 memory=memory or _NoMemory(),
                                 aliases=None, db=db))
    return DirectChatService(memory or _NoMemory(), db, MagicMock(),
                             AliasResolver("{}"), tool_router=router)


@pytest.fixture
def legacy_episode_store(monkeypatch):
    """Эпизоды читаются legacy-путём `lore_stories` (фасад mca_episodes пуст
    в свежей БД; обе ветки — production-реальные, гейт лишь выбирает стор)."""
    monkeypatch.setattr(mca_gates, "retrieval_context_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "episodes_compiler_facade_enabled",
                        lambda: False)


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


# ── (a) дефект 1: эпизоды больше не занимают срез целиком ─────────────────


class TestHistoryPoolFairness:
    @pytest.mark.asyncio
    async def test_episode_heavy_pool_keeps_verbatim_messages(
            self, db, legacy_episode_store):
        """Измерение §5 п.1-2: 8/8 слотов эпизодами при пуле, где сообщения
        сильнее по рангу. Срез обязан сохранить эпизоды-первыми, но не отдать
        их каналу целиком."""
        await _seed_episodes(db, 12, "дроны и полёты")
        for i in range(6):
            await _seed_message(db, f"дроны над городом раз{i}",
                                _ts(2023, 5, 1 + i), tg_id=5000 + i)

        result = await rc.retrieve(
            db, None, rc.RetrievalRequest(
                chat_id=CHAT_ID, query="расскажи историю про дроны",
                mode="history", top_k=8, reply_depth=0))

        episodes = [c for c in result.candidates if c.entity_type == "episode"]
        messages = [c for c in result.candidates if c.entity_type == "message"]
        assert result.candidates[0].entity_type == "episode"   # эпизоды первыми
        assert len(result.candidates) == 8
        assert len(episodes) <= 8 // 2, (
            f"эпизоды заняли {len(episodes)}/8 слотов — starvation (дефект 1)")
        assert messages, "message-хиты вытеснены эпизодами (дефект 1)"
        assert result.reason_code == "episodes_used"

    @pytest.mark.asyncio
    async def test_episodes_still_usable_when_no_other_channel(
            self, db, legacy_episode_store):
        """Регрессия: эпизоды остаются материалом там, где других кандидатов
        нет (эпизоды-первыми ADR-1027-7 D2 не отменяются)."""
        await _seed_episodes(db, 3, "дроны и полёты")
        result = await rc.retrieve(
            db, None, rc.RetrievalRequest(
                chat_id=CHAT_ID, query="дроны", mode="history", top_k=8,
                reply_depth=0))
        assert result.candidates
        assert all(c.entity_type == "episode" for c in result.candidates)
        assert result.reason_code == "episodes_used"


# ── (a) на потребителе: `<Old_Episode>` непуст / честно пуст ──────────────


class TestOldEpisodeBlock:
    @pytest.mark.asyncio
    async def test_block_non_empty_for_chat_with_relevant_old_messages(
            self, db, legacy_episode_store):
        """Измерение §3: пять классов дали 8/8 эпизодов → блок пуст. После
        фикса у чата с релевантными старыми сообщениями блок НЕ пуст."""
        await _seed_episodes(db, 12, "дроны и полёты")
        await _seed_message(db, "дроны тогда летали над дачей",
                            _ts(2022, 7, 3), tg_id=7001)
        await _seed_message(db, "спорили про дроны и рыбалку",
                            _ts(2022, 7, 3, 13), tg_id=7002)

        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "расскажи историю про дроны", [], {})

        assert block.startswith("<Old_Episode>") and block.endswith(
            "</Old_Episode>")
        assert "дроны тогда летали над дачей" in block
        assert stats["count"] >= 1 and stats["messages"] >= 1
        assert _composer.direct_metrics_snapshot()[
            "direct_old_episode_empty_total"] >= 0     # счётчик существует

    @pytest.mark.asyncio
    async def test_block_honestly_empty_when_nothing_matches(
            self, db, legacy_episode_store):
        """Обратная сторона: нет релевантного материала — блок пуст честно
        (ничего не выдумывается), пустой счётчик не растёт."""
        before = _composer.direct_metrics_snapshot().get(
            "direct_old_episode_empty_total", 0)
        await _seed_episodes(db, 12, "дроны и полёты")
        await _seed_message(db, "дроны тогда летали над дачей",
                            _ts(2022, 7, 3), tg_id=7001)

        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "квазар", [], {})

        assert block == ""
        assert stats["count"] == 0
        after = _composer.direct_metrics_snapshot().get(
            "direct_old_episode_empty_total", 0)
        assert after == before, "пустой ПУЛ не должен считаться «блок пуст»"


# ── TIME-03 episode-r2: vector message-anchor leg for S3/S4 ──────────────


class _EpisodeResult:
    def __init__(self, candidates, fact_rows=()):
        self.candidates = tuple(candidates)
        self.fact_rows = tuple(fact_rows)


class _EpisodeCandidate:
    def __init__(self, cid, entity_type, channel, preview):
        self.id = cid
        self.entity_type = entity_type
        self.channel = channel
        self.preview = preview
        self.sent_at = 0


class TestEpisodeFactRowAnchor:
    """TIME-03 r4: ``fact:<id>`` → source message via the existing fact row."""

    def test_fact_row_anchor_forms(self):
        assert _episode_anchor_of_fact_row(
            {"item_id": "msg:42"}) == (None, 42)
        assert _episode_anchor_of_fact_row(
            {"item_id": "tg:77"}) == (77, None)
        assert _episode_anchor_of_fact_row(
            {"tg_message_id": 9001}) == (9001, None)
        assert _episode_anchor_of_fact_row(
            {"item_id": "fact:5"}) == (None, None)
        assert _episode_anchor_of_fact_row(None) == (None, None)

    @pytest.mark.asyncio
    async def test_imported_source_row_becomes_msg_anchor(
            self, db, legacy_episode_store, monkeypatch):
        row_id = await _seed_message(
            db, "работа и зарплата без tg-id", _ts(2026, 8, 1, 10))
        await _seed_message(
            db, "обсуждали зарплату и работу", _ts(2026, 8, 1, 10) + 120,
            uid=222, author="U222")

        graph = _EpisodeCandidate("fact:77", "graph_fact", "lexical", "")
        graph.entity_id = "77"
        fact_rows = [{"id": 77, "item_id": f"msg:{row_id}",
                      "tg_message_id": None, "weight": 0.8, "importance": 8,
                      "fact": "работа и зарплата без tg-id"}]

        async def fake(_db, _memory, request):
            return _EpisodeResult([graph], fact_rows=fact_rows)

        monkeypatch.setattr(rc, "retrieve", fake)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "что сейчас с работой и зарплатой?", [], {})
        assert block
        assert f"msg:{row_id}" in block, block
        assert stats["spans"]

    @pytest.mark.asyncio
    async def test_fact_row_anchor_recovery_is_load_bearing(
            self, db, legacy_episode_store, monkeypatch):
        await _seed_message(db, "работа и зарплата в 2026",
                            _ts(2026, 8, 1, 10), tg_id=9001)
        graph = _EpisodeCandidate("fact:77", "graph_fact", "lexical", "")
        graph.entity_id = "77"
        fact_rows = [{"id": 77, "item_id": "fact:77", "tg_message_id": 9001,
                      "weight": 0.9, "importance": 9,
                      "fact": "работа и зарплата в 2026"}]

        async def fake(_db, _memory, request):
            return _EpisodeResult([graph], fact_rows=fact_rows)

        monkeypatch.setattr(rc, "retrieve", fake)
        # Ablation: without the fact-row source-message conversion the
        # lexical `fact:` candidate is discarded again.
        monkeypatch.setattr(dcs, "_episode_anchor_of_fact_row",
                            lambda _row: (None, None))
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "что сейчас с работой и зарплатой?", [], {})
        assert block == ""
        assert stats["anchor_candidates"] == 0

    @pytest.mark.asyncio
    async def test_graph_fact_below_two_stems_is_not_anchored(
            self, db, legacy_episode_store, monkeypatch):
        await _seed_message(db, "работа и зарплата в 2026",
                            _ts(2026, 8, 1, 10), tg_id=9001)
        graph = _EpisodeCandidate("fact:77", "graph_fact", "lexical",
                                  "работа")
        graph.entity_id = "77"
        fact_rows = [{"id": 77, "item_id": "tg:9001", "tg_message_id": 9001,
                      "weight": 0.9, "importance": 9, "fact": "работа"}]

        async def fake(_db, _memory, request):
            return _EpisodeResult([graph], fact_rows=fact_rows)

        monkeypatch.setattr(rc, "retrieve", fake)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "работа и зарплата", [], {})
        assert block == ""
        assert stats["anchor_candidates"] == 0


class TestR4MultiAnchor:
    """TIME-03 r4: a second similar 2022 episode and multi-year anchors."""

    @pytest.mark.asyncio
    async def test_second_similar_2022_anchor_is_delivered(
            self, db, legacy_episode_store):
        for index, (text, day) in enumerate((
                ("та самая история с синей кружкой на кухне", 4),
                ("синей кружкой разбили чашку", 4),
                ("потом все смеялись над кружкой", 4),
                ("ещё одна история про синюю кружку", 18),
                ("синяя кружка треснула у раковины", 18),
                ("кружку склеили и оставили", 18))):
            await _seed_message(
                db, text, _ts(2022, 3, day, 11) + (index % 3) * 120,
                tg_id=7300 + int(day) + index)
        for index, text in enumerate((
                "похожий случай с посудой на кухне",
                "красная посуда разбилась")):
            await _seed_message(
                db, text, _ts(2025, 8, 9, 12) + index * 120,
                uid=222, author="Аня", tg_id=7400 + index)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, 'та самая история с "синей кружкой"', [], {})
        assert block
        years_2022 = [span for span in stats["spans"]
                      if time.gmtime(span["first_ts"]).tm_year == 2022]
        assert len(years_2022) == 2, stats["spans"]
        assert "синяя кружка треснула" in block, block

    @pytest.mark.asyncio
    async def test_multi_year_anchors_are_all_resolvable(
            self, db, legacy_episode_store, monkeypatch):
        seed = {}
        for year, tg in ((2022, 7501), (2023, 7502), (2024, 7503)):
            await _seed_message(
                db, f"Артём и переезд в {year}", _ts(year, 6, 1),
                tg_id=tg)
            seed[year] = tg
        candidates = [
            _EpisodeCandidate(f"tg:{seed[year]}", "message", "lexical",
                              f"Артём и переезд в {year}")
            for year in (2022, 2023, 2024)
        ]

        async def fake(_db, _memory, request):
            return _EpisodeResult(candidates)

        monkeypatch.setattr(rc, "retrieve", fake)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "что ты знаешь про Артёма за всё время?", [], {})
        assert block
        # All three year anchors are evidence-backed (person-name match) and
        # the multi-year extension renders all three; the normal 2-episode cap
        # still applies to same-year/similar islands.
        assert stats["anchor_candidates"] == 3, stats
        assert stats["anchor_ranked"] == 3, stats
        assert stats["count"] == 3, stats
        assert {time.gmtime(span["first_ts"]).tm_year
                for span in stats["spans"]} == {2022, 2023, 2024}


class TestR5CrowdingAndMultiYear:
    """R5: current base rows must not crowd old anchors; 3-year evidence."""

    @staticmethod
    async def _seed_old_episodes(db):
        anchors = []
        for year, first_tg in ((2022, 7501), (2023, 7601), (2024, 7701)):
            for index, text in enumerate((
                    f"Артём и переезд в {year}",
                    f"Артём обсуждал переезд в {year}")):
                await _seed_message(
                    db, text, _ts(year, 6, 1, 12) + index * 120,
                    tg_id=first_tg + index)
            anchors.append(_EpisodeCandidate(
                f"tg:{first_tg}", "message", "lexical",
                f"Артём и переезд в {year}"))
        return anchors

    @staticmethod
    async def _seed_current_base(db):
        rows = []
        for index in range(10):
            tg = 9100 + index
            await _seed_message(
                db, f"Артём и переезд, текущий эпизод {index}",
                _ts(2026, 1, 1) + index * 10 * 86400, tg_id=tg)
            rows.append({
                "id": 9000 + index, "item_id": f"tg:{tg}",
                "tg_message_id": tg, "fact": "Артём и переезд в 2026",
                "weight": 0.9, "importance": 9, "status": "confirmed",
                "expires_at": None, "origin": "chat_history",
            })
        return rows

    @pytest.mark.asyncio
    async def test_crowding_regression_keeps_old_anchors(
            self, db, legacy_episode_store, monkeypatch):
        anchors = await self._seed_old_episodes(db)
        base_rows = await self._seed_current_base(db)

        async def fake(_db, _memory, request):
            return _EpisodeResult(anchors)

        monkeypatch.setattr(rc, "retrieve", fake)
        service = _service(db)
        query = "что ты знаешь про Артёма и переезд за всё время?"
        service._rag_last_rows = base_rows
        service._rag_last_rows_key = (CHAT_ID, query)
        block, stats = await service._build_old_episodes(
            CHAT_ID, query, [], {})
        assert block
        # The base/current rows are for a current-state question only; they
        # must not occupy the 8-slot anchor cap here.
        assert stats["anchor_candidates"] == 3, stats
        years = {time.gmtime(span["first_ts"]).tm_year
                 for span in stats["spans"]}
        assert years == {2022, 2023, 2024}, stats["spans"]
        for tg in (7501, 7601, 7701):
            assert f"tg:{tg}" in block, block
        assert "tg:9100" not in block, "current base row leaked into old query"

        # Same base rows ARE appropriate for a current-state question.
        current_query = "что сейчас с Артёмом и переездом?"
        service._rag_last_rows_key = (CHAT_ID, current_query)
        current_block, current_stats = await service._build_old_episodes(
            CHAT_ID, current_query, [], {})
        assert current_block
        assert any(time.gmtime(span["first_ts"]).tm_year == 2026
                   for span in current_stats["spans"]), current_stats["spans"]

    @pytest.mark.asyncio
    async def test_crowding_gate_is_load_bearing(
            self, db, legacy_episode_store, monkeypatch):
        anchors = await self._seed_old_episodes(db)
        base_rows = await self._seed_current_base(db)

        async def fake(_db, _memory, request):
            return _EpisodeResult(anchors)

        monkeypatch.setattr(rc, "retrieve", fake)
        monkeypatch.setattr(dcs, "_is_current_state_query",
                            lambda _query: True)
        service = _service(db)
        query = "что ты знаешь про Артёма и переезд за всё время?"
        service._rag_last_rows = base_rows
        service._rag_last_rows_key = (CHAT_ID, query)
        _block, stats = await service._build_old_episodes(
            CHAT_ID, query, [], {})
        # Mutation witness: with the gate forced open, 13 anchors compete and
        # the old 2022/23/24 spans are crowded out.
        assert stats["anchor_candidates"] == 13, stats
        assert not ({2022, 2023, 2024}
                    <= {time.gmtime(span["first_ts"]).tm_year
                        for span in stats["spans"]}), stats["spans"]

    @pytest.mark.asyncio
    async def test_period_fact_anchor_survives_non_current_gate(
            self, db, legacy_episode_store, monkeypatch):
        await _seed_message(
            db, "Артём и переезд в 2023", _ts(2023, 4, 1, 10),
            tg_id=9301)
        await _seed_message(
            db, "Артём и переезд в 2026", _ts(2026, 4, 1, 10),
            tg_id=9302)
        period_row = {
            "id": 88, "item_id": "tg:9301", "tg_message_id": 9301,
            "fact": "Артём и переезд в 2023", "period_fill": True,
            "weight": 0.6, "importance": 5, "status": "confirmed",
            "origin": "history_import",
        }
        current_row = {
            "id": 89, "item_id": "tg:9302", "tg_message_id": 9302,
            "fact": "Артём и переезд в 2026", "weight": 0.9,
            "importance": 9, "status": "confirmed",
            "origin": "chat_history",
        }

        async def fake(_db, _memory, request):
            return types.SimpleNamespace(candidates=(), fact_rows=())

        monkeypatch.setattr(rc, "retrieve", fake)
        service = _service(db)
        query = "что ты знаешь про Артёма и переезд за всё время?"
        service._rag_last_rows = [period_row, current_row]
        service._rag_last_rows_key = (CHAT_ID, query)
        block, stats = await service._build_old_episodes(
            CHAT_ID, query, [], {})
        assert block
        assert "tg:9301" in block, block
        assert "tg:9302" not in block, block
        assert {time.gmtime(span["first_ts"]).tm_year
                for span in stats["spans"]} == {2023}

    @pytest.mark.asyncio
    async def test_three_complete_multi_year_spans_with_subject(
            self, db, legacy_episode_store, monkeypatch):
        anchors = await self._seed_old_episodes(db)

        async def fake(_db, _memory, request):
            return _EpisodeResult(anchors)

        monkeypatch.setattr(rc, "retrieve", fake)
        service = _service(db)
        block, stats = await service._build_old_episodes(
            CHAT_ID, "что ты знаешь про Артёма и переезд за всё время?",
            [], {})
        assert block
        assert stats["count"] == 3, stats
        assert stats["messages"] == 6, stats
        assert {time.gmtime(span["first_ts"]).tm_year
                for span in stats["spans"]} == {2022, 2023, 2024}
        assert block.count("Артём") == 6, block
        assert all(len(span["source_ids"]) >= 2 for span in stats["spans"])

    @pytest.mark.asyncio
    async def test_multi_year_cap_is_load_bearing(
            self, db, legacy_episode_store, monkeypatch):
        anchors = await self._seed_old_episodes(db)

        async def fake(_db, _memory, request):
            return _EpisodeResult(anchors)

        monkeypatch.setattr(rc, "retrieve", fake)
        service = _service(db)
        service._RAG_EPISODE_MULTI_YEAR_CAP = 2
        _block, stats = await service._build_old_episodes(
            CHAT_ID, "что ты знаешь про Артёма и переезд за всё время?",
            [], {})
        assert stats["count"] == 2, stats
        assert 2024 not in {time.gmtime(span["first_ts"]).tm_year
                            for span in stats["spans"]}


class TestEpisodeVectorMessageLeg:
    @staticmethod
    async def _seed(db):
        # 2026 current window and 2025 older analog: same topic, different years.
        for tg, ts, uid, text in (
                (9001, _ts(2026, 8, 1, 10), 111,
                 "работа и зарплата в 2026"),
                (9002, _ts(2026, 8, 1, 10) + 120, 222,
                 "обсуждали зарплату и работу"),
                (8001, _ts(2025, 8, 1, 10), 111,
                 "работа и зарплата в 2025"),
                (8002, _ts(2025, 8, 1, 10) + 120, 222,
                 "старая зарплата и работа")):
            await _seed_message(db, text, ts, uid=uid, author=f"U{uid}",
                                tg_id=tg)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", (
        pytest.param("как менялось отношение к работе и зарплате?",
                     id="S3_relationship_change"),
        pytest.param("что сейчас с работой и зарплатой?",
                     id="S4_current_state"),
    ))
    async def test_lexical_graph_fact_anchor_restores_current_span(
            self, db, legacy_episode_store, monkeypatch, query):
        await self._seed(db)
        calls = []
        lexical = _EpisodeCandidate("tg:8001", "message", "lexical",
                                    "работа и зарплата в 2025")
        # A real graph-fact candidate: its own ref is `fact:<id>`, not a
        # message ref. The source anchor comes from the existing fact row.
        graph = _EpisodeCandidate("fact:77", "graph_fact", "lexical", "")
        graph.entity_id = "77"
        fact_rows = [{"id": 77, "item_id": "fact:77", "tg_message_id": 9001,
                      "weight": 0.9, "importance": 9,
                      "fact": "работа и зарплата в 2026"}]
        vector_calls = []
        original = rc.retrieve

        async def fake(_db, _memory, request):
            calls.append(request)
            if tuple(request.channels) == ("vector",):
                vector_calls.append(request)
                return _EpisodeResult([], fact_rows=fact_rows)
            return _EpisodeResult([lexical, graph], fact_rows=fact_rows)

        monkeypatch.setattr(rc, "retrieve", fake)
        svc = _service(db)
        block, stats = await svc._build_old_episodes(
            CHAT_ID, query, [], {})
        assert block
        assert stats["anchor_candidates"] >= 2
        assert time.gmtime(stats["spans"][0]["first_ts"]).tm_year == 2026, \
            stats["spans"]
        assert "tg:9001" in block, block
        assert 2026 in stats["years"], stats["years"]
        main = [r for r in calls if tuple(r.channels) != ("vector",)]
        assert main and tuple(main[0].channels) == ("exact", "lexical")
        assert main[0].no_age_bias is True
        assert main[0].time_from is None and main[0].time_to is None
        assert vector_calls and vector_calls[0].no_age_bias is True
        assert vector_calls[0].time_from is None
        assert vector_calls[0].time_to is None

    @pytest.mark.asyncio
    async def test_main_anchor_wins_over_same_vector_anchor(
            self, db, legacy_episode_store, monkeypatch):
        await self._seed(db)
        graph = _EpisodeCandidate("fact:77", "graph_fact", "lexical", "")
        graph.entity_id = "77"
        vector = _EpisodeCandidate("fact:77", "graph_fact", "vector", "")
        vector.entity_id = "77"
        fact_rows = [{"id": 77, "item_id": "fact:77", "tg_message_id": 9001,
                      "weight": 0.9, "importance": 9,
                      "fact": "работа и зарплата в 2026"}]

        async def fake(_db, _memory, request):
            if tuple(request.channels) == ("vector",):
                return _EpisodeResult([vector], fact_rows=fact_rows)
            return _EpisodeResult([graph], fact_rows=fact_rows)

        monkeypatch.setattr(rc, "retrieve", fake)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "что сейчас с работой и зарплатой?", [], {})
        assert block
        assert stats["vector_message_candidates"] == 1
        assert not stats.get("vector_message_used"), (
            "the same anchor already recovered by the main lexical result "
            "must not be credited to the secondary vector leg")

    @pytest.mark.asyncio
    async def test_vector_leg_secondary_not_primary(
            self, db, legacy_episode_store, monkeypatch):
        await self._seed(db)
        lexical = _EpisodeCandidate("tg:8001", "message", "lexical",
                                    "работа и зарплата в 2025")
        vector = _EpisodeCandidate("tg:9001", "graph_fact", "vector",
                                   "работа и зарплата в 2026")
        vector.entity_id = "77"

        async def fake(_db, _memory, request):
            if tuple(request.channels) == ("vector",):
                return _EpisodeResult([vector])
            return _EpisodeResult([lexical])

        monkeypatch.setattr(rc, "retrieve", fake)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "что сейчас с работой и зарплатой?", [], {})
        assert block
        assert time.gmtime(stats["spans"][0]["first_ts"]).tm_year == 2025
        assert stats["vector_message_used"] == 1
        assert 2026 in stats["years"]

    @pytest.mark.asyncio
    async def test_vector_anchor_requires_relevance_threshold(
            self, db, legacy_episode_store, monkeypatch):
        """A vector hit without the lexical subject threshold is not used:
        no calendar/age workaround, no junk span."""
        await self._seed(db)
        lexical = _EpisodeCandidate("tg:8001", "message", "lexical",
                                    "работа и зарплата в 2025")
        vector = _EpisodeCandidate("tg:9001", "graph_fact", "vector",
                                   "погода и рыбалка")

        async def fake(_db, _memory, request):
            if tuple(request.channels) == ("vector",):
                return _EpisodeResult([vector])
            return _EpisodeResult([lexical])

        monkeypatch.setattr(rc, "retrieve", fake)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "что сейчас с работой и зарплатой?", [], {})
        assert block
        assert stats["vector_message_candidates"] == 0
        assert time.gmtime(stats["spans"][0]["first_ts"]).tm_year == 2025

    @pytest.mark.asyncio
    async def test_ablation_channel_restriction_reproduces_2025_span(
            self, db, legacy_episode_store, monkeypatch):
        """Ablation seam: disable only the vector message-anchor leg; the same
        query/fixture then selects the 2025 lexical span, proving the channel
        restriction (not a calendar rule) was the cause."""
        await self._seed(db)
        lexical = _EpisodeCandidate("tg:8001", "message", "lexical",
                                    "работа и зарплата в 2025")
        vector = _EpisodeCandidate("tg:9001", "graph_fact", "vector",
                                   "работа и зарплата в 2026")
        calls = []

        async def fake(_db, _memory, request):
            calls.append(request)
            if tuple(request.channels) == ("vector",):
                return _EpisodeResult([vector])
            return _EpisodeResult([lexical])

        monkeypatch.setattr(rc, "retrieve", fake)
        monkeypatch.setattr(DirectChatService, "_RAG_EPISODE_VECTOR_CHANNELS",
                            ())
        block, stats = await svc_build(db, "что сейчас с работой и зарплатой?")
        assert block
        assert time.gmtime(stats["spans"][0]["first_ts"]).tm_year == 2025, \
            stats["spans"]
        assert stats["years"] == {2025: 2}, stats["years"]
        assert int(stats.get("vector_message_candidates") or 0) == 0
        assert all(tuple(r.channels) != ("vector",) for r in calls)


async def svc_build(db, query):
    return await _service(db)._build_old_episodes(CHAT_ID, query, [], {})


# ── (b) дефект 2: `msg:<row>` — полноценная ссылка ────────────────────────


class TestMsgRefAccepted:
    def test_anchor_of_ref_both_forms(self):
        assert _episode_anchor_of_ref("tg:555") == (555, None)
        assert _episode_anchor_of_ref("msg:777") == (None, 777)
        assert _episode_anchor_of_ref("fact:9") == (None, None)
        assert _episode_anchor_of_ref("") == (None, None)
        assert _episode_anchor_of_ref("msg:нечисло") == (None, None)

    @pytest.mark.asyncio
    async def test_msg_ref_message_reaches_payload_with_date_and_author(
            self, db, legacy_episode_store):
        """Измерение §5 п.4: 6 из 7 message-кандидатов выбрасывались как
        «tg id unresolved», потому что ссылка была `msg:<row>` (импорт без
        tg-id). Такое сообщение обязано дойти до payload с реальной датой и
        автором."""
        hit_ts = _ts(2023, 4, 12, 9)
        row_id = await _seed_message(
            db, "в 2023-м мы поругались из-за дрона", hit_ts,
            uid=138811255, author="Aleksey", tg_id=None)
        # соседние строки другого дня, чтобы эпизод не склеил всё в один блок
        await _seed_message(db, "постороннее сообщение рядом", _ts(2023, 4, 20),
                            uid=222, author="Диана", tg_id=None)

        svc = _service(db)
        block, stats = await svc._build_old_episodes(
            CHAT_ID, "из-за чего мы ругались про дрон", [], {})

        assert block, "msg:<row>-хит выброшен как нераспознанная ссылка"
        assert "в 2023-м мы поругались из-за дрона" in block
        assert _fmt(hit_ts) in block, "потеряна реальная дата сообщения"
        assert "Aleksey" in block, "потерян реальный автор сообщения"
        assert f"msg:{row_id}" in block, "ссылка должна остаться row-формой"
        assert stats["count"] == 1

    @pytest.mark.asyncio
    async def test_tg_ref_still_works(self, db, legacy_episode_store):
        """Регрессия: прежняя форма `tg:<tg_id>` читается как раньше."""
        await _seed_message(db, "старый спор про дрона", _ts(2023, 4, 12),
                            tg_id=991)
        block, stats = await _service(db)._build_old_episodes(
            CHAT_ID, "старый спор про дрона", [], {})
        assert "старый спор про дрона" in block
        assert "tg:991" in block


# ── (c) дефект 3: оконный поиск bounded по доступу, а не по корпусу ───────


class TestWindowedSearchBounded:
    @pytest.mark.asyncio
    async def test_windowed_plan_driven_by_time_index(self, db):
        """Механизм: с окном запрос ведётся от `idx_smart_messages_chat_ts`
        (стоимость ∝ окну), а не rank-планом FTS, который читает строку
        контента для каждого совпадения корпуса (дефект 3)."""
        await _seed_message(db, "дроны в 2023", _ts(2023, 5, 5), tg_id=1)
        await _seed_message(db, "дроны в 2024", _ts(2024, 5, 5), tg_id=2)

        captured: list[tuple[str, tuple]] = []
        real_execute = db.db.execute

        async def spy(sql, params=()):
            if "smart_messages_fts" in str(sql) and "SELECT m.id" in str(sql):
                captured.append((str(sql), tuple(params)))
            return await real_execute(sql, params)

        db.db.execute = spy
        rows = await db.search_messages_fts(
            CHAT_ID, '"дроны"*', 10, since_ts=_ts(2023, 1, 1),
            until_ts=_ts(2023, 12, 31), order="time")
        assert [r["tg_message_id"] for r in rows] == [1]
        assert captured, "оконный запрос должен идти через search_messages_fts"

        sql, params = captured[-1]
        plan = " ".join(
            str(c[3]) for c in await (await real_execute(
                "EXPLAIN QUERY PLAN " + sql, params)).fetchall())
        assert "idx_smart_messages_chat_ts" in plan, plan
        assert "SEARCH m USING INTEGER PRIMARY KEY" not in plan.replace(
            "COVERING", ""), (
            "rank-план читает content-таблицу на каждом совпадении: " + plan)

    @pytest.mark.asyncio
    async def test_windowed_search_returns_in_bounded_time(self, db):
        """Смоук по времени на локальном архиве (алгоритмический замер —
        на реальных 1,93 млн строк в evidence: 12,59 → 3,36 млн VM-шагов)."""
        base = _ts(2021, 1, 1)
        for i in range(1200):
            await _seed_message(db, f"дроны событие {i}",
                                base + i * 86400, tg_id=100000 + i)
        started = time.monotonic()
        rows = await db.search_messages_fts(
            CHAT_ID, '"дроны"*', 40, since_ts=_ts(2022, 1, 1),
            until_ts=_ts(2022, 12, 31), order="time")
        elapsed = time.monotonic() - started
        assert elapsed < 5.0, f"оконный поиск вышел за бюджет: {elapsed:.2f}s"
        assert rows, "окно 2022 было непустым"
        ts_list = [int(r["timestamp"]) for r in rows]
        assert all(_ts(2022, 1, 1) <= ts <= _ts(2022, 12, 31)
                   for ts in ts_list), "строки вне запрошенного окна"
        assert ts_list == sorted(ts_list, reverse=True), "порядок по времени"

    @pytest.mark.asyncio
    async def test_search_long_term_passes_order_through(self, db):
        """Проводка: дефолт остаётся rank-паритетом, bounded-план включается
        только явным `order="time"` от вызывающего (dig со окном периода)."""
        calls: list[dict] = []

        class _Recorder:
            def __init__(self, inner):
                self.inner = inner

            async def search_messages_fts(self, chat_id, query, limit, **kw):
                calls.append(dict(kw))
                return []

        obj = type("Mem", (), {})()
        obj.db = _Recorder(db)
        await MemoryManager.search_long_term(
            obj, CHAT_ID, ["дроны"], 10, since_ts=_ts(2023, 1, 1),
            until_ts=_ts(2023, 12, 31))
        await MemoryManager.search_long_term(
            obj, CHAT_ID, ["дроны"], 10, since_ts=_ts(2023, 1, 1),
            until_ts=_ts(2023, 12, 31), order="time")
        assert calls[0]["order"] == "rank", "паритет прежних вызывающих"
        assert calls[1]["order"] == "time"


class TestDigPayloadHonesty:
    @staticmethod
    def _deps(memory) -> ToolDeps:
        return ToolDeps(search=MagicMock(), memory=memory, aliases=None)

    @staticmethod
    def _ctx() -> ToolContext:
        return ToolContext(CHAT_ID, "вопрос", user_id=None)

    @staticmethod
    def _row(text="сниппет", ts=None) -> dict:
        return {"id": 1, "user_id": 10, "author_name": "вася", "text": text,
                "timestamp": ts or int(time.time()), "tg_message_id": None,
                "is_forward": 0, "forward_source": None}

    def _router(self, monkeypatch, rows):
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled", lambda: True)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.db = MagicMock()
        memory.db.search_messages_fts_count_by_author = AsyncMock(
            return_value={"count": 5, "by_author": [], "first_seen": 1,
                          "last_seen": 2})
        return ToolRouter(self._deps(memory)), memory

    @pytest.mark.asyncio
    async def test_year_window_reports_window_scan_sampling(self, monkeypatch):
        inside = _ts(2023, 5, 5)
        router, memory = self._router(monkeypatch, [
            self._row("сниппет один", ts=inside),
            self._row("сниппет два", ts=inside + 60)])
        out = await router._dig_into_lore(
            {"query": "дроны", "year": 2023, "mode": "messages"}, self._ctx())
        coverage = json.loads(out)["coverage"]
        assert coverage["sampling"] == "window_scan_by_time"
        # 5 совпадений в окне, показано 2 → обрезка названа честно
        assert coverage["truncated"] is True
        assert coverage["messages_total"] == 5
        assert coverage["messages_shown"] == 2
        # окно периода запрошено bounded-планом (order="time")
        assert memory.search_long_term.await_args.kwargs["order"] == "time"

    @pytest.mark.asyncio
    async def test_no_period_reports_relevance_sampling(self, monkeypatch):
        router, memory = self._router(monkeypatch, [self._row()])
        out = await router._dig_into_lore(
            {"query": "дроны", "mode": "messages"}, self._ctx())
        coverage = json.loads(out)["coverage"]
        assert coverage["sampling"] == "top_by_relevance"
        assert coverage["truncated"] is True
        # без периода bound-ключ не запрашивается — прежний rank-порядок
        assert "order" not in memory.search_long_term.await_args.kwargs
