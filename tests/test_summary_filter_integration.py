"""S1 round1026 (ADR-1026-1/1026-2) — интеграционный регресс врезки
алгоритмического префильтра в ``SummaryGenerator._run``.

Покрывает rework-блок H (Step 2b @Architect, 23.09.2026):

* **T-3160 (M-1)** — мастер-тумблер ``flags.summary_filter_enabled`` резолвится
  **per-chat** (чат A override ≠ чат B), OFF → фильтр не вызывается
  (spec §6.1/SC-05);
* **L-1 / L-R1026S1-2** — OFF = байт-в-байт прежний вход; RAG/память работают
  по **исходному** окну; ошибка фильтра не роняет Саммари (fail-open);
  при ON ровно **2** LLM-вызова (фильтр — 0 LLM);
* **L-R1026S1-1** — sentinel-нормализация потолка токенов перед бюджетом §93
  (``0`` → дефолт, ``-1`` → потолок «безлимита»).
"""
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import summary_generator as sg
from services.summary_generator import SummaryGenerator
from services.summary_xml import XmlGroundingBuilder
from services.token_counter import resolve_context_tokens

from tests.test_summary_generator import FakeMemory, _row

CHAT_A = -1001
CHAT_B = -1002
CHAT_C = -1003

_FLAG = "flags.summary_filter_enabled"
# S2 (ADR-1026-4 D4): тот же ключ — мастер-гейт восстановления контекста.
# В S1-изолированных кейсах выключаем его, чтобы XML-вход был байт-в-байт S1.
_S2_FLAG = "flags.summary_filter_reply_context_enabled"


def _rows():
    """Два сообщения: важное (@-упоминание → kept) и мусор (score 0 → dropped)."""
    return [
        _row(id=1, tg_message_id=101, user_id=10, text="@vasya привет",
             timestamp=1000),
        _row(id=2, tg_message_id=102, user_id=11, text="мусор",
             timestamp=1001),
    ]


def _patch_chat_limit(monkeypatch, overrides):
    """Стаб `get_chat_param`: per-chat override → переданный default (hot/env)."""

    async def _fake(chat_id, key, default=None):
        return overrides.get((chat_id, key), default)

    monkeypatch.setattr(sg, "_chat_limit", _fake)


def _patch_delivery(monkeypatch, rec):
    """Изоляция от публикации (D4): записываем факт доставки, без сети."""

    async def _plain(self, chat_id, text, *a, **kw):
        rec["plain"].append(text)

    async def _rich(self, chat_id, text, *a, **kw):
        rec["rich"].append(text)

    monkeypatch.setattr(SummaryGenerator, "_deliver_plain", _plain)
    monkeypatch.setattr(SummaryGenerator, "_deliver_rich", _rich)


def _gen(memory, llm):
    return SummaryGenerator(memory, XmlGroundingBuilder(), llm, AsyncMock())


def _spy_build(gen, monkeypatch, captured):
    """Захватываем аргумент `xml.build` (что именно уходит в L1-историю)."""
    real = gen.xml.build

    def _build(messages, aliases=None, trigger_message_id=None):
        captured["rows"] = messages
        return real(messages, aliases, trigger_message_id)

    monkeypatch.setattr(gen.xml, "build", _build)


class RecMemory(FakeMemory):
    """FakeMemory + запись строк, попадающих в RAG/graph-путь."""

    def __init__(self, rows=None):
        super().__init__(rows=rows)
        self.graph_rows = None

    async def get_graph_facts(self, chat_id, rows, keywords):
        self.graph_rows = list(rows)
        return []


# ── T-3160: мастер-тумблер per-chat ────────────────────────────────────────

class TestPerChatToggle:
    @pytest.mark.asyncio
    async def test_chat_a_override_differs_from_chat_b(self, monkeypatch):
        """override чата A (ON) ≠ override чата B (OFF): фильтр только для A/C."""
        memory = FakeMemory(rows=_rows())
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст")
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_B, _FLAG): False,
            (CHAT_C, _FLAG): True,
        })
        gen = _gen(memory, llm)

        applied = []

        async def _spy(self, chat_id, rows, correlation_id, trigger_message_id):
            applied.append(chat_id)
            return rows

        monkeypatch.setattr(SummaryGenerator, "_apply_filter", _spy)

        await gen._run(CHAT_A, False)
        await gen._run(CHAT_B, False)
        await gen._run(CHAT_C, False)

        # B — OFF: фильтр не вызывается вовсе (прежний вход).
        assert applied == [CHAT_A, CHAT_C]
        assert CHAT_B not in applied

    @pytest.mark.asyncio
    async def test_off_chat_flag_keeps_legacy_input(self, monkeypatch):
        """OFF тумблера (per-chat) → xml.build получает исходные rows."""
        rows = _rows()
        memory = FakeMemory(rows=rows)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст")
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        _patch_chat_limit(monkeypatch, {(CHAT_B, _FLAG): False})
        gen = _gen(memory, llm)
        captured = {}
        _spy_build(gen, monkeypatch, captured)

        await gen._run(CHAT_B, False)

        assert captured["rows"] is memory.rows        # тот же объект
        assert captured["rows"] == rows
        assert gen._filter_metrics == {}              # без метрик/счёта фильтра


# ── L-1 / L-R1026S1-2: интеграционные инварианты врезки ─────────────────────

class TestFilterIntegration:
    @pytest.mark.asyncio
    async def test_on_filters_xml_but_rag_uses_original_rows(self, monkeypatch):
        """ON: XML = kept, а RAG/graph — по исходному окну (нет регресса recall)."""
        rows = _rows()
        memory = RecMemory(rows=rows)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст")
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_A, _S2_FLAG): False,      # изоляция S1 от S2 (ADR-1026-4)
        })
        gen = _gen(memory, llm)
        captured = {}
        _spy_build(gen, monkeypatch, captured)

        await gen._run(CHAT_A, False)

        assert [r["id"] for r in captured["rows"]] == [1]          # фильтр на XML
        assert [r["id"] for r in memory.graph_rows] == [1, 2]      # RAG — исходное
        assert gen._filter_metrics[CHAT_A]["saved_count"] == 1
        assert rec["plain"]                                        # доставка состоялась

    @pytest.mark.asyncio
    async def test_filter_error_is_fail_open(self, monkeypatch, caplog):
        """Ошибка фильтра не роняет Саммари: WARNING FILTER_ERROR + unfiltered."""
        rows = _rows()
        memory = FakeMemory(rows=rows)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст саммари")
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True})
        gen = _gen(memory, llm)
        captured = {}
        _spy_build(gen, monkeypatch, captured)

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(sg, "filter_window", _boom)

        with caplog.at_level(logging.WARNING, logger=sg.__name__):
            await gen._run(CHAT_A, False)

        assert captured["rows"] is memory.rows         # fail-open → исходное окно
        assert rec["plain"]                            # Саммари не упало
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "FILTER_ERROR" in joined

    @pytest.mark.asyncio
    async def test_on_exactly_two_llm_calls(self, monkeypatch):
        """ON: фильтр алгоритмический → ровно 2 LLM-вызова (Редактор → Рассказчик)."""
        memory = FakeMemory(rows=_rows())
        editor = json.dumps({"response_mode": "casual",
                             "digest": "# Тема\n- Вася спорил с Петей",
                             "cover_prompt": ""})
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[editor, "готовый текст саммари"])
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True})
        gen = _gen(memory, llm)

        await gen._run(CHAT_A, False)

        assert llm.generate.await_count == 2           # фильтр добавил 0 вызовов


# ── L-R1026S1-1: sentinel-нормализация потолка токенов ──────────────────────

class TestTokenCeilingNormalised:
    @pytest.mark.asyncio
    async def test_zero_cap_falls_back_to_default(self, monkeypatch):
        """override 0 → дефолт (бюджет не вырождается в «фрагмент на сообщение»)."""
        memory = FakeMemory(rows=_rows())
        gen = _gen(memory, MagicMock())
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_A, _S2_FLAG): False,      # изоляция S1 от S2 (ADR-1026-4)
            (CHAT_A, "limits.summary_max_context_tokens"): 0,
        })

        kept = await gen._apply_filter(CHAT_A, _rows(), "run-1", None)

        assert [r["id"] for r in kept] == [1]          # обычная фильтрация
        budget = gen._filter_metrics[CHAT_A]["budget"]
        assert budget["kind"] == "tokens"
        assert budget["limit"] == resolve_context_tokens(0, 30000)
        assert budget["fits"] is True                  # не вырождается (0 → дефолт)

    @pytest.mark.asyncio
    async def test_negative_cap_is_unlimited_ceiling(self, monkeypatch):
        """override -1 → потолок «безлимита» (как resolve_context_tokens)."""
        memory = FakeMemory(rows=_rows())
        gen = _gen(memory, MagicMock())
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_A, _S2_FLAG): False,      # изоляция S1 от S2 (ADR-1026-4)
            (CHAT_A, "limits.summary_max_context_tokens"): -1,
        })

        await gen._apply_filter(CHAT_A, _rows(), "run-2", None)

        budget = gen._filter_metrics[CHAT_A]["budget"]
        assert budget["limit"] == resolve_context_tokens(-1, 30000)
        assert budget["fits"] is True
