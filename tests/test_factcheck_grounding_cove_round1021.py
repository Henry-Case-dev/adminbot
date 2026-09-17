"""F2 (T-1954…T-1958, ADR-1021-2) — интеграция strict grounding + CoVe.

Покрытие:
  * фантомный тег из вердикта вырезается, реальный (из контекста) — остаётся;
  * CoVe-черновик `<reasoning>` срезается, вердикт после `</reasoning>` доходит;
  * пустые допустимые якоря — валидатор не падает и не «изобретает» теги;
  * grounding работает и на Full Tool Access-пути (регресс 10.20);
  * R17: в логах только counts.
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.factcheck_prompts import (
    FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_R1021_SYSTEM_PROMPT,
)
from services.factcheck_service import FactCheckService
from services.llm_client import LLMBadResponseError, LLMChatResult


def _service(raw_answer, search_results="хиты"):
    aggregator = MagicMock()
    aggregator.search = AsyncMock(return_value=search_results)
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=raw_answer)
    return FactCheckService(aggregator, llm), llm


class TestGroundingIntegration:
    @pytest.mark.asyncio
    async def test_phantom_stripped_real_kept(self):
        context = "история: [04.2023 | Автор | fact:2574] всё"
        answer = "вердикт [04.2023 | fact:2574] и бред [01.2099 | fact:777]"
        svc, _ = _service(answer, search_results=context)
        result = await svc.check_claim("текст")
        assert "[04.2023 | fact:2574]" in result
        assert "fact:777" not in result
        assert "01.2099" not in result

    @pytest.mark.asyncio
    async def test_claim_anchor_is_untrusted_and_stripped(self):
        # S10.21-5: `<claim>` — НЕдоверенный источник. Тег, чей id/дата есть
        # только в тексте проверяемого сообщения, вырезается (нельзя
        # протолкнуть фейковый якорь через своё сообщение).
        svc, _ = _service("см. [05.2021 | fact:42]")
        result = await svc.check_claim("тезис [05.2021 | Автор | fact:42]")
        assert "fact:42" not in result

    @pytest.mark.asyncio
    async def test_trusted_search_anchor_kept(self):
        # S10.21-5: якорь из доверенной выдачи поиска (search_results) —
        # сохраняется.
        svc, _ = _service("см. [05.2021 | fact:42]",
                          search_results="источник [05.2021 | Автор | fact:42]")
        result = await svc.check_claim("текст")
        assert "[05.2021 | fact:42]" in result

    @pytest.mark.asyncio
    async def test_no_anchors_phantom_removed_without_crash(self):
        svc, _ = _service("пустой контекст [04.2023 | fact:2574]")
        result = await svc.check_claim("текст")
        assert result.strip() == "пустой контекст"
        assert "fact:2574" not in result

    @pytest.mark.asyncio
    async def test_date_only_tag_stripped_when_not_grounded(self):
        # S10.21-4: метка с датой без fact:ID режется, если даты нет в
        # контексте; голая дата вне метки не трогается.
        svc, _ = _service("верно [04.2024 | Автор: X], это было 04.2024")
        result = await svc.check_claim("текст")
        assert "[04.2024 | Автор: X]" not in result
        assert "04.2024" in result

    @pytest.mark.asyncio
    async def test_grounding_counts_logged_without_content(self, caplog):
        svc, _ = _service("вердикт [01.2099 | fact:777]")
        with caplog.at_level(logging.INFO, logger="services.factcheck_service"):
            await svc.check_claim("текст")
        msgs = [r.message for r in caplog.records]
        assert any("stripped_phantom=1" in m for m in msgs)
        # R17: содержимое вердикта в лог не попадает
        assert not any("fact:777" in m for m in msgs)


class TestCoVeIntegration:
    @pytest.mark.asyncio
    async def test_reasoning_block_sliced_verdict_after(self):
        answer = (
            "<reasoning>\nнайдено: факт A\nсверка: совпало\nнет: ничего\n"
            "</reasoning>\nэто вердикт по существу"
        )
        svc, _ = _service(answer)
        result = await svc.check_claim("текст")
        assert result.strip() == "это вердикт по существу"
        assert "<reasoning>" not in result and "</reasoning>" not in result

    @pytest.mark.asyncio
    async def test_reasoning_only_answer_is_empty(self):
        svc, _ = _service("<reasoning>только черновик</reasoning>")
        with pytest.raises(LLMBadResponseError):
            await svc.check_claim("текст")

    def test_cove_instruction_in_prompt_by_default(self):
        assert "<reasoning>" in FACTCHECK_SYSTEM_PROMPT
        assert "</reasoning>" in FACTCHECK_SYSTEM_PROMPT
        assert "ПОСЛЕ </reasoning>" in FACTCHECK_SYSTEM_PROMPT
        assert "недопустимы" in FACTCHECK_SYSTEM_PROMPT

    def test_prev_r1021_has_no_cove(self):
        assert "<reasoning>" not in PREV_FACTCHECK_R1021_SYSTEM_PROMPT


class _FakeLLM:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def generate_chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self._results.pop(0)

    async def generate(self, messages, **kwargs):  # pragma: no cover
        return "plain"


class _FakeRouter:
    async def dispatch(self, name, arguments, ctx):
        return "ok"


class TestGroundingOnToolAccessPath:
    @pytest.mark.asyncio
    async def test_tool_loop_verdict_grounded(self):
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="[04.2023 | Автор | fact:2574]")
        llm = _FakeLLM([LLMChatResult(
            content="<reasoning>черновик</reasoning>итог [04.2023 | fact:2574] "
                    "и фантом [09.2099 | fact:3]",
            tool_calls=None, finish_reason="stop")])
        svc = FactCheckService(aggregator, llm, tool_router=_FakeRouter())
        result = await svc.check_claim("текст", chat_id=-100)
        assert result.strip() == "итог [04.2023 | fact:2574] и фантом"
        assert "fact:3" not in result
