"""Epic 51 (R51-2/R51-4в, Section 59.3, D211): payload-билдер.

build_messages: system на индексе 0, user = "\n\n".join(блоков) в порядке.
Guard-тест (59.5 #9): у ВСЕХ LLM-генераторов messages[0]["role"] == "system"
— мок-call захват (summary/factcheck/search/youtube/web/checkup/direct/
compress/extract; карта 59.3 + memory-генераторы).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.payload_builder import build_messages


class TestBuildMessages:
    def test_system_at_index_zero(self):
        messages = build_messages("sys", ["блок1", "блок2"])
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "sys"}
        assert messages[1] == {"role": "user", "content": "блок1\n\nблок2"}

    def test_single_block(self):
        messages = build_messages("sys", ["только один"])
        assert messages[1]["content"] == "только один"

    def test_empty_blocks(self):
        messages = build_messages("sys", [])
        assert messages[1]["content"] == ""


class _SpyLLM:
    """Захватывает messages; возвращает канон-ответ."""

    def __init__(self, text="ответ"):
        self.text = text
        self.messages = None

    async def generate(self, messages, temperature=None):
        self.messages = messages
        return self.text


def _assert_system_at_zero(llm):
    assert llm.messages is not None, "LLM не был вызван"
    assert llm.messages[0]["role"] == "system"


class TestSystemPromptGuard:
    """R51-4в: system на нулевом индексе у всех LLM-генераторов (59.5 #9)."""

    @pytest.mark.asyncio
    async def test_summary_generator(self):
        from services.summary_generator import SummaryGenerator
        from services.summary_xml import XmlGroundingBuilder

        llm = _SpyLLM()
        memory = MagicMock()
        memory.compress_and_purge = AsyncMock()
        memory.get_window_messages = AsyncMock(return_value=[
            {"id": 1, "user_id": 10, "author_name": "вася", "text": "текст",
             "timestamp": 1_700_000_000, "media_type": "text",
             "reply_to_id": None}])
        memory.search_long_term = AsyncMock(return_value=[])
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_graph_facts = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")

        generator = SummaryGenerator(memory, XmlGroundingBuilder(), llm,
                                     AsyncMock())
        await generator.generate_and_send(-100)
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_factcheck_service(self):
        from services.factcheck_service import FactCheckService

        llm = _SpyLLM()
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="результаты поиска")
        service = FactCheckService(aggregator, llm)
        await service.check_claim("проверь заявление")
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_search_service(self):
        from services.search_service import SearchService

        llm = _SpyLLM()
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="результаты поиска")
        service = SearchService(aggregator, llm)
        await service.research("как дела")
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_youtube_service(self):
        from services.youtube_summarizer_service import YoutubeSummarizerService

        llm = _SpyLLM()
        engine = MagicMock()
        engine.fetch_transcript = AsyncMock(return_value="субтитры видео")
        service = YoutubeSummarizerService(engine, llm)
        await service.summarize("dQw4w9WgXcQ")
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_web_service(self):
        from services.web_summarizer_service import WebSummarizerService

        llm = _SpyLLM()
        extractor = MagicMock()
        extractor.extract = AsyncMock(return_value="текст страницы")
        service = WebSummarizerService(extractor, llm)
        await service.summarize("https://site.ru/a")
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_checkup_service(self):
        from services.checkup_service import CheckupService

        llm = _SpyLLM()
        service = CheckupService(llm)
        await service.checkup("логи сервера", used_fallback=False)
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_direct_chat_payload(self):
        from services.direct_chat_service import DirectChatService
        from services.summary_aliases import AliasResolver

        llm = _SpyLLM()

        class FakeMemory:
            async def get_window_messages(self, chat_id):
                return []

            async def get_rag_context(self, chat_id, query, *,
                                      sort_by_timestamp=False,
                                      include_direct_reply=False):
                return ""

        class FakeDB:
            async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
                return None

        service = DirectChatService(
            FakeMemory(), FakeDB(), llm, AliasResolver("{}"),
            bot_id=12345, bot_username="test_bot")
        msg = MagicMock()
        msg.text = "привет"
        msg.message_id = 1
        msg.chat = MagicMock()
        msg.chat.id = -100
        msg.from_user = MagicMock()
        msg.from_user.id = 10
        msg.from_user.first_name = "Вася"
        msg.from_user.last_name = None
        msg.from_user.username = "vasya"
        bot = MagicMock()
        sent = MagicMock()
        sent.message_id = 50
        bot.send_message = AsyncMock(return_value=sent)
        await service.handle(bot, msg, msg.from_user)
        _assert_system_at_zero(llm)
        # канон раунда 8 (T-790): первый абзац «как читать блоки», блоки
        # СИСТЕМНАЯ РОЛЬ/ПРИОРИТЕТЫ/ИНСТРУМЕНТЫ/ограничение сохранены
        assert llm.messages[0]["content"].startswith("КАК ЧИТАТЬ КОНТЕКСТ:")
        assert "СИСТЕМНАЯ РОЛЬ:" in llm.messages[0]["content"]
        assert "ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" in llm.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_memory_compress_batch(self):
        from services.summary_memory import MemoryManager

        llm = _SpyLLM()
        memory = MemoryManager(None, llm)
        await memory._compress_batch([
            {"author_name": "вася", "text": "сообщение"}])
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_memory_extract_and_save_graph(self):
        from services.summary_memory import MemoryManager

        llm = _SpyLLM(text="[]")          # пустой JSON → нет DB-вызовов
        db = MagicMock()
        memory = MemoryManager(db, llm)
        await memory._extract_and_save_graph(-100, [
            {"author_name": "вася", "text": "сообщение"}])
        _assert_system_at_zero(llm)

    @pytest.mark.asyncio
    async def test_memory_memorize_facts_extractor(self):
        """memorize_facts → FACT_EXTRACT_PROMPT (R46-2) на индексе 0."""
        import json

        from services.summary_memory import MemoryManager

        llm = _SpyLLM(text=json.dumps([
            {"subject": "а", "subject_type": "topic",
             "predicate": "р", "object": "б", "object_type": "topic"}],
            ensure_ascii=False))
        db = MagicMock()
        db.upsert_node = AsyncMock(side_effect=[1, 2])
        db.upsert_edge = AsyncMock()
        db.insert_graph_fact = AsyncMock(return_value=10)
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, "текст", "search_fact")
        _assert_system_at_zero(llm)
