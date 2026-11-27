"""P-OLDROW — доставка старшего периода в вопросе о человеке.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/selector-rootcause-
2026-11-27.md` §3 (R1/R2/R3), §5 (RED/GREEN), §6 (мутации M1–M8).
База RED: deployed `9516c9125` (2.58.257).

Дефект (измерен на снимке `450604f1…`): у вопроса о человеке без года
периодный селектор принимал только строки 2026; старая subject-bound строка
имела одну общую основу и уходила в `dropped_subject`; `author_window`
требовал явного года; `auto` вообще не запускал периодный добор. Итог —
10/10 фактов и 9–10 строк 2026 при существующем материале 2023–2025.

Покрытие (CONTRACT):
  * R1: 3 строгих строки 2026 + 2 мягких старых, `slots=2` — ровно ОДНА
    строка старшего периода входит в первые слоты, помечена `reserved_old`,
    длина `accepted` не превышает `max(прежняя, slots)`;
  * `reserve_period_append` доставляет помеченную строку даже при смешанных
    годах верхних слотов, бюджет не растёт;
  * R2: `author_window` исполняется по РАЗРЕШЁННОМУ субъекту (точный uid),
    ограничен `limit//5` и распределён по трём завершённым годам;
    `_collect_originals` ставит авторские сообщения первыми;
  * R3: `resolve_period_intent(subject_present, current_state)` даёт
    `multi_year/subject_scope`, `PERIOD_REPLACE_SOURCES` не расширяется,
    прямой путь разрешает `breadth_reason="subject_scope"`;
  * контроли: «что сейчас»/`operative`/явный год не меняются; одна мягкая
    строка блок не собирает; безымянная (unattributed) строка не
    атрибутируется; календарные квоты остаются 0.

TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/vmq-mem P-OLDROW
R17: только синтетические факты/сообщения, никаких реальных переписок.
"""
import asyncio
import calendar
import types

import pytest

from services import direct_chat_service as dcs
from services import hot_config as hot
from services import mca_retrieval_context as mrc
from services.database import DatabaseService

CHAT = -1002661910336
UID = 485008070
NAME = "Аню"
PERSON_QUERY = "что ты знаешь про Аню и конфу?"
CURRENT_QUERY = "что сейчас происходит про Аню?"


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


def _row(fid, text, *, year=None, subject_uid=UID, target_user="",
         weight=0.5, importance=4, status="confirmed", ts=None):
    row = {"id": fid, "fact": text, "origin": "history_import",
           "status": status, "expires_at": None,
           "created_at": _ts(year) if year else ts,
           "message_timestamp": _ts(year) if year else ts,
           "weight": weight, "importance": importance,
           "tg_message_id": 800 + fid, "chat_id": CHAT,
           "item_id": f"fact:{fid}", "period_source": "lexical",
           "subject_proxy": "stems"}
    if subject_uid is not None:
        row["speaker_author_id"] = int(subject_uid)
    if target_user:
        row["target_user"] = target_user
    return row


def _base_rows(count=10, ids=None):
    ids = list(ids or range(8000, 8000 + count))
    return [{"id": fid, "fact": f"текущий факт {index}",
             "origin": "chat_history", "status": "confirmed",
             "created_at": _ts(2026), "message_timestamp": _ts(2026),
             "rag_ts": _ts(2026), "chat_id": CHAT,
             "item_id": f"fact:{fid}"}
            for index, fid in enumerate(ids)]


def _strict_pool(years=(2026, 2026, 2026), first_id=9100):
    """Строгие строки: 2 общих основы с вопросом о человеке."""
    return [_row(first_id + index, "про Аню и конфу говорили в чате",
                 year=year) for index, year in enumerate(years)]


def _soft_old_pool():
    """Мягкие строки старшего периода: ровно одна общая основа."""
    return [_row(9201, "про Аню вспоминали", year=2025),
            _row(9202, "конфу вспоминали часто", year=2024)]


class _Result:
    def __init__(self, fact_rows, period_fill=None, candidates=()):
        self.fact_rows = tuple(fact_rows)
        self.period_fill = period_fill
        self.candidates = tuple(candidates)


class _FakeHot:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


def _service(monkeypatch, base_rows, period_rows, calls=None):
    monkeypatch.setattr(hot, "_cache", _FakeHot(
        {"limits.graph_rag_facts_limit": len(base_rows)}))
    db = types.SimpleNamespace(search_messages_fts=lambda *a, **k: None)
    service = dcs.DirectChatService(memory=object(), db=db, llm=None,
                                    aliases=None)
    calls = calls if calls is not None else []

    async def fake(_db, _memory, chat_id, query, channels, limit, policy,
                   *, period_fill=False, period_intent=None, **_kwargs):
        calls.append({"period_fill": bool(period_fill),
                      "channels": tuple(channels),
                      "subject_uids": tuple(_kwargs.get("subject_uids") or ()),
                      "author_uids": tuple(_kwargs.get("author_uids") or ()),
                      "intent": (period_intent.as_dict()
                                 if period_intent else None)})
        if period_fill:
            return _Result(period_rows,
                           {"vector_leg": "compat_not_proven",
                            "vector_rows": 0})
        return _Result(base_rows)

    monkeypatch.setattr(service, "_rag_retrieve", fake)
    service._oldrow_calls = calls
    return service


def _stub(text):
    return types.SimpleNamespace(text=text, chat_id=CHAT, message_id=0)


# ── R1: один зарезервированный старший период ─────────────────────────────


class TestSelectorReservesOneOldRow:
    def test_three_strict_plus_two_soft_reserves_exactly_one(self):
        """M1/M4: 3 строгих 2026 + 2 мягких старых, slots=2.

        RED на базе: старая строка уходит в `dropped_subject`, `reserved_old=0`.
        GREEN: ровно одна строка старшего периода в первых слотах, длина
        `accepted` не больше `max(прежняя, slots)`, квоты остаются нулями."""
        pool = _strict_pool() + _soft_old_pool()
        accepted, stats = mrc.select_period_rows(
            pool, query=PERSON_QUERY, policy="historical", slots=2)
        marked = [row for row in accepted if row.get("reserved_old")]
        assert len(marked) == 1, accepted
        assert mrc.period_row_year(marked[0]) == 2025, (
            "ближайший старший год выбирается первым")
        assert stats["reserved_old"] == 1
        assert stats["reserved_displaced"] == 1
        assert len(accepted) == 3, "длина не выросла сверх прежней"
        assert any(row is marked[0] for row in accepted[:2]), (
            "помеченная строка обязана быть в первых slots")
        assert stats["historical_quota"] == 0
        assert stats["multi_year_quota"] == 0

    def test_single_soft_row_does_not_reserve(self):
        """M2: одна мягкая строка блок не собирает (контракт §2/§5)."""
        pool = _strict_pool() + [_soft_old_pool()[0]]
        accepted, stats = mrc.select_period_rows(
            pool, query=PERSON_QUERY, policy="historical", slots=2)
        assert stats.get("reserved_old", 0) == 0
        assert not any(row.get("reserved_old") for row in accepted)
        assert {mrc.period_row_year(row) for row in accepted} == {2026}

    def test_unattributed_old_row_is_not_attributed(self):
        """M5: строка импорта без привязки к субъекту не атрибутируется."""
        unattributed = [
            _row(9301, "про Аню вспоминали", year=2025, subject_uid=None),
            _row(9302, "конфу вспоминали часто", year=2024, subject_uid=None),
        ]
        pool = _strict_pool() + unattributed
        accepted, stats = mrc.select_period_rows(
            pool, query=PERSON_QUERY, policy="historical", slots=2,
            subject_uids=(UID,), subject_names=(NAME,))
        assert stats.get("reserved_old", 0) == 0, (
            "безымянная строка не становится сведением о человеке")
        assert {mrc.period_row_year(row) for row in accepted} == {2026}
        # Контроль: та же строка с реальной привязкой (точный uid) входит.
        bound = [
            _row(9301, "про Аню вспоминали", year=2025, subject_uid=UID),
            _row(9302, "конфу вспоминали часто", year=2024, subject_uid=UID),
        ]
        accepted, stats = mrc.select_period_rows(
            _strict_pool() + bound, query=PERSON_QUERY, policy="historical",
            slots=2, subject_uids=(UID,), subject_names=(NAME,))
        assert stats["reserved_old"] == 1
        assert 9301 in [row["id"] for row in accepted]

    def test_explicit_year_and_operative_are_untouched(self):
        """M3: явный год и `operative` не получают резерв старшего периода."""
        pool = [_row(9401, "конфу вспоминали в 2023", year=2023),
                _row(9402, "про Аню и конфу в 2023", year=2023),
                _row(9403, "Аню и конфу вспоминали", year=2023),
                _row(9404, "про Аню вспоминали", year=2025)]
        accepted, stats = mrc.select_period_rows(
            pool, query="про Аню и конфу в 2023 году", policy="auto",
            slots=2)
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_YEAR
        assert stats.get("reserved_old", 0) == 0
        assert {mrc.period_row_year(row) for row in accepted} == {2023}
        accepted, stats = mrc.select_period_rows(
            pool, query=PERSON_QUERY, policy="operative", slots=2)
        assert stats.get("reserved_old", 0) == 0
        assert 2025 not in {mrc.period_row_year(row) for row in accepted}

    def test_none_intent_has_no_reservation(self):
        """`none` (обычный вопрос) не ослабляется резервом старшего периода."""
        pool = _strict_pool() + _soft_old_pool()
        accepted, stats = mrc.select_period_rows(
            pool, query="как дела с конфой?", policy="auto", slots=2)
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_NONE
        assert stats.get("reserved_old", 0) == 0


class TestAppendHonoursReservation:
    def test_marker_wins_with_mixed_top_years(self):
        """M4: помеченная строка доезжает при смешанных годах верхних слотов."""
        marked = _row(9501, "про Аню вспоминали", year=2023)
        marked["reserved_old"] = True
        rows = [_row(9502, "верхний период", year=2026),
                _row(9503, "средний период", year=2024),
                marked]
        selected = mrc.reserve_period_append(rows, budget=2)
        assert [row["id"] for row in selected] == [9502, 9501]
        assert len(selected) == 2, "бюджет не растёт"

    def test_marker_already_inside_budget_is_untouched(self):
        marked = _row(9511, "про Аню вспоминали", year=2023)
        marked["reserved_old"] = True
        rows = [_row(9512, "верхний период", year=2026), marked,
                _row(9513, "верхний период 2", year=2026)]
        assert mrc.reserve_period_append(rows, budget=2) == rows[:2]

    def test_no_marker_keeps_previous_behaviour(self):
        """Без пометки действует прежнее правило MEM-07 (один слот старшему)."""
        rows = [_row(9521, "верхний период", year=2026),
                _row(9522, "верхний период 2", year=2026),
                _row(9523, "старый период", year=2021)]
        assert [row["id"] for row in
                mrc.reserve_period_append(rows, budget=2)] == [9521, 9523]
        # Один период в кандидатах — прежний срез байт-в-байт.
        same = [_row(9531, "верхний период", year=2026),
                _row(9532, "верхний период 2", year=2026)]
        assert mrc.reserve_period_append(same, budget=2) == same[:2]


# ── R3: разрешённый субъект в `auto` ──────────────────────────────────────


class TestSubjectScopeIntent:
    def test_subject_present_yields_multi_year_subject_scope(self):
        intent = mrc.resolve_period_intent(
            PERSON_QUERY, memory_scope="auto", subject_present=True)
        assert intent.kind == mrc.PERIOD_INTENT_MULTI_YEAR
        assert intent.source == "subject_scope"
        # Права замещать базовый срез НЕТ: множество источников не расширено.
        assert mrc.period_replace_allowed(intent, "auto") is False

    def test_current_state_and_operative_have_no_subject_scope(self):
        assert mrc.resolve_period_intent(
            PERSON_QUERY, memory_scope="auto", subject_present=True,
            current_state=True).kind == mrc.PERIOD_INTENT_NONE
        assert mrc.resolve_period_intent(
            PERSON_QUERY, memory_scope="operative",
            subject_present=True).kind == mrc.PERIOD_INTENT_NONE
        # Более сильный сигнал не понижается до субъекта.
        assert mrc.resolve_period_intent(
            "про Аню и конфу в 2023 году", subject_present=True
        ).kind == mrc.PERIOD_INTENT_YEAR
        assert mrc.resolve_period_intent(
            PERSON_QUERY, memory_scope="historical", subject_present=True
        ).source == "memory_scope"

    @pytest.mark.asyncio
    async def test_auto_person_reaches_old_row_without_replacing_base(
            self, monkeypatch):
        """R3 end-to-end: `auto` + полный срез + субъект → старый год доставлен.

        Базовый срез при этом не заменяется целиком: добавление идёт в
        существующий бюджет `limit//5`, замещение разрешено только
        `period_replace_allowed` (для `subject_scope` — нет)."""
        base = _base_rows()
        service = _service(monkeypatch, base, _strict_pool() + _soft_old_pool())
        rows = await service._rag_unified_rows(
            CHAT, PERSON_QUERY, _stub(PERSON_QUERY), memory_scope="auto",
            subject_name=NAME, subject_uid=UID)
        assert service._oldrow_calls[1]["period_fill"] is True, (
            "разрешённый субъект запускает тот же периодный вызов")
        assert "author_window" in service._oldrow_calls[1]["channels"]
        assert service._oldrow_calls[1]["subject_uids"] == (UID,)
        stats = service._rag_period_stats
        assert stats["breadth_reason"] == "subject_scope"
        assert stats["replace_allowed"] == 0
        assert stats["reserved_old"] == 1
        years = [mrc.period_row_year(row) for row in rows]
        assert years.count(2025) == 1, years
        assert len(rows) == len(base), "срез не растёт сверх limit"
        # Первая (базовая) строка среза остаётся на месте.
        assert rows[0]["id"] == 8000

    @pytest.mark.asyncio
    async def test_auto_without_resolved_subject_keeps_full_slice(
            self, monkeypatch):
        """Контроль: без разрешённого субъекта `auto`+полный срез не добирает."""
        base = _base_rows()
        service = _service(monkeypatch, base, _strict_pool() + _soft_old_pool())
        rows = await service._rag_unified_rows(
            CHAT, "как дела с конфой?", _stub("как дела с конфой?"),
            memory_scope="auto")
        assert [row["id"] for row in rows] == [row["id"] for row in base]
        assert len(service._oldrow_calls) == 1
        assert service._rag_period_stats["period_skipped"] == "auto_full_slice"

    @pytest.mark.asyncio
    async def test_current_state_person_keeps_period_off(self, monkeypatch):
        """M7: «что сейчас» с тем же субъектом не запускает периодный добор."""
        base = _base_rows()
        service = _service(monkeypatch, base, _strict_pool() + _soft_old_pool())
        rows = await service._rag_unified_rows(
            CHAT, CURRENT_QUERY, _stub(CURRENT_QUERY), memory_scope="auto",
            subject_name=NAME, subject_uid=UID)
        assert {mrc.period_row_year(row) for row in rows} == {2026}
        assert service._oldrow_calls, "базовый вызов обязан быть"
        assert not any(call["period_fill"] for call in service._oldrow_calls), (
            "«что сейчас» не платит периодный вызов")
        assert service._rag_period_stats["breadth_reason"] in ("", "none")
        assert "author_window" not in service._oldrow_calls[0]["channels"]


# ── R2: author_window по разрешённому субъекту ─────────────────────────────


async def _db():
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _add_msg(db, user, text, ts, tg):
    await db.save_smart_message(
        user_id=user, chat_id=CHAT, text=text, reply_to_id=None,
        timestamp=ts, media_type="text", author_name="", message_id=tg)


async def _seed_author_years(db):
    tg = 9000
    for year in (2023, 2024, 2025):
        for index in range(5):
            await _add_msg(db, UID, f"речь {year} номер {index}",
                           _ts(year, 3, 1) + index, tg)
            tg += 1
    await _add_msg(db, UID, "свежая речь 2026", _ts(2026, 2, 1), tg)
    await db.db.commit()


def _subject_request(**overrides):
    base = dict(
        chat_id=CHAT, query=PERSON_QUERY, mode="specific", purpose="reply",
        top_k=32, channels=("lexical", "vector", "author_window"),
        reply_depth=0, memory_scope="historical", period_fill=True,
        subject_entity_ids=(UID,), subject_names=(NAME,))
    base.update(overrides)
    return mrc.RetrievalRequest(**base)


class TestAuthorWindowBySubject:
    @pytest.mark.asyncio
    async def test_subject_window_is_bounded_and_multi_year(self):
        """M8: старые сообщения субъекта ≤ `top_k//5` и из РАЗНЫХ лет."""
        db = await _db()
        try:
            await _seed_author_years(db)
            result = await mrc.retrieve(db, memory=None,
                                        request=_subject_request())
            own = [cand for cand in result.candidates
                   if cand.entity_type == "message"
                   and cand.author_id == UID]
            assert own, "author_window обязан исполниться по субъекту"
            assert "author_window" in result.channels_used
            fill = result.period_fill
            assert fill["author_window"] == 1
            assert 1 <= fill["author_window_rows"] <= 32 // 5
            assert fill["author_window_years"] == 3, (
                "вклад распределён по трём завершённым годам")
            assert {mrc._candidate_year(cand) for cand in own} == {
                2023, 2024, 2025}
            # Ни один год не получает больше своей квоты.
            per_year: dict = {}
            for cand in own:
                year = mrc._candidate_year(cand)
                per_year[year] = per_year.get(year, 0) + 1
            assert max(per_year.values()) <= 32 // 5
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_operative_current_state_has_no_author_window(self):
        """M7: `operative`/«что сейчас» не читает старые оригиналы."""
        db = await _db()
        try:
            await _seed_author_years(db)
            calls: list = []
            real = db.get_author_message_periods

            async def _spy(chat_id, user_id, limit, **kwargs):
                calls.append(int(user_id))
                return await real(chat_id, user_id, limit, **kwargs)

            db.get_author_message_periods = _spy
            intent = mrc.resolve_period_intent(
                CURRENT_QUERY, subject_present=True, current_state=True)
            result = await mrc.retrieve(
                db, memory=None,
                request=_subject_request(query=CURRENT_QUERY,
                                         memory_scope="operative",
                                         period_intent=intent))
            assert calls == [], "«что сейчас» не читает старые сообщения"
            assert "author_window" not in result.channels_used
        finally:
            await db.close()

    def test_originals_put_author_window_first(self):
        """M8: авторские оригиналы не срезаются лексическими (cap 12)."""
        def _cand(kind, index, channel):
            return types.SimpleNamespace(
                entity_type=kind, channel=channel, entity_id=index,
                revision=f"tg:{5000 + index}", preview=f"строка {index}",
                author_id=UID, chat_id=CHAT, sent_at=_ts(2025), id=str(index))

        lexical = [_cand("message", index, "lexical") for index in range(15)]
        authors = [_cand("message", 100 + index, "author_window")
                   for index in range(2)]
        result = types.SimpleNamespace(candidates=lexical + authors)
        rows = dcs.DirectChatService._collect_originals(result, 12)
        assert len(rows) == 12
        assert [row["source_channel"] for row in rows[:2]] == [
            "author_window", "author_window"], rows[:2]


# ── e2e: исторический вопрос о человеке доставляет старый год ──────────────


class TestHistoricalPersonDeliversOldRow:
    @pytest.mark.asyncio
    async def test_historical_person_gets_old_row_in_block(self, monkeypatch):
        """RED на базе: 2026-only. GREEN: один старший subject-bound ряд."""
        base = _base_rows()
        service = _service(monkeypatch, base, _strict_pool() + _soft_old_pool())
        rows = await service._rag_unified_rows(
            CHAT, PERSON_QUERY, _stub(PERSON_QUERY),
            memory_scope="historical", subject_name=NAME, subject_uid=UID)
        years = [mrc.period_row_year(row) for row in rows]
        assert years.count(2025) == 1, years
        assert years.count(2026) == len(rows) - 1
        stats = service._rag_period_stats
        assert stats["reserved_old"] == 1
        assert stats["historical_quota"] == 0
        assert stats["multi_year_quota"] == 0
        assert stats["soft_fallback"] == 0, (
            "резерв — не мягкий fallback: строгий отбор не отменялся")
