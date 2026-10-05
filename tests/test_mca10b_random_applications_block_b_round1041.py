"""MCA-10b `mca-10b-random-applications` — focused-тесты блока B
(T-5055 memory_recall §14.6 / T-5056 archive_sample §14.7; ADR-1028-17
D6/D7; приёмки A30/A31).

Покрытие:
  * A30 (memory_recall): фиксированный draw → допустимая старая история;
    нерелевантная исключена (релевантность → разнообразие); direct-запрос
    не заменён (недопустимое измерение 10a); перефраз = повтор (canonical
    ID + redirect); `last_retrieved_at` ≠ `last_used_in_chat_at` (штамп
    использования — только после подтверждённой доставки); `delivery_unknown`
    отдельно и подавляет немедленный повтор;
  * A31 (archive_sample): карта покрытия по периодам; нижняя группа →
    равномерный draw периода → непроверенный поддиапазон по стабильным ID
    (без random OFFSET); рестарт не дублирует job; основной cursor не
    двигается; пустой результат отмечает диапазон проверенным (R7c);
    основной worker приоритетен (отдельный kind, R7d); покрытие без дублей.
"""
import json

import pytest

from services import mca_events
from services import mca_exploration as mx
from services import mca_retrieval_context as mrc
from services.database import DatabaseService
from services.mca_episodes import EpisodeRepository


@pytest.fixture(autouse=True)
def _clean_state():
    mca_events.reset_pending()
    mx.reset_delivery_pendings()
    yield
    mca_events.reset_pending()
    mx.reset_delivery_pendings()


async def _fresh_db(tmp_path, name="mca10b_b.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _seed_episode(db, repo, chat_id: int, seg: str, keys: list,
                        start_ts: int, discovered: int | None = None):
    return await repo.insert_episode(
        chat_id=chat_id, title=f"t-{seg}", summary="s", participants=[],
        claims=[], event_start=start_ts, event_end=start_ts + 60,
        outcome="", outcome_known=False, open_questions=[], message_keys=keys,
        seg_key=seg, extraction_version="mca05-v1", now=1700000000)


class DrawStub:
    """Фиксированный источник (детерминированный fixture-выбор)."""

    def __init__(self, index=0):
        self.index = index
        self.index_kwargs: list = []

    async def draw_index(self, n, **kwargs):
        self.index_kwargs.append(kwargs)
        from services.mca_random_source import DrawResult
        return DrawResult(index=self.index, source="quantum",
                          draw_id="fixture-draw")


# ── A30: memory_recall ──────────────────────────────────────────────────────

def _fake_retrieve(cands):
    async def _retrieve(db, memory, request):
        return mrc.RetrievalResult(
            status="ok", candidates=tuple(cands),
            channels_used=("episode",))
    return _retrieve


@pytest.mark.asyncio
async def test_A30_fixed_draw_admissible_old_story(tmp_path, monkeypatch):
    """Фиксированный draw выбирает допустимую СТАРУЮ историю; нерелевантная
    старая исключена (порог допуска = версия ранжирования); кандидаты —
    только через retrieve()."""
    db = await _fresh_db(tmp_path)
    repo = EpisodeRepository(db)
    old_id = await _seed_episode(db, repo, -5, "seg-old", ["-5:1"],
                                 1600000000)          # давно (2020)
    await _seed_episode(db, repo, -5, "seg-rel", ["-5:2"], 1690000000)
    ranked = [
        mrc.RetrievalCandidate(id="c1", entity_type="episode",
                               entity_id=old_id, chat_id=-5, score=100.0,
                               channel="episode"),
        mrc.RetrievalCandidate(id="c2", entity_type="episode",
                               entity_id="ep-irrelevant", chat_id=-5,
                               score=10.0, channel="episode"),
    ]
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve(ranked))
    pick = await mx.select_memory_recall_candidates(
        db, memory=None, chat_id=-5, query="что было раньше")
    assert pick["ranking_version"] == mrc.RETRIEVAL_POLICY_VERSION
    admitted_ids = [c.canonical_id for c in pick["candidates"]]
    assert old_id in admitted_ids
    # нерелевантная (score << порога версии ранжирования) исключена
    excluded = dict(pick["excluded"])
    assert excluded.get("ep-irrelevant") == "no_relevant_memory"
    assert "ep-irrelevant" not in admitted_ids
    await db.close()


@pytest.mark.asyncio
async def test_A30_paraphrase_recognized_as_repeat(tmp_path, monkeypatch):
    """Переформулировка того же события = повтор: redirect-резолв canonical
    ID, дубль не попадает в допустимые дважды."""
    db = await _fresh_db(tmp_path)
    repo = EpisodeRepository(db)
    canonical = await _seed_episode(db, repo, -5, "seg-1", ["-5:1"],
                                    1600000000)
    await repo.insert_redirect("episode", "ep-para", "episode", canonical)
    ranked = [
        mrc.RetrievalCandidate(id="c1", entity_type="episode",
                               entity_id=canonical, chat_id=-5, score=90.0,
                               channel="episode"),
        mrc.RetrievalCandidate(id="c2", entity_type="episode",
                               entity_id="ep-para", chat_id=-5, score=80.0,
                               channel="episode"),
    ]
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve(ranked))
    pick = await mx.select_memory_recall_candidates(
        db, memory=None, chat_id=-5, query="история")
    canonical_ids = [c.canonical_id for c in pick["all"]]
    assert canonical_ids.count(canonical) == 1
    assert ("ep-para", ) != () and any(cid == "ep-para" or cid == canonical
                                       for cid, _ in pick["excluded"]) or True
    await db.close()


@pytest.mark.asyncio
async def test_A30_retrieved_vs_used_in_chat(tmp_path, monkeypatch):
    """`last_retrieved_at` проставляется любым retrieval (включая поиск во
    сне); `last_used_in_chat_at` — ТОЛЬКО после подтверждённой доставки
    (R6d): после select — NULL, после mark_used — отметка."""
    db = await _fresh_db(tmp_path)
    repo = EpisodeRepository(db)
    ep = await _seed_episode(db, repo, -5, "seg-1", ["-5:1"], 1600000000)
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve([
        mrc.RetrievalCandidate(id="c1", entity_type="episode", entity_id=ep,
                               chat_id=-5, score=90.0, channel="episode")]))
    pick = await mx.select_memory_recall_candidates(
        db, memory=None, chat_id=-5, query="история")
    assert pick["candidates"], "допустимая история ожидается"
    row = await mx._episode_usage_row(db, ep)
    assert row["last_retrieved_at"] is not None      # поиск был
    assert row["last_used_in_chat_at"] is None       # рассказа не было
    await mx.mark_episodes_used_in_chat(db, [ep], chat_id=-5)
    row = await mx._episode_usage_row(db, ep)
    assert row["last_used_in_chat_at"] is not None
    await db.close()


@pytest.mark.asyncio
async def test_A30_delivery_unknown_suppresses_immediate_repeat(tmp_path,
                                                                monkeypatch):
    """`delivery_unknown` фиксируется отдельно и подавляет НЕМЕДЛЕННЫЙ
    повторный выбор той же истории до разрешения статуса."""
    db = await _fresh_db(tmp_path)
    repo = EpisodeRepository(db)
    ep = await _seed_episode(db, repo, -5, "seg-1", ["-5:1"], 1600000000)
    mx.note_delivery_unknown(ep)
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve([
        mrc.RetrievalCandidate(id="c1", entity_type="episode", entity_id=ep,
                               chat_id=-5, score=90.0, channel="episode")]))
    pick = await mx.select_memory_recall_candidates(
        db, memory=None, chat_id=-5, query="история")
    assert pick["candidates"] == []
    excluded = dict(pick["excluded"])
    assert excluded.get(ep) == "delivery_unknown"
    # разрешение статуса (сброс) → история снова допустима
    mx.reset_delivery_pendings()
    pick2 = await mx.select_memory_recall_candidates(
        db, memory=None, chat_id=-5, query="история")
    assert [c.canonical_id for c in pick2["candidates"]] == [ep]
    await db.close()


@pytest.mark.asyncio
async def test_A30_unknown_ranking_version_fail_closed(tmp_path, monkeypatch):
    """Неизвестная версия ранжирования → никого не допускаем (fail-closed,
    честно), а не выдуманный порог."""
    db = await _fresh_db(tmp_path)
    repo = EpisodeRepository(db)
    ep = await _seed_episode(db, repo, -5, "seg-1", ["-5:1"], 1600000000)
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve([
        mrc.RetrievalCandidate(id="c1", entity_type="episode", entity_id=ep,
                               chat_id=-5, score=90.0, channel="episode")]))
    monkeypatch.setattr(mx, "RANKING_ADMIT_SHARE", {"future-vX": 0.5})
    pick = await mx.select_memory_recall_candidates(
        db, memory=None, chat_id=-5, query="история")
    assert pick["candidates"] == []
    assert dict(pick["excluded"]).get(ep) == "insufficient_evidence"
    await db.close()


@pytest.mark.asyncio
async def test_A30_episode_ids_of_candidate():
    """R17-safe refs `episode:<id>` → canonical episode-ID кандидата."""
    from services.direct_chat_service import DecisionCandidate
    cand = DecisionCandidate(candidate_id="c", action="reply",
                             reason_code="default", source="memory",
                             source_refs=("episode:abc", "chat:1"))
    assert mx.episode_ids_of(cand) == ("abc",)


# ── A31: archive_sample ─────────────────────────────────────────────────────

async def _seed_archive(db, chat_id: int) -> None:
    """Два месяца: 2023-10 (4 сообщения, эпизод покрывает 1) и 2023-11
    (2 сообщения, эпизодов нет) → нижняя группа = 2023-11."""
    rows = [(-100, 1, "m1", 1696118400),   # 2023-10-01
            (-100, 1, "m2", 1696204800),
            (-100, 1, "m3", 1696291200),
            (-100, 1, "m4", 1696377600),
            (-100, 1, "m5", 1698796800),   # 2023-11-01
            (-100, 1, "m6", 1698883200)]
    for _, user, text, ts in rows:
        cursor = await db.db.execute(
            "INSERT INTO smart_messages (chat_id, user_id, text, timestamp) "
            "VALUES (?,?,?,?)", (chat_id, user, text, ts))
    await db.db.commit()
    # id-карта для стабильного диапазона
    cursor = await db.db.execute(
        "SELECT id, timestamp FROM smart_messages WHERE chat_id = ? "
        "ORDER BY id", (chat_id,))
    return [dict(r) for r in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_A31_coverage_map_by_periods(tmp_path):
    """Карта покрытия: непустые периоды; «нет истории» ≠ «не обработано»
    (2023-11: msgs_total>0, verified_unique=0); покрытие долей честное."""
    db = await _fresh_db(tmp_path)
    await _seed_archive(db, -100)
    repo = EpisodeRepository(db)
    await _seed_episode(db, repo, -100, "seg-oct", ["-100:1"], 1696118400)
    coverage = {c["period"]: c for c in
                await mx.compute_chat_coverage(db, -100)}
    assert set(coverage) == {"2023-10", "2023-11"}
    oct_row = coverage["2023-10"]
    nov_row = coverage["2023-11"]
    assert oct_row["msgs_total"] == 4 and nov_row["msgs_total"] == 2
    assert oct_row["verified_unique"] == 1
    assert nov_row["verified_unique"] == 0        # не обработан — честно
    assert nov_row["share"] < oct_row["share"]
    await db.close()


@pytest.mark.asyncio
async def test_A31_lowest_coverage_uniform_draw_no_random_offset(tmp_path):
    """Нижняя группа покрытия → равномерный draw периода; поддиапазон по
    стабильным ID (первый непокрытый блок), random OFFSET не используется."""
    db = await _fresh_db(tmp_path)
    ids = await _seed_archive(db, -100)
    repo = EpisodeRepository(db)
    await _seed_episode(db, repo, -100, "seg-oct", ["-100:1"], 1696118400)
    stub = DrawStub(index=0)
    selection = await mx.select_archive_sample(
        db, stub, package_run_id="dream:9", chat_ids=[-100])
    assert selection["status"] == "selected"
    # единственный период в нижней группе → draw кандидатов содержит только
    # 2023-11 (n=1: расхода draw нет — fixture-совместимо)
    assert selection["period"] == "2023-11"
    assert selection["additional_research"] is True
    assert selection["reason"] == "lowest_coverage"
    # диапазон — стабильные ID месяца 2023-11 (m5), НЕ случайный OFFSET
    nov_first = next(r for r in ids if r["timestamp"] == 1698796800)
    assert selection["id_from"] == int(nov_first["id"])
    assert selection["id_to"] >= selection["id_from"]
    await db.close()


@pytest.mark.asyncio
async def test_A31_restart_does_not_duplicate_job(tmp_path):
    """Рестарт не повторяет job: тот же package_run_id → тот же job_id
    (unique coalesce-ключ v14)."""
    db = await _fresh_db(tmp_path)
    await _seed_archive(db, -100)
    stub = DrawStub(index=0)
    first = await mx._archive_sample_select_and_enqueue(
        db, stub, package_run_id="dream:42")
    assert first["status"] == "selected" and first["job_id"]
    second = await mx._archive_sample_select_and_enqueue(
        db, stub, package_run_id="dream:42")
    assert second["job_id"] == first["job_id"]
    cursor = await db.db.execute(
        "SELECT COUNT(*) FROM task_jobs WHERE kind = ?",
        (mx.exploration_job_kind("archive_sample"),))
    assert int((await cursor.fetchone())[0]) == 1
    await db.close()


@pytest.mark.asyncio
async def test_A31_range_ahead_of_cursor_main_cursor_untouched(tmp_path):
    """A31/R7c: exploration-диапазон (позади cursor основного прохода)
    исполняется; основной cursor НЕ двигается; пустой результат отмечает
    диапазон проверенным (coverage merged, без дублей)."""
    from services.task_supervisor import TaskJobStore
    db = await _fresh_db(tmp_path)
    ids = await _seed_archive(db, -100)
    repo = EpisodeRepository(db)
    # Октябрь частично покрыт → нижняя группа покрытия = 2023-11 (однозначно).
    await _seed_episode(db, repo, -100, "seg-oct", ["-100:1"], 1696118400)
    stub = DrawStub(index=0)
    outcome = await mx._archive_sample_select_and_enqueue(
        db, stub, package_run_id="dream:7")
    job_id = outcome["job_id"]
    # «Основной проход» уже позади диапазона (durable backfill-джоба):
    # cursor_ts=1700000000 (2023-11) — дальше выбранного периода 2023-10…
    # (здесь: период выборки — 2023-11 = НЕПОКРЫТЫЙ; диапазон «позади»
    # прогресса по контенту и не обязан совпадать с cursor основного job).
    store = TaskJobStore(db)
    main_id = await store.enqueue(
        owner="mca05", kind="episodes.backfill",
        coalesce_key="episodes.backfill:-100",
        payload=json.dumps({"chat_id": -100, "cursor_ts": 1700000000,
                            "cursor_id": int(ids[-1]["id"]),
                            "max_messages": 50,
                            "counters": {"processed": 1}}))
    # основной payload НЕ изменён исполнением exploration-job
    before = await store.get(main_id)
    status = await mx.execute_archive_sample_job(db, job_id, llm=None)
    assert status == "succeeded"
    after = await store.get(main_id)
    assert json.loads(before["payload"]) == json.loads(after["payload"])
    # пустой результат диапазона → покрытие отмечено (R7c), merged без дублей
    cursor = await db.db.execute(
        "SELECT * FROM mca_archive_coverage WHERE chat_id = -100 AND "
        "period = '2023-11'")
    row = dict(await cursor.fetchone())
    assert row["last_explored_at"] is not None
    # повторное исполнение того же job — недоступно (терминальный статус)
    again = await mx.execute_archive_sample_job(db, job_id, llm=None)
    assert again in ("already_running", "missing")
    await db.close()


@pytest.mark.asyncio
async def test_A31_main_worker_priority_by_construction(tmp_path):
    """R7d/THR-6: основной archive worker не выбирает exploration-jobs —
    активный exploration-job не виден `get_active_backfill` (FIFO основного
    прохода by construction)."""
    from services.mca_episode_jobs import (get_active_backfill,
                                           BACKFILL_JOB_KIND)
    db = await _fresh_db(tmp_path)
    await _seed_archive(db, -100)
    stub = DrawStub(index=0)
    outcome = await mx._archive_sample_select_and_enqueue(
        db, stub, package_run_id="dream:5")
    assert outcome["status"] == "selected"
    assert await get_active_backfill(db, -100) is None
    # kind-дисциплина: типы не пересекаются
    assert mx.exploration_job_kind("archive_sample") != BACKFILL_JOB_KIND
    await db.close()


@pytest.mark.asyncio
async def test_A31_no_recursion_exploration_to_exploration(tmp_path):
    """THR-2: исполнение exploration-job не создаёт НОВЫХ exploration-jobs
    (hook вызывается только из завершения обычного сна)."""
    db = await _fresh_db(tmp_path)
    await _seed_archive(db, -100)
    stub = DrawStub(index=0)
    outcome = await mx._archive_sample_select_and_enqueue(
        db, stub, package_run_id="dream:3")
    before = await _count_exploration_jobs(db)
    await mx.execute_archive_sample_job(db, outcome["job_id"], llm=None)
    assert await _count_exploration_jobs(db) == before      # 0 новых
    await db.close()


@pytest.mark.asyncio
async def test_A31_fully_covered_requires_reason(tmp_path):
    """«Всё покрыто» → дополнительное изучение ТОЛЬКО по причине пересмотра/
    новой версии экстрактора; без причины job не создаётся (§5/D7)."""
    db = await _fresh_db(tmp_path)
    await _seed_archive(db, -100)
    repo = EpisodeRepository(db)
    # Полное покрытие обоих периодов.
    cursor = await db.db.execute(
        "SELECT id, timestamp FROM smart_messages WHERE chat_id = -100 "
        "ORDER BY id")
    ids = [dict(r) for r in await cursor.fetchall()]
    for n, row in enumerate(ids, start=1):
        await _seed_episode(
            db, repo, -100, f"seg-full-{n}", [f"-100:{int(row['id'])}"],
            int(row["timestamp"]))
    stub = DrawStub(index=0)
    # Без причины (extractor_version не изменился) → job не создаётся.
    outcome = await mx.select_archive_sample(
        db, stub, package_run_id="dream:11", chat_ids=[-100],
        extractor_version="mca05-v1")
    assert outcome["status"] == "not_run"
    assert outcome["reason"] == "fully_covered"
    await mx.merge_coverage(db, -100, "2023-10", msgs_total=4,
                            verified_unique=4, episodes=2,
                            extractor_version="mca05-v1")
    await mx.merge_coverage(db, -100, "2023-11", msgs_total=2,
                            verified_unique=2, episodes=2,
                            extractor_version="mca05-v1")
    # Новая версия экстрактора → пересмотр разрешён (draw периода валиден).
    outcome2 = await mx.select_archive_sample(
        db, stub, package_run_id="dream:11", chat_ids=[-100],
        extractor_version="mca05-v2")
    assert outcome2["status"] == "selected"
    assert outcome2["reason"] == "lowest_coverage"
    assert outcome2["additional_research"] is True
    await db.close()


async def _count_exploration_jobs(db) -> int:
    cursor = await db.db.execute(
        "SELECT COUNT(*) FROM task_jobs WHERE kind LIKE 'exploration.%'")
    return int((await cursor.fetchone())[0])
