"""D1-disk-diag: ротация деплой-бэкапов `pre_t*.db` (keep=2 новейших).

Деплой-тулинг кладёт по копии ~1.3G за релизное окно; паттерн `pre_t*.db` не
входил ни в один prune-пул — копии накапливались без ротации (3.9G, диск 92%).
Проверяем:
  (a) 3+ фиктивных `pre_t*.db` (tmp_path) → остаются 2 новейших, старые
      удалены;
  (b) непаттерн-файлы (daily/pre_migration/history/facts) не тронуты.
Реальные файлы прода не используются.
"""
import os
import time
from pathlib import Path

import services.disk_retention as dr


def _mk(path: Path, days_ago: float) -> Path:
    path.write_bytes(b"x")
    ts = time.time() - days_ago * 86400.0
    os.utime(path, (ts, ts))
    return path


def test_prune_deploy_backups_keeps_two_newest(tmp_path):
    a = _mk(tmp_path / "pre_t5216_20261006_232333.db", days_ago=4)
    b = _mk(tmp_path / "pre_t5273_20261007_045424.db", days_ago=3)
    c = _mk(tmp_path / "pre_t5274_20261007_055326.db", days_ago=2)
    d = _mk(tmp_path / "pre_t5999_20261008_000000.db", days_ago=1)
    removed = dr.prune_deploy_backups(tmp_path)  # keep=2 по умолчанию
    assert set(removed) == {str(a), str(b)}
    assert c.exists() and d.exists()
    assert sorted(tmp_path.glob("pre_t*.db")) == [c, d]


def test_prune_deploy_backups_spares_non_pattern_files(tmp_path):
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
