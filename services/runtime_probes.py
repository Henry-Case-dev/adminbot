"""SELF-DIAG-01 D3 — typed read-only runtime probes.

Один расширяемый реестр ``DiagnosticProbe`` (ТЗ §5): процесс, CPU/память,
диски, FDs/сокеты, локальные логи, systemd/контейнер, планировщик, доставка
Telegram, STT/vision, LLM/инструменты, память, БД, конфигурация, деплой,
зависимости, сеть, инциденты. Новый сервис регистрирует свой probe через
``register_probe`` — центральный код править не нужно.

Инварианты:

* только чтение: никаких shell/SSH/SQL от модели, только существующие
  сервисы/файлы/README-источники; тяжёлые проверки — отдельные ``expensive``
  probes, которые сценарий по умолчанию не запускает;
* аргументы модели валидируются по закрытой схеме конкретного probe; ``unit``,
  ``path``, ``root``, ``sql``, ``chat_id`` и т.п. не принимаются ни одним
  probe (LLM не может подменить scope или чужой unit);
* измерения честные: ``declared`` ≠ ``configured`` ≠ ``probe_succeeded`` ≠
  ``healthy``; по одному замеру не вычисляются проценты CPU/IO; отсутствие
  ошибок не выдаётся за «здоров»;
* всё, что может содержать пользовательский текст/секрет, проходит
  существующий sanitizer и возвращается как ``stack_summary``/коды, а не
  сырыми логами.
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
import os
import re
import tempfile
import time
import urllib.parse
from typing import Any, Awaitable, Callable, Iterable

from config.settings import settings
from services import capability_registry
from services import evidence_bundle as bundle
from services import hot_config as hot
from services import log_ring
from services import mca_events
from services import mca_gates
from services import mca_incidents
from services import mca_watchdog
from services import memory_diagnostics
from services import memory_health
from services.system_logs_fetcher import (
    CheckupLogsFetcher,
    CheckupLogsUnavailableException,
    detect_runtime,
)

logger = logging.getLogger(__name__)

# ── Ограничения (engineering settings, не keyword-гейты) ───────────────────
#
# Значения читаются из окружения один раз на процесс (прецедент
# ``LOG_RING_MAX_ENTRIES``): бюджеты редактируются без правки кода и не
# зависят от текста запроса. Тесты инжектят свой ``ProbeLimits``.


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


@dataclasses.dataclass(frozen=True)
class ProbeLimits:
    """Бюджеты проб: быстрые по умолчанию, дорогие — только по запросу."""

    probe_timeout_seconds: float = 5.0
    expensive_timeout_seconds: float = 20.0
    max_rows: int = 200
    max_window_seconds: int = 86400
    default_window_seconds: int = 3600
    snapshot_ttl_seconds: float = 15.0
    identity_ttl_seconds: float = 60.0
    max_output_chars: int = 9000
    max_facts_chars: int = 3000
    stack_budget_chars: int = 2000
    disk_free_min_percent: float = 5.0
    memory_available_min_percent: float = 5.0
    expensive_enabled: bool = True

    @classmethod
    def from_env(cls) -> "ProbeLimits":
        return cls(
            probe_timeout_seconds=_env_float(
                "SELF_DIAG_PROBE_TIMEOUT_SECONDS", 5.0, 0.2),
            expensive_timeout_seconds=_env_float(
                "SELF_DIAG_PROBE_EXPENSIVE_TIMEOUT_SECONDS", 20.0, 1.0),
            max_rows=_env_int("SELF_DIAG_PROBE_MAX_ROWS", 200, 1),
            max_window_seconds=_env_int(
                "SELF_DIAG_PROBE_MAX_WINDOW_SECONDS", 86400, 60),
            default_window_seconds=_env_int(
                "SELF_DIAG_PROBE_DEFAULT_WINDOW_SECONDS", 3600, 60),
            snapshot_ttl_seconds=_env_float(
                "SELF_DIAG_PROBE_SNAPSHOT_TTL_SECONDS", 15.0, 0.0),
            identity_ttl_seconds=_env_float(
                "SELF_DIAG_PROBE_IDENTITY_TTL_SECONDS", 60.0, 0.0),
            max_output_chars=_env_int(
                "SELF_DIAG_PROBE_MAX_OUTPUT_CHARS", 9000, 800),
            max_facts_chars=_env_int(
                "SELF_DIAG_PROBE_MAX_FACTS_CHARS", 3000, 400),
            stack_budget_chars=_env_int(
                "SELF_DIAG_PROBE_STACK_BUDGET_CHARS", 2000, 300),
            disk_free_min_percent=_env_float(
                "SELF_DIAG_DISK_FREE_MIN_PERCENT", 5.0, 0.0),
            memory_available_min_percent=_env_float(
                "SELF_DIAG_MEMORY_AVAILABLE_MIN_PERCENT", 5.0, 0.0),
            expensive_enabled=bool(
                str(os.getenv("SELF_DIAG_PROBE_EXPENSIVE_ENABLED", "1"))
                .strip().lower() in ("1", "true", "yes", "on")),
        )


# ── Закрытые наборы ────────────────────────────────────────────────────────

AREAS: tuple[str, ...] = (
    "process", "resources", "disks", "fds_sockets", "logs", "service",
    "scheduler", "telegram", "media", "llm", "memory", "db", "config",
    "deploy", "dependencies", "network", "incidents",
)

READ_SCOPE_CURRENT_CHAT = "current_chat"
READ_SCOPE_INSTANCE = "instance"
READ_SCOPE_HOST = "host"
READ_SCOPE_REPO = "repo"
READ_SCOPES: tuple[str, ...] = (
    READ_SCOPE_CURRENT_CHAT, READ_SCOPE_INSTANCE, READ_SCOPE_HOST,
    READ_SCOPE_REPO,
)

#: Значения аргумента ``scope`` инструмента (закрытый набор, ТЗ §10).
REQUEST_SCOPES: tuple[str, ...] = ("current_chat", "host", "instance")

#: Ключи, которые не принимает НИ ОДИН probe даже если какой-то модуль
#: попытается объявить их в схеме: LLM не меняет unit/scope/пути/SQL.
DENIED_ARGUMENT_KEYS: frozenset[str] = frozenset({
    "command", "cmd", "shell", "sql", "query_sql", "path", "root", "unit",
    "unit_override", "chat_id", "user_id", "telegram_id", "host", "port",
    "url", "dsn", "token", "api_key", "env", "file", "filename",
})

#: Тип аргумента → проверка значения.
_ARG_TYPES: tuple[str, ...] = ("string", "integer", "boolean")

# ── Типы ──────────────────────────────────────────────────────────────────

ProbeHandler = Callable[["ProbeContext"], Any]
AsyncProbeHandler = Callable[["ProbeContext"], Awaitable[Any]]


@dataclasses.dataclass(frozen=True)
class ProbeSpec:
    """Контракт зарегистрированной операции (расширяемость без правок центра)."""

    probe_id: str
    area: str
    title: str
    description: str
    read_scope: str
    handler: ProbeHandler | AsyncProbeHandler | None = None
    args: dict | None = None
    requires: tuple[str, ...] = ()
    expensive: bool = False
    scenario: bool = False
    children: tuple[str, ...] = ()
    default_window_seconds: int = 0
    max_window_seconds: int = 0
    health_criterion: str = ""
    source_owner: str = "runtime"
    kind: str = ""

    def __post_init__(self) -> None:
        if self.area not in AREAS:
            raise ValueError(f"invalid probe area: {self.area!r}")
        prefix = f"{self.area}."
        if not str(self.probe_id).startswith(prefix):
            raise ValueError(
                f"probe id must start with {prefix!r}: {self.probe_id!r}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+",
                            str(self.probe_id)):
            raise ValueError(f"invalid probe id: {self.probe_id!r}")
        if self.read_scope not in READ_SCOPES:
            raise ValueError(f"invalid read_scope: {self.read_scope!r}")
        if self.scenario:
            if not self.children:
                raise ValueError("scenario probe requires children")
            if self.handler is not None:
                raise ValueError("scenario probe must not have a handler")
        elif self.handler is None:
            raise ValueError("probe requires a handler")
        for key, spec in (self.args or {}).items():
            if key in DENIED_ARGUMENT_KEYS:
                raise ValueError(f"argument {key!r} is forbidden")
            if not isinstance(spec, dict) or spec.get("type") not in _ARG_TYPES:
                raise ValueError(f"invalid arg spec for {key!r}")


@dataclasses.dataclass(frozen=True)
class ProbeObservation:
    """Результат одного probe: факты + честные состояния доступности."""

    status: str
    facts: dict
    source_id: str
    owner: str
    coverage: dict
    reason_code: str | None = None
    not_checked: tuple[str, ...] = ()
    healthy: bool | None = None
    verified: bool | None = None
    redaction: dict | None = None
    source_ref: dict | None = None
    next_offset: int | None = None

    def __post_init__(self) -> None:
        if self.status not in bundle.STATUSES:
            raise ValueError(f"invalid observation status: {self.status!r}")


@dataclasses.dataclass
class ProbeContext:
    """Всё, что нужно probe: зависимости, проверенные аргументы, scope."""

    deps: "ProbeDeps"
    limits: ProbeLimits
    chat_id: int | None
    scope: str
    request_id: str
    arguments: dict = dataclasses.field(default_factory=dict)
    time_window: tuple[int, int] | None = None
    cursor_offset: int = 0
    now: float = dataclasses.field(default_factory=time.time)

    def redact(self, text: str) -> tuple[str, dict]:
        return self.deps.redact(text)


@dataclasses.dataclass
class ProbeDeps:
    """Инъекция существующих источников (DI из bot/tests; без новых сторов)."""

    db: Any = None
    memory: Any = None
    logs_fetcher: Any = None
    status: Any = None
    identity_collector: Callable[..., dict] | None = None
    recent_commits_collector: Callable[..., dict] | None = None
    capability_view: Callable[..., Awaitable[list[dict]]] | None = None
    redactor: Callable[[str], tuple[str, dict]] | None = None
    process: Any = None
    clock: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    dns_resolver: Callable[[str], Awaitable[Any]] | None = None
    systemctl_runner: Callable[[str], Awaitable[dict]] | None = None
    log_ring_getter: Callable[[], Any] | None = None
    cpu_counters_reader: Callable[[], dict] | None = None
    repo_root: str | None = None

    def redact(self, text: str) -> tuple[str, dict]:
        if self.redactor is not None:
            return self.redactor(text)
        cleaned = log_ring.sanitize(str(text or ""))
        if cleaned == text:
            return cleaned, bundle.redaction(0, (), reason="no_secret_values")
        return cleaned, bundle.redaction(1, ("pattern",),
                                         reason="pattern_only")


# ── Реестр ────────────────────────────────────────────────────────────────

PROBE_REGISTRY: dict[str, ProbeSpec] = {}


def register_probe(spec: ProbeSpec, *, replace: bool = False) -> ProbeSpec:
    """Регистрация typed probe; подмодулям не нужен правка центрального кода."""
    if not isinstance(spec, ProbeSpec):
        raise TypeError("spec must be ProbeSpec")
    if spec.probe_id in PROBE_REGISTRY and not replace:
        raise ValueError(f"probe already registered: {spec.probe_id}")
    if spec.scenario:
        missing = [c for c in spec.children if c not in PROBE_REGISTRY]
        if missing and not replace:
            # Дети могут регистрироваться позже; проверяем при вызове.
            logger.debug("[self_diag] scenario children pending | %s",
                         missing)
    PROBE_REGISTRY[spec.probe_id] = spec
    return spec


def unregister_probe(probe_id: str) -> None:
    PROBE_REGISTRY.pop(str(probe_id), None)


def get_probe(probe_id: str) -> ProbeSpec | None:
    return PROBE_REGISTRY.get(str(probe_id or ""))


def list_probes(area: str = "") -> list[ProbeSpec]:
    items = list(PROBE_REGISTRY.values())
    if area:
        items = [p for p in items if p.area == area]
    return sorted(items, key=lambda p: p.probe_id)


def _required_sources(spec: ProbeSpec) -> list[str]:
    """Зависимости probe; для сценария — объединение зависимостей детей."""
    names = list(spec.requires)
    if spec.scenario:
        for child_id in spec.children:
            child = PROBE_REGISTRY.get(child_id)
            if child is not None:
                names.extend(child.requires)
    return sorted({str(name) for name in names if str(name or "")})


def _missing_dependencies(spec: ProbeSpec, deps: ProbeDeps) -> list[str]:
    missing: list[str] = []
    for name in _required_sources(spec):
        value = getattr(deps, name, None)
        if value is None:
            missing.append(name)
    return missing


def probe_catalog(*, deps: ProbeDeps | None = None,
                  area: str = "") -> dict:
    """Каталог зарегистрированных операций: advertised только реально
    зарегистрированные; ``configured`` — есть зависимости; ``ready`` не
    выставляется (ready требует успешного probe, а не декларации)."""
    deps = deps or ProbeDeps()
    entries = []
    for spec in list_probes(area):
        missing = _missing_dependencies(spec, deps)
        entry = {
            "probe": spec.probe_id,
            "area": spec.area,
            "title": spec.title,
            "description": spec.description,
            "read_scope": spec.read_scope,
            "declared": True,
            "configured": not missing,
            "arguments": {
                key: {k: v for k, v in spec_dict.items()}
                for key, spec_dict in (spec.args or {}).items()
            },
            "expensive": bool(spec.expensive),
            "scenario": bool(spec.scenario),
            "requires": _required_sources(spec),
            "health_criterion": spec.health_criterion,
        }
        if missing:
            entry["reason_code"] = "missing_dependency:" + ",".join(missing)
        if spec.children:
            entry["children"] = list(spec.children)
        entries.append(entry)
    return {
        "schema": "self-diag-01/d3-catalog-v1",
        "areas": list(AREAS),
        "probes": entries,
        "status": bundle.STATUS_OK if entries else bundle.STATUS_NOT_CHECKED,
    }


# ── Валидация аргументов/окна ─────────────────────────────────────────────

def validate_arguments(spec: ProbeSpec, raw: Any) -> tuple[dict, str]:
    """(clean_args, reason). Причина непустая — аргументы отклонены."""
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, "arguments_must_be_object"
    schema = spec.args or {}
    clean: dict = {}
    for key, value in raw.items():
        name = str(key)
        if name in DENIED_ARGUMENT_KEYS:
            return {}, "argument_not_allowed"
        if name not in schema:
            return {}, f"unknown_argument:{name[:40]}"
        arg = schema[name] or {}
        expected = arg.get("type")
        if expected == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return {}, f"invalid_type:{name}"
            minimum = int(arg.get("minimum", -10 ** 9))
            maximum = int(arg.get("maximum", 10 ** 9))
            if value < minimum or value > maximum:
                return {}, f"out_of_range:{name}"
        elif expected == "boolean":
            if not isinstance(value, bool):
                return {}, f"invalid_type:{name}"
        elif expected == "string":
            if not isinstance(value, str):
                return {}, f"invalid_type:{name}"
            limit = int(arg.get("max_chars", 200))
            if len(value) > limit:
                return {}, f"too_long:{name}"
            enum = arg.get("enum")
            if enum and value not in enum:
                return {}, f"invalid_value:{name}"
        clean[name] = value
    return clean, ""


def _parse_time_value(value: Any, *, now: float) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=datetime.timezone.utc).timestamp()
    return moment.timestamp()


def parse_time_window(raw: Any, *, limits: ProbeLimits, now: float,
                      default_seconds: int = 0) -> tuple[tuple[int, int] | None,
                                                          str]:
    """Валидированное окно (epoch-секунды). Кривые/чужие окна — отказ."""
    default = int(default_seconds or limits.default_window_seconds)
    max_window = int(limits.max_window_seconds)
    if raw is None or raw == {}:
        end = int(now)
        return (max(0, end - min(default, max_window)), end), ""
    if not isinstance(raw, dict):
        return None, "time_window_must_be_object"
    unknown = set(raw) - {"since", "until", "last_seconds"}
    if unknown:
        return None, "time_window_unknown_field"
    if "last_seconds" in raw:
        if set(raw) - {"last_seconds"}:
            return None, "time_window_ambiguous"
        try:
            seconds = int(raw["last_seconds"])
        except (TypeError, ValueError):
            return None, "invalid_time_window"
        if seconds < 1 or seconds > max_window:
            return None, "time_window_out_of_range"
        end = int(now)
        return (max(0, end - seconds), end), ""
    since = _parse_time_value(raw.get("since"), now=now) if "since" in raw \
        else None
    until = _parse_time_value(raw.get("until"), now=now) if "until" in raw \
        else None
    if since is None and until is None:
        return None, "invalid_time_window"
    end = int(until if until is not None else now)
    start = int(since if since is not None else end - default)
    if start < 0 or end < 0:
        return None, "invalid_time_window"
    if start > end:
        return None, "time_window_reversed"
    if end - start > max_window:
        return None, "time_window_too_wide"
    if end > int(now) + 300:
        return None, "time_window_in_future"
    return (start, end), ""


# ── Общие хелперы ─────────────────────────────────────────────────────────

def _psutil():
    import psutil as _psutil_mod
    return _psutil_mod


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_text_file(path: str, *, max_bytes: int = 65536) -> str | None:
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes)
        return data.decode("utf-8", "replace")
    except OSError:
        return None


def _runtime_identity() -> dict:
    try:
        identity = detect_runtime()
        return {
            "kind": identity.kind,
            "pid": identity.pid,
            "unit": identity.unit,
            "invocation_id": identity.invocation_id,
            "container_marker": identity.container_marker,
        }
    except Exception:
        return {"kind": "unknown", "pid": os.getpid()}


def runtime_identity() -> dict:
    """Публичная форма identity среды (для collector/bundle)."""
    return _runtime_identity()


def reset_observations() -> None:
    """Сброс process-local CPU-наблюдений (честный первый замер в тестах)."""
    _CPU_SAMPLE.clear()


def _source_coverage(parts: Iterable[str], *, complete: bool = True,
                     truncated: bool = False, why: str = "") -> dict:
    return bundle.coverage(parts, complete=complete, truncated=truncated,
                           why=why)


def _observation(kind: str, *, status: str, facts: dict, source_id: str,
                 owner: str = "runtime", parts: Iterable[str] = (),
                 complete: bool = True, truncated: bool = False,
                 why: str = "", reason_code: str | None = None,
                 not_checked: Iterable[str] = (), healthy: bool | None = None,
                 verified: bool | None = None,
                 redaction: dict | None = None,
                 source_ref: dict | None = None,
                 next_offset: int | None = None,
                 health_criterion: str = "") -> ProbeObservation:
    # ``health_criterion`` декларируется в ProbeSpec/каталоге; в наблюдении
    # оно не дублируется (healthy уже содержит результат критерия).
    del health_criterion
    return ProbeObservation(
        status=status, facts=facts, source_id=source_id, owner=owner,
        coverage=_source_coverage(parts or (kind,), complete=complete,
                                  truncated=truncated, why=why),
        reason_code=reason_code, not_checked=tuple(not_checked),
        healthy=healthy, verified=verified, redaction=redaction,
        source_ref=source_ref, next_offset=next_offset)


# ── process ───────────────────────────────────────────────────────────────

def _probe_process_self(ctx: ProbeContext) -> ProbeObservation:
    psutil = _psutil()
    proc = ctx.deps.process or psutil.Process(os.getpid())
    facts: dict = {"scope_kind": _runtime_identity().get("kind", "unknown")}
    try:
        with proc.oneshot():
            facts.update({
                "pid": proc.pid,
                "ppid": proc.ppid(),
                "name": str(proc.name())[:120],
                "exe": os.path.basename(str(proc.exe() or ""))[:120],
                "status": str(proc.status())[:40],
                "threads": proc.num_threads(),
                "create_time": round(float(proc.create_time()), 3),
                "uptime_seconds": max(
                    0, int(ctx.now - float(proc.create_time()))),
            })
            try:
                cmdline = proc.cmdline()
                # Только число аргументов и basename[0]: raw argv может
                # содержать токены/пароли (ТЗ §5).
                facts["argv_count"] = len(cmdline)
            except Exception:
                facts["argv_count"] = None
            fds = _safe_int(getattr(proc, "num_fds", lambda: None)())
            if fds is None:
                fds = _safe_int(getattr(proc, "num_handles", lambda: None)())
            facts["open_fds"] = fds
    except Exception as exc:
        return _observation(
            "process", status=bundle.STATUS_UNAVAILABLE, facts=facts,
            source_id=f"process:pid:{os.getpid()}", owner="runtime",
            reason_code="process_read_failed",
            not_checked=("process_details",))
    identity = _runtime_identity()
    facts.update({
        "runtime_kind": identity.get("kind"),
        "unit": identity.get("unit"),
        "invocation_id": identity.get("invocation_id"),
        "container_marker": identity.get("container_marker"),
    })
    fd_limit = None
    if os.name == "posix":
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            fd_limit = {"soft": int(soft), "hard": int(hard)}
        except Exception:
            fd_limit = None
    facts["fd_limit"] = fd_limit
    return _observation(
        "process", status=bundle.STATUS_OK, facts=facts,
        source_id=f"process:pid:{os.getpid()}",
        health_criterion="none",   # нет порога — healthy не выдумываем
        not_checked=("restarts", "exit_reason", "args_sanitized"))


# ── resources ─────────────────────────────────────────────────────────────

_CPU_SAMPLE: dict[str, tuple[float, dict]] = {}


def _read_cpu_counters() -> dict:
    """Накопительные CPU-счётчики (Linux /proc/stat, иначе psutil)."""
    text = _read_text_file("/proc/stat")
    if text:
        for line in text.splitlines():
            if line.startswith("cpu "):
                parts = [p for p in line.split()[1:] if p]
                keys = ("user", "nice", "system", "idle", "iowait", "irq",
                        "softirq", "steal", "guest", "guest_nice")
                counters = {}
                for key, value in zip(keys, parts):
                    try:
                        counters[key] = int(value)
                    except ValueError:
                        counters[key] = 0
                if counters:
                    return counters
    psutil = _psutil()
    times = psutil.cpu_times()
    counters = {}
    for key in ("user", "nice", "system", "idle", "iowait", "irq",
                "softirq", "steal"):
        value = getattr(times, key, None)
        if value is not None:
            counters[key] = int(value * 1000)
    return counters


def _cpu_delta(previous: dict, current: dict) -> dict:
    keys = set(previous) & set(current)
    deltas = {key: current[key] - previous[key] for key in keys}
    total = sum(max(0, value) for value in deltas.values())
    result = {"counters_delta": deltas, "total_delta": total}
    if total > 0:
        result["percent"] = {
            key: round(max(0, value) * 100.0 / total, 1)
            for key, value in deltas.items()
        }
    return result


def _probe_resources_cpu(ctx: ProbeContext) -> ProbeObservation:
    counters = ((ctx.deps.cpu_counters_reader or _read_cpu_counters)())
    allowed = False
    previous = _CPU_SAMPLE.get("self")
    delta = None
    if previous is not None:
        interval = ctx.deps.monotonic() - previous[0]
        if interval > 0:
            delta = _cpu_delta(previous[1], counters)
            delta["interval_seconds"] = round(interval, 3)
            delta["basis"] = "two_real_observations"
            allowed = delta.get("total_delta", 0) > 0
    _CPU_SAMPLE["self"] = (ctx.deps.monotonic(), counters)
    facts: dict = {
        "counters": counters,
        "derived": bool(allowed),
        "basis": ("two_real_observations" if allowed else "counters_only"),
        "cpu_count": os.cpu_count(),
    }
    if delta is not None and allowed:
        facts["delta"] = delta
    elif delta is not None:
        facts["delta"] = {"counters_delta": delta.get("counters_delta"),
                          "total_delta": delta.get("total_delta"),
                          "basis": "insufficient_delta"}
    try:
        loadavg = os.getloadavg()
        facts["loadavg"] = {"1m": round(loadavg[0], 2),
                            "5m": round(loadavg[1], 2),
                            "15m": round(loadavg[2], 2),
                            "cores": os.cpu_count() or 1,
                            "basis": "system_aggregate"}
    except (AttributeError, OSError):
        facts["loadavg"] = None
    cgroup_max = _read_text_file("/sys/fs/cgroup/cpu.max")
    if cgroup_max:
        facts["cgroup_cpu_max"] = cgroup_max.strip()[:120]
    return _observation(
        "resources", status=bundle.STATUS_OK, facts=facts,
        source_id="resources:cpu", health_criterion="none",
        not_checked=(() if allowed else ("cpu_utilization_delta",)))


def _meminfo() -> dict:
    text = _read_text_file("/proc/meminfo")
    values: dict[str, int] = {}
    if not text:
        return values
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0]) * 1024
        except ValueError:
            continue
    return values


def _probe_resources_memory(ctx: ProbeContext) -> ProbeObservation:
    psutil = _psutil()
    facts: dict = {}
    try:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        facts.update({
            "total_bytes": int(vm.total),
            "available_bytes": int(getattr(vm, "available", vm.free)),
            "used_bytes": int(vm.used),
            "percent_used": round(float(vm.percent), 1),
            "swap_total_bytes": int(swap.total),
            "swap_used_bytes": int(swap.used),
        })
    except Exception:
        return _observation(
            "resources", status=bundle.STATUS_UNAVAILABLE, facts=facts,
            source_id="resources:memory", reason_code="memory_read_failed")
    total = max(1, int(facts["total_bytes"]))
    available_pct = round(facts["available_bytes"] * 100.0 / total, 1)
    facts["available_percent"] = available_pct
    try:
        cgroup_limit = _read_text_file("/sys/fs/cgroup/memory.max") \
            or _read_text_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        cgroup_current = _read_text_file(
            "/sys/fs/cgroup/memory.current") \
            or _read_text_file("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        if cgroup_limit:
            facts["cgroup_memory_limit"] = cgroup_limit.strip()[:40]
        if cgroup_current:
            facts["cgroup_memory_current"] = cgroup_current.strip()[:40]
    except Exception:
        pass
    psi = _read_text_file("/proc/pressure/memory")
    if psi:
        facts["psi_memory"] = psi.strip()[:300]
    vmstat = _read_text_file("/proc/vmstat")
    if vmstat:
        for line in vmstat.splitlines():
            if line.startswith("oom_kill "):
                facts["oom_kill_total"] = _safe_int(line.split()[1])
    facts["scope_kind"] = _runtime_identity().get("kind", "unknown")
    healthy = available_pct >= float(
        ctx.limits.memory_available_min_percent)
    return _observation(
        "resources", status=bundle.STATUS_OK, facts=facts,
        source_id="resources:memory",
        health_criterion=("available_percent>="
                          f"{ctx.limits.memory_available_min_percent}"),
        healthy=healthy,
        reason_code=None if healthy else "low_available_memory")


def _probe_resources_pressure(ctx: ProbeContext) -> ProbeObservation:
    facts: dict = {}
    parts: list[str] = []
    for name in ("cpu", "memory", "io"):
        text = _read_text_file(f"/proc/pressure/{name}")
        if text:
            facts[name] = text.strip()[:400]
            parts.append(name)
    if not facts:
        return _observation(
            "resources", status=bundle.STATUS_UNSUPPORTED, facts={},
            source_id="resources:pressure", reason_code="psi_not_available",
            not_checked=("cpu", "memory", "io"))
    return _observation(
        "resources", status=bundle.STATUS_OK, facts=facts,
        source_id="resources:pressure", parts=parts,
        health_criterion="none")


# ── disks ─────────────────────────────────────────────────────────────────

def _disk_targets(ctx: ProbeContext) -> dict[str, str]:
    targets: dict[str, str] = {"cwd": os.getcwd()}
    if os.name == "posix":
        targets["root"] = "/"
    else:
        targets["root"] = os.path.abspath(os.sep)
    tmp = tempfile.gettempdir()
    if tmp:
        targets["tmp"] = tmp
    db_path = getattr(ctx.deps.db, "db_path", None)
    if db_path is None:
        db_path = getattr(settings, "DB_PATH", "")
    if db_path and str(db_path) != ":memory:":
        targets["db"] = os.path.dirname(os.path.abspath(str(db_path))) or "."
    return {k: v for k, v in targets.items() if v}


def _probe_disks_usage(ctx: ProbeContext) -> ProbeObservation:
    psutil = _psutil()
    selected = str(ctx.arguments.get("mount") or "").strip()
    targets = _disk_targets(ctx)
    if selected:
        if selected not in targets:
            return _observation(
                "disks", status=bundle.STATUS_UNSUPPORTED, facts={},
                source_id="disks:usage", reason_code="unknown_mount",
                not_checked=tuple(sorted(targets)))
        targets = {selected: targets[selected]}
    facts: dict = {"mounts": {}}
    parts: list[str] = []
    failures = 0
    min_free = float(ctx.limits.disk_free_min_percent)
    healthy = True
    for name, path in targets.items():
        entry: dict = {"path_kind": name}
        try:
            usage = psutil.disk_usage(path)
            free_pct = round(float(usage.free) * 100.0 /
                             max(1, int(usage.total)), 1)
            entry.update({
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
                "free_percent": free_pct,
                "read_only": None,
                "inodes": None,
            })
            if free_pct < min_free:
                healthy = False
            if os.name == "posix":
                try:
                    stat = os.statvfs(path)
                    entry["inodes"] = {
                        "total": int(stat.f_files),
                        "free": int(stat.f_ffree),
                    }
                except OSError:
                    entry["inodes"] = None
        except Exception:
            entry["status"] = bundle.STATUS_UNAVAILABLE
            failures += 1
            healthy = None
        facts["mounts"][name] = entry
        parts.append(name)
    db_path = getattr(ctx.deps.db, "db_path", None)
    if db_path and str(db_path) != ":memory:":
        try:
            wal_path = str(db_path) + "-wal"
            facts["wal_bytes"] = (os.path.getsize(wal_path)
                                  if os.path.isfile(wal_path) else 0)
        except OSError:
            facts["wal_bytes"] = None
    if failures and not any("free_percent" in v
                            for v in facts["mounts"].values()):
        status = bundle.STATUS_UNAVAILABLE
    elif failures:
        status = bundle.STATUS_DEGRADED
    else:
        status = bundle.STATUS_OK
    if status != bundle.STATUS_OK:
        healthy = None if healthy is True else healthy
    return _observation(
        "disks", status=status, facts=facts, source_id="disks:usage",
        parts=parts, complete=not failures,
        why=("mount_read_failed" if failures else ""),
        health_criterion=f"free_percent>={min_free}",
        healthy=healthy,
        reason_code=(None if healthy else "disk_space_low"
                     if healthy is False else "disk_read_partial"),
        not_checked=("device_io", "read_write_latency"))


# ── fds_sockets ───────────────────────────────────────────────────────────

def _probe_fds_process(ctx: ProbeContext) -> ProbeObservation:
    psutil = _psutil()
    proc = ctx.deps.process or psutil.Process(os.getpid())
    facts: dict = {}
    try:
        with proc.oneshot():
            fds = _safe_int(getattr(proc, "num_fds", lambda: None)())
            if fds is None:
                fds = _safe_int(getattr(proc, "num_handles", lambda: None)())
            facts["open_fds"] = fds
    except Exception:
        facts["open_fds"] = None
    if os.name == "posix":
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            facts["fd_limit"] = {"soft": int(soft), "hard": int(hard)}
        except Exception:
            facts["fd_limit"] = None
    states: dict[str, int] = {}
    listening = 0
    connections_available = True
    try:
        for conn in proc.net_connections(kind="inet"):
            state = str(getattr(conn, "status", "") or "unknown")
            states[state] = states.get(state, 0) + 1
            if state.upper() == "LISTEN":
                listening += 1
        facts["connections_by_state"] = states
        facts["listening_sockets_own_process"] = listening
    except Exception:
        connections_available = False
        facts["connections_by_state"] = None
        facts["listening_sockets_own_process"] = None
    return _observation(
        "fds_sockets", status=bundle.STATUS_OK, facts=facts,
        source_id=f"fds:pid:{proc.pid}",
        health_criterion="none",
        not_checked=(() if connections_available else ("connections",))
        + ("dns_failures", "tcp_errors", "remote_payloads"))


# ── logs ──────────────────────────────────────────────────────────────────

_ERROR_MARKER_RE = re.compile(r"\b(?:ERROR|CRITICAL|Traceback)\b")


def _ring_snapshot() -> dict:
    try:
        ring = log_ring.get_log_ring()
        return {
            "levels": dict(ring.level_counts()),
            "errors_total": int(ring.get_errors_total()),
        }
    except Exception:
        return {"levels": {}, "errors_total": None}


async def _probe_logs_window(ctx: ProbeContext) -> ProbeObservation:
    fetcher = ctx.deps.logs_fetcher
    if fetcher is None:
        return _observation(
            "logs", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="logs:local", reason_code="no_log_backend",
            not_checked=("journal_window",))
    started = ctx.deps.monotonic()
    try:
        text, used_fallback = await fetcher.fetch()
    except CheckupLogsUnavailableException:
        return _observation(
            "logs", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="logs:local", reason_code="logs_unavailable",
            not_checked=("journal_window",))
    except Exception:
        return _observation(
            "logs", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="logs:local", reason_code="logs_read_failed",
            not_checked=("journal_window",))
    text = str(text or "")
    lines = [line for line in text.splitlines() if line.strip()]
    markers = len(_ERROR_MARKER_RE.findall(text))
    facts = {
        "backend": _fetcher_source(fetcher),
        "window_lines": len(lines),
        "used_fallback": bool(used_fallback),
        "error_marker_count": markers,
        "error_marker_basis": "line_markers",
        "empty_window": len(lines) == 0,
        "ring": _ring_snapshot(),
        "read_ms": int((ctx.deps.monotonic() - started) * 1000),
    }
    # Пустой корректно прочитанный журнал ≠ «сервис здоров» (ТЗ §6.1).
    healthy = None
    if facts["empty_window"]:
        reason = "empty_log_window"
    elif markers:
        reason = "error_markers_observed"
    else:
        reason = None
    return _observation(
        "logs", status=bundle.STATUS_OK, facts=facts,
        source_id="logs:local", complete=not used_fallback,
        truncated=bool(used_fallback),
        why=("read_own_stream" if used_fallback else ""),
        health_criterion="none", healthy=healthy, reason_code=reason,
        not_checked=("journal_contents",))


def _fetcher_source(fetcher) -> str:
    try:
        describe = getattr(fetcher, "describe_source", None)
        if callable(describe):
            return str(describe())[:200]
    except Exception:
        pass
    return type(fetcher).__name__


async def _probe_logs_errors(ctx: ProbeContext) -> ProbeObservation:
    try:
        ring = (ctx.deps.log_ring_getter or log_ring.get_log_ring)()
    except Exception:
        return _observation(
            "logs", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="logs:errors", reason_code="log_ring_unavailable")
    limit = min(int(ctx.arguments.get("limit") or 20),
                int(ctx.limits.max_rows))
    include_stack = bool(ctx.arguments.get("include_stack", True))
    try:
        entries = ring.get_entries(level="ERROR", limit=limit)
    except Exception:
        entries = []
    stack = None
    stack_redaction = None
    if include_stack:
        for entry in entries:
            exc_text = str(entry.get("exc_text") or "")
            if not exc_text:
                continue
            cleaned, report = ctx.redact(exc_text)
            stack = bundle.stack_summary(
                cleaned, budget_chars=ctx.limits.stack_budget_chars,
                cursor=str(ctx.arguments.get("cursor") or ""))
            stack_redaction = report
            break
    facts = {
        "error_entries": len(entries),
        "latest_ts": (entries[0].get("ts") if entries else None),
        "levels": _ring_snapshot(),
        "stack": stack,
    }
    return _observation(
        "logs", status=bundle.STATUS_OK if entries else bundle.STATUS_OK,
        facts=facts, source_id="logs:errors",
        health_criterion="none",
        reason_code=("errors_observed" if entries else "no_error_entries"),
        redaction=stack_redaction,
        not_checked=(() if entries else ("stack_summary",)))


_EVENT_FIELDS = (
    "ts", "event_name", "outcome", "level", "component", "stage", "status",
    "reason_code", "duration_ms", "trace_id", "job_id", "pipeline_run_id",
    "chat_id",
)


async def _probe_logs_events(ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    if db is None:
        return _observation(
            "logs", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="logs:events", reason_code="no_db",
            not_checked=("event_ledger",))
    limit = min(int(ctx.arguments.get("limit") or 100),
                int(ctx.limits.max_rows))
    correlation_id = str(ctx.arguments.get("correlation_id") or "").strip()
    window = ctx.time_window
    offset = max(0, int(ctx.cursor_offset or 0))
    if correlation_id:
        rows = await _query(db, trace_id=correlation_id,
                            limit=min(1000, limit + offset + 1), offset=0)
    else:
        rows = await _query(db, limit=min(1000, limit), offset=offset)
    if rows is None:
        return _observation(
            "logs", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="logs:events", reason_code="event_store_unavailable",
            not_checked=("event_ledger",))
    current_chat = ctx.chat_id
    visible: list[dict] = []
    foreign = 0
    for row in rows:
        row_chat = row.get("chat_id")
        if row_chat is not None and row_chat != current_chat:
            foreign += 1
            continue
        ts = _safe_int(row.get("ts"))
        if window and ts is not None and not (window[0] <= ts <= window[1]):
            continue
        visible.append({key: row.get(key) for key in _EVENT_FIELDS})
    stage_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    durations: list[int] = []
    correlated: list[dict] = []
    for row in visible:
        stage = str(row.get("stage") or "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        code = str(row.get("reason_code") or "")
        if code:
            reason_counts[code] = reason_counts.get(code, 0) + 1
        duration = _safe_int(row.get("duration_ms"))
        if duration is not None:
            durations.append(duration)
        if correlation_id and (code or str(row.get("status") or "")
                              in ("failed", "timeout")):
            correlated.append({"stage": stage, "reason_code": code or None,
                               "status": row.get("status"),
                               "duration_ms": duration})
    durations.sort()
    facts = {
        "returned": len(visible),
        "foreign_scope_excluded": foreign,
        "stage_counts": stage_counts,
        "reason_counts": reason_counts,
        "last_error": next(
            ({"stage": r.get("stage"), "reason_code": r.get("reason_code")}
             for r in visible if r.get("level") == "ERROR"), None),
        "latency_ms": {
            "p50": _percentile(durations, 0.5),
            "p95": _percentile(durations, 0.95),
            "max": durations[-1] if durations else None,
        },
        "correlation_id": correlation_id or None,
        "correlated_failures": correlated[:20],
        "window": (list(window) if window else None),
    }
    capped = offset + limit if not correlation_id else 0
    has_more = (not correlation_id and len(rows) >= limit)
    return _observation(
        "logs", status=bundle.STATUS_OK, facts=facts,
        source_id="logs:events", complete=(foreign == 0),
        why=("foreign_scope_rows_excluded" if foreign else ""),
        health_criterion="none",
        not_checked=(("event_payloads",) + ("foreign_chat_rows",)
                     if foreign else ("event_payloads",)),
        next_offset=(capped if has_more else None))


async def _query(db, *, trace_id=None, limit=100, offset=0):
    try:
        return await mca_events.query_events(
            db, trace_id=trace_id, limit=limit, offset=offset)
    except Exception:
        return None


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    index = int(round((len(values) - 1) * float(quantile)))
    return values[max(0, min(len(values) - 1, index))]


# ── service (systemd/container) ───────────────────────────────────────────

async def _default_systemctl_show(unit: str) -> dict:
    properties = ("ActiveState", "SubState", "NRestarts", "Result",
                  "ExecMainStartTimestamp", "InvocationID", "ExecMainPID")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "show", unit,
            "--property=" + ",".join(properties), "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        stdout, _stderr = await asyncio.wait_for(proc.communicate(),
                                                 timeout=2.0)
        text = stdout.decode("utf-8", "replace")
        parsed = {}
        for line in text.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                parsed[key.strip()] = value.strip()
        return parsed
    finally:
        if proc is not None and getattr(proc, "returncode", None) is None:
            try:
                proc.kill()
            except Exception:
                pass


_PROPS = ("ActiveState", "SubState", "NRestarts", "Result",
          "ExecMainStartTimestamp", "InvocationID", "ExecMainPID")


async def _probe_service_runtime(ctx: ProbeContext) -> ProbeObservation:
    identity = _runtime_identity()
    facts = dict(identity)
    if identity.get("kind") != "systemd":
        return _observation(
            "service", status=bundle.STATUS_UNSUPPORTED, facts=facts,
            source_id="service:runtime",
            reason_code=f"not_systemd:{identity.get('kind')}",
            health_criterion="none",
            not_checked=("systemd_state", "restarts", "last_exit"))
    unit = identity.get("unit") or ""
    if not unit:
        return _observation(
            "service", status=bundle.STATUS_UNAVAILABLE, facts=facts,
            source_id="service:runtime", reason_code="unit_not_detected",
            not_checked=("systemd_state",))
    runner = ctx.deps.systemctl_runner or _default_systemctl_show
    try:
        props = await asyncio.wait_for(runner(unit), timeout=3.0)
    except Exception:
        return _observation(
            "service", status=bundle.STATUS_UNAVAILABLE, facts=facts,
            source_id=f"service:unit:{unit}", reason_code="systemctl_failed",
            not_checked=("systemd_state",))
    facts["systemd"] = {key: props.get(key) for key in _PROPS
                        if key in props}
    active = str(facts["systemd"].get("ActiveState") or "")
    return _observation(
        "service",
        status=bundle.STATUS_OK if active == "active" else bundle.STATUS_DEGRADED,
        facts=facts, source_id=f"service:unit:{unit}",
        health_criterion="ActiveState==active",
        healthy=(active == "active") if active else None,
        reason_code=None if active == "active" else "service_not_active")


# ── scheduler ─────────────────────────────────────────────────────────────

async def _probe_scheduler_jobs(ctx: ProbeContext) -> ProbeObservation:
    from services.task_supervisor import TaskJobStore, get_task_supervisor
    facts: dict = {}
    try:
        supervisor = get_task_supervisor()
        facts.update({
            "registry_size": int(supervisor.registry_size()),
            "running": int(supervisor.running_count()),
            "active_tasks": [
                {"owner": rec.owner, "kind": rec.kind, "status": rec.status}
                for rec in supervisor.active()[:20]
            ],
        })
    except Exception:
        facts.update({"registry_size": None, "running": None,
                      "active_tasks": []})
    db = ctx.deps.db
    if db is None:
        facts.update({"job_store": None})
        return _observation(
            "scheduler", status=bundle.STATUS_NOT_CONFIGURED, facts=facts,
            source_id="scheduler:jobs", reason_code="no_db",
            health_criterion="none",
            not_checked=("job_store", "stale_jobs", "progress_stalled"))
    store = TaskJobStore(db)
    try:
        active = await store.active()
        overdue = await store.overdue()
        depth = await store.depth()
        stale = await mca_watchdog.stale_jobs(db)
        stalled = await mca_watchdog.progress_stalled_jobs(db)
    except Exception:
        return _observation(
            "scheduler", status=bundle.STATUS_UNAVAILABLE, facts=facts,
            source_id="scheduler:jobs", reason_code="job_store_read_failed",
            not_checked=("job_store",))
    retry_due = 0
    now = int(ctx.now)
    next_run = []
    for row in active:
        retry_at = _safe_int(row.get("next_retry_at"))
        if retry_at is not None:
            if retry_at <= now:
                retry_due += 1
            next_run.append({"job_id": row.get("job_id"),
                             "owner": row.get("owner"),
                             "kind": row.get("kind"),
                             "next_retry_at": retry_at})
    facts.update({
        "job_store": {
            "active": len(active),
            "queued_depth": int(depth),
            "overdue": len(overdue),
            "overdue_jobs": [
                {"job_id": r.get("job_id"), "owner": r.get("owner"),
                 "kind": r.get("kind"),
                 "deadline_at": r.get("deadline_at")}
                for r in overdue[:20]
            ],
            "retry_due": retry_due,
            "next_run": next_run[:20],
        },
        "stale_jobs": len(stale),
        "progress_stalled": len(stalled),
    })
    healthy = (len(overdue) == 0 and len(stale) == 0
               and len(stalled) == 0)
    return _observation(
        "scheduler", status=bundle.STATUS_OK, facts=facts,
        source_id="scheduler:jobs",
        health_criterion="no_overdue_stale_or_stalled",
        healthy=healthy,
        reason_code=None if healthy else "jobs_not_healthy",
        not_checked=("schedule_calendar",))


# ── telegram delivery ─────────────────────────────────────────────────────

async def _probe_telegram_delivery_async(
        ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    if db is None:
        return _observation(
            "telegram", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="telegram:delivery", reason_code="no_db",
            not_checked=("chat_output_ledger",))
    if ctx.chat_id is None:
        return _observation(
            "telegram", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="telegram:delivery", reason_code="no_chat_scope",
            not_checked=("chat_output_ledger",))
    from services import bot_output_ledger
    window = ctx.time_window or (0, int(ctx.now))
    limit = min(int(ctx.arguments.get("limit") or 100),
                int(ctx.limits.max_rows))
    try:
        rows = await bot_output_ledger.list_bot_output_history(
            db, int(ctx.chat_id), since_ts=window[0], until_ts=window[1],
            limit=limit)
    except Exception:
        rows = None
    if rows is None:
        return _observation(
            "telegram", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="telegram:delivery", reason_code="ledger_read_failed",
            not_checked=("chat_output_ledger",))
    media_only = sum(1 for row in rows if row.get("media_only"))
    undated = sum(1 for row in rows if not row.get("time_known", True))
    last = rows[-1] if rows else None
    facts = {
        "delivered": len(rows),
        "media_only": media_only,
        "undated": undated,
        "last_delivered_at": (last.get("sent_at") if last else None),
        "window": list(window),
    }
    global_counts = {}
    try:
        metrics = await mca_events.metrics(db)
        delivery = (metrics.get("metrics") or {}).get("delivery") or {}
        if delivery.get("available"):
            global_counts = {
                key: value for key, value in delivery.items()
                if key != "available"
                and isinstance(value, (int, float, bool))
            }
    except Exception:
        global_counts = {}
    facts["global_delivery_metrics"] = global_counts or None
    return _observation(
        "telegram", status=bundle.STATUS_OK, facts=facts,
        source_id=f"telegram:chat:{ctx.chat_id}",
        health_criterion="none",
        source_ref=bundle.source_ref(
            store="telegram", entity_type="message",
            entity_id=str(last.get("tg_message_id")) if last
            and last.get("tg_message_id") is not None else f"chat:{ctx.chat_id}",
            chat_id=int(ctx.chat_id),
            tg_message_id=(last.get("tg_message_id") if last
                           and isinstance(last.get("tg_message_id"), int)
                           else None)),
        not_checked=("delivery_errors_per_chat", "rate_limit_per_chat"))


# ── media (STT/vision) ────────────────────────────────────────────────────

async def _probe_media_stt(ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    if db is None:
        return _observation(
            "media", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="media:stt", reason_code="no_db",
            not_checked=("voice_queue",))
    if ctx.chat_id is None:
        return _observation(
            "media", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="media:stt", reason_code="no_chat_scope",
            not_checked=("voice_queue",))
    reader = getattr(db, "get_voice_window", None)
    if reader is None:
        return _observation(
            "media", status=bundle.STATUS_UNSUPPORTED, facts={},
            source_id="media:stt", reason_code="voice_reader_absent",
            not_checked=("voice_queue",))
    window = ctx.time_window or (0, int(ctx.now))
    limit = min(int(ctx.arguments.get("limit") or 120),
                int(ctx.limits.max_rows))
    try:
        rows = await reader(int(ctx.chat_id), window[0], limit)
    except Exception:
        return _observation(
            "media", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="media:stt", reason_code="voice_read_failed",
            not_checked=("voice_queue",))
    statuses: dict[str, int] = {}
    last_success = None
    last_error = None
    for row in rows or ():
        row = dict(row)
        is_voice = (str(row.get("media_type") or "") == "voice"
                    or bool(row.get("transcript_status")))
        if not is_voice:
            continue
        status = str(row.get("transcript_status") or "pending")
        statuses[status] = statuses.get(status, 0) + 1
        if status in ("ready", "ok", "completed"):
            stamp = row.get("transcript_updated_at") or row.get("timestamp")
            if stamp is not None and (last_success is None
                                      or int(stamp) > int(last_success)):
                last_success = int(stamp)
        if status in ("failed", "error"):
            last_error = {
                "reason_code": str(row.get("transcript_reason") or "")[:120]
                or None,
                "at": row.get("transcript_updated_at"),
                "tg_message_id": row.get("tg_message_id"),
            }
    failed = sum(count for key, count in statuses.items()
                 if key in ("failed", "error"))
    pending = statuses.get("pending", 0)
    facts = {
        "window": list(window),
        "statuses": statuses,
        "failed": failed,
        "pending": pending,
        "last_success_at": last_success,
        "last_error": last_error,
        "rows_scanned": len(rows or ()),
    }
    healthy = False if failed else None
    return _observation(
        "media",
        status=bundle.STATUS_DEGRADED if failed else bundle.STATUS_OK,
        facts=facts, source_id=f"media:stt:chat:{ctx.chat_id}",
        health_criterion="no_failed_transcripts",
        healthy=healthy,
        reason_code=("transcript_failures" if failed else
                     "transcripts_pending" if pending else None),
        source_ref=bundle.source_ref(
            store="sqlite", entity_type="message",
            entity_id=f"chat:{ctx.chat_id}", chat_id=int(ctx.chat_id)),
        not_checked=("provider_latency", "album_cohesion"))


# ── llm / telemetry ───────────────────────────────────────────────────────

async def _probe_llm_telemetry(ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    if db is None:
        return _observation(
            "llm", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="llm:telemetry", reason_code="no_db",
            not_checked=("provider_counters",))
    try:
        metrics = await mca_events.metrics(db)
    except Exception:
        return _observation(
            "llm", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="llm:telemetry", reason_code="metrics_unavailable",
            not_checked=("provider_counters",))
    groups = metrics.get("metrics") or {}
    facts = {
        "available": bool(metrics.get("available")),
        "events_total": metrics.get("events_total"),
        "errors_total": metrics.get("errors_total"),
        "degraded_share": metrics.get("degraded_share"),
        "groups": {
            name: {k: v for k, v in (group or {}).items()
                   if isinstance(v, (int, float, bool))}
            for name, group in groups.items()
            if name in ("providers", "cost", "tasks", "cache", "lock",
                        "degradations")
        },
    }
    return _observation(
        "llm",
        status=(bundle.STATUS_OK if metrics.get("available")
                else bundle.STATUS_DEGRADED),
        facts=facts, source_id="llm:telemetry",
        health_criterion="none",
        reason_code=(None if metrics.get("available")
                     else "telemetry_store_unavailable"),
        not_checked=("live_provider_probe", "prompt_bodies", "tool_offer_counts"))


# ── dependencies (providers/capabilities) ─────────────────────────────────

_CAPABILITY_STATUS_MAP = {
    capability_registry.STATUS_READY: bundle.STATUS_OK,
    capability_registry.STATUS_NOT_CONFIGURED: bundle.STATUS_NOT_CONFIGURED,
    capability_registry.STATUS_DISABLED: bundle.STATUS_NOT_CONFIGURED,
    capability_registry.STATUS_TEMPORARILY_UNAVAILABLE: bundle.STATUS_DEGRADED,
    capability_registry.STATUS_QUOTA_EXHAUSTED: bundle.STATUS_DEGRADED,
    capability_registry.STATUS_UNSUPPORTED: bundle.STATUS_UNSUPPORTED,
    capability_registry.STATUS_UNKNOWN: bundle.STATUS_UNKNOWN,
}


async def _probe_dependencies_providers(
        ctx: ProbeContext) -> ProbeObservation:
    view = ctx.deps.capability_view or capability_registry.capability_view
    try:
        states = await view(ctx.chat_id)
    except Exception:
        return _observation(
            "dependencies", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="dependencies:providers",
            reason_code="capability_view_failed",
            not_checked=("provider_states",))
    items = []
    mapped: list[str] = []
    any_measured = False
    any_failed = False
    for state in states or ():
        status_raw = str(state.get("status") or "unknown")
        mapped_status = _CAPABILITY_STATUS_MAP.get(status_raw,
                                                   bundle.STATUS_UNKNOWN)
        last_result = str(state.get("last_result") or "unknown")
        measured = last_result != "unknown"
        any_measured = any_measured or measured
        any_failed = any_failed or last_result == "failed"
        mapped.append(mapped_status)
        items.append({
            "capability": state.get("capability_id"),
            "tool": state.get("tool") or None,
            "status": mapped_status,
            "capability_status": status_raw,
            "reason_code": state.get("reason_code") or None,
            "declared": bool(state.get("declared")),
            "configured": bool(state.get("tryable")),
            "probe_succeeded": measured,
            "healthy": (True if last_result == "success" else
                        False if last_result == "failed" else None),
            "last_result": last_result,
            "last_result_code": state.get("last_result_code") or None,
            "checked_at": state.get("checked_at"),
        })
    overall = bundle.aggregate_status(mapped) if mapped else bundle.STATUS_UNKNOWN
    return _observation(
        "dependencies", status=overall,
        facts={"capabilities": items},
        source_id="dependencies:providers",
        health_criterion="last_result_success",
        healthy=(None if not any_measured else not any_failed),
        reason_code=(None if not any_failed else "provider_last_result_failed"),
        not_checked=("fresh_network_probe",))


# ── memory ────────────────────────────────────────────────────────────────

async def _probe_memory_health(ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    if db is None:
        return _observation(
            "memory", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="memory:health", reason_code="no_db",
            not_checked=("memory_metrics",))
    snapshot = await memory_health.collect_snapshot(db, ctx.deps.memory)
    facts = {"snapshot": snapshot}
    diagnostics = {}
    try:
        diagnostics = await memory_diagnostics.memory_health_diagnostics(
            db, chat_id=ctx.chat_id,
            vector_runtime=bool(getattr(ctx.deps.memory, "vec_available",
                                        False)))
        facts["diagnostics"] = diagnostics
    except Exception:
        facts["diagnostics"] = None
    status = bundle.STATUS_OK if snapshot.get("available") else \
        bundle.STATUS_DEGRADED
    if diagnostics and diagnostics.get("status") == "load_failed":
        status = bundle.STATUS_DEGRADED
    return _observation(
        "memory", status=status, facts=facts,
        source_id="memory:health",
        health_criterion="none",
        reason_code=(None if snapshot.get("available")
                     else str(snapshot.get("reason") or "memory_metrics_failed")),
        source_ref=bundle.source_ref(
            store="sqlite", entity_type="graph_fact",
            entity_id="memory:health", chat_id=ctx.chat_id,
            resolution="unknown"),
        not_checked=("retrieval_quality",))


# ── db ────────────────────────────────────────────────────────────────────

async def _sqlite_scalar(db, sql: str, params: tuple = ()):
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return row


async def _probe_db_health(ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    if db is None:
        return _observation(
            "db", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="db:health", reason_code="no_db",
            not_checked=("sqlite",))
    facts: dict = {}
    parts: list[str] = []
    try:
        await _sqlite_scalar(db, "SELECT 1")
        parts.append("sqlite_select")
        facts["sqlite"] = {"connected": True}
        for name, sql in (
                ("user_version", "PRAGMA user_version"),
                ("page_count", "PRAGMA page_count"),
                ("page_size", "PRAGMA page_size"),
                ("freelist_count", "PRAGMA freelist_count"),
                ("journal_mode", "PRAGMA journal_mode")):
            try:
                row = await _sqlite_scalar(db, sql)
                facts["sqlite"][name] = (list(row)[0] if row is not None
                                         else None)
            except Exception:
                facts["sqlite"][name] = None
        db_path = getattr(db, "db_path", None)
        if db_path and str(db_path) != ":memory:":
            facts["sqlite"]["db_bytes"] = (
                os.path.getsize(db_path) if os.path.exists(db_path) else None)
            wal_path = str(db_path) + "-wal"
            facts["sqlite"]["wal_bytes"] = (
                os.path.getsize(wal_path) if os.path.exists(wal_path) else 0)
    except Exception:
        return _observation(
            "db", status=bundle.STATUS_UNAVAILABLE, facts=facts,
            source_id="db:health", reason_code="sqlite_unavailable",
            health_criterion="sqlite_select_ok", healthy=False,
            not_checked=("postgres",))
    pg_configured = None
    try:
        cache = hot.get_config_cache()
        pg = getattr(cache, "pg", None) if cache is not None else None
        pg_configured = bool(pg is not None and
                             getattr(pg, "pool", None) is not None)
    except Exception:
        pg_configured = None
    facts["postgres"] = {"configured": pg_configured, "checked": False}
    return _observation(
        "db", status=bundle.STATUS_OK, facts=facts, source_id="db:health",
        parts=parts, health_criterion="sqlite_select_ok", healthy=True,
        reason_code=None,
        source_ref=bundle.source_ref(
            store="sqlite", entity_type="unknown",
            entity_id="db:health", resolution="unknown"),
        not_checked=("postgres_live", "integrity_check"))


async def _probe_db_integrity(ctx: ProbeContext) -> ProbeObservation:
    """Дорогая проверка по требованию: read-only ``PRAGMA quick_check``."""
    db = ctx.deps.db
    if db is None:
        return _observation(
            "db", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="db:integrity", reason_code="no_db",
            not_checked=("integrity",))
    try:
        row = await _sqlite_scalar(db, "PRAGMA quick_check")
        result = str(list(row)[0]) if row is not None else ""
    except Exception:
        return _observation(
            "db", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="db:integrity", reason_code="integrity_check_failed",
            not_checked=("integrity",))
    ok = result.lower() == "ok"
    return _observation(
        "db", status=bundle.STATUS_OK if ok else bundle.STATUS_DEGRADED,
        facts={"quick_check": result[:200]},
        source_id="db:integrity",
        health_criterion="quick_check==ok", healthy=ok,
        reason_code=None if ok else "integrity_issues")


# ── config ────────────────────────────────────────────────────────────────

#: Закрытый набор несекретных ключей, влияющих на диагностику/модули.
_CONFIG_KEYS: tuple[str, ...] = (
    "flags.checkup_enabled",
    "limits.checkup_max_symbols",
    "limits.checkup_max_input_symbols",
    "flags.checkup_memory_metrics_enabled",
    "flags.factcheck_enabled",
    "temporal.tool_enabled",
    "flags.image_generation_module_enabled",
    "flags.lore_compiler_enabled",
    "flags.graph_rag_enabled",
    "memory.dream_enabled",
    "flags.self_diag_repo_origin",
)


def _normalize_repo_origin_value(value) -> str | None:
    """Существующая D4-нормализация: owner/name без userinfo/scheme/host."""
    try:
        from services.source_reader import normalize_repo_origin
        return normalize_repo_origin(value)
    except Exception:
        return None


def _probe_config_effective(ctx: ProbeContext) -> ProbeObservation:
    cache = None
    try:
        cache = hot.get_config_cache()
    except Exception:
        cache = None
    loaded_at = None
    try:
        loaded_at = cache.loaded_at() if cache is not None else None
    except Exception:
        loaded_at = None
    items = []
    for key in _CONFIG_KEYS:
        source = "code"
        value = None
        updated_at = None
        invalid_reason = None
        try:
            if cache is not None:
                sentinel = object()
                raw = cache.get(key, sentinel)
                if raw is not sentinel and raw is not None:
                    source = "pg"
                    value = raw
                try:
                    updated_at = cache.get_updated_at(key)
                except Exception:
                    updated_at = None
            if value is None:
                value = hot.get(key, None)
                source = "code" if value is not None else "default"
        except Exception:
            source = "unknown"
            value = None
        if key == "flags.self_diag_repo_origin":
            # B1 (SELF-DIAG-01 D3 security): значение — repo identity, а не
            # произвольный URL. Даже non-secret ключ мог быть сохранён с
            # userinfo/token; наружу отдаём ТОЛЬКО owner/name через
            # существующую D4-нормализацию, raw URL не покидает probe.
            raw_value = value
            normalized = _normalize_repo_origin_value(raw_value)
            if normalized is not None:
                value = normalized
            elif str(raw_value or "").strip():
                value = None
                invalid_reason = "invalid_repo_origin"
            else:
                value = None
        items.append({
            "key": key,
            "effective": value if isinstance(
                value, (bool, int, float, str)) else (
                    None if value is None else str(value)),
            "source": source,
            "updated_at": updated_at,
            "applied_at": loaded_at,
            "pending_restart": False,   # hot-ключи применяются без рестарта
            **({"reason_code": invalid_reason} if invalid_reason else {}),
        })
    return _observation(
        "config", status=bundle.STATUS_OK, facts={"settings": items},
        source_id="config:effective", health_criterion="none",
        not_checked=("secret_values", "non_diagnostic_keys"))


# ── deploy ────────────────────────────────────────────────────────────────

def _default_repo_root(deps: ProbeDeps) -> str | None:
    if deps.repo_root:
        return deps.repo_root
    configured = str(getattr(settings, "SELF_DIAG_LOCAL_REPO_ROOT", "")
                     or "").strip()
    if configured:
        return configured
    try:
        return os.getcwd()
    except OSError:
        return None


def default_repo_root(deps: ProbeDeps) -> str | None:
    """Публичный доступ к тому же root-выбору (collector identity snapshot)."""
    return _default_repo_root(deps)


_IDENTITY_STATUS_MAP = {
    "verified_deployed": bundle.STATUS_OK,
    "local_unverified": bundle.STATUS_OK,
    "unavailable": bundle.STATUS_UNAVAILABLE,
    "permission_denied": bundle.STATUS_PERMISSION_DENIED,
    "path_denied": bundle.STATUS_PERMISSION_DENIED,
    "root_missing": bundle.STATUS_NOT_CONFIGURED,
    "root_not_dir": bundle.STATUS_NOT_CONFIGURED,
    "conflict": bundle.STATUS_DEGRADED,
}


async def _probe_deploy_identity(ctx: ProbeContext) -> ProbeObservation:
    collector = ctx.deps.identity_collector
    if collector is None:
        from services import deploy_identity
        collector = deploy_identity.collect_identity
    root = _default_repo_root(ctx.deps)
    process_started_at = getattr(ctx.deps.status, "started_at", None)
    try:
        record = await asyncio.wait_for(
            asyncio.to_thread(collector, root,
                              process_started_at=process_started_at),
            timeout=max(2.0, float(ctx.limits.probe_timeout_seconds)))
    except Exception:
        return _observation(
            "deploy", status=bundle.STATUS_UNAVAILABLE,
            facts={"root_configured": bool(root)},
            source_id="deploy:identity", reason_code="identity_collector_failed",
            health_criterion="none",
            not_checked=("identity", "commits"))
    if not isinstance(record, dict):
        record = {}
    code = str(record.get("code") or "unknown")
    status = _IDENTITY_STATUS_MAP.get(code, bundle.STATUS_UNKNOWN)
    facts = {
        "code": code,
        "reason": record.get("reason"),
        "repo_origin": record.get("repo_origin"),
        "deployed_sha": record.get("deployed_sha"),
        "checkout_sha": record.get("checkout_sha"),
        "branch": (record.get("local_identity") or {}).get("branch"),
        "dirty": (record.get("local_identity") or {}).get("dirty"),
        "upstream_head": record.get("upstream_head"),
        "local_source_verification": record.get(
            "local_source_verification"),
        "version_provenance": record.get("version_provenance"),
        "deployed_at": record.get("deployed_at"),
        "observed_at": record.get("observed_at"),
        "conflict": record.get("conflict"),
    }
    commits = None
    not_checked = ["commits_since_deploy"]
    if ctx.arguments.get("include_commits"):
        commits_collector = ctx.deps.recent_commits_collector
        if commits_collector is None:
            from services import deploy_identity
            commits_collector = deploy_identity.recent_commits
        try:
            commits = await asyncio.wait_for(
                asyncio.to_thread(commits_collector, root, limit=5),
                timeout=max(2.0, float(ctx.limits.expensive_timeout_seconds)))
            not_checked = []
        except Exception:
            commits = None
            not_checked = ["commits"]
    verified = None
    if code == "verified_deployed":
        verified = True
    elif code in ("local_unverified", "unavailable", "permission_denied",
                  "path_denied"):
        verified = False
    return _observation(
        "deploy", status=status, facts=facts,
        source_id="deploy:identity",
        health_criterion="none", verified=verified,
        reason_code=(None if status == bundle.STATUS_OK
                     else str(record.get("reason") or code)),
        not_checked=tuple(not_checked))


# ── network ───────────────────────────────────────────────────────────────

def _configured_hosts() -> list[str]:
    """Хосты ТОЛЬКО уже настроенных сервисов (не произвольный scan)."""
    candidates = [
        getattr(settings, "LLM_BASE_URL", ""),
        getattr(settings, "EMBEDDING_BASE_URL", ""),
        getattr(settings, "EMBEDDING_FALLBACK_BASE_URL", ""),
    ]
    hosts: list[str] = []
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            parsed = urllib.parse.urlparse(text)
            host = parsed.hostname or ""
        except ValueError:
            host = ""
        if host and host not in hosts:
            hosts.append(host)
    if "api.telegram.org" not in hosts:
        hosts.append("api.telegram.org")
    return hosts


async def _default_resolve(host: str) -> list:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, 443, type=0)


async def _probe_network_endpoints(ctx: ProbeContext) -> ProbeObservation:
    hosts = _configured_hosts()
    resolver = ctx.deps.dns_resolver or _default_resolve
    results = []
    failures = 0
    for host in hosts:
        entry = {"host": host}
        try:
            infos = await asyncio.wait_for(resolver(host), timeout=2.0)
            entry["dns"] = bundle.STATUS_OK
            entry["addresses"] = len(list(infos or ()))
        except asyncio.TimeoutError:
            entry["dns"] = bundle.STATUS_UNAVAILABLE
            entry["reason_code"] = "dns_timeout"
            failures += 1
        except Exception:
            entry["dns"] = bundle.STATUS_UNAVAILABLE
            entry["reason_code"] = "dns_failed"
            failures += 1
        entry["tls"] = bundle.STATUS_NOT_CHECKED
        entry["endpoint_health"] = bundle.STATUS_NOT_CHECKED
        results.append(entry)
    if not results:
        return _observation(
            "network", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="network:endpoints", reason_code="no_configured_hosts",
            not_checked=("dns", "tls", "endpoint_health"))
    healthy = failures == 0
    return _observation(
        "network",
        status=(bundle.STATUS_OK if healthy else bundle.STATUS_DEGRADED),
        facts={"hosts": results},
        source_id="network:endpoints",
        health_criterion="dns_all_configured_hosts",
        healthy=healthy,
        reason_code=(None if healthy else "dns_failures"),
        not_checked=("tls", "endpoint_health", "arbitrary_hosts"))


# ── incidents ─────────────────────────────────────────────────────────────

async def _probe_incidents_active(ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    if db is None:
        return _observation(
            "incidents", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="incidents:active", reason_code="no_db",
            not_checked=("active_incidents",))
    if not mca_gates.incidents_enabled():
        return _observation(
            "incidents", status=bundle.STATUS_NOT_CONFIGURED, facts={},
            source_id="incidents:active", reason_code="incidents_disabled",
            not_checked=("active_incidents",))
    limit = min(int(ctx.arguments.get("limit") or 50),
                int(ctx.limits.max_rows))
    try:
        rows = await mca_incidents.active_incidents(db, limit=limit)
    except Exception:
        return _observation(
            "incidents", status=bundle.STATUS_UNAVAILABLE, facts={},
            source_id="incidents:active",
            reason_code="incidents_read_failed",
            not_checked=("active_incidents",))
    by_severity: dict[str, int] = {}
    public = []
    for row in rows:
        severity = str(row.get("severity") or "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        public.append({
            "incident_id": row.get("incident_id"),
            "process_id": row.get("process_id"),
            "stage": row.get("stage"),
            "severity": severity,
            "first_ts": row.get("first_ts"),
            "last_ts": row.get("last_ts"),
            "repeat_count": row.get("repeat_count"),
            "first_trace_id": row.get("first_trace_id"),
            "last_trace_id": row.get("last_trace_id"),
        })
    healthy = len(rows) == 0
    return _observation(
        "incidents",
        status=(bundle.STATUS_OK if healthy else bundle.STATUS_DEGRADED),
        facts={"active": len(rows), "by_severity": by_severity,
               "incidents": public},
        source_id="incidents:active",
        health_criterion="no_active_incidents",
        healthy=healthy,
        reason_code=(None if healthy else "active_incidents"),
        source_ref=bundle.source_ref(
            store="sqlite", entity_type="unknown",
            entity_id="incidents:active", resolution="unknown"),
        not_checked=("resolution_history",))


async def _probe_incidents_watchdog(ctx: ProbeContext) -> ProbeObservation:
    db = ctx.deps.db
    facts: dict = {
        "external_observer_available": bool(
            mca_watchdog.external_observer_available()),
        "real_time_when_down": False,
        "post_restart_reconstruction": True,
    }
    status = ctx.deps.status
    started_at = getattr(status, "started_at", None)
    facts["process_started_at"] = started_at
    if started_at:
        try:
            facts["process_uptime_seconds"] = max(
                0, int(ctx.now - datetime.datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")).timestamp()))
        except (TypeError, ValueError):
            facts["process_uptime_seconds"] = None
    facts["telemetry_freshness"] = await mca_watchdog.telemetry_freshness(db)
    if db is not None:
        try:
            facts["stale_jobs"] = len(await mca_watchdog.stale_jobs(db))
            facts["progress_stalled"] = len(
                await mca_watchdog.progress_stalled_jobs(db))
        except Exception:
            facts["stale_jobs"] = None
            facts["progress_stalled"] = None
    else:
        facts["stale_jobs"] = None
        facts["progress_stalled"] = None
    return _observation(
        "incidents", status=bundle.STATUS_OK, facts=facts,
        source_id="incidents:watchdog",
        health_criterion="none",
        reason_code=(None if facts["external_observer_available"]
                     else "no_external_observer"),
        not_checked=("in_process_self_diagnosis_when_down",))


# ── Регистрация встроенных probes ─────────────────────────────────────────

_STRING_ARGS = {"type": "string", "max_chars": 120}
_LIMIT_ARG = {"type": "integer", "minimum": 1, "maximum": 1000}

_BUILTIN_PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        "process.self", "process", "Собственный процесс",
        "PID/PPID/uptime/threads/open FDs и способ запуска (systemd/container/"
        "standalone). Raw argv не выдаётся.",
        READ_SCOPE_INSTANCE, handler=_probe_process_self,
        source_owner="runtime"),
    ProbeSpec(
        "resources.cpu", "resources", "CPU и load average",
        "Накопительные CPU-счётчики; проценты только по двум реальным "
        "наблюдениям; loadavg — системный агрегат.",
        READ_SCOPE_HOST, handler=_probe_resources_cpu,
        source_owner="system"),
    ProbeSpec(
        "resources.memory", "resources", "Память/swap/PSI/OOM",
        "RAM/swap, cgroup-лимиты, PSI и oom_kill; host vs container виден.",
        READ_SCOPE_HOST, handler=_probe_resources_memory,
        source_owner="system"),
    ProbeSpec(
        "resources.pressure", "resources", "PSI pressure",
        "PSI cpu/memory/io (если ядро/контейнер отдают); иначе unsupported.",
        READ_SCOPE_HOST, handler=_probe_resources_pressure,
        source_owner="system"),
    ProbeSpec(
        "disks.usage", "disks", "Диски и inodes",
        "Закрытый набор mount-ключей (root/cwd/db/tmp) и WAL; LLM не задаёт "
        "произвольный путь.",
        READ_SCOPE_HOST, handler=_probe_disks_usage,
        args={"mount": {"type": "string",
                        "enum": ("root", "cwd", "db", "tmp"),
                        "max_chars": 16}},
        source_owner="system"),
    ProbeSpec(
        "fds_sockets.process", "fds_sockets", "FD и сокеты процесса",
        "Open FDs/лимит и состояния inet-соединений ТОЛЬКО своего процесса.",
        READ_SCOPE_INSTANCE, handler=_probe_fds_process,
        source_owner="runtime"),
    ProbeSpec(
        "logs.window", "logs", "Локальное окно логов",
        "Существующий локальный backend (journal/stream/ledger); meta-факты "
        "без сырого текста логов.",
        READ_SCOPE_INSTANCE, handler=_probe_logs_window,
        requires=("logs_fetcher",), source_owner="journal"),
    ProbeSpec(
        "logs.errors", "logs", "Ошибки и stack summary",
        "In-process error-ring; traceback отдаётся структурной выжимкой с "
        "continuation, а не обрезкой по первым N символам.",
        READ_SCOPE_INSTANCE, handler=_probe_logs_errors,
        args={"limit": _LIMIT_ARG,
              "include_stack": {"type": "boolean"},
              "cursor": _STRING_ARGS},
        source_owner="runtime"),
    ProbeSpec(
        "logs.events", "logs", "Журнал событий (mca_events)",
        "События ТЕКУЩЕГО chat scope либо безличные; чужие chat rows "
        "исключаются и только считаются. Correlation ID → стадии/таймауты.",
        READ_SCOPE_CURRENT_CHAT, handler=_probe_logs_events,
        requires=("db",),
        args={"limit": _LIMIT_ARG,
              "correlation_id": {"type": "string", "max_chars": 64}},
        source_owner="sqlite"),
    ProbeSpec(
        "service.runtime", "service", "systemd/контейнер identity",
        "Фактический unit/invocation и systemd state; не-systemd честно "
        "unsupported.",
        READ_SCOPE_INSTANCE, handler=_probe_service_runtime,
        source_owner="systemd"),
    ProbeSpec(
        "scheduler.jobs", "scheduler", "Планировщик и durable jobs",
        "TaskSupervisor + task_jobs + watchdog stale/stalled; next_run и "
        "last_success не выдаются за «выполнено».",
        READ_SCOPE_INSTANCE, handler=_probe_scheduler_jobs,
        requires=("db",), source_owner="sqlite"),
    ProbeSpec(
        "telegram.delivery", "telegram", "Доставка Telegram",
        "Ledger доставленного ТОЛЬКО текущего чата + обезличенные глобальные "
        "счётчики; чужие чаты не читаются.",
        READ_SCOPE_CURRENT_CHAT, handler=_probe_telegram_delivery_async,
        requires=("db",),
        args={"limit": _LIMIT_ARG}, source_owner="telegram"),
    ProbeSpec(
        "media.stt", "media", "STT/voice статусы",
        "Очередь/статусы транскрибации текущего чата, last success/error; "
        "приватные аудио/другие чаты не читаются.",
        READ_SCOPE_CURRENT_CHAT, handler=_probe_media_stt,
        requires=("db",),
        args={"limit": _LIMIT_ARG}, source_owner="sqlite"),
    ProbeSpec(
        "llm.telemetry", "llm", "LLM/инструменты (телеметрия)",
        "Счётчики provider/cost/tasks/degradations из существующего "
        "mca_events.metrics; без prompt bodies.",
        READ_SCOPE_INSTANCE, handler=_probe_llm_telemetry,
        requires=("db",), source_owner="sqlite"),
    ProbeSpec(
        "dependencies.providers", "dependencies", "Провайдеры/зависимости",
        "Существующий capability_registry: declared/configured/"
        "probe_succeeded/healthy раздельно; live-сеть не дёргается.",
        READ_SCOPE_INSTANCE, handler=_probe_dependencies_providers,
        source_owner="runtime"),
    ProbeSpec(
        "memory.health", "memory", "Память/GraphRAG",
        "Существующие memory_health + memory_diagnostics: счётчики, FTS/vec, "
        "stale rebuild; нового графа нет.",
        READ_SCOPE_CURRENT_CHAT, handler=_probe_memory_health,
        requires=("db",), source_owner="sqlite"),
    ProbeSpec(
        "db.health", "db", "БД",
        "SQLite connectivity/PRAGMA/page/WAL и configured PG; произвольный "
        "SQL от модели не принимается.",
        READ_SCOPE_INSTANCE, handler=_probe_db_health,
        requires=("db",), source_owner="sqlite"),
    ProbeSpec(
        "db.integrity", "db", "SQLite quick_check",
        "ДОРОГАЯ read-only integrity-проверка только по явному запросу.",
        READ_SCOPE_INSTANCE, handler=_probe_db_integrity,
        requires=("db",), expensive=True, source_owner="sqlite"),
    ProbeSpec(
        "config.effective", "config", "Эффективная конфигурация",
        "Закрытый набор несекретных hot/кодовых ключей: effective value, "
        "source, updated_at/applied_at; секреты не читаются.",
        READ_SCOPE_INSTANCE, handler=_probe_config_effective,
        source_owner="runtime"),
    ProbeSpec(
        "deploy.identity", "deploy", "Деплой и ревизия",
        "Существующий deploy_identity: repo_origin/deployed_sha/checkout_sha/"
        "dirty/upstream; commits — только по явному include_commits.",
        READ_SCOPE_REPO, handler=_probe_deploy_identity,
        args={"include_commits": {"type": "boolean"}},
        source_owner="repo"),
    ProbeSpec(
        "network.endpoints", "network", "DNS настроенных сервисов",
        "DNS только уже настроенных хостов (LLM/embeddings/Telegram API); "
        "произвольный scan и TLS-инспекция не выполняются.",
        READ_SCOPE_INSTANCE, handler=_probe_network_endpoints,
        source_owner="network"),
    ProbeSpec(
        "incidents.active", "incidents", "Активные инциденты",
        "Существующий mca_incidents read-only: severity/стадии/trace id; "
        "resolution history — not_checked.",
        READ_SCOPE_INSTANCE, handler=_probe_incidents_active,
        requires=("db",),
        args={"limit": _LIMIT_ARG}, source_owner="sqlite"),
    ProbeSpec(
        "incidents.watchdog", "incidents", "Watchdog/пост-рестарт",
        "Внешний observer и правдивая пост-рестарт реконструкция; процесс "
        "не обещает ответить после собственного падения.",
        READ_SCOPE_INSTANCE, handler=_probe_incidents_watchdog,
        source_owner="runtime"),
    ProbeSpec(
        "incidents.investigate_incident", "incidents",
        "Сценарий расследования инцидента",
        "Сценарий СУЩЕСТВУЮЩЕГО координатора: deploy + voice/STT + provider "
        "status + logs/events + scheduler/config/active incidents. Без второй "
        "LLM-стадии и без нового агента.",
        READ_SCOPE_CURRENT_CHAT, scenario=True,
        children=(
            "deploy.identity", "process.self", "resources.cpu",
            "resources.memory", "scheduler.jobs", "media.stt",
            "dependencies.providers", "logs.window", "logs.events",
            "config.effective", "incidents.active",
        ),
        source_owner="runtime"),
)


def _register_builtins() -> None:
    for spec in _BUILTIN_PROBES:
        register_probe(spec, replace=True)


_register_builtins()

