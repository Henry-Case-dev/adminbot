"""Epic 85 (84.15, T-641) — управление жизненным циклом бота (/api/control/*).

Механика (84.15.4):
  * Режим: автоопределение — Linux + /run/systemd/system + shutil.which
    ('systemctl') → «systemd»; иначе «dev» (Windows); переопределение env
    CONTROL_MODE (systemd|dev).
  * Дебаунс: ≥30с между ЛЮБЫМИ control-вызовами (in-memory) → 429
    (ControlDebouncedError).
  * Аудит: logger «control» (попадает в ring-buffer 84.11.1):
    [control] action=… by=<telegram_id> mode=…
  * Немедленный 202 → отложенное выполнение asyncio.sleep(2.0) (ответ
    успевает уйти); запрос НИКОГДА не ждёт выполнения команды.
  * systemd: отвязанный subprocess ['systemctl', action, 'admin_bot']
    (start_new_session=True, без ожидания). stop: ДО вызова создаётся
    флаг-файл .adminbot_keep_stopped (рабочая директория, вне git) —
    страховка от Restart=always-петли; restart/start — флаг удаляется.
  * dev: restart/stop = graceful exit через колбэк request_shutdown
    (инжектируется из bot.py — stop_event); start = 409
    (ControlStartUnavailable).
"""
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

control_logger = logging.getLogger("control")

DEBOUNCE_SECONDS = 30.0
EXEC_DELAY_SECONDS = 2.0
FLAG_FILE_NAME = ".adminbot_keep_stopped"
SYSTEMD_UNIT = "admin_bot"


class ControlError(Exception):
    status_code = 500


class ControlDebouncedError(ControlError):
    status_code = 429


class ControlStartUnavailableError(ControlError):
    status_code = 409


def detect_mode() -> str:
    """systemd | dev (84.15.4). CONTROL_MODE форсирует."""
    override = os.getenv("CONTROL_MODE", "").strip().lower()
    if override in ("systemd", "dev"):
        return override
    if sys.platform.startswith("linux") \
            and Path("/run/systemd/system").exists() \
            and shutil.which("systemctl"):
        return "systemd"
    return "dev"


class ControlService:
    """restart/stop/start: 202 + отложенное выполнение (84.15)."""

    def __init__(self, mode: str | None = None,
                 request_shutdown: Callable[[], None] | None = None,
                 unit: str = SYSTEMD_UNIT,
                 flag_file: str | None = None,
                 exec_delay: float = EXEC_DELAY_SECONDS,
                 debounce_seconds: float = DEBOUNCE_SECONDS) -> None:
        self.mode = mode or detect_mode()
        self._request_shutdown = request_shutdown
        self._unit = unit
        self._flag_file = Path(flag_file) if flag_file else (
            Path.cwd() / FLAG_FILE_NAME)
        self._exec_delay = exec_delay
        self._debounce_seconds = debounce_seconds
        self._last_call: float | None = None
        self._lock = asyncio.Lock()

    async def request(self, action: str, by: int) -> dict:
        """Входная точка роута: дебаунс → аудит → 202 → отложенный exec."""
        async with self._lock:
            now = time.monotonic()
            if self._last_call is not None \
                    and now - self._last_call < self._debounce_seconds:
                remaining = round(self._debounce_seconds
                                  - (now - self._last_call), 1)
                control_logger.warning(
                    "[control] debounced | action=%s by=%s remaining=%.1fs",
                    action, by, remaining)
                raise ControlDebouncedError(
                    f"слишком частые команды, подождите {remaining}с")
            self._last_call = now
        if action == "start" and self.mode == "dev":
            control_logger.info(
                "[control] start dev → 409 | by=%s mode=%s", by, self.mode)
            raise ControlStartUnavailableError(
                "start недоступен в dev-режиме")
        control_logger.info("[control] action=%s by=%s mode=%s",
                            action, by, self.mode)
        asyncio.create_task(self._execute_after(action, by))
        return {"action": action,
                "scheduled_in_seconds": self._exec_delay,
                "mode": self.mode}

    async def _execute_after(self, action: str, by: int) -> None:
        """Отложенное выполнение (ответ 202 успевает уйти)."""
        await asyncio.sleep(self._exec_delay)
        try:
            if self.mode == "systemd":
                self._run_systemd(action)
            else:
                self._dev_exit(action)
        except Exception:
            control_logger.exception(
                "[control] execute failed | action=%s by=%s mode=%s",
                action, by, self.mode)

    # ── systemd ────────────────────────────────────────────────────────────

    def _run_systemd(self, action: str) -> None:
        """Отвязанный subprocess systemctl (84.15.4). stop — сначала флаг-файл
        (страховка от Restart=always), restart/start — флаг удаляется."""
        if action == "stop":
            self.create_flag_file()
        elif action in ("restart", "start"):
            self.remove_flag_file()
        cmd = ["systemctl", action, self._unit]
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            control_logger.info("[control] spawned: %s", " ".join(cmd))
        except Exception:
            control_logger.exception("[control] subprocess failed: %s",
                                    " ".join(cmd))

    # ── dev-режим ──────────────────────────────────────────────────────────

    def _dev_exit(self, action: str) -> None:
        """restart/stop = graceful exit (84.15.4); start → 409 (выше)."""
        control_logger.warning(
            "[control] dev mode | action=%s → graceful exit "
            "(перезапустите python bot.py вручную)", action)
        if self._request_shutdown is not None:
            self._request_shutdown()

    # ── флаг-файл (84.15.4) ────────────────────────────────────────────────

    def create_flag_file(self) -> None:
        try:
            self._flag_file.write_text("1", encoding="utf-8")
            control_logger.info("[control] flag-file created: %s",
                                self._flag_file)
        except OSError:
            control_logger.warning(
                "[control] flag-file create failed: %s", self._flag_file,
                exc_info=True)

    def remove_flag_file(self) -> None:
        try:
            if self._flag_file.exists():
                self._flag_file.unlink()
                control_logger.info("[control] flag-file removed: %s",
                                    self._flag_file)
        except OSError:
            control_logger.warning(
                "[control] flag-file remove failed: %s", self._flag_file,
                exc_info=True)

    @staticmethod
    def flag_file_exists(flag_file: str | None = None) -> bool:
        """Проверка при старте бота (84.15.4): флаг есть → мгновенный exit 0."""
        path = Path(flag_file) if flag_file else (Path.cwd() / FLAG_FILE_NAME)
        return path.exists()
