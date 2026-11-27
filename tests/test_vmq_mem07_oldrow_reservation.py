"""VMQ-MEM-07 — старый период не вытесняется рангом доказательств.

Дефект (измерен 2026-11-27 на архиве 2.58.225 и на выложенной 2.58.256):
A1/A1P `historical` — принятая строка старшего периода (2024/2025) доходила до
`select_period_rows`, но append-бюджет `top_k // 5 = 2` целиком занимали
строки 2026 (доминирующий период), выбранные `_rag_evidence_rank`. Покрытие
периодов падало 0.40 → 0.20.

Правило (одно предложение): когда бюджет добора — ограничение, а порядок
доказательств заполняет его целиком строками верхнего периода, последний слот
резервируется за лучшей по существующему рангу принятой строкой СТАРШЕГО
периода, иначе отсутствующей в срезе; остальные слоты сохраняют прежний ранг.

Покрытие (REGRESSION):
  * A1 `historical`: до фикса — 2026:12 (0.20), после — 2024:1 + 2026:11 (0.40);
  * A1P `historical`: до фикса — 2026:12 (0.20), после — 2025:1 + 2026:11 (0.40);
  * A1 `auto` (контроль): 0.20 без изменений — добор не запускается;
  * B retell: состав факт-блока 2024:2 + 2026:10 (0.40) и порядок не меняются;
  * D conflict 2025: порядок выбранной пары (7491, 6095) не меняется;
  * резерв не увеличивает бюджет: `len(result) <= budget`, при одном периоде —
    байт-паритет с прежним срезом `rows[:budget]`.

Идентификаторы/годы строк повторяют измеренные артефакты
`evidence/mem07-2.58.256/*.json`; тексты фактов — синтетические (R17), они не
участвуют в проверке.

TEST-LIFECYCLE: REGRESSION owner=VMQ-ONTO-01/vmq-mem VMQ-MEM-07
"""
import calendar
import types

import pytest

from services import direct_chat_service as dcs
from services import hot_config as hot
from services import mca_retrieval_context as mrc

CHAT = -100
LIMIT = 12  # прод-чат: limits.graph_rag_facts_limit ×2 (backfill G)
REF_YEARS = (2022, 2023, 2024, 2025, 2026)

A1 = "напиши юмористический рассказ об основных шизах конфы"
A1P = "перескажи, что в чате писали про шизов и конфу"
B_RETELL = "перескажи историю конфы с самого начала"


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


def _row(fid, text, *, year, weight=0.5, importance=4,
         origin="history_import", source="lexical"):
    return {"id": fid, "fact": text, "origin": origin,
            "status": "confirmed", "expires_at": None,
            "created_at": _ts(year), "message_timestamp": _ts(year),
            "weight": weight, "importance": importance,
            "tg_message_id": 800 + fid, "chat_id": CHAT,
            "item_id": f"fact:{fid}", "period_source": source,
            "subject_proxy": "knn" if source == "vector" else "stems"}


def _base(ids=None):
    """Полный текущий срез: 12 строк 2026 (как в измерении)."""
    ids = list(ids or range(30000, 30000 + LIMIT))
    return [_row(fid, f"текущий факт {index}", year=2026,
                 origin="chat_history")
            for index, fid in enumerate(ids)]


def _coverage(years) -> float:
    """Покрытие периодов — та же метрика артефакта: |hit ∩ ref| / |ref|."""
    return len(set(REF_YEARS) & set(years)) / len(REF_YEARS)


def _period_rows(rows, *, keys=("period_fill",)) -> list:
    return [row for row in rows if row.get("period_fill")]


class _Result:
    def __init__(self, fact_rows, period_fill=None):
        self.fact_rows = tuple(fact_rows)
        self.period_fill = period_fill


class _FakeHot:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


def _service(monkeypatch, base_rows, period_rows):
    """DirectChatService с одним подменённым швом `_rag_retrieve`."""
    monkeypatch.setattr(hot, "_cache", _FakeHot(
        {"limits.graph_rag_facts_limit": LIMIT}))
    db = types.SimpleNamespace(search_messages_fts=lambda *a, **k: None)
    service = dcs.DirectChatService(memory=object(), db=db, llm=None,
                                    aliases=None)
    calls: list = []

    async def fake(_db, _memory, chat_id, query, channels, limit, policy,
                   *, period_fill=False, **_kwargs):
        calls.append(bool(period_fill))
        if period_fill:
            return _Result(period_rows,
                           {"vector_leg": "embed_unavailable",
                            "vector_rows": 0})
        return _Result(base_rows)

    monkeypatch.setattr(service, "_rag_retrieve", fake)
    service._mem07_calls = calls
    return service


def _stub(text):
    return types.SimpleNamespace(text=text, chat_id=CHAT, message_id=0)


# ── A1: 2026-строки не вытесняют принятую строку 2024 ──────────────────────


A1_POOL = [
    # id/год из измерения; evidence: rank 2 × 2026 → appended (30524, 9552)
    _row(30524, "Никита предлагал добавить её в конфу ради шизни шиза",
         year=2026, weight=0.5, importance=4, origin="chat_history"),
    _row(9552, "Глеб был торжественно посвящён в шизы конфы и получил корону",
         year=2026, weight=0.3, importance=2),
    _row(3775, "Трой Кавасаки предлагает кандидата на роль создателя "
               "основного документа конфы", year=2024, weight=0.3,
         importance=2),
]


class TestA1HistoricalOldPeriodKept:
    @pytest.mark.asyncio
    async def test_a1_historical_covers_old_period(self, monkeypatch):
        """RED на выложенном коде: 2026:12 (0.20) вместо 2024:1+2026:11."""
        service = _service(monkeypatch, _base(), A1_POOL)
        rows = await service._rag_unified_rows(
            CHAT, A1, _stub(A1), memory_scope="historical")
        appended = _period_rows(rows)
        years = [mrc.period_row_year(row) for row in appended]
        delivered = [mrc.period_row_year(row) for row in rows]
        assert sorted(years) == [2024, 2026], (
            "принятая строка 2024 обязана попасть в добор: " + str(years))
        assert delivered.count(2026) == 11 and delivered.count(2024) == 1
        assert _coverage(delivered) == pytest.approx(0.40)
        assert service._mem07_calls == [False, True], (
            "ровно один базовый и один периодный вызов")

    @pytest.mark.asyncio
    async def test_a1_auto_control_stays_current_only(self, monkeypatch):
        """Контроль: `auto` не запускает добор — покрытие 0.20 неизменно."""
        service = _service(monkeypatch, _base(), A1_POOL)
        rows = await service._rag_unified_rows(
            CHAT, A1, _stub(A1), memory_scope="auto")
        delivered = [mrc.period_row_year(row) for row in rows]
        assert set(delivered) == {2026}, delivered
        assert _period_rows(rows) == []
        assert _coverage(delivered) == pytest.approx(0.20)
        assert service._mem07_calls == [False]

    @pytest.mark.asyncio
    async def test_a1_budget_is_still_two(self, monkeypatch):
        """Фикс не повышает бюджет: добор ≤ limit // 5 = 2 строк."""
        service = _service(monkeypatch, _base(), A1_POOL)
        rows = await service._rag_unified_rows(
            CHAT, A1, _stub(A1), memory_scope="historical")
        assert len(_period_rows(rows)) == 2
        assert len(rows) == LIMIT


# ── A1P: 2026-строки не вытесняют принятую строку 2025 ─────────────────────


A1P_POOL = [
    _row(35502, "адрес вдовина известен в чате писали уже сто раз",
         year=2026, weight=0.5, importance=4, origin="chat_history"),
    _row(30524, "Никита предлагал добавить её в конфу ради шизни шиза",
         year=2026, weight=0.5, importance=4, origin="chat_history"),
    _row(20593, "Глеб создал видео про шизов в конфе", year=2026,
         weight=0.5, importance=4, origin="chat_history"),
    _row(5908, "Майнкрафт мая жызнь напал на конфу шизов Вдовин",
         year=2025, weight=0.3, importance=2),
]


class TestA1PHistoricalOldPeriodKept:
    @pytest.mark.asyncio
    async def test_a1p_historical_covers_old_period(self, monkeypatch):
        """RED на выложенном коде: 2026:12 (0.20) вместо 2025:1+2026:11."""
        service = _service(monkeypatch, _base(), A1P_POOL)
        rows = await service._rag_unified_rows(
            CHAT, A1P, _stub(A1P), memory_scope="historical")
        appended = _period_rows(rows)
        years = sorted(mrc.period_row_year(row) for row in appended)
        delivered = [mrc.period_row_year(row) for row in rows]
        assert years == [2025, 2026], (
            "принятая строка 2025 обязана попасть в добор: " + str(years))
        assert delivered.count(2026) == 11 and delivered.count(2025) == 1
        assert _coverage(delivered) == pytest.approx(0.40)


# ── B / D: состав и порядок не меняются ────────────────────────────────────


B_POOL = [
    _row(23674, "alina ненавидит макса (конфа)", year=2026, weight=0.5,
         importance=4, origin="chat_history"),
    _row(4249, "сказала Дане и пацанам о происходящем с самого начала",
         year=2024, weight=0.3, importance=2),
    _row(3893, "Алина начала травить в конфах Лиза", year=2024, weight=0.3,
         importance=2),
]


class TestBRetellUnchanged:
    @pytest.mark.asyncio
    async def test_b_composition_and_order_are_unchanged(self, monkeypatch):
        """B: оба принятых 2024 доезжают в прежнем порядке (4249, 3893).

        Lore-канал (5/14) живёт в episode-пути и этой функцией не
        затрагивается; здесь фиксируется факт-состав блока измеренного B.
        """
        service = _service(monkeypatch, _base(), B_POOL)
        rows = await service._rag_unified_rows(
            CHAT, B_RETELL, _stub(B_RETELL), memory_scope="historical")
        appended = [row["id"] for row in _period_rows(rows)]
        delivered = [mrc.period_row_year(row) for row in rows]
        assert appended == [4249, 3893], appended
        assert delivered.count(2026) == 10 and delivered.count(2024) == 2
        assert _coverage(delivered) == pytest.approx(0.40)


D_ACCEPTED = [
    _row(7491, "Гипербореец не хочет пить с Корсаром из-за прошлых "
               "конфликтов", year=2025, weight=0.3, importance=2),
    _row(6095, "Корсар выполнял действия с женой Корсара", year=2025,
         weight=0.3, importance=2),
    _row(6869, "Гений отмечает Корсара", year=2025, weight=0.3, importance=2),
    _row(7869, "Гений считает Корсара", year=2025, weight=0.3, importance=2),
    _row(8576, "Yaroslav родственник по отцу", year=2025, weight=0.3,
         importance=2),
    _row(7724, "Гений сравнивает Корсара с борисами", year=2025, weight=0.3,
         importance=2),
    _row(8099, "Гений называет Корсара Паладином", year=2025, weight=0.3,
         importance=2),
    _row(5841, "Алина напоминает о конфликте из прошлого", year=2025,
         weight=0.3, importance=2),
]


class TestDConflictOrderUnchanged:
    def test_d_selected_pair_and_order_are_unchanged(self):
        """D: прежний выбор (7491, 6095) — один период, резерв не вмешивается.

        Принятый набор D целиком из целевого 2025 (периодный intent —
        `explicit_year`), поэтому резерв не имеет старшего периода и обязан
        вернуть прежний срез `accepted[:budget]` байт-в-байт: порядок
        доставки и хронологическая точность D не меняются.
        """
        selected = mrc.reserve_period_append(D_ACCEPTED, budget=2)
        assert [row["id"] for row in selected] == [7491, 6095]
        assert selected == D_ACCEPTED[:2], (
            "при одном периоде в кандидатах результат — прежний срез")


# ── резерв не может превысить бюджет ──────────────────────────────────────


class TestReservationBounded:
    def test_never_exceeds_budget_and_keeps_rank(self):
        candidates = [
            _row(1, "шизы конфы один", year=2026, weight=0.9, importance=9),
            _row(2, "шизы конфы два", year=2026, weight=0.8, importance=9),
            _row(3, "шизы конфы три", year=2026, weight=0.7, importance=9),
            _row(4, "шизы конфы четыре", year=2026, weight=0.6, importance=9),
            _row(5, "старое про шизы конфы", year=2021, weight=0.1,
                 importance=1),
        ]
        for budget in (1, 2, 3, 4):
            selected = mrc.reserve_period_append(candidates, budget=budget)
            assert len(selected) <= budget, budget
            if budget >= 2:
                assert selected[-1]["id"] == 5, (budget, selected)
                assert selected[:-1] == candidates[:budget - 1]
        # Бюджет 1 не может и удержать верхний период, и добавить старший.
        assert [row["id"] for row in
                mrc.reserve_period_append(candidates, budget=1)] == [1]

    def test_single_period_is_byte_identical(self):
        rows = [_row(index, f"факт {index}", year=2026,
                     weight=1.0 - index * 0.1, importance=5)
                for index in range(1, 6)]
        assert mrc.reserve_period_append(rows, budget=2) == rows[:2]
        assert mrc.reserve_period_append([], budget=2) == []
        assert mrc.reserve_period_append(rows, budget=0) == []

    def test_unknown_year_is_not_a_period(self):
        """Строка без времени не выдаётся за «старший период»."""
        rows = [_row(1, "текущее", year=2026),
                {"id": 2, "fact": "без времени", "origin": "chat_history",
                 "item_id": "fact:2"}]
        assert mrc.reserve_period_append(rows, budget=2) == rows[:2]

    def test_already_diverse_selection_is_untouched(self):
        """Если ранг уже покрывает два периода, резерв не двигает ни строки."""
        rows = [_row(1, "верхний период", year=2026, weight=0.9),
                _row(2, "старший период", year=2024, weight=0.5),
                _row(3, "верхний период 2", year=2026, weight=0.4)]
        assert mrc.reserve_period_append(rows, budget=2) == rows[:2]

    def test_multiple_old_periods_take_one_slot(self):
        rows = [_row(1, "верхний период", year=2026),
                _row(2, "верхний период 2", year=2026),
                _row(3, "старый 2022", year=2022),
                _row(4, "старый 2021", year=2021)]
        selected = mrc.reserve_period_append(rows, budget=2)
        assert [row["id"] for row in selected] == [1, 3], (
            "резервируется ОДИН слот — лучший ранг среди старших периодов")
