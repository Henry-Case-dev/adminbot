"""VMQ-MEM/TIME Slice B — subject, chronology and relations projection.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/root-cause-2026-11-15.md`
§4 (Slice B) и `corpus-run-2026-11-15.md` §6 (A1/T2/Old_Episode/profile/
relationships остаются открытыми после Slice A).

Покрытие (CONTRACT/REGRESSION), на реальных путях кода:

* A1: историческое/повествовательное намерение даёт ОГРАНИЧЕННЫЙ старый вклад
  даже когда строгий порог §2 уже принял строку (раньше fallback не включался
  и owner-запрос получал только 2024); текущее состояние (`intent=none`)
  не ослабляется;
* T2: вопрос о событии без года получает структурный multi-year intent из
  существующего request/plan-сигнала (`request_intent`/`plan_act`), а не из
  нового словаря; вклад ограничен слотами и не подменяет 2026;
* Old_Episode: вопрос с явным 2023 получает episode-материал 2023, а не
  2025+2026; SQL-окно — существующие `since_ts/until_ts`, второй поиск не
  создаётся;
* профиль: P1-материал несёт субъектные ссылки (`subject_ref_id`/
  `speaker_author_id`) и годы 2023/2024; без субъектных данных — честный
  empty/limitation, НЕ fallback author=subject;
* связи: существующие sourced-рёбра получают год (`last_updated`) либо
  честную диагностику «нет временной проекции»; выдуманных рёбер 0 при
  непустом знаменателе.

TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/vmq-mem Slice B
R17: только синтетические факты/сообщения, никаких реальных переписок.
"""
import asyncio
import calendar
import time
from unittest.mock import MagicMock

import pytest

from services import direct_chat_service as dcs
from services import mca_retrieval_context as mrc
from services.database import DatabaseService
from services.summary_aliases import AliasResolver
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT = -100
UID = 7
OWNER_CREATIVE = "напиши юмористический рассказ об основных шизах конфы"
T2_EVENT = "что вообще было с E1, напомни?"
CURRENT_STATE = "что сейчас происходит с E1?"
CONFLICT_2023 = "из-за чего мы ссорились и ругались в 2023 году"
SLOT_DIV = 5


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


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
                speaker=None, status="confirmed", weight=0.6, origin=None):
    return await db.insert_graph_fact(
        CHAT, text, origin or "chat_history", None, target_user=target,
        status=status, weight=weight, importance=5,
        message_timestamp=_ts(year), subject_ref_id=subject_ref,
        speaker_author_id=speaker, attribution_method="self_report",
        tg_message_id=9000 + year + abs(hash(text)) % 100)


def _router(db, aliases=None):
    return ToolRouter(ToolDeps(search=MagicMock(), memory=None,
                               aliases=aliases or FakeAliases({str(UID): "Лёха"}),
                               db=db))


# ── A1: строгая строка не разбавляется «обязательным» старым годом ────────


class TestHistoricalMeaningSelection:
    def test_strict_row_is_not_diluted_by_weak_old_year(self):
        """Строгая строка сохраняется; добавляется НЕ БОЛЕЕ одной старшей.

        TIME-03 (контракт 2026-11-20 §3.3/§4.2): календарной квоты
        `historical_quota` нет, и мягкий fallback сам по себе блок не собирает.

        P-OLDROW R1 (контракт `selector-rootcause-2026-11-27.md` §3): при
        `historical` и не меньше двух soft-строк ОДНА строка с годом СТРОГО
        старше минимального года принятых входит в первые `slots` (здесь
        единственная такая — 2023; 2025 новее принятой 2024 и потому не
        выбирается). Строгая строка 2024 остаётся первой и не вытесняется;
        строка без общей основы (2022) по-прежнему не добавляется. Поэтому
        ожидание обновлено с явной ссылкой на контракт."""
        pool = [
            _row(1, "шизах на конфе обсуждали", year=2024),   # strict: 2 основы
            _row(2, "шизах был знатный", year=2023),          # 1 основа
            _row(3, "шизах снова", year=2025),                # 1 основа
            _row(4, "совсем другое", year=2022),              # 0 основ
        ]
        accepted, stats = mrc.select_period_rows(
            pool, query=OWNER_CREATIVE, policy="auto", slots=2,
            reference_year=2026)
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_HISTORICAL
        assert stats["soft_fallback"] == 0
        assert stats["historical_quota"] == 0
        assert stats["multi_year_quota"] == 0
        assert accepted[0]["id"] == 1, "строгая строка остаётся первой"
        assert [row["id"] for row in accepted] == [1, 2], accepted
        assert stats["reserved_old"] == 1
        assert {mrc.period_row_year(row) for row in accepted} == {2024, 2023}
        # Строка без общей основы не добирается и без квоты.
        assert 4 not in [row["id"] for row in accepted]

    def test_quota_is_bounded_by_slots_and_never_adds_current_year(self):
        pool = [_row(1, "шизы конфе", year=2024),
                _row(2, "шиза конфе", year=2023),
                _row(3, "шиза конфе", year=2022),
                _row(4, "шиза конфе", year=2026)]
        accepted, stats = mrc.select_period_rows(
            pool, query=OWNER_CREATIVE, policy="auto", slots=2,
            reference_year=2026)
        years = [mrc.period_row_year(row) for row in accepted]
        assert len(accepted) <= 2
        assert 2026 not in years
        assert all(row.get("stems_shared") is not None for row in accepted)
        assert stats["historical_quota"] <= 2

    def test_current_state_path_is_not_weakened(self):
        accepted, stats = mrc.select_period_rows(
            [_row(8436, "выгнали сами и ноют сейчас", year=2025)],
            query=CURRENT_STATE, policy="auto", slots=2, reference_year=2026)
        assert accepted == []
        assert stats["intent"]["kind"] == mrc.PERIOD_INTENT_NONE
        assert stats["historical_quota"] == 0


# ── T2: структурный multi-year intent из request/plan-сигнала ───────────────


class TestEventWithoutYearIntent:
    def test_request_intent_is_structured_not_lexical(self):
        intent = mrc.resolve_period_intent(
            T2_EVENT, request_intent="what-happened")
        assert intent.kind == mrc.PERIOD_INTENT_MULTI_YEAR
        assert intent.source == "request_intent"
        assert intent.is_multi_year is True
        # Тот же вопрос без сигнала остаётся прежним none: словаря нет.
        assert mrc.resolve_period_intent(T2_EVENT).kind == mrc.PERIOD_INTENT_NONE

    def test_plan_act_and_history_mode_are_structured_signals(self):
        assert mrc.resolve_period_intent(
            T2_EVENT, plan_act="historical_recall").kind == \
            mrc.PERIOD_INTENT_MULTI_YEAR
        assert mrc.resolve_period_intent(
            T2_EVENT, request_mode="episodic").kind == \
            mrc.PERIOD_INTENT_MULTI_YEAR

    def test_multi_year_selection_spans_old_years_and_is_bounded(self):
        intent = mrc.resolve_period_intent(
            T2_EVENT, request_intent="what-happened")
        pool = [
            _row(1, "вообще про E1", year=2023),
            _row(2, "было про E1", year=2024),
            _row(3, "напомни про E1", year=2025),
            _row(5, "не по теме", year=2023),
        ]
        accepted, stats = mrc.select_period_rows(
            pool, query=T2_EVENT, intent=intent, policy="auto", slots=2,
            reference_year=2026)
        years = [mrc.period_row_year(row) for row in accepted]
        assert len(accepted) == 2
        assert len(set(years)) == 2, "две строки пула — разные годы"
        assert 2026 not in years
        # TIME-03 §4.2: вместо календарной квоты — предметный fallback;
        # разные годы здесь свойство пула, а не требование квоты.
        assert all(row["stems_shared_reason"] ==
                   mrc.PERIOD_KEEP_SOFT_FALLBACK for row in accepted)
        assert stats["soft_fallback"] == 2
        assert stats["multi_year_quota"] == 0

    def test_current_state_with_multi_year_intent_is_not_triggered(self):
        """«Что сейчас» не получает multi-year intent: сигнал не лексический,
        а план запроса; none-путь не меняется."""
        assert mrc.resolve_period_intent(CURRENT_STATE).kind == \
            mrc.PERIOD_INTENT_NONE

    @pytest.mark.asyncio
    async def test_direct_rag_consumes_plan_act_signal(self, monkeypatch):
        """L1-план `historical_recall` доезжает до периодного отбора:
        событие без года получает bounded материал 2023/2024, а не 10/10 2026."""
        import types

        service = dcs.DirectChatService(memory=object(), db=types.SimpleNamespace(
            search_messages_fts=lambda *a, **k: None), llm=None, aliases=None)
        calls: list = []

        class _Result:
            def __init__(self, fact_rows, period_fill=None):
                self.fact_rows = tuple(fact_rows)
                self.period_fill = period_fill

        async def fake(db, memory, chat_id, query, channels, limit, policy,
                       *, period_fill=False, period_intent=None, **_kwargs):
            calls.append({"period_fill": period_fill,
                          "intent": period_intent.as_dict()
                          if period_intent else None})
            if period_fill:
                return _Result(
                    [_row(11, "вообще про E1", year=2023),
                     _row(12, "было про E1", year=2024),
                     _row(13, "напомни про E1", year=2025)],
                    period_fill={"vector_leg": "compat_not_proven",
                                 "vector_rows": 0})
            return _Result([_row(1 + i, f"текущее событие {i}", year=2026)
                            for i in range(10)])

        monkeypatch.setattr(service, "_rag_retrieve", fake)
        rows = await service._rag_unified_rows(
            CHAT, T2_EVENT, None, memory_scope="auto",
            plan_act="historical_recall")
        assert calls and calls[0]["period_fill"] is False
        period = [call for call in calls if call["period_fill"]]
        assert period and period[0]["intent"]["kind"] == \
            mrc.PERIOD_INTENT_MULTI_YEAR
        years = {mrc.period_row_year(row) for row in rows}
        assert {2023, 2024} <= years, years
        assert len([y for y in years if y]) >= 2

    @pytest.mark.asyncio
    async def test_plan_act_rebuilds_even_when_scope_is_auto(self, monkeypatch):
        """`historical_recall` — самостоятельный plan-сигнал: пересборка не
        требует `memory_scope=historical` и передаёт plan_act в блок."""
        import types
        service = dcs.DirectChatService(memory=object(), db=None, llm=None,
                                        aliases=None)
        calls: list = []

        async def fake_build(chat_id, message, global_ctx, *,
                             memory_scope=None, plan_act="", **_kwargs):
            calls.append({"memory_scope": memory_scope, "plan_act": plan_act})
            return "<RAG_Memory>multi</RAG_Memory>", ""

        monkeypatch.setattr(service, "_build_rag_block", fake_build)
        plan = types.SimpleNamespace(memory_scope="auto",
                                     response_act="historical_recall")
        blocks = ["<RAG_Memory>auto</RAG_Memory>"]
        out = await service._apply_plan_memory_scope(
            blocks, {"chat_id": CHAT, "message": object(), "global_ctx": "",
                     "history_sample": None, "projection": None,
                     "subject_name": None, "subject_uid": None}, plan)
        assert calls == [{"memory_scope": "auto",
                          "plan_act": "historical_recall"}]
        assert out == ["<RAG_Memory>multi</RAG_Memory>"]


# ── Old_Episode: явный 2023 не подменяется 2025/2026 ───────────────────────


def _service(db):
    router = _router(db)
    return dcs.DirectChatService(MagicMock(), db, MagicMock(),
                                 AliasResolver("{}"), tool_router=router)


class TestOldEpisodeChronology:
    @pytest.mark.asyncio
    async def test_explicit_2023_episode_uses_2023_window(self, db,
                                                          monkeypatch):
        from services import mca_gates
        monkeypatch.setattr(mca_gates, "retrieval_context_enabled",
                            lambda: True)
        monkeypatch.setattr(mca_gates, "episodes_compiler_facade_enabled",
                            lambda: False)
        # 30 свежих реплик с точными словами вопроса + одна 2023.
        for i in range(30):
            await db.save_smart_message(
                UID, CHAT, f"ссорились и ругались 2026 #{i}", None,
                _ts(2026, 5, 1 + i % 28), "text", "Лёха",
                message_id=10_000 + i)
        await db.save_smart_message(
            111, CHAT, "ссорились и ругались в 2023 из-за конференции",
            None, _ts(2023, 4, 10), "text", "Толя", message_id=20_001)

        block, stats = await _service(db)._build_old_episodes(
            CHAT, CONFLICT_2023, [], {})

        assert "2023 из-за конференции" in block, block
        assert "2026" not in block, "год вопроса подменён свежим аналогом"
        assert stats["period_intent"]["kind"] == mrc.PERIOD_INTENT_YEAR
        assert stats["period_intent"]["years"] == [2023]
        assert stats["year_window"] == [2023]
        assert stats["messages"] >= 1

    @pytest.mark.asyncio
    async def test_no_year_question_keeps_previous_episode_path(self, db,
                                                                 monkeypatch):
        from services import mca_gates
        monkeypatch.setattr(mca_gates, "retrieval_context_enabled",
                            lambda: True)
        monkeypatch.setattr(mca_gates, "episodes_compiler_facade_enabled",
                            lambda: False)
        await db.save_smart_message(
            111, CHAT, "дроны тогда летали над дачей", None, _ts(2022, 7, 3),
            "text", "Толя", message_id=30_001)
        _block, stats = await _service(db)._build_old_episodes(
            CHAT, "расскажи историю про дроны", [], {})
        assert "year_window" not in stats
        assert stats["period_intent"]["kind"] in (
            mrc.PERIOD_INTENT_NONE, mrc.PERIOD_INTENT_HISTORICAL)


# ── профиль: субъектные ссылки и годы 2023/2024 ─────────────────────────────


class TestSubjectProfileMaterial:
    @pytest.mark.asyncio
    async def test_db_read_returns_subject_and_speaker_years(self, db):
        about_2026 = await _fact(db, "Лёха любит чай", year=2026,
                                 subject_ref=None, target="Лёха",
                                 speaker=UID)
        said_2024 = await _fact(db, "в 2024 сменил работу", year=2024,
                                subject_ref=None, target="другой",
                                speaker=UID, status="archived_fact")
        said_2023 = await _fact(db, "в 2023 переехал", year=2023,
                                subject_ref=None, target="другой",
                                speaker=UID, status="archived_fact")
        foreign = await _fact(db, "чужой факт 2023", year=2023,
                              subject_ref=None, target="другой",
                              speaker=999)
        rows = await db.get_subject_profile_facts(
            CHAT, "Лёха", 10, int(time.time()), user_id=UID)
        returned = {row["id"] for row in rows}
        assert about_2026 in returned
        assert said_2023 in returned and said_2024 in returned
        assert foreign not in returned
        by_id = {row["id"]: row for row in rows}
        assert by_id[about_2026]["subject_role"] == "subject"
        assert by_id[said_2023]["subject_role"] == "speaker"
        assert by_id[said_2023]["speaker_author_id"] == UID
        years = {time.gmtime(int(row["message_timestamp"])).tm_year
                 for row in rows}
        assert {2023, 2024, 2026} <= years

    @pytest.mark.asyncio
    async def test_tool_biography_envelope_carries_refs_and_years(self, db):
        await _fact(db, "Лёха любит чай", year=2026, target="Лёха",
                    speaker=UID)
        await _fact(db, "в 2024 сменил работу", year=2024, target="другой",
                    speaker=UID, status="archived_fact")
        await _fact(db, "в 2023 переехал", year=2023, target="другой",
                    speaker=UID, status="archived_fact")
        await _fact(db, "чужой факт 2023", year=2023, target="другой",
                    speaker=999)
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        import json
        payload = json.loads(raw)
        facts = payload["facts"]
        years = {fact.get("as_of_year") for fact in facts}
        assert {2023, 2024} <= years, years
        assert any(fact.get("speaker_author_id") == UID for fact in facts)
        assert all(str(fact.get("text") or "").strip() for fact in facts)
        # Чужая строка не выдаётся за сведения о P1: если она вообще попала
        # в профиль (общий контекст чата), она помечена `unattributed` и не
        # входит в субъектное покрытие.
        foreign = [fact for fact in facts
                   if "чужой факт" in str(fact.get("text"))]
        assert all(fact.get("unattributed") for fact in foreign)
        assert payload["subject_material"]["subject_bound"] >= 3
        assert {2023, 2024} <= set(payload["subject_material"]["years"])

    @pytest.mark.asyncio
    async def test_no_subject_data_is_honest_empty_not_author_fallback(self,
                                                                       db):
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        import json
        payload = json.loads(raw)
        assert payload["no_data"] is True
        assert payload["facts"] == []
        assert payload["subject_material"]["subject_bound"] == 0
        assert payload["subject_material"]["limitation"] == \
            "no_subject_bound_material"

    @pytest.mark.asyncio
    async def test_author_message_periods_are_bounded_and_exact(self, db):
        mine_2023 = await db.save_smart_message(
            UID, CHAT, "моё сообщение 2023", None, _ts(2023, 3, 1), "text",
            "Лёха", message_id=41_001)
        mine_2024 = await db.save_smart_message(
            UID, CHAT, "моё сообщение 2024", None, _ts(2024, 3, 1), "text",
            "Лёха", message_id=41_002)
        foreign = await db.save_smart_message(
            999, CHAT, "чужое 2023", None, _ts(2023, 3, 2), "text",
            "Толя", message_id=41_003)
        rows = await db.get_author_message_periods(
            CHAT, UID, 10, reference_year=2026)
        ids = {row["id"] for row in rows}
        assert mine_2023 in ids and mine_2024 in ids
        assert foreign not in ids
        years = {time.gmtime(int(row["timestamp"])).tm_year for row in rows}
        assert {2023, 2024} <= years
        assert all(row["speaker_author_id"] == UID for row in rows)
        assert all(row["subject_role"] == "speaker" for row in rows)

    @pytest.mark.asyncio
    async def test_tool_biography_uses_own_messages_when_no_facts(self, db):
        """У P1 есть 44 577 сообщений 2023-2024, но фактов о нём за эти годы
        может не быть: профиль обязан взять его СОБСТВЕННЫЕ сообщения с
        точным uid, а не чужой материал и не author=subject fallback."""
        await db.save_smart_message(
            UID, CHAT, "в 2023 я переехал в другой город", None,
            _ts(2023, 4, 1), "text", "Лёха", message_id=42_001)
        await db.save_smart_message(
            UID, CHAT, "в 2024 я сменил работу", None,
            _ts(2024, 5, 1), "text", "Лёха", message_id=42_002)
        await db.save_smart_message(
            999, CHAT, "чужое сообщение 2023", None, _ts(2023, 4, 2),
            "text", "Толя", message_id=42_003)
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        import json
        payload = json.loads(raw)
        facts = payload["facts"]
        texts = [str(fact.get("text") or "") for fact in facts]
        assert any("2023" in text for text in texts), texts
        assert any("2024" in text for text in texts), texts
        assert not any("чужое сообщение" in text for text in texts)
        years = {fact.get("as_of_year") for fact in facts}
        assert {2023, 2024} <= years
        assert payload["subject_material"]["subject_bound"] >= 2
        assert {2023, 2024} <= set(payload["subject_material"]["years"])

    @pytest.mark.asyncio
    async def test_reply_profile_rows_do_not_read_author_calendar_windows(
            self, db):
        """TIME-03: прямой путь профиля больше НЕ читает календарные окна
        сообщений автора (`get_author_message_periods`); профиль человека —
        только его факты/атрибуция `scope="whole"`."""
        await db.save_smart_message(
            UID, CHAT, "в 2023 я переехал", None, _ts(2023, 4, 1), "text",
            "Лёха", message_id=43_001)
        await db.save_smart_message(
            UID, CHAT, "в 2024 я сменил работу", None, _ts(2024, 5, 1),
            "text", "Лёха", message_id=43_002)
        reads = {"messages": 0}
        original = db.get_author_message_periods

        async def _spy(*args, **kwargs):
            reads["messages"] += 1
            return await original(*args, **kwargs)

        db.get_author_message_periods = _spy
        service = dcs.DirectChatService(memory=object(), db=db, llm=None,
                                        aliases=None)
        base = [{"id": 901, "fact": "текущий факт", "rag_ts": _ts(2026),
                 "message_timestamp": _ts(2026), "origin": "chat_history"}]
        out = await service._rag_append_profile_rows(
            db, base, CHAT, "что говорил Лёха?", "Лёха", UID, 10)
        assert reads["messages"] == 0, (
            "календарные окна сообщений автора удалены из прямого пути")
        assert len(out) == len(base)

    @pytest.mark.asyncio
    async def test_reply_profile_rows_carry_subject_years(self, db):
        """Reply-путь (`_rag_append_profile_rows`) получает субъектный
        материал 2023/2024 с ролью `subject|speaker` из одного `whole`-чтения,
        а не через календарное окно автора."""
        await _fact(db, "в 2024 сменил работу", year=2024, target="другой",
                    speaker=UID, status="archived_fact")
        await _fact(db, "в 2023 переехал", year=2023, target="другой",
                    speaker=UID, status="archived_fact")
        await _fact(db, "в 2022 женился", year=2022, target="другой",
                    speaker=UID, status="archived_fact")
        service = dcs.DirectChatService(memory=object(), db=db, llm=None,
                                        aliases=None)
        base = [{"id": 900, "fact": "текущий факт", "rag_ts": _ts(2026),
                 "message_timestamp": _ts(2026), "origin": "chat_history"}]
        out = await service._rag_append_profile_rows(
            db, base, CHAT, "что говорил Лёха?", "Лёха", UID, 10)
        added = out[len(base):]
        years = {mrc.period_row_year(row) for row in added}
        # Один `whole`-профиль, бюджет добора limit//5=2: два старых года
        # достижимы без 3-летнего окна и без годовой квоты.
        assert years == {2023, 2024}, years
        assert all(row.get("period_fill") for row in added)
        assert all(row.get("subject_role") == "speaker" for row in added)
        assert all(row.get("origin") != "bot_direct_reply" for row in added)

    @pytest.mark.asyncio
    async def test_foreign_material_is_not_counted_as_subject(self, db):
        await _fact(db, "совсем другой человек", year=2023, target="другой",
                    speaker=999)
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        import json
        payload = json.loads(raw)
        assert payload["subject_material"]["subject_bound"] == 0
        assert payload["subject_material"]["limitation"] == \
            "no_subject_bound_material"
        for fact in payload["facts"]:
            assert fact.get("unattributed") is True, fact
            assert fact.get("subject_role") is None
            assert fact.get("subject_ref_id") is None


# ── связи: временная проекция существующих sourced-рёбер ───────────────────


class TestRelationsTemporalProjection:
    @pytest.mark.asyncio
    async def test_existing_edge_carries_year_and_denominator(self, db):
        sid = await db.upsert_node(CHAT, "Лёха", "user")
        tid = await db.upsert_node(CHAT, "Толя", "user")
        await db.upsert_edge(sid, tid, "дружил с", fact_id=None)
        await db.db.execute(
            "UPDATE edges SET last_updated = '2023-06-01 12:00:00'")
        await db.db.commit()
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "relationships", "user_id": UID},
            ToolContext(CHAT, "как менялись отношения за эти годы"))
        import json
        payload = json.loads(raw)
        projection = payload["temporal_projection"]
        assert projection["edges_total"] == 1
        assert projection["year_bearing"] == 1
        assert projection["years"] == [2023]
        assert projection["reason"] == "ok"
        assert projection["invented"] == 0
        assert payload["facts"], "sourced-ребро не доставлено"
        assert payload["facts"][0]["as_of_year"] == 2023
        assert payload["facts"][0]["time"] > 0

    @pytest.mark.asyncio
    async def test_no_edges_returns_non_vacuous_reason(self, db):
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "relationships", "user_id": UID},
            ToolContext(CHAT, "как менялись отношения за эти годы"))
        import json
        payload = json.loads(raw)
        assert payload["no_data"] is True
        projection = payload["temporal_projection"]
        assert projection["edges_total"] == 0
        assert projection["year_bearing"] == 0
        assert projection["reason"] == "no_edges"
        assert projection["invented"] == 0
