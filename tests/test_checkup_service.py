"""Tests for services/checkup_service.py (T-330-A #24-26, Section 51.6).

system.replace({max_symbols}) → llm.generate → cleanup_llm_text; скрытая
приписка CHECKUP_FALLBACK_NOTICE в КОНЕЦ system-сообщения ровно 1 раз при
used_fallback; user = <system_logs>…</system_logs> (escape_xml_text);
LLMError пробрасывается; пустые логи валидны.
Epic 60 (64.5, T-466): db+memory → data-секция <memory_health> ДАННЫМИ
(R42-6 НЕ меняется); без db — ровно старое поведение.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import checkup_service as svc_mod
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE
from services.checkup_service import CheckupService
from services.database import DatabaseService
from services.llm_client import LLMBadResponseError, LLMError


@pytest.fixture
def make_service():
    def _make(return_value="всё горит"):
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=return_value)
        return CheckupService(llm), llm

    return _make


class TestCheckupService:
    @pytest.mark.asyncio
    async def test_max_symbols_substituted_and_context(self, make_service):
        """#24: system содержит подставленный max_symbols; приписки НЕТ;
        user = <system_logs>…</system_logs>."""
        service, llm = make_service()
        await service.checkup("some logs", used_fallback=False)
        messages = llm.generate.await_args.args[0]
        assert len(messages) == 2
        system, user = messages[0], messages[1]
        assert "{max_symbols}" not in system["content"]
        assert str(svc_mod.settings.CHECKUP_MAX_SYMBOLS) in system["content"]
        assert CHECKUP_FALLBACK_NOTICE not in system["content"]
        assert user["content"].startswith("<system_logs>")
        assert user["content"].endswith("</system_logs>")
        assert "some logs" in user["content"]

    @pytest.mark.asyncio
    async def test_fallback_notice_appended_once_at_end(self, make_service):
        """#25: used_fallback=True → приписка ровно 1 раз, в КОНЦЕ system."""
        service, llm = make_service()
        await service.checkup("logs", used_fallback=True)
        system = llm.generate.await_args.args[0][0]["content"]
        assert system.count(CHECKUP_FALLBACK_NOTICE) == 1
        assert system.endswith(CHECKUP_FALLBACK_NOTICE)
        assert system[: -len(CHECKUP_FALLBACK_NOTICE)].endswith("\n\n")

    @pytest.mark.asyncio
    async def test_logs_xml_escaped(self, make_service):
        service, llm = make_service()
        await service.checkup('<evil> & "quotes"', used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "<evil>" not in user
        assert "&lt;evil&gt;" in user

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_output(self, make_service):
        """#26: llm вернул «—»/««»»/«**» → cleanup_llm_text применился."""
        service, llm = make_service(return_value="поломка — «тест» **маркдаун**")
        result = await service.checkup("logs", used_fallback=False)
        assert result == 'поломка - "тест" **маркдаун**'
        assert "—" not in result and "«" not in result

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self, make_service):
        """#26: LLMError пробрасывается (хендлер шлёт CHECKUP_LLM_ERROR_PHRASES)."""
        service, llm = make_service()
        llm.generate = AsyncMock(side_effect=LLMError("нейронка отвалилась"))
        with pytest.raises(LLMError):
            await service.checkup("logs", used_fallback=False)

    @pytest.mark.asyncio
    async def test_empty_answer_raises_bad_response(self, make_service):
        """65.1 (T-469): пустой ответ (после cleanup) → LLMBadResponseError
        (хендлер молчит + 🗿, ничего не шлёт)."""
        service, llm = make_service(return_value="   ")
        with pytest.raises(LLMBadResponseError):
            await service.checkup("logs", used_fallback=False)

    @pytest.mark.asyncio
    async def test_empty_logs_valid(self, make_service):
        """51.6: пустые логи («» от journalctl) валидны — не dead-пул."""
        service, llm = make_service()
        result = await service.checkup("", used_fallback=True)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == "<system_logs></system_logs>"
        assert result == "всё горит"


class TestEpic49ScrubAndTruncate:
    """Epic 49 (57.5, D196): scrub C0 (кроме \\n \\t → пробел) + потолок
    CHECKUP_MAX_INPUT_SYMBOLS; кириллица не затрагивается."""

    @pytest.mark.asyncio
    async def test_scrub_control_chars(self, make_service):
        """#4: "a\\x00b\\x01c\\nd\\x7fe" → "a b c\\nd e" — C0→пробел, \\n сохранён."""
        service, llm = make_service()
        await service.checkup("a\x00b\x01c\nd\x7fe", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "a b c\nd e" in user
        assert "\x00" not in user and "\x01" not in user and "\x7f" not in user

    @pytest.mark.asyncio
    async def test_scrub_keeps_tab(self, make_service):
        """\\t НЕ заменяется (разрешён вместе с \\n)."""
        service, llm = make_service()
        await service.checkup("a\tb\nc", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "a\tb\nc" in user

    @pytest.mark.asyncio
    async def test_input_truncated_with_warning(self, make_service, caplog):
        """#5: вход 12001+ симв → user ≤ CHECKUP_MAX_INPUT_SYMBOLS, WARNING,
        кириллица цела."""
        import logging

        limit = svc_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS
        logs = "я" * (limit + 1)
        service, llm = make_service()
        with caplog.at_level(logging.WARNING):
            await service.checkup(logs, used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == f"<system_logs>{'я' * limit}</system_logs>"
        assert any("[checkup] input truncated" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_within_limit_unchanged(self, make_service):
        """#6: вход ≤ 12000 — байт-в-байт прежний путь (никаких правок)."""
        service, llm = make_service()
        await service.checkup("обычные логи без аномалий", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == "<system_logs>обычные логи без аномалий</system_logs>"


@pytest.fixture
def mem_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class TestEpic60MemoryMetrics:
    """Epic 60 (64.5/64.9 #7, T-466): метрики памяти ДАННЫМИ в user-контент;
    system-сообщение (R42-6) остаётся каноном."""

    @pytest.mark.asyncio
    async def test_metrics_appended_after_logs(self, mem_db):
        await mem_db.insert_graph_fact(-100, "озон быстрее чем вб",
                                       "search_fact", None)
        memory = MagicMock()
        memory.vec_available = False
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="отчёт")
        service = CheckupService(llm, db=mem_db, memory=memory)
        await service.checkup("some logs", used_fallback=False)
        messages = llm.generate.await_args.args[0]
        system, user = messages[0], messages[1]
        assert "{max_symbols}" not in system["content"]   # R42-6 канон не тронут
        assert user["content"].startswith("<system_logs>")
        assert "some logs" in user["content"]
        assert "&lt;memory_health&gt;" in user["content"]   # секция экранирована
        assert "graph_facts: 1" in user["content"]
        assert user["content"].index("some logs") < user["content"].index("memory_health")

    @pytest.mark.asyncio
    async def test_metrics_disabled_no_section(self, mem_db):
        await mem_db.insert_graph_fact(-100, "факт", "search_fact", None)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="x")
        service = CheckupService(llm, db=mem_db, metrics_enabled=False)
        await service.checkup("logs", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "memory_health" not in user

    @pytest.mark.asyncio
    async def test_metrics_survive_when_logs_at_limit(self, mem_db):
        """Epic 61 хотфикс (D250/T-501): логи ровно в лимит → секция метрик
        НЕ теряется (резерв длины), payload в пределах бюджета."""
        await mem_db.insert_graph_fact(-100, "факт", "search_fact", None)
        limit = svc_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="x")
        memory = MagicMock()
        memory.vec_available = False
        service = CheckupService(llm, db=mem_db, memory=memory)
        await service.checkup("я" * limit, used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "memory_health" in user          # метрики живы
        assert "&lt;memory_health&gt;" in user  # экранированы один раз

    @pytest.mark.asyncio
    async def test_no_db_keeps_old_behavior(self, make_service):
        """DI: без db — user-контент ровно как раньше (метрики пустые)."""
        service, llm = make_service()
        await service.checkup("логи", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == "<system_logs>логи</system_logs>"


class TestEpic61HotfixMetricsBudget:
    """Epic 61 (64.5 хотфикс, D250/T-501): секция метрик с резервом длины —
    метрики гарантированно живы; escape РОВНО ОДИН раз; без db/выключатель —
    поведение ПОБАЙТОВО прежнее. Тест-план (а)-(е) Section 64.5."""

    def _service(self, mem_db=None):
        memory = None
        if mem_db is not None:
            memory = MagicMock()
            memory.vec_available = False
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="отчёт")
        return CheckupService(llm, db=mem_db, memory=memory), llm

    @pytest.mark.asyncio
    async def test_long_logs_metrics_survive_within_limit(self, mem_db, caplog):
        """(а): логи ~20.5к → <memory_health> в payload ЦЕЛИКОМ (закрывающий
        тег на месте), логи ужаты ровно до бюджета (лимит соблюдён ДО escape:
        сам escape раздувает только теги секции и логи из «я» не содержит)."""
        import logging

        await mem_db.insert_graph_fact(-100, "факт", "search_fact", None)
        service, llm = self._service(mem_db)
        with caplog.at_level(logging.WARNING):
            await service.checkup("я" * 20500, used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "&lt;memory_health&gt;" in user
        assert "&lt;/memory_health&gt;" in user      # закрывающий тег на месте
        assert "graph_facts: 1" in user              # содержимое не порезано
        _, budget = next(r.args for r in caplog.records
                         if "[checkup] input truncated" in r.message)
        logs_part = user[len("<system_logs>"):
                         user.index("&lt;memory_health&gt;") - 2]
        assert len(logs_part) == budget              # логи ровно по бюджету
        assert len(user) <= svc_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS \
            + len("<system_logs></system_logs>") + 12   # +12: escape тегов

    @pytest.mark.asyncio
    async def test_short_logs_no_warning_metrics_present(self, mem_db, caplog):
        """(б): короткие логи → без WARNING обрезки, метрики на месте."""
        import logging

        await mem_db.insert_graph_fact(-100, "факт", "search_fact", None)
        service, llm = self._service(mem_db)
        with caplog.at_level(logging.WARNING):
            await service.checkup("короткие логи", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "&lt;memory_health&gt;" in user and "graph_facts: 1" in user
        assert not any("input truncated" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_disabled_or_no_db_byte_identical_old_behavior(
            self, mem_db, caplog):
        """(в): metrics_enabled=False / db=None → payload идентичен эталону
        старого поведения (в т.ч. при переполнении)."""
        import logging

        limit = svc_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS
        logs = "я" * (limit + 500)
        expected = f"<system_logs>{'я' * limit}</system_logs>"
        for kwargs in ({"db": mem_db, "metrics_enabled": False}, {}):
            llm = MagicMock()
            llm.generate = AsyncMock(return_value="x")
            service = CheckupService(llm, **kwargs)
            with caplog.at_level(logging.WARNING):
                await service.checkup(logs, used_fallback=False)
            assert llm.generate.await_args.args[0][1]["content"] == expected
            # прежний формат WARNING с прежними числами (бюджет = 12000)
            rec = next(r for r in caplog.records
                       if "[checkup] input truncated" in r.message)
            assert rec.args == (len(logs), limit)
            caplog.clear()

    @pytest.mark.asyncio
    async def test_collect_metrics_raises_fail_open(self, mem_db,
                                                    monkeypatch, caplog):
        """(г): collect_metrics бросает исключение → WARNING, payload БЕЗ
        секции, поведение ПОБАЙТОВО прежнее."""
        import logging

        async def _boom(db, memory):
            raise RuntimeError("db down")

        monkeypatch.setattr(svc_mod, "collect_metrics", _boom)
        service, llm = self._service(mem_db)
        with caplog.at_level(logging.WARNING):
            await service.checkup("логи", used_fallback=False)
        assert any("[checkup] memory metrics failed" in r.message
                   for r in caplog.records)
        assert llm.generate.await_args.args[0][1]["content"] \
            == "<system_logs>логи</system_logs>"

    @pytest.mark.asyncio
    async def test_metrics_escaped_exactly_once(self, mem_db, monkeypatch):
        """(д): спецсимволы (& < >) в метриках экранируются ровно ОДИН раз
        (нет &amp;amp; / &amp;amp;lt; и т.п.)."""
        async def _fake(db, memory):
            return "a & b < c > d"

        monkeypatch.setattr(svc_mod, "collect_metrics", _fake)
        service, llm = self._service(mem_db)
        await service.checkup("логи & хвосты", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "a &amp; b &lt; c &gt; d" in user
        assert "&amp;amp;" not in user and "&amp;lt;" not in user \
            and "&amp;gt;" not in user

    @pytest.mark.asyncio
    async def test_truncation_warning_honest_numbers(self, mem_db, caplog):
        """(е): при переполнении логов WARNING содержит реальные chars и
        бюджет логов (MAX_INPUT − len(секции метрик)), а не общий лимит."""
        import logging

        await mem_db.insert_graph_fact(-100, "факт", "search_fact", None)
        limit = svc_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS
        logs_len = 20500
        service, llm = self._service(mem_db)
        with caplog.at_level(logging.WARNING):
            await service.checkup("я" * logs_len, used_fallback=False)
        rec = next(r for r in caplog.records
                   if "[checkup] input truncated" in r.message)
        chars, budget = rec.args
        assert chars == logs_len
        assert limit - 2000 <= budget < limit   # резерв длины секции учтён
        user = llm.generate.await_args.args[0][1]["content"]
        assert "&lt;/memory_health&gt;" in user
        assert len(user) <= limit \
            + len("<system_logs></system_logs>") + 12   # +12: escape тегов
