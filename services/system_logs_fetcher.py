"""SELF-DIAG-01 (D1) — portable local log backend для «чекапа».

Заменяет каскад «Better Stack SQL API → shell-journalctl» (Epic 42/45)
единственным локальным путём, который построен по ФАКТИЧЕСКОЙ среде процесса:

1. ``detect_runtime()`` определяет собственный процесс и способ запуска:
   контейнер (маркер ``/run/systemd/container``, ``container=`` env,
   ``/.dockerenv``, ``/run/.containerenv``, k8s env, cgroup-маркеры),
   systemd (``INVOCATION_ID`` + unit из собственного ``/proc/self/cgroup``)
   либо standalone.
2. Для systemd журнал читается фиксированным argv через
   ``create_subprocess_exec`` (без shell), и ТОЛЬКО для этого экземпляра:
   матч ``_SYSTEMD_INVOCATION_ID=<id>``, а если его нет — ``--unit`` из
   собственного cgroup. Имя unit никогда не берётся из свободного текста;
   override принимается лишь если совпадает с живым cgroup-значением.
3. Контейнер/standalone читают собственный stdout (если это обычный файл)
   либо существующий in-process event ledger (``services.log_ring``).
4. Пустой журнал, журнал только с INFO и нечитаемый журнал — РАЗНЫЕ
   состояния (см. ``_ReadOutcome.state`` и провенанс-строку в тексте).
   Корректно прочитанный пустой журнал НЕ выдаётся за «сервис здоров».
5. Нет ни одного читаемого источника → ``CheckupLogsUnavailableException``
   (хендлер шлёт CHECKUP_DEAD_PHRASES), при недоступном основном источнике
   возвращается честная частичная диагностика из ledger.

Сетевых клиентов у чекапа больше нет: модуль не импортирует httpx и не
делает HTTP-запросов. Глобальный observability-ingest (отдельный модуль
отправки логов) не затронут.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Callable

from config.settings import settings
from services.log_ring import get_log_ring

logger = logging.getLogger(__name__)

# Потолки: окно журнала, число строк в отчёте, длина текста, длина события.
_MAX_LOG_LINES = 300
_MAX_LOG_SYMBOLS = 20000
_MAX_EVENT_MESSAGE_CHARS = 400
_JOURNAL_TIMEOUT = 15.0
_OWN_FILE_TAIL_BYTES = 256 * 1024
# Фильтр локального журнала (как раньше): только проблемные строки.
_LOCAL_LINE_MARKERS = ("error", "warning", "traceback")

_JOURNALCTL_BIN = "journalctl"
_CGROUP_PATH = "/proc/self/cgroup"
_STDOUT_FD_PATH = "/proc/self/fd/1"
_SYSTEMD_CONTAINER_FILE = "/run/systemd/container"

# Сентинел: `container_marker=None` = «маркеров нет» (тесты), а не «искать».
_UNSET = object()

# systemd unit: имя, полученное из cgroup — только такой безопасный вид.
_UNIT_RE = re.compile(r"[A-Za-z0-9_.@:\-]+\.(?:service|scope)")
_INVOCATION_RE = re.compile(r"[0-9a-f]{32}")
_CONTAINER_CGROUP_MARKERS = (
    "docker", "kubepods", "containerd", "lxc", "podman", "libpod",
)


class CheckupLogsUnavailableException(Exception):
    """Не прочитан ни один локальный источник логов (журнал + ledger)."""


@dataclass(frozen=True)
class RuntimeIdentity:
    """Как запущен ИМЕННО этот процесс (не «как обычно бывает на сервере»)."""

    kind: str                          # "systemd" | "container" | "standalone"
    pid: int
    unit: str | None = None            # из /proc/self/cgroup, не из текста
    invocation_id: str | None = None   # systemd INVOCATION_ID этого запуска
    cgroup: str | None = None
    container_marker: str | None = None


@dataclass
class _ReadOutcome:
    state: str                         # ok | empty | info_only | unreadable
    backend: str                       # systemd | stdout_file | ledger
    lines: list[str]
    read: int                          # строк в окне (до фильтра уровней)
    matched: int                       # строк после фильтра уровней
    unit: str | None = None
    invocation_id: str | None = None
    journal: str | None = None         # состояние основного журнала при деградации
    detail: str | None = None
    used_fallback: bool = False


# ── Определение среды процесса ──────────────────────────────────────────


def _read_text_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _path_exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except OSError:                     # pragma: no cover - защитный
        return False


def _detect_container_marker(environ: dict, cgroup: str | None) -> str | None:
    """Явные признаки контейнера; env/cgroup — не догадка по имени юнита."""
    systemd_container = (_read_text_file(_SYSTEMD_CONTAINER_FILE) or "").strip()
    if systemd_container:
        return f"systemd-container:{systemd_container}"
    env_container = str(environ.get("container") or "").strip()
    if env_container:
        return f"env:{env_container}"
    if str(environ.get("KUBERNETES_SERVICE_HOST") or "").strip():
        return "env:kubernetes"
    for path in ("/.dockerenv", "/run/.containerenv"):
        if _path_exists(path):
            return f"file:{path}"
    lowered = (cgroup or "").lower()
    for marker in _CONTAINER_CGROUP_MARKERS:
        if marker in lowered:
            return f"cgroup:{marker}"
    return None


def _unit_from_cgroup(cgroup: str | None) -> str | None:
    """Актуальный unit ИМЕННО нашего cgroup (а не историческое имя юнита)."""
    if not cgroup:
        return None
    found = _UNIT_RE.findall(cgroup)
    if not found:
        return None
    services = [item for item in found if item.endswith(".service")]
    return (services or found)[-1]


def detect_runtime(
    *,
    environ: dict | None = None,
    cgroup: str | None = None,
    container_marker: object = _UNSET,
) -> RuntimeIdentity:
    """Определить способ запуска собственного процесса.

    ``cgroup=None`` — прочитать ``/proc/self/cgroup``; ``""`` — считать, что
    файла нет (тесты/не-Linux). ``container_marker`` — принудительный маркер
    (``None`` = маркеров нет, тесты); по умолчанию ищется по реальным признакам.
    """
    env = os.environ if environ is None else environ
    cgroup_text = _read_text_file(_CGROUP_PATH) if cgroup is None else cgroup
    if container_marker is _UNSET:
        marker = _detect_container_marker(env, cgroup_text)
    else:
        marker = container_marker
    unit = _unit_from_cgroup(cgroup_text)
    raw_invocation = str(env.get("INVOCATION_ID") or "").strip()
    invocation = (raw_invocation
                  if _INVOCATION_RE.fullmatch(raw_invocation) else None)
    pid = os.getpid()
    if marker:
        return RuntimeIdentity(
            kind="container", pid=pid, unit=unit,
            invocation_id=invocation, cgroup=cgroup_text,
            container_marker=marker,
        )
    if invocation or unit:
        return RuntimeIdentity(
            kind="systemd", pid=pid, unit=unit,
            invocation_id=invocation, cgroup=cgroup_text,
        )
    return RuntimeIdentity(kind="standalone", pid=pid, cgroup=cgroup_text)


# ── Чтение логов ────────────────────────────────────────────────────────


class CheckupLogsFetcher:
    """Локальный источник логов для чекапа (интерфейс ``fetch/close`` сохранён).

    ``unit_override`` — необязательный пин systemd-юнита: принимается только
    при совпадении с живым cgroup-значением (иначе WARNING и фактический unit),
    поэтому переименованный/устаревший unit не даёт ложное «ошибок нет».
    """

    def __init__(
        self,
        unit_override: str = settings.CHECKUP_LOG_UNIT,
        window_lines: int = settings.CHECKUP_LOG_WINDOW_LINES,
        timeout: float = _JOURNAL_TIMEOUT,
        identity_probe: Callable[[], RuntimeIdentity] | None = None,
        journal_runner: Callable[[list[str]], "asyncio.Future"] | None = None,
        ledger_reader: Callable[[int], list[dict]] | None = None,
        stdout_tail_reader: Callable[[int], list[str] | None] | None = None,
    ) -> None:
        self._unit_override = str(unit_override or "").strip()
        self._window = max(10, int(window_lines or _MAX_LOG_LINES))
        self._timeout = float(timeout)
        self._identity_probe = identity_probe or detect_runtime
        self._journal_runner = journal_runner
        self._ledger_reader = ledger_reader or self._default_ledger_reader
        self._stdout_tail_reader = stdout_tail_reader or self._default_stdout_tail

    # — совместимость (D1-09): закрывать больше нечего —
    async def close(self) -> None:
        return None

    def describe_source(self) -> str:
        """Человекочитаемый фактический источник (для стартового лога/отчёта)."""
        identity = self._identity_probe()
        if identity.invocation_id:
            return (f"systemd invocation={identity.invocation_id} "
                    f"unit={identity.unit or '-'} pid={identity.pid}")
        if identity.unit:
            return f"systemd unit={identity.unit} pid={identity.pid}"
        if identity.kind == "container":
            return (f"container ({identity.container_marker}) "
                    f"pid={identity.pid} -> own stream/ledger")
        return f"standalone pid={identity.pid} -> own stream/ledger"

    async def fetch(self) -> tuple[str, bool]:
        """(logs_text, used_fallback).

        ``used_fallback`` = основной для этой среды источник не прочитан и
        отчёт построен на in-process ledger (хендлер шлёт fallback-фразу).
        Полная невозможность прочитать хоть что-то → исключение.
        """
        identity = self._identity_probe()
        journal = await self._try_journal(identity)
        if journal is not None and journal.state in ("ok", "empty", "info_only"):
            return self._render(journal), False
        stream = self._read_own_stream(
            identity,
            journal_state=journal.state if journal is not None
            else "not_available",
            journal_detail=journal.detail if journal is not None else None,
        )
        if journal is not None:
            stream.used_fallback = True
        return self._render(stream), stream.used_fallback

    # — systemd journal (фиксированный argv, без shell) —

    def _effective_unit(self, identity: RuntimeIdentity) -> str | None:
        detected = identity.unit
        if not self._unit_override:
            return detected
        if not _UNIT_RE.fullmatch(self._unit_override):
            logger.warning(
                "[checkup fetcher] unit override rejected (bad format) | value=%r",
                self._unit_override,
            )
            return detected
        if detected is None:
            logger.warning(
                "[checkup fetcher] unit override rejected (no live unit to "
                "verify) | value=%s", self._unit_override,
            )
            return None
        if self._unit_override != detected:
            logger.warning(
                "[checkup fetcher] unit override rejected (live cgroup differs) "
                "| override=%s | actual=%s", self._unit_override, detected,
            )
            return detected
        return detected

    def _journal_argv(
        self, identity: RuntimeIdentity, unit: str | None,
    ) -> list[str] | None:
        argv = [
            _JOURNALCTL_BIN, "--no-pager", "--quiet",
            "--output=short-iso", f"--lines={self._window}",
        ]
        if identity.invocation_id:
            argv.append(
                f"_SYSTEMD_INVOCATION_ID={identity.invocation_id}")
        elif unit:
            argv.extend(["--unit", unit])
        else:
            return None
        return argv

    async def _run_journal(self, argv: list[str]) -> tuple[int, str, str]:
        if self._journal_runner is not None:
            rc, out, err = await self._journal_runner(argv)
            return int(rc), out, err
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            raw_out, raw_err = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError, OSError):
                proc.kill()
            with suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            raise
        return (
            int(proc.returncode or 0),
            (raw_out or b"").decode("utf-8", errors="replace"),
            (raw_err or b"").decode("utf-8", errors="replace"),
        )

    async def _try_journal(
        self, identity: RuntimeIdentity,
    ) -> _ReadOutcome | None:
        unit = self._effective_unit(identity)
        argv = self._journal_argv(identity, unit)
        if argv is None:
            return None                      # у процесса нет своего журнала
        try:
            rc, out, err = await self._run_journal(argv)
        except (OSError, asyncio.TimeoutError, NotImplementedError) as exc:
            logger.warning(
                "[checkup fetcher] journal spawn/run failed | error=%s", exc)
            return _ReadOutcome(
                state="unreadable", backend="systemd", lines=[], read=0,
                matched=0, unit=unit, invocation_id=identity.invocation_id,
                detail=f"spawn:{type(exc).__name__}", used_fallback=True,
            )
        if rc != 0:
            tail = err.strip()[-200:]
            logger.warning(
                "[checkup fetcher] journal unavailable | rc=%s | stderr_tail=%r",
                rc, tail,
            )
            reason = ("permission" if "permission" in tail.lower()
                      or "not seeing messages" in tail.lower()
                      else "rc")
            return _ReadOutcome(
                state="unreadable", backend="systemd", lines=[], read=0,
                matched=0, unit=unit, invocation_id=identity.invocation_id,
                detail=reason, used_fallback=True,
            )
        window_lines = out.splitlines()
        matched = [
            line for line in window_lines
            if any(marker in line.lower() for marker in _LOCAL_LINE_MARKERS)
        ][-_MAX_LOG_LINES:]
        if not window_lines:
            state = "empty"
        elif not matched:
            state = "info_only"
        else:
            state = "ok"
        logger.info(
            "[checkup fetcher] journal read | state=%s | window=%d | matched=%d",
            state, len(window_lines), len(matched),
        )
        return _ReadOutcome(
            state=state, backend="systemd", lines=matched,
            read=len(window_lines), matched=len(matched), unit=unit,
            invocation_id=identity.invocation_id,
        )

    # — собственный stdout / in-process ledger —

    def _default_stdout_tail(self, limit: int) -> list[str] | None:
        try:
            target = os.readlink(_STDOUT_FD_PATH)
        except OSError:
            return None
        if not target or target.startswith(("pipe:", "socket:", "/dev/")):
            return None
        try:
            size = os.path.getsize(target)
            with open(target, "rb") as fh:
                fh.seek(max(0, size - _OWN_FILE_TAIL_BYTES))
                data = fh.read()
        except OSError:
            return None
        text = data.decode("utf-8", errors="replace")
        return text.splitlines()[-limit:]

    @staticmethod
    def _default_ledger_reader(limit: int) -> list[dict]:
        return get_log_ring().get_entries(level="ALL", limit=limit)

    @staticmethod
    def _ledger_line(entry: dict) -> str:
        ts = str(entry.get("ts") or "-")
        level = str(entry.get("level") or "-")
        message = " ".join(str(entry.get("message") or "").split())
        exc_text = entry.get("exc_text")
        if exc_text:
            first = str(exc_text).strip().splitlines()[-1:] or [""]
            message = f"{message} | {first[0]}".strip(" |")
        return f"{ts} - {level} - {message}"[:_MAX_EVENT_MESSAGE_CHARS + 60]

    def _read_own_stream(
        self,
        identity: RuntimeIdentity,
        *,
        journal_state: str,
        journal_detail: str | None,
    ) -> _ReadOutcome:
        tail = self._stdout_tail_reader(self._window)
        if tail is not None:
            matched = [
                line for line in tail
                if any(marker in line.lower() for marker in _LOCAL_LINE_MARKERS)
            ][-_MAX_LOG_LINES:]
            state = ("ok" if matched
                     else ("info_only" if tail else "empty"))
            return _ReadOutcome(
                state=state, backend="stdout_file", lines=matched,
                read=len(tail), matched=len(matched),
                journal=journal_state if journal_state != "not_available"
                else None, detail=journal_detail,
            )
        try:
            entries = self._ledger_reader(self._window)
        except Exception as exc:
            logger.error("[checkup fetcher] ledger unreadable | error=%s", exc)
            raise CheckupLogsUnavailableException(
                f"ledger unavailable: {exc}") from exc
        entries = list(entries or [])
        matched_entries = [
            entry for entry in entries
            if str(entry.get("level") or "").upper() in (
                "WARNING", "ERROR", "CRITICAL")
            or entry.get("exc_text")
        ]
        # ledger отдаёт новые→старые; в отчёт — хронологически.
        lines = [self._ledger_line(entry)
                 for entry in reversed(matched_entries)][-_MAX_LOG_LINES:]
        state = ("ok" if lines
                 else ("info_only" if entries else "empty"))
        logger.info(
            "[checkup fetcher] ledger read | state=%s | window=%d | matched=%d",
            state, len(entries), len(lines),
        )
        return _ReadOutcome(
            state=state, backend="ledger", lines=lines,
            read=len(entries), matched=len(lines),
            journal=journal_state if journal_state != "not_available" else None,
            detail=journal_detail,
        )

    # — рендер: провенанс + честные пометки + строки логов —

    _STATE_NOTES = {
        "empty": ("в окне журнала нет ни одной строки: пустой корректно "
                  "прочитанный журнал НЕ доказывает, что сервис здоров"),
        "info_only": ("в окне нет строк ERROR/WARNING (только INFO и ниже): "
                      "это не доказывает отсутствие сбоев"),
    }

    def _render(self, outcome: _ReadOutcome) -> str:
        parts = [f"backend={outcome.backend}"]
        if outcome.unit:
            parts.append(f"unit={outcome.unit}")
        if outcome.invocation_id:
            parts.append(f"invocation={outcome.invocation_id}")
        if outcome.journal:
            journal = outcome.journal
            if outcome.detail:
                journal = f"{journal}({outcome.detail})"
            parts.append(f"journal={journal}")
        parts.append(f"window={self._window}")
        parts.append(f"read={outcome.read}")
        parts.append(f"matched={outcome.matched}")
        parts.append(f"state={outcome.state}")
        header = "[log-source] " + " ".join(parts)
        blocks = [header]
        if outcome.journal:
            detail = f" ({outcome.detail})" if outcome.detail else ""
            blocks.append(
                "[log-source-note] основной журнал недоступен"
                f"{detail}; ниже — события, прочитанные из собственного "
                "потока/ledger этого процесса")
        note = self._STATE_NOTES.get(outcome.state)
        if note:
            blocks.append("[log-source-note] " + note)
        body = "\n".join(outcome.lines)
        if body:
            blocks.append(body)
        return "\n".join(blocks)[:_MAX_LOG_SYMBOLS]
