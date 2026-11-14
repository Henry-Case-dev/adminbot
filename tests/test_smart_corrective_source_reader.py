"""SMART-CORRECTIVE-01 · S1/S2 — SourceReader result contract and content search.

Проверяет наблюдаемый контракт §1–§4 corrective:

* структурные классы результата (`outcome`: not_found / search_failed /
  partial / source_unavailable / permission_denied / provider_limit /
  revision_mismatch) при сохранении прежнего `status` для существующих
  потребителей;
* identity выбранного источника (repo/ref/commit/checkout), provenance,
  progress/idempotency id;
* поиск по содержимому всей доступной ревизии, включая идентификатор, не
  являющийся именем файла; отсутствие фиксированного top-3; различение
  implementation/caller/tests/docs/plans/migration/deploy/mention;
* порционную выдачу с opaque continuation cursor без повтора уже выданного;
* ровно один local→remote fallback по точному deployed commit, отсутствие
  циклов; отказ прав не обходится; `revision_mismatch` честен;
* `partial` с конкретной причиной, а не ложный `not_found`.

Тесты используют реальные байты синтетического локального дерева
(`LocalSnapshotProvider`) и deterministic stub удалённого провайдера — без сети.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.settings import settings
from services import hot_config as hot
from services import source_reader as sr
from services import tool_result

REPO = sr.DEFAULT_REPO_ORIGIN
SHA = "a" * 40
OTHER_SHA = "b" * 40

BASE_FILES = {
    "services/source_reader.py": "def probe():\n    return 42\n",
    "config/settings.py": "APP_VERSION = '2.58.200'\n",
}


def _tree(tmp_path: Path, files: dict[str, str], *, sha: str = SHA,
          origin: str = REPO) -> Path:
    root = tmp_path / "app"
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in {**BASE_FILES, **files}.items():
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
    return root


def _identity(*, code: str = "verified_deployed", checkout: str | None = SHA,
              deployed: str | None = SHA, dirty: bool | None = False,
              origin: str = REPO, runtime: str = "2.58.200",
              manifest: str | None = "2.58.200",
              consistent: bool | None = True) -> dict:
    return {
        "schema": 1, "code": code, "reason": "",
        "repo_origin": origin, "deployed_sha": deployed,
        "checkout_sha": checkout, "dirty": dirty,
        "local_source_verification": ("verified_deployed"
                                      if code == "verified_deployed"
                                      else "local_unverified"),
        "version_provenance": {"runtime": runtime, "manifest": manifest,
                               "consistent": consistent},
        "local_identity": {"checkout_sha": checkout, "dirty": dirty,
                           "checkout_mtime": None, "branch": "main"},
    }


def _resolve(tree: Path | None, identity: dict | None) -> dict:
    return sr.resolve_local_source(
        runtime_root=tree, configured_root="", repo_origin=REPO,
        identity_reader=(lambda _root: identity) if identity else None)


class _StubRemote:
    """Deterministic remote provider: fixed bytes, no network, no DNS."""

    name = sr.PROVIDER_GITHUB
    uses_auth = False
    network_calls = 0

    def __init__(self, files: dict[str, str] | None = None, *,
                 tree_none: bool = False,
                 tree_error: sr.SourceFetchError | None = None,
                 read_error: sr.SourceFetchError | None = None) -> None:
        self.files = dict(files or {})
        self.tree_none = tree_none
        self.tree_error = tree_error
        self.read_error = read_error
        self.calls: list[str] = []
        self.refs: list[str] = []
        self.list_tree_calls = 0
        self.read_calls = 0

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
        return text.lower() if len(text) == 40 else SHA

    async def list_tree(self, repo, commit):
        self.calls.append("list_tree")
        self.list_tree_calls += 1
        if self.tree_error is not None:
            raise self.tree_error
        if self.tree_none:
            return None
        return sr.TreeListing(entries=[
            sr.TreeEntry(path=path, kind="blob", size=len(text.encode()))
            for path, text in sorted(self.files.items())])

    async def read_file(self, repo, commit, path, *, blob_sha="", **kwargs):
        self.calls.append("read_file")
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        text = self.files.get(path)
        if text is None:
            return None
        return sr.SourceFile(path=path, data=text.encode("utf-8"),
                             sha="", size=len(text.encode()),
                             endpoint=sr.ENDPOINT_CONTENTS)


class _FailingReadProvider(_StubRemote):
    """Дерево доступно, но каждое чтение файла падает заданным отказом."""

    def __init__(self, files: dict[str, str], error: sr.SourceFetchError):
        super().__init__(files, read_error=error)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", True)
    monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN", "")
    monkeypatch.setattr(type(settings), "SELF_DIAG_LOCAL_REPO_ROOT", "")
    monkeypatch.setattr(hot, "get", lambda key, default=None: default)
    monkeypatch.setattr(sr, "_REPO_ORIGIN_LAST", None)
    monkeypatch.setattr(sr, "runtime_application_root", lambda: None)
    monkeypatch.delenv("ADMINBOT_DEPLOYED_SHA", raising=False)
    for name in ("SOURCE_READ_MAX_FILES", "SOURCE_READ_MAX_DEPTH",
                 "SOURCE_READ_MAX_REQUESTS", "SOURCE_READ_CONTENT_SCAN_BYTES"):
        monkeypatch.delenv(name, raising=False)

    async def _budgets_off(chat_id=None):
        return False

    monkeypatch.setattr(sr, "budget_limits_enforced", _budgets_off)


def _reader(tmp_path: Path, files: dict[str, str], *,
            identity: dict | None = None,
            remote: _StubRemote | None = None):
    tree = _tree(tmp_path, files)
    record = _resolve(tree, identity or _identity())
    provider = sr.LocalSnapshotProvider(
        tree, repo_origin=REPO,
        identity_reader=lambda _root: identity or _identity(),
        source=record)
    reader = sr.SourceReader(provider=remote or _StubRemote(),
                             local_provider=provider, repo_origin=REPO)
    return reader, record, tree, provider


def _remote_reader(remote: _StubRemote) -> sr.SourceReader:
    """Только удалённый провайдер + известный deployed SHA (без локального)."""
    return sr.SourceReader(
        provider=remote,
        local_source={"usable": False, "verification": "unavailable",
                      "revision": "", "revision_kind": sr.LOCAL_REVISION_NONE,
                      "deployed_sha": SHA, "version_verified": False},
        repo_origin=REPO)


NO_MARKER_FILES = {
    "services/aaa_module_0.py": "VALUE = 0\n",
    "services/aaa_module_1.py": "VALUE = 1\n",
    "services/aaa_module_2.py": "VALUE = 2\n",
}


GENERIC_FILES = {
    # 5 implementation-файлов до цели: старый ranked[:3] не дошёл бы до неё.
    "services/aaa_module_0.py": "VALUE = 0\n",
    "services/aaa_module_1.py": "VALUE = 1\n",
    "services/aaa_module_2.py": "VALUE = 2\n",
    "services/aaa_module_3.py": "VALUE = 3\n",
    "services/aaa_module_4.py": "VALUE = 4\n",
    # Цель: имя файла не содержит искомого идентификатора.
    "services/payments_worker.py": (
        "LEDGER_MARKER = 'ledger.reconcile.marker'\n\n"
        "def reconcile():\n    return LEDGER_MARKER\n"),
    "services/payments_caller.py": (
        "from services.payments_worker import reconcile\n\n"
        "def run():\n    return reconcile()\n"),
    "tests/test_payments_worker.py": (
        "def test_marker():\n    assert 'ledger.reconcile.marker'\n"),
    "docs/payments.md": "Marker `ledger.reconcile.marker` is documented.\n",
    "plans/payments-plan.md": "План: ledger.reconcile.marker\n",
    "migrations/0007_ledger.sql": "-- ledger.reconcile.marker\nSELECT 1;\n",
    "scripts/deploy_payments.sh": "echo ledger.reconcile.marker\n",
}


class TestContentSearch:
    @pytest.mark.asyncio
    async def test_identifier_not_a_filename_found_beyond_top_three(
            self, tmp_path):
        remote = _StubRemote()
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES, remote=remote)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)

        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["outcome"] == sr.OUTCOME_OK, payload
        assert payload["verified"] is True
        assert payload["path"] == "services/payments_worker.py"
        assert payload["match_material"] == sr.MATERIAL_IMPLEMENTATION
        assert payload["match_line"] >= 1
        assert "ledger.reconcile.marker" in payload["snippet"]
        # Доказано, что проверено больше трёх кандидатов и цель не по имени.
        assert payload["content_search"]["files_scanned"] > 3
        assert payload["content_search"]["complete"] is True
        assert payload["candidate_paths_total"] >= len(GENERIC_FILES) + 2

        materials = {item["material"] for item in payload["matches"]}
        assert sr.MATERIAL_IMPLEMENTATION in materials
        assert sr.MATERIAL_TESTS in materials
        assert sr.MATERIAL_DOCUMENTATION in materials
        assert sr.MATERIAL_PLANS in materials
        assert sr.MATERIAL_MIGRATION in materials
        assert sr.MATERIAL_DEPLOY_SCRIPT in materials
        assert remote.calls == []          # verified local tree, без сети

    @pytest.mark.asyncio
    async def test_content_search_returns_exact_watchdog_component(
            self, tmp_path):
        files = {
            "services/aaa_harness.py": "def dump():\n    return 1\n",
            "services/mca_watchdog.py": (
                "PROCESS_ID = 'watchdog.jobs'\n\n"
                "def emit():\n    return PROCESS_ID\n"),
        }
        reader, _record, _tree_path, _provider = _reader(tmp_path, files)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="watchdog.jobs", follow=False)
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["path"] == "services/mca_watchdog.py"
        assert payload["match_material"] == sr.MATERIAL_IMPLEMENTATION
        assert payload["matches"][0]["material"] == (
            sr.MATERIAL_IMPLEMENTATION)

    @pytest.mark.asyncio
    async def test_symbol_query_distinguishes_implementation_and_callers(
            self, tmp_path):
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="reconcile", symbol="reconcile", follow=False)
        assert payload["status"] == sr.STATUS_OK, payload
        roles: dict[str, set] = {}
        for item in payload["matches"]:
            roles.setdefault(item["path"], set()).add(item["material"])
        assert sr.MATERIAL_IMPLEMENTATION in roles.get(
            "services/payments_worker.py", set())
        assert sr.MATERIAL_CALLER in roles.get(
            "services/payments_caller.py", set())

    @pytest.mark.asyncio
    async def test_verified_local_absence_is_honest_not_found_without_network(
            self, tmp_path):
        remote = _StubRemote()
        reader, record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES, remote=remote)
        assert record["version_verified"] is True
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="absent.marker.xyz", follow=False)
        assert payload["status"] == sr.STATUS_NOT_FOUND, payload
        assert payload["outcome"] == sr.OUTCOME_NOT_FOUND
        assert payload["verified"] is False
        assert payload["content_search"]["complete"] is True
        assert payload["content_search"]["reason"] == "no_content_match"
        assert remote.calls == []

    @pytest.mark.asyncio
    async def test_scan_budget_returns_partial_and_cursor_continues(
            self, tmp_path, monkeypatch):
        files = {
            # Первый implementation-файл уже содержит пробу: он будет выдан
            # в первой порции и НЕ должен повториться во второй.
            "services/aaa_module_0.py": "MARKER = 'ledger.reconcile.marker'\n",
            "services/aaa_module_1.py": "VALUE = 1\n",
            "services/payments_worker.py": (
                "TARGET = 'ledger.reconcile.marker'\n"),
        }
        budget = len("MARKER = 'ledger.reconcile.marker'\n".encode()) + 1
        monkeypatch.setattr(sr, "content_scan_budget_bytes", lambda: budget)
        reader, _record, _tree_path, _provider = _reader(tmp_path, files)
        first = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert first["outcome"] == sr.OUTCOME_PARTIAL, first
        assert first["status"] == sr.STATUS_OK
        assert first["path"] == "services/aaa_module_0.py"
        token = first["continuation"]["cursor"]
        assert token and "ledger" not in token
        assert first["continuation"]["kind"] == "content_search"
        assert first["continuation"]["remaining"] is True
        assert first["continuation"]["progress_id"] == first["progress_id"]

        second = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", cursor=token, follow=False)
        assert second["status"] == sr.STATUS_OK, second
        assert second["progress_id"] == first["progress_id"]
        assert second["path"] != "services/aaa_module_0.py"
        returned = {item["path"] for item in second["matches"]}
        assert "services/aaa_module_0.py" not in returned
        assert second["content_search"]["files_scanned"] >= 1

    @pytest.mark.asyncio
    async def test_scan_budget_without_hit_is_honest_partial_not_not_found(
            self, tmp_path, monkeypatch):
        files = {"services/aaa_module_0.py": "VALUE = 0\n",
                 "services/payments_worker.py": "TARGET = 1\n"}
        monkeypatch.setattr(sr, "content_scan_budget_bytes", lambda: 1)
        reader, _record, _tree_path, _provider = _reader(tmp_path, files)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["status"] == sr.STATUS_PARTIAL
        assert payload["outcome"] == sr.OUTCOME_PARTIAL
        assert payload["verified"] is False
        assert payload["not_checked"]["reason"] == "scan_budget"
        assert payload["content_search"]["reason"] == "scan_budget"
        assert payload["continuation"]["cursor"]

    @pytest.mark.asyncio
    async def test_line_truncation_has_file_continuation(
            self, tmp_path):
        body = "\n".join(f"row_{index} = {index}" for index in range(80)) + "\n"
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, {"services/big.py": body})
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, path="services/big.py",
            follow=False, budget_chars=200)
        assert payload["status"] == sr.STATUS_OK
        assert payload["outcome"] == sr.OUTCOME_PARTIAL
        assert payload["truncation"]["truncated"] is True
        continuation = payload["continuation"]
        assert continuation["kind"] == "file_lines"
        assert continuation["next_arguments"]["line_start"] == (
            payload["truncation"]["next_line_start"])
        assert continuation["next_arguments"]["path"] == "services/big.py"


class TestFallback:
    @pytest.mark.asyncio
    async def test_unverified_local_search_uses_exact_deployed_commit_once(
            self, tmp_path):
        remote = _StubRemote({
            "services/remote_only.py": "TARGET = 'ledger.reconcile.marker'\n"})
        identity = _identity(code="local_unverified", checkout=OTHER_SHA,
                             deployed=SHA, dirty=None)
        reader, record, _tree_path, _provider = _reader(
            tmp_path, NO_MARKER_FILES, identity=identity, remote=remote)
        assert record["version_verified"] is False
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert payload["commit"] == SHA
        assert payload["path"] == "services/remote_only.py"
        selection = payload["source_selection"]
        assert selection["fallback"]
        assert selection["fallback"]["commit"] == SHA
        # Ни одной подстановки master/default branch: чтение закреплено точным
        # SHA (для 40-hex GitHub resolve_commit вообще не нужен).
        assert payload["commit"] == SHA
        assert all(ref.lower() == SHA for ref in remote.refs)
        assert remote.list_tree_calls == 1
        assert remote.read_calls >= 1

    @pytest.mark.asyncio
    async def test_local_tree_unavailable_search_falls_back_once(
            self, tmp_path):
        remote = _StubRemote({
            "services/remote_only.py": "TARGET = 'ledger.reconcile.marker'\n"})
        reader, _record, tree, _provider = _reader(
            tmp_path, GENERIC_FILES, remote=remote)
        import shutil
        shutil.rmtree(tree)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["provider"] == sr.PROVIDER_GITHUB
        assert payload["commit"] == SHA
        assert payload["source_selection"]["fallback"]
        # Ровно один удалённый маршрут, без local→remote→local цикла.
        assert remote.list_tree_calls <= 1

    @pytest.mark.asyncio
    async def test_remote_unavailable_after_fallback_is_structured_no_loop(
            self, tmp_path):
        remote = _StubRemote(tree_none=True)
        identity = _identity(code="local_unverified", checkout=OTHER_SHA,
                             deployed=SHA, dirty=None)
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, NO_MARKER_FILES, identity=identity, remote=remote)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["outcome"] == sr.OUTCOME_SOURCE_UNAVAILABLE
        assert payload["source_selection"]["fallback"]
        assert remote.list_tree_calls == 1
        assert remote.files == {}

    @pytest.mark.asyncio
    async def test_remote_cursor_continues_on_same_provider_after_fallback(
            self, tmp_path, monkeypatch):
        remote_files = {
            f"services/r{index:02d}.py": "VALUE = 0\n" for index in range(10)}
        remote_files["services/r08.py"] = "TARGET = 'ledger.reconcile.marker'\n"
        remote = _StubRemote(remote_files)
        identity = _identity(code="local_unverified", checkout=OTHER_SHA,
                             deployed=SHA, dirty=None)
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, {}, identity=identity, remote=remote)
        monkeypatch.setattr(sr, "content_scan_budget_bytes", lambda: 50)
        first = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert first["provider"] == sr.PROVIDER_GITHUB
        assert first["outcome"] == sr.OUTCOME_PARTIAL, first
        token = first["continuation"]["cursor"]
        assert token
        second = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", cursor=token, follow=False)
        assert second["provider"] == sr.PROVIDER_GITHUB
        assert second["commit"] == SHA
        assert second["progress_id"] == first["progress_id"]
        assert second["path"] == "services/r08.py"
        assert second["outcome"] in (sr.OUTCOME_OK, sr.OUTCOME_PARTIAL)

    @pytest.mark.asyncio
    async def test_permission_denied_is_not_bypassed_by_remote(
            self, tmp_path):
        remote = _StubRemote({".env": "SECRET=1\n"})
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, {".env": "SECRET=1\n", **GENERIC_FILES}, remote=remote)
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, path=".env",
            follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_PATH_DENIED
        assert payload["outcome"] == sr.OUTCOME_PERMISSION_DENIED
        assert payload["source_selection"]["fallback"] is None
        assert remote.calls == []

    @pytest.mark.asyncio
    async def test_requested_other_commit_is_not_silently_substituted(
            self, tmp_path):
        remote = _StubRemote({"services/other.py": "X = 1\n"})
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES, remote=remote)
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, ref=OTHER_SHA,
            path="services/payments_worker.py", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_REVISION_MISMATCH
        assert payload["outcome"] == sr.OUTCOME_REVISION_MISMATCH
        # Явно запрошенная чужая ревизия не подменяется deployed SHA.
        assert payload["commit"] == ""
        assert remote.calls == []

    @pytest.mark.asyncio
    async def test_exact_commit_mismatch_is_revision_mismatch(
            self, tmp_path):
        remote = _StubRemote()
        identity = _identity(code="local_unverified", checkout=SHA,
                             deployed=None, dirty=None)
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES, identity=identity, remote=remote)
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, ref=OTHER_SHA,
            path="services/payments_worker.py", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_REVISION_MISMATCH
        assert payload["outcome"] == sr.OUTCOME_REVISION_MISMATCH
        assert remote.calls == []


class TestStructuredFailures:
    @pytest.mark.asyncio
    async def test_search_failure_after_bounded_retry_is_search_failed(
            self, tmp_path):
        remote = _FailingReadProvider(
            {"services/payments_worker.py": "TARGET = 1\n"},
            sr.SourceFetchError(sr.ERR_PARSE, sr.STAGE_FETCH,
                                detail="invalid_json"))
        reader = _remote_reader(remote)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["outcome"] == sr.OUTCOME_SEARCH_FAILED
        assert payload["error"] == sr.ERR_PARSE
        assert payload["content_search"]["error"]["code"] == sr.ERR_PARSE

    @pytest.mark.asyncio
    async def test_retryable_read_error_bounded_retry_then_source_unavailable(
            self, tmp_path):
        remote = _FailingReadProvider(
            {"services/payments_worker.py": "TARGET = 1\n"},
            sr.SourceFetchError(sr.ERR_PROVIDER_UNAVAILABLE,
                                sr.STAGE_FETCH, retryable=True,
                                detail="boom"))
        reader = _remote_reader(remote)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        # Один bounded retry на чтение; дальше — честный structured result.
        assert remote.read_calls == 2
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["outcome"] == sr.OUTCOME_SOURCE_UNAVAILABLE
        assert payload["error"] == sr.ERR_PROVIDER_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_provider_rate_limit_is_provider_limit(self, tmp_path):
        remote = _StubRemote(
            tree_error=sr.SourceFetchError(sr.ERR_RATE_LIMIT,
                                           sr.STAGE_FETCH, retryable=True))
        reader = _remote_reader(remote)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["outcome"] == sr.OUTCOME_PROVIDER_LIMIT
        assert payload["error"] == sr.ERR_RATE_LIMIT

    @pytest.mark.asyncio
    async def test_tree_unavailable_is_source_unavailable(self):
        remote = _StubRemote(tree_none=True)
        reader = _remote_reader(remote)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["outcome"] == sr.OUTCOME_SOURCE_UNAVAILABLE
        assert payload["reason"] == "tree_unavailable"

    @pytest.mark.asyncio
    async def test_unknown_or_foreign_cursor_is_revision_mismatch(
            self, tmp_path):
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", cursor="not-a-real-cursor",
            follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["outcome"] == sr.OUTCOME_REVISION_MISMATCH

    @pytest.mark.asyncio
    async def test_cursor_identity_mismatch_is_revision_mismatch(
            self, tmp_path, monkeypatch):
        files = {
            "services/aaa_module_0.py": "MARKER = 'ledger.reconcile.marker'\n",
            "services/aaa_module_1.py": "VALUE = 1\n",
        }
        monkeypatch.setattr(sr, "content_scan_budget_bytes", lambda: 20)
        reader, _record, _tree_path, _provider = _reader(tmp_path, files)
        first = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        token = first["continuation"]["cursor"]
        # Тот же cursor с ДРУГОЙ ревизией (identity) не читает чужое дерево.
        tampered = dict(sr._cursor_decode(token))
        tampered["commit"] = OTHER_SHA
        second = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO, ref=SHA,
            query="ledger.reconcile.marker",
            cursor=sr._cursor_encode(tampered), follow=False)
        assert second["outcome"] == sr.OUTCOME_REVISION_MISMATCH
        assert second["error"] == sr.ERR_REVISION_MISMATCH


class TestContractMetadata:
    @pytest.mark.asyncio
    async def test_provenance_selection_progress_and_idempotency(
            self, tmp_path):
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES)
        payload = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        assert payload["progress_id"].startswith("srp_")
        assert payload["idempotency_key"].startswith("sri_")
        assert payload["query"] == "ledger.reconcile.marker"
        selection = payload["source_selection"]
        assert selection["repo"] == REPO
        assert selection["revision"] == SHA
        assert selection["identity"]["commit"] == SHA
        assert selection["identity"]["checkout_sha"] == SHA
        assert selection["requested_ref"] == ""
        provenance = payload["provenance"]
        assert provenance["repo"] == REPO
        assert provenance["commit"] == SHA
        assert provenance["provider"] == sr.PROVIDER_LOCAL
        assert provenance["endpoint"] == sr.PROVIDER_LOCAL
        assert provenance["outcome"] == sr.OUTCOME_OK
        assert isinstance(provenance["fetched_at"], int)
        assert str(_tree_path) not in json.dumps(provenance,
                                                 ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_legacy_tool_result_consumer_maps_new_classes(
            self, tmp_path, monkeypatch):
        files = {"services/aaa_module_0.py": "VALUE = 0\n"}
        monkeypatch.setattr(sr, "content_scan_budget_bytes", lambda: 1)
        reader, _record, _tree_path, _provider = _reader(tmp_path, files)
        partial = await reader.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="ledger.reconcile.marker", follow=False)
        partial_info = tool_result.classify_output(
            "read_source_code", json.dumps(partial, ensure_ascii=False))
        assert partial_info["status"] == tool_result.STATUS_OK
        assert partial_info["partial"] is True

        monkeypatch.setattr(sr, "content_scan_budget_bytes",
                            lambda: 8 * 1024 * 1024)
        reader2, _record2, _tree_path2, _provider2 = _reader(
            tmp_path / "missing", files)
        not_found = await reader2.run(
            operation=sr.OPERATION_LOCATE, repo=REPO,
            query="absent.marker.xyz", follow=False)
        not_found_info = tool_result.classify_output(
            "read_source_code", json.dumps(not_found, ensure_ascii=False))
        assert not_found_info["status"] == tool_result.STATUS_EMPTY

    @pytest.mark.asyncio
    async def test_same_request_has_same_progress_and_idempotency_ids(
            self, tmp_path):
        reader, _record, _tree_path, _provider = _reader(
            tmp_path, GENERIC_FILES)
        args = dict(operation=sr.OPERATION_LOCATE, repo=REPO,
                    query="ledger.reconcile.marker", follow=False)
        first = await reader.run(**args)
        second = await reader.run(**args)
        assert first["progress_id"] == second["progress_id"]
        assert first["idempotency_key"] == second["idempotency_key"]
        assert first["path"] == second["path"]
