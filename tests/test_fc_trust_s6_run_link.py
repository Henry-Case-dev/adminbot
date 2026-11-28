"""FCT-S6 U1 — сшивка прогонов и звенья трассы (28.11.2026).

Источник: `plans/features/fc-trust-01/evidence/fct-s5-s6-scoping-2026-11-28/
scoping.md` §S6/U1 + D-S6-1 (schema-изменение — отдельный релиз v50) и
D-S6-3 (события — только id/коды).

Проверяется наблюдаемый результат:

* миграция v49→v50 аддитивна: `mca_factcheck_runs.correlation_id` + индекс,
  `mca_factcheck_evidence.evidence_id/opened/strength`; существующие строки
  не меняются, `user_version` 49→50, повтор — no-op; откат SQL обратим;
* envelope- и legacy-прогоны пишут durable run с `correlation_id` =
  `pipeline_run_id`/`mca_bot_outputs.correlation_id`;
* evidence сохраняет роль (`relation`), `opened`, `strength`, `ev-N`;
* `deliver` появляется в `stage_trace` только после подтверждённой отправки.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import services.memory_backup as memory_backup_mod
from services import bot_output_ledger as bol
from services import database as dbmod
from services import factcheck_orchestrator as orch
from services import temporal_factcheck as tf
from services.database import DatabaseService, _SCHEMA_MIGRATIONS_DDL

CHAT_ID = -100777


async def _noop_backup(db, *, target_version=None):
    return None


@pytest.fixture
def fast_guard(monkeypatch):
    monkeypatch.setattr(memory_backup_mod, "migration_backup", _noop_backup)


def _make_v49_db(path) -> None:
    """Копия схемы v49: baseline + v33-таблицы фактчека + две старые строки."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(DatabaseService._SCHEMA_SQL)
        conn.execute(_SCHEMA_MIGRATIONS_DDL)
        conn.execute(dbmod._MCA_FACTCHECK_RUNS_DDL)
        conn.execute(dbmod._MCA_FACTCHECK_EVIDENCE_DDL)
        for ddl in (dbmod._MCA_FACTCHECK_RUNS_INDEX_DDL
                    + dbmod._MCA_FACTCHECK_EVIDENCE_INDEX_DDL):
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO mca_factcheck_runs (run_id, access_scope, chat_id, "
            "claim_text, factual_verdict, verdict_text, stage_trace, "
            "created_at, updated_at) VALUES "
            "('tfr-old', 'chat:1', 1, 'старый тезис', 'refuted', "
            "'старый ответ', '[{\"stage\": \"verdict\"}]', 1, 1)")
        conn.execute(
            "INSERT INTO mca_factcheck_evidence (run_id, claim_part, url, "
            "support, relation, source_kind, created_at) VALUES "
            "('tfr-old', 'c1', 'https://old.example/a', 'старая выдержка', "
            "'supports', 'secondary', 1)")
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at, "
            "checksum) VALUES (49, 'self_diag_samples_v49', "
            "strftime('%s','now'), '')")
        conn.execute("PRAGMA user_version = 49")
        conn.commit()
    finally:
        conn.close()


async def _columns(conn, table: str) -> set:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


# ── Миграция v49 → v50 ──────────────────────────────────────────────────────

class TestMigrationV50:
    @pytest.mark.asyncio
    async def test_v49_to_v50_adds_columns_and_keeps_rows(self, tmp_path,
                                                          fast_guard):
        path = tmp_path / "v49.db"
        _make_v49_db(path)
        svc = DatabaseService(str(path))
        await svc.initialize()
        try:
            cur = await svc.db.execute("PRAGMA user_version")
            assert (await cur.fetchone())[0] == 50
            run_cols = await _columns(svc.db, "mca_factcheck_runs")
            ev_cols = await _columns(svc.db, "mca_factcheck_evidence")
            assert "correlation_id" in run_cols
            assert {"evidence_id", "opened", "strength"} <= ev_cols
            cur = await svc.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_mca_factcheck_runs_correlation'")
            assert await cur.fetchone() is not None
            # существующие строки не переписаны; новые колонки NULL
            old_run = await svc.get_factcheck_run("tfr-old")
            assert old_run["claim_text"] == "старый тезис"
            assert old_run["factual_verdict"] == "refuted"
            assert old_run["correlation_id"] is None
            assert old_run["stage_trace"] == '[{"stage": "verdict"}]'
            old_ev = await svc.get_factcheck_evidence("tfr-old")
            assert old_ev[0]["url"] == "https://old.example/a"
            assert old_ev[0]["relation"] == "supports"
            assert old_ev[0]["evidence_id"] is None
            assert old_ev[0]["opened"] is None
            cur = await svc.db.execute(
                "SELECT COUNT(*) AS c FROM mca_factcheck_runs")
            assert (await cur.fetchone())["c"] == 1
        finally:
            await svc.close()

    @pytest.mark.asyncio
    async def test_reapply_is_noop(self, tmp_path, fast_guard):
        path = tmp_path / "v49_retry.db"
        _make_v49_db(path)
        first = DatabaseService(str(path))
        await first.initialize()
        await first.close()
        second = DatabaseService(str(path))
        await second.initialize()
        try:
            cur = await second.db.execute("PRAGMA user_version")
            assert (await cur.fetchone())[0] == 50
            cur = await second.db.execute(
                "SELECT COUNT(*) AS c FROM schema_migrations WHERE version=50")
            assert (await cur.fetchone())["c"] == 1
        finally:
            await second.close()

    @pytest.mark.asyncio
    async def test_rollback_sql_restores_v49_shape(self, tmp_path,
                                                   fast_guard):
        """Откат: DROP INDEX + DROP COLUMN, данные и старый SELECT целы."""
        path = tmp_path / "v50_rollback.db"
        _make_v49_db(path)
        svc = DatabaseService(str(path))
        await svc.initialize()
        await svc.close()
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                "DROP INDEX IF EXISTS idx_mca_factcheck_runs_correlation")
            conn.execute(
                "ALTER TABLE mca_factcheck_runs DROP COLUMN correlation_id")
            for column in ("evidence_id", "opened", "strength"):
                conn.execute(
                    f"ALTER TABLE mca_factcheck_evidence DROP COLUMN {column}")
            conn.execute("PRAGMA user_version = 49")
            conn.commit()
            run_cols = {r[1] for r in
                        conn.execute("PRAGMA table_info(mca_factcheck_runs)")}
            ev_cols = {r[1] for r in
                       conn.execute("PRAGMA table_info(mca_factcheck_evidence)")}
            assert "correlation_id" not in run_cols
            assert not ({"evidence_id", "opened", "strength"} & ev_cols)
            row = conn.execute(
                "SELECT claim_text, factual_verdict FROM mca_factcheck_runs "
                "WHERE run_id='tfr-old'").fetchone()
            assert row == ("старый тезис", "refuted")
            ev = conn.execute(
                "SELECT url, relation FROM mca_factcheck_evidence "
                "WHERE run_id='tfr-old'").fetchone()
            assert ev == ("https://old.example/a", "supports")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == 49
        finally:
            conn.close()


# ── Сшивка прогона: correlation_id и evidence-провенанс ────────────────────

def _env(**overrides):
    base = dict(
        claim_id="c-1", chat_id=CHAT_ID, target_tg_message_id=10,
        target_revision=1, target_content_hash="hash", trigger_tg_message_id=11,
        claim_text="в 2022 году ввели новый налог", claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1760000000)
    base.update(overrides)
    return tf.TemporalClaimEnvelope(**base)


def _verdict():
    return tf.TemporalVerdict(
        factual_verdict="supported", temporal_status="current",
        evaluated_period={"from": 1665277000, "to": 1665277000,
                          "precision": "day"},
        assessment_mode="contextual", as_of=1760000000,
        evidence_refs=("ev-1",), uncertainty={}, parts=(), reason=None)


class _EnvelopeService:
    def __init__(self, run):
        self.run = run

    async def check_claim_envelope(self, envelope, chat_context=None,
                                   run_id=None):
        return self.run


class _LegacyService:
    async def check_claim(self, *args, **kwargs):
        return "legacy verdict text"


def _run_result():
    evidence_row = {
        "evidence_id": "ev-1", "claim_part": "c1",
        "url": "https://example.org/a", "support": "выдержка",
        "published_at": 1665277000, "published_at_source": "page",
        "retrieved_at": 1760000001, "temporal_relevance": None,
        "relation": "supports", "source_kind": "secondary",
        "opened": True, "strength": "direct",
    }
    return tf.TemporalRunResult(
        envelope=_env(), verdict=_verdict(), verdict_text="ответ",
        evidence_rows=(evidence_row,),
        stage_trace=({"stage": "verdict", "outcome": "success"},))


class TestRunLink:
    @pytest.mark.asyncio
    async def test_envelope_run_links_pipeline_and_ledger(self, tmp_path):
        db = DatabaseService(str(tmp_path / "link.db"))
        await db.initialize()
        try:
            req = orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=11,
                target_tg_message_id=10, target_text="тезис")
            await orch._run_envelope_branch(
                req, _EnvelopeService(_run_result()), db, None, _env(),
                None, tf, None, run_id="corr-env")
            runs = await db.list_factcheck_runs(chat_id=CHAT_ID)
            assert len(runs) == 1
            stored = runs[0]
            assert stored["correlation_id"] == "corr-env"
            # evidence провенанс сохранён (не только в публичном тексте)
            evidence = await db.get_factcheck_evidence(stored["run_id"])
            assert evidence[0]["evidence_id"] == "ev-1"
            assert evidence[0]["relation"] == "supports"
            assert evidence[0]["opened"] == 1
            assert evidence[0]["strength"] == "direct"
            # тот же correlation_id — в ledger отправленного текста
            from unittest.mock import patch
            with patch.object(bol, "ledger_enabled", lambda: True):
                await bol.record_factcheck_output(
                    db, chat_id=CHAT_ID, tg_message_id=60, text="ответ",
                    correlation_id="corr-env")
            cur = await db.db.execute(
                "SELECT correlation_id FROM mca_bot_outputs WHERE chat_id = ?",
                (CHAT_ID,))
            ledger_ids = {r["correlation_id"] for r in await cur.fetchall()}
            assert "corr-env" in ledger_ids
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_deliver_stage_appended_after_send(self, tmp_path):
        db = DatabaseService(str(tmp_path / "deliver.db"))
        await db.initialize()
        try:
            req = orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=11,
                target_tg_message_id=10, target_text="тезис")
            await orch._run_envelope_branch(
                req, _EnvelopeService(_run_result()), db, None, _env(),
                None, tf, None, run_id="corr-deliver")
            run = (await db.list_factcheck_runs(chat_id=CHAT_ID))[0]
            trace = json.loads(run["stage_trace"])
            assert all(item["stage"] != "deliver" for item in trace)
            assert await tf.record_delivery_stage(
                db, correlation_id="corr-deliver")
            run = (await db.list_factcheck_runs(chat_id=CHAT_ID))[0]
            trace = json.loads(run["stage_trace"])
            assert trace[-1]["stage"] == "deliver"
            assert trace[-1]["outcome"] == "success"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_legacy_branch_writes_run(self, tmp_path):
        db = DatabaseService(str(tmp_path / "legacy.db"))
        await db.initialize()
        try:
            req = orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=11,
                target_tg_message_id=10, target_text="legacy тезис")
            verdict = await orch._run_legacy_branch(
                req, _LegacyService(), None, db=db,
                correlation_id="corr-legacy")
            assert verdict.route == "legacy_single"
            runs = await db.list_factcheck_runs(chat_id=CHAT_ID)
            assert len(runs) == 1
            run = runs[0]
            assert run["correlation_id"] == "corr-legacy"
            assert run["pipeline_version"] == "legacy_single"
            assert run["claim_text"] == "legacy тезис"
            assert run["verdict_text"] == "legacy verdict text"
            assert json.loads(run["stage_trace"]) == [
                {"stage": "verdict", "outcome": "success"}]
            assert await tf.record_delivery_stage(
                db, correlation_id="corr-legacy")
            run = (await db.list_factcheck_runs(chat_id=CHAT_ID))[0]
            assert json.loads(run["stage_trace"])[-1] == {
                "stage": "deliver", "outcome": "success"}
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_record_temporal_run_without_pipeline_id_self_links(
            self, tmp_path):
        """Manual-путь: run связывается со своим run_id, который уходит в
        ledger — звено не теряется."""
        db = DatabaseService(str(tmp_path / "manual.db"))
        await db.initialize()
        try:
            run_id = await tf.record_temporal_run(db, _run_result(),
                                                  scope="chat:1")
            stored = await db.get_factcheck_run(run_id)
            assert stored["correlation_id"] == run_id
        finally:
            await db.close()
