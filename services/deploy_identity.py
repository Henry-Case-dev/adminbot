"""Deployed identity (SELF-DIAG-01 / D4-A).

Единственная запись identity исполняемой ревизии. Порядок источников
фиксирован контрактом ``plans/features/self-diag-01/architecture-d4-identity.md``:

1. release manifest ``<repo_root>/.deploy/release.json``;
2. ``.git`` рабочего checkout (``HEAD`` -> ref -> ``packed-refs``);
3. env ``ADMINBOT_DEPLOYED_SHA`` (только если манифеста нет).

Модуль только читает. Он не пишет манифест, не кэширует результат,
не ходит в сеть, не вызывает shell и не исполняет файлы репозитория.
``git status`` вызывается фиксированным argv с таймаутом 3 c только для
определения ``dirty``; ``git log`` — только в ``recent_commits``.

Публичный API (schema 1):
    CODES, DEFAULT_REPO_ORIGIN, MANIFEST_REL_PATH, REASONS
    collect_identity(repo_root=None, *, process_started_at=None) -> dict
    recent_commits(repo_root=None, *, limit=5, basis="deployed") -> dict
    path_is_denied(rel_path) -> bool
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

CODES = (
    "verified_deployed",
    "local_unverified",
    "mismatch",
    "unknown",
    "unavailable",
)

DEFAULT_REPO_ORIGIN = "Henry-Case-dev/adminbot"
MANIFEST_REL_PATH = ".deploy/release.json"

# Закрытый набор причин contract v1.1 (§2.3 + Amendment 1 / B2):
# dirty_tracked — наблюдаемое dirty=true; no_process_start/version_unknown —
# штатные local_unverified; internal_error — только непредвиденное исключение
# верхнего уровня.
REASONS = (
    "no_manifest",
    "manifest_invalid_json",
    "manifest_incomplete",
    "manifest_sha_invalid",
    "no_git",
    "gitdir_unavailable",
    "head_unresolved",
    "dirty_unknown",
    "dirty_tracked",
    "git_unavailable",
    "git_timeout",
    "sha_conflict",
    "version_conflict",
    "process_predates_deploy",
    "no_remote_ref",
    "root_missing",
    "root_not_dir",
    "permission_denied",
    "path_denied",
    "no_process_start",
    "version_unknown",
    "internal_error",
    "",
)

_SCHEMA = 1
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_GIT_TIMEOUT_SECONDS = 3.0
_MANIFEST_MAX_BYTES = 64 * 1024
_HEAD_MAX_BYTES = 4096
_PACKED_REFS_MAX_BYTES = 1024 * 1024
_GIT_LOG_LIMIT_MAX = 5
_GIT_LOG_SUBJECT_MAX = 200

_MANIFEST_REQUIRED = ("deployed_sha", "deployed_at", "version", "effect")
_MANIFEST_ALLOWED = {
    "schema",
    "deployed_sha",
    "release_branch",
    "version",
    "deployed_at",
    "effect",
    "previous_sha",
    "previous_version",
    "dirty_tracked",
    "schema_version",
    "deployer",
}
_DENIED_DIRS = {
    "backups",
    "logs",
    "migrate_history",
    "chrome-profile",
    "bot-chrome-profile",
}
_DENIED_SUBSTRINGS = ("credential", "secret", "cookie")
_DENIED_FILES = {
    "deploy_commands.txt",
    "deploy_result.json",
    "check_remote_bot.py",
}
# Единственное точное исключение для self-read кода модуля (§B1).
_SELF_READ_PATH = "services/deploy_identity.py"
_REF_FORBIDDEN = set(" ~^:?*[\\\x7f")


class _PathDenied(Exception):
    """Путь после realpath вышел за разрешённый корень."""


# --------------------------------------------------------------------------
# helpers: путь, sha, время
# --------------------------------------------------------------------------


def _is_sha(value) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.match(value.strip()))


def _within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso_utc(value: datetime.datetime) -> str:
    return value.astimezone(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z")


def _mtime_iso(path: Path) -> str | None:
    try:
        return _iso_utc(datetime.datetime.fromtimestamp(
            path.stat().st_mtime, datetime.timezone.utc))
    except OSError:
        return None


def _parse_datetime(value) -> datetime.datetime | None:
    """datetime или ISO-строка; naive трактуется как UTC."""
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _parse_manifest_utc(value) -> datetime.datetime | None:
    """Манифест допускает только UTC ISO8601 (``...Z`` или ``+00:00``)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not (text.endswith("Z") or text.endswith("z")
            or text.endswith("+00:00")):
        return None
    parsed = _parse_datetime(text)
    if parsed is None:
        return None
    if parsed.utcoffset() != datetime.timedelta(0):
        return None
    return parsed


def _read_text_inside(path: Path, base: Path, *,
                      max_bytes: int | None = None) -> str:
    """Чтение файла, только если realpath остаётся внутри ``base``."""
    resolved = path.resolve()
    if not _within(base, resolved):
        raise _PathDenied(str(path))
    if not resolved.is_file():
        raise FileNotFoundError(str(path))
    if max_bytes is not None and resolved.stat().st_size > max_bytes:
        raise ValueError("file_too_large")
    return resolved.read_text(encoding="utf-8", errors="strict")


def _resolve_root(repo_root) -> tuple[Path | None, str]:
    if repo_root is None:
        return None, "root_missing"
    try:
        raw = Path(repo_root)
    except (TypeError, ValueError):
        return None, "root_missing"
    try:
        if not raw.exists():
            return None, "root_missing"
        if not raw.is_dir():
            return None, "root_not_dir"
        root = raw.resolve(strict=True)
    except PermissionError:
        return None, "permission_denied"
    except OSError:
        return None, "root_missing"
    if not root.is_dir():
        return None, "root_not_dir"
    return root, ""


# --------------------------------------------------------------------------
# denylist (§3.3)
# --------------------------------------------------------------------------


def _rel_parts(rel_path) -> list[str]:
    if not isinstance(rel_path, str):
        raise ValueError("not_a_string")
    text = rel_path.strip()
    if not text or "\x00" in text:
        raise ValueError("empty")
    text = text.replace("\\", "/")
    if text.startswith("/") or text.startswith("//") or re.match(
            r"^[A-Za-z]:", text):
        raise ValueError("absolute")
    parts = []
    for part in text.split("/"):
        normalized = part.strip()
        if normalized in ("", "."):
            continue
        if normalized == "..":
            raise ValueError("parent")
        parts.append(part)
    if not parts:
        raise ValueError("empty")
    return parts


def path_is_denied(rel_path: str) -> bool:
    """Единый предикат запрещённых путей contract v1.1 / §B1.

    Лексическая проверка: ``\\``→``/``, компоненты ``c = part.strip().lower()``,
    для точных имён ``ct = c.rstrip(". ")``. Отказ не зависит от scope/прав.
    Симлинк/выход за корень проверяются отдельно через ``realpath``.

    Deny: любой компонент ``== .git``; любой компонент содержит
    ``credential``/``secret``/``cookie`` на любой глубине; любой компонент из
    ``backups/logs/migrate_history/chrome-profile/bot-chrome-profile``;
    basename из закрытого набора; ``deploy_*.py`` на любой глубине, кроме
    точного ``services/deploy_identity.py`` (self-read). ``False`` означает
    «путь не относится к запрещённой лексике», а не «файл существует».
    """
    try:
        parts = _rel_parts(rel_path)
    except (TypeError, ValueError):
        return True
    lower = [part.strip().lower() for part in parts]
    exact = [part.rstrip(". ") for part in lower]
    if any(not part for part in lower):
        return True
    # Компонент из одних точек/пробелов — Windows-алиас ``.``/``..``.
    if any(not part for part in exact):
        return True
    if any(part == ".git" for part in exact):
        return True
    if any(any(needle in part for needle in _DENIED_SUBSTRINGS)
           for part in lower):
        return True
    if any(part in _DENIED_DIRS for part in exact):
        return True

    name = exact[-1]
    if name == ".env":
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    if name.endswith((".pem", ".key", ".p12")):
        return True
    if name.startswith(("id_rsa", "id_ed25519")):
        return True
    if name.endswith((".db", ".db-wal", ".db-shm")):
        return True
    if name.startswith("pre_migration_") and name.endswith(".db"):
        return True
    if name == "local_database.db":
        return True
    if name.endswith(".log"):
        return True
    if name in _DENIED_FILES:
        return True
    if name.startswith("deploy_") and name.endswith(".py"):
        # Единственное исключение — точный полный путь self-read кода.
        if "/".join(parts) != _SELF_READ_PATH:
            return True
    return False


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------


def _read_manifest(root: Path) -> tuple[str, dict | None]:
    deploy_dir = root / ".deploy"
    manifest_path = root / ".deploy" / "release.json"
    try:
        if deploy_dir.is_symlink():
            resolved_dir = deploy_dir.resolve()
            if not _within(root, resolved_dir):
                return "path_denied", None
        if manifest_path.is_symlink():
            resolved_file = manifest_path.resolve()
            if not _within(root, resolved_file):
                return "path_denied", None
        if not manifest_path.exists():
            return "no_manifest", None
        if not manifest_path.is_file():
            return "permission_denied", None
        text = _read_text_inside(manifest_path, root,
                                 max_bytes=_MANIFEST_MAX_BYTES)
    except FileNotFoundError:
        return "no_manifest", None
    except PermissionError:
        return "permission_denied", None
    except _PathDenied:
        return "path_denied", None
    except (OSError, ValueError):
        return "permission_denied", None

    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return "manifest_invalid_json", None
    if not isinstance(data, dict):
        return "manifest_incomplete", None
    if any(key not in _MANIFEST_ALLOWED for key in data):
        # Контракт §1.2: закрытый набор ключей schema 1.
        return "manifest_incomplete", None
    schema = data.get("schema", _SCHEMA)
    if (not isinstance(schema, int) or isinstance(schema, bool)
            or schema != _SCHEMA):
        return "manifest_incomplete", None
    for key in _MANIFEST_REQUIRED:
        if key not in data:
            return "manifest_incomplete", None
    if not _is_sha(data.get("deployed_sha")):
        return "manifest_sha_invalid", None
    if _parse_manifest_utc(data.get("deployed_at")) is None:
        return "manifest_incomplete", None
    if not _safe_label(data.get("version"), max_len=64):
        return "manifest_incomplete", None
    if data.get("effect") not in ("deploy", "rollback"):
        return "manifest_incomplete", None
    if "release_branch" in data and data["release_branch"] is not None:
        if not _valid_branch_name(data["release_branch"]):
            return "manifest_incomplete", None
    if ("previous_sha" in data and data["previous_sha"] is not None
            and not _is_sha(data["previous_sha"])):
        return "manifest_incomplete", None
    if ("previous_version" in data and data["previous_version"] is not None
            and not _safe_label(data["previous_version"], max_len=64)):
        return "manifest_incomplete", None
    if "dirty_tracked" in data and not isinstance(data["dirty_tracked"], bool):
        return "manifest_incomplete", None
    if ("schema_version" in data and data["schema_version"] is not None
            and (not isinstance(data["schema_version"], int)
                 or isinstance(data["schema_version"], bool))):
        return "manifest_incomplete", None
    if ("deployer" in data and data["deployer"] is not None
            and not _safe_label(data["deployer"], max_len=100)):
        return "manifest_incomplete", None
    return "", data


def _safe_label(value, *, max_len: int) -> bool:
    """Короткая метка без host-path/секретных разделителей."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > max_len:
        return False
    if any(ch in text for ch in ("/", "\\", "\x00", "\n", "\r")):
        return False
    return True


def _valid_branch_name(value) -> bool:
    if not isinstance(value, str) or not value or len(value) > 200:
        return False
    if value.startswith(("/", "-")) or "\x00" in value:
        return False
    if any(ch in _REF_FORBIDDEN for ch in value):
        return False
    if any(part in ("", ".", "..") for part in value.split("/")):
        return False
    return True


# --------------------------------------------------------------------------
# .git checkout
# --------------------------------------------------------------------------


def _resolve_git_dir(root: Path) -> tuple[Path | None, str]:
    dot = root / ".git"
    try:
        if dot.is_symlink():
            target = dot.resolve()
            if not _within(root, target):
                return None, "path_denied"
            if not target.is_dir():
                return None, "gitdir_unavailable"
            return target, ""
        if dot.is_file():
            text = dot.read_text(encoding="utf-8", errors="replace")
            if not text.startswith("gitdir:"):
                return None, "gitdir_unavailable"
            raw = text.split(":", 1)[1].strip()
            if not raw:
                return None, "gitdir_unavailable"
            path = Path(raw)
            if not path.is_absolute():
                path = root / path
            target = path.resolve()
            if not _within(root, target):
                return None, "path_denied"
            if not target.is_dir():
                return None, "gitdir_unavailable"
            return target, ""
        if dot.is_dir():
            target = dot.resolve()
            if not _within(root, target):
                return None, "path_denied"
            return target, ""
        return None, "no_git"
    except OSError:
        return None, "gitdir_unavailable"


def _valid_ref(ref: str) -> bool:
    if not isinstance(ref, str) or not ref or "\x00" in ref:
        return False
    if ref.startswith("/") or ref.endswith("/"):
        return False
    if any(ch in _REF_FORBIDDEN for ch in ref):
        return False
    parts = ref.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    return True


def _read_ref_file(git_dir: Path, ref: str) -> tuple[str | None, str | None]:
    if not _valid_ref(ref):
        return None, None
    path = git_dir / ref
    try:
        resolved = path.resolve()
        if not _within(git_dir, resolved):
            return None, None
        if not resolved.is_file():
            return None, None
        text = resolved.read_text(encoding="ascii", errors="strict").strip()
    except (OSError, ValueError):
        return None, None
    if not _is_sha(text):
        return None, None
    return text.lower(), _mtime_iso(resolved)


def _read_packed_refs(git_dir: Path) -> tuple[str | None, list[str]]:
    try:
        text = _read_text_inside(git_dir / "packed-refs", git_dir,
                                 max_bytes=_PACKED_REFS_MAX_BYTES)
    except (_PathDenied, FileNotFoundError):
        return None, []
    except (OSError, ValueError, PermissionError):
        return None, []
    return _mtime_iso(git_dir / "packed-refs"), text.splitlines()


def _read_packed_ref(git_dir: Path, ref: str) -> tuple[str | None, str | None]:
    observed_at, lines = _read_packed_refs(git_dir)
    if observed_at is None and not lines:
        return None, None
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", "^")):
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref and _is_sha(parts[0]):
            return parts[0].lower(), observed_at
    return None, None


def _read_head(git_dir: Path) -> tuple[str | None, str | None, str]:
    try:
        text = _read_text_inside(git_dir / "HEAD", git_dir,
                                 max_bytes=_HEAD_MAX_BYTES).strip()
    except _PathDenied:
        return None, None, "path_denied"
    except FileNotFoundError:
        return None, None, "head_unresolved"
    except PermissionError:
        return None, None, "gitdir_unavailable"
    except (OSError, ValueError):
        return None, None, "head_unresolved"

    if _is_sha(text):
        return text.lower(), None, ""
    if not text.startswith("ref:"):
        return None, None, "head_unresolved"
    ref = text[4:].strip()
    if not _valid_ref(ref):
        return None, None, "head_unresolved"
    sha, _observed_at = _read_ref_file(git_dir, ref)
    if sha is None:
        sha, _observed_at = _read_packed_ref(git_dir, ref)
    if sha is None:
        return None, None, "head_unresolved"
    branch = None
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        branch = ref[len(prefix):]
    return sha, branch, ""


def _read_upstream(git_dir: Path | None,
                   branch: str | None) -> dict:
    empty = {
        "sha": None,
        "ref": None,
        "observed_at": None,
        "reason": "no_remote_ref",
    }
    if git_dir is None or not branch:
        return empty
    ref = f"refs/remotes/origin/{branch}"
    sha, observed_at = _read_ref_file(git_dir, ref)
    if sha is None:
        sha, observed_at = _read_packed_ref(git_dir, ref)
    if sha is None:
        return empty
    return {
        "sha": sha,
        "ref": ref,
        "observed_at": observed_at,
        "reason": "",
    }


def _checkout_mtime(git_dir: Path | None) -> str | None:
    if git_dir is None:
        return None
    try:
        resolved = (git_dir / "HEAD").resolve()
        if not _within(git_dir, resolved) or not resolved.is_file():
            return None
        return _mtime_iso(resolved)
    except OSError:
        return None


def _repo_origin(git_dir: Path | None) -> str:
    if git_dir is None:
        return DEFAULT_REPO_ORIGIN
    try:
        text = _read_text_inside(git_dir / "config", git_dir,
                                 max_bytes=_PACKED_REFS_MAX_BYTES)
    except (_PathDenied, OSError, ValueError, PermissionError):
        return DEFAULT_REPO_ORIGIN
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if section != 'remote "origin"' or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip().lower() != "url":
            continue
        normalized = _normalize_repo_url(value.strip())
        if normalized:
            return normalized
    return DEFAULT_REPO_ORIGIN


def _normalize_repo_url(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    text = url.strip().strip('"').strip("'")
    if not text:
        return None
    if "://" in text:
        try:
            parsed = urllib.parse.urlsplit(text)
        except ValueError:
            return None
        path = parsed.path
    elif ":" in text and "@" in text.split(":", 1)[0]:
        # scp-подобный remote: git@github.com:owner/name.git
        path = text.split(":", 1)[1]
    else:
        # Локальный путь как remote: не выдаём host path.
        return None
    path = path.replace("\\", "/").strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None
    if any(part in (".", "..") for part in parts):
        return None
    if any(any(ch in part for ch in ("@", ":", "?", "#")) for part in parts):
        return None
    return "/".join(parts)


# --------------------------------------------------------------------------
# git CLI: только фиксированный argv, без сети
# --------------------------------------------------------------------------


def _git_env() -> dict:
    """Минимальное окружение вместо наследования произвольного env.

    ``GIT_OPTIONAL_LOCKS=0`` запрещает git обновлять index/refs как
    необязательный побочный эффект чтения (``git status`` остаётся
    read-only для нашего сценария).
    """
    keys = (
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "HOME",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    )
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _run_git(root: Path, extra: list[str]):
    argv = [
        "git",
        "-C",
        str(root),
        "-c",
        "core.fsmonitor=false",
        *extra,
    ]
    return subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        env=_git_env(),
        check=False,
    )


def _git_dirty(root: Path) -> tuple[bool | None, str]:
    try:
        proc = _run_git(root, [
            "status",
            "--porcelain",
            "--untracked-files=no",
            "--ignore-submodules=all",
        ])
    except FileNotFoundError:
        return None, "git_unavailable"
    except subprocess.TimeoutExpired:
        return None, "git_timeout"
    except (OSError, ValueError):
        return None, "git_unavailable"
    if proc.returncode != 0:
        return None, "git_unavailable"
    return bool(proc.stdout.strip()), ""


def _git_log(root: Path, sha: str,
             limit: int) -> list[dict] | None:
    try:
        proc = _run_git(root, [
            "log",
            "--no-show-signature",
            "--format=%H%x1f%ct%x1f%s",
            "-n",
            str(limit),
            sha,
        ])
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    commits = []
    text = proc.stdout.decode("utf-8", errors="replace")
    for line in text.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 3:
            continue
        commit_sha = parts[0].strip()
        if not _is_sha(commit_sha):
            continue
        try:
            committed_ts = int(parts[1])
        except (TypeError, ValueError):
            committed_ts = 0
        commits.append({
            "sha": commit_sha.lower(),
            "committed_at": (_iso_utc(datetime.datetime.fromtimestamp(
                committed_ts, datetime.timezone.utc))
                if committed_ts > 0 else None),
            "subject": parts[2][:_GIT_LOG_SUBJECT_MAX],
        })
    return commits


# --------------------------------------------------------------------------
# runtime version / env
# --------------------------------------------------------------------------


def _runtime_app_version() -> str | None:
    """APP_VERSION загруженного модуля config.settings (не из repo-файла)."""
    try:
        from config.settings import APP_VERSION
    except Exception:
        return None
    if not APP_VERSION:
        return None
    return str(APP_VERSION)


def _env_deployed_sha() -> str | None:
    value = os.environ.get("ADMINBOT_DEPLOYED_SHA")
    if _is_sha(value):
        return value.strip().lower()
    return None


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------


def _empty_record(code: str, reason: str,
                  observed_at: str | None = None,
                  runtime_version: str | None = None) -> dict:
    now = observed_at or _iso_utc(_utc_now())
    return {
        "schema": _SCHEMA,
        "code": code,
        "reason": reason,
        "repo_origin": DEFAULT_REPO_ORIGIN,
        "deployed_sha": None,
        "checkout_sha": None,
        "dirty": None,
        "upstream_head": {
            "sha": None,
            "ref": None,
            "observed_at": None,
            "reason": "no_remote_ref",
        },
        "version_provenance": {
            "runtime": runtime_version,
            "manifest": None,
            "consistent": None,
        },
        "local_source_verification": "unknown",
        "artifact": {
            "kind": "git_checkout",
            "release_branch": None,
            "schema_version": None,
        },
        "deployed_at": None,
        "observed_at": now,
        "sources": (
            ["runtime_app_version"] if runtime_version is not None else []
        ),
        "conflict": [],
        "local_identity": {
            "checkout_sha": None,
            "dirty": None,
            "checkout_mtime": None,
            "branch": None,
        },
        "effect": None,
        "previous_sha": None,
        "previous_version": None,
    }


def collect_identity(repo_root=None, *,
                     process_started_at=None) -> dict:
    """Единственная запись identity. Только чтение, без сети и без исполнения.

    ``process_started_at`` — существующий источник ``status.started_at``
    (ISO-строка или datetime). Если он не передан, identity не может быть
    ``verified_deployed``: честный код ``local_unverified`` / причина
    ``no_process_start``. D6 передаёт ``status.started_at``.
    """
    try:
        return _collect_identity(repo_root, process_started_at)
    except Exception:
        try:
            return _empty_record("unavailable", "internal_error")
        except Exception:
            return {
                "schema": _SCHEMA,
                "code": "unavailable",
                "reason": "internal_error",
                "repo_origin": DEFAULT_REPO_ORIGIN,
                "deployed_sha": None,
                "checkout_sha": None,
                "dirty": None,
                "upstream_head": {
                    "sha": None,
                    "ref": None,
                    "observed_at": None,
                    "reason": "no_remote_ref",
                },
                "version_provenance": {
                    "runtime": None,
                    "manifest": None,
                    "consistent": None,
                },
                "local_source_verification": "unknown",
                "artifact": {
                    "kind": "git_checkout",
                    "release_branch": None,
                    "schema_version": None,
                },
                "deployed_at": None,
                "observed_at": _iso_utc(_utc_now()),
                "sources": [],
                "conflict": [],
                "local_identity": {
                    "checkout_sha": None,
                    "dirty": None,
                    "checkout_mtime": None,
                    "branch": None,
                },
                "effect": None,
                "previous_sha": None,
                "previous_version": None,
            }


def _collect_identity(repo_root, process_started_at) -> dict:
    observed_at = _iso_utc(_utc_now())
    runtime_version = _runtime_app_version()
    root, root_reason = _resolve_root(repo_root)
    if root is None:
        return _empty_record("unavailable", root_reason,
                             observed_at, runtime_version)

    manifest_reason, manifest = _read_manifest(root)
    git_dir, git_reason = _resolve_git_dir(root)

    checkout_sha = None
    branch = None
    head_reason = git_reason or "no_git"
    if git_dir is not None:
        checkout_sha, branch, head_reason = _read_head(git_dir)

    upstream = _read_upstream(git_dir, branch)
    checkout_mtime = _checkout_mtime(git_dir)

    dirty = None
    dirty_reason = git_reason or "no_git"
    if git_dir is not None:
        dirty, dirty_reason = _git_dirty(root)

    env_sha = _env_deployed_sha()
    repo_origin = _repo_origin(git_dir)

    manifest_ok = manifest is not None
    manifest_sha = None
    manifest_version = None
    manifest_deployed_at = None
    effect = None
    previous_sha = None
    previous_version = None
    artifact_branch = branch
    artifact_schema_version = None
    if manifest_ok:
        manifest_sha = str(manifest["deployed_sha"]).strip().lower()
        manifest_version = str(manifest["version"]).strip()
        manifest_deployed_at = _parse_manifest_utc(manifest["deployed_at"])
        effect = str(manifest["effect"]).strip()
        previous_sha = manifest.get("previous_sha")
        if isinstance(previous_sha, str):
            previous_sha = previous_sha.strip().lower()
        previous_version = manifest.get("previous_version")
        if isinstance(previous_version, str):
            previous_version = previous_version.strip()
        if manifest.get("release_branch"):
            artifact_branch = manifest["release_branch"]
        artifact_schema_version = manifest.get("schema_version")

    deployed_at_iso = (_iso_utc(manifest_deployed_at)
                       if manifest_deployed_at is not None else None)
    if manifest_ok:
        deployed_sha = manifest_sha
    elif manifest_reason == "no_manifest":
        # env — резервный источник только при отсутствии манифеста.
        deployed_sha = env_sha
    else:
        deployed_sha = None

    if runtime_version is None or manifest_version is None:
        version_consistent = None
    else:
        version_consistent = manifest_version == runtime_version

    record = {
        "schema": _SCHEMA,
        "code": "",
        "reason": "",
        "repo_origin": repo_origin,
        "deployed_sha": deployed_sha,
        "checkout_sha": checkout_sha,
        "dirty": dirty,
        "upstream_head": upstream,
        "version_provenance": {
            "runtime": runtime_version,
            "manifest": manifest_version,
            "consistent": version_consistent,
        },
        "local_source_verification": "unknown",
        "artifact": {
            "kind": "git_checkout",
            "release_branch": artifact_branch,
            "schema_version": artifact_schema_version,
        },
        "deployed_at": deployed_at_iso,
        "observed_at": observed_at,
        "sources": [],
        "conflict": [],
        "local_identity": {
            "checkout_sha": checkout_sha,
            "dirty": dirty,
            "checkout_mtime": checkout_mtime,
            "branch": branch,
        },
        "effect": effect,
        "previous_sha": previous_sha,
        "previous_version": previous_version,
    }

    process_dt = _parse_datetime(process_started_at)

    code = ""
    reason = ""
    conflict = []
    conflict_values = None

    if manifest_reason == "permission_denied":
        code, reason = "unavailable", "permission_denied"
    elif manifest_reason == "path_denied":
        code, reason = "unknown", "path_denied"
    elif manifest_reason in (
            "manifest_invalid_json",
            "manifest_incomplete",
            "manifest_sha_invalid",
    ):
        code, reason = "unknown", manifest_reason
    elif git_reason == "path_denied":
        code, reason = "unknown", "path_denied"
    elif git_reason == "gitdir_unavailable":
        code, reason = "unknown", "gitdir_unavailable"
    elif git_reason == "no_git":
        code, reason = "unknown", "no_git"
    elif checkout_sha is None:
        code, reason = "unknown", (head_reason or "head_unresolved")
    elif manifest_ok:
        if env_sha is not None and env_sha != manifest_sha:
            code, reason = "mismatch", "sha_conflict"
            conflict = ["release_manifest", "env"]
            conflict_values = {
                "release_manifest": manifest_sha,
                "env": env_sha,
            }
        elif manifest_sha != checkout_sha:
            code, reason = "mismatch", "sha_conflict"
            conflict = ["release_manifest", "git_head"]
        elif version_consistent is None:
            code, reason = "local_unverified", "version_unknown"
        elif version_consistent is False:
            code, reason = "mismatch", "version_conflict"
            conflict = ["release_manifest", "runtime_app_version"]
        elif dirty is True:
            code, reason = "local_unverified", "dirty_tracked"
        elif dirty is None:
            code, reason = "local_unverified", (
                dirty_reason or "dirty_unknown")
        elif manifest.get("dirty_tracked") is True:
            code, reason = "local_unverified", "dirty_tracked"
        elif process_dt is None:
            code, reason = "local_unverified", "no_process_start"
        elif process_dt < manifest_deployed_at:
            code, reason = "mismatch", "process_predates_deploy"
            conflict = ["release_manifest", "process_start"]
        else:
            code, reason = "verified_deployed", ""
    else:
        # Манифеста нет: env может дать deployed_sha, но код не выше
        # local_unverified (SD1-D4-08).
        code, reason = "local_unverified", "no_manifest"

    if code == "verified_deployed":
        local_source_verification = "verified_deployed"
    elif checkout_sha is not None:
        local_source_verification = "local_unverified"
    else:
        local_source_verification = "unknown"

    sources = []
    if manifest_ok:
        sources.append("release_manifest")
    if checkout_sha is not None:
        sources.append("git_head")
    if dirty is not None:
        sources.append("git_cli")
    # env учитывается только когда манифеста нет; при битом манифесте env
    # не подменяет его (см. §1.1). В случае конфликта манифест/env оба
    # источника обязаны быть перечислены.
    if env_sha is not None and (
            manifest_reason == "no_manifest" or "env" in conflict):
        sources.append("env")
    if runtime_version is not None:
        sources.append("runtime_app_version")
    if process_dt is not None:
        sources.append("process_start")

    record.update({
        "code": code,
        "reason": reason,
        "deployed_sha": deployed_sha,
        "sources": sources,
        "conflict": conflict,
        "local_source_verification": local_source_verification,
    })
    if conflict_values is not None and code == "mismatch":
        record["conflict_values"] = conflict_values
    return record


# --------------------------------------------------------------------------
# recent commits (D6 consumer)
# --------------------------------------------------------------------------


def _commits_result(code: str, reason: str, basis: dict | None,
                    commits: list[dict],
                    observed_at: str) -> dict:
    return {
        "schema": _SCHEMA,
        "code": code,
        "reason": reason,
        "basis": basis or {"kind": "unknown", "sha": None},
        "commits": commits,
        "observed_at": observed_at,
    }


def recent_commits(repo_root=None, *, limit: int = 5,
                   basis: str = "deployed") -> dict:
    """Последние коммиты относительно basis; вне basis — deployed=false.

    ``basis``: ``deployed`` (манифест, иначе HEAD), ``head``/``checkout``
    или явный 40-hex SHA. ``limit`` клампится в 1..5. Как и
    ``collect_identity``, функция не бросает исключений.
    """
    observed_at = _iso_utc(_utc_now())
    try:
        return _recent_commits(repo_root, limit, basis, observed_at)
    except Exception:
        return _commits_result("unavailable", "internal_error", None, [],
                               observed_at)


def _recent_commits(repo_root, limit, basis, observed_at: str) -> dict:
    try:
        clamped = int(limit)
    except (TypeError, ValueError):
        clamped = 1
    clamped = max(1, min(_GIT_LOG_LIMIT_MAX, clamped))

    root, root_reason = _resolve_root(repo_root)
    if root is None:
        return _commits_result("unavailable", root_reason, None, [],
                               observed_at)

    git_dir, git_reason = _resolve_git_dir(root)
    if git_dir is None:
        return _commits_result("unknown", git_reason or "no_git",
                               None, [], observed_at)

    checkout_sha, _branch, head_reason = _read_head(git_dir)
    manifest_reason, manifest = _read_manifest(root)
    deployed_sha = None
    if manifest is not None:
        deployed_sha = str(manifest["deployed_sha"]).strip().lower()

    basis_text = basis.strip().lower() if isinstance(basis, str) else ""
    if basis_text in ("deployed", "deployed_sha"):
        if deployed_sha is not None:
            basis_sha, kind = deployed_sha, "deployed_sha"
        else:
            basis_sha, kind = checkout_sha, "checkout_sha"
    elif basis_text in ("head", "checkout", "checkout_sha"):
        basis_sha, kind = checkout_sha, "checkout_sha"
    elif _is_sha(basis):
        basis_sha, kind = basis.strip().lower(), "explicit"
    else:
        return _commits_result("unknown", "head_unresolved",
                               {"kind": "unknown", "sha": None}, [],
                               observed_at)

    if basis_sha is None:
        reason = head_reason or "head_unresolved"
        if manifest_reason == "no_manifest":
            reason = "no_manifest"
        return _commits_result("unknown", reason,
                               {"kind": kind, "sha": None}, [],
                               observed_at)

    commits = _git_log(root, basis_sha, clamped)
    if commits is None:
        return _commits_result("unknown", "git_unavailable",
                               {"kind": kind, "sha": basis_sha}, [],
                               observed_at)
    is_deployed_basis = deployed_sha is not None and basis_sha == deployed_sha
    for commit in commits:
        commit["deployed"] = bool(
            is_deployed_basis and commit["sha"] == deployed_sha)
    return _commits_result("ok", "", {"kind": kind, "sha": basis_sha},
                           commits, observed_at)
