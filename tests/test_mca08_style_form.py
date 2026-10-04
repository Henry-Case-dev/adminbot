"""MCA-08 `mca-08-character-speech` — блоки C+D (T-4903…T-4910, ADR-1028-11).

Focused-контракты (без полного suite):
  * C (K3): Δ DDL v26 (`mca_style_requests` + 2 индекса, реестр mca-14,
    идемпотентность, PG no-op); закрытая грамматика «директива + scope»;
    explicit-only/анти-максимизация; права participant/chat/topic; приоритет
    participant > topic > chat; supersede/TTL/sweep/сброс; OFF-паритет.
  * D (K4): форма G1–G3 (утечки/числа+отрицание/новые имена ростера); ≤1
    повтор внутри существующего бюджета; fallback на проверенный черновик;
    reason-события `form_guard_*`; OFF-паритет и паритет default-параметров.
  * E (T-4910): реестр mca-17a — стадии direct.reply + процесс `style.scope`,
    `_GATE_RESOLVERS` K3/K4, reason codes +9, Δ каталога = 0.

R17: в события/логи — только коды/ID/числа; тестовые строки синтетические.
"""
import inspect
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from config.settings import settings
from services import mca_events
from services import mca_gates
from services import mca_process_registry as reg
from services import mca_style_scope as ss
from services.database import DatabaseService
from services.negative_constraints import (
    FORM_GUARD_LEAK_BLOCKED,
    FORM_GUARD_REJECTED,
    FormContract,
    check_form_contract,
    verbalize_validated,
)
from services.prompt_style_blocks import (
    CLICHE_RETRY_SYSTEM_PROMPT,
    FORM_GUARD_RETRY_SYSTEM_PROMPT,
)
from tests.test_direct_chat import (
    CHAT_ID,
    FakeLLM,
    FakeMemory,
    _bot,
    _force_persona_flag,
    _force_self_awareness,
    _make_service,
    _message,
)
from tests.test_mca08_character_speech import _persona_patch
from tests.test_direct_two_call_round1022 import _SYNTH_JSON, _tool_raw

ADMIN_ID = 999001

pytestmark = pytest.mark.system2


@pytest.fixture(autouse=True)
def _self_awareness_off(monkeypatch):
    _force_self_awareness(monkeypatch, False)


def _gates(monkeypatch, *, style: bool = True, form: bool = True) -> None:
    monkeypatch.setattr(mca_gates, "style_scope_enabled", lambda: style)
    monkeypatch.setattr(mca_gates, "postprocess_form_guard_enabled",
                        lambda: form)


def _admin(monkeypatch, value: bool = True) -> None:
    from services import chat_access
    monkeypatch.setattr(chat_access, "is_admin", lambda uid: value)


def _events(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        mca_events, "emit_mca_event",
        lambda name, **kw: calls.append({"event_name": name, **kw}))
    return calls


async def _db(tmp_path, name="style.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _active(db, chat_id=-100, now=1e12):
    return await ss._fetch_active(db, chat_id, now)


# ── E: Δ DDL v26 (реестр mca-14) ────────────────────────────────────────────

class TestStyleRequestsDdl:
    @pytest.mark.asyncio
    async def test_v26_fresh_db_table_indexes_book_idempotent(self, tmp_path):
        path = str(tmp_path / "ddl.db")
        db = DatabaseService(path)
        await db.initialize()
        try:
            cur = await db.db.execute("PRAGMA user_version")
            assert (await cur.fetchone())[0] == 26
            cur = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                ("mca_style_requests",))
            assert await cur.fetchone() is not None
            cur = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
                "(?,?)", ("idx_mca_style_requests_active",
                          "idx_mca_style_requests_participant"))
            assert len(await cur.fetchall()) == 2
            cur = await db.db.execute(
                "SELECT name FROM schema_migrations WHERE version=26")
            assert (await cur.fetchone())["name"] == "style_requests"
        finally:
            await db.close()
        # повторный initialize на том же файле (рестарт) — no-op/идемпотентно
        db2 = DatabaseService(path)
        await db2.initialize()
        try:
            cur = await db2.db.execute("PRAGMA user_version")
            assert (await cur.fetchone())[0] == 26
            cur = await db2.db.execute(
                "SELECT COUNT(*) AS c FROM schema_migrations WHERE version=26")
            assert (await cur.fetchone())["c"] == 1
        finally:
            await db2.close()

    def test_migration_step_registered(self):
        from services.database import (
            MigrationStep, _SCHEMA_VERSION_STYLE_REQUESTS,
            _STYLE_REQUESTS_DDL,
        )
        assert _SCHEMA_VERSION_STYLE_REQUESTS == 26
        steps = {s.version: s.name for s in DatabaseService.migration_steps()}
        assert steps[26] == "style_requests"
        assert isinstance(
            next(s for s in DatabaseService.migration_steps()
                 if s.version == 26), MigrationStep)
        # аддитивность: только CREATE IF NOT EXISTS (ни ALTER/DROP/UPDATE)
        assert "CREATE TABLE IF NOT EXISTS" in _STYLE_REQUESTS_DDL
        assert "ALTER" not in _STYLE_REQUESTS_DDL

    @pytest.mark.asyncio
    async def test_check_constraint_rejects_bad_scope(self, tmp_path):
        import sqlite3
        db = await _db(tmp_path, "check.db")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                await db.db.execute(
                    "INSERT INTO mca_style_requests (chat_id, scope, facet, "
                    "directive, set_by, source, created_at) VALUES "
                    "(-1,'bad','humor','off',1,'command',1.0)")
            await db.db.rollback()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_v25_to_v26_backup_guard_and_apply(self, tmp_path):
        """Прод-путь v25→v26: backup pre-DDL + read-back + применение."""
        import sqlite3
        path = tmp_path / "v25.db"
        db = DatabaseService(str(path))
        await db.initialize()
        await db.close()
        # откат к состоянию прод-БД v25 (таблицы v26 ещё нет)
        conn = sqlite3.connect(str(path))
        conn.execute("DROP TABLE IF EXISTS mca_style_requests")
        conn.execute("DELETE FROM schema_migrations WHERE version=26")
        conn.execute("PRAGMA user_version = 25")
        conn.commit()
        conn.close()
        db2 = DatabaseService(str(path))
        await db2.initialize()          # сработает fail-closed backup-guard
        try:
            cur = await db2.db.execute("PRAGMA user_version")
            assert (await cur.fetchone())[0] == 26
            backups = list(tmp_path.glob("pre_migration_*.db"))
            assert backups, "pre-migration backup не создан"
            conn = sqlite3.connect(str(backups[-1]))
            backup_version = conn.execute("PRAGMA user_version").fetchone()[0]
            conn.close()
            assert backup_version == 25  # read-back копии
        finally:
            await db2.close()

    def test_pg_no_op_and_no_catalog_delta(self):
        root = Path(__file__).resolve().parent.parent
        assert "mca_style_requests" not in (
            root / "services" / "pg_db.py").read_text(encoding="utf-8")
        try:
            from services.param_catalog import PARAM_DEFS
            names = {d.key for d in PARAM_DEFS}
        except Exception:
            from services import param_catalog
            names = {str(getattr(v, "key", ""))
                     for v in getattr(param_catalog, "_PARAMS", [])}
        assert not ({"MCA_STYLE_SCOPE_ENABLED",
                     "MCA_POSTPROCESS_FORM_GUARD_ENABLED",
                     "MCA_STYLE_SCOPE_CHAT_TTL_DAYS",
                     "MCA_STYLE_SCOPE_TOPIC_TTL_DAYS"} & names)


# ── C: закрытая грамматика ──────────────────────────────────────────────────

class TestStyleParser:
    @pytest.mark.parametrize("text,facet,directive,scope,topic", [
        ("Бот, отвечай короче", "verbosity", "short", "participant", None),
        ("отвечай короче, пожалуйста", "verbosity", "short",
         "participant", None),
        ("со мной без шуток", "humor", "off", "participant", None),
        ("в этом чате говори прямо", "directness", "direct", "chat", None),
        ("для всех без смайлов", "emoji", "off", "chat", None),
        ("вообще отвечай подробнее", "verbosity", "long", "chat", None),
        ("по теме рыбалка без шуток", "humor", "off", "topic", "рыбалка"),
        ("когда речь о машинах — отвечай подробнее", "verbosity", "long",
         "topic", "машинах"),
        ("если разговор о кухне, без смайлов", "emoji", "off",
         "topic", "кухне"),
        ("обращайся на «ты»", "address", "ty", "participant", None),
        ("не шути", "humor", "off", "participant", None),
        ("можно шутить", "humor", "on", "participant", None),
    ])
    def test_clean_matches(self, text, facet, directive, scope, topic):
        parsed = ss.parse_directive_request(text)
        assert parsed is not None and not parsed.ambiguous
        assert (parsed.facet, parsed.directive, parsed.scope,
                parsed.topic_key) == (facet, directive, scope, topic)

    @pytest.mark.parametrize("text", [
        "Бот, отвечай короче и без шуток",          # 2 директивы
        "по теме рыбалка в этом чате без шуток",    # конфликт scope
        "по теме х! без шуток",                     # битая метка (1 символ)
        "мне вчера сказали без шуток, что смешно",  # лишний смысл
    ])
    def test_ambiguous_skipped_not_recorded(self, text):
        parsed = ss.parse_directive_request(text)
        assert parsed is not None and parsed.ambiguous

    @pytest.mark.parametrize("text", [
        "привет, как дела?", "почему?", "шучу, я вчера был на Марсе",
        "ты меня достал", "форма не меняет факты", "ок", "...",
        "расскажи, как вы вчера встречались",
    ])
    def test_not_a_request_is_silent(self, text):
        assert ss.parse_directive_request(text) is None

    def test_directive_only_for_command(self):
        assert ss.parse_directive_only("отвечай короче") == \
            ("verbosity", "short")
        assert ss.parse_directive_only("без смягчений") == \
            ("directness", "direct")
        assert ss.parse_directive_only("чат") is None
        assert ss.parse_directive_only("без шуток и короче") is None

    def test_topic_key_validation(self):
        assert ss.validate_topic_key("Рыбалка") == "рыбалка"
        assert ss.validate_topic_key("утренняя рыбалка") == \
            "утренняя рыбалка"
        assert ss.validate_topic_key("x" * 60) is None
        assert ss.validate_topic_key("тема!") is None


# ── C: ingest/права/приоритет/supersede/TTL/сброс ───────────────────────────

class TestStyleIngestRights:
    @pytest.mark.asyncio
    async def test_participant_recorded_and_scoped_to_author(self, tmp_path):
        db = await _db(tmp_path)
        try:
            result = await ss.ingest_message(
                db, chat_id=-100, sender_id=7,
                text="Бот, отвечай короче", message_id=55, now=1000.0)
            assert result["status"] == "recorded"
            rows = await _active(db, -100, now=1001.0)
            assert rows[0]["participant_id"] == 7
            assert rows[0]["source"] == "message"
            assert rows[0]["source_message_id"] == 55
            assert rows[0]["expires_at"] is None         # participant — без TTL
            block = await ss.resolve_block(
                db, chat_id=-100, text="привет", participant_id=7, now=1001.0)
            assert "[участник] отвечай короче" in block
            assert await ss.resolve_block(
                db, chat_id=-100, text="привет", participant_id=8,
                now=1001.0) == ""
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_chat_topic_denied_without_admin(self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        calls = _events(monkeypatch)
        _admin(monkeypatch, False)
        try:
            denied = await ss.ingest_message(
                db, chat_id=-100, sender_id=7,
                text="в этом чате без шуток", now=1000.0)
            assert denied["status"] == "denied"
            denied2 = await ss.ingest_message(
                db, chat_id=-100, sender_id=7,
                text="по теме рыбалка без шуток", now=1000.0)
            assert denied2["status"] == "denied"
            assert await _active(db, -100, now=1000.0) == []
            assert [c["reason_code"] for c in calls] == [
                "style_request_denied", "style_request_denied"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_chat_admin_via_lore_store(self, tmp_path, monkeypatch):
        from services import lore_runtime
        db = await _db(tmp_path)
        _admin(monkeypatch, False)

        class _Store:
            async def is_chat_admin(self, uid, chat_id):
                return uid == 7

        lore_runtime.set_lore_components(store=_Store())
        try:
            result = await ss.ingest_message(
                db, chat_id=-100, sender_id=7,
                text="в этом чате говори прямо", now=1000.0)
            assert result["status"] == "recorded"
            assert (await _active(db, -100, now=1000.0))[0]["scope"] == "chat"
        finally:
            lore_runtime.reset_lore_runtime()
            await db.close()

    @pytest.mark.asyncio
    async def test_rights_error_fail_closed(self, tmp_path, monkeypatch):
        from services import chat_access
        db = await _db(tmp_path)
        monkeypatch.setattr(
            chat_access, "is_admin",
            lambda uid: (_ for _ in ()).throw(RuntimeError("pg down")))
        try:
            result = await ss.ingest_message(
                db, chat_id=-100, sender_id=7,
                text="для всех без шуток", now=1000.0)
            assert result["status"] == "denied"
            assert await _active(db, -100, now=1000.0) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_ambiguity_event_only_for_lookalikes(self, tmp_path,
                                                       monkeypatch):
        db = await _db(tmp_path)
        calls = _events(monkeypatch)
        try:
            await ss.ingest_message(
                db, chat_id=-100, sender_id=7, text="ок", now=1000.0)
            await ss.ingest_message(
                db, chat_id=-100, sender_id=7,
                text="отвечай короче и без шуток", now=1000.0)
            assert [c["reason_code"] for c in calls] == [
                "style_request_ambiguous_skipped"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_budgets_per_chat_and_per_hour_no_event_noise(
            self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        _admin(monkeypatch, True)
        facets = [("verbosity", "short"), ("verbosity", "long"),
                  ("humor", "off"), ("humor", "on"), ("emoji", "off")]
        try:
            for index, (facet, directive) in enumerate(facets):
                result = await ss._apply_request(
                    db, chat_id=-100, set_by=7,
                    parsed=ss.ParsedRequest(facet, directive, "participant"),
                    source="command", source_message_id=None,
                    now=1000.0 + index)
                assert result["status"] == "recorded", (facet, directive)
            # 5 записей/час исчерпаны → отказ без события-шума
            calls = _events(monkeypatch)
            refused = await ss._apply_request(
                db, chat_id=-100, set_by=7,
                parsed=ss.ParsedRequest("address", "ty", "participant"),
                source="command", source_message_id=None, now=1010.0)
            assert refused["status"] == "budget_exceeded"
            assert calls == []
            # активных меньше 5: supersede по facet (verbosity/humor)
            active = await _active(db, -100, now=1010.0)
            assert len(active) == 3
            assert {r["facet"] for r in active} == {"verbosity", "humor",
                                                    "emoji"}
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_supersede_and_reverse_directives(self, tmp_path,
                                                    monkeypatch):
        db = await _db(tmp_path)
        calls = _events(monkeypatch)
        try:
            await ss.ingest_message(db, chat_id=-100, sender_id=7,
                                    text="без шуток", now=1000.0)
            result = await ss.ingest_message(db, chat_id=-100, sender_id=7,
                                             text="можно шутить", now=1001.0)
            assert result["superseded"] == 1
            cursor = await db.db.execute(
                "SELECT id, revoked_at, superseded_by FROM mca_style_requests "
                "WHERE chat_id=? ORDER BY id", (-100,))
            by_id = {int(r["id"]): dict(r) for r in await cursor.fetchall()}
            assert by_id[1]["revoked_at"] == 1001.0
            assert by_id[1]["superseded_by"] == 2
            assert [c["reason_code"] for c in calls] == [
                "style_request_recorded", "style_request_recorded",
                "style_request_superseded"]
            active = await _active(db, -100, now=1001.0)
            assert len(active) == 1 and active[0]["directive"] == "on"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_priority_participant_over_topic_over_chat(
            self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        _admin(monkeypatch, True)
        try:
            await ss.handle_command(db, chat_id=-100, user_id=ADMIN_ID,
                                    args="чат отвечай короче", now=1000.0)
            await ss.handle_command(db, chat_id=-100, user_id=ADMIN_ID,
                                    args="тема рыбалка отвечай подробнее",
                                    now=1001.0)
            result = await ss.ingest_message(
                db, chat_id=-100, sender_id=7, text="со мной без смайлов",
                now=1002.0)
            assert result["status"] == "recorded"
            # добавим участнику тот же facet verbosity
            await ss.ingest_message(
                db, chat_id=-100, sender_id=7, text="отвечай короче",
                now=1003.0)
            selected = await ss.resolve_active(
                db, chat_id=-100, text="рыбалка сегодня",
                participant_id=7, now=1004.0)
            by_facet = {r["facet"]: r for r in selected}
            assert by_facet["verbosity"]["scope"] == "participant"
            assert by_facet["verbosity"]["directive"] == "short"
            assert by_facet["emoji"]["scope"] == "participant"
            # без participant-строки побеждает topic над chat
            selected_eight = await ss.resolve_active(
                db, chat_id=-100, text="рыбалка сегодня", participant_id=8,
                now=1004.0)
            assert {r["facet"]: r["scope"] for r in selected_eight}[
                "verbosity"] == "topic"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_latest_within_scope_wins(self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        try:
            await ss.ingest_message(db, chat_id=-100, sender_id=7,
                                    text="отвечай короче", now=1000.0)
            await ss.ingest_message(db, chat_id=-100, sender_id=7,
                                    text="отвечай подробнее", now=1001.0)
            selected = await ss.resolve_active(
                db, chat_id=-100, text="x", participant_id=7, now=1002.0)
            assert len(selected) == 1
            assert selected[0]["directive"] == "long"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_ttl_chat_topic_and_lazy_filter(self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        _admin(monkeypatch, True)
        day = 86400.0
        try:
            await ss.handle_command(db, chat_id=-100, user_id=ADMIN_ID,
                                    args="чат без шуток", now=1000.0)
            await ss.handle_command(db, chat_id=-100, user_id=ADMIN_ID,
                                    args="тема рыбалка без смайлов",
                                    now=1000.0)
            rows = {r["scope"]: r for r in await _active(db, -100, now=1000.0)}
            assert rows["chat"]["expires_at"] == 1000.0 + 7 * day
            assert rows["topic"]["expires_at"] == 1000.0 + 30 * day
            # ленивый фильтр: chat истёк на 8-й день, topic жив
            selected = await ss.resolve_active(
                db, chat_id=-100, text="рыбалка сегодня", participant_id=7,
                now=1000.0 + 8 * day)
            assert {r["scope"] for r in selected} == {"topic"}
            # topic истёк на 31-й день
            assert await ss.resolve_active(
                db, chat_id=-100, text="рыбалка сегодня", participant_id=7,
                now=1000.0 + 31 * day) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_expire_sweep_bounded_and_events(self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        _admin(monkeypatch, True)
        day = 86400.0
        try:
            chat_facets = [("verbosity", "short"), ("humor", "off"),
                           ("emoji", "off"), ("directness", "direct"),
                           ("address", "ty")]
            now = 1000.0
            for index, (facet, directive) in enumerate(chat_facets):
                await ss._apply_request(
                    db, chat_id=-100, set_by=ADMIN_ID,
                    parsed=ss.ParsedRequest(facet, directive, "chat"),
                    source="command", source_message_id=None,
                    now=now + index * 7200.0)
            for index, (facet, directive) in enumerate(
                    [("verbosity", "long"), ("humor", "on")]):
                await ss._apply_request(
                    db, chat_id=-100, set_by=ADMIN_ID,
                    parsed=ss.ParsedRequest(facet, directive, "topic",
                                            topic_key="рыбалка"),
                    source="command", source_message_id=None,
                    now=now + (len(chat_facets) + index) * 7200.0)
            assert len(await _active(db, -100, now=now)) == 7
            expiry_check = now + 6 * 7200.0 + 31 * day
            calls = _events(monkeypatch)
            marked = await ss.sweep_expired(db, chat_id=-100, now=expiry_check)
            assert marked == 5                       # bounded ≤5
            assert [c["reason_code"] for c in calls] == \
                ["style_request_expired"] * 5
            assert await ss.sweep_expired(db, chat_id=-100,
                                          now=expiry_check) == 2
            # идемпотентность: третий sweep — 0
            assert await ss.sweep_expired(db, chat_id=-100,
                                          now=expiry_check) == 0
            assert await _active(db, -100, now=expiry_check) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_reset_idempotent_and_admin_boundaries(self, tmp_path,
                                                         monkeypatch):
        db = await _db(tmp_path)
        _admin(monkeypatch, False)
        try:
            await ss.ingest_message(db, chat_id=-100, sender_id=7,
                                    text="отвечай короче", now=1000.0)
            # participant — сам, идемпотентно
            assert await ss.reset_requests(
                db, chat_id=-100, scope="participant", participant_id=7,
                now=1001.0) == 1
            assert await ss.reset_requests(
                db, chat_id=-100, scope="participant", participant_id=7,
                now=1002.0) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_command_grammar(self, tmp_path, monkeypatch):
        from services import smartmodule_phrases as ph
        db = await _db(tmp_path)
        _admin(monkeypatch, True)
        try:
            assert await ss.handle_command(
                db, chat_id=-100, user_id=7, args="") == \
                ph.CHAT_STYLE_LIST_EMPTY_PHRASE
            assert await ss.handle_command(
                db, chat_id=-100, user_id=7, args="отвечай короче") == \
                ph.CHAT_STYLE_SET_PARTICIPANT_PHRASE.replace(
                    "{directive}", "отвечай короче")
            listing = await ss.handle_command(
                db, chat_id=-100, user_id=7, args="список")
            assert "[участник] отвечай короче" in listing
            assert await ss.handle_command(
                db, chat_id=-100, user_id=ADMIN_ID, args="чат без шуток") == \
                ph.CHAT_STYLE_SET_CHAT_PHRASE.replace("{directive}",
                                                      "без шуток")
            assert await ss.handle_command(
                db, chat_id=-100, user_id=ADMIN_ID,
                args="тема рыбалка без смайлов") == \
                ph.CHAT_STYLE_SET_TOPIC_PHRASE.replace(
                    "{directive}", "без смайлов").replace("{label}", "рыбалка")
            assert await ss.handle_command(
                db, chat_id=-100, user_id=ADMIN_ID, args="тема x! без смайлов") \
                == ph.CHAT_STYLE_INVALID_TOPIC_PHRASE
            assert await ss.handle_command(
                db, chat_id=-100, user_id=7, args="сепулька") == \
                ph.CHAT_STYLE_UNKNOWN_PHRASE
            _admin(monkeypatch, False)
            assert await ss.handle_command(
                db, chat_id=-100, user_id=7, args="чат off") == \
                ph.CHAT_STYLE_ADMIN_ONLY_PHRASE
            _admin(monkeypatch, True)
            assert await ss.handle_command(
                db, chat_id=-100, user_id=ADMIN_ID, args="чат off") == \
                ph.CHAT_STYLE_OFF_CHAT_DONE_PHRASE
            assert await ss.handle_command(
                db, chat_id=-100, user_id=ADMIN_ID, args="всё off") == \
                ph.CHAT_STYLE_OFF_ALL_DONE_PHRASE
            assert await ss._fetch_active(db, -100, 1e12) == []
            # битый db → честная «недоступно», не исключение
            assert await ss.handle_command(
                None, chat_id=-100, user_id=7, args="список") == \
                ph.CHAT_STYLE_UNAVAILABLE_PHRASE
        finally:
            await db.close()


class TestStyleExplicitOnlyAntiMaximization:
    @pytest.mark.asyncio
    async def test_silence_jokes_provocations_never_mutate(self, tmp_path,
                                                           monkeypatch):
        db = await _db(tmp_path)
        calls = _events(monkeypatch)
        try:
            for text in ("...", "ок", "ты молчишь", "ну да, великий спортсмен",
                         "ты меня достал", "шучу, я вчера был на Марсе",
                         "> он вчера уехал\nи что"):
                result = await ss.ingest_message(
                    db, chat_id=-100, sender_id=7, text=text, now=1000.0)
                assert result is None
            assert await _active(db, -100, now=1000.0) == []
            assert calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_repetition_does_not_escalate(self, tmp_path):
        db = await _db(tmp_path)
        try:
            for _ in range(10):
                await ss.ingest_message(db, chat_id=-100, sender_id=7,
                                        text="отвечай короче", now=1000.0)
            active = await _active(db, -100, now=1000.0)
            assert len(active) == 1                  # supersede, не накопление
            blocks = {await ss.resolve_block(
                db, chat_id=-100, text="x", participant_id=7, now=1000.0)
                for _ in range(3)}
            assert len(blocks) == 1                  # поведение не растёт
        finally:
            await db.close()

    def test_single_writer_and_no_counter_paths(self):
        source = inspect.getsource(ss)
        assert source.count("INSERT INTO mca_style_requests") == 1
        assert "create_task" not in source and "asyncio" not in source
        params = inspect.signature(ss.ingest_message).parameters
        assert list(params) == ["db", "chat_id", "sender_id", "text",
                                "message_id", "now"]


# ── C: рендер ───────────────────────────────────────────────────────────────

class TestStyleRender:
    def test_canon_tags_and_escaping(self):
        rows = [
            {"scope": "participant", "facet": "verbosity",
             "directive": "short"},
            {"scope": "chat", "facet": "humor", "directive": "off"},
            {"scope": "topic", "topic_key": "<b>&",
             "facet": "emoji", "directive": "off"},
        ]
        block = ss.render_style_block(rows)
        assert block.startswith("<Style_Requests>\n")
        assert block.endswith("\n</Style_Requests>")
        assert "[участник] отвечай короче" in block
        assert "[чат] без шуток" in block
        assert "[тема: &lt;b&gt;&amp;]" in block     # XML-спецсимволы label

    def test_cap_600(self):
        rows = [{"scope": "topic", "topic_key": f"тема{index}" * 3,
                 "facet": "humor", "directive": "off"}
                for index in range(40)]
        block = ss.render_style_block(rows)
        assert len(block) <= 600
        assert "…\n</Style_Requests>" in block

    def test_empty_rows_no_block(self):
        assert ss.render_style_block([]) == ""


# ── C: врезка в direct-путь (T-4904) ────────────────────────────────────────

class TestStyleDirectIntegration:
    @pytest.mark.asyncio
    async def test_style_block_between_rules_and_speech(self, tmp_path,
                                                        monkeypatch):
        from services import bot_persona
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        db = await _db(tmp_path)
        _force_persona_flag(monkeypatch, True)
        _persona_patch(monkeypatch)
        try:
            llm = FakeLLM(text="ок")
            svc = _make_service(memory=FakeMemory(), db=db, llm=llm)
            msg = _message(text="Бот, отвечай короче", message_id=901)
            await svc.handle(_bot(), msg, msg.from_user)
            system = llm.messages[0]["content"]
            assert system.startswith(CHAT_SYSTEM_PROMPT)
            assert system.index("<Character_Rules>") < \
                system.index("<Style_Requests>")
            assert "[участник] отвечай короче" in system
            rows = await _active(db, CHAT_ID, now=1e12)
            assert rows[0]["participant_id"] == msg.from_user.id
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_participant_request_not_applied_to_other_user(
            self, tmp_path, monkeypatch):
        _force_persona_flag(monkeypatch, True)
        _persona_patch(monkeypatch)
        db = await _db(tmp_path)
        try:
            llm = FakeLLM(text="ок")
            svc = _make_service(memory=FakeMemory(), db=db, llm=llm)
            first = _message(text="Бот, отвечай короче", message_id=902)
            await svc.handle(_bot(), first, first.from_user)
            other = _message(text="Бот, расскажи о себе", message_id=903)
            other.from_user.id = 77
            await svc.handle(_bot(), other, other.from_user)
            assert "<Style_Requests>" not in llm.messages[0]["content"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_style_before_speech_in_tail(self, tmp_path, monkeypatch):
        _force_persona_flag(monkeypatch, True)
        _persona_patch(monkeypatch)
        db = await _db(tmp_path)
        try:
            await ss.ingest_message(db, chat_id=CHAT_ID, sender_id=10,
                                    text="отвечай короче", now=1.0)
            llm = FakeLLM(text="ок")
            svc = _make_service(memory=FakeMemory(), db=db, llm=llm)
            msg = _message(text="я не был на встрече", message_id=906)
            await svc.handle(_bot(), msg, msg.from_user)
            system = llm.messages[0]["content"]
            assert "<Style_Requests>" in system
            assert "<Speech_Understanding>" in system
            assert system.index("<Style_Requests>") < \
                system.index("<Speech_Understanding>")
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_reply_to_another_user_not_ingested(self, tmp_path):
        db = await _db(tmp_path)
        try:
            llm = FakeLLM(text="ок")
            svc = _make_service(memory=FakeMemory(), db=db, llm=llm)
            msg = _message(text="отвечай короче", message_id=907)
            reply = MagicMock()
            reply.from_user = MagicMock()
            reply.from_user.id = 555
            reply.text = "просто сообщение"
            msg.reply_to_message = reply
            await svc.handle(_bot(), msg, msg.from_user)
            assert await _active(db, CHAT_ID, now=1e12) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_k3_off_byte_parity_and_no_write(self, tmp_path, monkeypatch):
        from services import bot_persona
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        db = await _db(tmp_path)
        _force_persona_flag(monkeypatch, True)
        _persona_patch(monkeypatch)
        _gates(monkeypatch, style=False, form=True)
        try:
            llm = FakeLLM(text="ок")
            svc = _make_service(memory=FakeMemory(), db=db, llm=llm)
            msg = _message(text="Бот, отвечай короче", message_id=904)
            await svc.handle(_bot(), msg, msg.from_user)
            from tests.test_mca08_character_speech import _persona_block
            assert llm.messages[0]["content"] == (
                CHAT_SYSTEM_PROMPT + "\n\n" + _persona_block() + "\n\n"
                + bot_persona.build_character_rules_block())
            assert await _active(db, CHAT_ID, now=1e12) == []
            assert await ss.handle_command(
                db, chat_id=CHAT_ID, user_id=7, args="off") is None
        finally:
            await db.close()


# ── K3/K4: реестры, reason codes, каталог ───────────────────────────────────

class TestStyleFormKillSwitches:
    def test_registered_default_on_and_resolvers(self):
        expected = {
            "MCA_STYLE_SCOPE_ENABLED": "style_scope_enabled",
            "MCA_POSTPROCESS_FORM_GUARD_ENABLED":
                "postprocess_form_guard_enabled",
        }
        for name, resolver in expected.items():
            default, parity = mca_gates.KILL_SWITCHES[name]
            assert default is True and parity
            assert reg._GATE_RESOLVERS[name] == resolver
            assert callable(getattr(mca_gates, resolver))
            assert getattr(settings, name) is True
        assert mca_gates.style_scope_chat_ttl_days() == 7
        assert mca_gates.style_scope_topic_ttl_days() == 30

    def test_reason_codes_plus_nine_total(self):
        sanctioned = {
            "style_request_recorded", "style_request_ambiguous_skipped",
            "style_request_denied", "style_request_superseded",
            "style_request_expired", "clarification_asked",
            "clarification_assumption_used", "form_guard_rejected",
            "form_guard_leak_blocked",
        }
        assert sanctioned <= mca_events.REASON_CODES


# ── D: form-гарды G1–G3 ─────────────────────────────────────────────────────

class TestFormContractGuards:
    def test_clean_form_change_passes(self):
        contract = FormContract(
            source_text="у меня 1 000 рублей и не было времени")
        assert check_form_contract(
            "было у меня 1 000 рублей, времени не было", contract) is None

    @pytest.mark.parametrize("candidate,reason", [
        ("у меня 2 000 рублей и не было времени", FORM_GUARD_REJECTED),
        ("у меня 1 000 рублей и было время", FORM_GUARD_REJECTED),
        ("у меня 1 000 рублей fact:12 и не было времени",
         FORM_GUARD_LEAK_BLOCKED),
        ("у меня 1 000 рублей <thought>x</thought> и не было времени",
         FORM_GUARD_LEAK_BLOCKED),
        ("у меня 1 000 рублей <<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА] и не было времени",
         FORM_GUARD_LEAK_BLOCKED),
    ])
    def test_rejects(self, candidate, reason):
        contract = FormContract(
            source_text="у меня 1 000 рублей и не было времени")
        assert check_form_contract(candidate, contract) == reason

    def test_added_negation_rejected(self):
        contract = FormContract(source_text="баланс 500 рублей")
        assert check_form_contract("не 500 рублей на балансе", contract) == \
            FORM_GUARD_REJECTED

    def test_number_normalization_variants(self):
        contract = FormContract(source_text="счёт 1 000,5 рубля")
        for variant in ("счёт 1000,5 рубля", "счёт 1\u00a0000,5 рубля",
                        "счёт 1000.5 рубля"):
            assert check_form_contract(variant, contract) is None

    def test_roster_names_g3(self):
        contract = FormContract(source_text="привет, Вася",
                                roster_names=("Вася", "Петя"))
        assert check_form_contract("Вася, привет", contract) is None
        assert check_form_contract("привет, Петя", contract) == \
            FORM_GUARD_REJECTED
        assert check_form_contract("привет, вася", contract) is None
        # границы слов: «Василиса» не ловится именем «Вася»
        assert check_form_contract("привет, Василиса", contract) is None

    def test_addressee_field_does_not_break(self):
        contract = FormContract(source_text="иди сюда", addressee="Вася")
        assert check_form_contract("ну иди сюда", contract) is None

    def test_no_action_or_fact_layer_touch(self):
        from services import negative_constraints as nc
        source = inspect.getsource(ss) + inspect.getsource(nc)
        for forbidden in ("CoordinatorDecision", "ACTION_SILENT",
                          "ACTION_REACT", "EvidenceBundle"):
            assert forbidden not in source


class TestVerbalizeFormFlow:
    @pytest.mark.asyncio
    async def test_reject_then_clean_retry_uses_form_prompt(self):
        seen: list = []

        async def gen(messages):
            seen.append(messages[-1]["content"] if len(messages) > 1 else "")
            return "13 штук" if len(seen) == 1 else "двенадцать штук"

        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            form_contract=FormContract(source_text="двенадцать штук"),
            fallback_text="двенадцать штук")
        assert text == "двенадцать штук"
        assert len(seen) == 2
        assert seen[1] == FORM_GUARD_RETRY_SYSTEM_PROMPT
        assert stats["form_retry"] is True
        assert stats["form_guard_rejects"] == 1
        assert stats["form_fallback"] is False
        assert stats["attempts"] == 2 and stats["retries"] == 1

    @pytest.mark.asyncio
    async def test_exhausted_bounded_retry_and_fallback_text(self):
        calls = []

        async def gen(messages):
            calls.append(1)
            return "13 штук"

        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], max_retries=2,
            form_contract=FormContract(source_text="двенадцать штук"),
            fallback_text="двенадцать штук (проверенный)")
        assert len(calls) == 2                      # ровно ≤1 form-повтор
        assert text == "двенадцать штук (проверенный)"
        assert stats["form_fallback"] is True
        assert stats["fallback"] is True
        assert stats["form_guard_rejects"] == 2
        assert stats["retries"] == 1

    @pytest.mark.asyncio
    async def test_no_fallback_text_degraded_best(self):
        async def gen(messages):
            return "13 штук"

        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            form_contract=FormContract(source_text="двенадцать штук"))
        assert text == "13 штук"
        assert stats["form_fallback"] is True
        assert stats["form_guard_reason"] == FORM_GUARD_REJECTED

    @pytest.mark.asyncio
    async def test_form_ok_preferred_over_fewer_cliches(self):
        replies = ["как ИИ 13", "подводя итог и в заключение avatar"]

        async def gen(messages):
            return replies.pop(0)

        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], max_retries=1,
            form_contract=FormContract(source_text="avatar"))
        # второй вариант form-ok (имя avatar из source), хотя клише больше
        assert text == "подводя итог и в заключение avatar"
        assert stats["form_guard_rejects"] >= 1

    @pytest.mark.asyncio
    async def test_k4_off_ignores_contract_and_stats_parity(self, monkeypatch):
        _gates(monkeypatch, style=True, form=False)
        calls = []

        async def gen(messages):
            calls.append(1)
            return "13 штук"

        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            form_contract=FormContract(source_text="двенадцать штук"),
            fallback_text="двенадцать штук")
        assert len(calls) == 1
        assert text == "13 штук"
        assert stats == {"attempts": 1, "retries": 0, "hits": [],
                         "fallback": False, "retry_error": False,
                         "enabled": True}

    @pytest.mark.asyncio
    async def test_default_params_byte_parity(self):
        async def gen(messages):
            return "нормальный дерзкий текст"

        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}])
        assert text == "нормальный дерзкий текст"
        assert stats == {"attempts": 1, "retries": 0, "hits": [],
                         "fallback": False, "retry_error": False,
                         "enabled": True}

    @pytest.mark.asyncio
    async def test_cliche_retry_prompt_unchanged_without_form(self):
        seen = []

        async def gen(messages):
            seen.append(messages[-1]["content"] if len(messages) > 1 else "")
            return "как ИИ" if len(seen) == 1 else "чисто"

        await verbalize_validated(gen, [{"role": "user", "content": "x"}])
        assert seen[1] == CLICHE_RETRY_SYSTEM_PROMPT


# ── D: интеграция System2 + событие reason ──────────────────────────────────

class TestPostprocessDirectIntegration:
    @pytest.mark.asyncio
    async def test_reject_retry_and_event(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = _events(monkeypatch)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[
            _SYNTH_JSON, "тринадцать 13 штук", "двенадцать штук, красиво"])
        text, _mode = await svc._synthesize_direct_answer(
            1, "q", _tool_raw(text="двенадцать штук"), None)
        assert text == "двенадцать штук, красиво"
        form_events = [c for c in calls if c["event_name"] == "postprocess_form"]
        assert len(form_events) == 1
        assert form_events[0]["reason_code"] == FORM_GUARD_REJECTED
        assert form_events[0]["chat_id"] == 1

    @pytest.mark.asyncio
    async def test_exhausted_returns_verified_draft(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = _events(monkeypatch)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[
            _SYNTH_JSON, "13 штук", "13 штук"])
        text, _mode = await svc._synthesize_direct_answer(
            1, "q", _tool_raw(text="двенадцать штук"), None)
        assert text == "двенадцать штук"            # проверенный черновик
        assert any(c["event_name"] == "postprocess_form"
                   for c in calls)

    @pytest.mark.asyncio
    async def test_leak_blocked_event_reason(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = _events(monkeypatch)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[
            _SYNTH_JSON, "двенадцать штук fact:99", "двенадцать штук"])
        text, _mode = await svc._synthesize_direct_answer(
            1, "q", _tool_raw(text="двенадцать штук"), None)
        assert text == "двенадцать штук"
        form_events = [c for c in calls if c["event_name"] == "postprocess_form"]
        assert form_events[0]["reason_code"] == FORM_GUARD_LEAK_BLOCKED

    @pytest.mark.asyncio
    async def test_k4_off_no_event_and_no_new_stats(self, monkeypatch):
        import services.direct_chat_service as dcs
        _gates(monkeypatch, style=True, form=False)
        calls = _events(monkeypatch)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[
            _SYNTH_JSON, "тринадцать 13 штук"])
        text, _mode = await svc._synthesize_direct_answer(
            1, "q", _tool_raw(text="двенадцать штук"), None)
        assert text == "тринадцать 13 штук"          # байт-паритет K4 OFF
        assert not [c for c in calls if c["event_name"] == "postprocess_form"]

    @pytest.mark.asyncio
    async def test_style_directives_forwarded_to_verbalizer(self):
        import services.direct_chat_service as dcs
        from services.chat_prompts import DIRECT_VERBALIZER_SYSTEM_PROMPT
        from services.prompt_style_blocks import compose_verbalizer_system
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "ответ"])
        block = ss.render_style_block([
            {"scope": "participant", "facet": "verbosity",
             "directive": "short"}])
        await svc._synthesize_direct_answer(
            1, "q", _tool_raw(), None, style_directives=block)
        stage2 = svc.llm.generate.await_args_list[1].args[0]
        assert stage2[0]["content"] == compose_verbalizer_system(
            DIRECT_VERBALIZER_SYSTEM_PROMPT, "", "plain",
            style_directives=block)
        assert "<Style_Requests>" in stage2[0]["content"]


# ── E: реестр процессов mca-17a (T-4910) ────────────────────────────────────

class TestObservabilityRegistry:
    def test_direct_reply_stages_and_style_process(self):
        direct = reg.get_process("direct.reply")
        for stage in ("character", "speech", "form_guard"):
            assert stage in direct.stages
        assert direct.stages_to_events["speech"] == "speech_understanding"
        assert direct.stages_to_events["form_guard"] == "postprocess_form"
        style = reg.get_process("style.scope")
        assert style.version == "1"
        assert style.stages == ("ingest", "resolve", "apply", "expire")
        assert style.state_source == ("mca_style_requests",)
        assert style.enabled_gate == "MCA_STYLE_SCOPE_ENABLED"
        assert style.widget_id == "Личность/интересы"
        assert style.event_names == ("style_scope",)
        assert style.owner_feature == "mca-08"

    def test_declared_events_really_emitted_in_code(self):
        import re
        root = Path(__file__).resolve().parent.parent
        real = set()
        for path in (list((root / "services").glob("*.py"))
                     + list((root / "handlers").glob("*.py"))):
            text = path.read_text(encoding="utf-8", errors="replace")
            real |= set(re.findall(
                r'emit_mca_event\(\s*["\']([A-Za-z0-9_]+)["\']', text))
            real |= {"mca07_" + name for name in re.findall(
                r'emit_stage_event\(\s*["\']([a-z_]+)["\']', text)}
        assert {"speech_understanding", "postprocess_form"} <= real
        for process_id in ("direct.reply", "style.scope"):
            process = reg.get_process(process_id)
            declared = set(process.event_names) | set(
                process.stages_to_events.values())
            assert declared <= real, (process_id, declared - real)

    def test_off_status_is_honest_not_run_disabled(self, monkeypatch):
        style = reg.get_process("style.scope")
        assert reg.runtime_status(
            style, event_names_present=frozenset({"style_scope"})) == \
            reg.STATUS_IMPLEMENTED
        assert reg.runtime_status(
            style, event_names_present=frozenset()) == reg.STATUS_NOT_RUN
        monkeypatch.setattr(mca_gates, "style_scope_enabled", lambda: False)
        assert reg.runtime_status(style) == reg.STATUS_DISABLED
