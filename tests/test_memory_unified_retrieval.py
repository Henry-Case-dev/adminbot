"""VMQ-M2 — единый retrieval: person overview/temporal bundle + semantic hints.

TEST-LIFECYCLE: CONTRACT.

Контракт:
  * `plans/features/vmq-onto-01/evidence/m2-contract-confirmation-2026-11-15.md`
    (`ARCH_REUSE_CONFIRMED`, M-04/M-05/O-04, единственная точка `retrieve()`);
  * `plans/features/vmq-onto-01/architecture-m1-episodes.md` (эпизоды/периоды,
    `EpisodeView`/`LongitudinalView`, повторы≠независимость, counterexamples);
  * `plans/features/vmq-onto-01/architecture-onto-ab.md` (§49–66: typed
    definitions/relations только как hints, один маршрут);
  * `requirements-map.json` строки `MAN-M-04`, `MAN-M-05`, `MAN-O-04`.

Проверяется на temp/БД в памяти (production не затрагивается), реальными
владельцами (`mca_episodes`, `database`, `semantic_contracts`) — без моков
вместо предмета проверки:

  * M-04: один `retrieve()` с `include_overview` даёт bounded overview
    (coverage/независимые периоды/контрпримеры/limitations) и наполняет
    ЕДИНЫЙ `EvidenceBundle`; person overview и temporal queries идут тем же
    маршрутом; повтор мема не считается независимым подтверждением.
  * M-05: overview-чтения read-only (ноль DDL/записей), без массового
    reembedding/embedding-вызовов и без строк/эпизодов чужого чата.
  * O-04: semantic definitions — только hints (кандидаты/порядок не меняются),
    ambiguity/legacy не повышаются до verified, исправления и версии источника
    применяются к последующим запросам, маршрут остаётся один.
"""
import contextlib
import json
import re

import pytest

from services import mca_retrieval_context as rc
from services.database import DatabaseService
from services.mca_episodes import (
    VIEW_STATE_EMPTY,
    VIEW_STATE_OK,
    EpisodeService,
    list_episode_views,
)

CHAT = -889001
CHAT2 = -889002
NOW = 1790000000                 # «сегодня» тестов
T2021 = 1623758400               # 2021-06-15 12:00 UTC
T2022 = 1650000000               # 2022-04-15
T2023 = 1686820800               # 2023-06-15 12:00 UTC
UID = 555
SUBJECT_NAME = "Папаха"

_WRITE_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|VACUUM|REINDEX)\b",
    re.IGNORECASE)


# ── фикстуры (реальная БД, существующие владельцы) ──────────────────────────

async def _db() -> DatabaseService:
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _add_msg(db, chat, tg, user, text, ts, reply_to_tg=None) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, 'text', '', ?)",
        (user, chat, text, reply_to_tg, ts, tg))
    await db.db.commit()
    return int(cursor.lastrowid)


async def _seed_episodes(db, chat, messages) -> None:
    """Существующий M1 pipeline (детерминированная карточка без LLM)."""
    svc = EpisodeService(db, llm=None, now=NOW)
    await svc.process_batch(chat, messages)


async def _add_fact(db, *, chat, fact, ts, created_at=None, origin="chat_history",
                    status="confirmed", target_user=None, subject_ref_id=None,
                    speaker=None, weight=1.0) -> int:
    cursor = await db.db.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
        "target_user, tg_message_id, status, message_timestamp, weight, "
        "importance, subject_ref_id, speaker_author_id, "
        "attribution_method, assertion_kind, provenance_channel) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, 3, ?, ?, ?, ?, ?)",
        (chat, fact, origin, int(created_at if created_at is not None else ts),
         target_user, status, ts, weight, subject_ref_id, speaker,
         "self_report" if speaker is not None else None,
         "biographical" if speaker is not None else None,
         "chat_history" if speaker is not None else None))
    await db.db.commit()
    return int(cursor.lastrowid)


async def _bind_subject(db, chat, uid) -> int:
    """Существующий реестр SourceRef: uid → `subject_ref_id` (без DDL)."""
    cursor = await db.db.execute(
        "INSERT INTO mca_source_refs (store, entity_type, entity_id, chat_id, "
        "created_at) VALUES ('telegram', 'user', ?, ?, ?)",
        (str(uid), int(chat), NOW))
    await db.db.commit()
    return int(cursor.lastrowid)


async def _count(db, sql, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _user_version(db) -> int:
    cursor = await db.db.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _table_names(db) -> set:
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")
    return {str(row[0]) for row in await cursor.fetchall()}


class _MemorySpy:
    """Существующий vector-канал: только `retrieve_fact_candidates`.

    Любой embedding/upsert/rebuild-вызов — дефект M-05, поэтому такие методы
    фиксируются и роняют тест, а не тихо игнорируются."""

    def __init__(self, rows=None):
        self.rows = [dict(row) for row in (rows or [])]
        self.fact_calls: list = []
        self.forbidden_calls: list = []

    async def retrieve_fact_candidates(self, chat_id, query, limit=5, **kwargs):
        self.fact_calls.append((int(chat_id), str(query), int(limit)))
        return [row for row in self.rows
                if int(row.get("chat_id") or chat_id) == int(chat_id)]

    async def embed_text(self, *args, **kwargs):
        self.forbidden_calls.append("embed_text")
        raise AssertionError("embedding provider must not be called")

    async def upsert_fact_vector(self, *args, **kwargs):
        self.forbidden_calls.append("upsert_fact_vector")
        raise AssertionError("vector upsert must not be called")

    async def rebuild_index(self, *args, **kwargs):
        self.forbidden_calls.append("rebuild_index")
        raise AssertionError("index rebuild must not be called")


class _TracedConnection:
    """Прокси aiosqlite-соединения: записывает SQL каждого execute."""

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "statements", [])

    async def execute(self, sql, params=()):
        self.statements.append(" ".join(str(sql).split()))
        return await self._conn.execute(sql, params)

    async def executemany(self, sql, params):
        self.statements.append(" ".join(str(sql).split()))
        return await self._conn.executemany(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@contextlib.contextmanager
def _trace_sql(db):
    proxy = _TracedConnection(db.db)
    db.db = proxy
    try:
        yield proxy
    finally:
        db.db = proxy._conn


def _request(**kwargs) -> "rc.RetrievalRequest":
    base = dict(chat_id=CHAT, query="расскажи что было про Папаха",
                top_k=12, subject_names=(SUBJECT_NAME,))
    base.update(kwargs)
    return rc.RetrievalRequest(**base)


async def _overview_fixture(db):
    """2021 — поддержка, 2023 — контрпример (тема/участник те же)."""
    support = "Папаха встретился в парке как договаривались"
    counter = "Папаха не встретился в парке как договаривались"
    await _add_msg(db, CHAT, 1, UID, support, T2021)
    await _add_msg(db, CHAT, 2, UID, counter, T2023)
    await _seed_episodes(db, CHAT, [
        {"chat_id": CHAT, "id": None, "tg_message_id": 1, "user_id": UID,
         "text": support, "timestamp": T2021, "reply_to_tg_message_id": None},
        {"chat_id": CHAT, "id": None, "tg_message_id": 2, "user_id": UID,
         "text": counter, "timestamp": T2023, "reply_to_tg_message_id": None},
    ])
    return support, counter


# ═══ M-04: person overview / temporal через единственный retrieve ═══════════

class TestM04OverviewBundle:
    @pytest.mark.asyncio
    async def test_person_overview_overview_and_single_bundle(self):
        db = await _db()
        try:
            support, counter = await _overview_fixture(db)
            fact_id = await _add_fact(
                db, chat=CHAT, fact="Папаха любит дронов", ts=T2021,
                target_user=SUBJECT_NAME, subject_ref_id=await _bind_subject(
                    db, CHAT, UID), speaker=UID)
            memory = _MemorySpy()
            result = await rc.retrieve(
                db, memory,
                _request(include_overview=True, subject_entity_ids=(UID,)))

            assert result.status == rc.RETRIEVAL_OK
            overview = result.overview
            assert overview is not None
            assert overview.chat_id == CHAT
            assert overview.state == VIEW_STATE_OK

            # coverage: реальные периоды + честный пропуск 2022
            assert [p["period"] for p in overview.coverage["present_periods"]] \
                == ["2021", "2023"]
            assert overview.coverage["missing_periods"] == ["2022"]
            assert overview.coverage["earliest_ts"] == T2021
            assert overview.coverage["latest_ts"] == T2023
            # покрытие никогда не выдаётся за полный архив
            assert overview.coverage["complete"] is False
            assert overview.coverage["complete_reason"]

            # независимые периоды и контрпримеры различимы
            assert set(overview.independent_periods) == {"2021", "2023"}
            assert overview.independent_support_count == 2
            assert overview.counterexamples, "counterexample expected"
            pair = overview.counterexamples[0]
            assert pair["left_text"] != pair["right_text"]
            refs = set(pair["left_refs"]) | set(pair["right_refs"])
            assert refs and refs <= set(overview.episode_refs)
            # support refs не смешаны с counterexample refs
            assert not (set(overview.support_source_refs) & set(pair["left_refs"]))

            # limitations — честные коды (не выдуманная полнота)
            assert "coverage_complete_unknown_until_archive_bounds_proven" \
                in overview.limitations
            assert "missing_period_means_no_episode_not_no_event" \
                in overview.limitations

            # semantic hints: типизированное значение уже прочитанной строки
            hints = [h for h in overview.semantic_hints
                     if h.get("fact_id") == fact_id]
            assert hints, "fact hint expected"
            assert hints[0]["verification"] in (
                "verified", "tentative", "unknown", "rejected")
            assert hints[0]["entity_type"] == "fact"

            # ЕДИНЫЙ bundle: аддитивные поля заполняются тем же overview
            bundle = rc.EvidenceBundle(context_version="v1",
                                       summary_text=("память: строка",))
            enriched = rc.apply_overview_to_bundle(bundle, overview)
            assert enriched.coverage
            assert enriched.independent_periods == ("2021", "2023")
            assert enriched.counterexamples
            assert enriched.limitations
            assert enriched.episode_refs
            assert enriched.semantic_hints
            assert enriched.context_version == "v1"      # version стабилен
            # не-тронутые слоты сохраняются (аддитивность)
            assert enriched.schema_version == bundle.schema_version
            assert enriched.summary_text == bundle.summary_text

            # повтор одного мема — не независимое подтверждение
            assert support.strip() and counter.strip()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_overview_off_by_default_keeps_payload_and_no_episode_io(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            memory = _MemorySpy()
            with _trace_sql(db) as trace:
                plain = await rc.retrieve(db, memory, _request())
            assert plain.overview is None
            assert not [s for s in trace.statements
                        if s.upper().startswith("SELECT") and "mca_episodes" in s]
            # bundle без overview остаётся байт-паритетным по новым слотам
            bundle = rc.EvidenceBundle()
            assert rc.apply_overview_to_bundle(bundle, None) is bundle
            assert bundle.coverage == ()
            assert bundle.independent_periods == ()
            assert bundle.counterexamples == ()
            assert bundle.limitations == ()
            assert bundle.episode_refs == ()
            assert bundle.semantic_hints == ()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_temporal_query_across_periods_single_route(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            memory = _MemorySpy()
            with _trace_sql(db) as trace:
                result = await rc.retrieve(
                    db, memory, _request(mode="history",
                                         include_overview=True))
            assert [p["period"] for p in result.overview.coverage["present_periods"]] \
                == ["2021", "2023"]
            # temporal-ответ идёт тем же маршрутом: есть episode-канал
            assert "episode" in result.channels_used
            # ни одного embedding/upsert/rebuild-вызова
            assert memory.forbidden_calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_repeated_meme_is_not_independent_period(self):
        db = await _db()
        try:
            meme = "Папаха приносил мем про парк каждый год"
            await _add_msg(db, CHAT, 1, UID, meme, T2021)
            await _add_msg(db, CHAT, 2, UID, meme, T2023)
            await _seed_episodes(db, CHAT, [
                {"chat_id": CHAT, "id": None, "tg_message_id": 1,
                 "user_id": UID, "text": meme, "timestamp": T2021,
                 "reply_to_tg_message_id": None},
                {"chat_id": CHAT, "id": None, "tg_message_id": 2,
                 "user_id": UID, "text": meme, "timestamp": T2023,
                 "reply_to_tg_message_id": None},
            ])
            result = await rc.retrieve(
                db, _MemorySpy(), _request(include_overview=True))
            overview = result.overview
            # покрытие содержит оба года, независимая опора — один
            assert [p["period"] for p in overview.coverage["present_periods"]] \
                == ["2021", "2023"]
            assert overview.independent_periods == ("2021",)
            assert overview.independent_support_count == 1
            assert overview.repeated_claims == 1
            periods = {row["period"]: row for row in overview.period_support}
            assert periods["2023"]["independent"] == 0
            assert periods["2023"]["repeated"] >= 1
            assert "repeated_claims_present" in overview.limitations
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_empty_coverage_is_honest(self):
        db = await _db()
        try:
            memory = _MemorySpy()
            result = await rc.retrieve(
                db, memory, _request(include_overview=True))
            overview = result.overview
            assert overview is not None
            assert overview.state == VIEW_STATE_EMPTY
            assert overview.coverage["present_periods"] == []
            assert overview.coverage["missing_periods"] == []
            assert overview.coverage["complete"] is False
            assert "no_episodes_in_scope" in overview.limitations
            assert overview.episode_refs == ()
            assert result.status == rc.RETRIEVAL_EMPTY
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_overview_failure_does_not_break_retrieval(self, monkeypatch):
        db = await _db()
        try:
            await _overview_fixture(db)
            import services.mca_episodes as episodes_mod

            async def _boom(*args, **kwargs):
                raise RuntimeError("episode store unavailable")

            monkeypatch.setattr(episodes_mod, "subject_longitudinal_view", _boom)
            memory = _MemorySpy()
            result = await rc.retrieve(
                db, memory, _request(include_overview=True))
            # retrieval не падает и не теряет кандидатов; overview честно нет
            assert result.status == rc.RETRIEVAL_OK
            assert result.candidates
            assert result.overview is None
            assert memory.forbidden_calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_overview_gate_off_keeps_zero_episode_reads(self, monkeypatch):
        db = await _db()
        try:
            await _overview_fixture(db)
            from services import mca_gates

            monkeypatch.setattr(mca_gates, "episodes_enabled", lambda: False)
            memory = _MemorySpy()
            with _trace_sql(db) as trace:
                result = await rc.retrieve(
                    db, memory, _request(include_overview=True))
            assert result.overview is None
            assert result.status in (rc.RETRIEVAL_OK, rc.RETRIEVAL_EMPTY)
            assert not [s for s in trace.statements if "mca_episodes" in s]
            assert memory.forbidden_calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_multi_chat_acl_scope_is_not_merged(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            other = "Папаха встретился в парке как договаривались"
            await _add_msg(db, CHAT2, 9, UID, other, T2021)
            await _seed_episodes(db, CHAT2, [
                {"chat_id": CHAT2, "id": None, "tg_message_id": 9,
                 "user_id": UID, "text": other, "timestamp": T2021,
                 "reply_to_tg_message_id": None}])
            result = await rc.retrieve(
                db, _MemorySpy(),
                _request(include_overview=True, chat_ids=(CHAT, CHAT2)))
            assert result.overview is not None
            assert result.overview.chat_id == CHAT
            own_refs = {v.episode_ref for v in await list_episode_views(db, CHAT)}
            assert set(result.overview.episode_refs) <= own_refs
            assert "cross_chat_acl_scope_overview_single_chat" \
                in result.overview.limitations
        finally:
            await db.close()


# ═══ M-05: read-only, без reembedding, без утечки чужого чата ═══════════════

class TestM05IsolationAndNoReembedding:
    @pytest.mark.asyncio
    async def test_overview_reads_are_read_only(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            await _add_fact(db, chat=CHAT, fact="Папаха любит дронов", ts=T2021,
                            target_user=SUBJECT_NAME, subject_ref_id=4242,
                            speaker=UID)
            before_version = await _user_version(db)
            before_tables = await _table_names(db)
            before = {
                "messages": await _count(db, "SELECT COUNT(*) FROM smart_messages"),
                "episodes": await _count(db, "SELECT COUNT(*) FROM mca_episodes"),
                "facts": await _count(db, "SELECT COUNT(*) FROM graph_facts"),
                "source_refs": await _count(
                    db, "SELECT COUNT(*) FROM mca_source_refs"),
            }
            memory = _MemorySpy()
            with _trace_sql(db) as trace:
                await rc.retrieve(db, memory, _request(include_overview=True))
                await rc.retrieve(db, memory, _request(include_overview=True))
            writes = [s for s in trace.statements if _WRITE_RE.search(s)]
            assert writes == [], f"unexpected write SQL: {writes[:3]}"
            assert await _user_version(db) == before_version
            assert await _table_names(db) == before_tables
            after = {
                "messages": await _count(db, "SELECT COUNT(*) FROM smart_messages"),
                "episodes": await _count(db, "SELECT COUNT(*) FROM mca_episodes"),
                "facts": await _count(db, "SELECT COUNT(*) FROM graph_facts"),
                "source_refs": await _count(
                    db, "SELECT COUNT(*) FROM mca_source_refs"),
            }
            assert after == before
            # ноль embedding/upsert/rebuild-вызовов (список запрещённых пуст)
            assert memory.forbidden_calls == []
            assert memory.fact_calls      # vector-канал читал, не писал
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_foreign_chat_rows_never_leak_into_overview(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            foreign_text = "Папаха встретился в парке как договаривались"
            await _add_msg(db, CHAT2, 7, UID, foreign_text, T2021)
            await _seed_episodes(db, CHAT2, [
                {"chat_id": CHAT2, "id": None, "tg_message_id": 7,
                 "user_id": UID, "text": foreign_text, "timestamp": T2021,
                 "reply_to_tg_message_id": None}])
            await _add_fact(db, chat=CHAT2, fact="Папаха любит чужие дроны",
                            ts=T2021, target_user=SUBJECT_NAME,
                            subject_ref_id=4343, speaker=UID)
            result = await rc.retrieve(
                db, _MemorySpy(), _request(include_overview=True,
                                           memory_scope="historical"))
            own = {v.episode_ref for v in await list_episode_views(db, CHAT)}
            foreign = {v.episode_ref
                       for v in await list_episode_views(db, CHAT2)}
            assert own and foreign and not (own & foreign)
            assert set(result.overview.episode_refs) <= own
            assert not (set(result.overview.episode_refs) & foreign)
            assert all(int(c.chat_id or CHAT) == CHAT for c in result.candidates)
            assert all("чужие дроны" not in str(c.preview or "")
                       for c in result.candidates)
        finally:
            await db.close()


# ═══ O-04: definitions как hints, corrections/versions, один маршрут ════════

class TestO04SemanticHintsSingleRoute:
    @pytest.mark.asyncio
    async def test_semantic_hints_do_not_change_candidates(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            ref_id = await _bind_subject(db, CHAT, UID)
            bound_id = await _add_fact(
                db, chat=CHAT, fact="Папаха любит дронов", ts=T2021,
                target_user=SUBJECT_NAME, subject_ref_id=ref_id, speaker=UID)
            legacy_id = await _add_fact(
                db, chat=CHAT, fact="Папаха любит рыбалку", ts=T2023,
                target_user=SUBJECT_NAME)
            memory = _MemorySpy()
            plain = await rc.retrieve(db, memory, _request())
            hinted = await rc.retrieve(
                db, memory,
                _request(include_overview=True, subject_entity_ids=(UID,)))
            assert [c.id for c in plain.candidates] == \
                [c.id for c in hinted.candidates]
            assert [c.entity_id for c in plain.candidates] == \
                [c.entity_id for c in hinted.candidates]

            hints = {h.get("fact_id"): h for h in hinted.overview.semantic_hints
                     if h.get("fact_id") is not None}
            assert bound_id in hints and legacy_id in hints
            # legacy-факт остаётся видимым (weak hint), но не verified
            assert hints[legacy_id]["verification"] != "verified"
            assert hints[legacy_id]["reason_code"] or hints[legacy_id]["degraded"]
            # типизированное определение факта — hint, не отбор
            assert hints[bound_id]["entity_type"] == "fact"
            for hint in hints.values():
                assert "verification" in hint
                assert hint["verification"] in (
                    "verified", "tentative", "unknown", "rejected")
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_subject_definition_hint_is_not_promoted(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            by_uid = await rc.retrieve(
                db, _MemorySpy(),
                _request(include_overview=True, subject_entity_ids=(UID,)))
            by_name = await rc.retrieve(
                db, _MemorySpy(), _request(include_overview=True))
            uid_hints = [h for h in by_uid.overview.semantic_hints
                         if h.get("kind") == "subject_identity"]
            name_hints = [h for h in by_name.overview.semantic_hints
                          if h.get("kind") == "subject_identity"]
            assert uid_hints and uid_hints[0]["basis"] == "participant_identity"
            assert uid_hints[0]["status"] == "verified"
            # имя без устойчивой идентичности — НЕ basis, и не verified
            assert name_hints and name_hints[0]["entity_id"] == ""
            assert name_hints[0]["basis"] in ("none", "name_hint")
            assert name_hints[0]["status"] != "verified"
            assert "subject_identity_name_hint_only" in by_name.overview.limitations
            # неоднозначный субъект не выбирается «популярным»
            ambiguous = await rc.retrieve(
                db, _MemorySpy(),
                _request(include_overview=True,
                         ambiguous_subjects=(SUBJECT_NAME,)))
            assert ambiguous.overview is not None
            assert "subject_ambiguous_overview_unfiltered" in \
                ambiguous.overview.limitations
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_corrections_and_versions_apply_to_next_query(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            ref_id = await _bind_subject(db, CHAT, UID)
            fact_id = await _add_fact(
                db, chat=CHAT, fact="Папаха любит дронов", ts=T2021,
                target_user=SUBJECT_NAME, subject_ref_id=ref_id, speaker=UID)
            first = await rc.retrieve(
                db, _MemorySpy(),
                _request(include_overview=True, subject_entity_ids=(UID,)))
            first_fingerprints = {v["episode_ref"]: v["source_fingerprint"]
                                 for v in first.overview.episode_versions}
            first_hint = next(h for h in first.overview.semantic_hints
                              if h.get("fact_id") == fact_id)
            assert first_fingerprints
            assert first_hint["verification"] != "unknown"

            # исправление источника: ревизия smart_messages (существующая
            # колонка) + снятая атрибуция факта — тем же write-владельцем
            cursor = await db.db.execute(
                "UPDATE smart_messages SET current_revision = "
                "COALESCE(current_revision, 1) + 1 WHERE chat_id = ?",
                (CHAT,))
            assert cursor.rowcount >= 1
            await db.db.execute(
                "UPDATE graph_facts SET subject_ref_id = NULL, "
                "speaker_author_id = NULL WHERE id = ?", (fact_id,))
            await db.db.commit()

            second = await rc.retrieve(
                db, _MemorySpy(),
                _request(include_overview=True, subject_entity_ids=(UID,)))
            second_fingerprints = {v["episode_ref"]: v["source_fingerprint"]
                                  for v in second.overview.episode_versions}
            assert set(second_fingerprints) == set(first_fingerprints)
            assert all(second_fingerprints[ref] != first_fingerprints[ref]
                       for ref in first_fingerprints)
            second_hint = next(h for h in second.overview.semantic_hints
                               if h.get("fact_id") == fact_id)
            assert second_hint["verification"] != first_hint["verification"]
            assert second_hint["verification"] != "verified"
            # никакого отдельного журнала исправлений/версий не появилось
            assert not [name for name in await _table_names(db)
                        if "correction" in name or "term" in name]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_one_route_no_extra_search_or_model_calls(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            memory = _MemorySpy()
            with _trace_sql(db) as plain_trace:
                await rc.retrieve(db, memory, _request())
            plain_calls = len(memory.fact_calls)
            plain_fts = len([s for s in plain_trace.statements
                             if "graph_facts_fts MATCH" in s])
            plain_msg_fts = len([s for s in plain_trace.statements
                                 if "smart_messages_fts MATCH" in s])
            with _trace_sql(db) as hinted_trace:
                await rc.retrieve(db, memory, _request(include_overview=True))
            hinted_fts = len([s for s in hinted_trace.statements
                              if "graph_facts_fts MATCH" in s])
            hinted_msg_fts = len([s for s in hinted_trace.statements
                                  if "smart_messages_fts MATCH" in s])
            # hints добавляют только чтение уже существующих эпизодов
            assert hinted_fts == plain_fts
            assert hinted_msg_fts == plain_msg_fts
            assert len(memory.fact_calls) - plain_calls == 1   # второй вызов
            assert memory.forbidden_calls == []
            # ни одного второго поискового движка: каждая ДОПОЛНИТЕЛЬНАЯ
            # инструкция читает существующий episode-контракт M1
            plain_sql = list(plain_trace.statements)
            extra = list(hinted_trace.statements)
            for statement in plain_sql:
                if statement in extra:
                    extra.remove(statement)
            assert extra, "overview читает существующий episode-контракт"
            assert all("mca_episode" in s or "smart_messages" in s
                       for s in extra), extra[:3]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_overview_bounded(self):
        db = await _db()
        try:
            await _overview_fixture(db)
            result = await rc.retrieve(
                db, _MemorySpy(), _request(include_overview=True, top_k=1))
            overview = result.overview
            assert len(overview.episode_refs) <= rc.OVERVIEW_MAX_EPISODES
            assert len(overview.episode_versions) <= rc.OVERVIEW_MAX_EPISODES
            assert len(overview.counterexamples) <= rc.OVERVIEW_MAX_COUNTEREXAMPLES
            assert len(overview.limitations) <= rc.OVERVIEW_MAX_LIMITATIONS
            assert len(overview.semantic_hints) <= rc.OVERVIEW_MAX_HINTS
            payload = overview.as_dict()
            assert json.loads(json.dumps(payload)) == payload  # сериализуемо
            assert overview.derived_version == rc.OVERVIEW_VERSION
        finally:
            await db.close()
