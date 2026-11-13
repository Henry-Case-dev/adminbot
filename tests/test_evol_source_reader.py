"""EVOL-SRC-READER (W6) — проверенное чтение исходников (`read_source_code`).

Приёмка — 7 сценариев §1.5 ТЗ (без обязательных живых внешних вызовов):
прямая blob-ссылка, только имя репозитория + описание механизма, только
описание, «класс лишь выставляет параметр», честные отказы (403/404/rate
limit/timeout/HTML), отсутствие выдуманных цитат/дат, отсутствие лишних
сетевых вызовов и утечек/исполнения.

Сеть НЕ используется: провайдер работает через существующий `SafeFetcher` с
`httpx.MockTransport` (прецедент `tests/test_mca02_safe_fetch_round1027.py`), а
DNS-резолв подменяется детерминированно. Проверяется то, что утверждает
контракт: `verified` только по реальным байтам, `snippet` — точная подстрока,
`line_range` из этих байт, commit-pinned `verified_url`, reuse по claim-key,
chat-isolation приватного доступа, границы follow-up и отсутствие новых кодов.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest

from config.settings import settings
from services import capability_registry as caps
from services import direct_chat_service as dcs
from services import evidence_policy as evp
from services import mca_events
from services import safe_fetch as sf
from services import source_reader as sr
from services import source_reuse
from services import tool_result
from services import tool_schemas
from services.tool_router import ToolContext, ToolDeps, ToolRouter

COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
REPO = "acme/mod"
PUBLIC_IP = "93.184.216.34"

FILE_MACHINE = """package acme;

public class ParallelHatchPartMachine extends HatchPartMachine {
    private final ParallelLogic logic;
    private int parallel;

    public ParallelHatchPartMachine(int parallel) {
        this.parallel = parallel;
        this.logic = new ParallelLogic(parallel);
    }

    @Override
    public int getParallel() {
        return logic.compute(parallel);
    }
}
"""

FILE_LOGIC = """package acme;

public class ParallelLogic {
    private final int limit;

    public ParallelLogic(int limit) {
        this.limit = limit;
    }

    public int compute(int requested) {
        return Math.min(requested, limit);
    }
}
"""

#: Класс, который «лишь выставляет параметр» (§1.2.4 сценарий 4).
FILE_CONFIG = """package acme;

public class ParallelConfig {
    public int chanceLimit;
    public static final int MAX_PARALLEL = 8;
}
"""

FILE_TEST = """package acme;

public class ParallelLogicTest { }
"""

#: Тот же исходник в CRLF: реальные Windows-репозитории (и 16 файлов этого
#: репозитория) закоммичены так. Фрагмент обязан оставаться точной подстрокой.
FILE_CRLF = FILE_LOGIC.replace("\n", "\r\n")

#: UTF-8 с кириллицей в комментариях и строках — обычный русский исходник.
FILE_CYRILLIC = """package acme;

// Параллельный выход: считаем по пределу
public class ParallelLimit {
    private int limit = 4;

    public int compute(int requested) {
        // минимум из запрошенного и предела
        return Math.min(requested, limit);
    }
}
"""

#: Бинарные байты (заголовок PNG + NUL): не «код», verified быть не может.
FILE_BINARY = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
               b"\x00\x00\x01\x00\x00\x00\x01\x00\x08\x06\x00"
               b"\x00\x00\x1f\x15\xc4\x89\x00\x00")

#: Не-UTF-8 байты (0xFF) — честный invalid_encoding, не «файл не найден».
FILE_BAD_UTF8 = b"package acme;\n// caf\xe9 \xff\nclass A {}\n"

FILES = {
    "src/main/java/acme/ParallelHatchPartMachine.java": FILE_MACHINE,
    "src/main/java/acme/ParallelLogic.java": FILE_LOGIC,
    "src/main/java/acme/ParallelConfig.java": FILE_CONFIG,
    "src/main/java/acme/CrlfLogic.java": FILE_CRLF,
    "src/main/java/acme/ParallelLimit.java": FILE_CYRILLIC,
    "src/main/java/acme/Empty.java": "",
    "src/main/java/acme/Legacy.java": FILE_BAD_UTF8,
    "assets/logo.bin": FILE_BINARY,
    "src/test/java/acme/ParallelLogicTest.java": FILE_TEST,
    "README.md": "# acme mod\n",
}


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _b64_bytes(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _tree(files: dict) -> dict:
    entries = []
    for path, body in files.items():
        if isinstance(body, bytes):
            entries.append({"path": path, "type": "blob",
                            "sha": _sha_bytes(body), "size": len(body)})
        else:
            entries.append({"path": path, "type": "blob", "sha": _sha(body),
                            "size": len(body.encode("utf-8"))})
    entries.append({"path": "src/main/java/acme", "type": "tree",
                    "sha": _sha("dir")})
    return {"sha": COMMIT, "tree": entries, "truncated": False}


class FakeGitHub:
    """Детерминированный GitHub: только фикстуры, ни одного реального вызова."""

    def __init__(self, files: dict | None = None, *, status: int | None = None,
                 body: bytes | None = None, redirect_to: str = "",
                 path_mismatch: bool = False, truncated_tree: bool = False,
                 raw_disabled: bool = False,
                 tree_status: int | None = None,
                 directories: tuple[str, ...] = (),
                 search_items: list | None = None) -> None:
        self.files = dict(FILES if files is None else files)
        self.directories = set(directories)
        self.tree_status = tree_status
        self.status = status
        self.body = body
        self.redirect_to = redirect_to
        self.path_mismatch = path_mismatch
        self.truncated_tree = truncated_tree
        self.raw_disabled = raw_disabled
        self.search_items = search_items
        self.calls: list[str] = []

    # -- helpers ---------------------------------------------------
    @staticmethod
    def _json(request, payload, status: int = 200) -> httpx.Response:
        return httpx.Response(status, json=payload, request=request)

    def _contents(self, request, path: str) -> httpx.Response:
        if path in self.directories:
            return self._json(request, [{"name": "x", "type": "file"}])
        body = self.files.get(path)
        if body is None:
            return self._json(request, {"message": "Not Found"}, 404)
        if isinstance(body, bytes):
            return self._json(request, {
                "type": "file", "path": path,
                "sha": _sha_bytes(body), "size": len(body),
                "encoding": "base64", "content": _b64_bytes(body)})
        return self._json(request, {
            "type": "file",
            "path": "src/main/java/acme/Other.java" if self.path_mismatch
            else path,
            "sha": _sha(body),
            "size": len(body.encode("utf-8")),
            "encoding": "base64",
            "content": _b64(body),
        })

    # -- transport handler -----------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        # Соединение идёт на валидированный IP (pinning SafeFetcher), а
        # логический хост сервер видит в Host — маршрутизация по vhost.
        host = (request.headers.get("host", "").split(":")[0] or url.host)
        self.calls.append(f"{host}{url.path}")
        if self.status is not None:
            headers = {}
            return httpx.Response(self.status, headers=headers,
                                  content=self.body or b"", request=request)
        if self.redirect_to:
            return httpx.Response(302, headers={"location": self.redirect_to},
                                  request=request)
        path = url.path
        if host == "api.github.com":
            if path == "/search/repositories":
                return self._json(request, {"items": self.search_items or []})
            if path == f"/repos/{REPO}":
                return self._json(request, {
                    "full_name": REPO, "name": "mod", "owner": {"login": "acme"},
                    "default_branch": "main", "language": "Java",
                    "stargazers_count": 1200,
                    "description": "parallel output helpers",
                    "pushed_at": "2026-01-01T00:00:00Z"})
            if path == f"/repos/{REPO}/commits":
                ref = url.params.get("sha", "")
                sha = {"main": COMMIT, "1.20.1": COMMIT,
                       "feature/x": COMMIT}.get(ref)
                if not sha:
                    return self._json(request, {"message": "Not Found"}, 404)
                return self._json(request, [{"sha": sha}])
            if path == f"/repos/{REPO}/git/trees/{COMMIT}":
                if self.tree_status:
                    return self._json(request, {"message": "boom"},
                                      self.tree_status)
                tree = _tree(self.files)
                tree["truncated"] = self.truncated_tree
                return self._json(request, tree)
            prefix = f"/repos/{REPO}/contents/"
            if path.startswith(prefix):
                return self._contents(request, path[len(prefix):])
            blob_prefix = f"/repos/{REPO}/git/blobs/"
            if path.startswith(blob_prefix):
                sha = path[len(blob_prefix):]
                for body in self.files.values():
                    if isinstance(body, bytes):
                        if _sha_bytes(body) == sha:
                            return self._json(request, {
                                "sha": sha, "size": len(body),
                                "encoding": "base64", "content": _b64_bytes(body)})
                        continue
                    if _sha(body) == sha:
                        return self._json(request, {
                            "sha": sha, "size": len(body.encode("utf-8")),
                            "encoding": "base64", "content": _b64(body)})
                return self._json(request, {"message": "Not Found"}, 404)
            return self._json(request, {"message": "Not Found"}, 404)
        if host == "raw.githubusercontent.com":
            if self.raw_disabled:
                return httpx.Response(404, content=b"", request=request)
            # /{owner}/{repo}/{commit}/{path}
            parts = path.lstrip("/").split("/")
            body = self.files.get("/".join(parts[3:])) if len(parts) > 3 else None
            if body is None:
                return httpx.Response(404, content=b"", request=request)
            raw = body if isinstance(body, bytes) else body.encode("utf-8")
            return httpx.Response(200, content=raw,
                                  headers={"content-type": "text/plain"},
                                  request=request)
        return httpx.Response(404, content=b"", request=request)


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Резолв детерминированный: никаких реальных DNS-запросов (без сети)."""
    monkeypatch.setattr(sf, "_resolve_ip", lambda host: [PUBLIC_IP])
    # Kill-switch по умолчанию ON и токена нет (изоляция тестов).
    monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", True)
    monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN", "")
    monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_FILES", 3)
    monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_DEPTH", 1)
    monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_REQUESTS", 8)
    source_reuse.clear()


def _reader(fake: FakeGitHub, **kwargs) -> sr.SourceReader:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler),
                               follow_redirects=False, timeout=None)
    provider = sr.GitHubProvider(sf.SafeFetcher(client=client), **kwargs)
    return sr.SourceReader(provider=provider)


def _router(fake: FakeGitHub, **deps_kwargs) -> ToolRouter:
    class _Search:
        def __init__(self, text=""):
            self.text = text

        async def search(self, query, max_symbols=None, **kwargs):
            return self.text

    return ToolRouter(ToolDeps(_Search(), None,
                               source_reader=_reader(fake), **deps_kwargs))


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(-100500, "где считается параллельный выход", **kwargs)


# ── 1. Разбор ссылок (форма URL, не словарь имён) ───────────────────────────

class TestUrlParsing:
    def test_blob_link_with_line_fragment(self):
        parsed = sr.parse_source_url(
            "https://github.com/acme/mod/blob/1.20.1/"
            "src/main/java/acme/ParallelHatchPartMachine.java#L12-L14")
        assert parsed is not None and parsed.supported
        assert (parsed.owner, parsed.repo) == ("acme", "mod")
        assert parsed.kind == sr.KIND_FILE
        assert parsed.ref == "1.20.1"
        assert parsed.path == "src/main/java/acme/ParallelHatchPartMachine.java"
        assert (parsed.line_start, parsed.line_end) == (12, 14)

    def test_branch_with_slash_has_shortest_ref_first(self):
        parsed = sr.parse_source_url(
            "https://github.com/acme/mod/blob/feature/x/src/Foo.java")
        refs = [ref for ref, _path in parsed.ref_path_candidates]
        assert refs[0] == "feature"
        assert "feature/x" in refs           # слэш-ветка тоже проверяется
        assert len(parsed.ref_path_candidates) <= 4

    def test_tree_readme_issue_pull_forms(self):
        tree = sr.parse_source_url("https://github.com/acme/mod/tree/main/src")
        assert tree.kind == sr.KIND_DIRECTORY and tree.ref == "main"
        readme = sr.parse_source_url(
            "https://github.com/acme/mod/blob/main/README.md")
        assert readme.kind == sr.KIND_README
        assert sr.parse_source_url(
            "https://github.com/acme/mod/issues/12").kind == sr.KIND_ISSUE
        assert sr.parse_source_url(
            "https://github.com/acme/mod/pull/7").kind == sr.KIND_PULL
        assert sr.parse_source_url(
            "https://github.com/acme/mod").kind == sr.KIND_REPO

    def test_raw_and_api_forms(self):
        raw = sr.parse_source_url(
            "https://raw.githubusercontent.com/acme/mod/main/src/Foo.java")
        assert (raw.ref, raw.path) == ("main", "src/Foo.java")
        api = sr.parse_source_url(
            "https://api.github.com/repos/acme/mod/contents/src/Foo.java"
            "?ref=main")
        assert (api.owner, api.repo, api.ref, api.path) == (
            "acme", "mod", "main", "src/Foo.java")

    def test_foreign_and_lookalike_hosts_are_unsupported(self):
        for url in ("https://gitlab.com/acme/mod/-/blob/main/x.py",
                    "https://github.com.evil.tld/acme/mod/blob/main/x.py",
                    "https://bitbucket.org/acme/mod/src/main/x.py"):
            parsed = sr.parse_source_url(url)
            assert parsed is not None and not parsed.supported, url

    def test_non_url_and_repo_spec(self):
        assert sr.parse_source_url("просто текст") is None
        assert sr.parse_source_url("ftp://github.com/a/b") is None
        assert sr.parse_repo_spec("acme/mod") == ("acme", "mod")
        assert sr.parse_repo_spec("https://github.com/acme/mod.git") == (
            "acme", "mod")


# ── 2. Прямая blob-ссылка → проверенное содержимое (V1) ─────────────────────

class TestVerifiedFetch:
    @pytest.mark.asyncio
    async def test_blob_link_returns_verified_commit_pinned_fragment(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ,
            url=("https://github.com/acme/mod/blob/1.20.1/src/main/java/acme/"
                 "ParallelHatchPartMachine.java#L12-L14"),
            symbol="getParallel", follow=False)
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["verified"] is True
        assert payload["commit"] == COMMIT
        assert payload["path"].endswith("ParallelHatchPartMachine.java")
        assert payload["line_range"] == [12, 14]
        # V1.3: snippet — ТОЧНАЯ подстрока декодированных байт.
        assert payload["snippet"] in FILE_MACHINE
        assert payload["snippet"].startswith("    @Override")
        # V1.4: verified_url привязан к commit, не к ветке.
        assert COMMIT in payload["verified_url"]
        assert "1.20.1" not in payload["verified_url"]
        assert payload["verified_url"].endswith("#L12-L14")
        # provenance — от байтов файла, а не от HTML-страницы.
        assert payload["provenance"]["sha256"] == hashlib.sha256(
            FILE_MACHINE.encode("utf-8")).hexdigest()
        assert payload["provenance"]["endpoint"] in (
            sr.ENDPOINT_CONTENTS, sr.ENDPOINT_BLOBS, sr.ENDPOINT_RAW)
        assert "://" not in json.dumps(payload["provenance"])

    @pytest.mark.asyncio
    async def test_symbol_line_and_exact_substring(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="1.20.1",
            path="src/main/java/acme/ParallelLogic.java", symbol="compute",
            follow=False)
        assert payload["verified"] is True
        assert payload["symbol_found"] is True
        assert payload["line_range"][0] <= 10 <= payload["line_range"][1]
        assert payload["snippet"] in FILE_LOGIC
        assert payload["file_total_lines"] == len(FILE_LOGIC.splitlines())

    @pytest.mark.asyncio
    async def test_server_200_for_another_path_is_not_verified(self):
        """200 с ДРУГИМ путём в ответе — это не наше чтение (V1.1)."""
        # raw тоже 404: единственный источник байт — ответ contents с ЧУЖИМ
        # путём, поэтому подтверждать нечего.
        fake = FakeGitHub(path_mismatch=True, raw_disabled=True)
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelLogic.java", follow=False)
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["verified"] is False
        assert payload["snippet"] == ""
        assert payload["verified_url"] == ""
        assert payload["error"] == sr.ERR_PARSE
        assert payload["error_detail"]["detail"] == "path_mismatch"

    @pytest.mark.asyncio
    async def test_readme_is_read_but_never_verified(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="README.md", follow=False)
        assert payload["status"] == sr.STATUS_OK
        assert payload["source_kind"] == sr.KIND_README
        assert payload["verified"] is False          # V1.5
        assert payload["verified_url"] == ""
        assert payload["snippet"]                     # текст доставлен честно

    @pytest.mark.asyncio
    async def test_commit_pinned_url_skips_branch_resolution(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref=COMMIT,
            path="src/main/java/acme/ParallelLogic.java", follow=False)
        assert payload["verified"] is True
        assert payload["commit"] == COMMIT
        assert not any(call.endswith("/commits") for call in fake.calls)


# ── 3. Discovery: имя репозитория / только описание ────────────────────────

class TestDiscovery:
    @pytest.mark.asyncio
    async def test_repo_name_then_locate_then_verified_read(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo="acme/mod", ref="1.20.1",
            query="parallel hatch machine", symbol="getParallel")
        assert payload["status"] == sr.STATUS_OK
        assert payload["verified"] is True
        assert payload["path"].endswith("ParallelHatchPartMachine.java")
        assert payload["files"][0]["path"].endswith(
            "ParallelHatchPartMachine.java")

    @pytest.mark.asyncio
    async def test_description_only_finds_repository_via_api_search(self):
        item = {"full_name": "acme/mod", "name": "mod",
                "owner": {"login": "acme"}, "default_branch": "main",
                "language": "Java", "stargazers_count": 1200,
                "description": "parallel output helpers",
                "pushed_at": "2026-01-01T00:00:00Z"}
        fake = FakeGitHub(search_items=[item])
        payload = await _reader(fake).run(
            operation=sr.OPERATION_DISCOVER,
            query="parallel output hatch mechanism java")
        assert payload["status"] == sr.STATUS_OK
        assert payload["repo"] == REPO
        assert payload["verified"] is False           # discovery ≠ чтение
        assert payload["read_level"] == "discovered"
        assert payload["candidates"][0]["repo"] == REPO

    @pytest.mark.asyncio
    async def test_two_equally_plausible_repos_ask_one_question(self):
        def item(full, stars=100, desc="parallel output"):
            owner, name = full.split("/")
            return {"full_name": full, "name": name, "owner": {"login": owner},
                    "default_branch": "main", "language": "Java",
                    "stargazers_count": stars, "description": desc,
                    "pushed_at": "2026-01-01T00:00:00Z"}
        fake = FakeGitHub(search_items=[item("acme/mod", 100),
                                        item("acme/modkit", 100)])
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, query="parallel output register")
        assert payload["status"] == sr.STATUS_AMBIGUOUS
        assert payload["needs_choice"] is True
        assert 1 <= len(payload["candidates"]) <= 3
        assert payload["question"].count("?") == 1     # ровно одна развилка
        assert payload["verified"] is False
        assert payload["snippet"] == ""

    @pytest.mark.asyncio
    async def test_empty_search_is_honest_no_relevant_results(self):
        fake = FakeGitHub(search_items=[])
        payload = await _reader(fake).run(
            operation=sr.OPERATION_DISCOVER, query="no such mechanism")
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_NO_RESULTS
        assert payload["network_calls"] >= 1


# ── 4. Follow-up: «класс лишь выставляет параметр» ────────────────────────

class TestFollowUp:
    @pytest.mark.asyncio
    async def test_parameter_only_triggers_chain_and_reports_not_checked(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelConfig.java", symbol="chanceLimit",
            follow=True)
        assert payload["status"] == sr.STATUS_OK
        assert payload["parameter_only"] is True
        assert payload["verified"] is True             # байты реально прочитаны
        # Ложного объяснения поведения по параметру нет: цепочка + not_checked.
        assert "not_checked" in payload
        assert payload["not_checked"]["files_read"] >= 1
        assert payload["followup_incomplete"] is True
        assert payload["not_checked"]["reason"] in (
            "budget", "not_found", "depth_limit", "tree_truncated")
        assert payload["files"][0]["role"] == "primary"

    @pytest.mark.asyncio
    async def test_file_budget_produces_untried_paths(self, monkeypatch):
        monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_FILES", 1)
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelHatchPartMachine.java",
            symbol="getParallel", follow=True)
        assert payload["followup_incomplete"] is True
        assert payload["not_checked"]["reason"] == "budget"
        assert payload["not_checked"]["untried_paths"]
        assert len(payload["files"]) == 1

    @pytest.mark.asyncio
    async def test_depth_limit_is_reported_not_hidden(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelHatchPartMachine.java",
            symbol="getParallel", follow=True)
        # ParallelLogic найден по идентификатору из тела → цепочка прочитана.
        assert len(payload["files"]) >= 2
        assert payload["files"][1]["path"].endswith("ParallelLogic.java")
        assert payload["files"][1]["verified"] is True
        assert payload["not_checked"]["depth_left"] == 0

    @pytest.mark.asyncio
    async def test_tree_failure_does_not_destroy_verified_read(self):
        """Сбой дерева в follow-up → цепочка неполна, но чтение подтверждено."""
        payload = await _reader(FakeGitHub(tree_status=502)).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelHatchPartMachine.java",
            symbol="getParallel", follow=True)
        assert payload["status"] == sr.STATUS_OK
        assert payload["verified"] is True
        assert payload["followup_incomplete"] is True
        assert payload["not_checked"]["reason"] == "tree_unavailable"
        assert payload["files"][0]["role"] == "primary"

    @pytest.mark.asyncio
    async def test_follow_false_keeps_single_file(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelHatchPartMachine.java",
            symbol="getParallel", follow=False)
        assert payload["files"] == []
        assert payload["followup_incomplete"] is False


# ── 5. Честные отказы: 403/404/rate limit/timeout/HTML ────────────────────

class TestHonestFailures:
    @pytest.mark.asyncio
    async def test_404_is_source_missing_without_pseudo_url(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/Missing.java")
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == sr.ERR_SOURCE_MISSING
        assert payload["verified"] is False
        assert payload["verified_url"] == ""
        assert payload["snippet"] == ""

    @pytest.mark.asyncio
    async def test_rate_limit_code_from_headers(self):
        fake = FakeGitHub(status=403, body=b'{"message":"rate"}')
        fake.handler_headers = {"x-ratelimit-remaining": "0"}

        def handler(request):
            fake.calls.append(str(request.url))
            return httpx.Response(403, content=b'{"message":"rate"}',
                                  headers={"x-ratelimit-remaining": "0"},
                                  request=request)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                   follow_redirects=False, timeout=None)
        reader = sr.SourceReader(
            provider=sr.GitHubProvider(sf.SafeFetcher(client=client)))
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   ref="main", path="a/B.java")
        assert payload["error"] == sr.ERR_RATE_LIMIT
        assert payload["error_detail"]["retryable"] is True

    @pytest.mark.asyncio
    async def test_403_without_rate_headers_is_auth_failed(self):
        fake = FakeGitHub(status=403, body=b'{"message":"forbidden"}')
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main", path="a/B.java")
        assert payload["error"] == sr.ERR_AUTH_FAILED
        assert payload["error_detail"]["http"] == 403

    @pytest.mark.asyncio
    async def test_5xx_is_provider_unavailable(self):
        fake = FakeGitHub(status=502, body=b"")
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main", path="a/B.java")
        assert payload["error"] == sr.ERR_PROVIDER_UNAVAILABLE
        assert payload["error_detail"]["retryable"] is True

    @pytest.mark.asyncio
    async def test_html_instead_of_code_is_parse_error(self):
        fake = FakeGitHub(status=200,
                          body=b"<!DOCTYPE html><html>blob page</html>")
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelLogic.java")
        assert payload["error"] == sr.ERR_PARSE
        assert payload["verified"] is False
        assert payload["snippet"] == ""

    @pytest.mark.asyncio
    async def test_unsupported_host_is_provider_unconfigured(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ,
            url="https://gitlab.com/acme/mod/-/blob/main/x.py")
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["error"] == sr.ERR_PROVIDER_UNCONFIGURED
        assert payload["error_detail"]["detail"] == "host_not_supported"
        assert fake.calls == []          # чужой хостинг даже не запрашивается

    @pytest.mark.asyncio
    async def test_ssrf_redirect_to_private_target_is_blocked(self):
        """Редирект в приватную сеть гасится существующим SafeFetcher."""
        fake = FakeGitHub(redirect_to="http://10.1.2.3/internal")
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelLogic.java")
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["error"] == "redirect_blocked"
        assert payload["verified"] is False
        assert payload["snippet"] == ""

    @pytest.mark.asyncio
    async def test_credentialed_link_is_stripped_and_never_reaches_network(self):
        """Креденшелы в ссылке: в запросы/логи/payload они не попадают.

        Пользовательский URL не передаётся транспорту как есть (провайдер
        строит адреса сам), поэтому опасность — именно утечка. Проверяем
        фактические контакты и содержимое payload, а не «отказ»."""
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ,
            url="https://user:pass@github.com/acme/mod/blob/main/"
                "src/main/java/acme/ParallelLogic.java", follow=False)
        hosts = {call.split("/")[0] for call in fake.calls}
        assert hosts <= {"api.github.com", "raw.githubusercontent.com"}
        # Сама ссылка с креденшелами гасится существующим guard'ом SafeFetcher.
        with pytest.raises(sf.SafeFetchError) as exc:
            sf.guarded_target("https://user:pass@github.com/acme/mod")
        assert exc.value.code == "credentials_in_url"
        body = json.dumps(payload, ensure_ascii=False)
        assert "pass@" not in body and "user:" not in body
        assert payload["repo"] == REPO
        assert payload["verified"] in (True, False)   # чтение, не утечка

    @pytest.mark.asyncio
    async def test_missing_identity_arguments(self):
        fake = FakeGitHub()
        payload = await _reader(fake).run(operation=sr.OPERATION_READ)
        assert payload["error"] == sr.ERR_INVALID_URL
        assert payload["error_detail"]["detail"] == "no_url_no_repo_no_query"


# ── 6. Kill-switch, отсутствие лишних вызовов и исполнения кода ───────────

class TestGuards:
    @pytest.mark.asyncio
    async def test_kill_switch_off_hides_tool_and_performs_no_lookup(
            self, monkeypatch):
        monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", False)
        names = [tool["function"]["name"] for tool in tool_schemas.active_tools()]
        assert "read_source_code" not in names
        assert len(names) == len(tool_schemas.TOOL_CALLING_TOOLS) - 3  # img+edit+src
        fake = FakeGitHub()
        router = _router(fake)
        out = json.loads(await router.dispatch(
            "read_source_code", {"operation": "read", "repo": REPO},
            _ctx()))
        assert out["status"] == "disabled" and out["reason"] == "disabled"
        assert fake.calls == []                # ни одного сетевого вызова
        info = tool_result.classify_output("read_source_code", json.dumps(out))
        assert info["status"] == tool_result.STATUS_DENIED
        assert info["error_code"] == "disabled"

    @pytest.mark.asyncio
    async def test_disabled_provider_path_reports_disabled(self, monkeypatch):
        monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", False)
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main", path="a/B.java")
        assert payload["error"] == sr.ERR_DISABLED

    @pytest.mark.asyncio
    async def test_request_budget_fuse_stops_the_lookup(self, monkeypatch):
        monkeypatch.setattr(type(settings), "SOURCE_READ_MAX_REQUESTS", 1)
        fake = FakeGitHub()
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="1.20.1",
            path="src/main/java/acme/ParallelLogic.java")
        assert payload["status"] == sr.STATUS_ERROR
        assert payload["not_checked"]["reason"] == "budget"
        assert len(fake.calls) <= 1

    def test_module_never_executes_downloaded_code(self):
        """Инвариант «скачанный код не исполняется» — по AST, а не по тексту."""
        import ast
        tree = ast.parse(Path(sr.__file__).read_text(encoding="utf-8"))
        banned_modules = {"subprocess", "importlib", "ctypes", "runpy",
                          "pickle", "marshal"}
        banned_calls = {"exec", "eval", "compile", "__import__", "execfile"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned_modules, alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned_modules, node.module
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", "")
                assert name not in banned_calls, name

    @pytest.mark.asyncio
    async def test_payload_never_contains_tokens_or_raw_urls(self, monkeypatch):
        monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN",
                            "ghp_SUPERSECRETTOKEN123")
        provider = sr.GitHubProvider(sf.SafeFetcher(),
                                    token=sr.github_token())
        headers = provider._headers()
        assert headers["Authorization"].endswith("ghp_SUPERSECRETTOKEN123")
        # Токен живёт только в заголовке: ни payload, ни provenance его не несут.
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="1.20.1",
            path="src/main/java/acme/ParallelLogic.java", follow=False)
        body = json.dumps(payload, ensure_ascii=False)
        assert "ghp_SUPERSECRETTOKEN123" not in body
        assert "Authorization" not in body
        assert "://" not in json.dumps(payload["provenance"])


# ── 7. Reuse: те же байты без сети, смена версии — новый fetch ────────────

class TestQualifiedReuse:
    @pytest.mark.asyncio
    async def test_second_read_of_same_identity_reuses_without_network(self):
        fake = FakeGitHub()
        router = _router(fake)
        args = {"operation": "read", "repo": REPO, "ref": "1.20.1",
                "path": "src/main/java/acme/ParallelLogic.java",
                "claim": {"entity": "parallel output", "relation": "spec",
                          "version": "1.20.1"}}
        ctx = _ctx()
        first = json.loads(await router.dispatch("read_source_code", args, ctx))
        assert first["verified"] is True and first["reused"] is False
        calls_after_first = len(fake.calls)
        second = json.loads(await router.dispatch("read_source_code", args,
                                                  _ctx()))
        assert second["reused"] is True
        assert second["network_calls"] == 0
        assert second["snippet"] == first["snippet"]
        assert second["line_range"] == first["line_range"]
        assert len(fake.calls) == calls_after_first      # ни одного нового вызова

    @pytest.mark.asyncio
    async def test_reuse_by_link_with_other_ref_fetches(self):
        """Тот же claim, две ссылки с разным ref → второй вызов читает заново."""
        fake = FakeGitHub()
        router = _router(fake)
        claim = {"entity": "parallel output", "relation": "spec",
                 "version": "1.20.1"}
        first = json.loads(await router.dispatch(
            "read_source_code",
            {"operation": "read", "claim": claim,
             "url": ("https://github.com/acme/mod/blob/1.20.1/src/main/java/"
                     "acme/ParallelLogic.java")}, _ctx()))
        assert first["status"] == "ok" and first["verified"] is True
        assert first["ref"] == "1.20.1"
        second = json.loads(await router.dispatch(
            "read_source_code",
            {"operation": "read", "claim": claim,
             "url": ("https://github.com/acme/mod/blob/main/src/main/java/"
                     "acme/ParallelLogic.java")}, _ctx()))
        assert second["reused"] is False          # чужая версия не переиспользована
        assert second["ref"] == "main"
        assert second["network_calls"] > 0

    @pytest.mark.asyncio
    async def test_reuse_by_link_to_other_file_fetches(self):
        """Тот же claim, ссылка на ДРУГОЙ файл → отдаётся запрошенный файл."""
        fake = FakeGitHub()
        router = _router(fake)
        claim = {"entity": "parallel output", "relation": "spec"}
        base = "https://github.com/acme/mod/blob/main/src/main/java/acme/"
        first = json.loads(await router.dispatch(
            "read_source_code",
            {"operation": "read", "claim": claim, "url": base + "ParallelLogic.java"},
            _ctx()))
        assert first["path"].endswith("ParallelLogic.java")
        second = json.loads(await router.dispatch(
            "read_source_code",
            {"operation": "read", "claim": claim, "url": base + "ParallelConfig.java"},
            _ctx()))
        assert second["reused"] is False
        assert second["path"].endswith("ParallelConfig.java")
        assert "chanceLimit" in second["snippet"]

    @pytest.mark.asyncio
    async def test_reuse_same_link_with_branch_slash_reuses(self):
        """Ветка со слэшем: повторная та же ссылка = reuse, без сети."""
        fake = FakeGitHub()
        router = _router(fake)
        claim = {"entity": "parallel output", "relation": "spec"}
        url = ("https://github.com/acme/mod/blob/feature/x/src/main/java/acme/"
               "ParallelLogic.java")
        first = json.loads(await router.dispatch(
            "read_source_code", {"operation": "read", "claim": claim,
                                 "url": url}, _ctx()))
        assert first["verified"] is True
        assert first["path"].endswith("ParallelLogic.java")
        # ref показывается тот, к которому чтение реально привязано.
        assert first["ref"] == "feature/x"
        calls = len(fake.calls)
        again = json.loads(await router.dispatch(
            "read_source_code", {"operation": "read", "claim": claim,
                                 "url": url}, _ctx()))
        assert again["reused"] is True
        assert again["network_calls"] == 0
        assert len(fake.calls) == calls

    @pytest.mark.asyncio
    async def test_reuse_refuses_file_read_for_another_symbol(self):
        """R-1: запрос другого символа без path не получает чужой файл.

        Фрагмент окна привязан к символу: отдать ранее прочитанный файл с
        `verified=true` и `symbol_found=true` про ДРУГОЙ символ нельзя — либо
        реальное чтение, либо честное «не найдено»."""
        fake = FakeGitHub()
        router = _router(fake)
        claim = {"entity": "parallel output", "relation": "spec"}
        first = json.loads(await router.dispatch(
            "read_source_code",
            {"operation": "read", "claim": claim, "repo": REPO, "ref": "main",
             "path": "src/main/java/acme/ParallelLogic.java",
             "symbol": "compute", "follow": False}, _ctx()))
        assert first["verified"] is True
        assert first["symbol"] == "compute" and first["symbol_found"] is True
        # Тот же claim и repo, но ДРУГОЙ символ и без path/ref.
        second = json.loads(await router.dispatch(
            "read_source_code",
            {"operation": "read", "claim": claim, "repo": REPO,
             "symbol": "chanceLimit", "follow": False}, _ctx()))
        assert second["reused"] is False
        # Никакого подтверждения про чужой символ: либо честный отказ, либо
        # чтение, где символ — именно запрошенный.
        assert not (second["symbol"] == "compute"
                    and second["symbol_found"] is True)
        if second["verified"]:
            assert second["symbol"] == "chanceLimit"
        else:
            assert second["status"] in ("not_found", "error", "unsupported")
            assert second["verified_url"] == ""

    @pytest.mark.asyncio
    async def test_reuse_keeps_honest_truncation_metadata(self):
        """Повторное чтение большого файла: те же обрезка/остаток/строки (B3)."""
        body = "\n".join(f"int field{i} = {i};" for i in range(1, 1201)) + "\n"
        fake = FakeGitHub(files={"src/main/java/acme/Huge.java": body})
        router = _router(fake)
        args = {"operation": "read", "repo": REPO, "ref": "main",
                "path": "src/main/java/acme/Huge.java", "follow": False,
                "claim": {"entity": "huge file", "relation": "spec"}}
        ctx = _ctx()
        ctx.evidence_budget_chars = 8000
        first = json.loads(await router.dispatch("read_source_code", args, ctx))
        assert first["truncation"]["truncated"] is True
        assert first["truncation"]["retrievable_remainder_lines"] > 0
        first_chars = first["snippet_chars"]
        first_range = list(first["line_range"])
        second = json.loads(await router.dispatch("read_source_code", args, _ctx()))
        assert second["reused"] is True
        assert second["network_calls"] == 0
        # Тот же доставленный фрагмент и та же ЧЕСТНАЯ обрезка.
        assert second["snippet_chars"] == first_chars
        assert second["snippet"] == first["snippet"]
        assert second["line_range"] == first_range
        assert second["truncation"]["truncated"] is True
        assert second["truncation"]["retrievable_remainder_lines"] == \
            first["truncation"]["retrievable_remainder_lines"]

    @pytest.mark.asyncio
    async def test_changed_ref_forces_new_fetch(self):
        fake = FakeGitHub()
        router = _router(fake)
        base = {"operation": "read", "repo": REPO,
                "path": "src/main/java/acme/ParallelLogic.java",
                "claim": {"entity": "parallel output", "relation": "spec",
                          "version": "1.20.1"}}
        first = json.loads(await router.dispatch(
            "read_source_code", dict(base, ref="1.20.1"), _ctx()))
        assert first["reused"] is False
        second = json.loads(await router.dispatch(
            "read_source_code", dict(base, ref="main"), _ctx()))
        # Другая версия/ветка — старое доказательство НЕ переиспользуется.
        assert second["reused"] is False
        assert second["ref"] == "main"
        assert any(call.endswith("/commits") for call in fake.calls)

    @pytest.mark.asyncio
    async def test_changed_commit_forces_new_fetch(self):
        fake = FakeGitHub()
        router = _router(fake)
        base = {"operation": "read", "repo": REPO,
                "path": "src/main/java/acme/ParallelLogic.java",
                "claim": {"entity": "parallel output", "relation": "spec",
                          "version": "1.20.1"}}
        await router.dispatch("read_source_code", dict(base, ref=COMMIT), _ctx())
        second = json.loads(await router.dispatch(
            "read_source_code", dict(base, ref=OTHER_COMMIT), _ctx()))
        assert second["reused"] is False
        assert second["commit"] != COMMIT or second["status"] == "error"

    @pytest.mark.asyncio
    async def test_token_scope_is_chat_isolated(self, monkeypatch):
        monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN",
                            "ghp_token_for_private_access")
        fake = FakeGitHub()
        reader = _reader(fake)
        router = ToolRouter(ToolDeps(None, None, source_reader=reader))
        args = {"operation": "read", "repo": REPO, "ref": "1.20.1",
                "path": "src/main/java/acme/ParallelLogic.java",
                "claim": {"entity": "parallel output", "relation": "spec"}}
        first = json.loads(await router.dispatch(
            "read_source_code", args, ToolContext(111, "q")))
        assert first["reused"] is False
        # Другой чат: приватный (авторизованный) источник не переиспользуется.
        other = json.loads(await router.dispatch(
            "read_source_code", args, ToolContext(222, "q")))
        assert other["reused"] is False
        assert other["network_calls"] > 0
        # Тот же чат — reuse разрешён.
        again = json.loads(await router.dispatch(
            "read_source_code", args, ToolContext(111, "q")))
        assert again["reused"] is True
        assert again["network_calls"] == 0

    @pytest.mark.asyncio
    async def test_reuse_never_claims_verified_without_stored_bytes(self):
        """Запись без реальных байт (нет sha256/commit) не отдаётся как proof."""
        reader = _reader(FakeGitHub())
        key = source_reuse.claim_key("acme", "spec", "1.20.1")
        source_reuse.store(key, url="https://github.com/acme/mod/blob/x/y",
                           source_id="deadbeef", snippet="junk",
                           read_level=source_reuse.READ_LEVEL_SELECTED,
                           scope="public", chat_id=None,
                           full_source_pointer={"repo": REPO, "ref": "1.20.1",
                                                "path": "a/B.java"})
        payload = ToolRouter(ToolDeps(None, None, source_reader=reader)) \
            ._source_reuse_payload(reader, [key],
                                   identity={"repo": REPO, "ref": "1.20.1",
                                             "path": "a/B.java", "symbol": "",
                                             "operation": "read"},
                                   scope="public", chat_id=None,
                                   operation="read")
        assert payload is None


# ── 3b. B1: байтовые семантики (CRLF, не-UTF-8, бинарь, кириллица) ────────

class TestByteSemantics:
    @pytest.mark.asyncio
    async def test_crlf_file_verifies_and_snippet_is_exact_substring(self):
        """CRLF-исходник: `verified=true`, фрагмент — точные байты файла."""
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="1.20.1",
            path="src/main/java/acme/CrlfLogic.java", symbol="compute",
            follow=False)
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["verified"] is True
        # Фрагмент сохраняет реальные переводы строк файла и совпадает
        # ПОСТРОЧНО с диапазоном line_range (иное означало бы сдвиг смещений).
        assert "\r\n" in payload["snippet"]
        assert payload["snippet"] in FILE_CRLF
        # Строки CRLF-файла уже содержат свой "\r", поэтому склейка идёт
        # через "\n" и воспроизводит реальные "\r\n" файла.
        lines = sr.split_lines(FILE_CRLF)
        start, end = payload["line_range"]
        assert payload["snippet"] == "\n".join(lines[start - 1:end])
        assert lines[start - 1].endswith("\r")
        assert payload["file_total_lines"] == len(sr.split_lines(FILE_CRLF))
        # Номера строк считаются по реальному файлу: `compute` — 10-я строка.
        assert payload["symbol_found"] is True
        assert payload["line_range"][0] <= 10 <= payload["line_range"][1]
        assert payload["verified_url"].startswith(
            f"https://github.com/{REPO}/blob/{COMMIT}/")

    @pytest.mark.asyncio
    async def test_utf8_cyrillic_file_verifies_with_correct_lines(self):
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelLimit.java", symbol="compute",
            follow=False)
        assert payload["status"] == sr.STATUS_OK
        assert payload["verified"] is True
        assert "Параллельный выход" in payload["snippet"]
        assert payload["snippet"] in FILE_CYRILLIC
        cyrillic_lines = sr.split_lines(FILE_CYRILLIC)
        start, end = payload["line_range"]
        assert payload["snippet"] == "\n".join(cyrillic_lines[start - 1:end])
        assert payload["symbol_found"] is True
        assert payload["file_total_lines"] == len(sr.split_lines(FILE_CYRILLIC))

    @pytest.mark.asyncio
    async def test_binary_file_never_verifies(self):
        """PNG-байты с NUL не могут стать «проверенным исходником»."""
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="assets/logo.bin", follow=False)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["verified"] is False
        assert payload["verified_url"] == ""
        assert payload["snippet"] == ""
        assert payload["reason"] == "binary_content"
        assert payload["not_checked"]["files_read"] == 1

    @pytest.mark.asyncio
    async def test_invalid_utf8_is_not_source(self):
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/Legacy.java", follow=False)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["verified"] is False
        assert payload["reason"] == "invalid_encoding"

    @pytest.mark.asyncio
    async def test_empty_file_is_not_missing(self):
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/Empty.java", follow=False)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["reason"] == "empty_content"
        assert payload["verified"] is False
        assert payload["path"] == "src/main/java/acme/Empty.java"

    @pytest.mark.asyncio
    async def test_directory_path_is_directory_not_missing(self):
        fake = FakeGitHub(directories=("src/main/java/acme",))
        payload = await _reader(fake).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme", follow=False)
        assert payload["status"] == sr.STATUS_UNSUPPORTED
        assert payload["reason"] == "path_is_directory"
        assert payload["source_kind"] == sr.KIND_DIRECTORY
        assert payload["verified"] is False

    def test_decode_rule_is_strict(self):
        """Правило декодирования: UTF-8 strict, без latin-1-отката, без NUL."""
        assert sr.decode_source_bytes("код".encode("utf-8")).ok is True
        assert sr.decode_source_bytes(b"a\r\nb\r\n").text == "a\r\nb\r\n"
        bad = sr.decode_source_bytes(b"\xff\xfe\xfd")
        assert bad.ok is False and bad.reason == "invalid_encoding"
        # NUL в сырых байтах — бинарь, даже если кодировка «не читается».
        assert sr.decode_source_bytes(b"\xff\x00").reason == "binary_content"
        binary = sr.decode_source_bytes(b"MZ\x00\x01\x02")
        assert binary.ok is False and binary.reason == "binary_content"
        assert sr.decode_source_bytes(b"").reason == "empty_content"
        # Строки: разделитель только \n, CR сохраняется, хвостовой \n не строка.
        assert sr.split_lines("a\r\nb\r\n") == ["a\r", "b\r"]
        assert sr.split_lines("a\nb") == ["a", "b"]


# ── 4b. Доказательность payload (§1.4): без выдуманной хронологии ─────────

class TestEvidenceHonesty:
    @pytest.mark.asyncio
    async def test_payload_never_carries_chat_chronology_or_quotes(self):
        """§1.4.1/§1.5.6: инструмент не синтезирует реплики/даты/цитаты."""
        payload = await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="1.20.1",
            path="src/main/java/acme/ParallelLogic.java", follow=False)
        banned = {"messages", "chat_history", "message_id", "quote",
                  "quoted_text", "author", "author_name", "sender",
                  "reply_to", "published_at", "date", "yesterday"}
        assert not (banned & set(payload))
        # Единственная временная метка — техническая метка получения байт.
        assert set(payload["provenance"]) == {
            "provider", "endpoint", "fetched_at", "bytes", "sha256",
            "read_level", "network_calls"}
        assert isinstance(payload["provenance"]["fetched_at"], int)

    @pytest.mark.asyncio
    async def test_not_checked_block_is_present_in_every_status(self):
        """«Что НЕ проверено» присутствует всегда — включая отказы."""
        cases = [
            (dict(operation="read", repo=REPO, ref="1.20.1",
                  path="src/main/java/acme/ParallelLogic.java"), sr.STATUS_OK),
            (dict(operation="read", repo=REPO, ref="main",
                  path="src/main/java/acme/Missing.java"), sr.STATUS_ERROR),
            (dict(operation="read",
                  url="https://gitlab.com/acme/mod/-/blob/main/x.py"),
             sr.STATUS_UNSUPPORTED),
        ]
        for kwargs, expected in cases:
            payload = await _reader(FakeGitHub()).run(**kwargs)
            assert payload["status"] == expected, kwargs
            assert isinstance(payload.get("not_checked"), dict)
            assert "files_read" in payload["not_checked"]


# ── 8. Окно evidence: без новых потолков 4000/8000 ────────────────────────
class TestEvidenceWindow:
    @pytest.mark.asyncio
    async def test_big_file_is_cut_by_dynamic_window_not_by_4000(self):
        body = "\n".join(f"int field{i} = {i};" for i in range(1, 2001)) + "\n"
        files = {"src/main/java/acme/Huge.java": body}
        fake = FakeGitHub(files=files)
        reader = _reader(fake)
        window_budget = 5000
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/Huge.java", budget_chars=window_budget,
            follow=False)
        assert payload["verified"] is True
        assert payload["truncation"]["truncated"] is True
        assert payload["truncation"]["why"] == "over_window"
        assert payload["truncation"]["effective_limit"] == window_budget
        assert payload["truncation"]["limit_source"] == "evidence_window"
        assert payload["truncation"]["retrievable_remainder_lines"] > 0
        assert payload["snippet"] in body
        assert payload["read_level"] == "selected"

    @pytest.mark.asyncio
    async def test_window_comes_from_tool_context_budget(self):
        """Инструмент берёт окно из существующего `evidence_budget_chars`."""
        fake = FakeGitHub()
        ctx = _ctx()
        ctx.evidence_budget_chars = 1500
        router = _router(fake)
        out = json.loads(await router.dispatch(
            "read_source_code",
            {"operation": "read", "repo": REPO, "ref": "1.20.1",
             "path": "src/main/java/acme/ParallelHatchPartMachine.java",
             "follow": False}, ctx))
        assert out["status"] == "ok"
        limit = out["truncation"]["effective_limit"]
        # Окно считается существующим `auto_budget` (бюджет композера × grow),
        # а НЕ новым потолком: значение в порядке величины бюджета, не 8000.
        assert 0 < limit <= 8000
        assert limit != 8000
        assert limit <= 1500 * 2
        assert ctx.evidence_limits[-1]["effective_limit"] == limit
        assert ctx.evidence_limits[-1]["limit_source"] == "call_budget"
        assert ctx.evidence_limits[-1]["tool"] == "read_source_code"
        assert ctx.evidence_limits[-1]["source_read_level"] in (
            "selected", "parsed")


# ── 8b. Исходящий сигнал §2 и закрытый словарь кодов (N1/N3) ──────────────

class TestOutboundSignal:
    @pytest.mark.asyncio
    async def test_fetch_failure_sets_out_of_band_signal(self):
        """§2: SafeFetchError-код/стадия/retryable → out-of-band сигнал."""
        ctx = _ctx()
        out = await _router(FakeGitHub(status=404, body=b"")).dispatch(
            "read_source_code",
            {"operation": "read", "repo": REPO, "ref": "1.20.1",
             "path": "src/main/java/acme/Missing.java"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["error"] == sr.ERR_SOURCE_MISSING
        signal = tool_result.take_signal(ctx)
        assert isinstance(signal, dict), signal
        assert signal["error_code"] == sr.ERR_SOURCE_MISSING
        assert signal["retryable"] is False
        assert signal["stage"] in sr.STAGES

    @pytest.mark.asyncio
    async def test_provider_5xx_signal_is_retryable(self):
        ctx = _ctx()
        await _router(FakeGitHub(status=502, body=b"")).dispatch(
            "read_source_code",
            {"operation": "read", "repo": REPO, "ref": "main",
             "path": "a/B.java"}, ctx)
        signal = tool_result.take_signal(ctx)
        assert signal["error_code"] == sr.ERR_PROVIDER_UNAVAILABLE
        assert signal["retryable"] is True

    def test_every_mapped_reason_code_exists_in_dictionary(self):
        """N3: ни один payload-код не отображается в несуществующий код."""
        unknown = {payload_code: reason
                   for payload_code, reason in sr._REASON_FOR_CODE.items()
                   if reason not in mca_events.REASON_CODES}
        assert unknown == {}
        assert sr.ERR_UNSUPPORTED_KIND in sr._REASON_FOR_CODE


# ── 9. Телеметрия: стадии различимы, коды — существующие ──────────────────

class TestTelemetry:
    @pytest.mark.asyncio
    async def test_stage_events_use_existing_reason_codes(self, monkeypatch):
        events: list[dict] = []
        import services.mca_retrieval_context as mrc

        def fake_emit(stage, outcome, *, level=None, **fields):
            events.append({"stage": stage, "outcome": outcome, **fields})
            return None
        monkeypatch.setattr(mrc, "emit_stage_event", fake_emit)
        await _reader(FakeGitHub()).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="1.20.1",
            path="src/main/java/acme/ParallelLogic.java", follow=False)
        stages = {event["stage"] for event in events}
        assert "source_discover" in stages
        assert "source_fetch" in stages
        for event in events:
            code = event.get("reason_code")
            assert code is None or code in mca_events.REASON_CODES, code
            # R17: в событии нет URL/текста кода.
            blob = json.dumps(event, ensure_ascii=False)
            assert "://" not in blob

    @pytest.mark.asyncio
    async def test_failure_event_carries_closed_code(self, monkeypatch):
        events: list[dict] = []
        import services.mca_retrieval_context as mrc
        monkeypatch.setattr(
            mrc, "emit_stage_event",
            lambda stage, outcome, **fields: events.append(
                {"stage": stage, "outcome": outcome, **fields}))
        await _reader(FakeGitHub(status=404, body=b"")).run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main", path="a/B.java")
        codes = [event.get("reason_code") for event in events]
        assert "source_missing" in codes
        assert all(code is None or code in mca_events.REASON_CODES
                   for code in codes)


# ── 10. Evidence policy: capability reachable ТОЛЬКО через существующую цепь

class TestEvidencePolicyChain:
    def test_source_read_is_mapped_to_capability_registry(self):
        assert dcs._EVIDENCE_CAP_REGISTRY["source_read"] == "source_read"
        assert evp.CAPABILITY_SOURCE_READ == "source_read"
        # Мёртвый флаг «ещё не реализовано» снят вместе с реализацией.
        assert not hasattr(evp, "_SOURCE_READER_READY")

    @pytest.mark.asyncio
    async def test_allowed_grants_source_read_when_tool_is_ready(self):
        caps._CACHE.clear()
        ctx = await dcs._evidence_context(-100500, ("source_read",))
        ok, code = evp.allowed("source_read", ctx)
        assert ok is True and code == ""

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_through_the_same_chain(self, monkeypatch):
        monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", False)
        caps._CACHE.clear()
        ctx = await dcs._evidence_context(-100500, ("source_read",))
        ok, code = evp.allowed("source_read", ctx)
        assert ok is False
        assert code == evp.BLOCK_EXTERNAL_DISABLED

    @pytest.mark.asyncio
    async def test_ssrf_and_privacy_still_deny(self):
        caps._CACHE.clear()
        ctx = await dcs._evidence_context(-100500, ("source_read",))
        blocked = evp.EvidenceContext(
            capabilities=dict(ctx.capabilities), ssrf_ok={"source_read": False})
        ok, code = evp.allowed("source_read", blocked)
        assert (ok, code) == (False, evp.BLOCK_SSRF)
        forbidding = evp.EvidenceContext(
            capabilities=dict(ctx.capabilities), user_forbids_external=True)
        assert evp.allowed("source_read", forbidding) == (
            False, evp.BLOCK_EXTERNAL_DISABLED)
        no_rbac = evp.EvidenceContext(capabilities=dict(ctx.capabilities),
                                      rbac_ok=False)
        assert evp.allowed("source_read", no_rbac) == (False, evp.BLOCK_RBAC)

    def test_explicit_read_source_request_requires_the_capability(self):
        decision = evp.evaluate_evidence_need(
            plan=None, task_kind="question",
            explicit=evp.ExplicitRequest(read_source=True))
        assert decision.required is True
        assert decision.required_caps == (evp.CAPABILITY_SOURCE_READ,)
        assert decision.source_kind == "source_code"


# ── 11. Конвейер ToolResult: статусы без новых кодов ─────────────────────

class TestToolResultMapping:
    @pytest.mark.asyncio
    async def test_ok_status_maps_to_tool_result_ok(self):
        out = await _router(FakeGitHub()).dispatch(
            "read_source_code",
            {"operation": "read", "repo": REPO, "ref": "1.20.1",
             "path": "src/main/java/acme/ParallelLogic.java", "follow": False},
            _ctx())
        info = tool_result.classify_output("read_source_code", out)
        assert info["status"] == tool_result.STATUS_OK
        assert info["data"]["verified"] is True

    @pytest.mark.asyncio
    async def test_not_found_maps_to_empty(self):
        out = await _router(FakeGitHub()).dispatch(
            "read_source_code",
            {"operation": "read", "repo": REPO, "ref": "main",
             "path": "src/main/java/acme/Nope.java"}, _ctx())
        info = tool_result.classify_output("read_source_code", out)
        assert info["status"] in (tool_result.STATUS_ERROR,
                                  tool_result.STATUS_EMPTY)

    @pytest.mark.asyncio
    async def test_error_maps_to_error_with_closed_code(self):
        out = await _router(FakeGitHub(status=500, body=b"")).dispatch(
            "read_source_code",
            {"operation": "read", "repo": REPO, "ref": "main", "path": "a/B.java"},
            _ctx())
        info = tool_result.classify_output("read_source_code", out)
        assert info["status"] == tool_result.STATUS_ERROR
        assert info["error_code"] == sr.ERR_PROVIDER_UNAVAILABLE
        assert info["retryable"] is True

    @pytest.mark.asyncio
    async def test_invalid_operation_is_rejected_before_network(self):
        fake = FakeGitHub()
        out = json.loads(await _router(fake).dispatch(
            "read_source_code", {"operation": "delete", "repo": REPO}, _ctx()))
        assert out["error"] == "invalid_arguments"
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_invalid_line_range_is_rejected(self):
        fake = FakeGitHub()
        out = json.loads(await _router(fake).dispatch(
            "read_source_code",
            {"operation": "read", "repo": REPO, "line_start": 0}, _ctx()))
        assert out["reason"] == "invalid_line_range"


# ── 12. Канон инструментов и объявление ──────────────────────────────────

class TestToolCanon:
    def test_canon_is_16_and_new_tool_is_last(self):
        # SELF-DIAG-01 D3: канон 16 → 17 (+inspect_runtime в хвост);
        # D5/D6: → 18 (+prompt_readback в хвост). read_source_code остаётся
        # 16-й записью (индекс 15), существующие схемы байт-в-байт.
        assert len(tool_schemas.TOOL_CALLING_TOOLS) == 18
        assert tool_schemas.TOOL_CALLING_TOOLS[15] is \
            tool_schemas.TOOL_READ_SOURCE_CODE
        assert tool_schemas.TOOL_CALLING_TOOLS[-2] is \
            tool_schemas.TOOL_INSPECT_RUNTIME
        assert tool_schemas.TOOL_CALLING_TOOLS[-1]["function"]["name"] == \
            "prompt_readback"
        assert tool_schemas.TOOL_READ_SOURCE_CODE["function"]["name"] == \
            "read_source_code"

    def test_schema_is_strict_and_operation_only_required(self):
        params = tool_schemas.TOOL_READ_SOURCE_CODE["function"]["parameters"]
        assert params["additionalProperties"] is False
        assert params["required"] == ["operation"]
        assert params["properties"]["operation"]["enum"] == [
            "discover", "locate", "read"]
        for name in ("url", "repo", "query", "ref", "path", "symbol",
                     "line_start", "line_end", "follow", "language"):
            assert name in params["properties"], name

    def test_announcement_gate_is_the_env_kill_switch(self):
        assert tool_schemas.read_source_code_enabled() is True
        names = [tool["function"]["name"] for tool in tool_schemas.active_tools()]
        assert "read_source_code" in names

    def test_metered_and_read_only_evidence_classification(self):
        from services import tool_loop
        assert "read_source_code" in tool_loop.METERED_TOOLS
        # ER-08: read-only проверка не режется «денежным» счётчиком.
        assert "read_source_code" in tool_loop.METERED_EVIDENCE_READ_ONLY
        assert tool_loop.cost_limited_tool("read_source_code") is False

    def test_capability_resolves_ready(self):
        import asyncio
        state = asyncio.run(caps.resolve("source_read", 1, use_cache=False))
        assert state.status == caps.STATUS_READY
        assert state.tool_name == "read_source_code"


class TestPinnedTransport:
    """Транспорт GitHub-провайдера: TCP — на валидированный IP, vhost — в Host.

    Контракт 2.58.200 (причина production-отказа SafeFetch): имя не резолвится
    транспортом повторно, поэтому ротация A-записей не может дать peer вне
    набора, проверенного SSRF-политикой для этой попытки.
    """

    @pytest.mark.asyncio
    async def test_read_connects_to_validated_ip_and_keeps_vhost(self):
        fake = FakeGitHub()
        inner = fake.handler
        seen: list[tuple[str, str, str]] = []

        def handler(request):
            seen.append((request.url.host,
                         str(request.headers.get("host", "")),
                         str(request.extensions.get("sni_hostname", ""))))
            return inner(request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                   follow_redirects=False, timeout=None)
        reader = sr.SourceReader(
            provider=sr.GitHubProvider(sf.SafeFetcher(client=client)))
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelLogic.java")
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["verified"] is True
        assert seen
        assert {host for host, _, _ in seen} == {PUBLIC_IP}
        assert {vhost for _, vhost, _ in seen} == {"api.github.com"}
        assert {sni for _, _, sni in seen} == {"api.github.com"}

    @pytest.mark.asyncio
    async def test_rate_limit_stays_honest_with_pinned_transport(self):
        def handler(request):
            return httpx.Response(403, content=b'{"message":"rate"}',
                                  headers={"x-ratelimit-remaining": "0"},
                                  request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                   follow_redirects=False, timeout=None)
        reader = sr.SourceReader(
            provider=sr.GitHubProvider(sf.SafeFetcher(client=client)))
        payload = await reader.run(
            operation=sr.OPERATION_READ, repo=REPO, ref="main",
            path="src/main/java/acme/ParallelLogic.java")
        assert payload["error"] == sr.ERR_RATE_LIMIT
        assert payload["verified"] is False
        assert payload["error_detail"]["retryable"] is True
