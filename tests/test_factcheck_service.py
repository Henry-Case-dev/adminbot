"""Tests for services/factcheck_service.py (T-252-B, Section 42.6/42.10).

build_user_content: XML-структура, is_forward/forward_source, user_hint
опционален, escape_xml_text. check_claim: пайплайн aggregator→LLM→cleanup,
подстановка {max_symbols}, проброс ошибок.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services.factcheck_service import FactCheckService
from services.llm_client import LLMError
from services.search_aggregator import AllSearchEnginesFailedException


class TestBuildUserContent:
    def test_claim_without_attributes(self):
        content = FactCheckService.build_user_content(
            "Земля плоская", None, None, "хиты поиска"
        )
        assert content.startswith("<claim>Земля плоская</claim>")
        assert "<user_hint>" not in content
        assert "<search_results>хиты поиска</search_results>" in content

    def test_forward_source_adds_is_forward(self):
        content = FactCheckService.build_user_content(
            "текст", None, "Канал X @chx", "хиты"
        )
        assert '<claim is_forward="true" forward_source="Канал X @chx">текст</claim>' in content

    def test_user_hint_optional_and_included_when_given(self):
        without = FactCheckService.build_user_content("т", None, None, "х")
        assert "<user_hint>" not in without
        with_hint = FactCheckService.build_user_content("т", "про дату", None, "х")
        assert "<user_hint>про дату</user_hint>" in with_hint

    def test_xml_escape_applied_to_claim_and_results(self):
        content = FactCheckService.build_user_content(
            "<a> & </a>", None, None, "<b> & </b>"
        )
        assert "<claim>&lt;a&gt; &amp; &lt;/a&gt;</claim>" in content
        assert "<search_results>&lt;b&gt; &amp; &lt;/b&gt;</search_results>" in content

    def test_quote_escaped_in_forward_source(self):
        content = FactCheckService.build_user_content(
            "т", None, 'канал "во благо"', "х"
        )
        assert 'forward_source="канал &quot;во благо&quot;"' in content

    def test_user_hint_escaped(self):
        content = FactCheckService.build_user_content("т", "<x> & y", None, "х")
        assert "<user_hint>&lt;x&gt; &amp; y</user_hint>" in content


class TestCheckClaim:
    def _service(self, monkeypatch):
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="вердикт «да» — пиздеж")
        return FactCheckService(aggregator, llm), aggregator, llm

    @pytest.mark.asyncio
    async def test_pipeline_order_and_substitution(self):
        service, aggregator, llm = self._service(None)
        result = await service.check_claim("текст", "хинт", None)
        aggregator.search.assert_awaited_once_with("текст", settings.FACTCHECK_MAX_SYMBOLS)
        messages = llm.generate.await_args.args[0]
        system, user = messages[0]["content"], messages[1]["content"]
        assert str(settings.FACTCHECK_MAX_SYMBOLS) in system
        assert "{max_symbols}" not in system
        assert "Максимальный жесткий потолок" in system  # R36-2 (D120)
        assert "<claim>текст</claim>" in user
        assert "<user_hint>хинт</user_hint>" in user
        assert "<search_results>хиты</search_results>" in user

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_llm_output(self):
        service, _, _ = self._service(None)
        service.llm.generate = AsyncMock(return_value="«ёлочки» — тире")
        result = await service.check_claim("текст")
        assert result == '"ёлочки" - тире'

    @pytest.mark.asyncio
    async def test_search_failure_propagates(self):
        service, aggregator, _ = self._service(None)
        aggregator.search = AsyncMock(
            side_effect=AllSearchEnginesFailedException("все упали")
        )
        with pytest.raises(AllSearchEnginesFailedException):
            await service.check_claim("текст")
        service.llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(self):
        service, _, llm = self._service(None)
        llm.generate = AsyncMock(side_effect=LLMError("llm сдох"))
        with pytest.raises(LLMError):
            await service.check_claim("текст")

    @pytest.mark.asyncio
    async def test_forward_source_passed_to_content(self):
        service, _, _ = self._service(None)
        await service.check_claim("текст", None, "Канал")
        user = service.llm.generate.await_args.args[0][1]["content"]
        assert 'is_forward="true"' in user
        assert 'forward_source="Канал"' in user


# ── Epic 46 (55.5, T-366-A #17-18) ────────────────────────────────

class TestGraphRagV2Hooks:
    def _service_with_memory(self):
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="вердикт")
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        memory.get_rag_context = AsyncMock(return_value="")
        return FactCheckService(aggregator, llm, memory=memory), aggregator, llm, memory

    @pytest.mark.asyncio
    async def test_memory_none_old_path_no_create_task(self, monkeypatch):
        """#17: memory=None → create_task НЕ вызван."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        service, _, llm = TestCheckClaim._service(self, None)
        result = await service.check_claim("текст", "хинт", None)
        assert result == 'вердикт "да" - пиздеж'
        assert spy == []
        user = llm.generate.await_args.args[0][1]["content"]
        assert "<claim>текст</claim>" in user

    @pytest.mark.asyncio
    async def test_memory_set_create_task_and_raw_memorize(self, monkeypatch):
        """#18: create_task вызван; вердикт возвращается (не блокирует);
        memorize — с raw-результатами поиска."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        service, _, llm, memory = self._service_with_memory()
        result = await service.check_claim("текст", None, None, chat_id=-100)
        assert result == "вердикт"
        assert len(spy) == 1
        await spy[0]        # выполняем фоновую задачу вручную (детерминизм)
        memory.memorize_facts.assert_awaited_once_with(-100, "хиты", "search_fact")
        memory.get_rag_context.assert_awaited_once_with(-100, "текст")
        user = llm.generate.await_args.args[0][1]["content"]
        assert "<claim>текст</claim>" in user

    @pytest.mark.asyncio
    async def test_rag_context_prefixed_to_user_content(self, monkeypatch):
        """55.5/55.6: RAG-контекст — префикс user-контента (до <claim>)."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        service, _, llm, memory = self._service_with_memory()
        memory.get_rag_context = AsyncMock(return_value="<context>ctx</context>")
        await service.check_claim("текст", None, None, chat_id=-100)
        await spy[0]        # выполняем фоновую задачу вручную (детерминизм)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user.startswith("<context>ctx</context>\n\n<claim>текст</claim>")
