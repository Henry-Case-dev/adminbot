"""F4 (T-2044…T-2052 + T-2095, ADR-1022-4) — саммари: 2 вызова.

Покрытие: Редактор → Markdown-выжимка; Рассказчик видит ТОЛЬКО выжимку;
невалидный digest (теги/пустота) → fallback; validator-loop; kill-switch.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services.prompt_style_blocks import compose_verbalizer_system
from services.summary_generator import SummaryGenerator
from services.summary_prompts import (
    SUMMARY_EDITOR_SYSTEM_PROMPT,
    SUMMARY_NARRATOR_SYSTEM_PROMPT,
)

pytestmark = pytest.mark.system2

_DIGEST = "# Событие\n- Вася спорил с Петей про футбол"


def _generator(side_effect):
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=side_effect)
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                           bot=None)
    return gen, llm


class TestSummaryTwoCall:
    @pytest.mark.asyncio
    async def test_editor_then_narrator(self):
        gen, llm = _generator([_DIGEST, "связный саркастичный текст"])
        text = await gen._generate_two_call("сырая история", 3800, -100)
        assert text == "связный саркастичный текст"
        assert llm.generate.await_count == 2
        stage1 = llm.generate.await_args_list[0].args[0]
        stage2 = llm.generate.await_args_list[1].args[0]
        assert stage1[0]["content"] == SUMMARY_EDITOR_SYSTEM_PROMPT
        assert stage1[1]["content"] == "сырая история"
        assert stage2[0]["content"] == compose_verbalizer_system(
            SUMMARY_NARRATOR_SYSTEM_PROMPT.replace("{max_symbols}", "3800"),
            "serious", "plain")
        assert stage2[1]["content"] == "ВЫЖИМКА (Markdown):\n" + _DIGEST

    @pytest.mark.asyncio
    async def test_llm_generate_logs_no_raw_text(self, caplog):
        """S10.22-8 (R17): ответ LLM не попадает в INFO-лог — только числа."""
        secret = "СЕКРЕТНЫЙ_СЫРОЙ_ОТВЕТ_LLM_42"
        gen, _llm = _generator(["  " + secret + "  "])
        with caplog.at_level("INFO"):
            raw = await gen._llm_generate(
                [{"role": "user", "content": "x"}], -100)
        assert raw == "  " + secret + "  "
        assert secret not in caplog.text
        assert "len=" in caplog.text

    @pytest.mark.asyncio
    async def test_narrator_isolated_from_raw_history(self):
        gen, llm = _generator([_DIGEST, "текст"])
        await gen._generate_two_call("СЕКРЕТНАЯ СЫРАЯ ИСТОРИЯ", 3800, -100)
        stage2_user = llm.generate.await_args_list[1].args[0][1]["content"]
        assert "СЕКРЕТНАЯ" not in stage2_user

    @pytest.mark.asyncio
    async def test_invalid_digest_returns_none(self):
        gen, llm = _generator(["# мусор fact:12", "не должно вызваться"])
        assert await gen._generate_two_call("история", 3800, -100) is None
        assert llm.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_empty_digest_returns_none(self):
        gen, llm = _generator(["   "])
        assert await gen._generate_two_call("история", 3800, -100) is None
        assert llm.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_validator_loop_retry(self):
        gen, llm = _generator([_DIGEST, "как ИИ отвечаю", "чистый текст"])
        text = await gen._generate_two_call("история", 3800, -100)
        assert text == "чистый текст"
        assert llm.generate.await_count == 3

    @pytest.mark.asyncio
    async def test_validator_exhausted_returns_best(self):
        gen, llm = _generator([
            _DIGEST, "как ИИ и подводя итог", "подводя итог", "в заключение"])
        text = await gen._generate_two_call("история", 3800, -100)
        assert text == "подводя итог"      # лучший вариант (fail-open)
        assert llm.generate.await_count == 4

    @pytest.mark.asyncio
    async def test_empty_narrator_returns_none(self):
        gen, _llm = _generator([_DIGEST, "   "])
        assert await gen._generate_two_call("история", 3800, -100) is None


class TestSummaryRunBranchOn:
    """Ревью (High-3): прод-путь с флагами ON — ветвление `_run`, постфикс,
    доставка (был вакуумный `assert ... is False`)."""

    @pytest.mark.asyncio
    async def test_run_on_branch_two_call_postfix_and_delivery(
            self, monkeypatch):
        from services.summary_xml import XmlGroundingBuilder
        from tests.test_summary_generator import FakeMemory, _row

        assert Settings.SYSTEM2_SUMMARY_ENABLED is True   # прод-дефолт ON
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)

        class TwoCallLLM:
            def __init__(self):
                self.calls = 0

            async def generate(self, messages):
                self.calls += 1
                return _DIGEST if self.calls == 1 else "связный дерзкий рассказ"

        delivered: list = []

        async def _capture(self, chat_id, text):
            delivered.append(text)

        monkeypatch.setattr(SummaryGenerator, "_send_streaming", _capture)
        monkeypatch.setattr(SummaryGenerator, "_send_chunked", _capture)

        gen = SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                               XmlGroundingBuilder(), TwoCallLLM(), AsyncMock())
        await gen._run(-100, False)
        assert gen.llm.calls == 2          # Редактор + Рассказчик
        assert delivered and "связный дерзкий рассказ" in delivered[0]
        assert "самым главным шизом объявляется" in delivered[0]

    @pytest.mark.asyncio
    async def test_run_off_branch_single_call(self, monkeypatch):
        from services.summary_xml import XmlGroundingBuilder
        from tests.test_summary_generator import FakeMemory, _row

        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)

        class OneCallLLM:
            def __init__(self):
                self.calls = 0

            async def generate(self, messages):
                self.calls += 1
                return "одиночный текст"

        delivered: list = []

        async def _capture(self, chat_id, text):
            delivered.append(text)

        monkeypatch.setattr(SummaryGenerator, "_send_streaming", _capture)
        monkeypatch.setattr(SummaryGenerator, "_send_chunked", _capture)

        gen = SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                               XmlGroundingBuilder(), OneCallLLM(), AsyncMock())
        await gen._run(-100, False)
        assert gen.llm.calls == 1          # OFF → одиночный путь 10.21
        assert delivered and "одиночный текст" in delivered[0]
