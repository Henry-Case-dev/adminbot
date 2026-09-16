"""Раунд 10.20 (Фаза E, БЛОК 6) — тесты T-1907…T-1911.

Покрытие:
  * T-1907/T-1911 — Full Tool Access фактчекера: tool-сет (3 инструмента,
    флаг «Летописца» OFF → 2), реюз `chat_with_tools`/ToolRouter, лимит раундов,
    метаданные БЛОК 0 в `<chat_context>`, ЗАМЕР стоимости (число LLM-вызовов);
  * T-1908/T-1911 — функциональный блок канона фактчекера + промпт-миграция
    (`PREV_FACTCHECK_R2020` → новый канон);
  * T-1910/T-1911 — CLI retention при ЖИВОМ боте (снапшот, WAL) + fsync каталога.
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import sqlite3
import pytest

import manage
from services import memory_maintenance as mm
from services.chat_context import format_chat_context
from services.database import DatabaseService
from services.factcheck_prompts import (
    FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_R2020_SYSTEM_PROMPT,
)
from services.factcheck_service import FactCheckService
from services.llm_client import LLMChatResult, LLMToolCall
from services.prompt_migrations import PROMPT_MIGRATIONS, migrate_prompt_canons
from services.tool_schemas import factcheck_tools


# ── T-1907: tool-сет фактчекера ────────────────────────────────────────────

class TestFactcheckToolSet:
    def test_three_tools_exactly(self):
        names = [t["function"]["name"] for t in factcheck_tools(True)]
        assert names == ["dig_into_lore", "compile_lore_story",
                         "execute_web_search"]

    def test_lore_flag_off_drops_compile_lore_story(self):
        names = [t["function"]["name"] for t in factcheck_tools(False)]
        assert names == ["dig_into_lore", "execute_web_search"]

    def test_no_download_or_summarize_in_factcheck(self):
        names = {t["function"]["name"] for t in factcheck_tools(True)}
        assert "download_media" not in names
        assert "summarize_video" not in names
        assert "get_bot_health" not in names

    def test_returns_new_list_snapshot_not_mutated(self):
        first = factcheck_tools(True)
        first.pop()
        assert len(factcheck_tools(True)) == 3


# ── T-1907/T-1911: Full Tool Access через chat_with_tools ───────────────────

class _FakeLLM:
    """`generate_chat`-контракт tool-loop: очередь LLMChatResult + учёт вызовов."""

    def __init__(self, results):
        self._results = list(results)
        self.calls: list[dict] = []
        self.generate_calls = 0

    async def generate_chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self._results.pop(0)

    async def generate(self, messages, **kwargs):
        self.generate_calls += 1
        return "plain"


class _FakeRouter:
    def __init__(self, result="найдено: датированный факт"):
        self.result = result
        self.dispatched: list[tuple] = []

    async def dispatch(self, name, arguments, ctx):
        self.dispatched.append((name, arguments, ctx.chat_id))
        return self.result


def _service(tool_router, *, results, memory=None):
    aggregator = MagicMock()
    aggregator.search = AsyncMock(return_value="хиты поиска")
    llm = _FakeLLM(results)
    svc = FactCheckService(aggregator, llm, memory=memory,
                           tool_router=tool_router)
    return svc, llm


class TestFactcheckFullToolAccess:
    @pytest.mark.asyncio
    async def test_tool_router_uses_chat_with_tools(self):
        """tool_router задан → вердикт через chat_with_tools (generate_chat)."""
        router = _FakeRouter()
        svc, llm = _service(router, results=[
            LLMChatResult(content="вердикт", tool_calls=None,
                          finish_reason="stop")])
        result = await svc.check_claim("текст", chat_id=-100)
        assert result == "вердикт"
        assert len(llm.calls) == 1
        assert llm.generate_calls == 0
        passed = [t["function"]["name"] for t in llm.calls[0]["tools"]]
        assert passed == ["dig_into_lore", "compile_lore_story",
                          "execute_web_search"]

    @pytest.mark.asyncio
    async def test_dig_into_lore_dispatch_and_second_round(self):
        """Спор «кто что сказал» → dig_into_lore реально диспатчится."""
        router = _FakeRouter()
        call = LLMToolCall(id="c1", name="dig_into_lore",
                           arguments='{"query": "кто слил мем"}')
        svc, llm = _service(router, results=[
            LLMChatResult(content=None, tool_calls=[call],
                          finish_reason="tool_calls"),
            LLMChatResult(content="вот вердикт с датой", tool_calls=None,
                          finish_reason="stop")])
        result = await svc.check_claim("текст", chat_id=-100)
        assert result == "вот вердикт с датой"
        assert router.dispatched == [("dig_into_lore",
                                      {"query": "кто слил мем"}, -100)]
        assert len(llm.calls) == 2

    @pytest.mark.asyncio
    async def test_lore_flag_off_excludes_tool_from_llm(self, monkeypatch):
        from services import hot_config as hot
        monkeypatch.setattr(hot, "get",
                            lambda key, default=None: False if key ==
                            "flags.lore_compiler_enabled" else default)
        router = _FakeRouter()
        svc, llm = _service(router, results=[
            LLMChatResult(content="вердикт", tool_calls=None,
                          finish_reason="stop")])
        await svc.check_claim("текст", chat_id=-100)
        passed = [t["function"]["name"] for t in llm.calls[0]["tools"]]
        assert "compile_lore_story" not in passed

    @pytest.mark.asyncio
    async def test_no_router_keeps_old_single_generate(self):
        """tool_router=None / chat_id=None → ровно прежний одиночный вызов."""
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="старый вердикт")
        svc = FactCheckService(aggregator, llm)
        assert await svc.check_claim("текст") == "старый вердикт"
        llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_chat_id_falls_back_to_generate(self):
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="старый вердикт")
        svc = FactCheckService(aggregator, llm, tool_router=_FakeRouter())
        assert await svc.check_claim("текст", chat_id=None) == "старый вердикт"
        llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_round_limit_same_four(self):
        """Лимит раундов — общий TOOL_MAX_ROUNDS=4 (spec §7.1)."""
        from services.tool_loop import TOOL_MAX_ROUNDS
        assert TOOL_MAX_ROUNDS == 4

    @pytest.mark.asyncio
    async def test_per_chat_flag_on_overrides_global_off(self, monkeypatch):
        """S10.20-2: глобально OFF, для чата ON → compile_lore_story доступен
        (иначе модель видит тул и получает «инструмент отключен»)."""
        from services import hot_config as hot
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: (
                False if key == "flags.lore_compiler_enabled" else default))

        async def _chat_param(chat_id, key, default=None):
            if key == "flags.lore_compiler_enabled":
                return True
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            _chat_param)
        router = _FakeRouter()
        svc, llm = _service(router, results=[
            LLMChatResult(content="вердикт", tool_calls=None,
                          finish_reason="stop")])
        await svc.check_claim("текст", chat_id=-100)
        passed = [t["function"]["name"] for t in llm.calls[0]["tools"]]
        assert "compile_lore_story" in passed

    @pytest.mark.asyncio
    async def test_tool_verdict_html_tags_stripped(self):
        """S10.20-4: если модель вернула HTML-историю — теги не в plain-выдаче."""
        router = _FakeRouter()
        svc, llm = _service(router, results=[
            LLMChatResult(content="<b>история</b> вместо вердикта",
                          tool_calls=None, finish_reason="stop")])
        result = await svc.check_claim("текст", chat_id=-100)
        assert result == "история вместо вердикта"

    @pytest.mark.asyncio
    async def test_ctx_disables_verbatim_instruction(self):
        """S10.20-4: фактчекер создаёт ToolContext без «верни story ДОСЛОВНО»."""
        captured = {}

        class _CtxRouter:
            async def dispatch(self, name, arguments, ctx):
                captured["verbatim"] = ctx.lore_verbatim_instruction
                return "ok"

        call = LLMToolCall(id="c1", name="dig_into_lore",
                           arguments='{"query": "x"}')
        svc, llm = _service(_CtxRouter(), results=[
            LLMChatResult(content=None, tool_calls=[call],
                          finish_reason="tool_calls"),
            LLMChatResult(content="вердикт", tool_calls=None,
                          finish_reason="stop")])
        await svc.check_claim("текст", chat_id=-100)
        assert captured["verbatim"] is False


# ── T-1911: метаданные БЛОК 0 в контексте фактчека ──────────────────────────

class TestFactcheckMetadata:
    def _rows(self):
        return [
            {"id": 1, "tg_message_id": 501, "user_id": 7,
             "author_name": "Ваня", "text": "я такое не говорил",
             "timestamp": 1_723_000_000, "is_forward": 0,
             "forward_source": ""},
            {"id": 2, "tg_message_id": 502, "user_id": 8,
             "author_name": "Петя", "text": "говорил, вот пруф",
             "timestamp": 1_723_003_600, "is_forward": 1,
             "forward_source": "Канал X"},
        ]

    def test_chat_context_carries_canonical_metadata(self):
        block = format_chat_context(self._rows())
        assert block.startswith("<chat_context ")
        assert "[07.08.2024" in block  # ts+время в каноническом префиксе
        assert "Ваня" in block and "Петя" in block
        assert "tg:501" in block and "tg:502" in block
        assert "Переслано: Канал X" in block

    @pytest.mark.asyncio
    async def test_metadata_reaches_llm_messages(self):
        router = _FakeRouter()
        svc, llm = _service(router, results=[
            LLMChatResult(content="вердикт", tool_calls=None,
                          finish_reason="stop")])
        ctx_block = format_chat_context(self._rows())
        await svc.check_claim("текст", chat_id=-100, chat_context=ctx_block)
        user = llm.calls[0]["messages"][1]["content"]
        assert "tg:501" in user and "Переслано: Канал X" in user
        assert "<chat_context" in user


# ── T-1911: замер стоимости factcheck-цикла ────────────────────────────────

class TestFactcheckCost:
    @pytest.mark.asyncio
    async def test_direct_answer_one_llm_call(self):
        router = _FakeRouter()
        svc, llm = _service(router, results=[
            LLMChatResult(content="вердикт", tool_calls=None,
                          finish_reason="stop")])
        await svc.check_claim("текст", chat_id=-100)
        assert len(llm.calls) == 1 and router.dispatched == []

    @pytest.mark.asyncio
    async def test_one_tool_round_costs_two_calls(self):
        router = _FakeRouter()
        call = LLMToolCall(id="c1", name="execute_web_search",
                           arguments='{"query": "новость"}')
        svc, llm = _service(router, results=[
            LLMChatResult(content=None, tool_calls=[call],
                          finish_reason="tool_calls"),
            LLMChatResult(content="вердикт", tool_calls=None,
                          finish_reason="stop")])
        await svc.check_claim("текст", chat_id=-100)
        assert len(llm.calls) == 2 and len(router.dispatched) == 1


# ── T-1908: канон промпта + миграция ───────────────────────────────────────

class TestFactcheckPromptCanon:
    def test_functional_source_block_present(self):
        prompt = FACTCHECK_SYSTEM_PROMPT
        assert "ВЫБОР ИСТОЧНИКА (ФУНКЦИОНАЛЬНО, ОБЯЗАТЕЛЬНО):" in prompt
        assert "веб-поиском" in prompt
        assert "dig_into_lore" in prompt and "compile_lore_story" in prompt
        assert "ИМЕННО В ЭТОМ ЧАТЕ" in prompt
        assert "[Дата Время | Автор | Переслано: откуда]" in prompt

    def test_tone_of_voice_preserved(self):
        """TЗ стр. 244-247 (R10): тон/мат не переписаны."""
        assert "токсичный, ироничный фактчекер" in FACTCHECK_SYSTEM_PROMPT
        assert "жидко обосрался" in FACTCHECK_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире" in FACTCHECK_SYSTEM_PROMPT

    def test_prev_snapshot_is_pre_instructions(self):
        assert PREV_FACTCHECK_R2020_SYSTEM_PROMPT != FACTCHECK_SYSTEM_PROMPT
        assert "ВЫБОР ИСТОЧНИКА" not in PREV_FACTCHECK_R2020_SYSTEM_PROMPT
        assert "торопливое письмо" in PREV_FACTCHECK_R2020_SYSTEM_PROMPT

    def test_migration_step_registered(self):
        steps = PROMPT_MIGRATIONS["prompts.factcheck_system_prompt"]
        assert (PREV_FACTCHECK_R2020_SYSTEM_PROMPT,
                FACTCHECK_SYSTEM_PROMPT) in steps

    @pytest.mark.asyncio
    async def test_prev_r2020_migrates_to_new_canon(self):
        class FakeCache:
            pg_available = True

            def __init__(self, values):
                self.values = dict(values)
                self.set_calls = []

            def get(self, key, default=None):
                return self.values.get(key, default)

            async def set(self, key, value, category):
                self.set_calls.append((key, value, category))

        cache = FakeCache({
            "prompts.factcheck_system_prompt":
                PREV_FACTCHECK_R2020_SYSTEM_PROMPT})
        report = await migrate_prompt_canons(cache)
        assert report == {"prompts.factcheck_system_prompt": "updated"}
        assert cache.set_calls == [
            ("prompts.factcheck_system_prompt", FACTCHECK_SYSTEM_PROMPT,
             "prompts")]


# ── T-1910a: CLI retention при живом боте (снапшот/WAL) ─────────────────────

class TestRetentionLiveBot:
    def test_dry_run_snapshot_with_live_connection(self, tmp_path, monkeypatch,
                                                   capsys):
        """Живой процесс держит WAL-соединение → CLI dry-run НЕ падает
        (работает по временному снапшоту) и считает кандидатов."""
        import asyncio
        import time

        async def _prepare():
            db = DatabaseService(str(tmp_path / "live.db"))
            await db.initialize()
            ts_old = int(time.time()) - 10 * 86400
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, timestamp,"
                " media_type, import_key, history_processed) "
                "VALUES (1, -100, 'старьё', ?, 'text', 'k1', 1)",
                (ts_old,))
            await db.db.commit()
            return db

        live = asyncio.run(_prepare())          # «живой бот» — соединение открыто

        async def _allowed(chat_id):
            return True, 1, "default"           # 1 день → строка-кандидат
        monkeypatch.setattr(mm.retention_policy,
                            "imported_history_purge_allowed", _allowed)
        try:
            rc = manage.main(["retention", "--db", str(tmp_path / "live.db")])
            out = capsys.readouterr().out
        finally:
            asyncio.run(live.close())
        assert rc == 0
        assert "mode=dry-run" in out
        assert "candidates=1" in out
        # R17: в выводе нет путей к БД/архиву
        assert str(tmp_path) not in out

    def test_apply_uses_initialize_existing_without_ddl(self, tmp_path,
                                                        monkeypatch, capsys):
        """`--apply` открывает живую БД без DDL/миграций (initialize_existing)."""
        import asyncio

        async def _prepare():
            db = DatabaseService(str(tmp_path / "live.db"))
            await db.initialize()
            await db.close()
        asyncio.run(_prepare())

        calls = {"existing": 0, "full": 0}
        real_existing = DatabaseService.initialize_existing
        real_full = DatabaseService.initialize

        async def _spy_existing(self):
            calls["existing"] += 1
            return await real_existing(self)

        async def _spy_full(self):
            calls["full"] += 1
            return await real_full(self)

        monkeypatch.setattr(DatabaseService, "initialize_existing",
                            _spy_existing)
        monkeypatch.setattr(DatabaseService, "initialize", _spy_full)

        async def _allowed(chat_id):
            return True, 1, "default"
        monkeypatch.setattr(mm.retention_policy,
                            "imported_history_purge_allowed", _allowed)
        rc = manage.main(["retention", "--apply", "--db",
                          str(tmp_path / "live.db")])
        out = capsys.readouterr().out
        assert rc == 0
        assert calls["existing"] == 1
        assert calls["full"] == 0
        assert "mode=APPLY" in out


# ── T-1910b: fsync каталога (best-effort) ──────────────────────────────────

class TestDirFsync:
    def test_noop_on_windows_with_honest_log(self, monkeypatch, caplog,
                                             tmp_path):
        monkeypatch.setattr(mm.os, "name", "nt")
        with caplog.at_level(logging.INFO,
                             logger="services.memory_maintenance"):
            mm._fsync_directory(tmp_path)
        assert any("dir fsync skipped" in r.message for r in caplog.records)

    def test_posix_opens_and_fsyncs_dir(self, monkeypatch, tmp_path):
        seen: list = []
        monkeypatch.setattr(mm.os, "name", "posix")
        monkeypatch.setattr(mm.os, "open", lambda path, flags: 42)
        monkeypatch.setattr(mm.os, "fsync", lambda fd: seen.append(("fsync", fd)))
        monkeypatch.setattr(mm.os, "close", lambda fd: seen.append(("close", fd)))
        mm._fsync_directory(tmp_path)
        assert ("fsync", 42) in seen and ("close", 42) in seen

    def test_open_error_is_best_effort(self, monkeypatch, tmp_path, caplog):
        def _boom(path, flags):
            raise OSError("nope")
        monkeypatch.setattr(mm.os, "name", "posix")
        monkeypatch.setattr(mm.os, "open", _boom)
        with caplog.at_level(logging.WARNING,
                             logger="services.memory_maintenance"):
            mm._fsync_directory(tmp_path)      # не бросает
        assert any("dir fsync unavailable" in r.message
                   for r in caplog.records)

    def test_combined_helper_file_then_dir(self, monkeypatch, tmp_path):
        order: list = []
        monkeypatch.setattr(mm, "_flush_and_fsync",
                            lambda fh: order.append("file"))
        monkeypatch.setattr(mm, "_fsync_directory",
                            lambda d: order.append("dir"))
        mm._flush_fsync_and_dir(object(), tmp_path)
        assert order == ["file", "dir"]
