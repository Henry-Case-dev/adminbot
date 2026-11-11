"""VMQ-MEM next stage (§1–§5): семантическая нога периодного добора.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/next-stage-design.md`.

Покрытие (CONTRACT):
  * §1 векторная нога периодного добора — ОДИН float-MATCH с фиксированным
    `k=32` и JOIN по `rowid` к `graph_facts`; годы базового среза
    исключаются ПОСЛЕ среза, старый факт вне `k` честно не находится
    (`vector_pool_miss`, не «тихий успех»);
  * §1 SQL-окно года у `search_graph_facts_fts` — до `ORDER BY rank LIMIT`;
  * §2 лексическая строка входит только при ≥2 разных общих основах;
    векторная строка порог не проходит (иначе смысловой путь отменён);
  * §3 валидный пустой вердикт реранка гасит ТОЛЬКО строки, которые модель
    видела; лексический добор §2, в реранк не отправлявшийся, выживает;
  * §2/§5 одна чужая строка (2023) не собирает блок сама;
  * §4 наблюдаемый случай 2025 года под `auto` режется порогом основ, а НЕ
    словарём «сейчас»;
  * §1/§5 поколение индекса `compat_not_proven` → нога не принимается:
    деградация на лексический путь с кодом причины, без исключения и без
    молчаливой пустоты.

TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/next-stage
R17: только синтетические факты и векторы, никаких реальных переписок.
"""
import asyncio
import calendar
import json
import time
import types

import pytest

from services import direct_chat_service as dcs
from services import hot_config as hot
from services import mca_retrieval_context as mrc
from services.database import DatabaseService
from services.summary_memory import MemoryManager

CHAT = -100
CHAT_FOREIGN = -999
DIM = 8
_DAY = 86400


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


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
    """embed по карте текст→вектор (синтетика R17); generate не нужен."""

    def __init__(self, vec_map=None, default=None):
        self.vec_map = dict(vec_map or {})
        self.default = default or _unit(0)

    async def embed(self, texts):
        return [self.vec_map.get(t, self.default) for t in texts]

    async def generate(self, messages):  # pragma: no cover
        raise AssertionError("generate в этих тестах не нужен")


class _FakeHotCache:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


class _Msg:
    def __init__(self, text):
        self.text = text


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


async def _memory(db, monkeypatch):
    """MemoryManager на реальной SQLite+sqlite-vec (KNN-путь рабочий)."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        pytest.skip("sqlite-vec not installed")

    async def _probe_fixed(self):
        return False

    monkeypatch.setattr(MemoryManager, "_probe_vec_int8", _probe_fixed)
    memory = MemoryManager(db, VecLLM())

    async def _noop_backfill() -> int:
        return 0

    memory.backfill_archive_vectors = _noop_backfill
    memory.backfill_graph_fact_vectors = _noop_backfill
    if not await memory.initialize():
        pytest.skip("sqlite-vec extension could not be loaded")
    return memory


async def _seed(db, memory, text, vector, *, year=2026, chat_id=CHAT,
                origin="chat_history", with_vec=True):
    fact_id = await db.insert_graph_fact(
        chat_id, text, origin, None, target_user="aleksey",
        status="confirmed", weight=0.5, importance=5,
        message_timestamp=_ts(year), subject_ref_id=7,
        speaker_author_id=7, attribution_method="self_report",
        tg_message_id=9000 + abs(hash(text)) % 1000)
    now = int(time.time())
    await db.db.execute(
        "UPDATE graph_facts SET last_confirmed_at = ? WHERE id = ?",
        (now, fact_id))
    await db.db.commit()
    if with_vec:
        memory.llm.vec_map[text] = vector
        await memory._insert_graph_vec_row(fact_id, chat_id, text, origin,
                                           None, vector)
    return fact_id


# ── §1: векторная нога — срез 32, JOIN по rowid, окно года ПОСЛЕ среза ─────


class TestPeriodVectorLeg:
    @pytest.mark.asyncio
    async def test_old_fact_selected_after_year_filter(self, db, monkeypatch):
        """Старый факт достаётся, хотя базовый год исключён: фильтр стоит
        ПОСЛЕ среза, а не в WHERE по aux-колонке vec-таблицы."""
        memory = await _memory(db, monkeypatch)

        async def _accept(_self):
            return ""

        monkeypatch.setattr(MemoryManager, "_period_vector_guard", _accept)
        query = "где было про ванную и ремонт"
        memory.llm.vec_map[query] = _unit(0)
        fresh = await _seed(db, memory, "свежий факт 2026", _unit(0))
        old = await _seed(db, memory, "старый факт про ванную", _mix(0.9, 0.3),
                          year=2023)
        foreign = await _seed(db, memory, "чужой чат ближе всех",
                              _mix(0.99, 0.1), year=2023,
                              chat_id=CHAT_FOREIGN)
        stats: dict = {}
        rows = await memory.period_fill_candidates(
            CHAT, query, k=32, exclude_years=(2026,),
            include_direct_reply=True, include_self=True,
            include_archived=True, stats=stats)
        ids = [int(row["id"]) for row in rows]
        assert ids == [old], "2026 исключён окном, чужой чат — JOIN-фильтром"
        assert fresh not in ids and foreign not in ids
        assert stats["vector_leg"] == "ok"
        assert stats["vector_rows"] == 1
        assert stats["vector_pool_miss"] == 0

    @pytest.mark.asyncio
    async def test_pool_miss_is_recorded_not_faked(self, db, monkeypatch):
        """Старый факт вне ближайших `k` — честный `vector_pool_miss`."""
        memory = await _memory(db, monkeypatch)

        async def _accept(_self):
            return ""

        monkeypatch.setattr(MemoryManager, "_period_vector_guard", _accept)
        query = "где было про ванную и ремонт"
        memory.llm.vec_map[query] = _unit(0)
        await _seed(db, memory, "свежий факт 2026", _unit(0))
        await _seed(db, memory, "старый факт про ванную", _mix(0.5, 0.87),
                    year=2023)
        stats: dict = {}
        rows = await memory.period_fill_candidates(
            CHAT, query, k=1, exclude_years=(2026,),
            include_direct_reply=True, include_self=True,
            include_archived=True, stats=stats)
        assert rows == [], "в пуле 1 ближайший — свежий, его год исключён"
        assert stats["vector_pool_miss"] == 1
        assert stats["vector_leg"] == "ok", "нога работала, она просто пуста"

    @pytest.mark.asyncio
    async def test_compat_not_proven_degrades_to_lexical(self, db, monkeypatch):
        """§5: `compat_not_proven` → нога не принимается, добор остаётся
        лексическим, причина записана, исключения и молчаливой пустоты нет."""
        memory = await _memory(db, monkeypatch)
        old = await _seed(db, memory, "старый факт про ванную ремонт",
                          _mix(0.9, 0.3), year=2023)

        async def _not_proven(_self):
            return "compat_not_proven"

        monkeypatch.setattr(MemoryManager, "_period_vector_guard",
                            _not_proven)
        result = await mrc.retrieve(db, memory, mrc.RetrievalRequest(
            chat_id=CHAT, query="старый факт про ванную ремонт",
            mode="specific", purpose="reply", top_k=32,
            channels=("lexical", "vector"), reply_depth=0,
            memory_scope="historical", lexical_stem=True,
            include_archived=True, include_self=True,
            include_direct_reply=True, preserve_channel_order=True,
            period_fill=True, exclude_years=(2026,)))
        ids = {int(row["id"]) for row in (result.fact_rows or ())}
        assert old in ids, "лексический путь обязан остаться рабочим"
        assert result.period_fill["vector_leg"] == "compat_not_proven"
        assert result.period_fill["vector_rows"] == 0

    @pytest.mark.asyncio
    async def test_guard_falls_back_to_generation_gate(self, db, monkeypatch):
        """Контроль-плоскость без доказательства расхождения → решает
        прежний гейт A06; исключения нет, нога не отключается молча."""
        memory = await _memory(db, monkeypatch)

        async def _boom(*_a, **_k):
            raise RuntimeError("control plane down")

        monkeypatch.setattr(
            "services.embedding_control_plane.resolve_index_compat", _boom)
        assert await memory._period_vector_guard() == ""


# ── §2/§4: порог основ — «тот же предмет, не то же слово» ──────────────────


def _period_row(fid, text, *, year=2023, source="lexical"):
    return {"id": fid, "fact": text, "origin": "history_import",
            "status": "confirmed", "expires_at": None,
            "created_at": _ts(year), "message_timestamp": _ts(year),
            "tg_message_id": 800 + fid, "chat_id": CHAT,
            "item_id": f"fact:{fid}", "period_source": source}


class TestSubjectThreshold:
    def test_lexical_row_needs_two_stems(self):
        """Одна общая основа — шум одного слова (на архиве: айтишники)."""
        query = "что говорили про зарплату айтишников в Перми?"
        accepted, rejected = dcs.DirectChatService._rag_period_subject_filter(
            query,
            [_period_row(1, "Корсар считает айтишников уёбками"),
             _period_row(2, "зарплата айтишников в Перми выросла")])
        assert [row["id"] for row in accepted] == [2]
        assert rejected == 1

    def test_vector_row_bypasses_threshold_and_goes_first(self):
        """Смысловой путь не отменяется порогом лексики и идёт первым."""
        accepted, rejected = dcs.DirectChatService._rag_period_subject_filter(
            "что говорили про зарплату айтишников в Перми?",
            [_period_row(1, "зарплата айтишников в Перми выросла"),
             _period_row(2, "шаурма и витамины", source="vector")])
        assert [row["id"] for row in accepted] == [2, 1]
        assert rejected == 0

    def test_auto_requires_two_stems_even_for_vector_row(self):
        """§4/§5: под `auto` решения L1 нет — старый год входит ТОЛЬКО через
        §2, в том числе векторный сосед. Иначе на вопрос о текущем состоянии
        добавлялась бы чужая строка без общих основ (наблюдалось на C1)."""
        rows = [_period_row(7388, "наблюдается за поведением участников чата",
                            year=2025, source="vector")]
        query = "что сейчас происходит в чате?"
        accepted, rejected = dcs.DirectChatService._rag_period_subject_filter(
            query, rows, "auto")
        assert accepted == [] and rejected == 1
        # С двумя основами тот же сосед проходит и под `auto`.
        accepted, rejected = dcs.DirectChatService._rag_period_subject_filter(
            query,
            [_period_row(7388, "происходит в чате обсуждение", year=2025,
                         source="vector")], "auto")
        assert [row["id"] for row in accepted] == [7388]
        assert rejected == 0

    def test_current_state_row_cut_by_stems_not_by_now_dictionary(self):
        """§4: наблюдаемая строка 2025 года («… ноют сейчас») не проходит
        порог основ. Тот же текст с второй основой проходит — значит режет
        порог, а не словарь «сейчас»/времени."""
        query = "что сейчас происходит в чате?"
        noisy, _rejected = dcs.DirectChatService._rag_period_subject_filter(
            query, [_period_row(8436, "выгнали сами и ноют сейчас",
                                year=2025)])
        assert noisy == [], "одна основа «сейчас» — не предмет вопроса"
        accepted, rejected = dcs.DirectChatService._rag_period_subject_filter(
            query, [_period_row(8436, "выгнали сами и ноют сейчас в чате",
                                year=2025)])
        assert [row["id"] for row in accepted] == [8436]
        assert rejected == 0


# ── §1: SQL-окно года у search_graph_facts_fts — до ORDER BY/LIMIT ─────────


class TestFtsYearWindow:
    @pytest.mark.asyncio
    async def test_year_window_applied_before_limit(self, db, monkeypatch):
        """Окно года стоит ДО `LIMIT`: при `limit=1` и исключённом годе
        возвращается строка другого года, а не пустой результат."""
        memory = await _memory(db, monkeypatch)
        await _seed(db, memory, "ремонт ванной закончили в 2026 году",
                    _unit(0), year=2026, with_vec=False)
        old = await _seed(db, memory, "ремонт", _mix(0.5, 0.87), year=2023,
                          with_vec=False)
        now = int(time.time())
        match = "ремонт OR ванной OR закончили"
        without = await db.search_graph_facts_fts(CHAT, match, 1, now,
                                                  include_self=True,
                                                  include_archived=True)
        assert without and int(without[0]["id"]) != old, (
            "ближайший по рангу — строка 2026")
        windowed = await db.search_graph_facts_fts(
            CHAT, match, 1, now, include_self=True, include_archived=True,
            exclude_years=(2026,))
        assert [int(row["id"]) for row in windowed] == [old], (
            "фильтр после LIMIT вернул бы пустой срез")

    @pytest.mark.asyncio
    async def test_empty_window_is_byte_identical(self, db, monkeypatch):
        """Пустой набор годов не добавляет предикат (`NOT IN ()` запрещён)."""
        memory = await _memory(db, monkeypatch)
        fact = await _seed(db, memory, "ремонт ванной", _unit(0), year=2026,
                           with_vec=False)
        now = int(time.time())
        for extra in (None, (), ()):
            rows = await db.search_graph_facts_fts(
                CHAT, "ремонт", 5, now, include_self=True,
                include_archived=True, exclude_years=extra)
            assert [int(row["id"]) for row in rows] == [fact]


# ── §1/§2/§3: сквозь реальный сборщик блока ────────────────────────────────


class TestBlockIntegration:
    @staticmethod
    def _service(memory, db_now):
        return dcs.DirectChatService(memory=memory, db=db_now, llm=None,
                                     aliases=None)

    async def _base_2026(self, db, memory, count=11):
        """Базовый срез 2026-доминирован: старый факт вытеснен из него."""
        for index in range(count):
            await _seed(db, memory, f"текущий факт номер {index}",
                        _mix(1.0 - index * 0.001, 0.02 + index * 0.001))

    @pytest.mark.asyncio
    async def test_single_foreign_row_does_not_assemble_block(
            self, db, monkeypatch):
        """Одна чужая строка 2023 с единственной общей основой не собирает
        блок сама; с двумя основами — собирает (тот же механизм)."""
        memory = await _memory(db, monkeypatch)
        _hot(monkeypatch, {"flags.graph_rag_enabled": True,
                           "flags.chat_rag_rerank_enabled": False,
                           "memory.nostalgia_layer_a_enabled": False,
                           "limits.graph_rag_facts_limit": 10,
                           "limits.graph_rag_context_max_chars": 2000})

        async def _no_chat_param(*_args, **_kwargs):
            return None

        monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
        await self._base_2026(db, memory)
        noisy = await _seed(db, memory, "собака убежала домой",
                            _mix(0.4, 0.9), year=2023, with_vec=False)
        service = self._service(memory, db)
        block, _hint = await service._build_rag_block(
            CHAT, _Msg("что было с собакой?"), "",
            memory_scope="historical")
        assert "собака убежала домой" not in block, (
            block, "одна общая основа — не предмет вопроса")
        assert service._rag_period_stats.get("rejected_subject") == 1
        assert noisy

        # Контроль: тот же старый факт, но с двумя основами — доходит.
        await _seed(db, memory, "было так: собака убежала домой",
                    _mix(0.4, 0.9), year=2024, with_vec=False)
        block2, _hint2 = await service._build_rag_block(
            CHAT, _Msg("что было с собакой?"), "", memory_scope="historical")
        assert "было так: собака убежала домой" in block2, block2

    @pytest.mark.asyncio
    async def test_current_state_question_adds_no_old_row(self, db, monkeypatch):
        """C1-подобный вопрос под `auto`: единственная старая строка с
        «сейчас» не добавляется, текущий год остаётся большинством."""
        memory = await _memory(db, monkeypatch)
        _hot(monkeypatch, {"flags.graph_rag_enabled": True,
                           "flags.chat_rag_rerank_enabled": False,
                           "memory.nostalgia_layer_a_enabled": False,
                           "limits.graph_rag_facts_limit": 10,
                           "limits.graph_rag_context_max_chars": 2000})

        async def _no_chat_param(*_args, **_kwargs):
            return None

        monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
        await self._base_2026(db, memory)
        await _seed(db, memory, "выгнали сами и ноют сейчас",
                    _mix(0.35, 0.93), year=2025, with_vec=False)
        service = self._service(memory, db)
        block, _hint = await service._build_rag_block(
            CHAT, _Msg("что сейчас происходит в чате?"), "",
            memory_scope="auto")
        assert "ноют сейчас" not in block, (block, "периодных строк быть 0")
        assert service._rag_period_stats.get("rejected_subject") == 1

    @pytest.mark.asyncio
    async def test_empty_verdict_keeps_row_model_never_saw(
            self, db, monkeypatch):
        """§3: пустой вердикт снимает судимые строки (включая knn-соседа и
        непериодный срез) и не гасит лексический добор, которого модель не
        видела."""
        _hot(monkeypatch, {"flags.graph_rag_enabled": True,
                           "flags.chat_rag_rerank_enabled": True,
                           "memory.nostalgia_layer_a_enabled": False,
                           "limits.graph_rag_facts_limit": 10,
                           "limits.graph_rag_context_max_chars": 2000})
        rows = [
            {"id": 1, "origin": "chat_history", "fact": "Свежая строка",
             "status": "confirmed", "expires_at": None,
             "created_at": _ts(2026), "message_timestamp": _ts(2026),
             "tg_message_id": 1, "chat_id": CHAT, "item_id": "fact:1"},
            {"id": 2, "origin": "history_import", "fact": "Сосед из 2025",
             "status": "confirmed", "expires_at": None,
             "created_at": _ts(2025), "message_timestamp": _ts(2025),
             "tg_message_id": 2, "chat_id": CHAT, "item_id": "fact:2",
             "period_fill": True, "subject_proxy": "knn"},
            {"id": 3, "origin": "history_import", "fact": "Ремонт ванной 2023",
             "status": "confirmed", "expires_at": None,
             "created_at": _ts(2023), "message_timestamp": _ts(2023),
             "tg_message_id": 3, "chat_id": CHAT, "item_id": "fact:3",
             "period_fill": True, "subject_proxy": "stems"},
        ]
        seen: list = []

        class _Memory:
            async def rerank_rag_facts(self, query, facts):
                seen.append([item[1] for item in facts])
                return []            # валидный пустой выбор модели

        # Гейт реранка — реальная per-chat цепочка 2.58.186 (`_cp_g` → override
        # чата → hot → фабричный дефолт). Заглушка `_cp_g → None` скрывала бы
        # флаг от гейта (chat-слой в тесте не инициализирован) — она убрана,
        # как и в test_mem_time_policy.py релиза 2.58.186.
        service = dcs.DirectChatService(memory=_Memory(), db=None, llm=None,
                                       aliases=None)

        async def fake_rows(*_args, **_kwargs):
            return rows

        monkeypatch.setattr(service, "_rag_unified_rows", fake_rows)
        block, _hint = await service._build_rag_block(
            CHAT, _Msg("что было с ремонтом ванной"), "")
        assert "Ремонт ванной 2023" in block, (
            block, "лексический добор §2 не отправлялся в реранк")
        assert "Свежая строка" not in block
        assert "Сосед из 2025" not in block, (
            block, "knn-строку модель видела — пустой выбор её снимает")
        assert seen, "реранк вызывался"
        assert any("Сосед из 2025" in text for text in seen[0]), seen
        assert all("Ремонт ванной 2023" not in text for text in seen[0]), seen


# ── §1/§5: ОДНА векторная нога на ход (пересборка блока после плана L1) ────


class _PeriodResult:
    """Результат `retrieve`-двойника: строки + телеметрия периодной ноги."""

    def __init__(self, rows=(), meta=None):
        self.fact_rows = tuple(rows)
        self.period_fill = meta


def _base_rows(count=8, year=2026):
    return [{"id": 100 + index, "origin": "history_import",
             "fact": "текущий факт %d" % index, "status": "confirmed",
             "expires_at": None, "created_at": _ts(year),
             "message_timestamp": _ts(year), "tg_message_id": 700 + index,
             "chat_id": CHAT, "item_id": "fact:%d" % (100 + index)}
            for index in range(count)]


def _block_row(fid, year, text, *, period=False, proxy=None):
    row = {"id": fid, "origin": "history_import", "fact": text,
           "status": "confirmed", "expires_at": None,
           "message_timestamp": _ts(year), "created_at": _ts(year),
           "tg_message_id": 900 + fid, "chat_id": CHAT,
           "item_id": "fact:%d" % fid}
    if period:
        row["period_fill"] = True
    if proxy:
        row["subject_proxy"] = proxy
    return row


class TestOnePeriodLegPerTurn:
    """Блок памяти собирается до плана L1 (`auto`), затем пересобирается с
    политикой плана. Периодный пул (embed + KNN k=32 + лексика) обязан
    оплачиваться ОДИН раз за ход; `operative` не добавляет второй ноги."""

    class _Memory:
        async def rerank_rag_facts(self, query, facts):
            return list(facts)

    @staticmethod
    def _wire(monkeypatch, service):
        async def _no_chat_param(*_args, **_kwargs):
            return None

        monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
        calls: list = []

        async def fake_retrieve(db, memory, chat_id, query, channels, limit,
                                policy, **kwargs):
            calls.append({"channels": tuple(channels), "limit": int(limit),
                          "policy": policy, "kwargs": dict(kwargs)})
            if tuple(channels) == ("vector",):
                return _PeriodResult(_base_rows())
            return _PeriodResult((), {"vector_leg": "ok", "vector_rows": 0,
                                      "vector_pool_miss": 1})

        service.db = types.SimpleNamespace(
            search_messages_fts=lambda *a, **k: None)
        monkeypatch.setattr(service, "_rag_retrieve", fake_retrieve)
        return calls

    @staticmethod
    def _period_calls(calls):
        return [call for call in calls if call["kwargs"].get("period_fill")]

    @pytest.mark.asyncio
    async def test_auto_then_historical_pays_one_period_leg(
            self, monkeypatch):
        _hot(monkeypatch, {"flags.graph_rag_enabled": True,
                           "flags.chat_rag_rerank_enabled": False,
                           "memory.nostalgia_layer_a_enabled": False,
                           "limits.graph_rag_facts_limit": 10,
                           "limits.graph_rag_context_max_chars": 2000})
        service = dcs.DirectChatService(memory=self._Memory(), db=None,
                                        llm=None, aliases=None)
        calls = self._wire(monkeypatch, service)
        question = "что было с концертом органной музыки?"
        block, _hint = await service._build_rag_block(
            CHAT, _Msg(question), "", memory_scope="auto")
        period = self._period_calls(calls)
        assert len(period) == 1, (calls, "auto платит одну периодную ногу")
        # Пул — ЛИТЕРАЛЬНО 32: константа реализацией не считается.
        assert period[0]["limit"] == 32, (
            period[0], "пул периодной ноги фиксирован")
        assert service._rag_period_pool, "пул сохранён для пересборки"
        out = await service._apply_plan_memory_scope(
            ["<Current_Question>%s</Current_Question>" % question, block],
            {"chat_id": CHAT, "message": _Msg(question), "global_ctx": ""},
            types.SimpleNamespace(memory_scope="historical"))
        period = self._period_calls(calls)
        assert len(period) == 1, (
            calls, "пересборка НЕ платит вторую векторную ногу")
        assert [call["policy"] for call in period] == ["auto"]
        assert period[0]["limit"] == 32
        assert period[0]["kwargs"].get("period_fill") is True
        base = [call for call in calls if call["channels"] == ("vector",)]
        assert len(base) == 2, "основной срез строится в обоих проходах"
        assert out and out[-1].startswith("<RAG_Memory>"), out
        # Окно пересборки закрыто: между ходами пул не переиспользуется.
        assert service._rag_period_reuse is None
        assert service._rag_period_pool is None

    @pytest.mark.asyncio
    async def test_auto_then_operative_pays_one_period_leg(
            self, monkeypatch):
        _hot(monkeypatch, {"flags.graph_rag_enabled": True,
                           "flags.chat_rag_rerank_enabled": False,
                           "memory.nostalgia_layer_a_enabled": False,
                           "limits.graph_rag_facts_limit": 10,
                           "limits.graph_rag_context_max_chars": 2000})
        service = dcs.DirectChatService(memory=self._Memory(), db=None,
                                        llm=None, aliases=None)
        calls = self._wire(monkeypatch, service)
        question = "что сейчас происходит в чате?"
        block, _hint = await service._build_rag_block(
            CHAT, _Msg(question), "", memory_scope="auto")
        out = await service._apply_plan_memory_scope(
            ["<Current_Question>%s</Current_Question>" % question, block],
            {"chat_id": CHAT, "message": _Msg(question), "global_ctx": ""},
            types.SimpleNamespace(memory_scope="operative"))
        period = self._period_calls(calls)
        assert len(period) == 1, (
            calls, "operative-план не добавляет второй периодной ноги")
        operative_base = [call for call in calls
                          if call["channels"] == ("vector",)
                          and call["policy"] == "operative"]
        assert len(operative_base) == 1, calls
        assert out and out[-1].startswith("<RAG_Memory>"), out


class TestPeriodKeptTelemetry:
    """§4: `period_kept` = сколько периодных строк ФАКТИЧЕСКИ показано."""

    class _Msg:
        def __init__(self, text):
            self.text = text

    @staticmethod
    def _service(monkeypatch, memory, rows):
        service = dcs.DirectChatService(memory=memory, db=None, llm=None,
                                        aliases=None)

        # Гейт реранка — реальная per-chat цепочка 2.58.186 (см. выше): стаб
        # `_cp_g → None` превращал бы флаг ON в OFF и обесценивал телеметрию.
        async def fake_rows(*_args, **_kwargs):
            return rows

        monkeypatch.setattr(service, "_rag_unified_rows", fake_rows)
        return service

    @staticmethod
    def _log(monkeypatch, service, query):
        import logging

        captured: list = []

        class _Handler(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())

        handler = _Handler()
        logger = logging.getLogger("services.direct_chat_service")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        loop = asyncio.new_event_loop()
        try:
            block, _hint = loop.run_until_complete(service._build_rag_block(
                CHAT, TestPeriodKeptTelemetry._Msg(query), ""))
        finally:
            logger.removeHandler(handler)
            loop.close()
        line = next((item for item in captured
                     if item.startswith("direct: rag block")), "")
        return block, line

    def test_period_kept_rerank_off_counts_rendered_row(self, monkeypatch):
        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": False,
                           "memory.nostalgia_layer_a_enabled": False})

        class _Memory:
            async def rerank_rag_facts(self, query, facts):
                raise AssertionError("реранк выключен")

        rows = [_block_row(1, 2026, "Текущее событие про отпуск"),
                _block_row(3, 2023, "Старое событие про переезд",
                           period=True, proxy="stems")]
        service = self._service(monkeypatch, _Memory(), rows)
        block, line = self._log(monkeypatch, service, "что было с отпуском")
        assert "переезд" in block, block
        assert "period_kept=1" in line, (line, "показанная строка — 1")
        assert "period_kept_despite_empty=0" in line, line

    def test_period_kept_rerank_on_counts_chosen_knn_row(self, monkeypatch):
        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": True,
                           "memory.nostalgia_layer_a_enabled": False})

        class _Memory:
            async def rerank_rag_facts(self, query, facts):
                return list(facts)          # модель выбрала всё, включая knn

        rows = [_block_row(1, 2026, "Текущее событие про отпуск"),
                _block_row(3, 2023, "Сосед про отпуск",
                           period=True, proxy="knn")]
        service = self._service(monkeypatch, _Memory(), rows)
        block, line = self._log(monkeypatch, service, "что было с отпуском")
        assert "Сосед про отпуск" in block, block
        assert "period_kept=1" in line, (line, "knn-строка выбрана моделью")
        assert "period_kept_despite_empty=0" in line, line

    def test_period_kept_despite_empty_stays_separate(self, monkeypatch):
        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": True,
                           "memory.nostalgia_layer_a_enabled": False})

        class _Memory:
            async def rerank_rag_facts(self, query, facts):
                return []

        rows = [_block_row(1, 2026, "Текущее событие про отпуск"),
                _block_row(3, 2023, "Старое событие про переезд",
                           period=True, proxy="stems")]
        service = self._service(monkeypatch, _Memory(), rows)
        block, line = self._log(monkeypatch, service, "что было с отпуском")
        assert "переезд" in block, block
        assert "period_kept=1" in line, line
        assert "period_kept_despite_empty=1" in line, line
