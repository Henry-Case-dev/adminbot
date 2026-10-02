"""T-4506 (post-asap4-corrective-pass): сервер-sайд retention/cleanup `tools/disk_retention.py`.

Покрытие (контракт T-4506 / R5-C-001, R5-C-003):
  * policy-математика: возраст (строгая граница), количество (keep_newest
    с ранжирующим пулом по всем местам якорей), текущий месяц, размерный кап;
  * HARDCODE denylist неприкосновенен даже в whitelist-каталоге:
    рабочая БД+WAL, суточный/именованные копии, pre_migration_20261002_101544,
    pre_v21-маркер, .env*, история, cookies, media/uploads, память/GraphRAG;
  * dry-run по умолчанию ничего не удаляет; --apply удаляет ровно план;
  * повторный прогон — no-op (идемпотентность);
  * kill-switch env-only; ничего вне whitelist-корней (включая симлинк-эскейп
    и подделанный план) не трогается;
  * migrate_history — только с owner-confirm;
  * apt-кэш — только безопасная каноническая команда без shell.
Только stdlib + tmp_path; реальные прод-пути и рабочая БД не трогаются.
"""
import json
import os
import time
from pathlib import Path

import pytest

from tools import disk_retention as dr


def _set_mtime(path: Path, days_ago: float) -> None:
    ts = time.time() - days_ago * 86400.0
    os.utime(path, (ts, ts))


def _mk(path: Path, content: bytes = b"x", days_ago: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if days_ago:
        _set_mtime(path, days_ago)
    return path


def _paths(plan: dict) -> set[str]:
    return {c["path"] for c in plan["plan"]}


# ── HARDCODE denylist: неприкосновенно даже в whitelist-каталоге ────────────


class TestDenylist:
    def test_working_db_wal_shm_never_selected(self, tmp_path):
        root = tmp_path / "wl"
        for name in ("local_database.db", "local_database.db-wal",
                     "local_database.db-shm"):
            _mk(root / name, days_ago=100)
        rule = dr.RetentionRule(key="wl", roots=(str(root),), patterns=("*",))
        plan = dr.build_plan([rule])
        assert plan["plan"] == []
        assert all(i["reason"] == "protected_db_or_wal"
                   for i in plan["protected"])

    def test_named_db_copies_and_anchors_denied(self, tmp_path):
        root = tmp_path / "wl"
        names = (
            "local_database_20261002.db",                      # суточный
            "local_database_20261001-080155_pre_v21.db",       # якорь pre_v21
            "pre_migration_20261002_101544.db",                # якорь pass'а
            "imported_history_2026.jsonl",                     # сырая история
            ".env.bak.round1025-f0",                           # секреты
            "cookies.txt",                                     # cookies
        )
        for name in names:
            _mk(root / name, days_ago=100)
        rule = dr.RetentionRule(key="wl", roots=(str(root),), patterns=("*",))
        plan = dr.build_plan([rule])
        assert _paths(plan) == set()
        reasons = {os.path.basename(i["path"]): i["reason"]
                   for i in plan["protected"]}
        assert reasons["local_database_20261001-080155_pre_v21.db"].startswith(
            "denied_")
        assert reasons["pre_migration_20261002_101544.db"].startswith("denied_")
        assert reasons[".env.bak.round1025-f0"] == "denied_glob:.env*"

    def test_adhoc_bak_is_not_denied_but_gated_by_its_own_rule(self):
        # ad-hoc bak НЕ в denylist — он удаляется только правилом
        # app_adhoc_db_baks (возраст > 14д); по умолчанию (без правила) нет.
        assert dr.deny_reason(
            "/var/www/admin_bot/"
            "local_database.db.bak.2026-09-15-0744") == ""

    def test_denied_dir_segments_even_inside_whitelist(self, tmp_path):
        root = tmp_path / "wl"
        _mk(root / "media" / "leha_greeting.ogg", days_ago=100)
        _mk(root / "uploads" / "doc.pdf", days_ago=100)
        _mk(root / "graphrag" / "vectors.bin", days_ago=100)
        _mk(root / "memory" / "facts.db", days_ago=100)
        _mk(root / "venv" / "lib" / "py.py", days_ago=100)
        _mk(root / "chrome-profile" / "Cookies", days_ago=100)
        rule = dr.RetentionRule(key="wl", roots=(str(root),), patterns=("*",))
        plan = dr.build_plan([rule])
        assert plan["plan"] == []
        assert len(plan["protected"]) == 6

    def test_deny_reason_unit_cases(self):
        assert dr.deny_reason("/x/local_database.db") != ""
        assert dr.deny_reason("/x/local_database.db-wal") != ""
        assert dr.deny_reason("/x/pre_migration_20261002_101544.db") != ""
        assert dr.deny_reason("/x/anchor_pre_v21.db") != ""
        assert dr.deny_reason("/x/.env") != ""
        assert dr.deny_reason("/x/anything_pre_v22.db") != ""
        assert dr.deny_reason("/home/nik/ok_file.bin") == ""

    def test_apply_never_deletes_denied_even_in_forged_plan(self, tmp_path):
        root = tmp_path / "wl"
        db = _mk(root / "local_database.db", b"live", days_ago=100)
        anchor = _mk(root / "pre_migration_20261002_101544.db", b"anchor",
                     days_ago=100)
        rule = dr.RetentionRule(key="wl", roots=(str(root),), patterns=("*",))
        forged = [{"rule": "wl", "path": str(db), "bytes": 4},
                  {"rule": "wl", "path": str(anchor), "bytes": 6}]
        log: list[str] = []
        report = dr.apply_plan(forged, rules=[rule], log=log.append)
        assert report["deleted"] == 0
        assert report["blocked"] == 2
        assert db.read_bytes() == b"live"
        assert anchor.read_bytes() == b"anchor"
        assert any("BLOCKED" in line for line in log)


# ── Policy-математика: возраст / количество / месяц / размер ────────────────


class TestPolicyAge:
    def test_age_boundary_is_strict(self, tmp_path):
        root = tmp_path / "age"
        # запас ±60с от порога: mtime задаётся раньше чтения часов, дрейф
        # чтения времени не должен ломать границу
        fresh = _mk(root / "fresh.bin", days_ago=3.0 - 60 / 86400.0)
        old = _mk(root / "old.bin", days_ago=3.0 + 60 / 86400.0)
        rule = dr.RetentionRule(key="age", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        assert _paths(plan) == {str(old)}
        assert fresh.exists() and old.exists()

    def test_fresh_files_untouched(self, tmp_path):
        root = tmp_path / "age"
        _mk(root / "a.bin", days_ago=0.5)
        _mk(root / "b.bin", days_ago=2.9)
        rule = dr.RetentionRule(key="age", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        assert dr.build_plan([rule])["plan"] == []


class TestPolicyKeepNewest:
    def test_keep_newest_two(self, tmp_path):
        root = tmp_path / "keep"
        a = _mk(root / "a.db", days_ago=40)
        b = _mk(root / "b.db", days_ago=30)
        c = _mk(root / "c.db", days_ago=1)
        rule = dr.RetentionRule(key="keep", roots=(str(root),),
                                patterns=("*.db",), recursive=False,
                                keep_newest=2)
        plan = dr.build_plan([rule])
        assert _paths(plan) == {str(a)}
        assert b.exists() and c.exists()

    def test_denied_file_occupies_keep_slot(self, tmp_path):
        root = tmp_path / "keep"
        old = _mk(root / "pre_mca_v19_20260929_052904.db", days_ago=40)
        mid = _mk(root / "generic_mid.db", days_ago=30)
        _mk(root / "local_database_20261001-080155_pre_v21.db", days_ago=5)
        rule = dr.RetentionRule(key="keep", roots=(str(root),),
                                patterns=("*.db",), recursive=False,
                                keep_newest=2)
        plan = dr.build_plan([rule])
        # denied pre_v21 — новейший и занимает слот; mid остаётся в пределах
        # keep_newest=2; old — кандидат (denylist сам защищён от удаления)
        assert _paths(plan) == {str(old)}
        assert mid.exists()

    def test_rank_roots_count_toward_newest_but_never_deleted(self, tmp_path):
        del_root = tmp_path / "home_backups"
        rank_root = tmp_path / "app"
        a = _mk(del_root / "pre_mca_v19.db", days_ago=40)
        b = _mk(del_root / "generic.db", days_ago=10)
        live = _mk(rank_root / "local_database.db", days_ago=0.1)
        rule = dr.RetentionRule(
            key="anchors", roots=(str(del_root),), patterns=("*.db",),
            recursive=False, keep_newest=2,
            rank_roots=(str(rank_root),), rank_patterns=("*.db",))
        plan = dr.build_plan([rule])
        # пул = {a(40д), b(10д), live(0.1д)} → новейшие 2: live, b → кандидат a;
        # live в rank-корне не удаляется (и к тому же denylist)
        assert _paths(plan) == {str(a)}
        assert live.exists() and b.exists()


class TestPolicyCurrentMonth:
    def test_current_month_kept_previous_month_selected(self, tmp_path):
        root = tmp_path / "month"
        prev = _mk(root / "prev_anchor.db", days_ago=40)   # всегда прошлый месяц
        cur = _mk(root / "cur_anchor.db", days_ago=1)      # текущий месяц
        rank = tmp_path / "rank"
        _mk(rank / "local_database.db", days_ago=0.01)
        rule = dr.RetentionRule(
            key="month", roots=(str(root),), patterns=("*.db",),
            recursive=False, keep_newest=2, keep_current_month=True,
            rank_roots=(str(rank),), rank_patterns=("*.db",))
        plan = dr.build_plan([rule])
        # пул = {prev(40д), cur(1д), live(0.01д)} → новейшие 2: live, cur;
        # prev — прошлый месяц → кандидат; cur остаётся (текущий месяц)
        assert _paths(plan) == {str(prev)}
        assert cur.exists()


class TestPolicyMaxTotalBytes:
    def test_cap_keeps_newest_bytes_deletes_older(self, tmp_path):
        root = tmp_path / "cap"
        files = [_mk(root / f"f{i}.bin", b"x" * 100, days_ago=4 - i)
                 for i in range(4)]
        rule = dr.RetentionRule(key="cap", roots=(str(root),),
                                patterns=("*.bin",), recursive=False,
                                max_total_bytes=250)
        plan = dr.build_plan([rule])
        # удерживаем новейшие до 250B: f3(1д)+f2(2д)+f1(3д)=300>250 → f3+f2=200,
        # f1 → 200+100=300>250 → f1 в кандидаты; f0 (4д) тоже сверх капа
        assert _paths(plan) == {str(files[0]), str(files[1])}

    def test_cap_not_exceeded_no_candidates(self, tmp_path):
        root = tmp_path / "cap2"
        _mk(root / "a.bin", b"x" * 10, days_ago=30)
        rule = dr.RetentionRule(key="cap2", roots=(str(root),),
                                patterns=("*.bin",), recursive=False,
                                max_total_bytes=1000)
        assert dr.build_plan([rule])["plan"] == []


# ── Audit-replay: disposition disk-audit §9 для якорей ──────────────────────


class TestAuditReplayAnchors:
    def test_pre_mca_v19_selected_protected_anchors_kept(self, tmp_path):
        home = tmp_path / "backups"
        app = tmp_path / "admin_bot"
        v19 = _mk(home / "pre_mca_v19_20260929_052904.db", days_ago=40)
        v21 = _mk(app / "local_database_20261001-080155_pre_v21.db", days_ago=1)
        premig = _mk(app / "pre_migration_20261002_101544.db", days_ago=0.5)
        live = _mk(app / "local_database.db", days_ago=0.02)
        rule = dr.RetentionRule(
            key="db_anchor_backups", roots=(str(home),), patterns=("*.db",),
            recursive=False, keep_newest=2, keep_current_month=True,
            rank_roots=(str(app),), rank_patterns=("*.db",))
        plan = dr.build_plan([rule])
        assert _paths(plan) == {str(v19)}
        reasons = {os.path.basename(i["path"]) for i in plan["protected"]}
        assert "pre_migration_20261002_101544.db" in reasons
        assert "local_database_20261001-080155_pre_v21.db" in reasons
        assert "local_database.db" in reasons
        for kept in (v21, premig, live):
            assert kept.exists()


# ── Dry-run / apply / идемпотентность ───────────────────────────────────────


class TestDryRunAndApply:
    def test_dry_run_default_deletes_nothing(self, tmp_path):
        root = tmp_path / "dry"
        doomed = _mk(root / "old.bin", days_ago=10)
        keeper = _mk(root / "new.bin", days_ago=1)
        rule = dr.RetentionRule(key="dry", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        assert len(plan["plan"]) == 1
        assert doomed.exists() and keeper.exists()  # build_plan ничего не делает

    def test_apply_deletes_exactly_selected(self, tmp_path):
        root = tmp_path / "app"
        doomed = _mk(root / "old.bin", b"old", days_ago=10)
        keeper = _mk(root / "new.bin", b"new", days_ago=1)
        rule = dr.RetentionRule(key="app", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        log: list[str] = []
        report = dr.apply_plan(plan["plan"], rules=[rule], log=log.append)
        assert report["deleted"] == 1
        assert report["bytes_freed"] == 3
        assert not doomed.exists()
        assert keeper.read_bytes() == b"new"
        assert any(line.startswith("DELETE") for line in log)

    def test_repeated_run_is_noop(self, tmp_path):
        root = tmp_path / "idem"
        _mk(root / "old.bin", days_ago=10)
        rule = dr.RetentionRule(key="idem", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan1 = dr.build_plan([rule])
        report = dr.apply_plan(plan1["plan"], rules=[rule])
        assert report["deleted"] == 1
        plan2 = dr.build_plan([rule])
        assert plan2["plan"] == []
        report2 = dr.apply_plan(plan2["plan"], rules=[rule])
        assert report2["deleted"] == 0 and report2["skipped"] == 0


# ── Whitelist-контейнмент: ничего вне корней ────────────────────────────────


class TestWhitelistContainment:
    def test_sibling_dir_never_scanned_or_deleted(self, tmp_path):
        inside = tmp_path / "in"
        outside = tmp_path / "out"
        _mk(inside / "i.bin", days_ago=10)
        out_file = _mk(outside / "o.bin", days_ago=10)
        rule = dr.RetentionRule(key="in", roots=(str(inside),),
                                patterns=("*",), min_age_days=3.0)
        plan = dr.build_plan([rule])
        assert _paths(plan) == {str(inside / "i.bin")}
        dr.apply_plan(plan["plan"], rules=[rule])
        assert out_file.exists()

    def test_parent_root_not_deleted_only_files(self, tmp_path):
        root = tmp_path / "deep"
        _mk(root / "sub" / "old.bin", days_ago=10)
        rule = dr.RetentionRule(key="deep", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        report = dr.apply_plan(plan["plan"], rules=[rule])
        assert report["deleted"] == 1
        assert (root / "sub").is_dir()  # каталоги не удаляются, только файлы

    def test_forged_plan_outside_roots_blocked(self, tmp_path):
        inside = tmp_path / "in"
        outside = tmp_path / "out"
        _mk(inside / "i.bin", days_ago=10)
        out_file = _mk(outside / "o.bin", b"out", days_ago=10)
        rule = dr.RetentionRule(key="in", roots=(str(inside),), patterns=("*",))
        forged = [{"rule": "in", "path": str(out_file), "bytes": 3}]
        log: list[str] = []
        report = dr.apply_plan(forged, rules=[rule], log=log.append)
        assert report["deleted"] == 0 and report["blocked"] == 1
        assert out_file.read_bytes() == b"out"
        assert any("outside-whitelist" in line for line in log)

    def test_forged_plan_unknown_rule_blocked(self, tmp_path):
        root = tmp_path / "in"
        f = _mk(root / "i.bin", b"i", days_ago=10)
        rule = dr.RetentionRule(key="in", roots=(str(root),), patterns=("*",))
        forged = [{"rule": "nope", "path": str(f), "bytes": 1}]
        report = dr.apply_plan(forged, rules=[rule])
        assert report["blocked"] == 1 and report["deleted"] == 0
        assert f.exists()

    def test_forged_plan_pattern_mismatch_blocked(self, tmp_path):
        root = tmp_path / "in"
        f = _mk(root / "important.db", b"imp", days_ago=10)
        rule = dr.RetentionRule(key="in", roots=(str(root),),
                                patterns=("*.tmp",))
        forged = [{"rule": "in", "path": str(f), "bytes": 3}]
        report = dr.apply_plan(forged, rules=[rule])
        assert report["blocked"] == 1
        assert f.read_bytes() == b"imp"

    def test_symlink_escape_blocked(self, tmp_path):
        root = tmp_path / "in"
        outside = tmp_path / "out"
        target = _mk(outside / "victim.bin", b"victim", days_ago=10)
        link = root / "link.bin"
        # M-4504-1: раньше root не создавался — os.symlink падал
        # FileNotFoundError и тест skip'ался на ЛЮБОЙ ОС с misleading-причиной.
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unavailable on this host "
                        "(Windows: нужны привилегия/Developer Mode)")
        rule = dr.RetentionRule(key="in", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        # L-4504-5: скан не следует по файловым симлинкам — ссылка не попадает
        # в план (нет PLAN-строк, которые apply потом блокирует как шум).
        assert _paths(plan) == set()
        report = dr.apply_plan(plan["plan"], rules=[rule])
        assert report["deleted"] == 0
        # Defense-in-depth apply не ослаблен: подделанный план с симлинком
        # (realpath указывает вне whitelist) блокируется, жертва цела.
        forged = [{"rule": "in", "path": str(link), "bytes": 6}]
        log: list[str] = []
        forged_report = dr.apply_plan(forged, rules=[rule], log=log.append)
        assert forged_report["deleted"] == 0
        assert forged_report["blocked"] == 1
        assert any("BLOCKED" in line for line in log)
        assert target.read_bytes() == b"victim"

    def test_directories_are_never_unlinked(self, tmp_path):
        root = tmp_path / "in"
        _mk(root / "sub" / "old.bin", days_ago=10)
        rule = dr.RetentionRule(key="in", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        assert all(Path(c["path"]).is_file() for c in plan["plan"])


# ── migrate_history: только owner-confirm ───────────────────────────────────


class TestOwnerConfirmGate:
    def test_rule_excluded_without_flag(self, tmp_path):
        mh = tmp_path / "migrate_history"
        _mk(mh / "2026.json", b"{}", days_ago=30)
        rule = dr.RetentionRule(key="migrate_history", roots=(str(mh),),
                                patterns=("*",), min_age_days=7.0,
                                requires_owner_confirm=True)
        plan = dr.build_plan([rule])
        assert plan["plan"] == []
        assert any(i["reason"] == "owner_confirm_required:rule"
                   for i in plan["protected"])

    def test_segment_guard_independent_of_rule(self, tmp_path):
        # даже если правило без флага — сегмент migrate_history запрещён
        assert dr.deny_reason("/x/migrate_history/2026.json") == \
            "owner_confirm_required:migrate_history"
        assert dr.deny_reason("/x/migrate_history/2026.json",
                              owner_confirm=True) == ""

    def test_with_owner_confirm_old_selected_fresh_kept(self, tmp_path):
        mh = tmp_path / "migrate_history"
        old = _mk(mh / "2026.json", b"{}", days_ago=30)
        fresh = _mk(mh / "fresh.json", b"{}", days_ago=1)
        rule = dr.RetentionRule(key="migrate_history", roots=(str(mh),),
                                patterns=("*",), min_age_days=7.0,
                                requires_owner_confirm=True)
        plan = dr.build_plan([rule], owner_confirm=True)
        assert _paths(plan) == {str(old)}
        assert fresh.exists()


# ── Kill-switch (env-only, default ON) ──────────────────────────────────────


class TestKillSwitch:
    def test_env_default_on(self):
        assert dr.retention_enabled(environ={}) is True
        assert dr.retention_enabled(environ={dr.ENABLED_ENV: "0"}) is False
        assert dr.retention_enabled(environ={dr.ENABLED_ENV: "false"}) is False
        assert dr.retention_enabled(environ={dr.ENABLED_ENV: "1"}) is True

    def test_disabled_build_plan_is_empty(self, tmp_path):
        root = tmp_path / "ks"
        _mk(root / "old.bin", days_ago=100)
        rule = dr.RetentionRule(key="ks", roots=(str(root),), patterns=("*",))
        plan = dr.build_plan([rule], enabled=False)
        assert plan["enabled"] is False and plan["plan"] == []

    def test_main_disabled_noop(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(dr.ENABLED_ENV, "0")
        assert dr.main([]) == 0
        out = capsys.readouterr().out
        assert "no-op" in out


# ── Ротированные логи: активный лог паттерну не соответствует ───────────────


class TestRotatedLogs:
    def test_only_rotated_selected_active_log_kept(self, tmp_path):
        root = tmp_path / "logs"
        active = _mk(root / "proxy.log", days_ago=0.1)
        r1 = _mk(root / "proxy.log.1", days_ago=30)
        r5 = _mk(root / "proxy.log.5", days_ago=30)
        rule = dr.RetentionRule(
            key="rotated_logs", roots=(str(root),),
            patterns=("*.log.[0-9]*", "*.log.[0-9]*.gz"), recursive=False,
            min_age_days=14.0)
        plan = dr.build_plan([rule])
        assert _paths(plan) == {str(r1), str(r5)}
        assert active.exists()


# ── df-снимок и отчёт ───────────────────────────────────────────────────────


class TestReportAndDf:
    def test_df_snapshot_on_existing_root(self, tmp_path):
        root = tmp_path / "df"
        root.mkdir()
        snap = dr.df_snapshot([str(root), str(tmp_path / "missing")])
        assert os.path.realpath(str(root)) in snap
        info = snap[os.path.realpath(str(root))]
        assert info["total"] > 0 and info["free"] > 0

    def test_render_report_dry_run_has_plan_and_protection(self, tmp_path):
        root = tmp_path / "rep"
        _mk(root / "old.bin", b"abcd", days_ago=10)
        _mk(root / "local_database.db", b"live", days_ago=10)
        rule = dr.RetentionRule(key="rep", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        text = dr.render_report(plan)
        assert "DRY-RUN" in text
        assert "old.bin" in text
        assert "protected_db_or_wal" in text
        assert "TOTAL" in text

    def test_render_report_apply_shows_freed(self, tmp_path):
        root = tmp_path / "rep2"
        _mk(root / "old.bin", b"abcd", days_ago=10)
        rule = dr.RetentionRule(key="rep2", roots=(str(root),), patterns=("*",),
                                min_age_days=3.0)
        plan = dr.build_plan([rule])
        df_before = dr.df_snapshot([str(root)])
        report = dr.apply_plan(plan["plan"], rules=[rule])
        df_after = dr.df_snapshot([str(root)])
        text = dr.render_report(plan, apply_report=report,
                                df_before=df_before, df_after=df_after)
        assert "APPLY" in text
        assert "freed=" in text
        assert "освобождено" in text

    def test_human_bytes(self):
        assert dr.human_bytes(0) == "0.0 B"
        assert dr.human_bytes(2048) == "2.0 KiB"
        assert dr.human_bytes(3 * 1024 ** 3) == "3.0 GiB"


# ── apt-кэш: только безопасная каноническая команда, без shell ─────────────


class TestAptClean:
    def test_run_apt_clean_argv_no_shell(self):
        calls: list[dict] = []

        def fake_run(args, **kwargs):
            calls.append({"args": args, **kwargs})

            class P:
                returncode = 0

            return P()

        result = dr.run_apt_clean(runner=fake_run)
        assert result["returncode"] == 0
        assert calls[0]["args"] == ["apt-get", "clean"]
        assert calls[0].get("shell") is False

    def test_run_apt_clean_missing_binary_not_fatal(self):
        def boom(args, **kwargs):
            raise FileNotFoundError("apt-get")

        result = dr.run_apt_clean(runner=boom)
        assert result["returncode"] is None
        assert result["error"] == "FileNotFoundError"

    def test_main_dry_run_never_runs_apt(self, tmp_path, monkeypatch, capsys):
        called: list[bool] = []
        monkeypatch.setattr(dr, "run_apt_clean",
                            lambda *a, **k: called.append(True) or {})
        assert dr.main([]) == 0
        assert called == []

    def test_main_apply_with_apt_invokes_once(self, tmp_path, monkeypatch,
                                              capsys):
        called: list[bool] = []
        monkeypatch.setattr(dr, "run_apt_clean",
                            lambda *a, **k: called.append(True)
                            or {"cmd": "apt-get clean", "returncode": 0})
        assert dr.main(["--apply", "--with-apt"]) == 0
        assert called == [True]
        assert "apt-get clean" in capsys.readouterr().out


# ── CLI ─────────────────────────────────────────────────────────────────────


class TestCli:
    def test_dry_run_is_default_and_exit_zero(self, capsys):
        assert dr.main([]) == 0
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "APPLY" not in out

    def test_json_output_parseable(self, capsys):
        assert dr.main(["--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["mode"] == "dry-run"
        assert payload["enabled"] is True
        assert isinstance(payload["plan"], list)

    def test_apply_without_candidates_is_safe_noop(self, capsys):
        assert dr.main(["--apply"]) == 0
        out = capsys.readouterr().out
        assert "deleted=0" in out

    def test_apply_and_dry_run_mutually_exclusive(self):
        with pytest.raises(SystemExit) as exc:
            dr.main(["--apply", "--dry-run"])
        assert exc.value.code == 2

    def test_default_rules_contract(self):
        rules = {r.key: r for r in dr.default_rules()}
        assert set(rules) == {
            "db_anchor_backups", "app_adhoc_db_baks", "playwright_artifacts",
            "pytest_tmp", "pytest_tmp_files", "rotated_logs",
            "migrate_history"}
        assert rules["db_anchor_backups"].roots == (
            "/home/nik/backups", "/home/nik/backups_adminbot")
        assert rules["db_anchor_backups"].keep_newest == 2
        assert rules["db_anchor_backups"].keep_current_month is True
        assert rules["app_adhoc_db_baks"].patterns == \
            ("local_database.db.bak.*",)
        assert rules["playwright_artifacts"].min_age_days == 7.0
        assert rules["pytest_tmp"].min_age_days == 3.0
        assert rules["rotated_logs"].min_age_days == 14.0
        assert rules["migrate_history"].requires_owner_confirm is True
        assert rules["migrate_history"].roots == \
            ("/var/www/admin_bot/migrate_history",)

    def test_adhoc_bak_pattern_spares_working_db(self, tmp_path):
        root = tmp_path / "app"
        bak = _mk(root / "local_database.db.bak.2026-09-15-0744",
                  days_ago=20)
        for name in ("local_database.db", "local_database.db-wal",
                     "local_database_20261002.db"):
            _mk(root / name, days_ago=20)
        rule = dr.RetentionRule(
            key="app_adhoc_db_baks", roots=(str(root),),
            patterns=("local_database.db.bak.*",), recursive=False,
            min_age_days=14.0)
        plan = dr.build_plan([rule])
        assert _paths(plan) == {str(bak)}
