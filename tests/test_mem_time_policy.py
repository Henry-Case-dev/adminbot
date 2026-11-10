"""VMQ-MEM-TIME (§1–§4): три раздельных свойства факта и политика охвата.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/time/fix-contract.md`
(уточнение владельца 10.11.2026 — `plans/owner_inputs/2026-11-10-vmq-time-refinement.md`).

Покрытие (CONTRACT):
  * H (историческая значимость) = cosine × важность; возраст и статус в H НЕ
    входят — старый факт не становится «незначимым»;
  * R (фактическая достоверность) = вес × provenance; `archived_fact` (квота)
    R НЕ понижает;
  * V (актуальность сейчас) — булев предикат, не множитель значимости;
  * `operative` — прежняя формула байт-в-байт (полураспад 60 дн., пол 0.1);
    `historical|auto` — возраст максимум 5 % tie-break, score = H × R;
  * V — tie-window 0.05, не штраф;
  * адаптивный подбор: минимум `limit//5` исторических в `historical` при
    H ≥ 0.75 × max(H по действующим), потолок `HIST_MAX_SHARE` в `auto`;
  * M2/M3/M4 — вопрос без года по событиям даёт несколько лет, известный факт
    2023–2024 находится, вопрос «что сейчас» остаётся 2026-доминированным.
"""
import asyncio
import calendar
import time
import types

import pytest

from services import hot_config as hot
from services import summary_memory as sm
from services.database import DatabaseService
from services.summary_memory import MemoryManager

CHAT = -100
_DAY = 86400


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


class _FakeHotCache:
    def __init__(self, values):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


def _hot(monkeypatch, values: dict | None = None):
    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _row(**kwargs) -> dict:
    """Полная строка graph_facts для чистых проверок скоринга."""
    row = {
        "id": 1, "fact": "факт", "origin": "chat_history",
        "created_at": _ts(2026), "target_user": "aleksey",
        "weight": 0.5, "status": "confirmed",
        "last_confirmed_at": _ts(2026), "message_timestamp": _ts(2026),
        "belief_meta": None, "kind": "fact", "importance": 5,
        "tg_message_id": 1, "forward_from": "", "expires_at": None,
        "chat_id": CHAT, "subject_ref_id": 138811255,
        "speaker_author_id": 138811255, "assertion_kind": None,
        "attribution_method": "self_report", "provenance_channel": None,
    }
    row.update(kwargs)
    return row


async def _fact(db, text, *, year=2026, status="confirmed", weight=0.5,
                importance=5, subject_ref=7, age_days=0):
    now = int(time.time())
    confirmed = now - age_days * _DAY
    fact_id = await db.insert_graph_fact(
        CHAT, text, "chat_history", None, target_user="aleksey",
        status=status, weight=weight, importance=importance,
        message_timestamp=_ts(year), subject_ref_id=subject_ref,
        speaker_author_id=subject_ref, attribution_method="self_report",
        tg_message_id=1000 + year)
    await db.db.execute(
        "UPDATE graph_facts SET last_confirmed_at = ? WHERE id = ?",
        (confirmed, fact_id))
    await db.db.commit()
    return fact_id


def _stub_candidates(monkeypatch, memory, mapping):
    """KNN-слой → заданные cosine (эмбеддинги в тестах не считаем)."""
    async def fake_vec(chat_id, vector, fetch_k, include_direct_reply, now,
                       include_self=False, expired_only=False):
        if expired_only:
            return []
        items = [(fid, cosine, None) for fid, cosine in mapping]
        return items[:fetch_k]
    monkeypatch.setattr(memory, "_vec_candidates", fake_vec)


# ── 1. H, R, V — раздельность (никакого единого score) ─────────────────────

class TestThreeProperties:

    def test_h_excludes_age_and_status(self):
        """H не содержит возраст и статус: одинаковый смысл → одинаковое H."""
        young = _row(status="confirmed", created_at=_ts(2026),
                     last_confirmed_at=_ts(2026))
        old_archived = _row(status="archived_fact", created_at=_ts(2022),
                            last_confirmed_at=_ts(2022) - 900 * _DAY)
        h_young = sm._significance(0.8, young)
        h_old = sm._significance(0.8, old_archived)
        assert h_old == pytest.approx(h_young, rel=0, abs=0)

    def test_archived_fact_does_not_lower_reliability(self):
        """`archived_fact` — квота, не ложность: R тот же."""
        confirmed = _row(status="confirmed")
        archived = _row(status="archived_fact")
        assert sm._reliability_factor(confirmed) == \
            sm._reliability_factor(archived) == 1.0
        # legacy без атрибуции — ниже, и это свойство provenance, не статуса.
        legacy = _row(status="archived_fact", subject_ref_id=None,
                      speaker_author_id=None)
        assert sm._reliability_factor(legacy) < 1.0

    def test_v_is_boolean_predicate(self):
        now = int(time.time())
        assert sm._fact_valid_now(_row(status="confirmed"), now) is True
        assert sm._fact_valid_now(
            _row(status="confirmed", expires_at=now - 10), now) is False
        assert sm._fact_valid_now(_row(status="archived_fact"), now) is False
        assert sm._fact_valid_now(_row(status="archived_belief"), now) is False
        assert sm._fact_valid_now(_row(status="unconfirmed"), now) is False

    def test_operative_decay_is_legacy_formula(self):
        """`operative` — байт-в-байт прежняя формула (60 дн., пол 0.1)."""
        now = int(time.time())
        for age_days, expected in (
                (0, 0.5), (60, 0.25), (139, None), (4000, 0.1)):
            value = sm._effective_weight(0.5, now - age_days * _DAY, now)
            if expected is None:
                assert value == pytest.approx(0.5 * 0.5 ** (139 / 60.0))
            else:
                assert value == pytest.approx(expected, rel=1e-9)
        # Выключатель — прежнее поведение (вес как есть).
        assert sm._effective_weight(0.5, now - 4000 * _DAY, now) == \
            pytest.approx(0.1)

    def test_historical_decay_is_bounded_freshness_tiebreak(self, monkeypatch):
        """Возраст в исторической политике — ≤5 %, не множитель."""
        _hot(monkeypatch, {})
        now = int(time.time())
        fresh = sm._effective_weight(0.5, now, now, policy="historical")
        ancient = sm._effective_weight(0.5, now - 3650 * _DAY, now,
                                       policy="auto")
        assert fresh == pytest.approx(0.5, rel=1e-9)
        assert ancient == pytest.approx(0.5 * 0.95, rel=1e-9)
        # Разница за давность (5 %) меньше разрыва смысловой значимости (10 %).
        assert (fresh - ancient) / fresh <= 0.05 + 1e-12


# ── 2. Порядок: H×R основной, V — tie-window ───────────────────────────────

class TestPolicyOrder:

    def test_tie_window_prefers_current(self):
        entries = [
            {"fid": 1, "score": 0.50, "valid": False, "significance": 0.9},
            {"fid": 2, "score": 0.53, "valid": True, "significance": 0.9},
        ]
        ordered = sm._policy_order(entries)
        assert [e["fid"] for e in ordered] == [2, 1]

    def test_significance_beats_tie_window(self):
        """Δ(H×R) ≥ окна → порядок по значимости, V не спасает."""
        entries = [
            {"fid": 1, "score": 0.60, "valid": False, "significance": 0.95},
            {"fid": 2, "score": 0.50, "valid": True, "significance": 0.70},
        ]
        ordered = sm._policy_order(entries)
        assert [e["fid"] for e in ordered] == [1, 2]


# ── 3. Адаптивный подбор: минимум-гарантия и страховка ─────────────────────

class TestAdaptiveSelection:

    def test_historical_guarantees_min_slots(self, monkeypatch):
        _hot(monkeypatch, {"limits.graph_hist_rel_floor": 0.75})
        ordered = sm._policy_order([
            {"fid": 1, "score": 0.40, "valid": True, "significance": 0.80},
            {"fid": 2, "score": 0.39, "valid": True, "significance": 0.78},
            {"fid": 3, "score": 0.30, "valid": False, "significance": 0.70},
            {"fid": 4, "score": 0.29, "valid": False, "significance": 0.66},
        ])
        chosen = sm._select_by_policy(ordered, 4, "historical")
        assert 3 in chosen and 4 in chosen       # limit//5 = 2 слота

    def test_historical_respects_relevance_floor(self, monkeypatch):
        """Слабый исторический кандидат не подменяет текущее состояние."""
        _hot(monkeypatch, {"limits.graph_hist_rel_floor": 0.75})
        ordered = sm._policy_order([
            {"fid": 1, "score": 0.40, "valid": True, "significance": 0.80},
            {"fid": 2, "score": 0.10, "valid": False, "significance": 0.10},
        ])
        chosen = sm._select_by_policy(ordered, 1, "historical")
        assert chosen == [1]

    def test_auto_share_cap_keeps_current(self, monkeypatch):
        _hot(monkeypatch, {"limits.graph_hist_max_share": 0.5})
        ordered = sm._policy_order([
            {"fid": i, "score": 1.0 - i * 0.01, "valid": False,
             "significance": 0.9} for i in range(1, 9)
        ] + [
            {"fid": 100 + i, "score": 0.5, "valid": True,
             "significance": 0.4} for i in range(1, 5)
        ])
        chosen = sm._select_by_policy(ordered, 10, "auto")
        historic = [fid for fid in chosen if fid < 100]
        assert len(historic) <= 5          # HIST_MAX_SHARE=0.5 при limit=10
        assert any(fid >= 100 for fid in chosen)

    def test_no_fixed_fresh_share(self, monkeypatch):
        """Фиксированной доли нет: сильная история занимает больше слотов."""
        _hot(monkeypatch, {"limits.graph_hist_max_share": 0.5})
        strong = sm._select_by_policy(sm._policy_order([
            {"fid": i, "score": 0.9 - i * 0.01, "valid": False,
             "significance": 0.95} for i in range(1, 7)
        ] + [
            {"fid": 100 + i, "score": 0.4, "valid": True,
             "significance": 0.5} for i in range(1, 7)
        ]), 10, "auto")
        weak = sm._select_by_policy(sm._policy_order([
            {"fid": i, "score": 0.1, "valid": False, "significance": 0.2}
            for i in range(1, 4)
        ] + [
            {"fid": 100 + i, "score": 0.5, "valid": True,
             "significance": 0.9} for i in range(1, 10)
        ]), 10, "auto")
        hist_strong = len([fid for fid in strong if fid < 100])
        hist_weak = len([fid for fid in weak if fid < 100])
        # Сильная история занимает всю допустимую долю, слабая — только
        # оставшийся слот (9 действующих на 10 мест): фиксированной доли нет.
        assert hist_strong == 5
        assert hist_weak == 1


# ── 4. Пул и паритет `operative` ───────────────────────────────────────────

class TestPoolAndParity:

    def test_operative_pool_and_scoring_parity(self, db, monkeypatch):
        """`operative` = прежняя формула и прежний пул (без archived_fact)."""
        _hot(monkeypatch, {"flags.graph_mmr_enabled": False,
                           "flags.graph_fact_touch_enabled": False,
                           "flags.belief_decay_enabled": False})
        memory = MemoryManager(db, None)
        loop = asyncio.get_event_loop()
        fresh_id = loop.run_until_complete(
            _fact(db, "свежий факт 2026", year=2026))
        old_id = loop.run_until_complete(
            _fact(db, "старый подтверждённый факт 2023", year=2023,
                  age_days=400))
        archived_id = loop.run_until_complete(
            _fact(db, "вытесненный квотой факт 2023", year=2023,
                  status="archived_fact", age_days=900))
        mapping = [(archived_id, 0.99), (old_id, 0.80), (fresh_id, 0.70)]
        _stub_candidates(monkeypatch, memory, mapping)
        rows = loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, with_meta=True, policy="operative"))
        returned = [row["id"] for row in rows]
        assert archived_id not in returned, "архив квоты в live-выдаче нет"
        # Независимый эталон прежней формулы (cosine × w_eff × важность).
        now = int(time.time())
        records = {row["id"]: dict(row) for row in loop.run_until_complete(
            db.get_graph_fact_records([old_id, fresh_id]))}
        reference = {
            fid: (cosine
                  * sm._effective_weight(row["weight"],
                                         row["last_confirmed_at"], now)
                  * sm._importance_factor(sm._row_importance(row)))
            for fid, cosine in ((old_id, 0.80), (fresh_id, 0.70))
            for row in (records[fid],)}
        expected = sorted(reference, key=lambda fid: reference[fid],
                          reverse=True)
        assert returned == expected

    def test_operative_full_order_parity_with_legacy_formula(self, db,
                                                            monkeypatch):
        """M5: полный порядок `operative` совпадает с прежней формулой."""
        _hot(monkeypatch, {"flags.graph_mmr_enabled": False,
                           "flags.graph_fact_touch_enabled": False,
                           "flags.belief_decay_enabled": False})
        loop = asyncio.get_event_loop()
        memory = MemoryManager(db, None)
        facts = []
        for idx in range(6):
            facts.append(loop.run_until_complete(_fact(
                db, f"свежий {idx}", age_days=idx * 10,
                importance=1 + idx, weight=0.5)))
        for idx in range(3):
            facts.append(loop.run_until_complete(_fact(
                db, f"старый подтверждённый {idx}", year=2023,
                age_days=300 + idx * 30, importance=8, weight=0.6)))
        archived = loop.run_until_complete(_fact(
            db, "вытесненный квотой", year=2022, status="archived_fact",
            age_days=700, importance=10, weight=0.9))
        belief = loop.run_until_complete(_fact(
            db, "убеждение", status="archived_belief", age_days=200,
            importance=6, weight=0.6))
        cosines = {fid: 0.9 - idx * 0.05 for idx, fid in
                   enumerate(facts + [archived, belief])}
        mapping = list(cosines.items())
        _stub_candidates(monkeypatch, memory, mapping)
        rows = loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, with_meta=True, policy="operative"))
        returned = [row["id"] for row in rows]

        # Независимый эталон прежней формулы: cosine × w_eff × важность,
        # минус belief-пенальти для archived_belief (archived_fact в live-пул
        # не входит вовсе).
        now = int(time.time())
        penalty = float(hot.get("limits.belief_resonance_penalty", 0.3)
                        or 0.3)
        records = {row["id"]: dict(row) for row in loop.run_until_complete(
            db.get_graph_fact_records(facts + [belief]))}
        reference = {}
        for fid, row in records.items():
            if str(row["status"]) not in ("confirmed", "archived_belief"):
                continue
            score = (cosines[fid]
                     * sm._effective_weight(row["weight"],
                                            row["last_confirmed_at"], now)
                     * sm._importance_factor(sm._row_importance(row)))
            if str(row["status"]) == "archived_belief":
                score -= penalty
            reference[fid] = score
        expected = sorted(reference, key=lambda fid: reference[fid],
                          reverse=True)
        assert returned == expected
        assert archived not in returned

    def test_dedup_keeps_stronger_row_of_same_entity(self):
        """R4: дедуп archived/confirmed с одним `dedup_id` — остаётся сильнейший."""
        from services import mca_retrieval_context as mrc
        confirmed = mrc.RetrievalCandidate(
            id="tg:1", entity_type="graph_fact", entity_id="1",
            score=40.0, channel="lexical", dedup_id="fact:1",
            preview="confirmed")
        archived = mrc.RetrievalCandidate(
            id="tg:1", entity_type="graph_fact", entity_id="1",
            score=60.0, channel="vector", dedup_id="fact:1",
            preview="archived")
        kept = mrc._dedup([confirmed, archived])
        assert len(kept) == 1
        assert kept[0].channel == "vector"
        # Обратный порядок входа — тот же результат (не зависит от позиции).
        kept_reversed = mrc._dedup([archived, confirmed])
        assert len(kept_reversed) == 1
        assert kept_reversed[0].channel == "vector"

    def test_auto_pool_includes_archived_fact(self, db, monkeypatch):
        _hot(monkeypatch, {"flags.graph_mmr_enabled": False,
                           "flags.graph_fact_touch_enabled": False,
                           "flags.belief_decay_enabled": False})
        memory = MemoryManager(db, None)
        loop = asyncio.get_event_loop()
        fresh_id = loop.run_until_complete(_fact(db, "текущее 2026"))
        archived_id = loop.run_until_complete(_fact(
            db, "архив 2023", year=2023, status="archived_fact",
            age_days=900))
        _stub_candidates(monkeypatch, memory,
                         [(archived_id, 0.90), (fresh_id, 0.60)])
        stats = {}
        rows = loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, with_meta=True, policy="auto",
            stats=stats))
        returned = {row["id"] for row in rows}
        assert archived_id in returned, "квота не является границей истории"


# ── 5. M2/M3/M4: вопросы без года ──────────────────────────────────────────

class TestYearlessQuestions:

    def _multi_year_archive(self, db, loop):
        """Архив по годам: 2026 плотный и свежий, 2022–2024 архивные."""
        current = [
            loop.run_until_complete(_fact(db, f"текущее событие {i}", year=2026))
            for i in range(12)]
        archived = []
        for year, cosine in ((2024, 0.86), (2024, 0.84), (2023, 0.82),
                             (2023, 0.80), (2022, 0.78)):
            archived.append((
                loop.run_until_complete(_fact(
                    db, f"событие {year}", year=year,
                    status="archived_fact", age_days=400)),
                cosine))
        return current, archived

    def test_m2_yearless_event_spans_years(self, db, monkeypatch):
        """M2: вопрос без года → ≥3 разных года (база оперативная: 1 год)."""
        _hot(monkeypatch, {"flags.graph_mmr_enabled": False,
                           "flags.graph_fact_touch_enabled": False,
                           "flags.belief_decay_enabled": False})
        loop = asyncio.get_event_loop()
        memory = MemoryManager(db, None)
        current, archived = self._multi_year_archive(db, loop)
        mapping = [(fid, 0.70) for fid in current] + archived
        _stub_candidates(monkeypatch, memory, mapping)

        auto_rows = loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, with_meta=True, policy="auto"))
        auto_ids = {row["id"] for row in auto_rows}
        years = {time.gmtime(int(row["message_timestamp"])).tm_year
                 for row in auto_rows if row["message_timestamp"]}
        assert len(years) >= 3, f"годы исторического вопроса: {sorted(years)}"
        assert 2023 in years and 2024 in years

        operative_rows = loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, with_meta=True, policy="operative"))
        operative_years = {
            time.gmtime(int(row["message_timestamp"])).tm_year
            for row in operative_rows if row["message_timestamp"]}
        assert len(operative_years) == 1, "база: только свежий год"
        assert auto_ids != {row["id"] for row in operative_rows}

    def test_m3_known_answer_old_fact_is_found(self, db, monkeypatch):
        """M3: заранее известный факт 2023–2024 обязан попасть в материал."""
        _hot(monkeypatch, {"flags.graph_mmr_enabled": False,
                           "flags.graph_fact_touch_enabled": False,
                           "flags.belief_decay_enabled": False})
        loop = asyncio.get_event_loop()
        memory = MemoryManager(db, None)
        known_2023 = loop.run_until_complete(_fact(
            db, "в 2023 году aleksey переехал в другой город", year=2023,
            status="archived_fact", age_days=500))
        known_2024 = loop.run_until_complete(_fact(
            db, "в 2024 году aleksey сменил работу", year=2024,
            status="archived_fact", age_days=300))
        current = [loop.run_until_complete(_fact(db, f"разговор {i}"))
                   for i in range(10)]
        mapping = ([(fid, 0.62) for fid in current]
                   + [(known_2023, 0.76), (known_2024, 0.80)])
        _stub_candidates(monkeypatch, memory, mapping)
        rows = loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, with_meta=True, policy="historical"))
        returned = {row["id"] for row in rows}
        assert known_2023 in returned and known_2024 in returned

    def test_m4_current_question_stays_current(self, db, monkeypatch):
        """M4: «что сейчас» остаётся 2026-доминированным, истории не выдаёт
        за действующее."""
        _hot(monkeypatch, {"flags.graph_mmr_enabled": False,
                           "flags.graph_fact_touch_enabled": False,
                           "flags.belief_decay_enabled": False})
        loop = asyncio.get_event_loop()
        memory = MemoryManager(db, None)
        current = [loop.run_until_complete(_fact(db, f"сейчас {i}"))
                   for i in range(10)]
        old = [loop.run_until_complete(_fact(
            db, f"давнее {i}", year=2023, status="archived_fact",
            age_days=600)) for i in range(2)]
        mapping = ([(fid, 0.85) for fid in current]
                   + [(fid, 0.60) for fid in old])
        _stub_candidates(monkeypatch, memory, mapping)
        rows = loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, with_meta=True, policy="auto"))
        years = [time.gmtime(int(row["message_timestamp"])).tm_year
                 for row in rows if row["message_timestamp"]]
        assert years, "выдача не пуста"
        share_2026 = years.count(2026) / len(years)
        assert share_2026 >= 0.8, f"доля 2026: {share_2026:.2f}"
        now = int(time.time())
        returned = {row["id"] for row in rows}
        for fid in old:
            if fid in returned:
                record = loop.run_until_complete(
                    db.get_graph_fact_records([fid]))[0]
                assert sm._fact_valid_now(dict(record), now) is False


# ── 7. Наблюдаемость: покрытие по годам и причины исключения (§10) ─────────

class TestObservability:

    def test_retrieval_year_coverage_aggregates_durable_events(self, db):
        """Status/Analytics: годы выдачи и причины исключения из `usage_json`."""
        import asyncio as _asyncio
        import json as _json
        from services.memory_diagnostics import retrieval_year_coverage
        loop = _asyncio.get_event_loop()
        events = [
            {"policy": "auto", "years": {"2026": 7, "2023": 2},
             "excluded": {"status": 3, "budget": 1}},
            {"policy": "historical", "years": {"2024": 5},
             "excluded": {"policy_operative": 4}},
        ]
        for pressure in events:
            loop.run_until_complete(db.db.execute(
                "INSERT INTO mca_events (ts, level, event_name, outcome, "
                "usage_json) VALUES (?, 'INFO', 'mca07_retrieval', "
                "'success', ?)",
                (int(time.time()), _json.dumps(pressure))))
        loop.run_until_complete(db.db.commit())
        body = loop.run_until_complete(retrieval_year_coverage(db))
        assert body["available"] is True
        assert body["years"] == {"2023": 2, "2024": 5, "2026": 7}
        assert body["year_count"] == 3
        assert body["excluded"] == {"policy_operative": 4, "status": 3,
                                    "budget": 1}
        assert body["policy"] == {"auto": 1, "historical": 1}

    def test_retrieval_year_coverage_is_honest_when_empty(self, db):
        """Нет событий → available=false + empty_reason (не нули)."""
        import asyncio as _asyncio
        from services.memory_diagnostics import retrieval_year_coverage
        body = _asyncio.get_event_loop().run_until_complete(
            retrieval_year_coverage(db))
        assert body["available"] is False
        assert body["empty_reason"] == "no_data"
        assert body["years"] == {}


# ── 6. Наблюдаемость: причины исключения (числа, без текстов) ──────────────

class TestExclusionStats:

    def test_operative_counts_quota_exclusions(self, db, monkeypatch):
        _hot(monkeypatch, {"flags.graph_mmr_enabled": False,
                           "flags.graph_fact_touch_enabled": False,
                           "flags.belief_decay_enabled": False})
        loop = asyncio.get_event_loop()
        memory = MemoryManager(db, None)
        fresh = loop.run_until_complete(_fact(db, "свежий"))
        archived = loop.run_until_complete(_fact(
            db, "архивный", year=2023, status="archived_fact", age_days=500))
        unconfirmed = loop.run_until_complete(_fact(
            db, "неподтверждённый", status="unconfirmed"))
        _stub_candidates(monkeypatch, memory,
                         [(fresh, 0.7), (archived, 0.8), (unconfirmed, 0.9)])
        stats: dict = {}
        loop.run_until_complete(memory._knn_graph_facts(
            CHAT, [0.1, 0.1], 10, policy="operative", stats=stats))
        assert stats.get("policy_operative") == 1
        assert stats.get("status") == 1
        # Текстов фактов в счётчиках нет — только числа.
        assert all(isinstance(value, int) for value in stats.values())


class TestPeriodSlots:
    """Блокер 2 ре-ревью 10.11.2026: срез политики добирает ДРУГОЙ период.

    На реальном архиве канал `vector` отдаёт 2024–2026 и не отдаёт найденный
    по тексту факт 2023; добор делает существующий канал `lexical` того же
    `retrieve`, а из профиля — существующее чтение `get_user_context_facts`.
    """

    @staticmethod
    def _row(fid, year, origin="history_import"):
        return {"id": fid, "origin": origin, "fact": f"факт {fid}",
                "status": "confirmed", "expires_at": None,
                "message_timestamp": _ts(year), "created_at": _ts(year),
                "tg_message_id": 900 + fid, "chat_id": CHAT,
                "item_id": f"fact:{fid}"}

    @staticmethod
    def _service():
        from services import direct_chat_service as dcs
        return dcs.DirectChatService(memory=object(), db=None, llm=None,
                                     aliases=None)

    def test_only_other_periods_and_never_self_origin(self):
        service = self._service()
        rows = [self._row(1, 2026), self._row(2, 2026)]
        extra = [self._row(3, 2023), self._row(4, 2026),
                 self._row(5, 2024, origin="bot_direct_reply")]
        out = service._rag_append_period_rows(rows, extra, 10, slots=2)
        ids = [row["id"] for row in out]
        assert ids[:2] == [1, 2], "основной срез не переупорядочивается"
        assert 3 in ids, "старый период добирается"
        assert 4 not in ids, "тот же год не дублируется"
        assert 5 not in ids, "прошлые ответы бота — не факты мира"

    def test_bounded_by_slots(self):
        service = self._service()
        rows = [self._row(1, 2026)]
        extra = [self._row(2, 2023), self._row(3, 2024), self._row(4, 2025)]
        out = service._rag_append_period_rows(rows, extra, 10, slots=2)
        assert len(out) == 3

    @pytest.mark.asyncio
    async def test_operative_keeps_single_vector_call(self, monkeypatch):
        _hot(monkeypatch)
        service = self._service()
        service.db = types.SimpleNamespace(
            search_messages_fts=lambda *a, **k: None)
        calls: list = []

        class _Result:
            fact_rows = (TestPeriodSlots._row(1, 2026),)

        async def fake(db, memory, chat_id, query, channels, limit, policy,
                 **_kwargs):
            calls.append((tuple(channels), policy))
            return _Result()

        monkeypatch.setattr(service, "_rag_retrieve", fake)
        rows = await service._rag_unified_rows(CHAT, "q", None,
                                               memory_scope="operative")
        assert calls == [(("vector",), "operative")]
        assert [row["id"] for row in rows] == [1]

    @pytest.mark.asyncio
    async def test_historical_adds_period_channels_and_profile(self,
                                                               monkeypatch):
        _hot(monkeypatch)
        service = self._service()
        profile_calls: list = []

        async def reader(chat_id, name, limit, now_ts, user_id=None,
                         scope=None):
            profile_calls.append((name, user_id, scope))
            return [TestPeriodSlots._row(7, 2023)]

        service.db = types.SimpleNamespace(
            search_messages_fts=lambda *a, **k: None,
            get_user_context_facts=reader)
        calls: list = []

        class _Result:
            fact_rows = (TestPeriodSlots._row(1, 2026),)

        async def fake(db, memory, chat_id, query, channels, limit, policy,
                 **_kwargs):
            calls.append(tuple(channels))
            return _Result()

        monkeypatch.setattr(service, "_rag_retrieve", fake)
        rows = await service._rag_unified_rows(
            CHAT, "q", None, memory_scope="historical",
            subject_name="Aleksey", subject_uid=7)
        assert calls == [("vector",), ("lexical",)], calls
        assert profile_calls == [("Aleksey", 7, "historical")]
        ids = [row["id"] for row in rows]
        assert ids[0] == 1, "основной срез остаётся первым"
        assert 7 in ids, "история профиля добирается как другой период"
    @pytest.mark.asyncio
    async def test_auto_with_thin_slice_is_not_diversified(self, monkeypatch):
        """Срез из одних прошлых ответов бота не «разбавляется» историей."""
        _hot(monkeypatch)
        service = self._service()
        service.db = types.SimpleNamespace(
            search_messages_fts=lambda *a, **k: None)
        calls: list = []

        class _Result:
            fact_rows = (TestPeriodSlots._row(1, 2026,
                                              origin="bot_direct_reply"),)

        async def fake(db, memory, chat_id, query, channels, limit, policy,
                 **_kwargs):
            calls.append(tuple(channels))
            return _Result()

        monkeypatch.setattr(service, "_rag_retrieve", fake)
        await service._rag_unified_rows(CHAT, "q", None, memory_scope="auto")
        assert calls == [("vector",)], calls


class TestPeriodFillSurvivesRerank:
    """Решение архитектора 10.11.2026: строки, добранные политикой охвата
    (`period_fill`), не отбрасываются реранком РЕЛЕВАНТНОСТИ, тогда как
    остальной срез реранк по-прежнему фильтрует. Потолок добора
    (`limit // 5`) сохраняется, `operative` до добора не доходит.
    """

    @staticmethod
    def _row(fid, year, text, *, period=False, origin="history_import"):
        row = {"id": fid, "origin": origin, "fact": text,
               "status": "confirmed", "expires_at": None,
               "message_timestamp": _ts(year), "created_at": _ts(year),
               "tg_message_id": 900 + fid, "chat_id": CHAT,
               "item_id": f"fact:{fid}"}
        if period:
            row["period_fill"] = True
        return row

    class _Msg:
        def __init__(self, text):
            self.text = text

    class _Memory:
        """Реранк как в проде: оставляет подмножество (позиции 1..keep_n)."""

        def __init__(self, keep_n=1):
            self.keep_n = keep_n
            self.calls = []

        async def rerank_rag_facts(self, query, facts):
            self.calls.append(list(facts))
            return list(facts)[:self.keep_n]

    @classmethod
    def _service(cls, monkeypatch, memory, rows):
        from services import direct_chat_service as dcs

        async def _no_chat_param(*_args, **_kwargs):
            return None

        monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
        service = dcs.DirectChatService(memory=memory, db=None, llm=None,
                                        aliases=None)

        async def fake_rows(*_args, **_kwargs):
            return rows

        monkeypatch.setattr(service, "_rag_unified_rows", fake_rows)
        return service

    @pytest.mark.asyncio
    async def test_period_row_survives_rerank_rest_is_filtered(
            self, monkeypatch):
        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": True,
                           "memory.nostalgia_layer_a_enabled": False})
        rows = [self._row(1, 2026, "Текущее событие про отпуск"),
                self._row(2, 2026, "Нерелевантная строка про рыбалку"),
                self._row(3, 2023, "Старое событие про переезд", period=True)]
        memory = self._Memory(keep_n=1)
        service = self._service(monkeypatch, memory, rows)
        block, _hint = await service._build_rag_block(
            CHAT, self._Msg("что было с отпуском"), "")
        assert "переезд" in block, (block, "периодный добор обязан выжить")
        assert "рыбалку" not in block, (block, "реранк фильтрует остальной срез")
        # Реранку отдаётся только не-периодная часть среза.
        assert memory.calls, "реранк вызывался"
        assert all("переезд" not in item[1] for item in memory.calls[0])

    @pytest.mark.asyncio
    async def test_valid_empty_rerank_renders_no_block(self, monkeypatch):
        """F1 (ре-ревью 11.11.2026): валидный пустой ответ реранка
        (`{"selected":[]}`) — это решение модели «ничего не релевантно»; оно
        НЕ перекрывается добором, иначе блок собирался бы из одной старой
        строки (на архиве: «что нового у Aleksey?» → строка 2023 года)."""
        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": True,
                           "memory.nostalgia_layer_a_enabled": False})
        rows = [self._row(1, 2026, "Свежий факт"),
                self._row(9, 2024, "Факт другого периода", period=True)]
        memory = self._Memory(keep_n=0)          # валидный пустой выбор
        service = self._service(monkeypatch, memory, rows)
        block, _hint = await service._build_rag_block(
            CHAT, self._Msg("что нового?"), "")
        assert block == "", (block, "пустой ответ реранка — блока нет")
        assert memory.calls, "реранк вызывался по не-периодной части"

    @pytest.mark.asyncio
    async def test_fail_open_rerank_keeps_slice(self, monkeypatch):
        """Сбой реранка (fail-open) — срез остаётся прежним, добор тоже."""
        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": True,
                           "memory.nostalgia_layer_a_enabled": False})
        rows = [self._row(1, 2026, "Свежий факт"),
                self._row(9, 2024, "Факт другого периода", period=True)]

        class _Broken:
            async def rerank_rag_facts(self, query, facts):
                raise RuntimeError("provider down")

        service = self._service(monkeypatch, _Broken(), rows)
        block, _hint = await service._build_rag_block(
            CHAT, self._Msg("что нового?"), "")
        assert "Свежий факт" in block, block
        assert "другого периода" in block, block

    @pytest.mark.asyncio
    async def test_operative_has_no_period_fill(self, monkeypatch):
        """`operative` выходит ДО добора: маркеров нет, защита инертна."""
        from services import direct_chat_service as dcs

        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": True,
                           "memory.nostalgia_layer_a_enabled": False})
        service = dcs.DirectChatService(memory=self._Memory(keep_n=1), db=None,
                                        llm=None, aliases=None)
        calls: list = []

        class _Result:
            fact_rows = (TestPeriodFillSurvivesRerank._row(1, 2026, "Свежий"),
                         )

        async def fake_retrieve(db, memory, chat_id, query, channels,
                                limit, policy):
            calls.append(tuple(channels))
            return _Result()

        service.db = types.SimpleNamespace(
            search_messages_fts=lambda *a, **k: None)
        monkeypatch.setattr(service, "_rag_retrieve", fake_retrieve)
        rows = await service._rag_unified_rows(CHAT, "q", None,
                                               memory_scope="operative")
        assert calls == [("vector",)]
        assert not any(row.get("period_fill") for row in rows)
        assert dcs._rag_period_keys(rows) == set()

    def test_many_period_rows_are_capped(self):
        """Потолок `limit // 5`: сколько бы периодов ни было — не больше 2."""
        from services import direct_chat_service as dcs
        service = TestPeriodSlots._service()
        rows = [self._row(1, 2026, "текущее")]
        extra = [self._row(10 + index, 2019 + index, f"период {index}")
                 for index in range(6)]
        out = service._rag_append_period_rows(rows, extra, 10)
        assert len(out) == 3, "2 добора при limit=10"
        assert len(dcs._rag_period_keys(out)) == 2


class TestLexicalStemPeriodFill:
    """Решение архитектора 11.11.2026: периодный добор сводит словоформы
    вопроса и старого текста к одной основе (`lexical_stem`) и видит
    вытесненные квотой строки (`include_archived`). FTS5 без стемминга
    находил «колбас*», но не «колбасой»; векторный канал в добор не вводится.
    """

    @staticmethod
    def _msg(text):
        return TestPeriodFillSurvivesRerank._Msg(text)

    def test_default_mode_is_byte_identical(self):
        """Дефолт не изменился: прежняя prefix-OR формула байт-в-байт."""
        from services.summary_memory import build_fts_query
        assert build_fts_query(["колбасой", "было"]) == \
            '"колбасой"* OR "было"*'
        assert build_fts_query(["колбасой"], mode="prefix_or") == \
            '"колбасой"*'
        assert build_fts_query([], mode="prefix_or_stem") == ""

    def test_stem_mode_is_superset(self):
        from services.summary_memory import build_fts_query
        base = build_fts_query(["колбасой", "было"]).split(" OR ")
        stem = build_fts_query(["колбасой", "было"],
                               mode="prefix_or_stem").split(" OR ")
        assert set(base).issubset(set(stem)), (base, stem)
        assert '"колбас"*' in stem, stem
        # Короткие слова не усекаются: префикс остаётся прежним.
        assert '"было"*' in stem
        for term in stem:
            assert len(term.strip('"*')) >= 4, term

    def test_stem_word_has_no_six_char_clip(self):
        from services.search_aggregator import stem_word, term_key
        # «колбасный»: term_key клипует до 6 символов, stem_word — нет.
        assert stem_word("колбасный") == "колбасн"
        assert term_key("колбасный") == "колбас"
        # Минимум основы 4 символа: слишком короткая основа не берётся.
        assert stem_word("нового") == "новог"
        assert stem_word("я") == "я"

    @pytest.mark.asyncio
    async def test_period_call_flags_only_for_history(self, monkeypatch):
        """Новые флаги — только у периодного вызова historical/auto."""
        from services import direct_chat_service as dcs

        _hot(monkeypatch, {"flags.chat_rag_rerank_enabled": False,
                           "memory.nostalgia_layer_a_enabled": False})
        service = dcs.DirectChatService(memory=object(), db=None, llm=None,
                                        aliases=None)
        calls: list = []
        base_rows = [TestPeriodFillSurvivesRerank._row(index, 2026, f"f{index}")
                     for index in range(1, 7)]

        class _Result:
            fact_rows = ()

        async def fake_retrieve(db, memory, chat_id, query, channels, limit,
                                policy, **kwargs):
            calls.append((tuple(channels), policy, kwargs))
            result = _Result()
            result.fact_rows = (tuple(base_rows) if tuple(channels) == ("vector",)
                                else ())
            return result

        service.db = types.SimpleNamespace(
            search_messages_fts=lambda *a, **k: None)
        monkeypatch.setattr(service, "_rag_retrieve", fake_retrieve)

        for policy in ("historical", "auto", "operative"):
            calls.clear()
            await service._rag_unified_rows(CHAT, "что было с колбасой?",
                                            None, memory_scope=policy)
            base = [call for call in calls if call[0] == ("vector",)]
            period = [call for call in calls if call[0] == ("lexical",)]
            assert base and base[0][2] == {}, base
            if policy == "operative":
                assert period == [], "operative до добора не доходит"
            else:
                assert period, calls
                assert period[0][2] == {"lexical_stem": True,
                                        "include_archived": True}, period

    @pytest.mark.asyncio
    async def test_word_form_mismatch_finds_old_fact(self):
        """Словоформа вопроса ≠ форме в тексте: без стемминга не находится,
        со стеммингом — находится (реальный сборщик запроса и FTS)."""
        from services import mca_retrieval_context as mrc
        from services.database import DatabaseService

        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            old = await db.insert_graph_fact(
                CHAT, "сообщает о покупке еды маленькую колбасу",
                "history_import", None, weight=0.3, importance=2,
                message_timestamp=_ts(2023))
            # Вытесненная квотой строка: видна только с include_archived.
            archived = await db.insert_graph_fact(
                CHAT, "купил вкусную колбасу на рынке", "history_import",
                None, status="archived_fact", weight=0.3, importance=2,
                message_timestamp=_ts(2023))

            query = "колбасой"

            def ids(result):
                return {int(row["id"])
                        for row in (result.fact_rows or ())}

            plain = await mrc.retrieve(db, None, mrc.RetrievalRequest(
                chat_id=CHAT, query=query, mode="specific",
                purpose="reply", top_k=10, channels=("lexical",),
                reply_depth=0, memory_scope="historical"))
            assert old not in ids(plain), "базовый префикс не ловит словоформу"
            assert archived not in ids(plain)

            stem = await mrc.retrieve(db, None, mrc.RetrievalRequest(
                chat_id=CHAT, query=query, mode="specific",
                purpose="reply", top_k=10, channels=("lexical",),
                reply_depth=0, memory_scope="historical",
                lexical_stem=True, include_archived=True))
            assert old in ids(stem), "стемминг обязан найти словоформу"
            assert archived in ids(stem), "include_archived видит квоту"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_default_request_keeps_prefix_or_match(self):
        """Дефолтный `retrieve` строит ПРЕЖНЮЮ формулу (доказательство на
        вызове, а не только по коду): match без стемминга байт-в-байт."""
        from services import mca_retrieval_context as mrc
        from services.database import DatabaseService

        db = DatabaseService(":memory:")
        await db.initialize()
        seen: list = []
        original = db.search_graph_facts_fts

        async def spy(chat_id, match, limit, now_ts, **kwargs):
            seen.append((match, kwargs.get("include_archived")))
            return await original(chat_id, match, limit, now_ts, **kwargs)

        db.search_graph_facts_fts = spy
        try:
            await db.insert_graph_fact(
                CHAT, "сообщает о покупке еды маленькую колбасу",
                "history_import", None, weight=0.3, importance=2,
                message_timestamp=_ts(2023))
            await mrc.retrieve(db, None, mrc.RetrievalRequest(
                chat_id=CHAT, query="колбасой", mode="specific",
                purpose="reply", top_k=10, channels=("lexical",),
                reply_depth=0, memory_scope="historical"))
            await mrc.retrieve(db, None, mrc.RetrievalRequest(
                chat_id=CHAT, query="колбасой", mode="specific",
                purpose="reply", top_k=10, channels=("lexical",),
                reply_depth=0, memory_scope="historical",
                lexical_stem=True, include_archived=True))
        finally:
            await db.close()
        assert seen[0][0] == '"колбасой"*', seen
        assert seen[0][1] is False, "по умолчанию архив не запрашивается"
        assert seen[1][0] == '"колбасой"* OR "колбас"*', seen
        assert seen[1][1] is True
