"""P0-PROD-DISK-01: ротация деплой-бэкапов (keep=2 новейших).

Деплой-тулинг кладёт копию БД перед выкатом: сейчас
`pre_deploy_<ver>_<ts>.db`, legacy-снимки — `predeploy-<...>.db`, старые
харнессы — `pre_t*.db`. Исходный паттерн `pre_t*.db` не матчил реальные
имена: audit видел их как `other`, `plan_cleanup` давал candidates=0,
`prune_deploy_backups` не удалял ничего. Проверяем:
  (a) все три семейства: 3+ файлов → остаются 2 новейших;
  (b) daily/migration/history/facts не затронуты;
  (c) CLI plan/apply включает пул `deploy_backup` (`--apply` удаляет);
  (d) fail-closed: без валидного свежего daily-бэкапа deploy-копии не
      удаляются (сами себя страховкой не подтверждают);
  (e) идемпотентность повторного apply и clamp keep>=1;
  (f) живая `local_database.db`/`-wal`/`-shm` не матчится и не удаляется;
  (g) ежедневный путь `memory_backup._rotate` подрезает деплой-пул до 2.
Реальные файлы прода не используются.
"""
import os
import time
from pathlib import Path

import manage
import services.disk_retention as dr
from services.memory_backup import MemoryBackupService


def _mk(path: Path, days_ago: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    ts = time.time() - days_ago * 86400.0
    os.utime(path, (ts, ts))
    return path


def _deploy_family(tmp_path: Path) -> list[Path]:
    """4 копии в порядке старения: pre_deploy / predeploy / pre_t."""
    return [
        _mk(tmp_path / "pre_deploy_258199_20261001_120000.db", days_ago=4),
        _mk(tmp_path / "predeploy-258196-20261002_120000.db", days_ago=3),
        _mk(tmp_path / "pre_deploy_258204_20261003_120000.db", days_ago=2),
        _mk(tmp_path / "pre_t258205_20261004_120000.db", days_ago=1),
    ]


def _fresh_daily(tmp_path: Path) -> Path:
    return _mk(tmp_path / "local_database_20261004.db", days_ago=0.5)


# ── (a) паттерны и классификация ────────────────────────────────────────────

def test_prune_deploy_backups_keeps_two_newest_across_families(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    removed = dr.prune_deploy_backups(tmp_path)  # keep=2 по умолчанию
    assert set(removed) == {str(a), str(b)}
    assert c.exists() and d.exists()
    assert not a.exists() and not b.exists()


def test_classify_marks_deploy_copies_and_audit_counts_them(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    for path in (a, b, c, d):
        assert dr.classify(path) == "deploy_backup"
    report = dr.audit([tmp_path])
    assert report["categories"]["deploy_backup"]["count"] == 4


def test_prune_deploy_backups_legacy_pre_t_still_works(tmp_path):
    a = _mk(tmp_path / "pre_t5216_20261006_232333.db", days_ago=4)
    b = _mk(tmp_path / "pre_t5273_20261007_045424.db", days_ago=3)
    c = _mk(tmp_path / "pre_t5274_20261007_055326.db", days_ago=2)
    d = _mk(tmp_path / "pre_t5999_20261008_000000.db", days_ago=1)
    removed = dr.prune_deploy_backups(tmp_path)
    assert set(removed) == {str(a), str(b)}
    assert c.exists() and d.exists()


# ── (b) не-деплойные файлы неприкосновенны для deploy-пула ─────────────────

def test_prune_deploy_backups_spares_non_pattern_files(tmp_path):
    oldest = _mk(tmp_path / "pre_deploy_1000_20260101_000000.db", days_ago=30)
    _mk(tmp_path / "pre_deploy_2000_20260201_000000.db", days_ago=20)
    _mk(tmp_path / "predeploy-3000-20260301-000000.db", days_ago=10)
    daily = _mk(tmp_path / "local_database_20260101.db", days_ago=1)
    rebuild = _mk(tmp_path / "memory_rebuild_20260201_000000_000000.db",
                  days_ago=1)
    pre_mig = _mk(tmp_path / "pre_migration_20261006_121956.db", days_ago=1)
    history = _mk(tmp_path / "imported_history_2026.jsonl", days_ago=1)
    facts = _mk(tmp_path / "facts_20260101.txt", days_ago=1)
    removed = dr.prune_deploy_backups(tmp_path, keep=2)
    assert removed == [str(oldest)]
    for p in (daily, rebuild, pre_mig, history, facts):
        assert p.exists()


# ── (c) CLI plan/apply включает deploy-пул ─────────────────────────────────

def test_cli_plan_and_apply_include_deploy_pool(tmp_path, capsys):
    a, b, c, d = _deploy_family(tmp_path)
    _fresh_daily(tmp_path)

    rc = manage.main(["disk", "cleanup", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "DRY-RUN candidates=2" in out
    assert a.name in out and b.name in out
    assert "category=deploy_backup" in out
    assert "deploy_keep_newest_2" in out
    assert a.exists() and b.exists()      # dry-run ничего не удалил

    rc2 = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
    out2 = capsys.readouterr().out
    assert rc2 == 0 and "APPLY deleted=2" in out2
    assert not a.exists() and not b.exists()
    assert c.exists() and d.exists()


# ── (d) fail-closed: deploy-копии не подтверждают verify сами себе ─────────

def test_deploy_only_plan_aborts_without_fresh_daily_backup(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    plan = dr.plan_cleanup([tmp_path])
    assert {i["category"] for i in plan} == {"deploy_backup"}
    result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    assert result["aborted_reason"] == "no_valid_backup"
    assert result["deleted"] == 0
    for p in (a, b, c, d):
        assert p.exists()


# ── (e) идемпотентность и clamp keep>=1 ────────────────────────────────────

def test_second_apply_is_idempotent(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    _fresh_daily(tmp_path)
    plan = dr.plan_cleanup([tmp_path])
    first = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    second = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    assert first["deleted"] == 2
    assert second["deleted"] == 0
    assert second["skipped"] == 2
    assert c.exists() and d.exists()
    assert dr.plan_cleanup([tmp_path]) == []


def test_prune_deploy_backups_keep_clamped_to_one(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    removed = dr.prune_deploy_backups(tmp_path, keep=0)
    assert set(removed) == {str(a), str(b), str(c)}
    assert d.exists()          # нельзя снести все копии


# ── (f) живая БД и её WAL/SHM не трогаются ─────────────────────────────────

def test_live_database_wal_shm_never_touched(tmp_path):
    live = _mk(tmp_path / "local_database.db", days_ago=30)
    wal = _mk(tmp_path / "local_database.db-wal", days_ago=30)
    shm = _mk(tmp_path / "local_database.db-shm", days_ago=30)
    _fresh_daily(tmp_path)
    a, b, c, d = _deploy_family(tmp_path)

    plan = dr.plan_cleanup([tmp_path])
    planned = {i["path"] for i in plan}
    for path in (live, wal, shm):
        assert str(path) not in planned
        assert dr.classify(path) == "other"

    result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    assert result["aborted_reason"] == ""
    for path in (live, wal, shm):
        assert path.exists()
    assert not a.exists() and not b.exists()
    assert c.exists() and d.exists()


# ── (g) ежедневный путь: memory_backup._rotate подрезает deploy-пул ────────

def test_daily_rotate_prunes_deploy_pool_to_two(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    daily = _fresh_daily(tmp_path)
    facts = _mk(tmp_path / "facts_20261004.txt", days_ago=0.5)

    service = MemoryBackupService.__new__(MemoryBackupService)
    service._rotate(tmp_path)

    assert not a.exists() and not b.exists()
    assert c.exists() and d.exists()
    assert daily.exists() and facts.exists()
