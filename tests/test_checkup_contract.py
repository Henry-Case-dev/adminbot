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


class _FillService:
    """Заглушка `CheckupService` с per-run телеметрией (как реальный сервис).

    Хендлер передаёт СВОЙ словарь `telemetry`; сервис заполняет именно его
    (`SD1-D6-05` B1). Никакого общего `last_run` у заглушки нет.
    """

    def __init__(self, report="отчёт", *, prompt_source="default",
                 prompt_hash="abc123def456"):
        self.report = report
        self.prompt_source = prompt_source
        self.prompt_hash = prompt_hash
        self.calls: list[dict] = []
        self.telemetry_seen: list[dict] = []

    async def checkup(self, logs_text, used_fallback, chat_id=None, *,
                      telemetry=None, tool_runtime=None):
        self.calls.append({"logs": logs_text,
                           "used_fallback": bool(used_fallback),
                           "chat_id": chat_id})
        payload = {
            "prompt_source": self.prompt_source,
            "prompt_hash": self.prompt_hash,
            "prompt_version_used": f"{self.prompt_source}:{self.prompt_hash}",
            "prompt_chars": 42,
            "latency_ms": 7,
            "report_chars": len(self.report),
            "metrics_included": False,
            "input_truncated": False,
            "used_fallback": bool(used_fallback),
            "chat_scoped": chat_id is not None,
        }
        if telemetry is not None:
            telemetry.update(payload)
            self.telemetry_seen.append(dict(telemetry))
        return self.report


def _wire(service, fetcher, collector=None):
    checkup_mod.setup_checkup(service, fetcher, diagnostics=collector)


class TestExplicitCheckupWiring:
    @pytest.mark.asyncio
    async def test_uses_shared_collector_and_keeps_report(self, cleanup):
        service = _FillService(report="отчёт", prompt_source="default",
                               prompt_hash="abc123def456")
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
        assert service.calls == [{
            "logs": "DIAGNOSTIC_EVIDENCE status=ok\nлоги",
            "used_fallback": False, "chat_id": CHAT_ID}]
        # Телеметрия — именно per-run словарь хендлера (B1).
        assert service.telemetry_seen and \
            service.telemetry_seen[0]["prompt_hash"] == "abc123def456"

    @pytest.mark.asyncio
    async def test_collector_failure_does_not_disable_checkup(self, cleanup):
        service = _FillService(report="отчёт по логам")
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        collector = _StubCollector(error=RuntimeError("probe boom"))
        _wire(service, fetcher, collector)

        await checkup_mod.checkup_handler(_make_msg(), bot=AsyncMock())

        assert service.calls == [{"logs": "логи", "used_fallback": False,
                                  "chat_id": CHAT_ID}]

    @pytest.mark.asyncio
    async def test_partial_evidence_is_reported_in_event(self, cleanup,
                                                         monkeypatch):
        captured = []
        monkeypatch.setattr(
            "services.mca_events.emit_mca_event",
            lambda name, **kw: captured.append((name, kw)))
        service = _FillService(report="отчёт", prompt_source="default",
                               prompt_hash="deadbeef1234")
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
        assert payload["prompt_version_used"] == "default:deadbeef1234"
        assert payload["prompt_hash"] == "deadbeef1234"
        # Содержимое промпта/отчёта в телеметрию не попадает.
        assert "отчёт" not in str(raw)

    @pytest.mark.asyncio
    async def test_per_run_telemetry_is_not_shared_between_chats(
            self, cleanup, monkeypatch):
        """B1: два чекапа подряд не видят телеметрию друг друга."""
        captured = []
        monkeypatch.setattr(
            "services.mca_events.emit_mca_event",
            lambda name, **kw: captured.append((name, kw)))
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        service = _FillService(report="отчёт", prompt_hash="aaaa1111")
        _wire(service, fetcher, _StubCollector())
        await checkup_mod.checkup_handler(
            _make_msg(chat_id=-100, user_id=1), bot=AsyncMock())
        service.prompt_hash = "bbbb2222"
        await checkup_mod.checkup_handler(
            _make_msg(chat_id=-200, user_id=2), bot=AsyncMock())

        payloads = []
        for name, fields in captured:
            if name != "checkup_triggered":
                continue
            raw = fields["source_ref_json"]
            payloads.append(json.loads(raw) if isinstance(raw, str)
                            else dict(raw))
        assert [p["prompt_hash"] for p in payloads] == ["aaaa1111",
                                                        "bbbb2222"]

    @pytest.mark.asyncio
    async def test_identity_log_is_machine_only(self, cleanup, caplog):
        service = _FillService(report="отчёт")
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
        service = _FillService(report="отчёт")
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
        service = _FillService()
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

# ── B1–B4 (independent review): регрессии, которые падали на 61e50806 ──────


class _FakeLLM:
    """Захватывает system-сообщения, реально ушедшие в LLM."""

    def __init__(self, report="готово"):
        self.report = report
        self.systems: list[str] = []

    async def generate(self, messages):
        self.systems.append(messages[0]["content"])
        return self.report


def _service(monkeypatch, *, owner=None, report="готово"):
    from services.checkup_service import CheckupService

    llm = _FakeLLM(report=report)
    svc = CheckupService(llm, db=None, memory=None, metrics_enabled=False)

    async def _passthrough(text, chat_id):
        return text
    monkeypatch.setattr(CheckupService, "_apply_outbound_style",
                        staticmethod(_passthrough))
    if owner is not None:
        async def _owner(chat_id):
            return owner(chat_id)
        monkeypatch.setattr("services.checkup_service.speech_owner_block",
                            _owner)
    else:
        async def _none(chat_id):
            return ""
        monkeypatch.setattr("services.checkup_service.speech_owner_block",
                            _none)
    return svc, llm


class TestB1PromptTelemetry:
    """B1: hash/source описывают ФИНАЛЬНЫЙ system, телеметрия per-run."""

    @pytest.mark.asyncio
    async def test_hash_matches_final_system_and_default_source(
            self, monkeypatch):
        svc, llm = _service(monkeypatch)
        telemetry: dict = {}
        await svc.checkup("логи", True, chat_id=None, telemetry=telemetry)

        system = llm.systems[0]
        # Hash — по фактическому system, а не по шаблону с {max_symbols}.
        assert telemetry["prompt_hash"] == hashlib.sha256(
            system.encode("utf-8")).hexdigest()[:16]
        assert telemetry["prompt_chars"] == len(system)
        # В тестовой среде PG-значения нет → кодовый канон = default.
        assert telemetry["prompt_source"] == "default"
        assert telemetry["prompt_version_used"].startswith("default:")
        # Старый дефект: hash шаблона ДО подстановки/приписки.
        assert telemetry["prompt_hash"] != hashlib.sha256(
            CHECKUP_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:16]
        # fallback-notice входит в финальный system.
        from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE
        assert system.endswith(CHECKUP_FALLBACK_NOTICE)

    @pytest.mark.asyncio
    async def test_global_source_follows_resolver(self, monkeypatch):
        svc, llm = _service(monkeypatch)
        monkeypatch.setattr(
            "services.checkup_service.resolve_prompt_with_source",
            lambda key, default: ("effective", "global"))
        telemetry: dict = {}
        await svc.checkup("логи", False, chat_id=None, telemetry=telemetry)
        assert telemetry["prompt_source"] == "global"
        assert telemetry["prompt_hash"] == hashlib.sha256(
            llm.systems[0].encode("utf-8")).hexdigest()[:16]

    @pytest.mark.asyncio
    async def test_two_concurrent_chats_do_not_share_telemetry(
            self, monkeypatch):
        import asyncio

        svc, llm = _service(monkeypatch, owner=lambda chat_id:
                            f"OWNER-{chat_id}")
        t1: dict = {}
        t2: dict = {}
        await asyncio.gather(
            svc.checkup("логи-1", False, chat_id=1, telemetry=t1),
            svc.checkup("логи-2", False, chat_id=2, telemetry=t2))

        systems = llm.systems
        by_chat = {1: [s for s in systems if "OWNER-1" in s],
                   2: [s for s in systems if "OWNER-2" in s]}
        assert by_chat[1] and by_chat[2]
        assert t1["prompt_hash"] == hashlib.sha256(
            by_chat[1][0].encode("utf-8")).hexdigest()[:16]
        assert t2["prompt_hash"] == hashlib.sha256(
            by_chat[2][0].encode("utf-8")).hexdigest()[:16]
        assert t1["prompt_hash"] != t2["prompt_hash"]
        # Сервис больше не держит общий mutable-атрибут телеметрии.
        assert not hasattr(svc, "last_run")

    def test_prompt_readback_allowed_only_on_delivery(self, monkeypatch):
        events: list[str] = []
        monkeypatch.setattr(
            "services.mca_events.emit_mca_event",
            lambda name, **kw: events.append(name))
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        ctx = ToolContext(CHAT_ID, "покажи промпт")

        for ack in ("PROMPT_READBACK status=partial reason=delivery_failed",
                    "PROMPT_READBACK status=invalid_request reason=x",
                    "PROMPT_READBACK status=not_found reason=x",
                    "PROMPT_READBACK status=revision_unavailable reason=x"):
            events.clear()
            router._note_prompt_readback_outcome(ctx, ack)
            assert "prompt_readback_allowed" not in events, ack

        events.clear()
        router._note_prompt_readback_outcome(
            ctx, "PROMPT_READBACK status=delivered destination=reply")
        assert events.count("prompt_readback_allowed") == 1


class TestB2SuccessStatuses:
    """B2: report_sent/called — успех, а не partial."""

    def _rows(self):
        now = int(datetime.datetime.now(
            datetime.timezone.utc).timestamp())

        def row(name, status, *, outcome="success", duration=None):
            return {"event_name": name, "status": status, "outcome": outcome,
                    "duration_ms": duration, "stage": "final", "ts": now}
        return [
            row("checkup_triggered", "report_sent", duration=900),
            row("get_bot_health_called", "called", duration=700),
            row("inspect_runtime_called", "degraded", duration=200),
        ]

    def test_checkup_and_health_are_complete(self):
        from web.api import routes as web_routes
        checkup = web_routes._self_diag_stats(self._rows(), "checkup_triggered")
        health = web_routes._self_diag_stats(self._rows(),
                                             "get_bot_health_called")
        for stats in (checkup, health):
            assert stats["calls"] == 1
            assert stats["complete"] == 1
            assert stats["partial"] == 0
            assert stats["last_success_ts"] is not None
        inspect = web_routes._self_diag_stats(self._rows(),
                                              "inspect_runtime_called")
        assert inspect["complete"] == 0 and inspect["partial"] == 1

    def test_skipped_is_not_a_partial_measurement(self):
        from web.api import routes as web_routes
        rows = [{"event_name": "checkup_triggered", "status": "cooldown",
                 "outcome": "skipped", "duration_ms": None,
                 "stage": "final", "ts": 1},
                {"event_name": "checkup_triggered", "status": "report_sent",
                 "outcome": "success", "duration_ms": 100,
                 "stage": "final", "ts": 2}]
        stats = web_routes._self_diag_stats(rows, "checkup_triggered")
        assert stats["skipped"] == 1
        assert stats["complete"] == 1
        assert stats["partial"] == 0
        assert stats["partial_share"] == 0.0


class TestB3SecretMeasured:
    """B3: `0` только когда enforcement измерен у каждой доставки."""

    def _row(self, name, status, *, stage="", outcome="success"):
        return {"event_name": name, "status": status, "stage": stage,
                "outcome": outcome, "duration_ms": None, "ts": 1}

    def test_unrelated_validation_does_not_make_zero_measured(self):
        from web.api import routes as web_routes
        rows = [self._row("checkup_triggered", "report_sent"),
                self._row("diagnostic_output_validated", "clean",
                          stage="execute_web_search")]
        result = web_routes._self_diag_validation_coverage(rows)
        assert result["measured"] is False
        assert result["value"] is None
        assert result["reason"] == "validation_not_correlated"
        assert result["gaps"]["checkup"] == 1

    def test_delivery_validated_by_dedicated_event_is_measured(self):
        from web.api import routes as web_routes
        rows = [self._row("checkup_triggered", "report_sent"),
                self._row("checkup_output_validated", "clean"),
                self._row("inspect_runtime_called", "ok",
                          stage="deploy.identity"),
                self._row("diagnostic_output_validated", "clean",
                          stage="inspect_runtime")]
        result = web_routes._self_diag_validation_coverage(rows)
        assert result["measured"] is True
        assert result["value"] == 0
        assert result["reason"] == "enforcement_measured"

    def test_no_deliveries_is_not_measured(self):
        from web.api import routes as web_routes
        result = web_routes._self_diag_validation_coverage(
            [self._row("diagnostic_output_validated", "clean",
                       stage="inspect_runtime")])
        assert result["measured"] is False
        assert result["value"] is None
        assert result["reason"] == "no_deliveries_in_window"


class TestB4ConfiguredSources:
    """B4: `configured` каталога считает реальные зависимости среды."""

    @pytest.mark.asyncio
    async def test_configured_reflects_existing_services(self, monkeypatch):
        from web.api import routes as web_routes

        service = MagicMock()
        service.db = object()
        service.memory = object()
        checkup_mod.setup_checkup(service, object(), diagnostics=False)
        deps = checkup_mod.checkup_probe_deps()
        assert deps.db is service.db
        assert deps.memory is service.memory
        assert deps.logs_fetcher is not None

        monkeypatch.setattr("services.lore_runtime.get_lore_db",
                            lambda: None)

        def _identity(root=None, *, process_started_at=None):
            return {"deployed_sha": "deadbeef", "repo_origin": "o/r"}
        monkeypatch.setattr("services.deploy_identity.collect_identity",
                            _identity)
        payload = await web_routes._self_diag_payload(None)
        by_id = {src["id"]: src for src in payload["sources"]}
        assert by_id["media.stt"]["configured"] is True
        assert by_id["scheduler.jobs"]["configured"] is True
        checkup_mod._service = None
        checkup_mod._fetcher = None

    @pytest.mark.asyncio
    async def test_catalog_does_not_execute_probes(self, monkeypatch):
        from web.api import routes as web_routes

        called = {"value": False}

        def _boom(ctx):
            called["value"] = True
            raise AssertionError("probe executed")
        monkeypatch.setattr("services.runtime_probes._probe_service_runtime",
                            _boom)
        monkeypatch.setattr("services.lore_runtime.get_lore_db",
                            lambda: None)

        def _identity(root=None, *, process_started_at=None):
            return {"deployed_sha": "deadbeef"}
        monkeypatch.setattr("services.deploy_identity.collect_identity",
                            _identity)
        payload = await web_routes._self_diag_payload(None)
        assert payload["available"] is True
        assert called["value"] is False


class TestB2B3PayloadEndToEnd:
    """B2/B3 на уровне `/api/status/self-diagnosis`: смешанные события."""

    @pytest.mark.asyncio
    async def test_payload_counts_success_and_never_fakes_zero(
            self, monkeypatch):
        from web.api import routes as web_routes

        mixed = [
            {"event_name": "checkup_triggered", "status": "report_sent",
             "outcome": "success", "duration_ms": 900, "stage": "final",
             "ts": 10},
            {"event_name": "get_bot_health_called", "status": "called",
             "outcome": "success", "duration_ms": 700, "stage": "tool",
             "ts": 11},
            # Посторонний validated от ДРУГОГО инструмента: не доказывает,
            # что чекап прошёл output validation.
            {"event_name": "diagnostic_output_validated", "status": "clean",
             "outcome": "success", "duration_ms": None,
             "stage": "execute_web_search", "ts": 12},
        ]

        async def _rows(db, since, **kwargs):
            return mixed
        monkeypatch.setattr(web_routes, "_self_diag_event_rows", _rows)
        monkeypatch.setattr("services.lore_runtime.get_lore_db",
                            lambda: None)

        def _identity(root=None, *, process_started_at=None):
            return {"deployed_sha": "deadbeef"}
        monkeypatch.setattr("services.deploy_identity.collect_identity",
                            _identity)

        payload = await web_routes._self_diag_payload(None)
        analytics = payload["analytics"]
        assert analytics["checkup"]["complete"] == 1
        assert analytics["checkup"]["partial"] == 0
        assert analytics["get_bot_health"]["complete"] == 1
        assert analytics["checkup"]["last_success_ts"] == 10
        assert "checkup_output_validated" in analytics["event_counts"]
        # Ложного «измеренного 0» быть не может.
        assert analytics["secret_value_disclosures"]["measured"] is False
        assert analytics["secret_value_disclosures"]["value"] is None
        assert analytics["secret_value_disclosures"]["gaps"]["checkup"] == 1

    @pytest.mark.asyncio
    async def test_payload_mixed_validation_is_not_measured(
            self, monkeypatch):
        """B3: посторонний validated не делает чекап «измеренным»."""
        from web.api import routes as web_routes

        mixed = [
            {"event_name": "checkup_triggered", "status": "report_sent",
             "outcome": "success", "duration_ms": 900, "stage": "final",
             "ts": 10},
            {"event_name": "diagnostic_output_validated", "status": "clean",
             "outcome": "success", "duration_ms": None,
             "stage": "execute_web_search", "ts": 12},
        ]

        async def _rows(db, since, **kwargs):
            return mixed
        monkeypatch.setattr(web_routes, "_self_diag_event_rows", _rows)
        monkeypatch.setattr("services.lore_runtime.get_lore_db",
                            lambda: None)

        def _identity(root=None, *, process_started_at=None):
            return {"deployed_sha": "deadbeef"}
        monkeypatch.setattr("services.deploy_identity.collect_identity",
                            _identity)

        payload = await web_routes._self_diag_payload(None)
        secret = payload["analytics"]["secret_value_disclosures"]
        assert secret["measured"] is False
        assert secret["value"] is None
        assert secret["gaps"]["checkup"] == 1


class TestB2ResidualSkippedCalls:
    """B2-residual: skipped не попадает в calls/p50/p95/by_stage."""

    def _row(self, name, status, *, outcome, duration, stage="final", ts=1):
        return {"event_name": name, "status": status, "outcome": outcome,
                "duration_ms": duration, "stage": stage, "ts": ts}

    def test_cooldown_is_not_a_call_or_latency_sample(self):
        from web.api import routes as web_routes
        rows = [self._row("checkup_triggered", "report_sent",
                          outcome="success", duration=900, ts=20),
                self._row("checkup_triggered", "cooldown",
                          outcome="skipped", duration=0, ts=10)]
        stats = web_routes._self_diag_stats(rows, "checkup_triggered")
        assert stats["triggered"] == 2
        assert stats["calls"] == 1
        assert stats["complete"] == 1
        assert stats["partial"] == 0
        assert stats["skipped"] == 1
        assert stats["p50_ms"] == 900
        assert stats["p95_ms"] == 900
        assert stats["partial_share"] == 0.0
        assert [s["calls"] for s in stats["by_stage"]] == [1]

    def test_degraded_inspect_runtime_stays_partial(self):
        from web.api import routes as web_routes
        rows = [self._row("inspect_runtime_called", "degraded",
                          outcome="success", duration=200,
                          stage="logs.errors")]
        stats = web_routes._self_diag_stats(rows, "inspect_runtime_called")
        assert stats["calls"] == 1
        assert stats["complete"] == 0
        assert stats["partial"] == 1
        assert stats["by_stage"][0]["failed"] == 1


class TestB3ResidualBlockedValidation:
    """B3-residual: blocked-валидация не закрывает gap доставки."""

    def _row(self, name, status, *, stage="", outcome="success"):
        return {"event_name": name, "status": status, "stage": stage,
                "outcome": outcome, "duration_ms": None, "ts": 1}

    def test_blocked_checkup_cannot_close_success_gap(self):
        from web.api import routes as web_routes
        rows = [
            self._row("checkup_triggered", "report_sent"),
            self._row("checkup_triggered", "publication_blocked",
                      outcome="failed"),
            self._row("checkup_output_validated", "blocked"),
        ]
        result = web_routes._self_diag_validation_coverage(rows)
        assert result["measured"] is False
        assert result["value"] is None
        assert result["reason"] == "validation_not_correlated"
        assert result["deliveries"]["checkup"] == 1
        assert result["validated"]["checkup"] == 0
        assert result["gaps"]["checkup"] == 1

    def test_paired_allowed_validation_is_measured(self):
        from web.api import routes as web_routes
        rows = [
            self._row("checkup_triggered", "report_sent"),
            self._row("checkup_output_validated", "partially_redacted"),
        ]
        result = web_routes._self_diag_validation_coverage(rows)
        assert result["measured"] is True
        assert result["value"] == 0
        assert result["gaps"] == {}

    def test_handler_emits_status_from_publication_and_skips_blocked(
            self, monkeypatch):
        events = []

        def _emit(name, **kw):
            events.append((name, kw.get("status")))
        monkeypatch.setattr("services.mca_events.emit_mca_event", _emit)

        class _Publication:
            def __init__(self, allowed, status):
                self.allowed = allowed
                self.status = status

        checkup_mod.emit_checkup_validation_event(
            chat_id=CHAT_ID, publication=_Publication(True,
                                                      "partially_redacted"))
        checkup_mod.emit_checkup_validation_event(
            chat_id=CHAT_ID, publication=_Publication(False, "blocked"))
        assert events == [("checkup_output_validated", "partially_redacted")]


@pytest.fixture
def prompt_layers():
    """Изоляция реальных слоёв prompt-readback (D5) без сети/PG."""
    from services import chat_params
    from services import prompt_registry as pr
    from services import telegram_role_check as role_check

    chat_params.set_chat_params_cache(None)
    pr.reset_cache()
    role_check.reset_cache()
    yield
    chat_params.set_chat_params_cache(None)
    pr.reset_cache()
    role_check.reset_cache()


class TestPromptReadbackAllowedDispatch:
    """Blocker: реальный `ToolRouter.dispatch` с РАЗРЕШЁННОЙ идентичностью.

    Проверяется не «deny без identity», а полный путь: политика разрешает
    `prompts.view` владельцу, handler D5 собирает реальный промпт из
    существующего реестра, отправляет его в чат, и только ПОСЛЕ фактической
    отправки эмитится `prompt_readback_allowed`.
    """

    def _router(self):
        return ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))

    @pytest.mark.asyncio
    async def test_allowed_owner_gets_real_prompt_after_policy(
            self, monkeypatch, prompt_layers):
        from services import chat_params
        from services import hot_config as hot
        from services import prompt_readback as readback_srv
        from services import prompt_registry as pr
        from tests.test_prompt_readback import (FakeBot, FakeCache,
                                                FakeChatStore, GROUP,
                                                OWNER_ID, TEST_BLOCK,
                                                _request)

        chat_params.set_chat_params_cache(FakeChatStore())
        cache = FakeCache({OWNER_ID: "global_admin"})
        monkeypatch.setattr(hot, "get_config_cache", lambda: cache)

        bot = FakeBot({})
        events: list[tuple] = []

        def _emit(name, **kwargs):
            events.append((name, len(bot.sent), kwargs.get("status")))
        monkeypatch.setattr("services.mca_events.emit_mca_event", _emit)

        ctx = ToolContext(GROUP, query="", bot=bot, user_id=OWNER_ID,
                          reply_to_message_id=101)
        out = await self._router().dispatch("prompt_readback", _request(), ctx)

        # 1) Реальный prompt/delivery, а не unknown/denied.
        assert "неизвестный инструмент" not in out
        assert "status=delivered" in out
        assert "prompt_id=" + TEST_BLOCK in out
        assert "denied" not in out
        # 2) В чат ушёл ИМЕННО эффективный промпт существующего реестра.
        assert len(bot.sent) == 1
        expected = pr.effective_prompt(TEST_BLOCK)
        assert readback_srv.payload_body(bot.sent[0]["text"]) == expected.text
        assert "revision=" + expected.revision in out
        assert "source=factory_default" in out
        # 3) allowed — только ПОСЛЕ фактической отправки (sent=1), requested —
        #    до неё (sent=0); ровно одно allowed-событие.
        requested = [row for row in events
                     if row[0] == "prompt_readback_requested"]
        allowed = [row for row in events if row[0] == "prompt_readback_allowed"]
        assert requested and requested[0][1] == 0
        assert len(allowed) == 1
        assert allowed[0][1] == 1
        assert ctx.tool_result_signal.get("status") != "denied"

    @pytest.mark.asyncio
    async def test_member_dispatch_is_denied_and_not_counted_allowed(
            self, monkeypatch, prompt_layers):
        from services import chat_params
        from services import hot_config as hot
        from tests.test_prompt_readback import (FakeBot, FakeCache,
                                                FakeChatStore, GROUP,
                                                MEMBER_ID, _request)

        chat_params.set_chat_params_cache(FakeChatStore())
        cache = FakeCache({})
        monkeypatch.setattr(hot, "get_config_cache", lambda: cache)

        bot = FakeBot({(GROUP, MEMBER_ID): "member"})
        events: list[tuple] = []

        def _emit(name, **kwargs):
            events.append((name, len(bot.sent), kwargs.get("status")))
        monkeypatch.setattr("services.mca_events.emit_mca_event", _emit)

        ctx = ToolContext(GROUP, query="", bot=bot, user_id=MEMBER_ID,
                          reply_to_message_id=101)
        out = await self._router().dispatch("prompt_readback", _request(), ctx)

        assert "неизвестный инструмент" not in out
        assert "status=delivered" not in out
        assert "denied_prompt_content_member" in out
        assert bot.sent == []
        assert not [row for row in events
                    if row[0] == "prompt_readback_allowed"]
        # Отказ происходит ДО исполнения инструмента: сигнала нет вовсе,
        # запрос даже не дошёл до handler'а (requested не эмитится).
        assert ctx.tool_result_signal is None
        assert not [row for row in events
                    if row[0] == "prompt_readback_requested"]
