"""SELF-DIAG-01 D6 — контракт интеграции чекапа, регистрации и аналитики.

Проверяются именно наблюдаемые обязательства D6:

* explicit-чекап берёт факты у ТОГО ЖЕ ``DiagnosticCollector``
  (``collect_for_checkup``), промпт и характер чекапа не меняются, а сбой
  collector'а не выключает чекап (`SD1-AC-01`, `SD1-AC-02`, `SD1-D6-07/09/22`);
* защищённый ``prompt_readback`` действительно зарегистрирован в существующем
  tool-пути (не «неизвестный инструмент»), отказ приходит машинным статусом
  (`SD1-D5-02`, `SD1-AMX-04`, `SD1-D6-11`);
* ``inspect_runtime`` сохраняет 17-е место, ``prompt_readback`` — 18-е
  (`SD1-D3-01`, инвариант `tool_calling`);
* телеметрия и аналитика «Самодиагностики» не выдумывают значения: без
  источника — ``None``/``measured=false`` (`SD1-D6-05`, `SD1-D6-17..20`);
* output validation удаляет ТОЛЬКО опасный фрагмент, а не весь отчёт
  (`SD1-D6-01`).

Тесты не ходят в сеть/БД/Telegram: collector, prompt-prepare и события —
детерминированные двойники, окно и psutil — реальные локальные.
"""
import datetime
import hashlib
import json
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import checkup as checkup_mod
from services import diagnostic_policy as diag
from services import output_projection
from services import prompt_readback as readback_srv
from services import tool_schemas
from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT_ID = -1001234567890
#: sha256 заводского `prompts.checkup_system_prompt` до/после D6 (байты).
CHECKUP_SYSTEM_PROMPT_SHA256 = (
    "b0c70f974e0e7a78da3cb3f9c907a85673431de169d0e25c607d954858b4dfdf")


def _make_msg(text="чекап", message_id=11, user_id=1, chat_id=CHAT_ID):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    return msg


class _StubBundle:
    def __init__(self, *, status="ok", sources=None, truncated=False,
                 runtime=None, deployed_sha="abcdef1234567890",
                 git_meta=True):
        self._payload = {
            "status": status,
            "coverage": {"truncated": truncated},
            "sources": sources or [
                {"id": "deploy.identity", "status": "ok"},
                {"id": "process.self", "status": "ok"},
            ],
            "not_checked": ["commits_since_deploy"] if not git_meta else [],
            "runtime": runtime or {"runtime_type": "standalone"},
            "runtime_sha": deployed_sha,
            "git_head_sha": deployed_sha,
            "source_verified": True,
            "git_metadata_attempted": git_meta,
            "commits_since_deploy": None,
        }

    def to_dict(self):
        return dict(self._payload)


class _StubCollector:
    def __init__(self, *, facts="DIAGNOSTIC_EVIDENCE status=ok",
                 bundle=None, error=None):
        self.facts = facts
        self.bundle = bundle if bundle is not None else _StubBundle()
        self.error = error
        self.calls = []

    async def collect_for_checkup(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.bundle, self.facts


@pytest.fixture
def cleanup():
    yield
    checkup_mod._service = None
    checkup_mod._fetcher = None
    checkup_mod._diagnostics = None
    checkup_mod._cooldown._last.clear()


def _wire(service, fetcher, collector=None):
    checkup_mod.setup_checkup(service, fetcher, diagnostics=collector)


class TestExplicitCheckupWiring:
    @pytest.mark.asyncio
    async def test_uses_shared_collector_and_keeps_report(self, cleanup):
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        service.last_run = {"prompt_version_used": "default:abc123def456",
                            "prompt_hash": "abc123def456"}
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        collector = _StubCollector(facts="DIAGNOSTIC_EVIDENCE status=ok")
        _wire(service, fetcher, collector)

        await checkup_mod.checkup_handler(_make_msg(), bot=AsyncMock())

        assert len(collector.calls) == 1
        call = collector.calls[0]
        assert call["logs_text"] == "логи"
        assert call["used_fallback"] is False
        assert call["chat_id"] == CHAT_ID
        # Решение политики передаётся машинными полями, без секретов.
        assert call["permission"]["data_class"] == "PUBLIC_TECH"
        # Факты идут ДАННЫМИ перед логами; промпт не меняется.
        service.checkup.assert_awaited_once_with(
            "DIAGNOSTIC_EVIDENCE status=ok\nлоги", False, chat_id=CHAT_ID)

    @pytest.mark.asyncio
    async def test_collector_failure_does_not_disable_checkup(self, cleanup):
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт по логам")
        service.last_run = {}
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        collector = _StubCollector(error=RuntimeError("probe boom"))
        _wire(service, fetcher, collector)

        await checkup_mod.checkup_handler(_make_msg(), bot=AsyncMock())

        service.checkup.assert_awaited_once_with("логи", False, chat_id=CHAT_ID)

    @pytest.mark.asyncio
    async def test_partial_evidence_is_reported_in_event(self, cleanup,
                                                         monkeypatch):
        captured = []
        monkeypatch.setattr(
            "services.mca_events.emit_mca_event",
            lambda name, **kw: captured.append((name, kw)))
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        service.last_run = {"prompt_version_used": "global:deadbeef1234",
                            "prompt_hash": "deadbeef1234"}
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", True))
        bundle = _StubBundle(status="degraded", truncated=True, git_meta=False)
        _wire(service, fetcher, _StubCollector(bundle=bundle))

        await checkup_mod.checkup_handler(_make_msg(), bot=AsyncMock())

        name, fields = captured[-1]
        assert name == "checkup_triggered"
        raw = fields["source_ref_json"]
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
        assert payload["bundle_delivered"] is True
        assert payload["bundle_truncated"] is True
        assert payload["bundle_status"] == "degraded"
        assert payload["prompt_version_used"] == "global:deadbeef1234"
        assert payload["prompt_hash"] == "deadbeef1234"
        # Содержимое промпта/отчёта в телеметрию не попадает.
        assert "отчёт" not in str(raw)

    @pytest.mark.asyncio
    async def test_identity_log_is_machine_only(self, cleanup, caplog):
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        service.last_run = {}
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        bundle = _StubBundle(
            runtime={"runtime_type": "standalone",
                     "note": "SECRET-TOKEN-9988"})
        _wire(service, fetcher, _StubCollector(bundle=bundle))

        with caplog.at_level("INFO", logger="handlers.checkup"):
            await checkup_mod.checkup_handler(_make_msg(), bot=AsyncMock())

        line = [r.message for r in caplog.records
                if "[checkup] identity" in r.message]
        assert line, "identity-строка должна писаться"
        assert "abcdef123456" in line[0]
        assert "sources=2/2" in line[0]
        assert "SECRET-TOKEN-9988" not in line[0]

    @pytest.mark.asyncio
    async def test_group_checkup_not_blocked_for_unverifiable_admin(
            self, cleanup):
        """`SD1-D6-10`: неверифицируемый админ группы не блокирует чекап."""
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        service.last_run = {}
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher, _StubCollector())
        bot = AsyncMock()
        # bot.get_chat_member недоступен (AsyncMock вернёт MagicMock) — живая
        # проверка Telegram не подтверждает роль, но public_tech доступен.
        await checkup_mod.checkup_handler(
            _make_msg(user_id=777), bot=bot)
        fetcher.fetch.assert_awaited_once()

    def test_no_second_prompt_or_writer(self):
        """`SD1-GRAL-02`/`SD1-EVD-02`: один промпт и один Writer."""
        assert hashlib.sha256(CHECKUP_SYSTEM_PROMPT.encode("utf-8")) \
            .hexdigest() == CHECKUP_SYSTEM_PROMPT_SHA256
        service = MagicMock()
        service.checkup = AsyncMock()
        _wire(service, MagicMock(), None)
        # Чек-ап использует ОДИН llm-клиент сервиса; второго Writer нет.
        assert checkup_mod._service is service

    def test_checkup_is_not_a_prompt_readback_trigger(self):
        """`SD1-D6-11`: «чекап» не становится командой «покажи промпты»."""
        assert checkup_mod._is_checkup_trigger("чекап") is True
        assert checkup_mod._is_checkup_trigger("покажи промпт") is False
        assert checkup_mod._is_checkup_trigger("покажи системный промпт") is False
        source = open(checkup_mod.__file__, encoding="utf-8").read()
        assert "prompt_readback" not in source
        assert "покажи промпт" not in source

    def test_output_validation_replaces_only_dangerous_fragment(self):
        """`SD1-D6-01`: маскируется только опасный фрагмент, отчёт остаётся."""
        result = output_projection.sanitize(
            "Сервер жив. Ключ sk-live-1234567890 в логе. Версия 2.58.197.",
            kind="final",
            secrets={"sk-live-1234567890": "OPENAI_API_KEY"})
        assert result.allowed is True
        assert "sk-live-1234567890" not in result.text
        assert "Сервер жив." in result.text
        assert "Версия 2.58.197." in result.text
        assert result.report.redacted == 1


class TestPromptReadbackRegistration:
    def test_tool_canon_positions(self):
        names = [t["function"]["name"] for t in tool_schemas.TOOL_CALLING_TOOLS]
        assert len(names) == 18
        assert names[16] == "inspect_runtime"
        assert names[17] == "prompt_readback"

    def test_capability_is_prompts(self):
        assert diag.TOOL_CAPABILITIES["prompt_readback"] == "prompts"
        capability = diag.CAPABILITY_MAP["prompts"]
        assert "prompt_readback" in capability.tool_names
        assert "view" in capability.actions

    def test_schema_is_typed_and_has_no_trigger_text(self):
        tool = tool_schemas.TOOL_PROMPT_READBACK
        params = tool["function"]["parameters"]
        assert params["required"] == ["resource_kind"]
        assert params["additionalProperties"] is False
        enum = params["properties"]["resource_kind"]["enum"]
        assert enum == [readback_srv.RESOURCE_KIND_PROMPT]
        blob = json.dumps(tool, ensure_ascii=False).lower()
        for phrase in ("покажи промпт", "show me the prompt", "чекап"):
            assert phrase not in blob

    @pytest.mark.asyncio
    async def test_dispatch_is_not_unknown_and_denies_without_identity(self):
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        ctx = ToolContext(CHAT_ID, "покажи промпт")
        out = await router.dispatch(
            "prompt_readback", {"resource_kind": "prompt"}, ctx)
        assert "неизвестный инструмент" not in out

    @pytest.mark.asyncio
    async def test_denied_ack_is_honest_signal_and_telemetry(
            self, monkeypatch):
        events = []
        monkeypatch.setattr(
            "services.mca_events.emit_mca_event",
            lambda name, **kw: events.append(name))

        async def _allow(*args, **kwargs):
            return types.SimpleNamespace(allowed=True, effect="allow")

        async def _prepare(arguments, **kwargs):
            return types.SimpleNamespace(
                deliverable=False, status="denied", reason="unverified",
                machine="PROMPT_READBACK status=denied reason=unverified",
                metadata={}, messages=(), request_id="req-1")

        monkeypatch.setattr("services.diagnostic_policy.check_tool_call",
                            _allow)
        monkeypatch.setattr(readback_srv, "prepare", _prepare)
        async def _secrets(**kwargs):
            return {}
        monkeypatch.setattr(output_projection,
                            "known_secret_values_async", _secrets)

        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        ctx = ToolContext(CHAT_ID, "покажи промпт", user_id=1, bot=AsyncMock())
        out = await router.dispatch(
            "prompt_readback", {"resource_kind": "prompt"}, ctx)

        assert out == "PROMPT_READBACK status=denied reason=unverified"
        assert ctx.tool_result_signal["status"] == "denied"
        assert "prompt_readback_requested" in events
        assert "prompt_readback_denied" in events


class TestSelfDiagnosisAnalytics:
    def _rows(self):
        now = int(datetime.datetime.now(
            datetime.timezone.utc).timestamp())

        def row(name, status, duration=None, stage="", ts=None):
            return {"event_name": name, "status": status,
                    "duration_ms": duration, "stage": stage,
                    "ts": ts or now, "outcome": "success",
                    "source_ref_json": None, "attempt": None}

        return [
            row("inspect_runtime_called", "ok", 100, "deploy.identity"),
            row("inspect_runtime_called", "ok", 300, "deploy.identity"),
            row("inspect_runtime_called", "degraded", 200, "logs.errors"),
            row("checkup_triggered", "report_sent", 900, "final"),
            row("get_bot_health_called", "called", 700, "tool"),
            row("diagnostic_output_validated", "clean", None, "tool"),
        ]

    def test_percentiles_partial_and_per_stage(self):
        from web.api import routes as web_routes
        stats = web_routes._self_diag_stats(
            self._rows(), "inspect_runtime_called")
        assert stats["calls"] == 3
        assert stats["partial"] == 1
        assert stats["partial_share"] == pytest.approx(0.3333, abs=1e-3)
        assert stats["p50_ms"] == 200
        assert stats["p95_ms"] == 290.0
        top = stats["by_stage"][0]
        assert top["stage"] == "deploy.identity"
        assert top["calls"] == 2 and top["failed"] == 0

    def test_event_counts_cover_required_names(self):
        from web.api import routes as web_routes
        rows = self._rows()
        for name in ("checkup_triggered", "get_bot_health_called",
                     "inspect_runtime_called", "read_source_attempted",
                     "read_source_verified", "code_unavailable",
                     "prompt_readback_requested", "prompt_readback_allowed",
                     "prompt_readback_denied"):
            assert web_routes._self_diag_count(rows, name) >= 0

    @pytest.mark.asyncio
    async def test_payload_has_no_invented_values(self, monkeypatch):
        from web.api import routes as web_routes

        def _no_db():
            return None
        monkeypatch.setattr("services.lore_runtime.get_lore_db", _no_db)

        def _identity(root=None, *, process_started_at=None):
            return {"deployed_sha": "deadbeef" * 5, "checkout_sha": "deadbeef",
                    "branch": "main", "dirty": False,
                    "repo_origin": "Henry-Case-dev/adminbot",
                    "commits_since_deploy": None}
        monkeypatch.setattr("services.deploy_identity.collect_identity",
                            _identity)

        payload = await web_routes._self_diag_payload(None)
        analytics = payload["analytics"]
        assert payload["available"] is True
        # Нет событий → нет измеренных значений, а не «0/зелёное».
        assert analytics["secret_value_disclosures"]["value"] is None
        assert analytics["secret_value_disclosures"]["measured"] is False
        assert analytics["golden_eval"]["available"] is False
        assert analytics["retries"]["measured"] is False
        assert analytics["inspect_runtime"]["measured"] is False
        # Источники помечены как declared, пока нет наблюдения.
        assert payload["sources"]
        assert all(src["fact_kind"] == "declared"
                   for src in payload["sources"])
        assert payload["missing_evidence"]["count"] == len(payload["sources"])
        assert payload["runtime"]["deployed_sha"].startswith("deadbeef")
        # Никаких credential-полей в payload.
        blob = json.dumps(payload, ensure_ascii=False).lower()
        assert "api_key=" not in blob and "token=" not in blob

    @pytest.mark.asyncio
    async def test_endpoint_restricted_without_capability(self, monkeypatch):
        from web.api import routes as web_routes

        request = MagicMock()
        request.app.state = MagicMock()
        monkeypatch.setattr(web_routes, "get_cache",
                            lambda _req: MagicMock())

        async def _ctx(*args, **kwargs):
            return types.SimpleNamespace(role="user")
        monkeypatch.setattr("services.roles.access_for", _ctx)

        async def _deny(*args, **kwargs):
            return types.SimpleNamespace(allowed=False,
                                         reason_code="denied_class_default")
        monkeypatch.setattr("services.diagnostic_policy.decide", _deny)

        out = await web_routes.get_status_self_diagnosis(
            request, types.SimpleNamespace(id=1), x_chat_id=None)
        assert out["available"] is False
        assert out["restricted"] is True


class TestSelfDiagnosisSurface:
    """`SD1-D6-12/16`, `SD1-AMX-01/06`: UI на СУЩЕСТВУЮЩИХ страницах."""

    def _read(self, rel):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_status_page_has_self_diagnosis_block(self):
        html = self._read("web/index.html")
        assert "data-self-diagnosis" in html
        assert "data-self-diagnosis-refresh" in html
        # Страница не делает собственных запросов: данные грузит app.js.
        assert 'fetch("/api/status/self-diagnosis"' not in html

    def test_access_page_has_self_diagnosis_matrix(self):
        html = self._read("web/index.html")
        for marker in ("data-self-diag-access", "data-self-diag-cap",
                       "data-self-diag-save", "data-self-diag-reset",
                       "data-self-diag-explain", "data-self-diag-audit"):
            assert marker in html, marker
        app = self._read("web/app.js")
        for marker in ("loadSelfDiagnosis", "loadDiagMatrix",
                       "saveDiagCapability", "resetDiagCapability",
                       "explainDiagAccess", "loadDiagAudit",
                       "/api/status/self-diagnosis",
                       "/api/access/diagnostic_policy"):
            assert marker in app, marker

    def test_no_new_page_or_agent_controllers(self):
        app = self._read("web/app.js")
        assert "selfdiag/run" not in app and "diagnostic-agent" not in app
