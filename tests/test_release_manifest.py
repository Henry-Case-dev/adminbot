"""SELF-DIAG-01 corrective §6: producer `.deploy/release.json` + identity.

Проверяется связка «deploy producer → deploy_identity», а не только форма
JSON: манифест пишется для фактического HEAD, переживает рестарт, не
подменяет checkout исполняемой версией и честно даёт mismatch после смены
checkout/версии. Тесты герметичны: локальный git init, без сети/прода.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from config.settings import APP_VERSION
from services import deploy_identity as di
from tools import release_manifest as rm

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(
    GIT is None, reason="git binary is not available")


def _git(root, *args) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} rc={proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()}")
    return proc


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_patch(version: str) -> str:
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def _repo(tmp_path, *, version: str = APP_VERSION):
    """Настоящий локальный checkout: config/settings.py + один коммит."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Corrective Tests")
    (root / "config").mkdir()
    (root / "config" / "settings.py").write_text(
        f'APP_VERSION = "{version}"\n', encoding="utf-8")
    (root / ".gitignore").write_text(".deploy/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    return root, sha


def _commit(root, *, version: str | None = None,
            message: str = "next") -> str:
    if version is not None:
        (root / "config" / "settings.py").write_text(
            f'APP_VERSION = "{version}"\n', encoding="utf-8")
    else:
        with (root / "tracked.txt").open("a", encoding="utf-8") as handle:
            handle.write(f"{message}\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _manifest_path(root):
    return root / rm.MANIFEST_REL_PATH


def _read_manifest(root) -> dict:
    return json.loads(_manifest_path(root).read_text(encoding="utf-8"))


# ── producer: schema + фактический HEAD ───────────────────────────────────

@requires_git
def test_producer_records_schema_valid_manifest_for_head(tmp_path):
    root, sha = _repo(tmp_path)

    manifest = rm.build_manifest(root)
    path = rm.write_manifest(root, manifest)

    assert path == _manifest_path(root)
    data = _read_manifest(root)
    assert data["schema"] == 1
    assert data["deployed_sha"] == sha
    assert data["version"] == APP_VERSION
    assert data["effect"] == "deploy"
    assert data["deployed_at"].endswith("Z")
    assert data["release_branch"] == "main"
    assert data["previous_sha"] is None
    assert data["previous_version"] is None
    assert data["dirty_tracked"] is False
    assert set(data) <= {
        "schema", "deployed_sha", "release_branch", "version", "deployed_at",
        "effect", "previous_sha", "previous_version", "dirty_tracked",
        "schema_version", "deployer",
    }


@requires_git
def test_producer_identity_agrees_with_running_process(tmp_path):
    root, sha = _repo(tmp_path)
    rm.write_manifest(root, rm.build_manifest(root))

    started = datetime.now(timezone.utc) + timedelta(seconds=2)
    record = di.collect_identity(root, process_started_at=started)

    assert record["code"] == "verified_deployed", record
    assert record["reason"] == ""
    assert record["deployed_sha"] == sha
    assert record["checkout_sha"] == sha
    assert record["dirty"] is False
    assert record["deployed_at"]
    assert record["process_started_at"] == _iso(started)
    assert record["version_provenance"]["manifest"] == APP_VERSION
    assert record["version_provenance"]["consistent"] is True
    assert "release_manifest" in record["sources"]
    assert "git_head" in record["sources"]
    assert "process_start" in record["sources"]


@requires_git
def test_manifest_survives_restart_without_rewrite(tmp_path):
    root, sha = _repo(tmp_path)
    rm.write_manifest(root, rm.build_manifest(root))
    first_bytes = _manifest_path(root).read_bytes()

    first = di.collect_identity(
        root, process_started_at=datetime.now(timezone.utc))
    second = di.collect_identity(
        root, process_started_at=datetime.now(timezone.utc)
        + timedelta(minutes=5))

    assert first["code"] == second["code"] == "verified_deployed"
    assert first["deployed_at"] == second["deployed_at"]
    assert second["deployed_sha"] == sha
    assert _manifest_path(root).read_bytes() == first_bytes


@requires_git
def test_checkout_is_not_reported_as_deployed_without_manifest(tmp_path):
    root, sha = _repo(tmp_path)

    record = di.collect_identity(
        root, process_started_at=datetime.now(timezone.utc))

    assert record["code"] == "local_unverified"
    assert record["reason"] == "no_manifest"
    assert record["deployed_sha"] is None
    assert record["checkout_sha"] == sha
    assert record["deployed_at"] is None
    assert record["local_source_verification"] == "local_unverified"


@requires_git
def test_moved_checkout_after_manifest_is_mismatch_with_both_shas(tmp_path):
    root, deployed_sha = _repo(tmp_path)
    rm.write_manifest(root, rm.build_manifest(root))
    moved_sha = _commit(root, message="post-deploy commit")

    record = di.collect_identity(
        root, process_started_at=datetime.now(timezone.utc)
        + timedelta(minutes=1))

    assert record["code"] == "mismatch"
    assert record["reason"] == "sha_conflict"
    assert record["deployed_sha"] == deployed_sha
    assert record["checkout_sha"] == moved_sha
    assert record["conflict"] == ["release_manifest", "git_head"]


@requires_git
def test_process_started_before_manifest_is_process_predates_deploy(tmp_path):
    root, sha = _repo(tmp_path)
    deployed_at = datetime.now(timezone.utc)
    rm.write_manifest(root, rm.build_manifest(root, now=deployed_at))

    record = di.collect_identity(
        root, process_started_at=deployed_at - timedelta(minutes=1))

    assert record["code"] == "mismatch"
    assert record["reason"] == "process_predates_deploy"
    assert record["deployed_sha"] == sha
    assert record["conflict"] == ["release_manifest", "process_start"]


@requires_git
def test_version_from_different_checkout_is_not_hidden(tmp_path):
    root, _sha = _repo(tmp_path, version="0.0.0")
    rm.write_manifest(root, rm.build_manifest(root))

    record = di.collect_identity(
        root, process_started_at=datetime.now(timezone.utc)
        + timedelta(seconds=1))

    assert record["code"] == "mismatch"
    assert record["reason"] == "version_conflict"
    assert record["version_provenance"]["manifest"] == "0.0.0"
    assert record["version_provenance"]["consistent"] is False


# ── producer: previous/rollback + отказ на грязный tracked-tree ───────────

@requires_git
def test_previous_release_is_taken_from_existing_manifest(tmp_path):
    root, first_sha = _repo(tmp_path)
    rm.write_manifest(root, rm.build_manifest(root))

    second_version = _next_patch(APP_VERSION)
    second_sha = _commit(root, version=second_version, message="deploy two")
    manifest = rm.build_manifest(root, effect="deploy")
    rm.write_manifest(root, manifest)
    data = _read_manifest(root)

    assert data["deployed_sha"] == second_sha
    assert data["version"] == second_version
    assert data["previous_sha"] == first_sha
    assert data["previous_version"] == APP_VERSION


@requires_git
def test_rollback_manifest_points_to_previous_running_version(tmp_path):
    root, first_sha = _repo(tmp_path)
    rm.write_manifest(root, rm.build_manifest(root))
    second_version = _next_patch(APP_VERSION)
    second_sha = _commit(root, version=second_version, message="deploy two")
    rm.write_manifest(root, rm.build_manifest(root))

    _git(root, "checkout", "-q", first_sha)
    rm.write_manifest(root, rm.build_manifest(root, effect="rollback"))
    data = _read_manifest(root)

    assert data["effect"] == "rollback"
    assert data["deployed_sha"] == first_sha
    assert data["previous_sha"] == second_sha
    assert data["previous_version"] == second_version


@requires_git
def test_dirty_tracked_checkout_is_refused_and_manifest_preserved(tmp_path):
    root, sha = _repo(tmp_path)
    rm.write_manifest(root, rm.build_manifest(root))
    before = _manifest_path(root).read_text(encoding="utf-8")
    (root / "tracked.txt").write_text("modified\n", encoding="utf-8")

    with pytest.raises(rm.ManifestError, match="dirty"):
        rm.build_manifest(root)

    assert _manifest_path(root).read_text(encoding="utf-8") == before
    assert json.loads(before)["deployed_sha"] == sha


@requires_git
def test_untracked_files_do_not_block_or_dirty_manifest(tmp_path):
    root, sha = _repo(tmp_path)
    (root / "local-scratch.tmp").write_text("x\n", encoding="utf-8")

    rm.write_manifest(root, rm.build_manifest(root))
    record = di.collect_identity(
        root, process_started_at=datetime.now(timezone.utc)
        + timedelta(seconds=1))

    assert record["code"] == "verified_deployed"
    assert record["dirty"] is False
    assert record["deployed_sha"] == sha
    porcelain = _git(root, "status", "--porcelain").stdout
    assert ".deploy" not in porcelain       # манифест не отслеживается git
    assert "local-scratch.tmp" in porcelain


@requires_git
def test_symlinked_deploy_dir_is_refused(tmp_path):
    root, _sha = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / ".deploy").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")

    with pytest.raises(rm.ManifestWriteError, match="symlink"):
        rm.write_manifest(root, rm.build_manifest(root))

    assert not (outside / "release.json").exists()


@requires_git
def test_invalid_previous_manifest_does_not_poison_new_record(tmp_path):
    root, sha = _repo(tmp_path)
    _manifest_path(root).parent.mkdir(parents=True, exist_ok=True)
    _manifest_path(root).write_text("{not valid json", encoding="utf-8")

    rm.write_manifest(root, rm.build_manifest(root))
    data = _read_manifest(root)

    assert data["deployed_sha"] == sha
    assert data["previous_sha"] is None
    assert data["previous_version"] is None


@requires_git
def test_app_version_with_utf8_bom_is_read(tmp_path):
    """Реальный config/settings.py начинается с BOM: AST-разбор обязан
    читать его так же, как Python-импорт (иначе deploy ложно блокируется)."""
    root, _sha = _repo(tmp_path)
    (root / "config" / "settings.py").write_bytes(
        b"\xef\xbb\xbf" + f'APP_VERSION = "{APP_VERSION}"\n'.encode("utf-8"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "bom settings")

    manifest = rm.build_manifest(root)

    assert manifest["version"] == APP_VERSION


@requires_git
def test_missing_app_version_is_refused(tmp_path):
    root, _sha = _repo(tmp_path)
    (root / "config" / "settings.py").write_text("# no version\n",
                                                 encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "no version")

    with pytest.raises(rm.ManifestError, match="APP_VERSION"):
        rm.build_manifest(root)


@requires_git
def test_invalid_effect_is_refused(tmp_path):
    root, _sha = _repo(tmp_path)

    with pytest.raises(rm.ManifestError, match="effect"):
        rm.build_manifest(root, effect="publish")


# ── producer: атомарность и CLI ───────────────────────────────────────────

@requires_git
def test_manifest_write_is_atomic_and_leaves_no_temp(tmp_path):
    root, _sha = _repo(tmp_path)
    rm.write_manifest(root, rm.build_manifest(root))

    assert sorted(path.name for path in (root / ".deploy").iterdir()) == [
        "release.json"]


@requires_git
def test_dry_run_prints_manifest_and_writes_nothing(tmp_path, capsys):
    root, sha = _repo(tmp_path)

    code = rm.main(["--repo-root", str(root), "--dry-run"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["deployed_sha"] == sha
    assert not _manifest_path(root).exists()


def test_cli_refuses_non_git_root(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()

    code = rm.main(["--repo-root", str(plain)])

    assert code == 2
    assert "not a git checkout" in capsys.readouterr().err


def test_manifest_path_constant_agrees_with_identity_reader():
    assert rm.MANIFEST_REL_PATH == di.MANIFEST_REL_PATH
    assert rm.SCHEMA == 1
