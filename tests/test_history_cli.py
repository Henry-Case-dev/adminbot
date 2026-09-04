"""Фаза 2 (T-754, C2) — тесты CLI `manage.py import_history --mode fts`.

Запуск через subprocess (реальный интерпретатор, корень репо):
флаги, идемпотентность, resume-сценарий, dry-run (ничего не пишет),
охват обязателен, отчёт печатается, чужой чат не появляется.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANAGE = os.path.join(ROOT, "manage.py")
CHAT_2026 = os.path.join(ROOT, "tests", "fixtures", "history", "chat_2026.json")
CHAT_2025 = os.path.join(ROOT, "tests", "fixtures", "history", "chat_2025.json")
TARGET_CHAT = -1002661910336


def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, MANAGE, *args],
        capture_output=True, text=True, encoding="utf-8",
        env=env, cwd=cwd or ROOT, timeout=180)


def _sqlite_rows(db_path: str) -> int:
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM smart_messages").fetchone()[0]
    finally:
        conn.close()


class TestCliFts:
    def test_import_writes_and_reports(self, tmp_path):
        db = str(tmp_path / "cli.db")
        proc = _run("import_history", "--mode", "fts",
                    "--files", CHAT_2026, "--db", db,
                    "--target-chat", str(TARGET_CHAT), "--no-vacuum")
        assert proc.returncode == 0, proc.stderr
        assert "итог:" in proc.stdout
        assert "chat_id=" in proc.stdout
        assert "ВСТАВЛЕНО 5" in proc.stdout
        assert _sqlite_rows(db) == 5

    def test_second_run_idempotent(self, tmp_path):
        db = str(tmp_path / "cli2.db")
        first = _run("import_history", "--mode", "fts",
                     "--files", CHAT_2026, CHAT_2025, "--db", db,
                     "--no-vacuum")
        assert first.returncode == 0, first.stderr
        assert "ВСТАВЛЕНО 6" in first.stdout
        rows_after_first = _sqlite_rows(db)
        second = _run("import_history", "--mode", "fts",
                      "--files", CHAT_2026, CHAT_2025, "--db", db,
                      "--no-vacuum")
        assert second.returncode == 0, second.stderr
        assert "ВСТАВЛЕНО 0" in second.stdout
        assert _sqlite_rows(db) == rows_after_first == 6

    def test_dry_run_writes_nothing(self, tmp_path):
        db = str(tmp_path / "dry.db")
        proc = _run("import_history", "--mode", "fts",
                    "--files", CHAT_2026, CHAT_2025,
                    "--db", db, "--dry-run")
        assert proc.returncode == 0, proc.stderr
        assert "--dry-run" in proc.stdout or "dry" in proc.stdout.lower()
        assert "итог:" in proc.stdout
        assert "ВСТАВЛЕНО" not in proc.stdout
        assert not os.path.exists(db)

    def test_reset_flag_repeats_import(self, tmp_path):
        db = str(tmp_path / "reset.db")
        first = _run("import_history", "--mode", "fts",
                     "--files", CHAT_2026, "--db", db, "--no-vacuum")
        assert first.returncode == 0
        again = _run("import_history", "--mode", "fts",
                     "--files", CHAT_2026, "--db", db,
                     "--reset", "--no-vacuum")
        assert again.returncode == 0, again.stderr
        assert "ВСТАВЛЕНО 0" in again.stdout
        assert _sqlite_rows(db) == 5

    def test_scope_is_required(self):
        proc = _run("import_history", "--mode", "fts")
        assert proc.returncode != 0
        assert "охват" in (proc.stderr + proc.stdout)

    def test_missing_file_fails(self, tmp_path):
        proc = _run("import_history", "--mode", "fts",
                    "--files", str(tmp_path / "нет-такого.json"))
        assert proc.returncode != 0
        assert "не найден" in (proc.stderr + proc.stdout)

    def test_foreign_chat_filtered_by_target_chat(self, tmp_path):
        """Весь импорт идёт под --target-chat (экспортные файлы без chat_id
        на уровне сообщений; чужой чат-таргет не мешает записи)."""
        db = str(tmp_path / "other.db")
        proc = _run("import_history", "--mode", "fts",
                    "--files", CHAT_2026, "--db", db,
                    "--target-chat", "-100999", "--no-vacuum")
        assert proc.returncode == 0, proc.stderr
        import sqlite3
        conn = sqlite3.connect(db)
        try:
            chats = {r[0] for r in conn.execute(
                "SELECT DISTINCT chat_id FROM smart_messages")}
            assert chats == {-100999}
        finally:
            conn.close()
