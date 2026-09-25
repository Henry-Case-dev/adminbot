"""A3 `unified-image-request-round1026` (Эпик 3, Wave 2; ADR-1026-16; risk R3).

Покрытие §18/§19/§20/§21:
* §20/§18 (T-3559…T-3562): единый ``ImageRequest`` + единственная сборка
  ``final_prompt`` (reuse ``extract_prompt``) + единый раннер
  ``run_image_request`` → СУЩЕСТВУЮЩИЙ ``generate_and_send``; оба входа
  (direct/tool) сходятся до подготовки запроса; второго pipeline нет.
* §20/D3 (T-3563): авторитетный маркер прогона ``image_request_handled`` →
  tool-путь первым делом возвращает ``skipped``/``already_handled`` без
  генерации/списания бюджета; forced ``image_enabled=False`` сохранён.
* §21/D4 (T-3567/T-3568): уточнение ТОЛЬКО текста описания (канон 11 не
  меняется), валидация структурированных аргументов fail-closed, результат
  в цикл через reuse A2-envelope, реальная ошибка доводится.
* D6/D10 (T-3576): R17-логи (без промптов/URL) + OFF → legacy эквивалент.

Тесты не ходят в сеть (провайдер/бюджет подменяются) и не печатают секреты.
"""
from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import image_generation as ig
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import (
    TOOL_CALLING_TOOLS,
    TOOL_GENERATE_IMAGE,
    TOOL_GENERATE_IMAGE_LEGACY,
    TOOL_GENERATE_IMAGE_V21,
    active_tools,
)
from services.llm_client import LLMChatResult, LLMToolCall

_FIRST_EIGHT = [
    "query_chat_memory", "dig_into_lore", "execute_web_search",
    "summarize_video", "download_media", "get_bot_health",
    "get_recent_history", "compile_lore_story",
]

_CANONICAL_QUERY = "Бот, нарисуй красного кота"


def _ctx(chat_id=7, *, handled=False, user_id=42, reply_id=101,
         correlation_id="c-1"):
    return ToolContext(chat_id, "запрос", bot="B", user_id=user_id,
                       reply_to_message_id=reply_id,
                       correlation_id=correlation_id,
                       image_request_handled=handled)


def _router():
    """ToolRouter только для image-пути: deps не используются."""
    deps = MagicMock(spec=ToolDeps)
    return ToolRouter(deps)


def _ok_result():
    return ig.GenerationResult(ok=True, content=b"\x89PNG\r\n\x1a\n")


# ── C/D2: контракт ImageRequest и единственный раннер ──────────────────────


class TestUnifiedContract:
    def test_build_image_request_defaults(self):
        # D5/§19/§22: поля памяти — строго заглушки (A4 не нарушается).
        r = ig.build_image_request("tool", 7, "画的 кот")
        assert r.source == "tool"
        assert r.chat_id == 7
        assert r.resolved_subjects == []
        assert r.context_required is False
        assert r.context_sources == []
        assert r.generator_config == {}

    def test_source_normalization(self):
        assert ig.build_image_request("direct", 1, "x").source == "direct"
        assert ig.build_image_request("unknown", 1, "x").source == "tool"

    def test_build_final_prompt_reuses_extract_prompt(self):
        # §19/REQ-A3-02: канонический прямой запрос — тот же промпт.
        r = ig.build_image_request("direct", 7, _CANONICAL_QUERY)
        assert ig.build_final_prompt(r) == "красного кота"
        assert ig.build_final_prompt(r) == ig.extract_prompt(_CANONICAL_QUERY)

    @pytest.mark.asyncio
    async def test_run_image_request_calls_existing_generator(self,
                                                              monkeypatch):
        # §104: раннер — обвязка, генератор существующий.
        sent = {}

        async def fake_send(bot, chat_id, prompt, *, reply_to_message_id=None,
                            correlation_id=None, source="direct", **kwargs):
            sent.update(bot=bot, chat_id=chat_id, prompt=prompt,
                        reply_to_message_id=reply_to_message_id,
                        correlation_id=correlation_id, source=source)
            return _ok_result()

        monkeypatch.setattr(ig, "generate_and_send", fake_send)
        r = ig.build_image_request("direct", 7, _CANONICAL_QUERY,
                                   requester_id=42, original_message_id=101)
        out = await ig.run_image_request(r, bot="B", correlation_id="c-1")
        assert out.ok
        assert sent == {"bot": "B", "chat_id": 7, "prompt": "красного кота",
                        "reply_to_message_id": 101, "correlation_id": "c-1",
                        # A5 (ADR-1026-17 D3): idem-дискриминатор входа.
                        "source": "direct"}


# ── C/T-3560: прямой (keyword) путь строит ImageRequest без регрессий ──────


class TestDirectPath:
    @pytest.mark.asyncio
    async def test_direct_on_uses_shared_runner(self, monkeypatch):
        seen = {}

        async def fake_run(request, *, bot=..., correlation_id=...):
            seen["request"] = request
            seen["bot"] = bot
            seen["correlation_id"] = correlation_id
            return _ok_result()

        monkeypatch.setattr(ig, "run_image_request", fake_run)
        ctx = ToolContext(7, _CANONICAL_QUERY, bot="B", user_id=42,
                          reply_to_message_id=101, correlation_id="c-1")
        block = await ig.maybe_handle_keyword(ctx, _CANONICAL_QUERY)
        assert 'status="ok"' in block
        r = seen["request"]
        assert isinstance(r, ig.ImageRequest)
        assert r.source == "direct"
        assert r.chat_id == 7
        assert r.requester_id == 42
        assert r.original_message_id == 101
        assert r.user_request == _CANONICAL_QUERY
        assert seen["bot"] == "B" and seen["correlation_id"] == "c-1"

    @pytest.mark.asyncio
    async def test_direct_on_same_prompt_as_legacy(self, monkeypatch):
        # REQ-A3-02: ON-путь даёт байт-в-байт тот же вызов генератора,
        # что и legacy (промпт/чат/reply/budget — без изменений).
        calls = []

        async def fake_send(bot, chat_id, prompt, *, reply_to_message_id=None,
                            correlation_id=None, source="direct", **kwargs):
            calls.append({"bot": bot, "chat_id": chat_id, "prompt": prompt,
                          "reply_to_message_id": reply_to_message_id,
                          "correlation_id": correlation_id,
                          "source": source})
            return _ok_result()

        ctx = ToolContext(7, _CANONICAL_QUERY, bot="B", user_id=42,
                          reply_to_message_id=101, correlation_id="c-1")
        monkeypatch.setattr(ig, "generate_and_send", fake_send)

        await ig.maybe_handle_keyword(ctx, _CANONICAL_QUERY)   # ON (default)
        on_call = dict(calls[0])

        monkeypatch.setattr(ig, "unified_image_request_enabled",
                            lambda: False)
        await ig.maybe_handle_keyword(ctx, _CANONICAL_QUERY)   # OFF (legacy)
        legacy_call = dict(calls[1])
        assert on_call == legacy_call == {
            "bot": "B", "chat_id": 7, "prompt": "красного кота",
            "reply_to_message_id": 101, "correlation_id": "c-1",
            "source": "direct"}

    @pytest.mark.asyncio
    async def test_direct_off_no_image_request(self, monkeypatch):
        # D6: OFF → legacy-путь без ImageRequest.
        monkeypatch.setattr(ig, "unified_image_request_enabled",
                            lambda: False)
        run = AsyncMock(return_value=_ok_result())
        monkeypatch.setattr(ig, "run_image_request", run)
        sent = AsyncMock(return_value=_ok_result())
        monkeypatch.setattr(ig, "generate_and_send", sent)
        ctx = ToolContext(7, _CANONICAL_QUERY, bot="B",
                          reply_to_message_id=101, correlation_id="c-1")
        block = await ig.maybe_handle_keyword(ctx, _CANONICAL_QUERY)
        assert 'status="ok"' in block
        run.assert_not_called()
        assert sent.call_args.args == ("B", 7, "красного кота")


# ── C/T-3561/T-3562: tool-путь — тот же ImageRequest/раннер ────────────────


class TestToolPath:
    @pytest.mark.asyncio
    async def test_tool_uses_shared_runner(self, monkeypatch):
        seen = {}

        async def fake_run(request, *, bot=..., correlation_id=...):
            seen["request"] = request
            return _ok_result()

        monkeypatch.setattr(ig, "run_image_request", fake_run)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        ctx = _ctx()
        out = await _router()._generate_image({"prompt": "селёдка в шляпе"},
                                              ctx)
        payload = json.loads(out)
        assert payload["status"] == "success"
        r = seen["request"]
        assert isinstance(r, ig.ImageRequest)
        assert r.source == "tool"
        assert r.chat_id == 7
        assert r.requester_id == 42
        assert r.original_message_id == 101
        assert r.user_request == "селёдка в шляпе"

    @pytest.mark.asyncio
    async def test_tool_off_direct_call(self, monkeypatch):
        # OFF → legacy: прямой вызов generate_and_send, без ImageRequest.
        monkeypatch.setattr(ig, "unified_image_request_enabled",
                            lambda: False)
        run = AsyncMock(return_value=_ok_result())
        sent = AsyncMock(return_value=_ok_result())
        monkeypatch.setattr(ig, "run_image_request", run)
        monkeypatch.setattr(ig, "generate_and_send", sent)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        out = await _router()._generate_image({"prompt": "кот"}, _ctx())
        assert json.loads(out)["status"] == "success"
        run.assert_not_called()
        assert sent.call_args.args == ("B", 7, "кот")


# ── D/T-3563: двойная генерация невозможна (маркер прогона) ────────────────


class TestAlreadyHandled:
    @pytest.mark.asyncio
    async def test_skipped_without_regeneration(self, monkeypatch):
        # D3 слой 2: маркер первым делом → skipped, без генерации/списания.
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        run = AsyncMock(return_value=_ok_result())
        sent = AsyncMock(return_value=_ok_result())
        budget = AsyncMock(return_value=True)
        monkeypatch.setattr(ig, "run_image_request", run)
        monkeypatch.setattr(ig, "generate_and_send", sent)
        monkeypatch.setattr(ig, "_consume_budget", budget)
        ctx = _ctx(handled=True)
        out = await _router()._generate_image({"prompt": "кот"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert payload["reason"] == "already_handled"
        run.assert_not_called()
        sent.assert_not_called()
        budget.assert_not_called()   # image_calls не списываются

    @pytest.mark.asyncio
    async def test_marker_off_legacy(self, monkeypatch):
        # D6: киль-свитч OFF → прежнее поведение (генерация выполняется).
        monkeypatch.setattr(ig, "unified_image_request_enabled",
                            lambda: False)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        sent = AsyncMock(return_value=_ok_result())
        monkeypatch.setattr(ig, "generate_and_send", sent)
        out = await _router()._generate_image(
            {"prompt": "кот"}, _ctx(handled=True))
        assert json.loads(out)["status"] == "success"
        sent.assert_called_once()

    @pytest.mark.asyncio
    async def test_loop_double_trigger_is_one_generation(self, monkeypatch):
        # SC-A3-09 adversarial: пре-гейт сработал на ход → даже если модель
        # вызывает generate_image в цикле, генерация ровно одна (никакой
        # второй платной попытки; skipped возвращается в цикл как tool-роль).
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        run = AsyncMock(return_value=_ok_result())
        budget = AsyncMock(return_value=True)
        monkeypatch.setattr(ig, "run_image_request", run)
        monkeypatch.setattr(ig, "_consume_budget", budget)

        ctx = ToolContext(7, _CANONICAL_QUERY, bot="B",
                          reply_to_message_id=101, user_id=42,
                          correlation_id="c-1", image_request_handled=True)
        router = _router()
        llm = _LoopLLM([_tc("c1", "generate_image",
                            {"prompt": "кот", "extra": 1}),
                        _text("готово")])
        from services.tool_loop import ToolLoopResult  # noqa: F401
        result = await chat_with_tools(
            llm, [{"role": "user", "content": _CANONICAL_QUERY}],
            tools=active_tools(image_generation_enabled=True),
            router=router, ctx=ctx)
        assert isinstance(result, str) and result
        run.assert_not_called()            # генерация НЕ повторялась
        budget.assert_not_called()         # бюджет не списан
        tool_msg = [m for m in llm.all_messages[-1]
                    if m.get("role") == "tool"]
        assert len(tool_msg) == 1
        assert json.loads(tool_msg[0]["content"])["status"] == "skipped"
        # A2-envelope: skipped-вызов виден в журнале прогона.
        entries = [e for e in ctx.tool_results if e["tool"] == "generate_image"]
        assert entries and entries[-1]["data"]["status"] == "skipped"


# ── E/T-3568: fail-closed валидация структурированных аргументов ───────────


class TestValidation:
    @pytest.mark.asyncio
    async def test_missing_prompt_fail_closed(self, monkeypatch):
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        sent = AsyncMock(return_value=_ok_result())
        monkeypatch.setattr(ig, "generate_and_send", sent)
        out = await _router()._generate_image({}, _ctx())
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert "prompt" in payload["message"]
        sent.assert_not_called()
        # Статус error не исключает работу цикла: классификация A2-envelope.
        from services.tool_loop import _classify_output
        info = _classify_output("generate_image", out)
        assert info["status"] == "error"

    @pytest.mark.asyncio
    async def test_module_off_error_and_no_generation(self, monkeypatch):
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=False))
        sent = AsyncMock(return_value=_ok_result())
        monkeypatch.setattr(ig, "generate_and_send", sent)
        out = await _router()._generate_image({"prompt": "кот"}, _ctx())
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert "отключена" in payload["message"]
        sent.assert_not_called()


# ── E/T-3570: реальная ошибка доводится, «отказ модели» не выдумывается ────


class TestRealErrorPropagation:
    @pytest.mark.asyncio
    async def test_generator_reason_is_surfaced(self, monkeypatch):
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))

        async def fail_run(request, *, bot=..., correlation_id=...):
            return ig.GenerationResult(ok=False, reason="timeout")

        monkeypatch.setattr(ig, "run_image_request", fail_run)
        out = await _router()._generate_image({"prompt": "кот"}, _ctx())
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["reason"] == "timeout"        # реальный reason_class
        # Текст нейтрально-пользовательский: НЕ утверждает «модель отказалась»
        assert "модель" not in payload["message"].lower()
        assert payload["message"] == ig.IMAGE_GENERATION_FALLBACK_PHRASE

    @pytest.mark.asyncio
    async def test_error_enters_loop_as_tool_role(self, monkeypatch):
        # SC-A3-07/-08: результат/ошибка возвращаются в цикл (kick A2-envelope
        # reuse); модель видит структурированный JSON с реальной причиной.
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))

        async def fail_run(request, *, bot=..., correlation_id=...):
            return ig.GenerationResult(ok=False, reason="network")

        monkeypatch.setattr(ig, "run_image_request", fail_run)
        ctx = _ctx()
        llm = _LoopLLM([_tc("c1", "generate_image", {"prompt": "кот"}),
                        _text("изображение не получилось")])
        await chat_with_tools(
            llm, [{"role": "user", "content": "нарисуй"}],
            tools=active_tools(image_generation_enabled=True),
            router=_router(), ctx=ctx)
        tool_msgs = [m for m in llm.all_messages[-1]
                     if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        payload = json.loads(tool_msgs[0]["content"])
        assert payload["status"] == "error" and payload["reason"] == "network"
        # envelope reuse: запись есть в ctx.tool_results (не новый контракт).
        entries = [e for e in ctx.tool_results if e["tool"] == "generate_image"]
        assert entries and entries[-1]["data"]["status"] == "error"
        assert entries[-1]["error_code"] == "network"
        assert entries[-1]["metered"] is True


# ── D4/T-3567: описание инструмента — только текст; канон 11 ───────────────


class TestToolDescriptionU21:
    def test_canon_unchanged(self):
        # A6 (ADR-1026-18 D1): канон 11 → 12 (+get_user_context, в хвост).
        names = [t["function"]["name"] for t in TOOL_CALLING_TOOLS]
        assert names == _FIRST_EIGHT + ["generate_image", "transcribe_video",
                                        "fetch_article", "get_user_context"]
        assert names[8] == "generate_image"

    def test_schema_structure_identical_in_variants(self):
        for tool in (TOOL_GENERATE_IMAGE, TOOL_GENERATE_IMAGE_LEGACY,
                     TOOL_GENERATE_IMAGE_V21):
            fn = tool["function"]
            assert fn["name"] == "generate_image"
            assert tool["type"] == "function"
            assert fn["parameters"]["required"] == ["prompt"]
            assert fn["parameters"]["additionalProperties"] is False
            assert fn["parameters"]["properties"]["prompt"]["type"] == "string"

    def test_v21_covers_six_s21_points(self):
        text = TOOL_GENERATE_IMAGE_V21["function"]["description"].lower()
        # (1) когда вызывать
        assert "when to call" in text or ("when" in text and "call" in text)
        # (2) обязательные аргументы
        assert "required arg" in text
        # (3) как формировать описание
        assert "how to build" in text
        # (4) что при отсутствии контекста
        assert "without extra context" in text
        # (5) как интерпретировать результат
        assert "how to interpret" in text
        # (6) как сообщать об ошибке
        assert "reason" in text and "do not invent" in text

    def test_legacy_text_is_baseline(self):
        # D6: OFF-текст байт-в-байт равен baseline-описанию.
        assert TOOL_GENERATE_IMAGE_LEGACY["function"]["description"] == (
            "Generate an image from a text description and send "
            "it to this chat. Call when the user asks to draw, "
            "create, generate or imagine a picture, meme, art or "
            "illustration.")

    def test_default_is_refined(self):
        # default ON (D6): активный текст — уточнённый.
        assert TOOL_GENERATE_IMAGE["function"]["description"] == \
            TOOL_GENERATE_IMAGE_V21["function"]["description"]
        assert TOOL_GENERATE_IMAGE["function"]["description"] != \
            TOOL_GENERATE_IMAGE_LEGACY["function"]["description"]

    def test_kill_switch_off_restores_legacy_via_env(self):
        # D6: UNIFIED_IMAGE_REQUEST_ENABLED=false → прежний текст описания
        # (выбор статичен на уровне импорта модуля — проверяем в свежем
        # интерпретаторе с окружением OFF).
        import os
        env = dict(os.environ)
        env["UNIFIED_IMAGE_REQUEST_ENABLED"] = "false"
        code = (
            "import json, sys;"
            "sys.path.insert(0, r'C:\\Code\\Python\\adminbot');"
            "from services.tool_schemas import TOOL_GENERATE_IMAGE;"
            "print(json.dumps(TOOL_GENERATE_IMAGE['function']['description']))"
        )
        done = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=60,
                              env=env)
        assert done.returncode == 0, done.stderr[-400:]
        printed = json.loads(done.stdout.strip())   # без цитат/обёрток
        legacy = TOOL_GENERATE_IMAGE_LEGACY["function"]["description"]
        assert printed == legacy

    def test_active_tools_with_kill_switch_off_effective(self):
        # D6: OFF → still 11-name canon via TOOL_CALLING_TOOLS (без изменений
        # состава), флаг-гейт — прежний (image_generation_enabled=False →
        # generate_image исключён).
        names = [t["function"]["name"]
                 for t in active_tools(image_generation_enabled=True)]
        assert "generate_image" in names
        names_off = [t["function"]["name"] for t in active_tools()]
        assert "generate_image" not in names_off


# ── D10/T-3575: R17 — логи без промптов/URL/секретов ───────────────────────


class TestR17Logs:
    @pytest.mark.asyncio
    async def test_failure_logs_are_codes_only(self, monkeypatch, caplog):
        import logging
        prompt = "СУПЕР-СЕКРЕТЗАНЯТНЫЙ-промпт-кот"
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))

        async def fail_run(request, *, bot=..., correlation_id=...):
            return ig.GenerationResult(ok=False, reason="bad_request")

        monkeypatch.setattr(ig, "run_image_request", fail_run)
        with caplog.at_level(logging.INFO, logger="services.tool_router"):
            await _router()._generate_image({"prompt": prompt}, _ctx())
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "timeout" in joined or "reason" in joined
        for text in (prompt, "http", "Bearer"):
            assert text not in joined


# ── фейк-LLM для tool-цикла ────────────────────────────────────────────────


class _LoopLLM:
    def __init__(self, answers):
        self._answers = list(answers)
        self.all_messages = []

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append([dict(m) for m in messages])
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        return "plain"


def _tc(call_id, name, args):
    return LLMChatResult(
        content=None,
        tool_calls=[LLMToolCall(id=call_id, name=name,
                                arguments=json.dumps(args))],
        finish_reason="tool_calls")


def _text(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


# ── G/R3: границы diff — §104, DDL, каталог, версия, banned-пути ───────────


class TestBoundsA3:
    """T-3577/T-3578/T-3579 (D6/D7/D8): §104-генератор AST-идентичен
    baseline `e8646af`; Δ DDL=0; Δ каталога=0; киль-свитч env-only;
    banned-пути вне diff; 2-вызовность/канон не тронуты."""

    _BASELINE = "e8646af"
    _ROOT = None

    @classmethod
    def _root(cls):
        from pathlib import Path
        return Path(__file__).resolve().parents[1]

    def _baseline_file(self, rel):
        proc = subprocess.run(
            ["git", "-C", str(self._root()), "show",
             f"{self._BASELINE}:{rel}"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        if proc.returncode != 0:
            pytest.skip(f"baseline {self._BASELINE} недоступен")
        return proc.stdout

    def _fn_dump(self, source: str, names: set) -> dict:
        import ast
        tree = ast.parse(source)
        out = {}
        for node in tree.body:
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                    and node.name in names:
                out[node.name] = ast.dump(node)
        return out

    def test_104_generator_functions_ast_identical(self):
        # §104: generate/generate_image(_verbose)/reason_class и
        # ключевик-канон — байт-в-байт (AST) не изменены.
        # NOTE (A5, ADR-1026-17 D2/D7): `generate_and_send` исключён из
        # set-equal — A5 санкционированно оборачивает его жизненным циклом
        # `reserve → generate → commit/release` (§29) вокруг НЕИЗМЕННОГО
        # генератора; сам платный вызов `generate`/провайдер §104 — SAME.
        rel = "services/image_generation.py"
        old_src = self._baseline_file(rel)
        new_src = (self._root() / rel).read_text(encoding="utf-8")
        names = {"generate", "generate_image",
                 "generate_image_verbose", "extract_prompt",
                 "is_image_keyword"}
        old_fns = self._fn_dump(old_src, names)
        new_fns = self._fn_dump(new_src, names)
        assert set(old_fns) == set(new_fns), old_fns.keys()
        for name in old_fns:
            assert old_fns[name] == new_fns[name], name
        # §104-ядро платного вызова остаётся неизменным явной проверкой.
        assert "generate_and_send" not in names

    def test_104_fallback_phrase_unchanged(self):
        old_src = self._baseline_file("services/image_generation.py")
        old = ig.IMAGE_GENERATION_FALLBACK_PHRASE
        # Вырезаем и сравниваем литерал из baseline-файла.
        import ast as _ast
        tree = _ast.parse(old_src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign) and \
                    any(getattr(t, "id", "") == "IMAGE_GENERATION_FALLBACK_PHRASE"
                        for t in node.targets):
                assert node.value.value == \
                    ig.IMAGE_GENERATION_FALLBACK_PHRASE
                return
        pytest.fail("IMAGE_GENERATION_FALLBACK_PHRASE не найден в baseline")

    def test_forbidden_paths_out_of_diff_vs_baseline(self):
        forbidden = [
            "services/summary_prompts.py", "services/prompt_migrations.py",
            # NOTE (A5, ADR-1026-17 D9): `services/param_catalog.py` исключён —
            # A5 санкционирует Δ каталога +1 ParamSpec +1 GroupSpec.
            "services/telegram_send.py",
            "services/chat_prompts.py",
            # NOTE (A9, ADR-1026-22 D1/D7/D10): `services/execution_graph_source.py`
            # и `web/static/execution_graph.js` исключены — A9 санкционирует
            # аддитивное расширение СУЩЕСТВУЮЩЕГО ExecutionGraph (9 этапов §51,
            # display-only; Δ DDL=0; Δ каталога=0). §104 не затронут (A3 AST).
            "web/api/routes.py", "plans/current_task.md",
        ]
        proc = subprocess.run(
            ["git", "-C", str(self._root()), "diff", "--name-only",
             self._BASELINE, "--", *forbidden],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        changed = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        assert changed == [], f"запрещённые пути изменены: {changed}"
        assert not any(ln.startswith("db/") for ln in self._diff_names())
        # NOTE (A5, ADR-1026-17 D9): web/app.js, web/index.html санкционированы
        # для UI-врезки §27/§50; A9 (ADR-1026-22 D10): + web/static/
        # execution_graph.js (display-only 9 этапов §51); api/routes.py
        # остаётся запрещён (список выше).
        assert not any(ln.startswith("web/")
                       and not ln.startswith(("web/app.js", "web/index.html",
                                              "web/static/execution_graph.js"))
                       for ln in self._diff_names())

    def _diff_names(self):
        proc = subprocess.run(
            ["git", "-C", str(self._root()), "diff", "--name-only",
             self._BASELINE],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        return [ln.strip().replace("\\", "/")
                for ln in proc.stdout.splitlines() if ln.strip()]

    def test_no_ddl_in_touched_sources(self):
        for rel in ("services/image_generation.py",
                    "services/direct_chat_service.py",
                    "services/tool_router.py", "services/tool_schemas.py",
                    "config/settings.py"):
            text = (self._root() / rel).read_text(encoding="utf-8").upper()
            assert "CREATE TABLE" not in text, rel
            assert "ALTER TABLE" not in text, rel

    def test_kill_switch_env_only_not_in_catalog(self):
        import dataclasses
        from services import param_catalog as pc
        from config.settings import APP_VERSION
        assert APP_VERSION == "2.58.31"            # bump запрещён (D8)
        assert "UNIFIED_IMAGE_REQUEST_ENABLED" not in pc.REGISTRY
        assert "UNIFIED_IMAGE_REQUEST_ENABLED" not in {
            f.name for f in dataclasses.fields(Settings)}

    def test_catalog_counts_unchanged(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 473
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21

    def test_two_llm_calls_intact(self):
        # SC-A3-12: A3 не добавляет LLM-вызовов (тест уже в coordinator-сете);
        # здесь — статическая проверка: новый код не вызывает generate_chat.
        src = (self._root() / "services/image_generation.py").read_text(
            encoding="utf-8")
        assert "generate_chat" not in src
        src2 = (self._root() / "services/tool_router.py").read_text(
            encoding="utf-8")
        assert src2.count("generate_chat(") <= 1
