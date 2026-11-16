"""P0-PROD-DISK-01: деплой-харнесс вызывает retention и чистит /tmp.

Проверяем фактическое поведение существующего харнесса `deploy_v2.9.2.py`
без сети (fake SSH-клиент):
  (a) после успешного деплоя выполняется `manage.py disk cleanup --apply`;
  (b) staging-копии `/tmp/predeploy-*`, `/tmp/pre_deploy_*`, `/tmp/pre_t*`
      удаляются в `finally`;
  (c) ошибка cleanup не отменяет статус успешного деплоя.
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Channel:
    def __init__(self, rc: int = 0) -> None:
        self._rc = rc

    def recv_exit_status(self) -> int:
        return self._rc


class _Stream:
    def __init__(self, payload: bytes = b"", rc: int = 0) -> None:
        self._payload = payload
        self.channel = _Channel(rc)

    def read(self) -> bytes:
        return self._payload


class _Transport:
    def __init__(self, active: bool = True) -> None:
        self._active = active

    def is_active(self) -> bool:
        return self._active


class _FakeClient:
    """Минимальный paramiko-совместимый клиент: пишет команды, отдаёт статус."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.closed = False
        self.cleanup_error: Exception | None = None

    def set_missing_host_key_policy(self, *_args) -> None:
        pass

    def connect(self, *_args, **_kwargs) -> None:
        pass

    def exec_command(self, cmd: str, timeout=None):
        self.commands.append(cmd)
        if "systemctl status" in cmd:
            return (None, _Stream(b"Main PID: 321\nActive: active (running)\n"),
                    _Stream())
        if "manage.py disk cleanup" in cmd:
            if self.cleanup_error is not None:
                raise self.cleanup_error
            return (None, _Stream(b"disk cleanup: APPLY deleted=1"), _Stream())
        return None, _Stream(b"ok"), _Stream()

    def get_transport(self) -> _Transport:
        return _Transport()

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def harness(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "deploy_harness_v292", REPO_ROOT / "deploy_v2.9.2.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    client = _FakeClient()
    monkeypatch.setattr(module.paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(module.time, "sleep", lambda *_a: None)
    monkeypatch.setenv("DEPLOY_SSH_PASSWORD", "fake")
    monkeypatch.chdir(tmp_path)
    return module, client


def test_post_deploy_cleanup_and_tmp_removal(harness):
    module, client = harness
    assert module.main() == 0

    cleanup_calls = [c for c in client.commands
                     if "manage.py disk cleanup --apply" in c]
    tmp_calls = [c for c in client.commands if c.startswith("rm -f /tmp/predeploy")]
    assert len(cleanup_calls) == 1
    assert len(tmp_calls) == 1
    assert "/tmp/predeploy-*.db" in tmp_calls[0]
    assert "/tmp/pre_deploy_*.db" in tmp_calls[0]
    # cleanup идёт после деплоя, удаление /tmp — уже в finally (после cleanup)
    assert (client.commands.index(cleanup_calls[0])
            < client.commands.index(tmp_calls[0]))
    assert client.closed is True


def test_cleanup_failure_does_not_fail_successful_deploy(harness):
    module, client = harness
    client.cleanup_error = RuntimeError("cleanup boom")
    assert module.main() == 0
    assert any(c.startswith("rm -f /tmp/predeploy") for c in client.commands)
