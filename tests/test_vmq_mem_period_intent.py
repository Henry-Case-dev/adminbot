"""VMQ-MEM/TIME Slice A — периодный intent, сохранение целевого года, честная
векторная нога.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/root-cause-2026-11-15.md`
§4 (Slice A), `measurement-2026-11-15.md` §4/§8.

Покрытие (CONTRACT/REGRESSION):
  * явный год вопроса: строки ЦЕЛЕВОГО года сохраняются в периодном пуле
    (прежний порог §2 отклонял 15 из 16 и терял все 13 строк 2023);
  * строка другого года (2026) не выдаёт себя за 2023 — отсев с кодом
    причины `out_of_target_year`, а не молчаливая подмена;
  * точная owner-формулировка («…рассказ…») разрешается как историческое
    намерение и получает ОГРАНИЧЕННЫЙ вклад старого периода; одна слабая
    строка блок не собирает (действующий контракт §2/§5);
  * «что сейчас» остаётся `none`: словаря «сейчас» нет, свежесть доминирует;
  * векторная нога: `insufficient` → честный `vector_unavailable` + причина и
    НИ ОДНОГО вызова KNN; `compatible`/`admitted` → нога участвует;
  * причины отсева согласованы: строки = принятые + dropped_* (+ cap),
    каждый принятый id принадлежит реально поданным строкам (нет fabrication).

TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/vmq-mem Slice A
R17: только синтетические факты/векторы, никаких реальных переписок.
"""
import asyncio
import calendar
import time
import types

import pytest

from services import direct_chat_service as dcs
from services import hot_config as hot
from services import mca_retrieval_context as mrc
from services.database import DatabaseService
from services.summary_memory import MemoryManager

CHAT = -100
DIM = 8
SLOT_DIV = 5


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


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


async def _memory(db, monkeypatch):
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        pytest.skip("sqlite-vec not installed")

    async def _probe_fixed(self):
        return False

    monkeypatch.setattr(MemoryManager, "_probe_vec_int8", _probe_fixed)
    monkeypatch.setattr(hot, "_cache", _FakeHotCache({}))
    memory = MemoryManager(db, VecLLM())

    async def _noop_backfill() -> int:
        return 0

    memory.backfill_archive_vectors = _noop_backfill
    memory.backfill_graph_fact_vectors = _noop_backfill
    if not await memory.initialize():
        pytest.skip("sqlite-vec extension could not be loaded")
    return memory


async def _seed(db, memory, text, vector, *, year=2026, chat_id=CHAT,
                origin="chat_history"):
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
    memory.llm.vec_map[text] = vector
    await memory._insert_graph_vec_row(fact_id, chat_id, text, origin, None,
                                       vector)
    return fact_id


def _row(fid, text, *, year=None, source="lexical", ts=None):
    row = {"id": fid, "fact": text, "origin": "history_import",
           "status": "confirmed", "expires_at": None,
           "created_at": _ts(year) if year else ts,
           "message_timestamp": _ts(year) if year else ts,
           "tg_message_id": 800 + fid, "chat_id": CHAT,
           "item_id": f"fact:{fid}"}
    if source:
        row["period_source"] = source
        row["subject_proxy"] = "knn" if source == "vector" else "stems"
    return row


CONFLICT_2023 = "из-за чего мы ссорились и ругались в 2023 году"
OWNER_CREATIVE = "напиши юмористический рассказ об основных шизах конфы"
CURRENT_STATE = "что сейчас происходит с E1?"


# ── §1: структурированное периодное намерение ──────────────────────────────


class TestPeriodIntentResolution:
    def test_explicit_year_wins_and_is_structured(self):
        intent = mrc.resolve_period_intent(CONFLICT_2023)
        assert intent.kind == mrc.PERIOD_INTENT_YEAR
        assert intent.years == (2023,)
        assert intent.source == "query_year"
        assert intent.is_explicit_year is True
        # Год старше 2000 и «не год» (id/число) не путаются.
        assert mrc.resolve_period_intent("напомни 15.06.2023").years == (2023,)
        assert mrc.resolve_period_intent("посмотри id 20231").kind == \
            mrc.PERIOD_INTENT_NONE

    def test_owner_creative_formulation_is_historical(self):
        """«рассказ» — не маркер `_HISTORY_MARKERS`, но периодное намерение
        обязано распознать повествовательный запрос (Slice A)."""
        intent = mrc.resolve_period_intent(OWNER_CREATIVE)
        assert intent.kind == mrc.PERIOD_INTENT_HISTORICAL
        assert intent.source == "query_marker"

    def test_plain_question_and_current_state_stay_none(self):
        """«что за шизы были…» и «что сейчас…» — не исторический период:
        словаря «сейчас» нет, ослабления текущего пути нет."""
        for query in ("что за шизы были на конфе?", CURRENT_STATE):
            intent = mrc.resolve_period_intent(query)
            assert intent.kind == mrc.PERIOD_INTENT_NONE, query

    def test_memory_scope_historical_is_intent(self):
        intent = mrc.resolve_period_intent("общий вопрос", memory_scope="historical")
        assert intent.kind == mrc.PERIOD_INTENT_HISTORICAL
        assert intent.source == "memory_scope"


# ── §1 (дефект D): явный 2023 сохраняется, 2026 не маскируется ──────────────


def _2023_pool():
    """13 строк 2023 (документированный пул измерения) + 3 агрессивные 2026.

    Строки 2023 слабо пересекаются с вопросом (0–1 общая основа) — именно их
    прежний порог §2 отклонял (15 из 16), теряя весь целевой год."""
    weak = [
        "вы тогда сильно поругались из-за ерунды",
        "потом помирились и обсуждали планы",
        "в чате была тишина и обиды",
        "кто-то ушёл и вернулся через день",
        "спорили о встрече и деньгах",
        "долго не разговаривали друг с другом",
        "было неприятно и шумно",
        "переругались и всё обсудили",
        "конфликт закончился миром",
        "серьёзный разговор состоялся вечером",
        "неделя выдалась нервной",
        "потом всё стало спокойно",
        "история закончилась примирением",
    ]
    rows = [_row(1000 + i, text, year=2023) for i, text in enumerate(weak)]
    # 2026-строки с максимальным предметным совпадением: не должны попасть.
    rows.append(_row(3001, "ссорились и ругались в 2023 очень сильно",
                     year=2026))
    rows.append(_row(3002, "мы ссорились и ругались каждый день", year=2026))
    rows.append(_row(3003, "ругались ссорились и обижались", year=2026))
    return rows


class TestExplicitYearPreserved:
    def test_target_year_survives_subject_threshold(self):
        """RED на базе: 13 строк 2023 в пуле → 0 принятых. GREEN: целевой год
        сохраняется, порядок — по числу общих основ."""
        accepted, rejected = dcs.DirectChatService._rag_period_subject_filter(
            CONFLICT_2023, _2023_pool())
        ids = [row["id"] for row in accepted]
        assert ids, "целевой год 2023 не должен теряться целиком"
        assert all(1000 <= fid < 2000 for fid in ids), ids
        assert rejected == 0
        assert all(row["stems_shared_reason"] == mrc.PERIOD_KEEP_IN_TARGET
                   for row in accepted)

    def test_2026_rows_do_not_masquerade_as_2023(self):
        pool = _2023_pool()
        accepted, _rejected = dcs.DirectChatService._rag_period_subject_filter(
            CONFLICT_2023, pool)
        assert not {3001, 3002, 3003} & {row["id"] for row in accepted}
        _accepted, stats = mrc.select_period_rows(
            pool, query=CONFLICT_2023, policy="auto", slots=2)
        assert stats["dropped_out_of_target_year"] == 3
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_YEAR
        assert stats["intent"]["years"] == [2023]

    def test_unknown_time_is_fail_closed_for_explicit_year(self):
        pool = [_row(1, "ссорились и ругались", ts=None),
                _row(2, "ругались и ссорились", year=2023)]
        accepted, stats = mrc.select_period_rows(
            pool, query=CONFLICT_2023, policy="auto", slots=2)
        assert [row["id"] for row in accepted] == [2]
        assert stats["dropped_unknown_year"] == 1
        assert pool[0]["stems_shared_reason"] == mrc.PERIOD_DROP_UNKNOWN_YEAR

    @pytest.mark.asyncio
    async def test_measurement_shape_pool_keeps_target_year(self, db, monkeypatch):
        """Форма документированного пула D (13 строк 2023 + 3 строки 2026).

        На базе после порога §2 в выдаче оставались ТОЛЬКО строки 2026, а все
        13 строк целевого года терялись. Здесь проверяется весь путь:
        FTS-пул → фильтр явного года в `retrieve` → отбор потребителя →
        добор в срез (`limit//5` слотов)."""
        memory = await _memory(db, monkeypatch)
        old_ids = []
        for index in range(13):
            old_ids.append(await _seed(
                db, memory, f"ругались из-за ерунды номер {index}",
                _mix(0.2 + index / 100.0, 0.3), year=2023))
        fresh_ids = []
        for index in range(3):
            fresh_ids.append(await _seed(
                db, memory, f"ссорились и ругались очень сильно {index}",
                _unit(index), year=2026))
        _compat(monkeypatch, state="insufficient",
                reason="compat_not_proven", cls="COMPATIBILITY_UNKNOWN",
                action="retry_canary")
        request = mrc.RetrievalRequest(
            chat_id=CHAT, query=CONFLICT_2023, mode="specific",
            purpose="reply", top_k=32, channels=("lexical", "vector"),
            reply_depth=0, memory_scope="auto", lexical_stem=True,
            include_archived=True, include_self=True,
            include_direct_reply=True, preserve_channel_order=True,
            period_fill=True, exclude_years=())
        result = await mrc.retrieve(db, memory, request)
        delivered = {int(row["id"]) for row in result.fact_rows}
        assert delivered == set(old_ids), (
            "в пуле периода обязаны остаться только строки целевого года")
        fill = result.period_fill
        assert fill["rows_in_target"] == 13
        assert fill["dropped_out_of_target_year"] == 3
        accepted, selection = mrc.select_period_rows(
            [dict(row) for row in result.fact_rows], query=CONFLICT_2023,
            policy="auto", slots=2)
        assert selection["kept_in_target"] == len(accepted) >= 8
        assert selection["dropped_subject"] == 0
        base = [_row(900 + i, f"текущий факт {i}", year=2026) for i in range(8)]
        block = dcs.DirectChatService._rag_append_period_rows(
            base, accepted, 10, slots=2)
        appended = block[len(base):]
        assert appended, "строки 2023 обязаны доехать до среза"
        assert {mrc.period_row_year(row) for row in appended} == {2023}
        assert not set(fresh_ids) & {row["id"] for row in appended}

    @pytest.mark.asyncio
    async def test_retrieval_period_pool_filters_out_of_target_years(
            self, db, monkeypatch):
        """Интеграция `retrieve(period_fill=True)`: в выданном пуле только
        целевой год, причины отсева — в `usage_json.period_fill`."""
        memory = await _memory(db, monkeypatch)
        old = await _seed(db, memory, "ругались из-за ерунды", _mix(0.5, 0.5),
                          year=2023)
        fresh = await _seed(db, memory, "ссорились и ругались каждый день",
                            _unit(0), year=2026)
        # Векторная нога не участвует (детерминированно лексический путь):
        # отказ допуска честно назван и не маскируется.
        _compat(monkeypatch, state="insufficient",
                reason="compat_not_proven", cls="COMPATIBILITY_UNKNOWN",
                action="retry_canary")
        request = mrc.RetrievalRequest(
            chat_id=CHAT, query=CONFLICT_2023, mode="specific",
            purpose="reply", top_k=32, channels=("lexical", "vector"),
            reply_depth=0, memory_scope="auto", lexical_stem=True,
            include_archived=True, include_self=True,
            include_direct_reply=True, preserve_channel_order=True,
            period_fill=True, exclude_years=())
        result = await mrc.retrieve(db, memory, request)
        years = {mrc.period_row_year(row) for row in result.fact_rows}
        ids = {int(row["id"]) for row in result.fact_rows}
        assert old in ids and fresh not in ids, ids
        assert years == {2023}, years
        fill = result.period_fill
        assert fill["period_intent"]["kind"] == mrc.PERIOD_INTENT_YEAR
        assert fill["period_intent"]["years"] == [2023]
        assert fill["rows_in_target"] >= 1
        # 2026-строка была в пуле и отсечена кодом причины, а не «повезло».
        assert fill["dropped_out_of_target_year"] >= 1


# ── TIME-03: год не выбирает и не исключает строки ───────────────────────


class TestNaturalYearSelection:
    """TIME-03 (контракт 2026-11-20 §3.3/§4.2): прямой отбор не исключает год
    базового среза, не требует «другого года» и не сортирует по возрасту."""

    def test_t4_yearless_pool_keeps_relevant_year_including_current(self):
        pool = [_row(1, "шизы и конф в 2026", year=2026),
                _row(2, "шизы и конф в 2023", year=2023)]
        accepted, stats = mrc.select_period_rows(
            pool, query="что было про шизы и конф?", policy="auto",
            slots=2, review=True, reference_year=2026)
        assert [row["id"] for row in accepted] == [1, 2], (
            "текущий год не исключается и не заменяется «другим»")
        assert stats["dropped_out_of_target_year"] == 0
        assert stats["historical_quota"] == 0
        assert stats["multi_year_quota"] == 0
        assert {mrc.period_row_year(row) for row in accepted} == {2023, 2026}

    def test_t4_weak_old_row_enters_by_meaning_not_by_year(self):
        """Review-путь: при ≥2 строках «одного предмета» старая 2023 входит
        по основам, а не потому, что она старый год."""
        pool = [_row(3, "шизы обсуждали", year=2023),
                _row(4, "шизы вспоминали", year=2024),
                _row(5, "совсем другая тема", year=2025)]
        accepted, stats = mrc.select_period_rows(
            pool, query="что было про шизы и конф?", policy="auto",
            slots=2, review=True)
        assert {row["id"] for row in accepted} == {3, 4}
        assert stats["soft_fallback"] == 2
        assert stats["dropped_subject"] == 1
        assert stats["dropped_out_of_target_year"] == 0

    def test_t5_explicit_year_is_target_filter_not_calendar_quota(self):
        pool = [_row(11, "конфликт на конфе", year=2023),
                _row(12, "ссорились и ругались на конфе", year=2023),
                _row(13, "ссорились и ругались на конфе", year=2026)]
        accepted, stats = mrc.select_period_rows(
            pool, query=CONFLICT_2023, policy="auto", slots=2,
            reference_year=2026)
        assert {row["id"] for row in accepted} == {11, 12}
        # Порядок — число общих основ, а не год.
        assert accepted[0]["id"] == 12
        assert stats["dropped_out_of_target_year"] == 1
        assert stats["kept_in_target"] == 2
        assert stats["historical_quota"] == 0

    def test_t6_operative_keeps_only_current_year(self):
        pool = [_row(21, "происходит сейчас", year=2026),
                _row(22, "происходило раньше", year=2025)]
        accepted, stats = mrc.select_period_rows(
            pool, query="что сейчас происходит?", policy="operative",
            slots=2, reference_year=2026)
        assert [row["id"] for row in accepted] == [21]
        assert stats["dropped_out_of_target_year"] == 1




class TestHistoricalSoftFallback:
    def test_bounded_fallback_needs_two_rows(self):
        pool = [_row(1, "конфа была шумной", year=2023),
                _row(2, "рассказ получился смешным", year=2022),
                _row(3, "конфликт на конфе", year=2024),
                _row(4, "вообще не по теме", year=2021)]
        accepted, stats = mrc.select_period_rows(
            pool, query=OWNER_CREATIVE, policy="auto", slots=2)
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_HISTORICAL
        assert stats["soft_fallback"] == 2
        # TIME-03 (контракт 2026-11-20 §3.3): порядок — смысл (`-shared`),
        # затем индекс пула; год не выбирает строки. Обе строки делят с
        # вопросом по одной основе, поэтому входят пуловым порядком 2023→2022.
        assert {row["id"] for row in accepted} == {1, 2}
        assert [mrc.period_row_year(row) for row in accepted] == [2023, 2022]
        assert all(row["stems_shared_reason"] ==
                   mrc.PERIOD_KEEP_SOFT_FALLBACK for row in accepted)
        assert stats["dropped_subject"] == 2

    def test_single_weak_row_does_not_assemble_block(self):
        """Действующий контракт §2/§5: одна слабая строка блок не собирает."""
        # RC4 (A2): «шизы» и «шизах» — один short-стем «шиз», поэтому прежний
        # текст даёт 2 общих стема и законно проходит порог. Слабая строка —
        # ровно 1 общий стем (порог PERIOD_MIN_SHARED_STEMS=2 не менялся).
        accepted, stats = mrc.select_period_rows(
            [_row(1, "обсуждали на конфе", year=2023)],
            query=OWNER_CREATIVE, policy="auto", slots=2)
        assert accepted == []
        assert stats["soft_fallback"] == 0
        assert stats["dropped_subject"] == 1

    def test_strict_match_is_not_replaced_by_fallback(self):
        """Если порог §2 уже дал строку, fallback не подмешивает шум."""
        pool = [_row(1, "шизы конфе рассказ", year=2023),
                _row(2, "шиза была знатная", year=2022)]
        accepted, stats = mrc.select_period_rows(
            pool, query=OWNER_CREATIVE, policy="auto", slots=2)
        assert [row["id"] for row in accepted] == [1]
        assert stats["soft_fallback"] == 0
        assert stats["dropped_subject"] == 1

    def test_owner_formulation_contributes_bounded_old_rows(self):
        """Точная owner-формулировка: вклад старого периода ограничен слотами
        и попадает в срез как `period_fill` (не как «факты текущего»)."""
        pool = [_row(1, "шизы на конфе обсуждали", year=2023),
                _row(2, "шиза была знатная", year=2022),
                _row(3, "шиза на конфе", year=2024)]
        accepted, _stats = dcs.DirectChatService._rag_period_subject_filter(
            OWNER_CREATIVE, pool)
        base = [_row(100 + i, f"текущий факт {i}", year=2026) for i in range(8)]
        limit = 10
        slots = max(1, limit // SLOT_DIV)
        block = dcs.DirectChatService._rag_append_period_rows(
            base, accepted, limit, slots=slots)
        added = block[len(base):]
        assert added, "старый период не дошёл до среза"
        assert len(added) <= slots
        assert {mrc.period_row_year(row) for row in added} <= {2022, 2023, 2024}
        assert all(row.get("period_fill") for row in added)


# ── §4: текущее состояние не ослаблено ─────────────────────────────────────


class TestCurrentStateControl:
    def test_one_stem_row_is_still_rejected(self):
        accepted, rejected = dcs.DirectChatService._rag_period_subject_filter(
            CURRENT_STATE, [_row(8436, "выгнали сами и ноют сейчас", year=2025)])
        assert accepted == []
        assert rejected == 1

    def test_fresh_slice_dominates_and_no_period_rows(self):
        """«что сейчас»: периодный пул не даёт строк — срез остаётся 2026."""
        accepted, _rejected = dcs.DirectChatService._rag_period_subject_filter(
            CURRENT_STATE, [_row(8436, "выгнали сами и ноют сейчас", year=2025)])
        base = [_row(100 + i, f"текущий факт {i}", year=2026) for i in range(8)]
        block = dcs.DirectChatService._rag_append_period_rows(
            base, accepted, 10, slots=2)
        assert block == base
        assert {mrc.period_row_year(row) for row in block} == {2026}


# ── §1: векторная нога — только после допуска, иначе честный отказ ─────────


def _compat(monkeypatch, *, state, reason="", cls="", action=""):
    async def _resolve(*_args, **_kwargs):
        return {"state": state, "reason_code": reason, "class": cls,
                "action": action, "admission": None, "serviceable":
                state == "compatible"}

    monkeypatch.setattr(
        "services.embedding_control_plane.resolve_index_compat", _resolve)


def _period_request(**overrides):
    base = dict(
        chat_id=CHAT, query=CONFLICT_2023, mode="specific", purpose="reply",
        top_k=32, channels=("lexical", "vector"), reply_depth=0,
        memory_scope="auto", lexical_stem=True, include_archived=True,
        include_self=True, include_direct_reply=True,
        preserve_channel_order=True, period_fill=True, exclude_years=(2026,))
    base.update(overrides)
    return mrc.RetrievalRequest(**base)


class TestVectorAdmission:
    @staticmethod
    def _spy(memory):
        calls: list = []
        original = memory.period_fill_candidates

        async def _leg(*args, **kwargs):
            calls.append(kwargs)
            return await original(*args, **kwargs)

        memory.period_fill_candidates = _leg
        return calls

    @pytest.mark.asyncio
    async def test_insufficient_admission_is_honest_and_skips_leg(
            self, db, monkeypatch):
        """`insufficient/compat_not_proven` — ровно наблюдённое состояние
        probe-копии: нога не вызывается, отказ назван, лексика работает."""
        memory = await _memory(db, monkeypatch)
        old = await _seed(db, memory, "ругались из-за ерунды", _mix(0.5, 0.5),
                          year=2023)

        async def _compat(*_args, **_kwargs):
            return {"state": "insufficient", "reason_code": "compat_not_proven",
                    "class": "COMPATIBILITY_UNKNOWN", "action": "retry_canary",
                    "admission": None, "serviceable": False}

        monkeypatch.setattr(
            "services.embedding_control_plane.resolve_index_compat", _compat)
        calls = self._spy(memory)
        result = await mrc.retrieve(db, memory, _period_request())
        fill = result.period_fill
        assert calls == [], "недопущенная нога не должна выполнять KNN"
        assert fill["vector_unavailable"] == 1
        assert fill["vector_unavailable_reason"] == "compat_not_proven"
        assert fill["vector_admission"]["state"] == "insufficient"
        assert fill["vector_admission"]["proven"] is False
        assert fill["vector_leg"] == "compat_not_proven"
        ids = {int(row["id"]) for row in result.fact_rows}
        assert old in ids, "лексический путь обязан остаться рабочим"

    @pytest.mark.asyncio
    async def test_compatible_admission_lets_leg_participate(self, db, monkeypatch):
        memory = await _memory(db, monkeypatch)
        old = await _seed(db, memory, "ругались из-за ерунды", _mix(0.9, 0.2),
                          year=2023)
        _compat(monkeypatch, state="compatible", cls="ADMITTED_COMPATIBLE")
        calls = self._spy(memory)
        query_vec = _mix(0.9, 0.2)
        memory.llm.vec_map[CONFLICT_2023] = query_vec
        result = await mrc.retrieve(db, memory, _period_request())
        fill = result.period_fill
        assert len(calls) == 1, "допущенная нога выполняется один раз"
        assert fill["vector_admission"]["admitted"] is True
        assert fill["vector_admission"]["proven"] is True
        assert fill["vector_unavailable"] == 0
        assert fill["vector_leg"] == "ok"
        assert fill["vector_rows"] >= 1
        assert old in {int(row["id"]) for row in result.fact_rows}

    @pytest.mark.asyncio
    async def test_missing_admission_registry_defers_to_existing_gate(
            self, db, monkeypatch):
        """`no_generation` — доказательства нет ни в одну сторону: решает
        прежний гейт A06 внутри MemoryManager (не строже основного KNN),
        но `proven=False` не выдаётся за допуск."""
        memory = await _memory(db, monkeypatch)
        await _seed(db, memory, "ругались из-за ерунды", _mix(0.5, 0.5),
                    year=2023)

        async def _accept(_self):
            return ""

        async def _compat(*_args, **_kwargs):
            return {"state": "no_generation", "reason_code": "no_generation",
                    "class": "", "action": "register_generation",
                    "admission": None, "serviceable": False}

        monkeypatch.setattr(MemoryManager, "_period_vector_guard", _accept)
        monkeypatch.setattr(
            "services.embedding_control_plane.resolve_index_compat", _compat)
        memory.llm.vec_map[CONFLICT_2023] = _mix(0.5, 0.5)
        result = await mrc.retrieve(db, memory, _period_request())
        fill = result.period_fill
        assert fill["vector_admission"]["state"] == "no_generation"
        assert fill["vector_admission"]["admitted"] is None
        assert fill["vector_admission"]["proven"] is False
        assert fill["vector_leg"] == "ok"


# ── причины отсева согласованы, источник не выдуман ────────────────────────


class TestReasonCodedDrops:
    def test_counts_add_up_and_sources_are_real(self):
        pool = _2023_pool() + [_row(4001, "без времени", ts=None)]
        accepted, stats = mrc.select_period_rows(
            pool, query=CONFLICT_2023, policy="auto", slots=2)
        assert stats["rows"] == len(pool)
        assert stats["rows"] == (stats["kept"]
                                 + stats["dropped_out_of_target_year"]
                                 + stats["dropped_unknown_year"]
                                 + stats["dropped_pool_cap"])
        input_ids = {row["id"] for row in pool}
        assert {row["id"] for row in accepted} <= input_ids
        reasons = {row["stems_shared_reason"] for row in pool}
        assert mrc.PERIOD_DROP_OUT_OF_TARGET_YEAR in reasons
        assert mrc.PERIOD_DROP_UNKNOWN_YEAR in reasons

    def test_pool_cap_is_recorded_not_silent(self):
        pool = [_row(2000 + i, f"ругались ссорились {i}", year=2023)
                for i in range(20)]
        accepted, stats = mrc.select_period_rows(
            pool, query=CONFLICT_2023, policy="auto", slots=2)
        assert len(accepted) == max(4, 2 * 4)
        assert stats["dropped_pool_cap"] == len(pool) - len(accepted)
