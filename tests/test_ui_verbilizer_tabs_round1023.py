"""F8 (раунд 10.23, ADR-1023-8) — UI Синтезатор/Вербализатор + режимы + клише.

Покрытие:
  * Δ каталога: +10 prompts-ключей (Stage-1/2 + режимы) и +1 группа
    `prompts_verbilizer`; phantom-ключ клише НЕ регистрируем (review iter1);
  * поле `ParamSpec.stage` и аддитивная отдача в `/api/config`;
  * рантайм hot-get Stage-1/Stage-2/режимов (правка промптов из UI работает
    без рестарта); fallback на код-константы; число LLM-вызовов = 2;
  * UI-маркеры (секции, Tabs, блок клише) и freeze-меню.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import hot_config as hot
from services import param_catalog as pc
from services.param_catalog import (
    CATEGORY_PROMPTS,
    TAB_PROMPTS,
)
from services.prompt_style_blocks import (
    MODE_CASUAL_BLOCK,
    MODE_DEEP_RESEARCH_BLOCK,
    MODE_SERIOUS_BLOCK,
    VERBILIZER_DEFAULT_MODE,
    compose_verbalizer_system,
)

pytestmark = pytest.mark.system2


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


# ── A. Каталог: Δ F8 ────────────────────────────────────────────────────────

NEW_PROMPT_KEYS = {
    "prompts.factcheck_analyst_system_prompt": ("prompts_factcheck", "synthesizer"),
    "prompts.factcheck_verbalizer_system_prompt": ("prompts_factcheck", "verbalizer"),
    "prompts.summary_editor_system_prompt": ("prompts_summary", "synthesizer"),
    "prompts.summary_narrator_system_prompt": ("prompts_summary", "verbalizer"),
    "prompts.direct_chat_synthesizer_system_prompt": ("prompts_direct_chat",
                                                      "synthesizer"),
    "prompts.direct_chat_verbalizer_system_prompt": ("prompts_direct_chat",
                                                     "verbalizer"),
    "prompts.verbilizer_mode_casual": ("prompts_verbilizer", "mode"),
    "prompts.verbilizer_mode_serious": ("prompts_verbilizer", "mode"),
    "prompts.verbilizer_mode_deep_research": ("prompts_verbilizer", "mode"),
    "prompts.verbilizer_default_mode": ("prompts_verbilizer", "mode"),
}

ONE_STAGE_KEYS = {
    "prompts.search_system_prompt",
    "prompts.youtube_system_prompt",
    "prompts.youtube_video_system_prompt",
    "prompts.webpage_system_prompt",
}


class TestCatalogDelta:
    def test_counts(self):
        # F21 (10.24, ADR-1024-22 D8): +1 REGISTRY/GROUPS/mapped — теперь
        # 459/98/96; TAB_RULES 20 (новых вкладок нет).
        assert len(pc.REGISTRY) == 468
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21

    def test_new_group_bound_to_prompts_tab(self):
        g = pc.get_group("prompts_verbilizer")
        assert g is not None
        assert g.category == CATEGORY_PROMPTS
        assert g.order == 9
        assert pc.group_tab("prompts_verbilizer") == TAB_PROMPTS

    def test_new_prompt_keys_group_and_stage(self):
        for key, (group, stage) in NEW_PROMPT_KEYS.items():
            spec = pc.get_by_pg_key(key)
            assert spec is not None, key
            assert spec.category == CATEGORY_PROMPTS
            assert spec.group == group, key
            assert spec.stage == stage, key
            assert spec.progressive_level == "advanced", key
            assert spec.code_source, key
            assert spec.hidden is False

    def test_prompts_count_and_all_have_code_source(self):
        prompts = [s for s in pc.REGISTRY.values()
                   if s.category == CATEGORY_PROMPTS]
        # 10.26 (S3/ADR-1026-5 D4): +1 — prompts.summary_l1_clusterizer_system_prompt.
        assert len(prompts) == 22
        for spec in prompts:
            assert spec.code_source
            assert spec.stage in (None, "synthesizer", "verbalizer", "mode")

    def test_one_stage_modules_are_verbalizer_only(self):
        for key in ONE_STAGE_KEYS:
            spec = pc.get_by_pg_key(key)
            assert spec.stage == "verbalizer", key
        # Никакого фейкового Синтезатора у одностадийных модулей.
        for gid in ("prompts_search", "prompts_youtube", "prompts_web"):
            synth = [s for s in pc.REGISTRY.values()
                     if s.group == gid and s.stage == "synthesizer"]
            assert synth == [], gid

    def test_default_mode_select(self):
        spec = pc.get_by_pg_key("prompts.verbilizer_default_mode")
        assert spec.widget == "select"
        assert spec.select_options == ("casual", "serious", "deep_research")
        assert len(spec.select_labels) == 3
        # F6 (10.24, ADR-1024-10 D2): код-дефолт резервного режима → casual.
        assert VERBILIZER_DEFAULT_MODE == "casual"
        assert spec.code_source == (
            "services.prompt_style_blocks.VERBILIZER_DEFAULT_MODE")

    def test_modes_catalog_selection_contract(self):
        for mode in ("casual", "serious", "deep_research"):
            item = pc.get_by_pg_key(f"prompts.verbilizer_mode_{mode}")
            assert item.stage == "mode"

    def test_phantom_cliche_key_not_registered(self):
        """Review iter1 (Low): phantom-ключ `content.dynamic_cliche_list` НЕ
        регистрируем — F4 хранит клише в PG-таблице, ключ был бы «мёртвой
        ручкой» в матрице прав. UI-блок работает через /api/anticliche."""
        assert pc.get_by_pg_key("content.dynamic_cliche_list") is None


# ── B. Рантайм hot-get (кросс-фичевый контракт §4.1) ─────────────────────────

_DIGEST = "# Событие\n- Вася спорил с Петей"


def _factcheck_json(mode="casual"):
    return json.dumps({
        "claim": "тезис",
        "findings": [{"assertion": "тезис", "status": "false",
                      "human_time": "вчера", "author": "Вася",
                      "evidence": "факт"}],
        "verdict": "бред",
        "response_mode": mode,
    })


def _direct_json(mode="casual"):
    return json.dumps({
        "user_question": "вопрос",
        "facts": [{"topic": "t", "finding": "f", "source": "exa",
                   "confidence": "high"}],
        "answer_outline": "план",
        "limitations": [],
        "response_mode": mode,
    })


class TestModeBlockHotGet:
    def test_mode_block_from_cache(self):
        hot.set_config_cache(_FakeCache(
            {"prompts.verbilizer_mode_casual": "CUSTOM_CASUAL_BLOCK"}))
        composed = compose_verbalizer_system("BASE", "casual", "plain")
        assert "CUSTOM_CASUAL_BLOCK" in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_mode_block_empty_falls_back(self):
        hot.set_config_cache(_FakeCache(
            {"prompts.verbilizer_mode_serious": "   "}))
        assert MODE_SERIOUS_BLOCK in compose_verbalizer_system(
            "BASE", "serious", "plain")

    def test_default_mode_from_cache(self):
        hot.set_config_cache(_FakeCache(
            {"prompts.verbilizer_default_mode": "casual"}))
        assert MODE_CASUAL_BLOCK in compose_verbalizer_system("BASE", "wat")

    def test_default_mode_invalid_falls_back_casual(self):
        # F6 (10.24, ADR-1024-10 D2): битое значение ключа → код-дефолт casual.
        hot.set_config_cache(_FakeCache(
            {"prompts.verbilizer_default_mode": "bogus"}))
        composed = compose_verbalizer_system("BASE", "wat")
        assert MODE_CASUAL_BLOCK in composed
        assert MODE_SERIOUS_BLOCK not in composed


class TestSummaryRuntimeHotGet:
    @staticmethod
    def _gen(side_effect):
        from services.summary_generator import SummaryGenerator
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=side_effect)
        return SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                                bot=None), llm

    @pytest.mark.asyncio
    async def test_stage1_and_stage2_from_cache(self):
        hot.set_config_cache(_FakeCache({
            "prompts.summary_editor_system_prompt": "EDITOR_FROM_PG",
            "prompts.summary_narrator_system_prompt": "NARRATOR_FROM_PG",
        }))
        editor = json.dumps({"response_mode": "serious", "digest": _DIGEST})
        gen, llm = self._gen([editor, "готовый текст"])
        await gen._generate_two_call("история", 3800, -100)
        stage1 = llm.generate.await_args_list[0].args[0][0]["content"]
        stage2 = llm.generate.await_args_list[1].args[0][0]["content"]
        assert stage1 == "EDITOR_FROM_PG"
        assert stage2.startswith("NARRATOR_FROM_PG")
        assert llm.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_stage1_and_stage2_fall_back_to_constants(self):
        from services.summary_prompts import (
            SUMMARY_EDITOR_SYSTEM_PROMPT, SUMMARY_NARRATOR_SYSTEM_PROMPT)
        editor = json.dumps({"response_mode": "serious", "digest": _DIGEST})
        gen, llm = self._gen([editor, "текст"])
        await gen._generate_two_call("история", 3800, -100)
        stage1 = llm.generate.await_args_list[0].args[0][0]["content"]
        assert stage1 == SUMMARY_EDITOR_SYSTEM_PROMPT
        assert SUMMARY_NARRATOR_SYSTEM_PROMPT.replace(
            "{max_symbols}", "3800") in \
            llm.generate.await_args_list[1].args[0][0]["content"]


class TestFactcheckRuntimeHotGet:
    @pytest.mark.asyncio
    async def test_stage_prompts_from_cache(self):
        from services.factcheck_service import FactCheckService
        hot.set_config_cache(_FakeCache({
            "prompts.factcheck_analyst_system_prompt": "ANALYST_FROM_PG",
            "prompts.factcheck_verbalizer_system_prompt": "VERB_FROM_PG",
        }))
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[_factcheck_json(), "ответ"])
        service = FactCheckService(aggregator, llm)
        result = await service.check_claim("тезис")
        assert result == "ответ"
        stage1 = llm.generate.await_args_list[0].args[0][0]["content"]
        stage2 = llm.generate.await_args_list[1].args[0][0]["content"]
        assert stage1 == "ANALYST_FROM_PG"
        assert stage2.startswith("VERB_FROM_PG")
        assert llm.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_stage1_fallback_constant(self):
        from services.factcheck_service import FactCheckService
        from services.factcheck_prompts import (
            FACTCHECK_ANALYST_SYSTEM_PROMPT)
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[_factcheck_json(), "ответ"])
        service = FactCheckService(aggregator, llm)
        await service.check_claim("тезис")
        stage1 = llm.generate.await_args_list[0].args[0][0]["content"]
        assert stage1 == FACTCHECK_ANALYST_SYSTEM_PROMPT


class TestDirectRuntimeHotGet:
    @staticmethod
    def _svc(side_effect):
        from services.direct_chat_service import DirectChatService
        svc = DirectChatService.__new__(DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=side_effect)
        return svc

    @staticmethod
    def _raw():
        from services.tool_loop import ToolLoopResult
        return ToolLoopResult(
            "финал", rounds_used=1,
            tool_trace=[{"round": 1, "tool": "execute_web_search", "ok": True,
                         "out_chars": 5}],
            tool_context="логи")

    @pytest.mark.asyncio
    async def test_stage_prompts_from_cache(self):
        hot.set_config_cache(_FakeCache({
            "prompts.direct_chat_synthesizer_system_prompt": "SYNTH_FROM_PG",
            "prompts.direct_chat_verbalizer_system_prompt": "VERB_FROM_PG",
        }))
        svc = self._svc([_direct_json(), "ответ"])
        text, mode = await svc._synthesize_direct_answer(
            -100, "q", self._raw(), None)
        assert (text, mode) == ("ответ", "casual")
        stage1 = svc.llm.generate.await_args_list[0].args[0][0]["content"]
        stage2 = svc.llm.generate.await_args_list[1].args[0][0]["content"]
        assert stage1 == "SYNTH_FROM_PG"
        assert stage2.startswith("VERB_FROM_PG")
        assert svc.llm.generate.await_count == 2


# ── B2. Fail-safe на пустое PG-значение (review iter1, Low) ─────────────────

class TestEmptyPgFallback:
    """Пустое/whitespace значение ключа → код-константа (инвариант §4.1)."""

    def test_resolve_prompt_helper(self):
        from services.prompt_style_blocks import resolve_prompt
        key = "prompts.factcheck_analyst_system_prompt"
        assert resolve_prompt(key, "CODE") == "CODE"            # нет кэша
        hot.set_config_cache(_FakeCache({key: "   "}))
        assert resolve_prompt(key, "CODE") == "CODE"            # пусто
        hot.set_config_cache(_FakeCache({key: "PG"}))
        assert resolve_prompt(key, "CODE") == "PG"              # значение есть

    @pytest.mark.asyncio
    async def test_summary_empty_stage_prompts_fall_back(self):
        from services.summary_prompts import (
            SUMMARY_EDITOR_SYSTEM_PROMPT, SUMMARY_NARRATOR_SYSTEM_PROMPT)
        hot.set_config_cache(_FakeCache({
            "prompts.summary_editor_system_prompt": "  ",
            "prompts.summary_narrator_system_prompt": "",
        }))
        editor = json.dumps({"response_mode": "serious", "digest": _DIGEST})
        gen, llm = TestSummaryRuntimeHotGet._gen([editor, "текст"])
        await gen._generate_two_call("история", 3800, -100)
        stage1 = llm.generate.await_args_list[0].args[0][0]["content"]
        assert stage1 == SUMMARY_EDITOR_SYSTEM_PROMPT
        assert SUMMARY_NARRATOR_SYSTEM_PROMPT.replace(
            "{max_symbols}", "3800") in \
            llm.generate.await_args_list[1].args[0][0]["content"]

    @pytest.mark.asyncio
    async def test_factcheck_empty_analyst_falls_back(self):
        from services.factcheck_service import FactCheckService
        from services.factcheck_prompts import FACTCHECK_ANALYST_SYSTEM_PROMPT
        hot.set_config_cache(_FakeCache({
            "prompts.factcheck_analyst_system_prompt": "   "}))
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[_factcheck_json(), "ответ"])
        service = FactCheckService(aggregator, llm)
        await service.check_claim("тезис")
        stage1 = llm.generate.await_args_list[0].args[0][0]["content"]
        assert stage1 == FACTCHECK_ANALYST_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_direct_empty_synth_falls_back(self):
        from services.chat_prompts import DIRECT_SYNTHESIZER_SYSTEM_PROMPT
        hot.set_config_cache(_FakeCache({
            "prompts.direct_chat_synthesizer_system_prompt": "\n "}))
        svc = TestDirectRuntimeHotGet._svc([_direct_json(), "ответ"])
        await svc._synthesize_direct_answer(
            -100, "q", TestDirectRuntimeHotGet._raw(), None)
        stage1 = svc.llm.generate.await_args_list[0].args[0][0]["content"]
        assert stage1 == DIRECT_SYNTHESIZER_SYSTEM_PROMPT


# ── C. API/UI: аддитивная отдача stage и маркеры фронта ─────────────────────

class TestApiAndUiMarkers:
    ROUTES = open("web/api/routes.py", encoding="utf-8").read()
    JS = open("web/app.js", encoding="utf-8").read()
    HTML = open("web/index.html", encoding="utf-8").read()

    def test_config_exposes_stage(self):
        # Дополнительный grep-гейт (поведенческий — в test_webapp_api.py).
        assert '"stage": spec.stage if spec else None' in self.ROUTES

    def test_js_stage_sections_and_mode_tabs(self):
        for token in ("promptStageItems", "promptOtherItems",
                      "promptsHasSynthesizer", "promptsHasVerbalizer",
                      "promptSections", "selectPromptMode",
                      "promptModeTabs", "promptModeItem", "promptMode:"):
            assert token in self.JS, token
        # Секции строит promptSections (условная Вербализатор-секция).
        assert "promptSections(grp)" in self.HTML
        assert "Синтезатор (Логика)" in self.JS
        assert "Вербализатор (Характер)" in self.JS
        # High: селект сохраняет по $event.target.value.
        assert '@change="selectPromptMode($event.target.value)"' in self.HTML

    def test_js_cliche_monitor(self):
        for token in ("loadCliche", "forceRefreshCliche", "saveCliche",
                      "toggleClicheEdit", "clicheAvailable",
                      "/api/anticliche", "/api/anticliche/refresh"):
            assert token in self.JS, token

    def test_html_restores_perms_and_override_controls(self):
        """Review iter1 (Medium): в карточках F8 вернули права/оверрайды."""
        assert "openPermPicker(item)" in self.HTML
        assert "resetChatOverride(item)" in self.HTML
        assert "item.chat_source === 'chat'" in self.HTML
        assert "advancedOpen" in self.HTML  # basic/advanced дисклоузер (F24)

    def test_html_cliche_block(self):
        assert "Режимы Вербализатора" in self.HTML
        assert "Модуль одностадийный" in self.JS
        assert "Анти-клише: динамический список" in self.HTML
        assert 'data-block="anticliche-monitor"' in self.HTML
        # Freeze: вкладка «Промпты» и витрина модулей не переписаны.
        assert "id: 'prompts'" in self.JS
        assert "Модули" in self.HTML

    def test_freeze_menu_21_tabs(self):
        # F5 (10.24, ADR-1024-9 D3): 20→21 config-вкладок (+mod_images).
        assert len(pc.TAB_RULES) == 21
        assert len(pc.CONFIG_TAB_TITLES) == 21
        assert set(pc.TAB_NAV) == set(pc.CONFIG_TAB_TITLES)
