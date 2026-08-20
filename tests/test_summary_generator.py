"""Tests for services/summary_generator.py (T-186, Section 33.7)."""
import logging
import sqlite3
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch as mock_patch

import pytest
from aiogram.exceptions import TelegramRetryAfter

from config.settings import settings
from services.llm_client import LLMError
from services.summary_aliases import AliasResolver
from services.summary_generator import SummaryGenerator
from services.summary_xml import XmlGroundingBuilder


@pytest.fixture
def no_sleep(monkeypatch):
    """Replace asyncio in summary_generator with a stub whose sleep is recorded."""
    import asyncio as real_asyncio

    fake = MagicMock()
    fake.sleep = AsyncMock(return_value=None)
    fake.Lock = real_asyncio.Lock
    monkeypatch.setattr("services.summary_generator.asyncio", fake)
    return fake.sleep


class FakeMemory:
    def __init__(self, rows=None, error=None, graph_facts=None):
        self.rows = rows if rows is not None else []
        self.error = error
        self.graph_facts = graph_facts if graph_facts is not None else []
        self.events = []
        self.memorized = []
        self.rag_context = ""

    async def compress_and_purge(self, chat_id):
        self.events.append("compress")

    async def get_window_messages(self, chat_id):
        self.events.append("window")
        if self.error == "window":
            raise sqlite3.OperationalError("бд упала")
        if self.error == "generic":
            raise ValueError("что-то странное")
        return self.rows

    async def search_long_term(self, chat_id, keywords, limit):
        self.events.append("l2")
        return []

    async def vector_search(self, chat_id, query, limit):
        self.events.append("l3")
        return []

    async def get_graph_facts(self, chat_id, rows, keywords):
        if self.error == "graph":
            raise sqlite3.OperationalError("граф упал")
        return self.graph_facts

    async def memorize_facts(self, chat_id, raw_text, source_type):
        """Epic 46 (55.5): фоновый хук — фиксируем вызов, не трогаем events."""
        self.memorized.append((chat_id, raw_text, source_type))

    async def get_rag_context(self, chat_id, query):
        """Epic 46 (55.6): RAG-контекст (по умолчанию пуст — старые тесты)."""
        return self.rag_context


class FakeLLM:
    def __init__(self, text="саммари текста", error=None):
        self.text = text
        self.error = error
        self.messages = None

    async def generate(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return self.text


class RetryLLM:
    """Epic 47 (56.6): generate падает LLMError первые fail_times вызовов."""

    def __init__(self, fail_times=0, text="саммари текста"):
        self.fail_times = fail_times
        self.text = text
        self.calls = 0
        self.messages = None

    async def generate(self, messages):
        self.calls += 1
        self.messages = messages
        if self.calls <= self.fail_times:
            raise LLMError("api упал")
        return self.text


def _row(author_name="вася", text="какое-то сообщение", **kwargs):
    defaults = {
        "id": 1,
        "user_id": 10,
        "timestamp": 1_700_000_000,
        "author_name": author_name,
        "text": text,
        "reply_to_id": None,
        "media_type": "text",
    }
    defaults.update(kwargs)
    return defaults


def _make_generator(memory, llm, bot, monkeypatch=None, aliases=None):
    return SummaryGenerator(memory, XmlGroundingBuilder(), llm, bot, aliases=aliases)


class TestPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_order_and_max_symbols(self, no_sleep):
        memory = FakeMemory(rows=[_row(), _row(author_name="петя")])
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        assert memory.events == ["compress", "window", "l2", "l3"]
        system = llm.messages[0]["content"]
        assert "3800 символов" in system  # MAX_SUMMARY_PARTS=1 → 1*4000-200
        user = llm.messages[1]["content"]
        assert "<chat_history>" in user
        assert '<message id="1"' in user
        bot.send_message.assert_called_once()
        sent = bot.send_message.call_args.args[1]
        assert "самым главным шизом объявляется" in sent

    @pytest.mark.asyncio
    async def test_empty_window_no_llm_call(self, no_sleep):
        memory = FakeMemory(rows=[])
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        assert llm.messages is None
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_error_retry_then_degraded(self, no_sleep):
        memory = FakeMemory(rows=[_row()])
        llm = RetryLLM(fail_times=99)
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        bot.send_message.assert_called_once()
        sent = bot.send_message.call_args.args[1]
        assert "выжимка без нейронки:" in sent
        assert "вася: какое-то сообщение" in sent
        assert "самым главным шизом объявляется" in sent

    @pytest.mark.asyncio
    async def test_llm_error_retry_once_pause(self, no_sleep, caplog):
        memory = FakeMemory(rows=[_row()])
        llm = RetryLLM(fail_times=1)
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        with caplog.at_level(logging.WARNING):
            await generator.generate_and_send(-100)
        assert llm.calls == 2
        no_sleep.assert_awaited_once_with(settings.SUMMARY_RETRY_ONCE_PAUSE)
        bot.send_message.assert_called_once()
        sent = bot.send_message.call_args.args[1]
        assert "выжимка без нейронки:" not in sent
        assert "самым главным шизом объявляется" in sent
        assert any("summary: LLM failed — retry-once" in r.message
                   for r in caplog.records)
        assert not any("degraded summary" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_llm_error_degraded_disabled_ux_phrase(self, no_sleep, caplog):
        memory = FakeMemory(rows=[_row()])
        llm = RetryLLM(fail_times=99)
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        mod = replace(settings, SUMMARY_DEGRADED_ENABLED=False)
        with mock_patch("services.summary_generator.settings", mod):
            with caplog.at_level(logging.WARNING):
                await generator.generate_and_send(-100)
        bot.send_message.assert_called_once_with(
            -100, "не смог сделать саммари потому что упал апи"
        )
        assert any("summary: LLM failed | chat_id=-100" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_degraded_summary_limits(self):
        rows = [_row(id=i, text=f"фрагмент номер {i} " * 50) for i in range(20)]
        bot = AsyncMock()
        generator = _make_generator(FakeMemory(rows=rows), FakeLLM(), bot)
        text = generator._degraded_summary(rows)
        lines = text.splitlines()
        assert "выжимка без нейронки:" in lines[0]
        frags = [l for l in lines[1:-1] if l]
        assert len(frags) <= 15  # SUMMARY_DEGRADED_COUNT
        assert all(len(l) <= 200 for l in frags)
        assert "самым главным шизом объявляется" in text
        assert "фрагмент номер 0" in text

    @pytest.mark.asyncio
    async def test_degraded_summary_empty_rows(self):
        bot = AsyncMock()
        generator = _make_generator(FakeMemory(rows=[]), FakeLLM(), bot)
        text = generator._degraded_summary([])
        assert text.startswith("выжимка без нейронки:\nникто ничего не написал")
        assert "самым главным шизом объявляется" in text

    @pytest.mark.asyncio
    async def test_db_error_ux_phrase(self, no_sleep):
        memory = FakeMemory(rows=[_row()], error="window")
        bot = AsyncMock()
        generator = _make_generator(memory, FakeLLM(), bot)
        await generator.generate_and_send(-100)
        bot.send_message.assert_called_once_with(-100, "база данных подавилась")

    @pytest.mark.asyncio
    async def test_generic_error_ux_phrase(self, no_sleep):
        memory = FakeMemory(rows=[_row()], error="generic")
        bot = AsyncMock()
        generator = _make_generator(memory, FakeLLM(), bot)
        await generator.generate_and_send(-100)
        bot.send_message.assert_called_once_with(-100, "не смог сделать саммари")

    @pytest.mark.asyncio
    async def test_ux_send_failure_does_not_crash(self, no_sleep):
        memory = FakeMemory(rows=[_row()])
        llm = FakeLLM(error=LLMError("упал"))
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Exception("бот забанен"))
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)

    @pytest.mark.asyncio
    async def test_raw_response_logged(self, no_sleep, caplog):
        import logging

        memory = FakeMemory(rows=[_row()])
        llm = FakeLLM(text="сырой текст саммари")
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        with caplog.at_level(logging.INFO):
            await generator.generate_and_send(-100)
        assert any("summary LLM raw response" in r.message for r in caplog.records)
        assert any("сырой текст саммари" in r.message for r in caplog.records)


class TestShizPostfix:
    def test_postfix_added_when_missing(self):
        rows = [_row(author_name="вася"), _row(author_name="петя"), _row(author_name="вася")]
        text = SummaryGenerator._ensure_shiz_postfix(None, "было всякое", rows)
        assert text.endswith("самым главным шизом объявляется вася")

    def test_most_active_author_chosen(self):
        rows = [_row(author_name="петя"), _row(author_name="вася"), _row(author_name="вася")]
        text = SummaryGenerator._ensure_shiz_postfix(None, "текст", rows)
        assert text.endswith("самым главным шизом объявляется вася")

    def test_existing_postfix_not_duplicated(self):
        text = "тут уже есть самым главным шизом объявляется петя приписка"
        result = SummaryGenerator._ensure_shiz_postfix(None, text, [_row()])
        assert result == text
        assert result.count("самым главным шизом") == 1

    def test_at_symbol_stripped_from_llm_name(self):
        text = "конец. самым главным шизом объявляется @вася"
        result = SummaryGenerator._ensure_shiz_postfix(None, text, [_row()])
        assert "самым главным шизом объявляется вася" in result
        assert "объявляется @" not in result

    def test_no_rows_fallback_name(self):
        text = SummaryGenerator._ensure_shiz_postfix(None, "текст", [])
        assert text.endswith("самым главным шизом объявляется кто-то")

    def test_empty_author_rows_fallback(self):
        text = SummaryGenerator._ensure_shiz_postfix(None, "текст", [_row(author_name="")])
        assert text.endswith("самым главным шизом объявляется кто-то")


class TestChunking:
    def test_short_text_single_chunk(self):
        assert SummaryGenerator._chunk_by_whitespace("короткий текст", 4096) == ["короткий текст"]

    def test_empty_text(self):
        assert SummaryGenerator._chunk_by_whitespace("", 4096) == []

    def test_chunks_respect_limit(self):
        words = ["а" * 10] * 1000
        text = " ".join(words)
        chunks = SummaryGenerator._chunk_by_whitespace(text, 4096)
        assert len(chunks) == 3
        assert all(len(c) <= 4096 for c in chunks)
        assert " ".join(chunks) == text

    def test_never_splits_words(self):
        text = " ".join(["длинноеслово" * 100, "короткое"])
        chunks = SummaryGenerator._chunk_by_whitespace(text, 500)
        # первое слово (1200 символов) не режется и идёт целым чанком
        assert chunks[0] == "длинноеслово" * 100
        assert chunks[1] == "короткое"


class TestSendChunked:
    @pytest.mark.asyncio
    async def test_delay_between_chunks(self, no_sleep):
        bot = AsyncMock()
        generator = SummaryGenerator(FakeMemory(), XmlGroundingBuilder(), FakeLLM(), bot)
        text = " ".join(["а" * 10] * 1000)
        await generator._send_chunked(-100, text)
        assert bot.send_message.await_count == 3
        assert no_sleep.await_count == 2
        no_sleep.assert_any_await(settings.SUMMARY_CHUNK_DELAY)

    @pytest.mark.asyncio
    async def test_single_chunk_no_delay(self, no_sleep):
        bot = AsyncMock()
        generator = SummaryGenerator(FakeMemory(), XmlGroundingBuilder(), FakeLLM(), bot)
        await generator._send_chunked(-100, "один чанк")
        assert bot.send_message.await_count == 1
        no_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_retry_after_sleeps_and_retries(self, no_sleep):
        bot = AsyncMock()
        bot.send_message = AsyncMock(
            side_effect=[
                TelegramRetryAfter(method=None, message="retry", retry_after=3),
                None,
            ]
        )
        generator = SummaryGenerator(FakeMemory(), XmlGroundingBuilder(), FakeLLM(), bot)
        await generator._send_chunked(-100, "чанк")
        assert bot.send_message.await_count == 2
        no_sleep.assert_any_await(3)

    @pytest.mark.asyncio
    async def test_oversized_word_warns_but_sends(self, no_sleep, caplog):
        import logging

        bot = AsyncMock()
        generator = SummaryGenerator(FakeMemory(), XmlGroundingBuilder(), FakeLLM(), bot)
        with caplog.at_level(logging.WARNING):
            await generator._send_chunked(-100, "х" * 5000)
        assert bot.send_message.await_count == 1
        assert any("exceeds 4096" in r.message for r in caplog.records)


class TestComposeUserContent:
    def test_xml_only(self):
        result = SummaryGenerator._compose_user_content("<chat_history/>", [], [])
        assert result == "<chat_history/>"

    def test_with_memory_and_facts(self):
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>", ["кто-то: цитата"], ["факт один"]
        )
        assert "<memory>\nкто-то: цитата\n</memory>" in result
        assert "<facts>\nфакт один\n</facts>" in result

    def test_memory_and_facts_are_xml_escaped(self):
        """Review Low-2: L2/L3 контент проходит то же экранирование, что и <chat_history>."""
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>",
            ["кто-то: 1 < 2 & 3 > 2"],
            ["факт с <тегом> и & амперсандом"],
        )
        assert "1 &lt; 2 &amp; 3 &gt; 2" in result
        assert "факт с &lt;тегом&gt; и &amp; амперсандом" in result
        assert "<тегом>" not in result

    def test_memory_and_facts_control_chars_stripped(self):
        """Review Low-2: control-символы вырезаются и в <memory>/<facts>."""
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>",
            ["цитата\x00\x08с хвостом"],
            ["факт\x1fконец"],
        )
        assert "\x00" not in result
        assert "\x08" not in result
        assert "\x1f" not in result
        assert "цитатас хвостом" in result
        assert "фактконец" in result


class TestComposeGraphFacts:
    """Epic 26 (R26-3/D71/Q8): <historical_graph_facts> — ПЕРВОЙ секцией, до <chat_history>."""

    def test_default_arg_output_unchanged(self):
        """D71: default [] → вывод байт-в-байт прежний (регрессия)."""
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>", ["кто-то: цитата"], ["факт"]
        )
        assert result == "<chat_history/>\n\n<memory>\nкто-то: цитата\n</memory>\n\n<facts>\nфакт\n</facts>"

    def test_graph_section_first(self):
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>", [], [], ["[Историческая справка: вася (спорил с) петя]"]
        )
        assert result.startswith("<historical_graph_facts>")
        assert result.index("<historical_graph_facts>") < result.index("<chat_history/")

    def test_graph_facts_escaped(self):
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>",
            [],
            [],
            ["[Историческая справка: a < b & c > d (р) e]"],
        )
        assert "a &lt; b &amp; c &gt; d" in result
        assert "< b" not in result

    def test_graph_facts_control_chars_stripped(self):
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>", [], [], ["[Историческая справка: a\x00b (р) c]"]
        )
        assert "\x00" not in result

    def test_empty_graph_facts_no_section(self):
        result = SummaryGenerator._compose_user_content("<chat_history/>", [], [], [])
        assert "<historical_graph_facts>" not in result


class TestPipelineGraphFacts:
    @pytest.mark.asyncio
    async def test_run_includes_graph_facts_in_user_prompt(self, no_sleep):
        memory = FakeMemory(
            rows=[_row()],
            graph_facts=["[Историческая справка: вася (спорил с) петя]"],
        )
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        user = llm.messages[1]["content"]
        assert user.startswith("<historical_graph_facts>")
        assert "Историческая справка" in user
        bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_graph_facts_error_still_sends_summary(self, no_sleep):
        """get_graph_facts бросает → саммари всё равно отправлено без секции."""
        memory = FakeMemory(rows=[_row()], error="graph")
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        user = llm.messages[1]["content"]
        assert "<historical_graph_facts>" not in user
        assert "<chat_history>" in user
        bot.send_message.assert_called_once()


# ── Epic 46 (55.5, T-366-A #20) ───────────────────────────────────

class TestGraphRagV2Hooks:
    @pytest.mark.asyncio
    async def test_run_memorizes_chat_history_in_background(self, no_sleep):
        """#20: _run → memorize_facts(chat_history) в фоновой задаче
        (не блокирует ответ)."""
        import asyncio as real_asyncio

        memory = FakeMemory(rows=[_row()])
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        for _ in range(10):
            await real_asyncio.sleep(0)        # даём fire_and_forget-задаче выполниться
        assert len(memory.memorized) == 1
        chat_id, raw_text, source_type = memory.memorized[0]
        assert chat_id == -100
        assert source_type == "chat_history"
        assert "какое-то сообщение" in raw_text
        bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_rag_context_first_section(self, no_sleep):
        """#20: непустой RAG-контекст — ПЕРВОЙ секцией user-контента."""
        memory = FakeMemory(rows=[_row()])
        memory.rag_context = "<context>\n  <user_gossip>сплетня</user_gossip>\n</context>"
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        user = llm.messages[1]["content"]
        assert user.startswith("<context>")
        assert user.index("<context>") < user.index("<chat_history")
        assert "<chat_history>" in user
        bot.send_message.assert_called_once()

    def test_compose_rag_context_first_before_graph_and_history(self):
        """#20: порядок секций — rag → historical_graph_facts → chat_history."""
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>",
            [],
            [],
            ["[Историческая справка: вася (спорил с) петя]"],
            rag_context="<context>\n</context>",
        )
        assert result.startswith("<context>")
        assert result.index("<context>") < result.index("<historical_graph_facts>")
        assert result.index("<historical_graph_facts>") < result.index("<chat_history/")

    def test_compose_without_rag_context_unchanged(self):
        """#20: rag_context="" → вывод как раньше."""
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>", [], [], ["[Историческая справка: вася (спорил с) петя]"]
        )
        assert result == (
            "<historical_graph_facts>\n[Историческая справка: вася (спорил с) петя]\n"
            "</historical_graph_facts>\n\n<chat_history/>"
        )


class TestExtractKeywords:
    def test_top_keywords_ignore_stopwords(self):
        from services.summary_generator import _STOPWORDS

        rows = [
            _row(text="ракета летит ракета дрон"),
            _row(text="ракета и дрон"),
        ]
        keywords = SummaryGenerator._extract_keywords(rows)
        assert keywords[0] == "ракета"
        assert "дрон" in keywords
        assert all(kw not in _STOPWORDS for kw in keywords)

    def test_short_tokens_ignored(self):
        rows = [_row(text="а б в длинноеслово")]
        keywords = SummaryGenerator._extract_keywords(rows)
        assert keywords == ["длинноеслово"]


class TestManualFlag:
    """Epic 25 (B2/B4/B5): manual=True — UX-ответы; manual=False (cron) — тишина."""

    @pytest.mark.asyncio
    async def test_empty_window_manual_sends_ux(self, no_sleep):
        memory = FakeMemory(rows=[])
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100, manual=True)
        bot.send_message.assert_awaited_once_with(-100, "тут тишина, саммарить нечего")
        assert llm.messages is None

    @pytest.mark.asyncio
    async def test_empty_window_cron_silent(self, no_sleep):
        memory = FakeMemory(rows=[])
        llm = FakeLLM()
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        bot.send_message.assert_not_called()
        assert llm.messages is None

    @pytest.mark.asyncio
    async def test_lock_busy_manual_sends_busy_ux_then_queues(self, no_sleep):
        memory = FakeMemory(rows=[_row()])
        bot = AsyncMock()
        generator = _make_generator(memory, FakeLLM(), bot)

        class FakeLock:
            def locked(self):
                return True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        generator._lock = FakeLock()
        await generator.generate_and_send(-100, manual=True)
        texts = [call.args[1] for call in bot.send_message.await_args_list]
        assert texts[0] == "уже делаю саммари, подожди"
        assert any("самым главным шизом" in t for t in texts)

    @pytest.mark.asyncio
    async def test_lock_busy_cron_no_ux(self, no_sleep, caplog):
        import logging

        memory = FakeMemory(rows=[_row()])
        bot = AsyncMock()
        generator = _make_generator(memory, FakeLLM(), bot)

        class FakeLock:
            def locked(self):
                return True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        generator._lock = FakeLock()
        with caplog.at_level(logging.INFO):
            await generator.generate_and_send(-100)
        texts = [call.args[1] for call in bot.send_message.await_args_list]
        assert texts and all("уже делаю" not in t for t in texts)
        assert any("lock busy" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_lock_busy_logged_with_manual(self, no_sleep, caplog):
        import logging

        memory = FakeMemory(rows=[_row()])
        generator = _make_generator(memory, FakeLLM(), AsyncMock())

        class FakeLock:
            def locked(self):
                return True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        generator._lock = FakeLock()
        with caplog.at_level(logging.INFO):
            await generator.generate_and_send(-100, manual=True)
        assert any("lock busy — queued" in r.message and "manual=True" in r.message
                   for r in caplog.records)


# ── Epic 28 (T-214/T-218): репост-маркер, ре-резолв, cleanup ───

class TestL2QuoteForward:
    def test_forward_quote_with_source(self):
        generator = _make_generator(FakeMemory(), FakeLLM(), AsyncMock())
        row = _row(author_name="оля", text="контент", is_forward=1, forward_source="Канал X")
        assert generator._format_l2_quote(row) == 'оля (репост из "Канал X"): контент'

    def test_forward_quote_without_source(self):
        generator = _make_generator(FakeMemory(), FakeLLM(), AsyncMock())
        row = _row(author_name="оля", text="контент", is_forward=1, forward_source="")
        assert generator._format_l2_quote(row) == "оля (репост): контент"

    def test_forward_source_inner_quotes_replaced(self):
        generator = _make_generator(FakeMemory(), FakeLLM(), AsyncMock())
        row = _row(author_name="оля", text="контент", is_forward=1, forward_source='Канал "X"')
        assert generator._format_l2_quote(row) == "оля (репост из \"Канал 'X'\"): контент"

    def test_plain_quote_unchanged(self):
        generator = _make_generator(FakeMemory(), FakeLLM(), AsyncMock())
        row = _row(author_name="оля", text="контент")
        assert generator._format_l2_quote(row) == "оля: контент"

    def test_quote_author_resolved_through_aliases(self):
        generator = _make_generator(
            FakeMemory(), FakeLLM(), AsyncMock(),
            aliases=AliasResolver('{"10": "оля-алиас"}'),
        )
        row = _row(author_name="старое имя", text="контент")
        assert generator._format_l2_quote(row) == "оля-алиас: контент"


class TestMostActiveAuthorAliases:
    def test_alias_overrides_stored_name(self):
        rows = [
            _row(author_name="старый вася"),
            _row(author_name="петя"),
            _row(author_name="старый вася"),
        ]
        aliases = AliasResolver('{"10": "шкет"}')
        assert SummaryGenerator._most_active_author(rows, aliases) == "шкет"

    def test_without_aliases_old_behavior(self):
        rows = [
            _row(author_name="старый вася"),
            _row(author_name="петя"),
            _row(author_name="старый вася"),
        ]
        assert SummaryGenerator._most_active_author(rows, None) == "старый вася"

    def test_ensure_shiz_postfix_uses_generator_aliases(self):
        generator = _make_generator(
            FakeMemory(), FakeLLM(), AsyncMock(),
            aliases=AliasResolver('{"10": "шкет"}'),
        )
        text = generator._ensure_shiz_postfix("текст", [_row(author_name="старый вася")])
        assert text.endswith("самым главным шизом объявляется шкет")

    def test_ensure_shiz_postfix_none_self_old_behavior(self):
        text = SummaryGenerator._ensure_shiz_postfix(
            None, "текст", [_row(author_name="старый вася")]
        )
        assert text.endswith("самым главным шизом объявляется старый вася")


class TestCleanupApplied:
    @pytest.mark.asyncio
    async def test_cleanup_replaces_forbidden_typography(self, no_sleep):
        memory = FakeMemory(rows=[_row()])
        llm = FakeLLM(text="саммари с «ёлочками» и тире — длинным – коротким")
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        sent = bot.send_message.call_args.args[1]
        assert "«" not in sent and "»" not in sent
        assert "—" not in sent and "–" not in sent
        assert 'саммари с "ёлочками" и тире - длинным - коротким' in sent

    @pytest.mark.asyncio
    async def test_cleanup_applied_before_shiz_postfix(self, no_sleep):
        memory = FakeMemory(rows=[_row()])
        llm = FakeLLM(text="итог «шикарный» — ок")
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        await generator.generate_and_send(-100)
        sent = bot.send_message.call_args.args[1]
        assert "«" not in sent
        assert "—" not in sent
        assert sent.endswith("самым главным шизом объявляется вася")

    @pytest.mark.asyncio
    async def test_raw_log_kept_before_cleanup(self, no_sleep, caplog):
        import logging

        memory = FakeMemory(rows=[_row()])
        llm = FakeLLM(text="с «ёлочкой» — да")
        bot = AsyncMock()
        generator = _make_generator(memory, llm, bot)
        with caplog.at_level(logging.INFO):
            await generator.generate_and_send(-100)
        raw_logs = [r.message for r in caplog.records if "summary LLM raw response" in r.message]
        assert any("«ёлочкой»" in msg for msg in raw_logs)  # лог честный raw, до очистки
