"""VMQ-MEM / VMQ-MEM-TIME — Slice D: авторитет L1 вместо словаря запроса.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/slice-d-review-r2.md`
(Needs Fixes: D1/N1–N6) и ARCH_DECISION 15.11.2026: «настоящее vs историческое»
решает только `memory_scope` L1 и структурный `PeriodIntent.source`; словарь
формулировки не имеет права замещать текущий срез.

Покрытие (CONTRACT/REGRESSION):
* `period_replace_allowed`: `operative` — никогда, `historical` — всегда,
  `auto` — только `query_year|request_intent|plan_act|request_mode|memory_scope`;
  `query_marker` — нет;
* `_build_rag_block`/`_rag_unified_rows` под `auto`: текущий срез цел, старых
  строк 0, `replace_allowed=0`, `period_skipped` назван; профильные чтения при
  полном срезе не выполняются; под `historical` — старые строки есть;
* A1P: `historical` → 2024 (short-stem strict subject); `auto` → 2026:10
  без потери id;
* план `historical_recall` (в т.ч. `memory_scope=auto`) — multi-year вклад,
  один периодный retrieve; reuse пула не платит вторую ногу;
* `operative` — байт-паритет основного среза;
* N2: tool-биография добирает свободный конверт (пол, не потолок);
* TIME-04: трасса несёт `policy/replace_allowed/period_skipped/intent_source`,
  L1-карточка — `memory_scope`;
* TIME-07: размеченный набор v2, конкурирующие дистракторы, T3-контроль;
* TIME-01/02: собственные сообщения по годам, tool-биография с резервом,
  известный uid без материала честно назван.

TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/vmq-mem Slice D
R17: только синтетические факты/сообщения, никаких реальных переписок.
"""
import asyncio
import calendar
import json
import os
import time
import types

import pytest

from services import direct_chat_service as _dcs
from services import mca_retrieval_context as mrc
from services import turn_trace as tt
from services.database import DatabaseService
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT = -100
UID = 7
A1_CREATIVE = "напиши юмористический рассказ об основных шизах конфы"
A1P_PLAIN = "что за шизы были на конфе?"
CURRENT_E1 = "что сейчас происходит с E1?"
CURRENT_ALINA = "что сейчас с Алиной?"
CURRENT_MULYANKA = "как дела с мулянкой?"
CURRENT_MARKER = "расскажи, что сейчас с мулянкой?"
CONFLICT_2023 = "из-за чего мы ссорились и ругались в 2023 году"
LABELED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "vmq_slice_d_labeled.json")


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


def _row(fid, text, *, year=None, source="lexical", ts=None,
         status="confirmed", expires_at=None, weight=0.6, importance=5):
    row = {"id": fid, "fact": text, "origin": "history_import",
           "status": status, "expires_at": expires_at,
           "created_at": _ts(year) if year else ts,
           "message_timestamp": _ts(year) if year else ts,
           "weight": weight, "importance": importance,
           "tg_message_id": 800 + fid, "chat_id": CHAT,
           "item_id": f"fact:{fid}"}
    if source:
        row["period_source"] = source
        row["subject_proxy"] = "knn" if source == "vector" else "stems"
    return row


def _current_rows(count=10, ids=None):
    ids = list(ids or range(8000, 8000 + count))
    return [{"id": fid, "fact": f"текущий факт {index}", "origin": "chat_history",
             "status": "confirmed", "created_at": _ts(2026),
             "message_timestamp": _ts(2026), "rag_ts": _ts(2026),
             "chat_id": CHAT, "item_id": f"fact:{fid}"}
            for index, fid in enumerate(ids)]


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
    return ToolRouter(ToolDeps(search=None, memory=None,
                               aliases=aliases or FakeAliases({str(UID): "Лёха"}),
                               db=db))


class _Result:
    def __init__(self, fact_rows, period_fill=None):
        self.fact_rows = tuple(fact_rows)
        self.period_fill = period_fill


def _service(monkeypatch, base_rows, period_rows=(), calls=None,
             db=None):
    """DirectChatService с подменённым `_rag_retrieve` (один шов)."""
    db = db or types.SimpleNamespace(
        search_messages_fts=lambda *a, **k: None)

    async def _identity_rerank(_query, facts):
        return list(facts)

    memory = types.SimpleNamespace(rerank_rag_facts=_identity_rerank)
    service = _dcs.DirectChatService(memory=memory, db=db, llm=None,
                                     aliases=None)

    async def fake(_db, _memory, chat_id, query, channels, limit, policy,
                   *, period_fill=False, period_intent=None, **_kwargs):
        if calls is not None:
            calls.append({
                "period_fill": bool(period_fill),
                "policy": policy,
                "intent": period_intent.as_dict() if period_intent else None,
                # TIME-03 §4.1: прямой путь не передаёт календарный фильтр.
                "exclude_years": tuple(_kwargs.get("exclude_years") or ()),            })
        if period_fill:
            return _Result(period_rows,
                           period_fill={"vector_leg": "compat_not_proven",
                                        "vector_rows": 0})
        return _Result(base_rows)

    monkeypatch.setattr(service, "_rag_retrieve", fake)
    return service


def _stub(**kwargs):
    base = {"text": "", "chat_id": CHAT, "message_id": 0}
    base.update(kwargs)
    return types.SimpleNamespace(**base)


# ── авторитет: предикат замещения ─────────────────────────────────────────


class TestReplaceAuthority:
    def test_sources_and_policy_matrix(self):
        assert mrc.period_replace_allowed(
            mrc.resolve_period_intent(CONFLICT_2023), "auto") is True
        assert mrc.period_replace_allowed(
            mrc.PeriodIntent(mrc.PERIOD_INTENT_MULTI_YEAR, (),
                             "request_intent"), "auto") is True
        assert mrc.period_replace_allowed(
            mrc.PeriodIntent(mrc.PERIOD_INTENT_MULTI_YEAR, (),
                             "plan_act"), "auto") is True
        assert mrc.period_replace_allowed(
            mrc.PeriodIntent(mrc.PERIOD_INTENT_MULTI_YEAR, (),
                             "request_mode"), "auto") is True
        assert mrc.period_replace_allowed(
            mrc.PeriodIntent(mrc.PERIOD_INTENT_HISTORICAL, (),
                             "memory_scope"), "auto") is True
        # Словарная формулировка не имеет права замещать срез.
        marker = mrc.resolve_period_intent(A1_CREATIVE)
        assert marker.source == "query_marker"
        assert mrc.period_replace_allowed(marker, "auto") is False
        assert mrc.period_replace_allowed(marker, "operative") is False
        # `historical` разрешает и словарному намерению (oversight M2 не
        # теряется, но факты замещаются только по решению L1).
        assert mrc.period_replace_allowed(marker, "historical") is True
        assert mrc.period_replace_allowed(mrc.PeriodIntent(), "auto") is False


# ── D1: real caller, full slice, marker, profile ──────────────────────────


class TestCurrentStatePaths:
    @pytest.mark.asyncio
    async def test_build_rag_block_auto_keeps_slice_historical_control(
            self, monkeypatch):
        """D1 (real caller): `_build_rag_block(auto, subject_name/uid)` не
        теряет текущие id; контроль с `historical` даёт старые строки."""
        base = _current_rows(10)
        old = [_row(8101, "Алина была в 2022", year=2022),
               _row(8102, "Алина снова в 2023", year=2023)]
        reads = {"profile": 0, "messages": 0}

        async def _profile(*_a, **_k):
            reads["profile"] += 1
            return []

        async def _messages(*_a, **_k):
            reads["messages"] += 1
            return []

        db = types.SimpleNamespace(search_messages_fts=lambda *a, **k: None,
                                   get_subject_profile_facts=_profile,
                                   get_author_message_periods=_messages)
        service = _service(monkeypatch, base, old, db=db)
        trace: dict = {}
        block, _hint = await service._build_rag_block(
            CHAT, _stub(text=CURRENT_ALINA), "", memory_scope="auto",
            subject_name="Alina", subject_uid=485008070, out_memory=trace)
        assert block, "текущий блок не должен исчезнуть"
        ids = set(trace.get("source_ids") or ())
        assert {f"fact:{i}" for i in range(8000, 8010)} <= ids, ids
        assert trace["period"]["replace_allowed"] == 0
        assert trace["period"]["kept"] == 0
        assert trace["period"]["period_skipped"] in (
            "auto_full_slice", "auto_thin_slice")
        assert reads == {"profile": 0, "messages": 0}
        # Контроль: `historical` — старые строки реально приходят.
        trace_hist: dict = {}
        await service._build_rag_block(
            CHAT, _stub(text=CURRENT_ALINA), "", memory_scope="historical",
            subject_name="Alina", subject_uid=485008070,
            out_memory=trace_hist)
        assert trace_hist["period"]["replace_allowed"] == 1
        assert trace_hist["period"]["kept"] == 2
        assert {2022, 2023} <= set(trace_hist["years"])

    @pytest.mark.asyncio
    async def test_unmarked_present_questions_keep_ids_and_skip(self,
                                                               monkeypatch):
        """D1: unmarked present questions — `auto_full_slice`, id целы."""
        for query in (CURRENT_MULYANKA, "что нового у Алины?"):
            calls: list = []
            base = _current_rows(10)
            service = _service(monkeypatch, base, [], calls=calls)
            rows = await service._rag_unified_rows(
                CHAT, query, _stub(text=query), memory_scope="auto")
            assert {row["id"] for row in rows} == set(range(8000, 8010))
            stats = service._rag_period_stats
            assert stats["replace_allowed"] == 0
            assert stats["period_skipped"] == "auto_full_slice"
            assert len(calls) == 1 and calls[0]["period_fill"] is False

    @pytest.mark.asyncio
    async def test_marker_present_question_auto_vs_historical(self,
                                                              monkeypatch):
        """D1: `«расскажи, что сейчас…»` — `query_marker`; auto не замещает,
        historical — замещает (не вакуумный контроль)."""
        base = _current_rows(10)
        old = [_row(8201, "мулянкой и сейчас", year=2022),
               _row(8202, "мулянкой и сейчас снова", year=2023)]
        calls: list = []
        service = _service(monkeypatch, base, old, calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, CURRENT_MARKER, _stub(text=CURRENT_MARKER),
            memory_scope="auto")
        stats = service._rag_period_stats
        assert stats["intent_source"] == "query_marker"
        assert stats["replace_allowed"] == 0
        assert {row["id"] for row in rows} == set(range(8000, 8010))
        # Current-state query: base call + bounded current-fact leg, but the
        # Slice D boundary still keeps the base composition (no period fill).
        assert len(calls) == 2
        assert stats["current_leg_calls"] == 1
        assert stats["current_leg_used"] == 0

        rows = await service._rag_unified_rows(
            CHAT, CURRENT_MARKER, _stub(text=CURRENT_MARKER),
            memory_scope="historical")
        assert any(row.get("period_fill") for row in rows), rows
        assert service._rag_period_stats["breadth_reason"] == \
            "policy_historical"

    @pytest.mark.asyncio
    async def test_profile_reads_not_called_on_full_auto_slice(self,
                                                               monkeypatch):
        """D1: профиль под auto при полном срезе — 0 чтений, 0 period_fill."""
        reads = {"profile": 0, "messages": 0}

        async def _profile(*_a, **_k):
            reads["profile"] += 1
            return []

        async def _messages(*_a, **_k):
            reads["messages"] += 1
            return []

        db = types.SimpleNamespace(search_messages_fts=lambda *a, **k: None,
                                   get_subject_profile_facts=_profile,
                                   get_author_message_periods=_messages)
        service = _service(monkeypatch, _current_rows(10), [], db=db)
        rows = await service._rag_unified_rows(
            CHAT, CURRENT_ALINA, _stub(text=CURRENT_ALINA),
            memory_scope="auto", subject_name="Alina",
            subject_uid=485008070)
        assert len(rows) == 10
        assert not any(row.get("period_fill") for row in rows)
        assert reads == {"profile": 0, "messages": 0}

    @pytest.mark.asyncio
    async def test_a1p_historical_vs_auto(self, monkeypatch):
        """A1P: historical — 2024 через short-stem strict subject; auto — 2026:10.

        RC4/A2: `шизах` нормализуется в `шиз`, поэтому `на шизах и конф` —
        строгий subject-match. P-OLDROW R1 (контракт
        `selector-rootcause-2026-11-27.md` §3): при `historical` и ≥2 soft-
        строках в первые слоты входит РОВНО ОДНА строка с годом строго старше
        принятого (принята 2024 → 2023; 2025 новее и не выбирается), поэтому
        состав — 2026:8 + 2024:1 + 2023:1 при том же бюджете `limit//5=2`;
        календарной квоты по-прежнему нет. Ожидание обновлено с явной ссылкой
        на контракт; auto остаётся 2026:10."""
        base = _current_rows(10)
        pool = [
            _row(1, "конфа тогда шумела", year=2023),
            _row(2, "на конфе шумели", year=2024),
            _row(3, "на шизах и конф", year=2024),
            _row(4, "шизы обсуждали", year=2025),
        ]
        service = _service(monkeypatch, base, pool)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN),
            memory_scope="historical")
        years = {}
        for row in rows:
            year = mrc.period_row_year(row)
            if year:
                years[year] = years.get(year, 0) + 1
        assert years == {2026: 8, 2024: 1, 2023: 1}, years
        # RC4: строгий subject-match уже дал 2024; soft-fallback не нужен.
        assert service._rag_period_stats["soft_fallback"] == 0
        assert service._rag_period_stats["historical_quota"] == 0
        assert service._rag_period_stats["reserved_old"] == 1

        calls: list = []
        service = _service(monkeypatch, base, pool, calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto")
        assert {row["id"] for row in rows} == set(range(8000, 8010))
        assert service._rag_period_stats["period_skipped"] == \
            "auto_full_slice"
        assert len(calls) == 1 and calls[0]["period_fill"] is False


# ── план L1 / T2 ─────────────────────────────────────────────────────────


class TestPlanSignal:
    @pytest.mark.asyncio
    async def test_plan_act_multi_year_quota(self, monkeypatch):
        """TIME-03: `historical_recall` больше не получает календарную квоту.

        Прежний `multi_year_quota=2` заменён предметным soft-fallback:
        строки «того же предмета» входят по смыслу, без выбора года и без
        обязательной доли старого; бюджет — только `limit//5` строк."""
        base = _current_rows(10)
        pool = [_row(11, "вообще про E1", year=2023),
                _row(12, "было про E1", year=2024),
                _row(13, "напомни про E1", year=2025)]
        calls: list = []
        service = _service(monkeypatch, base, pool, calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, "что вообще было с E1, напомни?",
            _stub(text="что вообще было с E1, напомни?"),
            memory_scope="auto", plan_act="historical_recall")
        stats = service._rag_period_stats
        assert stats["replace_allowed"] == 1
        assert stats["intent_source"] == "plan_act"
        assert stats["breadth_allowed"] == 1
        assert stats["breadth_reason"] == "plan_historical"
        assert stats["breadth_used"] == 2
        assert stats["soft_fallback"] == 2
        assert stats["multi_year_quota"] == 0
        assert stats["historical_quota"] == 0
        assert len([c for c in calls if c["period_fill"]]) == 1
        years = {mrc.period_row_year(row) for row in rows
                 if row.get("period_fill")}
        assert {2023, 2024} <= years

    @pytest.mark.asyncio
    async def test_apply_plan_memory_scope_replaces_and_reuses_pool(
            self, monkeypatch):
        """Полный путь: план `historical_recall` пересобирает блок, пул
        периода переиспользуется (вторая нога не платится)."""
        base = _current_rows(10)
        pool = [_row(21, "событие E1 в 2023", year=2023),
                _row(22, "событие E1 в 2024", year=2024)]
        service = _service(monkeypatch, base, pool)
        service._rag_period_pool = {
            "key": (CHAT, "что вообще было с E1, напомни?"),
            "rows": [dict(row) for row in pool],
            "meta": {"vector_leg": "compat_not_proven", "vector_rows": 0,
                     "period_intent": {"kind": "multi_year", "years": [],
                                       "source": "plan_act"}},
        }
        calls: list = []
        original = service._rag_retrieve

        async def spy(*args, **kwargs):
            calls.append(bool(kwargs.get("period_fill")))
            return await original(*args, **kwargs)

        monkeypatch.setattr(service, "_rag_retrieve", spy)
        plan = types.SimpleNamespace(memory_scope="auto",
                                     response_act="historical_recall")
        blocks = await service._apply_plan_memory_scope(
            ["<RAG_Memory>auto</RAG_Memory>"],
            {"chat_id": CHAT, "message": _stub(
                text="что вообще было с E1, напомни?"),
             "global_ctx": "", "history_sample": None, "projection": None,
             "subject_name": None, "subject_uid": None}, plan)
        assert blocks and blocks[0] != "<RAG_Memory>auto</RAG_Memory>"
        assert service._rag_period_stats["period_leg_reused"] == 1
        assert calls == [False], "пул переиспользован — периодного retrieve нет"


# ── TIME-03 natural memory: bounded post-plan breadth ────────────────────


class TestNaturalBreadth:
    """TIME-03 (контракт 2026-11-20 §3.1/§3.2/§4.1): `research` и тонкий
    срез получают bounded добор; полный `auto`+`answer` остаётся базовым;
    календарных фильтров в прямом пути нет."""

    POOL = [_row(1, "шизы и конф на конфе", year=2023),
            _row(2, "конф и шизы снова", year=2024)]

    @pytest.mark.asyncio
    async def test_t1_auto_answer_full_slice_stays_base(self, monkeypatch):
        calls: list = []
        service = _service(monkeypatch, _current_rows(10), self.POOL,
                           calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act="answer")
        stats = service._rag_period_stats
        assert {row["id"] for row in rows} == set(range(8000, 8010))
        assert stats["breadth_allowed"] == 0
        assert stats["breadth_reason"] == "none"
        assert stats["period_skipped"] == "auto_full_slice"
        assert len(calls) == 1 and calls[0]["period_fill"] is False

    @pytest.mark.asyncio
    async def test_t1b_thin_slice_triggers_strict_breadth(self, monkeypatch):
        calls: list = []
        base = _current_rows(3)
        service = _service(monkeypatch, base, self.POOL, calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act="answer")
        stats = service._rag_period_stats
        assert stats["breadth_allowed"] == 1
        assert stats["breadth_reason"] == "thin_base"
        # Тонкий срез добирается строгой лексикой (без мягкого fallback).
        assert stats["soft_fallback"] == 0
        # Тонкий срез добран, а не оставлен пустым; лишних вызовов нет.
        assert len(calls) == 2
        period_calls = [call for call in calls if call["period_fill"]]
        assert len(period_calls) == 1
        assert period_calls[0]["exclude_years"] == ()
        added = [row for row in rows if row.get("period_fill")]
        assert {row["id"] for row in added} == {1, 2}
        # R1: тонкий base сохраняется целиком; добор занимает свободную
        # ёмкость среза, а не вытесняет текущие строки.
        assert [row["id"] for row in rows] == [8000, 8001, 8002, 1, 2]
        assert len(rows) == 5
        assert stats["breadth_used"] == 2

    @pytest.mark.asyncio
    async def test_t1b_empty_base_stays_empty_when_nothing_accepted(
            self, monkeypatch):
        calls: list = []
        service = _service(monkeypatch, [], [], calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act="answer")
        assert rows == []
        assert service._rag_period_stats["breadth_reason"] == "thin_base"
        assert service._rag_period_stats["breadth_used"] == 0
        assert len(calls) == 2, "тонкий/пустой срез — один bounded добор"

    @pytest.mark.asyncio
    async def test_t2_research_gets_bounded_breadth(self, monkeypatch):
        calls: list = []
        service = _service(monkeypatch, _current_rows(10), self.POOL,
                           calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act="research")
        stats = service._rag_period_stats
        assert stats["replace_allowed"] == 0, "research не исторический режим"
        assert stats["breadth_allowed"] == 1
        assert stats["breadth_reason"] == "plan_research"
        assert stats["breadth_used"] == 2
        assert len(calls) == 2
        assert [call["period_fill"] for call in calls] == [False, True]
        added = {row["id"] for row in rows if row.get("period_fill")}
        assert added == {1, 2}
        # Полный базовый срез сохраняет 8 строк: добавлено ровно 2.
        assert {row["id"] for row in rows} == (
            set(range(8000, 8008)) | {1, 2})

    @pytest.mark.asyncio
    async def test_t2b_one_accepted_cuts_exactly_one_base_row(self,
                                                             monkeypatch):
        pool = [_row(3, "шизы и конф", year=2023),
                _row(4, "совсем другое", year=2024)]
        service = _service(monkeypatch, _current_rows(10), pool)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act="research")
        ids = {row["id"] for row in rows}
        assert ids == set(range(8000, 8009)) | {3}
        assert 8009 not in ids, "потеряна ровно одна хвостовая строка"
        assert service._rag_period_stats["breadth_used"] == 1

    @pytest.mark.asyncio
    async def test_t2b_zero_accepted_keeps_base_intact(self, monkeypatch):
        pool = [_row(5, "совсем другое", year=2023),
                _row(6, "и это тоже другое", year=2024)]
        service = _service(monkeypatch, _current_rows(10), pool)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act="research")
        assert {row["id"] for row in rows} == set(range(8000, 8010))
        assert service._rag_period_stats["breadth_used"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("plan_act", ["research", "answer"])
    async def test_r1_thin_base_survives_when_accepted_equals_base(
            self, monkeypatch, plan_act):
        """R1 regression (review r1, IN_SCOPE High): 2 текущих факта + 2
        строго релевантных старых при `limit=10` не должны обнулять base.

        Тонкий/текущий срез сохраняется целиком; старые строки занимают
        только оставшуюся ёмкость. Полный срез по-прежнему отдаёт хвостовые
        слоты (T2/T2b), это отдельное поведение."""
        base = _current_rows(2)
        service = _service(monkeypatch, base, self.POOL)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act=plan_act)
        ids = [row["id"] for row in rows]
        assert ids == [8000, 8001, 1, 2], ids
        assert {8000, 8001} <= set(ids), "оба base-факта обязаны остаться"
        assert all(row.get("period_fill") for row in rows[2:]), rows
        assert service._rag_period_stats["breadth_used"] == 2

    @pytest.mark.asyncio
    async def test_t3_query_marker_keeps_slice_d_boundary(self, monkeypatch):
        calls: list = []
        service = _service(monkeypatch, _current_rows(10), self.POOL,
                           calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, CURRENT_MARKER, _stub(text=CURRENT_MARKER),
            memory_scope="auto", plan_act="answer")
        stats = service._rag_period_stats
        assert stats["intent_source"] == "query_marker"
        assert stats["replace_allowed"] == 0
        assert stats["breadth_allowed"] == 0
        assert stats["period_skipped"] == "auto_full_slice"
        assert {row["id"] for row in rows} == set(range(8000, 8010))
        assert len(calls) == 2
        assert stats["current_leg_calls"] == 1
        assert stats["current_leg_used"] == 0

    @pytest.mark.asyncio
    async def test_t17_added_rows_never_leave_chat_scope(self, db,
                                                         monkeypatch):
        """Все добранные строки — того же `chat_id`; чужой чат не протекает."""
        await _fact(db, "шизы и конф в нашем чате", year=2023,
                    target="Лёха")
        foreign = await _fact(db, "шизы и конф в чужом чате", year=2023,
                              target="Лёха", chat_id=CHAT - 1)
        current = await _fact(db, "текущий факт про дронов", year=2026,
                              target="Лёха")

        class _ScopedMemory:
            async def retrieve_fact_candidates(self, chat_id, query, **kw):
                row = await db.get_graph_fact_records([current])
                return [dict(row[0])] if chat_id == CHAT and row else []

            async def rerank_rag_facts(self, _query, facts):
                return list(facts)

        service = _dcs.DirectChatService(memory=_ScopedMemory(), db=db,
                                         llm=None, aliases=None)
        rows = await service._rag_unified_rows(
            CHAT, "что было про шизы и конф?",
            _stub(text="что было про шизы и конф?"), memory_scope="auto",
            plan_act="research")
        assert rows, "добор должен найти старую строку"
        ids = {row["id"] for row in rows}
        assert foreign not in ids
        assert all(int(row.get("chat_id") or CHAT) == CHAT for row in rows)

    @pytest.mark.asyncio
    async def test_t18_bounded_retrieve_cost(self, monkeypatch):
        for plan_act, expected_period_calls in (
                ("answer", 0), ("research", 1)):
            calls: list = []
            service = _service(monkeypatch, _current_rows(10), self.POOL,
                               calls=calls)
            await service._rag_unified_rows(
                CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
                plan_act=plan_act)
            assert sum(1 for call in calls if call["period_fill"]) == \
                expected_period_calls
            assert len(calls) <= 1 + expected_period_calls
        # `historical` — тот же предел: базовый срез + один bounded добор.
        calls = []
        service = _service(monkeypatch, _current_rows(10), self.POOL,
                           calls=calls)
        await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="historical")
        assert sum(1 for call in calls if call["period_fill"]) == 1
        assert len(calls) == 2
        calls = []
        service = _service(monkeypatch, _current_rows(10), self.POOL,
                           calls=calls)
        await service._rag_unified_rows(CHAT, CURRENT_ALINA,
                                        _stub(text=CURRENT_ALINA),
                                        memory_scope="operative")
        assert len(calls) == 1 and calls[0]["period_fill"] is False




class TestR4EvidenceRank:
    """TIME-03 r4: evidence-ranked base/period and lexical graph_fact anchors."""

    def test_evidence_rank_never_uses_year(self, monkeypatch):
        service = _service(monkeypatch, [], [])
        rows = [
            _row(1, "шизы и конф слабый", year=2026, weight=0.1,
                 importance=1),
            _row(2, "шизы и конф сильный", year=2022, weight=0.9,
                 importance=9),
            _row(3, "шизы и конф сильный", year=2024, weight=0.9,
                 importance=9),
        ]
        ranked = service._rag_evidence_rank(rows, A1P_PLAIN)
        assert [row["id"] for row in ranked] == [2, 3, 1], ranked
        # Equal evidence keeps the retrieval order whatever the years are;
        # the function has no calendar input at all.
        reversed_ranked = service._rag_evidence_rank(
            list(reversed(rows)), A1P_PLAIN)
        assert [row["id"] for row in reversed_ranked] == [3, 2, 1]

    @pytest.mark.asyncio
    async def test_period_append_prefers_evidence_not_order(self, monkeypatch):
        pool = [
            _row(1, "шизы и конф слабый", year=2023, weight=0.1,
                 importance=1),
            _row(2, "шизы и конф сильный", year=2022, weight=0.9,
                 importance=9),
            _row(3, "шизы и конф средний", year=2024, weight=0.5,
                 importance=5),
        ]
        service = _service(monkeypatch, _current_rows(10), pool)
        rows = await service._rag_unified_rows(
            CHAT, A1P_PLAIN, _stub(text=A1P_PLAIN), memory_scope="auto",
            plan_act="research")
        added = {row["id"] for row in rows if row.get("period_fill")}
        assert added == {2, 3}, added

    @pytest.mark.asyncio
    async def test_base_row_fact_becomes_current_episode_anchor(
            self, db, monkeypatch):
        for tg, ts, uid, text in (
                (9001, _ts(2026), 111, "работа и зарплата в 2026"),
                (9002, _ts(2026) + 120, 222, "обсуждали работу и зарплату"),
                (8001, _ts(2025), 111, "старая работа и зарплата")):
            await db.save_smart_message(uid, CHAT, text, None, ts, "text",
                                        f"U{uid}", message_id=tg)
        base_row = _row(77, "работа и зарплата в 2026", year=2026,
                        weight=0.9, importance=9)
        base_row["tg_message_id"] = 9001
        base_row["item_id"] = "tg:9001"
        service = _service(monkeypatch, [base_row], [], db=db)
        from services.summary_aliases import AliasResolver
        service.aliases = AliasResolver("{}")
        rows = await service._rag_unified_rows(
            CHAT, "что сейчас с работой и зарплатой?", _stub(
                text="что сейчас с работой и зарплатой?"),
            memory_scope="auto", plan_act="answer")
        assert any(row["id"] == 77 for row in rows)
        block, stats = await service._build_old_episodes(
            CHAT, "что сейчас с работой и зарплатой?", [], {})
        assert block
        assert stats["anchor_candidates"] >= 1
        assert mrc.year_time_bounds(2026)[0] <= stats["spans"][0]["first_ts"] \
            <= mrc.year_time_bounds(2026)[1]

    @pytest.mark.asyncio
    async def test_foreign_turn_base_rows_are_not_used(self, db, monkeypatch):
        await db.save_smart_message(
            111, CHAT, "работа и зарплата в 2026", None, _ts(2026),
            "text", "U111", message_id=9001)
        base_row = _row(77, "работа и зарплата в 2026", year=2026)
        base_row["tg_message_id"] = 9001
        base_row["item_id"] = "tg:9001"
        query = "что сейчас с работой и зарплатой?"

        async def fake(_db, _memory, request):
            return types.SimpleNamespace(candidates=(), fact_rows=())

        monkeypatch.setattr(mrc, "retrieve", fake)
        service = _service(monkeypatch, [], [], db=db)
        from services.summary_aliases import AliasResolver
        service.aliases = AliasResolver("{}")
        # Same query, matching stems and a real source message: only the turn
        # key differs. This discriminates the key guard from the >=2-stem
        # threshold (the old "квазар" variant did not).
        service._rag_last_rows = [base_row]
        service._rag_last_rows_key = (CHAT, "другой вопрос")
        block, stats = await service._build_old_episodes(
            CHAT, query, [], {})
        assert block == ""
        assert stats["anchor_candidates"] == 0

    @pytest.mark.asyncio
    async def test_second_similar_2022_anchor_is_ranked(self, db, monkeypatch):
        for tg, ts, text in (
                (9001, _ts(2022), "ссорились и ругались первый раз"),
                (9002, _ts(2022) + 120, "потом помирились"),
                (9101, _ts(2022, 7), "ссорились и ругались второй раз"),
                (9102, _ts(2022, 7) + 120, "снова помирились"),
                (8001, _ts(2024), "ссорились и ругались позже")):
            await db.save_smart_message(111, CHAT, text, None, ts, "text",
                                        "U111", message_id=tg)
        candidates = [
            types.SimpleNamespace(id="tg:9001", entity_type="message",
                                  channel="lexical",
                                  preview="ссорились и ругались первый раз",
                                  score=0.0),
            types.SimpleNamespace(id="tg:9101", entity_type="message",
                                  channel="lexical",
                                  preview="ссорились и ругались второй раз",
                                  score=0.0),
            types.SimpleNamespace(id="tg:8001", entity_type="message",
                                  channel="lexical",
                                  preview="ссорились и ругались позже",
                                  score=0.0),
        ]

        class _Result:
            fact_rows = ()
            def __init__(self):
                self.candidates = tuple(candidates)

        async def fake(_db, _memory, request):
            return _Result()

        monkeypatch.setattr(mrc, "retrieve", fake)
        service = _service(monkeypatch, [], [], db=db)
        from services.summary_aliases import AliasResolver
        service.aliases = AliasResolver("{}")
        service._rag_last_rows = []
        block, stats = await service._build_old_episodes(
            CHAT, "та самая история где ссорились и ругались", [], {})
        assert block
        assert stats["anchor_candidates"] >= 2
        years = [mrc.period_row_year({"message_timestamp": s["first_ts"]})
                 for s in stats["spans"][:2]]
        assert years == [2022, 2022], years


class TestR5CurrentFactLeg:
    """S4: bounded current-fact leg outside the base top-10."""

    @staticmethod
    def _fake_retrieve(base, extra, calls):
        async def fake(_db, _memory, chat_id, query, channels, limit, policy,
                       *, period_fill=False, **_kwargs):
            calls.append(int(limit))
            if period_fill:
                return _Result([])
            if int(limit) >= 32:
                return _Result(base + extra)
            return _Result(base)
        return fake

    @pytest.mark.asyncio
    async def test_three_current_facts_outside_top10_are_added(
            self, monkeypatch):
        base = [_row(9000 + i, f"текущий факт {i}", year=2026)
                for i in range(10)]
        required = [
            _row(15172, "вайп сервера завершён", year=2026, weight=0.9,
                 importance=9),
            _row(18330, "вайп сервера перенесён", year=2026, weight=0.9,
                 importance=9),
            _row(20419, "вайп сервера подтверждён", year=2026, weight=0.9,
                 importance=9),
        ]
        archived = _row(15175, "вайп сервера архивный", year=2026,
                        status="archived_fact", weight=0.9, importance=9)
        calls: list = []
        service = _service(monkeypatch, [], [])
        monkeypatch.setattr(
            service, "_rag_retrieve",
            self._fake_retrieve(base, required + [archived], calls))
        query = "что сейчас с вайпом и сервером?"
        rows = await service._rag_unified_rows(
            CHAT, query, _stub(text=query), memory_scope="auto",
            plan_act="answer")
        ids = {row["id"] for row in rows}
        assert {15172, 18330, 20419} <= ids, ids
        assert 15175 not in ids, "archived fact must not be current"
        assert len(rows) == 10, rows
        assert calls == [10, 32], calls
        stats = service._rag_period_stats
        assert stats["current_leg_calls"] == 1
        assert stats["current_leg_rows"] == 14
        assert stats["current_leg_used"] == 3
        assert all(row.get("current_fill") for row in rows
                   if row["id"] in {15172, 18330, 20419})

    @pytest.mark.asyncio
    async def test_non_current_question_keeps_one_call(self, monkeypatch):
        base = [_row(9000 + i, f"текущий факт {i}", year=2026)
                for i in range(10)]
        extra = [_row(15172, "вайп сервера завершён", year=2026)]
        calls: list = []
        service = _service(monkeypatch, [], [])
        monkeypatch.setattr(
            service, "_rag_retrieve", self._fake_retrieve(base, extra, calls))
        rows = await service._rag_unified_rows(
            CHAT, "расскажи про вайп и сервер", _stub(
                text="расскажи про вайп и сервер"), memory_scope="auto",
            plan_act="answer")
        assert {row["id"] for row in rows} == set(range(9000, 9010))
        assert calls == [10], calls
        assert service._rag_period_stats["current_leg_calls"] == 0
        assert service._rag_period_stats["current_leg_used"] == 0

    @pytest.mark.asyncio
    async def test_current_gate_is_load_bearing(self, monkeypatch):
        base = [_row(9000 + i, f"текущий факт {i}", year=2026)
                for i in range(10)]
        required = [_row(15172, "вайп сервера завершён", year=2026)]
        calls: list = []
        service = _service(monkeypatch, [], [])
        monkeypatch.setattr(
            service, "_rag_retrieve",
            self._fake_retrieve(base, required, calls))
        monkeypatch.setattr(_dcs, "_is_current_state_query",
                            lambda _query: False)
        query = "что сейчас с вайпом и сервером?"
        rows = await service._rag_unified_rows(
            CHAT, query, _stub(text=query), memory_scope="auto",
            plan_act="answer")
        assert 15172 not in {row["id"] for row in rows}
        assert calls == [10], calls
        assert service._rag_period_stats["current_leg_calls"] == 0


class TestOperativeParity:
    @pytest.mark.asyncio
    async def test_operative_returns_base_slice_only(self, monkeypatch):
        calls: list = []
        base = _current_rows(10)
        service = _service(monkeypatch, base, [_row(1, "старое", year=2023)],
                           calls=calls)
        rows = await service._rag_unified_rows(
            CHAT, CURRENT_ALINA, _stub(text=CURRENT_ALINA),
            memory_scope="operative", subject_name="Alina",
            subject_uid=485008070)
        assert {row["id"] for row in rows} == set(range(8000, 8010))
        assert service._rag_period_stats == {}
        assert calls == [{"period_fill": False, "policy": "operative",
                          "intent": None, "exclude_years": ()}]


# ── субъектная половина / N2 ─────────────────────────────────────────────


class TestSubjectHalf:
    @pytest.mark.asyncio
    async def test_author_messages_cover_three_completed_years(self, db):
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

    @pytest.mark.asyncio
    async def test_known_person_without_bound_material_is_named(self, db):
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        payload = json.loads(raw)
        assert payload["no_data"] is True
        assert payload["empty_reason"] == "no_subject_bound_material"
        assert payload["subject_material"]["limitation"] == \
            "no_subject_bound_material"

    @pytest.mark.asyncio
    async def test_unconfirmed_subject_facts_are_not_biography(self, db):
        await _fact(db, "непроверенный слух о Лёхе", year=2026,
                    subject_ref=15612, target="Лёха", status="unconfirmed")
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        payload = json.loads(raw)
        assert payload["no_data"] is True
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
        assert by_year[2026]["subject_ref_id"] == 15612

    @pytest.mark.asyncio
    async def test_biography_fills_free_envelope_beyond_reserve(self, db):
        """N2: 1 факт + 6 сообщений (3 старых года) → 7 фактов, а не 3."""
        await _fact(db, "единственный факт 2026", year=2026,
                    target="Лёха", speaker=UID)
        for year, mid in ((2023, 52_001), (2023, 52_002),
                          (2024, 52_003), (2024, 52_004),
                          (2025, 52_005), (2025, 52_006)):
            await db.save_smart_message(
                UID, CHAT, f"сообщение {year}", None, _ts(year, 4, 1),
                "text", "Лёха", message_id=mid)
        router = _router(db)
        raw = await router._get_user_context(
            {"person": "Лёха", "purpose": "biography", "user_id": UID},
            ToolContext(CHAT, "что ты знаешь про Лёху?"))
        payload = json.loads(raw)
        years = {fact.get("as_of_year") for fact in payload["facts"]}
        assert len(payload["facts"]) == 7, payload["facts"]
        assert {2023, 2024, 2025} <= years, years
        assert 2026 in years
        assert payload["subject_material"]["subject_bound"] >= 7

    @pytest.mark.asyncio
    async def test_subject_material_replaces_generic_period_row(self, db):
        """TIME-03: профиль человека (`scope="whole"`) вытесняет generic
        period-строку только при структурном сигнале и только если имя
        человека прозвучало в вопросе; календарные окна автора не читаются."""
        import services.direct_chat_service as _dcs2
        await _fact(db, "в 2023 Лёха переехал", year=2023,
                    target="другой", speaker=UID)
        service = _dcs2.DirectChatService(memory=object(), db=db, llm=None,
                                          aliases=None)
        base = [{"id": 900 + i, "fact": f"текущий факт {i}",
                 "rag_ts": _ts(2026), "message_timestamp": _ts(2026),
                 "origin": "chat_history"} for i in range(8)]
        generic = {"id": 999, "fact": "старый период", "rag_ts": _ts(2025),
                   "message_timestamp": _ts(2025),
                   "origin": "history_import", "period_fill": True}
        query = "что говорил Лёха про переезд?"
        out = await service._rag_append_profile_rows(
            db, base + [generic], CHAT, query, "Лёха", UID, 10,
            allow_replace=True)
        assert generic not in out
        assert any(row.get("subject_role") == "speaker" for row in out)
        # auto (allow_replace=False) не вытесняет period-строку.
        out2 = await service._rag_append_profile_rows(
            db, base + [generic], CHAT, query, "Лёха", UID, 10,
            allow_replace=False)
        assert generic in out2
        # Guard: адресат «Лёха» не прозвучал в вопросе → чужой профиль не
        # читается и generic-строка не вытесняется.
        out3 = await service._rag_append_profile_rows(
            db, base + [generic], CHAT, "что случилось с отпуском?",
            "Лёха", UID, 10, allow_replace=True)
        assert generic in out3

    # ── D1 (VMQ-MEM-07 five-class 2026-11-28) ────────────────────────────
    # Причина: `bound=True` удалял `period_fill`-строки ДО origin-отбора
    # профиля. Профиль, целиком состоящий из собственных прошлых ответов бота
    # (`bot_direct_reply`), после origin-фильтра даёт 0 допустимых строк, но
    # уже принятая строка старшего периода к этому моменту уничтожена.
    # Инвариант: origin-отбор не может приводить к потере уже найденной
    # периодной строки; заменять `period_fill` вправе только профиль, у
    # которого после origin-фильтра остался хотя бы один кандидат.

    @staticmethod
    def _d1_base():
        return _current_rows(8, ids=range(9100, 9108))

    @staticmethod
    def _d1_old_row():
        """Единственная строка старшего периода (архивный случай 5567/2025)."""
        return {"id": 5567, "fact": "Вася Поляна, 2025", "rag_ts": _ts(2025),
                "message_timestamp": _ts(2025), "origin": "history_import",
                "period_fill": True}

    @pytest.mark.asyncio
    async def test_bot_origin_profile_keeps_accepted_old_period_row(self, db):
        """D1 RED→GREEN: профильные чтения вернули только выводы бота —
        старшая периодная строка остаётся в срезе, новых строк не появляется,
        базовый срез не замещается."""
        import services.direct_chat_service as _dcs2
        for text, year in (("в 2026 Вася уточняет детали", 2026),
                           ("в 2025 Вася сказал про Поляну", 2025)):
            await _fact(db, text, year=year, target="Вася", speaker=UID,
                        origin="bot_direct_reply")
        service = _dcs2.DirectChatService(memory=object(), db=db, llm=None,
                                          aliases=None)
        base = self._d1_base()
        old = self._d1_old_row()
        out = await service._rag_append_profile_rows(
            db, base + [old], CHAT,
            "расскажи, что за человек Вася, по его сообщениям",
            "Вася", UID, 10, allow_replace=True)
        assert old in out, "принятая строка старшего периода потеряна"
        assert out[:len(base)] == base, "базовый срез замещён профилем"
        assert len(out) == len(base) + 1, [row.get("id") for row in out]
        assert not any(row.get("origin") == "bot_direct_reply" for row in out)

    @pytest.mark.asyncio
    async def test_admissible_profile_replaces_period_row_but_not_base(self, db):
        """Дифференциальный контроль к D1: тот же профиль с нейтральным
        origin вытесняет ТОЛЬКО `period_fill`-строку и не трогает базу."""
        import services.direct_chat_service as _dcs2
        for text, year in (("в 2026 Вася уточняет детали", 2026),
                           ("в 2025 Вася сказал про Поляну", 2025)):
            await _fact(db, text, year=year, target="Вася", speaker=UID,
                        origin="chat_history")
        service = _dcs2.DirectChatService(memory=object(), db=db, llm=None,
                                          aliases=None)
        base = self._d1_base()
        old = self._d1_old_row()
        out = await service._rag_append_profile_rows(
            db, base + [old], CHAT,
            "расскажи, что за человек Вася, по его сообщениям",
            "Вася", UID, 10, allow_replace=True)
        assert old not in out, "допустимый профиль не вытеснил period-строку"
        assert out[:len(base)] == base, "базовый срез замещён профилем"
        added = [row for row in out if row.get("id") not in
                 {r["id"] for r in base}]
        assert added, "допустимый профиль не добрал ни одной строки"
        assert len(out) <= 10


# ── TIME-04: окно и трасса ───────────────────────────────────────────────


class TestYearLossTrace:
    @pytest.mark.asyncio
    async def test_unknown_time_is_not_presented_as_year_event(self, db):
        await db.save_smart_message(
            UID, CHAT, 'цитата "старый конфликт" 2023', None,
            _ts(2023, 4, 1), "text", "Лёха", message_id=50_001)
        await db.save_smart_message(
            UID, CHAT, 'цитата "старый конфликт" без даты', None, 0,
            "text", "Лёха", message_id=50_002)
        request = mrc.RetrievalRequest(
            chat_id=CHAT, query='цитата "старый конфликт"',
            mode="history", purpose="reply", top_k=8, reply_depth=0,
            time_from=_ts(2023, 1, 1),
            time_to=_ts(2023, 12, 31) + 86399)
        result = await mrc.retrieve(db, None, request)
        previews = [str(cand.preview or "") for cand in result.candidates]
        assert any("2023" in text and "без даты" not in text
                   for text in previews), previews
        assert not any("без даты" in text for text in previews)
        assert all(cand.sent_at for cand in result.candidates)

    def test_apply_filters_without_window_keeps_old_behaviour(self):
        cand = mrc.RetrievalCandidate(
            id="msg:1", entity_type="message", entity_id="1", chat_id=CHAT,
            sent_at=0, channel="lexical")
        kept = mrc._apply_filters([cand], mrc.RetrievalRequest(
            chat_id=CHAT, query="вопрос"))
        assert kept == [cand]

    def test_period_trace_carries_authority_fields(self, monkeypatch):
        stats = {"policy": "auto", "replace_allowed": 0,
                 "period_skipped": "auto_full_slice",
                 "period_intent": {"kind": "none", "years": [],
                                   "source": ""},
                 "intent_source": "", "selection_rows": 0,
                 "selection_kept": 0, "historical_quota": 0,
                 "multi_year_quota": 0, "rejected_subject": 0,
                 "dropped_budget": 0, "dropped_status": 0,
                 "pool_status": {"confirmed": 0, "archived": 0, "other": 0},
                 "pool_expired": 0, "age_policy": "not_applied",
                 "vector_leg": "", "vector_rows": 0}
        period, years = _dcs._period_trace(stats, [])
        assert period["policy"] == "auto"
        assert period["replace_allowed"] == 0
        assert period["period_skipped"] == "auto_full_slice"
        assert "intent_source" in period
        assert years == {}

    def test_selection_payload_keeps_authority_and_block_years(self):
        payload = tt._selection_payload({
            "memory_period": {
                "policy": "historical", "replace_allowed": 1,
                "period_skipped": "", "intent_source": "query_year",
                "pool": 16, "kept": 2,
                "pool_status": {"confirmed": 14, "archived": 1, "other": 1},
                "query": "не должно попасть",
            },
            "blocks": [{"kind": "rag", "rendered": True,
                        "years": {2023: 2, 2026: 8}}],
        })
        assert payload["memory_period"]["policy"] == "historical"
        assert payload["memory_period"]["replace_allowed"] == 1
        assert payload["memory_period"]["intent_source"] == "query_year"
        assert "query" not in payload["memory_period"]
        assert payload["blocks"][0]["years"] == {2023: 2, 2026: 8}

    def test_l1_card_carries_memory_scope(self):
        trace_id = "slice-d-trace-1"
        tt.begin(trace_id, chat_id=CHAT)
        tt.note_l1(trace_id, response_act="answer", memory_scope="auto")
        assert tt.get(trace_id).l1["memory_scope"] == "auto"


# ── TIME-06: год-триггер и векторная нога ───────────────────────────────


class TestVectorLegAndYearTrigger:
    @pytest.mark.asyncio
    async def test_year_in_question_is_the_only_window_trigger(self, db,
                                                              monkeypatch):
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
        assert fill["vector_rows"] == 0
        assert calls == []

        plain = mrc.RetrievalRequest(
            chat_id=CHAT, query=A1P_PLAIN, mode="specific",
            purpose="reply", top_k=10, period_fill=True,
            memory_scope="auto", channels=("lexical", "vector"),
            exclude_years=(2026,))
        plain_result = await mrc.retrieve(db, _Memory(), plain)
        assert plain_result.period_fill["period_intent"]["kind"] == \
            mrc.PERIOD_INTENT_NONE


# ── TIME-07: размеченный набор (historical) ──────────────────────────────


def _labels():
    with open(LABELED_PATH, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


class TestLabeledRelevance:
    @pytest.mark.asyncio
    async def test_precision_under_historical_authority(self, db, monkeypatch):
        """Метки независимы; historical — единственный путь, где старый
        материал замещает срез. Hard-кейсы допускают ошибку периода/темы.
        T3 (N9): нулевой старый вклад под `auto` измеряется на НЕПУСТОМ пуле,
        который реально проходит `retrieve`, а не литералами."""
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
            if case["kind"] == "current":
                # N9: контроль «T3: 0 периодных строк» обязан реально
                # обращаться к пулу. Досеиваем строку, которая делит с
                # вопросом ДВЕ основы и потому прошла бы §2-порог селектора:
                # нулевой старый вклад в срез даёт авторитет (`auto` не
                # замещает), а не пустой пул или порог.
                await _fact(db, "Алиной сейчас", year=2023,
                            origin="history_import", target=None,
                            ts=_ts(2023, 8, 1), chat_id=case["_chat"])
                query_stems = mrc.period_subject_stems(case["query"])
                assert mrc.period_subject_shared(
                    query_stems, "Алиной сейчас") >= 2
                pool_request = mrc.RetrievalRequest(
                    chat_id=case["_chat"], query=case["query"],
                    mode="specific", purpose="reply", top_k=32,
                    period_fill=True, memory_scope="auto",
                    channels=("lexical",), exclude_years=(2026,))
                pool_result = await mrc.retrieve(db, None, pool_request)
                pool_rows = list(pool_result.fact_rows)
                assert pool_rows, "T3: старый пул должен быть непустым"
                # Реальный консьюмер на полном текущем срезе.
                base = _current_rows(10)
                calls: list = []
                service_auto = _service(monkeypatch, base, pool_rows,
                                        calls=calls)
                rows = await service_auto._rag_unified_rows(
                    case["_chat"], case["query"], _stub(text=case["query"]),
                    memory_scope="auto")
                stats = service_auto._rag_period_stats
                delivered = sum(1 for row in rows
                                if isinstance(row, dict) and row.get("period_fill"))
                assert delivered == 0, rows
                assert {row["id"] for row in rows} == set(range(8000, 8010))
                assert calls and all(call["period_fill"] is False
                                     for call in calls), calls
                assert stats["replace_allowed"] == 0, stats
                assert stats["period_skipped"] == "auto_full_slice", stats
                measured.append({
                    "id": case["id"], "kind": "current",
                    "delivered": delivered, "relevant": 0,
                    "pool": len(pool_rows),
                    "expected_years": [], "delivered_years": [],
                    "replace_allowed": int(stats["replace_allowed"]),
                    "period_skipped": str(stats["period_skipped"]),
                })
                continue
            request = mrc.RetrievalRequest(
                chat_id=case["_chat"], query=case["query"], mode="specific",
                purpose="reply", top_k=32, period_fill=True,
                memory_scope="historical", channels=("lexical",),
                exclude_years=(2026,))
            result = await mrc.retrieve(db, None, request)
            accepted, stats = mrc.select_period_rows(
                list(result.fact_rows), query=case["query"],
                policy="historical", slots=2, reference_year=2026)
            delivered = service._rag_append_period_rows(
                [], accepted, 10, slots=2)
            years = [mrc.period_row_year(row) for row in delivered]
            relevant = [
                1 for row, year in zip(delivered, years)
                if any(stem.casefold() in str(row.get("fact") or "").casefold()
                       for stem in case["topic_stems"])
                and year in case["expected_years"]]
            measured.append({
                "id": case["id"], "kind": case["kind"],
                "pool": len(result.fact_rows),
                "delivered": len(delivered), "relevant": len(relevant),
                "expected_years": case["expected_years"],
                "delivered_years": sorted({y for y in years if y}),
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
        assert core_total > 0 and core_precision >= 0.9, (core_precision, core)
        hard_good, hard_total, hard_precision = _precision(hard)
        assert hard_total > 0 and 0.0 < hard_precision < 1.0, (
            hard_precision, hard)
        total = core_total + hard_total
        good = core_good + hard_good
        assert good / total >= 0.8, (good / total, measured)
        labelled = [item for item in measured if item["kind"] != "current"]
        covered = sum(1 for item in labelled
                      if set(item["expected_years"])
                      & set(item["delivered_years"]))
        assert covered / len(labelled) >= 0.8, (covered, labelled)
        assert current["delivered"] == 0
