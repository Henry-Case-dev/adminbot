"""ASAP 8 v6 Wave C (D03) — Direct L1 credentials/accounting/temperature.

§18C.1/§18C.6:
  * permission-политика (та же, что у обычных вызовов) ПЕРЕД каждым
    dedicated L1 attempt: no-own-key + global-forbidden → блок
    (sandbox-фраза, LLM не вызывается);
  * exhausted budget → блок;
  * own chat key → попытка разрешена, бюджет НЕ тратится;
  * ОБЕ попытки (первая + repair) учтены (usage-row + бюджет);
  * dedicated temperature реально применяется в payload; провайдер
    отверг temperature → честный retry без неё + флаг unsupported;
  * Inspector (diagnostics snapshot) показывает configured vs applied
    без секретов.

TEST-LIFECYCLE: CONTRACT owner=ASAP8-V6/D03
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import direct_l1 as _l1
from services.llm_client import LLMError, NoApiKeyForChat

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

CHAT_ID = -1001234567890


# ── фейки ────────────────────────────────────────────────────────────────────


class _AuthLLM:
    """Fake LLM с авторизационным seam и per-call payload-записью _post."""

    def __init__(self, *, source="global", auth_error=None,
                 post_error=None, temperature_error=False):
        self.source = source
        self.auth_error = auth_error
        self.post_error = post_error
        self.temperature_error = temperature_error
        self.post_calls = []
        self.generate_calls = []
        self.reported_budget = []

    async def _resolve_api_key_and_source(self, chat_id=None):
        if self.auth_error is not None:
            raise self.auth_error
        return "k", self.source

    async def _post(self, path, payload, *, api_key=None, base_url=None,
                    **kw):
        self.post_calls.append({"payload": payload, "api_key": api_key})
        if self.post_error is not None:
            raise self.post_error
        if self.temperature_error and "temperature" in payload:
            raise LLMError("400 provider: temperature is not supported")
        content = json.dumps({"action": "reply", "confidence": 0.9},
                             ensure_ascii=False)
        resp = MagicMock()
        resp.json = lambda: {"choices": [{"message": {"content": content}}],
                             "usage": {"prompt_tokens": 10,
                                       "completion_tokens": 5}}
        return resp

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kw):
        self.generate_calls.append({"step": step, "temperature": temperature})
        if step == "l1_planner":
            return json.dumps({"action": "reply", "confidence": 0.9},
                              ensure_ascii=False)
        return "финальный ответ"

    def _pg(self):
        return None


def _drive(monkeypatch, llm, text="бот, ответь"):
    import services.direct_chat_service as dcs
    from tests.test_direct_chat import _bot, _make_service, _message, _user
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    svc = _make_service(tool_router=None, llm=llm)
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc._send_direct_answer = AsyncMock(return_value=999)
    svc.remember_bot_reply = AsyncMock()
    react = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", react)
    return svc, react, _bot(), _message(text=text), _user()


def _dedicated_slot(monkeypatch):
    monkeypatch.setattr(
        _l1, "resolve_l1_model",
        lambda chat_id=None, **kw: _l1.L1ModelSlot(
            base_url="https://l1.example", model="l1-model",
            api_key="slot-key", dedicated=True, source="l1"))


# ── §18C.1: permission policy ────────────────────────────────────────────────


class TestAuthorizationPolicy:
    @pytest.mark.asyncio
    async def test_no_own_key_global_forbidden_blocks_dedicated(
            self, monkeypatch):
        """Acceptance 1: no own key + global forbidden → блок; LLM НЕ
        вызывается; песочница content.no_key_reply (R16, не тишина)."""
        llm = _AuthLLM(auth_error=NoApiKeyForChat(CHAT_ID, "forbidden"))
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        assert llm.post_calls == [], "dedicated L1 не должен был вызваться"
        assert llm.generate_calls == []
        svc._send_direct_answer.assert_not_awaited()
        bot.send_message.assert_awaited()      # sandbox-фраза отправлена

    @pytest.mark.asyncio
    async def test_exhausted_budget_blocks(self, monkeypatch):
        """Acceptance 2: exhausted budget → блок по той же политике."""
        llm = _AuthLLM(auth_error=NoApiKeyForChat(CHAT_ID, "budget"))
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        assert llm.post_calls == []
        assert llm.generate_calls == []

    @pytest.mark.asyncio
    async def test_own_chat_key_allows_dedicated(self, monkeypatch):
        """Acceptance 3+4: own chat key → dedicated попытка разрешена
        (транспорт на слоте, не на глобальном ключе)."""
        llm = _AuthLLM(source="chat")
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        assert len(llm.post_calls) == 1
        assert llm.post_calls[0]["api_key"] == "slot-key"
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_authorize_uses_same_resolver_seam(self, monkeypatch):
        """D03: резолв — тот же метод клиента (_resolve_api_key_and_source),
        вызывается с chat_id ПЕРЕД платной попыткой."""
        calls = []

        class _Probe(_AuthLLM):
            async def _resolve_api_key_and_source(self, chat_id=None):
                calls.append(chat_id)
                return "k", "global"

        llm = _Probe()
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        assert calls == [CHAT_ID]
        assert len(llm.post_calls) == 1


# ── §18C.1: usage accounting (обе попытки) ───────────────────────────────────


class TestUsageAccounting:
    @pytest.mark.asyncio
    async def test_repair_attempt_recorded_for_dedicated(
            self, monkeypatch):
        """Acceptance 5: invalid первый план → repair; ОБЕ dedicated
        попытки попали в usage_events.record (step=l1_planner)."""
        recorded = []

        async def fake_record(pg, **kw):
            recorded.append(kw)

        import services.usage_events as ue
        monkeypatch.setattr(ue, "record", fake_record)
        monkeypatch.setattr(ue, "is_enabled", lambda: True)

        class _RepairLLM(_AuthLLM):
            def __init__(self):
                super().__init__(source="chat")
                self._posts = 0

            async def _post(self, path, payload, **kw):
                self._posts += 1
                self.post_calls.append({"payload": payload})
                if self._posts == 1:
                    return self._resp("это вообще не json")
                return self._resp(json.dumps(
                    {"action": "reply", "confidence": 0.9},
                    ensure_ascii=False))

            @staticmethod
            def _resp(content):
                resp = MagicMock()
                resp.json = lambda: {"choices": [{"message": {
                    "content": content}}],
                    "usage": {"prompt_tokens": 10,
                              "completion_tokens": 5}}
                return resp

        llm = _RepairLLM()
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        assert llm._posts == 2, "ровно 1 попытка + 1 repair"
        assert len(recorded) == 2, "обе попытки в usage"
        assert all(r.get("step") == "l1_planner" for r in recorded)
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_global_source_reports_budget(self, monkeypatch):
        """source='global' → попытка списывает бюджет глобального ключа
        (mirror _record_global_usage); source='chat' — НЕ списывает."""
        reported = []

        async def fake_report(pg, chat_id, tokens=0):
            reported.append((chat_id, tokens))

        import services.chat_usage as cu
        monkeypatch.setattr(cu, "report_call", fake_report)
        monkeypatch.setattr(_l1, "_estimate_budget_tokens", None,
                            raising=False)

        llm = _AuthLLM(source="global")
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        assert reported, "global-попытка должна списывать бюджет"

        reported.clear()
        llm2 = _AuthLLM(source="chat")
        _dedicated_slot(monkeypatch)
        svc2, react2, bot2, msg2, user2 = _drive(monkeypatch, llm2)
        await svc2.handle(bot2, msg2, user2)
        assert reported == [], "own-key попытка бюджет НЕ тратит"


# ── §18C.6: temperature ──────────────────────────────────────────────────────


class TestTemperature:
    @pytest.mark.asyncio
    async def test_dedicated_temperature_applied_to_payload(
            self, monkeypatch):
        """Сохранённая dedicated температура реально в payload."""
        monkeypatch.setattr(_l1, "l1_temperature", lambda default=None: 0.4)
        llm = _AuthLLM(source="chat")
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        assert llm.post_calls, "dedicated вызов был"
        assert llm.post_calls[0]["payload"].get("temperature") == 0.4
        diag = _l1.get_l1_diagnostics(CHAT_ID)
        assert diag["temperature_configured"] == 0.4
        assert diag["temperature_applied"] is True

    @pytest.mark.asyncio
    async def test_temperature_unsupported_honest(self, monkeypatch):
        """Провайдер отверг temperature → единственный retry без неё +
        честный флаг unsupported (диагностика configured vs applied)."""
        monkeypatch.setattr(_l1, "l1_temperature", lambda default=None: 0.4)
        llm = _AuthLLM(source="chat", temperature_error=True)
        _dedicated_slot(monkeypatch)
        svc, react, bot, msg, user = _drive(monkeypatch, llm)
        await svc.handle(bot, msg, user)
        temp_calls = [c for c in llm.post_calls
                      if "temperature" in c["payload"]]
        plain_calls = [c for c in llm.post_calls
                       if "temperature" not in c["payload"]]
        assert len(temp_calls) == 1, "первая попытка с температурой"
        assert len(plain_calls) >= 1, "retry без температуры"
        diag = _l1.get_l1_diagnostics(CHAT_ID)
        assert diag["temperature_unsupported"] is True
        assert diag["temperature_applied"] is False
        svc._send_direct_answer.assert_awaited_once()

    def test_plan_meta_carries_temperature_axes(self):
        from services.direct_chat_service import _l1_usage_plan_meta
        plan = _l1.normalize_l1_plan({"action": "reply",
                                      "capabilities_needed": []})
        meta = {"credential_source": "chat",
                "temperature_configured": 0.4,
                "temperature_applied": True,
                "temperature_unsupported": False,
                "planner_fallback_reason": "",
                "required_capability": ""}
        out = _l1_usage_plan_meta(plan, meta, fallback_flag="",
                                  latency_ms=10, input_chars=100)
        assert out["temperature"] == 0.4
        assert out["credential_source"] == "chat"
        assert out["execution_mode"] == "none"
        # sanitize_plan_meta пропускает новые оси (whitelist).
        from services.usage_events import sanitize_plan_meta
        safe = sanitize_plan_meta(out)
        assert safe["temperature"] == 0.4
        assert safe["execution_mode"] == "none"
