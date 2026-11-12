"""SELF-DIAG-01 / D4-B: local snapshot provider, routing, repo_origin setting.

Контракт: ``plans/features/self-diag-01/architecture-d4-identity.md`` v1.1
§2.4 (repo_origin), §3.1–§3.4 (local snapshot / denylist / local_unverified),
§4 (шов D6 не реализуется здесь), §9 (тесты провайдера/маршрутизации).

Тесты герметичны: ``tmp_path`` + рукописные ``.git``-структуры; реальный
``git init`` используется только там, где проверяется интеграция с D4-A
identity (skip при отсутствии git). Сети нет.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from config.settings import settings
from services import deploy_identity as di
from services import hot_config as hot
from services import param_catalog as pc
from services import source_reader as sr
from services import source_reuse
from services.tool_router import ToolContext, ToolDeps, ToolRouter

REPO = "Henry-Case-dev/adminbot"
SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
SECRET = "ghp_D4B_SECRET_MARKER_123"


# ── фикстуры/помощники ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Никакой сети/токенов/локального провайдера по умолчанию."""
    monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", True)
    monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN", "")
    monkeypatch.setattr(type(settings), "SELF_DIAG_LOCAL_REPO_ROOT", "")
    monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_FILES", 3)
    monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_DEPTH", 1)
    monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_REQUESTS", 8)
    monkeypatch.setattr(hot, "get", lambda key, default=None: default)
    monkeypatch.setattr(sr, "_REPO_ORIGIN_LAST", None)


FILES: dict[str, bytes] = {
    "services/source_reader.py": b"def probe():\n    return 42\n",
    "services/deploy_identity.py": b"# self-read exception\n",
    "tests/test_probe.py": b"def test_probe():\n    assert True\n",
    "README.md": b"# demo\n",
    ".env.example": b"TOKEN=\n",
    ".env": ("TOKEN=" + SECRET + "\n").encode(),
    "config/credentials/notes.txt": b"credential\n",
    "config/secrets/notes.txt": b"secret\n",
    "media/cookies/notes.txt": b"cookie\n",
    "backups/db.sqlite": b"backup\n",
    "local_database.db": b"db\n",
    "secrets.pem": b"pem\n",
    "deploy_commands.txt": b"commands\n",
    "deploy_result.json": b"result\n",
    "check_remote_bot.py": b"check\n",
    "services/deploy_evil.py": b"evil\n",
    "logs/app.log": b"log\n",
    "node_modules/pkg/index.js": b"module\n",
    ".venv/lib.py": b"venv\n",
}


def _make_repo(tmp_path: Path, *, sha: str = SHA,
               origin_url: str = "") -> Path:
    """Каталог-снимок + рукописный ``.git`` (HEAD → refs/heads/main)."""
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in FILES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git_dir = root / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs" / "heads" / "main").write_text(
        sha + "\n", encoding="utf-8")
    url = origin_url or f"https://user:{SECRET}@github.com/{REPO}.git"
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
    return root


def _identity(*, sha: str = SHA, dirty=False,
              code: str = "local_unverified", branch: str = "main") -> dict:
    verification = ("verified_deployed" if code == "verified_deployed"
                    else code)
    return {
        "schema": 1, "code": code, "reason": "",
        "repo_origin": REPO, "deployed_sha": None, "checkout_sha": sha,
        "dirty": dirty, "local_source_verification": verification,
        "local_identity": {"checkout_sha": sha, "dirty": dirty,
                           "checkout_mtime": None, "branch": branch},
    }


def _local(tmp_path: Path, *, identity: dict | None = None,
           root: Path | None = None, **kwargs) -> sr.LocalSnapshotProvider:
    repo_root = root if root is not None else _make_repo(tmp_path)
    record = identity if identity is not None else _identity()
    return sr.LocalSnapshotProvider(
        repo_root, repo_origin=REPO,
        identity_reader=lambda _root: record, **kwargs)


class _StubGitHub:
    """Сторонний провайдер: фиксированные байты, без сети."""

    name = sr.PROVIDER_GITHUB
    uses_auth = False
    network_calls = 0

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def search_repos(self, query, *, limit=5):
        self.calls.append("search")
        return []

    async def resolve_repo(self, owner, repo):
        self.calls.append("resolve")
        return sr.RepoInfo(owner=owner, name=repo, default_branch="main",
                           language="Python")

    async def resolve_commit(self, repo, ref):
        self.calls.append("commit")
        return OTHER_SHA

    async def list_tree(self, repo, commit):
        self.calls.append("tree")
        return sr.TreeListing(entries=[
            sr.TreeEntry(path="pkg/probe.py", kind="blob", size=22)])

    async def read_file(self, repo, commit, path, *, blob_sha=""):
        self.calls.append("read")
        return sr.SourceFile(path=path, data=b"def probe():\n    return 1\n",
                             endpoint="contents")


async def _read_local(provider: sr.LocalSnapshotProvider, *,
                      path: str = "services/source_reader.py",
                      repo: str = REPO, ref: str = "main",
                      follow=False) -> dict:
    reader = sr.SourceReader(provider=_StubGitHub(),
                             local_provider=provider)
    return await reader.run(operation=sr.OPERATION_READ, repo=repo,
                            ref=ref, path=path, follow=follow,
                            budget_chars=4000)


# ── 1. repo_origin: default, каталог, нормализация, событие смены ───────────

class TestRepoOriginSetting:
    def test_default_is_canonical_and_shared_with_identity(self):
        assert sr.DEFAULT_REPO_ORIGIN == "Henry-Case-dev/adminbot"
        assert sr.DEFAULT_REPO_ORIGIN == di.DEFAULT_REPO_ORIGIN
        assert sr.configured_repo_origin() == sr.DEFAULT_REPO_ORIGIN

    def test_repo_origin_is_non_secret_admin_catalog_param(self):
        spec = pc.get_by_pg_key(sr.REPO_ORIGIN_SETTING_KEY)
        assert spec is not None
        assert spec.pg_key == "flags.self_diag_repo_origin"
        assert spec.category == pc.CATEGORY_FLAGS
        assert spec.type == "str"
        assert spec.secret is False
        assert spec.hidden is False
        assert spec.per_chat is False
        assert spec.group == "flags_service"
        # Видимость в существующей вкладке «Диагностика», без новой страницы.
        assert pc.group_tab(spec.group) == pc.TAB_MOD_CHECKUP

    @pytest.mark.parametrize("value", [
        "Henry-Case-dev/adminbot",
        "https://github.com/Henry-Case-dev/adminbot",
        "https://github.com/Henry-Case-dev/adminbot.git",
        f"https://user:{SECRET}@github.com/Henry-Case-dev/adminbot.git",
        "git@github.com:Henry-Case-dev/adminbot.git",
    ])
    def test_repo_origin_normalizes_to_owner_name(self, value):
        assert sr.normalize_repo_origin(value) == REPO

    @pytest.mark.parametrize("value", [
        "", "   ", "https://github.com/onlyowner", "a/b/c",
        "../../etc/passwd", "C:\\Windows\\system.ini",
        "file:///etc/passwd",
    ])
    def test_invalid_repo_origin_is_rejected(self, value):
        assert sr.normalize_repo_origin(value) is None

    def test_configured_origin_strips_credentials(self, monkeypatch):
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: (
                f"https://user:{SECRET}@github.com/{REPO}.git"
                if key == sr.REPO_ORIGIN_SETTING_KEY else default))
        assert sr.configured_repo_origin() == REPO

    def test_invalid_configured_origin_falls_back_without_leaking(
            self, monkeypatch, caplog):
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: (
                f"https://user:{SECRET}@github.com/onlyowner"
                if key == sr.REPO_ORIGIN_SETTING_KEY else default))
        with caplog.at_level(logging.INFO):
            assert sr.configured_repo_origin() == sr.DEFAULT_REPO_ORIGIN
        assert "repo_origin invalid" in caplog.text
        assert SECRET not in caplog.text

    def test_change_event_records_old_new_without_secret(
            self, monkeypatch, caplog):
        values = {sr.REPO_ORIGIN_SETTING_KEY: REPO}
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: values.get(key, default))
        monkeypatch.setattr(sr, "_REPO_ORIGIN_LAST", None)
        assert sr.configured_repo_origin() == REPO
        values[sr.REPO_ORIGIN_SETTING_KEY] = (
            f"https://user:{SECRET}@github.com/Other/repo.git")
        with caplog.at_level(logging.INFO):
            assert sr.configured_repo_origin() == "Other/repo"
            # Повторное наблюдение того же значения не дублирует событие.
            assert sr.configured_repo_origin() == "Other/repo"
        assert caplog.text.count("repo_identity_changed") == 1
        assert "old=" + REPO in caplog.text
        assert "new=Other/repo" in caplog.text
        assert SECRET not in caplog.text

    def test_local_provider_disabled_by_default(self):
        assert sr.local_snapshot_root() == ""
        assert sr.build_local_provider() is None
        assert sr.SourceReader()._local_provider is None

    def test_local_provider_auto_built_only_when_configured(self, tmp_path,
                                                            monkeypatch):
        root = _make_repo(tmp_path)
        monkeypatch.setattr(type(settings), "SELF_DIAG_LOCAL_REPO_ROOT",
                            str(root))
        reader = sr.SourceReader()
        assert reader._local_provider is not None
        assert reader._provider_for(REPO) is reader._local_provider
        assert reader._provider_for("other/repo") is not reader._local_provider


# ── 2. LocalSnapshotProvider: чтение, pinning, denylist, без исполнения ─────

class TestLocalSnapshotProvider:
    @pytest.mark.asyncio
    async def test_read_file_returns_exact_bytes_without_host_path(
            self, tmp_path):
        provider = _local(tmp_path)
        source = await provider.read_file(
            REPO, SHA, "services/source_reader.py")
        assert source is not None
        assert source.path == "services/source_reader.py"
        assert source.data == FILES["services/source_reader.py"]
        assert source.endpoint == sr.PROVIDER_LOCAL
        assert str(tmp_path) not in repr(source)

    @pytest.mark.asyncio
    async def test_commit_is_pinned_to_clean_head(self, tmp_path):
        provider = _local(tmp_path)
        assert await provider.resolve_commit(REPO, "main") == SHA
        assert await provider.resolve_commit(REPO, "HEAD") == SHA
        assert await provider.resolve_commit(REPO, SHA) == SHA
        assert await provider.resolve_commit(REPO, OTHER_SHA) is None
        assert await provider.resolve_commit(REPO, "feature/x") is None
        with pytest.raises(sr.SourceFetchError) as excinfo:
            await provider.read_file(
                REPO, OTHER_SHA, "services/source_reader.py")
        assert excinfo.value.code == sr.ERR_PROVIDER_UNAVAILABLE
        assert excinfo.value.detail == "commit_not_available"

    @pytest.mark.asyncio
    async def test_missing_root_or_commit_is_honest(self, tmp_path):
        provider = _local(tmp_path, root=tmp_path / "missing")
        assert await provider.resolve_repo(*REPO.split("/")) is None
        assert await provider.resolve_commit(REPO, "main") is None
        assert await provider.list_tree(REPO, SHA) is None
        with pytest.raises(sr.SourceFetchError) as excinfo:
            await provider.read_file(REPO, SHA, "services/source_reader.py")
        assert excinfo.value.detail == "root_missing"
        reader = sr.SourceReader(provider=_StubGitHub(),
                                 local_provider=provider)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   ref="main",
                                   path="services/source_reader.py")
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_SOURCE_MISSING
        assert payload["provider"] == sr.PROVIDER_LOCAL
        assert payload["host"] == sr.PROVIDER_LOCAL
        assert isinstance(payload.get("not_checked"), dict)

    @pytest.mark.asyncio
    async def test_list_tree_excludes_denied_and_tool_dirs(self, tmp_path):
        provider = _local(tmp_path)
        listing = await provider.list_tree(REPO, SHA)
        assert listing is not None
        paths = {entry.path for entry in listing.entries}
        assert "services/source_reader.py" in paths
        assert "tests/test_probe.py" in paths
        assert ".env.example" in paths
        for denied in (".env", ".git/config", "config/credentials/notes.txt",
                       "config/secrets/notes.txt", "media/cookies/notes.txt",
                       "backups/db.sqlite", "secrets.pem",
                       "deploy_commands.txt", "services/deploy_evil.py",
                       "logs/app.log"):
            assert denied not in paths
        assert not any(path.startswith(("node_modules/", ".venv/"))
                       for path in paths)

    @pytest.mark.parametrize("path", [
        ".env", ".env.local", ".git/config", "config/credentials/notes.txt",
        "config/secrets/notes.txt", "media/cookies/notes.txt",
        "backups/db.sqlite", "local_database.db", "secrets.pem",
        "deploy_commands.txt", "deploy_result.json", "check_remote_bot.py",
        "services/deploy_evil.py", "logs/app.log",
    ])
    @pytest.mark.asyncio
    async def test_denied_paths_return_closed_code_without_content(
            self, tmp_path, path):
        provider = _local(tmp_path)
        with pytest.raises(sr.SourceFetchError) as excinfo:
            await provider.read_file(REPO, SHA, path)
        assert excinfo.value.code == sr.ERR_PATH_DENIED
        assert excinfo.value.detail == "path_denied"
        assert SECRET not in str(excinfo.value)
        # Отказ не подтверждает существование: несуществующий denied-путь
        # даёт тот же закрытый код.
        with pytest.raises(sr.SourceFetchError) as missing:
            await provider.read_file(REPO, SHA, "backups/does-not-exist.db")
        assert missing.value.code == sr.ERR_PATH_DENIED

    @pytest.mark.asyncio
    async def test_allowed_paths_including_self_read(self, tmp_path):
        provider = _local(tmp_path)
        for path in (".env.example", "services/deploy_identity.py",
                     "tests/test_probe.py"):
            source = await provider.read_file(REPO, SHA, path)
            assert source is not None and source.path == path

    @pytest.mark.parametrize("path", [
        "../outside.txt", "services/../../outside.txt",
        "/etc/passwd", "C:\\Windows\\win.ini",
        "services/source_reader.py:stream",
    ])
    @pytest.mark.asyncio
    async def test_absolute_and_parent_paths_are_denied(self, tmp_path, path):
        provider = _local(tmp_path)
        with pytest.raises(sr.SourceFetchError) as excinfo:
            await provider.read_file(REPO, SHA, path)
        assert excinfo.value.code == sr.ERR_PATH_DENIED

    @pytest.mark.asyncio
    async def test_symlink_escape_is_denied(self, tmp_path):
        provider = _local(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("TOPSECRET", encoding="utf-8")
        link = tmp_path / "repo" / "escape.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation is not permitted on this host")
        with pytest.raises(sr.SourceFetchError) as excinfo:
            await provider.read_file(REPO, SHA, "escape.txt")
        assert excinfo.value.code == sr.ERR_PATH_DENIED

    @pytest.mark.asyncio
    async def test_repository_code_is_never_imported_or_executed(
            self, tmp_path):
        provider = _local(tmp_path)
        marker = tmp_path / "EXECUTED"
        trap = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', "
            "encoding='utf-8')\n"
        )
        (tmp_path / "repo" / "d4b_trap_module.py").write_text(
            trap, encoding="utf-8")
        source = await provider.read_file(REPO, SHA, "d4b_trap_module.py")
        assert source is not None and b"write_text" in source.data
        await provider.list_tree(REPO, SHA)
        await provider.search_repos("adminbot")
        assert marker.exists() is False
        assert "d4b_trap_module" not in sys.modules

    @pytest.mark.asyncio
    async def test_search_matches_only_own_origin(self, tmp_path):
        provider = _local(tmp_path)
        found = await provider.search_repos("adminbot", limit=5)
        assert [info.full_name for info in found] == [REPO]
        assert await provider.search_repos("parallel minecraft mod") == []
        assert await provider.search_repos("") == []

    @pytest.mark.asyncio
    async def test_file_size_cap_is_explicit(self, tmp_path):
        provider = _local(tmp_path, max_bytes=10)
        (tmp_path / "repo" / "big.txt").write_bytes(b"x" * 100)
        with pytest.raises(sr.SourceFetchError) as excinfo:
            await provider.read_file(REPO, SHA, "big.txt")
        assert excinfo.value.code == sr.ERR_UNSUPPORTED_KIND
        assert excinfo.value.detail == "file_too_large"

    @pytest.mark.asyncio
    async def test_verification_never_raises(self, tmp_path):
        def broken(_root):
            raise RuntimeError("boom")
        provider = sr.LocalSnapshotProvider(
            _make_repo(tmp_path), repo_origin=REPO,
            identity_reader=broken)
        record = provider.verification()
        assert record["code"] == "unavailable"
        assert record["reason"] == "internal_error"
        assert record["local_source_verification"] == "unknown"
        assert await provider.resolve_commit(REPO, "main") is None

    def test_identity_record_strips_credentials_from_git_origin(self, tmp_path):
        root = _make_repo(tmp_path)
        record = di.collect_identity(root)
        assert record["repo_origin"] == REPO
        assert SECRET not in json.dumps(record, ensure_ascii=False)


# ── 3. SourceReader: маршрутизация, local_unverified, отсутствие host paths ─

class TestSourceReaderRouting:
    @pytest.mark.asyncio
    async def test_self_read_uses_local_provider(self, tmp_path):
        provider = _local(tmp_path)
        stub = _StubGitHub()
        reader = sr.SourceReader(provider=stub, local_provider=provider)
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="services/source_reader.py", follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_LOCAL
        assert payload["host"] == sr.PROVIDER_LOCAL
        assert payload["repo"] == REPO
        assert payload["commit"] == SHA
        assert payload["path"] == "services/source_reader.py"
        assert payload["snippet"] == "def probe():\n    return 42"
        assert payload["verified"] is True
        assert payload["verified_url"].startswith(
            f"repo://adminbot@{SHA}/services/source_reader.py#L")
        assert payload["local_source_verification"] == "local_unverified"
        assert "не подтверждено" in payload["local_source_note"]
        assert payload["provenance"]["provider"] == sr.PROVIDER_LOCAL
        assert stub.calls == []
        body = json.dumps(payload, ensure_ascii=False)
        assert str(tmp_path) not in body
        assert SECRET not in body

    @pytest.mark.asyncio
    async def test_verified_deployed_marker_is_reported(self, tmp_path):
        provider = _local(tmp_path,
                          identity=_identity(code="verified_deployed"))
        payload = await _read_local(provider)
        assert payload["local_source_verification"] == "verified_deployed"
        assert "подтверждённая ревизия" in payload["local_source_note"]
        assert payload["verified"] is True

    @pytest.mark.asyncio
    async def test_dirty_snapshot_is_never_verified(self, tmp_path):
        provider = _local(tmp_path, identity=_identity(dirty=True))
        payload = await _read_local(provider)
        assert payload["status"] == sr.STATUS_OK
        assert payload["verified"] is False
        assert payload["verified_url"] == ""
        assert payload["local_source_verification"] == "local_unverified"
        assert "рабочее дерево изменено" in payload["local_source_note"]

    @pytest.mark.asyncio
    async def test_third_party_repo_keeps_github_provider(self, tmp_path):
        provider = _local(tmp_path)
        stub = _StubGitHub()
        reader = sr.SourceReader(provider=stub, local_provider=provider)
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo="other/mod", ref="main",
            path="pkg/probe.py", follow=False, budget_chars=4000)
        assert payload["status"] == sr.STATUS_OK
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert payload["host"] == "github.com"
        assert payload["repo"] == "other/mod"
        assert payload["verified_url"].startswith("https://github.com/")
        assert "read" in stub.calls
        assert "local_source_verification" not in payload

    @pytest.mark.asyncio
    async def test_routing_is_exact_match_casefold_only(self, tmp_path):
        provider = _local(tmp_path)
        stub = _StubGitHub()
        reader = sr.SourceReader(provider=stub, local_provider=provider)
        own = await reader.run(operation=sr.OPERATION_READ,
                               repo="Henry-Case-dev/ADMINBOT", ref="main",
                               path="services/source_reader.py",
                               follow=False, budget_chars=4000)
        assert own["provider"] == sr.PROVIDER_LOCAL
        fork = await reader.run(operation=sr.OPERATION_READ,
                                repo="Henry-Case-dev/adminbot-fork",
                                ref="main", path="pkg/probe.py",
                                follow=False, budget_chars=4000)
        assert fork["provider"] == sr.PROVIDER_GITHUB
        assert "read" in stub.calls

    @pytest.mark.asyncio
    async def test_denied_path_payload_has_no_content(self, tmp_path):
        provider = _local(tmp_path)
        payload = await _read_local(provider, path=".env")
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_PATH_DENIED
        assert payload["reason"] == sr.ERR_PATH_DENIED
        assert payload["verified"] is False
        assert SECRET not in json.dumps(payload, ensure_ascii=False)
        assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)
        assert isinstance(payload.get("not_checked"), dict)

    @pytest.mark.asyncio
    async def test_real_identity_makes_unverified_but_clean_read(
            self, tmp_path):
        root = _make_repo(tmp_path)
        provider = sr.LocalSnapshotProvider(root, repo_origin=REPO)
        payload = await _read_local(provider)
        # Рукописный .git: checkout известен, но доказательства тождества нет.
        assert payload["status"] == sr.STATUS_OK
        assert payload["local_source_verification"] in (
            "local_unverified", "unknown")
        assert str(root) not in json.dumps(payload, ensure_ascii=False)
        assert str(root.as_posix()) not in json.dumps(payload,
                                                      ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_real_git_checkout_clean_read_is_verified(self, tmp_path):
        if shutil.which("git") is None:
            pytest.skip("git binary is not available")
        root = tmp_path / "realrepo"
        root.mkdir()
        (root / "pkg").mkdir()
        (root / "pkg" / "probe.py").write_text(
            "def probe():\n    return 7\n", encoding="utf-8")
        env = {"GIT_OPTIONAL_LOCKS": "0"}
        subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True,
                       env=env)
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=test@example.invalid",
             "-c", "user.name=D4B", "commit", "-q", "-m", "init"],
            check=True, env=env)
        provider = sr.LocalSnapshotProvider(root, repo_origin=REPO)
        head = await provider.resolve_commit(REPO, "HEAD")
        assert head is not None and len(head) == 40
        payload = await _read_local(provider, path="pkg/probe.py", ref="HEAD")
        assert payload["status"] == sr.STATUS_OK
        assert payload["commit"] == head
        assert payload["verified"] is True
        assert payload["local_source_verification"] == "local_unverified"
        assert payload["verified_url"].startswith(
            f"repo://adminbot@{head}/pkg/probe.py#L")


class TestToolSeamReuse:
    @pytest.mark.asyncio
    async def test_reused_local_answer_keeps_provider_and_marker(self, tmp_path):
        source_reuse.clear()
        provider = _local(tmp_path)
        reader = sr.SourceReader(provider=_StubGitHub(),
                                 local_provider=provider)
        router = ToolRouter(ToolDeps(None, None, source_reader=reader))
        args = {
            "operation": "read", "repo": REPO, "ref": "main",
            "path": "services/source_reader.py",
            "claim": {"entity": "self diag d4b", "relation": "spec",
                      "version": "d4b"},
        }
        first = json.loads(await router.dispatch(
            "read_source_code", args, ToolContext(-100500, "q")))
        assert first["status"] == sr.STATUS_OK
        assert first["provider"] == sr.PROVIDER_LOCAL
        second = json.loads(await router.dispatch(
            "read_source_code", args, ToolContext(-100500, "q")))
        assert second["reused"] is True
        assert second["provider"] == sr.PROVIDER_LOCAL
        assert second["host"] == sr.PROVIDER_LOCAL
        assert second["local_source_verification"] == "local_unverified"
        assert "не подтверждено" in second["local_source_note"]
        assert "repo://adminbot@" in second["verified_url"]
        source_reuse.clear()
