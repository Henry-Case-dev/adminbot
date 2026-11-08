"""SELF-DIAG-01 D1 — portable local log backend чекапа (CONTRACT).

Проверяется наблюдаемый контракт, а не внутренняя проводка:

* определение способа запуска собственного процесса
  (systemd / container / standalone) по cgroup, маркерам и INVOCATION_ID;
* systemd-журнал читается фиксированным argv через
  ``create_subprocess_exec`` (shell НЕ используется), unit берётся из
  собственного cgroup, устаревший unit из конфига не подхватывается;
* пустой журнал, журнал «только INFO» и нечитаемый журнал — РАЗНЫЕ
  состояния, и пустой журнал не выдаётся за «сервис здоров»;
* контейнер/standalone не предполагают journalctl: свой stdout-файл или
  существующий in-process ledger (``services.log_ring``);
* Better Stack в runtime-пути чекапа отсутствует: ноль HTTP-клиентов,
  ноль сетевых вызовов, а bare «чекап» по-прежнему возвращает отчёт тем же
  ключом промпта.

TEST-LIFECYCLE: CONTRACT owner=SELF-DIAG-01-D1 (requirements-map SD1-D1-01..14)
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import system_logs_fetcher as fetcher_mod
from services.system_logs_fetcher import (
    CheckupLogsFetcher,
    CheckupLogsUnavailableException,
    RuntimeIdentity,
    detect_runtime,
)

UNIT = "admin_bot.service"
INVOCATION = "0123456789abcdef0123456789abcdef"

SYSTEMD_IDENTITY = RuntimeIdentity(
    kind="systemd", pid=4242, unit=UNIT, invocation_id=INVOCATION,
    cgroup=f"0::/system.slice/{UNIT}",
)
SYSTEMD_NO_INVOCATION = RuntimeIdentity(
    kind="systemd", pid=4242, unit=UNIT,
    cgroup=f"1:name=systemd:/system.slice/{UNIT}",
)
CONTAINER_IDENTITY = RuntimeIdentity(
    kind="container", pid=4242, cgroup="0::/",
    container_marker="file:/.dockerenv",
)
STANDALONE_IDENTITY = RuntimeIdentity(kind="standalone", pid=4242, cgroup="")


def _fetcher(
    identity=SYSTEMD_IDENTITY,
    *,
    runner=None,
    ledger=None,
    stdout=None,
    **kwargs,
):
    """Фетчер с полностью подменёнными источниками (без реального I/O)."""
    if ledger is None:
        ledger = lambda limit: []          # noqa: E731
    if stdout is None:
        stdout = lambda limit: None        # noqa: E731
    return CheckupLogsFetcher(
        identity_probe=lambda: identity,
        journal_runner=runner,
        ledger_reader=ledger,
        stdout_tail_reader=stdout,
        **kwargs,
    )


def _journal_runner(rc=0, out="", err="", calls=None):
    async def runner(argv):
        if calls is not None:
            calls.append(list(argv))
        return rc, out, err

    return runner


def _header(text: str) -> str:
    return text.splitlines()[0]


def _ledger_entries(*rows):
    return [
        {"ts": "2026-11-09T10:00:0%d+00:00" % i, "level": level,
         "logger": "x", "message": message, "exc_text": None}
        for i, (level, message) in enumerate(rows)
    ]


# ── Определение среды процесса ──────────────────────────────────────────


class TestRuntimeDetection:
    def test_systemd_uses_own_cgroup_unit_and_invocation(self):
        identity = detect_runtime(
            environ={"INVOCATION_ID": INVOCATION},
            cgroup=f"0::/system.slice/{UNIT}",
            container_marker=None,
        )
        assert identity.kind == "systemd"
        assert identity.unit == UNIT
        assert identity.invocation_id == INVOCATION

    def test_systemd_legacy_cgroup_v1(self):
        identity = detect_runtime(
            environ={},
            cgroup=f"1:name=systemd:/system.slice/{UNIT}\n0::/init.scope",
            container_marker=None,
        )
        assert identity.kind == "systemd"
        assert identity.unit == UNIT
        assert identity.invocation_id is None

    @pytest.mark.parametrize(
        "environ,cgroup,expected",
        [
            ({"container": "docker"}, "0::/", "env:docker"),
            ({"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, "0::/", "env:kubernetes"),
            ({}, "0::/kubepods/burstable/pod123/abc", "cgroup:kubepods"),
            ({}, "0::/docker/0123456789abcdef", "cgroup:docker"),
        ],
    )
    def test_container_markers(self, monkeypatch, environ, cgroup, expected):
        # Файловые пробы отключены — проверяются env/cgroup-маркеры.
        monkeypatch.setattr(fetcher_mod, "_read_text_file", lambda path: None)
        monkeypatch.setattr(fetcher_mod, "_path_exists", lambda path: False)
        identity = detect_runtime(environ=environ, cgroup=cgroup)
        assert identity.kind == "container"
        assert identity.container_marker == expected

    def test_container_marker_from_dot_dockerenv(self, monkeypatch):
        monkeypatch.setattr(fetcher_mod, "_read_text_file", lambda path: None)
        monkeypatch.setattr(
            fetcher_mod, "_path_exists", lambda path: path == "/.dockerenv")
        identity = detect_runtime(environ={}, cgroup="0::/")
        assert identity.kind == "container"
        assert identity.container_marker == "file:/.dockerenv"

    def test_container_detection_wins_over_journal_env(self):
        identity = detect_runtime(
            environ={"INVOCATION_ID": INVOCATION},
            cgroup=f"0::/system.slice/{UNIT}",
            container_marker="file:/.dockerenv",
        )
        assert identity.kind == "container"
        assert identity.container_marker == "file:/.dockerenv"

    def test_standalone_without_markers(self):
        identity = detect_runtime(
            environ={}, cgroup="", container_marker=None,
        )
        assert identity.kind == "standalone"
        assert identity.unit is None
        assert identity.invocation_id is None

    def test_invalid_invocation_id_not_used(self):
        identity = detect_runtime(
            environ={"INVOCATION_ID": "not-a-real-invocation; rm -rf /"},
            cgroup="", container_marker=None,
        )
        assert identity.invocation_id is None
        assert identity.kind == "standalone"


# ── systemd: фиксированный argv, свой unit, честные состояния ───────────


class TestJournalBackend:
    @pytest.mark.asyncio
    async def test_fixed_argv_via_exec_without_shell(self, monkeypatch):
        """shell-строки нет: только create_subprocess_exec(*argv), argv[0] —
        journalctl, окно — из настроенного лимита."""
        calls = []
        proc = SimpleNamespace(
            returncode=0,
            communicate=AsyncMock(return_value=(b"ERROR boom\n", b"")),
        )

        async def fake_exec(*argv, stdout=None, stderr=None):
            calls.append(list(argv))
            return proc

        async def forbidden_shell(*args, **kwargs):       # pragma: no cover
            raise AssertionError("checkup must not use a shell string")

        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_exec",
                            fake_exec)
        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell",
                            forbidden_shell)
        fetcher = CheckupLogsFetcher(identity_probe=lambda: SYSTEMD_IDENTITY,
                                     window_lines=250,
                                     ledger_reader=lambda n: [])
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        assert len(calls) == 1
        argv = calls[0]
        assert argv[0] == "journalctl"
        assert "--lines=250" in argv
        assert argv[-1] == f"_SYSTEMD_INVOCATION_ID={INVOCATION}"
        assert not any(" " in part or ";" in part or "|" in part
                       for part in argv[1:])
        assert "ERROR boom" in text
        assert "state=ok" in _header(text)

    @pytest.mark.asyncio
    async def test_invocation_match_scopes_journal_to_this_instance(self):
        calls = []
        fetcher = _fetcher(runner=_journal_runner(
            out="ERROR boom\n", calls=calls))
        await fetcher.fetch()
        assert f"_SYSTEMD_INVOCATION_ID={INVOCATION}" in calls[0]
        assert "--unit" not in calls[0]

    @pytest.mark.asyncio
    async def test_unit_from_cgroup_when_invocation_absent(self):
        calls = []
        fetcher = _fetcher(identity=SYSTEMD_NO_INVOCATION,
                           runner=_journal_runner(out="", calls=calls))
        await fetcher.fetch()
        assert "--unit" in calls[0]
        assert calls[0][calls[0].index("--unit") + 1] == UNIT

    @pytest.mark.asyncio
    async def test_stale_unit_override_is_rejected(self, caplog):
        """Старое имя юнита (в т.ч. из прежнего CHECKUP_JOURNALCTL_CMD) не
        используется: argv получает фактический unit из cgroup."""
        import logging

        calls = []
        fetcher = _fetcher(identity=SYSTEMD_NO_INVOCATION,
                           runner=_journal_runner(out="", calls=calls),
                           unit_override="admin_bot")
        with caplog.at_level(logging.WARNING):
            await fetcher.fetch()
        assert "--unit" in calls[0]
        assert calls[0][calls[0].index("--unit") + 1] == UNIT
        assert "admin_bot" not in calls[0]
        assert any("unit override rejected" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_stale_unit_override_never_replaces_invocation_match(self):
        """Даже валидный по форме, но чужой unit не подменяет invocation-матч:
        источником остаётся ИМЕННО этот запуск процесса."""
        calls = []
        fetcher = _fetcher(runner=_journal_runner(out="", calls=calls),
                           unit_override="other_bot.service")
        await fetcher.fetch()
        assert f"_SYSTEMD_INVOCATION_ID={INVOCATION}" in calls[0]
        assert "other_bot.service" not in calls[0]
        assert "--unit" not in calls[0]

    @pytest.mark.asyncio
    async def test_override_matching_live_cgroup_is_accepted(self):
        calls = []
        fetcher = _fetcher(identity=SYSTEMD_NO_INVOCATION,
                           runner=_journal_runner(out="", calls=calls),
                           unit_override=UNIT)
        await fetcher.fetch()
        assert calls[0][calls[0].index("--unit") + 1] == UNIT

    @pytest.mark.asyncio
    async def test_empty_journal_is_not_healthy(self):
        fetcher = _fetcher(runner=_journal_runner(out=""))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        header = _header(text)
        assert "state=empty" in header and "read=0" in header
        assert "НЕ доказывает" in text

    @pytest.mark.asyncio
    async def test_info_only_window_is_distinct(self):
        out = "2026-11-09T10:00:00+00:00 host bot[1]: INFO all fine\n" * 3
        fetcher = _fetcher(runner=_journal_runner(out=out))
        text, used_fallback = await fetcher.fetch()
        header = _header(text)
        assert "state=info_only" in header
        assert "read=3" in header and "matched=0" in header
        assert "INFO" in text  # честная пометка про INFO-only
        assert used_fallback is False

    @pytest.mark.asyncio
    async def test_error_lines_are_filtered_and_matched_counted(self):
        out = (
            "2026-11-09T10:00:00+00:00 host bot[1]: INFO all fine\n"
            "2026-11-09T10:00:01+00:00 host bot[1]: ERROR disk exploded\n"
            "2026-11-09T10:00:02+00:00 host bot[1]: WARNING low memory\n"
            "2026-11-09T10:00:03+00:00 host bot[1]: INFO still fine\n"
        )
        fetcher = _fetcher(runner=_journal_runner(out=out))
        text, _ = await fetcher.fetch()
        body = text.splitlines()[1:]
        assert "read=4" in _header(text) and "matched=2" in _header(text)
        assert any("ERROR disk exploded" in line for line in body)
        assert any("WARNING low memory" in line for line in body)
        assert not any("INFO all fine" in line for line in body)

    @pytest.mark.asyncio
    async def test_permission_denied_falls_back_to_own_ledger(self):
        fetcher = _fetcher(
            runner=_journal_runner(
                rc=1, err="Hint: You are currently not seeing messages from "
                          "other users. Permission denied"),
            ledger=lambda limits: _ledger_entries(("ERROR", "ledger boom")),
        )
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        header = _header(text)
        assert "backend=ledger" in header
        assert "journal=unreadable(permission)" in header
        assert "ledger boom" in text

    @pytest.mark.asyncio
    async def test_spawn_error_is_partial_not_fatal(self):
        async def runner(argv):
            raise OSError("journalctl not found")

        fetcher = _fetcher(runner=runner,
                           ledger=lambda limits: _ledger_entries(
                               ("ERROR", "in-process boom")))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert "journal=unreadable(spawn:OSError)" in _header(text)
        assert "in-process boom" in text

    @pytest.mark.asyncio
    async def test_timeout_is_unavailable_from_journal(self):
        async def runner(argv):
            raise asyncio.TimeoutError()

        fetcher = _fetcher(runner=runner,
                           ledger=lambda limits: _ledger_entries())
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert "backend=ledger" in _header(text)
        assert "journal=unreadable" in _header(text)


# ── container / standalone: свой поток / ledger, без journalctl ─────────


class TestLocalStreamBackends:
    @pytest.mark.asyncio
    async def test_container_without_journal_uses_own_stream(self):
        """Контейнер без systemd-журнала: journalctl НЕ вызывается вовсе."""
        calls = []
        fetcher = _fetcher(
            identity=CONTAINER_IDENTITY,
            runner=_journal_runner(out="ERROR never", calls=calls),
            stdout=lambda limit: ["ERROR container boom"],
        )
        text, used_fallback = await fetcher.fetch()
        assert calls == []
        assert used_fallback is False
        assert "backend=stdout_file" in _header(text)
        assert "ERROR container boom" in text

    @pytest.mark.asyncio
    async def test_container_without_stream_uses_ledger(self):
        fetcher = _fetcher(
            identity=CONTAINER_IDENTITY,
            ledger=lambda limits: _ledger_entries(("ERROR", "ledger boom")),
        )
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        assert "backend=ledger" in _header(text)
        assert "ledger boom" in text

    @pytest.mark.asyncio
    async def test_standalone_uses_event_ledger_chronologically(self):
        # Реальный ledger отдаёт новые→старые; отчёт — хронологически.
        entries = _ledger_entries(("WARNING", "second"), ("ERROR", "first"),
                                  ("INFO", "noise"))
        fetcher = _fetcher(identity=STANDALONE_IDENTITY,
                           ledger=lambda limits: entries)
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        lines = [ln for ln in text.splitlines() if " - " in ln]
        assert len(lines) == 2
        assert "first" in lines[0] and "second" in lines[1]
        assert "read=3" in _header(text) and "matched=2" in _header(text)

    @pytest.mark.asyncio
    async def test_empty_ledger_is_distinct_from_info_only(self):
        empty = _fetcher(identity=STANDALONE_IDENTITY,
                         ledger=lambda limits: [])
        text, _ = await empty.fetch()
        assert "state=empty" in _header(text)

        info_only = _fetcher(
            identity=STANDALONE_IDENTITY,
            ledger=lambda limits: _ledger_entries(("INFO", "noise")),
        )
        text, _ = await info_only.fetch()
        assert "state=info_only" in _header(text)
        assert "не доказывает" in text

    @pytest.mark.asyncio
    async def test_nothing_readable_raises_unavailable(self):
        def broken_ledger(limit):
            raise RuntimeError("ring exploded")

        fetcher = _fetcher(identity=STANDALONE_IDENTITY,
                           ledger=broken_ledger)
        with pytest.raises(CheckupLogsUnavailableException):
            await fetcher.fetch()

    @pytest.mark.asyncio
    async def test_window_is_bounded(self):
        seen = {}

        def ledger(limit):
            seen["limit"] = limit
            return []

        fetcher = _fetcher(identity=STANDALONE_IDENTITY, ledger=ledger,
                           window_lines=120)
        await fetcher.fetch()
        assert seen["limit"] == 120

    def test_describe_source_reports_factual_environment(self):
        fetcher = _fetcher()
        described = fetcher.describe_source()
        assert "systemd" in described
        assert INVOCATION in described
        assert UNIT in described


# ── Better Stack в runtime-пути чекапа отсутствует ─────────────────────


class TestNoBetterStackInCheckupRuntime:
    def test_fetcher_module_has_no_http_client_and_no_legacy_settings(self):
        from config.settings import settings

        assert not hasattr(fetcher_mod, "httpx")
        source = (fetcher_mod.__file__ and
                  open(fetcher_mod.__file__, encoding="utf-8").read()) or ""
        assert "betterstack" not in source.lower()
        assert "create_subprocess_shell" not in source
        for legacy in (
            "CHECKUP_JOURNALCTL_CMD",
            "CHECKUP_BETTERSTACK_SQL_HOST",
            "CHECKUP_BETTERSTACK_SQL_USER",
            "CHECKUP_BETTERSTACK_SQL_PASSWORD",
            "CHECKUP_BETTERSTACK_SQL_TABLE",
            "CHECKUP_BETTERSTACK_SQL_QUERY",
        ):
            assert not hasattr(settings, legacy), legacy

    def test_catalog_has_no_checkup_betterstack_keys(self):
        from services import param_catalog as pc

        keys = set(pc.REGISTRY.keys())
        assert not {key for key in keys if "BETTERSTACK_SQL" in key}
        assert "CHECKUP_JOURNALCTL_CMD" not in keys
        assert "models_checkup" not in {g.id for g in pc.GROUPS}
        assert "keys_betterstack" not in {g.id for g in pc.GROUPS}

    @pytest.mark.asyncio
    async def test_bare_checkup_makes_zero_network_calls(self, monkeypatch):
        """Полный bare-путь «чекап» с реальным fetcher: ни одного HTTP-клиента
        и ни одного обращения к Better Stack; отчёт уходит реплаем."""
        import httpx
        from handlers import checkup as checkup_mod
        from services.checkup_service import CheckupService

        def forbidden_client(*args, **kwargs):       # pragma: no cover
            raise AssertionError("сетевой клиент создан в runtime-пути чекапа")

        monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)
        monkeypatch.setattr(httpx, "Client", forbidden_client)

        runner = _journal_runner(
            out="2026-11-09T10:00:00+00:00 host bot[1]: ERROR disk exploded\n")
        fetcher = _fetcher(runner=runner)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="отчёт о здоровье")
        checkup_mod.setup_checkup(CheckupService(llm), fetcher)
        message = MagicMock()
        message.text = "чекап"
        message.caption = None
        message.message_id = 77
        message.chat.id = -1001234567890
        message.from_user.id = 42
        bot = AsyncMock()
        try:
            result = await checkup_mod.checkup_handler(message, bot=bot)
        finally:
            checkup_mod._service = None
            checkup_mod._fetcher = None
            checkup_mod._cooldown._last.clear()

        assert result is None
        assert bot.send_message.await_args.args[1] == "отчёт о здоровье"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        user_content = llm.generate.await_args.args[0][1]["content"]
        assert "ERROR disk exploded" in user_content
        assert "[log-source]" in user_content

    @pytest.mark.asyncio
    async def test_bare_checkup_uses_same_prompt_key(self, monkeypatch):
        """Промпт-ключ и его байты не меняются: чекup идёт через
        resolve_prompt("prompts.checkup_system_prompt", CHECKUP_SYSTEM_PROMPT)."""
        from services import checkup_service as svc_mod
        from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT
        from services.checkup_service import CheckupService

        seen = {}
        real_resolve = svc_mod.resolve_prompt

        def spy(key, default):
            seen["key"] = key
            seen["default"] = default
            return real_resolve(key, default)

        monkeypatch.setattr(svc_mod, "resolve_prompt", spy)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="отчёт")
        fetcher = _fetcher(runner=_journal_runner(out=""))
        await CheckupService(llm).checkup(*(await fetcher.fetch()),
                                          chat_id=None)
        assert seen["key"] == "prompts.checkup_system_prompt"
        assert seen["default"] == CHECKUP_SYSTEM_PROMPT
