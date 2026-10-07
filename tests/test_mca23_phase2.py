"""MCA-23 фаза 2 — multi-tool DAG, ResponseDocument, media/clarification,
tool-путь max_tokens.

Покрытие (контракт MCA-23 §17-§25, §39-§44; лейн P2-A-mca23):
* §17: bounded multi-tool DAG — детерминированный план (0 LLM), исполнение
  шагов в топологическом порядке через существующий router.dispatch,
  синтез одним Stage-1 с блоком <tool_plan_results>; partial failure
  сохраняет успешные результаты (§19/M); bounds §39 не превышаются.
* Killing constraint: без плана (micro/chat/один tool) — путь байт-в-байт
  прежний (нет <tool_plan_results>, те же вызовы LLM).
* §Model slots: max_output_tokens доезжает до tool-раундов и FR-15
  plain-фолбэка; None → паритет.
* §18-I/§23: media-план с доставленным медиа — Writer не нужен; провал —
  нужен (честная деградация).
* §20: clarification — один конкретный вопрос, разрешимая цель → не спрашиваем.
* §22/§24/§O: ResponseDocument plain/rich round-trip без потери контента.
"""
import copy
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import response_document as rd
from services import response_extent as rext
from services.llm_client import (
    LLMError,
    LLMChatResult,
    LLMToolCall,
)
from services.response_extent import ResponsePlan
from services.tool_loop import (
    chat_with_tools,
    media_delivered,
    normalize_tool_plan,
    _topo_order,
    ToolLoopResult,
)


# ── Фейки (паттерн test_tool_loop + capture kwargs) ──────────────────────────

class FakeLLM:
    """generate_chat по заранее заданным ответам; ВСЕ kwargs запоминаются."""

    def __init__(self, answers, plain_text="обычный ответ"):
        self._answers = list(answers)
        self.plain_text = plain_text
        self.generated_plain = 0
        self.chat_kwargs = []
        self.plain_kwargs = []
        self.all_messages = []

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.chat_kwargs.append(dict(kwargs))
        self.all_messages.append(copy.deepcopy(messages))
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.generated_plain += 1
        self.plain_kwargs.append(dict(kwargs))
        self.all_messages.append(copy.deepcopy(messages))
        return self.plain_text


def _text(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


class FakeRouter:
    def __init__(self, outputs=None):
        self._outputs = dict(outputs) if outputs else {}
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, arguments))
        return self._outputs[(name, json.dumps(arguments, sort_keys=True))]

    def put(self, name, arguments, output):
        self._outputs[(name, json.dumps(arguments, sort_keys=True))] = output


MESSAGES = [{"role": "user", "content": "вопрос"}]

_SCHEMAS = [{"type": "function", "function": {"name": "fetch_article"}},
            {"type": "function", "function": {"name": "execute_web_search"}},
            {"type": "function", "function": {"name": "download_media"}}]

_FETCH_A = {"step_id": "fetch_a", "tool": "fetch_article",
            "arguments": {"url": "https://a.example/x"},
            "depends_on": [], "failure_policy": "optional"}
_FETCH_B = {"step_id": "fetch_b", "tool": "fetch_article",
            "arguments": {"url": "https://b.example/y"},
            "depends_on": [], "failure_policy": "optional"}


def _plan_steps_in_payload(llm):
    """Контент Stage-1 (первого) вызова — единственный user-текст."""
    first = llm.all_messages[0]
    return [m.get("content") for m in first if m.get("role") == "user"][-1]


# ── §17: детерминированный план (0 LLM) ──────────────────────────────────────

class TestBuildToolPlan:
    def test_two_link_comparison_builds_fetch_steps(self):
        plan = rext.build_tool_plan(
            "сравни https://a.example/x и https://b.example/y",
            available_tools={"fetch_article", "execute_web_search"})
        assert [s["tool"] for s in plan] == ["fetch_article", "fetch_article"]
        assert plan[0]["step_id"] == "fetch_1"
        assert plan[1]["step_id"] == "fetch_2"
        assert plan[0]["arguments"] == {"url": "https://a.example/x"}
        assert plan[1]["arguments"] == {"url": "https://b.example/y"}
        assert all(s["depends_on"] == [] for s in plan)
        assert all(s["failure_policy"] == "optional" for s in plan)

    def test_golden_e_web_hint_adds_optional_web_step(self):
        plan = rext.build_tool_plan(
            "сравни https://a.example/x и https://b.example/y "
            "и проверь в интернете что изменилось",
            available_tools={"fetch_article", "execute_web_search"})
        assert len(plan) == 3
        assert plan[2]["step_id"] == "web_1"
        assert plan[2]["tool"] == "execute_web_search"
        assert plan[2]["failure_policy"] == "optional"
        assert "https://" not in plan[2]["arguments"]["query"]

    def test_single_url_no_plan(self):
        assert rext.build_tool_plan(
            "прочитай https://a.example/x",
            available_tools={"fetch_article"}) == []

    def test_no_marker_no_plan(self):
        assert rext.build_tool_plan(
            "посмотри https://a.example/x и https://b.example/y",
            available_tools={"fetch_article"}) == []

    def test_too_many_urls_no_plan(self):
        urls = " ".join(f"https://u{i}.example/" for i in range(4))
        assert rext.build_tool_plan(
            f"сравни {urls}", available_tools={"fetch_article"}) == []

    def test_unknown_tools_dropped_no_plan(self):
        """§38: шаги с именами вне runtime-набора не исполняются."""
        assert rext.build_tool_plan(
            "сравни https://a.example/x и https://b.example/y",
            available_tools={"execute_web_search"}) == []

    def test_kill_switch_off(self, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(type(settings_mod.settings),
                            "DIRECT_TOOL_PLAN_ENABLED", False, raising=False)
        assert rext.tool_plan_enabled() is False
        assert rext.build_tool_plan(
            "сравни https://a.example/x и https://b.example/y") == []

    def test_never_raises_on_garbage(self):
        assert rext.build_tool_plan(None) == []
        assert rext.build_tool_plan(12345) == []


class TestCapabilityMap:
    def test_preferred_capability_names(self):
        assert rext.resolve_tool_name("article_fetch") == "fetch_article"
        assert rext.resolve_tool_name("web_search") == "execute_web_search"
        assert rext.resolve_tool_name("media_download") == "download_media"

    def test_real_name_passthrough_and_downstream_validation(self):
        assert rext.resolve_tool_name("fetch_article") == "fetch_article"
        # неизвестные строки проходят как есть — их отбрасывает
        # normalize_tool_plan по runtime-набору (§38)
        assert rext.resolve_tool_name("wat") == "wat"
        assert normalize_tool_plan(
            [{"step_id": "a", "tool": "wat", "arguments": {}}],
            announced={"fetch_article"}) == []
        assert rext.resolve_tool_name(None) == ""


# ── §17/§38: нормализация и топология ────────────────────────────────────────

class TestNormalizeToolPlan:
    def test_garbage_empty(self):
        assert normalize_tool_plan(None) == []
        assert normalize_tool_plan("nope") == []
        assert normalize_tool_plan([1, "x", {}]) == []

    def test_unknown_tool_step_dropped(self):
        steps = normalize_tool_plan(
            [_FETCH_A, {"step_id": "w", "tool": "secret_tool"}],
            announced={"fetch_article"})
        assert [s["tool"] for s in steps] == ["fetch_article"]

    def test_depends_on_unknown_dropped_and_cycle_cut(self):
        cycle = [
            {"step_id": "a", "tool": "fetch_article",
             "arguments": {}, "depends_on": ["b"]},
            {"step_id": "b", "tool": "fetch_article",
             "arguments": {}, "depends_on": ["a"]},
            {"step_id": "c", "tool": "execute_web_search",
             "arguments": {"query": "q"}, "depends_on": ["ghost", "a"]},
        ]
        steps = normalize_tool_plan(cycle, announced={"fetch_article",
                                                     "execute_web_search"})
        assert _topo_order(steps) == []          # цикл a-b не исполняется
        solo = normalize_tool_plan(
            [{"step_id": "c", "tool": "execute_web_search",
              "arguments": {"query": "q"}, "depends_on": ["ghost"]}])
        assert _topo_order(solo)[0]["step_id"] == "c"

    def test_step_cap(self):
        raw = [{"step_id": f"s{i}", "tool": "execute_web_search",
                "arguments": {"query": str(i)}} for i in range(9)]
        assert len(normalize_tool_plan(raw)) == 6   # PLAN_MAX_STEPS

    def test_bad_policy_defaults_optional(self):
        steps = normalize_tool_plan(
            [{"step_id": "a", "tool": "fetch_article",
              "failure_policy": "yolo"}])
        assert steps[0]["failure_policy"] == "optional"


# ── §17: исполнение DAG поверх существующего цикла ──────────────────────────

class TestToolPlanExecution:
    @pytest.mark.asyncio
    async def test_golden_e_two_fetches_then_synthesis(self):
        llm = FakeLLM([_text("сравнение: A про драконов, B про грифонов")])
        router = FakeRouter()
        router.put("fetch_article", {"url": "https://a.example/x"},
                   '{"status":"ok","markdown":"статья A"}')
        router.put("fetch_article", {"url": "https://b.example/y"},
                   '{"status":"ok","markdown":"статья B"}')
        out = await chat_with_tools(
            llm, MESSAGES, tools=_SCHEMAS, router=router, ctx=MagicMock(),
            tool_plan=[_FETCH_A, _FETCH_B])
        # независимые шаги — последовательно в порядке плана (§17)
        assert router.calls == [
            ("fetch_article", {"url": "https://a.example/x"}),
            ("fetch_article", {"url": "https://b.example/y"}),
        ]
        # ровно один LLM-вызов (Stage-1 с результатами, без лишних раундов)
        assert len(llm.chat_kwargs) == 1
        stage1 = _plan_steps_in_payload(llm)
        assert "<tool_plan_results>" in stage1
        assert "[fetch_a | fetch_article]" in stage1
        assert "статья A" in stage1 and "статья B" in stage1
        assert out == "сравнение: A про драконов, B про грифонов"
        assert not out.degraded and out.reason == "ok"
        # str-инвариант ToolLoopResult сохранён
        assert isinstance(out, str) and isinstance(out, ToolLoopResult)
        # плановые шаги видны в trace/envelopes c round=0
        assert [e["round"] for e in out.tool_trace] == [0, 0]
        assert [env["round"] for env in out.tool_results] == [0, 0]
        assert all(env["status"] == "ok" for env in out.tool_results)

    @pytest.mark.asyncio
    async def test_dependent_step_runs_after_parent(self):
        b = dict(_FETCH_B, depends_on=["fetch_a"])
        llm = FakeLLM([_text("итог")])
        router = FakeRouter()
        router.put("fetch_article", _FETCH_A["arguments"], "данные A")
        router.put("fetch_article", _FETCH_B["arguments"], "данные B")
        await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS, router=router,
                              ctx=MagicMock(), tool_plan=[b, _FETCH_A])
        # b объявлен ПЕРВЫМ, но зависит от a → топологический порядок a→b
        assert [args["url"] for _name, args in router.calls] == [
            "https://a.example/x", "https://b.example/y"]

    @pytest.mark.asyncio
    async def test_golden_m_partial_failure_preserved_with_limitation(self):
        llm = FakeLLM([_text("B недоступна, сравниваю по A")])
        router = FakeRouter()
        router.put("fetch_article", _FETCH_A["arguments"],
                   '{"status":"ok","markdown":"статья A"}')
        router.put("fetch_article", _FETCH_B["arguments"],
                   "ОШИБКА fetch_article: timeout")
        out = await chat_with_tools(
            llm, MESSAGES, tools=_SCHEMAS, router=router, ctx=MagicMock(),
            tool_plan=[_FETCH_A, _FETCH_B])
        stage1 = _plan_steps_in_payload(llm)
        # успешный результат СОХРАНЁН (§19/M)
        assert "статья A" in stage1
        assert "ОШИБКА fetch_article" in stage1
        # честная limitation-пометка, выдумывать данные запрещено
        assert "ОГРАНИЧЕНИЯ:" in stage1
        assert "fetch_b" in stage1
        assert "НЕ выдумывай" in stage1
        # run не деградировал: partial failure не рушит run
        assert not out.degraded

    @pytest.mark.asyncio
    async def test_bounds_plan_shares_chain_budget(self, monkeypatch):
        """§39: плановые шаги расходуют ОБЩИЙ §17-бюджет (cap 6 total)."""
        from config import settings as settings_mod
        from services import tool_loop as _tl
        # F5-гейт: settings-инстанс frozen (pydantic) — monkeypatch.setattr
        # бросает FrozenInstanceError, raising=False глотал его молча. Кроме
        # того, test_bot_main_flow делает importlib.reload(config.settings):
        # tool_loop держит ссылку на СТАРЫЙ инстанс — патчить нужно именно
        # тот объект, который читает getattr в tool_loop.
        _inst = _tl.settings
        assert _inst is not None
        _name = "MCA_TOOL_MAX_TOTAL_CALLS"
        _had = _name in _inst.__dict__
        _old = _inst.__dict__.get(_name)
        object.__setattr__(_inst, _name, 2)
        try:
            await self._bounds_plan_shares_chain_budget_body()
        finally:
            if _had:
                object.__setattr__(_inst, _name, _old)
            else:
                _inst.__dict__.pop(_name, None)
        assert settings_mod is not None  # импорт для сигнатуры совместимости

    async def _bounds_plan_shares_chain_budget_body(self):
        """Тело §39: плановые шаги расходуют ОБЩИЙ §17-бюджет (здесь cap=2)."""
        steps = [dict(_FETCH_A, step_id=f"f{i}",
                      arguments={"url": f"https://u{i}.example/"})
                 for i in range(2)]
        llm = FakeLLM([
            LLMChatResult(content=None, tool_calls=[
                LLMToolCall(id="c1", name="fetch_article",
                            arguments='{"url": "https://extra.example/"}')],
                          finish_reason="tool_calls"),
            _text("отвечаю тем, что есть"),
        ])
        router = FakeRouter()
        for i in range(2):
            router.put("fetch_article", {"url": f"https://u{i}.example/"},
                       f"данные {i}")
        out = await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS,
                                    router=router, ctx=MagicMock(),
                                    tool_plan=steps)
        # суммарно исполнено ровно 2 вызова (обе плановые; модельный —
        # отказан по chain_call_limit), бюджет не превышен
        assert len(router.calls) == 2
        assert out.degraded
        assert out.reason == "chain_call_limit"
        statuses = [env["status"] for env in out.tool_results]
        assert statuses == ["ok", "ok", "denied"]

    @pytest.mark.asyncio
    async def test_model_recall_same_call_bounded_not_looping(self):
        """§17-семантика без изменений: одинаковый вызов ≤2 раз, третий —
        из кэша (reuse cached intermediate data). Plan-шаг + recall модели
        не создают бесконечный dispatch."""
        llm = FakeLLM([
            LLMChatResult(content=None, tool_calls=[
                LLMToolCall(id="c1", name="fetch_article",
                            arguments=json.dumps(_FETCH_A["arguments"]))],
                          finish_reason="tool_calls"),
            _text("готово"),
        ])
        router = FakeRouter()
        router.put("fetch_article", _FETCH_A["arguments"], "данные A")
        await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS, router=router,
                              ctx=MagicMock(), tool_plan=[_FETCH_A])
        # plan 1 + recall 1 = 2 (кап _max_same_call), не больше
        assert len(router.calls) <= 2
        tool_msg = llm.all_messages[1][-1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["content"] == "данные A"

    @pytest.mark.asyncio
    async def test_unknown_plan_tool_never_dispatched(self):
        llm = FakeLLM([_text("без данных")])
        router = FakeRouter()
        out = await chat_with_tools(
            llm, MESSAGES, tools=_SCHEMAS, router=router, ctx=MagicMock(),
            tool_plan=[{"step_id": "x", "tool": "secret_tool",
                        "arguments": {}}])
        assert router.calls == []
        assert out == "без данных"

    @pytest.mark.asyncio
    async def test_plan_produces_system2_seed_trace(self):
        """Плановые шаги → tool_trace → существующий System2-гейт сработает
        (синтез результатов + limitations — §17 synthesis)."""
        llm = FakeLLM([_text("синтез")])
        router = FakeRouter()
        router.put("fetch_article", _FETCH_A["arguments"], "данные A")
        router.put("fetch_article", _FETCH_B["arguments"], "данные B")
        out = await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS,
                                    router=router, ctx=MagicMock(),
                                    tool_plan=[_FETCH_A, _FETCH_B])
        assert bool(out.tool_trace) and not out.degraded

    @pytest.mark.asyncio
    async def test_golden_i_media_repeat_bounded(self):
        """Golden I: media-вызовы ограничены §17-дедупом (≤2 одинаковых
        dispatch), третий — из кэша; цикла нет, side effect не спамится."""
        step = {"step_id": "dl", "tool": "download_media",
                "arguments": {"url": "https://v.example/1"},
                "depends_on": [], "failure_policy": "required"}
        steps = [dict(step, step_id=f"dl{i}") for i in range(3)]
        ok_json = '{"status": "success", "message": "Файл успешно загружен"}'
        llm = FakeLLM([_text("видео доставлено")])
        router = FakeRouter()
        router.put("download_media", step["arguments"], ok_json)
        out = await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS,
                                    router=router, ctx=MagicMock(),
                                    tool_plan=steps)
        assert len(router.calls) == 2          # 2 dispatch + 1 dedup
        dupes = [env for env in out.tool_results if env.get("duplicate")]
        assert len(dupes) == 1 and dupes[0]["round"] == 0
        # media доставлен → Writer-ветка не нужна (§18-I)
        assert media_delivered(out) is True

    @pytest.mark.asyncio
    async def test_no_plan_byte_parity(self):
        """Killing constraint: tool_plan=None → модельный ввод прежний."""
        llm_plan = FakeLLM([_text("финал")])
        llm_plain = FakeLLM([_text("финал")])
        router = FakeRouter()
        router.put("fetch_article", _FETCH_A["arguments"], "данные A")
        await chat_with_tools(llm_plan, MESSAGES, tools=_SCHEMAS,
                              router=router, ctx=MagicMock(),
                              tool_plan=[_FETCH_A])
        await chat_with_tools(llm_plain, MESSAGES, tools=_SCHEMAS,
                              router=router, ctx=MagicMock())
        assert "<tool_plan_results>" not in _plan_steps_in_payload(llm_plain)
        assert _plan_steps_in_payload(llm_plain) == "вопрос"
        # у plan-прогона блок есть и содержит результат
        assert "данные A" in _plan_steps_in_payload(llm_plan)


# ── §Model slots: tool-путь max_tokens ──────────────────────────────────────

class TestToolPathMaxTokens:
    @pytest.mark.asyncio
    async def test_longform_tokens_reach_tool_rounds(self):
        llm = FakeLLM([
            LLMChatResult(content=None, tool_calls=[
                LLMToolCall(id="c1", name="execute_web_search",
                            arguments='{"query": "q"}')],
                          finish_reason="tool_calls"),
            _text("развернутый ответ"),
        ])
        router = FakeRouter()
        router.put("execute_web_search", {"query": "q"}, "находки")
        await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS, router=router,
                              ctx=MagicMock(), max_output_tokens=4096)
        assert all(kw.get("max_output_tokens") == 4096
                   for kw in llm.chat_kwargs)

    @pytest.mark.asyncio
    async def test_plain_fallback_receives_tokens(self):
        class RejectingLLM(FakeLLM):
            async def generate_chat(self, messages, **kwargs):
                raise LLMError("HTTP 400: no tools")

        llm = RejectingLLM([])
        await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS,
                              router=FakeRouter(), ctx=MagicMock(),
                              max_output_tokens=2048)
        assert llm.generated_plain == 1
        assert llm.plain_kwargs[0].get("max_output_tokens") == 2048

    @pytest.mark.asyncio
    async def test_none_no_token_key(self):
        llm = FakeLLM([_text("ответ")])
        await chat_with_tools(llm, MESSAGES, tools=_SCHEMAS,
                              router=FakeRouter(), ctx=MagicMock())
        assert llm.chat_kwargs[0].get("max_output_tokens") is None

    @pytest.mark.asyncio
    async def test_generate_chat_payload_contract(self):
        captured: dict = {}
        from services.llm_client import LLMClient
        client = LLMClient("http://x", "KEY", "chat-model", "")

        class _Resp:
            @staticmethod
            def json():
                return {"choices": [
                    {"message": {"content": "ок", "tool_calls": None}}],
                        "usage": {}}

        async def _fake_post(path, payload, api_key=None, **kwargs):
            captured["payload"] = payload
            return _Resp()

        async def _fake_key(chat_id=None):
            return "KEY", "global"

        client._post_with_key = _fake_post               # type: ignore[assignment]
        client._resolve_api_key_and_source = _fake_key   # type: ignore[assignment]
        client._record_global_usage = AsyncMock()        # type: ignore[assignment]
        client._record_analytics = AsyncMock()           # type: ignore[assignment]
        await client.generate_chat([{"role": "user", "content": "q"}],
                                   chat_id=-100, max_output_tokens=4096)
        assert captured["payload"]["max_tokens"] == 4096
        await client.generate_chat([{"role": "user", "content": "q"}],
                                   chat_id=-100)
        assert "max_tokens" not in captured["payload"]


# ── §18-I/§23: media-ветка Delivery Router ──────────────────────────────────

class TestMediaDelivery:
    def test_classify_media_tasks_route_to_media_channel(self):
        dl = rext.classify_request("скачай https://v.example/watch?v=x")
        assert dl.task_kind == "media_download"
        assert dl.delivery_hint == "media"
        gen = rext.classify_request("бот, нарисуй дракона")
        assert gen.task_kind == "media_generation"
        assert gen.delivery_hint == "media"
        # не-media планы не менялись
        assert rext.classify_request("бот, как дела?").delivery_hint == "plain"

    @staticmethod
    def _raw(envs):
        return ToolLoopResult("текст", tool_results=envs)

    def test_media_delivered_ok_envelope(self):
        raw = self._raw([{"tool": "download_media", "status": "ok"}])
        assert media_delivered(raw) is True

    def test_media_tool_failed_not_delivered(self):
        raw = self._raw([{"tool": "download_media", "status": "error"}])
        assert media_delivered(raw) is False

    def test_non_media_tool_not_delivered(self):
        raw = self._raw([{"tool": "fetch_article", "status": "ok"}])
        assert media_delivered(raw) is False

    def test_media_writer_skipped_only_on_success(self):
        plan = ResponsePlan(task_kind="media_download", delivery_hint="media")
        assert rext.media_writer_needed(plan, self._raw(
            [{"tool": "download_media", "status": "ok"}])) is False
        # провал media-тула → Writer нужен (честная деградация §19)
        assert rext.media_writer_needed(plan, self._raw(
            [{"tool": "download_media", "status": "error"}])) is True
        # не-media план → прежнее поведение
        plain_plan = ResponsePlan(task_kind="comparison")
        assert rext.media_writer_needed(plain_plan, self._raw(
            [{"tool": "download_media", "status": "ok"}])) is True
        assert rext.media_writer_needed(None, None) is True


# ── §20: clarification — один конкретный вопрос ──────────────────────────────

class TestClarification:
    def test_missing_target_one_concrete_question(self):
        plan = rext.classify_request("скачай это")
        assert plan.task_kind == "media_download"
        question = rext.clarification_question(plan, has_target=False)
        assert question
        assert "уточн" not in question.lower()   # не «уточните пожалуйста»
        assert "ссылк" in question.lower()       # конкретика: что нужно

    def test_resolvable_target_no_question(self):
        plan = rext.classify_request("скачай https://v.example/1")
        assert rext.clarification_question(plan, has_target=True) == ""

    def test_media_generation_needs_no_target(self):
        plan = rext.classify_request("бот, нарисуй дракона")
        assert rext.clarification_question(plan, has_target=False) == ""

    def test_non_media_plan_no_question(self):
        plan = rext.classify_request("бот, подробно объясни каналы Go")
        assert rext.clarification_question(plan, has_target=False) == ""

    def test_transcription_without_target_asks(self):
        plan = rext.classify_request("транскрибируй")
        assert plan.task_kind == "transcription"
        assert rext.clarification_question(plan, has_target=False)


# ── §22/§24/§O: ResponseDocument ─────────────────────────────────────────────

class TestResponseDocument:
    def test_micro_answer_is_one_text_block(self):
        doc = rd.document_from_answer("да")
        assert doc.is_micro
        assert len(doc.blocks) == 1
        assert doc.plain_text() == "да"

    def test_plain_round_trip_byte_parity(self):
        text = ("Первый абзац.\n\nВторой [ссылка](https://x) и *акценты*,\n"
                "третья строка с ёлочками «и» тире —.")
        doc = rd.document_from_answer(text)
        assert doc.plain_text() == text
        assert doc.rich_text() == text

    def test_plain_fallback_wins_over_blocks(self):
        doc = rd.ResponseDocument(
            title="T",
            blocks=(rd.TextBlock("a"), rd.TextBlock("b")),
            plain_fallback="фиксированный plain")
        assert doc.plain_text() == "фиксированный plain"
        assert not doc.is_micro

    def test_documents_equal_content(self):
        a = rd.document_from_answer("одинаковый смысл")
        b = rd.ResponseDocument(
            blocks=(rd.TextBlock("другая структура"),),
            plain_fallback="одинаковый смысл")
        assert rd.documents_equal_content(a, b)
        assert not rd.documents_equal_content(a, rd.document_from_answer("x"))

    @pytest.mark.asyncio
    async def test_golden_o_rich_fail_plain_same_document(self, monkeypatch):
        """Rich fail → Plain ТОГО ЖЕ ResponseDocument, без регенерации."""
        from services.direct_chat_service import DirectChatService
        bot = MagicMock()
        bot.send_rich_message = AsyncMock(
            side_effect=RuntimeError("sendRichMessage not supported"))
        chunked = AsyncMock(return_value=888)
        monkeypatch.setattr("services.direct_chat_service.send_chunked_reply",
                            chunked)
        answer = "Полный ответ статьи: раздел 1, раздел 2, вывод."
        doc = rd.document_from_answer(answer)
        sent_id = await DirectChatService._send_direct_answer(
            bot, -100, answer, 42, rich=True, document=doc)
        assert sent_id == 888
        # rich пытался уйти с ТЕМ ЖЕ смыслом документа (chat_id + rich-body)
        rich_args = bot.send_rich_message.await_args.args
        assert rich_args[0] == -100
        rich_body = getattr(rich_args[1], "html", None) \
            or getattr(rich_args[1], "markdown", "")
        assert "раздел 1" in str(rich_body)
        # plain-фолбэк получил plain_text() того же документа (без потерь)
        assert chunked.await_args.args[2] == doc.plain_text() == answer

    @pytest.mark.asyncio
    async def test_document_none_backward_parity(self, monkeypatch):
        from services.direct_chat_service import DirectChatService
        bot = MagicMock()
        bot.send_rich_message = AsyncMock()
        chunked = AsyncMock(return_value=999)
        monkeypatch.setattr("services.direct_chat_service.send_chunked_reply",
                            chunked)
        sent_id = await DirectChatService._send_direct_answer(
            bot, -100, "ответ", 42)
        assert sent_id == 999
        assert chunked.await_args.args[2] == "ответ"
        bot.send_rich_message.assert_not_awaited()
