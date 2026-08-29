"""Epic 85 (T-641, 84.15) — тесты ControlService.

DoD 84.16.2 п.14: 202 + отложенное выполнение (мок sleep), дебаунс 429
(ControlDebouncedError), dev-режим start → 409, dev restart/stop →
request_shutdown, systemd → мок subprocess.Popen, флаг-файл stop,
restart/start удаляют флаг. Никогда не блокируем ответ.
"""
import asyncio
import time
from pathlib import Path

import pytest

from services.control_service import (
    ControlDebouncedError,
    ControlService,
    ControlStartUnavailableError,
    detect_mode,
)


@pytest.fixture
def shutdown_calls():
    calls = []
    return lambda: calls.append(1), calls


class TestDetectMode:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CONTROL_MODE", "systemd")
        assert detect_mode() == "systemd"
        monkeypatch.setenv("CONTROL_MODE", "dev")
        assert detect_mode() == "dev"

    def test_windows_dev(self, monkeypatch):
        monkeypatch.delenv("CONTROL_MODE", raising=False)
        monkeypatch.setattr("services.control_service.sys.platform", "win32")
        assert detect_mode() == "dev"

    def test_linux_systemd(self, monkeypatch):
        import types as _t

        class _FakePath:
            def __init__(self, p):
                self._p = p

            def exists(self):
                return str(self._p) == "/run/systemd/system"

        monkeypatch.delenv("CONTROL_MODE", raising=False)
        monkeypatch.setattr("services.control_service.sys.platform", "linux")
        monkeypatch.setattr("services.control_service.Path", _FakePath)
        monkeypatch.setattr(
            "services.control_service.shutil.which",
            lambda x: "/usr/bin/systemctl")
        assert detect_mode() == "systemd"

    def test_linux_without_systemd_dev(self, monkeypatch):
        monkeypatch.delenv("CONTROL_MODE", raising=False)
        monkeypatch.setattr("services.control_service.sys.platform", "linux")
        monkeypatch.setattr(
            "services.control_service.shutil.which", lambda x: None)
        assert detect_mode() == "dev"


class TestRequest:
    @pytest.mark.asyncio
    async def test_returns_202_payload_immediately(self, monkeypatch):
        svc = ControlService(mode="dev")
        monkeypatch.setattr(svc, "_exec_delay", 0)
        result = await svc.request("restart", by=1)
        assert result == {"action": "restart", "scheduled_in_seconds": 0,
                          "mode": "dev"}

    @pytest.mark.asyncio
    async def test_debounce_429(self, monkeypatch):
        svc = ControlService(mode="dev", debounce_seconds=30.0)
        await svc.request("stop", by=1)
        with pytest.raises(ControlDebouncedError) as exc:
            await svc.request("stop", by=2)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_dev_start_409(self):
        svc = ControlService(mode="dev")
        with pytest.raises(ControlStartUnavailableError) as exc:
            await svc.request("start", by=1)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_dev_restart_calls_shutdown_after_delay(self, monkeypatch):
        request_shutdown, calls = _shutdown_fixture()
        svc = ControlService(mode="dev", request_shutdown=request_shutdown,
                             exec_delay=0.05)
        result = await svc.request("restart", by=1)
        assert result["mode"] == "dev"
        assert calls == []                      # ответ не ждёт выполнения
        await asyncio.sleep(0.1)                # отложенный exec (sleep 0.05)
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_dev_stop_calls_shutdown(self, monkeypatch):
        request_shutdown, calls = _shutdown_fixture()
        svc = ControlService(mode="dev", request_shutdown=request_shutdown,
                             exec_delay=0.01)
        await svc.request("stop", by=1)
        await asyncio.sleep(0.05)
        assert calls == [1]


def _shutdown_fixture():
    calls = []

    def _cb():
        calls.append(1)

    return _cb, calls


class TestSystemd:
    @pytest.mark.asyncio
    async def test_restart_spawns_systemctl(self, monkeypatch, tmp_path):
        spawned = []
        monkeypatch.setattr(
            "services.control_service.subprocess.Popen",
            lambda cmd, **kw: spawned.append((cmd, kw)),
        )
        flag = tmp_path / "flag"
        svc = ControlService(mode="systemd", exec_delay=0.01,
                             flag_file=str(flag))
        flag.write_text("1")                    # остался от прошлого stop
        await svc.request("restart", by=1)
        await asyncio.sleep(0.05)
        assert len(spawned) == 1
        cmd, kw = spawned[0]
        assert cmd == ["systemctl", "restart", "admin_bot"]
        assert kw.get("start_new_session") is True
        assert not flag.exists()                # restart удаляет флаг

    @pytest.mark.asyncio
    async def test_stop_creates_flag_before_systemctl(self, monkeypatch,
                                                      tmp_path):
        spawned = []
        monkeypatch.setattr(
            "services.control_service.subprocess.Popen",
            lambda cmd, **kw: spawned.append(cmd),
        )
        flag = tmp_path / "flag"
        svc = ControlService(mode="systemd", exec_delay=0.01,
                             flag_file=str(flag))
        await svc.request("stop", by=1)
        await asyncio.sleep(0.05)
        assert flag.exists()                    # флаг ДО systemctl stop
        assert spawned == [["systemctl", "stop", "admin_bot"]]

    @pytest.mark.asyncio
    async def test_start_removes_flag_and_spawns(self, monkeypatch, tmp_path):
        spawned = []
        monkeypatch.setattr(
            "services.control_service.subprocess.Popen",
            lambda cmd, **kw: spawned.append(cmd),
        )
        flag = tmp_path / "flag"
        flag.write_text("1")
        svc = ControlService(mode="systemd", exec_delay=0.01,
                             flag_file=str(flag))
        await svc.request("start", by=1)
        await asyncio.sleep(0.05)
        assert not flag.exists()
        assert spawned == [["systemctl", "start", "admin_bot"]]

    @pytest.mark.asyncio
    async def test_subprocess_failure_logged_not_raised(self, monkeypatch,
                                                        caplog):
        def _boom(cmd, **kw):
            raise OSError("no systemctl")

        monkeypatch.setattr("services.control_service.subprocess.Popen", _boom)
        svc = ControlService(mode="systemd", exec_delay=0.01)
        await svc.request("restart", by=1)
        await asyncio.sleep(0.05)
        assert any("subprocess failed" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_execute_failure_logged_not_raised(self, monkeypatch,
                                                     caplog):
        """_execute_after: исключение выполнения логируется, запрос жив."""
        import logging

        svc = ControlService(mode="systemd", exec_delay=0.01)

        def _boom(action):
            raise RuntimeError("execution exploded")

        monkeypatch.setattr(svc, "_run_systemd", _boom)
        with caplog.at_level(logging.ERROR):
            await svc.request("restart", by=1)
            await asyncio.sleep(0.05)
        assert any("execute failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_flag_file_write_failure_logged(self, monkeypatch, caplog):
        import logging
        import types as _t

        class _BoomFile:
            def write_text(self, *a, **kw):
                raise OSError("ro fs")

            def exists(self):
                return True

            def unlink(self):
                raise OSError("ro fs")

        svc = ControlService(mode="systemd", exec_delay=0.01)
        svc._flag_file = _BoomFile()
        with caplog.at_level(logging.WARNING):
            svc.create_flag_file()
            svc.remove_flag_file()
        assert any("flag-file create failed" in r.message
                   for r in caplog.records)
        assert any("flag-file remove failed" in r.message
                   for r in caplog.records)


class TestFlagFile:
    def test_flag_file_exists(self, tmp_path, monkeypatch):
        flag = tmp_path / ".adminbot_keep_stopped"
        assert not ControlService.flag_file_exists(str(flag))
        flag.write_text("1")
        assert ControlService.flag_file_exists(str(flag))
