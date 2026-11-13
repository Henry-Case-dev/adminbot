"""SMART-EXECUTION-RELIABILITY-01 · C1 — SourceReader без скрытых потолков.

Проверяем контракт стадии C1 (`plans/owner_inputs/2026-11-14-...md`, §C1):

* SXR-C1-01: безусловные потолки 6 файлов / 2 глубины / 16 запросов и заводские
  defaults 3/1/8 больше НЕ ограничивают чтение; произвольной замены нет;
  модель последовательно читает связанные файлы и следующие диапазоны строк.
* SXR-C1-02: safety остаётся (пути/бинарь/размер порции), большой текст
  доступен через диапазоны/страницы, весь репозиторий в один ответ не уходит.
* SXR-C1-03: счётчики живут ОДИН запрос и сбрасываются; исчерпание предыдущим
  независимым запросом не ломает следующий.

Тесты используют существующие контуры: ``LocalSnapshotProvider`` (реальные
байты, без сети) и минимальный stub-провайдер GitHub (счётчик вызовов).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import settings
from services import budget_gate
from services import hot_config as hot
from services import source_reader as sr
from services import source_reuse

REPO = "Henry-Case-dev/adminbot"
SHA = "0123456789abcdef0123456789abcdef01234567"
_ORIGINAL_PREDICATE = getattr(sr, "budget_limits_enforced", None)


# ── окружение ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", True)
    monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN", "")
    monkeypatch.setattr(type(settings), "SELF_DIAG_LOCAL_REPO_ROOT", "")
    monkeypatch.setattr(hot, "get", lambda key, default=None: default)
    monkeypatch.setattr(sr, "_REPO_ORIGIN_LAST", None)
    for name in ("SOURCE_READ_MAX_FILES", "SOURCE_READ_MAX_DEPTH",
                 "SOURCE_READ_MAX_REQUESTS"):
        monkeypatch.delenv(name, raising=False)

    # Предикат бюджета детерминирован (без БД/hot): по умолчанию OFF.
    async def _budgets_off(chat_id=None):
        return False

    if hasattr(sr, "budget_limits_enforced"):
        monkeypatch.setattr(sr, "budget_limits_enforced", _budgets_off)
    source_reuse.clear()


def _identity(*, sha: str = SHA, dirty: bool = False) -> dict:
    return {
        "schema": 1, "code": "verified_deployed", "reason": "",
        "repo_origin": REPO, "deployed_sha": sha, "checkout_sha": sha,
        "dirty": dirty, "local_source_verification": "verified_deployed",
        "local_identity": {"checkout_sha": sha, "dirty": dirty,
                           "checkout_mtime": None, "branch": "main"},
    }


def _write_repo(tmp_path: Path, files: dict[str, bytes | str]) -> Path:
    """Каталог-снимок + ``.git`` (HEAD → refs/heads/main → SHA)."""
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode("utf-8") if isinstance(data, str)
                           else data)
    git_dir = root / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs" / "heads" / "main").write_text(sha_line(), encoding="utf-8")
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/{REPO}.git\n',
        encoding="utf-8")
    return root


def sha_line() -> str:
    return SHA + "\n"


def _local(tmp_path: Path, files: dict[str, bytes | str], *,
           identity: dict | None = None, max_bytes: int | None = None):
    root = _write_repo(tmp_path, files)
    return sr.LocalSnapshotProvider(
        root, repo_origin=REPO,
        identity_reader=lambda _root: identity or _identity(),
        **({"max_bytes": max_bytes} if max_bytes else {}))


def _reader(tmp_path: Path, files: dict[str, bytes | str], *,
            identity: dict | None = None):
    return sr.SourceReader(provider=_StubGitHub(files),
                           local_provider=_local(tmp_path, files,
                                                 identity=identity),
                           repo_origin=REPO)


def _network_reader(files: dict[str, bytes | str]) -> sr.SourceReader:
    """Только stub-провайдер GitHub: локального checkout нет, вызовы считаются."""
    return sr.SourceReader(provider=_StubGitHub(files), repo_origin=REPO)


def _chain_files(count: int, *, prefix: str = "helper") -> tuple[str, dict]:
    """Главный файл с N вызовами + N смежных файлов с этими функциями."""
    names = [f"{prefix}_{index:02d}_fn" for index in range(count)]
    hub = "def hub():\n" + "".join(f"    {name}()\n" for name in names)
    files: dict[str, str] = {"services/hub.py": hub}
    for name in names:
        files[f"services/{name}.py"] = f"def {name}():\n    return 1\n"
    return "services/hub.py", files


# ── stub-провайдер GitHub (счётчик вызовов, без сети) ──────────────────────

class _StubGitHub:
    name = sr.PROVIDER_GITHUB
    uses_auth = False
    network_calls = 0

    def __init__(self, files: dict[str, bytes | str]) -> None:
        self.files = {
            path: (data.encode("utf-8") if isinstance(data, str) else data)
            for path, data in files.items()}

    async def search_repos(self, query, *, limit=5):
        return []

    async def resolve_repo(self, owner, repo):
        self.network_calls += 1
        return sr.RepoInfo(owner=owner, name=repo, default_branch="main",
                           language="Python")

    async def resolve_commit(self, repo, ref):
        self.network_calls += 1
        return SHA

    async def list_tree(self, repo, commit):
        self.network_calls += 1
        return sr.TreeListing(
            entries=[sr.TreeEntry(path=path, kind="blob", sha="",
                                  size=len(data))
                     for path, data in sorted(self.files.items())])

    async def read_file(self, repo, commit, path, *, blob_sha=""):
        self.network_calls += 1
        data = self.files.get(path)
        if data is None:
            return None
        return sr.SourceFile(path=path, data=data, sha="", size=len(data),
                             endpoint=sr.ENDPOINT_CONTENTS)


# ── SXR-C1-01: потолки 6 / 2 / 16 удалены ──────────────────────────────────

class TestCapRemoval:
    @pytest.mark.asyncio
    async def test_more_than_six_files_in_one_request(self, tmp_path):
        """9 связанных файлов — раньше 6 файлов блокировали чтение."""
        path, files = _chain_files(9)
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA, path=path,
            follow=True)
        assert payload["status"] == sr.STATUS_OK
        assert len(payload["files"]) == 10            # primary + 9 follow-up
        assert payload["not_checked"]["files_read"] == 10
        assert all(item["verified"] for item in payload["files"])
        assert payload["followup_incomplete"] is False
        assert "untried_paths" not in payload["not_checked"]

    @pytest.mark.asyncio
    async def test_depth_ceiling_removed_for_linked_chain(self, tmp_path):
        """Глубина 2 больше не обрывает цепочку связанных модулей."""
        path, files = _chain_files(6)
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA, path=path,
            follow=True)
        followups = [item for item in payload["files"]
                     if item["role"] == "followup"]
        assert len(followups) >= 5                    # было бы ≤ 2 при depth=2
        assert payload["not_checked"]["depth_left"] is None
        assert payload["not_checked"]["applied_limits"] == {
            "files": 0, "depth": 0, "requests": 0, "budgets_enforced": False}
        assert payload["followup_incomplete"] is False

    @pytest.mark.asyncio
    async def test_more_than_sixteen_network_calls_in_one_request(self):
        """18 связанных файлов = >16 сетевых вызовов в ОДНОМ запросе."""
        path, files = _chain_files(18)
        payload = await _network_reader(files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA, path=path,
            follow=True)
        assert payload["status"] == sr.STATUS_OK
        assert payload["network_calls"] > 16
        assert payload["network_calls_total"] == payload["network_calls"]
        assert payload["not_checked"]["applied_limits"]["requests"] == 0
        assert payload["not_checked"]["reason"] == ""
        assert len(payload["files"]) == 19

    def test_factory_constants_are_gone(self):
        """Ни 6/2/16, ни defaults 3/1/8 не остались как потолки."""
        for name in ("_MAX_FILES_CEILING", "_MAX_DEPTH_CEILING",
                     "_MAX_REQUESTS_CEILING", "_DEFAULT_MAX_FILES",
                     "_DEFAULT_MAX_DEPTH", "_DEFAULT_MAX_REQUESTS"):
            assert not hasattr(sr, name), name
        assert sr.max_files() == 0 and sr.max_depth() == 0
        assert sr.max_requests() == 0


# ── SXR-C1-03: lifetime/reset счётчиков ────────────────────────────────────

class TestCounterLifetime:
    @pytest.mark.asyncio
    async def test_previous_request_does_not_exhaust_next_request(self):
        """Запрос A (>16 вызовов) не делает запрос B неработоспособным."""
        path, files = _chain_files(18)
        reader = _network_reader(files)
        first = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                 ref=SHA, path=path, follow=True)
        assert first["status"] == sr.STATUS_OK
        assert first["network_calls"] > 16
        total_after_first = first["network_calls_total"]
        assert total_after_first >= first["network_calls"]

        # Запрос B: явная политика 16 вызовов ЗА ЗАПРОС. Пожизненный счётчик
        # уже больше 16 — enforcement обязан считать только текущий запрос.
        import os
        os.environ["SOURCE_READ_MAX_REQUESTS"] = "16"
        try:
            second = await reader.run(
                operation=sr.OPERATION_READ, repo=REPO, ref=SHA, path=path,
                follow=False, budget_enforced=True)
        finally:
            os.environ.pop("SOURCE_READ_MAX_REQUESTS", None)
        assert second["status"] == sr.STATUS_OK
        assert second["network_calls"] < 16
        assert second["network_calls_total"] > second["network_calls"]

    @pytest.mark.asyncio
    async def test_counters_restart_for_each_request(self, tmp_path):
        path, files = _chain_files(9)
        reader = _reader(tmp_path, files)
        first = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                 ref=SHA, path=path, follow=True)
        assert first["not_checked"]["files_read"] == 10
        second = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                  ref=SHA, path=path, follow=False)
        assert second["not_checked"]["files_read"] == 1
        assert second["not_checked"]["reason"] == ""


# ── SXR-C1-01/02: диапазоны и продолжение ─────────────────────────────────

BIG_LINES = 1500


def _big_file(lines: int = BIG_LINES) -> dict[str, str]:
    body = "\n".join(f"value_{index} = {index}" for index in range(1, lines + 1))
    return {"services/big.py": body + "\n"}


class TestRangeContinuation:
    @pytest.mark.asyncio
    async def test_large_text_readable_in_pages(self, tmp_path):
        """Большой текст доступен страницами; каждая страница — точный срез."""
        files = _big_file()
        reader = _reader(tmp_path, files)
        original = files["services/big.py"]
        collected: list[str] = []
        start = 1
        for _page in range(20):
            payload = await reader.run(
                operation=sr.OPERATION_READ, repo=REPO, ref=SHA,
                path="services/big.py", line_start=start, line_end=start + 299,
                follow=False)
            assert payload["status"] == sr.STATUS_OK
            assert payload["verified"] is True
            assert payload["file_total_lines"] == BIG_LINES
            collected.append(payload["snippet"])
            if not payload["truncation"]["truncated"]:
                break
            start = payload["truncation"]["next_line_start"]
        assert "\n".join(collected) == original.rstrip("\n")
        assert len(collected) == 5

    @pytest.mark.asyncio
    async def test_next_line_start_drives_continuation(self, tmp_path):
        """Усечённое окно отдаёт явный next_line_start и дочитывается до конца."""
        files = _big_file(400)
        reader = _reader(tmp_path, files)
        seen: list[int] = []
        start = 1
        for _page in range(50):
            payload = await reader.run(
                operation=sr.OPERATION_READ, repo=REPO, ref=SHA,
                path="services/big.py", line_start=start,
                budget_chars=1200, follow=False)
            assert payload["status"] == sr.STATUS_OK
            assert payload["line_range"][0] == start
            seen.append(payload["line_range"][1])
            if not payload["truncation"]["truncated"]:
                break
            next_start = payload["truncation"]["next_line_start"]
            assert next_start == payload["line_range"][1] + 1
            start = next_start
        assert len(seen) > 1                       # порция кончилась, чтение нет
        assert payload["truncation"]["truncated"] is False
        assert payload["line_range"][1] == 400


# ── SXR-C1-02: safety остаётся ────────────────────────────────────────────

class TestSafetyRetained:
    @pytest.mark.asyncio
    async def test_path_traversal_is_denied(self, tmp_path):
        files = {"services/hub.py": "def hub():\n    return 1\n"}
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA,
            path="../../etc/passwd", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_PATH_DENIED
        assert payload["snippet"] == "" and payload["verified"] is False

    @pytest.mark.asyncio
    async def test_denied_paths_and_ads_are_denied(self, tmp_path):
        files = {"services/hub.py": "def hub():\n    return 1\n",
                 ".env": "TOKEN=secret\n"}
        reader = _reader(tmp_path, files)
        for path in (".env", "services/hub.py:stream"):
            payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                       ref=SHA, path=path, follow=False)
            assert payload["error"] in (sr.ERR_PATH_DENIED,
                                        sr.ERR_SOURCE_MISSING), path
            assert payload["snippet"] == ""

    @pytest.mark.asyncio
    async def test_binary_payload_is_not_a_verified_source(self, tmp_path):
        files = {"assets/logo.bin": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"}
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA,
            path="assets/logo.bin", follow=False)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["reason"] == "binary_content"
        assert payload["verified"] is False and payload["snippet"] == ""

    @pytest.mark.asyncio
    async def test_single_portion_limit_is_reported_not_silent(self, tmp_path,
                                                               monkeypatch):
        """Предел байтов файла — реальный safety: честный отказ, не «пусто»."""
        monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_FILE_BYTES", 1024)
        files = {"services/hub.py": "def hub():\n    return 1\n",
                 "services/large.py": "x = 1\n" * 400}
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA,
            path="services/large.py", follow=False)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["reason"] == "file_too_large"
        assert payload["verified"] is False
        # Малый файл при том же пределе читается: отказ не глобальный.
        small = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA,
            path="services/hub.py", follow=False)
        assert small["status"] == sr.STATUS_OK and small["verified"] is True

    @pytest.mark.asyncio
    async def test_foreign_host_still_unsupported(self, tmp_path):
        files = {"services/hub.py": "def hub():\n    return 1\n"}
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ,
            url="https://gitlab.com/acme/mod/-/blob/main/x.py", follow=False)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["error"] == sr.ERR_PROVIDER_UNCONFIGURED

    @pytest.mark.asyncio
    async def test_single_request_does_not_dump_the_whole_repository(
            self, tmp_path):
        """Один ответ ограничен одной порцией текста + untried остаётся явным."""
        path, files = _chain_files(40)
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA, path=path,
            follow=True, budget_chars=300)
        assert payload["status"] == sr.STATUS_OK
        assert 1 <= len(payload["files"]) < 40
        assert payload["not_checked"]["chain_portion_limit"] == 300
        assert payload["not_checked"]["chain_delivered_chars"] <= 300 + 64
        assert payload["not_checked"]["untried_paths"]
        assert payload["not_checked"]["reason"] == "budget"


# ── budgets OFF/ON ────────────────────────────────────────────────────────

class TestBudgetsInterplay:
    @pytest.mark.asyncio
    async def test_budgets_off_ignores_explicit_env_policy(self, tmp_path,
                                                          monkeypatch):
        """OFF: env-потолки не возвращаются ни через один путь SourceReader."""
        monkeypatch.setenv("SOURCE_READ_MAX_FILES", "1")
        monkeypatch.setenv("SOURCE_READ_MAX_DEPTH", "1")
        monkeypatch.setenv("SOURCE_READ_MAX_REQUESTS", "1")
        path, files = _chain_files(9)
        reader = _reader(tmp_path, files)          # predicate → False
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   ref=SHA, path=path, follow=True)
        assert payload["status"] == sr.STATUS_OK
        assert len(payload["files"]) == 10
        assert payload["not_checked"]["applied_limits"]["files"] == 0
        assert payload["not_checked"]["applied_limits"]["requests"] == 0

    @pytest.mark.asyncio
    async def test_budgets_on_without_policy_has_no_factory_caps(self, tmp_path):
        """ON без явной политики: 6/2/16 как заводские потолки не появляются."""
        path, files = _chain_files(9)
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA, path=path,
            follow=True, budget_enforced=True)
        assert len(payload["files"]) == 10
        assert payload["not_checked"]["applied_limits"] == {
            "files": 0, "depth": 0, "requests": 0, "budgets_enforced": True}
        assert payload["not_checked"]["depth_left"] is None

    @pytest.mark.asyncio
    async def test_predicate_read_through_budget_gate(self, monkeypatch):
        """Предикат читается существующим budget_gate (без правок модуля)."""
        original = _ORIGINAL_PREDICATE
        monkeypatch.setattr(sr, "budget_limits_enforced", original)

        async def _on(chat_id=None):
            return True

        seen: dict = {}

        async def _spy(chat_id=None):
            seen["chat"] = chat_id
            return False

        monkeypatch.setattr(budget_gate, "budgets_enabled", _spy)
        assert await sr.budget_limits_enforced(4242) is False
        assert seen["chat"] == 4242
        monkeypatch.setattr(budget_gate, "budgets_enabled", _on)
        assert await sr.budget_limits_enforced() is True

        async def _boom(chat_id=None):
            raise RuntimeError("settings store down")

        monkeypatch.setattr(budget_gate, "budgets_enabled", _boom)
        # Ошибка резолва не включает enforcement и не бросает наружу.
        assert await sr.budget_limits_enforced(1) is False


# ── provenance ────────────────────────────────────────────────────────────

class TestProvenance:
    @pytest.mark.asyncio
    async def test_provenance_fields_survive(self, tmp_path):
        files = {"services/hub.py": "def hub():\n    return 1\n"}
        payload = await _reader(tmp_path, files).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=SHA,
            path="services/hub.py", follow=False)
        assert payload["provider"] == sr.PROVIDER_LOCAL
        assert payload["repo"] == REPO
        assert payload["commit"] == SHA
        assert payload["path"] == "services/hub.py"
        assert payload["line_range"] == [1, 2]
        assert payload["verified"] is True
        assert payload["source_id"]
        assert payload["provenance"]["bytes"] == len(files["services/hub.py"])
        assert len(payload["provenance"]["sha256"]) == 64
        assert payload["local_source_verification"] == "verified_deployed"
        assert payload["verified_url"].startswith(
            f"repo://adminbot@{SHA}/services/hub.py#L")
