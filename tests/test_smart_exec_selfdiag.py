"""SMART-EXECUTION-RELIABILITY-01 · S8 Self-Diag (этап H).

Контракт остатка H1-H5 (owner input 2026-11-14, §H1-§H5). Уже выкаченные в
2.58.199 исправления не переимплементируются: здесь доказывается наблюдаемое
поведение текущего кандидата и закрываются остатки.

* SXR-H1-01: чекап исследует причины существующим tool-циклом; объект
  исследования выбирает модель; таблицы "код ошибки -> файл -> инструмент"
  нет; технический поиск по traceback/символам/модулям доступен; репозиторий
  целиком без нужды не читается.
* SXR-H1-02: отчёт различает подтверждённое рабочее состояние, дефект,
  установленную причину, гипотезу, недоступные сведения и рекомендуемое
  исправление; канон характера/стиля чекапа не переписан.
* SXR-H2-01: продолжение идёт обычным Direct-путём; отчёт доступен
  структурно; слова "код/репозиторий/GitHub/чекап" не нужны; не любое
  последующее сообщение считается продолжением.
* SXR-H3-01: журнал читается только собственного unit/вызова, без sudo и
  shell; внутренний поток остаётся fallback; видимость прав процесса.
* SXR-H4-01: .deploy/release.json создаётся существующим инструментом,
  привязан к выложенной версии, переживает рестарт и используется
  SourceReader и чекапом; манифест задним числом не создаётся.
* SXR-H5-01: недоступная наблюдаемость даёт unknown/not_checked, работающая —
  подтверждённый ноль; новых счётчиков нет.

TEST-LIFECYCLE: CONTRACT owner=SMART-S8-SELFDIAG (2026-11-14)
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import time

import pytest

from config.settings import APP_VERSION, settings
from services import checkup_prompts
from services import deploy_identity as di
from services import direct_chat_service as dcs
from services import direct_l1 as l1
from services import diagnostic_collector as dc
from services import runtime_probes as rp
from services import source_reader as sr
from services import system_logs_fetcher as slf
from services.checkup_service import CheckupService
from services.llm_client import LLMChatResult, LLMToolCall

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not available")

CHAT_ID = -100777


# ── общие фикстуры границ (без подмены предмета теста) ──────────────────────


class _StaticRouter:
    def __init__(self, output: str = "{\"status\": \"ok\"}") -> None:
        self.output = output
        self.calls: list = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments or {})))
        return self.output


class _ScriptedLLM:
    def __init__(self, results) -> None:
        self._results = list(results)
        self.messages: list = []
        self.calls = 0

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        self.messages = [dict(m) for m in messages]
        self.calls += 1
        return self._results.pop(0)

    async def generate(self, messages, **kwargs):      # pragma: no cover
        self.messages = [dict(m) for m in messages]
        self.calls += 1
        return "fallback"


def _tool_call(call_id: str, name: str, arguments: dict) -> LLMToolCall:
    return LLMToolCall(id=call_id, name=name,
                       arguments=json.dumps(arguments, ensure_ascii=False))


def _checkup_runtime(router, *, schemas=None):
    return {
        "router": router,
        "ctx": type("Ctx", (), {"chat_id": CHAT_ID})(),
        "schemas": schemas or [
            type("S", (), {"function": {"name": "read_source_code"}})(),
            type("S", (), {"function": {"name": "inspect_runtime"}})(),
        ],
        "correlation_id": "checkup:test",
    }


# ── H1-01: причины через существующие компоненты, объект выбирает модель ────


class TestCheckupRootCauseContract:
    def test_existing_readonly_tool_set_is_used(self, monkeypatch):
        """Тот же read-only набор, что у Direct; identity берётся сервером."""
        import handlers.checkup as hc

        monkeypatch.setattr(
            sr, "resolve_self_repo_identity",
            lambda **kw: {"target": "self", "repo": "Henry-Case-dev/adminbot",
                          "ref": "a" * 40, "ref_source": "deployed_sha",
                          "deployed_sha": "a" * 40,
                          "checkout_sha": "a" * 40,
                          "deployed_matches_checkout": True,
                          "local_source_verification": "verified",
                          "dirty": False, "conflict": [],
                          "identity_error": "", "note": ""})
        hc.setup_checkup_tool_router(object())
        try:
            runtime = asyncio.run(hc._build_checkup_tool_runtime(
                CHAT_ID, 1, bot=object(), correlation_id="checkup:h1"))
        finally:
            hc.setup_checkup_tool_router(None)
        names = {item["function"]["name"] for item in runtime["schemas"]}
        assert names == {"read_source_code", "inspect_runtime"}
        assert runtime["ctx"].diagnostic_research["target"] == "self"
        # Никакого инструмента полного обхода репозитория в наборе нет.
        assert not any("tree" in name or "list_repo" in name
                       for name in names)

    @pytest.mark.asyncio
    async def test_same_error_text_does_not_select_tool_by_itself(self):
        """Модель с тем же ERROR-текстом вправе не читать код вообще."""
        router = _StaticRouter()
        llm = _ScriptedLLM([
            LLMChatResult(content="По фактам причина в таймауте провайдера.",
                          tool_calls=None, finish_reason="stop")])
        report = await CheckupService(llm).checkup(
            "2026-11-13 ERROR TimeoutError: provider stalled",
            used_fallback=False, tool_runtime=_checkup_runtime(router))
        assert router.calls == []
        assert report.startswith("По фактам")
        # Если модель выбирает другой инструмент, исполняется ровно её выбор.
        router2 = _StaticRouter()
        llm2 = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tool_call("c1", "inspect_runtime",
                           {"area": "logs", "probe": "logs.window"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Проверил runtime.", tool_calls=None,
                          finish_reason="stop")])
        await CheckupService(llm2).checkup(
            "2026-11-13 ERROR TimeoutError: provider stalled",
            used_fallback=False, tool_runtime=_checkup_runtime(router2))
        assert [name for name, _ in router2.calls] == ["inspect_runtime"]

    def test_addendum_allows_technical_search_without_whole_repo(self):
        text = checkup_prompts.CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
        assert "traceback" in text
        assert "символ" in text
        assert "модул" in text
        assert "репозиторий целиком не читай" in text
        assert "код ошибки -> конкретный файл -> обязательный инструмент" in text
        # Таблицы соответствий в самом модуле промптов нет.
        lowered = text.casefold()
        assert "error_code_to_file" not in lowered
        assert "traceback_to_file" not in lowered


# ── H1-02: отчёт различает состояние/дефект/причину/гипотезу/unknown/fix ────


class TestCheckupReportCategories:
    REQUIRED = (
        "подтверждённое рабочее состояние",
        "обнаруженный дефект",
        "установленную причину",
        "гипотезу",
        "недоступные сведения",
        "рекомендуемое исправление",
    )

    def test_addendum_lists_all_categories_and_keeps_canon_bytes(self):
        text = checkup_prompts.CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
        for phrase in self.REQUIRED:
            assert phrase in text, phrase
        assert "Гипотезу не подавай как установленную причину" in text
        # Канон характера/стиля не переписан: операционная приписка отдельно.
        assert text not in checkup_prompts.CHECKUP_SYSTEM_PROMPT
        assert "СИСТЕМНАЯ РОЛЬ И ЗАДАЧА:" in checkup_prompts.CHECKUP_SYSTEM_PROMPT
        assert "ЖАНР ОТЧЁТА:" in checkup_prompts.CHECKUP_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_facts_carry_status_not_only_metrics(self):
        class _Fetcher:
            last_state = "ok"
            last_journal_state = "ok"

        collector = dc.DiagnosticCollector(
            deps=rp.ProbeDeps(logs_fetcher=_Fetcher()),
            limits=rp.ProbeLimits(probe_timeout_seconds=2.0,
                                  max_output_chars=9000,
                                  snapshot_ttl_seconds=5.0))
        _, facts = await collector.collect_for_checkup(
            logs_text="2026-11-13 ERROR boom\n", used_fallback=False,
            chat_id=CHAT_ID, request_id="h1-02")
        assert "status=degraded" in facts or "status=ok" in facts
        assert "reason_code=" in facts
        assert "not_checked=" in facts


# ── H2-01: продолжение обычным Direct-путём, без слов-маркеров ──────────────


class TestDiagnosticContinuation:
    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch):
        from services import hot_config as hot
        hot.set_config_cache(None)
        yield
        hot.set_config_cache(None)

    @pytest.mark.asyncio
    async def test_report_is_structural_context_without_marker_words(self):
        from services import bot_output_ledger as ledger
        from services.database import DatabaseService

        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            await ledger.record_delivered_output(
                db, chat_id=CHAT_ID, tg_message_id=91,
                text="ОТЧЁТ: причина в таймауте провайдера, строка 20.",
                output_kind="checkup_report", sent_at=int(time.time()),
                parent_message_ref="tg:5", correlation_id="checkup:h2")
            report = await dcs._recent_checkup_report_text(db, CHAT_ID)
        finally:
            await db.close()
        assert report.startswith("ОТЧЁТ")
        query = "так где всё-таки причина и что чинить?"
        for marker in ("код", "репозитор", "github", "чекап"):
            assert marker not in query.casefold()
        context = l1.build_l1_context(query=query, diagnostic_report=report,
                                      budget_tokens=1500)
        assert l1.DIAGNOSTIC_REPORT_SECTION in context
        assert "причина в таймауте" in context

    def test_not_every_followup_is_continuation(self):
        previous = {"diagnostic_needed": True,
                    "diagnostic_target": "self",
                    "diagnostic_sources": "source_code"}
        assert l1.preserved_diagnostic_research(previous,
                                                reply_to_bot=False) is None
        kept = l1.preserved_diagnostic_research(previous, reply_to_bot=True)
        assert kept is not None and kept.target == "self"
        addendum = checkup_prompts.CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
        assert "Ссылку на собственный репозиторий у человека не запрашивай" \
            in addendum

    def test_l1_addendum_is_semantic_not_marker_words(self):
        from services import chat_prompts as cp
        text = cp.DIRECT_L1_DIAGNOSTIC_RESEARCH_ADDENDUM
        assert "\"diagnostic_research\"" in text
        assert "по смыслу" in text
        # Одна благодарность/подтверждение не запускает исследование.
        assert "Одна благодарность или подтверждение" in text
        assert "target=self" in text


# ── H3-01: журнал собственного unit, минимальные права, fallback ────────────


def _systemd_identity(unit="admin_bot.service", invocation="a" * 32):
    return slf.RuntimeIdentity(kind="systemd", pid=4242, unit=unit,
                               invocation_id=invocation)


class TestJournalEnvironment:
    @pytest.mark.asyncio
    async def test_own_invocation_without_sudo_or_shell(self):
        calls: list = []

        async def _runner(argv):
            calls.append(list(argv))
            return 0, "2026-11-13 ERROR boom\n", ""

        fetcher = slf.CheckupLogsFetcher(
            unit_override="admin_bot.service",
            identity_probe=lambda: _systemd_identity(),
            journal_runner=_runner)
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        argv = calls[0]
        assert argv[0] == "journalctl"
        assert f"_SYSTEMD_INVOCATION_ID={'a' * 32}" in argv
        assert "--unit" not in argv
        assert not any(token in ("sudo", "sh", "-c", "/bin/sh")
                       for token in argv)
        assert "state=ok" in text
        assert fetcher.last_state == "ok"
        assert fetcher.last_journal_state == "ok"

    @pytest.mark.asyncio
    async def test_foreign_unit_override_is_rejected(self):
        calls: list = []

        async def _runner(argv):
            calls.append(list(argv))
            return 0, "", ""

        fetcher = slf.CheckupLogsFetcher(
            unit_override="admin_bot.service",
            identity_probe=lambda: slf.RuntimeIdentity(
                kind="systemd", pid=7, unit="other.service",
                invocation_id=None),
            journal_runner=_runner)
        await fetcher.fetch()
        assert "other.service" in calls[0]
        assert "admin_bot.service" not in calls[0]

    @pytest.mark.asyncio
    async def test_permission_failure_keeps_internal_fallback(self):
        async def _runner(argv):
            return 1, "", "No journal files were opened due to insufficient " \
                          "permissions"

        entries = [{"ts": "2026-11-13 05:00:00", "level": "ERROR",
                    "message": "ledger-boom"}]
        fetcher = slf.CheckupLogsFetcher(
            identity_probe=lambda: _systemd_identity(),
            journal_runner=_runner,
            ledger_reader=lambda limit: entries,
            stdout_tail_reader=lambda limit: None)
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert "ledger-boom" in text
        assert "основной журнал недоступен" in text
        assert fetcher.last_journal_state == "unreadable"
        assert fetcher.last_used_fallback is True

    @pytest.mark.asyncio
    async def test_process_rights_are_visible_and_root_is_flagged(
            self, monkeypatch):
        async def _runner(argv):
            return 0, "2026-11-13 ERROR boom\n", ""

        monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
        root_fetcher = slf.CheckupLogsFetcher(
            identity_probe=lambda: _systemd_identity(),
            journal_runner=_runner)
        root_text, _ = await root_fetcher.fetch()
        assert "uid=0" in root_text
        assert "правами root" in root_text

        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
        user_fetcher = slf.CheckupLogsFetcher(
            identity_probe=lambda: _systemd_identity(),
            journal_runner=_runner)
        user_text, _ = await user_fetcher.fetch()
        assert "uid=1000" in user_text
        assert "правами root" not in user_text


# ── H4-01: настоящий манифест существующего деплой-процесса ─────────────────


def _git(root: pathlib.Path, *args: str) -> str:
    proc = subprocess.run([GIT, *args], cwd=root, capture_output=True,
                          text=True, check=False)
    assert proc.returncode == 0, (args, proc.stderr)
    return (proc.stdout or "").strip()


def _fixture_repo(tmp_path: pathlib.Path, *, version: str,
                  manifest: bool = True) -> tuple[pathlib.Path, str]:
    from tools import release_manifest

    root = pathlib.Path(tmp_path) / "deployed"
    (root / "config").mkdir(parents=True)
    (root / "config" / "settings.py").write_text(
        f'APP_VERSION = "{version}"\n', encoding="utf-8")
    (root / "bot.py").write_text("print('deployed')\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "selfdiag@example.invalid")
    _git(root, "config", "user.name", "selfdiag")
    _git(root, "add", "config/settings.py", "bot.py")
    _git(root, "commit", "-q", "-m", "release fixture")
    sha = _git(root, "rev-parse", "HEAD")
    if manifest:
        deployed_at = datetime.datetime(2026, 11, 14, 12, 0, 0,
                                        tzinfo=datetime.timezone.utc)
        data = release_manifest.build_manifest(root, now=deployed_at)
        assert data["deployed_sha"] == sha
        assert data["version"] == version
        release_manifest.write_manifest(root, data)
    return root, sha


@requires_git
class TestDeployManifestIdentity:
    def test_existing_deploy_tool_writes_manifest_bound_to_release(
            self, tmp_path):
        from tools import release_manifest

        root, sha = _fixture_repo(tmp_path, version=APP_VERSION)
        manifest_path = root / ".deploy" / "release.json"
        assert manifest_path.is_file()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["deployed_sha"] == sha
        assert data["version"] == APP_VERSION
        assert data["effect"] == "deploy"
        # Инструмент не даёт записать манифест по грязному tracked-дереву.
        (root / "bot.py").write_text("print('edited')\n", encoding="utf-8")
        with pytest.raises(release_manifest.ManifestError):
            release_manifest.build_manifest(root)
        # И не переписывает уже существующий манифест сам по себе.
        assert json.loads(manifest_path.read_text(encoding="utf-8")) == data

    def test_identity_is_consistent_and_survives_restart(self, tmp_path):
        root, sha = _fixture_repo(tmp_path, version=APP_VERSION)
        deployed_at = datetime.datetime(2026, 11, 14, 12, 0, 0,
                                        tzinfo=datetime.timezone.utc)
        first = di.collect_identity(
            root, process_started_at=deployed_at
            + datetime.timedelta(seconds=5))
        assert first["code"] == "verified_deployed", first
        assert first["deployed_sha"] == sha
        assert first["checkout_sha"] == sha
        assert first["version_provenance"]["consistent"] is True
        assert "release_manifest" in first["sources"]
        assert "process_start" in first["sources"]
        before = (root / ".deploy" / "release.json").read_bytes()
        again = di.collect_identity(
            root, process_started_at=deployed_at
            + datetime.timedelta(seconds=600))
        assert again["code"] == "verified_deployed"
        assert again["deployed_sha"] == sha
        assert (root / ".deploy" / "release.json").read_bytes() == before

    def test_source_reader_and_checkup_use_the_manifest(self, tmp_path):
        root, sha = _fixture_repo(tmp_path, version=APP_VERSION)
        deployed_at = datetime.datetime(2026, 11, 14, 12, 0, 0,
                                        tzinfo=datetime.timezone.utc)
        started = deployed_at + datetime.timedelta(seconds=5)
        local = sr.resolve_local_source(runtime_root=str(root),
                                        configured_root="",
                                        process_started_at=started)
        assert local["usable"] is True
        assert local["verification"] == "verified_running"
        assert local["version_verified"] is True
        assert local["deployed_sha"] == sha
        assert local["manifest_present"] is True

        collector = dc.DiagnosticCollector(
            deps=rp.ProbeDeps(
                logs_fetcher=type("F", (), {
                    "last_state": "ok", "last_journal_state": "ok",
                    "fetch": None})(),
                repo_root=str(root),
                status=type("S", (), {"started_at": started})()),
            limits=rp.ProbeLimits(probe_timeout_seconds=5.0,
                                  max_output_chars=9000,
                                  snapshot_ttl_seconds=5.0))
        result = asyncio.run(collector.collect(dc.CollectionRequest(
            probe="deploy.identity", chat_id=CHAT_ID, scope="instance",
            request_id="h4")))
        page = result[1]
        source = page["sources"][0]
        assert source["source_id"] == "deploy:identity"
        assert source["facts"]["code"] == "verified_deployed"
        assert source["facts"]["deployed_sha"] == sha

    def test_no_manifest_is_not_backfilled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ADMINBOT_DEPLOYED_SHA", raising=False)
        root, _sha = _fixture_repo(tmp_path, version=APP_VERSION,
                                   manifest=False)
        record = di.collect_identity(
            root, process_started_at=datetime.datetime.now(
                datetime.timezone.utc))
        assert record["code"] == "local_unverified"
        assert record["reason"] == "no_manifest"
        assert record["deployed_sha"] is None
        assert not (root / ".deploy" / "release.json").exists()


# ── H5-01: unknown вместо нуля, подтверждённый ноль только по факту ─────────


class _StateFetcher:
    def __init__(self, state: str, journal_state: str) -> None:
        self.last_state = state
        self.last_journal_state = journal_state

    async def fetch(self):        # pragma: no cover - не вызывается
        raise AssertionError("collector must not re-read the journal")


def _collector(fetcher=None, db=None) -> dc.DiagnosticCollector:
    return dc.DiagnosticCollector(
        deps=rp.ProbeDeps(logs_fetcher=fetcher, db=db),
        limits=rp.ProbeLimits(probe_timeout_seconds=2.0,
                              max_output_chars=9000,
                              snapshot_ttl_seconds=5.0))


class TestUnknownVersusConfirmedZero:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("state,used_fallback,expected", [
        ("unreadable", True, "unknown"),
        ("unreadable", False, "unknown"),
        ("ok", False, "observed"),
        ("info_only", False, "confirmed_zero"),
        ("empty", False, "confirmed_zero"),
    ])
    async def test_checkup_logs_state_is_honest(self, state, used_fallback,
                                                expected):
        collector = _collector(_StateFetcher(state, state))
        bundle, facts = await collector.collect_for_checkup(
            logs_text="2026-11-13 ERROR boom\n" if state == "ok" else "",
            used_fallback=used_fallback, chat_id=CHAT_ID,
            request_id=f"h5-{state}-{used_fallback}")
        source = next(item for item in bundle.sources
                      if item.source_id == "logs:checkup_input")
        assert source.facts["errors_state"] == expected
        assert f"errors_state={expected}" in facts
        if expected == "unknown":
            assert source.status == "degraded"
            assert source.reason_code == "journal_unavailable"
        if expected == "confirmed_zero":
            assert source.facts["zero_basis"] == \
                "journal_window_read_no_error_lines"

    @pytest.mark.asyncio
    async def test_unknown_state_does_not_become_zero(self):
        collector = _collector(_StateFetcher("", ""))
        bundle, _facts = await collector.collect_for_checkup(
            logs_text="", used_fallback=False, chat_id=CHAT_ID,
            request_id="h5-unknown")
        source = next(item for item in bundle.sources
                      if item.source_id == "logs:checkup_input")
        assert source.facts["errors_state"] == "unknown"
        assert source.status == "not_checked"
        assert "errors_total" in source.not_checked

    @pytest.mark.asyncio
    async def test_telegram_zero_requires_observability(self, monkeypatch):
        from services import bot_output_ledger as ledger

        class _NoReaderDb:
            pass

        monkeypatch.setattr(ledger, "ledger_enabled", lambda: False)
        result = await _collector(db=_NoReaderDb()).collect(
            dc.CollectionRequest(
                probe="telegram.delivery", chat_id=CHAT_ID,
                scope="current_chat", request_id="h5-tg-off"))
        source = result[1]["sources"][0]
        assert source["status"] == "not_configured"
        assert source["facts"]["delivered"] is None
        assert "delivered" in source["not_checked"]

        class _Db:
            async def list_bot_outputs_between(self, chat_id, *, since_ts=0,
                                               until_ts=0, limit=200,
                                               kinds=None):
                return []

        monkeypatch.setattr(ledger, "ledger_enabled", lambda: True)
        result = await _collector(db=_Db()).collect(dc.CollectionRequest(
            probe="telegram.delivery", chat_id=CHAT_ID,
            scope="current_chat", request_id="h5-tg-on"))
        source = result[1]["sources"][0]
        assert source["status"] == "ok"
        assert source["facts"]["delivered"] == 0
        assert source["facts"]["observations"] == 0

    @pytest.mark.asyncio
    async def test_stt_without_events_is_not_checked(self):
        class _Db:
            async def get_voice_window(self, chat_id, since_ts, limit):
                return []

        result = await _collector(db=_Db()).collect(dc.CollectionRequest(
            probe="media.stt", chat_id=CHAT_ID, scope="current_chat",
            request_id="h5-stt"))
        source = result[1]["sources"][0]
        assert source["status"] == "not_checked"
        assert source["facts"]["failed"] is None
        assert source["reason_code"] == "no_voice_rows"
        assert "voice_transcripts" in source["not_checked"]

    @pytest.mark.asyncio
    async def test_journal_probe_zero_requires_read_window(self):
        class _EmptyFetcher:
            def describe_source(self):
                return "fake:journal"

            async def fetch(self):
                return "", False

        result = await _collector(_EmptyFetcher()).collect(
            dc.CollectionRequest(probe="logs.window", chat_id=CHAT_ID,
                                 scope="instance", request_id="h5-window"))
        source = result[1]["sources"][0]
        assert source["status"] == "ok"
        assert source["facts"]["empty_window"] is True
        assert source["facts"]["error_marker_count"] is None
        assert source["facts"]["error_marker_basis"] == "no_observations"
        assert source["healthy"] is None
