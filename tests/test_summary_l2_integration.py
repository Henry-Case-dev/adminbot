"""S5 round1026 (ADR-1026-7 D5/D6) — интеграция L1→пакет→L2 за kill-switch.

Покрытие SC-02/SC-14: OFF-путь байт-в-байт (`_generate_two_call`), ровно 2
LLM-вызова на ОБОИХ путях (ON — на моках), флаг OFF по умолчанию, fail-closed
(не usable вход → L2 не вызывается), `content_format="html"` не ломает legacy.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services.llm_client import LLMError
from services.summary_generator import SummaryDraft, SummaryGenerator


def _generator(side_effect):
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=side_effect)
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                           bot=None)
    return gen, llm


# ── SC-02/SC-14: kill-switch default OFF + OFF-путь ────────────────────────

class TestKillSwitch:
    def test_flag_default_off(self):
        assert getattr(settings, "SUMMARY_HYBRID_L2_ENABLED", None) is False

    def test_env_only_no_catalog_key(self):
        from services import param_catalog as pc
        assert "SUMMARY_HYBRID_L2_ENABLED" not in {
            f.name for f in __import__("dataclasses").fields(
                settings.__class__)}

    @pytest.mark.asyncio
    async def test_hybrid_disabled_by_default(self, monkeypatch):
        gen, _ = _generator([])
        from services import hot_config as hot
        monkeypatch.setattr(hot, "get", lambda k, d=None: (
            False if k == "flags.summary_hybrid_l2_enabled" else d))
        assert await gen._hybrid_l2_enabled(-100) is False

    @pytest.mark.asyncio
    async def test_hybrid_enabled_when_per_chat_true(self, monkeypatch):
        gen, _ = _generator([])

        async def fake_chat_limit(chat_id, key, default):
            return True

        monkeypatch.setattr("services.summary_generator._chat_limit",
                            fake_chat_limit)
        assert await gen._hybrid_l2_enabled(-100) is True


# ── SC-02: OFF-путь `_generate_two_call` сохранён (2 вызова stage1+stage2) ──

class TestOffPath:
    @pytest.mark.asyncio
    async def test_two_calls_stage1_stage2(self):
        digest = "# Выжимка\n- что-то"
        gen, llm = _generator([digest, "готовый текст"])
        draft = await gen._generate_two_call("контент", 3800, -100)
        assert llm.generate.await_count == 2
        steps = [c.kwargs.get("step") for c in llm.generate.await_args_list]
        assert steps == ["stage1", "stage2"]
        assert draft.text == "готовый текст"

    @pytest.mark.asyncio
    async def test_no_l2_modules_imported_on_off_path(self):
        # OFF-путь не вызывает L1/L2-модули: `_generate_two_call` не знает
        # про run_l1/run_l2 (изоляция живого OFF-пути, D5).
        import services.summary_generator as sg
        import inspect
        source = inspect.getsource(sg.SummaryGenerator._generate_two_call)
        assert "run_l1" not in source and "run_l2" not in source


# ── SC-02: ON-путь на моках — ровно 2 вызова (L1+L2) ───────────────────────

class TestOnPath:
    @pytest.mark.asyncio
    async def test_two_calls_l1_l2_on_mocks(self, monkeypatch):
        from services.summary_l1_contract import L1Result
        from services.summary_fact_package import FactPackageResult

        l1_payload = {
            "schema_version": 1,
            "threads": [{
                "thread_id": "thread_001",
                "topic": "Погода",
                "message_ids": [101],
                "facts": [{"text": "шёл дождь",
                           "evidence_message_ids": [101]}],
            }],
            "unassigned_message_ids": [],
        }
        # run_l1 → 1 "вызов"; мокаем сам L1-модуль на 1 вызов llm, а L2
        # гоняем реальным run_l2 через `llm.generate`.
        l1_result = L1Result(
            status="ok", payload=l1_payload, invalid_reason=None,
            threads_count=1, facts_count=1, auto_unassigned_count=0,
            skipped_ids=(), skipped_tg_ids=(), response_mode="serious",
            cover_prompt="", duration_ms=1.0)
        package = {
            "schema_version": 1, "status": "ok",
            "threads": [{
                "thread_id": "thread_001", "name": "Погода",
                "description": "шёл дождь",
                "chronology": [{"message_id": 101, "timestamp": 1}],
                "facts": [{"text": "шёл дождь",
                           "evidence_message_ids": [101]}],
                "evidence_ids": [101],
                "fragments": [{"message_id": 101, "timestamp": 1,
                               "text": "шёл дождь"}],
            }],
            "unassigned_message_ids": [], "service": {
                "response_mode": "serious", "cover_prompt": ""},
            "budget": {"kind": "tokens", "limit": 30000, "estimated": 1,
                       "fits": True},
        }
        package_result = FactPackageResult(
            status="ok", package=package, reason="ok", metrics={}, budget={})

        l1_calls = {"n": 0}

        async def fake_run_l1(**kwargs):
            l1_calls["n"] += 1
            return l1_result

        def fake_build_package(*a, **k):
            return package_result

        # L2 получает реальный llm.generate → 1 вызов.
        doc = {"schema_version": 1, "title": "Дождь",
               "paragraphs": [{"text": "В чате был дождь.", "emphasis": None}]}
        gen, llm = _generator([json.dumps(doc, ensure_ascii=False)])
        gen.memory.compress_and_purge = AsyncMock()
        gen.memory.get_window_messages = AsyncMock(return_value=[
            {"id": 1, "tg_message_id": 101, "timestamp": 1, "text": "дождь"}])
        gen._deliver_l2_plain = AsyncMock()

        monkeypatch.setattr(
            "services.summary_l1_clusterizer.run_l1", fake_run_l1)
        monkeypatch.setattr(
            "services.summary_fact_package.build_fact_package",
            fake_build_package)
        monkeypatch.setattr(
            "services.summary_context_restore.build_l1_payload",
            lambda rows, chat_id: [{"message_id": 101, "timestamp": 1,
                                    "text": "дождь"}])

        await gen._run_hybrid_l2(
            -100, [{"id": 1, "tg_message_id": 101, "timestamp": 1,
                    "text": "дождь"}], None, "run-x")
        assert l1_calls["n"] == 1
        assert llm.generate.await_count == 1     # только L2 (L1 замокан)
        gen._deliver_l2_plain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_l1_not_usable_skips_l2(self, monkeypatch, caplog):
        from services.summary_l1_contract import invalid_result

        async def fake_run_l1(**kwargs):
            return invalid_result("invalid_json")

        gen, llm = _generator([])
        gen.memory.compress_and_purge = AsyncMock()
        gen.memory.get_window_messages = AsyncMock(return_value=[
            {"id": 1, "tg_message_id": 101, "timestamp": 1, "text": "x"}])
        gen._deliver_l2_plain = AsyncMock()
        monkeypatch.setattr(
            "services.summary_l1_clusterizer.run_l1", fake_run_l1)

        with caplog.at_level("INFO"):
            await gen._run_hybrid_l2(
                -100, [{"id": 1, "tg_message_id": 101, "timestamp": 1,
                        "text": "x"}], None, "run-y")
        assert llm.generate.await_count == 0     # L2 не вызывается
        assert "L2_SKIPPED" in caplog.text
        gen._deliver_l2_plain.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_l2_failure_no_publication(self, monkeypatch):
        from services.summary_l1_contract import L1Result

        l1_result = L1Result(
            status="ok", payload={"schema_version": 1, "threads": [{
                "thread_id": "thread_001", "topic": "t", "message_ids": [101],
                "facts": [{"text": "f", "evidence_message_ids": [101]}]}],
                "unassigned_message_ids": []},
            invalid_reason=None, threads_count=1, facts_count=1,
            auto_unassigned_count=0, skipped_ids=(), skipped_tg_ids=(),
            response_mode="serious", cover_prompt="", duration_ms=1.0)
        package = {
            "schema_version": 1, "status": "ok",
            "threads": [{"thread_id": "thread_001", "name": "t",
                         "description": "f",
                         "chronology": [{"message_id": 101, "timestamp": 1}],
                         "facts": [{"text": "f",
                                    "evidence_message_ids": [101]}],
                         "evidence_ids": [101],
                         "fragments": []}],
            "unassigned_message_ids": [], "service": {}, "budget": {}}

        async def fake_run_l1(**kwargs):
            return l1_result

        from services.summary_fact_package import FactPackageResult
        def fake_build_package(*a, **k):
            return FactPackageResult(status="ok", package=package,
                                     reason="ok", metrics={}, budget={})

        gen, llm = _generator([])
        # L2 упадёт: llm.generate поднимает LLMError.
        llm.generate = AsyncMock(side_effect=LLMError("boom"))
        gen.memory.compress_and_purge = AsyncMock()
        gen.memory.get_window_messages = AsyncMock(return_value=[
            {"id": 1, "tg_message_id": 101, "timestamp": 1, "text": "x"}])
        gen._deliver_l2_plain = AsyncMock()
        gen._deliver_l2_rich = AsyncMock()
        monkeypatch.setattr(
            "services.summary_l1_clusterizer.run_l1", fake_run_l1)
        monkeypatch.setattr(
            "services.summary_fact_package.build_fact_package",
            fake_build_package)
        monkeypatch.setattr(
            "services.summary_context_restore.build_l1_payload",
            lambda rows, chat_id: [{"message_id": 101, "timestamp": 1,
                                    "text": "x"}])

        await gen._run_hybrid_l2(
            -100, [{"id": 1, "tg_message_id": 101, "timestamp": 1,
                    "text": "x"}], None, "run-z")
        # Ровно 1 вызов (L2), публикации нет, 3-го вызова/legacy нет.
        assert llm.generate.await_count == 1
        gen._deliver_l2_plain.assert_not_awaited()
        gen._deliver_l2_rich.assert_not_awaited()


# ── SC-14: `content_format="html"` не ломает legacy (default auto) ──────────

class TestContentFormat:
    @pytest.mark.asyncio
    async def test_auto_default_unchanged_markdown(self):
        from services import telegram_send
        captured = {}

        class Bot:
            async def send_rich_message(self, chat_id, rich, **kwargs):
                captured["rich"] = rich
                captured["chat_id"] = chat_id

        await telegram_send.send_rich_message(
            Bot(), -100, "# заголовок\n\nтекст", cover_id=None)
        assert getattr(captured["rich"], "markdown", None) == "# заголовок\n\nтекст"

    @pytest.mark.asyncio
    async def test_html_format_explicit(self):
        from services import telegram_send
        captured = {}

        class Bot:
            async def send_rich_message(self, chat_id, rich, **kwargs):
                captured["rich"] = rich

        html = "<h1>Заголовок</h1><p>текст</p>"
        await telegram_send.send_rich_message(
            Bot(), -100, html, cover_id=None, content_format="html")
        assert getattr(captured["rich"], "html", None) == html


# ── S-R1026S5-1: ON-ветка ПОСЛЕ S1/S2 (фильтр → восстановление → L1) ───────

class TestOnPathAppliesS1S2:
    @pytest.mark.asyncio
    async def test_on_path_runs_filter_restore_and_feeds_l1(self, monkeypatch):
        """ON применяет S1 (`_apply_filter`) и S2 (`restore_context`), а L1
        получает уже отфильтрованный/восстановленный вход + focus-блок."""
        import services.summary_generator as sg
        from services.summary_filter import FilterResult
        from services.summary_context_restore import RestoreResult
        from services.summary_l1_contract import invalid_result

        raw_rows = [{"id": 1, "tg_message_id": 101, "timestamp": 1,
                     "text": "сырое", "user_id": 7, "author_name": "A",
                     "reply_to_id": None, "media_type": None}]
        filtered_rows = [{"id": 1, "tg_message_id": 101, "timestamp": 1,
                          "text": "отфильтровано", "user_id": 7,
                          "author_name": "A", "reply_to_id": None,
                          "media_type": None}]

        gen, _ = _generator([])
        gen.memory.compress_and_purge = AsyncMock()
        gen.memory.get_window_messages = AsyncMock(return_value=raw_rows)

        async def hybrid_on(chat_id):
            return True

        monkeypatch.setattr(gen, "_hybrid_l2_enabled", hybrid_on)

        async def chat_limit(chat_id, key, default):
            if key in ("flags.summary_filter_enabled",
                       "flags.summary_filter_reply_context_enabled"):
                return True
            return default

        monkeypatch.setattr(sg, "_chat_limit", chat_limit)
        fw_calls = {}

        def fake_filter_window(rows, params, **kw):
            fw_calls.update(kw)
            return FilterResult(
                kept=list(filtered_rows), dropped=[],
                fragments=None, source_count=len(rows),
                saved_count=len(filtered_rows),
                restored_count=0, drop_percent=0.0,
                counts={}, scores={}, budget={},
                status="ok", duration_ms=0.1)

        monkeypatch.setattr(sg, "filter_window", fake_filter_window)
        restore_calls = {"n": 0}

        def fake_restore(kept, dropped, window, params, **kw):
            restore_calls["n"] += 1
            return RestoreResult(
                kept=list(kept), restored=[], restored_count=0,
                parent_count=0, neighbor_count=0, restored_tg_ids=(),
                skipped_ids=(), budget={"fits": True}, status="ok",
                duration_ms=0.1)

        monkeypatch.setattr(sg, "restore_context", fake_restore)

        captured = {}

        async def fake_run_l1(**kwargs):
            captured["rows"] = kwargs["rows"]
            captured["focus_block"] = kwargs.get("focus_block")
            return invalid_result("invalid_json")

        monkeypatch.setattr(
            "services.summary_l1_clusterizer.run_l1", fake_run_l1)

        await gen._run(-100, True, "тема X", 555)

        assert restore_calls["n"] == 1                     # S2 вызван
        assert fw_calls.get("trigger_message_id") == 555   # маркер учтён S1
        assert captured["rows"] == filtered_rows           # L1 = S1/S2-вход
        assert captured["rows"] is not raw_rows
        assert "тема X" in (captured["focus_block"] or "")  # focus учтён


# ── L-R1026S5-2: прямой OFF-тест `_run` (legacy-цепочка + эталонный текст) ──

class TestOffPathDirect:
    @pytest.mark.system2
    @pytest.mark.asyncio
    async def test_run_off_uses_legacy_two_call_and_delivers_etalon(
            self, monkeypatch):
        import services.summary_generator as sg

        gen, _ = _generator([])
        gen.memory.compress_and_purge = AsyncMock()
        gen.memory.get_window_messages = AsyncMock(return_value=[
            {"id": 1, "tg_message_id": 101, "timestamp": 1, "text": "x",
             "user_id": 7, "author_name": "A", "reply_to_id": None,
             "media_type": None}])
        gen.memory.search_long_term = AsyncMock(return_value=[])
        gen.memory.vector_search = AsyncMock(return_value=[])
        gen.memory.get_graph_facts = AsyncMock(return_value=[])
        gen.memory.get_rag_context = AsyncMock(return_value=[])
        gen.xml.build = MagicMock(return_value="<xml/>")
        monkeypatch.setattr(sg, "fire_and_forget", lambda *a, **k: None)

        async def chat_limit(chat_id, key, default):
            return default

        monkeypatch.setattr(sg, "_chat_limit", chat_limit)
        monkeypatch.setattr(gen, "_hybrid_l2_enabled",
                            AsyncMock(return_value=False))

        etalon = SummaryDraft(text="ЭТАЛОН OFF-ПУТИ", cover_prompt="",
                              response_mode="serious")
        two_call = AsyncMock(return_value=etalon)
        monkeypatch.setattr(gen, "_generate_two_call", two_call)

        delivered = {}

        async def deliver_plain(chat_id, text):
            delivered["text"] = text

        monkeypatch.setattr(gen, "_deliver_plain", deliver_plain)

        await gen._run(-100, True)

        two_call.assert_awaited_once()                     # legacy-путь
        assert delivered["text"].startswith("ЭТАЛОН OFF-ПУТИ")
        assert "самым главным шизом объявляется A" in delivered["text"]

