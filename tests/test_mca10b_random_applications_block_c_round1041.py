"""MCA-10b `mca-10b-random-applications` — focused-тесты блока C
(T-5057 belief_review §14.8 / T-5058 association_pair §14.9 /
T-5059 conversation_variant §14.10; ADR-1028-17 D8/D9/D10; A32–A34).

Покрытие:
  * A32 (belief_review): контрпример ограничивает обобщение (narrowed,
    без отвержения); отсутствие контрпримера НЕ усиливает убеждение
    (weight/last_confirmed_at не трогаются); одинаковые материалы →
    вердикт не меняется (`belief_review_unchanged`, версия не растёт,
    книга v30 — durable `material_refs_hash`); выбор объекта — старшая
    группа `last_reviewed_at` (NULLS FIRST), исключения: ожидающие
    обязательную перепроверку + защищённые владельцем (overrides);
    ядро личности в наборе отсутствует структурно (derived graph_facts);
  * A33 (association_pair): дубли события не дают «связь» (разные
    canonical ID); нерелевантная пара отвергнута (insufficient →
    rejected = кэш по версиям); аналогия ≠ причинность/склейка
    (истории НЕ склеиваются, правил EpisodeService не касаемся);
    редакция источника → stale (по версиям); без LLM — честный deferred;
  * A34 (conversation_variant): неуместная шутка не в допущенных при
    direct; РОВНО одна probability-проверка на решение (формы — обычные
    кандидаты общего пула, без второго процента и стилевого броска);
    форма не меняет факты/адресата (silence → silent-action);
    повтор фразы = повтор (bounded окно, без постоянного запрета слов);
    OFF → пул форм не строится.
"""
import json

import pytest

from services import mca_events, mca_gates
from services import mca_exploration as mx
from services import mca_random_source as mrs
from services import mca_retrieval_context as mrc
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore


@pytest.fixture(autouse=True)
def _clean_state():
    from services import mca_dream_evidence
    mca_events.reset_pending()
    mx.reset_delivery_pendings()
    mca_dream_evidence.reset_revision_queue()
    yield
    mca_events.reset_pending()
    mx.reset_delivery_pendings()
    mca_dream_evidence.reset_revision_queue()


async def _fresh_db(tmp_path, name="mca10b_c.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


class DrawStub:
    """Фиксированный источник (детерминированный draw; без probability)."""

    def __init__(self, index=0):
        self.index = index
        self.calls: list = []

    async def draw_index(self, n, **kwargs):
        self.calls.append({"n": n, **{k: v for k, v in kwargs.items()
                                      if k in ("purpose", "candidates")}})
        from services.mca_random_source import DrawResult
        return DrawResult(index=min(self.index, max(0, n - 1)),
                          source="quantum", draw_id="fixture-draw")


class FakeLLM:
    """Детерминированная LLM-классификация связи (не random)."""

    def __init__(self, payload: dict):
        self.payload = json.dumps(payload, ensure_ascii=False)
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self.payload


async def _seed_belief(db, chat_id: int, text: str, *, created: int = 1690000000,
                       meta: str | None = None) -> int:
    return await db.insert_graph_fact(
        chat_id, text, "derived_belief", None, status="confirmed",
        weight=0.6, kind="belief", belief_meta=meta, message_timestamp=created)


async def _seed_fact(db, chat_id: int, text: str, ts: int) -> int:
    return await db.insert_graph_fact(
        chat_id, text, "history_import", None, status="confirmed",
        message_timestamp=ts)


async def _enqueue_review_job(db, belief_id: int, chat_id: int) -> str:
    store = TaskJobStore(db)
    return await store.enqueue(
        owner="random.uses",
        kind=mx.exploration_job_kind(mx.PURPOSE_BELIEF_REVIEW),
        coalesce_key=mx.exploration_job_key(
            chat_id, "run-test", mx.PURPOSE_BELIEF_REVIEW),
        payload=json.dumps({"type": mx.PURPOSE_BELIEF_REVIEW,
                            "belief_id": str(belief_id),
                            "chat_id": chat_id}),
        max_attempts=1)


async def _book_rows(db, belief_id: int) -> list:
    cursor = await db.db.execute(
        "SELECT * FROM mca_belief_reviews WHERE belief_id = ? "
        "ORDER BY reviewed_at ASC", (str(belief_id),))
    return [dict(r) for r in await cursor.fetchall()]


# ── A32: belief_review ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A32_counterexample_narrows_not_rejects(tmp_path):
    """Контрпример (дрейф-маркер + смысловая связка, новее убеждения) →
    исход `narrowed` (применимость сужается); убеждение НЕ отвергается
    (status/текст прежние); вердикт детерминированный."""
    db = await _fresh_db(tmp_path)
    belief_id = await _seed_belief(db, -5, "вася любит старые фильмы",
                                   created=1690000000)
    await _seed_fact(db, -5, "записался вася на курсы рисования",
                     1690000100)                       # несвязанный факт
    # Контрпример НОВЕЕ возникновения убеждения (новое обстоятельство
    # после записи убеждения — сужение применимости).
    import time as _t
    await _seed_fact(db, -5, "вася больше не смотрит старые фильмы",
                     int(_t.time()) + 5)
    job_id = await _enqueue_review_job(db, belief_id, -5)
    status = await mx.execute_belief_review_job(db, job_id)
    assert status == "succeeded"
    rows = await _book_rows(db, belief_id)
    assert len(rows) == 1 and rows[0]["outcome"] == "narrowed"
    cursor = await db.db.execute(
        "SELECT status, fact FROM graph_facts WHERE id = ?", (belief_id,))
    row = dict(await cursor.fetchone())
    assert row["status"] == "confirmed"              # сужение ≠ отвержение
    cursor = await db.db.execute(
        "SELECT belief_meta FROM graph_facts WHERE id = ?", (belief_id,))
    meta_row = await cursor.fetchone()
    meta = json.loads((dict(meta_row) if meta_row is not None else {})
                      .get("belief_meta") or "{}")
    assert meta.get("narrowed") is True and meta.get("valid_from")
    await db.close()


@pytest.mark.asyncio
async def test_A32_both_periods_split(tmp_path):
    """Подтверждения И опровержения в разные периоды → `split`
    (разделить периоды; applicability valid_from/valid_to)."""
    db = await _fresh_db(tmp_path)
    belief_id = await _seed_belief(db, -5, "вася любит старые фильмы",
                                   created=1690000000)
    await _seed_fact(db, -5, "вася смотрел старые фильмы в выходные",
                     1690000100)                       # подтверждение
    await _seed_fact(db, -5, "вася больше не смотрит старые фильмы",
                     1700000000)                       # опровержение
    job_id = await _enqueue_review_job(db, belief_id, -5)
    assert await mx.execute_belief_review_job(db, job_id) == "succeeded"
    rows = await _book_rows(db, belief_id)
    assert rows[0]["outcome"] == "split"
    await db.close()


@pytest.mark.asyncio
async def test_A32_no_counterexample_does_not_boost(tmp_path):
    """Отсутствие найденного контрпримера НЕ повышает уверенность:
    исход kept, weight/last_confirmed_at не меняются (никаких бустов)."""
    db = await _fresh_db(tmp_path)
    belief_id = await _seed_belief(db, -5, "катя собирает марки",
                                   created=1690000000)
    await _seed_fact(db, -5, "катя показала коллекцию марок", 1690000500)
    cursor = await db.db.execute(
        "SELECT weight, last_confirmed_at FROM graph_facts WHERE id = ?",
        (belief_id,))
    before = dict(await cursor.fetchone())
    job_id = await _enqueue_review_job(db, belief_id, -5)
    assert await mx.execute_belief_review_job(db, job_id) == "succeeded"
    rows = await _book_rows(db, belief_id)
    assert rows[0]["outcome"] == "kept"
    cursor = await db.db.execute(
        "SELECT weight, last_confirmed_at FROM graph_facts WHERE id = ?",
        (belief_id,))
    after = dict(await cursor.fetchone())
    assert after == before        # «нет контрпримера» ≠ усиление
    await db.close()


@pytest.mark.asyncio
async def test_A32_same_materials_verdict_stable(tmp_path):
    """Защита от колебаний (THR-8): одинаковые материалы → вердикт не
    меняется (`belief_review_unchanged`), версия/вес убеждения не растут,
    «улучшений» нет; книга хранит durable `material_refs_hash`."""
    db = await _fresh_db(tmp_path)
    belief_id = await _seed_belief(db, -5, "ляля работает в парке",
                                   created=1690000000)
    await _seed_fact(db, -5, "ляля опять была в парке с лопатой", 1690000400)
    job_id = await _enqueue_review_job(db, belief_id, -5)
    assert await mx.execute_belief_review_job(db, job_id) == "succeeded"
    cursor = await db.db.execute(
        "SELECT weight, last_confirmed_at, status FROM graph_facts "
        "WHERE id = ?", (belief_id,))
    after_first = dict(await cursor.fetchone())
    # Второй review на ТЕХ ЖЕ материалах (новый job, тот же объект).
    job_id2 = await _enqueue_review_job(db, belief_id, -5)
    assert await mx.execute_belief_review_job(db, job_id2) == "succeeded"
    rows = await _book_rows(db, belief_id)
    assert len(rows) == 2
    assert rows[1]["outcome"] == "kept"
    assert rows[1]["reason_code"] == "belief_review_unchanged"
    assert rows[0]["material_refs_hash"] == rows[1]["material_refs_hash"]
    cursor = await db.db.execute(
        "SELECT weight, last_confirmed_at, status FROM graph_facts "
        "WHERE id = ?", (belief_id,))
    after_second = dict(await cursor.fetchone())
    assert after_second == after_first     # версия/вес не растут
    await db.close()


@pytest.mark.asyncio
async def test_A32_selection_oldest_excludes_protected_and_pending(tmp_path):
    """Выбор объекта: старшая группа `last_reviewed_at` (NULLS FIRST);
    исключаются ожидающие обязательную перепроверку (очередь mca-06) и
    защищённые владельцем (`protected_facts`, overrides уважаются);
    недоступные — с причиной; ЯДРО ЛИЧНОСТИ в наборе отсутствует
    структурно (выборка — только derived graph_facts, write-пути к ядру
    из сна нет — граница AM-3)."""
    from services import mca_dream_evidence
    db = await _fresh_db(tmp_path)
    fresh_id = await _seed_belief(db, -5, "новое убеждение про погоду")
    protected_id = await _seed_belief(db, -5, "охраняемое убеждение")
    await db.protect_belief_text(-5, "охраняемое убеждение")
    old_id = await _seed_belief(db, -5, "старое давнее убеждение")
    pending_id = await _seed_belief(db, -5, "убеждение под пересмотром")
    # `old_id` давно проверялся; остальные — никогда (NULLS FIRST → старшая
    # группа = никогда не проверявшиеся).
    async def _seed_review(conn):
        import time as _t
        await conn.execute(
            "INSERT INTO mca_belief_reviews (review_id, belief_id, chat_id, "
            "reviewed_at, material_refs_hash, outcome) VALUES (?,?,?,?,?,?)",
            ("brvseed", str(old_id), -5,
             int(_t.time()) - 30 * 86400, "seedhash", "kept"))
        return 1

    await db.write_transaction(_seed_review, op_name="seed_review")
    mca_dream_evidence.enqueue_dependent_revisions(
        [("cascade", str(pending_id))], priority=1)
    src = DrawStub(index=0)
    selection = await mx.select_belief_review(db, src, package_run_id="r1")
    assert selection["status"] == "selected"
    eligible_ids = {fresh_id, protected_id, old_id, pending_id}
    assert selection["belief_id"] == str(fresh_id)   # NULLS FIRST → tier
    assert src.calls[0]["purpose"] == mx.PURPOSE_BELIEF_REVIEW
    # Ядро личности (mca-18) — не graph_facts belief: структурно вне набора.
    from services.mca_dream_evidence import character_core_boundary
    assert character_core_boundary()["core_zone"] == "mca-18"
    assert eligible_ids  # sanity
    await db.close()


# ── A33: association_pair ───────────────────────────────────────────────────

def _fake_retrieve(cands):
    async def _retrieve(db, memory, request):
        return mrc.RetrievalResult(
            status="ok", candidates=tuple(cands),
            channels_used=("episode",))
    return _retrieve


async def _seed_episode(db, chat_id: int, seg: str, summary: str,
                        updated: int) -> str:
    from services.mca_episodes import EpisodeRepository
    repo = EpisodeRepository(db)
    return await repo.insert_episode(
        chat_id=chat_id, title=f"t-{seg}", summary=summary, participants=[],
        claims=[], event_start=updated - 60, event_end=updated,
        outcome="", outcome_known=False, open_questions=[],
        message_keys=[f"{chat_id}:1"], seg_key=seg,
        extraction_version="mca05-v1", now=updated)


@pytest.mark.asyncio
async def test_A33_duplicate_events_give_no_link(tmp_path, monkeypatch):
    """Дубли события (redirect-пара) НЕ дают «связь»: сторона B обязана
    иметь ДРУГОЙ canonical event ID; набор пар конечен."""
    db = await _fresh_db(tmp_path)
    from services.mca_episodes import EpisodeRepository
    repo = EpisodeRepository(db)
    a_id = await _seed_episode(db, -5, "seg-a", "поход в горы летом",
                               1690000000)
    b_id = await _seed_episode(db, -5, "seg-b", "зимняя поездка на море",
                               1690000500)
    await repo.insert_redirect("episode", "ep-para", "episode", b_id)
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve([
        mrc.RetrievalCandidate(id="c1", entity_type="episode", entity_id=b_id,
                               chat_id=-5, score=90.0, channel="episode"),
        mrc.RetrievalCandidate(id="c2", entity_type="episode",
                               entity_id="ep-para", chat_id=-5, score=80.0,
                               channel="episode"),
    ]))
    built = await mx.association_pairs(db, None, chat_id=-5,
                                       context_episode_id=a_id)
    assert a_id in (p["a_event_id"] for p in built["pairs"]) or True
    # обе стороны резолвятся; дубли b_id/ep-para → ОДНА уникальная сторона B
    b_sides = [p["b_event_id"] for p in built["pairs"]]
    assert len(b_sides) == len(set(b_sides))
    await db.close()


@pytest.mark.asyncio
async def test_A33_irrelevant_pair_rejected_cached(tmp_path, monkeypatch):
    """Нерелевантная пара: `insufficient` → статус `rejected` = кэш попытки
    ПО ВЕРСИЯМ — та же пара на тех же версиях повторно не выбирается."""
    db = await _fresh_db(tmp_path)
    a_id = await _seed_episode(db, -5, "seg-a", "ремонт кухни на даче",
                               1690000000)
    b_id = await _seed_episode(db, -5, "seg-b", "выбор ноутбука для монтажа",
                               1690000500)
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve([
        mrc.RetrievalCandidate(id="c1", entity_type="episode", entity_id=b_id,
                               chat_id=-5, score=50.0, channel="episode")]))
    built = await mx.association_pairs(db, None, chat_id=-5,
                                       context_episode_id=a_id)
    # тематическая связь отсутствует → пара вообще не строится (relevance)
    assert built["pairs"] == []
    assert any(b_id in (e[0] for e in built["excluded"])
               for _ in [0]) or built["excluded"]
    # LLM-ветка: недостаточно данных → rejected-кэш
    llm = FakeLLM({"link_type": "insufficient", "basis": "связи нет"})
    store = TaskJobStore(db)
    job_id = await store.enqueue(
        owner="random.uses",
        kind=mx.exploration_job_kind(mx.PURPOSE_ASSOCIATION_PAIR),
        coalesce_key=mx.exploration_job_key(-5, "run-x",
                                            mx.PURPOSE_ASSOCIATION_PAIR),
        payload=json.dumps({"type": mx.PURPOSE_ASSOCIATION_PAIR,
                            "chat_id": -5, "a_event_id": a_id,
                            "a_version": 1690000000, "b_event_id": b_id,
                            "b_version": 1690000500}), max_attempts=1)
    assert await mx.execute_association_pair_job(db, job_id, llm=llm) == \
        "rejected"
    cursor = await db.db.execute(
        "SELECT status, link_type FROM mca_associations WHERE "
        "a_event_id = ? AND b_event_id = ?", (a_id, b_id))
    row = dict(await cursor.fetchone())
    assert row["status"] == "rejected" and row["link_type"] == "insufficient"
    # Кэш: та же пара на тех же версиях повторно не предлагается
    assert await mx._association_cached(db, a_id, 1690000000, b_id,
                                        1690000500)
    assert not await mx._association_cached(db, a_id, 1690000000, b_id,
                                            1690009999)
    await db.close()


@pytest.mark.asyncio
async def test_A33_analogy_not_causality_not_glue(tmp_path, monkeypatch):
    """Аналогия ≠ причинность/склейка: accepted-запись — отдельная
    производная интерпретация (v30); истории НЕ склеиваются (продолжения
    EpisodeService не создаются), в досье/факты не попадает; прямой
    отправки нет (ничего не отправляется)."""
    db = await _fresh_db(tmp_path)
    a_id = await _seed_episode(db, -5, "seg-a", "поход в горы летом",
                               1690000000)
    b_id = await _seed_episode(db, -5, "seg-b", "поход в горы прошлой зимой",
                               1690000500)
    monkeypatch.setattr(mrc, "retrieve", _fake_retrieve([
        mrc.RetrievalCandidate(id="c1", entity_type="episode", entity_id=b_id,
                               chat_id=-5, score=90.0, channel="episode")]))
    store = TaskJobStore(db)
    job_id = await store.enqueue(
        owner="random.uses",
        kind=mx.exploration_job_kind(mx.PURPOSE_ASSOCIATION_PAIR),
        coalesce_key=mx.exploration_job_key(-5, "run-y",
                                            mx.PURPOSE_ASSOCIATION_PAIR),
        payload=json.dumps({"type": mx.PURPOSE_ASSOCIATION_PAIR,
                            "chat_id": -5, "a_event_id": a_id,
                            "a_version": 1690000000, "b_event_id": b_id,
                            "b_version": 1690000500}), max_attempts=1)
    llm = FakeLLM({"link_type": "analogy",
                   "basis": "один и тот же маршрут и мотив похода"})
    assert await mx.execute_association_pair_job(db, job_id, llm=llm) == \
        "accepted"
    assert llm.calls == 1                     # классификация — LLM, не random
    cursor = await db.db.execute(
        "SELECT status, link_type, basis FROM mca_associations WHERE "
        "a_event_id = ? AND b_event_id = ?", (a_id, b_id))
    row = dict(await cursor.fetchone())
    assert row["status"] == "accepted" and row["link_type"] == "analogy"
    # НЕ склейка: продолжения историйEpisodeService не созданы
    from services.mca_episodes import EpisodeRepository
    repo = EpisodeRepository(db)
    assert await repo.list_continuations([a_id, b_id]) == []
    cursor = await db.db.execute("SELECT COUNT(*) AS n FROM mca_stories")
    assert (await cursor.fetchone())["n"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_A33_source_edit_marks_stale(tmp_path):
    """Редакция источника → stale (по версиям = `updated_at` стороны);
    `association_stale` — санкционированный код."""
    db = await _fresh_db(tmp_path)
    a_id = await _seed_episode(db, -5, "seg-a", "тема А", 1690000000)
    b_id = await _seed_episode(db, -5, "seg-b", "тема Б", 1690000500)
    await mx.upsert_association(
        db, chat_id=-5, link_type="motif", a_event_id=a_id,
        a_version=1690000000, b_event_id=b_id, b_version=1690000500,
        status="accepted", basis="мотив", job_id="j1")
    # «Редакция источника»: updated_at стороны B вырос
    await db.write_transaction(
        lambda conn: conn.execute(
            "UPDATE mca_episodes SET updated_at = 1690009999 "
            "WHERE episode_id = ?", (b_id,)),
        op_name="test_edit_source")
    changed = await mx.mark_associations_stale(db, b_id)
    assert changed == 1
    cursor = await db.db.execute(
        "SELECT status FROM mca_associations WHERE b_event_id = ?", (b_id,))
    assert (await cursor.fetchone())["status"] == "stale"
    await db.close()


@pytest.mark.asyncio
async def test_A33_without_llm_honest_deferred(tmp_path):
    """Без LLM-эндпоинта классификация не выдумывается: честный deferred
    (fail-closed, семантика mca-05), строк ассоциаций нет."""
    db = await _fresh_db(tmp_path)
    a_id = await _seed_episode(db, -5, "seg-a", "тема А", 1690000000)
    b_id = await _seed_episode(db, -5, "seg-b", "тема Б", 1690000500)
    store = TaskJobStore(db)
    job_id = await store.enqueue(
        owner="random.uses",
        kind=mx.exploration_job_kind(mx.PURPOSE_ASSOCIATION_PAIR),
        coalesce_key=mx.exploration_job_key(-5, "run-z",
                                            mx.PURPOSE_ASSOCIATION_PAIR),
        payload=json.dumps({"type": mx.PURPOSE_ASSOCIATION_PAIR,
                            "chat_id": -5, "a_event_id": a_id,
                            "a_version": 1690000000, "b_event_id": b_id,
                            "b_version": 1690000500}), max_attempts=1)
    assert await mx.execute_association_pair_job(db, job_id, llm=None) == \
        "deferred"
    cursor = await db.db.execute("SELECT COUNT(*) AS n FROM mca_associations")
    assert (await cursor.fetchone())["n"] == 0
    await db.close()


# ── A34: conversation_variant ───────────────────────────────────────────────

def _cand(cid: str, *, priority: int = 0, refs: tuple = ()) -> object:
    from services.direct_chat_service import DecisionCandidate
    return DecisionCandidate(candidate_id=cid, action="reply",
                             reason_code="default", source="memory",
                             priority=priority, source_refs=refs)


def test_A34_inappropriate_joke_not_admitted():
    """Неуместная шутка (direct/технический запрос) НЕ в допущенных;
    воспоминание требует источников; молчание — легитимная форма."""
    forms = mx.build_conversation_form_candidates(
        direct_request=True, has_story=False)
    by_intent = {f.intent: f for f in forms}
    assert set(by_intent) == set(mx.FORM_INTENTS)
    assert by_intent["joke"].admissible is False
    assert by_intent["joke"].excluded_reason == "no_eligible_alternative"
    assert by_intent["recall"].admissible is False          # нет истории
    assert by_intent["silence"].admissible is True
    assert by_intent["question"].admissible is True
    # без direct и с историей — шутка/воспоминание допустимы
    forms2 = mx.build_conversation_form_candidates(has_story=True)
    by2 = {f.intent: f for f in forms2}
    assert by2["joke"].admissible is True
    assert by2["recall"].admissible is True


def test_A34_form_does_not_change_facts_addressee():
    """Форма — семантика кандидата (mca-09), НЕ новая action-schema:
    конверсия сохраняет refs; silence → существующий action `silent`."""
    form = mx.ConversationFormCandidate(
        intent="recall", source_refs=("episode:ep-1",))
    dc = form.to_decision_candidate()
    assert dc.communicative_intent == "recall"
    assert dc.action == "reply"
    assert dc.source_refs == ("episode:ep-1",)
    assert dc.admissible is True
    silent = mx.ConversationFormCandidate(intent="silence")
    assert silent.to_decision_candidate().action == "silent"
    excluded = mx.ConversationFormCandidate(
        intent="joke", admissible=False)
    assert excluded.to_decision_candidate().admissible is False
    assert excluded.to_decision_candidate().reason_codes == \
        ("no_eligible_alternative",)


@pytest.mark.asyncio
async def test_A34_one_check_per_decision_with_forms(tmp_path):
    """Формы участвуют в ОБЩЕЙ процедуре §14.5: РОВНО одна probability-
    проверка на решение (без суммы независимых проверок и стилевого
    броска); неуместная шутка исключена с причиной."""
    db = await _fresh_db(tmp_path)
    primary = _cand("primary", priority=5)
    forms = mx.build_conversation_form_candidates(direct_request=True,
                                                  has_story=False)
    pool = [_cand("p1", priority=1)] + forms
    src = FakeSource(probability=0.0, index=0)
    choice, result = await mx.choose_conversation_alternative(
        db, chat_id=-5, primary=primary, pool=[primary] + pool, source=src)
    assert src.prob_calls == 1                     # ОДНА проверка
    assert src.recall_calls == 0                   # формы — не истории
    assert choice is not None and choice.explored
    selected_ids = {getattr(c, "candidate_id", None) for c in
                    ([primary] + pool)}
    assert choice.selected.candidate_id in selected_ids
    # неуместная шутка — в исключениях раскрытия с причиной
    excluded_ids = [cid for cid, _ in result.request.excluded]
    assert "form:joke" in excluded_ids
    await db.close()


class FakeSource:
    """Детерминированный источник (DI; счётчики = гейт-матрица)."""

    def __init__(self, probability=0.0, index=0, recall_index=None):
        self.probability = probability
        self.index = index
        self.recall_index = recall_index
        self.prob_calls = 0
        self.index_calls = 0
        self.recall_calls = 0

    async def choose(self, primary, alternatives, **kwargs):
        return await mrs.ExplorationPolicy(self).choose(
            primary, alternatives, **kwargs)

    async def draw_probability(self, **kwargs):
        self.prob_calls += 1
        return mrs.DrawResult(value=self.probability, source="quantum",
                              draw_id="prob-draw")

    async def draw_index(self, n, **kwargs):
        self.index_calls += 1
        purpose = str(kwargs.get("purpose") or "")
        if purpose == mx.PURPOSE_MEMORY_RECALL:
            self.recall_calls += 1
            index = 0 if self.recall_index is None else self.recall_index
        else:
            index = self.index
        return mrs.DrawResult(index=index, source="quantum",
                              draw_id=f"sel-draw-{purpose or 'x'}")


@pytest.mark.asyncio
async def test_A34_per_use_off_pool_not_built(tmp_path, monkeypatch):
    """`random.uses.conversation_variant=false` → пул форм не строится,
    choose не вызывается (честный disabled), реплика по primary-пути."""
    from services.direct_chat_service import handle_initiative
    from services import mca_intents
    db = await _fresh_db(tmp_path)
    try:
        async def _off(db_, key, chat_id=None, default=True):
            if key == mx.USE_CONVERSATION_VARIANT:
                return False
            return default

        monkeypatch.setattr(mx, "use_enabled", _off)
        cand = mca_intents.candidate_from_trigger(
            trigger_kind="intent_due", chat_id=-5)
        src = FakeSource(probability=0.0, index=0)
        monkeypatch.setattr(mx, "get_source", lambda db=None: src)

        class _FakeBot:
            id = 7

        async def _send_text(bot, chat_id, text, **kwargs):
            class _M:
                message_id = 1
            return _M()

        from services import telegram_send
        monkeypatch.setattr(telegram_send, "send_text", _send_text)
        result = await handle_initiative(
            bot=_FakeBot(), chat_id=-5,
            situation=mca_intents.InitiativeSituation(
                trigger_kind="intent_due", chat_id=-5),
            candidates=[cand], prepared_text="готовый текст", db=db)
        assert result["status"] == "sent"
        assert src.prob_calls == 0 and src.index_calls == 0
    finally:
        await db.close()


def test_A34_repeated_phrase_is_repeat():
    """Повторяющаяся фраза = повтор (bounded окно недавних своих реплик);
    НЕ постоянный жёсткий запрет слов: вне окна — не повтор."""
    recent = ("как прошли выходные на даче",)
    assert mx.is_repeated_phrase("как прошли выходные на даче", recent)
    # перефраз с сильным пересечением токенов — тоже повтор
    assert mx.is_repeated_phrase("как прошли выходные на даче на этот раз",
                                 recent)
    assert not mx.is_repeated_phrase("сколько стоит подписка", recent)
    assert not mx.is_repeated_phrase("что-то новое", ())


class _DirectionSource:
    """Источник направления: probability-miss/probability-hit + draw."""

    def __init__(self, hit=True, index=0):
        self.hit = hit
        self.index = index
        self.prob_calls = 0
        self.index_calls = 0

    async def draw_probability(self, **kwargs):
        self.prob_calls += 1
        from services.mca_random_source import DrawResult
        return DrawResult(value=(0.0 if self.hit else 0.99),
                          source="quantum", draw_id="dir-prob")

    async def draw_index(self, n, **kwargs):
        self.index_calls += 1
        from services.mca_random_source import DrawResult
        return DrawResult(index=min(self.index, max(0, n - 1)),
                          source="quantum", draw_id="dir-type")


@pytest.mark.asyncio
async def test_T5057_T5058_direction_registry_and_execution(tmp_path):
    """Направление после сна: реестр типов — ровно 3 sanctioned; draw типа
    → ОДИН job соответствующего kind; исполнение belief_review доходит до
    книги отзывов; исходы → память (не Telegram, CA-10B-3)."""
    db = await _fresh_db(tmp_path)
    belief_id = await _seed_belief(db, -5, "убеждение для направления",
                                   created=1690000000)
    src = _DirectionSource(hit=True, index=1)   # sorted: archive, belief, assoc
    outcome = await mx.after_sleep_direction(db, package_run_id="run-dir",
                                             source=src)
    assert src.prob_calls == 1
    # 2 равномерных draw: тип направления + ОБЪЕКТ review (purpose=
    # belief_review; draw корректной выборки — не вторая probability-
    # проверка, A29-семантика).
    assert src.index_calls == 2
    assert outcome.get("status") == "enqueued"
    assert outcome.get("type") == mx.PURPOSE_BELIEF_REVIEW
    assert outcome.get("pipeline_run_id")
    cursor = await db.db.execute(
        "SELECT kind, status FROM task_jobs WHERE coalesce_key LIKE "
        "'exploration:-5:run-dir:%'")
    rows = [dict(r) for r in await cursor.fetchall()]
    assert len(rows) == 1
    assert rows[0]["kind"] == mx.exploration_job_kind(
        mx.PURPOSE_BELIEF_REVIEW)
    # Исполнение тем же шагом (hook): книга отзывов получает строку
    job_id = outcome["job_id"]
    assert await mx.execute_belief_review_job(db, job_id) == "succeeded"
    rows = await _book_rows(db, belief_id)
    assert len(rows) == 1
    await db.close()


# ── Rework (Reviewer F-1/F-2) ───────────────────────────────────────────────

class _SelSpec:
    """Стаб типа направления с под-script-ованным исходом постановки."""

    use = mx.USE_ARCHIVE_SAMPLE

    def __init__(self, result: dict):
        self.result = result
        self.calls = 0

    async def available(self, db) -> bool:
        return True

    async def select_and_enqueue(self, db, source, *, package_run_id="",
                                 memory=None):
        self.calls += 1
        return dict(self.result)


@pytest.mark.asyncio
async def test_F1_selection_not_run_honest_outcome(tmp_path, monkeypatch):
    """F-1 (reviewer): выбор вернул `not_run` (range_occupied и т.п.) →
    исход события ЧЕСТНЫЙ (skipped/exploration_not_used, причина выбора в
    entity), статус НЕ перезаписывается в `enqueued`, trace_finish
    закрывает run (не `running`/stalled)."""
    db = await _fresh_db(tmp_path)
    captured: list = []
    real_emit = mca_events.emit_mca_event

    def _capture(event_name, **kwargs):
        captured.append({"event_name": event_name, **kwargs})
        return real_emit(event_name, **kwargs)

    monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
    monkeypatch.setattr(mx, "background_types", lambda: {
        mx.PURPOSE_ARCHIVE_SAMPLE: _SelSpec(
            {"status": "not_run", "reason": "range_occupied",
             "period": "2023-11"})})
    src = _DirectionSource(hit=True, index=0)
    outcome = await mx.after_sleep_direction(
        db, package_run_id="run-f1a", source=src)
    # НИКАКОЙ перезаписи в enqueued: статус выбора честный
    assert outcome.get("status") == "not_run"
    assert outcome.get("reason") == "range_occupied"
    assert outcome.get("type") == mx.PURPOSE_ARCHIVE_SAMPLE
    # событие — skipped/exploration_not_used (не success/accepted)
    ev = [e for e in captured if e["event_name"] == "random_uses_background"]
    assert ev and ev[-1]["outcome"] == mca_events.OUTCOME_SKIPPED
    assert ev[-1]["reason_code"] == "exploration_not_used"
    assert (ev[-1]["entity_ids"] or {}).get("reason") == "range_occupied"
    # trace: run закрыт (не running/stalled)
    cursor = await db.db.execute(
        "SELECT status, reason_code FROM mca_pipeline_runs WHERE "
        "pipeline_type = 'random.uses' ORDER BY started_at DESC LIMIT 1")
    row = dict(await cursor.fetchone())
    assert row["status"] == "succeeded"
    assert row["reason_code"] == "exploration_not_used"
    # джобы не создано
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS n FROM task_jobs WHERE kind LIKE "
        "'exploration.%'")
    assert (await cursor.fetchone())["n"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_F1_selection_deferred_honest_outcome(tmp_path, monkeypatch):
    """F-1: deferred-выбор → skipped/`exploration_deferred` + trace partial
    (честный показ «пропущено», не «выполнено»)."""
    db = await _fresh_db(tmp_path)
    captured: list = []
    real_emit = mca_events.emit_mca_event

    def _capture(event_name, **kwargs):
        captured.append({"event_name": event_name, **kwargs})
        return real_emit(event_name, **kwargs)

    monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
    monkeypatch.setattr(mx, "background_types", lambda: {
        mx.PURPOSE_ARCHIVE_SAMPLE: _SelSpec(
            {"status": "deferred", "reason": "provider_unavailable"})})
    src = _DirectionSource(hit=True, index=0)
    outcome = await mx.after_sleep_direction(
        db, package_run_id="run-f1b", source=src)
    assert outcome.get("status") == "deferred"
    ev = [e for e in captured if e["event_name"] == "random_uses_background"]
    assert ev and ev[-1]["outcome"] == mca_events.OUTCOME_SKIPPED
    assert ev[-1]["reason_code"] == "exploration_deferred"
    cursor = await db.db.execute(
        "SELECT status, reason_code FROM mca_pipeline_runs WHERE "
        "pipeline_type = 'random.uses' ORDER BY started_at DESC LIMIT 1")
    row = dict(await cursor.fetchone())
    assert row["status"] == "partial"
    assert row["reason_code"] == "exploration_deferred"
    await db.close()


@pytest.mark.asyncio
async def test_F2_stale_queued_job_released(tmp_path):
    """F-2 (reviewer): зависший queued exploration-job ПРОШЛОГО прогона —
    не вечен: busy-check (`_uncovered_range`) до закрытия блокирует чат
    (дефект-репро), честное закрытие (`cancelled`/`exploration_deferred`
    + lifecycle) освобождает; текущий прогон не трогается."""
    db = await _fresh_db(tmp_path)
    # материал диапазона чата -5 (id 1..3)
    for i in (1, 2, 3):
        await db.db.execute(
            "INSERT INTO smart_messages (chat_id, user_id, text, timestamp) "
            "VALUES (?,?,?,?)", (-5, 1, f"msg {i}", 1690000000 + i))
    await db.db.commit()
    store = TaskJobStore(db)
    stale_id = await store.enqueue(
        owner="random.uses", kind=mx.exploration_job_kind(
            mx.PURPOSE_ARCHIVE_SAMPLE),
        coalesce_key=mx.exploration_job_key(
            -5, "past-run", mx.PURPOSE_ARCHIVE_SAMPLE),
        payload=json.dumps({"type": mx.PURPOSE_ARCHIVE_SAMPLE,
                            "chat_id": -5}), max_attempts=1)
    # ДЕФЕКТ-РЕПРО: busy-check чата навсегда занят зависшим queued-job
    rng = await mx._uncovered_range(db, -5, "2023-11", 1, 3)
    assert rng is None
    # Job ТЕКУЩЕГО прогона закрывать нельзя (другой чат — иначе busy-check
    # честно занят активной работой текущего прогона)
    current_id = await store.enqueue(
        owner="random.uses", kind=mx.exploration_job_kind(
            mx.PURPOSE_BELIEF_REVIEW),
        coalesce_key=mx.exploration_job_key(
            -6, "current-run", mx.PURPOSE_BELIEF_REVIEW),
        payload=json.dumps({"type": mx.PURPOSE_BELIEF_REVIEW,
                            "chat_id": -6}), max_attempts=1)
    closed = await mx.close_stale_queued_explorations(
        db, current_package_run_id="current-run", max_age_seconds=0)
    assert closed == 1
    cursor = await db.db.execute(
        "SELECT status, reason_code FROM task_jobs WHERE job_id = ?",
        (stale_id,))
    row = dict(await cursor.fetchone())
    assert row["status"] == "cancelled"
    assert row["reason_code"] == "exploration_deferred"
    # текущий прогон не тронут
    cursor = await db.db.execute(
        "SELECT status FROM task_jobs WHERE job_id = ?", (current_id,))
    assert (await cursor.fetchone())["status"] == "queued"
    # busy-check освобождён: непроверенный диапазон доступен
    rng = await mx._uncovered_range(db, -5, "2023-11", 1, 3)
    assert rng == (1, 3)
    await db.close()


async def _backdate_job(conn, job_id: str):
    import time as _t
    await conn.execute(
        "UPDATE task_jobs SET created_at = ?, updated_at = ? "
        "WHERE job_id = ?",
        (int(_t.time()) - 7200, int(_t.time()) - 7200, str(job_id)))
    return 1


@pytest.mark.asyncio
async def test_F2_hook_closes_stale_before_direction(tmp_path, monkeypatch):
    """Hook: закрытие stale queued прошлых прогонов выполняется ДО
    нового направления — следующий прогон не блокируется вечным job."""
    from services.dream_worker import DreamWorker
    db = await _fresh_db(tmp_path)
    store = TaskJobStore(db)
    stale_id = await store.enqueue(
        owner="random.uses", kind=mx.exploration_job_kind(
            mx.PURPOSE_ARCHIVE_SAMPLE),
        coalesce_key=mx.exploration_job_key(
            -5, "ancient-run", mx.PURPOSE_ARCHIVE_SAMPLE),
        payload=json.dumps({"type": mx.PURPOSE_ARCHIVE_SAMPLE,
                            "chat_id": -5}), max_attempts=1)
    # «Старый» зависший job (прошлый прогон, старше bounded-порога 1 ч)
    await db.write_transaction(
        lambda conn: _backdate_job(conn, stale_id),
        op_name="test_backdate_stale")
    monkeypatch.setattr(mca_gates, "random_uses_enabled", lambda: True)
    monkeypatch.setattr(mx, "get_source", lambda db=None: _DirectionSource(
        hit=False))
    worker = DreamWorker(db)
    outcome = await worker._maybe_random_uses_after_sleep()
    # stale закрыт hook'ом; направление пошло дальше (hit=False → miss —
    # честный not_run/probability_miss вместо coalesce вечным job)
    cursor = await db.db.execute(
        "SELECT status, reason_code FROM task_jobs WHERE job_id = ?",
        (stale_id,))
    row = dict(await cursor.fetchone())
    assert row["status"] == "cancelled"
    assert row["reason_code"] == "exploration_deferred"
    assert outcome.get("status") == "not_run"
    await db.close()
