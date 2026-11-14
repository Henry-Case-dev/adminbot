#!/usr/bin/env python3
"""SMART-EXECUTION-RELIABILITY-01 — live canary harness (READ-ONLY).

Один standalone-скрипт для production-наблюдений по строкам, ожидающим
live-подтверждения: SXR-L1-01, SXR-K3-01, SXR-L2-01, SXR-L3-01, SXR-L4-01,
SXR-F2-01, SXR-F4-01, SXR-L5-01, SXR-L6-01, SXR-H3-01, SXR-H4-01, SXR-L7-01,
SXR-I1-01, SXR-I2-01, SXR-L8-01.

Контракт безопасности (жёсткий):

* НЕТ Telegram I/O: aiogram-бот/сообщения не создаются, ничего не отправляется.
* НЕТ записи конфигурации: PG читается напрямую read-only запросами; горячие
  кэши (`hot_config`, `chat_params`) заполняются ТОЛЬКО чтением; DDL/сиды/
  миграции конфигурации не запускаются.
* НЕТ разрушительных записей: SQLite всегда открывается `mode=ro`; SQL —
  только SELECT. Сценарии бюджетов исполняются подменой функций В ПАМЯТИ с
  гарантированным восстановлением.
* Исполняемые production-пути сами эмитят телеметрию в существующие
  in-memory буферы (`execution_graph_source`, `mca_events`); durable-записи
  НЕ выполняются (flush не вызывается), т.к. sink БД не конфигурируется.
* Никаких секретов/chat_id в выводе: chat_id → `chat-<sha8>`, значения ключей
  не читаются/не печатаются; строки режутся и проходят redaction.
* Никаких фоновых циклов: только конечные проверки с таймаутом.
* LLM-вызовы (платные) ЗАПРЕЩЕНЫ по умолчанию; включаются
  `--allow-provider-calls` и ограничены `--max-provider-calls`.

Каждая проверка возвращает: id, req_ids, status (observed|not_observed|
error), evidence_class (plumbing|production|unavailable), summary, details
(redacted), duration_s. `status=observed` разрешён ТОЛЬКО для
`evidence_class=production`: проверка, исполненная на scripted-двойниках или
синтетическом входе, обязана сообщать `not_observed` с
`evidence_class=plumbing`, даже если весь контракт прошёл. Скрипт
завершается с кодом 0, если он реально отработал; провал отдельной проверки
остаётся в JSON.

Флаги:
  --json-out PATH          куда записать JSON (атомарно)
  --dry-run                перечислить проверки и выйти (без сети/БД)
  --self-test              офлайн-самопроверка логики харнесса (без сети/БД)
  --allow-provider-calls   разрешить реальные LLM-вызовы (по умолчанию OFF)
  --max-provider-calls N   потолок платных вызовов (по умолчанию 4)
  --repo-path PATH         корень deployed-кода (по умолчанию cwd)
  --db-path PATH           SQLite БД (по умолчанию <repo>/local_database.db)
  --checkup-unit NAME      systemd unit бота (по умолчанию admin_bot)
  --chat-id N              явный chat scope (можно несколько)
  --checks a,b             подмножество проверок
  --check-timeout SEC      таймаут одной проверки (по умолчанию 180)
  --offline                запретить любой сетевой доступ (read_source_code/
                           capacity-каталог/LLM) — отчёт честно скажет, что
                           сетевая часть не наблюдалась
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as _dt
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

#: 1.2.0 (2026-11-14): r2 corrective — effective_config читает master-флаг
#: бюджетов по фактическому ключу deployed-резолвера (`budgets_enabled`) и
#: честно проваливает утверждение на неизвестной форме вместо KeyError;
#: k3_settings атрибутирует post-deploy изменения профилей по провенансу
#: (prompt_activations/chat_lore_history) — ручная правка владельца законна,
#: запись релиза без следа проваливает проверку; external_reads доказывает
#: verified-идентичность файлом исходника (README по контракту V1 — honest
#: verified=false) и требует от tool-path отказа БЕЗ сетевого вызова.
#: 1.3.0 (2026-11-14): F4 external-code acceptance — новый check
#: `external_scenarios` (публичный repo, поиск файла/символа на точном commit,
#: чтение по blob-ссылке, переход к связанным источникам, фактический отказ
#: недоступного repo, отсутствие отдельной GitHub-команды) и
#: `external_natural_request` (естественный запрос о внешнем коде через Direct
#: L1 с ОДНИМ реальным provider-вызовом; без решения модели — честный
#: not_observed с трассой).
HARNESS_VERSION = "1.3.0"
SCHEMA = "smart-live-canary/2"

STATUS_OBSERVED = "observed"
STATUS_NOT_OBSERVED = "not_observed"
STATUS_ERROR = "error"

#: Классы доказательности. `production` = реальный production-путь/данные
#: (provider/сеть, PG, systemd-journal, deployed-файлы) без подмены стимула.
#: `plumbing` = production-код исполнен, но вход/LLM/роутер подменены харнессом
#: либо данные синтетические: это проверка контракта, а не production-факт.
#: `unavailable` = нужный production-источник в этом окружении недоступен.
EVIDENCE_PRODUCTION = "production"
EVIDENCE_PLUMBING = "plumbing"
EVIDENCE_UNAVAILABLE = "unavailable"
EVIDENCE_CLASSES = (EVIDENCE_PLUMBING, EVIDENCE_PRODUCTION, EVIDENCE_UNAVAILABLE)

TOOL_LOOP_FALLBACK_PHRASE = (
    "Чет долго думал, аж перегрелся — и всё равно ни к чему не пришёл. "
    "Спроси проще, что ли."
)

_CHAT_KEYS = {
    "chat", "chat_id", "chatid", "worst_chat", "scope_chat_id", "cid",
    "resource_chat_id",
}
_CHAT_REF_RE = re.compile(r"(?<!\d)(-?\d{5,})(?!\d)")
_BOT_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}")

# Acceptance-critical environment/config names (presence only; secret values
# are never read or printed).
_ENV_NAMES = (
    "BUDGETS_ENABLED",
    "TOOL_CHAIN_LIMITS_ENABLED",
    "MCA_TOOL_MAX_TOTAL_CALLS",
    "MCA_TOOL_MAX_METERED_CALLS",
    "MCA_TOOL_MAX_SAME_CALL",
    "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
    "CHAT_UNKNOWN_MODEL_WINDOW",
    "MODEL_CAPACITY_RESOLVER_ENABLED",
    "SOURCE_READ_ENABLED",
    "LLM_MODEL_NAME",
    "LLM_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_BASE_URL",
    "POSTGRES_DSN",
    "DB_PATH",
    "ADMINBOT_DEPLOYER",
)

_NON_SECRET_ENV_VALUES = {
    "BUDGETS_ENABLED",
    "TOOL_CHAIN_LIMITS_ENABLED",
    "MCA_TOOL_MAX_TOTAL_CALLS",
    "MCA_TOOL_MAX_METERED_CALLS",
    "MCA_TOOL_MAX_SAME_CALL",
    "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
    "CHAT_UNKNOWN_MODEL_WINDOW",
    "MODEL_CAPACITY_RESOLVER_ENABLED",
    "SOURCE_READ_ENABLED",
    "LLM_MODEL_NAME",
    "LLM_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_BASE_URL",
    "DB_PATH",
}

# Release evidence baseline (plans/features/smart-execution-reliability-01/
# release-evidence/2.58.200/deploy.md). The canary compares CURRENT persisted
# state against these recorded values; it never writes them back.
K3_BASELINE: dict[str, Any] = {
    "source": "release-evidence/2.58.200/deploy.md",
    "deployed_version": "2.58.200",
    "deploy_at_utc": "2026-11-14T05:18:47+00:00",
    "bot_settings_total": 548,
    "chat_profiles_max_updated_at": "2026-11-13T11:07:51+00:00",
    "override_key_counts": [5, 8, 31],
    "protected_settings": {
        # key: {"value": <expected or None>, "updated_date": "YYYY-MM-DD"}
        "flags.budgets_enabled": {"value": False, "updated_date": "2026-10-25"},
        "models.llm_model_name": {"value": None, "updated_date": "2026-11-11"},
        "models.llm_base_url": {"value": None, "updated_date": "2026-09-12"},
    },
    # Единственная новая строка prompts.* этого релиза (factory-текст).
    "allowed_new_prompt_keys": ["prompts.factcheck_subject_system_prompt"],
}

_LOOP_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_source_code",
            "description": "Canary read of a code fragment (read-only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "repo": {"type": "string"},
                    "url": {"type": "string"},
                    "ref": {"type": "string"},
                    "path": {"type": "string"},
                    "symbol": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                },
            },
        },
    }
]


# ── redaction/utilities ──────────────────────────────────────────────────────


def _chat_ref(value: Any) -> str:
    try:
        raw = str(int(value))
    except (TypeError, ValueError):
        raw = str(value or "")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"chat-{digest}"


def _clip(text: Any, limit: int = 1200) -> str:
    s = " ".join(str(text if text is not None else "").split())
    return s if len(s) <= limit else s[: limit - 12] + "…[clipped]"


def _scrub_text(text: str, repo_root: str | None = None) -> str:
    s = _BOT_TOKEN_RE.sub("[bot-token]", str(text or ""))
    s = _SK_KEY_RE.sub("[api-key]", s)
    s = _BEARER_RE.sub("Bearer [redacted]", s)
    if repo_root:
        s = s.replace(str(repo_root), "<repo>")
        try:
            s = s.replace(str(Path(repo_root).resolve()), "<repo>")
        except OSError:
            pass
    return s


def _scrub_obj(value: Any, repo_root: str | None = None, _depth: int = 0) -> Any:
    """JSON-safe redacted projection (chat ids never leak)."""
    if _depth > 6:
        return "[depth]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:200]:
            lk = str(key).lower()
            if lk in _CHAT_KEYS and isinstance(item, (int, str)):
                out[str(key)] = _chat_ref(item)
                continue
            out[str(key)] = _scrub_obj(item, repo_root, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub_obj(v, repo_root, _depth + 1) for v in list(value)[:200]]
    if isinstance(value, str):
        return _scrub_text(_clip(value, 4000), repo_root)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _scrub_text(_clip(repr(value), 400), repo_root)


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _file_sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


# ── harness plumbing ─────────────────────────────────────────────────────────


@dataclass
class CheckOutcome:
    status: str
    summary: str
    details: dict = field(default_factory=dict)
    evidence_class: str = EVIDENCE_PLUMBING
    evidence_reason: str = ""

    def as_dict(self, check_id: str, req_ids: list[str], duration_s: float,
                title: str) -> dict:
        return {
            "id": check_id,
            "title": title,
            "req_ids": list(req_ids),
            "status": self.status,
            "evidence_class": self.evidence_class,
            "evidence_reason": _clip(self.evidence_reason, 400),
            "production_observed": (
                self.status == STATUS_OBSERVED
                and self.evidence_class == EVIDENCE_PRODUCTION
            ),
            "summary": _clip(self.summary, 800),
            "details": self.details,
            "duration_s": round(duration_s, 3),
        }


class Asserts:
    """Прозрачный список ожиданий: failure → not_observed (не error)."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.failures: list[str] = []

    def expect(self, name: str, ok: Any, detail: Any = "") -> bool:
        passed = bool(ok)
        self.items.append(
            {"name": str(name), "ok": passed, "detail": _clip(detail, 400)}
        )
        if not passed:
            self.failures.append(str(name))
        return passed

    def report(self) -> list[dict]:
        return list(self.items)


#: Ключ master-флага бюджетов в снимке deployed-резолвера
#: (`services.budget_gate.BudgetState.as_meta()`): ключ называется
#: ``budgets_enabled``. Имя не угадывается: если deployed-резолвер отдаст
#: другую форму, проверка обязана провалиться с наблюдаемой формой, а не
#: упасть с KeyError.
BUDGET_FLAG_KEY = "budgets_enabled"


def _budget_flag(meta_or_state: Any) -> tuple[bool | None, dict]:
    """Прочитать master-флаг бюджетов из снимка/состояния резолвера.

    Возвращает ``(value, observed)``; ``value is None`` ⇔ документированного
    ключа в фактической форме нет — тогда ``observed`` несёт реальную форму
    (тип/ключи) для честного провала утверждения.
    """
    meta: Any = meta_or_state
    if not isinstance(meta, dict):
        try:
            meta = meta_or_state.as_meta()
        except Exception:
            meta = None
    if isinstance(meta, dict) and BUDGET_FLAG_KEY in meta:
        return bool(meta[BUDGET_FLAG_KEY]), {"keys": sorted(map(str, meta))}
    observed = {
        "expected_key": BUDGET_FLAG_KEY,
        "observed_type": type(meta_or_state).__name__,
    }
    if isinstance(meta, dict):
        observed["observed_keys"] = sorted(map(str, meta))
        observed["observed"] = _clip(json.dumps(meta, default=str), 400)
    return None, observed


def _plumbing_outcome(a: Asserts, details: dict, summary: str) -> CheckOutcome:
    """Итог проверки, исполненной на scripted-двойниках/синтетике.

    `observed` здесь запрещён: это контрактная (plumbing) проверка, а не
    production-наблюдение. Провал контракта остаётся `not_observed`.
    """
    assertions = a.report()
    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "plumbing-контракт НЕ подтверждён: " + ", ".join(a.failures[:6]),
            {**details, "assertions": assertions, "plumbing_pass": False},
            EVIDENCE_PLUMBING,
            "scripted doubles/synthetic input; contract failed",
        )
    return CheckOutcome(
        STATUS_NOT_OBSERVED,
        "plumbing-контракт подтверждён; production-путь не наблюдался "
        "(scripted doubles/синтетический вход): " + summary,
        {**details, "assertions": assertions, "plumbing_pass": True},
        EVIDENCE_PLUMBING,
        "scripted doubles/synthetic input; not production evidence",
    )


def _enforce_evidence_class(payload: dict) -> dict:
    """Запретить `observed` без production-доказательства.

    Защита от будущих правок: даже если проверка случайно вернёт `observed`
    с `plumbing`/`unavailable`, JSON честно понижает статус.
    """
    evidence_class = str(payload.get("evidence_class") or EVIDENCE_UNAVAILABLE)
    if evidence_class not in EVIDENCE_CLASSES:
        evidence_class = EVIDENCE_UNAVAILABLE
    payload["evidence_class"] = evidence_class
    observed = payload.get("status") == STATUS_OBSERVED
    production = evidence_class == EVIDENCE_PRODUCTION
    if observed and not production:
        details = payload.get("details")
        if not isinstance(details, dict):
            details = {}
            payload["details"] = details
        details["status_downgrade"] = {
            "from": STATUS_OBSERVED,
            "to": STATUS_NOT_OBSERVED,
            "reason": f"evidence_class={evidence_class}; observed требует production",
        }
        payload["status"] = STATUS_NOT_OBSERVED
        payload["summary"] = (
            f"[downgraded: {evidence_class}-only] "
            + str(payload.get("summary") or "")
        )[:800]
        observed = False
    payload["production_observed"] = bool(observed and production)
    return payload


def _harness_identity(path: Path) -> dict:
    """Идентичность самого harness: sha256 + Git-привязка авторской копии."""
    resolved = path.resolve()
    sha = _file_sha256(resolved) or None
    info: dict[str, Any] = {
        "path": str(resolved),
        "sha256": sha,
        "git_repo": None,
        "git_relative": None,
        "git_head": None,
        "tracked": None,
        "blob_matches_head": None,
        "dirty_vs_head": None,
        "note": "",
    }
    top = _git(resolved.parent, "rev-parse", "--show-toplevel")
    if not top:
        info["note"] = "harness file is outside a Git repository"
        return info
    repo = Path(top).resolve()
    try:
        relative = resolved.relative_to(repo).as_posix()
    except ValueError:
        info["note"] = "harness file is outside its Git repository root"
        return info
    info["git_repo"] = str(repo)
    info["git_relative"] = relative
    info["git_head"] = _git(repo, "rev-parse", "HEAD") or None
    info["git_branch"] = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or None
    tracked = _git(repo, "ls-files", "--error-unmatch", "--", relative)
    info["tracked"] = tracked == relative
    head_blob = _git(repo, "rev-parse", f"HEAD:{relative}") if tracked else ""
    local_blob = _git(repo, "hash-object", "--", str(resolved))
    info["blob_matches_head"] = bool(
        head_blob and local_blob and head_blob == local_blob)
    info["dirty_vs_head"] = bool(
        info["tracked"] and head_blob and local_blob and head_blob != local_blob)
    if not info["tracked"]:
        info["note"] = "UNTRACKED: commit the harness before using the JSON as candidate-bound evidence"
    elif not info["blob_matches_head"]:
        info["note"] = "WORKTREE COPY DIFFERS FROM HEAD: commit before evidence run"
    info["path"] = _scrub_text(str(resolved), str(repo))
    info["git_repo"] = _scrub_text(str(repo), str(repo))
    return info


@dataclass
class HarnessContext:
    repo_root: Path
    args: argparse.Namespace
    started_monotonic: float = field(default_factory=time.monotonic)
    results: dict[str, dict] = field(default_factory=dict)
    provider_calls: int = 0
    provider_denied: int = 0
    _pg: Any = None
    _pg_failed: bool = False
    _config_loaded: bool = False
    _sqlite: Any = None
    _sqlite_failed: bool = False
    _identity: dict | None = None
    _logs: tuple | None = None
    _llm: Any = None

    # -- provider budget ----------------------------------------------------
    def allow_provider(self) -> bool:
        return bool(self.args.allow_provider_calls) and not self.args.offline

    def take_provider_call(self) -> bool:
        if not self.allow_provider():
            self.provider_denied += 1
            return False
        if self.provider_calls >= int(self.args.max_provider_calls):
            self.provider_denied += 1
            return False
        self.provider_calls += 1
        return True

    # -- PG read-only config layer -----------------------------------------
    async def pg(self):
        if self._pg is not None:
            return self._pg
        if self._pg_failed:
            return None
        dsn = os.getenv("POSTGRES_DSN") or ""
        if not dsn:
            self._pg_failed = True
            return None
        try:
            from services.pg_db import PgDatabase

            pg = PgDatabase(dsn=dsn)
            await pg.connect()  # pool only: DDL/сиды НЕ вызываются
            if pg.pool is None:
                self._pg_failed = True
                return None
            self._pg = pg
            return pg
        except Exception:
            self._pg_failed = True
            return None

    async def load_config_cache(self) -> bool:
        """Прочитать реальный persisted-слой в RAM (без DDL/сидов/записи)."""
        if self._config_loaded:
            return True
        pg = await self.pg()
        if pg is None:
            return False
        try:
            from services import hot_config as hot
            from services.chat_params import ChatParamsCache, \
                set_chat_params_cache
            from services.config_cache import ConfigCache

            cache = ConfigCache(pg=pg, retry_attempts=1, retry_delay=0)
            await cache._load_all()  # read-only SELECT'ы
            hot.set_config_cache(cache)
            set_chat_params_cache(ChatParamsCache(pg))
            self._config_loaded = True
            return True
        except Exception:
            return False

    async def pg_rows(self, sql: str, params: tuple = ()) -> list[dict]:
        pg = await self.pg()
        if pg is None or pg.pool is None:
            return []
        async with pg.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(row) for row in rows]

    # -- SQLite read-only ---------------------------------------------------
    async def sqlite(self):
        if self._sqlite is not None:
            return self._sqlite
        if self._sqlite_failed:
            return None
        from services.database import DatabaseService

        path = Path(self.args.db_path) if self.args.db_path else (
            self.repo_root / "local_database.db")
        try:
            db = DatabaseService(str(path))
            await db.initialize_readonly()
            self._sqlite = db
            return db
        except Exception:
            self._sqlite_failed = True
            return None

    async def sqlite_rows(self, sql: str, params: tuple = ()) -> list[dict]:
        db = await self.sqlite()
        if db is None or db.db is None:
            return []
        cursor = await db.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def sqlite_one(self, sql: str, params: tuple = ()) -> dict:
        rows = await self.sqlite_rows(sql, params)
        return rows[0] if rows else {}

    # -- identities/logs ----------------------------------------------------
    async def identity(self) -> dict:
        if self._identity is None:
            from services import source_reader as sr

            self._identity = await asyncio.to_thread(
                sr.resolve_self_repo_identity)
        return self._identity

    async def runtime_logs(self) -> tuple[str, bool, str, str]:
        if self._logs is not None:
            return self._logs
        from services.system_logs_fetcher import (
            CheckupLogsFetcher,
            RuntimeIdentity,
        )

        unit = str(self.args.checkup_unit or "").strip()
        identity = RuntimeIdentity(
            kind="systemd" if unit else "standalone",
            pid=os.getpid(),
            unit=unit or None,
        )

        def _probe():
            return identity

        fetcher = CheckupLogsFetcher(identity_probe=_probe)
        try:
            text, used_fallback = await fetcher.fetch()
        except Exception as exc:
            self._logs = ("", True, "unreadable", f"fetch:{type(exc).__name__}")
            return self._logs
        self._logs = (
            str(text or ""),
            bool(used_fallback),
            str(fetcher.last_state or ""),
            str(fetcher.last_journal_state or ""),
        )
        return self._logs

    def llm(self):
        """Реальный production LLMClient (только при разрешённых вызовах)."""
        if self._llm is not None:
            return self._llm
        from config.settings import settings
        from services import hot_config as hot
        from services.llm_client import LLMClient

        self._llm = LLMClient(
            hot.get("models.llm_base_url", settings.LLM_BASE_URL),
            hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
            hot.get("models.embedding_model_name",
                    settings.EMBEDDING_MODEL_NAME),
            embed_base_url=hot.get("models.embedding_base_url",
                                   settings.EMBEDDING_BASE_URL),
            embed_api_key=hot.get("keys.embedding_api_key",
                                  settings.EMBEDDING_API_KEY),
        )
        return self._llm


@dataclass
class CheckSpec:
    id: str
    group: str
    title: str
    req_ids: tuple[str, ...]
    fn: Callable[[HarnessContext], Awaitable[CheckOutcome]]


# ── in-memory patches (всегда восстанавливаются) ─────────────────────────────


class _SettingsProxy:
    """Read-only proxy: отдаёт реальные settings, кроме явных overrides.

    `config.settings.settings` — frozen dataclass; in-memory подмена
    выполняется НЕ мутацией объекта, а подменой ссылки в конкретном модуле
    (tool_loop), с восстановлением исходной ссылки в finally.
    """

    def __init__(self, real, overrides: dict) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_overrides", dict(overrides))

    def __getattr__(self, name: str):
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_real"), name)


@contextlib.contextmanager
def patched_tool_loop_settings(**values):
    """Временная (in-memory) политика tool-loop; всегда восстанавливается."""
    import services.tool_loop as tool_loop

    real = tool_loop.settings
    tool_loop.settings = _SettingsProxy(real, values)
    try:
        yield
    finally:
        tool_loop.settings = real


@contextlib.contextmanager
def patched_budgets_enabled(value: bool):
    from services import budget_gate

    original = budget_gate.budgets_enabled

    async def _forced(chat_id=None):  # noqa: ANN001
        _ = chat_id
        return bool(value)

    budget_gate.budgets_enabled = _forced
    try:
        yield
    finally:
        budget_gate.budgets_enabled = original


@contextlib.contextmanager
def network_blocked():
    """Доказать, что путь НЕ ходил в сеть: любой вызов SafeFetcher падает."""
    from services import safe_fetch

    names = ("fetch", "fetch_text", "fetch_json", "stream_to_file")
    originals = {name: getattr(safe_fetch.SafeFetcher, name) for name in names}

    async def _blocked(self, *args, **kwargs):  # noqa: ANN001
        raise RuntimeError("network blocked by smart_live_canary")

    for name in originals:
        setattr(safe_fetch.SafeFetcher, name, _blocked)
    try:
        yield
    finally:
        for name, fn in originals.items():
            setattr(safe_fetch.SafeFetcher, name, fn)


@contextlib.contextmanager
def offline_guard():
    """Полный offline-режим: SafeFetcher + provider-каталоги отключены."""
    with network_blocked():
        with patched_capacity_adapters_missing():
            yield


@contextlib.contextmanager
def patched_capacity_adapters_missing():
    from services import model_capacity as mc

    names = (
        "_adapter_nanogpt_catalog",
        "_adapter_openrouter",
        "_adapter_llama_cpp",
        "_adapter_ollama",
        "_adapter_vllm",
    )
    originals = {name: getattr(mc, name) for name in names if hasattr(mc, name)}

    async def _none(*_a, **_k):
        return None

    for name in originals:
        setattr(mc, name, _none)
    try:
        mc.invalidate_capacity_cache()
        yield
    finally:
        for name, fn in originals.items():
            setattr(mc, name, fn)
        mc.invalidate_capacity_cache()


# ── scripted doubles (детерминированный LLM/роутер для сценариев) ────────────


class ScriptedLLM:
    """Строгий двойник LLMClient: только заданный сценарий, без сети."""

    def __init__(self, rounds, *, final_text: str = "",
                 finalizer_error: Exception | None = None) -> None:
        self.rounds = list(rounds)
        self.final_text = final_text
        self.finalizer_error = finalizer_error
        self.index = 0
        self.calls = 0
        self.generate_calls = 0
        #: id'ы tool_calls, запрошенных сценарием (для проверки, что КАЖДЫЙ
        #: получил role:"tool" до следующего вызова модели).
        self.requested_ids: list[str] = []
        for _item in self.rounds:
            if isinstance(_item, BaseException):
                continue
            _content, _calls = _item
            for _tc in _calls or ():
                self.requested_ids.append(str(_tc.id))
        self.tool_message_ids_seen: list[str] = []
        self.tool_messages_at_last_call = 0

    @staticmethod
    def _tool_ids(messages) -> list[str]:
        out: list[str] = []
        for message in messages or ():
            if not isinstance(message, dict):
                continue
            if message.get("role") == "tool" and message.get("tool_call_id"):
                out.append(str(message["tool_call_id"]))
        return out

    async def generate_chat(self, messages, **_kwargs):  # noqa: ANN001
        from services.llm_client import LLMChatResult

        self.calls += 1
        seen = self._tool_ids(messages)
        self.tool_message_ids_seen = seen
        self.tool_messages_at_last_call = len(seen)
        item = self.rounds[self.index] if self.index < len(self.rounds) else (
            "", None)
        self.index += 1
        if isinstance(item, BaseException):
            raise item
        content, tool_calls = item
        return LLMChatResult(
            content=content or None,
            tool_calls=list(tool_calls) if tool_calls else None,
            finish_reason="tool_calls" if tool_calls else "stop",
        )

    async def generate(self, messages, **_kwargs):  # noqa: ANN001
        self.generate_calls += 1
        if self.finalizer_error is not None:
            raise self.finalizer_error
        return self.final_text

    def result_sequence_stats(self) -> dict:
        requested = set(self.requested_ids)
        seen = set(self.tool_message_ids_seen)
        return {
            "requested": len(requested),
            "tool_messages": self.tool_messages_at_last_call,
            "missing_tool_messages": sorted(requested - seen),
            "every_call_got_result": bool(requested) and requested <= seen,
        }


def _tool_call(call_id: str, name: str, arguments: dict):
    from services.llm_client import LLMToolCall

    return LLMToolCall(
        id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False)
    )


class StubRouter:
    """Управляемая инъекция отказов (fault injection) для §G-сценариев."""

    def __init__(self, responder: Callable[[str, dict, int], Any]) -> None:
        self.responder = responder
        self.calls: list[dict] = []

    async def dispatch(self, name: str, arguments: dict, ctx) -> str:  # noqa: ANN001
        index = len(self.calls)
        self.calls.append({"tool": name, "arguments": dict(arguments or {})})
        result = self.responder(name, arguments or {}, index)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False)
        return str(result)


def _ok_source(tool: str, marker: str) -> dict:
    return {
        "status": "ok",
        "summary": f"canary source {marker}",
        "results": [
            {
                "title": f"canary-{marker}",
                "url": f"https://example.org/canary/{marker}",
                "snippet": f"Evidence body for marker {marker}.",
            }
        ],
    }


def _error_source(code: str, *, stage: str = "fetch", retryable: bool = False):
    return {
        "status": "error",
        "error": code,
        "stage": stage,
        "retryable": retryable,
        "summary": f"canary error {code}",
    }


# ═════════════════════════════════════════════════════════════════════════════
# 1. effective_config → SXR-L1-01, SXR-K3-01
# ═════════════════════════════════════════════════════════════════════════════


def _env_presence(ctx: HarnessContext) -> dict:
    env_file_keys: set[str] = set()
    for name in (".env", ".env.local"):
        path = ctx.repo_root / name
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if key:
                    env_file_keys.add(key)
        except OSError:
            continue
    out: dict[str, dict] = {}
    for name in _ENV_NAMES:
        item: dict[str, Any] = {
            "in_process_env": name in os.environ,
            "in_env_file": name in env_file_keys,
        }
        if name in _NON_SECRET_ENV_VALUES:
            value = os.getenv(name)
            item["value"] = None if value is None else _clip(value, 160)
        out[name] = item
    return out


async def check_effective_config(ctx: HarnessContext) -> CheckOutcome:
    from config.settings import settings
    from services import budget_gate, model_capacity as capacity
    from services import hot_config as hot
    from services.tool_loop import resolve_chain_limits

    a = Asserts()
    details: dict[str, Any] = {"effective": {}, "checks": []}
    unexpected_errors: list[str] = []

    env = _env_presence(ctx)
    details["env"] = env

    factory = {
        "BUDGETS_ENABLED": bool(getattr(settings, "BUDGETS_ENABLED", True)),
        "TOOL_CHAIN_LIMITS_ENABLED": bool(
            getattr(settings, "TOOL_CHAIN_LIMITS_ENABLED", True)),
        "MCA_TOOL_MAX_TOTAL_CALLS": int(
            getattr(settings, "MCA_TOOL_MAX_TOTAL_CALLS", 0) or 0),
        "MCA_TOOL_MAX_METERED_CALLS": int(
            getattr(settings, "MCA_TOOL_MAX_METERED_CALLS", 0) or 0),
        "MCA_TOOL_MAX_SAME_CALL": int(
            getattr(settings, "MCA_TOOL_MAX_SAME_CALL", 0) or 0),
        "MCA_TOOL_CHAIN_TIMEOUT_SECONDS": float(
            getattr(settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 0.0) or 0.0),
        "CHAT_UNKNOWN_MODEL_WINDOW": int(
            getattr(settings, "CHAT_UNKNOWN_MODEL_WINDOW", 1000000) or 0),
        "MODEL_CAPACITY_RESOLVER_ENABLED": bool(
            getattr(settings, "MODEL_CAPACITY_RESOLVER_ENABLED", True)),
        "SOURCE_READ_ENABLED": bool(getattr(settings, "SOURCE_READ_ENABLED", True)),
    }
    details["factory"] = factory

    configured = await ctx.load_config_cache()
    details["persisted_layer_loaded"] = configured

    # -- master budgets: global + per real chat -----------------------------
    try:
        global_state = await budget_gate.resolve_budgets(None)
        details["master_global"] = global_state.as_meta()
    except Exception as exc:
        unexpected_errors.append(f"master_global:{type(exc).__name__}")
        global_state = None

    chat_ids: list[int] = []
    if configured:
        try:
            rows = await ctx.pg_rows(
                "SELECT chat_id FROM chat_profiles ORDER BY chat_id")
            chat_ids = [int(r["chat_id"]) for r in rows if r.get("chat_id") is not None]
        except Exception as exc:
            unexpected_errors.append(f"chat_profiles:{type(exc).__name__}")
    details["real_chats"] = [_chat_ref(cid) for cid in chat_ids]

    per_chat: list[dict] = []
    for cid in chat_ids:
        try:
            state = await budget_gate.resolve_budgets(cid)
            limits = resolve_chain_limits(budgets_enabled=state.enabled).as_meta()
            per_chat.append(
                {
                    "chat": _chat_ref(cid),
                    "budgets": state.as_meta(),
                    "chain_limits": limits,
                }
            )
        except Exception as exc:
            unexpected_errors.append(f"chat_resolve:{type(exc).__name__}")
    details["master_per_chat"] = per_chat
    details["budget_flag_contract"] = {
        "key": BUDGET_FLAG_KEY,
        "resolver": "services.budget_gate.resolve_budgets().as_meta()",
        "source_priority": "chat override → global → settings.BUDGETS_ENABLED",
    }
    details["master_per_chat_flags"] = [
        {
            "chat": entry["chat"],
            "budgets_enabled": _budget_flag(entry.get("budgets"))[0],
            "source": (entry.get("budgets") or {}).get("source"),
            "known": (entry.get("budgets") or {}).get("known"),
        }
        for entry in per_chat
    ]
    details["chain_limits_global"] = resolve_chain_limits().as_meta()

    # -- model capacity: chat-path model, async catalog + legacy sync ------
    import asyncio as _asyncio

    base_url = str(hot.get("models.llm_base_url", settings.LLM_BASE_URL) or "")
    model = str(hot.get("models.llm_model_name", settings.LLM_MODEL_NAME) or "")
    fallback_base = str(hot.get("models.llm_fallback_base_url",
                                settings.LLM_FALLBACK_BASE_URL) or "")
    fallback_model = str(hot.get("models.llm_fallback_model",
                                 settings.LLM_FALLBACK_MODEL) or "")
    details["chat_model"] = {
        "base_url_host": _clip(re.sub(r"(?i)\b[\w.-]+://", "", base_url).split("/")[0], 120),
        "model": model,
        "fallback_model": fallback_model or None,
        "fallback_configured": bool(fallback_model),
    }
    try:
        legacy = capacity.resolve_model_context_window(model)
        details["capacity_legacy"] = {
            "value": int(legacy[0]) if legacy else None,
            "source": legacy[1] if legacy else None,
        }
    except Exception as exc:
        unexpected_errors.append(f"legacy_capacity:{type(exc).__name__}")
        details["capacity_legacy"] = {"error": type(exc).__name__}

    if ctx.args.offline:
        details["capacity_async"] = {"skipped": "offline"}
    else:
        try:
            result = await _asyncio.wait_for(
                capacity.resolve_capacity(base_url, model), timeout=45)
            details["capacity_async"] = result.as_window_meta()
        except Exception as exc:
            details["capacity_async"] = {"error": type(exc).__name__}
            unexpected_errors.append(f"async_capacity:{type(exc).__name__}")

    try:
        details["effective_window"] = capacity.resolve_effective_window(
            model, fallback_model or None)
    except Exception as exc:
        details["effective_window"] = {"error": type(exc).__name__}

    # -- expectations -------------------------------------------------------
    a.expect("persisted_config_readable", configured,
             "PG config layer read (read-only)")
    a.expect("real_chats_discovered", bool(chat_ids),
             f"count={len(chat_ids)}")
    if global_state is not None:
        master_meta = details["master_global"]
        a.expect("master_global_known", bool(master_meta.get("known")),
                 master_meta)
        master_flag, master_observed = _budget_flag(master_meta)
        if master_flag is None:
            a.expect(
                "master_global_off", False,
                {"reason": "master budget flag key missing in the deployed "
                           "resolver snapshot", **master_observed})
        else:
            a.expect("master_global_off", not master_flag, master_meta)
    for entry in per_chat:
        chat_flag, chat_observed = _budget_flag(entry.get("budgets"))
        if chat_flag is None:
            a.expect(
                f"chat_budgets_off:{entry['chat']}", False,
                {"reason": "budget flag key missing in the deployed resolver "
                           "snapshot", **chat_observed})
            continue
        a.expect(
            f"chat_budgets_off:{entry['chat']}",
            not chat_flag,
            entry["budgets"],
        )
    for meta_key in ("chain_limits_global",):
        meta = details[meta_key]
        a.expect(f"{meta_key}_no_caps",
                 all(int(meta.get(k) or 0) == 0 for k in (
                     "max_total_calls", "max_metered_calls", "max_same_call")),
                 meta)
        a.expect(f"{meta_key}_no_fuse",
                 float(meta.get("fuse_seconds") or 0.0) == 0.0, meta)
    hidden = {
        name: item.get("value")
        for name, item in env.items()
        if (
            name.startswith("MCA_TOOL_MAX_")
            or name in (
                "BUDGETS_ENABLED", "TOOL_CHAIN_LIMITS_ENABLED",
                "CHAT_UNKNOWN_MODEL_WINDOW")
        )
        and (item.get("in_process_env") or item.get("in_env_file"))
    }
    details["possible_env_overrides"] = hidden
    for name, value in hidden.items():
        if name.startswith("MCA_TOOL_MAX_"):
            try:
                a.expect(f"env_{name}_not_enforcing", int(float(value or 0)) == 0,
                         value)
            except (TypeError, ValueError):
                a.expect(f"env_{name}_not_enforcing", False, value)
    fake_1m = details.get("capacity_legacy", {}).get("value")
    a.expect("legacy_unknown_not_16384", fake_1m != 16384,
             f"legacy={fake_1m}")
    details["unexpected_errors"] = unexpected_errors
    a.expect("no_unexpected_errors", not unexpected_errors,
             ", ".join(unexpected_errors))

    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "effective-конфигурация прочитана, но контракт не подтверждён: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION if (configured and chat_ids)
            else EVIDENCE_UNAVAILABLE,
            "real settings/PG persisted config" if (configured and chat_ids)
            else "PG persisted config unavailable",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "master budgets OFF во всех реальных чатах, скрытого enforcement нет, "
        "capacity-резолвер доступен",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real env/settings + read-only PG bot_settings/chat_profiles",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2/3. tool-loop control scenarios → SXR-L1-01
# ═════════════════════════════════════════════════════════════════════════════

_LOOP_READ_SPECS = [
    {"path": "config/settings.py", "line_start": 1, "line_end": 14},
    {"path": "config/settings.py", "line_start": 15, "line_end": 28},
    {"path": "config/settings.py", "line_start": 29, "line_end": 42},
    {"path": "services/tool_loop.py", "line_start": 1, "line_end": 14},
    {"path": "services/tool_loop.py", "line_start": 15, "line_end": 28},
    {"path": "services/tool_loop.py", "line_start": 29, "line_end": 42},
    {"path": "services/tool_loop.py", "line_start": 43, "line_end": 56},
]


def _loop_rounds(specs: list[dict], *, final_text: str):
    """>4 раундов, >6 вызовов, >2 корректных вызова в одном раунде."""
    calls = []
    index = 0
    for spec in specs:
        index += 1
        calls.append(_tool_call(f"call_{index}", "read_source_code",
                                {"operation": "read", **spec}))
    rounds = [
        ("", calls[0:3]),   # 3 корректных вызова в одном раунде
        ("", calls[3:4]),
        ("", calls[4:5]),
        ("", calls[5:7]),
        (final_text, None),  # 5-й LLM-раунд — финальный ответ
    ]
    return rounds


async def _run_loop_scenario(ctx: HarnessContext, *, scripted_rounds,
                             chat_id: int = 0):
    from services.tool_loop import chat_with_tools
    from services.tool_router import ToolContext, ToolDeps, ToolRouter

    identity = await ctx.identity()
    router = ToolRouter(ToolDeps(search=None, memory=None))
    tool_ctx = ToolContext(chat_id, "canary control loop",
                           diagnostic_research=identity)
    llm = ScriptedLLM(scripted_rounds, final_text="canary final answer")
    result = await chat_with_tools(
        llm,
        [{"role": "user", "content": "canary: прочитай фрагменты своего кода"}],
        tools=_LOOP_TOOL_SCHEMAS,
        router=router,
        ctx=tool_ctx,
        chat_id=chat_id,
        correlation_id="canary-smart-live",
    )
    return result, llm, router, tool_ctx


def _envelope_stats(result, llm: ScriptedLLM | None = None) -> dict:
    envelopes = [e for e in (result.tool_results or []) if isinstance(e, dict)]
    statuses: dict[str, int] = {}
    for entry in envelopes:
        key = str(entry.get("status") or "")
        statuses[key] = statuses.get(key, 0) + 1
    denied = [
        e for e in envelopes
        if str(e.get("status") or "") == "denied"
        or str(e.get("error_code") or "").startswith("chain_")
    ]
    sequence = (
        llm.result_sequence_stats() if llm is not None
        else {"requested": len(envelopes), "tool_messages": len(envelopes),
              "missing_tool_messages": [], "every_call_got_result": False,
              "source": "unavailable_no_scripted_llm"}
    )
    sequence.setdefault("source", "scripted_llm")
    return {
        "total": len(envelopes),
        "statuses": statuses,
        "chain_denied": len(denied),
        "duplicates": sum(1 for e in envelopes if e.get("duplicate")),
        "sequence": sequence,
        "reasons": sorted({str(e.get("error_code") or "") for e in envelopes
                           if e.get("error_code")}),
    }


async def check_control_loop_off(ctx: HarnessContext) -> CheckOutcome:
    from services import budget_gate
    from services.tool_loop import resolve_chain_limits

    a = Asserts()
    details: dict[str, Any] = {}
    identity = await ctx.identity()
    details["self_identity"] = {
        "source": identity.get("source"),
        "ref_source": identity.get("ref_source"),
        "verification": identity.get("verification"),
        "deployed_matches_checkout": identity.get("deployed_matches_checkout"),
        "repo": identity.get("repo"),
        "ref": identity.get("ref"),
        "note": identity.get("note"),
    }
    budgets_on = bool(await budget_gate.budgets_enabled(0))
    limits = resolve_chain_limits(budgets_enabled=budgets_on).as_meta()
    details["effective_limits"] = limits
    details["budgets_enabled_for_chat"] = budgets_on

    a.expect("budgets_effectively_off", not budgets_on, limits)
    a.expect("no_volume_caps",
             all(int(limits.get(k) or 0) == 0 for k in (
                 "max_total_calls", "max_metered_calls", "max_same_call")),
             limits)

    try:
        with network_blocked():
            result, llm, _router, tool_ctx = await _run_loop_scenario(
                ctx,
                scripted_rounds=_loop_rounds(
                    _LOOP_READ_SPECS[:7],
                    final_text="canary final answer: все фрагменты получены"),
            )
        stats = _envelope_stats(result, llm)
        metered = sum(1 for e in (result.tool_results or [])
                      if isinstance(e, dict) and e.get("metered"))
        details["loop"] = {
            **stats,
            "rounds_used": int(getattr(result, "rounds_used", 0) or 0),
            "degraded": bool(getattr(result, "degraded", False)),
            "reason": str(getattr(result, "reason", "")),
            "finalize_mode": str(getattr(result, "finalize_mode", "")),
            "final_chars": len(str(result)),
            "llm_rounds": llm.calls,
            "scripted_round_sizes": [
                len(calls or ()) for _content, calls in llm.rounds],
            "metered_envelopes": metered,
            "evidence_window_entries": len(getattr(tool_ctx, "evidence_limits", [])),
        }
        a.expect("rounds_gt_4", int(getattr(result, "rounds_used", 0)) > 4,
                 getattr(result, "rounds_used", 0))
        a.expect("calls_gt_6", stats["total"] > 6, stats["total"])
        a.expect("three_calls_in_one_round",
                 max(details["loop"]["scripted_round_sizes"] or [0]) >= 3,
                 details["loop"]["scripted_round_sizes"])
        a.expect("multi_call_single_round", llm.calls == 5, llm.calls)
        a.expect("every_call_got_result",
                 stats["sequence"]["every_call_got_result"]
                 and stats["sequence"]["tool_messages"] == stats["total"],
                 stats["sequence"])
        a.expect("no_chain_cap_skip", stats["chain_denied"] == 0,
                 stats["reasons"])
        a.expect("no_duplicate_skips", stats["duplicates"] == 0, stats)
        a.expect("usage_accounting_preserved", metered == stats["total"],
                 {"metered": metered, "total": stats["total"]})
        a.expect("not_degraded", not bool(getattr(result, "degraded", False)),
                 getattr(result, "reason", ""))
        a.expect("final_answer_present",
                 bool(str(result).strip()) and TOOL_LOOP_FALLBACK_PHRASE
                 not in str(result), str(result)[:160])
        evidence_limits = list(getattr(tool_ctx, "evidence_limits", []) or [])
        a.expect("no_network_needed",
                 bool(evidence_limits)
                 and all(int((e or {}).get("network_calls") or 0) == 0
                         for e in evidence_limits),
                 evidence_limits)
    except Exception as exc:
        details["exception"] = _clip(traceback.format_exc(limit=3), 800)
        return CheckOutcome(
            STATUS_ERROR,
            f"tool-loop сценарий упал: {type(exc).__name__}",
            {**details, "assertions": a.report()},
        )

    if a.failures:
        return _plumbing_outcome(
            a, details,
            "tool-loop отработал, но контракт OFF не подтверждён: "
            + ", ".join(a.failures[:6]),
        )
    return _plumbing_outcome(
        a, details,
        "OFF-контракт подтверждён: 5 раундов, 7 вызовов (3 в одном раунде), "
        "все получили результат, cap-скипов нет",
    )


async def check_caps_on_and_override(ctx: HarnessContext) -> CheckOutcome:
    from config.settings import settings
    from services import budget_gate

    a = Asserts()
    details: dict[str, Any] = {}
    original_budgets_fn = budget_gate.budgets_enabled
    original = {
        "MCA_TOOL_MAX_TOTAL_CALLS": getattr(settings, "MCA_TOOL_MAX_TOTAL_CALLS"),
        "MCA_TOOL_MAX_METERED_CALLS": getattr(
            settings, "MCA_TOOL_MAX_METERED_CALLS"),
        "MCA_TOOL_MAX_SAME_CALL": getattr(settings, "MCA_TOOL_MAX_SAME_CALL"),
        "TOOL_CHAIN_LIMITS_ENABLED": getattr(
            settings, "TOOL_CHAIN_LIMITS_ENABLED"),
        "MCA_TOOL_CHAIN_TIMEOUT_SECONDS": getattr(
            settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS"),
    }
    details["restored_from"] = dict(original)

    try:
        # (A) budgets ON + factory caps (0) → никакого enforcement.
        with patched_budgets_enabled(True), patched_tool_loop_settings(
                MCA_TOOL_MAX_TOTAL_CALLS=0,
                MCA_TOOL_MAX_METERED_CALLS=0,
                MCA_TOOL_MAX_SAME_CALL=0,
                TOOL_CHAIN_LIMITS_ENABLED=True,
                MCA_TOOL_CHAIN_TIMEOUT_SECONDS=0.0):
            with network_blocked():
                result_on, llm_on, _r, _c = await _run_loop_scenario(
                    ctx,
                    scripted_rounds=_loop_rounds(
                        _LOOP_READ_SPECS[:7],
                        final_text="canary final answer (budgets on, no caps)"),
                )
            stats_on = _envelope_stats(result_on, llm_on)
            details["budgets_on_factory_caps"] = {
                **stats_on,
                "rounds_used": int(getattr(result_on, "rounds_used", 0) or 0),
                "degraded": bool(getattr(result_on, "degraded", False)),
                "reason": str(getattr(result_on, "reason", "")),
                "llm_rounds": llm_on.calls,
            }
            a.expect("on_factory_caps_no_skip", stats_on["chain_denied"] == 0,
                     stats_on["reasons"])
            a.expect("on_factory_caps_no_duplicates",
                     stats_on["duplicates"] == 0, stats_on)
            a.expect("on_factory_caps_rounds_gt_4",
                     int(getattr(result_on, "rounds_used", 0) or 0) > 4,
                     getattr(result_on, "rounds_used", 0))
            a.expect("on_factory_caps_every_call_result",
                     stats_on["sequence"]["every_call_got_result"],
                     stats_on["sequence"])
            a.expect("on_factory_caps_not_degraded",
                     not bool(getattr(result_on, "degraded", False)),
                     getattr(result_on, "reason", ""))

        # (B) budgets ON + operator override → cap и same_call реально
        # применяются, но каждый вызов всё равно получает структурный ответ.
        with patched_budgets_enabled(True), patched_tool_loop_settings(
                MCA_TOOL_MAX_TOTAL_CALLS=3,
                MCA_TOOL_MAX_METERED_CALLS=0,
                MCA_TOOL_MAX_SAME_CALL=2,
                TOOL_CHAIN_LIMITS_ENABLED=True,
                MCA_TOOL_CHAIN_TIMEOUT_SECONDS=0.0):
            specs = _LOOP_READ_SPECS[:5]
            calls = [
                _tool_call(
                    f"cap_{i}", "read_source_code",
                    {"operation": "read", **spec})
                for i, spec in enumerate(specs)
            ]
            repeat = _tool_call("cap_repeat", "read_source_code",
                                {"operation": "read", **specs[0]})
            rounds = [
                ("", calls[0:3]),
                ("", calls[3:5] + [repeat]),
                ("canary final answer (override)", None),
            ]
            with network_blocked():
                result_cap, llm_cap, _r, _c = await _run_loop_scenario(
                    ctx, scripted_rounds=rounds)
            stats_cap = _envelope_stats(result_cap, llm_cap)
            details["budgets_on_override"] = {
                **stats_cap,
                "rounds_used": int(getattr(result_cap, "rounds_used", 0) or 0),
                "degraded": bool(getattr(result_cap, "degraded", False)),
                "reason": str(getattr(result_cap, "reason", "")),
                "finalize_mode": str(getattr(result_cap, "finalize_mode", "")),
                "text": str(result_cap)[:200],
                "llm_rounds": llm_cap.calls,
            }
            a.expect("override_policy_seen",
                     any(r in stats_cap["reasons"] for r in (
                         "chain_call_limit", "same_call")),
                     stats_cap["reasons"])
            a.expect("override_every_call_has_result",
                     stats_cap["total"] == len(llm_cap.requested_ids),
                     {"envelopes": stats_cap["total"],
                      "requested": len(llm_cap.requested_ids),
                      "sequence": stats_cap["sequence"]})
            a.expect("override_degraded_honestly",
                     bool(getattr(result_cap, "degraded", False)),
                     getattr(result_cap, "reason", ""))
            a.expect("override_no_hidden_exception",
                     bool(str(result_cap).strip()), str(result_cap)[:120])
            a.expect("override_limits_meta",
                     int(getattr(result_cap, "rounds_used", 0)) >= 2,
                     getattr(result_cap, "rounds_used", 0))

        # (C) восстановление реальных значений.
        restored = {
            "MCA_TOOL_MAX_TOTAL_CALLS": getattr(
                settings, "MCA_TOOL_MAX_TOTAL_CALLS"),
            "MCA_TOOL_MAX_METERED_CALLS": getattr(
                settings, "MCA_TOOL_MAX_METERED_CALLS"),
            "MCA_TOOL_MAX_SAME_CALL": getattr(
                settings, "MCA_TOOL_MAX_SAME_CALL"),
            "TOOL_CHAIN_LIMITS_ENABLED": getattr(
                settings, "TOOL_CHAIN_LIMITS_ENABLED"),
            "MCA_TOOL_CHAIN_TIMEOUT_SECONDS": getattr(
                settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS"),
        }
        details["restored_after"] = dict(restored)
        a.expect("settings_restored", restored == original,
                 {"before": original, "after": restored})

        from services import budget_gate

        real_state = await budget_gate.resolve_budgets(0)
        details["budgets_after_restore"] = real_state.as_meta()
        import services.tool_loop as tool_loop

        a.expect("tool_loop_settings_restored", tool_loop.settings is settings,
                 type(getattr(tool_loop, "settings", None)).__name__)
        a.expect("budget_gate_restored",
                 budget_gate.budgets_enabled is original_budgets_fn,
                 str(getattr(budget_gate.budgets_enabled, "__name__", "?")))
    except Exception as exc:
        details["exception"] = _clip(traceback.format_exc(limit=3), 800)
        return CheckOutcome(
            STATUS_ERROR,
            f"сценарий override упал: {type(exc).__name__}",
            {**details, "assertions": a.report()},
        )

    if a.failures:
        return _plumbing_outcome(
            a, details,
            "budgets ON/override отработали неконтрактно: "
            + ", ".join(a.failures[:6]),
        )
    return _plumbing_outcome(
        a, details,
        "budgets ON без политики не режет; операторский override даёт "
        "структурные cap/same_call ответы; значения восстановлены",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 4. evidence payload → SXR-L2-01
# ═════════════════════════════════════════════════════════════════════════════


def _make_long_source(total_chars: int, marker: str) -> tuple[str, str]:
    head = (
        "CANARY-EVIDENCE-BEGIN\n"
        "Это не секретный контрольный источник для проверки доставки evidence.\n"
    )
    tail = (
        f"\nCANARY-TAIL-MARKER:{marker}\n"
        "Конец источника: если этот маркер доставлен, хвост не потерян.\n"
    )
    filler_len = max(0, total_chars - len(head) - len(tail))
    line = "Факт: контрольная строка evidence остаётся видимой в payload.\n"
    body = (line * ((filler_len // len(line)) + 1))[:filler_len]
    return head + body + tail, marker


async def check_evidence_payload(ctx: HarnessContext) -> CheckOutcome:
    from config.settings import settings
    from services import auto_budget
    from services import hot_config as hot
    from services.direct_execution import (
        EvidenceSource,
        build_evidence_pack,
        l2_evidence_budget_chars,
    )

    a = Asserts()
    details: dict[str, Any] = {}

    base_url = str(hot.get("models.llm_base_url", settings.LLM_BASE_URL) or "")
    model = str(hot.get("models.llm_model_name", settings.LLM_MODEL_NAME) or "")

    capacity_source = "auto_budget"
    input_budget = None
    try:
        budget = await auto_budget.resolve_stage_budget(
            "l2", base_url=base_url, model=model, mandatory_tokens=0)
        input_budget = int(getattr(budget, "effective_input_budget", 0) or 0)
        details["stage_budget"] = {
            "context_window": int(getattr(budget, "context_window", 0) or 0),
            "output_reserve": int(getattr(budget, "output_reserve", 0) or 0),
            "effective_input_budget": input_budget,
            "source": str(getattr(budget, "source", "")),
        }
    except Exception as exc:
        capacity_source = f"error:{type(exc).__name__}"
        details["stage_budget"] = {"error": type(exc).__name__}

    if not input_budget:
        from services import model_capacity as capacity

        legacy = capacity.resolve_model_context_window(model) or (0, "")
        input_budget = int(legacy[0] or 0)
        capacity_source = f"legacy:{legacy[1]}"
    cap = l2_evidence_budget_chars(input_budget, other_chars=0)
    details["capacity"] = {
        "source": capacity_source,
        "input_budget_tokens": input_budget,
        "evidence_capacity_chars": cap,
    }

    source_text, marker = _make_long_source(13500, "7f3a")
    raw = type(
        "_RawCanary",
        (),
        {"evidence_sources": [
            EvidenceSource(tool="fetch_article", status="ok",
                           content=source_text, total_chars=len(source_text))
        ]},
    )()
    pack = build_evidence_pack(raw, None, capacity_chars=cap)
    delivered = int(getattr(pack.sources[0], "delivered_chars", 0)) if pack.sources else 0
    details["full_capacity"] = {
        "delivered_chars": delivered,
        "source_chars": len(source_text),
        "source_stripped_chars": len(source_text.strip()),
        "capacity_chars": int(getattr(pack, "capacity_chars", 0) or 0),
        "complete": bool(pack.complete),
        "limitations": list(pack.limitations),
        "tail_present": f"CANARY-TAIL-MARKER:{marker}" in pack.text,
        "payload_chars": len(pack.text),
    }
    a.expect("large_capacity_resolved", bool(cap) and int(cap) > 13500, cap)
    a.expect("full_source_delivered",
             delivered == len(source_text.strip()),
             f"delivered={delivered} source={len(source_text.strip())}")
    a.expect("tail_preserved", details["full_capacity"]["tail_present"])
    a.expect("full_pack_complete", bool(pack.complete), pack.limitations)
    a.expect("no_false_truncation", not pack.limitations, pack.limitations)

    # несколько связанных результатов — каждый блок доставлен
    sources = []
    for name in ("alpha", "beta", "gamma"):
        text = f"CANARY-SOURCE:{name}\nСвязанный фрагмент {name}.\n"
        sources.append(EvidenceSource(tool="fetch_article", status="ok",
                                      content=text, total_chars=len(text)))
    raw_multi = type("_RawMulti", (), {"evidence_sources": sources})()
    pack_multi = build_evidence_pack(raw_multi, None, capacity_chars=cap)
    details["multi_source"] = {
        "blocks": len(pack_multi.sources),
        "delivered": [int(s.delivered_chars) for s in pack_multi.sources],
        "complete": bool(pack_multi.complete),
        "all_markers": all(f"CANARY-SOURCE:{n}" in pack_multi.text
                           for n in ("alpha", "beta", "gamma")),
    }
    a.expect("multi_source_blocks", details["multi_source"]["blocks"] == 3,
             details["multi_source"])
    a.expect("multi_source_all_delivered",
             all(n > 0 for n in details["multi_source"]["delivered"]),
             details["multi_source"])

    # реальное превышение окна → честная обрезка, без «полного прочтения»
    tight_cap = 900
    pack_tight = build_evidence_pack(raw, None, capacity_chars=tight_cap)
    tight = pack_tight.sources[0] if pack_tight.sources else None
    details["tight_capacity"] = {
        "cap": tight_cap,
        "delivered_chars": int(getattr(tight, "delivered_chars", 0)) if tight else 0,
        "truncated": bool(getattr(tight, "truncated", False)) if tight else False,
        "complete": bool(pack_tight.complete),
        "limitations": list(pack_tight.limitations),
        "has_truncation_marker": "обрезано" in pack_tight.text,
        "tail_present": f"CANARY-TAIL-MARKER:{marker}" in pack_tight.text,
        "claims_full_read": "полный текст" in pack_tight.text.lower()
        and "обрезано" not in pack_tight.text,
    }
    a.expect("tight_truncated_honestly",
             details["tight_capacity"]["truncated"]
             and details["tight_capacity"]["has_truncation_marker"]
             and not details["tight_capacity"]["complete"],
             details["tight_capacity"])
    a.expect("tight_no_full_read_claim",
             not details["tight_capacity"]["claims_full_read"],
             details["tight_capacity"])

    if a.failures:
        return _plumbing_outcome(
            a, details,
            "evidence-пакет не подтвердил контракт: "
            + ", ".join(a.failures[:6]),
        )
    return _plumbing_outcome(
        a, details,
        "13 500 симв. доставлены целиком под реальную ёмкость, хвост сохранён; "
        "при малом окне — честная обрезка без заявления о полном чтении",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 5. capacity scenarios → SXR-L3-01
# ═════════════════════════════════════════════════════════════════════════════


async def check_capacity_scenarios(ctx: HarnessContext) -> CheckOutcome:
    from config.settings import settings
    from services import auto_budget
    from services import hot_config as hot
    from services import model_capacity as capacity
    from services.llm_client import LLMError

    a = Asserts()
    details: dict[str, Any] = {"scenarios": {}}

    base_url = str(hot.get("models.llm_base_url", settings.LLM_BASE_URL) or "")
    model = str(hot.get("models.llm_model_name", settings.LLM_MODEL_NAME) or "")
    fb_base = str(hot.get("models.llm_fallback_base_url",
                          settings.LLM_FALLBACK_BASE_URL) or "")
    fb_model = str(hot.get("models.llm_fallback_model",
                           settings.LLM_FALLBACK_MODEL) or "")
    offline = bool(ctx.args.offline)

    async def _resolve(label: str, base: str, name: str, **kw) -> dict:
        if offline:
            entry = {"skipped": "offline", "model": name}
        else:
            try:
                res = await asyncio.wait_for(
                    capacity.resolve_capacity(base, name, **kw), timeout=25)
                entry = res.as_window_meta()
            except Exception as exc:
                entry = {"error": type(exc).__name__, "model": name}
        details["scenarios"][label] = entry
        return entry

    details["chat_model"] = {"model": model,
                             "base_host": _clip(re.sub(
                                 r"(?i)\b[\w.-]+://", "", base_url
                             ).split("/")[0], 120),
                             "resolver_enabled": capacity.capacity_resolver_enabled(),
                             "live_precedence": capacity.live_precedence_enabled()}
    current = await _resolve("current_model", base_url, model)

    known_small = await _resolve("known_under_1m", base_url, "gpt-4o-mini")
    big_window = await _resolve("known_over_1m", base_url, "gemini-2.5-pro")
    unknown_name = "canary/custom-unknown-7f3a"
    unknown = await _resolve("unknown_custom", base_url, unknown_name)

    # смена основной модели: другой слот → другой бюджет
    try:
        switched = await auto_budget.resolve_stage_budget(
            "direct.primary", base_url=base_url,
            model="gpt-4o-mini", mandatory_tokens=0)
        details["scenarios"]["model_switch"] = {
            "model": "gpt-4o-mini",
            "context_window": int(getattr(switched, "context_window", 0) or 0),
            "effective_input_budget": int(
                getattr(switched, "effective_input_budget", 0) or 0),
            "source": str(getattr(switched, "source", "")),
        }
    except Exception as exc:
        details["scenarios"]["model_switch"] = {"error": type(exc).__name__}

    # fallback
    if fb_model:
        fallback = await _resolve("fallback_model", fb_base or base_url, fb_model)
    else:
        try:
            fallback = {
                "configured": False,
                "window": int(capacity.fallback_window_for_model(model)),
            }
        except Exception as exc:
            fallback = {"configured": False, "error": type(exc).__name__}
        details["scenarios"]["fallback_model"] = fallback

    # каталог недоступен (контролируемая инъекция, in-memory)
    try:
        with patched_capacity_adapters_missing():
            if offline:
                catalog_down = {"skipped": "offline"}
            else:
                res = await asyncio.wait_for(
                    capacity.resolve_capacity(base_url, model), timeout=45)
                catalog_down = res.as_window_meta()
        catalog_down["simulated"] = "catalog_adapters_returned_none"
        details["scenarios"]["catalog_unavailable"] = catalog_down
    except Exception as exc:
        details["scenarios"]["catalog_unavailable"] = {
            "error": type(exc).__name__}
        catalog_down = {}

    # context length exceeded: production-парсер + план восстановления
    try:
        exc = LLMError("context_length_exceeded: requested 140000 > limit 131072")
        exc.error_body = {
            "error": {
                "code": "context_length_exceeded",
                "model": model,
                "limit": 131072,
                "requested": 140000,
            }
        }
        info = capacity.parse_context_overflow_error(exc)
        noted, plan = capacity.note_context_overflow(
            exc, base_url=base_url, model=model, output_reserve_tokens=4096)
        details["scenarios"]["context_overflow"] = {
            "parsed": None if info is None else {
                "code": info.code,
                "structured": bool(info.structured),
                "limit_tokens": info.limit_tokens,
                "requested_tokens": info.requested_tokens,
                "model": info.model,
            },
            "noted": noted is not None,
            "plan": None if plan is None else plan.as_event_counts(),
        }
        capacity.clear_proven_limits()
    except Exception as exc:
        details["scenarios"]["context_overflow"] = {"error": type(exc).__name__}
        details["scenarios"]["context_overflow"]["detail"] = _clip(str(exc), 200)

    # -- expectations -------------------------------------------------------
    a.expect("resolver_enabled", bool(capacity.capacity_resolver_enabled()))
    if not offline:
        a.expect("current_model_resolved",
                 bool(current) and not current.get("error"), current)
        a.expect("known_under_1m_resolved",
                 bool(known_small) and not known_small.get("error"), known_small)
        a.expect("known_under_1m_below_1m",
                 int(known_small.get("effective_window") or 0) < 1_000_000,
                 known_small)
        a.expect("big_window_resolved",
                 bool(big_window) and not big_window.get("error"), big_window)
        a.expect("big_window_at_least_1m",
                 int(big_window.get("effective_window") or 0) >= 1_000_000,
                 big_window)
        a.expect("unknown_not_verified",
                 str(unknown.get("confidence") or "") != "verified"
                 and str(unknown.get("source") or "") != "provider_catalog",
                 unknown)
        a.expect("unknown_not_claimed_1m_as_proof",
                 int(unknown.get("effective_window") or 0) != 1_000_000
                 or str(unknown.get("source") or "") in (
                     "estimated_unknown", "fallback"),
                 unknown)
        a.expect("catalog_down_honest",
                 str(catalog_down.get("source") or "") != "provider_catalog"
                 and not catalog_down.get("error"),
                 catalog_down)
        if fb_model:
            a.expect("fallback_resolved",
                     bool(fallback) and not fallback.get("error"), fallback)
        else:
            a.expect("fallback_not_configured_honest",
                     fallback.get("configured") is False, fallback)
    overflow = details["scenarios"]["context_overflow"]
    a.expect("context_overflow_parsed",
             bool(overflow.get("parsed"))
             and overflow.get("parsed", {}).get("limit_tokens") == 131072,
             overflow)
    a.expect("context_overflow_plan", bool(overflow.get("plan")), overflow.get("plan"))
    a.expect("context_overflow_model_identity",
             str((overflow.get("parsed") or {}).get("model") or "") == model,
             overflow.get("parsed"))

    if offline:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "capacity-сценарии не наблюдались: --offline (provider-каталог/"
            "реестр недоступны); проверен только resolver-флаг и "
            "context-overflow парсер",
            {**details, "assertions": a.report()},
            EVIDENCE_UNAVAILABLE,
            "offline: provider capacity catalog not contacted",
        )
    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "восемь сценариев ёмкости не подтверждены: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION,
            "real resolver/provider catalog observed; contract failed",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "единый resolver: current/<1M/>1M/unknown/switch/fallback/"
        "catalog-down/overflow наблюдались, 1M не выдан за verified",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real resolver + provider catalog; one scenario injected in-memory",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 6. local source read → SXR-L4-01
# ═════════════════════════════════════════════════════════════════════════════


async def check_local_source_read(ctx: HarnessContext) -> CheckOutcome:
    from services.tool_router import ToolContext, ToolDeps, ToolRouter

    a = Asserts()
    details: dict[str, Any] = {}

    identity = await ctx.identity()
    head = _git(ctx.repo_root, "rev-parse", "HEAD")
    branch = _git(ctx.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    manifest_path = ctx.repo_root / ".deploy" / "release.json"
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    deployed_sha = str(identity.get("deployed_sha") or "").lower()
    manifest_sha = str(manifest.get("deployed_sha") or "").lower()
    details["runtime_identity"] = {
        "source": identity.get("source"),
        "ref_source": identity.get("ref_source"),
        "verification": identity.get("verification"),
        "deployed_sha": deployed_sha or None,
        "checkout_sha": str(identity.get("checkout_sha") or "").lower() or None,
        "deployed_matches_checkout": identity.get("deployed_matches_checkout"),
        "revision_kind": identity.get("revision_kind"),
        "repo": identity.get("repo"),
        "note": identity.get("note"),
        "selection_reason": identity.get("selection_reason"),
    }
    details["repo"] = {
        "head": head or None,
        "branch": branch or None,
        "app_version": str(getattr(
            __import__("config.settings", fromlist=["APP_VERSION"]),
            "APP_VERSION", "") or ""),
        "manifest_present": manifest_path.is_file(),
        "manifest_deployed_sha": manifest_sha or None,
        "manifest_version": manifest.get("version"),
        "manifest_dirty_tracked": manifest.get("dirty_tracked"),
    }
    a.expect("local_source_selected", identity.get("source") == "local",
             identity.get("source"))
    a.expect("local_source_verified",
             str(identity.get("verification") or "") in (
                 "verified_running", "verified_deployed_snapshot"),
             identity.get("verification"))
    a.expect("deployed_sha_matches_checkout",
             identity.get("deployed_matches_checkout") is True,
             identity.get("deployed_matches_checkout"))
    a.expect("manifest_matches_deployed_sha",
             bool(manifest_sha) and manifest_sha == deployed_sha,
             {"manifest": manifest_sha or None, "identity": deployed_sha or None})
    a.expect("git_head_matches_deployed",
             bool(head) and head.lower() == deployed_sha,
             {"head": head or None, "deployed": deployed_sha or None})

    router = ToolRouter(ToolDeps(search=None, memory=None))
    tool_ctx = ToolContext(0, "canary local source read",
                           diagnostic_research=identity)
    payload: dict = {}
    try:
        with network_blocked():
            out = await router.dispatch(
                "read_source_code",
                {"operation": "read", "path": "services/tool_loop.py",
                 "symbol": "chat_with_tools"},
                tool_ctx,
            )
        payload = json.loads(out) if str(out).strip().startswith("{") else {
            "raw": _clip(out, 300)}
    except Exception as exc:
        details["dispatch_exception"] = type(exc).__name__
    details["payload"] = {
        "status": payload.get("status"),
        "stage": payload.get("stage"),
        "verified": bool(payload.get("verified")),
        "source_kind": payload.get("source_kind"),
        "network_calls": int(payload.get("network_calls") or 0),
        "repo": payload.get("repo"),
        "commit": payload.get("commit"),
        "path": payload.get("path"),
        "line_range": payload.get("line_range"),
        "snippet_chars": int(payload.get("snippet_chars") or 0),
        "read_level": payload.get("read_level"),
        "error": payload.get("error") if isinstance(payload.get("error"), str) else None,
    }
    snippet = str(payload.get("snippet") or "")
    details["payload"]["symbol_present"] = "chat_with_tools" in snippet
    details["evidence_limits"] = list(
        getattr(tool_ctx, "evidence_limits", []) or [])
    a.expect("local_read_ok", payload.get("status") == "ok",
             details["payload"])
    a.expect("local_read_verified_in_prod",
             bool(payload.get("verified")) or identity.get("source") != "local",
             details["payload"])
    a.expect("local_read_no_network",
             int(payload.get("network_calls") or 0) == 0, details["payload"])
    a.expect("local_read_symbol_present",
             bool(details["payload"]["symbol_present"]), details["payload"])
    a.expect("local_read_commit_matches_deployed",
             str(payload.get("commit") or "").lower() == deployed_sha,
             {"payload": payload.get("commit"), "deployed": deployed_sha or None})
    a.expect("local_read_repo_matches_self",
             str(payload.get("repo") or "").lower()
             == str(identity.get("repo") or "").lower(),
             {"payload": payload.get("repo"), "identity": identity.get("repo")})
    a.expect("local_read_uses_canonical_path",
             str(payload.get("path") or "") == "services/tool_loop.py",
             payload.get("path"))

    read_observed = bool(
        payload.get("status") == "ok"
        and str(identity.get("verification") or "") in (
            "verified_running", "verified_deployed_snapshot"))
    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "локальное чтение собственного кода не подтверждено: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION if read_observed else EVIDENCE_UNAVAILABLE,
            "real verified deployed-tree read" if read_observed
            else "local source read unverified/unavailable",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "локальный verified-источник прочитан без GitHub; repo/commit/path "
        "совпадают с deployed SHA",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real deployed-tree read via production read_source_code",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 7. external reads + SSRF refusal → SXR-F2-01, SXR-F4-01, SXR-L5-01
# ═════════════════════════════════════════════════════════════════════════════


#: Публичный источник для production-read. README доказывает сеть и
#: идентичность источника, но по контракту SourceReader (`_read_payload`,
#: инвариант V1) `verified` выдаётся ТОЛЬКО байтам файла исходника
#: (`source_kind=file`), поэтому «получение исходников» доказывается отдельным
#: чтением реального файла того же публичного репозитория.
PUBLIC_README_URL = "https://github.com/octocat/Hello-World/blob/master/README"
PUBLIC_SOURCE_REPO = "octocat/Spoon-Knife"
PUBLIC_SOURCE_REF = "main"
PUBLIC_SOURCE_PATH = "index.html"
#: Причины отказа, при которых внешний файл честно назван отсутствующим
#: (404 — фактическая причина, а не «нет доступа»).
PUBLIC_MISSING_URL = (
    "https://github.com/octocat/Hello-World/blob/master/DOES-NOT-EXIST.md")


async def check_external_reads(ctx: HarnessContext) -> CheckOutcome:
    from services.tool_router import ToolContext, ToolDeps, ToolRouter

    a = Asserts()
    details: dict[str, Any] = {
        "offline": bool(ctx.args.offline),
        "scenario": {
            "readme_url": PUBLIC_README_URL,
            "source_repo": PUBLIC_SOURCE_REPO,
            "source_ref": PUBLIC_SOURCE_REF,
            "source_path": PUBLIC_SOURCE_PATH,
            "verified_contract": (
                "SourceReader._read_payload: verified=True только для "
                "source_kind=file (README доставляется с verified=False по "
                "инварианту V1)"),
        },
    }
    if ctx.args.offline:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "сетевые внешние чтения пропущены: --offline",
            {**details, "assertions": a.report()},
            EVIDENCE_UNAVAILABLE,
            "offline: network provider path not contacted",
        )

    router = ToolRouter(ToolDeps(search=None, memory=None))
    tool_ctx = ToolContext(0, "canary external reads")

    async def _dispatch(args: dict) -> dict:
        out = await router.dispatch("read_source_code", args, tool_ctx)
        if str(out).strip().startswith("{"):
            try:
                return json.loads(out)
            except ValueError:
                return {"raw": _clip(out, 300)}
        return {"raw": _clip(out, 300)}

    def _payload_view(payload: dict) -> dict:
        return {
            "status": payload.get("status"),
            "stage": payload.get("stage"),
            "verified": bool(payload.get("verified")),
            "network_calls": int(payload.get("network_calls") or 0),
            "repo": payload.get("repo"),
            "commit": payload.get("commit"),
            "path": payload.get("path"),
            "snippet_chars": int(payload.get("snippet_chars") or 0),
            "file_total_lines": int(payload.get("file_total_lines") or 0),
            "source_kind": payload.get("source_kind"),
            "read_level": payload.get("read_level"),
            "provider": payload.get("provider"),
            "error": payload.get("error")
            if isinstance(payload.get("error"), str) else None,
        }

    public = await _dispatch({"operation": "read", "url": PUBLIC_README_URL})
    details["public_read"] = _payload_view(public)
    a.expect("public_external_read_ok", public.get("status") == "ok",
             details["public_read"])
    a.expect("public_external_read_network",
             int(public.get("network_calls") or 0) > 0, details["public_read"])
    a.expect("public_external_read_content",
             int(public.get("snippet_chars") or 0) > 0, details["public_read"])
    a.expect("public_external_read_identity",
             bool(public.get("repo")) and bool(public.get("commit"))
             and bool(public.get("path")), details["public_read"])
    # README — документация, а не исходник: verified=True здесь был бы ложью.
    a.expect("public_readme_honest_unverified",
             str(public.get("source_kind") or "") == "readme"
             and public.get("verified") is False, details["public_read"])

    source = await _dispatch({
        "operation": "read", "repo": PUBLIC_SOURCE_REPO,
        "ref": PUBLIC_SOURCE_REF, "path": PUBLIC_SOURCE_PATH})
    details["public_source_read"] = _payload_view(source)
    a.expect("public_source_read_ok", source.get("status") == "ok",
             details["public_source_read"])
    a.expect("public_source_read_network",
             int(source.get("network_calls") or 0) > 0,
             details["public_source_read"])
    a.expect("public_source_read_content",
             int(source.get("snippet_chars") or 0) > 0,
             details["public_source_read"])
    a.expect("public_external_read_verified",
             bool(source.get("verified"))
             and str(source.get("source_kind") or "") == "file"
             and bool(source.get("repo")) and bool(source.get("commit"))
             and str(source.get("path") or "") == PUBLIC_SOURCE_PATH,
             details["public_source_read"])

    loopback = await _dispatch(
        {"operation": "read", "url": "http://127.0.0.1:9/canary"})
    metadata = await _dispatch(
        {"operation": "read",
         "url": "http://169.254.169.254/latest/meta-data/"})
    details["ssrf_refusals"] = []
    for label, payload in (("loopback", loopback), ("metadata", metadata)):
        err = payload.get("error_detail")
        if not isinstance(err, dict):
            err = {}
        entry = {
            "target": label,
            "source": "tool_path",
            "status": payload.get("status"),
            "stage": payload.get("stage"),
            "code": str(payload.get("error") or err.get("code") or "")[:64],
            "detail": str(err.get("detail") or "")[:64],
            "retryable": bool(payload.get("retryable", err.get("retryable"))),
            "network_calls": int(payload.get("network_calls") or 0),
        }
        details["ssrf_refusals"].append(entry)

    # Прямая проверка production SSRF-политики (SafeFetcher — единственный
    # сетевой транспорт): блокировка ДО соединения, стадия resolve.
    from services.safe_fetch import SafeFetchError, SafeFetcher

    fetcher = SafeFetcher()
    try:
        for label, url in (
            ("loopback_direct", "http://127.0.0.1:9/canary"),
            ("metadata_direct", "http://169.254.169.254/latest/meta-data/"),
        ):
            entry = {"target": label, "source": "safe_fetcher"}
            try:
                await asyncio.wait_for(fetcher.fetch_text(url), timeout=20)
                entry.update({"status": "allowed", "code": ""})
            except SafeFetchError as exc:
                entry.update({
                    "status": "blocked",
                    "code": str(getattr(exc, "code", "") or ""),
                    "stage": str(getattr(exc, "stage", "") or ""),
                    "retryable": bool(getattr(exc, "retryable", False)),
                })
            except Exception as exc:
                entry.update({"status": "error",
                              "code": type(exc).__name__})
            details["ssrf_refusals"].append(entry)
    finally:
        try:
            await fetcher.aclose()
        except Exception:
            pass

    direct_blocked = [
        e for e in details["ssrf_refusals"]
        if e.get("source") == "safe_fetcher" and e.get("status") == "blocked"
        and e.get("code") in ("destination_blocked",
                              "metadata_endpoint_blocked")
        and e.get("stage") == "resolve"
    ]
    # `read_source_code` — provider-scoped инструмент (заявлена поддержка
    # только github): не-GitHub адрес отклоняется на стадии discover ДО любого
    # соединения (`unsupported/provider_unconfigured`, detail=host_not_supported).
    # Безопасностное свойство здесь — «отказано и НИ ОДНОГО сетевого вызова»;
    # точные SSRF-коды доказывает реальный транспорт SafeFetcher ниже.
    tool_refusals = [e for e in details["ssrf_refusals"]
                     if e.get("source") == "tool_path"]
    a.expect("ssrf_loopback_refused",
             any(e["target"] == "loopback"
                 and str(e.get("status")) in ("blocked", "error", "unsupported")
                 and bool(e.get("code"))
                 and int(e.get("network_calls") or 0) == 0
                 for e in tool_refusals),
             {"tool_path": tool_refusals,
              "safe_fetcher_codes": [e.get("code") for e in direct_blocked]})
    a.expect("ssrf_metadata_refused",
             any(e["target"] == "metadata"
                 and str(e.get("status")) in ("blocked", "error", "unsupported")
                 and bool(e.get("code"))
                 and int(e.get("network_calls") or 0) == 0
                 for e in tool_refusals),
             {"tool_path": tool_refusals,
              "safe_fetcher_codes": [e.get("code") for e in direct_blocked]})
    a.expect("ssrf_policy_direct", len(direct_blocked) == 2, direct_blocked)

    missing = await _dispatch({"operation": "read",
                               "url": PUBLIC_MISSING_URL})
    err = missing.get("error_detail")
    if not isinstance(err, dict):
        err = {}
    details["external_failure"] = {
        "status": missing.get("status"),
        "stage": missing.get("stage"),
        "code": str(missing.get("error") or err.get("code") or "")[:64],
        "retryable": bool(missing.get("retryable", err.get("retryable"))),
    }
    a.expect("external_failure_honest",
             details["external_failure"]["status"] in ("error", "not_found")
             and bool(details["external_failure"]["code"]),
             details["external_failure"])

    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "внешние чтения/SSRF не подтверждены: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION,
            "real network/SafeFetcher path observed; contract failed",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "публичный GitHub: реальный сетевой read (README + файл исходника с "
        "verified-идентичностью); запрещённые назначения отклонены без "
        "сетевых вызовов, SafeFetcher даёт destination_blocked/"
        "metadata_endpoint_blocked; 404 отдан фактической причиной",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real public network read + real SafeFetcher policy",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 7b. F4 external-code scenarios → SXR-F4-01 (+ SXR-F2-01, SXR-L5-01)
# ═════════════════════════════════════════════════════════════════════════════

#: Публичный внешний репозиторий для сценариев F4. Маленькое дерево (16
#: файлов) + два файла, где ОДИН реально ссылается на другой по имени
#: (`AppTest.java` → `App`), поэтому related-sources проверяются на фактическом
#: содержимом, а не на догадке. Репозиторий учебный/архивный: содержимое и
#: ветка `master` стабильны.
EXTERNAL_REPO = "githubtraining/hellogitworld"
EXTERNAL_BRANCH = "master"
#: Основной файл цепочки: `public class AppTest extends TestCase` + `AppTest(…)`
#: → stem-идентификатор `app` указывает на `App.java` (проверено чистыми
#: функциями SourceReader: rank_sibling_paths).
EXTERNAL_CHAIN_PATH = "src/test/java/com/github/AppTest.java"
EXTERNAL_CHAIN_SIBLING = "src/main/java/com/github/App.java"
#: Поиск файла/символа: `main(` есть только в `App.java` (locate → ranked →
#: locate_symbol_line), поэтому результат детерминирован.
EXTERNAL_SEARCH_SYMBOL = "main"
EXTERNAL_SEARCH_EXPECT_PATH = "src/main/java/com/github/App.java"
#: Несуществующий репозиторий: GitHub обязан ответить фактической причиной
#: (404/private/rate limit), без обхода прав. Один запрос, без ретраев.
EXTERNAL_MISSING_REPO = "githubtraining/canary-does-not-exist-7f3a"
#: Фактические коды отказа внешнего чтения (причина, а не «нет доступа»).
EXTERNAL_FACTUAL_FAILURE_CODES = frozenset({
    "source_missing", "auth_failed", "rate_limit", "provider_unavailable",
})
#: Независимая естественная формулировка запроса о коде внешнего проекта
#: (не пересекается с _DIRECT_FORMULATIONS и не является командой).
EXTERNAL_NATURAL_REQUEST = (
    "Наткнулся на репозиторий githubtraining/hellogitworld. Посмотри по "
    "исходникам, что делает метод main в файле "
    "src/main/java/com/github/App.java, и ответь коротко по делу."
)


def _external_chain_facts(payload: dict) -> dict:
    """Факты по ответу `read`: primary + реально прочитанная цепочка."""
    files = [f for f in (payload.get("files") or []) if isinstance(f, dict)]
    primary = next((f for f in files
                    if str(f.get("role") or "") == "primary"), None)
    siblings = [f for f in files if str(f.get("role") or "") != "primary"]
    verified_siblings = [
        f for f in siblings
        if bool(f.get("verified")) and int(f.get("snippet_chars") or 0) > 0]
    primary_path = str(payload.get("path") or "")
    not_checked = payload.get("not_checked")
    return {
        "status": payload.get("status"),
        "commit": str(payload.get("commit") or "").lower(),
        "path": payload.get("path") or None,
        "verified": bool(payload.get("verified")),
        "source_kind": payload.get("source_kind"),
        "network_calls": int(payload.get("network_calls") or 0),
        "snippet_chars": int(payload.get("snippet_chars") or 0),
        "verified_url": str(payload.get("verified_url") or ""),
        "sibling_paths": [str(f.get("path") or "") for f in siblings],
        "verified_sibling_paths": [str(f.get("path") or "")
                                   for f in verified_siblings],
        "distinct_verified_sibling": any(
            str(f.get("path") or "") not in ("", primary_path)
            for f in verified_siblings),
        "files_read": (not_checked.get("files_read")
                       if isinstance(not_checked, dict) else None),
        "has_primary": bool(primary) and int(
            (primary or {}).get("snippet_chars") or 0) > 0,
    }


def _external_search_facts(payload: dict, *, expected_path: str,
                           expected_commit: str) -> dict:
    """Факты поиска файла/символа (`locate`) с проверкой точного commit."""
    commit = str(payload.get("commit") or "").lower()
    path = str(payload.get("path") or "")
    return {
        "status": payload.get("status"),
        "stage": payload.get("stage"),
        "path": path or None,
        "commit": commit or None,
        "verified": bool(payload.get("verified")),
        "source_kind": payload.get("source_kind"),
        "symbol": payload.get("symbol"),
        "symbol_found": bool(payload.get("symbol_found")),
        "line_range": list(payload.get("line_range") or []),
        "snippet_chars": int(payload.get("snippet_chars") or 0),
        "network_calls": int(payload.get("network_calls") or 0),
        "candidate_paths": list(payload.get("candidate_paths") or [])[:5],
        "path_matches": bool(expected_path) and path == expected_path,
        "commit_matches": bool(expected_commit)
        and commit == str(expected_commit).lower(),
    }


def _external_link_facts(payload: dict, *, expected_commit: str,
                         expected_path: str) -> dict:
    """Факты чтения по blob-ссылке: та же commit/path идентичность."""
    commit = str(payload.get("commit") or "").lower()
    path = str(payload.get("path") or "")
    return {
        "status": payload.get("status"),
        "stage": payload.get("stage"),
        "path": path or None,
        "commit": commit or None,
        "verified": bool(payload.get("verified")),
        "source_kind": payload.get("source_kind"),
        "snippet_chars": int(payload.get("snippet_chars") or 0),
        "network_calls": int(payload.get("network_calls") or 0),
        "path_matches": bool(expected_path) and path == expected_path,
        "commit_matches": bool(expected_commit)
        and commit == str(expected_commit).lower(),
    }


def _external_failure_facts(payload: dict) -> dict:
    """Факты отказа внешнего источника: причина названа, прав не обходим."""
    err = payload.get("error_detail")
    err = err if isinstance(err, dict) else {}
    code = str(payload.get("error") or err.get("code") or "")[:64]
    status = str(payload.get("status") or "")
    calls = int(payload.get("network_calls") or 0)
    return {
        "status": status,
        "stage": payload.get("stage"),
        "code": code,
        "detail": str(err.get("detail") or "")[:64],
        "http": err.get("http"),
        "retryable": bool(payload.get("retryable", err.get("retryable"))),
        "network_calls": calls,
        "factual": status in ("error", "not_found")
        and code in EXTERNAL_FACTUAL_FAILURE_CODES,
        "not_read": status != "ok",
        "no_retries": calls <= 2,
    }


def _external_capability_facts(schemas, commands) -> dict:
    """Внешний код — ОДИН tool с тремя операциями, а не отдельная команда."""
    tool = dict(getattr(schemas, "TOOL_READ_SOURCE_CODE", {}) or {})
    function = tool.get("function") or {}
    params = (function.get("parameters") or {}).get("properties") or {}
    operations = list((params.get("operation") or {}).get("enum") or [])
    name = str(function.get("name") or "")
    tools = [t for t in (getattr(schemas, "TOOL_CALLING_TOOLS", []) or [])
             if isinstance(t, dict)]
    names = [str(((t.get("function") or {}).get("name") or "")) for t in tools]
    github_like_tools = [n for n in names
                         if re.search(r"(?i)github|source|read_?code", n)]
    triggers: list[str] = []
    for _group, items in (getattr(commands, "FUNCTIONAL_COMMANDS", {}) or {}).items():
        for item in items or ():
            triggers.append(str(item))
    github_like_commands = [t for t in triggers
                            if re.search(r"(?i)github|исходник|репозитор", t)]
    return {
        "tool_name": name,
        "tool_operations": operations,
        "tool_count": len(names),
        "github_like_tools": github_like_tools,
        "command_triggers": len(triggers),
        "github_like_commands": github_like_commands,
        "single_tool": bool(name) and github_like_tools == [name],
        "operations_cover": set(operations) == {"discover", "locate", "read"},
        "no_separate_command": not github_like_commands,
    }


async def check_external_scenarios(ctx: HarnessContext) -> CheckOutcome:
    """F4: поиск файла/символа, blob-ссылка, related sources, отказ, команда."""
    from services.tool_router import ToolContext, ToolDeps, ToolRouter

    a = Asserts()
    details: dict[str, Any] = {
        "offline": bool(ctx.args.offline),
        "scenario": {
            "repo": EXTERNAL_REPO,
            "branch": EXTERNAL_BRANCH,
            "chain_path": EXTERNAL_CHAIN_PATH,
            "chain_sibling": EXTERNAL_CHAIN_SIBLING,
            "search_symbol": EXTERNAL_SEARCH_SYMBOL,
            "search_expect_path": EXTERNAL_SEARCH_EXPECT_PATH,
            "missing_repo": EXTERNAL_MISSING_REPO,
            "call_budget_policy": (
                "реальные запросы минимизированы: commit/verified_url берутся "
                "из уже полученного ответа, повторные запросы с теми же "
                "аргументами кэшируются в пределах прогона"),
        },
    }
    if ctx.args.offline:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "F4-сценарии пропущены: --offline",
            {**details, "assertions": a.report()},
            EVIDENCE_UNAVAILABLE,
            "offline: external provider path not contacted",
        )

    router = ToolRouter(ToolDeps(search=None, memory=None))
    tool_ctx = ToolContext(0, "canary external scenarios")
    cache: dict[str, dict] = {}

    async def _dispatch(args: dict, *, fresh: bool = False) -> dict:
        key = json.dumps(args, sort_keys=True, ensure_ascii=False)
        if not fresh and key in cache:
            cached = dict(cache[key])
            cached["_cache_hit"] = True
            return cached
        out = await router.dispatch("read_source_code", args, tool_ctx)
        payload: dict = {"raw": _clip(out, 300)}
        if str(out).strip().startswith("{"):
            try:
                payload = json.loads(out)
            except ValueError:
                payload = {"raw": _clip(out, 300)}
        if payload.get("status") == "ok":
            cache[key] = dict(payload)
        return payload

    # 1) Публичный репозиторий + чтение по ветке + переход к связанным файлам.
    chain_payload = await _dispatch({
        "operation": "read", "repo": EXTERNAL_REPO,
        "ref": EXTERNAL_BRANCH, "path": EXTERNAL_CHAIN_PATH})
    chain = _external_chain_facts(chain_payload)
    details["chain_read"] = chain
    a.expect("external_public_repo_read_ok", chain["status"] == "ok", chain)
    a.expect("external_branch_read_identity",
             len(chain["commit"] or "") == 40
             and str(chain["path"] or "") == EXTERNAL_CHAIN_PATH
             and chain["source_kind"] == "file",
             chain)
    a.expect("external_branch_read_verified", chain["verified"], chain)
    a.expect("external_read_uses_network", chain["network_calls"] > 0, chain)
    a.expect("external_related_sources_read",
             chain["has_primary"] and chain["distinct_verified_sibling"],
             chain)
    details["related_sources"] = {
        "verified_sibling_paths": chain["verified_sibling_paths"],
        "expected_sibling_present": EXTERNAL_CHAIN_SIBLING
        in chain["verified_sibling_paths"],
        "files_read": chain["files_read"],
    }

    commit = chain["commit"]

    # 2) Поиск файла/символа в публичном репозитории на ТОЧНОМ commit.
    search_payload = await _dispatch({
        "operation": "locate", "repo": EXTERNAL_REPO,
        "ref": commit or EXTERNAL_BRANCH, "symbol": EXTERNAL_SEARCH_SYMBOL})
    search = _external_search_facts(
        search_payload, expected_path=EXTERNAL_SEARCH_EXPECT_PATH,
        expected_commit=commit)
    details["symbol_search"] = search
    a.expect("external_symbol_search_ok",
             search["status"] == "ok" and search["stage"] == "locator", search)
    a.expect("external_symbol_search_found_path", search["path_matches"],
             search)
    a.expect("external_symbol_search_symbol_found", search["symbol_found"],
             search)
    a.expect("external_symbol_search_exact_commit", search["commit_matches"],
             search)
    a.expect("external_symbol_search_verified", search["verified"], search)

    # 3) Чтение по blob-ссылке (verified_url предыдущего ответа) — та же
    #    commit/path идентичность, без отдельного «github»-вызова.
    link_url = str(chain["verified_url"] or search.get("verified_url") or "")
    details["link_url_present"] = bool(link_url)
    if link_url:
        link_payload = await _dispatch({"operation": "read", "url": link_url})
    else:
        link_payload = {"status": "unavailable", "error": "no_verified_url"}
    link = _external_link_facts(
        link_payload, expected_commit=commit, expected_path=EXTERNAL_CHAIN_PATH)
    details["link_read"] = link
    a.expect("external_link_read_ok", link["status"] == "ok", link)
    a.expect("external_link_read_identity",
             link["path_matches"] and link["commit_matches"], link)
    a.expect("external_link_read_verified",
             link["verified"] and link["source_kind"] == "file", link)

    # 4) Отказ: несуществующий/недоступный репозиторий → фактическая причина,
    #    один bounded вызов, без обхода прав.
    missing_payload = await _dispatch({
        "operation": "read", "repo": EXTERNAL_MISSING_REPO})
    failure = _external_failure_facts(missing_payload)
    details["missing_repo"] = failure
    a.expect("external_missing_repo_factual", failure["factual"], failure)
    a.expect("external_missing_repo_not_read", failure["not_read"], failure)
    a.expect("external_missing_repo_no_retries", failure["no_retries"],
             failure)

    # 5) Отдельной GitHub-команды нет: возможность живёт как ОДИН tool.
    from services import command_registry, tool_schemas

    capability = _external_capability_facts(tool_schemas, command_registry)
    details["capability"] = capability
    a.expect("external_capability_single_tool", capability["single_tool"],
             capability)
    a.expect("external_capability_three_operations",
             capability["operations_cover"], capability)
    a.expect("external_capability_no_command",
             capability["no_separate_command"], capability)

    network_total = (chain["network_calls"]
                     + search["network_calls"]
                     + link["network_calls"]
                     + failure["network_calls"])
    details["network_calls_total"] = network_total
    a.expect("external_scenarios_network_observed", network_total > 0,
             network_total)

    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "F4-сценарии внешнего кода не подтверждены: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION,
            "real GitHub/provider path executed; contract not satisfied",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "публичный репозиторий прочитан по ветке (verified, точный commit); "
        "поиск символа дал тот же commit и файл; чтение по blob-ссылке дало ту "
        "же идентичность; переход к связанным источникам — реальное чтение "
        "смежного файла; недоступный репозиторий назван фактической причиной; "
        "отдельной GitHub-команды нет (один tool, три операции)",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real public GitHub read/search/link/follow-up + factual refusal",
    )


async def check_external_natural_request(ctx: HarnessContext) -> CheckOutcome:
    """F4: естественный запрос о коде внешнего проекта через Direct/L1.

    Ровно ОДИН реальный provider-вызов (`--allow-provider-calls`, общий cap).
    Если модель не запросила чтение исходников — честный `not_observed` с
    трассой решения (никакой подмены «мы сами вызвали tool»).
    """
    from config.settings import settings
    from services import direct_capabilities
    from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT
    from services.direct_l1 import build_l1_context, parse_l1_plan
    from services.prompt_style_blocks import resolve_prompt
    from services.tool_router import ToolContext, ToolDeps, ToolRouter

    a = Asserts()
    details: dict[str, Any] = {
        "query": EXTERNAL_NATURAL_REQUEST,
        "repo": EXTERNAL_REPO,
        "path": EXTERNAL_SEARCH_EXPECT_PATH,
        "offline": bool(ctx.args.offline),
    }
    if ctx.args.offline or not ctx.args.allow_provider_calls:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "естественный запрос о внешнем коде не наблюдался: provider calls "
            "выключены (--allow-provider-calls отсутствует или --offline)",
            {**details, "assertions": a.report(),
             "provider_calls": {"used": ctx.provider_calls,
                                "denied": ctx.provider_denied}},
            EVIDENCE_UNAVAILABLE,
            "provider calls disabled; production LLM decision unavailable",
        )

    await ctx.load_config_cache()  # read-only; реальные model/key
    if not ctx.take_provider_call():
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "provider-бюджет исчерпан до естественного запроса",
            {**details, "assertions": a.report(),
             "provider_calls": {"used": ctx.provider_calls,
                                "denied": ctx.provider_denied}},
            EVIDENCE_UNAVAILABLE,
            "provider budget denied the L1 call",
        )

    system_prompt = resolve_prompt(
        "prompts.direct_l1_planner_system_prompt",
        DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    )
    temperature = float(getattr(settings, "LLM_TEMPERATURE", 0.7) or 0.0)
    plan = None
    raw_chars = 0
    try:
        l1_context = build_l1_context(
            query=EXTERNAL_NATURAL_REQUEST, speaker="owner", addressee="bot",
            capabilities=("source_code",),
        )
        raw = await asyncio.wait_for(
            ctx.llm().generate(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": l1_context}],
                temperature=temperature, chat_id=None, module="canary",
                step="l1_external",
            ),
            timeout=120,
        )
        raw_chars = len(str(raw or ""))
        plan = parse_l1_plan(raw)
    except Exception as exc:
        details["error"] = type(exc).__name__
        details["error_detail"] = _clip(str(exc), 200)
    details["decision"] = None if plan is None else {
        "action": plan.action,
        "tool_policy": plan.tool_policy,
        "capabilities_needed": list(plan.capabilities_needed),
        "execution_mode": plan.execution_mode,
        "execution_mode_source": plan.execution_mode_source,
        "response_act": plan.response_act,
        "raw_chars": raw_chars,
    }
    selected_tool = ""
    for capability_name in (list(plan.capabilities_needed) if plan else []):
        for candidate in direct_capabilities.CAPABILITY_TOOLS.get(
                capability_name, ()):
            if candidate == "read_source_code":
                selected_tool = candidate
                break
        if selected_tool:
            break
    details["selected_tool"] = selected_tool or None

    execution: dict | None = None
    if selected_tool == "read_source_code":
        router = ToolRouter(ToolDeps(search=None, memory=None))
        tool_ctx = ToolContext(0, EXTERNAL_NATURAL_REQUEST)
        dispatched = {"operation": "read", "repo": EXTERNAL_REPO,
                      "ref": EXTERNAL_BRANCH, "path": EXTERNAL_SEARCH_EXPECT_PATH}
        details["dispatched_arguments"] = dispatched
        try:
            out = await router.dispatch("read_source_code", dispatched, tool_ctx)
            payload = json.loads(out) if str(out).strip().startswith("{") else {}
            execution = {
                "status": payload.get("status"),
                "stage": payload.get("stage"),
                "repo": payload.get("repo"),
                "path": payload.get("path"),
                "commit": str(payload.get("commit") or "").lower() or None,
                "verified": bool(payload.get("verified")),
                "source_kind": payload.get("source_kind"),
                "snippet_chars": int(payload.get("snippet_chars") or 0),
                "network_calls": int(payload.get("network_calls") or 0),
                "error": (payload.get("error")
                          if isinstance(payload.get("error"), str) else None),
            }
        except Exception as exc:
            execution = {"status": "exception",
                         "error": type(exc).__name__,
                         "error_detail": _clip(str(exc), 200)}
        details["tool_execution"] = execution

    details["provider_calls"] = {
        "used": ctx.provider_calls,
        "denied": ctx.provider_denied,
        "max_provider_calls": int(ctx.args.max_provider_calls),
    }
    a.expect("natural_request_provider_call", int(ctx.provider_calls) >= 1,
             details["provider_calls"])
    a.expect("natural_request_decision_parsed", plan is not None,
             details.get("decision"))
    a.expect("natural_request_selected_source_tool",
             selected_tool == "read_source_code", details.get("decision"))
    a.expect("natural_request_tool_executed",
             bool(execution) and (execution or {}).get("status") == "ok",
             execution)
    a.expect("natural_request_tool_verified",
             bool((execution or {}).get("verified"))
             and str((execution or {}).get("path") or "")
             == EXTERNAL_SEARCH_EXPECT_PATH
             and (execution or {}).get("source_kind") == "file",
             execution)
    a.expect("natural_request_tool_network",
             int((execution or {}).get("network_calls") or 0) > 0, execution)

    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "естественный запрос о внешнем коде не подтверждён: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION,
            "real L1 provider call executed; decision/execution not satisfied",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "естественный запрос о внешнем коде: L1 выбрал capability "
        "source_code, production tool реально прочитал файл на GitHub "
        "(verified, точный path)",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real provider decision + real source-read execution",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 8. diagnostic variants → SXR-L6-01
# ═════════════════════════════════════════════════════════════════════════════
async def _run_variant(rounds, responder, *, finalizer_error=None,
                       final_text="canary: данные сохранены и изложены"):
    from services.tool_loop import chat_with_tools
    from services.tool_router import ToolContext

    llm = ScriptedLLM(rounds, final_text=final_text,
                      finalizer_error=finalizer_error)
    router = StubRouter(responder)
    ctx_tool = ToolContext(0, "canary variant")
    result = await chat_with_tools(
        llm,
        [{"role": "user", "content": "canary diagnostic variant"}],
        tools=_LOOP_TOOL_SCHEMAS,
        router=router,
        ctx=ctx_tool,
        chat_id=0,
        correlation_id="canary-smart-live-variant",
    )
    return result, llm, router, ctx_tool


async def check_diagnostic_variants(ctx: HarnessContext) -> CheckOutcome:
    a = Asserts()
    details: dict[str, Any] = {"variants": {}}

    def _record(label: str, result, router, llm=None,
                extra: dict | None = None) -> dict:
        entry = {
            "text_chars": len(str(result)),
            "degraded": bool(getattr(result, "degraded", False)),
            "reason": str(getattr(result, "reason", "")),
            "finalize_mode": str(getattr(result, "finalize_mode", "")),
            "tool_calls": len(router.calls),
            "tool_names": sorted({c["tool"] for c in router.calls}),
            "envelopes": _envelope_stats(result, llm),
            "fallback_phrase": TOOL_LOOP_FALLBACK_PHRASE in str(result),
            "text_head": str(result)[:220],
        }
        if extra:
            entry.update(extra)
        details["variants"][label] = entry
        return entry

    # 1) все источники доступны (поиск + фактчек)
    try:
        rounds = [
            ("", [_tool_call("v1a", "execute_web_search",
                             {"query": "canary alpha"}),
                  _tool_call("v1b", "fact_check",
                             {"claim": "canary beta"})]),
            ("canary: подтверждено обоими источниками", None),
        ]
        result, _llm, router, _ctx = await _run_variant(
            rounds, lambda n, arg, i: _ok_source(n, f"v1-{i}"))
        entry = _record("all_sources", result, router)
        a.expect("v1_text", entry["text_chars"] > 0)
        a.expect("v1_no_stub", not entry["fallback_phrase"])
        a.expect("v1_two_calls", entry["tool_calls"] == 2, entry["tool_calls"])
    except Exception as exc:
        details["variants"]["all_sources"] = {"error": type(exc).__name__}
        a.expect("v1_ran", False, type(exc).__name__)

    # 2) один источник отказал → данные сохранены, отказ виден
    try:
        rounds = [
            ("", [_tool_call("v2a", "execute_web_search",
                             {"query": "canary alpha"}),
                  _tool_call("v2b", "fetch_article",
                             {"url": "https://example.org/canary/beta"})]),
            ("canary: один источник подтверждён, второй недоступен", None),
        ]

        def responder(name, arg, index):
            if name == "fetch_article":
                return _error_source("provider_unavailable")
            return _ok_source(name, f"v2-{index}")

        result, _llm, router, _ctx = await _run_variant(rounds, responder)
        entry = _record("one_failed", result, router)
        ok_entries = [e for e in (result.tool_results or [])
                      if str(e.get("status")) == "ok"]
        err_entries = [e for e in (result.tool_results or [])
                       if str(e.get("status")) not in ("ok", "empty")]
        a.expect("v2_ok_data_preserved", len(ok_entries) == 1, entry["envelopes"])
        a.expect("v2_failure_visible", len(err_entries) == 1, entry["envelopes"])
        a.expect("v2_text_present", entry["text_chars"] > 0)
        a.expect("v2_no_stub", not entry["fallback_phrase"])
    except Exception as exc:
        details["variants"]["one_failed"] = {"error": type(exc).__name__}
        a.expect("v2_ran", False, type(exc).__name__)

    # 3) GitHub заблокирован, локальный код доступен
    try:
        rounds = [
            ("", [_tool_call("v3a", "read_source_code",
                             {"operation": "read", "repo": "remote/repo"}),
                  _tool_call("v3b", "read_source_code",
                             {"operation": "read", "repo": "self"})]),
            ("canary: удалённый источник заблокирован, локальный прочитан", None),
        ]

        def responder(name, arg, index):
            if arg.get("repo") == "remote/repo":
                return _error_source("destination_blocked", stage="resolve")
            return {
                "status": "ok", "verified": True, "source_kind": "file",
                "network_calls": 0, "snippet": "local code fragment",
                "line_range": [1, 10],
            }

        result, _llm, router, _ctx = await _run_variant(rounds, responder)
        entry = _record("github_blocked_local_ok", result, router)
        a.expect("v3_local_data_preserved", "local code fragment" in str(result)
                 or "local code fragment" in (result.tool_context or ""),
                 entry["envelopes"])
        a.expect("v3_no_stub", not entry["fallback_phrase"])
    except Exception as exc:
        details["variants"]["github_blocked_local_ok"] = {
            "error": type(exc).__name__}
        a.expect("v3_ran", False, type(exc).__name__)

    # 4) локальный недоступен, удалённый доступен
    try:
        rounds = [
            ("", [_tool_call("v4a", "read_source_code",
                             {"operation": "read", "repo": "self"}),
                  _tool_call("v4b", "read_source_code",
                             {"operation": "read", "repo": "remote/repo"})]),
            ("canary: локальный недоступен, удалённый прочитан", None),
        ]

        def responder(name, arg, index):
            if arg.get("repo") == "self":
                return _error_source("local_source_unavailable")
            return {
                "status": "ok", "verified": True, "source_kind": "github",
                "network_calls": 1, "snippet": "remote code fragment",
                "line_range": [1, 10],
            }

        result, _llm, router, _ctx = await _run_variant(rounds, responder)
        entry = _record("local_down_remote_ok", result, router)
        a.expect("v4_remote_data_preserved",
                 "remote code fragment" in str(result)
                 or "remote code fragment" in (result.tool_context or ""),
                 entry["envelopes"])
        a.expect("v4_no_stub", not entry["fallback_phrase"])
    except Exception as exc:
        details["variants"]["local_down_remote_ok"] = {
            "error": type(exc).__name__}
        a.expect("v4_ran", False, type(exc).__name__)

    # 5) исследование невозможно (все источники падают, затем LLM-обрыв)
    try:
        from services.llm_client import LLMError

        rounds = [
            ("", [_tool_call("v5a", "execute_web_search",
                             {"query": "canary impossible"})]),
            LLMError("canary: provider unreachable mid-research"),
        ]
        result, _llm, router, _ctx = await _run_variant(
            rounds, lambda n, arg, i: _error_source("provider_unavailable"),
            final_text="")
        entry = _record("investigation_impossible", result, router)
        a.expect("v5_honest_status",
                 entry["finalize_mode"] == "structured_partial"
                 and entry["text_chars"] > 0, entry)
        a.expect("v5_no_fake_success",
                 "provider_unavailable" in str(result)
                 or "не" in str(result).lower(), entry["text_head"])
        a.expect("v5_no_meaningless_stub", not entry["fallback_phrase"], entry)
    except Exception as exc:
        details["variants"]["investigation_impossible"] = {
            "error": type(exc).__name__}
        a.expect("v5_ran", False, type(exc).__name__)

    # 6) финальный LLM недоступен → структурный partial из evidence
    try:
        from services.llm_client import LLMError

        ok_call = _tool_call("v6a", "execute_web_search",
                             {"query": "canary preserved"})
        rounds = [
            ("", [ok_call]),
            ("", [ok_call]),   # duplicate → no_progress
            ("", [ok_call]),   # duplicate → no_progress (2)
        ]
        result, _llm, router, _ctx = await _run_variant(
            rounds, lambda n, arg, i: _ok_source(n, "v6"),
            finalizer_error=LLMError("canary: finalizer unavailable"),
            final_text="")
        entry = _record("final_llm_unavailable", result, router)
        a.expect("v6_structured_partial",
                 entry["finalize_mode"] == "structured_partial", entry)
        a.expect("v6_data_preserved",
                 "canary source v6" in str(result)
                 or "canary source v6" in (result.tool_context or ""), entry)
        a.expect("v6_no_stub", not entry["fallback_phrase"], entry)
    except Exception as exc:
        details["variants"]["final_llm_unavailable"] = {
            "error": type(exc).__name__}
        a.expect("v6_ran", False, type(exc).__name__)

    # 7) технический дедлайн (operator fuse) во время исследования
    try:
        import asyncio as _asyncio

        async def slow_ok(name, arg, index):
            # Первый вызов быстрый (данные уже собраны), второй пересекает
            # fuse на границе следующего раунда.
            if index >= 1:
                await _asyncio.sleep(0.5)
            return _ok_source(name, f"v7-{index}")

        def slow_responder(name, arg, index):
            raise RuntimeError("unreachable")

        class _SlowRouter(StubRouter):
            async def dispatch(self, name, arguments, ctx):
                self.calls.append({"tool": name, "arguments": dict(arguments or {})})
                return json.dumps(
                    await slow_ok(name, arguments, len(self.calls) - 1),
                    ensure_ascii=False)

        from services.tool_loop import chat_with_tools
        from services.tool_router import ToolContext

        llm = ScriptedLLM(
            [("", [_tool_call("v7a", "execute_web_search",
                              {"query": "canary deadline 1"})]),
             ("", [_tool_call("v7b", "execute_web_search",
                              {"query": "canary deadline 2"})]),
             ("canary: данные собраны до дедлайна", None)],
            final_text="canary: данные собраны до дедлайна")
        router = _SlowRouter(slow_responder)
        with patched_tool_loop_settings(MCA_TOOL_CHAIN_TIMEOUT_SECONDS=0.2):
            result = await chat_with_tools(
                llm,
                [{"role": "user", "content": "canary deadline variant"}],
                tools=_LOOP_TOOL_SCHEMAS,
                router=router,
                ctx=ToolContext(0, "canary deadline"),
                chat_id=0,
                correlation_id="canary-smart-live-deadline",
            )
        entry = _record("technical_deadline", result, router)
        a.expect("v7_deadline_reason", entry["reason"] == "chain_timeout", entry)
        a.expect("v7_degraded_honestly", entry["degraded"], entry)
        a.expect("v7_data_preserved", "canary source v7" in str(result)
                 or "canary source v7" in (result.tool_context or ""), entry)
        a.expect("v7_no_stub", not entry["fallback_phrase"], entry)
    except Exception as exc:
        details["variants"]["technical_deadline"] = {
            "error": type(exc).__name__, "detail": _clip(str(exc), 200)}
        a.expect("v7_ran", False, type(exc).__name__)

    details["shared_mechanism"] = (
        "7 вариантов исполнены единым production tool-loop "
        "(services.tool_loop.chat_with_tools) с контролируемой инъекцией "
        "LLM/роутера; имена инструментов покрывают поиск (execute_web_search), "
        "фактчек (fact_check) и чтение источника (read_source_code)."
    )
    a.expect("seven_variants_executed", len(details["variants"]) == 7,
             len(details["variants"]))

    if a.failures:
        return _plumbing_outcome(
            a, details,
            "диагностические варианты не подтверждены: "
            + ", ".join(a.failures[:6]),
        )
    return _plumbing_outcome(
        a, details,
        "все 7 вариантов сохраняют полученные данные, различают отказы и не "
        "публикуют бессмысленную заглушку при наличии evidence",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 9. real checkup path → SXR-H3-01, SXR-H4-01, SXR-L7-01
# ═════════════════════════════════════════════════════════════════════════════


async def _systemctl_show(unit: str) -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "show", unit,
            "--property=ActiveState,MainPID,User,ExecMainStartTimestamp,"
            "ExecMainStartTimestampMonotonic",
            "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=10)
    except (OSError, asyncio.TimeoutError, NotImplementedError) as exc:
        return {"error": type(exc).__name__}
    text = (out or b"").decode("utf-8", errors="replace")
    props: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    if (proc.returncode or 0) != 0:
        props["error"] = _clip((err or b"").decode("utf-8", "replace"), 160)
    return props


async def _proc_owner(pid: int) -> dict:
    try:
        status = Path(f"/proc/{int(pid)}/status").read_text(
            encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": type(exc).__name__}
    out: dict[str, str] = {}
    for line in status.splitlines():
        if line.startswith(("Uid:", "Gid:", "Name:")):
            out[line.split(":", 1)[0]] = line.split(":", 1)[1].strip()
    return out


async def check_checkup_real(ctx: HarnessContext) -> CheckOutcome:
    a = Asserts()
    details: dict[str, Any] = {}

    await ctx.load_config_cache()  # no-op when PG unavailable; read-only
    logs_text, used_fallback, log_state, journal_state = await ctx.runtime_logs()
    details["logs"] = {
        "chars": len(logs_text),
        "used_fallback": bool(used_fallback),
        "log_state": log_state,
        "journal_state": journal_state,
    }
    a.expect("journal_read_ok",
             log_state == "ok" and bool(logs_text), details["logs"])
    a.expect("journal_not_fallback_only", journal_state != "not_available",
             details["logs"])

    # H3: сам unit, пользователь процесса и «не root»
    service = await _systemctl_show(str(ctx.args.checkup_unit or "admin_bot"))
    details["service"] = service
    pid = 0
    try:
        pid = int(service.get("MainPID") or 0)
    except ValueError:
        pid = 0
    owner = await _proc_owner(pid) if pid else {}
    details["process_owner"] = owner
    uid = str(owner.get("Uid") or "").split()[0] if owner.get("Uid") else ""
    service_user = str(service.get("User") or "").strip().lower()
    non_root = (uid != "0") if uid else (bool(service_user)
                                         and service_user != "root")
    a.expect("service_active", service.get("ActiveState") == "active", service)
    a.expect("service_pid_present", pid > 0, service)
    a.expect("bot_not_root", bool(non_root),
             {"uid": uid or None, "service_user": service_user or None})
    details["harness_uid"] = os.geteuid() if hasattr(os, "geteuid") else None
    details["harness_not_root_note"] = (
        "харнесс может быть запущен от root (DevOps); проверяется unit-процесс "
        "бота, а не процесс харнесса")

    # H4 + runtime identity: manifest ↔ git ↔ process start
    from services import deploy_identity

    process_started_at = None
    started_raw = str(service.get("ExecMainStartTimestamp") or "")
    # Locale-independent: start = now - (monotonic_now - exec_monotonic/1e6).
    mono_raw = str(service.get("ExecMainStartTimestampMonotonic") or "")
    if mono_raw:
        try:
            mono_seconds = int(mono_raw) / 1_000_000.0
            monotonic_now = time.clock_gettime(time.CLOCK_MONOTONIC)
            process_started_at = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(
                seconds=max(0.0, monotonic_now - mono_seconds))
        except (ValueError, OSError):
            process_started_at = None
    if process_started_at is None and started_raw:
        for fmt in ("%a %Y-%m-%d %H:%M:%S %Z",
                    "%Y-%m-%d %H:%M:%S %Z"):
            try:
                process_started_at = _dt.datetime.strptime(
                    started_raw, fmt).replace(tzinfo=_dt.timezone.utc)
                break
            except ValueError:
                continue
    try:
        identity = await asyncio.wait_for(
            asyncio.to_thread(deploy_identity.collect_identity,
                              ctx.repo_root,
                              process_started_at=process_started_at),
            timeout=60,
        )
    except Exception as exc:
        identity = {"code": "unavailable", "reason": type(exc).__name__}
    details["deploy_identity"] = {
        key: identity.get(key)
        for key in (
            "code", "reason", "deployed_sha", "checkout_sha",
            "process_started_at", "deployed_at", "effect", "previous_sha",
            "version_provenance", "conflict", "local_source_verification",
            "dirty", "upstream_head",
        )
    }
    details["deploy_identity"]["branch"] = (
        identity.get("local_identity") or {}).get("branch")
    a.expect("runtime_identity_verified",
             identity.get("code") == "verified_deployed",
             identity.get("code") or identity.get("reason"))
    deployed_sha = str(identity.get("deployed_sha") or "").lower()
    checkout_sha = str(identity.get("checkout_sha") or "").lower()
    a.expect("runtime_sha_matches_checkout",
             bool(deployed_sha) and deployed_sha == checkout_sha,
             {"deployed": deployed_sha or None, "checkout": checkout_sha or None})
    manifest = ctx.repo_root / ".deploy" / "release.json"
    a.expect("deploy_manifest_exists", manifest.is_file(), str(manifest.name))
    manifest_data: dict = {}
    if manifest.is_file():
        try:
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest_data = {}
    details["manifest"] = {
        key: manifest_data.get(key)
        for key in ("schema", "deployed_sha", "version", "deployed_at",
                    "effect", "previous_sha", "release_branch",
                    "dirty_tracked")
    }
    a.expect("manifest_valid",
             bool(manifest_data.get("deployed_sha"))
             and bool(manifest_data.get("version")),
             details["manifest"])
    a.expect("manifest_matches_process",
             str(manifest_data.get("deployed_sha") or "").lower()
             == deployed_sha,
             {"manifest": manifest_data.get("deployed_sha"),
              "process": deployed_sha or None})
    a.expect("manifest_matches_checkout",
             bool(checkout_sha)
             and str(manifest_data.get("deployed_sha") or "").lower()
             == checkout_sha,
             {"manifest": manifest_data.get("deployed_sha"),
              "checkout": checkout_sha or None})
    try:
        vprovenance = identity.get("version_provenance") or {}
        runtime_version = str((vprovenance or {}).get("runtime") or "")
    except Exception:
        runtime_version = ""
    details["runtime_version"] = runtime_version or None
    a.expect("manifest_version_matches_runtime",
             bool(runtime_version)
             and str(manifest_data.get("version") or "") == runtime_version,
             {"manifest": manifest_data.get("version"),
              "runtime": runtime_version or None})

    # локальный источник для чекапа/исследования
    self_identity = await ctx.identity()
    details["self_repo_identity"] = {
        key: self_identity.get(key)
        for key in ("source", "ref_source", "verification", "repo", "ref",
                    "deployed_matches_checkout", "note")
    }
    a.expect("checkup_local_source_usable",
             self_identity.get("source") in ("local", "remote"),
             self_identity.get("source"))

    # production CheckupService: реальные логи + collector + (опционально) LLM
    from services.checkup_service import CheckupService
    from services.diagnostic_collector import DiagnosticCollector
    from services.runtime_probes import ProbeDeps, ProbeLimits

    db = await ctx.sqlite()
    deps = ProbeDeps(db=db, memory=None, logs_fetcher=None,
                     status=None, repo_root=str(ctx.repo_root))
    collector = DiagnosticCollector(deps=deps, limits=ProbeLimits.from_env())
    bundle: dict = {}
    facts_text = ""
    if ctx.args.offline:
        details["collector_skipped"] = "offline"
    else:
        try:
            bundle_obj, facts_text = await asyncio.wait_for(
                collector.collect_for_checkup(
                    logs_text=logs_text, used_fallback=used_fallback,
                    chat_id=None, log_state=log_state,
                    journal_state=journal_state),
                timeout=90,
            )
            bundle = (bundle_obj.to_dict()
                      if hasattr(bundle_obj, "to_dict") else {})
        except Exception as exc:
            details["collector_error"] = type(exc).__name__
    cov = (bundle or {}).get("coverage") or {}
    details["facts"] = {
        "facts_chars": len(facts_text),
        "bundle_status": (bundle or {}).get("status"),
        "coverage_ok": cov.get("ok"),
        "coverage_failed": cov.get("failed"),
        "coverage_missing": cov.get("missing"),
        "sections": sorted((bundle or {}).keys())[:24],
    }
    a.expect("runtime_facts_collected", bool(facts_text), details["facts"])
    a.expect("facts_bundle_present", bool(bundle), details["facts"])

    report = ""
    telemetry: dict = {}
    provider_allowed = ctx.take_provider_call()
    details["provider_call"] = {
        "allowed": provider_allowed,
        "used_total": ctx.provider_calls,
        "denied_total": ctx.provider_denied,
    }
    if provider_allowed:
        try:
            service_obj = CheckupService(ctx.llm(), db=db, memory=None)
            report = await asyncio.wait_for(
                service_obj.checkup(logs_text, used_fallback, chat_id=None,
                                    telemetry=telemetry),
                timeout=120,
            )
        except Exception as exc:
            details["checkup_error"] = type(exc).__name__
            details["checkup_error_detail"] = _clip(str(exc), 240)
    details["report"] = {
        "chars": len(report),
        "telemetry": {k: telemetry.get(k) for k in (
            "prompt_source", "prompt_hash", "prompt_version_used",
            "prompt_chars", "latency_ms", "report_chars",
            "metrics_included", "input_truncated", "used_fallback")},
        "head": _clip(report, 300) if report else "",
    }
    a.expect("checkup_report_present", bool(report.strip()), details["report"])
    a.expect("checkup_report_not_stub",
             bool(report.strip()) and report.strip() not in ("🗿", "…"),
             _clip(report, 80))

    journal_observed = bool(logs_text) and log_state == "ok" \
        and journal_state != "not_available"
    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "чекап/runtime identity не подтверждены: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION if journal_observed else EVIDENCE_UNAVAILABLE,
            "real systemd journal read" if journal_observed
            else "systemd/journal unavailable in this environment",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "журнал unit прочитан, бот не root, manifest/runtime/checkout "
        "согласованы; отчёт чекапа построен",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real systemd journal + deployed identity + real checkup report",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 10. direct continuation → SXR-L7-01
# ═════════════════════════════════════════════════════════════════════════════

_DIRECT_FORMULATIONS = (
    "Проверь по исходникам нашего проекта, что делает функция "
    "resolve_capacity: нужен ли для ответа сам код?",
    "Хочу понять, как в нашем коде устроен resolve_capacity — посмотри "
    "файл, где он объявлен, и скажи по факту.",
)

#: Файл заведомо больше окна tool-evidence (200k символов в deployed
#: 2.58.200): нужен реальный remainder/cursor, а не «файл прочитан целиком».
_CONTINUATION_FILE = "services/tool_router.py"


async def _dispatch_source(router, tool_ctx, arguments: dict) -> dict:
    out = await router.dispatch("read_source_code", arguments, tool_ctx)
    if str(out).strip().startswith("{"):
        try:
            return json.loads(out)
        except ValueError:
            return {"raw": _clip(out, 300)}
    return {"raw": _clip(out, 300)}


def _continuation_facts(first: dict, second: dict | None) -> dict:
    """Реальные remainder/cursor + второй диапазон, без синтетики."""
    truncation = first.get("truncation")
    truncation = truncation if isinstance(truncation, dict) else {}
    first_range = list(first.get("line_range") or [])
    cursor = truncation.get("next_line_start")
    try:
        cursor_int = int(cursor) if cursor is not None else 0
    except (TypeError, ValueError):
        cursor_int = 0
    try:
        first_end = int(first_range[1]) if len(first_range) > 1 else 0
    except (TypeError, ValueError):
        first_end = 0
    second = second if isinstance(second, dict) else {}
    second_range = list(second.get("line_range") or [])
    try:
        second_start = int(second_range[0]) if second_range else 0
    except (TypeError, ValueError):
        second_start = 0
    facts = {
        "file": _CONTINUATION_FILE,
        "first": {
            "status": first.get("status"),
            "network_calls": int(first.get("network_calls") or 0),
            "line_range": first_range,
            "snippet_chars": int(first.get("snippet_chars") or 0),
            "file_total_lines": int(first.get("file_total_lines") or 0),
            "verified": bool(first.get("verified")),
            "truncated": bool(truncation.get("truncated")),
            "why": str(truncation.get("why") or ""),
            "retrievable_remainder_lines": int(
                truncation.get("retrievable_remainder_lines") or 0),
            "next_line_start": cursor_int or None,
            "error": first.get("error")
            if isinstance(first.get("error"), str) else None,
        },
        "second": {
            "status": second.get("status"),
            "network_calls": int(second.get("network_calls") or 0),
            "line_range": second_range,
            "snippet_chars": int(second.get("snippet_chars") or 0),
            "head": _clip(second.get("snippet") or "", 120),
            "error": second.get("error")
            if isinstance(second.get("error"), str) else None,
        },
    }
    first_ok = (
        facts["first"]["status"] == "ok"
        and facts["first"]["network_calls"] == 0
        and facts["first"]["snippet_chars"] > 0
    )
    remainder_ok = (
        facts["first"]["truncated"]
        and facts["first"]["retrievable_remainder_lines"] > 0
        and cursor_int > first_end > 0
    )
    next_ok = bool(
        second
        and facts["second"]["status"] == "ok"
        and facts["second"]["network_calls"] == 0
        and facts["second"]["snippet_chars"] > 0
        and second_start == cursor_int
    )
    facts["remainder_ok"] = bool(first_ok and remainder_ok)
    facts["next_range_ok"] = bool(remainder_ok and next_ok)
    facts["continuation_ok"] = bool(
        facts["remainder_ok"] and facts["next_range_ok"])
    return facts


async def _continuation_probe(router, tool_ctx) -> dict:
    """Прочитать большой файл, забрать remainder и реально дочитать его."""
    first = await _dispatch_source(
        router, tool_ctx,
        {"operation": "read", "path": _CONTINUATION_FILE,
         "line_start": 1, "line_end": 100000},
    )
    truncation = first.get("truncation")
    truncation = truncation if isinstance(truncation, dict) else {}
    cursor = truncation.get("next_line_start")
    second = None
    if cursor is not None:
        try:
            cursor_int = int(cursor)
        except (TypeError, ValueError):
            cursor_int = 0
        if cursor_int > 0:
            second = await _dispatch_source(
                router, tool_ctx,
                {"operation": "read", "path": _CONTINUATION_FILE,
                 "line_start": cursor_int, "line_end": cursor_int + 40},
            )
    return _continuation_facts(first, second)


async def check_direct_continuation(ctx: HarnessContext) -> CheckOutcome:
    from config.settings import settings
    from services import direct_capabilities
    from services.direct_l1 import build_l1_context, parse_l1_plan
    from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT
    from services.prompt_style_blocks import resolve_prompt
    from services.tool_router import ToolContext, ToolDeps, ToolRouter

    a = Asserts()
    details: dict[str, Any] = {"formulations": []}

    await ctx.load_config_cache()  # read-only; нужен для реальных model/key
    identity = await ctx.identity()
    router = ToolRouter(ToolDeps(search=None, memory=None))
    system_prompt = resolve_prompt(
        "prompts.direct_l1_planner_system_prompt",
        DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    )
    chat_id = ctx.args.chat_id[0] if ctx.args.chat_id else 0
    temperature = float(getattr(settings, "LLM_TEMPERATURE", 0.7) or 0.0)

    # Continuation: фактический remainder/cursor и реальное дочитывание
    # следующего диапазона через production read_source_code (локально,
    # без сети). Это не зависит от решения LLM и не является заглушкой.
    probe_ctx = ToolContext(0, "canary continuation probe",
                            diagnostic_research=identity)
    continuation: dict
    try:
        with network_blocked():
            continuation = await asyncio.wait_for(
                _continuation_probe(router, probe_ctx), timeout=90)
    except Exception as exc:
        continuation = {"error": type(exc).__name__,
                        "detail": _clip(str(exc), 200)}
    details["continuation"] = continuation
    a.expect("continuation_remainder_reported",
             bool(continuation.get("remainder_ok")), continuation)
    a.expect("continuation_next_range_read",
             bool(continuation.get("next_range_ok")), continuation)

    provider_enabled = bool(ctx.args.allow_provider_calls) \
        and not bool(ctx.args.offline)
    if not provider_enabled:
        details["provider_calls"] = {
            "used": ctx.provider_calls,
            "denied": ctx.provider_denied,
            "allowed_flag": bool(ctx.args.allow_provider_calls),
            "offline": bool(ctx.args.offline),
        }
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "LLM-путь Direct L1 не наблюдался: provider calls выключены "
            "(--allow-provider-calls отсутствует или --offline); "
            "continuation-проверка выполнена отдельно",
            {**details, "assertions": a.report()},
            EVIDENCE_UNAVAILABLE,
            "provider calls disabled; production LLM decision unavailable",
        )

    executed: list[dict] = []
    for text in _DIRECT_FORMULATIONS:
        entry: dict = {"query": text, "provider_call": False}
        if not ctx.take_provider_call():
            entry["skipped"] = "provider calls disabled/exhausted"
            details["formulations"].append(entry)
            continue
        entry["provider_call"] = True
        try:
            l1_context = build_l1_context(
                query=text, speaker="owner", addressee="bot",
                capabilities=("source_code",),
            )
            raw = await asyncio.wait_for(
                ctx.llm().generate(
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": l1_context}],
                    temperature=temperature,
                    chat_id=None,
                    module="canary",
                    step="l1",
                ),
                timeout=120,
            )
            plan = parse_l1_plan(raw)
            entry["plan"] = None if plan is None else {
                "action": plan.action,
                "tool_policy": plan.tool_policy,
                "capabilities_needed": list(plan.capabilities_needed),
                "execution_mode": plan.execution_mode,
                "execution_mode_source": plan.execution_mode_source,
                "response_act": plan.response_act,
                "raw_chars": len(str(raw or "")),
            }
            tool_name = ""
            capabilities = list(plan.capabilities_needed) if plan else []
            for capability in capabilities:
                tools = direct_capabilities.CAPABILITY_TOOLS.get(capability, ())
                for candidate in tools:
                    if candidate in ("read_source_code", "inspect_runtime"):
                        tool_name = candidate
                        break
                if tool_name:
                    break
            entry["selected_tool"] = tool_name or None
            if tool_name == "read_source_code":
                tool_ctx = ToolContext(chat_id, text,
                                       diagnostic_research=identity)
                with network_blocked():
                    out = await asyncio.wait_for(
                        router.dispatch(
                            "read_source_code",
                            {"operation": "read", "path": "services/tool_loop.py",
                             "symbol": "chat_with_tools"},
                            tool_ctx,
                        ),
                        timeout=90,
                    )
                payload = json.loads(out) if str(out).strip().startswith("{") else {}
                entry["tool_execution"] = {
                    "status": payload.get("status"),
                    "verified": bool(payload.get("verified")),
                    "network_calls": int(payload.get("network_calls") or 0),
                    "line_range": payload.get("line_range"),
                    "snippet_chars": int(payload.get("snippet_chars") or 0),
                    "error": payload.get("error")
                    if isinstance(payload.get("error"), str) else None,
                }
                executed.append(entry["tool_execution"])
        except Exception as exc:
            entry["error"] = type(exc).__name__
            entry["error_detail"] = _clip(str(exc), 200)
        details["formulations"].append(entry)

    ran = [f for f in details["formulations"] if f.get("provider_call")]
    decided = [f for f in ran if f.get("plan")]
    with_tool = [f for f in ran if f.get("tool_execution")]
    details["provider_calls"] = {
        "used": ctx.provider_calls,
        "denied": ctx.provider_denied,
        "allowed_flag": bool(ctx.args.allow_provider_calls),
    }
    a.expect("provider_call_performed", bool(ran), details["provider_calls"])
    a.expect("llm_decision_parsed", bool(decided), len(decided))
    a.expect("llm_decision_has_capabilities",
             any((f.get("plan") or {}).get("capabilities_needed") for f in decided),
             [f.get("plan") for f in decided])
    a.expect("tool_actually_executed", bool(with_tool), len(with_tool))
    a.expect("tool_execution_ok",
             all(e.get("status") == "ok" for e in executed) if executed else False,
             executed)
    a.expect("continuation_still_ok",
             bool(continuation.get("continuation_ok")), continuation)

    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "Direct-продолжение не подтверждено: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION if ran else EVIDENCE_UNAVAILABLE,
            "real L1 provider call executed; contract not satisfied" if ran
            else "provider budget denied the L1 call",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "L1 Planner принял независимые формулировки; решение LLM и реальный "
        "read-only tool-вызов зафиксированы; remainder/cursor и следующий "
        "диапазон реально дочитаны",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real provider L1 decision + real read_source_code continuation",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 11a. I1 — meme/initiative journal + spool (read-only) → SXR-I1-01
# ═════════════════════════════════════════════════════════════════════════════


def _parse_spool_lines(path: Path) -> dict:
    out = {"exists": path.is_file(), "rows": 0, "bad_rows": 0}
    if not path.is_file():
        return out
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    out["bad_rows"] += 1
                    continue
                if isinstance(payload, dict) and payload.get("attempt_id"):
                    out["rows"] += 1
                else:
                    out["bad_rows"] += 1
    except OSError as exc:
        out["error"] = type(exc).__name__
    return out


async def check_i1_spool(ctx: HarnessContext) -> CheckOutcome:
    from services import meme_initiative as meme

    a = Asserts()
    details: dict[str, Any] = {}
    table = meme.ATTEMPT_TABLE

    db = await ctx.sqlite()
    sqlite_ok = db is not None and getattr(db, "db", None) is not None
    details["sqlite_readable"] = sqlite_ok
    a.expect("sqlite_readable", sqlite_ok,
             "read-only SQLite DB must be readable")

    table_row = await ctx.sqlite_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,))
    details["attempt_table_exists"] = table_row.get("name") == table

    rows: list[dict] = []
    query_error = ""
    if details["attempt_table_exists"]:
        try:
            rows = await ctx.sqlite_rows(
                f"SELECT COUNT(*) AS c, MAX(ts) AS last_ts, "
                f"MAX(stage) AS last_stage FROM {table}")
        except Exception as exc:
            query_error = type(exc).__name__
    details["attempt_query_error"] = query_error or None
    summary = rows[0] if rows else {}
    details["attempts"] = {
        "table": table,
        "total": int(summary.get("c") or 0),
        "last_ts": int(summary["last_ts"]) if summary.get("last_ts") else None,
    }
    last: list[dict] = []
    if details["attempt_table_exists"]:
        try:
            last = await ctx.sqlite_rows(
                f"SELECT attempt_id, chat_id, ts, stage, outcome, reason_code, "
                f"detail, limit_source, limit_value FROM {table} "
                f"ORDER BY ts DESC LIMIT 5")
        except Exception as exc:
            details["attempt_query_error"] = type(exc).__name__
    details["last_attempts"] = []
    for row in last:
        facts = {}
        try:
            facts = meme.parse_attempt_facts(row)
        except Exception:
            facts = {}
        details["last_attempts"].append(
            {
                "attempt_id": _clip(row.get("attempt_id"), 40),
                "chat": _chat_ref(row.get("chat_id")),
                "ts": int(row["ts"]) if row.get("ts") else None,
                "stage": row.get("stage"),
                "outcome": row.get("outcome"),
                "reason_code": row.get("reason_code"),
                "limit_source": row.get("limit_source"),
                "limit_value": row.get("limit_value"),
                "facts": facts if isinstance(facts, dict) else {},
                "detail": _clip(row.get("detail"), 240),
            }
        )
    if details["last_attempts"]:
        facts = details["last_attempts"][0]["facts"] or {}
        details["last_attempt_display"] = {
            "mode": facts.get("mode") or meme.attempt_mode_of(facts) or None,
            "visible_ts": details["last_attempts"][0]["ts"],
            "outcome": details["last_attempts"][0]["outcome"],
            "reason_code": details["last_attempts"][0]["reason_code"],
            "stage": details["last_attempts"][0]["stage"],
        }

    spool_path = Path(str(
        Path(ctx.args.db_path) if ctx.args.db_path
        else (ctx.repo_root / "local_database.db"))) .with_name(
        (Path(ctx.args.db_path).name if ctx.args.db_path
         else "local_database.db") + ".attempts.pending.jsonl")
    details["spool"] = _parse_spool_lines(spool_path)
    details["spool"]["file"] = spool_path.name

    logs_text, _used_fallback, _log_state, _journal_state = await ctx.runtime_logs()
    lowered = logs_text.lower()
    markers = {
        "journal_spooled": lowered.count("attempt spooled (journal unavailable)"),
        "attempt_lost": lowered.count("attempt lost"),
        "journal_read_failed": lowered.count("attempt journal read failed"),
        "operational_error": lowered.count("operationalerror"),
    }
    details["journal_markers_in_window"] = markers

    a.expect("attempt_table_present", details["attempt_table_exists"],
             details["attempts"])
    a.expect("attempt_query_ok", not details.get("attempt_query_error"),
             details.get("attempt_query_error"))
    a.expect("attempt_aggregate_readable",
             len(rows) == 1 and not details.get("attempt_query_error")
             and int(summary.get("c") or 0) > 0
             and int(summary.get("last_ts") or 0) > 0,
             {"aggregate_rows": len(rows), "summary": summary,
              "query_error": details.get("attempt_query_error")})
    a.expect("attempt_rows_present", int(summary.get("c") or 0) > 0,
             details["attempts"])
    a.expect("last_attempt_state_present",
             bool(details["last_attempts"])
             and bool(details["last_attempts"][0].get("attempt_id"))
             and bool(details["last_attempts"][0].get("outcome")
                      or details["last_attempts"][0].get("reason_code")),
             details["last_attempts"][:1])
    a.expect("spool_drained", details["spool"]["rows"] == 0
             and details["spool"]["bad_rows"] == 0, details["spool"])
    a.expect("journal_window_readable",
             _log_state == "ok" and len(logs_text) > 0,
             {"log_state": _log_state, "journal_state": _journal_state,
              "chars": len(logs_text)})
    a.expect("journal_write_healthy",
             markers["journal_spooled"] == 0 and markers["attempt_lost"] == 0,
             markers)
    a.expect("accumulated_rows_preserved",
             int(summary.get("c") or 0) > 0
             and markers["operational_error"] == 0,
             {"total": int(summary.get("c") or 0), "markers": markers})
    if details["last_attempts"]:
        display = details["last_attempt_display"]
        a.expect("last_attempt_displayable",
                 bool(display.get("visible_ts"))
                 and bool(display.get("outcome") or display.get("reason_code")),
                 display)

    attempt_observed = bool(
        sqlite_ok
        and details["attempt_table_exists"]
        and int(summary.get("c") or 0) > 0
        and not details.get("attempt_query_error"))
    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "журнал/спул мемов не подтверждены: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION if attempt_observed else EVIDENCE_UNAVAILABLE,
            "real read-only SQLite attempt rows" if attempt_observed
            else "SQLite attempt rows unavailable/empty",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "журнал попыток доступен, последняя попытка читается, spool пуст "
        "(идемпотентный дренаж), маркеров недоступности журнала нет",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real read-only SQLite attempt rows + real journal window",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 11b. I2 — experience fresh stream (read-only) → SXR-I2-01
# ═════════════════════════════════════════════════════════════════════════════


async def check_i2_stream(ctx: HarnessContext) -> CheckOutcome:
    from services import mca_experience_jobs as jobs

    a = Asserts()
    details: dict[str, Any] = {"job_kind": jobs.REVIEW_JOB_KIND}

    db = await ctx.sqlite()
    sqlite_ok = db is not None and getattr(db, "db", None) is not None
    details["sqlite_readable"] = sqlite_ok
    a.expect("sqlite_readable", sqlite_ok,
             "read-only SQLite DB must be readable")

    job_rows: list[dict] = []
    try:
        job_rows = await ctx.sqlite_rows(
            "SELECT job_id, status, attempt, created_at, updated_at, "
            "finished_at, payload FROM task_jobs WHERE kind = ? "
            "ORDER BY COALESCE(finished_at, updated_at, created_at) DESC, "
            "rowid DESC LIMIT 5", (jobs.REVIEW_JOB_KIND,))
    except Exception as exc:
        details["job_query_error"] = type(exc).__name__
    details["recent_jobs"] = []
    payload: dict = {}
    for row in job_rows:
        raw = row.get("payload")
        data: dict = {}
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            data = {}
        if not payload and data:
            payload = data
        counters = data.get("counters") if isinstance(data.get("counters"), dict) else {}
        details["recent_jobs"].append(
            {
                "job_id": _clip(row.get("job_id"), 30),
                "status": row.get("status"),
                "attempt": row.get("attempt"),
                "created_at": row.get("created_at"),
                "finished_at": row.get("finished_at"),
                "counters": {k: v for k, v in sorted(counters.items())
                             if "semantic" in k or "fresh" in k or "archive" in k},
                "has_payload": bool(data),
            }
        )

    progress = jobs.semantic_progress_snapshot(payload)
    details["progress_snapshot"] = progress
    details["semantic_backlog"] = await jobs.semantic_backlog(db)

    cursor_entries = []
    for key, value in sorted(payload.items(), key=lambda kv: str(kv[0])):
        if not str(key).startswith(jobs.SEMANTIC_CURSOR_PREFIX):
            continue
        try:
            chat_id = int(str(key)[len(jobs.SEMANTIC_CURSOR_PREFIX):])
            cursor = int(value or 0)
        except (TypeError, ValueError):
            continue
        entry = {"chat": _chat_ref(chat_id), "cursor": cursor}
        try:
            max_row = await ctx.sqlite_one(
                "SELECT MAX(id) AS max_id FROM smart_messages WHERE chat_id = ?",
                (chat_id,))
            count_row = await ctx.sqlite_one(
                "SELECT COUNT(*) AS c, MIN(timestamp) AS oldest "
                "FROM smart_messages WHERE chat_id = ? AND id > ?",
                (chat_id, cursor))
        except Exception as exc:
            entry["query_error"] = type(exc).__name__
            cursor_entries.append(entry)
            continue
        max_id = int(max_row.get("max_id") or 0)
        count = int(count_row.get("c") or 0)
        oldest = int(count_row["oldest"]) if count_row.get("oldest") else 0
        entry.update({
            "max_id": max_id,
            "rows_after_cursor": count,
            "oldest_after_cursor": oldest or None,
            "cursor_lag_consistent": (max_id - cursor) >= count,
        })
        cursor_entries.append(entry)
    details["cursors"] = cursor_entries
    details["watermark"] = payload.get(jobs.SEMANTIC_WATERMARK_KEY)
    details["last_semantic_ts"] = payload.get(jobs.SEMANTIC_LAST_TS_KEY)
    measured = payload.get(jobs.SEMANTIC_LAG_KEY) or {}
    details["measured_lag_payload"] = {
        "available": bool(measured.get("available")),
        "rows": int(measured.get("rows") or 0),
        "worst_rows": int(measured.get("worst_rows") or 0),
        "partial": bool(measured.get("partial")),
        "age_seconds": measured.get("age_seconds"),
        "ts": measured.get("ts"),
    }
    total_rows_after = sum(e["rows_after_cursor"] for e in cursor_entries)
    details["recomputed_lag_rows"] = total_rows_after

    # I3-I6 facts, если доступны (те же read-only источники)
    if db is None:
        details["reason_codes"] = {"skipped": "sqlite_unavailable"}
    else:
        try:
            from services import experience_diagnostics as diag

            reasons = await asyncio.wait_for(
                diag.experience_pipeline_reasons(db), timeout=60)
            details["reason_codes"] = reasons
        except Exception as exc:
            details["reason_codes"] = {"error": type(exc).__name__}

    a.expect("review_job_present", bool(job_rows), len(job_rows))
    a.expect("durable_payload_present", bool(payload), len(payload))
    a.expect("cursor_identity_present", bool(cursor_entries), len(cursor_entries))
    a.expect("cursor_scope_chat", all("-" in c["chat"] for c in cursor_entries),
             [c["chat"] for c in cursor_entries])
    a.expect("lag_measurement_available",
             bool(measured.get("available")),
             details["measured_lag_payload"])
    a.expect("cursor_lag_recomputed",
             bool(cursor_entries)
             and all(isinstance(e.get("rows_after_cursor"), int)
                     and bool(e.get("cursor_lag_consistent"))
                     for e in cursor_entries),
             cursor_entries)
    a.expect("progress_matches_measured",
             int(progress.get("lag_rows") or 0) <= max(
                 total_rows_after, int(measured.get("rows") or 0)),
             {"snapshot": progress.get("lag_rows"),
              "recomputed": total_rows_after})
    a.expect("drain_cycles_recorded",
             any(str(r.get("status")) in ("completed", "failed", "interrupted")
                 for r in details["recent_jobs"]),
             details["recent_jobs"])

    stream_observed = bool(
        sqlite_ok and payload and cursor_entries
        and not details.get("job_query_error"))
    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "fresh stream не подтверждён: " + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION if stream_observed else EVIDENCE_UNAVAILABLE,
            "real durable job payload/cursors" if stream_observed
            else "SQLite durable payload/cursors unavailable",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "durable cursor/scope, backlog, измеренный lag и терминальные "
        "drain-циклы прочитаны без записи",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real read-only SQLite durable payload/cursors/backlog",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 13. persisted settings not overwritten → SXR-K3-01
# ═════════════════════════════════════════════════════════════════════════════


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_dt.timezone.utc)
        return value.isoformat()
    return str(value)


def _epoch(value: Any) -> float | None:
    """ISO-строка/datetime → epoch (UTC); неразборчивое → None."""
    if isinstance(value, _dt.datetime):
        moment = value if value.tzinfo else value.replace(
            tzinfo=_dt.timezone.utc)
        try:
            return moment.timestamp()
        except (OverflowError, OSError, ValueError):
            return None
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


#: Виды записей журнала `prompt_activations`, которые делает человек/владелец
#: (а не релиз). Только они могут объяснить изменение профиля чата после
#: deploy-снимка; запись релиза/миграции такого провенанса не имеет.
K3_OWNER_EDIT_KINDS = frozenset({
    "manual_edit", "manual_rollback", "manual_forward", "baseline_assign",
    "baseline_clear", "baseline_restore", "factory_restore",
    "chat_inherit_reset",
})
K3_OWNER_EDIT_OUTCOMES = frozenset({"applied", "recorded"})
#: Окно атрибуции «запись профиля ↔ провенанс» (значение и профиль пишутся
#: одной транзакцией, поэтому окно нужно только на рассинхрон часов).
K3_ATTRIBUTION_WINDOW_S = 300.0


def _attribute_profile_writes(
    profiles: list[dict],
    activations: list[dict],
    history: list[dict],
    *,
    baseline_max_updated: str,
    window_s: float = K3_ATTRIBUTION_WINDOW_S,
) -> dict:
    """Атрибутировать изменения `chat_profiles` после deploy-снимка.

    Контракт K3 — «deploy не перезаписал сохранённые настройки/модели/промпты».
    Поэтому изменение профиля (updated_at > baseline-снимка) допустимо ТОЛЬКО
    при наличии провенанса владельца/пользователя рядом по времени:

    * ``prompt_activations``: ``kind`` из :data:`K3_OWNER_EDIT_KINDS`
      (для per-chat правки промпта — ``scope='chat'``), либо
    * ``chat_lore_history``: ``field='chat_params'`` с непустым ``changed_by``
      (любая иная ручная правка настроек чата).

    Запись релиза/миграции (`deploy_activate`, прямой UPDATE без журнала) не
    даёт ни одного из этих следов → ``unattributed`` и провал утверждения.

    Чистая функция: строки PG → вердикт, без I/O (тестируется self-test'ом).
    """
    baseline_epoch = _epoch(baseline_max_updated)
    edits: dict[int, list[dict]] = {}
    for row in activations:
        chat_id = row.get("chat_id")
        kind = str(row.get("kind") or "")
        outcome = str(row.get("outcome") or "")
        if chat_id is None or kind not in K3_OWNER_EDIT_KINDS:
            continue
        if outcome and outcome not in K3_OWNER_EDIT_OUTCOMES:
            continue
        stamp = _epoch(row.get("created_at"))
        if stamp is None:
            continue
        edits.setdefault(int(chat_id), []).append({
            "source": "prompt_activations",
            "kind": kind,
            "outcome": outcome or None,
            "detail_code": str(row.get("detail_code") or ""),
            "block_id": str(row.get("block_id") or ""),
            "scope": str(row.get("scope") or ""),
            "actor_present": bool(str(row.get("actor") or "")),
            "created_at": _iso(row.get("created_at")),
            "_epoch": stamp,
        })
    for row in history:
        if str(row.get("field") or "") != "chat_params":
            continue
        chat_id = row.get("chat_id")
        changed_by = row.get("changed_by")
        if chat_id is None or changed_by in (None, "", 0):
            continue
        stamp = _epoch(row.get("created_at"))
        if stamp is None:
            continue
        edits.setdefault(int(chat_id), []).append({
            "source": "chat_lore_history",
            "kind": "chat_params",
            "changed_by_present": True,
            "created_at": _iso(row.get("created_at")),
            "_epoch": stamp,
        })

    post_deploy: list[dict] = []
    attributed: list[dict] = []
    unattributed: list[dict] = []
    for profile in profiles:
        changed = _epoch(profile.get("updated_at"))
        if baseline_epoch is not None and changed is not None:
            is_new = changed > baseline_epoch
        else:
            # Неразборчивая метка времени: изменение не доказано ни в одну
            # сторону → считаем отклонением, атрибуция решает.
            is_new = bool(profile.get("updated_at")) and (
                baseline_epoch is None or changed is None)
        if not is_new:
            continue
        entry = {
            "chat": profile.get("chat") or _chat_ref(profile.get("chat_id")),
            "updated_at": _iso(profile.get("updated_at")),
            "override_count": profile.get("override_count"),
        }
        post_deploy.append(entry)
        chat_id = profile.get("chat_id")
        candidates = edits.get(int(chat_id), []) if chat_id is not None else []
        match = None
        if changed is not None:
            for item in candidates:
                if abs(item["_epoch"] - changed) <= float(window_s):
                    match = item
                    break
        if match is None:
            unattributed.append({**entry, "provenance": None,
                                 "candidates": len(candidates)})
            continue
        attributed.append({
            **entry,
            "provenance": {k: v for k, v in match.items() if k != "_epoch"},
        })

    return {
        "baseline_max_updated_at": baseline_max_updated,
        "post_deploy_changes": post_deploy,
        "attributed": attributed,
        "unattributed": unattributed,
        "ok": not unattributed,
        "window_s": float(window_s),
    }


async def check_k3_settings(ctx: HarnessContext) -> CheckOutcome:
    a = Asserts()
    details: dict[str, Any] = {"baseline": K3_BASELINE}

    configured = await ctx.load_config_cache()
    a.expect("persisted_config_readable", configured,
             "PG bot_settings/chat_profiles read-only")
    if not configured:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "persisted-конфигурация недоступна: PG не прочитан",
            {**details, "assertions": a.report()},
            EVIDENCE_UNAVAILABLE,
            "PG persisted config unavailable",
        )

    rows = await ctx.pg_rows(
        "SELECT key, category, updated_at FROM bot_settings")
    total = len(rows)
    details["settings_total"] = total
    categories: dict[str, int] = {}
    by_key = {str(r.get("key")): r for r in rows}
    for row in rows:
        cat = str(row.get("category") or "")
        categories[cat] = categories.get(cat, 0) + 1
    details["settings_by_category"] = categories
    a.expect("settings_not_deleted", total >= int(K3_BASELINE["bot_settings_total"]),
             {"now": total, "baseline": K3_BASELINE["bot_settings_total"]})

    protected: dict[str, Any] = {}
    for key, expected in K3_BASELINE["protected_settings"].items():
        row = by_key.get(key)
        updated = _iso((row or {}).get("updated_at"))
        entry = {"present": row is not None, "updated_at": updated or None}
        if expected.get("updated_date"):
            entry["updated_date_matches"] = updated.startswith(
                str(expected["updated_date"]))
        protected[key] = entry
    details["protected_settings"] = protected
    for key, entry in protected.items():
        a.expect(f"protected_present:{key}", entry["present"], entry)
        if "updated_date_matches" in entry:
            a.expect(f"protected_not_rewritten:{key}",
                     entry["updated_date_matches"], entry)

    values: dict[str, Any] = {}
    for key in ("flags.budgets_enabled", "models.llm_model_name",
                "models.llm_base_url"):
        fetched = await ctx.pg_rows(
            "SELECT value FROM bot_settings WHERE key = $1", (key,))
        value = fetched[0].get("value") if fetched else None
        if isinstance(value, str) and value[:1] in '"[{':
            try:
                value = json.loads(value)
            except ValueError:
                pass
        values[key] = value
    details["protected_values"] = values
    a.expect("budgets_flag_persisted_false",
             values.get("flags.budgets_enabled") in (False, "false", 0, "0"),
             values.get("flags.budgets_enabled"))

    profiles = await ctx.pg_rows(
        "SELECT chat_id, updated_at, chat_params FROM chat_profiles")
    override_counts: list[int] = []
    max_updated = ""
    profile_entries: list[dict] = []
    for row in profiles:
        root = row.get("chat_params")
        if isinstance(root, str):
            try:
                root = json.loads(root)
            except ValueError:
                root = {}
        overrides = (root or {}).get("overrides") if isinstance(root, dict) else {}
        count = len(overrides or {})
        override_counts.append(count)
        stamp = _iso(row.get("updated_at"))
        if stamp > max_updated:
            max_updated = stamp
        profile_entries.append({
            "chat": _chat_ref(row.get("chat_id")),
            "chat_id": row.get("chat_id"),
            "updated_at": stamp,
            "override_count": count,
        })

    # Провенанс записей после deploy-снимка: только read-only SELECT'ы.
    provenance_errors: dict[str, str] = {}
    try:
        activations = await ctx.pg_rows(
            "SELECT block_id, scope, chat_id, kind, outcome, actor, "
            "detail_code, revision_id, created_at FROM prompt_activations "
            "ORDER BY activation_id DESC LIMIT 1000")
    except Exception as exc:                       # noqa: BLE001
        activations = []
        provenance_errors["prompt_activations"] = type(exc).__name__
    try:
        history = await ctx.pg_rows(
            "SELECT chat_id, field, changed_by, created_at "
            "FROM chat_lore_history WHERE field = 'chat_params' "
            "ORDER BY id DESC LIMIT 1000")
    except Exception as exc:                       # noqa: BLE001
        history = []
        provenance_errors["chat_lore_history"] = type(exc).__name__

    baseline_max_updated = str(K3_BASELINE["chat_profiles_max_updated_at"])
    attribution = _attribute_profile_writes(
        profile_entries, activations, history,
        baseline_max_updated=baseline_max_updated)
    details["chat_profiles"] = {
        "chats": len(profiles),
        "override_counts": sorted(override_counts),
        "max_updated_at": max_updated or None,
        "rows": [
            {k: v for k, v in entry.items() if k != "chat_id"}
            for entry in profile_entries
        ],
        "attribution": attribution,
        "provenance_errors": provenance_errors,
        "provenance_source": (
            "prompt_activations (kind=manual_edit/manual_* — правки владельца) "
            "+ chat_lore_history(field=chat_params, changed_by≠NULL); "
            "запись релиза/миграции такого следа не оставляет"),
    }
    a.expect("provenance_readable", not provenance_errors, provenance_errors)

    now_sorted = sorted(override_counts)
    base_sorted = sorted(int(v) for v in K3_BASELINE["override_key_counts"])
    no_reduction = (len(now_sorted) == len(base_sorted)
                    and all(now >= base for now, base
                            in zip(now_sorted, base_sorted)))
    delta = sum(now_sorted) - sum(base_sorted)
    a.expect("override_counts_unchanged",
             no_reduction and (delta == 0 or attribution["ok"]),
             {"now": now_sorted, "baseline": base_sorted, "delta": delta,
              "no_reduction": no_reduction,
              "attribution_ok": attribution["ok"],
              "attributed": attribution["attributed"],
              "unattributed": attribution["unattributed"]})
    a.expect("chat_profiles_unchanged_since_baseline",
             attribution["ok"],
             {"now_max_updated_at": max_updated or None,
              "baseline_max_updated_at": baseline_max_updated,
              "post_deploy_changes": attribution["post_deploy_changes"],
              "attributed_owner_edits": attribution["attributed"],
              "unattributed": attribution["unattributed"],
              "attribution_window_s": attribution["window_s"]})

    deploy_at = str(K3_BASELINE["deploy_at_utc"])
    prompt_rows = [r for r in rows if str(r.get("category")) == "prompts"]
    allowed_new = set(K3_BASELINE.get("allowed_new_prompt_keys") or ())
    changed_after_deploy = [
        str(r.get("key")) for r in prompt_rows
        if _iso(r.get("updated_at")) > deploy_at and str(r.get("key")) not in allowed_new
    ]
    details["prompts"] = {
        "count": len(prompt_rows),
        "changed_after_deploy": changed_after_deploy[:10],
        "allowed_new": sorted(allowed_new),
    }
    a.expect("prompts_not_overwritten", not changed_after_deploy,
             changed_after_deploy[:10])

    # «исправления работают без OFF/SHADOW»
    flags = {
        "MODEL_CAPACITY_RESOLVER_ENABLED": bool(getattr(
            __import__("config.settings", fromlist=["settings"]).settings,
            "MODEL_CAPACITY_RESOLVER_ENABLED", False)),
        "SOURCE_READ_ENABLED": bool(getattr(
            __import__("config.settings", fromlist=["settings"]).settings,
            "SOURCE_READ_ENABLED", False)),
        "TOOL_CHAIN_LIMITS_ENABLED": bool(getattr(
            __import__("config.settings", fromlist=["settings"]).settings,
            "TOOL_CHAIN_LIMITS_ENABLED", True)),
    }
    details["feature_switches"] = flags
    a.expect("fixes_not_shadowed", all(flags.values()), flags)

    if a.failures:
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "сохранённые настройки/модели/промпты не подтверждены: "
            + ", ".join(a.failures[:6]),
            {**details, "assertions": a.report()},
            EVIDENCE_PRODUCTION,
            "real read-only PG bot_settings/chat_profiles; contract failed",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        "persisted настройки, модели, prompts и chat-overrides не "
        "перезаписаны; исправления не в OFF/SHADOW",
        {**details, "assertions": a.report()},
        EVIDENCE_PRODUCTION,
        "real read-only PG bot_settings/chat_profiles",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 13. L8 rollup (по уже собранным фактам, без нового поведения) → SXR-L8-01
# ═════════════════════════════════════════════════════════════════════════════


def _rollup_status(ctx: HarnessContext, check_id: str) -> str:
    entry = ctx.results.get(check_id)
    return str((entry or {}).get("status") or "not_run")


async def check_l8_rollup(ctx: HarnessContext) -> CheckOutcome:
    """Свод по I1–I6: только уже наблюдённые факты, без новых действий."""
    i1 = _rollup_status(ctx, "i1_spool")
    i2 = _rollup_status(ctx, "i2_stream")
    k3 = _rollup_status(ctx, "k3_settings")
    diag = _rollup_status(ctx, "diagnostic_variants")

    i2_details = (ctx.results.get("i2_stream") or {}).get("details") or {}
    reason_codes = i2_details.get("reason_codes") or {}
    i1_details = (ctx.results.get("i1_spool") or {}).get("details") or {}
    spool = i1_details.get("spool") or {}
    attempts = i1_details.get("attempts") or {}
    cursors = i2_details.get("cursors") or []
    lag = i2_details.get("recomputed_lag_rows")

    items = {
        "I1_journal_and_spool": {
            "status": i1,
            "cause_evidence": {
                "attempts_total": attempts.get("total"),
                "journal_markers": i1_details.get("journal_markers_in_window"),
            },
            "fix_evidence": {
                "last_attempt_display": i1_details.get("last_attempt_display"),
                "spool_rows": spool.get("rows"),
                "spool_bad_rows": spool.get("bad_rows"),
                "accumulated_rows_preserved": attempts.get("total"),
            },
            "invariants": "attempt rows readable; spool drained without loss",
        },
        "I2_fresh_stream": {
            "status": i2,
            "cause_evidence": {
                "job_kind": i2_details.get("job_kind"),
                "payload_lag": i2_details.get("measured_lag_payload"),
            },
            "fix_evidence": {
                "cursor_count": len(cursors),
                "recomputed_lag_rows": lag,
                "drain_jobs": len(i2_details.get("recent_jobs") or []),
            },
            "invariants": "cursor identity/scope, backlog, lag recomputation",
        },
        "I3_lesson_rejected": {
            "status": "not_run",
            "reason": "в этом canary нет разрешённого/запрещённого "
                      "lesson-сценария; факт не наблюдён",
        },
        "I4_reason_codes": {
            "status": "observed" if isinstance(reason_codes, dict)
            and reason_codes and "error" not in reason_codes
            and "skipped" not in reason_codes else "not_observed",
            "evidence": reason_codes,
            "invariants": "unmapped codes classification (read-only snapshot)",
        },
        "I5_incidents": {
            "status": "not_run",
            "reason": "инцидентные сценарии требуют управляемого отказа; "
                      "в canary не исполнялись",
        },
        "I6_events": {
            "status": "not_run",
            "reason": "событийный путь мемов/инициативы проверяется I1; "
                      "отдельный I6-сценарий не исполнялся",
        },
    }
    statuses = [v.get("status") for v in items.values()]
    observed = sum(1 for s in statuses if s == "observed")
    not_observed = sum(1 for s in statuses if s in ("not_observed", "error"))
    not_run = sum(1 for s in statuses if s == "not_run")
    details = {
        "items": items,
        "rollup": {
            "observed": observed,
            "not_observed": not_observed,
            "not_run": not_run,
            "related_checks": {"i1": i1, "i2": i2, "k3": k3,
                               "diagnostic_variants": diag},
        },
        "no_new_behavior": True,
    }
    i1_entry = ctx.results.get("i1_spool") or {}
    i2_entry = ctx.results.get("i2_stream") or {}
    i1_class = str(i1_entry.get("evidence_class") or EVIDENCE_UNAVAILABLE)
    i2_class = str(i2_entry.get("evidence_class") or EVIDENCE_UNAVAILABLE)
    rollup_class = (
        EVIDENCE_PRODUCTION
        if i1_class == EVIDENCE_PRODUCTION and i2_class == EVIDENCE_PRODUCTION
        else EVIDENCE_UNAVAILABLE
    )
    details["input_evidence_classes"] = {"i1": i1_class, "i2": i2_class}
    if observed == 0 or (i1 != STATUS_OBSERVED and i2 != STATUS_OBSERVED):
        return CheckOutcome(
            STATUS_NOT_OBSERVED,
            "свод I1–I6 не опирается на наблюдённые I1/I2 "
            f"(i1={i1}, i2={i2}, observed={observed})",
            details,
            rollup_class,
            "rollup requires production-observed I1 and I2",
        )
    return CheckOutcome(
        STATUS_OBSERVED,
        f"I1/I2 наблюдены ({observed} пунктов observed, {not_observed} "
        f"not_observed, {not_run} not_run); свод без нового поведения",
        details,
        rollup_class,
        "rollup over production-observed I1/I2 facts",
    )


# ═════════════════════════════════════════════════════════════════════════════
# CHECK REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("effective_config", "1", "Effective config: budgets, caps, model capacity",
              ("SXR-L1-01", "SXR-K3-01"), check_effective_config),
    CheckSpec("control_loop_off", "2", "Tool loop OFF: >4 rounds, >6 calls, 3-in-round",
              ("SXR-L1-01",), check_control_loop_off),
    CheckSpec("caps_on_and_override", "3", "Budgets ON defaults + operator override",
              ("SXR-L1-01",), check_caps_on_and_override),
    CheckSpec("evidence_payload", "4", "Evidence 13.5k chars: delivery, tail, honesty",
              ("SXR-L2-01",), check_evidence_payload),
    CheckSpec("capacity_scenarios", "5", "Eight capacity scenarios on one resolver",
              ("SXR-L3-01",), check_capacity_scenarios),
    CheckSpec("local_source_read", "6", "Local own-code read with deployed identity",
              ("SXR-L4-01",), check_local_source_read),
    CheckSpec("external_reads", "7", "External GitHub read + SSRF refusal",
              ("SXR-F2-01", "SXR-F4-01", "SXR-L5-01"), check_external_reads),
    CheckSpec("external_scenarios", "7b",
              "F4: public repo, symbol search, link read, related sources, "
              "factual refusal, no separate command",
              ("SXR-F4-01", "SXR-F2-01", "SXR-L5-01"),
              check_external_scenarios),
    CheckSpec("external_natural_request", "7c",
              "F4: natural external-code request via Direct L1 (one provider call)",
              ("SXR-F4-01",), check_external_natural_request),
    CheckSpec("diagnostic_variants", "8", "Seven diagnostic/finalization variants",
              ("SXR-L6-01",), check_diagnostic_variants),
    CheckSpec("checkup_real", "9", "Real checkup: journal, identity, manifest, report",
              ("SXR-H3-01", "SXR-H4-01", "SXR-L7-01"), check_checkup_real),
    CheckSpec("direct_continuation", "10", "Direct L1 decision + real tool execution",
              ("SXR-L7-01",), check_direct_continuation),
    CheckSpec("i1_spool", "11", "I1 journal/spool read-only observation",
              ("SXR-I1-01",), check_i1_spool),
    CheckSpec("i2_stream", "11", "I2 fresh stream cursor/lag read-only observation",
              ("SXR-I2-01",), check_i2_stream),
    CheckSpec("k3_settings", "12", "Persisted settings/models/prompts not overwritten",
              ("SXR-K3-01",), check_k3_settings),
    CheckSpec("l8_rollup", "13", "I1–I6 structured rollup (no new behavior)",
              ("SXR-L8-01",), check_l8_rollup),
)


# ═════════════════════════════════════════════════════════════════════════════
# self-test (offline, no DB/network/provider)
# ═════════════════════════════════════════════════════════════════════════════


def _self_test_preflight(repo_root: Path) -> list[str]:
    """Проверить, что self-test исполняется на deployed-классах этого репо."""
    problems: list[str] = []
    import config.settings as _settings_mod
    import services.direct_execution as _direct
    import services.model_capacity as _capacity
    import services.tool_loop as _loop

    for module in (_settings_mod, _loop, _direct, _capacity):
        origin = Path(str(getattr(module, "__file__", "") or "")).resolve()
        try:
            origin.relative_to(repo_root)
        except ValueError:
            problems.append(
                f"{module.__name__} imported from {origin} (outside {repo_root})")
    capacity_cls = getattr(_capacity, "CapacityResult", None)
    if not callable(getattr(capacity_cls, "as_window_meta", None)):
        problems.append(
            "services.model_capacity.CapacityResult.as_window_meta missing: "
            "repo is not the deployed 2.58.200 tree")
    if not callable(getattr(_capacity, "resolve_capacity", None)):
        problems.append("services.model_capacity.resolve_capacity missing")
    if not callable(getattr(_direct, "build_evidence_pack", None)):
        problems.append("services.direct_execution.build_evidence_pack missing")
    if not callable(getattr(_loop, "chat_with_tools", None)):
        problems.append("services.tool_loop.chat_with_tools missing")
    return problems


async def _self_test_body(repo_root: Path) -> int:
    failures: list[str] = []

    def expect(name: str, ok: Any, detail: Any = "") -> None:
        if not ok:
            failures.append(f"{name}: {_clip(detail, 300)}")
        print(f"[self-test] {'PASS' if ok else 'FAIL'} {name}")

    harness_meta = _harness_identity(Path(__file__).resolve())
    try:
        from config.settings import APP_VERSION as _APP_VERSION

        app_version = str(_APP_VERSION or "")
    except Exception:
        app_version = ""
    print(f"[self-test] repo={repo_root}")
    print(f"[self-test] head={_git(repo_root, 'rev-parse', 'HEAD') or '?'} "
          f"branch={_git(repo_root, 'rev-parse', '--abbrev-ref', 'HEAD') or '?'} "
          f"app={app_version or '?'}")
    print(f"[self-test] harness_sha256={harness_meta.get('sha256') or '?'} "
          f"tracked={harness_meta.get('tracked')} "
          f"blob_matches_head={harness_meta.get('blob_matches_head')}")
    preflight = _self_test_preflight(repo_root)
    if preflight:
        for problem in preflight:
            print(f"[self-test] FAIL preflight: {problem}")
        print(f"[self-test] failures={len(preflight)}")
        print("[self-test] BLOCKED: run self-test from the deployed/release "
              "tree (cwd or --repo-path); this checkout is not 2.58.200")
        return 1

    # 1) tool loop: OFF-контракт (scripted LLM + stub router)
    from services.tool_loop import TOOL_LOOP_FALLBACK_PHRASE as _phrase
    from services.tool_loop import chat_with_tools
    from services.tool_router import ToolContext

    try:
        from services import budget_gate as _bg

        async def _off(chat_id=None):  # noqa: ANN001
            return False

        original = _bg.budgets_enabled
        _bg.budgets_enabled = _off
        calls = [
            _tool_call(f"s{i}", "read_source_code",
                       {"operation": "read", "path": "x.py",
                        "line_start": i * 10 + 1, "line_end": i * 10 + 10})
            for i in range(7)
        ]
        rounds = [("", calls[0:3]), ("", calls[3:4]), ("", calls[4:5]),
                  ("", calls[5:7]), ("final", None)]
        llm = ScriptedLLM(rounds, final_text="final")
        router = StubRouter(
            lambda n, a, i: {"status": "ok", "snippet": f"s{i}",
                             "network_calls": 0})
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "t"}],
            tools=_LOOP_TOOL_SCHEMAS, router=router,
            ctx=ToolContext(0, "t"), chat_id=0)
        stats = _envelope_stats(result, llm)
        expect("loop.rounds_gt_4", int(result.rounds_used) > 4, result.rounds_used)
        expect("loop.calls_gt_6", stats["total"] > 6, stats["total"])
        expect("loop.no_caps", stats["chain_denied"] == 0, stats["reasons"])
        expect("loop.final", str(result) == "final"
               and _phrase not in str(result), str(result))
        expect("loop.prompt_injected", llm.calls == 5, llm.calls)
        expect("loop.every_call_result",
               stats["sequence"]["every_call_got_result"], stats["sequence"])

        # 2) budgets ON + override
        async def _on(chat_id=None):  # noqa: ANN001
            return True

        _bg.budgets_enabled = _on
        with patched_tool_loop_settings(
                MCA_TOOL_MAX_TOTAL_CALLS=3,
                MCA_TOOL_MAX_SAME_CALL=2,
                TOOL_CHAIN_LIMITS_ENABLED=True,
                MCA_TOOL_CHAIN_TIMEOUT_SECONDS=0.0):
            rounds2 = [
                ("", calls[0:3]),
                ("", calls[3:5] + [calls[0]]),
                ("final", None),
            ]
            llm2 = ScriptedLLM(rounds2, final_text="partial final")
            router2 = StubRouter(
                lambda n, a, i: {"status": "ok", "snippet": f"o{i}",
                                 "network_calls": 0})
            result2 = await chat_with_tools(
                llm2, [{"role": "user", "content": "t"}],
                tools=_LOOP_TOOL_SCHEMAS, router=router2,
                ctx=ToolContext(0, "t"), chat_id=0)
            stats2 = _envelope_stats(result2, llm2)
            expect("caps.seen", any(r in stats2["reasons"] for r in (
                "chain_call_limit", "same_call")), stats2["reasons"])
            expect("caps.every_call_result",
                   stats2["total"] == len(llm2.requested_ids),
                   {"envelopes": stats2["total"],
                    "requested": len(llm2.requested_ids)})
            expect("caps.degraded", bool(result2.degraded), result2.reason)
    finally:
        try:
            _bg.budgets_enabled = original  # type: ignore[possibly-undefined]
        except Exception:
            pass

    # 3) evidence pack
    from services.direct_execution import (
        EvidenceSource,
        build_evidence_pack,
        l2_evidence_budget_chars,
    )

    text, marker = _make_long_source(13500, "selftest")
    raw = type("_R", (), {"evidence_sources": [
        EvidenceSource(tool="fetch_article", status="ok", content=text,
                       total_chars=len(text))]})()
    cap = l2_evidence_budget_chars(200000, 0)
    pack = build_evidence_pack(raw, None, capacity_chars=cap)
    expect("evidence.delivered", pack.sources[0].delivered_chars == len(text.strip()),
           {"delivered": pack.sources[0].delivered_chars,
            "expected": len(text.strip())})
    expect("evidence.tail", f"CANARY-TAIL-MARKER:{marker}" in pack.text)
    expect("evidence.complete", pack.complete, pack.limitations)
    tight = build_evidence_pack(raw, None, capacity_chars=900)
    expect("evidence.tight_truncated", tight.sources[0].truncated
           and "обрезано" in tight.text and not tight.complete)

    # 4) capacity (offline, no adapters)
    from services import model_capacity as mc
    from services.llm_client import LLMError

    expect("capacity.under_1m", mc.resolve_model_context_window(
        "gpt-4o-mini")[0] == 128000)
    expect("capacity.over_1m", mc.resolve_model_context_window(
        "gemini-2.5-pro")[0] == 1048576)
    unknown = await mc.resolve_capacity("https://offline.invalid/v1",
                                       "canary/unknown-selftest")
    expect("capacity.unknown_estimated", unknown.source in (
        "estimated_unknown", "fallback") and unknown.confidence != "verified",
        getattr(unknown, "as_window_meta", lambda: {"source": unknown.source})())
    expect("capacity.unknown_not_16384", unknown.effective_context_window != 16384,
           unknown.effective_context_window)
    exc = LLMError("context_length_exceeded")
    exc.error_body = {"error": {"code": "context_length_exceeded",
                                "limit": 131072, "requested": 140000}}
    info = mc.parse_context_overflow_error(exc)
    expect("capacity.overflow_parsed", info is not None
           and info.limit_tokens == 131072,
           None if info is None else info.limit_tokens)
    mc.clear_proven_limits()

    # 5) diagnostic variants: два ключевых (final LLM unavailable + deadline)
    from services.llm_client import LLMError as _LE

    ok_call = _tool_call("st1", "execute_web_search", {"query": "q"})
    try:
        res, _l, _r, _c = await _run_variant(
            [("", [ok_call]), ("", [ok_call]), ("", [ok_call])],
            lambda n, a, i: _ok_source(n, "st"),
            finalizer_error=_LE("unavailable"), final_text="")
        expect("variant.structured_partial",
               res.finalize_mode == "structured_partial", res.finalize_mode)
        expect("variant.data_preserved", "canary source st" in str(res)
               or "canary source st" in (res.tool_context or ""), None)
        expect("variant.no_stub", TOOL_LOOP_FALLBACK_PHRASE not in str(res), None)
        expect("variant.every_call_result",
               _envelope_stats(res, _l)["sequence"]["every_call_got_result"],
               _envelope_stats(res, _l)["sequence"])
    except Exception as exc:
        expect("variant.ran", False, type(exc).__name__)

    try:
        import asyncio as _a

        class _Slow(StubRouter):
            async def dispatch(self, name, arguments, ctx):
                self.calls.append({"tool": name})
                await _a.sleep(0.5)
                return json.dumps(_ok_source(name, "dl"), ensure_ascii=False)

        llm = ScriptedLLM(
            [("", [_tool_call("dl1", "execute_web_search", {"query": "q"})]),
             ("deadline final", None)], final_text="deadline final")
        with patched_tool_loop_settings(MCA_TOOL_CHAIN_TIMEOUT_SECONDS=0.2):
            res2 = await chat_with_tools(
                llm, [{"role": "user", "content": "d"}],
                tools=_LOOP_TOOL_SCHEMAS, router=_Slow(lambda n, a, i: ""),
                ctx=ToolContext(0, "d"), chat_id=0)
        expect("variant.deadline_reason", res2.reason == "chain_timeout",
               res2.reason)
        expect("variant.deadline_evidence", "canary source dl" in str(res2)
               or "canary source dl" in (res2.tool_context or ""), None)
    except Exception as exc:
        expect("variant.deadline_ran", False, type(exc).__name__)

    # 6) continuation: реальный remainder/cursor и реальное дочитывание
    try:
        from services import source_reader as _sr
        from services.tool_router import ToolContext as _TC
        from services.tool_router import ToolDeps as _TD
        from services.tool_router import ToolRouter as _TR

        identity = await asyncio.to_thread(_sr.resolve_self_repo_identity)
        router = _TR(_TD(search=None, memory=None))
        probe_ctx = _TC(0, "selftest continuation",
                        diagnostic_research=identity)
        with network_blocked():
            cont = await asyncio.wait_for(
                _continuation_probe(router, probe_ctx), timeout=60)
        expect("continuation.remainder", bool(cont.get("remainder_ok")), cont)
        expect("continuation.next_range", bool(cont.get("next_range_ok")), cont)
        first = cont.get("first") or {}
        second = cont.get("second") or {}
        expect("continuation.no_network",
               int(first.get("network_calls") or 0) == 0
               and int(second.get("network_calls") or 0) == 0, cont)
        broken = _continuation_facts(
            {"status": "ok", "network_calls": 0, "line_range": [1, 10],
             "snippet_chars": 10, "truncation": {"truncated": False}},
            None,
        )
        expect("continuation.broken_rejected",
               not broken.get("remainder_ok")
               and not broken.get("next_range_ok"), broken)
        wrong_range = _continuation_facts(
            {"status": "ok", "network_calls": 0, "line_range": [1, 10],
             "snippet_chars": 10,
             "truncation": {"truncated": True, "next_line_start": 11,
                            "retrievable_remainder_lines": 5}},
            {"status": "ok", "network_calls": 0, "line_range": [1, 40],
             "snippet_chars": 10},
        )
        expect("continuation.wrong_range_rejected",
               wrong_range.get("remainder_ok") is True
               and wrong_range.get("next_range_ok") is False, wrong_range)
    except Exception as exc:
        expect("continuation.ran", False, f"{type(exc).__name__}: {exc}")

    # 7) evidence_class guard: observed без production запрещён
    class _EmptyResult:
        tool_results: list = []

    stats_empty = _envelope_stats(_EmptyResult(), None)
    expect("envelope.no_llm_not_vacuous",
           stats_empty["sequence"]["every_call_got_result"] is False,
           stats_empty)
    downgraded = _enforce_evidence_class({
        "id": "guard", "status": STATUS_OBSERVED, "summary": "stub pass",
        "evidence_class": EVIDENCE_PLUMBING, "details": {},
    })
    expect("evidence_class.plumbing_downgraded",
           downgraded.get("status") == STATUS_NOT_OBSERVED
           and downgraded.get("production_observed") is False, downgraded)
    kept = _enforce_evidence_class({
        "id": "guard2", "status": STATUS_OBSERVED, "summary": "real",
        "evidence_class": EVIDENCE_PRODUCTION, "details": {},
    })
    expect("evidence_class.production_kept",
           kept.get("status") == STATUS_OBSERVED
           and kept.get("production_observed") is True, kept)

    # 8) redaction
    expect("redaction.chat", _chat_ref(123456789).startswith("chat-")
           and "123456789" not in _chat_ref(123456789))
    expect("redaction.token", "123456:abcdefghijklmnopqrstuvwxyz0123456789"
           not in _scrub_text(
               "token 123456:abcdefghijklmnopqrstuvwxyz0123456789"))

    # 9) deployed-форма master-флага бюджетов: известная форма читается,
    # неизвестная — честный провал с наблюдаемой формой (не KeyError).
    real_meta = {"budgets_enabled": True, "source": "default", "stale": False,
                 "known": True}
    flag, _obs = _budget_flag(real_meta)
    expect("budget_flag.real_shape", flag is True, real_meta)
    flag_off, _obs = _budget_flag(
        {"budgets_enabled": False, "source": "chat", "stale": False,
         "known": True})
    expect("budget_flag.real_shape_off", flag_off is False, None)
    missing_flag, missing_obs = _budget_flag({"enabled": True, "source": "x"})
    expect("budget_flag.unknown_shape_none", missing_flag is None, missing_obs)
    expect("budget_flag.unknown_shape_reported",
           missing_obs.get("expected_key") == BUDGET_FLAG_KEY
           and BUDGET_FLAG_KEY not in (missing_obs.get("observed_keys") or []),
           missing_obs)
    retry_flag, _obs = _budget_flag(
        type("_State", (), {"as_meta": lambda self: dict(real_meta)})())
    expect("budget_flag.as_meta_supported", retry_flag is True, None)
    expect("budget_flag.as_meta_broken_none",
           _budget_flag(type("_B", (), {
               "as_meta": lambda self: (_ for _ in ()).throw(RuntimeError)})()
           )[0] is None, None)

    # 10) K3-атрибуция post-deploy правок профиля: ручная правка владельца
    # законна; изменение без провенанса (запись релиза/миграции) — нет.
    base_max = "2026-11-13T11:07:51+00:00"
    owner_profile = [{"chat": "chat-aaaaaaaa", "chat_id": 111,
                      "updated_at": "2026-11-14T06:11:54.954581+00:00",
                      "override_count": 32}]
    owner_activations = [{
        "block_id": "checkup.base.system", "scope": "chat", "chat_id": 111,
        "kind": "manual_edit", "outcome": "applied", "actor": "canary-actor",
        "detail_code": "owner_edit", "revision_id": "act:x",
        "created_at": "2026-11-14T06:11:54.800000+00:00",
    }]
    owner_verdict = _attribute_profile_writes(
        owner_profile, owner_activations, [], baseline_max_updated=base_max)
    expect("k3.owner_edit_attributed", owner_verdict["ok"] is True
           and len(owner_verdict["attributed"]) == 1, owner_verdict)
    expect("k3.owner_edit_provenance_recorded",
           owner_verdict["attributed"][0]["provenance"].get("kind")
           == "manual_edit", owner_verdict["attributed"])
    unattributed_verdict = _attribute_profile_writes(
        owner_profile, [], [], baseline_max_updated=base_max)
    expect("k3.unattributed_write_fails",
           unattributed_verdict["ok"] is False
           and len(unattributed_verdict["unattributed"]) == 1,
           unattributed_verdict)
    deploy_owned_verdict = _attribute_profile_writes(
        owner_profile, [{"block_id": "checkup.base.system", "scope": "chat",
                        "chat_id": 111, "kind": "deploy_activate",
                        "outcome": "applied", "actor": "",
                        "detail_code": "deploy", "revision_id": "fac:x",
                        "created_at": "2026-11-14T06:11:54.900000+00:00"}],
        [], baseline_max_updated=base_max)
    expect("k3.deploy_write_not_attributed",
           deploy_owned_verdict["ok"] is False, deploy_owned_verdict)
    history_verdict = _attribute_profile_writes(
        owner_profile, [],
        [{"chat_id": 111, "field": "chat_params", "changed_by": 777,
          "created_at": "2026-11-14T06:11:54.900000+00:00"}],
        baseline_max_updated=base_max)
    expect("k3.chat_params_history_attributed",
           history_verdict["ok"] is True
           and history_verdict["attributed"][0]["provenance"].get("source")
           == "chat_lore_history", history_verdict)
    anonymous_history_verdict = _attribute_profile_writes(
        owner_profile, [],
        [{"chat_id": 111, "field": "chat_params", "changed_by": None,
          "created_at": "2026-11-14T06:11:54.900000+00:00"}],
        baseline_max_updated=base_max)
    expect("k3.anonymous_history_not_attributed",
           anonymous_history_verdict["ok"] is False, anonymous_history_verdict)
    far_edit_verdict = _attribute_profile_writes(
        owner_profile,
        [{**owner_activations[0],
          "created_at": "2026-11-14T04:00:00+00:00"}],
        [], baseline_max_updated=base_max)
    expect("k3.out_of_window_edit_not_attributed",
           far_edit_verdict["ok"] is False, far_edit_verdict)
    untouched_verdict = _attribute_profile_writes(
        [{"chat": "chat-bbbbbbbb", "chat_id": 222,
          "updated_at": "2026-11-13T11:07:51+00:00", "override_count": 8}],
        [], [], baseline_max_updated=base_max)
    expect("k3.untouched_profile_ok",
           untouched_verdict["ok"] is True
           and not untouched_verdict["post_deploy_changes"], untouched_verdict)

    # 11) F4 external-scenario predicates: positive + negative controls
    def _chain_payload(files, *, status="ok", path=EXTERNAL_CHAIN_PATH,
                       commit="a" * 40, verified=True, calls=5):
        return {"status": status, "path": path, "commit": commit,
                "verified": verified, "source_kind": "file",
                "network_calls": calls, "snippet_chars": 40,
                "files": files, "not_checked": {"files_read": len(files)}}

    good_files = [
        {"path": EXTERNAL_CHAIN_PATH, "role": "primary", "verified": True,
         "snippet_chars": 40, "verified_url": "https://github.com/x/y/blob/"
                                            + "a" * 40 + "/" + EXTERNAL_CHAIN_PATH},
        {"path": EXTERNAL_CHAIN_SIBLING, "role": "followup", "verified": True,
         "snippet_chars": 25},
    ]
    chain_ok = _external_chain_facts(_chain_payload(good_files))
    expect("external.chain_related_positive",
           chain_ok["has_primary"] and chain_ok["distinct_verified_sibling"]
           and EXTERNAL_CHAIN_SIBLING in chain_ok["verified_sibling_paths"],
           chain_ok)
    only_primary = _external_chain_facts(_chain_payload(good_files[:1]))
    expect("external.chain_no_sibling_negative",
           only_primary["has_primary"]
           and not only_primary["distinct_verified_sibling"], only_primary)
    unverified_sibling = _external_chain_facts(_chain_payload([
        good_files[0],
        {"path": EXTERNAL_CHAIN_SIBLING, "role": "followup",
         "verified": False, "snippet_chars": 25},
    ]))
    expect("external.chain_unverified_sibling_negative",
           not unverified_sibling["distinct_verified_sibling"],
           unverified_sibling)

    commit_ref = "b" * 40
    search_ok = _external_search_facts(
        {"status": "ok", "stage": "locator", "path": EXTERNAL_SEARCH_EXPECT_PATH,
         "commit": commit_ref, "verified": True, "source_kind": "file",
         "symbol": EXTERNAL_SEARCH_SYMBOL, "symbol_found": True,
         "line_range": [10, 13], "snippet_chars": 60, "network_calls": 4},
        expected_path=EXTERNAL_SEARCH_EXPECT_PATH, expected_commit=commit_ref)
    expect("external.search_symbol_positive",
           search_ok["path_matches"] and search_ok["commit_matches"]
           and search_ok["symbol_found"] and search_ok["verified"], search_ok)
    search_wrong_commit = _external_search_facts(
        {"status": "ok", "stage": "locator", "path": EXTERNAL_SEARCH_EXPECT_PATH,
         "commit": "c" * 40, "verified": True}, expected_path=
        EXTERNAL_SEARCH_EXPECT_PATH, expected_commit=commit_ref)
    expect("external.search_exact_commit_negative",
           not search_wrong_commit["commit_matches"], search_wrong_commit)
    search_wrong_path = _external_search_facts(
        {"status": "ok", "stage": "locator", "path": "src/Other.java",
         "commit": commit_ref, "verified": True},
        expected_path=EXTERNAL_SEARCH_EXPECT_PATH, expected_commit=commit_ref)
    expect("external.search_path_negative",
           not search_wrong_path["path_matches"], search_wrong_path)

    link_ok = _external_link_facts(
        {"status": "ok", "path": EXTERNAL_CHAIN_PATH, "commit": commit_ref,
         "verified": True, "source_kind": "file", "snippet_chars": 90,
         "network_calls": 3},
        expected_commit=commit_ref, expected_path=EXTERNAL_CHAIN_PATH)
    expect("external.link_identity_positive",
           link_ok["path_matches"] and link_ok["commit_matches"]
           and link_ok["verified"], link_ok)
    link_wrong = _external_link_facts(
        {"status": "ok", "path": "src/Other.java", "commit": "d" * 40,
         "verified": True, "source_kind": "file"},
        expected_commit=commit_ref, expected_path=EXTERNAL_CHAIN_PATH)
    expect("external.link_identity_negative",
           not link_wrong["path_matches"] and not link_wrong["commit_matches"],
           link_wrong)

    failure_missing = _external_failure_facts(
        {"status": "not_found", "stage": "discover", "error": "source_missing",
         "network_calls": 1})
    expect("external.failure_missing_factual",
           failure_missing["factual"] and failure_missing["not_read"]
           and failure_missing["no_retries"], failure_missing)
    failure_rate = _external_failure_facts(
        {"status": "error", "stage": "discover", "error": "rate_limit",
         "error_detail": {"code": "rate_limit", "stage": "discover",
                          "http": 403}, "network_calls": 1})
    expect("external.failure_rate_limit_factual",
           failure_rate["factual"] and failure_rate["http"] == 403,
           failure_rate)
    failure_read = _external_failure_facts(
        {"status": "ok", "network_calls": 1})
    expect("external.failure_read_negative", not failure_read["factual"],
           failure_read)
    failure_unknown_code = _external_failure_facts(
        {"status": "error", "error": "something_odd", "network_calls": 1})
    expect("external.failure_unknown_code_negative",
           not failure_unknown_code["factual"], failure_unknown_code)
    failure_hammered = _external_failure_facts(
        {"status": "not_found", "error": "source_missing", "network_calls": 9})
    expect("external.failure_retries_negative",
           not failure_hammered["no_retries"], failure_hammered)

    from services import command_registry as _cmd_registry
    from services import tool_schemas as _tool_schemas

    capability_ok = _external_capability_facts(_tool_schemas, _cmd_registry)
    expect("external.capability_real_single_tool",
           capability_ok["single_tool"]
           and capability_ok["tool_name"] == "read_source_code"
           and capability_ok["operations_cover"]
           and capability_ok["no_separate_command"], capability_ok)

    class _FakeSchemas:
        TOOL_READ_SOURCE_CODE = {
            "function": {"name": "read_source_code",
                         "parameters": {"properties": {
                             "operation": {"enum": ["read"]}}}}}
        TOOL_CALLING_TOOLS = [
            {"function": {"name": "read_source_code"}},
            {"function": {"name": "github_fetch"}},
        ]

    class _FakeCommands:
        FUNCTIONAL_COMMANDS = {"search": ("найди",),
                               "source": ("исходник",)}

    capability_bad = _external_capability_facts(_FakeSchemas, _FakeCommands)
    expect("external.capability_extra_tool_negative",
           not capability_bad["single_tool"], capability_bad)
    expect("external.capability_partial_operations_negative",
           not capability_bad["operations_cover"], capability_bad)
    expect("external.capability_command_negative",
           not capability_bad["no_separate_command"], capability_bad)

    # 12) F4-проверки целиком: проводка на канонических ответах (plumbing —
    # транспорт подменён, сеть запрещена guard'ом) + честный guard без флага.
    from services.tool_router import ToolRouter as _ToolRouter

    fake_ctx = type("_Ctx", (), {
        "args": type("_A", (), {
            "offline": False, "allow_provider_calls": False,
            "max_provider_calls": 0}),
        "provider_calls": 0,
        "provider_denied": 0,
    })()

    def _canned(payloads: dict):
        def _respond(arguments: dict) -> dict:
            arguments = arguments or {}
            if arguments.get("repo") == EXTERNAL_MISSING_REPO:
                return payloads["missing"]
            if str(arguments.get("operation") or "") == "locate":
                return payloads["locate"]
            if arguments.get("url"):
                return payloads["link"]
            return payloads["chain"]
        return _respond

    good_payloads = {
        "chain": {"status": "ok", "stage": "fetch", "path": EXTERNAL_CHAIN_PATH,
                  "commit": "e" * 40, "verified": True, "source_kind": "file",
                  "snippet_chars": 40, "network_calls": 5,
                  "verified_url": "https://github.com/x/y/blob/" + "e" * 40
                                  + "/" + EXTERNAL_CHAIN_PATH,
                  "files": good_files, "not_checked": {"files_read": 2}},
        "locate": {"status": "ok", "stage": "locator", "path":
                   EXTERNAL_SEARCH_EXPECT_PATH, "commit": "e" * 40,
                   "verified": True, "source_kind": "file",
                   "symbol": EXTERNAL_SEARCH_SYMBOL, "symbol_found": True,
                   "line_range": [10, 13], "snippet_chars": 60,
                   "network_calls": 4},
        "link": {"status": "ok", "stage": "fetch", "path": EXTERNAL_CHAIN_PATH,
                 "commit": "e" * 40, "verified": True, "source_kind": "file",
                 "snippet_chars": 90, "network_calls": 3},
        "missing": {"status": "not_found", "stage": "discover",
                    "error": "source_missing", "network_calls": 1},
    }
    broken_payloads = dict(good_payloads)
    broken_payloads["chain"] = {**good_payloads["chain"],
                                "files": good_files[:1]}
    broken_payloads["locate"] = {**good_payloads["locate"], "commit": "f" * 40}

    original_dispatch = _ToolRouter.dispatch

    async def _run_external_scenarios(payloads: dict):
        def _respond(arguments: dict) -> dict:
            return _canned(payloads)(arguments)

        async def _fake_dispatch(self, name, arguments, tool_ctx):  # noqa: ANN001
            return json.dumps(_respond(arguments), ensure_ascii=False)

        _ToolRouter.dispatch = _fake_dispatch
        try:
            return await check_external_scenarios(fake_ctx)
        finally:
            _ToolRouter.dispatch = original_dispatch

    try:
        positive = await _run_external_scenarios(good_payloads)
        negative = await _run_external_scenarios(broken_payloads)
        expect("external.check_wiring_observed",
               positive.status == STATUS_OBSERVED
               and positive.evidence_class == EVIDENCE_PRODUCTION,
               {"status": positive.status,
                "failed": [x["name"] for x in
                           (positive.details.get("assertions") or [])
                           if not x["ok"]]})
        negative_failed = [x["name"] for x in
                           (negative.details.get("assertions") or [])
                           if not x["ok"]]
        expect("external.check_wiring_broken_path_not_observed",
               negative.status == STATUS_NOT_OBSERVED
               and "external_related_sources_read" in negative_failed
               and "external_symbol_search_exact_commit" in negative_failed,
               {"status": negative.status, "failed": negative_failed})
        guard = await check_external_natural_request(fake_ctx)
        expect("external.natural_request_guard_without_flag",
               guard.status == STATUS_NOT_OBSERVED
               and guard.evidence_class == EVIDENCE_UNAVAILABLE, guard.status)
    except Exception as exc:
        expect("external.check_wiring_ran", False, type(exc).__name__)

    print(f"[self-test] failures={len(failures)}")
    for line in failures:
        print(f"[self-test]   - {line}")
    return 0 if not failures else 1


async def _self_test(repo_root: Path) -> int:
    """Обёртка: никакой traceback не выходит наружу, только FAIL-строки."""
    try:
        return await _self_test_body(repo_root)
    except Exception as exc:  # noqa: BLE001 - контракт «no traceback»
        print(f"[self-test] FAIL uncaught {type(exc).__name__}: "
              f"{_clip(str(exc), 300)}")
        print("[self-test] failures=1")
        return 1


# ═════════════════════════════════════════════════════════════════════════════
# runner / CLI
# ═════════════════════════════════════════════════════════════════════════════


async def _run_one(ctx: HarnessContext, spec: CheckSpec) -> dict:
    started = time.monotonic()
    try:
        outcome = await asyncio.wait_for(
            spec.fn(ctx), timeout=float(ctx.args.check_timeout))
    except asyncio.TimeoutError:
        outcome = CheckOutcome(
            STATUS_ERROR, f"таймаут проверки ({ctx.args.check_timeout}s)",
            {"exception": "TimeoutError"}, EVIDENCE_UNAVAILABLE,
            "check timed out before producing production evidence")
    except Exception as exc:
        outcome = CheckOutcome(
            STATUS_ERROR, f"проверка упала: {type(exc).__name__}",
            {"exception": _clip(traceback.format_exc(limit=4), 1200)},
            EVIDENCE_UNAVAILABLE,
            "check raised before production evidence was classified")
    duration = time.monotonic() - started
    payload = outcome.as_dict(spec.id, list(spec.req_ids), duration, spec.title)
    payload = _enforce_evidence_class(payload)
    payload["details"] = _scrub_obj(payload.get("details") or {},
                                    str(ctx.repo_root))
    ctx.results[spec.id] = payload
    print(f"[canary] {spec.id:24s} {payload['status']:12s} "
          f"{duration:6.2f}s  {payload['summary'][:110]}")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SMART-EXECUTION-RELIABILITY-01 live canary (read-only)")
    parser.add_argument("--json-out", default="", help="JSON output path")
    parser.add_argument("--dry-run", action="store_true",
                        help="list checks and exit (no network/DB)")
    parser.add_argument("--self-test", action="store_true",
                        help="offline self-test (no network/DB)")
    parser.add_argument("--allow-provider-calls", action="store_true",
                        help="allow real paid LLM calls (default off)")
    parser.add_argument("--max-provider-calls", type=int, default=4,
                        help="provider call budget (default 4)")
    parser.add_argument("--repo-path", default="",
                        help="deployed code root (default: cwd)")
    parser.add_argument("--db-path", default="",
                        help="SQLite DB path (default: <repo>/local_database.db)")
    parser.add_argument("--checkup-unit", default="admin_bot",
                        help="bot systemd unit for journal checks")
    parser.add_argument("--chat-id", type=int, action="append", default=[],
                        help="explicit chat scope (repeatable)")
    parser.add_argument("--checks", default="",
                        help="comma-separated check ids")
    parser.add_argument("--check-timeout", type=float, default=300.0,
                        help="per-check timeout seconds (default 300)")
    parser.add_argument("--offline", action="store_true",
                        help="forbid all network access")
    parser.add_argument("--expect-harness-sha256", default="",
                        help="fail unless this exact harness sha256 is running")
    return parser


def _repo_root(args) -> Path:
    root = Path(args.repo_path).expanduser() if args.repo_path else Path.cwd()
    return root.resolve()


def _validate_repo(root: Path) -> list[str]:
    missing = []
    for rel in ("config/settings.py", "services/tool_loop.py",
                "services/direct_execution.py"):
        if not (root / rel).is_file():
            missing.append(rel)
    return missing


def _selected_checks(args) -> list[CheckSpec]:
    wanted = [c.strip() for c in str(args.checks or "").split(",") if c.strip()]
    if not wanted:
        return list(CHECKS)
    known = {spec.id for spec in CHECKS}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise SystemExit(f"unknown check ids: {', '.join(unknown)}")
    return [spec for spec in CHECKS if spec.id in wanted]


def _write_json(path: str, payload: dict) -> None:
    target = Path(path).expanduser()
    if target.parent and str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, target)


async def _close_context(ctx: HarnessContext) -> None:
    """Закрыть только то, что открыл харнесс (пулы/соединения)."""
    if ctx._sqlite is not None:
        try:
            await ctx._sqlite.close()
        except Exception:
            pass
        ctx._sqlite = None
    if ctx._pg is not None:
        try:
            await ctx._pg.close()
        except Exception:
            pass
        ctx._pg = None
    if ctx._llm is not None:
        try:
            await ctx._llm.close()
        except Exception:
            pass
        ctx._llm = None


async def _amain(args) -> int:
    root = _repo_root(args)
    missing = _validate_repo(root)
    if missing:
        print(f"[canary] repo path is not the deployed tree: {root} "
              f"(missing {', '.join(missing)})", file=sys.stderr)
        return 2
    harness_meta_start = _harness_identity(Path(__file__).resolve())
    expected_sha = str(getattr(args, "expect_harness_sha256", "") or "").lower()
    if expected_sha:
        actual_sha = str(harness_meta_start.get("sha256") or "").lower()
        if actual_sha != expected_sha:
            print("[canary] harness sha256 mismatch: "
                  f"expected={expected_sha} actual={actual_sha or 'unreadable'}",
                  file=sys.stderr)
            return 2
    sys.path.insert(0, str(root))

    selected = _selected_checks(args)
    if args.dry_run:
        print(f"[canary] dry-run: {len(selected)} checks, repo={root}")
        for spec in selected:
            print(f"[canary]   {spec.id:24s} group={spec.group:>2s} "
                  f"req={','.join(spec.req_ids)}  {spec.title}")
        print("[canary] no network/DB touched")
        return 0

    if args.self_test:
        try:
            with offline_guard():
                return await asyncio.wait_for(
                    _self_test(root), timeout=float(args.check_timeout))
        except asyncio.TimeoutError:
            print("[self-test] FAIL timeout "
                  f"({args.check_timeout}s); no partial pass", file=sys.stderr)
            return 1
        except Exception as exc:  # no traceback by contract
            print(f"[self-test] FAIL uncaught {type(exc).__name__}: "
                  f"{_clip(str(exc), 300)}", file=sys.stderr)
            return 1

    ctx = HarnessContext(repo_root=root, args=args)
    started_iso = _utc_now_iso()
    version = ""
    try:
        from config.settings import APP_VERSION as _APP_VERSION

        version = str(_APP_VERSION or "")
    except Exception:
        version = ""
    print(f"[canary] SMART live canary v{HARNESS_VERSION} | "
          f"repo={root} | head={_git(root, 'rev-parse', 'HEAD')[:12] or '?'} | "
          f"branch={_git(root, 'rev-parse', '--abbrev-ref', 'HEAD') or '?'} | "
          f"app={version or '?'} | harness_sha={
              str(harness_meta_start.get('sha256') or '?')[:12]} | "
          f"checks={len(selected)} | provider_calls="
          f"{'allowed:' + str(args.max_provider_calls) if args.allow_provider_calls else 'off'}"
          f"{' | offline' if args.offline else ''}")

    try:
        scope = offline_guard() if args.offline else contextlib.nullcontext()
        with scope:
            for spec in selected:
                if spec.id == "l8_rollup":
                    continue  # всегда последним
                await _run_one(ctx, spec)
            rollup = next((s for s in selected if s.id == "l8_rollup"), None)
            if rollup is not None:
                await _run_one(ctx, rollup)
    finally:
        await _close_context(ctx)

    results = list(ctx.results.values())
    summary = {
        "checks": len(results),
        "observed": sum(1 for r in results if r["status"] == STATUS_OBSERVED),
        "production_observed": sum(
            1 for r in results if r.get("production_observed")),
        "not_observed": sum(1 for r in results
                            if r["status"] == STATUS_NOT_OBSERVED),
        "error": sum(1 for r in results if r["status"] == STATUS_ERROR),
        "by_evidence_class": {
            cls: sum(1 for r in results
                     if r.get("evidence_class") == cls)
            for cls in EVIDENCE_CLASSES
        },
        "failed_assertions": sum(
            len([a for a in (r.get("details") or {}).get("assertions") or []
                 if not a.get("ok")])
            for r in results),
    }
    harness_meta = _harness_identity(Path(__file__).resolve())
    manifest_data: dict = {}
    manifest_path = root / ".deploy" / "release.json"
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest_data = {}
    clean_tracked = (
        _git(root, "status", "--porcelain", "--untracked-files=no") == "")
    repo_info = {
        "root": _scrub_text(str(root), str(root)),
        "head": _git(root, "rev-parse", "HEAD") or None,
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD") or None,
        "origin": _scrub_text(_git(root, "remote", "get-url", "origin")) or None,
        "app_version": None,
        "manifest_present": manifest_path.is_file(),
        "manifest": {
            key: manifest_data.get(key)
            for key in ("schema", "deployed_sha", "version", "deployed_at",
                        "effect", "previous_sha", "release_branch",
                        "dirty_tracked")
        },
        "harness_sha256": harness_meta.get("sha256"),
        "clean_tracked": clean_tracked,
        "dirty_tracked": not clean_tracked,
    }
    try:
        from config.settings import APP_VERSION as _APP_VERSION

        repo_info["app_version"] = str(_APP_VERSION or "")
    except Exception:
        pass
    payload = {
        "schema": SCHEMA,
        "harness_version": HARNESS_VERSION,
        "harness": "smart_live_canary",
        "harness_sha256": harness_meta.get("sha256"),
        "harness_identity": harness_meta,
        "started_at": started_iso,
        "finished_at": _utc_now_iso(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pid": os.getpid(),
            "euid": os.geteuid() if hasattr(os, "geteuid") else None,
        },
        "repo": repo_info,
        "flags": {
            "allow_provider_calls": bool(args.allow_provider_calls),
            "max_provider_calls": int(args.max_provider_calls),
            "offline": bool(args.offline),
            "checkup_unit": str(args.checkup_unit or ""),
            "checks": [s.id for s in selected],
        },
        "provider_calls": {
            "used": ctx.provider_calls,
            "denied": ctx.provider_denied,
        },
        "summary": summary,
        "checks": results,
        "notes": [
            "canary не отправляет Telegram-сообщений и не пишет конфигурацию",
            "production code paths emit in-memory telemetry only; durable "
            "mca_events/execution-graph writes are not flushed by this process",
            "observed != VERIFIED: acceptability решается requirement map "
            "после независимой проверки Reviewer",
        ],
    }
    if args.json_out:
        _write_json(args.json_out, payload)
        print(f"[canary] json written: {args.json_out}")
    print("[canary] summary: " + json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
