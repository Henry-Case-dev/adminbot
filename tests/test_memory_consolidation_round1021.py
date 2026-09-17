"""F4 (`paradigm-thresholds-consolidation-round1021`, ADR-1021-4 /
T-1971…T-1979): READ-ONLY аудит, идемпотентная Memory Consolidation,
миграция порогов глубокого сна и наблюдаемость мета-слоя.

Покрытие spec §5:
  * аудит — флаги/счётчики/точка обрыва, ветвление A/B (fail-open);
  * `consolidate` идемпотентен (дедуп `_paradigm_dedup_keys`), `dry_run`
    ничего не пишет, ранжирование по числу опор;
  * PG-миграция порогов (в т.ч. принудительное снижение) идемпотентна,
    обратима, кастом не трогает, PG down/disabled → skip;
  * метрики `memory_health` отдаются, fail-open.
"""
import json
import time

import pytest

from services import config_migrations as cm
from services import memory_maintenance as mm
from services import worker_settings
from services.database import DatabaseService
from services.memory_health import collect_metrics


async def _db(tmp_path, name="f4.db"):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


def _patch_flags(monkeypatch, *, dream, deep, decay):
    async def _resolve(key, *, chat_id=None, default=None, log_source=False):
        return {"memory.dream_enabled": dream,
                "flags.deep_sleep_enabled": deep,
                "flags.belief_decay_enabled": decay}.get(key, default)
    monkeypatch.setattr(worker_settings, "resolve_setting_cached", _resolve)


class _FakeCache:
    pg_available = True

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    async def set(self, key, value, scope=None):
        self.data[key] = value


class TestAudit:
    @pytest.mark.asyncio
    async def test_flags_off_branch_a(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "audit_a.db")
        try:
            _patch_flags(monkeypatch, dream=False, deep=False, decay=False)
            out = await mm.collect_paradigm_audit(db)
            assert out["flags"] == {"dream_enabled": False,
                                    "deep_sleep_enabled": False,
                                    "belief_decay_enabled": False}
            assert out["break_point"] == "flags_off"
            assert out["branch"] == "A"
            assert out["paradigms_total"] == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_no_dream_runs_branch_a(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "audit_b.db")
        try:
            _patch_flags(monkeypatch, dream=True, deep=True, decay=False)
            out = await mm.collect_paradigm_audit(db)
            assert out["break_point"] == "no_dream_runs"
            assert out["branch"] == "A"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_no_paradigms_branch_b(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "audit_c.db")
        try:
            _patch_flags(monkeypatch, dream=True, deep=True, decay=False)
            now = int(time.time())
            await db.log_dream_event(-100, now, kind="run", tokens=10)
            await db.log_dream_event(-100, now, kind="deep_skip", tokens=0,
                                     status="no_anchors")
            out = await mm.collect_paradigm_audit(db)
            assert out["dream_log"]["run"] == 1
            assert out["dream_log"]["deep_skip"] == 1
            assert out["break_point"] == "no_paradigms"
            assert out["branch"] == "B"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_ok_with_paradigm(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "audit_d.db")
        try:
            _patch_flags(monkeypatch, dream=True, deep=True, decay=True)
            now = int(time.time())
            await db.log_dream_event(-100, now, kind="run", tokens=10)
            await db.log_dream_event(-100, now, kind="deep_run", tokens=10,
                                     status="ok")
            await db.insert_graph_fact(
                -100, "парадигма", "derived_belief", None, kind="belief",
                belief_meta=json.dumps({"type": "paradigm"}))
            out = await mm.collect_paradigm_audit(db)
            assert out["paradigms_total"] == 1
            assert out["paradigms_by_chat"] == {-100: 1}
            assert out["break_point"] == "ok"
        finally:
            await db.close()


async def _seed_belief(db, chat_id, text, source_ids, *, kind="belief"):
    facts = []
    for i, source in enumerate(source_ids):
        facts.append(await db.insert_graph_fact(
            chat_id, f"source {source}", "chat_history", None))
    return await db.insert_graph_fact(
        chat_id, text, "derived_belief", None, kind="belief",
        source_ids=json.dumps(facts),
        belief_meta=json.dumps({"type": kind}))


class TestConsolidate:
    @pytest.mark.asyncio
    async def test_idempotent_and_dedup(self, tmp_path):
        db = await _db(tmp_path, "con.db")
        bak = tmp_path / "bak"
        try:
            await _seed_belief(db, -100, "устойчивое убеждение",
                               ["a", "b", "c"])
            first = await mm.consolidate(
                db, chat_ids=[-100], db_path=str(tmp_path / "con.db"),
                backup_dir=bak)
            assert first["written"] == 1
            assert first["backup"]
            assert await db.count_paradigms(-100) == 1
            second = await mm.consolidate(
                db, chat_ids=[-100], db_path=str(tmp_path / "con.db"),
                backup_dir=bak)
            assert second["written"] == 0
            assert second["reasons"].get("duplicate") == 1
            assert await db.count_paradigms(-100) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, tmp_path):
        db = await _db(tmp_path, "con_dry.db")
        try:
            await _seed_belief(db, -100, "убеждение", ["a", "b"])
            out = await mm.consolidate(
                db, chat_ids=[-100], dry_run=True,
                db_path=str(tmp_path / "con_dry.db"), backup_dir=tmp_path / "b")
            assert out["candidates"] == 1 and out["written"] == 0
            assert out["backup"] == "" and out["archived"] == 0
            assert await db.count_paradigms(-100) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_min_sources_skips_weak(self, tmp_path):
        db = await _db(tmp_path, "con_min.db")
        try:
            await _seed_belief(db, -100, "слабое убеждение", ["a"])
            out = await mm.consolidate(
                db, chat_ids=[-100], min_sources=2,
                db_path=str(tmp_path / "con_min.db"), backup_dir=tmp_path / "b")
            assert out["written"] == 0
            assert out["reasons"].get("below_min_sources") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_ranking_prefers_more_sources(self, tmp_path):
        db = await _db(tmp_path, "con_rank.db")
        try:
            await _seed_belief(db, -100, "strong", ["a", "b", "c"])
            await _seed_belief(db, -100, "weak", ["d", "e"])
            out = await mm.consolidate(
                db, chat_ids=[-100], limit=1,
                db_path=str(tmp_path / "con_rank.db"), backup_dir=tmp_path / "b")
            # limit=1 → обработано только самое сильное убеждение
            assert out["candidates"] == 1 and out["written"] == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cap_limits_writes_per_run(self, tmp_path):
        """S10.21-1: кандидатов больше капа → пишем не больше
        `deep_sleep_max_paradigms_per_run` за прогон (как Deep Sleep)."""
        cap = max(1, int(mm.hot.get(
            "limits.deep_sleep_max_paradigms_per_run",
            mm.settings.DEEP_SLEEP_MAX_PARADIGMS)))
        db = await _db(tmp_path, "con_cap.db")
        bak = tmp_path / "bak"
        try:
            for i in range(cap + 2):
                await _seed_belief(db, -100, f"убеждение {i}",
                                   [f"a{i}", f"b{i}"])
            first = await mm.consolidate(
                db, chat_ids=[-100], db_path=str(tmp_path / "con_cap.db"),
                backup_dir=bak)
            assert first["max_paradigms"] == cap
            assert first["candidates"] == cap
            assert first["written"] == cap
            assert first["reasons"].get("cap_reached") == 2
            assert await db.count_paradigms(-100) == cap
            # повторный прогон: уже записанное — duplicate, кап снова держится
            second = await mm.consolidate(
                db, chat_ids=[-100], db_path=str(tmp_path / "con_cap.db"),
                backup_dir=bak)
            assert second["written"] <= cap
            assert second["reasons"].get("duplicate") == cap
            assert await db.count_paradigms(-100) == cap + second["written"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_no_db_path_is_fail_closed(self, tmp_path):
        # F4 fix-round 2 (Medium): без страховки боевой прогон НЕ пишет.
        db = await _db(tmp_path, "con_failclosed.db")
        try:
            await _seed_belief(db, -100, "устойчивое убеждение", ["a", "b"])
            out = await mm.consolidate(db, chat_ids=[-100])
            assert out["written"] == 0
            assert out["candidates"] == 1
            assert out["reasons"].get("backup_unavailable") == 1
            assert await db.count_paradigms(-100) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_allow_no_backup_explicit_opt_in(self, tmp_path):
        # Явный opt-in сохраняет прежнее «пишем без страховки» поведение.
        db = await _db(tmp_path, "con_optin.db")
        try:
            await _seed_belief(db, -100, "устойчивое убеждение", ["a", "b"])
            out = await mm.consolidate(db, chat_ids=[-100],
                                       allow_no_backup=True)
            assert out["written"] == 1
            assert out["backup"] == ""
            assert "backup_unavailable" not in out["reasons"]
            assert await db.count_paradigms(-100) == 1
        finally:
            await db.close()


class TestConsolidateSafety:
    @pytest.mark.asyncio
    async def test_backup_and_archive_before_write(self, tmp_path):
        db = await _db(tmp_path, "con_safe.db")
        bak = tmp_path / "bak"
        try:
            await _seed_belief(db, -100, "устойчивое убеждение",
                               ["a", "b", "c"])
            out = await mm.consolidate(
                db, chat_ids=[-100], db_path=str(tmp_path / "con_safe.db"),
                backup_dir=bak)
            assert out["written"] == 1
            assert out["candidates"] == out["archived"] == 1
            assert out["backup"]
            backups = list(bak.glob("memory_rebuild_*.db"))
            assert backups and backups[0].stat().st_size > 0
            files = list(bak.glob("memory_generated_consolidate_*.jsonl"))
            assert len(files) == 1
            payload = json.loads(files[0].read_text(encoding="utf-8").strip())
            assert payload["fact"] == "устойчивое убеждение"
            assert payload["chat_id"] == -100
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_backup_then_archive_then_write_order(
            self, tmp_path, monkeypatch):
        from services import memory_rebuild as mr
        from services.dream_worker import DreamWorker

        db = await _db(tmp_path, "con_order.db")
        bak = tmp_path / "bak"
        events: list[str] = []
        try:
            await _seed_belief(db, -100, "убеждение", ["a", "b"])
            real_backup = mr._safety_backup
            real_archive = mr._archive_generated_rows
            real_write = DreamWorker._write_paradigm

            async def _spy_backup(*args, **kwargs):
                result = await real_backup(*args, **kwargs)
                events.append("backup")
                return result

            async def _spy_archive(*args, **kwargs):
                result = await real_archive(*args, **kwargs)
                events.append("archive")
                return result

            async def _spy_write(self, *args, **kwargs):
                events.append("write")
                return await real_write(self, *args, **kwargs)

            monkeypatch.setattr(mr, "_safety_backup", _spy_backup)
            monkeypatch.setattr(mr, "_archive_generated_rows", _spy_archive)
            monkeypatch.setattr(DreamWorker, "_write_paradigm", _spy_write)
            out = await mm.consolidate(
                db, chat_ids=[-100], db_path=str(tmp_path / "con_order.db"),
                backup_dir=bak)
            assert out["written"] == 1
            assert events == ["backup", "archive", "write"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_archive_mismatch_aborts_write(self, tmp_path, monkeypatch):
        from services import memory_rebuild as mr

        db = await _db(tmp_path, "con_fail.db")
        try:
            await _seed_belief(db, -100, "убеждение", ["a", "b"])

            async def _bad_archive(rows, directory, label):
                return True, 999, str(directory / "x.jsonl")
            monkeypatch.setattr(mr, "_archive_generated_rows", _bad_archive)
            out = await mm.consolidate(
                db, chat_ids=[-100], db_path=str(tmp_path / "con_fail.db"),
                backup_dir=tmp_path / "b")
            assert out["reasons"].get("archive_mismatch") == 1
            assert out["written"] == 0
            assert await db.count_paradigms(-100) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_dry_run_no_backup_no_archive(self, tmp_path):
        db = await _db(tmp_path, "con_dry_safe.db")
        bak = tmp_path / "bak"
        try:
            await _seed_belief(db, -100, "убеждение", ["a", "b"])
            out = await mm.consolidate(
                db, chat_ids=[-100], dry_run=True,
                db_path=str(tmp_path / "con_dry_safe.db"), backup_dir=bak)
            assert out["written"] == 0
            assert out["backup"] == "" and out["archived"] == 0
            assert not bak.exists()
        finally:
            await db.close()


class TestThresholdMigration:
    @pytest.mark.asyncio
    async def test_enabled_updates_then_idempotent(self):
        key = "memory.deep_sleep_min_interval_hours"
        cache = _FakeCache({key: 20})
        report = await cm.migrate_deep_sleep_thresholds(cache, enabled=True)
        assert report == {key: "updated"}
        assert cache.data[key] == 6
        again = await cm.migrate_deep_sleep_thresholds(cache, enabled=True)
        assert again == {}
        assert cache.data[key] == 6

    @pytest.mark.asyncio
    async def test_disabled_is_noop(self):
        key = "memory.deep_sleep_min_interval_hours"
        cache = _FakeCache({key: 20})
        report = await cm.migrate_deep_sleep_thresholds(cache, enabled=False)
        assert report == {} and cache.data[key] == 20

    @pytest.mark.asyncio
    async def test_custom_untouched(self):
        key = "memory.deep_sleep_min_interval_hours"
        cache = _FakeCache({key: 15})
        report = await cm.migrate_deep_sleep_thresholds(cache, enabled=True)
        assert report == {} and cache.data[key] == 15

    @pytest.mark.asyncio
    async def test_missing_key_forced_to_new(self):
        key = "memory.deep_sleep_min_interval_hours"
        cache = _FakeCache({})
        report = await cm.migrate_deep_sleep_thresholds(cache, enabled=True)
        assert report == {key: "updated"} and cache.data[key] == 6

    @pytest.mark.asyncio
    async def test_pg_unavailable_skip(self):
        cache = _FakeCache({"memory.deep_sleep_min_interval_hours": 20})
        cache.pg_available = False
        report = await cm.migrate_deep_sleep_thresholds(cache, enabled=True)
        assert report == {}

    @pytest.mark.asyncio
    async def test_default_gate_off(self, monkeypatch):
        monkeypatch.setattr(type(cm.settings),
                            "DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED", False)
        key = "memory.deep_sleep_min_interval_hours"
        cache = _FakeCache({key: 20})
        assert await cm.migrate_deep_sleep_thresholds(cache) == {}
        assert cache.data[key] == 20


class TestObservability:
    @pytest.mark.asyncio
    async def test_meta_metrics_rendered(self, tmp_path):
        db = await _db(tmp_path, "health.db")
        try:
            now = int(time.time())
            await db.insert_graph_fact(
                -100, "парадигма", "derived_belief", None, kind="belief",
                belief_meta=json.dumps({"type": "paradigm"}))
            await db.log_dream_event(-100, now, kind="run", tokens=10)
            await db.log_dream_event(-100, now, kind="deep_run", tokens=10,
                                     status="ok")
            await db.log_dream_event(-100, now, kind="deep_skip", tokens=0,
                                     status="no_anchors")
            text = await collect_metrics(db, None)
            assert "парадигмы: всего 1" in text
            assert "снов за 7д 1" in text
            assert "no_anchors 1" in text
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_metrics_fail_open(self, tmp_path):
        db = await _db(tmp_path, "health_err.db")
        try:
            async def _boom(*a, **k):
                raise RuntimeError("db boom")
            db.db.execute = _boom
            assert await collect_metrics(db, None) == ""
        finally:
            await db.close()
