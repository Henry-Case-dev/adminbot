"""P0-PROD-DISK-01: ротация деплой-бэкапов (`pre_t*`, `pre_deploy_*`, `predeploy-*`).

Первопричина исчерпания диска на проде (16.11.2026): деплой-тулинг пишет
`pre_deploy_<ver>_<ts>.db` и `predeploy-<ver>*.db`, а `DEPLOY_BACKUP_PATTERNS`
содержал только `pre_t*.db` — 17 копий (44G) не попадали ни в один prune-пул
и не удалялись никогда. Проверяем:
  (a) реальные имена классифицируются как `deploy_backup` и ротируются (keep=2);
  (b) keep жёстко ≥ 1 (нельзя снести все копии) + идемпотентность + kill-switch;
  (c) daily/migration/history/facts и живая `local_database.db`+WAL не тронуты,
      WAL/SHM-компаньоны удалённых копий не остаются сиротами;
  (d) `plan_cleanup` и CLI `disk audit|cleanup` видят пул и применяют ту же
      политику (dry-run честный, `--apply` исполняет lifecycle, fail-closed);
      sidecar-файлы входят в байты своей копии и не считаются мусором `other`;
  (e) прод-подобная фикстура из 17 фактических имён ротируется до 2 новейших;
  (f) существующий ежедневный джоб (`memory_backup._rotate`) исполняет lifecycle.
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


# ── (a) реальные имена деплой-бэкапов ───────────────────────────────────────

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


def test_prune_spares_non_pattern_files(tmp_path):
    oldest = _mk(tmp_path / "pre_t1000_20260101_000000.db", days_ago=30)
    _mk(tmp_path / "pre_t2000_20260201_000000.db", days_ago=20)
    _mk(tmp_path / "pre_t3000_20260301_000000.db", days_ago=10)
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


# ── (b) keep ≥ 1, идемпотентность, kill-switch ──────────────────────────────

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


# ── (c) защищённые данные, sidecar-файлы, план и fail-closed ────────────────

def test_classify_sidecars_inherit_owner_pool(tmp_path):
    """WAL/SHM-компаньон — часть своей копии, не отдельный `other`."""
    deploy = _mk(tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=1)
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    assert dr.classify(_mk(Path(str(deploy) + "-wal"), days_ago=1)) == "deploy_backup"
    assert dr.classify(_mk(Path(str(deploy) + "-shm"), days_ago=1)) == "deploy_backup"
    assert dr.classify(_mk(Path(str(daily) + "-wal"), days_ago=1)) == "db_backup"
    assert dr.classify(_mk(Path(str(live) + "-shm"), days_ago=0)) == "other"
    # sidecar-детект ограничен `*.db-wal/-shm`, произвольный `-wal` — не копия
    assert dr.classify(_mk(tmp_path / "notes-wal", days_ago=1)) == "other"


def test_prune_keeps_sidecars_only_of_two_newest_copies(tmp_path):
    """3 deploy `.db` + sidecars → остаются 2 новейших `.db` и их sidecar;
    sidecar старейшей копии удаляется; daily/migration/history и живая
    `local_database.db` + её WAL/SHM не затрагиваются."""
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    live_wal = _mk(tmp_path / "local_database.db-wal", days_ago=0)
    live_shm = _mk(tmp_path / "local_database.db-shm", days_ago=0)
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=0.5)
    daily_wal = _mk(tmp_path / "local_database_20261116.db-wal", days_ago=0.5)
    migration = _mk(tmp_path / "pre_migration_20261006_121956.db", days_ago=0.5)
    migration_shm = _mk(tmp_path / "pre_migration_20261006_121956.db-shm",
                        days_ago=0.5)
    history = _mk(tmp_path / "imported_history_2026.jsonl", days_ago=0.5)
    stale = _mk_with_sidecars(
        tmp_path / "pre_deploy_258199_20261113T083507Z.db", days_ago=3)
    keep1 = _mk_with_sidecars(
        tmp_path / "pre_deploy_258204_20261115T025835Z.db", days_ago=2)
    keep2 = _mk_with_sidecars(
        tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)

    removed = dr.prune_deploy_backups(tmp_path)  # keep=2 по умолчанию

    assert removed == [str(stale[0])]
    for path in stale:
        assert not path.exists(), f"сирота удалённой копии {path.name}"
    for protected in (keep1 + keep2 + [live, live_wal, live_shm, daily,
                                        daily_wal, migration, migration_shm,
                                        history]):
        assert protected.exists(), f"затронут защищённый {protected.name}"


def test_audit_folds_sidecars_into_their_copy(tmp_path, capsys):
    """`disk audit` показывает sidecar в категории/байтах своей копии, а не
    отдельным мусором в `other` (прод: 2×32K `.db-shm` + 2×0B `.db-wal`)."""
    base = tmp_path / "pre_deploy_258205_20261115T094514Z.db"
    base.write_bytes(b"x" * 10)
    shm = tmp_path / (base.name + "-shm")
    shm.write_bytes(b"y" * 32768)
    wal = tmp_path / (base.name + "-wal")
    wal.write_bytes(b"")

    report = dr.audit([tmp_path])
    assert report["categories"]["deploy_backup"] == {
        "count": 1, "bytes": 10 + 32768}
    assert "other" not in report["categories"], "sidecar не отдельный мусор"
    assert report["sidecar_bytes"] == 32768
    assert report["total_bytes"] == 10 + 32768

    rc = manage.main(["disk", "audit", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "deploy_backup: count=1 bytes=32778" in out
    assert "other: count" not in out
    assert "sidecar_bytes=32768" in out


def test_cleanup_apply_removes_sidecars_with_rotated_copy(tmp_path, capsys):
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    live_wal = _mk(tmp_path / "local_database.db-wal", days_ago=0)
    daily = _mk(tmp_path / "local_database_20261116.db", days_ago=0)
    stale = _mk_with_sidecars(
        tmp_path / "pre_deploy_258199_20261113T083507Z.db", days_ago=3)
    keep1 = _mk_with_sidecars(
        tmp_path / "pre_deploy_258204_20261115T025835Z.db", days_ago=2)
    keep2 = _mk_with_sidecars(
        tmp_path / "pre_deploy_258205_20261115T094514Z.db", days_ago=1)

    plan = dr.plan_cleanup([tmp_path])
    stale_item = {item["path"]: item for item in plan}[str(stale[0])]
    assert stale_item["bytes"] == 3, "dry-run учитывает байты sidecar"

    rc = manage.main(["disk", "cleanup", "--apply", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "bytes_freed=3" in out
    for path in stale:
        assert not path.exists(), f"sidecar пережил копию: {path.name}"
    for protected in keep1 + keep2 + [live, live_wal, daily]:
        assert protected.exists(), f"cleanup удалил защищённый {protected.name}"


def test_apply_cleanup_never_deletes_standalone_sidecar(tmp_path):
    """Примитив удаления не трогает WAL/SHM как самостоятельный план-элемент."""
    live = _mk(tmp_path / "local_database.db", days_ago=0)
    live_wal = _mk(tmp_path / "local_database.db-wal", days_ago=0)
    _mk(tmp_path / "local_database_20261116.db", days_ago=0)   # свежий бэкап
    plan = [{"path": str(live_wal), "category": "other",
             "reason": "hand-made-plan", "bytes": 1}]

    result = dr.apply_cleanup(plan, verify=True, dirs=[tmp_path])
    assert result["aborted_reason"] == ""
    assert result["deleted"] == 0 and result["skipped"] == 1
    assert live.exists() and live_wal.exists()


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


# ── (d) CLI: audit видит пул, cleanup --apply исполняет lifecycle ───────────

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


# ── (e) регрессия прод-инцидента 16.11.2026 ─────────────────────────────────

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


# ── (f) ежедневный джоб исполняет lifecycle ─────────────────────────────────

def test_daily_rotation_hook_prunes_deploy_backups(tmp_path):
    service = MemoryBackupService(None)
    _mk(tmp_path / "pre_deploy_a_20261110T000000Z.db", days_ago=3)
    kept_prev = _mk(tmp_path / "pre_deploy_b_20261111T000000Z.db", days_ago=2)
    kept_new = _mk(tmp_path / "pre_deploy_c_20261112T000000Z.db", days_ago=1)
    service._rotate(tmp_path)
    assert sorted(p.name for p in tmp_path.glob("pre_deploy_*.db")) == sorted(
        [kept_prev.name, kept_new.name])
