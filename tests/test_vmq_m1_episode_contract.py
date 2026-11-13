"""VMQ-M1 — эпизоды/периоды: контракт M-01..M-03 (R17: только коды/числа).

TEST-LIFECYCLE: CONTRACT.
Контракт: plans/features/vmq-onto-01/architecture-m1-episodes.md
(разделы «Episode/period», «Rebuild, IDs, revisions», «Проверки и
acceptance M-01..M-03»).

Проверяется на temp-БД (production не затрагивается):
  * M-01 — границы: reply внутри горизонта склеивает, вне горизонта нет;
    gap/параллельные участники разделяют; overlap порции не дублирует;
    неизвестное время даёт partial/unknown; строгий chat scope; ordered
    source refs/event time/участники — из исходных строк.
  * M-02 — multi-year: независимые эпизоды, календарные периоды с честными
    пропусками, независимая опора (повтор мема её не повышает),
    counterexample отдельно, дата обнаружения не подменяет время события.
  * M-03 — incremental vs bounded rebuild дают одну projection на одном
    наборе source revisions; повтор идемпотентен без переезда IDs;
    revision после recheck стабильна; удалённый источник не выдаётся за
    проверенный; watermark не перепрыгивает незавершённую порцию; ручной
    override не затирается; старый rebuild-окно дедуплицируется и при
    >500 эпизодов чата.
  * Нет массового reembedding (spy + static), нет DDL (Δ user_version = 0),
    нет тел сообщений/секретов в логах, работа bounded, деградация честная.
"""
import inspect
import json

import pytest

from services import mca_gates
from services.database import DatabaseService
from services.mca_episode_jobs import (
    EpisodesBackfillRunner,
    RecheckAssemblyError,
    enqueue_episodes_backfill,
)
from services.mca_episodes import (
    CONTENT_READY,
    EPISODE_VIEW_LIMIT_MAX,
    EXTRACTOR_VERSION,
    LONGITUDINAL_VIEW_VERSION,
    EpisodeRepository,
    EpisodeService,
    SOURCE_INTEGRITY_MISSING,
    SOURCE_INTEGRITY_OK,
    SOURCE_INTEGRITY_PARTIAL,
    SOURCE_INTEGRITY_UNKNOWN,
    VIEW_STATE_EMPTY,
    VIEW_STATE_OK,
    VIEW_STATE_UNAVAILABLE,
    effective_story,
    episode_source_fingerprint,
    get_episode_view,
    list_episode_views,
    list_stories_for_retrieval,
    message_key,
    period_year,
    queue_source_recheck,
    subject_longitudinal_view,
)

CHAT = -777001
CHAT2 = -777002
NOW = 1790000000                 # «сегодня» тестов (2026-09)
T2021 = 1623758400               # 2021-06-15 12:00 UTC
T2023 = 1686820800               # 2023-06-15 12:00 UTC
T2022 = 1650000000               # 2022-04-15
HOUR = 3600


def _msg(chat, tg, user, text, ts, reply_to_tg=None, db_id=None):
    return {"chat_id": chat, "id": db_id, "tg_message_id": tg,
            "user_id": user, "text": text, "timestamp": ts,
            "reply_to_tg_message_id": reply_to_tg}


async def _db():
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _add_msg(db, msg) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, 'text', '', ?)",
        (msg["user_id"], msg["chat_id"], msg["text"],
         msg["reply_to_tg_message_id"], msg["timestamp"],
         msg["tg_message_id"]))
    await db.db.commit()
    return int(cursor.lastrowid)


async def _count(db, sql, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _fixture(messages) -> DatabaseService:
    db = await _db()
    for msg in messages:
        await _add_msg(db, msg)
    return db


async def _user_version(db) -> int:
    cursor = await db.db.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


def _extract(title="Эпизод", summary="Краткое описание", participants=("2",)):
    return json.dumps({
        "title": title, "summary": summary,
        "participants": list(participants),
        "claims": [{"text": "Утверждение с источником", "refs": []}],
        "outcome_known": False, "outcome": None,
        "open_questions": [], "unknown": [], "multi_topic": False,
    }, ensure_ascii=False)


class _FakeLLM:
    def __init__(self, answers=None, default=None):
        self.answers = list(answers or [])
        self.default = default
        self.calls: list = []

    async def generate(self, messages, *, temperature=0.0, chat_id=None):
        self.calls.append(messages)
        if self.answers:
            return self.answers.pop(0)
        if self.default is not None:
            return self.default
        raise RuntimeError("no scripted answer")


def _fingerprint_tuple(view):
    return (view.source_refs, view.event_start_ts, view.event_end_ts,
            view.participants, view.source_fingerprint, view.content_status)


# ═══ M-01: границы эпизодов, source refs, chat scope ════════════════════════

class TestM01Boundaries:
    @pytest.mark.asyncio
    async def test_reply_thread_merges_and_orders_source_refs(self):
        msgs = [_msg(CHAT, 1, 11, "Обсудили план деплоя на неделю", T2021),
                _msg(CHAT, 2, 12, "Согласен с планом деплоя", T2021 + 300,
                     reply_to_tg=1),
                _msg(CHAT, 3, 11, "Тогда начинаю в среду утром", T2021 + 900,
                     reply_to_tg=2)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            views = await list_episode_views(db, CHAT)
            assert len(views) == 1
            view = views[0]
            assert view.chat_id == CHAT
            assert view.source_refs == (f"{CHAT}:tg:1", f"{CHAT}:tg:2",
                                        f"{CHAT}:tg:3")
            assert view.event_start_ts == T2021
            assert view.event_end_ts == T2021 + 900
            assert view.event_period_known is True
            assert view.participants == ("11", "12")
            assert view.source_integrity == SOURCE_INTEGRITY_OK
            assert view.content_status == CONTENT_READY
            assert view.projection_complete is True
            assert view.discovered_at == NOW      # две даты не смешаны
            assert view.derived_version
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_time_gap_splits_episode(self):
        msgs = [_msg(CHAT, 1, 11, "Первая короткая тема разговора", T2021),
                _msg(CHAT, 2, 11, "Вторая спустя два часа тема", T2021 + 7200)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            views = await list_episode_views(db, CHAT)
            assert len(views) == 2
            assert {v.source_refs for v in views} == {
                (f"{CHAT}:tg:1",), (f"{CHAT}:tg:2",)}
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_reply_outside_horizon_does_not_glue(self):
        msgs = [_msg(CHAT, 1, 11, "Начало старой темы про поездку", T2021),
                _msg(CHAT, 2, 12, "Ответ через неделю про поездку",
                     T2021 + 7 * 86400, reply_to_tg=1)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            assert len(await list_episode_views(db, CHAT)) == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_parallel_conversations_not_merged(self):
        msgs = [_msg(CHAT, 1, 7, "Обсуждаем проект альфа детали", T2021),
                _msg(CHAT, 2, 7, "Проект альфа продолжение", T2021 + 60),
                _msg(CHAT, 3, 9, "А теперь про котов и усы", T2021 + 700),
                _msg(CHAT, 4, 9, "Коты и усы продолжение", T2021 + 760)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            views = await list_episode_views(db, CHAT)
            assert len(views) == 2
            assert {v.participants for v in views} == {("7",), ("9",)}
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_overlap_batch_no_duplicate_and_stable_fingerprint(self):
        msgs = [_msg(CHAT, 1, 11, "Первое сообщение про деплой", T2021),
                _msg(CHAT, 2, 11, "Второе сообщение про деплой", T2021 + 60)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            first = await list_episode_views(db, CHAT)
            await svc.process_batch(CHAT, list(reversed(msgs)))
            second = await list_episode_views(db, CHAT)
            assert len(first) == len(second) == 1
            assert first[0].episode_ref == second[0].episode_ref
            assert first[0].source_fingerprint == second[0].source_fingerprint
            assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_unknown_timestamp_is_partial_unknown_not_invented(self):
        msgs = [_msg(CHAT, 1, 11, "Сообщение без времени источника", 0)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            views = await list_episode_views(db, CHAT)
            assert len(views) == 1
            view = views[0]
            assert view.event_start_ts is None
            assert view.event_end_ts is None
            assert view.event_period_known is False
            assert view.projection_complete is False
            assert view.discovered_at == NOW      # не подменяет дату события
            lon = await subject_longitudinal_view(db, CHAT)
            assert lon.unknown_time_episode_refs == (view.episode_ref,)
            assert lon.coverage["present_periods"] == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_chat_scope_is_strict(self):
        msgs_a = [_msg(CHAT, 5, 11, "Разговор первого чата про дело", T2021)]
        msgs_b = [_msg(CHAT2, 5, 12, "Разговор второго чата про дело", T2021)]
        db = await _fixture(msgs_a + msgs_b)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs_a)
            await svc.process_batch(CHAT2, msgs_b)
            views_a = await list_episode_views(db, CHAT)
            views_b = await list_episode_views(db, CHAT2)
            assert len(views_a) == len(views_b) == 1
            assert views_a[0].source_refs == (f"{CHAT}:tg:5",)
            assert views_b[0].source_refs == (f"{CHAT2}:tg:5",)
            assert views_a[0].participants == ("11",)
            assert views_b[0].participants == ("12",)
            # Карточка чужого чата недоступна (не зависит от роутера).
            assert await get_episode_view(
                db, CHAT2, views_a[0].episode_ref) is None
            assert await get_episode_view(
                db, CHAT, views_a[0].episode_ref) is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_reply_to_unknown_parent_does_not_glue(self):
        msgs = [_msg(CHAT, 1, 11, "Сообщение с битым reply-родителем", T2021,
                     reply_to_tg=999),
                _msg(CHAT, 2, 12, "Другое сообщение с битым reply",
                     T2021 + 1200, reply_to_tg=998)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            views = await list_episode_views(db, CHAT)
            assert len(views) == 2      # нет выдуманной склейки
            assert all(v.source_integrity == SOURCE_INTEGRITY_OK
                       for v in views)
        finally:
            await db.close()


# ═══ M-02: периоды/coverage/опоры ════════════════════════════════════════════

class TestM02PeriodsCoverage:
    @pytest.mark.asyncio
    async def test_multi_year_episodes_independent_with_honest_gap(self):
        msgs = [_msg(CHAT, 1, 11, "Событие двадцать первого года", T2021),
                _msg(CHAT, 2, 11, "Событие двадцать третьего года", T2023)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            views = await list_episode_views(db, CHAT)
            assert len(views) == 2
            lon = await subject_longitudinal_view(db, CHAT)
            assert lon.state == VIEW_STATE_OK
            assert lon.derived_version == LONGITUDINAL_VIEW_VERSION
            present = [b["period"] for b in lon.coverage["present_periods"]]
            assert present == ["2021", "2023"]
            assert lon.coverage["missing_periods"] == ["2022"]
            assert lon.coverage["complete"] is False
            assert lon.coverage["earliest_ts"] == T2021
            assert lon.coverage["latest_ts"] == T2023
            assert "missing_period_means_no_episode_not_no_event" in lon.notes
            assert len(lon.episode_refs) == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_repeated_meme_does_not_increase_independent_support(self):
        text = "Договорились встретиться в парке"
        msgs = [_msg(CHAT, 1, 11, text, T2021),
                _msg(CHAT, 2, 11, text, T2021 + 60)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            lon = await subject_longitudinal_view(db, CHAT)
            assert lon.independent_support_count == 1
            assert len(lon.support_source_refs) == 1
            assert lon.repeated_claims == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_counterexample_kept_apart_from_support(self):
        msgs = [_msg(CHAT, 1, 11, "Встретились в парке как договаривались",
                     T2021),
                _msg(CHAT, 2, 11, "Не встречались в парке как договаривались",
                     T2023)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            lon = await subject_longitudinal_view(db, CHAT)
            assert len(lon.episode_refs) == 2
            assert lon.counterexample_pairs
            pair = lon.counterexample_pairs[0]
            refs = set(pair["left_refs"]) | set(pair["right_refs"])
            assert refs == set(lon.episode_refs)
            assert pair["left_text"] != pair["right_text"]
            # Повтор не повышает независимость: обе формулировки различимы.
            assert lon.repeated_claims == 0
            assert lon.independent_support_count == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_old_event_not_dated_by_discovery(self):
        msgs = [_msg(CHAT, 1, 11, "Давнее событие в апреле", T2022)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            view = (await list_episode_views(db, CHAT))[0]
            assert period_year(view.event_start_ts) == 2022
            assert view.discovered_at == NOW
            lon = await subject_longitudinal_view(db, CHAT)
            assert [b["period"]
                    for b in lon.coverage["present_periods"]] == ["2022"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_subject_filter_isolated(self):
        msgs = [_msg(CHAT, 1, 11, "Первый участник о своём деле", T2021),
                _msg(CHAT, 2, 12, "Второй участник о своём деле", T2023)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            first = await subject_longitudinal_view(db, CHAT, subject_id="11")
            second = await subject_longitudinal_view(db, CHAT, subject_id="12")
            assert len(first.episode_refs) == 1
            assert len(second.episode_refs) == 1
            assert first.episode_refs != second.episode_refs
            absent = await subject_longitudinal_view(
                db, CHAT, subject_id="999")
            assert absent.state == VIEW_STATE_EMPTY
            assert absent.episode_refs == ()
            assert "no_episodes_for_subject" in absent.notes
            empty = await subject_longitudinal_view(db, CHAT2)
            assert empty.state == VIEW_STATE_EMPTY
        finally:
            await db.close()


# ═══ M-03: incremental/rebuild, revisions, watermark, override ══════════════

class TestM03RebuildIdempotency:
    async def _process_incremental(self, db, msgs):
        svc = EpisodeService(db, llm=None, now=NOW)
        await svc.process_batch(CHAT, msgs)
        return await list_episode_views(db, CHAT)

    @pytest.mark.asyncio
    async def test_incremental_matches_bounded_rebuild(self):
        """Direct-путь (in-memory порция) и bounded rebuild из БД дают одну
        projection на одном наборе source revisions при одинаковом окне."""
        msgs = [_msg(CHAT, 1, 11, "Первая тема разговора дня", T2021),
                _msg(CHAT, 2, 11, "Вторая реплика разговора дня", T2021 + 60),
                _msg(CHAT, 3, 12, "Ответ другого участника дня",
                     T2021 + 120),
                _msg(CHAT, 4, 11, "Отдельная тема следующего года", T2023),
                _msg(CHAT, 5, 11, "Продолжение темы следующего года",
                     T2023 + 60)]
        db_a = await _fixture(msgs)
        db_b = await _fixture(msgs)
        try:
            incremental = await self._process_incremental(db_a, msgs)
            runner = EpisodesBackfillRunner(db_b, llm=None)
            result = await runner.rebuild_range(
                CHAT, since_ts=0, until_ts=T2023 + 86400)
            rebuilt = await list_episode_views(db_b, CHAT)
            assert result["enabled"] is True
            assert result["complete"] is True
            assert result["reason"] == "completed"
            assert result["episodes_created"] == len(rebuilt) == 2
            assert len(incremental) == 2
            # Одна и та же projection на одном наборе source revisions
            # (UUID между БД разные — сравнивается projection).
            assert sorted(_fingerprint_tuple(v) for v in incremental) == \
                sorted(_fingerprint_tuple(v) for v in rebuilt)
        finally:
            await db_a.close()
            await db_b.close()

    @pytest.mark.asyncio
    async def test_rebuild_twice_no_duplicates_no_id_drift(self):
        msgs = [_msg(CHAT, 1, 11, "Тема для повторной сборки", T2021),
                _msg(CHAT, 2, 11, "Вторая реплика для сборки", T2021 + 60)]
        db = await _fixture(msgs)
        try:
            runner = EpisodesBackfillRunner(db, llm=None)
            first = await runner.rebuild_range(CHAT, since_ts=0,
                                               until_ts=T2021 + 86400)
            views_first = await list_episode_views(db, CHAT)
            second = await runner.rebuild_range(CHAT, since_ts=0,
                                                until_ts=T2021 + 86400)
            views_second = await list_episode_views(db, CHAT)
            assert first["episodes_created"] == 1
            assert second["episodes_created"] == 0
            assert [v.episode_ref for v in views_first] == \
                [v.episode_ref for v in views_second]
            assert [_fingerprint_tuple(v) for v in views_first] == \
                [_fingerprint_tuple(v) for v in views_second]
            assert await _count(
                db, "SELECT COUNT(*) FROM mca_episodes") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_old_archive_rebuild_dedups_beyond_500_episodes(self):
        """Повтор старой порции не создаёт дубль, даже когда в чате >500
        эпизодов (дедуп по событийному диапазону, не по последним 500)."""
        msgs = [_msg(CHAT, 1, 11, "Старая тема разговора целиком", T2021),
                _msg(CHAT, 2, 11, "Реплика старой темы разговора",
                     T2021 + 60),
                _msg(CHAT, 3, 11, "Ещё реплика старой темы", T2021 + 120),
                _msg(CHAT, 4, 11, "Финал старой темы разговора", T2021 + 180)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            assert await _count(
                db, "SELECT COUNT(*) FROM mca_episodes") == 1
            filler = []
            for i in range(501):
                filler.append((
                    f"ep-fill-{i:04d}", CHAT, 1_000_000_000,
                    1_000_000_060, NOW + 10_000, NOW + 10_000,
                    f"fill-seg-{i}", json.dumps([f"{CHAT}:tg:{9000 + i}"])))
            await db.db.executemany(
                "INSERT INTO mca_episodes (episode_id, chat_id, "
                "event_start_ts, event_end_ts, discovered_at, updated_at, "
                "segment_key, message_keys_json) VALUES (?,?,?,?,?,?,?,?)",
                filler)
            await db.db.commit()
            # Сдвинутая граница: 4 общих ключа из 5 → прежний дедуп.
            shifted = msgs + [_msg(CHAT, 5, 11, "Пятое сообщение темы",
                                   T2021 + 240)]
            await svc.process_batch(CHAT, shifted)
            real = await _count(
                db, "SELECT COUNT(*) FROM mca_episodes "
                    "WHERE episode_id NOT LIKE 'ep-fill-%'")
            assert real == 1      # дубликат не создан
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_edit_recheck_revision_is_stable(self):
        db = await _fixture([_msg(CHAT, 1, 11, "Исходный текст события",
                                  T2021)])
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, [_msg(CHAT, 1, 11,
                                                "Исходный текст события",
                                                T2021)])
            repo = EpisodeRepository(db)
            episode = (await repo.list_episodes(CHAT))[0]
            key = message_key(_msg(CHAT, 1, 11, "правка", T2021))
            runner = EpisodesBackfillRunner(
                db, llm=_FakeLLM(answers=[
                    _extract(title="После правки один"),
                    _extract(title="После правки два")]))
            for expected_title in ("После правки один", "После правки два"):
                assert await queue_source_recheck(db, CHAT, [key]) == 1
                assert await runner.process_rechecks(CHAT) == 1
                row = await repo.get_episode(episode["episode_id"])
                assert row["title"] == expected_title
                # Ревизия не «уплывает» от повторов (stable revision).
                assert row["extraction_version"] == \
                    f"{EXTRACTOR_VERSION}+recheck"
                assert row["segment_key"] == episode["segment_key"]
                assert row["discovered_at"] == episode["discovered_at"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_source_time_revision_moves_event_window(self):
        """Правка timestamp источника: окно события следует за источником,
        дата обнаружения не меняется (A11), ID/segment_key стабильны."""
        db = await _fixture([_msg(CHAT, 1, 11, "Событие с датой источника",
                                  T2021)])
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(
                CHAT, [_msg(CHAT, 1, 11, "Событие с датой источника", T2021)])
            view = (await list_episode_views(db, CHAT))[0]
            assert view.event_start_ts == T2021
            await db.db.execute(
                "UPDATE smart_messages SET timestamp = ?, text = ? "
                "WHERE chat_id = ? AND tg_message_id = 1",
                (T2023, "Исправленная дата события", CHAT))
            await db.db.commit()
            assert await queue_source_recheck(
                db, CHAT, [f"{CHAT}:tg:1"]) == 1
            await EpisodesBackfillRunner(db, llm=None).process_rechecks(CHAT)
            updated = await get_episode_view(db, CHAT, view.episode_ref)
            assert updated.event_start_ts == T2023
            assert updated.event_end_ts == T2023
            assert updated.discovered_at == view.discovered_at
            assert updated.episode_ref == view.episode_ref
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_deleted_source_not_reported_verified(self):
        msgs = [_msg(CHAT, 1, 11, "Первое сообщение эпизода", T2021),
                _msg(CHAT, 2, 12, "Второе сообщение эпизода", T2021 + 60)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            view = (await list_episode_views(db, CHAT))[0]
            assert view.source_integrity == SOURCE_INTEGRITY_OK
            await db.db.execute(
                "DELETE FROM smart_messages WHERE chat_id = ? AND "
                "tg_message_id = ?", (CHAT, 2))
            await db.db.commit()
            partial = await get_episode_view(db, CHAT, view.episode_ref)
            assert partial.source_integrity == SOURCE_INTEGRITY_PARTIAL
            assert partial.missing_source_refs == (f"{CHAT}:tg:2",)
            assert partial.stale is True
            assert partial.projection_complete is False
            # Удалённый источник не пересоздаётся «восстановлением».
            assert await _count(
                db, "SELECT COUNT(*) FROM smart_messages WHERE chat_id = ?",
                (CHAT,)) == 1
            await db.db.execute(
                "DELETE FROM smart_messages WHERE chat_id = ?", (CHAT,))
            await db.db.commit()
            missing = await get_episode_view(db, CHAT, view.episode_ref)
            assert missing.source_integrity == SOURCE_INTEGRITY_MISSING
            assert missing.stale is True
            assert missing.projection_complete is False
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_watermark_does_not_jump_over_failed_portion(
            self, monkeypatch):
        """Ошибка модели в порции → paused, курсор НЕ продвинут через
        незавершённую порцию (рестарт перечитает её, дедуп → без дублей).

        Test-only overrides: continuation и direct-priority выключены,
        чтобы LLM-скрипт был детерминирован (проверяемое свойство —
        durable cursor, не эти ветки)."""
        monkeypatch.setattr(
            mca_gates, "episodes_continuation_enabled", lambda: False)
        monkeypatch.setattr(
            mca_gates, "episodes_direct_priority_enabled", lambda: False)
        msgs = [_msg(CHAT, i + 1, 11, f"Сообщение порции номер {i}", T2021
                     + i * 7200) for i in range(4)]
        db = await _fixture(msgs)
        try:
            jid = await enqueue_episodes_backfill(db, CHAT, max_messages=2)
            llm = _FakeLLM(default=_extract())
            llm.answers = [_extract(summary="первый"),
                           _extract(summary="второй")]

            class _FailAfterTwo:
                def __init__(self):
                    self.calls = 0

                async def generate(self, messages, **kwargs):
                    self.calls += 1
                    if self.calls <= 2:
                        return _extract(summary=f"ok-{self.calls}")
                    raise RuntimeError("model unavailable")

            runner = EpisodesBackfillRunner(db, llm=_FailAfterTwo())
            status = await runner.run(jid)
            assert status == "paused"
            row = await runner._store.get(jid)
            assert row["reason_code"] == "model_unavailable"
            payload = json.loads(row["payload"])
            # Курсор на конце ПЕРВОЙ (успешной) порции, не на конце второй.
            assert payload["cursor_id"] == msgs[1]["tg_message_id"]
            assert payload["cursor_ts"] == msgs[1]["timestamp"]
            assert payload["counters"]["processed"] == 2
            assert payload["counters"]["batches"] == 1
            # Рестарт новой задачей: перечитывает всё, дублей нет.
            jid2 = await enqueue_episodes_backfill(db, CHAT, max_messages=2)
            status2 = await EpisodesBackfillRunner(
                db, llm=None).run(jid2)
            assert status2 == "completed"
            assert await _count(
                db, "SELECT COUNT(*) FROM mca_episodes") == \
                await _count(db, "SELECT COUNT(DISTINCT segment_key) "
                                 "FROM mca_episodes")
            assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 4
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_reports_assemble_failure_after_recheck(
            self, monkeypatch):
        """M-03 blocker regression: recheck успешен, но пересборка историй
        падает → rebuild НЕ `complete=True` (честный `assemble_failed`),
        повтор завершает проекцию без потери override и без дублей."""
        db = await _fixture([
            _msg(CHAT, 1, 11, "Событие для пересборки истории", T2021)])
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(
                CHAT, [_msg(CHAT, 1, 11, "Событие для пересборки истории",
                            T2021)])
            repo = EpisodeRepository(db)
            story = (await repo.list_stories(CHAT))[0]
            await repo.update_story_manual(
                story["story_id"], int(story["expected_version"]),
                title="Ручная правка", now=NOW)
            assert await queue_source_recheck(
                db, CHAT, [f"{CHAT}:tg:1"]) == 1

            fail = {"armed": True, "calls": 0}
            original = EpisodeService.assemble_stories

            async def _flaky(self, chat_id, now, **kwargs):
                fail["calls"] += 1
                if fail["armed"] and fail["calls"] >= 2:
                    raise RuntimeError("story assemble unavailable")
                return await original(self, chat_id, now, **kwargs)

            monkeypatch.setattr(EpisodeService, "assemble_stories", _flaky)
            runner = EpisodesBackfillRunner(
                db, llm=_FakeLLM(default=_extract(summary="После правки")))
            first = await runner.rebuild_range(
                CHAT, since_ts=0, until_ts=T2021 + 86400)
            assert first["rechecked"] == 1
            assert first["errors"] >= 1
            assert first["complete"] is False
            assert first["reason"] == "assemble_failed"
            # Эпизод перепроверен, но story ещё не пересобрана.
            episode = (await repo.list_episodes(CHAT))[0]
            assert episode["extraction_version"].endswith("+recheck")
            stale_story = await repo.get_story(story["story_id"])
            stale_effective = effective_story(stale_story)
            assert "После правки" not in stale_effective["summary"]
            assert stale_effective["title"] == "Ручная правка"

            # Повторный bounded rebuild: честный completed, проекция
            # догоняет текущий эпизод, override и IDs сохранены.
            fail["armed"] = False
            second = await runner.rebuild_range(
                CHAT, since_ts=0, until_ts=T2021 + 86400)
            assert second["complete"] is True
            assert second["reason"] == "completed"
            assert second["errors"] == 0
            fresh = await repo.get_story(story["story_id"])
            effective = effective_story(fresh)
            assert effective["title"] == "Ручная правка"
            assert "После правки" in effective["summary"]
            assert fresh["override_title"] == "Ручная правка"
            assert await _count(
                db, "SELECT COUNT(*) FROM mca_stories") == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM mca_story_episode_links") == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM mca_episodes") == 1
            versions = await repo.list_story_versions(story["story_id"])
            assert len(versions) >= 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_process_rechecks_surfaces_assembly_failure(
            self, monkeypatch):
        """`process_rechecks` не выдаёт упавшую пересборку за успех."""
        db = await _fixture([_msg(CHAT, 1, 11, "Событие для recheck", T2021)])
        try:
            await EpisodeService(db, llm=None, now=NOW).process_batch(
                CHAT, [_msg(CHAT, 1, 11, "Событие для recheck", T2021)])
            assert await queue_source_recheck(
                db, CHAT, [f"{CHAT}:tg:1"]) == 1

            async def _broken(self, chat_id, now, **kwargs):
                raise RuntimeError("story assemble unavailable")

            monkeypatch.setattr(EpisodeService, "assemble_stories", _broken)
            runner = EpisodesBackfillRunner(
                db, llm=_FakeLLM(default=_extract(summary="После recheck")))
            with pytest.raises(RecheckAssemblyError):
                await runner.process_rechecks(CHAT)
            episode = (await EpisodeRepository(db).list_episodes(CHAT))[0]
            assert episode["extraction_version"].endswith("+recheck")
            assert int(episode["recheck_pending"] or 0) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_manual_override_survives_rebuild(self):
        msgs = [_msg(CHAT, 1, 11, "Событие для ручной правки истории", T2021)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            repo = EpisodeRepository(db)
            story = (await repo.list_stories(CHAT))[0]
            await repo.update_story_manual(
                story["story_id"], int(story["expected_version"]),
                title="Ручная правка", now=NOW)
            runner = EpisodesBackfillRunner(db, llm=None)
            await runner.rebuild_range(CHAT, since_ts=0,
                                       until_ts=T2021 + 86400)
            updated = await repo.get_story(story["story_id"])
            assert updated["override_title"] == "Ручная правка"
            assert effective_story(updated)["title"] == "Ручная правка"
            assert int(updated["expected_version"]) >= 2
            assert updated["discovered_at"] == story["discovered_at"]
        finally:
            await db.close()


# ═══ Нет mass-reembedding, нет DDL, нет секретов ════════════════════════════

class TestNoReembeddingNoDdl:
    @pytest.mark.asyncio
    async def test_no_embedding_writes_during_m1_flows(self, monkeypatch):
        from services import embedding_control_plane as ecp
        from services import llm_client

        calls: list[str] = []

        def _boom(name):
            async def _fail(*args, **kwargs):
                calls.append(name)
                raise AssertionError(f"embedding write attempted: {name}")
            return _fail

        monkeypatch.setattr(llm_client.LLMClient, "embed",
                            _boom("LLMClient.embed"))
        monkeypatch.setattr(llm_client.LLMClient, "embed_once",
                            _boom("LLMClient.embed_once"))
        monkeypatch.setattr(ecp.EmbeddingExecutor, "embed",
                            _boom("EmbeddingExecutor.embed"))
        monkeypatch.setattr(ecp.EmbeddingProviderAdapter, "embed_batch",
                            _boom("EmbeddingProviderAdapter.embed_batch"))
        msgs = [_msg(CHAT, 1, 11, "Сообщение без эмбеддингов один", T2021),
                _msg(CHAT, 2, 11, "Сообщение без эмбеддингов два", T2023)]
        db = await _fixture(msgs)
        try:
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            await list_episode_views(db, CHAT)
            await get_episode_view(
                db, CHAT, (await list_episode_views(db, CHAT))[0].episode_ref)
            await subject_longitudinal_view(db, CHAT)
            runner = EpisodesBackfillRunner(db, llm=None)
            await runner.rebuild_range(CHAT, since_ts=0,
                                       until_ts=T2023 + 86400)
            await runner.process_rechecks(CHAT)
            assert calls == []
            assert await _count(
                db, "SELECT COUNT(*) FROM embedding_cache") == 0
        finally:
            await db.close()

    def test_static_no_embedding_or_ddl_paths(self):
        from services import mca_episode_jobs, mca_episodes
        for module in (mca_episodes, mca_episode_jobs):
            source = inspect.getsource(module)
            for forbidden in ("embed(", "embed_once(", "embed_batch(",
                              "embedding_cache", "upsert_vector",
                              "embedding_control_plane"):
                assert forbidden not in source, (module.__name__, forbidden)
            for ddl in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE",
                        "CREATE INDEX", "DROP INDEX"):
                assert ddl not in source, (module.__name__, ddl)

    @pytest.mark.asyncio
    async def test_m1_flows_do_not_change_schema(self):
        from services import mca_episode_jobs, mca_episodes
        assert "CREATE TABLE" not in inspect.getsource(mca_episodes)
        assert "ALTER TABLE" not in inspect.getsource(mca_episode_jobs)
        msgs = [_msg(CHAT, 1, 11, "Сообщение для проверки схемы", T2021)]
        db = await _fixture(msgs)
        try:
            before = await _user_version(db)
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, msgs)
            runner = EpisodesBackfillRunner(db, llm=None)
            await runner.rebuild_range(CHAT, since_ts=0,
                                       until_ts=T2021 + 86400)
            await subject_longitudinal_view(db, CHAT)
            assert await _user_version(db) == before
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_failure_paths_do_not_log_message_bodies(self, caplog):
        secret = "SECRET_TOKEN_XYZ_987"
        msgs = [_msg(CHAT, 1, 11, f"Текст с секретом {secret}", T2021)]

        class _Raising:
            async def generate(self, messages, **kwargs):
                raise RuntimeError(f"provider error body={secret}")

        db = await _fixture(msgs)
        try:
            with caplog.at_level("DEBUG"):
                # Direct-путь с ошибкой провайдера (без валидного эпизода).
                await EpisodeService(
                    db, llm=_Raising(), now=NOW).process_batch(CHAT, msgs)
                # Готовый эпизод → правка → recheck с ошибкой провайдера.
                await EpisodeService(
                    db, llm=None, now=NOW).process_batch(CHAT, msgs)
                assert await queue_source_recheck(
                    db, CHAT, [f"{CHAT}:tg:1"]) == 1
                await EpisodesBackfillRunner(
                    db, llm=_Raising()).process_rechecks(CHAT)
            # Только логи нашего кода: DEBUG-лог aiosqlite печатает SQL-
            # параметры драйвера (внешнее поведение, INFO в production).
            chunks: list[str] = []
            for record in caplog.records:
                if not record.name.startswith("services"):
                    continue
                chunks.append(record.getMessage())
                if record.exc_text:
                    chunks.append(record.exc_text)
            text = "\n".join(chunks)
            assert secret not in text
            assert "body=" not in text
            assert "recheck extract failed" in text  # путь исполнен
        finally:
            await db.close()


# ═══ Деградация, legacy-совместимость, bounded-работа ═══════════════════════

class TestDegradationAndBounds:
    @pytest.mark.asyncio
    async def test_gate_off_keeps_legacy_paths(self, monkeypatch):
        db = await _fixture([_msg(CHAT, 1, 11, "Текст для гейта", T2021)])
        try:
            await db.upsert_lore_story(CHAT, "работа", "Работа",
                                       "старая история про работу",
                                       last_ts=T2021)
            monkeypatch.setattr(mca_gates, "episodes_enabled", lambda: False)
            svc = EpisodeService(db, llm=None, now=NOW)
            counters = await svc.process_batch(
                CHAT, [_msg(CHAT, 1, 11, "Текст для гейта", T2021)])
            assert counters["enabled"] is False
            assert await _count(
                db, "SELECT COUNT(*) FROM mca_episodes") == 0
            runner = EpisodesBackfillRunner(db, llm=None)
            off = await runner.rebuild_range(CHAT, since_ts=0)
            assert off["enabled"] is False
            assert off["reason"] == "episodes_disabled"
            legacy = await list_stories_for_retrieval(db, CHAT)
            assert any(row.get("kind") == "legacy_story" for row in legacy)
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_view_failure_is_honest_unavailable(self, monkeypatch):
        db = await _fixture([_msg(CHAT, 1, 11, "Текст события", T2021)])
        try:
            await EpisodeService(db, llm=None, now=NOW).process_batch(
                CHAT, [_msg(CHAT, 1, 11, "Текст события", T2021)])

            async def _broken(*args, **kwargs):
                raise RuntimeError("db gone")

            monkeypatch.setattr(EpisodeRepository, "list_episodes", _broken)
            assert await list_episode_views(db, CHAT) == ()
            lon = await subject_longitudinal_view(db, CHAT)
            assert lon.state == VIEW_STATE_UNAVAILABLE
            assert lon.notes == ("view_unavailable",)
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_legacy_episode_without_sources_is_unknown(self):
        """Legacy-строка без source refs читается, но не выдаётся за
        проверенную (integrity unknown, не verified)."""
        db = await _db()
        try:
            await db.db.execute(
                "INSERT INTO mca_episodes (episode_id, chat_id, title, "
                "summary, discovered_at, updated_at, segment_key, "
                "message_keys_json) VALUES ('ep-legacy', ?, 'Старый эпизод', "
                "'Без источников', ?, ?, 'legacy-seg', '[]')",
                (CHAT, NOW - 1000, NOW - 1000))
            await db.db.commit()
            view = await get_episode_view(db, CHAT, "ep-legacy")
            assert view is not None
            assert view.source_integrity == SOURCE_INTEGRITY_UNKNOWN
            assert view.source_refs == ()
            assert view.projection_complete is False
            assert view.source_fingerprint
            lon = await subject_longitudinal_view(db, CHAT)
            assert lon.legacy_unlinked_episode_refs == ("ep-legacy",)
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_legacy_rows_not_rewritten(self):
        db = await _fixture([_msg(CHAT, 1, 11, "Новое событие чата", T2021)])
        try:
            await db.upsert_lore_story(CHAT, "работа", "Работа",
                                       "старая история", last_ts=T2022)
            cursor = await db.db.execute(
                "SELECT * FROM lore_stories WHERE chat_id = ?", (CHAT,))
            before = dict(await cursor.fetchone())
            svc = EpisodeService(db, llm=None, now=NOW)
            await svc.process_batch(CHAT, [_msg(CHAT, 1, 11,
                                                "Новое событие чата",
                                                T2021)])
            runner = EpisodesBackfillRunner(db, llm=None)
            await runner.rebuild_range(CHAT, since_ts=0,
                                       until_ts=T2021 + 86400)
            cursor = await db.db.execute(
                "SELECT * FROM lore_stories WHERE chat_id = ?", (CHAT,))
            after = dict(await cursor.fetchone())
            assert after == before      # legacy mapped без перезаписи
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_range_is_bounded(self):
        msgs = [_msg(CHAT, i + 1, 11, f"Сообщение диапазона номер {i}",
                     T2021 + i * 7200) for i in range(6)]
        db = await _fixture(msgs)
        try:
            runner = EpisodesBackfillRunner(db, llm=None)
            first = await runner.rebuild_range(
                CHAT, since_ts=0, until_ts=T2021 + 86400,
                max_messages=2, max_batches=1)
            assert first["processed"] == 2
            assert first["batches"] == 1
            assert first["complete"] is False
            assert first["reason"] == "batch_cap_reached"
            assert first["episodes_created"] == 2
            # Продолжение с явной границы не теряет и не дублирует работу.
            second = await runner.rebuild_range(
                CHAT, since_ts=msgs[1]["timestamp"],
                until_ts=T2021 + 86400, max_messages=2, max_batches=10)
            assert second["complete"] is True
            assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 6
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_view_list_is_capped(self):
        db = await _fixture([_msg(CHAT, 1, 11, "Единственное сообщение",
                                  T2021)])
        try:
            await EpisodeService(db, llm=None, now=NOW).process_batch(
                CHAT, [_msg(CHAT, 1, 11, "Единственное сообщение", T2021)])
            views = await list_episode_views(db, CHAT, limit=10_000)
            assert len(views) <= EPISODE_VIEW_LIMIT_MAX
            assert views
        finally:
            await db.close()

    def test_source_fingerprint_is_revision_sensitive(self):
        keys = ["-1:tg:1", "-1:tg:2"]
        rev1 = {"-1:tg:1": 1, "-1:tg:2": 1}
        assert episode_source_fingerprint(
            keys, revisions=rev1) == episode_source_fingerprint(
                keys, revisions=dict(rev1))
        assert episode_source_fingerprint(
            keys, revisions=rev1) != episode_source_fingerprint(
                keys, revisions={"-1:tg:1": 2, "-1:tg:2": 1})
        # Неизвестная ревизия — не ноль (честный `?`).
        assert episode_source_fingerprint(keys) != \
            episode_source_fingerprint(keys, revisions=rev1)
        # Порядок refs значим (хронология эпизода).
        assert episode_source_fingerprint(keys) != \
            episode_source_fingerprint(list(reversed(keys)))
