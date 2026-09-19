"""F9 round 10.24 (ADR-1024-2): retention диска.

Покрытие spec §7:
  (a) prune_db_backups — оба префикса, ровно 1 новейший;
  (b) imported_history_*.jsonl НИКОГДА не удаляется (immutability);
  (c) не-history JSONL старше 180 дней удаляется, свежие — нет;
  (d) apply_cleanup(verify=True) без валидного бэкапа → abort (fail-closed);
  (e) CLI dry-run не удаляет, --apply удаляет и возвращает отчёт;
  (f) forecast_monthly детерминирован (mtime/размеры);
  (g) логи/отчёт без секретов (egress-сканер).
"""
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest

import manage
import services.disk_retention as dr
from config.settings import Settings


def _set_mtime(path: Path, days_ago: float) -> None:
    ts = time.time() - days_ago * 86400.0
    os.utime(path, (ts, ts))


def _mk(path: Path, content=b"x", days_ago: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    if days_ago:
        _set_mtime(path, days_ago)
    return path


# ── (a) ротация бэкапов БД: оба префикса, ровно 1 новейший ──────────────────

class TestPruneDbBackups:
    def test_covers_both_prefixes_keeps_one_newest(self, tmp_path):
        old = _mk(tmp_path / "local_database_20260101.db", b"x", days_ago=10)
        mid = _mk(tmp_path / "local_database_20260201.db", b"x", days_ago=5)
        new = _mk(tmp_path / "memory_rebuild_20260301_000000_000000.db", b"x",
                  days_ago=1)
        removed = dr.prune_db_backups(tmp_path)
        assert set(removed) == {str(old), str(mid)}
        assert new.exists()
        assert sorted(tmp_path.glob("*.db")) == [new]

    def test_keep_param_respected(self, tmp_path):
        a = _mk(tmp_path / "local_database_20260101.db", b"x", days_ago=10)
        b = _mk(tmp_path / "memory_rebuild_20260201_000000_000000.db", b"x",
                days_ago=5)
        c = _mk(tmp_path / "local_database_20260301.db", b"x", days_ago=1)
        removed = dr.prune_db_backups(tmp_path, keep=2)
        assert removed == [str(a)]
        assert b.exists() and c.exists()

    def test_facts_exports_keep_one(self, tmp_path):
        a = _mk(tmp_path / "facts_20260101.txt", "a", days_ago=10)
        b = _mk(tmp_path / "facts_20260201.txt", "b", days_ago=1)
        removed = dr.prune_facts_exports(tmp_path)
        assert removed == [str(a)]
        assert b.exists()

    def test_safety_backup_prunes_old_memory_rebuild(self, tmp_path):
        """Корневая причина +6.4 ГБ (ADR-1024-2 Context п.1): safety-бэкапы
        не накапливаются — ротация зовётся и из memory_rebuild."""
        from services import memory_rebuild as mr

        src = tmp_path / "live.db"
        con = sqlite3.connect(str(src))
        con.execute("CREATE TABLE t (x INTEGER)")
        con.commit()
        con.close()
        bdir = tmp_path / "backups"
        bdir.mkdir()
        for i in range(3):
            _mk(bdir / f"memory_rebuild_20260{i}01_000000_000000.db",
                b"old", days_ago=10 - i)
        target = mr.create_safety_backup(str(src), backup_dir=str(bdir))
        remaining = sorted(bdir.glob("memory_rebuild_*.db"))
        assert len(remaining) == 1
        assert Path(target).exists()
        assert remaining[0] == Path(target)


# ── (b) история сообщений неприкосновенна ───────────────────────────────────

class TestHistoryImmutable:
    def test_name_deny_list(self, tmp_path):
        f = _mk(tmp_path / "imported_history_20200101.jsonl",
                '{"chat_id":1}\n', days_ago=400)
        assert dr.classify(f) == "immutable"

    def test_content_sniff_detects_raw_history(self, tmp_path):
        f = _mk(tmp_path / "dump_random.jsonl",
                '{"chat_id":1,"user_id":2,"text":"привет","timestamp":1}\n',
                days_ago=400)
        assert dr.classify(f) == "immutable"

    def test_content_sniff_telegram_export_root(self, tmp_path):
        f = _mk(tmp_path / "export_2020.jsonl",
                '{"messages":[{"text":"x"}]}\n', days_ago=400)
        assert dr.classify(f) == "immutable"

    def test_never_in_plan_and_never_deleted(self, tmp_path):
        imp = _mk(tmp_path / "imported_history_20200101.jsonl",
                  '{"chat_id":1}\n', days_ago=1000)
        gen = _mk(tmp_path / "memory_generated_rebuild_20200101.jsonl",
                  '{"id":1}\n', days_ago=1000)
        _mk(tmp_path / "local_database_20260101.db", b"x", days_ago=1)
        plan = dr.plan_cleanup([tmp_path])
        paths = {item["path"] for item in plan}
        assert str(imp) not in paths          # история — не кандидат
        assert str(gen) in paths              # снимок досье — режем
        dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
        assert imp.exists()                   # НЕ удалена
        assert not gen.exists()

    def test_hard_even_if_flag_false(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(Settings, "HISTORY_JSONL_IMMUTABLE", False)
        f = _mk(tmp_path / "imported_history_x.jsonl", '{"chat_id":1}\n',
                days_ago=500)
        with caplog.at_level(logging.WARNING):
            assert dr.classify(f) == "immutable"
            assert dr.plan_cleanup([tmp_path]) == []
        assert f.exists()


# ── (c) окно не-history JSONL ───────────────────────────────────────────────

class TestJsonlWindow:
    def test_old_deleted_fresh_kept(self, tmp_path):
        old = _mk(tmp_path / "memory_generated_a_20200101.jsonl",
                  '{"id":1}\n', days_ago=200)
        fresh = _mk(tmp_path / "memory_generated_b_20260101.jsonl",
                    '{"id":2}\n', days_ago=10)
        plan = dr.plan_cleanup([tmp_path])
        paths = {item["path"] for item in plan}
        assert str(old) in paths
        assert str(fresh) not in paths
        item = next(i for i in plan if i["path"] == str(old))
        assert item["category"] == "jsonl_retention"
        assert "older_than_180d" in item["reason"]


# ── (d) fail-closed / идемпотентность ───────────────────────────────────────

class TestFailClosed:
    def test_abort_without_valid_backup(self, tmp_path):
        old_db = _mk(tmp_path / "local_database_20260101.db", b"x", days_ago=5)
        # «новейший» бэкап нулевого размера — не является страховкой.
        bad = _mk(tmp_path / "memory_rebuild_20260201_000000_000000.db", b"",
                  days_ago=1)
        plan = dr.plan_cleanup([tmp_path])
        assert any(i["category"] == "db_backup" for i in plan)
        result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
        assert result["aborted_reason"] == "no_valid_backup"
        assert result["deleted"] == 0
        assert old_db.exists() and bad.exists()

    def test_apply_with_valid_backup(self, tmp_path):
        old_db = _mk(tmp_path / "local_database_20260101.db", b"x", days_ago=5)
        new_db = _mk(tmp_path / "memory_rebuild_20260201_000000_000000.db",
                     b"valid", days_ago=1)
        plan = dr.plan_cleanup([tmp_path])
        result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
        assert result["aborted_reason"] == ""
        assert result["deleted"] >= 1
        assert not old_db.exists() and new_db.exists()

    def test_idempotent_second_apply(self, tmp_path):
        _mk(tmp_path / "memory_generated_old.jsonl", '{"id":1}\n',
            days_ago=200)
        _mk(tmp_path / "local_database_20260101.db", b"valid", days_ago=1)
        plan = dr.plan_cleanup([tmp_path])
        first = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
        second = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
        assert first["deleted"] >= 1
        assert second["deleted"] == 0
        assert second["skipped"] >= 1

    def test_empty_plan_is_noop(self):
        assert dr.apply_cleanup([]) == {
            "deleted": 0, "bytes_freed": 0, "aborted_reason": "",
            "skipped": 0, "errors": 0, "categories": {}}


# ── (e) CLI ─────────────────────────────────────────────────────────────────

class TestCli:
    def test_dry_run_does_not_delete_then_apply(self, tmp_path, capsys):
        old = _mk(tmp_path / "memory_generated_old.jsonl", '{"id":1}\n',
                  days_ago=200)
        _mk(tmp_path / "local_database_20260101.db", b"valid", days_ago=1)
        rc = manage.main(["disk", "cleanup", "--dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0 and "DRY-RUN" in out
        assert old.exists()

        rc2 = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
        out2 = capsys.readouterr().out
        assert rc2 == 0 and "APPLY" in out2
        assert not old.exists()

    def test_audit_is_read_only(self, tmp_path, capsys):
        imp = _mk(tmp_path / "imported_history_20200101.jsonl",
                  '{"chat_id":1}\n', days_ago=400)
        rc = manage.main(["disk", "audit", "--dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "immutable" in out
        assert imp.exists()

    def test_cleanup_aborts_without_backup(self, tmp_path, capsys):
        old = _mk(tmp_path / "memory_generated_old.jsonl", '{"id":1}\n',
                  days_ago=200)
        rc = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 1 and "ABORTED" in out
        assert old.exists()      # fail-closed: ни одного удаления


# ── (f) прогноз ─────────────────────────────────────────────────────────────

class TestForecast:
    def test_deterministic_on_fixtures(self, tmp_path):
        now = 1_700_000_000.0
        a = _mk(tmp_path / "local_database_x.db", b"a" * 1000, days_ago=0)
        os.utime(a, (now - 10 * 86400, now - 10 * 86400))
        b = _mk(tmp_path / "memory_generated_a.jsonl", '{"id":1}\n')
        os.utime(b, (now - 5 * 86400, now - 5 * 86400))
        report = dr.forecast_monthly([tmp_path], now=now)
        recent = a.stat().st_size + b.stat().st_size
        assert report["recent_bytes"] == recent
        assert report["span_days"] == 10.0
        per_day = recent / 10.0
        assert report["bytes_per_day"] == int(per_day)
        assert report["projected_30d"] == int(per_day * 30)

    def test_empty_dirs_zero(self, tmp_path):
        report = dr.forecast_monthly([tmp_path], now=1_700_000_000.0)
        assert report["bytes_per_day"] == 0
        assert report["projected_30d"] == 0


# ── (g) egress: без секретов ────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+\S+"
    r"|bearer\s+[A-Za-z0-9._\-]{12,}"
    r"|\b(?:sk|gsk|or|tvly)[-_][A-Za-z0-9_\-]{6,}"
    r"|://[^/\s:@]+:[^/\s@]+@)")


class TestEgress:
    def test_no_secret_in_logs_or_output(self, tmp_path, caplog, capsys):
        secret = "sk-EGRESSZZZ999888777666"
        _mk(tmp_path / "memory_generated_old.jsonl",
            '{"id":1,"fact":"' + secret + '"}\n', days_ago=200)
        _mk(tmp_path / "local_database_20260101.db", b"valid", days_ago=1)
        with caplog.at_level(logging.DEBUG):
            rc = manage.main(["disk", "audit", "--dir", str(tmp_path)])
            rc2 = manage.main(["disk", "cleanup", "--apply", "--dir",
                               str(tmp_path)])
        out = capsys.readouterr().out
        blob = out + "\n" + "\n".join(r.getMessage() for r in caplog.records)
        assert rc == 0 and rc2 == 0
        assert secret not in blob
        assert not _SECRET_RE.search(blob)


# ── флаги ───────────────────────────────────────────────────────────────────

class TestFlags:
    def test_log_retention_default_7(self):
        assert int(Settings.LOG_RETENTION_DAYS) == 7

    def test_db_keep_capped_at_one(self, monkeypatch):
        monkeypatch.setattr(Settings, "DB_BACKUP_KEEP", 5)
        assert dr._db_keep() == 1

    def test_kill_switch_disables_retention(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Settings, "DISK_RETENTION_ENABLED", False)
        _mk(tmp_path / "local_database_old.db", b"x", days_ago=10)
        _mk(tmp_path / "local_database_new.db", b"y", days_ago=1)
        assert dr.prune_db_backups(tmp_path) == []
        assert dr.plan_cleanup([tmp_path]) == []
        assert (tmp_path / "local_database_old.db").exists()
