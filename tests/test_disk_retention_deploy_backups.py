"""P0-PROD-DISK-01: ротация деплой-бэкапов (keep=2 новейших) + WAL/SHM.

Первопричина исчерпания диска на проде (16.11.2026): деплой-тулинг пишет
`pre_deploy_<ver>_<ts>.db` и `predeploy-<ver>*.db`, а `DEPLOY_BACKUP_PATTERNS`
содержал только `pre_t*.db` — 17 копий (44G) не попадали ни в один prune-пул
и не удалялись никогда; копии лежали вместе с `*.db-wal`/`*.db-shm`, которые
не матчились ни одним паттерном и оставались сиротами.

Проверяем:
  (a) все три семейства фактических имён классифицируются как `deploy_backup`
      и ротируются до 2 новейших;
  (b) daily/migration/rebuild/history/facts не затронуты, keep жёстко ≥ 1,
      ротация идемпотентна, kill-switch уважается;
  (c) WAL/SHM удаляются ТОЛЬКО у удалённой копии; у сохранённых копий и у
      живой `local_database.db` (+ `-wal`/`-shm`) ничего не пропадает;
  (d) `plan_cleanup` и CLI `disk audit|cleanup` видят пул и применяют ту же
      политику (dry-run честный, `--apply` исполняет lifecycle, fail-closed
      приоритетнее ротации, частичный план не отменяет keep=2);
  (e) прод-подобная фикстура из 17 фактических имён ротируется до 2 новейших;
  (f) ежедневный джоб (`memory_backup._rotate`) исполняет тот же lifecycle.
Реальные файлы прода не используются.
"""
import os
import time
from pathlib import Path

import pytest

import manage
import services.disk_retention as dr
from config.settings import Settings
from services.memory_backup import MemoryBackupService


def _mk(path: Path, days_ago: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    ts = time.time() - days_ago * 86400.0
    os.utime(path, (ts, ts))
    return path


def _sidecars(path: Path) -> list[Path]:
    """WAL/SHM-компаньоны копии БД (реальные имена прода: `*.db-wal/-shm`)."""
    return [Path(str(path) + suffix) for suffix in ("-wal", "-shm")]


def _mk_with_sidecars(path: Path, days_ago: float) -> list[Path]:
    base = _mk(path, days_ago)
    out = [base]
    for sidecar in _sidecars(path):
        out.append(_mk(sidecar, days_ago))
    return out


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


# ── (a) паттерны, классификация, ротация ────────────────────────────────────

@pytest.mark.parametrize("name", [
    "pre_deploy_258205_20261115T094514Z.db",      # фактический деплой 2.58.205
    "predeploy-258175.db",                        # ранняя схема
    "predeploy-258198-final-20261112T212408Z.db",  # схема с суффиксом
    "pre_t5216_20261006_232333.db",               # старый pre_t (D1-disk-diag)
])
def test_classify_recognises_real_deploy_backup_names(name, tmp_path):
    path = _mk(tmp_path / name, days_ago=1)
    assert dr._matches_any(name, dr.DEPLOY_BACKUP_PATTERNS)
    assert dr.classify(path) == "deploy_backup"


def test_prune_deploy_backups_keeps_two_newest_across_families(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    removed = dr.prune_deploy_backups(tmp_path)  # keep=2 по умолчанию
    assert set(removed) == {str(a), str(b)}
    assert c.exists() and d.exists()
    assert not a.exists() and not b.exists()


def test_prune_rotates_all_three_schemes_keeping_two_newest(tmp_path):
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=1)
    old_t = _mk(tmp_path / "pre_t5216_20261006_232333.db", days_ago=4)
    old_deploy = _mk(tmp_path / "pre_deploy_258199_20261113T083507Z.db",
                     days_ago=3)
    old_predeploy = _mk(tmp_path / "predeploy-258187-20261111T082439Z.db",
                        days_ago=2)
    new_deploy = _mk(tmp_path / "pre_deploy_258205_20261115T094514Z.db",
                     days_ago=1)
    new_predeploy = _mk(tmp_path / "predeploy-258198-final-20261112T212408Z.db",
                        days_ago=0)
    removed = dr.prune_deploy_backups(tmp_path)  # keep=2 по умолчанию

    assert set(removed) == {str(old_t), str(old_deploy), str(old_predeploy)}
    assert new_deploy.exists() and new_predeploy.exists()
    assert daily.exists(), "daily-бэкап не входит в deploy-пул"


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


# ── (c) keep ≥ 1, идемпотентность, kill-switch ──────────────────────────────

@pytest.mark.parametrize("keep", [1, 0, -5])
def test_keep_is_clamped_to_at_least_one(keep, tmp_path):
    old = _mk(tmp_path / "pre_deploy_a_20261110T000000Z.db", days_ago=3)
    mid = _mk(tmp_path / "pre_deploy_b_20261111T000000Z.db", days_ago=2)
    new = _mk(tmp_path / "pre_deploy_c_20261112T000000Z.db", days_ago=1)
    removed = dr.prune_deploy_backups(tmp_path, keep=keep)  # keep<1 → 1
    assert set(removed) == {str(old), str(mid)}
    assert new.exists(), "все deploy-копии не могут быть удалены"


def test_prune_is_idempotent(tmp_path):
    _mk(tmp_path / "pre_deploy_a_20261110T000000Z.db", days_ago=3)
    _mk(tmp_path / "pre_deploy_b_20261111T000000Z.db", days_ago=2)
    k1 = _mk(tmp_path / "pre_deploy_c_20261112T000000Z.db", days_ago=1)
    k2 = _mk(tmp_path / "predeploy-258198-final-20261112T212408Z.db", days_ago=0)
    assert len(dr.prune_deploy_backups(tmp_path)) == 2
    assert dr.prune_deploy_backups(tmp_path) == []
    assert sorted(p.name for p in tmp_path.glob("*.db")) == sorted(
        [k1.name, k2.name])


def test_kill_switch_spares_deploy_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "DISK_RETENTION_ENABLED", False)
    a = _mk(tmp_path / "pre_deploy_a_20261110T000000Z.db", days_ago=3)
    _mk(tmp_path / "pre_deploy_b_20261111T000000Z.db", days_ago=2)
    _mk(tmp_path / "pre_deploy_c_20261112T000000Z.db", days_ago=1)
    assert dr.prune_deploy_backups(tmp_path) == []
    assert a.exists()


# ── (d) sidecar-файлы удалённых копий ───────────────────────────────────────

def test_prune_removes_wal_shm_of_deleted_backup_only(tmp_path):
    stale = _mk_with_sidecars(
        tmp_path / "pre_deploy_258199_20261113T083507Z.db", days_ago=3)
    _mk(tmp_path / "pre_deploy_258204_20261115T025835Z.db", days_ago=2)
    kept = _mk_with_sidecars(
        tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)
    dr.prune_deploy_backups(tmp_path)
    for path in stale:
        assert not path.exists(), f"сирота {path.name}"
    for path in kept:
        assert path.exists(), f"потерян {path.name}"


def test_cli_apply_drops_sidecars_of_removed_copy_only(tmp_path, capsys):
    """Полный путь CLI `--apply`: sidecar уходят ровно вместе со своей копией."""
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    live_wal = _mk(tmp_path / "local_database.db-wal", days_ago=0)
    live_shm = _mk(tmp_path / "local_database.db-shm", days_ago=0)
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=0)
    stale = _mk_with_sidecars(
        tmp_path / "pre_deploy_258199_20261113T083507Z.db", days_ago=3)
    keep1 = _mk_with_sidecars(
        tmp_path / "pre_deploy_258204_20261115T025835Z.db", days_ago=2)
    keep2 = _mk_with_sidecars(
        tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)

    rc = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
    assert rc == 0, capsys.readouterr().out

    for path in stale:
        assert not path.exists(), f"сирота {path.name}"
    for path in [live, live_wal, live_shm, daily] + keep1 + keep2:
        assert path.exists(), f"удалён защищённый {path.name}"


# ── (e) план, verify и CLI ──────────────────────────────────────────────────

def test_plan_cleanup_marks_only_stale_deploy_backups(tmp_path):
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=1)
    old = _mk(tmp_path / "pre_deploy_258199_20261113T083507Z.db", days_ago=3)
    keep1 = _mk(tmp_path / "pre_deploy_258204_20261115T025835Z.db", days_ago=2)
    keep2 = _mk(tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    live_wal = _mk(tmp_path / "local_database.db-wal", days_ago=0)

    plan = dr.plan_cleanup([tmp_path])
    by_path = {item["path"]: item for item in plan}
    assert by_path[str(old)]["category"] == "deploy_backup"
    assert by_path[str(old)]["reason"] == "deploy_keep_newest_2"
    assert str(keep1) not in by_path and str(keep2) not in by_path
    assert str(daily) not in by_path, "daily держится отдельным пулом (keep=1)"
    assert str(live) not in by_path and str(live_wal) not in by_path

    report = dr.audit([tmp_path])
    assert report["categories"]["deploy_backup"]["count"] == 3


def test_deploy_only_plan_aborts_without_fresh_daily_backup(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    plan = dr.plan_cleanup([tmp_path])
    assert {i["category"] for i in plan} == {"deploy_backup"}
    result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    assert result["aborted_reason"] == "no_valid_backup"
    assert result["deleted"] == 0
    # F2: abort-ответ тоже несёт поле (и ничего не подрезал).
    assert result["deploy_pruned"] == 0
    for p in (a, b, c, d):
        assert p.exists()


def test_empty_plan_response_contains_deploy_pruned():
    """F2: пустой план (ранний return) не теряет поле API-ответа."""
    result = dr.apply_cleanup([])
    assert result["deploy_pruned"] == 0
    assert result["deleted"] == 0 and result["aborted_reason"] == ""


def test_apply_aborts_before_deploy_rotation_without_fresh_backup(tmp_path):
    """Fail-closed приоритетнее deploy-ротации: без свежего валидного
    `*.db`-бэкапа `--apply` не удаляет ничего, включая deploy-копии."""
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    old = _mk(tmp_path / "pre_deploy_a_20261110T000000Z.db", days_ago=3)
    mid = _mk(tmp_path / "pre_deploy_b_20261111T000000Z.db", days_ago=2)
    _mk(tmp_path / "pre_deploy_c_20261112T000000Z.db", days_ago=1)
    plan = dr.plan_cleanup([tmp_path])
    assert {item["path"] for item in plan} == {str(old)}

    result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    assert result["aborted_reason"] == "no_valid_backup"
    assert result["deleted"] == 0
    assert old.exists() and mid.exists() and live.exists()


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


def test_apply_cleanup_enforces_deploy_rotation_on_partial_plan(tmp_path):
    """`apply_cleanup` сам исполняет deploy-политику (не зависит от полноты
    входного плана): частичный план не отменяет keep=2."""
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=1)
    stale = _mk(tmp_path / "pre_deploy_a_20261110T000000Z.db", days_ago=3)
    mid = _mk(tmp_path / "pre_deploy_b_20261111T000000Z.db", days_ago=2)
    new = _mk(tmp_path / "pre_deploy_c_20261112T000000Z.db", days_ago=1)
    plan = [{"path": str(tmp_path / "gone.db"), "category": "deploy_backup",
             "reason": "stale-plan", "bytes": 1}]

    result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    assert result["aborted_reason"] == ""
    assert result["deploy_pruned"] == 1
    assert not stale.exists()
    assert mid.exists() and new.exists() and daily.exists()


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


def test_cli_audit_reports_deploy_backup_category(tmp_path, capsys):
    _mk(tmp_path / "local_database_20261116.db", days_ago=1)
    _mk(tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)
    _mk(tmp_path / "predeploy-258175.db", days_ago=1)
    rc = manage.main(["disk", "audit", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "deploy_backup: count=2" in out


def test_cli_cleanup_apply_rotates_deploy_and_spares_live_db(tmp_path, capsys):
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    live_wal = _mk(tmp_path / "local_database.db-wal", days_ago=0)
    live_shm = _mk(tmp_path / "local_database.db-shm", days_ago=0)
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=0)
    old = _mk_with_sidecars(
        tmp_path / "pre_deploy_258199_20261113T083507Z.db", days_ago=3)
    keep1 = _mk(tmp_path / "pre_deploy_258204_20261115T025835Z.db", days_ago=2)
    keep2 = _mk(tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)

    rc = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "deploy_backup" in out
    for path in (live, live_wal, live_shm, daily, keep1, keep2):
        assert path.exists(), f"cleanup удалил защищённый {path.name}"
    for path in old:
        assert not path.exists()

    # Идемпотентность CLI: повторный прогон ничего не удаляет.
    rc2 = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
    assert rc2 == 0
    assert "deleted=0" in capsys.readouterr().out


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


# ── (f) регрессия прод-инцидента 16.11.2026 ─────────────────────────────────

PROD_BACKUPS_2026_11_16 = [
    ("pre_deploy_258205_20261115T094514Z.db", 2),
    ("pre_deploy_258204_20261115T025835Z.db", 3),
    ("pre_deploy_258203_20261114T185501Z.db", 4),
    ("pre_deploy_258202_20261114T151257Z.db", 5),
    ("pre_deploy_258201_20261114T133538Z.db", 6),
    ("pre_deploy_258200_20261114T051849Z.db", 7),
    ("pre_deploy_258199_20261113T083507Z.db", 8),
    ("predeploy-258198-final-20261112T212408Z.db", 9),
    ("predeploy-258197-20261112T094016Z.db", 10),
    ("predeploy-258196-20261112T085424Z.db", 11),
    ("predeploy-258190-20261111T145101Z.db", 12),
    ("predeploy-258187-20261111T082439Z.db", 13),
    ("predeploy-258183.db", 14),
    ("predeploy-258178.db", 15),
    ("predeploy-258177.db", 16),
    ("predeploy-258176.db", 17),
    ("predeploy-258175.db", 18),
]


def test_prod_shaped_fixture_rotates_17_copies_to_two(tmp_path, capsys):
    """17 фактических имён из прод-`backups/` (44G) → 2 новейших; daily,
    facts, живая БД и её WAL/SHM не тронуты."""
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    live_wal = _mk(tmp_path / "local_database.db-wal", days_ago=0)
    live_shm = _mk(tmp_path / "local_database.db-shm", days_ago=0)
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=0)
    facts = _mk(tmp_path / "facts_20261116.txt", days_ago=0)
    for name, hours_ago in PROD_BACKUPS_2026_11_16:
        _mk(tmp_path / name, days_ago=hours_ago / 24.0)

    assert dr.audit([tmp_path])["categories"]["deploy_backup"]["count"] == 17

    rc = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "deleted=15" in out

    remaining = sorted(p.name for p in tmp_path.glob("*.db")
                       if dr.classify(p) == "deploy_backup")
    assert remaining == sorted([PROD_BACKUPS_2026_11_16[0][0],
                                PROD_BACKUPS_2026_11_16[1][0]])
    for protected in (live, live_wal, live_shm, daily, facts):
        assert protected.exists(), f"удалён защищённый {protected.name}"

    rc_audit = manage.main(["disk", "audit", "--dir", str(tmp_path)])
    assert rc_audit == 0
    assert "deploy_backup: count=2" in capsys.readouterr().out


# ── (g) ежедневный джоб исполняет lifecycle ─────────────────────────────────

def test_daily_rotate_prunes_deploy_pool_to_two(tmp_path):
    a, b, c, d = _deploy_family(tmp_path)
    daily = _fresh_daily(tmp_path)
    facts = _mk(tmp_path / "facts_20261004.txt", days_ago=0.5)

    service = MemoryBackupService.__new__(MemoryBackupService)
    service._rotate(tmp_path)

    assert not a.exists() and not b.exists()
    assert c.exists() and d.exists()
    assert daily.exists() and facts.exists()
