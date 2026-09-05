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

    def test_graph_dry_run_counts_nothing_written(self, tmp_path):
        """--mode graph --dry-run (часть B, T-761): подсчёт кандидатов/пачек
        без записи и без LLM; отчёт печатается; БД не меняется."""
        db = str(tmp_path / "graph.db")
        first = _run("import_history", "--mode", "fts",
                     "--files", CHAT_2026, CHAT_2025, "--db", db,
                     "--no-vacuum")
        assert first.returncode == 0, first.stderr
        before = _sqlite_rows(db)
        proc = _run("import_history", "--mode", "graph", "--db", db,
                    "--dry-run", "--embed-mode", "skip",
                    "--fact-density", "0.5", "--min-fact-chars", "1")
        assert proc.returncode == 0, proc.stderr
        assert "Graph-этап" in proc.stdout
        assert "dry-run" in proc.stdout
        assert "кандидатов 5" in proc.stdout
        assert "пачек 1" in proc.stdout
        assert "LLM/embed-вызовы НЕ выполнялись" in proc.stdout
        assert _sqlite_rows(db) == before == 6
        import sqlite3
        conn = sqlite3.connect(db)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM graph_facts").fetchone()[0]
            assert count == 0
        finally:
            conn.close()

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


class TestCliGraphHumanizedErrors:
    """Задача 2 (2026-09-05): человекочитаемые ошибки/останов Graph-этапа.

    Прямые unit-проверки manage.main: Ctrl+C → заметка + exit 130 (БЕЗ
    трейсбека); EmbedError верхнего уровня → печать humanize-причины.
    (Реальный SIGINT через subprocess не гоняется — обработчик покрыт
    вызовом main с подменой точки входа.)"""

    @staticmethod
    def _graph_args(tmp_path) -> list[str]:
        return ["import_history", "--mode", "graph",
                "--db", str(tmp_path / "g.db"), "--embed-mode", "skip"]

    def test_keyboard_interrupt_notice_and_exit_130(self, tmp_path, capsys,
                                                    monkeypatch):
        import manage as mg

        def raiser(coro):
            coro.close()
            raise KeyboardInterrupt

        monkeypatch.setattr(mg.asyncio, "run", raiser)
        code = mg.main(self._graph_args(tmp_path))
        assert code == 130
        out = capsys.readouterr()
        assert "Пауза в любой момент: Ctrl+C (прогресс сохраняется)" \
            in out.out
        assert "Остановлено вручную (Ctrl+C)" in out.err
        assert "Traceback" not in out.err

    def test_embed_error_top_level_printed_humanized(self, tmp_path, capsys,
                                                     monkeypatch):
        from tools.history_import.llm_worker import EmbedError
        import manage as mg

        def raiser(coro):
            coro.close()
            raise EmbedError("embed HTTP 403: quota exceeded")

        monkeypatch.setattr(mg.asyncio, "run", raiser)
        code = mg.main(self._graph_args(tmp_path))
        assert code == 1
        err = capsys.readouterr().err
        assert "ошибка Graph-этапа" in err
        assert "(403)" in err          # человеческая причина вместо голого exc
        assert "тип=EmbedError" in err

    def test_history_llm_error_top_level_humanized_separately(
            self, tmp_path, capsys, monkeypatch):
        """Задача 3(в): HistoryLLMError верхнего уровня — текст про парсинг
        фактов (НЕ про эмбеддинги): никакого «data[].embedding» в выводе."""
        from tools.history_import.llm_worker import HistoryLLMError
        import manage as mg

        def raiser(coro):
            coro.close()
            raise HistoryLLMError(
                "LLM ответ — не JSON-массив фактов: «мысли модели»")

        monkeypatch.setattr(mg.asyncio, "run", raiser)
        code = mg.main(self._graph_args(tmp_path))
        assert code == 1
        err = capsys.readouterr().err
        assert "ошибка Graph-этапа" in err
        assert "не удалось разобрать как список фактов" in err
        assert "data[].embedding" not in err
        assert "тип=HistoryLLMError" in err

    def test_unknown_error_keeps_plain_message(self, tmp_path, capsys,
                                               monkeypatch):
        import manage as mg

        def raiser(coro):
            coro.close()
            raise RuntimeError("неожиданный сбой")

        monkeypatch.setattr(mg.asyncio, "run", raiser)
        code = mg.main(self._graph_args(tmp_path))
        assert code == 1
        assert "RuntimeError" in capsys.readouterr().err
