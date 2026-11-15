"""VMQ-MEM/TIME Slice C — M2-обзор включается структурным намерением.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/root-cause-2026-11-15.md`
§2/§3 (M2-триггер — лексический дефект: «рассказ ... шизах» не включает обзор,
«история/расскажи» включает) и `measurement-2026-11-15.md` §3 (вопрос
`A1_creative_owner` = точная формулировка владельца).

Проверяется на реальном пути кода (`DirectChatService._build_rag_block` →
`_rag_unified_rows` → единый `retrieve`), temp/БД в памяти, без моков вместо
предмета проверки:

* точная формулировка владельца и равнозначные повествовательные/временные
  формы получают ТУ ЖЕ bounded-overview допустимость, что и прежние
  «история/расскажи»: слоты bundle несут фактическое покрытие, независимые
  периоды, контрпримеры и честные ограничения ИЗ ТОГО ЖЕ `RetrievalResult`;
* отрицание: вопрос о текущем состоянии («что сейчас …») обзора не получает,
  обычный путь остаётся прежним (ноль episode-чтений, тот же запрос);
* триггер — существующий структурный `PeriodIntent` (явный год, L1-план
  `historical_recall`, историческая политика), а не новый список слов; если
  структурного сигнала нет, обзора нет — честная тишина, а не догадка;
* аддитивность: один `retrieve`, один `EvidenceBundle`; допустимость обзора
  не меняет кандидатов, каналы и порядок.

TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/vmq-mem Slice C
R17: только синтетические факты/сообщения, никаких реальных переписок.
"""
import types

import pytest

from services import direct_chat_service as dcs
from services import mca_retrieval_context as mrc
from tests.test_memory_unified_retrieval import (
    CHAT,
    SUBJECT_NAME,
    T2021,
    UID,
    _MemorySpy,
    _add_fact,
    _bind_subject,
    _bundle_blocks,
    _db,
    _dcs,
    _msg_stub,
    _overview_fixture,
    _spy_retrieve,
    _trace_sql,
)

#: Точная формулировка владельца (measurement-2026-11-15 §3, `A1_creative_owner`).
OWNER_CREATIVE = "напиши юмористический рассказ об основных шизах конфы"
#: Равнозначные повествовательные/временные формы (не только «расскажи»).
HISTORY_FORMULATIONS = (
    OWNER_CREATIVE,
    "расскажи смешную историю про наши шутки и приколы за все годы",
    "перескажи, о чём мы говорили в этом чате за все годы",
    "из-за чего мы ссорились и ругались в 2023 году",
)
#: Вопрос о текущем состоянии — обзор не запрашивается.
CURRENT_STATE_QUERIES = (
    "что сейчас происходит с дронами?",
    "что с дронами",
)
#: Без структурного сигнала (ни года, ни плана, ни исторической формы) —
#: обзора нет: новый список слов не вводится.
NO_SIGNAL_QUERY = "что за шизы были на конфе?"


def _msg(text, mid=1):
    stub = _msg_stub(mid)
    stub.text = text
    return stub


def _vector_spy(fact_id=1, fact="шизы на конфе обсуждали", chat=CHAT, ts=T2021):
    """Существующий vector-канал: одна реальная строка `graph_facts`.

    Нужна, чтобы `_build_rag_block` рендерил непустой блок на обычном пути
    (формулировка владельца не совпадает с ней лексически)."""
    return _MemorySpy(rows=[{
        "id": fact_id, "fact": fact, "origin": "chat_history",
        "status": "confirmed", "chat_id": chat, "created_at": ts,
        "message_timestamp": ts, "target_user": None,
        "tg_message_id": 900 + fact_id, "expires_at": None,
        "subject_ref_id": None, "speaker_author_id": None,
    }])


async def _history_db():
    db = await _db()
    await _overview_fixture(db)
    ref_id = await _bind_subject(db, CHAT, UID)
    await _add_fact(db, chat=CHAT, fact="Папаха любит дронов", ts=T2021,
                    target_user=SUBJECT_NAME, subject_ref_id=ref_id,
                    speaker=UID)
    return db


class TestStructuredOverviewTrigger:
    @pytest.mark.asyncio
    async def test_owner_creative_query_gets_overview_with_real_coverage(
            self, monkeypatch):
        db = await _history_db()
        try:
            svc = _dcs(db, _MemorySpy())
            calls = _spy_retrieve(monkeypatch)

            block, _hint = await svc._build_rag_block(
                CHAT, _msg(OWNER_CREATIVE), "", memory_scope="operative")
            # (сам блок RAG может быть пуст — у формулировки владельца нет
            # лексического совпадения с синтетической строкой фикстуры;
            # обзор покрытия от выдачи среза не зависит)
            assert isinstance(block, str)
            # один маршрут: один retrieve, и он запросил overview
            assert len(calls) == 1
            assert calls[0].include_overview is True

            result = svc._rag_overview_result
            assert result is not None and result.overview is not None
            overview = result.overview
            # покрытие — фактическое: 2021/2023 есть, 2022 пропущен
            assert [p["period"] for p in overview.coverage["present_periods"]] \
                == ["2021", "2023"]
            assert overview.coverage["missing_periods"] == ["2022"]
            assert overview.coverage["complete"] is False
            assert overview.independent_periods == ("2021", "2023")
            assert overview.counterexamples
            assert overview.limitations

            bundle = await svc._build_evidence_bundle(
                CHAT, _msg(OWNER_CREATIVE), OWNER_CREATIVE, SUBJECT_NAME,
                UID, _bundle_blocks(), retrieval_result=result)
            assert bundle is not None
            # слоты bundle = тот же результат, никакого второго чтения
            assert bundle.coverage
            assert "2021: эпизодов 1" in bundle.coverage
            assert "пропущены периоды: 2022" in bundle.coverage
            assert bundle.independent_periods == ("2021", "2023")
            assert tuple(bundle.limitations) == tuple(overview.limitations)
            assert set(bundle.episode_refs) == set(overview.episode_refs)
            # выданное покрытие не выходит за материал retrieval
            present = {p["period"] for p in overview.coverage["present_periods"]}
            assert present == {"2021", "2023"}
            scoped = dcs._bundle_scoped_slice(bundle)
            assert "Покрытие памяти" in scoped
            assert "Независимые периоды: 2021, 2023" in scoped
            assert "Ограничения памяти" in scoped
        finally:
            await db.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", HISTORY_FORMULATIONS)
    async def test_narrative_and_temporal_formulations_trigger_overview(
            self, monkeypatch, query):
        db = await _history_db()
        try:
            svc = _dcs(db, _MemorySpy())
            calls = _spy_retrieve(monkeypatch)
            await svc._build_rag_block(
                CHAT, _msg(query, 11), "", memory_scope="operative")
            assert [c.include_overview for c in calls] == [True]
            assert svc._rag_overview_result is not None
            assert svc._rag_overview_result.overview is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_plan_signal_triggers_overview_without_lexical_markers(
            self, monkeypatch):
        """L1-план `historical_recall` — структурный сигнал, слов в запросе нет."""
        db = await _history_db()
        try:
            svc = _dcs(db, _MemorySpy())
            calls = _spy_retrieve(monkeypatch)
            await svc._build_rag_block(
                CHAT, _msg(NO_SIGNAL_QUERY, 12), "", memory_scope="auto",
                plan_act="historical_recall")
            assert [c.include_overview for c in calls][0] is True
            assert svc._rag_overview_result is not None
            assert svc._rag_overview_result.overview is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_historical_scope_triggers_overview(self, monkeypatch):
        db = await _history_db()
        try:
            svc = _dcs(db, _MemorySpy())
            calls = _spy_retrieve(monkeypatch)
            await svc._build_rag_block(
                CHAT, _msg(NO_SIGNAL_QUERY, 13), "", memory_scope="historical")
            # политика `historical` = решение об историческом охвате: обзор
            # запрошен один раз (второй вызов — периодный добор, без обзора)
            assert calls[0].include_overview is True
            assert sum(1 for c in calls if c.include_overview) == 1
            assert svc._rag_overview_result is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_no_structured_signal_keeps_overview_off(self, monkeypatch):
        """Сигнала нет → обзора нет (никаких новых маркеров/догадок)."""
        intent = mrc.resolve_period_intent(NO_SIGNAL_QUERY,
                                           memory_scope="auto")
        assert intent.kind == mrc.PERIOD_INTENT_NONE
        assert intent.wants_overview is False
        db = await _history_db()
        try:
            svc = _dcs(db, _MemorySpy())
            calls = _spy_retrieve(monkeypatch)
            with _trace_sql(db) as trace:
                await svc._build_rag_block(
                    CHAT, _msg(NO_SIGNAL_QUERY, 14), "", memory_scope="auto")
            assert [c.include_overview for c in calls] == [False]
            assert svc._rag_overview_result is None
            assert not [s for s in trace.statements if "mca_episodes" in s]
        finally:
            await db.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", CURRENT_STATE_QUERIES)
    async def test_current_state_query_keeps_ordinary_path(self, monkeypatch,
                                                          query):
        db = await _history_db()
        try:
            fact = "дроны летают над парком"
            svc = _dcs(db, _vector_spy(fact_id=902, fact=fact))
            calls = _spy_retrieve(monkeypatch)
            with _trace_sql(db) as trace:
                block, _hint = await svc._build_rag_block(
                    CHAT, _msg(query, 15), "", memory_scope="auto")
            # тот же запрос, что и раньше: обзор не запрошен
            assert calls and calls[0].include_overview is False
            assert svc._rag_overview_result is None
            assert fact in block       # обычный блок памяти на месте
            assert not [s for s in trace.statements if "mca_episodes" in s]
            bundle = await svc._build_evidence_bundle(
                CHAT, _msg(query, 15), query, SUBJECT_NAME, UID,
                _bundle_blocks())
            assert bundle is not None
            assert bundle.coverage == ()
            assert bundle.independent_periods == ()
            assert bundle.counterexamples == ()
            assert bundle.limitations == ()
            scoped = dcs._bundle_scoped_slice(bundle)
            assert "Покрытие памяти" not in scoped
            assert "Ограничения памяти" not in scoped
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_empty_corpus_reports_no_invented_coverage(self, monkeypatch):
        """Пустой retrieval не выдаёт периодов за покрытие: пусто + limitation."""
        db = await _db()
        try:
            svc = _dcs(db, _MemorySpy())
            _spy_retrieve(monkeypatch)
            block, _hint = await svc._build_rag_block(
                CHAT, _msg(OWNER_CREATIVE, 16), "", memory_scope="operative")
            # пустая выдача: блок памяти не рендерится, но обзор запрошен
            assert block == ""
            result = svc._rag_overview_result
            assert result is not None and result.overview is not None
            overview = result.overview
            assert overview.coverage["present_periods"] == []
            assert overview.coverage["missing_periods"] == []
            assert overview.coverage["earliest_ts"] is None
            assert overview.coverage["latest_ts"] is None
            assert overview.coverage["complete"] is False
            assert overview.independent_periods == ()
            assert overview.counterexamples == ()
            # честная причина вместо выдуманного покрытия
            assert "no_episodes_in_scope" in overview.limitations
            assert "coverage_complete_unknown_until_archive_bounds_proven" \
                in overview.limitations

            bundle = await svc._build_evidence_bundle(
                CHAT, _msg(OWNER_CREATIVE, 16), OWNER_CREATIVE, SUBJECT_NAME,
                UID, _bundle_blocks(), retrieval_result=result)
            assert bundle is not None
            assert bundle.coverage == ()          # периодов не заявлено
            assert bundle.independent_periods == ()
            assert bundle.counterexamples == ()
            assert tuple(bundle.limitations) == tuple(overview.limitations)
            scoped = dcs._bundle_scoped_slice(bundle)
            assert "Покрытие памяти" not in scoped
            assert "Независимые периоды" not in scoped
            assert "Ограничения памяти" in scoped
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_plan_rescope_enriches_the_same_bundle(self, monkeypatch):
        """Живой порядок: блок до плана → пересборка по `historical_recall` →
        те же слоты в ТОМ ЖЕ bundle (второго retrieval/bundle не появляется)."""
        db = await _history_db()
        try:
            svc = _dcs(db, _vector_spy(fact_id=901))
            calls = _spy_retrieve(monkeypatch)
            block, _hint = await svc._build_rag_block(
                CHAT, _msg(NO_SIGNAL_QUERY, 19), "", memory_scope="auto")
            assert block and svc._rag_overview_result is None
            plan = types.SimpleNamespace(memory_scope="auto",
                                         response_act="historical_recall")
            ctx = {"chat_id": CHAT, "message": _msg(NO_SIGNAL_QUERY, 19),
                   "global_ctx": "", "history_sample": None, "projection": None,
                   "subject_name": None, "subject_uid": None}
            out = await svc._apply_plan_memory_scope([block], ctx, plan)
            # пересборка — тем же чтением: plan_act сам включает обзор
            assert sum(1 for c in calls if c.include_overview) == 1
            result = svc._rag_overview_result
            assert result is not None and result.overview is not None
            assert out and out[0].startswith("<RAG_Memory>")
            bundle = mrc.apply_overview_to_bundle(
                mrc.EvidenceBundle(context_version="v1"), result.overview)
            assert bundle.coverage
            assert bundle.independent_periods == ("2021", "2023")
            assert tuple(bundle.limitations) == tuple(
                result.overview.limitations)
        finally:
            await db.close()

    def test_intent_source_names_existing_signal(self):
        """`source` — существующий сигнал, а не новый список слов."""
        assert mrc.resolve_period_intent(
            OWNER_CREATIVE, memory_scope="auto").as_dict() == {
            "kind": mrc.PERIOD_INTENT_HISTORICAL,
            "years": [], "source": "query_marker"}
        assert mrc.resolve_period_intent(
            NO_SIGNAL_QUERY, memory_scope="auto",
            plan_act="historical_recall").as_dict()["source"] == "plan_act"
        assert mrc.resolve_period_intent(
            NO_SIGNAL_QUERY, memory_scope="auto",
            request_intent="what-happened").as_dict()["source"] == \
            "request_intent"
        assert mrc.resolve_period_intent(
            NO_SIGNAL_QUERY, memory_scope="auto",
            request_mode="history").as_dict()["source"] == "request_mode"
        assert mrc.resolve_period_intent(
            NO_SIGNAL_QUERY, memory_scope="historical").as_dict()["source"] \
            == "memory_scope"
        assert mrc.resolve_period_intent(
            "из-за чего мы ссорились и ругались в 2023 году",
            memory_scope="auto").as_dict() == {
            "kind": mrc.PERIOD_INTENT_YEAR, "years": [2023],
            "source": "query_year"}
        # без сигнала — `none`, обзора нет
        assert mrc.resolve_period_intent(
            NO_SIGNAL_QUERY, memory_scope="auto").wants_overview is False

    @pytest.mark.asyncio
    async def test_trigger_adds_no_retrieve_and_no_second_bundle(
            self, monkeypatch):
        db = await _history_db()
        try:
            svc = _dcs(db, _MemorySpy())
            calls = _spy_retrieve(monkeypatch)
            builds: list = []
            original = svc._build_evidence_bundle

            async def _counting(*args, **kwargs):
                builds.append(kwargs.get("retrieval_result"))
                return await original(*args, **kwargs)

            monkeypatch.setattr(svc, "_build_evidence_bundle", _counting)
            await svc._build_rag_block(
                CHAT, _msg(OWNER_CREATIVE, 17), "", memory_scope="operative")
            result = svc._rag_overview_result
            assert result is not None
            calls_before_bundle = len(calls)
            bundle = await svc._build_evidence_bundle(
                CHAT, _msg(OWNER_CREATIVE, 17), OWNER_CREATIVE, SUBJECT_NAME,
                UID, _bundle_blocks(), retrieval_result=result)
            assert bundle is not None
            # один retrieve на ход, один bundle и ни одного лишнего чтения
            assert calls_before_bundle == 1
            assert len(calls) == 1
            assert len(builds) == 1 and builds[0] is result
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_trigger_does_not_change_candidates_order_or_channels(
            self, monkeypatch):
        db = await _history_db()
        try:
            svc = _dcs(db, _MemorySpy())
            calls = _spy_retrieve(monkeypatch)
            with_overview = await svc._rag_unified_rows(
                CHAT, OWNER_CREATIVE, _msg(OWNER_CREATIVE, 18),
                memory_scope="operative", include_overview=True)
            plain = await svc._rag_unified_rows(
                CHAT, OWNER_CREATIVE, _msg(OWNER_CREATIVE, 18),
                memory_scope="operative")
            assert [row["id"] for row in with_overview] == \
                [row["id"] for row in plain]
            first, second = calls[0], calls[1]
            assert first.include_overview is True
            assert second.include_overview is False
            # каналы/режим/срез те же — меняется только флаг обзора
            assert first.channels == second.channels
            assert first.top_k == second.top_k
            assert first.mode == second.mode
            assert first.memory_scope == second.memory_scope
        finally:
            await db.close()
