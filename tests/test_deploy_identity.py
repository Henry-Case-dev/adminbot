"""D4-A: контракт deployed identity.

Источник: ``plans/features/self-diag-01/architecture-d4-identity.md``
§1-§3, §5.2 (таблица 14 сценариев) и §5.1 (публичный API).

Тесты герметичны: ``tmp_path``, рукописные ``.git``-структуры и локальный
``git init`` без сети. Прод, реальный deploy-манифест и БД не используются.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from config.settings import APP_VERSION
from services import deploy_identity as di

SHA_A = "a" * 40
SHA_B = "b" * 40
BRANCH = "release/2.58.197"
ORIGIN_URL = "https://github.com/Henry-Case-dev/adminbot.git"
GIT = shutil.which("git")
requires_git = pytest.mark.skipif(
    GIT is None, reason="git binary is not available")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_ref(root, ref: str, sha: str) -> None:
    path = root / ".git" / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sha + "\n", encoding="ascii")


def _fake_repo(tmp_path, *, sha: str = SHA_A, branch: str = BRANCH,
               origin: str | None = ORIGIN_URL):
    """Рукописный checkout: HEAD -> ref, config; без git-объектов."""
    root = tmp_path / "repo"
    root.mkdir()
    git_dir = root / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n",
                                  encoding="ascii")
    _write_ref(root, f"refs/heads/{branch}", sha)
    config = "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
    if origin:
        config += f'[remote "origin"]\n\turl = {origin}\n'
    (git_dir / "config").write_text(config, encoding="utf-8")
    return root


def _manifest_data(sha: str, **overrides) -> dict:
    data = {
        "schema": 1,
        "deployed_sha": sha,
        "release_branch": BRANCH,
        "version": APP_VERSION,
        "deployed_at": _iso(_now() - timedelta(minutes=10)),
        "effect": "deploy",
        "previous_sha": SHA_B,
        "previous_version": "2.58.188",
        "dirty_tracked": False,
    }
    data.update(overrides)
    return data


def _write_manifest(root, data) -> None:
    path = root / ".deploy" / "release.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _real_repo(tmp_path, *, origin: str | None = ORIGIN_URL):
    """Настоящий локальный git-репозиторий (без сети) с одним коммитом."""
    root = tmp_path / "real"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "D4A Tests")
    if origin:
        _git(root, "remote", "add", "origin", origin)
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "initial")
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    return root, sha


# --------------------------------------------------------------------------
# 1. нет манифеста -> local_unverified, никогда verified
# --------------------------------------------------------------------------


def test_no_manifest_is_local_unverified_never_verified(tmp_path):
    root = _fake_repo(tmp_path)
    _write_ref(root, f"refs/remotes/origin/{BRANCH}", SHA_B)

    record = di.collect_identity(root)

    assert record["code"] == "local_unverified"
    assert record["reason"] == "no_manifest"
    assert record["deployed_sha"] is None
    assert record["checkout_sha"] == SHA_A
    assert record["local_source_verification"] == "local_unverified"
    assert record["upstream_head"]["sha"] == SHA_B
    assert record["upstream_head"]["ref"] == f"refs/remotes/origin/{BRANCH}"
    assert record["upstream_head"]["observed_at"]
    assert record["local_identity"]["branch"] == BRANCH
    assert record["local_identity"]["upstream_ref"] == (
        f"refs/remotes/origin/{BRANCH}")
    assert record["local_identity"]["checkout_mtime"]
    assert record["version_provenance"]["runtime"] == APP_VERSION
    assert record["version_provenance"]["manifest"] is None
    assert record["repo_origin"] == "Henry-Case-dev/adminbot"


# --------------------------------------------------------------------------
# 2. манифест != HEAD -> mismatch с обоими SHA
# --------------------------------------------------------------------------


def test_manifest_sha_differs_from_head_is_mismatch_with_both_shas(tmp_path):
    root = _fake_repo(tmp_path, sha=SHA_B)
    _write_manifest(root, _manifest_data(SHA_A))

    record = di.collect_identity(root)

    assert record["code"] == "mismatch"
    assert record["reason"] == "sha_conflict"
    assert record["deployed_sha"] == SHA_A
    assert record["checkout_sha"] == SHA_B
    assert record["local_source_verification"] == "local_unverified"
    assert record["conflict"] == ["release_manifest", "git_head"]


# --------------------------------------------------------------------------
# 3. грязное дерево -> verified=false
# --------------------------------------------------------------------------


@requires_git
def test_dirty_tracked_tree_is_never_verified(tmp_path):
    root, sha = _real_repo(tmp_path)
    _write_manifest(root, _manifest_data(sha))
    (root / "tracked.txt").write_text("modified after deploy\n",
                                      encoding="utf-8")
    index = root / ".git" / "index"
    index_before = (index.stat().st_mtime_ns, index.read_bytes())

    record = di.collect_identity(root, process_started_at=_now())

    assert record["dirty"] is True
    assert record["code"] == "local_unverified"
    assert record["reason"] == "dirty_unknown"
    assert record["local_source_verification"] == "local_unverified"
    # GIT_OPTIONAL_LOCKS=0: git status не переписывает index.
    assert (index.stat().st_mtime_ns, index.read_bytes()) == index_before


# --------------------------------------------------------------------------
# 4. нет .git -> unknown/no_git
# --------------------------------------------------------------------------


def test_no_git_directory_is_unknown(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] == "no_git"
    assert record["checkout_sha"] is None
    assert record["deployed_sha"] is None
    assert record["local_source_verification"] == "unknown"


# --------------------------------------------------------------------------
# 5. битый JSON -> unknown/manifest_invalid_json без утечки текста
# --------------------------------------------------------------------------


def test_broken_manifest_json_is_unknown_without_leaking_content(tmp_path):
    root = _fake_repo(tmp_path)
    (root / ".deploy").mkdir()
    (root / ".deploy" / "release.json").write_text(
        '{broken json "token": "should-not-leak"', encoding="utf-8")

    record = di.collect_identity(root)
    dumped = json.dumps(record, ensure_ascii=False)

    assert record["code"] == "unknown"
    assert record["reason"] == "manifest_invalid_json"
    assert "should-not-leak" not in dumped
    assert str(root) not in dumped


# --------------------------------------------------------------------------
# 6. symlink / gitdir вне репозитория -> отказ
# --------------------------------------------------------------------------


def test_gitdir_file_outside_repo_is_rejected(tmp_path):
    outside = tmp_path / "outside_git"
    outside.mkdir()
    (outside / "HEAD").write_text(SHA_A + "\n", encoding="ascii")
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").write_text(f"gitdir: {outside}\n", encoding="utf-8")

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] in ("path_denied", "gitdir_unavailable")
    assert record["checkout_sha"] is None


def test_dot_git_symlink_outside_repo_is_rejected(tmp_path):
    outside = tmp_path / "outside_git"
    outside.mkdir()
    (outside / "HEAD").write_text(SHA_A + "\n", encoding="ascii")
    root = tmp_path / "repo"
    root.mkdir()
    try:
        os.symlink(outside, root / ".git", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink is not available: {exc}")

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] in ("path_denied", "gitdir_unavailable")
    assert record["checkout_sha"] is None


# --------------------------------------------------------------------------
# 7. denylist
# --------------------------------------------------------------------------


def test_path_is_denied_contract_set():
    denied = [
        ".env",
        ".env.local",
        "backups/db.sqlite",
        "data/x.db",
        "cert.pem",
        "deploy_commands.txt",
        "cookies.txt",
        ".git/config",
        "logs/app.log",
        "id_rsa",
        "deploy_result.json",
        "deploy_evil.py",
        "secret.txt",
        "pre_migration_1.db",
        "media/cookies.txt",
        "C:/Windows/win.ini",
        "../outside.txt",
        "",
    ]
    for path in denied:
        assert di.path_is_denied(path) is True, path

    allowed = [
        ".env.example",
        "services/deploy_identity.py",
        "tests/test_deploy_identity.py",
        "README.md",
        "media/common/goodmorning.jpg",
    ]
    for path in allowed:
        assert di.path_is_denied(path) is False, path


# --------------------------------------------------------------------------
# 8. код из репозитория не исполняется
# --------------------------------------------------------------------------


def test_repository_code_is_never_imported_or_executed(tmp_path, monkeypatch):
    root = _fake_repo(tmp_path)
    marker = tmp_path / "executed.marker"
    trap_name = "trap_module_d4a"
    (root / f"{trap_name}.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "raise SystemExit('trap')\n",
        encoding="utf-8",
    )

    calls = []
    real_run = subprocess.run

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(di.subprocess, "run", spy)
    before = set(sys.modules)
    di.collect_identity(root, process_started_at=_now())
    di.recent_commits(root, limit=5, basis="deployed")

    assert not marker.exists()
    assert trap_name not in sys.modules
    assert trap_name not in (set(sys.modules) - before)
    assert calls
    for args, kwargs in calls:
        argv = args[0]
        assert isinstance(argv, list) and argv[0] == "git"
        assert kwargs.get("shell") is False
        assert all(trap_name not in str(item) for item in argv)


# --------------------------------------------------------------------------
# 9. все условия выполнены -> verified_deployed
# --------------------------------------------------------------------------


@requires_git
def test_verified_deployed_requires_manifest_head_clean_version_start(tmp_path):
    root, sha = _real_repo(tmp_path)
    deployed_at = _now() - timedelta(minutes=10)
    _write_manifest(root, _manifest_data(sha, deployed_at=_iso(deployed_at)))

    record = di.collect_identity(
        root, process_started_at=_iso(_now()))

    assert record["code"] == "verified_deployed"
    assert record["reason"] == ""
    assert record["deployed_sha"] == sha
    assert record["checkout_sha"] == sha
    assert record["dirty"] is False
    assert record["local_source_verification"] == "verified_deployed"
    assert record["version_provenance"] == {
        "runtime": APP_VERSION,
        "manifest": APP_VERSION,
        "consistent": True,
    }
    assert record["deployed_at"] == _iso(deployed_at)
    assert record["artifact"]["kind"] == "git_checkout"
    assert record["artifact"]["release_branch"] == BRANCH
    assert "release_manifest" in record["sources"]
    assert "git_head" in record["sources"]
    assert "git_cli" in record["sources"]
    assert "process_start" in record["sources"]
    assert record["repo_origin"] == "Henry-Case-dev/adminbot"


# --------------------------------------------------------------------------
# 10. процесс старше deployed_at -> mismatch/process_predates_deploy
# --------------------------------------------------------------------------


@requires_git
def test_process_started_before_deploy_is_not_verified(tmp_path):
    root, sha = _real_repo(tmp_path)
    deployed_at = _now() - timedelta(minutes=1)
    _write_manifest(root, _manifest_data(sha, deployed_at=_iso(deployed_at)))

    record = di.collect_identity(
        root, process_started_at=deployed_at - timedelta(minutes=5))

    assert record["code"] == "mismatch"
    assert record["reason"] == "process_predates_deploy"
    assert record["local_source_verification"] == "local_unverified"


# --------------------------------------------------------------------------
# 11. нет repo_root / путь — файл -> unavailable, без исключения
# --------------------------------------------------------------------------


def test_missing_or_file_repo_root_is_unavailable(tmp_path):
    missing = di.collect_identity(tmp_path / "does-not-exist")
    assert missing["code"] == "unavailable"
    assert missing["reason"] == "root_missing"

    file_path = tmp_path / "a_file.txt"
    file_path.write_text("x", encoding="utf-8")
    not_dir = di.collect_identity(file_path)
    assert not_dir["code"] == "unavailable"
    assert not_dir["reason"] == "root_not_dir"

    none_root = di.collect_identity(None)
    assert none_root["code"] == "unavailable"
    assert none_root["reason"] == "root_missing"


# --------------------------------------------------------------------------
# 12. recent_commits: кламп лимита, basis, отсутствие исключений
# --------------------------------------------------------------------------


@requires_git
def test_recent_commits_clamps_limit_and_marks_deployed_basis(tmp_path):
    root, sha = _real_repo(tmp_path)
    for index in range(6):
        (root / f"file_{index}.txt").write_text(str(index),
                                                 encoding="utf-8")
        _git(root, "add", f"file_{index}.txt")
        _git(root, "commit", "-q", "-m", f"commit {index}")

    one = di.recent_commits(root, limit=0, basis="deployed")
    assert one["code"] == "ok"
    assert len(one["commits"]) == 1
    assert one["basis"]["kind"] == "checkout_sha"
    assert all(commit["deployed"] is False for commit in one["commits"])

    five = di.recent_commits(root, limit=100, basis="head")
    assert five["code"] == "ok"
    assert len(five["commits"]) == 5
    assert all(commit["deployed"] is False for commit in five["commits"])

    invalid = di.recent_commits(root, limit="not-an-int", basis="nonsense")
    assert invalid["code"] == "unknown"
    assert invalid["reason"]
    assert invalid["commits"] == []

    _write_manifest(root, _manifest_data(sha))
    deployed = di.recent_commits(root, limit=5, basis="deployed")
    assert deployed["basis"]["kind"] == "deployed_sha"
    assert len(deployed["commits"]) == 1
    assert deployed["commits"][0]["sha"] == sha
    assert deployed["commits"][0]["deployed"] is True

    head = di.recent_commits(root, limit=5, basis="head")
    assert all(commit["deployed"] is False for commit in head["commits"])


# --------------------------------------------------------------------------
# 13. версия манифеста != runtime APP_VERSION -> mismatch/version_conflict
# --------------------------------------------------------------------------


@requires_git
def test_manifest_version_conflict_with_runtime(tmp_path):
    root, sha = _real_repo(tmp_path)
    _write_manifest(root, _manifest_data(sha, version="0.0.0"))

    record = di.collect_identity(root, process_started_at=_now())

    assert record["code"] == "mismatch"
    assert record["reason"] == "version_conflict"
    assert record["version_provenance"]["consistent"] is False
    assert record["local_source_verification"] == "local_unverified"


# --------------------------------------------------------------------------
# 14. env-фолбэк: манифеста нет, ADMINBOT_DEPLOYED_SHA валиден
# --------------------------------------------------------------------------


def test_env_fallback_without_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMINBOT_DEPLOYED_SHA", SHA_B)
    root = _fake_repo(tmp_path)

    record = di.collect_identity(root)

    assert record["deployed_sha"] == SHA_B
    assert "env" in record["sources"]
    assert record["code"] == "local_unverified"
    assert record["reason"] == "no_manifest"
    assert record["local_source_verification"] == "local_unverified"


def test_env_sha_is_recorded_even_without_git(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMINBOT_DEPLOYED_SHA", SHA_B)
    root = tmp_path / "plain"
    root.mkdir()

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] == "no_git"
    assert record["deployed_sha"] == SHA_B
    assert "env" in record["sources"]


# --------------------------------------------------------------------------
# contract extras: invalid deployed_at, missing fields, unreadable, env conflict
# --------------------------------------------------------------------------


@pytest.mark.parametrize("deployed_at", [
    "2026-11-12 20:31:07",
    "2026-11-12T20:31:07+05:00",
    "",
    123,
])
def test_manifest_invalid_deployed_at_is_unknown(tmp_path, deployed_at):
    root = _fake_repo(tmp_path)
    _write_manifest(root, _manifest_data(SHA_A, deployed_at=deployed_at))

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] == "manifest_incomplete"
    assert record["deployed_at"] is None


@pytest.mark.parametrize("field", [
    "deployed_sha",
    "deployed_at",
    "version",
    "effect",
])
def test_manifest_missing_required_field_is_unknown(tmp_path, field):
    root = _fake_repo(tmp_path)
    data = _manifest_data(SHA_A)
    data.pop(field)
    _write_manifest(root, data)

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] == "manifest_incomplete"


def test_unreadable_manifest_is_unavailable(tmp_path):
    root = _fake_repo(tmp_path)
    # Каталог на месте файла — реальный OSError без chmod-хаков.
    (root / ".deploy" / "release.json").mkdir(parents=True)

    record = di.collect_identity(root)

    assert record["code"] == "unavailable"
    assert record["reason"] == "permission_denied"


def test_manifest_sha_invalid_is_unknown(tmp_path):
    root = _fake_repo(tmp_path)
    _write_manifest(root, _manifest_data("not-a-40-hex-sha"))

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] == "manifest_sha_invalid"


def test_manifest_unknown_key_is_rejected(tmp_path):
    root = _fake_repo(tmp_path)
    _write_manifest(root, _manifest_data(SHA_A, extra_key="surprise"))

    record = di.collect_identity(root)

    assert record["code"] == "unknown"
    assert record["reason"] == "manifest_incomplete"


def test_manifest_env_conflict_keeps_both_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMINBOT_DEPLOYED_SHA", SHA_B)
    root = _fake_repo(tmp_path, sha=SHA_A)
    _write_manifest(root, _manifest_data(SHA_A))

    record = di.collect_identity(root)

    assert record["code"] == "mismatch"
    assert record["reason"] == "sha_conflict"
    assert record["conflict"] == ["release_manifest", "env"]
    assert record["conflict_values"] == {
        "release_manifest": SHA_A,
        "env": SHA_B,
    }
    assert record["deployed_sha"] == SHA_A
    assert record["checkout_sha"] == SHA_A
    assert "env" in record["sources"]


@requires_git
def test_manifest_dirty_tracked_blocks_verified(tmp_path):
    root, sha = _real_repo(tmp_path)
    _write_manifest(root, _manifest_data(sha, dirty_tracked=True))

    record = di.collect_identity(root, process_started_at=_now())

    assert record["code"] == "local_unverified"
    assert record["reason"] == "dirty_unknown"


@requires_git
def test_missing_process_start_is_local_unverified(tmp_path):
    root, sha = _real_repo(tmp_path)
    _write_manifest(root, _manifest_data(sha))

    record = di.collect_identity(root)

    assert record["code"] == "local_unverified"
    assert record["reason"] == "no_process_start"
    assert record["local_source_verification"] == "local_unverified"


# --------------------------------------------------------------------------
# негатив по утечкам: секреты и абсолютные пути не попадают в запись
# --------------------------------------------------------------------------


def test_record_contains_no_secrets_or_host_paths(tmp_path):
    root = _fake_repo(
        tmp_path,
        origin="https://user:tok-secret@github.com/Henry-Case-dev/adminbot.git",
    )
    (root / ".env").write_text(
        "ADMIN_TOKEN=super-secret-value\n", encoding="utf-8")

    record = di.collect_identity(root, process_started_at=_now())
    dumped = json.dumps(record, ensure_ascii=False)

    assert record["repo_origin"] == "Henry-Case-dev/adminbot"
    assert "tok-secret" not in dumped
    assert "super-secret-value" not in dumped
    assert str(tmp_path) not in dumped
    assert str(root) not in dumped
    assert "C:\\" not in dumped
    assert "/home/" not in dumped
