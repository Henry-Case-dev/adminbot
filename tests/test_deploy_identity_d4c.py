"""D4-C: корреляция traceback с deployed SHA (``SD1-D4-10`` / ``SD1-D4-14``).

Контракт: ``plans/owner_inputs/2026-11-09-self-diag-01.md`` строки 131 и 334,
``architecture-d4-identity.md`` §4.2.

Тесты герметичны: ``tmp_path``, локальный ``git init`` без сети, никакого
прод-манифеста, БД и реального деплоя. Traceback и коммиты — фикстуры.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from config.settings import APP_VERSION
from services import deploy_identity as di

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(
    GIT is None, reason="git binary is not available")


# ── фикстуры ──────────────────────────────────────────────────────────────

def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True, timeout=30)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_repo(tmp_path, *, previous=True, undeployed=True):
    """Release A -> release B (deployed) -> неразвёрнутый C (в ref)."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "D4C Tests")
    (root / "services").mkdir()

    voice = root / "services" / "voice.py"
    router = root / "services" / "router.py"
    voice.write_text("def handle_voice():\n    return 1\n", encoding="utf-8")
    router.write_text(
        "from services.voice import handle_voice\n\n\n"
        "def route(update):\n    return handle_voice()\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "release A")
    sha_a = _git(root, "rev-parse", "HEAD").stdout.strip()

    voice.write_text(
        "def handle_voice():\n    raise RuntimeError('boom')\n",
        encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "release B: voice raises")
    sha_b = _git(root, "rev-parse", "HEAD").stdout.strip()

    sha_c = None
    if undeployed:
        voice.write_text(
            "def handle_voice():\n    raise RuntimeError('boom-next')\n",
            encoding="utf-8")
        (root / "services" / "router.py").write_text(
            "from services.voice import handle_voice\n\n\n"
            "def route(update, ctx=None):\n    return handle_voice()\n",
            encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "undeployed C: voice message")
        sha_c = _git(root, "rev-parse", "HEAD").stdout.strip()
        # C существует в репозитории, но VPS исполняет B: checkout откатываем
        # на B, а C оставляем доступным как upstream-ref (реальный случай
        # «git pull сделан, процесс ещё не перезапущен»).
        _git(root, "update-ref", "refs/remotes/origin/main", sha_c)
        _git(root, "reset", "-q", "--hard", sha_b)
    if not previous:
        sha_a = None

    (root / ".deploy").mkdir()
    (root / ".deploy" / "release.json").write_text(json.dumps({
        "schema": 1,
        "deployed_sha": sha_b,
        "release_branch": "main",
        "version": APP_VERSION,
        "deployed_at": _iso(_now() - timedelta(minutes=5)),
        "effect": "deploy",
        "previous_sha": sha_a,
        "previous_version": "2.58.196",
        "dirty_tracked": False,
    }), encoding="utf-8")
    return {"root": root, "a": sha_a, "b": sha_b, "c": sha_c,
            "voice": voice, "router": router}


def _frame(path, line, function, source=""):
    text = (f'  File "{path}", line {line}, in {function}\n')
    if source:
        text += f"    {source}\n"
    return text


def _traceback_text(repo, *, message="boom", line=2, external=False,
                    extra_frames=()):
    root = repo["root"]
    parts = ["Traceback (most recent call last):\n"]
    if external:
        parts.append(_frame("/usr/lib/python3.12/json/decoder.py", 355,
                            "raw_decode", "obj, end = self.scan_once(s, idx)"))
    for path, number, function in extra_frames:
        parts.append(_frame(path, number, function))
    parts.append(_frame(root / "services" / "router.py", 5, "route",
                        "return handle_voice()"))
    parts.append(_frame(root / "services" / "voice.py", line, "handle_voice",
                        f"raise RuntimeError('{message}')"))
    parts.append(f"RuntimeError: {message}\n")
    return "".join(parts)


class _Status:
    def __init__(self, started_at):
        self.started_at = started_at


def _verified_identity(repo):
    started_at = _now() - timedelta(minutes=1)
    record = di.collect_identity(repo["root"],
                                process_started_at=started_at)
    assert record["code"] == "verified_deployed", record
    return record


def _event_after_release() -> str:
    return _iso(_now() - timedelta(minutes=3))


# ── 1. deployed изменение — кандидат, неразвёрнутый коммит — нет ─────────

@requires_git
def test_deployed_change_is_candidate_and_undeployed_is_excluded(tmp_path):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_event_after_release(), identity=identity)

    assert result["status"] == "ok", result
    assert result["reason"] == ""
    assert result["release"]["verification"] == "verified_deployed"
    assert result["release"]["deployed_sha"] == repo["b"]
    assert result["release"]["basis"] == "release_diff"
    assert result["release"]["deployed_at"]
    assert result["event"]["parsed"] is True
    assert result["event"]["relation"] == "event_after_release"

    # Изменение релиза, затронувшее отвечающий файл, — кандидат.
    candidate_shas = [item["sha"] for item in result["candidates"]]
    assert candidate_shas == [repo["b"]]
    assert result["candidates"][0]["deployed"] is True
    assert result["candidates"][0]["in_release"] is True
    assert result["blame"]["verdict"] == "release_change_suspect"

    # Неразвёрнутый C — виден, но excluded и НЕ обвиняется.
    excluded_shas = {item["sha"] for item in result["excluded"]}
    assert repo["c"] in excluded_shas
    assert repo["c"] not in candidate_shas
    assert all(item["deployed"] is False for item in result["excluded"])
    assert {item["reason"] for item in result["excluded"]} == {
        "undeployed_commit"}
    assert result["blame"]["newest_commit"] == repo["c"]
    assert result["blame"]["newest_deployed"] is False
    assert result["blame"]["newest_blamed"] is False
    assert result["blame"]["newest_reason"] == "recency_is_not_evidence"


@requires_git
def test_checkout_at_deployed_sha_is_verified_ok(tmp_path):
    repo = _build_repo(tmp_path, undeployed=False)
    identity = _verified_identity(repo)
    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_event_after_release(), identity=identity)
    assert result["status"] == "ok", result
    assert result["blame"]["newest_commit"] == repo["b"]
    assert result["blame"]["newest_deployed"] is True
    assert result["blame"]["newest_blamed"] is False
    assert result["excluded"] == []


# ── 2. нет метаданных коммита — честный unknown ───────────────────────────

@requires_git
def test_missing_manifest_is_unknown_and_not_comparable(tmp_path):
    repo = _build_repo(tmp_path)
    shutil.rmtree(repo["root"] / ".deploy")
    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_event_after_release())

    assert result["status"] == "unknown"
    assert result["reason"] == "no_deployed_sha"
    assert result["release"]["deployed_sha"] is None
    assert result["release"]["verification"] == "not_confirmed"
    assert result["blame"]["verdict"] == "not_comparable"
    assert result["candidates"] == []
    assert result["excluded"] == []
    assert result["blame"]["newest_blamed"] is False
    assert result["blame"]["newest_commit"] == repo["b"]
    assert result["blame"]["newest_deployed"] is False
    # Честно: без deployed SHA изменения/диф не проверялись.
    assert "changed_files" in result["not_checked"]
    assert "commit_diff" in result["not_checked"]
    # Отвечающий файл при этом найден по call chain.
    assert result["answering"]["file"] == "services/voice.py"


# ── 3. call chain: файл/функция/caller ────────────────────────────────────

@requires_git
def test_call_chain_reports_answering_file_function_and_caller(tmp_path):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo, external=True),
        event_at=_event_after_release(), identity=identity)

    chain = result["call_chain"]
    assert [entry["depth"] for entry in chain] == [0, 1, 2]
    assert chain[0]["in_repo"] is False
    assert chain[0]["external_name"] == "decoder.py"
    assert chain[0]["file"] == ""
    assert chain[1]["file"] == "services/router.py"
    assert chain[1]["caller"] is True
    assert chain[2]["file"] == "services/voice.py"
    assert chain[2]["answering"] is True

    answering = result["answering"]
    assert answering["file"] == "services/voice.py"
    assert answering["function"] == "handle_voice"
    assert answering["line"] == 2
    assert answering["exact_frame"] is True
    assert answering["caller_file"] == "services/router.py"
    assert answering["caller_function"] == "route"
    assert answering["caller_line"] == 5
    # Абсолютные пути хоста наружу не попадают.
    blob = json.dumps(result, ensure_ascii=False)
    assert str(repo["root"]) not in blob
    assert "decoder.py" in blob


@requires_git
def test_inner_external_frame_keeps_repo_answering_frame(tmp_path):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    root = repo["root"]
    text = (
        "Traceback (most recent call last):\n"
        f'  File "{root}\\services\\router.py", line 5, in route\n'
        "    return handle_voice()\n"
        f'  File "{root}\\services\\voice.py", line 2, in handle_voice\n'
        "    return _decode()\n"
        '  File "/usr/lib/python3.12/json/decoder.py", line 355, '
        "in raw_decode\n"
        "    raise JSONDecodeError('x')\n"
        "JSONDecodeError: x\n"
    )
    result = di.correlate_traceback(
        root, traceback_text=text, event_at=_event_after_release(),
        identity=identity)
    assert result["call_chain"][-1]["in_repo"] is False
    answering = result["answering"]
    assert answering["file"] == "services/voice.py"
    assert answering["depth"] == 1
    assert answering["exact_frame"] is False
    assert answering["caller_file"] == "services/router.py"
    assert answering["caller_function"] == "route"
    assert result["status"] == "ok", result


# ── 4. commit diff: только релиз и отвечающий файл, символы, бюджет ───────
@requires_git
def test_commit_diff_is_scoped_to_release_and_answering_file(tmp_path):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_event_after_release(), identity=identity)

    diff = result["commit_diff"]
    assert diff is not None
    assert diff["sha"] == repo["b"]
    assert diff["path"] == "services/voice.py"
    assert diff["added"] >= 1 and diff["removed"] >= 1
    assert "handle_voice" in diff["symbols"]
    assert any(line.startswith("+") for line in diff["lines"])
    assert any(line.startswith("-") for line in diff["lines"])
    assert diff["truncated"] is False
    assert diff["lines_truncated"] is False
    # Неразвёрнутый C в diff не попадает вообще.
    assert "boom-next" not in json.dumps(result, ensure_ascii=False)

    answering_file = next(item for item in result["files"]
                          if item["role"] == "answering")
    assert answering_file["changed_in_release"] is True
    assert answering_file["symbol_match"] is True
    assert answering_file["released_sha"] == repo["b"]

    call_chain_file = next(item for item in result["files"]
                           if item["role"] == "call_chain")
    assert call_chain_file["path"] == "services/router.py"
    assert call_chain_file["changed_in_release"] is False


@requires_git
def test_diff_budget_truncates_without_breaking_result(tmp_path):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    body = "\n".join(f"    value_{index} = '{'x' * 200}'"
                     for index in range(60))
    repo["voice"].write_text(
        "def handle_voice():\n" + body + "\n", encoding="utf-8")
    _git(repo["root"], "add", "services/voice.py")
    _git(repo["root"], "commit", "-q", "-m", "release D: big voice body")
    sha_d = _git(repo["root"], "rev-parse", "HEAD").stdout.strip()
    manifest = json.loads(
        (repo["root"] / ".deploy" / "release.json").read_text("utf-8"))
    manifest.update({"deployed_sha": sha_d, "previous_sha": repo["b"]})
    (repo["root"] / ".deploy" / "release.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    started_at = _now() - timedelta(minutes=1)
    identity = di.collect_identity(repo["root"],
                                  process_started_at=started_at)
    assert identity["code"] == "verified_deployed", identity

    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_event_after_release(), identity=identity,
        budget_chars=400)
    assert result["status"] in di.CORRELATION_STATUSES
    diff = result["commit_diff"]
    assert diff is not None
    assert diff["added"] >= 60
    assert diff["truncated"] is True
    assert result["truncated"] is True
    assert result["status"] == "degraded"
    assert result["reason"] == "budget_exhausted"
    assert len(diff["lines"]) <= di._CORRELATION_MAX_DIFF_LINES


# ── 5. секреты и shell-инъекции не проходят ───────────────────────────────

@requires_git
def test_no_secret_leak_and_no_shell_injection(tmp_path, monkeypatch):
    repo = _build_repo(tmp_path)
    secret = "Bearer sk-live-D4CSECRET"
    injection = "services/voice.py; touch pwned"
    repo["voice"].write_text(
        "def handle_voice():\n"
        f"    token = '{secret}'\n"
        "    raise RuntimeError('boom')\n", encoding="utf-8")
    _git(repo["root"], "add", "services/voice.py")
    _git(repo["root"], "commit", "-q", "-m", "release E: token in code")
    sha_e = _git(repo["root"], "rev-parse", "HEAD").stdout.strip()
    manifest = json.loads(
        (repo["root"] / ".deploy" / "release.json").read_text("utf-8"))
    manifest.update({"deployed_sha": sha_e, "previous_sha": repo["b"]})
    (repo["root"] / ".deploy" / "release.json").write_text(
        json.dumps(manifest), encoding="utf-8")

    captured = []
    real_run = di.subprocess.run

    def spy(argv, **kwargs):
        captured.append((list(argv), dict(kwargs)))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(di.subprocess, "run", spy)
    started_at = _now() - timedelta(minutes=1)
    identity = di.collect_identity(repo["root"],
                                  process_started_at=started_at)
    assert identity["code"] == "verified_deployed", identity
    traceback_text = _traceback_text(repo, message=secret, extra_frames=(
        (injection, 12, "evil"),
        ("/etc/shadow", 1, "root_read"),
        (repo["root"] / "backups" / "tool.py", 3, "restore"),
    ))
    result = di.correlate_traceback(
        repo["root"], traceback_text=traceback_text,
        event_at=_event_after_release(), identity=identity)

    blob = json.dumps(result, ensure_ascii=False)
    assert "sk-live-D4CSECRET" not in blob
    assert "***" in blob or "Bearer" not in blob
    assert str(repo["root"]) not in blob
    assert "/etc/shadow" not in blob
    # Инъекционный путь не стал pathspec и не попал в git argv.
    reasons = {entry.get("file_reason") for entry in result["call_chain"]}
    assert "path_rejected" in reasons or "non_source" in reasons
    for argv, kwargs in captured:
        assert argv[0] == "git"
        assert kwargs.get("shell") is False
        assert injection not in argv
        assert "/etc/shadow" not in argv
        assert "backups/tool.py" not in argv


# ── 6. graceful: таймаут/нет git/нет кадров/пустой текст ─────────────────

@requires_git
def test_git_timeout_is_graceful(tmp_path, monkeypatch):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    real_run = di.subprocess.run

    def boom(argv, **kwargs):
        if "status" in argv:
            return real_run(argv, **kwargs)
        raise subprocess.TimeoutExpired(cmd="git", timeout=3)

    monkeypatch.setattr(di.subprocess, "run", boom)
    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_event_after_release(), identity=identity)
    assert result["status"] in di.CORRELATION_STATUSES
    assert result["status"] in ("degraded", "unknown")
    assert result["reason"] == "git_timeout"
    assert result["blame"]["verdict"] == "not_comparable"
    assert result["candidates"] == []
    assert result["excluded"] == []
    assert result["answering"]["file"] == "services/voice.py"


@requires_git
def test_missing_git_and_root_and_frames_are_honest(tmp_path):
    repo = _build_repo(tmp_path)
    no_git = tmp_path / "plain"
    no_git.mkdir()

    result = di.correlate_traceback(
        no_git, traceback_text=_traceback_text(repo),
        event_at=_event_after_release())
    assert result["status"] == "unknown"
    assert result["reason"] == "no_git"
    assert "changed_files" in result["not_checked"]

    missing = di.correlate_traceback(
        tmp_path / "absent", traceback_text=_traceback_text(repo))
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "root_missing"

    no_frames = di.correlate_traceback(
        repo["root"], traceback_text="RuntimeError: boom\n")
    assert no_frames["status"] == "unknown"
    assert no_frames["reason"] == "no_frames"
    assert no_frames["call_chain"] == []
    assert "call_chain" in no_frames["not_checked"]

    empty = di.correlate_traceback(repo["root"], traceback_text="")
    assert empty["status"] == "ok"
    assert empty["reason"] == "no_traceback"
    # Установка релиза известна из манифеста; коррелировать больше нечего.
    assert set(empty["not_checked"]) == set(di.CORRELATION_AXES) - {
        "release_install"}

    unknown_frame = di.correlate_traceback(
        repo["root"],
        traceback_text=_frame("/usr/lib/python3.12/os.py", 1, "getcwd"))
    assert unknown_frame["status"] == "degraded"
    assert unknown_frame["reason"] == "no_answering_file"
    assert unknown_frame["answering"] is None


# ── 7. событие раньше релиза — изменение не виновно ───────────────────────

@requires_git
def test_event_before_release_does_not_blame_release_change(tmp_path):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    before = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_iso(_now() - timedelta(minutes=30)), identity=identity)
    assert before["event"]["relation"] == "event_before_release"
    assert before["blame"]["verdict"] == "event_precedes_release"
    assert repo["b"] not in [item["sha"] for item in before["candidates"]]
    assert repo["c"] not in [item["sha"] for item in before["candidates"]]


# ── 8. probe/collector seam: факты, source_ref, code_lookup ──────────────

class _Ring:
    def __init__(self, entries):
        self.entries = list(entries)

    def get_entries(self, level="INFO", limit=200):
        return self.entries[:limit]


def _error_entry(text):
    return {"ts": _event_after_release(), "level": "ERROR",
            "logger": "tests", "message": "boom", "exc_text": text}


def _probe_deps(**kwargs):
    from services import runtime_probes as rp
    return rp.ProbeDeps(**kwargs)


@pytest.mark.asyncio
@requires_git
async def test_probe_exposes_correlation_in_tool_facts(tmp_path):
    from services import diagnostic_collector as dc
    from services import runtime_probes as rp

    repo = _build_repo(tmp_path)
    started_at = _now() - timedelta(minutes=1)
    ring = _Ring([_error_entry(_traceback_text(repo))])
    collector = dc.DiagnosticCollector(
        deps=_probe_deps(log_ring_getter=lambda: ring,
                         repo_root=str(repo["root"]),
                         status=_Status(started_at)),
        limits=rp.ProbeLimits(probe_timeout_seconds=5.0))

    bundle, page = await collector.collect(dc.CollectionRequest(
        probe="deploy.traceback", chat_id=-100, scope="current_chat"))
    source = page["sources"][0]
    assert source["source_id"] == "deploy:traceback"
    assert source["status"] == "ok"
    assert source["coverage"]["parts"] == ["deploy"]
    assert source["source_ref"]["entity_id"] == f"commit:{repo['b']}"
    assert source["source_ref"]["store"] == "external"
    facts = source["facts"]
    assert facts["error_traceback"] is True
    assert facts["answering_file"] == "services/voice.py"
    assert facts["answering_function"] == "handle_voice"
    assert facts["caller_function"] == "route"
    assert facts["blame_verdict"] == "release_change_suspect"
    assert facts["deployed_sha"] == repo["b"]
    assert facts["newest_commit"] == repo["c"]
    assert facts["newest_commit_blamed"] is False
    assert facts["excluded_undeployed"] >= 1
    assert facts["correlation"]["blame"]["newest_blamed"] is False
    assert bundle.code_lookup_attempted is True
    assert bundle.runtime_sha == repo["b"]
    blob = json.dumps(page, ensure_ascii=False)
    assert str(repo["root"]) not in blob


@pytest.mark.asyncio
@requires_git
async def test_probe_without_error_traceback_is_not_checked(tmp_path):
    from services import diagnostic_collector as dc
    from services import runtime_probes as rp

    ring = _Ring([])
    collector = dc.DiagnosticCollector(
        deps=_probe_deps(log_ring_getter=lambda: ring,
                         repo_root=str(tmp_path)),
        limits=rp.ProbeLimits(probe_timeout_seconds=2.0))
    bundle, page = await collector.collect(dc.CollectionRequest(
        probe="deploy.traceback", chat_id=-100, scope="current_chat"))
    source = page["sources"][0]
    assert source["status"] == "ok"
    assert source["reason_code"] == "no_error_traceback"
    assert set(source["not_checked"]) == set(di.CORRELATION_AXES)
    assert source["facts"]["correlation"] is None
    assert bundle.code_lookup_attempted is False


@pytest.mark.asyncio
async def test_probe_log_ring_unavailable_is_honest():
    from services import diagnostic_collector as dc
    from services import runtime_probes as rp

    def broken():
        raise RuntimeError("no ring")

    collector = dc.DiagnosticCollector(
        deps=_probe_deps(log_ring_getter=broken),
        limits=rp.ProbeLimits(probe_timeout_seconds=2.0))
    _, page = await collector.collect(dc.CollectionRequest(
        probe="deploy.traceback", chat_id=-100, scope="current_chat"))
    source = page["sources"][0]
    assert source["status"] == "unavailable"
    assert source["reason_code"] == "log_ring_unavailable"


@pytest.mark.asyncio
@requires_git
async def test_probe_timeout_degrades_without_raising(tmp_path, monkeypatch):
    from services import diagnostic_collector as dc
    from services import runtime_probes as rp

    repo = _build_repo(tmp_path)
    ring = _Ring([_error_entry(_traceback_text(repo))])

    def slow(*args, **kwargs):
        time.sleep(3.0)
        return di._correlation_base("now")

    from services import deploy_identity as identity_module
    monkeypatch.setattr(identity_module, "correlate_traceback", slow)
    collector = dc.DiagnosticCollector(
        deps=_probe_deps(log_ring_getter=lambda: ring,
                         repo_root=str(repo["root"]),
                         status=_Status(_now() - timedelta(minutes=1))),
        limits=rp.ProbeLimits(probe_timeout_seconds=2.0))
    _, page = await collector.collect(dc.CollectionRequest(
        probe="deploy.traceback", chat_id=-100, scope="current_chat"))
    source = page["sources"][0]
    assert source["status"] == "degraded"
    assert source["reason_code"] == "correlation_timeout"
    assert set(source["not_checked"]) == set(di.CORRELATION_AXES)


@pytest.mark.asyncio
@requires_git
async def test_checkup_path_includes_traceback_correlation(tmp_path):
    from services import diagnostic_collector as dc
    from services import runtime_probes as rp

    repo = _build_repo(tmp_path)
    ring = _Ring([_error_entry(_traceback_text(repo))])
    collector = dc.DiagnosticCollector(
        deps=_probe_deps(log_ring_getter=lambda: ring,
                         repo_root=str(repo["root"]),
                         status=_Status(_now() - timedelta(minutes=1))),
        limits=rp.ProbeLimits(probe_timeout_seconds=5.0))
    bundle, facts_text = await collector.collect_for_checkup(
        logs_text="2026-11-13 ERROR boom\n", used_fallback=False,
        chat_id=-100)
    ids = {source.source_id for source in bundle.sources}
    assert "deploy:traceback" in ids
    assert "deploy:identity" in ids
    traceback_source = next(source for source in bundle.sources
                            if source.source_id == "deploy:traceback")
    assert traceback_source.facts["answering_file"] == "services/voice.py"
    assert "answering_file=services/voice.py" in facts_text
    assert "blame_verdict=release_change_suspect" in facts_text
    assert "newest_commit_blamed=False" in facts_text
    assert bundle.code_lookup_attempted is True


# ── 9. закрытые наборы и контракт «не бросает» ───────────────────────────

@requires_git
def test_closed_sets_and_never_raises(tmp_path):
    assert set(di.CORRELATION_STATUSES) == {"ok", "degraded", "unknown",
                                            "unavailable"}
    assert set(di.CORRELATION_BASES) == {"release_diff",
                                         "recent_before_release", "none"}
    assert "release_change_suspect" in di.CORRELATION_VERDICTS
    assert "not_comparable" in di.CORRELATION_VERDICTS

    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)

    class Exploding:
        """Мусор вместо traceback-текста и события."""

        def __str__(self):
            raise RuntimeError("no str")

    weird = di.correlate_traceback(
        repo["root"], traceback_text=None, event_at=object(),
        identity=identity)
    assert weird["status"] in di.CORRELATION_STATUSES
    assert weird["reason"] in di.CORRELATION_REASONS
    assert weird["event"]["parsed"] is False

    broken_identity = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        identity={"code": "unavailable", "reason": "internal_error"})
    assert broken_identity["status"] == "unknown"
    assert broken_identity["reason"] == "no_deployed_sha"
    assert broken_identity["blame"]["verdict"] == "not_comparable"

    with pytest.raises(RuntimeError):
        str(Exploding())


@requires_git
def test_result_is_json_serialisable(tmp_path):
    repo = _build_repo(tmp_path)
    identity = _verified_identity(repo)
    result = di.correlate_traceback(
        repo["root"], traceback_text=_traceback_text(repo),
        event_at=_event_after_release(), identity=identity)
    payload = json.dumps(result, ensure_ascii=False)
    assert json.loads(payload)["schema"] == 1
    for field in ("event", "release", "call_chain", "answering", "files",
                  "commits", "candidates", "excluded", "commit_diff",
                  "blame", "not_checked", "truncated"):
        assert field in result


@pytest.mark.asyncio
async def test_public_traceback_frames_helper():
    from services import evidence_bundle as eb

    parsed = eb.traceback_frames(
        'Traceback (most recent call last):\n'
        '  File "/srv/app/services/x.py", line 7, in run\n'
        "    boom()\n"
        "ValueError: bad\n")
    assert parsed["frames"][0]["file"].endswith("services/x.py")
    assert parsed["frames"][0]["function"] == "run"
    assert parsed["frames"][0]["line"] == 7
    assert parsed["exception"]["type"] == "ValueError"
    assert eb.traceback_frames("")["frames"] == []


def test_incident_scenario_includes_traceback_correlation():
    from services import runtime_probes as rp

    spec = rp.get_probe("incidents.investigate_incident")
    assert spec is not None
    assert "deploy.traceback" in spec.children
    traceback_spec = rp.get_probe("deploy.traceback")
    assert traceback_spec is not None
    assert traceback_spec.read_scope == rp.READ_SCOPE_REPO
    assert traceback_spec.args in (None, {})
    catalog = rp.probe_catalog(deps=rp.ProbeDeps())
    entry = next(item for item in catalog["probes"]
                 if item["probe"] == "deploy.traceback")
    assert entry["declared"] is True
    assert entry["configured"] is True
    assert entry["read_scope"] == rp.READ_SCOPE_REPO
