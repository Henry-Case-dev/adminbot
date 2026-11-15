"""VMQ-MEM / VMQ-MEM-TIME — Slice D: паритет обычного вопроса, субъектная
половина без выдачи общей истории за биографию, год события и трасса причин,
размеченная релевантность.

Контракт: `plans/features/vmq-onto-01/evidence/review-recovery-pass-2026-11-15.md`
(остаточный функциональный объём MEM-04 / TIME-01/02/04/06/07) и
`evidence/vmq-mem/root-cause-2026-11-15.md` §4.

Покрытие (CONTRACT/REGRESSION), на реальных путях кода:

* MEM-04: обычный вопрос без исторической формы получает ОГРАНИЧЕННЫЙ старый
  материал, если САМ ПУЛ показывает многолетнюю предметную непрерывность
  (≥2 строки «того же предмета» из ≥2 разных незавершённых лет); творческая и
  обычная формулировки на одном пуле дают сопоставимый вклад. Сигнал берётся
  из найденного материала, а не из слов запроса: списков фраз нет;
* negative: одна строка, один старый год или пул без общей основы паритет НЕ
  включают — текущее состояние остаётся текущим;
* TIME-01/02: профиль человека читает ТРИ последних завершённых года (2025
  входит, прежний диапазон терял его), собственные сообщения — точный uid;
  известный человек без подтверждённого субъектного материала получает
  `no_subject_bound_material`, а не «unknown_person» и не author=subject;
* TIME-04: при заданном временном окне кандидат с неизвестным временем не
  попадает в блок (fail-closed) — «время неизвестно» не выдаётся за событие
  года; причины потери года различимы (статус/давность/релевантность/бюджет);
* TIME-06: векторная нога без доказанного допуска не выполняет KNN и честно
  называет причину (`compat_not_proven`); год в вопросе — единственный
  триггер явного временного окна (словари годов не добавляются);
* TIME-07: размеченный набор исторических вопросов с ожидаемыми периодами и
  темами даёт измеримую точность отбора, а не только число строк.

TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/vmq-mem Slice D
R17: только синтетические факты/сообщения, никаких реальных переписок.
"""
import asyncio
import calendar
import json
import os
import time
from unittest.mock import MagicMock

import pytest

from services import mca_retrieval_context as mrc
from services import direct_chat_service as _dcs
from services.database import DatabaseService
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT = -100
UID = 7
SLOT_DIV = 5
A1_CREATIVE = "напиши юмористический рассказ об основных шизах конфы"
A1P_PLAIN = "что за шизы были на конфе?"
CURRENT_STATE = "что сейчас происходит с E1?"
CURRENT_ALINA = "что сейчас с Алиной?"
CONFLICT_2023 = "из-за чего мы ссорились и ругались в 2023 году"
LABELED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "vmq_slice_d_labeled.json")


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


def _row(fid, text, *, year=None, source="lexical", ts=None,
         status="confirmed", expires_at=None):
    row = {"id": fid, "fact": text, "origin": "history_import",
           "status": status, "expires_at": expires_at,
           "created_at": _ts(year) if year else ts,
           "message_timestamp": _ts(year) if year else ts,
           "tg_message_id": 800 + fid, "chat_id": CHAT,
           "item_id": f"fact:{fid}"}
    if source:
        row["period_source"] = source
        row["subject_proxy"] = "knn" if source == "vector" else "stems"
    return row


class FakeAliases:
    def __init__(self, mapping=None):
        self._aliases = {str(k): str(v) for k, v in (mapping or {}).items()}

    def canon_name(self, name):
        return str(name or "").strip()

    def resolve(self, user_id, nickname=None, username=None, **_kw):
        return self._aliases.get(str(user_id), nickname or str(user_id))


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


async def _fact(db, text, *, year=2026, subject_ref=None, target="Лёха",
                speaker=None, status="confirmed", weight=0.6, origin=None,
                ts=None, chat_id=CHAT):
    return await db.insert_graph_fact(
        chat_id, text, origin or "chat_history", None, target_user=target,
        status=status, weight=weight, importance=5,
        message_timestamp=_ts(year) if ts is None and year else ts,
        subject_ref_id=subject_ref, speaker_author_id=speaker,
        attribution_method="self_report",
        tg_message_id=9000 + year + abs(hash(text)) % 100)


def _router(db, aliases=None):
    return ToolRouter(ToolDeps(search=MagicMock(), memory=None,
                               aliases=aliases or FakeAliases({str(UID): "Лёха"}),
                               db=db))


def _measured_plain_pool():
    """Форма пула A1P из корпусного замера (Slice B, реальная копия).

    16 строк: 2023 — 2, 2024 — 5, 2025 — 9; 7 строк делят с обычным вопросом
    ровно одну основу (`шизы`/`конф`), 9 — ни одной; строгая строка A1
    («шизах»+«конф») одна. Строгий порог §2 (≥2) не принимает у A1P НИ ОДНОЙ
    строки — именно этот пул давал 0/16."""
    return [
        _row(2859, "конфа тогда шумела", year=2023),        # 1 основа
        _row(2088, "погода и дорога", year=2023),           # 0
        _row(3775, "на шизах и конф", year=2024),           # A1: 2, A1P: 1
        _row(3324, "на конфе шумели", year=2024),           # 1
        _row(3827, "обсуждали ролики", year=2024),          # 0
        _row(4245, "купил новый диск", year=2024),          # 0
        _row(4326, "вечером созвон", year=2024),            # 0
        _row(8056, "шизы обсуждали снова", year=2025),      # 1
        _row(5279, "на конфе виделись", year=2025),         # 1
        _row(5283, "конфа шумела", year=2025),              # 1
        _row(7999, "шизы случились", year=2025),            # 1
        _row(5412, "покупки на выходные", year=2025),       # 0
        _row(8330, "музыка играла", year=2025),             # 0
        _row(5568, "смотрели сериал", year=2025),           # 0
        _row(7405, "работа и дедлайны", year=2025),         # 0
        _row(7001, "играли в настолки", year=2025),         # 0
    ]


def _old_material_stats(accepted):
    return {
        "ids": [row["id"] for row in accepted],
        "years": sorted({mrc.period_row_year(row) for row in accepted}),
    }


# ── MEM-04: паритет обычного вопроса (данные пула, не формулировка) ────────


class TestPlainQuestionParity:
    def test_measured_plain_pool_gets_bounded_old_material(self):
        """RED на базе: pool 16 → 0 принятых. GREEN: обычный вопрос получает
        ограниченный старый материал с явным кодом причины."""
        pool = _measured_plain_pool()
        accepted, stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=2,
            reference_year=2026)
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_NONE
        assert len(accepted) == 2, stats
        assert stats["topic_quota"] == 2, stats
        assert stats["topic_years"] >= 2, stats
        assert stats["topic_common_stems"] >= 1, stats
        assert _old_material_stats(accepted)["years"] == [2023, 2024]
        assert all(row["stems_shared_reason"] == mrc.PERIOD_KEEP_TOPIC_PARITY
                   for row in accepted)
        assert all(row["stems_shared"] >= 1 for row in accepted)
        # D2: старые строки обязаны делить ОБЩУЮ основу между собой.
        row_stems = [mrc.period_subject_stems(row["fact"]) for row in accepted]
        assert set.intersection(*row_stems), row_stems

    def test_creative_and_plain_formulations_get_comparable_material(self):
        """Один и тот же пул: творческая формулировка (historical) и обычная
        (none) дают сопоставимый старый вклад — различается форма, не поиск."""
        pool = _measured_plain_pool()
        # Творческая формулировка имеет в пуле строгую строку: «на шизах и конф».
        creative, creative_stats = mrc.select_period_rows(
            pool, query=A1_CREATIVE, policy="auto", slots=2,
            reference_year=2026)
        plain, plain_stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=2,
            reference_year=2026)
        assert creative_stats["intent"]["kind"] == \
            mrc.PERIOD_INTENT_HISTORICAL
        assert plain_stats["intent"]["kind"] == mrc.PERIOD_INTENT_NONE
        assert len(creative) == len(plain) == 2
        assert _old_material_stats(creative)["years"] == \
            _old_material_stats(plain)["years"] == [2023, 2024]
        assert all(row["id"] in {r["id"] for r in pool}
                   for row in creative + plain)

    def test_bounded_by_slots_and_never_duplicates_years(self):
        pool = _measured_plain_pool()
        accepted, stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=1,
            reference_year=2026)
        assert len(accepted) == 1
        assert stats["topic_quota"] == 1
        years = [mrc.period_row_year(row) for row in accepted]
        assert len(set(years)) == len(years)

    def test_reason_codes_stay_consistent(self):
        """Принятые строки реально лежат в пуле; причины не выдуманы."""
        pool = _measured_plain_pool()
        accepted, stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=2,
            reference_year=2026)
        pool_ids = {row["id"] for row in pool}
        assert {row["id"] for row in accepted} <= pool_ids
        assert stats["rows"] == len(pool)
        assert stats["kept"] == len(accepted)

    def test_single_old_year_does_not_trigger_parity(self):
        """Два года нужны как доказательство многолетней темы: строки одного
        старого года паритет не включают (защита текущего ответа)."""
        pool = [
            _row(1, "шизы обсуждали", year=2024),
            _row(2, "на конфе шумели", year=2024),
            _row(3, "вечером созвон", year=2024),
        ]
        accepted, stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=2,
            reference_year=2026)
        assert accepted == []
        assert stats["topic_quota"] == 0
        assert stats["topic_years"] == 1

    def test_current_state_pool_is_untouched(self):
        """D1/D8: ДВЕ старые строки из ДВУХ лет (с общей основой между собой
        и с вопросом) под `auto` не вытесняют текущий блок: guard текущего
        состояния сильнее паритета. Прежний T3 не задействовал механизм
        (`period_stats={}`), здесь он реально доходит до отбора."""
        pool = [
            _row(8001, "Алина была в 2022", year=2022),
            _row(8002, "Алина снова в 2023", year=2023),
        ]
        accepted, stats = mrc.select_period_rows(
            pool, query=CURRENT_ALINA, policy="auto", slots=2,
            reference_year=2026)
        assert accepted == []
        assert stats["topic_quota"] == 0
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_NONE
        # Механизм был бы доступен без guard: общая основа и два года есть.
        assert stats["topic_years"] == 2
        assert stats["topic_common_stems"] >= 1

    @pytest.mark.asyncio
    async def test_full_path_current_state_keeps_current_ids(self, monkeypatch):
        """D1 (BLOCKER): полный путь `_rag_unified_rows` под `auto` не теряет
        текущие строки 8008/8009, хотя периодный пул дал бы паритет. Контроль:
        тот же пул без указателя настоящего — паритет срабатывает."""
        import types
        import services.direct_chat_service as _dcs

        service = _dcs.DirectChatService(
            memory=object(),
            db=types.SimpleNamespace(search_messages_fts=lambda *a, **k: None),
            llm=None, aliases=None)
        current_rows = [_row(8000 + i, f"текущее событие {i}", year=2026)
                        for i in range(10)]
        old_rows = [_row(8101, "Алина была в 2022", year=2022),
                    _row(8102, "Алина снова в 2023", year=2023)]

        class _Result:
            def __init__(self, fact_rows, period_fill=None):
                self.fact_rows = tuple(fact_rows)
                self.period_fill = period_fill

        async def fake(db, memory, chat_id, query, channels, limit, policy,
                       *, period_fill=False, period_intent=None, **_kwargs):
            if period_fill:
                return _Result(old_rows,
                               period_fill={"vector_leg": "compat_not_proven",
                                            "vector_rows": 0})
            return _Result(current_rows)

        monkeypatch.setattr(service, "_rag_retrieve", fake)
        rows = await service._rag_unified_rows(
            CHAT, CURRENT_ALINA, None, memory_scope="auto")
        ids = {row["id"] for row in rows}
        assert {8008, 8009} <= ids, ids
        assert not any(row.get("period_fill") for row in rows), rows

        # Контроль: тот же пул без указателя настоящего получает паритет.
        rows = await service._rag_unified_rows(
            CHAT, "Алина и её дела", None, memory_scope="auto")
        assert any(row.get("period_fill") for row in rows), rows
        assert {2022, 2023} <= {mrc.period_row_year(row) for row in rows
                                if row.get("period_fill")}

    def test_current_state_suppresses_strict_old_row(self):
        """D1: строгая строка старого года (≥2 общих основы) тоже не входит
        в вопрос о настоящем под `auto` — иначе она вытесняет текущую."""
        pool = [_row(8436, "мулянкой и сейчас и дела", year=2025)]
        accepted, stats = mrc.select_period_rows(
            pool, query="как сейчас дела с мулянкой?", policy="auto",
            slots=2, reference_year=2026)
        assert accepted == []
        assert stats["current_state_guard"] == 1
        assert stats["topic_quota"] == 0

    def test_two_old_years_without_shared_stem_do_not_trigger(self):
        """D2/D8: обе строки делят основу С ВОПРОСОМ, но не между собой —
        паритет не включается (это и есть дефект «шизы vs конфа»)."""
        pool = [
            _row(1, "шизы обсуждали", year=2023),
            _row(2, "на конфе шумели", year=2024),
        ]
        accepted, stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=2,
            reference_year=2026)
        assert accepted == []
        assert stats["topic_quota"] == 0
        assert stats["topic_years"] == 2
        assert stats["topic_common_stems"] == 0

    def test_operative_policy_is_not_weakened(self):
        """D8: `operative` не добирает старый материал, даже если строгая
        строка его бы прошла. Тест не вакуумный: текущая строка принята, а на
        том же пуле под `auto` старая строка принимается."""
        pool = [
            _row(1, "текущий факт 2026", year=2026),
            _row(2, "шизы и конф в 2023", year=2023),
        ]
        accepted, stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="operative", slots=2,
            reference_year=2026)
        assert accepted, "текущая строка должна остаться"
        assert {mrc.period_row_year(row) for row in accepted} == {2026}
        assert stats["topic_quota"] == 0
        assert all(mrc.period_row_year(row) == 2026 for row in accepted)

        auto_accepted, auto_stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=2,
            reference_year=2026)
        assert any(mrc.period_row_year(row) == 2023
                   for row in auto_accepted), auto_stats


# ── TIME-04: ступени потери года различимы ────────────────────────────────


class TestYearLossTrace:
    def test_year_loss_categories_are_machine_readable(self):
        future = int(time.time()) + 3600
        past = int(time.time()) - 3600
        pool = [
            _row(1, "конфа шумела", year=2023),
            _row(2, "на конфе шумели", year=2024),
            _row(3, "конфа снова", year=2024),
            _row(4, "конфа опять", year=2025),
            _row(5, "конфа ещё", year=2025),
            _row(6, "конфа архив", year=2024, status="archived_fact"),
            _row(7, "конфа слух", year=2024, status="tentative"),
            _row(8, "конфа старая", year=2024, expires_at=past),
            _row(9, "конфа новая", year=2024, expires_at=future),
        ]
        accepted, stats = mrc.select_period_rows(
            pool, query=A1P_PLAIN, policy="auto", slots=2,
            reference_year=2026)
        assert stats["pool_status"] == {"confirmed": 7, "archived": 1,
                                        "other": 1}, stats["pool_status"]
        assert stats["dropped_status"] == 1
        assert stats["pool_expired"] == 1
        assert stats["age_policy"] == "not_applied"
        # 8 строк «того же предмета» старого года (archived/expired/future
        # входят; tentative отсеян по статусу), принято 2 → 6 по бюджету.
        assert len(accepted) == 2, stats
        assert stats["topic_quota"] == 2
        assert stats["dropped_budget"] == 6, stats
        assert stats["dropped_subject"] == 6, stats

    @pytest.mark.asyncio
    async def test_unknown_time_is_not_presented_as_year_event(self, db):
        """Явный 2023: кандидат с неизвестным временем не входит в материал
        года (fail-closed), 2023-строка входит. RED на базе: неизвестное
        время проходило оба сравнения окна."""
        await db.save_smart_message(
            UID, CHAT, 'цитата "старый конфликт" 2023', None,
            _ts(2023, 4, 1), "text", "Лёха", message_id=50_001)
        await db.save_smart_message(
            UID, CHAT, 'цитата "старый конфликт" без даты', None, 0,
            "text", "Лёха", message_id=50_002)
        request = mrc.RetrievalRequest(
            chat_id=CHAT, query='цитата "старый конфликт"', mode="history",
            purpose="reply", top_k=8, reply_depth=0,
            time_from=_ts(2023, 1, 1),
            time_to=_ts(2023, 12, 31) + 86399)
        result = await mrc.retrieve(db, None, request)
        previews = [str(cand.preview or "") for cand in result.candidates]
        assert any("2023" in text and "без даты" not in text
                   for text in previews), previews
        assert not any("без даты" in text for text in previews), previews
        assert all(cand.sent_at for cand in result.candidates)

    def test_apply_filters_without_window_keeps_old_behaviour(self):
        """Без временного окна неизвестное время не отбрасывается — принятое
        поведение прежних путей (test_history_isolation)."""
        cand = mrc.RetrievalCandidate(
            id="msg:1", entity_type="message", entity_id="1", chat_id=CHAT,
            sent_at=0, channel="lexical")
        kept = mrc._apply_filters([cand], mrc.RetrievalRequest(
            chat_id=CHAT, query="вопрос"))
        assert kept == [cand]


# ── TIME-01/02: субъектная половина ───────────────────────────────────────


class TestSubjectHalf:
    @pytest.mark.asyncio
    async def test_author_messages_cover_three_completed_years(self, db):
        """RED на базе: диапазон начинался с base-2 и терял 2025 (ближайший
        завершённый год). GREEN: 2025/2024/2023, точный uid, роль speaker."""
        for year, mid in ((2023, 51_001), (2024, 51_002), (2025, 51_003)):
            await db.save_smart_message(
                UID, CHAT, f"моё сообщение {year}", None,
                _ts(year, 3, 1), "text", "Лёха", message_id=mid)
        await db.save_smart_message(
            999, CHAT, "чужое 2025", None, _ts(2025, 3, 2), "text",
            "Толя", message_id=51_004)
        rows = await db.get_author_message_periods(
            CHAT, UID, 10, reference_year=2026)
        years = {int(row["as_of_year"]) for row in rows}
        assert {2023, 2024, 2025} <= years, years
        assert all(row["speaker_author_id"] == UID for row in rows)
        assert all(row["subject_role"] == "speaker" for row in rows)
        assert all(row["authored_by_subject"] for row in rows)

    @pytest.mark.asyncio
    async def test_subject_material_replaces_generic_period_row(self, db):
        """Субъектные строки человека сильнее общего периодного добора: иначе
        паритет обычного вопроса (MEM-04) занимает слоты и профиль остаётся
        без собственных сообщений."""
        import services.direct_chat_service as _dcs
        await db.save_smart_message(
            UID, CHAT, "в 2023 я переехал", None, _ts(2023, 4, 1), "text",
            "Лёха", message_id=52_001)
        service = _dcs.DirectChatService(memory=object(), db=db, llm=None,
                                         aliases=None)
        base = [{"id": 900 + i, "fact": f"текущий факт {i}",
                 "rag_ts": _ts(2026), "message_timestamp": _ts(2026),
                 "origin": "chat_history"} for i in range(8)]
        generic = {"id": 999, "fact": "шизы обсуждали", "rag_ts": _ts(2025),
                   "message_timestamp": _ts(2025),
                   "origin": "history_import", "period_fill": True}
        rows = base + [generic]
        out = await service._rag_append_profile_rows(
            db, rows, CHAT, "Лёха", UID, 10)
        assert generic not in out
        assert any(row.get("subject_role") == "speaker" for row in out)
        assert len(out) <= 10

    @pytest.mark.asyncio
    async def test_tool_biography_reserves_multi_period_slots(self, db):
        """D3: топ-автор имеет 10/10 фактов 2026 — раньше сообщения 2024/2025
        не читались (`len(facts) < max_items`). Теперь годовая квота
        зарезервирована, релевантные факты не вытесняются целиком."""
        for index in range(10):
            await _fact(db, f"факт о Лёхе {index}", year=2026,
                        target="Лёха", speaker=UID)
        await db.save_smart_message(
            UID, CHAT, "в 2024 сменил работу", None, _ts(2024, 5, 1), "text",
            "Лёха", message_id=53_001)
        await db.save_smart_message(
            UID, CHAT, "в 2025 переехал", None, _ts(2025, 5, 1), "text",
            "Лёха", message_id=53_002)
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        payload = json.loads(raw)
        years = {fact.get("as_of_year") for fact in payload["facts"]}
        assert {2024, 2025} <= years, years
        assert 2026 in years, "релевантные факты не должны исчезнуть целиком"
        assert len(payload["facts"]) <= 10
        assert payload["subject_material"]["subject_bound"] >= 10

    @pytest.mark.asyncio
    async def test_known_person_without_bound_material_is_named(self, db):
        """Известный uid без подтверждённого субъектного материала: честное
        `no_subject_bound_material`, а не «unknown_person»."""
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        payload = json.loads(raw)
        assert payload["no_data"] is True
        assert payload["facts"] == []
        assert payload["empty_reason"] == "no_subject_bound_material"
        assert payload["subject_material"]["limitation"] == \
            "no_subject_bound_material"

    @pytest.mark.asyncio
    async def test_unconfirmed_subject_facts_are_not_biography(self, db):
        """Неподтверждённый факт о человеке не выдаётся за биографию и не
        подменяется общей историей чата (R=0 ≠ R>0)."""
        await _fact(db, "непроверенный слух о Лёхе", year=2026,
                    subject_ref=15612, target="Лёха", status="unconfirmed")
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        payload = json.loads(raw)
        assert payload["no_data"] is True
        assert payload["facts"] == []
        assert payload["subject_material"]["subject_bound"] == 0

    @pytest.mark.asyncio
    async def test_confirmed_subject_years_are_returned_with_roles(self, db):
        await _fact(db, "о Лёхе 2026", year=2026, subject_ref=15612,
                    target="Лёха", speaker=UID)
        await _fact(db, "сказал в 2024", year=2024, subject_ref=None,
                    target="другой", speaker=UID, status="archived_fact")
        rows = await db.get_subject_profile_facts(
            CHAT, "Лёха", 10, int(time.time()), user_id=UID)
        by_year = {int(row["yr"]): row for row in rows}
        assert 2026 in by_year and 2024 in by_year
        assert by_year[2024]["subject_role"] == "speaker"
        assert by_year[2024]["speaker_author_id"] == UID
        assert by_year[2026]["subject_ref_id"] == 15612


# ── TIME-06: векторная нога и год-триггер ────────────────────────────────


class TestVectorLegAndYearTrigger:
    @pytest.mark.asyncio
    async def test_year_in_question_is_the_only_window_trigger(self, db,
                                                              monkeypatch):
        """Явный год включает окно и периодный intent; вопрос без года —
        нет. Векторная нога без доказанного допуска KNN не выполняет и честно
        называет причину (`compat_not_proven`)."""
        calls = []

        class _Memory:
            async def period_fill_candidates(self, *args, **kwargs):
                calls.append(kwargs)
                raise AssertionError("KNN без допуска выполняться не должен")

        async def _admission(_db, _memory):
            return {"state": "insufficient",
                    "class": "COMPATIBILITY_UNKNOWN",
                    "reason_code": "compat_not_proven",
                    "action": "retry_canary", "admitted": False,
                    "proven": False}

        monkeypatch.setattr(mrc, "_period_vector_admission", _admission)
        request = mrc.RetrievalRequest(
            chat_id=CHAT, query=CONFLICT_2023, mode="specific",
            purpose="reply", top_k=10, period_fill=True,
            memory_scope="auto", channels=("lexical", "vector"),
            exclude_years=(2026,))
        result = await mrc.retrieve(db, _Memory(), request)
        fill = result.period_fill
        assert fill["period_intent"]["kind"] == mrc.PERIOD_INTENT_YEAR
        assert fill["period_intent"]["source"] == "query_year"
        assert fill["vector_unavailable"] == 1
        assert fill["vector_unavailable_reason"] == "compat_not_proven"
        assert fill["vector_admission"]["admitted"] is False
        assert fill["vector_admission"]["proven"] is False
        assert fill["vector_rows"] == 0
        assert fill["knn_ms_reason"] == "vector_leg_unavailable"
        assert calls == [], "недопущенная нога не должна выполнять KNN"

        plain = mrc.RetrievalRequest(
            chat_id=CHAT, query=A1P_PLAIN, mode="specific",
            purpose="reply", top_k=10, period_fill=True,
            memory_scope="auto", channels=("lexical", "vector"),
            exclude_years=(2026,))
        plain_result = await mrc.retrieve(db, _Memory(), plain)
        assert plain_result.period_fill["period_intent"]["kind"] == \
            mrc.PERIOD_INTENT_NONE
        assert plain_result.period_fill["vector_unavailable"] == 1


# ── TIME-04: ступени и per-block годы в продуктовой трассе ─────────────────


class TestProductTrace:
    def test_period_trace_carries_stage_fields_and_block_years(self):
        """D5: ступени отбора и годы RAG-блока формируются в том же ходе и
        уходят в существующую трассу (не остаются в локальном dict)."""
        stats = {
            "period_intent": {"kind": "none", "years": [], "source": ""},
            "selection_rows": 16,
            "selection_kept": 2,
            "topic_quota": 2,
            "topic_years": 3,
            "topic_common_stems": 1,
            "historical_quota": 0,
            "multi_year_quota": 0,
            "rejected_subject": 14,
            "dropped_budget": 6,
            "dropped_status": 1,
            "dropped_out_of_target_year": 0,
            "dropped_unknown_year": 0,
            "pool_status": {"confirmed": 14, "archived": 1, "other": 1},
            "pool_expired": 1,
            "age_policy": "not_applied",
            "vector_leg": "compat_not_proven",
            "vector_rows": 0,
            "vector_unavailable_reason": "compat_not_proven",
        }
        kept = [("chat_history", "факт 2023", _ts(2023), "chat_history"),
                ("chat_history", "факт 2023", _ts(2023), "chat_history"),
                ("chat_history", "факт 2026", _ts(2026), "chat_history")]
        period, years = _dcs._period_trace(stats, kept)
        assert period["topic_quota"] == 2
        assert period["topic_common_stems"] == 1
        assert period["dropped_budget"] == 6
        assert period["dropped_status"] == 1
        assert period["pool_status"]["archived"] == 1
        assert period["age_policy"] == "not_applied"
        assert years == {2023: 2, 2026: 1}

    def test_selection_trace_allowlist_keeps_period_and_block_years(self):
        """D5: durable-событие выбора сохраняет memory_period и per-block
        годы; текстов/запросов в трассе нет."""
        from services import turn_trace as tt
        payload = tt._selection_payload({
            "memory_period": {
                "intent": {"kind": "none", "years": [], "source": ""},
                "pool": 16, "kept": 2, "topic_quota": 2,
                "pool_status": {"confirmed": 14, "archived": 1, "other": 1},
                "age_policy": "not_applied",
                "vector_leg": "compat_not_proven",
                "query": "не должно попасть",
            },
            "blocks": [{"kind": "rag", "rendered": True,
                        "years": {2023: 2, 2026: 8}}],
        })
        assert payload["memory_period"]["topic_quota"] == 2
        assert payload["memory_period"]["pool_status"]["archived"] == 1
        assert "query" not in payload["memory_period"]
        assert payload["blocks"][0]["years"] == {2023: 2, 2026: 8}

    def test_prepared_payload_carries_memory_period_to_snapshot_fields(self):
        prepared = _dcs._prepared_turn_payload(
            chat_id=CHAT, correlation_id="trace-1", blocks=[],
            event_blocks=[], available_item_ids=(), window_messages=0,
            budget={}, dropped=(), self_outputs=(),
            memory_period={"topic_quota": 2, "pool": 16})
        assert prepared.memory_period == {"topic_quota": 2, "pool": 16}


# ── TIME-07: размеченная релевантность (precision, не «сколько строк») ────


def _labels():
    with open(LABELED_PATH, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


class TestLabeledRelevance:
    @pytest.mark.asyncio
    async def test_precision_on_independent_labeled_set(self, db):
        """D6: размеченный набор с КОНКУРИРУЮЩИМИ дистракторами.

        Метки (ожидаемые темы/периоды) заданы независимо от селектора; часть
        дистракторов делит основы с вопросом и с темой (generic-слово,
        поздний аналог), поэтому precision не может быть структурной 1.0.
        Метрика считается по строкам, реально доходящим до среза
        (`_rag_append_period_rows`), включая T3-контроль."""
        cases = _labels()
        for index, case in enumerate(cases):
            chat_id = CHAT - (index + 1)
            case["_chat"] = chat_id
            for year in case["seed_years"]:
                for offset, text in enumerate(case["topic_texts"]):
                    await _fact(db, f"{text} #{year}-{offset}", year=year,
                                origin="history_import", target=None,
                                ts=_ts(year, 4, 1 + offset), chat_id=chat_id)
            for extra in case.get("extra_rows") or ():
                year = int(extra["year"])
                await _fact(db, f"{extra['text']} #{case['id']}-{year}",
                            year=year, origin="history_import", target=None,
                            ts=_ts(year, 6, 1), chat_id=chat_id)
            for year in case["distractor_years"]:
                await _fact(db, f"{case['distractor_text']} {case['id']} "
                                f"#{year}",
                            year=year, origin="history_import", target=None,
                            ts=_ts(year, 5, 1), chat_id=chat_id)
        service = _dcs.DirectChatService(memory=object(), db=None, llm=None,
                                         aliases=None)
        measured = []
        for case in cases:
            request = mrc.RetrievalRequest(
                chat_id=case["_chat"], query=case["query"], mode="specific",
                purpose="reply", top_k=32, period_fill=True,
                memory_scope="auto", channels=("lexical",),
                exclude_years=(2026,))
            result = await mrc.retrieve(db, None, request)
            accepted, stats = mrc.select_period_rows(
                list(result.fact_rows), query=case["query"],
                policy="auto", slots=2, reference_year=2026)
            # До среза доходят не все принятые: срез ограничен слотами.
            delivered = service._rag_append_period_rows(
                [], accepted, 10, slots=2)
            years = [mrc.period_row_year(row) for row in delivered]
            relevant = [
                1 for row, year in zip(delivered, years)
                if any(stem.casefold() in str(row.get("fact") or "").casefold()
                       for stem in case["topic_stems"])
                and year in case["expected_years"]]
            measured.append({
                "id": case["id"],
                "kind": case["kind"],
                "pool": len(result.fact_rows),
                "delivered": len(delivered),
                "relevant": len(relevant),
                "expected_years": case["expected_years"],
                "delivered_years": sorted({y for y in years if y}),
                "intent": stats["intent"]["kind"],
                "topic_quota": int(stats["topic_quota"]),
                "common_stems": int(stats["topic_common_stems"]),
            })
        core = [item for item in measured if item["kind"] == "core"]
        hard = [item for item in measured if item["kind"] == "hard"]
        current = [item for item in measured
                   if item["kind"] == "current"][0]

        def _precision(items):
            total = sum(item["delivered"] for item in items)
            good = sum(item["relevant"] for item in items)
            return (good, total, (good / total) if total else 0.0)

        core_good, core_total, core_precision = _precision(core)
        assert core_total > 0, measured
        assert core_precision >= 0.9, (core_precision, core)
        hard_good, hard_total, hard_precision = _precision(hard)
        assert hard_total > 0, measured
        # Метрика обязана различать: конкурирующие дистракторы реально
        # попадают в срез, поэтому precision строго ниже 1.0 — не структурная.
        assert 0.0 < hard_precision < 1.0, (hard_precision, hard)
        total = core_total + hard_total
        good = core_good + hard_good
        assert good / total >= 0.8, (good / total, measured)
        labelled = [item for item in measured if item["kind"] != "current"]
        covered = sum(
            1 for item in labelled
            if set(item["expected_years"]) & set(item["delivered_years"]))
        assert covered / len(labelled) >= 0.8, (covered, labelled)
        # T3 (измерен тем же путём): указатель настоящего — ноль периода,
        # причём пул НЕ пуст (механизм реально задействован).
        assert current["pool"] > 0, current
        assert current["delivered"] == 0, current
        assert current["topic_quota"] == 0, current
