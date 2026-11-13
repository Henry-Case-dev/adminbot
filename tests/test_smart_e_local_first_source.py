"""SMART stage E (`SXR-E1..E4`): local-first проverified источник.

Контракт владельца (§E):
  E1 — local-first действует во всех сценариях исследования собственного кода и
       не привязан к формулировке запроса;
  E2 — локальный production-источник определяется автоматически (runtime/deploy
       identity), с проверкой прав сервисного пользователя, файлов, repo_origin
       и версии; cwd не считается корнем; ничего не клонируется/индексируется;
  E3 — различаются deployed SHA, checkout SHA, runtime identity, доступные
       файлы и удалённый commit; несовпадающий checkout не выдаётся за
       production; `master` по умолчанию не читается; фиктивный manifest из
       checkout не создаётся;
  E4 — порядок: проверенный локальный → иной локальный snapshot с честной
       идентичностью → GitHub по deployed commit/ref → честный partial;
       provenance сохраняется.

Тесты используют реальные файлы/права/байты синтетического дерева приложения.
Identity-запись (результат существующего `deploy_identity.collect_identity`)
подаётся через публичный DI-шов `identity_reader`; поведение самого коллектора
покрыто `tests/test_deploy_identity*.py`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from config.settings import settings
from services import hot_config as hot
from services import source_reader as sr

REPO = sr.DEFAULT_REPO_ORIGIN
SHA = "a" * 40
OTHER_SHA = "b" * 40
APP_FILES = {
    "services/source_reader.py": "def probe():\n    return 42\n",
    "config/settings.py": "APP_VERSION = '2.58.199'\n",
    "services/hub.py": "def hub():\n    return 1\n",
}


# ── фикстура: герметичность окружения ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", True)
    monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN", "")
    monkeypatch.setattr(type(settings), "SELF_DIAG_LOCAL_REPO_ROOT", "")
    monkeypatch.setattr(hot, "get", lambda key, default=None: default)
    monkeypatch.setattr(sr, "_REPO_ORIGIN_LAST", None)
    # По умолчанию «каталог приложения» не подставляется: каждый тест задаёт
    # runtime root явно (или проверяет, что без него источника нет).
    monkeypatch.setattr(sr, "runtime_application_root", lambda: None)
    monkeypatch.delenv("ADMINBOT_DEPLOYED_SHA", raising=False)


# ── синтетическое дерево приложения ────────────────────────────────────────

def _tree(tmp_path: Path, files: dict[str, str] | None = None, *,
          sha: str = SHA, origin: str = REPO,
          manifest: dict | None = None) -> Path:
    """Каталог-снимок приложения + рукописный ``.git`` (HEAD → refs/heads/main)."""
    root = tmp_path / "app"
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in (files or APP_FILES).items():
        target = root.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git_dir = root / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs" / "heads" / "main").write_text(sha + "\n",
                                                     encoding="utf-8")
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/{origin}.git\n',
        encoding="utf-8")
    if manifest is not None:
        deploy = root / ".deploy"
        deploy.mkdir(parents=True, exist_ok=True)
        (deploy / "release.json").write_text(json.dumps(manifest),
                                            encoding="utf-8")
    return root


def _identity(*, code: str = "verified_deployed", checkout: str | None = SHA,
              deployed: str | None = SHA, dirty: bool | None = False,
              origin: str = REPO, runtime_version: str = "2.58.199",
              manifest_version: str | None = "2.58.199",
              consistent: bool | None = True, branch: str = "main") -> dict:
    """Форма записи существующего ``deploy_identity.collect_identity``."""
    return {
        "schema": 1,
        "code": code,
        "reason": "",
        "repo_origin": origin,
        "deployed_sha": deployed,
        "checkout_sha": checkout,
        "dirty": dirty,
        "local_source_verification": ("verified_deployed"
                                      if code == "verified_deployed"
                                      else "local_unverified"),
        "version_provenance": {"runtime": runtime_version,
                               "manifest": manifest_version,
                               "consistent": consistent},
        "local_identity": {"checkout_sha": checkout, "dirty": dirty,
                           "checkout_mtime": None, "branch": branch},
    }


def _resolve(tree: Path | None, identity: dict | None, *,
             repo_origin: str = REPO) -> dict:
    """Автоматический выбор источника: runtime root + существующий DI identity."""
    return sr.resolve_local_source(
        runtime_root=tree, configured_root="", repo_origin=repo_origin,
        identity_reader=(lambda _root: identity) if identity is not None else None)


def _patch_identity(monkeypatch, identity: dict) -> None:
    """Подменить запись коллектора для путей, читающих его напрямую.

    `resolve_self_repo_identity` и автосборка `SourceReader` берут identity из
    `deploy_identity.collect_identity`; его собственное поведение покрыто
    `tests/test_deploy_identity*.py`.
    """
    from services import deploy_identity as di
    monkeypatch.setattr(di, "collect_identity",
                        lambda *a, **kw: dict(identity))


def _provider(tree: Path, identity: dict, *, record: dict | None = None,
              repo_origin: str = REPO) -> sr.LocalSnapshotProvider:
    return sr.LocalSnapshotProvider(
        tree, repo_origin=repo_origin,
        identity_reader=lambda _root: identity,
        source=record)


class _StubGitHub:
    """Удалённый провайдер: фиксированные байты, без сети, с журналом вызовов."""

    name = sr.PROVIDER_GITHUB
    uses_auth = False
    network_calls = 0

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = files or {"services/source_reader.py": "REMOTE\n"}
        self.calls: list[str] = []
        self.refs: list[str] = []

    async def search_repos(self, query, *, limit=5):
        self.calls.append("search")
        return []

    async def resolve_repo(self, owner, repo):
        self.calls.append("resolve_repo")
        return sr.RepoInfo(owner=owner, name=repo, default_branch="main",
                           language="Python")

    async def resolve_commit(self, repo, ref):
        self.calls.append("resolve_commit")
        self.refs.append(str(ref or ""))
        text = str(ref or "").strip()
        return text.lower() if len(text) == 40 else OTHER_SHA

    async def list_tree(self, repo, commit):
        self.calls.append("list_tree")
        return sr.TreeListing(entries=[
            sr.TreeEntry(path="services/hub.py", kind="blob", size=22)])

    async def read_file(self, repo, commit, path, *, blob_sha=""):
        self.calls.append("read_file")
        text = self.files.get(path)
        if text is None:
            return None
        return sr.SourceFile(path=path, data=text.encode("utf-8"),
                             endpoint="contents")


def _reader(tree: Path, identity: dict, *, stub: _StubGitHub | None = None,
            repo_origin: str = REPO) -> tuple[sr.SourceReader, dict]:
    """SourceReader с автоматически выбранным источником (как в проде)."""
    record = _resolve(tree, identity, repo_origin=repo_origin)
    provider = _provider(tree, identity, record=record, repo_origin=repo_origin)
    reader = sr.SourceReader(provider=stub or _StubGitHub(),
                             local_provider=provider,
                             repo_origin=repo_origin)
    return reader, record


# ── E2: доступный production-источник определяется автоматически ───────────

class TestLocalRootDiscovery:
    def test_runtime_root_with_matching_origin_and_version_is_verified_running(
            self, tmp_path):
        tree = _tree(tmp_path)
        record = _resolve(tree, _identity())
        assert record["root_source"] == sr.LOCAL_ROOT_RUNTIME
        assert record["is_runtime_root"] is True
        assert record["readable"] is True
        assert record["files_present"] is True
        assert record["git_present"] is True
        assert record["repo_origin"] == REPO
        assert record["repo_origin_match"] is True
        assert record["version_consistent"] is True
        assert record["revision"] == SHA
        assert record["revision_kind"] == sr.LOCAL_REVISION_CHECKOUT
        assert record["verification"] == sr.LOCAL_VERIFICATION_VERIFIED_RUNNING
        assert record["version_verified"] is True
        assert record["commit_bound"] is True
        assert record["usable"] is True

    def test_configured_root_is_a_snapshot_not_running_process(self, tmp_path):
        tree = _tree(tmp_path)
        record = sr.resolve_local_source(
            root=tree, runtime_root=None, configured_root="", repo_origin=REPO,
            identity_reader=lambda _root: _identity())
        assert record["root_source"] == sr.LOCAL_ROOT_CONFIGURED
        assert record["is_runtime_root"] is False
        assert record["verification"] == sr.LOCAL_VERIFICATION_VERIFIED_SNAPSHOT
        # Версия подтверждена, но это не доказательство работающего процесса.
        assert record["version_verified"] is True
        assert "snapshot" in record["note"]

    def test_configured_env_root_is_used_without_manual_steps(
            self, tmp_path, monkeypatch):
        tree = _tree(tmp_path)
        monkeypatch.setattr(type(settings), "SELF_DIAG_LOCAL_REPO_ROOT",
                           str(tree))
        record = sr.resolve_local_source(
            runtime_root=None, repo_origin=REPO,
            identity_reader=lambda _root: _identity())
        assert record["root_source"] == sr.LOCAL_ROOT_CONFIGURED
        assert record["usable"] is True
        assert record["verification"] == sr.LOCAL_VERIFICATION_VERIFIED_SNAPSHOT

    def test_unreadable_root_reports_permission_denied(self, tmp_path,
                                                       monkeypatch):
        tree = _tree(tmp_path)
        real_scandir = sr.os.scandir

        def _denied(path):
            raise PermissionError("simulated service-user denial")

        with monkeypatch.context() as scoped:
            scoped.setattr(sr.os, "scandir", _denied)
            record = _resolve(tree, None)
        assert sr.os.scandir is real_scandir
        assert record["usable"] is False
        assert record["readable"] is False
        assert record["verification"] == sr.LOCAL_VERIFICATION_UNAVAILABLE
        assert record["reason"] == "permission_denied"

    def test_denied_paths_are_denied_by_the_same_policy(self):
        # Тот же запрет применяется к каждому чтению локального источника.
        from services.deploy_identity import path_is_denied
        assert path_is_denied(".env") is True
        assert path_is_denied("config/secrets/notes.txt") is True
        assert path_is_denied("services/source_reader.py") is False

    def test_non_app_directory_is_not_a_source(self, tmp_path):
        plain = tmp_path / "some-cwd"
        plain.mkdir()
        (plain / "notes.txt").write_text("not the app\n", encoding="utf-8")
        record = _resolve(plain, None)
        assert record["files_present"] is False
        assert record["usable"] is False
        assert record["verification"] == sr.LOCAL_VERIFICATION_UNAVAILABLE
        assert record["reason"] == "app_markers_missing"

    def test_cwd_is_never_used_as_root(self, tmp_path, monkeypatch):
        tree = _tree(tmp_path)
        monkeypatch.chdir(tree)
        record = sr.resolve_local_source(
            runtime_root=None, configured_root="", repo_origin=REPO,
            identity_reader=lambda _root: _identity())
        assert record["root"] is None
        assert record["root_source"] == sr.LOCAL_ROOT_NONE
        assert record["usable"] is False

    def test_foreign_repo_origin_is_rejected(self, tmp_path):
        tree = _tree(tmp_path, origin="someone/else")
        record = _resolve(tree, _identity(origin="someone/else"))
        assert record["repo_origin_match"] is False
        assert record["verification"] == sr.LOCAL_VERIFICATION_ORIGIN_MISMATCH
        assert record["reason"] == "repo_origin_mismatch"
        assert record["usable"] is False

    def test_source_reader_builds_local_provider_from_runtime_identity(
            self, tmp_path, monkeypatch):
        tree = _tree(tmp_path)
        monkeypatch.setattr(sr, "runtime_application_root", lambda: tree)
        _patch_identity(monkeypatch, _identity())
        reader = sr.SourceReader(repo_origin=REPO)
        assert reader._local_provider is not None
        record = reader._local_source or {}
        assert record.get("root_source") == sr.LOCAL_ROOT_RUNTIME
        assert record.get("verification") == (
            sr.LOCAL_VERIFICATION_VERIFIED_RUNNING)


# ── E3: что именно прочитано — deployed/checkout/файлы/удалённый commit ────

class TestVersionDistinction:
    def test_identity_distinguishes_deployed_checkout_and_files(self, tmp_path,
                                                               monkeypatch):
        tree = _tree(tmp_path)
        monkeypatch.setattr(sr, "runtime_application_root", lambda: tree)
        _patch_identity(monkeypatch, _identity())
        identity = sr.resolve_self_repo_identity()
        assert identity["repo"] == REPO
        assert identity["deployed_sha"] == SHA
        assert identity["checkout_sha"] == SHA
        assert identity["deployed_matches_checkout"] is True
        assert identity["source"] == "local"
        assert identity["ref"] == ""
        assert identity["ref_source"] == "deployed_sha"
        assert identity["files_only"] is False
        assert identity["version_verified"] is True
        assert identity["exact_remote_commit"] == SHA
        assert "проверенный локальный код" in identity["note"]
        # Путь хоста наружу не уходит.
        assert str(tmp_path) not in json.dumps(identity, ensure_ascii=False)

    def test_mismatched_checkout_is_not_presented_as_production(self, tmp_path,
                                                               monkeypatch):
        tree = _tree(tmp_path, sha=SHA)
        monkeypatch.setattr(sr, "runtime_application_root", lambda: tree)
        _patch_identity(monkeypatch, _identity(checkout=SHA, deployed=OTHER_SHA,
                                               code="mismatch"))
        identity = sr.resolve_self_repo_identity()
        assert identity["deployed_matches_checkout"] is False
        assert identity["ref_source"] == "local_checkout_unverified"
        assert identity["version_verified"] is False
        assert "не доказано" in identity["note"]
        assert OTHER_SHA[:12] in identity["note"]

    def test_missing_local_and_missing_deployed_does_not_read_default_branch(
            self, monkeypatch):
        monkeypatch.setattr(sr, "runtime_application_root", lambda: None)
        identity = sr.resolve_self_repo_identity()
        assert identity["source"] == "none"
        assert identity["ref"] == ""
        assert identity["ref_source"] == "unverified_revision"
        assert identity["exact_remote_commit"] is None
        assert "master" in identity["note"]

    def test_manifest_is_not_fabricated_from_checkout(self, tmp_path):
        tree = _tree(tmp_path)
        from services import deploy_identity as di
        record = di.collect_identity(tree)
        assert record["deployed_sha"] is None
        assert record["version_provenance"]["manifest"] is None
        assert record["code"] != "verified_deployed"
        # Тот же реальный коллектор через автоматический выбор источника.
        local = sr.resolve_local_source(runtime_root=tree, configured_root="",
                                        repo_origin=REPO)
        assert local["revision_kind"] == sr.LOCAL_REVISION_CHECKOUT
        assert local["verification"] == (
            sr.LOCAL_VERIFICATION_RUNNING_UNVERIFIED)
        assert local["version_verified"] is False
        assert local["manifest_present"] is False

    def test_deployed_files_without_git_are_not_commit_bound(self, tmp_path):
        tree = _tree(tmp_path, files={rel: text for rel, text in APP_FILES.items()},
                     origin="")
        shutil.rmtree(tree / ".git")
        identity = _identity(code="unknown", checkout=None, deployed=SHA,
                             dirty=None, origin=None)
        record = _resolve(tree, identity)
        assert record["git_present"] is False
        assert record["revision"] == SHA
        assert record["revision_kind"] == sr.LOCAL_REVISION_DEPLOYED_FILES
        assert record["verification"] == sr.LOCAL_VERIFICATION_DEPLOYED_FILES
        assert record["commit_bound"] is False
        assert record["usable"] is True
        # Байты выложенных файлов НЕ являются commit-pinned доказательством.
        assert sr._local_bytes_verified(record, SHA) is False

    def test_version_conflict_is_not_version_verified(self, tmp_path):
        tree = _tree(tmp_path)
        identity = _identity(code="local_unverified", checkout=None,
                             deployed=SHA, dirty=None,
                             manifest_version="2.58.199",
                             runtime_version="2.58.200", consistent=False)
        record = _resolve(tree, identity)
        assert record["revision_kind"] == sr.LOCAL_REVISION_DEPLOYED_FILES
        assert record["version_consistent"] is False
        assert record["version_verified"] is False
        assert record["reason"] == "version_conflict"


# ── E4: порядок источников и provenance ────────────────────────────────────

class TestSourceOrder:
    @pytest.mark.asyncio
    async def test_verified_local_code_is_read_without_network(self, tmp_path):
        tree = _tree(tmp_path)
        stub = _StubGitHub()
        reader, record = _reader(tree, _identity(), stub=stub)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/source_reader.py",
                                   follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["verified"] is True
        assert "def probe()" in payload["snippet"]
        assert payload["provider"] == sr.PROVIDER_LOCAL
        assert payload["network_calls"] == 0
        assert stub.calls == []
        selection = payload["source_selection"]
        assert selection["provider"] == sr.PROVIDER_LOCAL
        assert selection["verification"] == (
            sr.LOCAL_VERIFICATION_VERIFIED_RUNNING)
        assert selection["version_verified"] is True
        assert selection["revision_kind"] == sr.LOCAL_REVISION_CHECKOUT
        assert selection["fallback"] is None
        assert selection["exact_remote_commit_available"] == ""
        provenance = payload["provenance"]
        assert provenance["provider"] == sr.PROVIDER_LOCAL
        assert provenance["endpoint"] == sr.PROVIDER_LOCAL
        assert provenance["network_calls"] == 0
        assert provenance["revision_kind"] == sr.LOCAL_REVISION_CHECKOUT
        assert provenance["version_verified"] is True
        assert provenance["source_verification"] == (
            sr.LOCAL_VERIFICATION_VERIFIED_RUNNING)
        assert provenance["deployed_sha"] == SHA
        assert provenance["checkout_sha"] == SHA
        # Никаких путей хоста в провенансе.
        assert str(tree) not in json.dumps(payload["provenance"],
                                            ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_provenance_keeps_repo_commit_path_range_and_status(
            self, tmp_path):
        tree = _tree(tmp_path,
                     files={**APP_FILES,
                            "services/big.py": "".join(f"row_{i} = {i}\n"
                                                       for i in range(80))})
        reader, _record = _reader(tree, _identity())
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/big.py", line_start=1,
                                   line_end=5, follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        selection = payload["source_selection"]
        assert selection["repo"] == REPO
        assert selection["revision"] == SHA
        assert selection["path"] == "services/big.py"
        assert selection["line_range"] == [1, 5]
        assert selection["status"] == sr.STATUS_OK

    @pytest.mark.asyncio
    async def test_external_repository_uses_remote_provider(self, tmp_path):
        tree = _tree(tmp_path)
        stub = _StubGitHub({"pkg/probe.py": "REMOTE = 1\n"})
        reader, _record = _reader(tree, _identity(), stub=stub)
        payload = await reader.run(operation=sr.OPERATION_READ,
                                   repo="other/project",
                                   path="pkg/probe.py", follow=False,
                                   budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert "read_file" in stub.calls
        assert payload["source_selection"]["verification"] == "remote_external"

    @pytest.mark.asyncio
    async def test_without_readable_app_tree_reads_exact_deployed_commit(
            self, tmp_path):
        # Манифест деплоя доступен, дерева приложения нет: честный удалённый
        # маршрут ровно по deployed SHA (ветка по умолчанию не подставляется).
        tree = _tree(tmp_path, files={"README.md": "# not the app\n"},
                     manifest={"schema": 1, "deployed_sha": SHA,
                               "deployed_at": "2026-11-01T10:00:00+00:00",
                               "version": "2.58.199", "effect": "deploy"})
        shutil.rmtree(tree / ".git")
        record = _resolve(tree, None)
        stub = _StubGitHub()
        assert record["usable"] is False
        assert record["reason"] == "app_markers_missing"
        assert record["deployed_sha"] == SHA
        reader = sr.SourceReader(provider=stub, local_source=record,
                                 repo_origin=REPO)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/source_reader.py",
                                   follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert payload["commit"] == SHA
        # Поиск/локатор/ветка не использовались: только чтение этого commit.
        assert "search" not in stub.calls
        assert "list_tree" not in stub.calls
        selection = payload["source_selection"]
        assert selection["verification"] == "remote_deployed_commit"
        assert selection["version_verified"] is True
        assert selection["fallback"] is None

    @pytest.mark.asyncio
    async def test_vanished_local_root_falls_back_to_exact_deployed_commit_once(
            self, tmp_path):
        tree = _tree(tmp_path)
        stub = _StubGitHub()
        reader, record = _reader(tree, _identity(), stub=stub)
        assert record["usable"] is True
        shutil.rmtree(tree)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/source_reader.py",
                                   follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert payload["commit"] == SHA
        fallback = payload["source_selection"]["fallback"]
        assert fallback == {"from": sr.PROVIDER_LOCAL,
                            "reason": "local_repo_unavailable",
                            "commit": SHA}

    @pytest.mark.asyncio
    async def test_local_read_error_falls_back_to_exact_deployed_commit(
            self, tmp_path):
        tree = _tree(tmp_path)
        stub = _StubGitHub()

        class _BrokenLocal(sr.LocalSnapshotProvider):
            async def read_file(self, repo, commit, path, **kwargs):
                raise sr.SourceFetchError(sr.ERR_PROVIDER_UNAVAILABLE,
                                          sr.STAGE_FETCH, retryable=False,
                                          detail="read_error")

        record = _resolve(tree, _identity())
        provider = _BrokenLocal(tree, repo_origin=REPO,
                                identity_reader=lambda _root: _identity(),
                                source=record)
        reader = sr.SourceReader(provider=stub, local_provider=provider,
                                 repo_origin=REPO)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/source_reader.py",
                                   follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert payload["commit"] == SHA
        assert payload["source_selection"]["fallback"]["reason"] == "read_error"

    @pytest.mark.asyncio
    async def test_security_refusal_is_not_bypassed_by_remote_fallback(
            self, tmp_path):
        tree = _tree(tmp_path, files={**APP_FILES, ".env": "TOKEN=secret\n"})
        stub = _StubGitHub({".env": "REMOTE_SECRET=1\n"})
        reader, _record = _reader(tree, _identity(), stub=stub)
        for denied in (".env", "../../etc/passwd",
                       "services/hub.py:stream"):
            payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                       path=denied, follow=False,
                                       budget_chars=4000)
            assert payload["status"] == sr.STATUS_ERROR, denied
            assert payload["error"] == sr.ERR_PATH_DENIED, denied
            assert payload["source_selection"]["fallback"] is None, denied
        assert stub.calls == []
        assert "REMOTE_SECRET" not in json.dumps(payload, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_directory_is_unsupported_and_not_served_remotely(
            self, tmp_path):
        tree = _tree(tmp_path)
        stub = _StubGitHub()
        reader, _record = _reader(tree, _identity(), stub=stub)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services", follow=False,
                                   budget_chars=4000)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["reason"] == "path_is_directory"
        assert stub.calls == []

    @pytest.mark.asyncio
    async def test_missing_file_in_verified_tree_is_honest_not_found(
            self, tmp_path):
        tree = _tree(tmp_path)
        stub = _StubGitHub({"services/absent.py": "REMOTE = 1\n"})
        reader, record = _reader(tree, _identity(), stub=stub)
        assert record["version_verified"] is True
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/absent.py", follow=False,
                                   budget_chars=4000)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_SOURCE_MISSING
        # Проверенная работающая версия — источник истины: сеть не дёргается.
        assert stub.calls == []

    @pytest.mark.asyncio
    async def test_unverified_snapshot_missing_file_may_use_exact_deployed_commit(
            self, tmp_path):
        tree = _tree(tmp_path, sha=OTHER_SHA)
        stub = _StubGitHub({"services/absent.py": "REMOTE = 1\n"})
        reader, record = _reader(
            tree, _identity(code="local_unverified", checkout=OTHER_SHA,
                            deployed=SHA), stub=stub)
        assert record["usable"] is True
        assert record["version_verified"] is False
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/absent.py", follow=False,
                                   budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert payload["commit"] == SHA
        assert payload["source_selection"]["verification"] == (
            "remote_deployed_commit")

    @pytest.mark.asyncio
    async def test_no_local_and_no_deployed_is_honest_partial(self):
        record = _resolve(None, None)
        reader = sr.SourceReader(provider=_StubGitHub(), local_source=record,
                                 repo_origin=REPO)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/source_reader.py",
                                   follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_SOURCE_MISSING
        assert payload["error_detail"]["detail"] == "deployed_revision_unknown"
        assert payload["source_selection"]["verification"] != (
            "remote_deployed_commit")


# ── E1: не зависит от формулировки, один и тот же маршрут ──────────────────

class TestScenarioIndependence:
    SCENARIOS = (
        "обычный чекап",
        "продолжение диагностического разговора",
        "исследование инцидента: почему упал воркер",
        "вопрос о реализации собственного модуля source_reader",
        "семантически определённый запрос о собственном коде",
    )

    @pytest.mark.asyncio
    async def test_source_choice_does_not_depend_on_request_wording(
            self, tmp_path):
        tree = _tree(tmp_path)
        stub = _StubGitHub()
        reader, _record = _reader(tree, _identity(), stub=stub)
        selections = []
        for scenario in self.SCENARIOS:
            payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                       path="services/source_reader.py",
                                       query=scenario, context_query=scenario,
                                       follow=False, budget_chars=4000)
            assert payload["status"] == sr.STATUS_OK, scenario
            assert payload["provider"] == sr.PROVIDER_LOCAL, scenario
            assert payload["network_calls"] == 0, scenario
            selection = payload["source_selection"]
            selections.append((selection["provider"], selection["verification"],
                               selection["revision_kind"],
                               selection["version_verified"]))
        assert len(set(selections)) == 1
        assert stub.calls == []

    @pytest.mark.asyncio
    async def test_checkup_identity_path_uses_same_local_source(self, tmp_path,
                                                               monkeypatch):
        tree = _tree(tmp_path)
        monkeypatch.setattr(sr, "runtime_application_root", lambda: tree)
        _patch_identity(monkeypatch, _identity())
        identity = sr.resolve_self_repo_identity()
        reader = sr.SourceReader(repo_origin=REPO)
        assert reader._local_provider is not None
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   path="services/hub.py", follow=False,
                                   budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_LOCAL
        assert payload["commit"] == identity["deployed_sha"]
        assert payload["network_calls"] == 0
