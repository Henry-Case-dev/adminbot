"""F3 (раунд 10.23, ADR-1023-3) — умный Вербализатор: 3 режима + каналы.

Покрытие:
  * роутер `response_mode` строго в Stage-1: enum, нормализатор с fail-safe
    `serious`, поле в трёх JSON-контрактах, backward-compatible обёртка
    `validate_summary_digest`;
  * выбор `MODE_*_BLOCK` по режиму и канального `FORMAT_*_BLOCK` по каналу;
  * типографика (общий `TYPOGRAPHY_BLOCK`) во всех Stage-2 канонах;
  * канальные правила: `plain_no_tables` активен на plain, не активен на rich;
    таблицы в plain бракуются/регенерируются, буллиты в deep_research живы;
  * safe-HTML доставка direct `deep_research` (fallback при TelegramBadRequest);
  * число LLM-вызовов Stage-1+Stage-2 = 2 (роутер не добавляет вызов);
  * kill-switch `SMART_VERBALIZER_MODES_ENABLED=false` → прежний Вербализатор;
  * канон-миграция F3: слепки, ступени migrate/rollback.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from config.settings import Settings
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    PREV_FACTCHECK_ANALYST_R1023_F3,
    PREV_FACTCHECK_VERBALIZER_R1023,
    FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
)
from services.chat_prompts import (
    DIRECT_SYNTHESIZER_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
    PREV_CHAT_VERBALIZER_R1023,
    PREV_DIRECT_SYNTHESIZER_R1023,
)
from services.negative_constraints import (
    channel_enabled_rules,
    detect_plain_tables,
    find_forbidden_cliches,
    verbalize_validated,
)
from services.prompt_style_blocks import (
    FORMAT_PLAIN_BLOCK,
    FORMAT_PLAIN_TEXT_BLOCK,
    FORMAT_RICH_BLOCK,
    MODE_CASUAL_BLOCK,
    MODE_DEEP_RESEARCH_BLOCK,
    MODE_SERIOUS_BLOCK,
    TYPOGRAPHY_BLOCK,
    compose_verbalizer_system,
)
from services.summary_generator import SummaryGenerator
from services.summary_prompts import (
    PREV_SUMMARY_EDITOR_R1023_F3,
    PREV_SUMMARY_NARRATOR_R1023,
    SUMMARY_EDITOR_SYSTEM_PROMPT,
    SUMMARY_NARRATOR_SYSTEM_PROMPT,
)
from services.system2_handoff import (
    RESPONSE_MODES,
    normalize_response_mode,
    parse_direct_synthesis,
    parse_factcheck_analysis,
    parse_summary_handoff,
    validate_summary_digest,
)

pytestmark = pytest.mark.system2

_DIGEST = "# Событие\n- Вася спорил с Петей про футбол"


def _factcheck_json(mode=None):
    data = {
        "claim": "земля плоская",
        "findings": [{"assertion": "земля плоская", "status": "false",
                      "human_time": "в августе", "author": "Вася",
                      "evidence": "спутники и фото"}],
        "verdict": "полный бред",
    }
    if mode is not None:
        data["response_mode"] = mode
    return json.dumps(data)


def _direct_json(mode=None):
    data = {
        "user_question": "что там с погодой",
        "facts": [{"topic": "погода", "finding": "завтра дождь",
                   "source": "exa", "confidence": "high"}],
        "answer_outline": "взять зонт",
        "limitations": [],
    }
    if mode is not None:
        data["response_mode"] = mode
    return json.dumps(data)


# ── A. Роутер response_mode (Stage-1) ────────────────────────────────

class TestResponseModeRouter:
    def test_enum(self):
        assert RESPONSE_MODES == ("casual", "serious", "deep_research")

    @pytest.mark.parametrize("value,expected", [
        ("casual", "casual"),
        ("serious", "serious"),
        ("deep_research", "deep_research"),
        (" Deep_Research ", "deep_research"),
        ("bogus", "serious"),
        ("", "serious"),
        (None, "serious"),
        (42, "serious"),
    ])
    def test_normalize_fail_safe(self, value, expected):
        assert normalize_response_mode(value) == expected

    def test_factcheck_analysis_keeps_mode(self):
        data = parse_factcheck_analysis(_factcheck_json("casual"))
        assert data is not None and data["response_mode"] == "casual"

    def test_factcheck_analysis_missing_or_invalid_is_serious(self):
        assert parse_factcheck_analysis(_factcheck_json())["response_mode"] == "serious"
        assert parse_factcheck_analysis(
            _factcheck_json("wat"))["response_mode"] == "serious"

    def test_direct_synthesis_keeps_mode(self):
        data = parse_direct_synthesis(_direct_json("deep_research"))
        assert data is not None and data["response_mode"] == "deep_research"
        assert parse_direct_synthesis(_direct_json())["response_mode"] == "serious"

    def test_parse_summary_handoff_json(self):
        raw = json.dumps({"response_mode": "deep_research", "digest": _DIGEST})
        parsed = parse_summary_handoff(raw)
        assert parsed == {"response_mode": "deep_research", "digest": _DIGEST,
                          "cover_prompt": ""}

    def test_parse_summary_handoff_missing_mode_serious(self):
        raw = json.dumps({"digest": _DIGEST})
        assert parse_summary_handoff(raw)["response_mode"] == "serious"

    def test_parse_summary_handoff_invalid_mode_serious(self):
        raw = json.dumps({"response_mode": "wat", "digest": _DIGEST})
        assert parse_summary_handoff(raw)["response_mode"] == "serious"

    def test_parse_summary_handoff_raw_markdown_backcompat(self):
        """Старый Stage-1 отдавал чистую Markdown-выжимку."""
        parsed = parse_summary_handoff(_DIGEST)
        assert parsed == {"response_mode": "serious", "digest": _DIGEST,
                          "cover_prompt": ""}

    def test_parse_summary_handoff_invalid_digest_none(self):
        raw = json.dumps({"response_mode": "casual", "digest": "мусор fact:12"})
        assert parse_summary_handoff(raw) is None
        assert parse_summary_handoff("   ") is None

    def test_validate_summary_digest_wrapper(self):
        assert validate_summary_digest(_DIGEST) == _DIGEST
        raw = json.dumps({"response_mode": "casual", "digest": _DIGEST})
        assert validate_summary_digest(raw) == _DIGEST
        assert validate_summary_digest("fact:12") is None


# ── B. Промпт-блоки: режим и канал ───────────────────────────────────

class TestModeAndFormatBlocks:
    def test_stage2_canons_carry_typography(self):
        for prompt in (SUMMARY_NARRATOR_SYSTEM_PROMPT,
                       FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
                       DIRECT_VERBALIZER_SYSTEM_PROMPT):
            assert TYPOGRAPHY_BLOCK in prompt

    def test_prev_snapshots_are_pre_f3(self):
        assert PREV_SUMMARY_NARRATOR_R1023 != SUMMARY_NARRATOR_SYSTEM_PROMPT
        assert PREV_FACTCHECK_VERBALIZER_R1023 != FACTCHECK_VERBALIZER_SYSTEM_PROMPT
        assert PREV_CHAT_VERBALIZER_R1023 != DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert TYPOGRAPHY_BLOCK not in PREV_SUMMARY_NARRATOR_R1023

    def test_stage1_canons_request_response_mode(self):
        assert "response_mode" in SUMMARY_EDITOR_SYSTEM_PROMPT
        assert "response_mode" in FACTCHECK_ANALYST_SYSTEM_PROMPT
        assert "response_mode" in DIRECT_SYNTHESIZER_SYSTEM_PROMPT
        assert PREV_SUMMARY_EDITOR_R1023_F3 != SUMMARY_EDITOR_SYSTEM_PROMPT
        assert PREV_FACTCHECK_ANALYST_R1023_F3 != FACTCHECK_ANALYST_SYSTEM_PROMPT
        assert PREV_DIRECT_SYNTHESIZER_R1023 != DIRECT_SYNTHESIZER_SYSTEM_PROMPT

    @pytest.mark.parametrize("mode,block", [
        ("casual", MODE_CASUAL_BLOCK),
        ("serious", MODE_SERIOUS_BLOCK),
        ("deep_research", MODE_DEEP_RESEARCH_BLOCK),
    ])
    def test_compose_selects_mode_block(self, mode, block):
        composed = compose_verbalizer_system("BASE", mode, "plain")
        assert block in composed

    def test_compose_casual_has_no_markdown_format_block(self):
        composed = compose_verbalizer_system("BASE", "casual", "plain")
        assert FORMAT_PLAIN_BLOCK not in composed
        assert FORMAT_PLAIN_TEXT_BLOCK not in composed
        assert FORMAT_RICH_BLOCK not in composed

    def test_compose_deep_plain_text_default_no_html(self):
        """Review iter1 (H2): plain без HTML-доставки → text-only блок."""
        composed = compose_verbalizer_system("BASE", "deep_research", "plain")
        assert FORMAT_PLAIN_TEXT_BLOCK in composed
        assert FORMAT_PLAIN_BLOCK not in composed
        assert FORMAT_RICH_BLOCK not in composed

    def test_compose_deep_plain_html_safe_requires_bold(self):
        composed = compose_verbalizer_system(
            "BASE", "deep_research", "plain", html_safe=True)
        assert FORMAT_PLAIN_BLOCK in composed
        assert FORMAT_PLAIN_TEXT_BLOCK not in composed
        assert FORMAT_RICH_BLOCK not in composed

    def test_compose_deep_rich_allows_everything(self):
        composed = compose_verbalizer_system("BASE", "deep_research", "rich")
        assert FORMAT_RICH_BLOCK in composed
        assert FORMAT_PLAIN_BLOCK not in composed
        assert FORMAT_PLAIN_TEXT_BLOCK not in composed

    def test_compose_unknown_mode_fail_safe_serious(self):
        assert MODE_SERIOUS_BLOCK in compose_verbalizer_system("BASE", "wat")


class TestDeepResearchPromptConsistency:
    """Review iter1 (H1): в собранном deep_research нет одновременного
    запрета и требования буллитов."""

    @pytest.mark.parametrize("base", [
        SUMMARY_NARRATOR_SYSTEM_PROMPT,
        FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
        DIRECT_VERBALIZER_SYSTEM_PROMPT,
    ])
    def test_no_bullet_ban_in_deep_research(self, base):
        composed = compose_verbalizer_system(base, "deep_research", "plain")
        # безусловный запрет списков из ANTI_BOT п.4 снят
        assert ("4. Списки с буллитами и нумерованные перечни в самом ответе."
                not in composed)
        # R11-запрет «только сплошной текст» снят (только у Рассказчика)
        assert ("2. Не выводи Markdown, списки, пункты и эмодзи: только "
                "сплошной текст" not in composed)
        # при этом перечисления буллитами разрешены/требуются
        assert "буллит" in composed.lower()

    def test_ban_kept_for_casual_and_serious(self):
        for mode in ("casual", "serious"):
            composed = compose_verbalizer_system(
                SUMMARY_NARRATOR_SYSTEM_PROMPT, mode, "plain")
            assert ("4. Списки с буллитами и нумерованные перечни в самом ответе."
                    in composed)


# ── C. Guard plain_no_tables и набор правил по каналу ────────────────

class TestPlainTableGuard:
    @pytest.mark.parametrize("text", [
        "<table><tr><td>x</td></tr></table>",          # HTML
        "+---+---+",                                   # ASCII-сетка
        "|---|---|",                                    # separator
        "шапка\n| col1 | col2 |\n|---|---|",           # Markdown с separator
        "| a | b |\n| c | d |",                        # ≥2 pipe-строк подряд
        "| a | b |\n|---|",                            # шапка + separator
        "a | b\n1 | 2",                                # 2 pipe-строки без внешних |
    ])
    def test_detect_true(self, text):
        assert detect_plain_tables(text) is True

    @pytest.mark.parametrize("text", [
        "",
        "обычный текст без таблиц",
        "- буллит один\n- буллит два",
        "дефис - и тире - не таблица",
        # Review iter2 (M5): одиночный `|` — НЕ таблица (контекстная детекция).
        "Команда: cat file | grep error",
        "a|b",
        "5|10",
        "сигнал|шум",
        "| a | b |",
        "a | b",
        "a | b | c",
    ])
    def test_detect_false_clean(self, text):
        assert detect_plain_tables(text) is False

    def test_rule_uses_detector_context_sensitive(self):
        """M2/M5: правило идёт через детектор; одиночный `|` не бракуется,
        реальная таблица с разделителем — бракуется."""
        assert detect_plain_tables("a | b") is False
        assert find_forbidden_cliches(
            "a | b", enabled_rules={"plain_no_tables"}) == []
        assert find_forbidden_cliches(
            "Команда: cat file | grep error",
            enabled_rules={"plain_no_tables"}) == []
        table = "| a | b |\n|---|---|"
        assert find_forbidden_cliches(
            table, enabled_rules={"plain_no_tables"}) == ["plain_no_tables"]

    def test_rule_only_when_enabled(self):
        table = "| a | b |\n|---|---|"
        assert find_forbidden_cliches(table) == []
        assert find_forbidden_cliches(
            table, enabled_rules={"plain_no_tables"}) == ["plain_no_tables"]

    def test_plain_rules_include_guard_rich_do_not(self):
        plain = channel_enabled_rules("plain", "serious")
        rich = channel_enabled_rules("rich", "deep_research")
        assert "plain_no_tables" in plain
        assert "plain_no_tables" not in rich

    def test_deep_research_plain_allows_bullets(self):
        rules = channel_enabled_rules("plain", "deep_research",
                                      forbid_bullets=True)
        assert "plain_no_tables" in rules
        assert "bullet_list" not in rules
        summary_serious = channel_enabled_rules("plain", "serious",
                                                forbid_bullets=True)
        assert "bullet_list" in summary_serious

    @pytest.mark.asyncio
    async def test_table_in_plain_rejected_and_regenerated(self):
        gen = AsyncMock(side_effect=["| a | b |\n|---|---|", "чистый ответ"])
        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            enabled_rules=channel_enabled_rules("plain", "deep_research"))
        assert text == "чистый ответ"
        assert gen.await_count == 2
        assert stats["fallback"] is False

    @pytest.mark.asyncio
    async def test_table_in_rich_not_rejected(self):
        gen = AsyncMock(return_value="| a | b |\n|---|---|")
        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            enabled_rules=channel_enabled_rules("rich", "deep_research"))
        assert text == "| a | b |\n|---|---|"
        assert gen.await_count == 1
        assert stats["fallback"] is False


# ── D. Интеграция Stage-1 → Stage-2 ──────────────────────────────────

def _summary_generator(side_effect):
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=side_effect)
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                           bot=None)
    return gen, llm


class TestTwoCallModes:
    @pytest.mark.asyncio
    async def test_summary_deep_research_plain_bullets(self):
        editor = json.dumps({"response_mode": "deep_research", "digest": _DIGEST})
        gen, llm = _summary_generator([editor, "- пункт один\n- пункт два"])
        draft = await gen._generate_two_call("сырая история", 3800, -100)
        # буллиты живы в deep_research (F6: результат — SummaryDraft)
        assert draft.text == "- пункт один\n- пункт два"
        assert llm.generate.await_count == 2          # роутер не добавил вызов
        stage2_system = llm.generate.await_args_list[1].args[0][0]["content"]
        assert MODE_DEEP_RESEARCH_BLOCK in stage2_system
        assert FORMAT_PLAIN_TEXT_BLOCK in stage2_system   # канал text-only
        assert FORMAT_PLAIN_BLOCK not in stage2_system
        assert FORMAT_RICH_BLOCK not in stage2_system

    @pytest.mark.asyncio
    async def test_summary_casual_mode_block(self):
        editor = json.dumps({"response_mode": "casual", "digest": _DIGEST})
        gen, llm = _summary_generator([editor, "ну короче вася опять спорил"])
        await gen._generate_two_call("сырая история", 3800, -100)
        stage2_system = llm.generate.await_args_list[1].args[0][0]["content"]
        assert MODE_CASUAL_BLOCK in stage2_system
        assert FORMAT_PLAIN_BLOCK not in stage2_system

    @pytest.mark.asyncio
    async def test_summary_plain_table_regenerated(self):
        editor = json.dumps({"response_mode": "deep_research", "digest": _DIGEST})
        gen, llm = _summary_generator([
            editor, "| a | b |\n|---|---|", "чистый текст без таблиц"])
        draft = await gen._generate_two_call("сырая история", 3800, -100)
        assert draft.text == "чистый текст без таблиц"
        assert llm.generate.await_count == 3

    @pytest.mark.asyncio
    async def test_summary_kill_switch_off_prev_narrator(self, monkeypatch):
        monkeypatch.setattr(Settings, "SMART_VERBALIZER_MODES_ENABLED", False)
        editor = json.dumps({"response_mode": "deep_research", "digest": _DIGEST})
        gen, llm = _summary_generator([editor, "прежний текст"])
        await gen._generate_two_call("сырая история", 3800, -100)
        stage2_system = llm.generate.await_args_list[1].args[0][0]["content"]
        assert stage2_system == PREV_SUMMARY_NARRATOR_R1023.replace(
            "{max_symbols}", "3800")
        assert TYPOGRAPHY_BLOCK not in stage2_system


class TestFactcheckTwoCallMode:
    @pytest.mark.asyncio
    async def test_casual_mode_selected(self):
        from services.factcheck_service import FactCheckService
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(
            side_effect=[_factcheck_json("casual"), "дерзкий ответ"])
        service = FactCheckService(aggregator, llm)
        result = await service.check_claim("тезис")
        assert result == "дерзкий ответ"
        stage2_system = llm.generate.await_args_list[1].args[0][0]["content"]
        assert MODE_CASUAL_BLOCK in stage2_system
        assert FORMAT_RICH_BLOCK not in stage2_system
        assert llm.generate.await_count == 2


class TestDirectTwoCallMode:
    @staticmethod
    def _service(side_effect):
        from services.direct_chat_service import DirectChatService
        svc = DirectChatService.__new__(DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=side_effect)
        return svc

    @staticmethod
    def _raw():
        from services.tool_loop import ToolLoopResult
        return ToolLoopResult(
            "финал tool-loop", rounds_used=2,
            tool_trace=[{"round": 1, "tool": "execute_web_search", "ok": True,
                         "out_chars": 20}],
            tool_context="сырые логи")

    @pytest.mark.asyncio
    async def test_mode_returned_and_prompt_composed(self):
        svc = self._service([_direct_json("deep_research"), "разбор"])
        text, mode = await svc._synthesize_direct_answer(
            -100, "что там", self._raw(), None)
        assert (text, mode) == ("разбор", "deep_research")
        stage2_system = svc.llm.generate.await_args_list[1].args[0][0]["content"]
        assert MODE_DEEP_RESEARCH_BLOCK in stage2_system
        assert FORMAT_PLAIN_BLOCK in stage2_system

    @pytest.mark.asyncio
    async def test_kill_switch_off_forces_serious_and_no_html_block(
            self, monkeypatch):
        """Review iter1 (M1): OFF → режим serious, доставка не уходит safe-HTML."""
        monkeypatch.setattr(Settings, "SMART_VERBALIZER_MODES_ENABLED", False)
        svc = self._service([_direct_json("deep_research"), "ответ"])
        text, mode = await svc._synthesize_direct_answer(
            -100, "q", self._raw(), None)
        assert (text, mode) == ("ответ", "serious")
        stage2_system = svc.llm.generate.await_args_list[1].args[0][0]["content"]
        assert stage2_system == PREV_CHAT_VERBALIZER_R1023
        assert MODE_DEEP_RESEARCH_BLOCK not in stage2_system


# ── E. Финальная доставка без сырого HTML (H2) ──────────────────────

class TestFinalDeliveryNoHtml:
    @pytest.mark.asyncio
    async def test_summary_run_strips_html_bold(self, monkeypatch):
        """Review iter1 (H2): саммари не рендерит HTML — `<b>` не должен
        доехать до пользователя сырым ни в одном режиме."""
        from services.summary_xml import XmlGroundingBuilder
        from tests.test_summary_generator import FakeMemory, _row

        editor = json.dumps({"response_mode": "deep_research", "digest": _DIGEST})

        class TwoCallLLM:
            def __init__(self):
                self.calls = 0

            async def generate(self, messages):
                self.calls += 1
                return (editor if self.calls == 1
                        else "<b>жирный</b> разбор без таблиц")

        delivered: list = []

        async def _capture(self, chat_id, text):
            delivered.append(text)

        monkeypatch.setattr(SummaryGenerator, "_send_streaming", _capture)
        monkeypatch.setattr(SummaryGenerator, "_send_chunked", _capture)
        gen = SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                               XmlGroundingBuilder(), TwoCallLLM(), AsyncMock())
        await gen._run(-100, False)
        assert delivered
        assert "<b>" not in delivered[0]
        assert "жирный" in delivered[0]

    @pytest.mark.asyncio
    async def test_factcheck_final_strips_html_bold(self):
        from services.factcheck_service import FactCheckService
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(
            side_effect=[_factcheck_json("deep_research"),
                         "<b>вердикт</b> без тегов"])
        service = FactCheckService(aggregator, llm)
        result = await service.check_claim("тезис")
        assert "<b>" not in result
        assert "вердикт" in result


# ── F. Доставка direct deep_research (safe-HTML «Летописца») ─────────

class TestDeepResearchDelivery:
    @pytest.mark.asyncio
    async def test_deep_research_goes_html_escaped(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = []

        async def fake_send(bot, chat_id, text, reply_to=None, **kw):
            calls.append((text, kw))
            return 1

        monkeypatch.setattr(dcs, "send_chunked_reply", fake_send)
        await dcs.DirectChatService._send_direct_answer(
            None, -100, "<b>акцент</b> 5 < 10", 7, deep_research=True)
        assert calls[0][1] == {"parse_mode": "HTML"}
        assert calls[0][0] == "<b>акцент</b> 5 &lt; 10"

    @pytest.mark.asyncio
    async def test_deep_research_broken_html_plain_fallback(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = []

        async def fake_send(bot, chat_id, text, reply_to=None, **kw):
            calls.append((text, kw))
            if kw.get("parse_mode") == "HTML":
                raise TelegramBadRequest(method="sendMessage",
                                         message="can't parse entities")
            return 1

        monkeypatch.setattr(dcs, "send_chunked_reply", fake_send)
        await dcs.DirectChatService._send_direct_answer(
            None, -100, "<b>битая", 7, deep_research=True)
        assert len(calls) == 2
        assert calls[0][1] == {"parse_mode": "HTML"}
        assert calls[1][1] == {}
        assert calls[1][0] == "<b>битая"

    @pytest.mark.asyncio
    async def test_casual_stays_plain(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = []

        async def fake_send(bot, chat_id, text, reply_to=None, **kw):
            calls.append((text, kw))
            return 1

        monkeypatch.setattr(dcs, "send_chunked_reply", fake_send)
        await dcs.DirectChatService._send_direct_answer(
            None, -100, "как ИИ **нельзя**", 7)
        assert calls[0][1] == {}
        assert calls[0][0] == "как ИИ **нельзя**"
