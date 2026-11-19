"""TIME-03 natural memory — детерминированный S1–S7 baseline/candidate harness.

Контракт: `plans/features/vmq-onto-01/evidence/mem07/architect-time03-natural-memory.md`
§6 (7 сценариев владельца) и §5 (T-кейсы). Полный 4,4 ГБ reissue здесь НЕ
выполняется: это адресный синтетический прогон на тех же механизмах
(retrieval-контракт, `_rag_unified_rows`, `_build_old_episodes`, EvidenceBundle),
с одинаковыми данными/настройками для baseline и candidate.

BASELINE — явно помеченная модель документированного поведения `0fce97a14`
(§1.4/§1.6/§1.8 архитектурного контракта), а НЕ продуктовый код:
  * `auto`+`answer` полный срез не запускал добор (`auto_full_slice`);
  * добор исключал годы базового среза и брал «другой старый год» квотой;
  * эпизодный запрос имел возрастной бонус (`age_days < 365`).

CANDIDATE — реальные функции продукта; fake только источник кандидатов
(`_rag_retrieve`/сообщения), потому что эмбеддинги в детерминированном
прогоне не участвуют.

Метрики сценария (numerator/denominator, без year-share):
`required_fact_recall`, `relevance`, `episode_completeness`,
`temporal_correctness`, `participant_attribution`, `source_proof`,
`retrieve_calls` (latency/cost proxy).
"""
import asyncio
import calendar
import json
import types
from pathlib import Path

import pytest

from services import direct_chat_service as dcs
from services import mca_retrieval_context as mrc
from services.database import DatabaseService
from services.summary_aliases import AliasResolver
from services.summary_memory import _fact_valid_now

CHAT = -100
UID_LEHA = 7
UID_ANYA = 8
UID_TOLYA = 9

BASELINE_PATH = (Path(__file__).resolve().parent / "fixtures"
                 / "time03_s_baseline_0fce97a14.json")


def _baseline():
    with BASELINE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)["scenarios"]


def _ts(year: int, month: int = 6, day: int = 1, hour: int = 12,
        minute: int = 0) -> int:
    return calendar.timegm((year, month, day, hour, minute, 0, 0, 0, 0))


def _row(fid, text, *, year=2026, month=6, day=1, hour=12,
         target="Лёха", speaker=UID_LEHA, status="confirmed",
         origin="history_import", ts=None):
    return {
        "id": fid, "fact": text, "origin": origin, "status": status,
        "expires_at": None, "target_user": target,
        "speaker_author_id": speaker,
        "created_at": ts if ts is not None else _ts(year, month, day, hour),
        "message_timestamp": ts if ts is not None else _ts(
            year, month, day, hour),
        "tg_message_id": 900_000 + fid, "chat_id": CHAT,
        "item_id": f"fact:{fid}", "weight": 0.6, "importance": 5,
    }


def _current_rows(count=10, start=9000):
    return [_row(fid, f"текущий факт {index}", origin="chat_history")
            for index, fid in enumerate(range(start, start + count))]


class _Result:
    def __init__(self, fact_rows, period_fill=None):
        self.fact_rows = tuple(fact_rows)
        self.period_fill = period_fill


class _DbStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    async def search_messages_fts(self, *_a, **_k):
        return []


def _service(monkeypatch, base_rows, pool_rows, *, calls=None, db=None):
    db = db or _DbStub()

    async def _identity_rerank(_query, facts):
        return list(facts)

    memory = types.SimpleNamespace(rerank_rag_facts=_identity_rerank)
    service = dcs.DirectChatService(memory=memory, db=db, llm=None,
                                    aliases=None)

    async def fake(_db, _memory, chat_id, query, channels, limit, policy,
                   *, period_fill=False, period_intent=None, **_kwargs):
        if calls is not None:
            calls.append({"period_fill": bool(period_fill),
                          "channels": tuple(channels),
                          "exclude_years": tuple(
                              _kwargs.get("exclude_years") or ())})
        if period_fill:
            return _Result(pool_rows,
                           period_fill={"vector_leg": "compat_not_proven",
                                        "vector_rows": 0})
        return _Result(base_rows)

    monkeypatch.setattr(service, "_rag_retrieve", fake)
    return service


def _metrics(rows, *, required, relevant, expected_years, universe):
    delivered = {row["id"] for row in rows}
    delivered_relevant = delivered & set(relevant)
    years = {mrc.period_row_year(row) for row in rows if row.get("period_fill")}
    return {
        "delivered": len(delivered),
        "required_recall": (len(delivered & set(required))
                            / max(1, len(set(required)))),
        "relevance": (len(delivered_relevant) / len(delivered)
                      if delivered else 0.0),
        "temporal_correctness": int(years == set(expected_years)),
        "source_proof": int(delivered <= set(universe) and all(
            row.get("item_id") for row in rows)),
    }


# ── S1: давно участвующий человек без года ─────────────────────────────────


@pytest.mark.asyncio
async def test_s1_long_term_person_without_year(monkeypatch):
    base = _current_rows(10)
    pool = [_row(100, "переезд Лёха в Казань в 2022", year=2022),
            _row(101, "переезд мебели в новый офис", year=2024,
                 target="Толя", speaker=UID_TOLYA)]
    reads = {"profile": 0}

    async def _profile(*_a, **_k):
        reads["profile"] += 1
        return []

    db = _DbStub(get_user_context_facts=_profile,
                 get_subject_profile_facts=_profile)
    calls: list = []
    service = _service(monkeypatch, base, pool, calls=calls, db=db)
    rows = await service._rag_unified_rows(
        CHAT, "что рассказывал Лёха про переезд?", None,
        memory_scope="auto", plan_act="research",
        subject_name="Толя", subject_uid=UID_TOLYA)
    metrics = _metrics(rows, required=(100,),
                       relevant=(100, 9000, 9001, 9002, 9003, 9004, 9005,
                                 9006, 9007, 9008, 9009),
                       expected_years=(2022,),
                       universe={100, 101, *range(9000, 9010)})
    delivered = {row["id"] for row in rows}
    assert metrics["required_recall"] == 1.0, metrics
    assert 100 in delivered and 101 not in delivered
    old = next(row for row in rows if row["id"] == 100)
    assert old["target_user"] == "Лёха", "атрибуция участника"
    assert mrc.period_row_year(old) == 2022
    assert metrics["source_proof"] == 1
    # Guard от чужого человека: профиль адресата «Толя» не читается.
    assert reads == {"profile": 0}
    # Baseline (0fce97a14, fixture): полный auto-срез не добирал старое.
    baseline = _baseline()["S1"]
    assert baseline["required_recall"] == 0.0
    assert baseline["period_rows"] == 0
    assert metrics["required_recall"] > baseline["required_recall"]
    assert metrics["temporal_correctness"] > baseline["temporal_correctness"]
    # Стоимость: один базовый + один bounded добор.
    assert sum(1 for call in calls if call["period_fill"]) == 1
    assert len(calls) == 2


# ── S2: старая история по неполной смысловой зацепке ──────────────────────


@pytest.mark.asyncio
async def test_s2_old_story_by_partial_anchor(monkeypatch):
    base = _current_rows(10)
    pool = [_row(200, "чинили лодку на даче", year=2023),
            _row(201, "чинили машину в гараже", year=2026),
            _row(202, "лодку покрасили весной", year=2024)]
    service = _service(monkeypatch, base, pool)
    rows = await service._rag_unified_rows(
        CHAT, "помнишь, как мы чинили лодку?", None,
        memory_scope="auto", plan_act="research")
    delivered = {row["id"] for row in rows}
    assert 200 in delivered, rows
    assert mrc.period_row_year(
        next(row for row in rows if row["id"] == 200)) == 2023
    baseline = _baseline()["S2_direct"]
    assert baseline["required_recall"] == 0.0
    assert baseline["period_rows"] == 0


@pytest.mark.asyncio
async def test_s2_episode_completeness_participants_and_order():
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        for index, text in enumerate((
                "чинили лодку утром на даче",
                "лодка текла, взяли инструменты",
                "к вечеру лодку починили")):
            await db.save_smart_message(
                UID_LEHA if index != 1 else UID_ANYA, CHAT, text, None,
                _ts(2023, 7, 1, 10, index * 3), "text",
                "Лёха" if index != 1 else "Аня",
                message_id=7000 + index)
        service = dcs.DirectChatService(memory=None, db=db, llm=None,
                                        aliases=AliasResolver("{}"))
        block, stats = await service._build_old_episodes(
            CHAT, "помнишь, как мы чинили лодку?", [], {})
        assert block.startswith("<Old_Episode>")
        lines = [line for line in block.split("\n") if "tg:" in line]
        assert len(lines) == 3, block
        assert "Лёха" in block and "Аня" in block
        # Последовательность: утро → вечер (ASC по времени).
        assert block.index("утром") < block.index("к вечеру")
        assert len(stats["spans"]) == 1
        span = stats["spans"][0]
        assert span["first_ts"] < span["last_ts"]
        assert span["source_ids"]
        # Baseline 0fce97a14 на том же fixture: тот же единственный эпизод.
        baseline = _baseline()["S2_episode"]
        assert baseline["episodes"] == 1
        assert span["first_ts"] == baseline["first_span_first_ts"]
    finally:
        await db.close()


# ── S3: изменение отношений/обстоятельств за несколько лет ────────────────


@pytest.mark.asyncio
async def test_s3_relationship_change_chronology(monkeypatch):
    base = _current_rows(10)
    pool = [_row(301, "Лёха и Аня поженились", year=2022, target="Лёха",
                 speaker=UID_LEHA),
            _row(302, "Лёха и Аня развелись", year=2024, target="Лёха",
                 speaker=UID_LEHA)]
    calls: list = []
    service = _service(monkeypatch, base, pool, calls=calls)
    rows = await service._rag_unified_rows(
        CHAT, "расскажи про отношения Лёха и Аня", None,
        memory_scope="auto", plan_act="research")
    delivered = {row["id"] for row in rows}
    assert {301, 302} <= delivered, rows
    years = {row["id"]: mrc.period_row_year(row) for row in rows
             if row.get("period_fill")}
    assert years == {301: 2022, 302: 2024}, years
    metrics = _metrics(rows, required=(301, 302),
                       relevant=(301, 302) + tuple(range(9000, 9008)),
                       expected_years=(2022, 2024),
                       universe={301, 302, *range(9000, 9010)})
    assert metrics["required_recall"] == 1.0, metrics
    assert metrics["temporal_correctness"] == 1, metrics
    baseline = _baseline()["S3"]
    assert baseline["required_recall"] == 0.0
    assert baseline["period_rows"] == 0
    assert metrics["required_recall"] > baseline["required_recall"]


# ── S4: текущее положение, историческая информация устарела ───────────────


@pytest.mark.asyncio
async def test_s4_current_state_not_replaced_by_stale_history(monkeypatch):
    base = _current_rows(10)
    base[0] = _row(9000, "Лёха работает в Яндексе", origin="chat_history")
    old = _row(401, "Лёха работал в Google", year=2019,
               status="archived_fact")
    service = _service(monkeypatch, base, [old])
    rows = await service._rag_unified_rows(
        CHAT, "где сейчас работает Лёха?", None,
        memory_scope="auto", plan_act="answer")
    delivered = {row["id"] for row in rows}
    # Контроль не вакуумный: старый факт существует и V=0.
    assert _fact_valid_now(old, _ts(2026)) is False
    assert 9000 in delivered
    assert 401 not in delivered, "полный auto-срез не добирает историю"
    assert service._rag_period_stats["breadth_allowed"] == 0
    baseline = _baseline()["S4"]
    assert baseline["current_present"] == 1
    assert baseline["old_present"] == 0
    assert (9000 in delivered) == bool(baseline["current_present"])
    assert (401 in delivered) == bool(baseline["old_present"])
    # `operative` не изменён: только действующее, без периода.
    calls: list = []
    operative = _service(monkeypatch, base, [old], calls=calls)
    op_rows = await operative._rag_unified_rows(
        CHAT, "где сейчас работает Лёха?", None, memory_scope="operative")
    assert {row["id"] for row in op_rows} == set(range(9000, 9010))
    assert calls == [{"period_fill": False, "channels": ("vector",),
                      "exclude_years": ()}]
    assert operative._rag_period_stats == {}


# ── S5: явно заданный период + последовательность ─────────────────────────


@pytest.mark.asyncio
async def test_s5_explicit_period_sequence(monkeypatch):
    base = _current_rows(10)
    pool = [_row(501, "первый день конференции", year=2023, month=5, day=2,
                 hour=9),
            _row(502, "закрытие конференции", year=2023, month=5, day=4,
                 hour=18),
            _row(503, "конференция 2026 года", year=2026)]
    calls: list = []
    service = _service(monkeypatch, base, pool, calls=calls)
    rows = await service._rag_unified_rows(
        CHAT, "что было на конференции в 2023 году?", None,
        memory_scope="auto", plan_act="answer")
    period = [row for row in rows if row.get("period_fill")]
    assert {row["id"] for row in period} == {501, 502}, period
    assert {mrc.period_row_year(row) for row in period} == {2023}
    assert 503 not in {row["id"] for row in rows}
    # Последовательность в блоке — хронология ASC (существующий рендер).
    block, _hint = await service._build_rag_block(
        CHAT, _Msg("что было на конференции в 2023 году?"), "",
        memory_scope="auto", plan_act="answer")
    assert "первый день конференции" in block
    assert "закрытие конференции" in block
    assert block.index("первый день") < block.index("закрытие")
    # Baseline explicit-year отбор (0fce97a14) терял вторую строку того же
    # года: `year in seen_years` — sequence incomplete (period_rows=1).
    baseline = _baseline()["S5"]
    assert baseline["period_rows"] == 1
    assert baseline["required_recall"] == 0
    assert len(period) == 2 > baseline["period_rows"]
    assert baseline["year_2026_period"] == 0


class _Msg:
    def __init__(self, text):
        self.text = text
        self.message_id = 100


# ── S6: несколько похожих эпизодов — выбрать правильный ──────────────────


@pytest.mark.asyncio
async def test_s6_similar_episodes_picks_correct_anchor():
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        for index, text in enumerate((
                "история с синей кружкой случилась на кухне",
                "синей кружкой разбили чашку",
                "потом все смеялись")):
            await db.save_smart_message(
                UID_LEHA, CHAT, text, None,
                _ts(2022, 3, 4, 11, index * 2), "text", "Лёха",
                message_id=7100 + index)
        for index, text in enumerate((
                "похожий случай с посудой на кухне",
                "красная посуда разбилась")):
            await db.save_smart_message(
                UID_ANYA, CHAT, text, None,
                _ts(2025, 8, 9, 12, index * 2), "text", "Аня",
                message_id=7200 + index)
        service = dcs.DirectChatService(memory=None, db=db, llm=None,
                                        aliases=AliasResolver("{}"))
        block, stats = await service._build_old_episodes(
            CHAT, 'та самая история с "синей кружкой"', [], {})
        assert "синей кружкой" in block
        # Правильный эпизод идёт первым; похожий свежий (если он вообще
        # попал в срез) не выдаётся за якорь и не сливается с ним.
        if "похожий случай" in block:
            assert block.index("синей кружкой") < block.index("похожий случай")
        first_span = stats["spans"][0]
        assert "msg:7100" in first_span["source_ids"]
        assert first_span["first_ts"] < _ts(2024, 1, 1)
        assert len(stats["spans"]) >= 1
        # Baseline 0fce97a14 на том же fixture: правильный якорь тоже первый
        # (exact-канал доминирует канальный вес); регрессии нет.
        baseline = _baseline()["S6"]
        assert baseline["correct_first"] == 1
        assert first_span["first_ts"] == baseline["first_span_first_ts"]
        assert int("синей кружкой" in block) >= \
            baseline["correct_anchor_present"]
    finally:
        await db.close()


# ── S7: отсутствующие сведения — честный недостаток доказательств ─────────


@pytest.mark.asyncio
async def test_s7_missing_information_is_honest(monkeypatch):
    base = _current_rows(10)
    calls: list = []
    service = _service(monkeypatch, base, [], calls=calls)
    rows = await service._rag_unified_rows(
        CHAT, "что было с вертолётом в 2019 году?", None,
        memory_scope="auto", plan_act="answer")
    assert {row["id"] for row in rows} == set(range(9000, 9010))
    assert not any(row.get("period_fill") for row in rows)
    assert service._rag_period_stats["breadth_used"] == 0
    # EvidenceBundle: только реальные refs базового среза, 0 выдуманных.
    block = "<RAG_Memory>\n" + "\n".join(
        f"[2026 | факт | fact:{row['id']}]: {row['fact']}" for row in rows
    ) + "\n</RAG_Memory>"
    bundle = await service._build_evidence_bundle(
        CHAT, _Msg("что было с вертолётом в 2019 году?"),
        "что было с вертолётом в 2019 году?", "Лёха", UID_LEHA, [block])
    assert bundle is not None
    refs = {item.entity_id for item in bundle.evidence}
    assert refs <= {f"fact:{fid}" for fid in range(9000, 9010)} | {"tg:100"}
    assert refs == {f"fact:{fid}" for fid in range(9000, 9010)} | {"tg:100"}, refs
    # Baseline 0fce97a14 на том же fixture: тоже без fabrication.
    baseline = _baseline()["S7"]
    assert baseline["base_intact"] == 1 and baseline["fabricated"] == 0
    assert baseline["period_rows"] == 0
    # Пустой периодный пул не маскируется: vector_leg честен.
    assert service._rag_period_stats["vector_leg"] == "compat_not_proven"
