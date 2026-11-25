"""UR-B acceptance on the LIVE path — что L2 реально получает и что ищется.

Покрывает строки карты `plans/features/unified-reply/requirements-map.json`:

* **UR-07.3** — L2 получает структурированные результаты с источником и
  ограничениями и НЕ приписывает поиску то, чего tool не вернул (пустая выдача
  → «проверки не было», а не «я проверил»; выдуманных источников нет).
  Дата веб-источника вынесена владельцем (11.11.2026) в UR-SRC-DATE и здесь не
  предъявляется.
* **UR-17.7** — на вопрос о доступной информации бот честно описывает
  инструменты (L1 видит РЕАЛЬНЫЙ набор доступных инструментов, выключенный
  инструмент не обещается) и на актуальном внешнем запросе реально использует
  Web Search.
* **UR-17.8** — на «правда, что ИИ тупеет от человеческих запросов?» тема не
  отводится: вопрос доходит до Writer'а, научное утверждение проверяется
  поиском, а при пустой выдаче в payload стоит честная граница знания, а не
  выдуманное исследование.

Все тесты идут ЖИВЫМ путём `DirectChatService.handle` с настоящим
`ToolRouter` и подменным провайдером поиска (0 сети, 0 платных вызовов), и
проверяют фактический L2-payload, а не константы модулей.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-B
"""
import json

import pytest

from services import direct_chat_service as dcs
from services.tool_router import ToolDeps, ToolRouter
from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json
from tests.test_direct_chat import (CHAT_ID, FakeMemory, _bot, _make_service,
                                    _message, _user)

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

CHAT = CHAT_ID


class _Provider:
    """Подменный поисковый провайдер (`SearchAggregator.search`-совместимый)."""

    def __init__(self, text="", *, fail=None):
        self.text = text
        self.fail = fail
        self.queries: list[str] = []

    async def search(self, query, max_symbols=4000, **kw):
        self.queries.append(str(query))
        if self.fail is not None:
            raise self.fail
        return self.text


def _service(provider, llm, *, db=None):
    router = ToolRouter(ToolDeps(search=provider, memory=object()))
    return _make_service(db=db, tool_router=router, llm=llm,
                         memory=FakeMemory(window=[]))


async def _turn(monkeypatch, plan_payload, answer, provider, text,
                *, message_id=100):
    """Один живой прямой ход: план L1 задан, провайдер поиска — двойник."""
    llm = _FakeLLM(l1=json.dumps(plan_payload, ensure_ascii=False), l2=answer)
    svc = _service(provider, llm)
    svc.remember_bot_reply = _async_ok()
    sent: list = []

    async def _send(bot, chat_id, answer_text, reply_to, **kwargs):
        sent.append(str(answer_text))
        return 7300 + len(sent)

    svc._send_direct_answer = _send
    msg = _message(text=text, message_id=message_id)
    await svc.handle(_bot(), msg, _user())
    payload = "".join(str(m.get("content"))
                      for m in llm.last_messages("l2_writer"))
    return svc, llm, payload, sent


def _copy_plan(**over):
    plan = json.loads(_plan_json(**over))
    return plan


def _async_ok():
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=None)


# ── UR-07.3: L2 получает источники + ограничения, не приписывает лишнего ─────

class TestUr073L2EvidenceContract:
    @pytest.mark.asyncio
    async def test_l2_payload_carries_source_status_and_limits(
            self, monkeypatch):
        """Находка поиска доезжает до Writer'а СТРУКТУРНО: блок источника с
        tool/status, и рядом — машинная граница знания; в payload нет URL,
        которых провайдер не возвращал."""
        provider = _Provider(
            "Заголовок статьи\nКороткий факт\nhttps://example.com/real")
        plan = _copy_plan(capabilities_needed=["web_search"],
                          knowledge_origin="open_world",
                          search_intent="required")
        _svc, _llm, payload, sent = await _turn(
            monkeypatch, plan, "ответ по найденному", provider,
            "Бот, что нового про эту модель?")
        assert provider.queries, "актуальный внешний запрос не дошёл до поиска"
        # Структурированный блок источника: tool + статус + выдержка.
        assert "[ИСТОЧНИК 1 | execute_web_search | ok" in payload
        assert "Короткий факт" in payload
        assert "https://example.com/real" in payload
        # Ни одного URL, которого провайдер не отдавал.
        assert "https://example.com/fake" not in payload
        assert sent and sent[0] == "ответ по найденному"

    @pytest.mark.asyncio
    async def test_empty_search_payload_forbids_claiming_checked(
            self, monkeypatch):
        """Пустая выдача: «проверки не было» прямо сказано Writer'у, блока
        источника нет, и «не найдено» не выдаётся за «не существует»."""
        provider = _Provider("")
        plan = _copy_plan(capabilities_needed=["web_search"],
                          knowledge_origin="open_world",
                          search_intent="required",
                          external_claims=[{"entity": "новый вид кита",
                                            "relation": "exists"}])
        _svc, _llm, payload, _sent = await _turn(
            monkeypatch, plan, "честный ответ", provider,
            "Бот, проверь, правда ли, что открыли новый вид кита?")
        assert provider.queries, "обязательная проверка не запускалась"
        # Пустая выдача не выдаётся за найденное: источник помечен ОШИБКОЙ
        # статуса, а не «ok», и содержимого-факта в блоке нет.
        assert "| execute_web_search | error" in payload
        assert "| execute_web_search | ok" not in payload
        assert "не утверждай, что проверил" in payload
        assert "«не найдено» ≠ «не существует»" in payload

    @pytest.mark.asyncio
    async def test_conversation_only_makes_no_network_call_and_no_claim(
            self, monkeypatch):
        """Разговорный вопрос без внешней потребности: сети нет, и в payload
        нет ни источника, ни заявления о проверке."""
        provider = _Provider("НЕ ДОЛЖНО ВЫЗЫВАТЬСЯ")
        plan = _copy_plan(knowledge_origin="conversation_only",
                          search_intent="not_applicable")
        _svc, _llm, payload, _sent = await _turn(
            monkeypatch, plan, "просто ответ", provider,
            "Бот, перескажи нашу шутку про 4 утра")
        assert provider.queries == []
        assert "[ИСТОЧНИК" not in payload
        # Даже если политика пометила проверку невыполненной, заявленного
        # результата поиска в payload нет.
        assert "| execute_web_search | ok" not in payload


# ── UR-17.7: честное описание инструментов + реальный Web Search ─────────────

class TestUr177ToolsHonestAndRealSearch:
    @pytest.mark.asyncio
    async def test_l1_sees_only_tools_that_are_really_available(
            self, monkeypatch):
        """L1 получает РЕАЛЬНЫЙ набор инструментов: выключенный модуль сети в
        списке capability не появляется — бот не обещает то, чего нет."""
        from services import direct_capabilities as caps

        announced = {t["function"]["name"] for t in
                     await dcs.active_tools_for_chat(CHAT, False, False)}
        assert "execute_web_search" in announced

        # Поиск выключен модульным гейтом (прод-путь проверки сети).
        from services import feature_gates

        real_enabled = feature_gates.module_enabled

        async def _search_off(chat_id, *, key, default=True):
            if key == "flags.search_enabled":
                return False
            return await real_enabled(chat_id, key=key, default=default)

        monkeypatch.setattr(feature_gates, "module_enabled", _search_off)
        provider = _Provider("не должно вызываться")
        plan = _copy_plan(capabilities_needed=["web_search"],
                          knowledge_origin="open_world",
                          search_intent="required")
        llm = _FakeLLM(l1=json.dumps(plan, ensure_ascii=False), l2="ответ")
        svc = _service(provider, llm)

        async def _send(bot, chat_id, answer_text, reply_to, **kwargs):
            return 7400

        svc._send_direct_answer = _send
        svc.remember_bot_reply = _async_ok()
        await svc.handle(_bot(), _message(text="Бот, найди в интернете"),
                         _user())
        # Сеть не тронута: инструмент выключен, а не «сделан вид».
        assert provider.queries == []
        # Capability-резолв честно назвал причину (инструмент не исполнен).
        assert caps.CAPABILITY_TOOLS.get("web_search")
        l2_payload = "".join(str(m.get("content"))
                             for m in llm.last_messages("l2_writer"))
        assert "[ИСТОЧНИК" not in l2_payload

    @pytest.mark.asyncio
    async def test_current_external_question_really_searches(
            self, monkeypatch):
        """Актуальный внешний вопрос: один реальный вызов провайдера до L2."""
        provider = _Provider("Свежая новость\nФакт\nhttps://example.com/news")
        plan = _copy_plan(capabilities_needed=["web_search"],
                          knowledge_origin="open_world",
                          search_intent="required")
        _svc, llm, _payload, _sent = await _turn(
            monkeypatch, plan, "ответ", provider,
            "Бот, какие новости про космос сегодня?")
        assert len(provider.queries) == 1, provider.queries
        assert llm.calls_of("l2_writer")

    @pytest.mark.asyncio
    async def test_question_about_own_information_is_not_fake_search(
            self, monkeypatch):
        """«Какой информацией владеешь?» — разговор о себе: поиска нет,
        поэтому описание инструментов не подменяется выдуманной проверкой."""
        provider = _Provider("не должно вызываться")
        plan = _copy_plan(knowledge_origin="conversation_only",
                          search_intent="not_applicable")
        _svc, _llm, payload, _sent = await _turn(
            monkeypatch, plan, "умею искать в интернете и читать память чата",
            provider, "Бот, какой информацией владеешь?")
        assert provider.queries == []
        assert "[ИСТОЧНИК" not in payload


# ── UR-17.8: научное утверждение проверяется, тема не отводится ──────────────

class TestUr178ScientificClaimChecked:
    @pytest.mark.asyncio
    async def test_claim_is_checked_by_search_and_topic_not_deflected(
            self, monkeypatch):
        """«Правда, что ИИ тупеет от человеческих запросов?» — план запросил
        проверку внешнего утверждения: провайдер вызван, Writer получил
        материал, тема не отведена (текст доставлен)."""
        provider = _Provider(
            "Исследование\nЕсть данные о деградации на длинных контекстах\n"
            "https://example.com/research")
        plan = _copy_plan(
            capabilities_needed=["web_search"],
            knowledge_origin="open_world", search_intent="required",
            external_claims=[{"entity": "деградация качества ответов модели",
                              "relation": "exists"}])
        _svc, llm, payload, sent = await _turn(
            monkeypatch, plan, "содержательный разбор вопроса", provider,
            "Бот, правда, что ИИ тупеет от человеческих запросов?",
            message_id=311)
        assert provider.queries, "научное утверждение не проверялось"
        assert "[ИСТОЧНИК 1 | execute_web_search | ok" in payload
        assert llm.calls_of("l2_writer")
        assert sent and sent[0] == "содержательный разбор вопроса"

    @pytest.mark.asyncio
    async def test_no_evidence_means_no_fabricated_research(
            self, monkeypatch):
        """Выдача пуста — payload запрещает заявлять проверку и не содержит
        выдуманных ссылок/исследований."""
        provider = _Provider("")
        plan = _copy_plan(
            capabilities_needed=["web_search"],
            knowledge_origin="open_world", search_intent="required",
            external_claims=[{"entity": "деградация качества ответов модели",
                              "relation": "exists"}])
        _svc, _llm, payload, sent = await _turn(
            monkeypatch, plan, "ответ с границей знания", provider,
            "Бот, правда, что ИИ тупеет от человеческих запросов?",
            message_id=312)
        assert provider.queries
        assert "не утверждай, что проверил" in payload
        assert "http://" not in payload and "https://" not in payload
        assert sent, "тема не должна отводиться молчанием"
