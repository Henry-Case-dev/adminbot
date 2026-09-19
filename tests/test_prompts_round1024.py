"""F6 (раунд 10.24, ADR-1024-10) — «Промпты»: плоский grid без аккордеонов,
fallback-предохранитель (`casual`) и табы режимов внутри карточек модулей.

Ключевые контракты, которые доказываем:
  * **Δ каталога = 0:** ключ `prompts.verbilizer_default_mode` сохранён, но
    подпись → «Резервный режим (Fallback)», select-опции не изменены;
  * **fail-safe сбойного пути:** валидный `response_mode` из Stage-1 НИКОГДА
    не переопределяется fallback-ключом; ключ читается только при пустом/
    невалидном `response_mode`;
  * **UI:** дропдаун один раз (`data-block="prompts-fallback-mode"`), табы
    режимов внутри карточек с Вербализатором (`data-block="prompt-mode-tabs"`),
    аккордеон промптов гейтится флагом `PROMPTS_UI_V2_ENABLED`.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import hot_config as hot
from services import param_catalog as pc
from services.prompt_style_blocks import (
    MODE_CASUAL_BLOCK,
    MODE_DEEP_RESEARCH_BLOCK,
    MODE_SERIOUS_BLOCK,
    VERBILIZER_DEFAULT_MODE,
    _resolve_default_mode,
    compose_verbalizer_system,
)
from services.system2_handoff import (
    normalize_response_mode,
    parse_direct_synthesis,
    parse_factcheck_analysis,
    parse_summary_handoff,
)

pytestmark = pytest.mark.system2

HTML = open("web/index.html", encoding="utf-8").read()
JS = open("web/app.js", encoding="utf-8").read()
ROUTES = open("web/api/routes.py", encoding="utf-8").read()


class _FakeCache:
    def __init__(self, values=None):
        self._settings = dict(values or {})
        self.pg_available = False

    def get(self, key, default=None):
        return self._settings.get(key, default)

    async def set(self, key, value, category):
        self._settings[key] = value


@pytest.fixture(autouse=True)
def _reset_cache():
    hot.set_config_cache(None)
    yield
    hot.set_config_cache(None)


# ── A. Каталог: ключ сохранён (Δ=0), подпись/дефолт обновлены ────────────────

class TestCatalogFallbackMode:
    def test_key_kept_and_select_contract_unchanged(self):
        spec = pc.get_by_pg_key("prompts.verbilizer_default_mode")
        assert spec is not None
        assert spec.widget == "select"
        assert spec.select_options == ("casual", "serious", "deep_research")
        assert len(spec.select_labels) == 3
        assert spec.code_source == (
            "services.prompt_style_blocks.VERBILIZER_DEFAULT_MODE")

    def test_title_is_fallback(self):
        spec = pc.get_by_pg_key("prompts.verbilizer_default_mode")
        assert "Резервный режим (Fallback)" in spec.title_ru

    def test_code_default_is_casual(self):
        assert VERBILIZER_DEFAULT_MODE == "casual"


# ── B. Fallback-контракт: штатный путь приоритетнее предохранителя ───────────

class TestFallbackContract:
    def test_valid_stage1_mode_wins_over_fallback_key(self):
        """Валидный `response_mode` приоритетен: fallback-ключ НЕ читается.

        Сентинелы на режимных блоках делают плечо однозначным: если бы ключ
        дефолта перехватывал роутинг, в промпте оказался бы DEEP_SENTINEL.
        """
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_casual": "CASUAL_SENTINEL",
            "prompts.verbilizer_mode_deep_research": "DEEP_SENTINEL",
            "prompts.verbilizer_default_mode": "deep_research",
        }))
        composed = compose_verbalizer_system("BASE", "casual")
        assert "CASUAL_SENTINEL" in composed
        assert "DEEP_SENTINEL" not in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_fallback_key_read_only_on_failure_path(self):
        """Пустой `response_mode` → предохранитель из ключа (casual)."""
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "casual",
        }))
        composed = compose_verbalizer_system("BASE", "")
        assert MODE_CASUAL_BLOCK in composed

    def test_fallback_key_uses_configured_mode_on_failure(self):
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_serious": "SERIOUS_SENTINEL",
            "prompts.verbilizer_default_mode": "serious",
        }))
        composed = compose_verbalizer_system("BASE", None)
        assert "SERIOUS_SENTINEL" in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_invalid_fallback_key_falls_back_to_code_default_casual(self):
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "bogus",
        }))
        composed = compose_verbalizer_system("BASE", "wat")
        assert MODE_CASUAL_BLOCK in composed
        assert MODE_SERIOUS_BLOCK not in composed

    def test_valid_deep_research_not_overridden(self):
        """Штатный deep_research из Stage-1 сохраняет и mode-, и канал-блок."""
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "casual",
        }))
        composed = compose_verbalizer_system("BASE", "deep_research", "rich")
        assert MODE_DEEP_RESEARCH_BLOCK in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_resolve_default_mode_fail_safe(self):
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "deep_research"}))
        assert _resolve_default_mode() == "deep_research"
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "  "}))
        assert _resolve_default_mode() == "casual"


# ── B2. Проводка сбойного пути: Stage-1 сбой → ключ-предохранитель ──────────
# Review iter1 (High): раньше `normalize_response_mode` коэрсил невалид в
# `"serious"`, и ветка `_resolve_default_mode()` была недостижима из прода.
# Теперь нормализация отдаёт "" (сигнал сбоя), а решение принимает compose.

_DIGEST = "# Событие\n- Вася спорил с Петей"


def _factcheck_json(mode="wat"):
    return json.dumps({
        "claim": "земля плоская",
        "findings": [{"assertion": "земля плоская", "status": "false",
                      "human_time": "в августе", "author": "Вася",
                      "evidence": "спутники и фото"}],
        "verdict": "полный бред",
        "response_mode": mode,
    })


def _direct_json(mode="wat"):
    return json.dumps({
        "user_question": "что там с погодой",
        "facts": [{"topic": "погода", "finding": "завтра дождь",
                   "source": "exa", "confidence": "high"}],
        "answer_outline": "взять зонт",
        "limitations": [],
        "response_mode": mode,
    })


def _tool_result():
    from services.tool_loop import ToolLoopResult
    return ToolLoopResult(
        "финал", rounds_used=1,
        tool_trace=[{"round": 1, "tool": "execute_web_search", "ok": True,
                     "out_chars": 5}],
        tool_context="логи")


class TestFailurePathWiring:
    def test_normalize_emits_failure_signal_not_serious(self):
        assert normalize_response_mode("wat") == ""
        assert normalize_response_mode(None) == ""
        assert normalize_response_mode("") == ""
        assert normalize_response_mode("casual") == "casual"

    def test_parsers_carry_failure_signal(self):
        assert parse_factcheck_analysis(_factcheck_json())["response_mode"] == ""
        assert parse_direct_synthesis(_direct_json())["response_mode"] == ""
        raw = json.dumps({"response_mode": "wat", "digest": _DIGEST})
        assert parse_summary_handoff(raw)["response_mode"] == ""

    @pytest.mark.asyncio
    async def test_direct_chat_failure_uses_fallback_key(self):
        from services.direct_chat_service import DirectChatService
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_casual": "CASUAL_SENTINEL",
            "prompts.verbilizer_default_mode": "casual",
        }))
        svc = DirectChatService.__new__(DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[_direct_json(), "ответ"])
        await svc._synthesize_direct_answer(-100, "q", _tool_result(), None)
        stage2 = svc.llm.generate.await_args_list[1].args[0][0]["content"]
        assert "CASUAL_SENTINEL" in stage2
        assert MODE_SERIOUS_BLOCK not in stage2

    @pytest.mark.asyncio
    async def test_direct_chat_valid_mode_wins_on_real_wiring(self):
        from services.direct_chat_service import DirectChatService
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_casual": "CASUAL_SENTINEL",
            "prompts.verbilizer_mode_deep_research": "DEEP_SENTINEL",
            "prompts.verbilizer_default_mode": "casual",
        }))
        svc = DirectChatService.__new__(DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[
            _direct_json("deep_research"), "ответ"])
        await svc._synthesize_direct_answer(-100, "q", _tool_result(), None)
        stage2 = svc.llm.generate.await_args_list[1].args[0][0]["content"]
        assert "DEEP_SENTINEL" in stage2
        assert "CASUAL_SENTINEL" not in stage2

    @pytest.mark.asyncio
    async def test_factcheck_failure_uses_fallback_key(self):
        from services.factcheck_service import FactCheckService
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_casual": "CASUAL_SENTINEL",
            "prompts.verbilizer_default_mode": "casual",
        }))
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[_factcheck_json(), "ответ"])
        service = FactCheckService(aggregator, llm)
        await service.check_claim("тезис")
        stage2 = llm.generate.await_args_list[1].args[0][0]["content"]
        assert "CASUAL_SENTINEL" in stage2
        assert MODE_SERIOUS_BLOCK not in stage2

    @pytest.mark.asyncio
    async def test_summary_failure_uses_fallback_key(self):
        from services.summary_generator import SummaryGenerator
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_casual": "CASUAL_SENTINEL",
            "prompts.verbilizer_default_mode": "casual",
        }))
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[
            json.dumps({"response_mode": "wat", "digest": _DIGEST}),
            "готовый текст"])
        gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                               bot=None)
        await gen._generate_two_call("история", 3800, -100)
        stage2 = llm.generate.await_args_list[1].args[0][0]["content"]
        assert "CASUAL_SENTINEL" in stage2


# ── C. Kill-switch и UI-маркеры новой раскладки ──────────────────────────────

class TestUiGateAndMarkers:
    def test_flag_delivered_via_me(self):
        from config.settings import settings
        assert bool(settings.PROMPTS_UI_V2_ENABLED) is True
        assert '"PROMPTS_UI_V2_ENABLED"' in ROUTES

    def test_fallback_dropdown_rendered_exactly_once(self):
        marker = 'data-block="prompts-fallback-mode"'
        assert HTML.count(marker) == 1
        # Дропдаун стоит ДО цикла карточек модулей → рендерится один раз,
        # а не в каждой карточке (ADR-1024-10 D4).
        idx_fallback = HTML.index(marker)
        idx_loop = HTML.index('v-for="grp in currentTabGroups" :key=')
        assert idx_fallback < idx_loop
        assert "promptDefaultModeItem().title" in HTML
        assert "предохранитель" in HTML

    def test_mode_tabs_live_inside_module_cards(self):
        assert 'data-block="prompt-mode-tabs"' in HTML
        assert "&& sec.id === 'verbalizer' && promptModeItem()" in HTML
        # Таб V2 только переключает редактируемый режим (ключ не пишет).
        assert "@click=\"switchPromptMode(m.id)\"" in HTML
        assert "@click=\"selectPromptMode(m.id)\"" in HTML   # OFF-карточка 10.23
        # Ключ fallback пишет только шапочный дропдаун.
        assert "@change=\"savePromptFallbackMode()\"" in HTML

    def test_prompts_accordion_render_gate(self):
        # Единый предикат рендера аккордеона; в V2 → false для любой секции.
        assert "promptsShowAccordion(sec)" in HTML
        assert "promptsShowAccordion" in JS
        # В области промптов нет безусловного <details class="advanced">:
        # единственный аккордеон гейтится предикатом (не флагом-строкой).
        assert 'v-if="promptsShowAccordion(sec)"' in HTML

    def test_verbilizer_group_card_skipped_in_v2(self):
        assert "grp.id === 'prompts_verbilizer')" in HTML
        assert "!(uiFlag('PROMPTS_UI_V2_ENABLED')" in HTML

    def test_js_flat_items_and_casual_sync(self):
        assert "promptVisibleItems" in JS
        assert "uiFlag('PROMPTS_UI_V2_ENABLED')" in JS
        # Санитайз дефолтного режима → casual (а не serious).
        assert "? value : 'casual';" in JS
