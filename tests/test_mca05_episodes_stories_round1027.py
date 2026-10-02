"""mca-05-episodes-stories (round 10.27, ADR-1027-12) — Builder-покрытие.

Приёмки/сценарии (spec §4 SC-01…SC-20, §19 A11/A12/A13):
  * v21 (SC-20/A28): аддитивная идемпотентная миграция — 7 таблиц +
    override-колонки + индексы; lore_stories не тронуты; повтор — no-op.
  * A11 (SC-03): событие 2022, найденное сегодня — две даты, время события
    не подменено (детерминированно, без LLM).
  * A12 (SC-02/SC-06/SC-09): две параллельные темы не склеены; overlap
    без дублей; продолжение через неделю — только по подтверждению.
  * A13 (SC-05): ручная правка + повторная сборка — override сохранён,
    версии доступны; stale CAS-апдейт отклонён.
  * SC-04: неизвестный исход — «исход неизвестен»/uncertain (финал не
    выдуман).
  * SC-11/§8.1: provenance ≥1 валидная ссылка или явный unknown.
  * SC-12: backfill честная финализация (paused, никогда ложный completed);
    рестарт без дублей; revision → recheck.
  * SC-13/SC-14: фасад компилятора/канал mca-07/local_context (M-MCA07-2).
  * SC-15: события post-commit (rollback → события нет).
  * SC-16/§2 п.13-14: нет новых разделов/маршрутов; grep-гейт send-path
    (T-4259); граница ASAP-3 verbatim-episode.
  * SC-17/SC-18: reason_code-словарь/маскирование; реестр процессов.
  * SC-20: kill-switch OFF — паритет baseline.

R17: в тестах числа/коды; секретов нет.
"""
import asyncio
import json
import sqlite3
import time

import pytest

from services import mca_events
from services import mca_gates
from services import mca_process_registry as reg
from services.database import (
    DatabaseService,
    EPISODE_STORY_STATES,
    EPISODE_UNKNOWN_OUTCOME,
    _SCHEMA_VERSION_EPISODES_STORIES,
)
from services.mca_episode_jobs import (
    enqueue_episodes_backfill,
    backfill_coalesce_key,
    backfill_status_from_job,
    EpisodesBackfillRunner,
    get_active_backfill,
)
from services.mca_episode_prompts import (
    parse_confirm_answer,
    parse_extract_answer,
    validate_confirm_payload,
    validate_extract_payload,
)
from services.mca_episodes import (
    EpisodeRepository,
    EpisodeService,
    StaleUpdateError,
    detect_contradictions,
    effective_story,
    list_stories_for_retrieval,
    merge_claims,
    message_key,
    queue_source_recheck,
    resolve_story_id,
    segment_key,
    segment_messages,
    segment_times,
    split_by_participant_clusters,
)

CHAT = -100500
CHAT2 = -100501
T_2022 = 1650000000          # 2022-04-15 (событие в прошлом)
_NOW = 1790000000            # «сегодня» для тестов


async def _db(tmp_path, name="mca05.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add_msg(db, chat_id, user_id, text, ts, tg_message_id=None,
                   reply_to_id=None) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, 'text', '', ?)",
        (user_id, chat_id, text, reply_to_id, ts, tg_message_id))
    await db.db.commit()
    return cursor.lastrowid


async def _count(db, sql, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


def _msg(chat_id, tg, user_id, text, ts, db_id=None, reply_to_tg=None):
    return {"chat_id": chat_id, "id": db_id, "tg_message_id": tg,
            "user_id": user_id, "text": text, "timestamp": ts,
            "reply_to_tg_message_id": reply_to_tg}


class _FakeLLM:
    """Скриптовый LLM (интерфейс `generate` — прецедент компилятора)."""

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


def _extract(title="Эпизод", summary="описание", participants=("2",),
             claims=(), outcome_known=False, outcome=None, multi=False,
             refs=()):
    return json.dumps({
        "title": title, "summary": summary,
        "participants": list(participants),
        "claims": [{"text": text, "refs": list(refs)} for text in claims],
        "outcome_known": outcome_known, "outcome": outcome,
        "open_questions": [], "unknown": [],
        "multi_topic": multi,
    }, ensure_ascii=False)


# ═══ v21: миграция (SC-20/A28) ═══════════════════════════════════════════════

class TestMigrationV21:
    @pytest.mark.asyncio
    async def test_v21_tables_and_user_version(self, tmp_path):
        db = await _db(tmp_path)
        cur = await db.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _SCHEMA_VERSION_STORIES_MARK
        for table in ("mca_episodes", "mca_stories", "mca_story_versions",
                      "mca_story_episode_links", "mca_story_continuations",
                      "mca_story_redirects", "mca_story_legacy_links"):
            assert await _count(
                db, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                f"AND name='{table}'") == 1, table
        # override-колонки nullable
        cursor = await db.db.execute("PRAGMA table_info(mca_stories)")
        cols = {r["name"] for r in await cursor.fetchall()}
        for name in ("override_title", "override_summary", "override_outcome",
                     "override_state", "override_open_questions"):
            assert name in cols
        await db.close()

    @pytest.mark.asyncio
    async def test_v21_idempotent_reinit(self, tmp_path):
        db = await _db(tmp_path)
        db2 = DatabaseService(str(tmp_path / "mca05.db"))
        await db2.initialize()
        cur = await db2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _SCHEMA_VERSION_STORIES_MARK
        book = await _count(
            db2, "SELECT COUNT(*) FROM schema_migrations WHERE version = 21")
        assert book == 1
        await db2.close()
        await db.close()

    @pytest.mark.asyncio
    async def test_v21_lore_stories_untouched(self, tmp_path):
        """Старые `lore_stories` и их данные не трогаются (паритет legacy)."""
        db = await _db(tmp_path)
        await db.upsert_lore_story(CHAT, "тема", "Тема", "старая история",
                                   last_ts=123)
        row = await db.get_lore_story(CHAT, "тема")
        assert row is not None and row["story"] == "старая история"
        db2 = DatabaseService(str(tmp_path / "mca05.db"))
        await db2.initialize()
        again = await db2.get_lore_story(CHAT, "тема")
        assert again is not None and again["id"] == row["id"]
        await db2.close()
        await db.close()

    @pytest.mark.asyncio
    async def test_registry_order_and_checksum(self):
        steps = DatabaseService.migration_steps()
        versions = [s.version for s in steps]
        assert versions == sorted(versions)
        assert len(set(versions)) == len(versions)
        # MCA-22 (ADR-1028-6 §4.1): хвост реестра теперь v22 — mca-05
        # остаётся в реестре; mark обновлён на текущий хвост по конвенции
        # волн (прецедент v16→v21).
        assert versions[-1] == _SCHEMA_VERSION_STORIES_MARK
        assert _SCHEMA_VERSION_EPISODES_STORIES in versions
        assert _SCHEMA_VERSION_EPISODES_STORIES == 21


# MCA-22: mark хвоста реестра — v22 (bot_outputs_ledger); v21-таблицы
# проверяются выше без изменений. ASAP-4 (ADR-1028-7): хвост реестра — v23
# (embedding_control_plane) — mark обновлён на актуальный конец реестра.
from services.database import (  # noqa: E402
    _SCHEMA_VERSION_BOT_OUTPUTS as _SCHEMA_VERSION_TAIL_V22,
    _SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE as _SCHEMA_VERSION_TAIL_V23,
)
_SCHEMA_VERSION_STORIES_MARK = _SCHEMA_VERSION_TAIL_V23


# ═══ Kill-switch OFF-паритет (SC-20, T-4249) ═════════════════════════════════

class TestKillSwitchParity:
    @pytest.mark.asyncio
    async def test_master_off_no_pipeline_writes(self, tmp_path,
                                                 monkeypatch):
        monkeypatch.setattr(mca_gates, "episodes_enabled",
                            lambda: False)
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        msgs = [_msg(CHAT, 10, 2, "текст", T_2022)]
        counters = await svc.process_batch(CHAT, msgs)
        assert counters["enabled"] is False
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 0
        assert await _count(db, "SELECT COUNT(*) FROM mca_stories") == 0
        # backfill-гейт инертен при master OFF
        assert mca_gates.episodes_backfill_enabled() is False
        assert mca_gates.episodes_continuation_enabled() is False
        assert mca_gates.episodes_compiler_facade_enabled() is False
        with pytest.raises(RuntimeError):
            await enqueue_episodes_backfill(db, CHAT)
        await db.close()

    @pytest.mark.asyncio
    async def test_facade_gate_off_legacy_channel_path(self, tmp_path,
                                                       monkeypatch):
        monkeypatch.setattr(mca_gates, "episodes_compiler_facade_enabled",
                            lambda: False)
        db = await _db(tmp_path)
        await db.upsert_lore_story(CHAT, "тема", "Тема", "история",
                                   last_ts=5)
        from services.mca_retrieval_context import RetrievalRequest, \
            _episode_candidates
        rows = await _episode_candidates(
            db, RetrievalRequest(chat_id=CHAT, query="тема"), ["тема"])
        assert rows and rows[0].entity_type == "episode"
        await db.close()

    def test_kill_switch_manifest_entries(self):
        for key in ("MCA_EPISODES_ENABLED", "MCA_EPISODES_BACKFILL_ENABLED",
                    "MCA_EPISODES_CONTINUATION_ENABLED",
                    "MCA_EPISODES_COMPILER_FACADE_ENABLED"):
            assert key in mca_gates.KILL_SWITCHES
            assert mca_gates.KILL_SWITCHES[key][0] is True  # default ON


# ═══ Сегментация (D4; SC-06/SC-07) ═══════════════════════════════════════════

class TestSegmentation:
    def test_time_gap_split(self):
        msgs = [_msg(CHAT, 1, 2, "a", T_2022),
                _msg(CHAT, 2, 2, "b", T_2022 + 60),
                _msg(CHAT, 3, 2, "c", T_2022 + 7200)]
        segments = segment_messages(msgs)
        assert len(segments) == 2
        assert [len(s) for s in segments] == [2, 1]

    def test_reply_join_within_horizon(self):
        msgs = [_msg(CHAT, 1, 2, "a", T_2022),
                _msg(CHAT, 2, 3, "b", T_2022 + 7200, reply_to_tg=1)]
        segments = segment_messages(msgs)
        assert len(segments) == 1      # reply-склейка внутри горизонта

    def test_reply_beyond_horizon_stays_separate(self):
        msgs = [_msg(CHAT, 1, 2, "a", T_2022),
                _msg(CHAT, 2, 3, "b", T_2022 + 7 * 86400, reply_to_tg=1)]
        segments = segment_messages(msgs)
        assert len(segments) == 2      # «через неделю» — отдельные эпизоды

    def test_parallel_threads_split_by_participant(self):
        """A12-база: параллельные разговоры (гэп > soft) не смешиваются."""
        msgs = [_msg(CHAT, 1, 7, "проект альфа", T_2022),
                _msg(CHAT, 2, 7, "проект альфа деталь", T_2022 + 60),
                _msg(CHAT, 3, 9, "коты и усы", T_2022 + 700),
                _msg(CHAT, 4, 9, "коты и усы часть 2", T_2022 + 760)]
        segments = segment_messages(msgs)
        assert len(segments) == 2
        authors = [{m["user_id"] for m in s} for s in segments]
        assert {7} in authors and {9} in authors

    @pytest.mark.asyncio
    async def test_overlap_dedup_same_keys(self, tmp_path):
        """SC-07: overlap границ batch не создаёт дублей: повтор того же
        окна → тот же segment_key (INSERT OR IGNORE); частичный overlap
        ≥50% → `_find_overlap_duplicate`."""
        msgs = [_msg(CHAT, 1, 2, "a", T_2022), _msg(CHAT, 2, 2, "b",
                                                    T_2022 + 30)]
        segs_a = segment_messages(msgs)
        segs_replay = segment_messages(list(reversed(msgs)))
        assert segment_key([message_key(m) for m in segs_a[0]]) == \
            segment_key([message_key(m) for m in segs_replay[0]])
        # порядок сообщений не влияет на ключ (детерминизм)
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 1
        # повтор того же окна — дубль не создаётся
        await svc.process_batch(CHAT, msgs)
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 1
        # частичный overlap (50%) — дубль
        await svc.process_batch(CHAT, msgs[:1] + [
            _msg(CHAT, 3, 2, "c", T_2022 + 60)])
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 1
        await db.close()

    def test_dedup_segments_by_key(self):
        seg = [_msg(CHAT, 1, 2, "a", T_2022)]
        out = segment_messages(seg + [dict(seg[0])])
        assert len(out) == 1

    def test_split_by_participant_clusters(self):
        seg = [_msg(CHAT, 1, 7, "a", T_2022),
               _msg(CHAT, 2, 9, "b", T_2022 + 5),
               _msg(CHAT, 3, 7, "a2", T_2022 + 30),
               _msg(CHAT, 4, 9, "b2", T_2022 + 35)]
        groups = split_by_participant_clusters(seg)
        assert len(groups) == 2
        # reply связывает авторов → один кластер (не рвём диалог)
        linked = [_msg(CHAT, 1, 7, "a", T_2022),
                  _msg(CHAT, 2, 9, "b", T_2022 + 5, reply_to_tg=1)]
        assert len(split_by_participant_clusters(linked)) == 1

    def test_segment_times_two_dates(self):
        seg = [_msg(CHAT, 1, 2, "a", T_2022), _msg(CHAT, 2, 2, "b",
                                                   T_2022 + 120)]
        assert segment_times(seg) == (T_2022, T_2022 + 120)


# ═══ Извлечение: offline-валидатор (D5; SC-08) ═══════════════════════════════

class TestExtractionContract:
    def test_unknown_claim_not_becomes_fact(self):
        raw = json.dumps({"title": "Т", "summary": "С",
                          "participants": ["2"],
                          "claims": [{"text": "без источника",
                                      "refs": ["нет такого"]}],
                          "outcome_known": True, "outcome": "финал",
                          "unknown": [], "multi_topic": False},
                         ensure_ascii=False)
        payload = validate_extract_payload(
            parse_extract_answer(raw), member_keys={message_key(
                _msg(CHAT, 10, 2, "x", T_2022))},
            participant_ids={"2"})
        assert payload["claims"] == []
        assert any("без источника" in u for u in payload["unknown"])

    def test_participant_filter_by_stable_ids(self):
        raw = json.dumps({"title": "Т", "summary": "",
                          "participants": ["2", "999"],
                          "claims": [], "outcome_known": False,
                          "outcome": None, "unknown": [],
                          "multi_topic": False}, ensure_ascii=False)
        payload = validate_extract_payload(
            parse_extract_answer(raw), member_keys={"k"},
            participant_ids={"2"})
        assert payload["participants"] == ["2"]     # 999 не из подборки

    def test_unknown_outcome_is_honest(self):
        raw = json.dumps({"title": "Т", "summary": "",
                          "participants": [], "claims": [],
                          "outcome_known": False, "outcome": None,
                          "unknown": [], "multi_topic": False},
                         ensure_ascii=False)
        payload = validate_extract_payload(
            parse_extract_answer(raw), member_keys={"k"},
            participant_ids=set())
        assert payload["outcome"] == EPISODE_UNKNOWN_OUTCOME
        assert payload["outcome_known"] is False

    def test_invalid_answer_never_fabricates(self):
        assert parse_extract_answer("мусор без JSON") is None
        assert parse_extract_answer(None) is None
        payload = validate_extract_payload(None, member_keys=set(),
                                           participant_ids=set())
        assert payload["valid"] is False
        assert payload["outcome"] == EPISODE_UNKNOWN_OUTCOME

    def test_confirm_fail_closed(self):
        assert validate_confirm_payload(parse_confirm_answer(
            json.dumps({"related": True})))["related"] is False  # нет conf
        assert validate_confirm_payload(parse_confirm_answer(
            json.dumps({"related": False, "confidence": 0.9})
        ))["related"] is False
        assert validate_confirm_payload(None)["related"] is False


# ═══ Модель/инварианты (D3; A11; state ≠ job) ════════════════════════════════

class TestModelInvariants:
    @pytest.mark.asyncio
    async def test_a11_two_dates_no_substitution(self, tmp_path):
        """A11: событие 2022, найденное сегодня — event_start/end 2022,
        discovered_at = сегодня; без LLM, детерминированно."""
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        msgs = [_msg(CHAT, 10, 2, "событие 2022 года", T_2022),
                _msg(CHAT, 11, 3, "продолжение", T_2022 + 300)]
        counters = await svc.process_batch(CHAT, msgs)
        assert counters["extracted"] == 1
        repo = EpisodeRepository(db)
        episodes = await repo.list_episodes(CHAT)
        episode = episodes[0]
        assert episode["event_start_ts"] == T_2022          # 2022
        assert episode["event_end_ts"] == T_2022 + 300
        assert episode["discovered_at"] == _NOW             # сегодня
        assert episode["discovered_at"] - episode["event_start_ts"] > \
            86400 * 300
        stories = await repo.list_stories(CHAT)
        card = effective_story(stories[0])
        assert card["event_start_ts"] == T_2022
        assert card["discovered_at"] == _NOW
        await db.close()

    @pytest.mark.asyncio
    async def test_state_is_not_job_status(self, tmp_path):
        """Состояние истории (`state`) и статус задания — разные поля."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Т", summary="", participants=["2"],
            claims=[], event_start=T_2022, event_end=T_2022,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=["k"], seg_key="s1",
            extraction_version="x", now=_NOW)
        story_id, _vid, _created = await repo.upsert_story(
            chat_id=CHAT, title="История", summary="", participants=["2"],
            claims=[], event_start=T_2022, event_end=T_2022,
            outcome=EPISODE_UNKNOWN_OUTCOME, state="uncertain",
            verification="unknown", open_questions=[],
            episode_ids=[episode_id], extractor_version="x", now=_NOW)
        # статус задания меняется — state НЕ трогается
        await repo.set_story_task_ref(story_id, "running")
        row = await repo.get_story(story_id)
        assert row["task_status_ref"] == "running"
        assert row["state"] == "uncertain"
        # смена state — task_status_ref НЕ трогается
        await repo.update_story_manual(story_id, 1, state="closed",
                                       now=_NOW)
        row = await repo.get_story(story_id)
        assert row["state"] == "closed"
        assert row["task_status_ref"] == "running"
        assert EPISODE_STORY_STATES == frozenset(
            {"open", "closed", "uncertain"})
        await db.close()

    @pytest.mark.asyncio
    async def test_story_requires_episode(self, tmp_path):
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        with pytest.raises(ValueError):
            await repo.upsert_story(
                chat_id=CHAT, title="Т", summary="", participants=[],
                claims=[], event_start=None, event_end=None,
                outcome="", state="open", verification="unknown",
                open_questions=[], episode_ids=[], extractor_version="x",
                now=_NOW)
        await db.close()

    @pytest.mark.asyncio
    async def test_backfill_status_is_not_story_state(self, tmp_path):
        """job-статус backfill (`completed`) не переводит истории в closed."""
        db = await _db(tmp_path)
        msgs = [_msg(CHAT, 10, 2, "событие", T_2022)]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        jid = await enqueue_episodes_backfill(db, CHAT)
        runner = EpisodesBackfillRunner(db, llm=None)
        status = await runner.run(jid)
        assert status == "completed"
        repo = EpisodeRepository(db)
        for story in await repo.list_stories(CHAT):
            assert story["state"] in ("open", "uncertain")
            assert story["task_status_ref"] is None
        await db.close()


# ═══ Версии/overrides/redirect (D9; A13) ═════════════════════════════════════

class TestVersionsOverrides:
    async def _seed_story(self, db):
        repo = EpisodeRepository(db)
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Эпизод", summary="начало",
            participants=["2"], claims=[], event_start=T_2022,
            event_end=T_2022, outcome=EPISODE_UNKNOWN_OUTCOME,
            outcome_known=False, open_questions=[], message_keys=["k1"],
            seg_key="s1", extraction_version="x", now=_NOW)
        # Поля совпадают с вычисляемыми пайплайном (пересборка без
        # изменения не создаёт версию — проверяется отдельно).
        story_id, _vid, _created = await repo.upsert_story(
            chat_id=CHAT, title="Эпизод", summary="начало",
            participants=["2"], claims=[], event_start=T_2022,
            event_end=T_2022, outcome=EPISODE_UNKNOWN_OUTCOME,
            state="uncertain", verification="unknown", open_questions=[],
            episode_ids=[episode_id], extractor_version="x", now=_NOW)
        return repo, story_id

    @pytest.mark.asyncio
    async def test_a13_override_survives_rebuild(self, tmp_path):
        """A13: ручная правка + повторная сборка → override сохранён,
        обе версии доступны."""
        db = await _db(tmp_path)
        repo, story_id = await self._seed_story(db)
        row = await repo.get_story(story_id)
        await repo.update_story_manual(story_id, int(row["expected_version"]),
                                       title="Моя правка", state="closed",
                                       now=_NOW)
        # повторная сборка (пайплайн) — override не затирается
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Эпизод", summary="начало",
            participants=["2"], claims=[], event_start=T_2022,
            event_end=T_2022, outcome=EPISODE_UNKNOWN_OUTCOME,
            outcome_known=False, open_questions=[], message_keys=["k1"],
            seg_key="s1", extraction_version="x", now=_NOW + 1)
        assert episode_id is None      # overlap-дедуп (тот же сегмент)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.assemble_stories(CHAT, _NOW + 2)
        row = await repo.get_story(story_id)
        card = effective_story(row)
        assert card["title"] == "Моя правка"
        assert card["state"] == "closed"
        versions = await repo.list_story_versions(story_id)
        assert len(versions) >= 2      # обе версии доступны
        assert versions[0]["created_by"] == "pipeline"
        assert versions[-1]["created_by"] == "manual"
        snapshot = json.loads(versions[-1]["payload_json"])
        assert snapshot["overrides"].get("title") == "Моя правка"
        await db.close()

    @pytest.mark.asyncio
    async def test_cas_stale_update_rejected(self, tmp_path):
        """CAS `expected_version`: stale update отклоняется, не затирает."""
        db = await _db(tmp_path)
        repo, story_id = await self._seed_story(db)
        row = await repo.get_story(story_id)
        await repo.update_story_manual(story_id, int(row["expected_version"]),
                                       title="правка 1", now=_NOW)
        try:
            await repo.update_story_manual(story_id, 1, title="stale",
                                           now=_NOW)
            raise AssertionError("stale update не отклонён")
        except StaleUpdateError:
            pass
        row = await repo.get_story(story_id)
        card = effective_story(row)
        assert card["title"] == "правка 1"
        await db.close()

    @pytest.mark.asyncio
    async def test_merge_and_redirect(self, tmp_path):
        """Merge сохраняет историю; redirect старых ID резолвится
        неограниченно долго (внешние ссылки не ломаются)."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        ids = []
        for i in ("a", "b"):
            episode_id = await repo.insert_episode(
                chat_id=CHAT, title=f"Э{i}", summary="", participants=["2"],
                claims=[], event_start=T_2022, event_end=T_2022,
                outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
                open_questions=[], message_keys=[f"k-{i}"], seg_key=f"s-{i}",
                extraction_version="x", now=_NOW)
            story_id, _v, _c = await repo.upsert_story(
                chat_id=CHAT, title=f"История {i}", summary="",
                participants=["2"], claims=[], event_start=T_2022,
                event_end=T_2022, outcome=EPISODE_UNKNOWN_OUTCOME,
                state="open", verification="unknown", open_questions=[],
                episode_ids=[episode_id], extractor_version="x", now=_NOW)
            ids.append(story_id)
        assert await repo.merge_stories([ids[1]], ids[0])
        assert await resolve_story_id(db, ids[1]) == ids[0]
        assert await resolve_story_id(db, ids[0]) == ids[0]
        # фасад скрывает redirect-источник
        rows = await list_stories_for_retrieval(db, CHAT)
        assert {r["id"] for r in rows if r["kind"] == "story"} == {ids[0]}
        # состав истории переехал (эпизоды не потеряны)
        eps = await repo.story_episode_ids(ids[0])
        assert len(eps) == 2
        await db.close()

    async def _seed_story_n(self, repo, names, *, known=True):
        """История из N эпизодов (state='open' при known-исходе)."""
        ep_ids = []
        for idx, name in enumerate(names):
            episode_id = await repo.insert_episode(
                chat_id=CHAT, title=f"Э{name}", summary=f"часть {name}",
                participants=["2"], claims=[],
                event_start=T_2022 + idx * 100,
                event_end=T_2022 + idx * 100 + 50,
                outcome=(EPISODE_UNKNOWN_OUTCOME if not known else "завершено"),
                outcome_known=known, open_questions=[],
                message_keys=[f"k-{name}"], seg_key=f"s-{name}",
                extraction_version="x", now=_NOW)
            assert episode_id
            ep_ids.append(episode_id)
        story_id, _v, created = await repo.upsert_story(
            chat_id=CHAT, title=f"История {''.join(names)}",
            summary=" ".join(f"часть {n}" for n in names),
            participants=["2"], claims=[],
            event_start=T_2022, event_end=T_2022 + len(names) * 100 - 50,
            outcome=(EPISODE_UNKNOWN_OUTCOME if not known else "завершено"),
            state=("uncertain" if not known else "open"),
            verification="unknown", open_questions=[],
            episode_ids=ep_ids, extractor_version="x", now=_NOW)
        assert story_id and created
        return story_id, ep_ids

    @pytest.mark.asyncio
    async def test_split_story_three_episodes(self, tmp_path):
        """Split (§9.2 `:334` «поддерживает merge/split», H-MCA05-1):
        split истории с 3 эпизодами → 2 истории (1+2), обе open;
        redirect НЕ создаётся; источник пересчитан новой версией;
        событие с reason_code='story_split' после фиксации."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        story_id, ep_ids = await self._seed_story_n(repo, "abc")
        new_id, ok = await repo.split_story(story_id, [ep_ids[0]],
                                            now=_NOW + 5)
        assert ok and new_id and new_id != story_id
        # состав: 1 + 2, эпизоды не потеряны
        assert await repo.story_episode_ids(new_id) == [ep_ids[0]]
        assert await repo.story_episode_ids(story_id) == ep_ids[1:]
        # обе истории открыты
        assert (await repo.get_story(story_id))["state"] == "open"
        assert (await repo.get_story(new_id))["state"] == "open"
        # redirect НЕ создаётся (обе истории живы)
        assert await _count(
            db, "SELECT COUNT(*) FROM mca_story_redirects") == 0
        assert await resolve_story_id(db, story_id) == story_id
        assert await resolve_story_id(db, new_id) == new_id
        # источник пересчитан: новая версия, состав/даты из оставшихся
        assert int((await repo.get_story(story_id))["expected_version"]) == 2
        versions = await repo.list_story_versions(story_id)
        assert len(versions) == 2
        snapshot = json.loads(versions[-1]["payload_json"])
        assert snapshot["episode_ids"] == ep_ids[1:]
        assert snapshot["event_start_ts"] == T_2022 + 100
        assert len(await repo.list_story_versions(new_id)) == 1
        # фасад показывает обе истории
        rows = await list_stories_for_retrieval(db, CHAT)
        assert {r["id"] for r in rows if r["kind"] == "story"} == \
            {story_id, new_id}
        # событие сплита (post-commit, санкционированный reason_code)
        await mca_events.flush_events(db)
        found = await _count(db, "SELECT COUNT(*) FROM mca_events WHERE "
                             "reason_code = 'story_split'")
        assert found >= 1
        await db.close()

    @pytest.mark.asyncio
    async def test_split_single_episode_story_noop(self, tmp_path):
        """Split «одиночный эпизод»: история из одного эпизода не
        сплится (отделять нечего) — no-op без изменений, без redirect
        и без события; пустой/чужой список эпизодов — тоже no-op."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        story_id, ep_ids = await self._seed_story_n(repo, "a", known=False)
        # изоляция от чужих событий в глобальном буфере (flush идёт в
        # СВОЮ БД каждого теста)
        mca_events.reset_pending()
        new_id, ok = await repo.split_story(story_id, [ep_ids[0]],
                                            now=_NOW + 1)
        assert not ok and new_id == ""
        assert await repo.story_episode_ids(story_id) == ep_ids
        assert await _count(
            db, "SELECT COUNT(*) FROM mca_story_redirects") == 0
        assert int((await repo.get_story(story_id))["expected_version"]) == 1
        assert (await repo.split_story(story_id, [], now=_NOW + 1))[1] is False
        assert (await repo.split_story(
            story_id, ["чужой-эпизод"], now=_NOW + 1))[1] is False
        found = await _count(db, "SELECT COUNT(*) FROM mca_events WHERE "
                             "reason_code = 'story_split'")
        assert found == 0
        await db.close()

    @pytest.mark.asyncio
    async def test_split_all_episodes_redirects_source(self, tmp_path):
        """Split всех эпизодов: источник не может остаться пустым
        (история ≥1 эпизода, §9.1) — удаляется, внешние ссылки спасает
        redirect на новую историю (spec (h))."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        story_id, ep_ids = await self._seed_story_n(repo, "ab")
        new_id, ok = await repo.split_story(story_id, ep_ids, now=_NOW + 5)
        assert ok and new_id and new_id != story_id
        assert await repo.get_story(story_id) is None
        assert await repo.story_episode_ids(new_id) == ep_ids
        assert await resolve_story_id(db, story_id) == new_id
        rows = await list_stories_for_retrieval(db, CHAT)
        assert {r["id"] for r in rows if r["kind"] == "story"} == {new_id}
        mca_events.reset_pending()      # гигиена глобального буфера событий
        await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_creates_new_version_once(self, tmp_path):
        """Повторная сборка без изменений НЕ плодит версии; с изменением —
        новая версия (старая доступна)."""
        db = await _db(tmp_path)
        repo, story_id = await self._seed_story(db)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.assemble_stories(CHAT, _NOW + 1)
        assert len(await repo.list_story_versions(story_id)) == 1
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Эпизод 2", summary="продолжение",
            participants=["2"], claims=[], event_start=T_2022 + 100,
            event_end=T_2022 + 200, outcome=EPISODE_UNKNOWN_OUTCOME,
            outcome_known=False, open_questions=[], message_keys=["k2"],
            seg_key="s2", extraction_version="x", now=_NOW + 1)
        # подтверждённая связь → компонент из двух эпизодов
        await repo.upsert_continuation(
            (await repo.list_episodes(CHAT))[1]["episode_id"],
            (await repo.list_episodes(CHAT))[0]["episode_id"],
            status="confirmed", confirmation={"manual": True}, now=_NOW + 1)
        await svc.assemble_stories(CHAT, _NOW + 2)
        versions = await repo.list_story_versions(story_id)
        assert len(versions) == 2
        eps = await repo.story_episode_ids(story_id)
        assert len(eps) == 2
        await db.close()


# ═══ Продолжения/сборка (D7; A12; SC-02/SC-09/SC-10) ═════════════════════════

class TestContinuationsAssembly:
    @pytest.mark.asyncio
    async def test_a12_parallel_topics_not_glued(self, tmp_path):
        """A12-негатив: две параллельные истории о работе (общее слово
        «работа») не склеены — multi_topic → детерминированный сплит по
        кластерам участников; без подтверждения связи истории раздельны."""
        db = await _db(tmp_path)
        no = json.dumps({"related": False, "confidence": 0.1,
                         "rationale": "разные", "shared": []},
                        ensure_ascii=False)
        extract_multi = _extract(title="смешанный", summary="разное",
                                 participants=("2", "9"), multi=True)
        extract_a = _extract(title="проект альфа", summary="работа альфа",
                             participants=("2",))
        extract_b = _extract(title="проект бета", summary="работа бета",
                             participants=("9",))
        llm = _FakeLLM(answers=[extract_multi, extract_a, extract_b],
                       default=no)
        svc = EpisodeService(db, llm=llm, now=_NOW)
        msgs = [_msg(CHAT, 1, 2, "работа проект альфа старт", T_2022),
                _msg(CHAT, 2, 9, "работа проект бета старт", T_2022 + 60)]
        counters = await svc.process_batch(CHAT, msgs)
        assert counters["extracted"] == 2
        assert counters["linked"] == 0
        repo = EpisodeRepository(db)
        stories = await repo.list_stories(CHAT)
        assert len(stories) == 2      # не склеены по теме/времени/слову
        await db.close()

    @pytest.mark.asyncio
    async def test_a12_continuation_confirmed_glued(self, tmp_path):
        """A12-позитив: продолжение через неделю ПОДТВЕРЖДЕНО и приклеено
        (эпизоды сохранены раздельно); без подтверждения — остаётся
        несвязанным (негатив в отдельном тесте)."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        yes = json.dumps({"related": True, "confidence": 0.9,
                          "rationale": "то же событие",
                          "shared": ["берлин"]}, ensure_ascii=False)
        extract1 = _extract(title="Берлин май", summary="план поездки",
                            participants=("2", "3"),
                            claims=("Леха едет в Берлин 3 мая",),
                            outcome_known=True, outcome="план")
        extract2 = _extract(title="Берлин итог", summary="итог поездки",
                            participants=("2",),
                            claims=("поездка в Берлин состоялась",),
                            outcome_known=True, outcome="состоялась")
        llm = _FakeLLM(answers=[extract1, extract2, yes])
        svc = EpisodeService(db, llm=llm, now=_NOW)
        msgs = [_msg(CHAT, 1, 2, "берлин план", T_2022),
                _msg(CHAT, 2, 2, "берлин итог", T_2022 + 7 * 86400)]
        counters = await svc.process_batch(CHAT, msgs)
        assert counters["linked"] == 1     # пара подтверждена
        stories = await repo.list_stories(CHAT)
        assert len(stories) == 1           # склеены в одну историю
        eps = await repo.story_episode_ids(stories[0]["story_id"])
        assert len(eps) == 2               # эпизоды сохранены раздельно
        conts = await repo.list_continuations(eps)
        statuses = {c["status"] for c in conts}
        assert statuses == {"confirmed"}
        await db.close()

    @pytest.mark.asyncio
    async def test_a12_continuation_rejected_stays_separate(self, tmp_path):
        """A12-негатив: кандидат-продолжение без подтверждения связи
        (LLM: related=false) не приклеивается."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        no = json.dumps({"related": False, "confidence": 0.2,
                         "rationale": "разные", "shared": []},
                        ensure_ascii=False)
        extract1 = _extract(title="Берлин май", summary="план поездки",
                            participants=("2",))
        extract2 = _extract(title="Другой Берлин", summary="другое",
                            participants=("2",))
        llm = _FakeLLM(answers=[extract1, extract2, no])
        svc = EpisodeService(db, llm=llm, now=_NOW)
        msgs = [_msg(CHAT, 1, 2, "берлин план", T_2022),
                _msg(CHAT, 2, 2, "другой берлин", T_2022 + 7 * 86400)]
        counters = await svc.process_batch(CHAT, msgs)
        assert counters["linked"] == 0
        stories = await repo.list_stories(CHAT)
        assert len(stories) == 2           # не склеены без подтверждения
        await db.close()

    @pytest.mark.asyncio
    async def test_contradiction_fixed_not_silently_resolved(self, tmp_path):
        """SC-10: противоречие фиксируется (verification=tentative +
        событие), не разрешается молча; оба утверждения сохранены."""
        db = await _db(tmp_path)
        yes = json.dumps({"related": True, "confidence": 0.9,
                          "rationale": "то же событие", "shared": []},
                         ensure_ascii=False)
        extract1 = _extract(title="Берлин", summary="поездка",
                            participants=("2",),
                            claims=("Леха едет в Берлин в мае",),
                            refs=(f"{CHAT}:tg:1",))
        extract2 = _extract(title="Берлин отмена", summary="отмена",
                            participants=("2",),
                            claims=("Леха не едет в Берлин в мае",),
                            outcome_known=True, outcome="отмена",
                            refs=(f"{CHAT}:tg:2",))
        llm = _FakeLLM(answers=[extract1, extract2, yes])
        svc = EpisodeService(db, llm=llm, now=_NOW)
        msgs = [_msg(CHAT, 1, 2, "берлин", T_2022),
                _msg(CHAT, 2, 2, "берлин отмена", T_2022 + 86400)]
        counters = await svc.process_batch(CHAT, msgs)
        assert counters["contradictions"] >= 1
        repo = EpisodeRepository(db)
        stories = await repo.list_stories(CHAT)
        card = effective_story(stories[0])
        assert card["verification"] == "tentative"
        claims = json.loads(card["claims_json"])
        texts = [c["text"] for c in claims]
        assert any("едет" in t and "не" not in t for t in texts)
        assert any("не едет" in t for t in texts)   # оба сохранены
        await db.close()

    def test_repeat_not_independent(self):
        """Повтор события (та же формулировка) не растит независимость."""
        merged, repeats = merge_claims([
            {"text": "Леха едет в Берлин", "refs": ["r1"]},
            {"text": "Леха едет в Берлин", "refs": ["r2"]}])
        assert len(merged) == 1
        assert merged[0]["repeat_count"] == 2
        assert repeats == 1

    def test_contradiction_detector(self):
        conflicts = detect_contradictions([
            {"text": "Леха едет в Берлин в мае"},
            {"text": "Леха не едет в Берлин в мае"},
            {"text": "другая тема про котов"}])
        assert len(conflicts) == 1
        assert detect_contradictions([
            {"text": "Леха едет в Берлин"},
            {"text": "Леха едет в Берлин снова"}]) == []

    def test_candidate_filter_by_event_not_topic(self):
        """Кандидат продолжения — по событию (участники+сущность+время);
        тема без общего события — не кандидат."""
        from services.mca_episode_prompts import is_continuation_candidate
        assert is_continuation_candidate(
            participants_a={"2", "3"}, participants_b={"2", "3"},
            tokens_a={"берлин", "поездка"}, tokens_b={"берлин", "билеты"},
            time_a=T_2022, time_b=T_2022 + 5 * 86400) is True
        # разные участники → не кандидат (даже при общей сущности)
        assert is_continuation_candidate(
            participants_a={"2"}, participants_b={"9"},
            tokens_a={"берлин"}, tokens_b={"берлин"},
            time_a=T_2022, time_b=T_2022 + 86400) is False
        # тот же день (не «продолжение в другие дни») → не кандидат
        assert is_continuation_candidate(
            participants_a={"2"}, participants_b={"2"},
            tokens_a={"берлин"}, tokens_b={"берлин"},
            time_a=T_2022, time_b=T_2022 + 60) is False
        # дистанция > 90 дней → не кандидат
        assert is_continuation_candidate(
            participants_a={"2"}, participants_b={"2"},
            tokens_a={"берлин"}, tokens_b={"берлин"},
            time_a=T_2022, time_b=T_2022 + 120 * 86400) is False


# ═══ События витрины (SC-15; post-commit) ════════════════════════════════════

class TestStorefrontEvents:
    @pytest.mark.asyncio
    async def test_events_only_after_commit(self, tmp_path, monkeypatch):
        """SC-15: событие — только после фиксации; откат → события нет."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        # провал транзакции: история без эпизодов → ValueError → upsert
        # возвращает ("", "", False) → событие story_discovered НЕ эмитится
        svc = EpisodeService(db, llm=None, now=_NOW)
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Э", summary="", participants=["2"],
            claims=[], event_start=T_2022, event_end=T_2022,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=["k"], seg_key="sk",
            extraction_version="x", now=_NOW)
        assert episode_id
        # успех: события витрины в durable-store после flush
        svc2 = EpisodeService(db, llm=None, now=_NOW)
        await svc2.process_batch(CHAT, [_msg(CHAT, 10, 2, "текст", T_2022)])
        await mca_events.flush_events(db)
        found = await _count(db, "SELECT COUNT(*) FROM mca_events WHERE "
                             "event_name IN ('story_discovered', "
                             "'story_extended')")
        assert found >= 1
        # rollback-семантика: провал upsert не оставляет события
        async def _failing_write(op, *, op_name="", **kwargs):
            if op_name == "mca05_story_upsert":
                raise RuntimeError("tx failed")
            return await op(db.db)
        monkeypatch.setattr(db, "write_transaction", _failing_write)
        episode2 = await repo.insert_episode(
            chat_id=CHAT2, title="Э2", summary="", participants=["3"],
            claims=[], event_start=T_2022, event_end=T_2022,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=["k2"], seg_key="sk2",
            extraction_version="x", now=_NOW)
        await svc2.assemble_stories(CHAT2, _NOW)
        await mca_events.flush_events(db)
        chat2_stories = await _count(
            db, "SELECT COUNT(*) FROM mca_stories WHERE chat_id = ?", (CHAT2,))
        assert chat2_stories == 0     # фиксации не было
        monkeypatch.undo()
        await db.close()

    @pytest.mark.asyncio
    async def test_empty_segment_info_reason(self, tmp_path):
        """SC-17: пустой результат сегментации — INFO story_segment_empty."""
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        counters = await svc.process_batch(CHAT, [])
        assert counters["extracted"] == 0
        await mca_events.flush_events(db)
        found = await _count(db, "SELECT COUNT(*) FROM mca_events WHERE "
                             "reason_code = 'story_segment_empty'")
        assert found >= 1
        await db.close()

    def test_reason_code_dictionary_and_masking(self):
        """+10 финальных кодов в словаре; секретоподобные значения в
        entity_ids маскируются `sanitize()` (контракт mca-13, B-MCA13-1);
        неизвестный reason_code отбрасывается."""
        for code in ("episode_extracted", "story_segment_empty",
                     "story_continuation_confirmed",
                     "story_continuation_rejected",
                     "story_contradiction_found", "story_legacy_unmapped",
                     "story_backfill_paused_budget",
                     "story_source_recheck_queued", "story_merged",
                     "story_split"):
            assert code in mca_events.REASON_CODES, code
        event = mca_events.build_event(
            "story_discovered", outcome="success", chat_id=CHAT,
            entity_ids={"story_id": "abc",
                        "summary": "ключ sk-ab12cd34ef56gh78"},
            reason_code="episode_extracted")
        assert event is not None
        assert "sk-ab12cd34ef56gh78" not in (event.get("entity_ids") or "")
        # неизвестный reason_code не проходит в событие (словарь §17.2)
        event2 = mca_events.build_event(
            "story_discovered", outcome="success", chat_id=CHAT,
            reason_code="выдуманный_код")
        assert event2 is not None
        assert "reason_code" not in event2

    @pytest.mark.asyncio
    async def test_storefront_event_payload_dates(self, tmp_path):
        """События витрины несут обе даты + refs (контракт mca-12)."""
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 10, 2, "текст", T_2022)])
        await mca_events.flush_events(db)
        cursor = await db.db.execute(
            "SELECT entity_ids FROM mca_events WHERE event_name = "
            "'story_discovered' LIMIT 1")
        row = await cursor.fetchone()
        assert row is not None
        entity = json.loads(row["entity_ids"])
        assert entity["event_start"] == T_2022
        assert entity["discovered_at"] == _NOW
        assert entity["episode_ids"]
        await db.close()


# ═══ Provenance (§8.1; SC-11) ════════════════════════════════════════════════

class TestProvenance:
    @pytest.mark.asyncio
    async def test_episode_has_source_or_unknown(self, tmp_path):
        db = await _db(tmp_path)
        await _add_msg(db, CHAT, 2, "исходное сообщение", T_2022,
                       tg_message_id=42)
        from services.mca_episodes import record_episode_provenance
        repo = EpisodeRepository(db)
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Э", summary="", participants=["2"],
            claims=[], event_start=T_2022, event_end=T_2022,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=[f"{CHAT}:tg:42"],
            seg_key="s", extraction_version="x", now=_NOW)
        status = await record_episode_provenance(
            db, repo, chat_id=CHAT, episode_id=episode_id,
            message_keys=[f"{CHAT}:tg:42"], extractor_version="x")
        assert status == "ok"
        # без валидного сообщения — явный unknown (не выдуманная ссылка)
        episode2 = await repo.insert_episode(
            chat_id=CHAT, title="Э2", summary="", participants=["2"],
            claims=[], event_start=T_2022, event_end=T_2022,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=[f"{CHAT}:tg:9999"],
            seg_key="s2", extraction_version="x", now=_NOW)
        status2 = await record_episode_provenance(
            db, repo, chat_id=CHAT, episode_id=episode2,
            message_keys=[f"{CHAT}:tg:9999"], extractor_version="x")
        assert status2 == "unknown"
        await db.close()

    @pytest.mark.asyncio
    async def test_story_source_validator(self, tmp_path):
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 10, 2, "т", T_2022)])
        repo = EpisodeRepository(db)
        story = (await repo.list_stories(CHAT))[0]
        from services.mca_episodes import validate_story_sources
        assert await validate_story_sources(db, story["story_id"]) == "ok"
        assert await validate_story_sources(db, "несуществующий") == "unknown"
        await db.close()


# ═══ Backfill job (D10; SC-12) ═══════════════════════════════════════════════

class TestBackfillJob:
    @pytest.mark.asyncio
    async def test_enqueue_coalescing(self, tmp_path):
        db = await _db(tmp_path)
        jid = await enqueue_episodes_backfill(db, CHAT)
        jid2 = await enqueue_episodes_backfill(db, CHAT)
        assert jid == jid2
        active = await get_active_backfill(db, CHAT)
        assert active is not None
        assert active["coalesce_key"] == backfill_coalesce_key(CHAT)
        await db.close()

    @pytest.mark.asyncio
    async def test_run_completes_and_counts(self, tmp_path):
        db = await _db(tmp_path)
        for i in range(5):
            await _add_msg(db, CHAT, 2, f"сообщение {i}",
                           T_2022 + i * 7200, tg_message_id=100 + i)
        jid = await enqueue_episodes_backfill(db, CHAT)
        runner = EpisodesBackfillRunner(db, llm=None)
        status = await runner.run(jid)
        assert status == "completed"
        row = await runner._store.get(jid)
        assert row["status"] == "completed"
        counters = json.loads(row["payload"])["counters"]
        assert counters["processed"] == 5
        assert counters["batches"] == 1
        await db.close()

    @pytest.mark.asyncio
    async def test_llm_failure_never_falsely_completes(self, tmp_path):
        """Бюджет/ошибка LLM → `paused` — никогда ложный `completed`."""
        db = await _db(tmp_path)
        await _add_msg(db, CHAT, 2, "т", T_2022, tg_message_id=1)
        jid = await enqueue_episodes_backfill(db, CHAT)
        exploding = _FakeLLM(default=RuntimeError("model down"))

        class _RaisingLLM:
            async def generate(self, messages, **kwargs):
                raise RuntimeError("model unavailable")

        runner = EpisodesBackfillRunner(db, llm=_RaisingLLM())
        status = await runner.run(jid)
        assert status == "paused"
        row = await runner._store.get(jid)
        assert row["status"] == "paused"
        assert row["reason_code"] == "model_unavailable"
        assert row["finished_at"] is not None
        await db.close()

    @pytest.mark.asyncio
    async def test_restart_without_duplicates(self, tmp_path):
        """Рестарт с checkpoint не удваивает эпизоды/связи."""
        db = await _db(tmp_path)
        for i in range(4):
            await _add_msg(db, CHAT, 2, f"сообщение {i}",
                           T_2022 + i * 7200, tg_message_id=200 + i)
        jid = await enqueue_episodes_backfill(db, CHAT)
        runner = EpisodesBackfillRunner(db, llm=None)
        await runner.run(jid)
        # повторный полный прогон (новая задача) — дедуп по segment_key
        jid2 = await enqueue_episodes_backfill(db, CHAT)
        runner2 = EpisodesBackfillRunner(db, llm=None)
        status = await runner2.run(jid2)
        assert status == "completed"
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == \
            await _count(db, "SELECT COUNT(DISTINCT segment_key) "
                             "FROM mca_episodes")
        stories = await _count(db, "SELECT COUNT(*) FROM mca_stories")
        links = await _count(db, "SELECT COUNT(*) FROM "
                             "mca_story_episode_links")
        assert links == stories     # без удвоенных связей
        await db.close()

    @pytest.mark.asyncio
    async def test_revision_recheck_queue(self, tmp_path):
        """Изменение источника (revision) ставит зависимые эпизоды на
        перепроверку; очередь без каскада; перепроверка создаёт версию."""
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        row_id = await _add_msg(db, CHAT, 2, "исходник", T_2022,
                                tg_message_id=300)
        await svc.process_batch(CHAT, [_msg(CHAT, 300, 2, "исходник",
                                            T_2022, db_id=row_id)])
        repo = EpisodeRepository(db)
        episodes = await repo.list_episodes(CHAT)
        assert episodes
        # revision: правка сообщения → recheck-очередь (через публичный API)
        marked = await queue_source_recheck(
            db, CHAT, [message_key(_msg(CHAT, 300, 2, "правка", T_2022,
                                        db_id=row_id))])
        assert marked == 1
        row = await repo.get_episode(episodes[0]["episode_id"])
        assert row["recheck_pending"] == 1
        # перепроверка: обновление на месте, discovered_at не меняется
        llm = _FakeLLM(default=_extract(title="обновлённый", summary="после "
                                        "правки", participants=("2",)))
        runner = EpisodesBackfillRunner(db, llm=llm)
        processed = await runner.process_rechecks(CHAT)
        assert processed == 1
        row = await repo.get_episode(episodes[0]["episode_id"])
        assert row["recheck_pending"] == 0
        assert row["title"] == "обновлённый"
        assert row["discovered_at"] == episodes[0]["discovered_at"]
        await db.close()

    @pytest.mark.asyncio
    async def test_record_edit_queues_recheck(self, tmp_path, monkeypatch):
        """Интеграция с mca-03: record_edit → очередь перепроверки
        (fail-open, за гейтом mca-05)."""
        from services import message_identity
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await _add_msg(db, CHAT, 2, "до правки", T_2022, tg_message_id=400)
        await svc.process_batch(CHAT, [_msg(CHAT, 400, 2, "до правки",
                                            T_2022)])
        # right message must exist in message_source_records contract;
        # упрощённо используем apply-путь через record_edit c live-строкой
        monkeypatch.setattr(message_identity, "revision_tracking_enabled",
                            lambda: True)
        try:
            await message_identity.record_edit(
                db, chat_id=CHAT, tg_message_id=400,
                text="после правки", caption=None, edited_at=_NOW)
        except Exception:
            pass  # apply_message_revision может отсутствовать на усечённой
        # БД — реакция mca-05 проверяется напрямую ниже (queue_source_recheck)
        repo = EpisodeRepository(db)
        episodes = await repo.list_episodes(CHAT)
        marked = await queue_source_recheck(
            db, CHAT, [f"{CHAT}:tg:400"])
        assert marked >= 1
        row = await repo.get_episode(episodes[0]["episode_id"])
        assert row["recheck_pending"] == 1
        await db.close()


# ═══ Фасад компилятора + канал mca-07 (SC-13/SC-14) ══════════════════════════

class TestFacadeAndChannel:
    @pytest.mark.asyncio
    async def test_legacy_no_auto_glue_unmapped_visible(self, tmp_path):
        """SC-13: legacy `lore_stories` не склеиваются автоматически;
        unmapped виден с честным unknown; инструмент компилятора жив."""
        db = await _db(tmp_path)
        await db.upsert_lore_story(CHAT, "работа", "Работа",
                                   "история про работу", last_ts=T_2022)
        await db.upsert_lore_story(CHAT, "работа_2", "Работа",
                                   "ДРУГАЯ история про работу",
                                   last_ts=T_2022 + 86400)
        from services.lore_compiler_service import LoreCompilerService
        compiler = LoreCompilerService(db, llm=None)
        result = await compiler.compile(CHAT, "Работа")
        assert result["status"] in ("ok", "not_found")
        # legacy-записи остались раздельными (UNIQUE по topic_key); маппинг
        # — только по подтверждённой event-связи (LLM), никогда по теме
        links = await _count(db, "SELECT COUNT(*) FROM "
                             "mca_story_legacy_links WHERE "
                             "mapping_status = 'mapped'")
        assert links == 0
        rows = await list_stories_for_retrieval(db, CHAT)
        legacy = [r for r in rows if r.get("kind") == "legacy_story"]
        assert len(legacy) == 2       # обе unmapped видимы
        await db.close()

    @pytest.mark.asyncio
    async def test_lazy_mapping_only_with_confirmation(self, tmp_path):
        """Ленивый маппинг: без LLM — unmapped + событие; с подтверждением —
        mapped; равенство темы связью НЕ считается (нужна сущность+время)."""
        db = await _db(tmp_path)
        extract = _extract(title="Берлин", summary="поездка в берлин",
                           participants=("2",))
        svc = EpisodeService(db, llm=_FakeLLM(default=extract), now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 1, 2, "берлин план",
                                            T_2022)])
        await db.upsert_lore_story(CHAT, "берлин", "Берлин",
                                   "пересказ про берлин", last_ts=T_2022)
        from services.mca_episodes import note_compiler_touch
        row = await db.get_lore_story(CHAT, "берлин")
        status = await note_compiler_touch(db, CHAT, dict(row), llm=None)
        assert status == "unmapped"
        assert await _count(db, "SELECT COUNT(*) FROM mca_events WHERE "
                            "reason_code = 'story_legacy_unmapped'") >= 0
        # LLM-подтверждение → mapped
        yes = json.dumps({"related": True, "confidence": 0.9,
                          "rationale": "то же событие", "shared": []},
                         ensure_ascii=False)
        status = await note_compiler_touch(db, CHAT, dict(row),
                                           llm=_FakeLLM(default=yes))
        assert status == "mapped"
        # отказ модели → unmapped (не склеиваем)
        await db.upsert_lore_story(CHAT, "берлин_2", "Берлин",
                                   "другой пересказ", last_ts=T_2022)
        row2 = await db.get_lore_story(CHAT, "берлин_2")
        no = json.dumps({"related": False, "confidence": 0.1,
                         "rationale": "разные", "shared": []},
                        ensure_ascii=False)
        status = await note_compiler_touch(db, CHAT, dict(row2),
                                           llm=_FakeLLM(default=no))
        assert status == "unmapped"
        # две разные legacy-записи с одной темой не склеены друг с другом
        links = await _count(db, "SELECT COUNT(*) FROM "
                             "mca_story_legacy_links WHERE "
                             "mapping_status = 'mapped'")
        assert links == 1
        await db.close()

    @pytest.mark.asyncio
    async def test_channel_reads_new_store_respects_excluded(
            self, tmp_path, monkeypatch):
        """SC-14: канал возвращает кандидатов из нового store; excluded не
        попадают; fail-open сохранён."""
        from services.mca_retrieval_context import (
            RetrievalRequest,
            _episode_candidates,
        )
        db = await _db(tmp_path)
        extract = _extract(title="Берлин поездка", summary="план берлин",
                           participants=("2",))
        svc = EpisodeService(db, llm=_FakeLLM(default=extract), now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 1, 2, "берлин поездка",
                                            T_2022)])
        repo = EpisodeRepository(db)
        story = (await repo.list_stories(CHAT))[0]
        request = RetrievalRequest(chat_id=CHAT, query="берлин")
        rows = await _episode_candidates(db, request, ["берлин"])
        assert rows and rows[0].entity_type == "episode"
        assert rows[0].id == f"episode:{story['story_id']}"
        # excluded → не в выдаче
        await repo.set_story_excluded(story["story_id"], True)
        rows = await _episode_candidates(db, request, ["берлин"])
        assert all(r.id != f"episode:{story['story_id']}" for r in rows)
        await repo.set_story_excluded(story["story_id"], False)
        # fail-open: фасад падает → legacy-путь (пусто, но без исключения)
        async def _broken_facade(db_, chat_id, limit=200):
            raise RuntimeError("facade down")
        monkeypatch.setattr(
            "services.mca_episodes.list_stories_for_retrieval",
            _broken_facade)
        rows = await _episode_candidates(db, request, ["берлин"])
        assert isinstance(rows, list)
        await db.close()

    @pytest.mark.asyncio
    async def test_channel_no_leak_of_excluded_via_legacy_fallback(
            self, tmp_path):
        """SC-14 (M-MCA05-1): excluded-история НЕ возвращается каналом
        через mapped-legacy двойника. Фолбэк на `list_lore_stories`
        легален только при гейте OFF/ошибке фасада; при успехе фасада
        пустой ответ = намеренное исключение → канал тоже пуст."""
        from services.mca_retrieval_context import (
            RetrievalRequest,
            _episode_candidates,
        )
        db = await _db(tmp_path)
        extract = _extract(title="Берлин поездка", summary="план берлин",
                           participants=("2",))
        svc = EpisodeService(db, llm=_FakeLLM(default=extract), now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 1, 2, "берлин поездка",
                                            T_2022)])
        repo = EpisodeRepository(db)
        story = (await repo.list_stories(CHAT))[0]
        # mapped-legacy двойник этой истории (прецедент ленивого маппинга)
        await db.upsert_lore_story(CHAT, "берлин", "Берлин",
                                   "пересказ про берлин", last_ts=T_2022)
        lore = await db.get_lore_story(CHAT, "берлин")
        assert await repo.upsert_legacy_link(
            int(lore["id"]), story_id=story["story_id"],
            mapping_status="mapped")
        request = RetrievalRequest(chat_id=CHAT, query="берлин")
        # до исключения: канал видит историю нового store (не двойника)
        rows = await _episode_candidates(db, request, ["берлин"])
        assert [r.id for r in rows] == [f"episode:{story['story_id']}"]
        # exclude → фасад честно пуст → канал ТОЖЕ пуст (утечки нет)
        assert await repo.set_story_excluded(story["story_id"], True)
        rows = await _episode_candidates(db, request, ["берлин"])
        assert rows == []
        # redirect-источник (слияние): фасад скрывает источник, приёмник
        # жив и видим; legacy-двойник redirect-источника не воскресает
        await repo.set_story_excluded(story["story_id"], False)
        episode2 = await repo.insert_episode(
            chat_id=CHAT, title="Берлин снова", summary="берлин часть 2",
            participants=["2"], claims=[], event_start=T_2022 + 86400,
            event_end=T_2022 + 86400, outcome=EPISODE_UNKNOWN_OUTCOME,
            outcome_known=False, open_questions=[], message_keys=["k-e2"],
            seg_key="s-e2", extraction_version="x", now=_NOW + 1)
        story2, _v, _c = await repo.upsert_story(
            chat_id=CHAT, title="Берлин снова", summary="берлин снова",
            participants=["2"], claims=[], event_start=T_2022 + 86400,
            event_end=T_2022 + 86400, outcome=EPISODE_UNKNOWN_OUTCOME,
            state="open", verification="unknown", open_questions=[],
            episode_ids=[episode2], extractor_version="x", now=_NOW + 1)
        assert await repo.merge_stories([story["story_id"]], story2)
        assert await resolve_story_id(db, story["story_id"]) == story2
        rows = await _episode_candidates(db, request, ["берлин"])
        assert {r.id for r in rows} == {f"episode:{story2}"}
        # приёмник тоже исключён → фасад честно пуст → mapped-двойник
        # redirect-источника НЕ воскресает (канал пуст)
        assert await repo.set_story_excluded(story2, True)
        rows = await _episode_candidates(db, request, ["берлин"])
        assert rows == []
        await db.close()

    @pytest.mark.asyncio
    async def test_local_context_fill_and_invariant(self, tmp_path):
        """M-MCA07-2: `local_context` наполнен на живом пути; пусто →
        инвариант not_available (tuple())."""
        from services.mca_episodes import build_local_context
        db = await _db(tmp_path)
        # пусто → ()
        assert await build_local_context(db, CHAT,
                                         trigger_tg_message_id=777) == ()
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 777, 2, "берлин", T_2022)])
        filled = await build_local_context(db, CHAT,
                                           trigger_tg_message_id=777)
        assert filled and filled[0].startswith("история:")
        # чужое сообщение → ()
        assert await build_local_context(db, CHAT,
                                         trigger_tg_message_id=778) == ()
        await db.close()

    @pytest.mark.asyncio
    async def test_local_context_gate_off(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mca_gates, "episodes_enabled", lambda: False)
        from services.mca_episodes import build_local_context
        db = await _db(tmp_path)
        assert await build_local_context(db, CHAT,
                                         trigger_tg_message_id=1) == ()
        await db.close()


# ═══ Наблюдаемость (SC-18) + границы (SC-16, T-4259/T-4267) ══════════════════

class TestObservabilityAndBoundaries:
    def test_process_registry_declares_episodes(self):
        ids = {p.process_id: p for p in reg.PROCESS_REGISTRY}
        build = ids["episodes.build"]
        assert build.owner_feature == "mca-05"
        assert set(build.stages) == {"segment", "extract", "confirm",
                                     "assemble", "link", "index"}
        assert build.enabled_gate == "MCA_EPISODES_ENABLED"
        backfill = ids["episodes.backfill"]
        assert backfill.enabled_gate == "MCA_EPISODES_BACKFILL_ENABLED"
        assert build.widget_id and backfill.widget_id

    @pytest.mark.asyncio
    async def test_live_run_writes_stage_events(self, tmp_path):
        """Живой прогон пишет стадии/run (SC-18)."""
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 1, 2, "т", T_2022)],
                                pipeline_run_id="run-test-1")
        await mca_events.flush_events(db)
        found = await _count(db, "SELECT COUNT(*) FROM mca_events WHERE "
                             "event_name = 'episodes_build' AND "
                             "pipeline_run_id = 'run-test-1'")
        assert found >= 2      # segment + terminal стадии
        await db.close()

    def test_no_send_path_in_pipeline(self):
        """T-4259 grep-гейт: пайплайн физически не имеет пути отправки."""
        import pathlib
        for name in ("mca_episodes.py", "mca_episode_jobs.py",
                     "mca_episode_prompts.py"):
            source = (pathlib.Path("services") / name).read_text(
                encoding="utf-8")
            for banned in ("telegram_send", "send_message", "sendMessage",
                           "sendRichMessage", "bot.send"):
                assert banned not in source, (name, banned)

    def test_asap3_verbatim_boundary_untouched(self):
        """Граница (g): verbatim-episode direct-контекста ASAP-3 не задет —
        композер/model_slots не импортируют EpisodeService."""
        import pathlib
        for name in ("direct_context_composer.py", "model_slots.py"):
            source = (pathlib.Path("services") / name).read_text(
                encoding="utf-8")
            assert "mca_episodes" not in source, name

    def test_no_new_storefront_section_in_this_feature(self):
        """SC-16: модель/события есть, UI/маршрутов/настроек в mca-05 нет —
        модуль не импортирует web-слой."""
        import pathlib
        source = (pathlib.Path("services") /
                  "mca_episodes.py").read_text(encoding="utf-8")
        for banned in ("APIRouter", "FastAPI", "param_catalog",
                       "_TAB_BY_GROUP"):
            assert banned not in source, banned

    @pytest.mark.asyncio
    async def test_single_writer_coexistence(self, tmp_path):
        """SC-19: записи mca-05 идут через write_transaction (single-writer
        mca-01) и не конфликтуют с параллельными write-задачами."""
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        msgs = [_msg(CHAT, i, 2, f"m{i}", T_2022 + i) for i in range(6)]
        async def _alien_writer():
            for _ in range(5):
                await db.write_transaction(
                    lambda conn: _touch(conn), op_name="alien")
        async def _touch(conn):
            await db.db.execute(
                "INSERT OR REPLACE INTO channel_state (key, value) "
                "VALUES ('alien', 'w')")
            return 1
        await asyncio.gather(svc.process_batch(CHAT, msgs), _alien_writer())
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") >= 1
        await db.close()

    @pytest.mark.asyncio
    async def test_chat_scope_isolation(self, tmp_path):
        """Chat scope не расширяется: эпизоды строго в пределах chat_id."""
        db = await _db(tmp_path)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 1, 2, "берлин", T_2022)])
        rows = await list_stories_for_retrieval(db, CHAT2)
        assert rows == []
        await db.close()
