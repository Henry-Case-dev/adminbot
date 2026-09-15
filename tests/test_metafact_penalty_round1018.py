"""Раунд 10.18 (F5 `metafact-penalty-extractor-prompt`, ADR-1018-5).

Покрытие:
  * канон-миграция ``FACT_EXTRACT_PROMPT`` (PREV-слепок + байт-тесты по
    ADR-1013-3); ``PROMPT_MIGRATIONS`` НЕ расширяется (модульная константа);
  * программный хард-лимит importance в единой точке записи
    (``insert_graph_fact``: subject/object ∈ penalty-стоп-лист → 1);
  * нормализация сравнения (casefold / краевая пунктуация / ё→е);
  * обычные факты не затронуты; факты БЕЗ subject/object — прежнее поведение;
  * мета-факты сохраняются, не проходят гейты Сна и не доминируют в RAG.
"""
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from config.settings import settings
from services import hot_config as hot
from services.dream_worker import DreamWorker
from services.graph_stoplist import (
    METAFACT_PENALTY_IMPORTANCE,
    METAFACT_PENALTY_STOPLIST,
    is_metafact_stopword,
)
from services.summary_memory import (
    FACT_EXTRACT_PROMPT,
    PREV_FACT_EXTRACT_PROMPT,
    MemoryManager,
    _importance_factor,
)

CHAT_ID = -100


def _hot_cache(monkeypatch, values: dict) -> None:
    """hot-кэш-заглушка (прецедент test_dream_worker): заданные ключи,
    отсутствующие → settings-дефолты."""
    class _FakeHotCache:
        def __init__(self, vals):
            self._values = dict(vals)

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))

# Прежний канон R46-2 (HEAD 118a03c) — байт-в-байт PREV-слепок.
_OLD_FACT_EXTRACT_PROMPT = """СИСТЕМНАЯ РОЛЬ:
Ты — безэмоциональный архивариус (ETL-процессор). Твоя задача: извлечь сухие, проверяемые факты из предоставленного текста и представить их в виде графовых триплетов (Субъект -> Предикат -> Объект).
- Игнорируй любые эмоции, шутки, оскорбления и личности авторов запроса.
- Извлекай только объективную информацию (суть статьи, результаты поиска, тезисы видео).
- Если текст содержит техническую или справочную инфу — сохрани её максимально точно.

ВЫВОД:
Верни строго JSON со списком фактов. Пример: [{"subject": "Ozon", "predicate": "доставляет быстрее чем", "object": "Wildberries", "context": "из-за большего количества складов"}]"""


@pytest_asyncio.fixture
async def db():
    from services.database import DatabaseService
    d = DatabaseService(":memory:")
    await d.initialize()
    yield d
    await d.close()


def _backlog_fact_extract_prompt() -> str:
    """Канон R46-2 из plans/docs/canon/backlog.md (якорь заголовка)."""
    lines = Path("plans/docs/canon/backlog.md").read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines)
        if line.startswith("**Канон R46-2 — промпт-экстрактор")
    )
    fence = next(
        i for i in range(start, len(lines)) if lines[i].strip() == "```"
    )
    end = next(
        i for i in range(fence + 1, len(lines)) if lines[i].strip() == "```"
    )
    return "\n".join(lines[fence + 1:end])


class TestCanonMigration:
    def test_prev_is_old_canon_byte_for_byte(self):
        assert PREV_FACT_EXTRACT_PROMPT == _OLD_FACT_EXTRACT_PROMPT

    def test_new_is_prev_plus_additive_paragraph(self):
        assert FACT_EXTRACT_PROMPT.startswith(PREV_FACT_EXTRACT_PROMPT)
        additive = FACT_EXTRACT_PROMPT[len(PREV_FACT_EXTRACT_PROMPT):]
        assert additive.startswith("\n\nФОКУС НА СОДЕРЖАНИИ:")
        assert "Фокусируйся на СУТИ и СОДЕРЖАНИИ" in additive
        assert "ТОЛЬКО если вокруг формата идёт явное обсуждение" in additive
        assert "игнорируй его формат" in additive

    def test_backlog_canon_byte_for_byte(self):
        """Эталон = код = тесты (ADR-1013-3 §2)."""
        assert FACT_EXTRACT_PROMPT == _backlog_fact_extract_prompt()

    def test_new_canon_mentions_penalty_stopwords(self):
        for word in ("голосов", "кружоч", "видеосообщ", "фото", "ссылк",
                     "стикер"):
            assert word in FACT_EXTRACT_PROMPT, word

    def test_prompt_migrations_not_extended(self):
        """F5 — модульная константа: ``PROMPT_MIGRATIONS`` не трогаем."""
        from services.prompt_migrations import PROMPT_MIGRATIONS
        joined = " ".join(PROMPT_MIGRATIONS.keys())
        assert "FACT_EXTRACT_PROMPT" not in joined
        assert "extract_system_prompt" not in joined


class TestStoplistsDistinct:
    def test_penalty_stoplist_content(self):
        assert METAFACT_PENALTY_STOPLIST == frozenset({
            "видеосообщение", "голосовое", "фото", "кружочек", "ссылка",
            "стикер"})

    def test_penalty_importance_is_one(self):
        assert METAFACT_PENALTY_IMPORTANCE == 1

    def test_message_is_center_only_not_penalty(self):
        from services.graph_stoplist import is_center_stopword
        assert is_center_stopword("сообщение") is True
        assert is_metafact_stopword("сообщение") is False


class TestImportanceHardLimit:
    @pytest.mark.asyncio
    async def test_stopword_object_cut_to_one(self, db):
        await db.insert_graph_fact(
            -100, "вася отправил видеосообщение", "chat_history", None,
            subject="вася", object="видеосообщение")
        cursor = await db.db.execute("SELECT importance, fact FROM graph_facts")
        row = await cursor.fetchone()
        assert row["importance"] == 1
        # факт СОХРАНЁН (не удалён) — статистика/шутки
        assert row["fact"] == "вася отправил видеосообщение"

    @pytest.mark.asyncio
    async def test_stopword_subject_cut_to_one(self, db):
        await db.insert_graph_fact(
            -100, "голосовое сломалось", "chat_history", None,
            subject="голосовое", object="вася")
        cursor = await db.db.execute("SELECT importance FROM graph_facts")
        assert (await cursor.fetchone())["importance"] == 1

    @pytest.mark.asyncio
    async def test_normalization_variants_cut(self, db):
        for subject, obj in (
                ("  «Видеосообщение»!  ", "вася"),
                ("КРУЖОЧЁК", "вася"),
                ("стикер.", "вася")):
            await db.insert_graph_fact(
                -100, f"{subject} -> тест", "chat_history", None,
                subject=subject, object=obj)
        cursor = await db.db.execute("SELECT importance FROM graph_facts")
        rows = await cursor.fetchall()
        assert len(rows) == 3
        assert all(r["importance"] == 1 for r in rows)

    @pytest.mark.asyncio
    async def test_explicit_high_importance_overridden(self, db):
        """LLM/вызывающий задал 10 — хард-лимит всё равно срезает до 1."""
        await db.insert_graph_fact(
            -100, "вася отправил ссылка", "chat_history", None,
            subject="вася", object="ссылка", importance=10)
        cursor = await db.db.execute("SELECT importance FROM graph_facts")
        assert (await cursor.fetchone())["importance"] == 1

    @pytest.mark.asyncio
    async def test_normal_fact_keeps_rule_importance(self, db):
        await db.insert_graph_fact(
            -100, "вася обсуждает проект", "chat_history", None,
            subject="вася", object="проект")
        cursor = await db.db.execute("SELECT importance FROM graph_facts")
        assert (await cursor.fetchone())["importance"] == 4   # база chat_history

    @pytest.mark.asyncio
    async def test_no_subject_object_unchanged(self, db):
        """Крон/direct-пути (без subject/object) — прежнее поведение."""
        await db.insert_graph_fact(
            -100, "вася отправил видеосообщение", "chat_history", None)
        cursor = await db.db.execute("SELECT importance FROM graph_facts")
        assert (await cursor.fetchone())["importance"] == 4

    @pytest.mark.asyncio
    async def test_explicit_importance_preserved_without_stopword(self, db):
        await db.insert_graph_fact(
            -100, "вася придумал фичу", "chat_history", None,
            subject="вася", object="фича", importance=9)
        cursor = await db.db.execute("SELECT importance FROM graph_facts")
        assert (await cursor.fetchone())["importance"] == 9


class TestMemorizePathPenalty:
    @pytest.mark.asyncio
    async def test_memorize_passes_subject_object(self, db):
        """`_memorize_facts_inner` передаёт subject/object → срез работает."""
        import json

        class _LLM:
            async def generate(self, messages):
                return json.dumps([{
                    "subject": "вася", "predicate": "отправил",
                    "object": "видеосообщение"}], ensure_ascii=False)

            async def embed(self, texts):
                return [[0.1] * 8 for _ in texts]

        from services.summary_memory import MemoryManager
        memory = MemoryManager(db, _LLM())
        await memory.memorize_facts(-100, "вася отправил видеосообщение",
                                    "chat_history")
        cursor = await db.db.execute("SELECT importance FROM graph_facts")
        rows = await cursor.fetchall()
        assert rows and all(r["importance"] == 1 for r in rows)

    def test_source_passes_subject_object_to_insert(self):
        src = Path("services/summary_memory.py").read_text(encoding="utf-8")
        assert "subject=subject, object=obj," in src


class _GateLLM:
    """Мок LLM: очередь ответов; считает число вызовов дистилляции."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = 0

    async def generate(self, messages, temperature=None):
        self.calls += 1
        if self._answers:
            return self._answers.pop(0)
        return '{"beliefs":[]}'

    async def embed(self, texts):
        return [[0.1] * 8 for _ in texts]


_GATE_ANS = ('{"beliefs":[{"text":"вася всегда платит за всех в баре",'
             '"evidence":[1,2,3]}]}')


class TestSleepGateBehavioral:
    """B4-2: ПОВЕДЕНЧЕСКИЙ тест реального гейта `dream_worker` (не константы).

    Гейт квалификации кластера: `len(cluster) >= repeat_threshold` И
    `Σ importance >= importance_sum_threshold`. Мета-кластер (imp=1 каждый)
    не набирает Σ; контрольный кластер тех же фактов без среза (imp из
    `rule_importance`) — набирает и дистиллируется."""

    @pytest.mark.asyncio
    async def test_meta_fact_cluster_fails_dream_gate(self, db, monkeypatch):
        _hot_cache(monkeypatch, {"memory.dream_enabled": True})
        # Свежая дистилляция («убеждения есть») → базовые пороги, не
        # fallback 2/6 (как в tests/test_dream_worker.py).
        await db.log_dream_event(CHAT_ID, int(time.time()),
                                 kind="distilled", status="ok")
        llm = _GateLLM(_GATE_ANS)
        worker = DreamWorker(db, memory=None, llm=llm)

        # 1) мета-кластер: subject/object ∈ penalty-стоп-лист → importance=1
        for i in range(3):
            await db.insert_graph_fact(
                CHAT_ID, f"вася отправил видеосообщение в {i + 1} раз",
                "chat_history", None, subject="вася", object="видеосообщение")
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 0
        assert res["clusters"] == 0           # кластер не прошёл гейт
        assert llm.calls == 0                 # LLM дистилляции не звался
        cursor = await db.db.execute("SELECT importance, fact FROM graph_facts")
        rows = await cursor.fetchall()
        assert rows and all(r["importance"] == 1 for r in rows)   # мета сохранены

        # 2) контроль: ТЕ ЖЕ по форме факты БЕЗ среза (imp=rule_importance=4,
        # Σ=12 >= DREAM_IMPORTANCE_SUM_THRESHOLD=8) — кластер проходит.
        for i in range(3):
            await db.insert_graph_fact(
                CHAT_ID, f"петя отправил открытку в {i + 1} раз",
                "chat_history", None)
        res2 = await worker.run_once(CHAT_ID)
        assert res2["distilled"] == 1         # важный кластер НЕ вытеснен
        assert llm.calls == 1


class TestRagImportanceRanking:
    """B4-1 (ADR-1018-5 D7): importance учитывается в ранжировании ОСНОВНОГО
    RAG — мета-факт (imp=1) не перебивает важный факт (imp≥8) при прочих
    равных; обычное относительное ранжирование не разрушено."""

    def test_importance_factor_bounded_and_monotonic(self):
        assert _importance_factor(1) == pytest.approx(0.55)
        assert _importance_factor(10) == pytest.approx(1.0)
        # нейтраль/кламп: None/мусор → 5; вне диапазона — clamp 1..10
        assert _importance_factor(None) == pytest.approx(0.75)
        assert _importance_factor(0) == pytest.approx(0.55)
        assert _importance_factor(99) == pytest.approx(1.0)
        vals = [_importance_factor(i) for i in range(1, 11)]
        assert vals == sorted(vals)           # монотонность
        # мета (1) vs важный (8): множитель строго ниже
        assert _importance_factor(1) < _importance_factor(8)

    def test_equal_importance_keeps_weight_order(self):
        """Множитель одинаков → относительный порядок по weight сохранён."""
        from services.summary_memory import _effective_weight
        now = 1_800_000_000
        heavy = _effective_weight(0.8, now, now) * _importance_factor(4)
        light = _effective_weight(0.5, now, now) * _importance_factor(4)
        assert heavy > light

    @pytest.mark.asyncio
    async def test_meta_fact_loses_to_important_fts(self, monkeypatch):
        """FTS-путь основного RAG: мета-факт «первым» по FTS-рангу, но
        ранжирование по weight×importance ставит важный факт выше."""
        _hot_cache(monkeypatch, {"flags.graph_fact_touch_enabled": False})

        rows_in = [
            {"id": 1, "fact": "вася отправил видеосообщение", "origin":
             "chat_history", "weight": 0.5, "last_confirmed_at": None,
             "importance": 1, "rag_ts": 0, "target_user": None},
            {"id": 2, "fact": "вася спас проект", "origin": "chat_history",
             "weight": 0.5, "last_confirmed_at": None, "importance": 8,
             "rag_ts": 0, "target_user": None},
        ]

        class _RagDB:
            async def search_graph_facts_fts(self, *a, **kw):
                return list(rows_in)

            async def touch_graph_facts(self, *a, **kw):
                return 0

        memory = MemoryManager(_RagDB(), _GateLLM())
        memory._vec_available = False
        facts = await memory._search_graph_facts(CHAT_ID, "вася", 10)
        assert [f[1] for f in facts] == [
            "вася спас проект", "вася отправил видеосообщение"]

    @pytest.mark.asyncio
    async def test_meta_fact_loses_to_important_knn(self, db, monkeypatch):
        """KNN-путь основного RAG: при равном cosine мета-факт уступает."""
        _hot_cache(monkeypatch, {
            "flags.graph_mmr_enabled": False,
            "flags.graph_fact_touch_enabled": False,
            "flags.graph_time_decay_enabled": False})
        meta_id = await db.insert_graph_fact(
            CHAT_ID, "вася отправил видеосообщение", "chat_history", None,
            subject="вася", object="видеосообщение", weight=0.5)   # imp=1
        imp_id = await db.insert_graph_fact(
            CHAT_ID, "вася спас проект", "chat_history", None,
            weight=0.5, importance=8)
        memory = MemoryManager(db, _GateLLM())
        memory._vec_available = True
        memory._vec_candidates = AsyncMock(return_value=[
            (meta_id, 0.9, [1.0, 0.0]),
            (imp_id, 0.9, [1.0, 0.0])])       # равный cosine
        rows = await memory._knn_graph_facts(CHAT_ID, [1.0, 0.0], 2)
        assert [r[1] for r in rows] == [
            "вася спас проект", "вася отправил видеосообщение"]
        # важный факт не вытеснен — присутствует в выборке
        assert "вася спас проект" in {r[1] for r in rows}

    @pytest.mark.asyncio
    async def test_meta_fact_excluded_from_golden_rag(self, db):
        """B4-info(b): порог привязан к settings.NOSTALGIA_GOLDEN_MIN_IMPORTANCE
        (production-порог «золотых»), а не к литералу."""
        now = int(time.time()) + 1000
        threshold = int(settings.NOSTALGIA_GOLDEN_MIN_IMPORTANCE)
        await db.insert_graph_fact(
            CHAT_ID, "вася отправил видеосообщение", "chat_history", None,
            subject="вася", object="видеосообщение")             # importance 1
        await db.insert_graph_fact(
            CHAT_ID, "вася обсуждает проект", "chat_history", None,
            subject="вася", object="проект",
            importance=threshold)                                # ≥ порога
        rows = await db.search_golden_facts_fts(
            CHAT_ID, "вася", 10, now, min_importance=threshold,
            max_age_ts=now)
        facts = {r["fact"] for r in rows}
        assert "вася обсуждает проект" in facts
        assert "вася отправил видеосообщение" not in facts

