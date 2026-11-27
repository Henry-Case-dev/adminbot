"""F-STALL-01: bounded event-loop lag watchdog (наблюдаемость, без продукта).

Инцидент 2026-11-27 (951.675 s непрерывной синхронной CPU-работы в потоке
event loop) не оставил точного кадра: стек в момент подвисания никто не снимал.
Этот модуль — ограниченный сторож: event loop раз в ``tick_s`` секунд обновляет
heartbeat (`loop.call_later`, без отдельной задачи), а отдельный daemon-поток
сравнивает heartbeat с ``time.monotonic()`` и при превышении порога снимает
**один** снимок всех потоков (``faulthandler.dump_traceback(all_threads=True)``)
и пишет **одну** структурированную WARNING-запись в лог приложения.

Почему дамп делает отдельный поток, а не сам loop: callback внутри loop
исполняется только ПОСЛЕ разблокировки, когда кадр виновника уже ушёл со стека.
Поток-наблюдатель снимает стек, пока loop ещё заблокирован, поэтому в снимке
остаётся именно блокирующий кадр (``file:line``) — исходная цель F-STALL-01.

Границы поведения (обязательны):

* ничего не отменяет, не прерывает и не завершает — только наблюдает;
* снимок попадает в лог (сообщение WARNING), а не в отдельный файл на диске;
* антифлуд: повторные срабатывания не чаще ``min_interval_s``;
* ``LOOP_LAG_WARN_S=0`` — сторож не стартует;
  пустое/невалидное/отрицательное/NaN значение — заводской порог ``5.0`` s;
* fail-open: любая ошибка сторожа логируется один раз и не ломает старт.

Настраивается только через окружение (``config/settings.py`` не меняется):

* ``LOOP_LAG_WARN_S`` — порог задержки, секунды (default ``5.0``);
* ``LOOP_LAG_MIN_INTERVAL_S`` — антифлуд, секунды (default ``60.0``).
"""

from __future__ import annotations

import asyncio
import faulthandler
import logging
import math
import os
import sys
import tempfile
import threading
import time
import traceback
from typing import List, Optional

logger = logging.getLogger(__name__)

ENV_WARN_S = "LOOP_LAG_WARN_S"
ENV_MIN_INTERVAL_S = "LOOP_LAG_MIN_INTERVAL_S"

#: Заводской порог задержки цикла (инцидент F-STALL-01: план «lag > 5 s»).
DEFAULT_WARN_S = 5.0
#: Заводской антифлуд: не чаще одного дампа в минуту (план «не чаще 1/60 s»).
DEFAULT_MIN_INTERVAL_S = 60.0
#: Период проверки. Один call_later-таймер, без отдельной задачи.
DEFAULT_TICK_S = 1.0
#: Жёсткий предел на текст снимка в одной лог-записи (защита от мегабайтных
#: стеков при глубокой рекурсии). Обрезается только хвост, начало сохраняется.
SNAPSHOT_MAX_CHARS = 262_144


def _env_float(name: str) -> Optional[float]:
    """Вернуть конечное float из env или None (пусто/мусор/NaN/inf)."""
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _resolve_warn_s() -> float:
    value = _env_float(ENV_WARN_S)
    # Отрицательный порог не имеет смысла и не является штатным off (это 0).
    if value is None or value < 0:
        return DEFAULT_WARN_S
    return value


def _resolve_min_interval_s() -> float:
    value = _env_float(ENV_MIN_INTERVAL_S)
    if value is None or value < 0:
        return DEFAULT_MIN_INTERVAL_S
    return value


def _manual_thread_snapshot() -> str:
    """Fallback-снимок всех потоков, если faulthandler-путь недоступен."""
    frames = sys._current_frames()
    chunks: List[str] = []
    for thread in threading.enumerate():
        chunks.append(
            f"\nThread {thread.name} (ident={thread.ident}, "
            f"daemon={thread.daemon}):\n")
        frame = frames.get(thread.ident)
        if frame is None:
            chunks.append("  <no frame>\n")
            continue
        chunks.extend(traceback.format_stack(frame))
    return "".join(chunks)


def _snapshot_buffer():
    """Временный буфер для ``faulthandler`` (только в RAM, без файла-артефакта).

    ``faulthandler.dump_traceback`` пишет только в объект с реальным
    ``fileno()``. Анонимный pipe здесь небезопасен: dump удерживает GIL, а
    читатель не успевает вычищать pipe → взаимная блокировка на большом
    снимке (проверено на многопоточном pytest-процессе). Поэтому на Linux
    используем ``memfd_create`` — файловый дескриптор в памяти ядра; на
    Windows (dev/тесты) — ``TemporaryFile`` (delete-on-close, наружу не
    попадает и не является лог-артефактом).
    """
    if hasattr(os, "memfd_create"):
        flags = getattr(os, "MFD_CLOEXEC", 0)
        try:
            fd = os.memfd_create("loop-lag-snapshot", flags)
        except OSError:
            fd = os.memfd_create("loop-lag-snapshot", 0)
        return os.fdopen(fd, "w+b")
    return tempfile.TemporaryFile(mode="w+b")


def _faulthandler_snapshot() -> str:
    """Снять ``faulthandler.dump_traceback(all_threads=True)`` в буфер."""
    with _snapshot_buffer() as buffer:
        faulthandler.dump_traceback(file=buffer, all_threads=True)
        buffer.flush()
        buffer.seek(0)
        data = buffer.read()
    if isinstance(data, str):
        return data
    return data.decode("utf-8", "replace") if data else ""


def dump_all_thread_stacks() -> str:
    """Текстовый снимок стеков всех потоков процесса; никогда не бросает."""
    try:
        snapshot = _faulthandler_snapshot()
        if snapshot.strip():
            return snapshot
    except Exception:  # noqa: BLE001 — fallback ниже, наблюдение не роняем
        pass
    try:
        return _manual_thread_snapshot()
    except Exception:  # noqa: BLE001 — снимок необязателен для WARNING
        return ""


class LoopLagWatchdog:
    """Замер задержки event loop по heartbeat и дамп стеков при лаге.

    ``loop.call_later`` обновляет ``_last_beat``; поток-наблюдатель замечает,
    что heartbeat «застыл», и снимает стеки, пока виновник ещё в кадре.
    """

    def __init__(
        self,
        threshold_s: float = DEFAULT_WARN_S,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        tick_s: float = DEFAULT_TICK_S,
        *,
        enabled: Optional[bool] = None,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        self.threshold_s = float(threshold_s)
        self.min_interval_s = max(0.0, float(min_interval_s))
        self.tick_s = max(0.001, float(tick_s))
        # «Флаг» выключен, если порог неположителен: env-ноль — штатный off.
        self.enabled = (self.threshold_s > 0) if enabled is None else bool(enabled)
        self._logger = logger_ or logger
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._handle: Optional[asyncio.TimerHandle] = None
        self._monitor: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_beat = 0.0
        self._last_report: Optional[float] = None
        self._error_logged = False
        # Наблюдаемые счётчики (для эксплуатации и тестов).
        self.ticks = 0
        self.triggers = 0
        self.suppressed = 0
        self.last_lag_s: float = 0.0

    @classmethod
    def from_env(cls) -> "LoopLagWatchdog":
        warn_s = _resolve_warn_s()
        return cls(
            threshold_s=warn_s,
            min_interval_s=_resolve_min_interval_s(),
            tick_s=DEFAULT_TICK_S,
            enabled=warn_s > 0,
        )

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Запустить сторож в текущем loop. Fail-open: False, не исключение."""
        if not self.enabled or self._running:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._log_error_once("start: no running event loop")
            return False
        try:
            self._loop = loop
            self._last_beat = time.monotonic()
            self._last_report = None
            self._stop_event.clear()
            self._running = True
            self._schedule(loop)
            monitor = threading.Thread(
                target=self._monitor_loop,
                name="loop-lag-watchdog",
                daemon=True,
            )
            self._monitor = monitor
            monitor.start()
        except Exception:  # noqa: BLE001 — старт бота не роняем
            self._running = False
            self._log_error_once("start failed")
            return False
        return True

    def stop(self) -> None:
        """Снять таймер и наблюдателя; безопасно вызывать повторно."""
        self._running = False
        self._stop_event.set()
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.cancel()
            except Exception:  # noqa: BLE001 — закрытие loop уже идёт
                pass
        monitor, self._monitor = self._monitor, None
        if monitor is not None and monitor is not threading.current_thread():
            try:
                monitor.join(timeout=max(1.0, self.tick_s * 2))
            except Exception:  # noqa: BLE001
                pass
        self._loop = None

    async def shutdown(self) -> None:
        """Async-обёртка для `on_shutdown` (единый `_safe`-контракт bot.py)."""
        self.stop()

    # ── внутреннее ──────────────────────────────────────────────────────────

    def _schedule(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self._running:
            return
        self._handle = loop.call_later(self.tick_s, self._tick)

    def _tick(self) -> None:
        """Heartbeat из самого loop: доказательство, что loop исполняет работу."""
        if not self._running:
            return
        try:
            loop = self._loop
            if loop is None or loop.is_closed():
                self._running = False
                return
            self._last_beat = time.monotonic()
            self.ticks += 1
        except Exception:  # noqa: BLE001 — наблюдение не влияет на продукт
            self._log_error_once("tick failed")
        finally:
            try:
                if self._running and self._loop is not None:
                    self._schedule(self._loop)
            except Exception:  # noqa: BLE001
                self._log_error_once("reschedule failed")

    def _monitor_loop(self) -> None:
        """Наблюдатель вне loop: ловит застывший heartbeat и снимает стеки."""
        while not self._stop_event.wait(self.tick_s):
            if not self._running:
                return
            try:
                now = time.monotonic()
                lag = max(0.0, now - self._last_beat)
                self.last_lag_s = lag
                if self.enabled and lag >= self.threshold_s:
                    self._report(lag, now)
            except Exception:  # noqa: BLE001 — наблюдатель не влияет на продукт
                self._log_error_once("monitor failed")

    def _report(self, lag_s: float, now: float) -> None:
        if (self._last_report is not None
                and now - self._last_report < self.min_interval_s):
            self.suppressed += 1
            return
        self._last_report = now
        self.triggers += 1
        lag_ms = int(round(lag_s * 1000.0))
        threshold_ms = int(round(self.threshold_s * 1000.0))
        snapshot = dump_all_thread_stacks()
        if len(snapshot) > SNAPSHOT_MAX_CHARS:
            snapshot = snapshot[:SNAPSHOT_MAX_CHARS] + "\n<truncated>\n"
        try:
            self._logger.warning(
                "loop_lag | lag_ms=%d threshold_ms=%d snapshot_begin\n"
                "%s\nsnapshot_end",
                lag_ms,
                threshold_ms,
                snapshot,
                extra={
                    "event": "loop_lag",
                    "loop_lag_ms": lag_ms,
                    "loop_lag_threshold_ms": threshold_ms,
                    "loop_lag_snapshot_chars": len(snapshot),
                },
            )
        except Exception:  # noqa: BLE001 — лог-сбой не должен ломать loop
            self._log_error_once("report logging failed")

    def _log_error_once(self, where: str) -> None:
        if self._error_logged:
            return
        self._error_logged = True
        try:
            self._logger.warning(
                "[loop_lag] watchdog %s — fail-open (наблюдение пропущено)",
                where, exc_info=True)
        except Exception:  # noqa: BLE001 — даже лог ошибки не роняет loop
            pass


def start_from_env() -> Optional[LoopLagWatchdog]:
    """Создать и запустить сторож из env; None — если выключен/не стартовал."""
    watchdog = LoopLagWatchdog.from_env()
    if not watchdog.enabled:
        return None
    if not watchdog.start():
        return None
    logger.info(
        "[loop_lag] watchdog started | warn_s=%.3f tick_s=%.3f "
        "min_interval_s=%.3f",
        watchdog.threshold_s, watchdog.tick_s, watchdog.min_interval_s)
    return watchdog
