#!/usr/bin/env python3
"""Release manifest writer for deploy identity (SELF-DIAG-01 corrective §6).

Штатный deploy-путь проекта — обновление checkout + ``systemctl restart
admin_bot``. Этот скрипт фиксирует фактически выкладываемую версию ДО
рестарта: пишет ``<repo_root>/.deploy/release.json`` (schema 1) атомарно
(временный файл в ``.deploy/`` + ``os.replace``).

Формат — тот же, что читает ``services/deploy_identity.py``:
``deployed_sha`` = ``git rev-parse HEAD`` текущего checkout, ``version`` —
``APP_VERSION`` из ``config/settings.py`` ЭТОГО checkout (AST-разбор, без
импорта/исполнения), ``deployed_at`` — UTC-время записи (start marker для
сравнения с ``status.started_at`` живого процесса), ``effect`` =
``deploy``/``rollback``, ``previous_*`` — из предыдущего валидного манифеста.

Скрипт не выдумывает identity: грязный tracked-дерево (код не совпадает с
SHA) отклоняется, отсутствие HEAD/version — ошибка, повторная запись не
создаёт историю задним числом. Manifest остаётся на диске после рестарта и
переживает ``git pull`` (``.deploy/`` не отслеживается git).

Использование (на сервере, из корня checkout, до рестарта)::

    python tools/release_manifest.py
    sudo systemctl restart admin_bot

Либо одной командой (если скрипт запущен с правами на restart)::

    python tools/release_manifest.py --restart

Коды выхода: 0 — успех, 2 — некорректный checkout/аргументы, 3 — ошибка
записи, 4 — ошибка ``systemctl restart``.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = 1
MANIFEST_REL_PATH = ".deploy/release.json"
EFFECTS = ("deploy", "rollback")
DEFAULT_UNIT = "admin_bot"

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_GIT_TIMEOUT_SECONDS = 10.0
_MANIFEST_MAX_BYTES = 64 * 1024
_EFFECT_LABEL_RE = re.compile(r"^[^\s/\\\x00-\x1f]{1,64}$")


class ManifestError(RuntimeError):
    """Checkout/аргументы не позволяют записать достоверный манифест."""


class ManifestWriteError(RuntimeError):
    """Манифест не удалось атомарно записать."""


def _iso_utc(value: datetime.datetime) -> str:
    return value.astimezone(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z")


def resolve_repo_root(repo_root: str | os.PathLike | None = None) -> Path:
    """Корень checkout: каталог с ``.git`` и ``config/settings.py``."""
    raw = Path(repo_root if repo_root is not None else ".")
    try:
        root = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ManifestError(f"repo root is not accessible: {exc}") from exc
    if not root.is_dir():
        raise ManifestError(f"repo root is not a directory: {root}")
    if not (root / ".git").exists():
        raise ManifestError(f"not a git checkout (no .git): {root}")
    if not (root / "config" / "settings.py").is_file():
        raise ManifestError(
            f"config/settings.py is missing in {root}")
    return root


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    argv = ["git", "-C", str(root), *args]
    try:
        return subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ManifestError("git binary is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise ManifestError(
            f"git {' '.join(args)} timed out") from exc
    except OSError as exc:
        raise ManifestError(f"git {' '.join(args)} failed: {exc}") from exc


def head_sha(root: Path) -> str:
    proc = _git(root, "rev-parse", "--verify", "HEAD")
    sha = (proc.stdout or "").strip()
    if proc.returncode != 0 or not _SHA_RE.match(sha):
        tail = (proc.stderr or "").strip().splitlines()
        reason = tail[-1][:200] if tail else f"rc={proc.returncode}"
        raise ManifestError(f"cannot resolve HEAD: {reason}")
    return sha.lower()


def current_branch(root: Path) -> str | None:
    proc = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if proc.returncode != 0:
        return None
    branch = (proc.stdout or "").strip()
    if not branch or any(ch in branch for ch in " ~^:?*[\\\x7f"):
        return None
    return branch


def tracked_dirty(root: Path) -> bool:
    """Только tracked-изменения: untracked-файлы не меняют код версии.

    ``--untracked-files=no`` намеренно: на проде есть постоянные untracked
    рабочие файлы, которые не влияют на исполняемый код.
    """
    proc = _git(root, "status", "--porcelain", "--untracked-files=no",
                "--ignore-submodules=all")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        reason = tail[-1][:200] if tail else f"rc={proc.returncode}"
        raise ManifestError(f"git status failed: {reason}")
    return bool((proc.stdout or "").strip())


def read_app_version(root: Path) -> str | None:
    """``APP_VERSION`` из config/settings.py без импорта/исполнения кода."""
    path = root / "config" / "settings.py"
    try:
        # UTF-8 BOM в settings.py допустим для Python-импорта; AST-разбор
        # должен читать так же, иначе реальный checkout ложно «без версии».
        source = path.read_text(encoding="utf-8-sig", errors="strict")
    except (OSError, UnicodeError):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    def _constant(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.strip()
        return None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP_VERSION":
                    return _constant(node.value)
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "APP_VERSION":
                return _constant(node.value)
    return None


def previous_release(root: Path) -> tuple[str | None, str | None]:
    """(previous_sha, previous_version) из предыдущего валидного манифеста.

    Битый/отсутствующий манифест не подменяется догадкой: обе величины
    остаются None. Значения читаются ДО перезаписи, поэтому rollback честно
    указывает версию, которую заменяет.
    """
    path = root / MANIFEST_REL_PATH
    try:
        if path.is_symlink() or path.stat().st_size > _MANIFEST_MAX_BYTES:
            return None, None
        data = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, ValueError, UnicodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    sha = data.get("deployed_sha")
    version = data.get("version")
    sha = sha.strip().lower() if isinstance(sha, str) else None
    version = version.strip() if isinstance(version, str) else None
    if not sha or not _SHA_RE.match(sha):
        sha = None
    if version is not None and not _EFFECT_LABEL_RE.match(version):
        version = None
    return sha, version


def _safe_deployer(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text or len(text) > 100:
        return None
    if any(ch in text for ch in ("/", "\\", "\x00", "\n", "\r")):
        return None
    return text


def build_manifest(root: Path, *, effect: str = "deploy",
                   deployer: str | None = None,
                   now: datetime.datetime | None = None) -> dict:
    """Собрать schema-1 манифест для текущего checkout (без записи)."""
    if effect not in EFFECTS:
        raise ManifestError(
            f"effect must be one of {EFFECTS}, got {effect!r}")
    if tracked_dirty(root):
        raise ManifestError(
            "tracked working tree is dirty: deployed SHA would not identify "
            "the running code; commit/stash changes first")
    sha = head_sha(root)
    version = read_app_version(root)
    if not version:
        raise ManifestError(
            "APP_VERSION not found in config/settings.py; cannot record "
            "an honest version")
    if not _EFFECT_LABEL_RE.match(version):
        raise ManifestError(f"APP_VERSION is not a safe label: {version!r}")
    previous_sha, previous_version = previous_release(root)
    deployed_at = now or datetime.datetime.now(datetime.timezone.utc)
    manifest = {
        "schema": SCHEMA,
        "deployed_sha": sha,
        "version": version,
        "deployed_at": _iso_utc(deployed_at),
        "effect": effect,
        "previous_sha": previous_sha,
        "previous_version": previous_version,
        "dirty_tracked": False,
    }
    branch = current_branch(root)
    if branch:
        manifest["release_branch"] = branch
    name = _safe_deployer(deployer if deployer is not None
                          else os.environ.get("ADMINBOT_DEPLOYER"))
    if name:
        manifest["deployer"] = name
    return manifest


def write_manifest(root: Path, manifest: dict) -> Path:
    """Атомарная запись ``.deploy/release.json`` (tmp + os.replace)."""
    deploy_dir = root / ".deploy"
    try:
        resolved_dir = deploy_dir.resolve() if deploy_dir.exists() else None
    except OSError as exc:
        raise ManifestWriteError(f"cannot resolve .deploy: {exc}") from exc
    if deploy_dir.is_symlink() or (
            resolved_dir is not None and resolved_dir != deploy_dir):
        raise ManifestWriteError(".deploy must not be a symlink")
    try:
        deploy_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    except OSError as exc:
        raise ManifestWriteError(f"cannot create .deploy: {exc}") from exc
    target = deploy_dir / "release.json"
    if target.is_symlink():
        raise ManifestWriteError(".deploy/release.json must not be a symlink")

    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="release.", suffix=".tmp",
                                        dir=str(deploy_dir))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
        tmp_path = None
        try:
            dir_fd = os.open(deploy_dir, os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except OSError as exc:
        raise ManifestWriteError(
            f"cannot write {MANIFEST_REL_PATH}: {exc}") from exc
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return target


def restart_service(unit: str) -> int:
    try:
        proc = subprocess.run(
            ["systemctl", "restart", unit],
            shell=False,
            capture_output=True,
            text=True,
            timeout=90.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"[release-manifest] systemctl restart {unit} failed: {exc}",
              file=sys.stderr)
        return 4
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        print(f"[release-manifest] systemctl restart {unit} rc="
              f"{proc.returncode}: {tail[-1] if tail else ''}",
              file=sys.stderr)
        return 4
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Record the deployed release manifest "
                     "(.deploy/release.json) for the current checkout."))
    parser.add_argument("--repo-root", default=".",
                        help="path to the deployed git checkout")
    parser.add_argument("--effect", choices=EFFECTS, default="deploy",
                        help="deploy (default) or rollback")
    parser.add_argument("--deployer", default=None,
                        help="safe label for the deploy operator")
    parser.add_argument("--restart", action="store_true",
                        help="restart systemd unit AFTER writing the manifest")
    parser.add_argument("--unit", default=DEFAULT_UNIT,
                        help=f"systemd unit for --restart (default {DEFAULT_UNIT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the manifest without writing it")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = resolve_repo_root(args.repo_root)
        manifest = build_manifest(root, effect=args.effect,
                                  deployer=args.deployer)
    except ManifestError as exc:
        print(f"[release-manifest] error: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2,
                         sort_keys=True))
        return 0
    try:
        path = write_manifest(root, manifest)
    except ManifestWriteError as exc:
        print(f"[release-manifest] error: {exc}", file=sys.stderr)
        return 3
    relative = path.relative_to(root).as_posix()
    print(f"[release-manifest] wrote {relative} | "
          f"sha={manifest['deployed_sha']} version={manifest['version']} "
          f"effect={manifest['effect']} "
          f"deployed_at={manifest['deployed_at']}")
    if args.restart:
        return restart_service(args.unit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
