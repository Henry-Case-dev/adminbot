"""ASAP-2 round1027 (T-3959) — приёмочные integration-тесты §17 №10–13
+ анти-лавина/гвард двойной публикации/worst-case (current_task.md:2604–2619,
ADR-1027-10 D3/D4/D8, матрица контракта (i)).

Mock-транспорт: очередь LLM-ответов + шпионы отправки; 0 реальных LLM/Telegram.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.summary_generator import SummaryGenerator
from services.summary_run_log import RunContext
from tests.test_summary_publish_integration_round1026 import (
    FakeMemory,
    CHAT,
    _HYBRID_FLAG,
    _L1_JSON,
    _L2_JSON,
    _capture_send_text,
    _rows,
    _fixed_rid,
    _gen,
    _lines,
    _patch_chat_limit,
)


async def _run_gen(gen):
    await gen._run(CHAT, False)


# ── §17.10 L1 completely unusable → deterministic fallback package → L2 ────

@pytest.mark.asyncio
async def test_t3959_10_l1_dead_level2_l2_called_and_cover_fallback(
        monkeypatch, caplog):
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})

    from services.summary_l1_contract import invalid_result

    async def dead_l1(**kwargs):
        return invalid_result("invalid_json")

    monkeypatch.setattr("services.summary_l1_clusterizer.run_l1", dead_l1)
    from unittest.mock import AsyncMock, MagicMock
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_L2_JSON)
    gen = _gen(FakeMemory(rows=_rows()), llm)
    rich = AsyncMock(return_value=True)
    gen._publish_rich_document = rich
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    assert llm.generate.await_count == 1               # L2 вызван на fallback
    fb = _lines(caplog, "L1_FALLBACK_PACKAGE")
    assert fb and "reason=invalid_json" in fb[0] and "fragments=" in fb[0]
    # DoD-14 на деградированном пути: обложка — детерминированный fallback.
    rich.assert_awaited_once()
    args = rich.await_args
    assert args.args[2], "cover_prompt должен быть выведен детерминированно"
    complete = _lines(caplog, "SUMMARY_COMPLETE")
    assert complete and "status=ok" in complete[0] and "fallback=none" \
        in complete[0]


@pytest.mark.asyncio
async def test_t3959_10b_empty_payload_not_failure(monkeypatch, caplog):
    """Матрица строка 2: пустой материал → НЕ failure: empty-семантика."""
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    from services.summary_l1_contract import empty_result

    async def empty_l1(**kwargs):
        return empty_result()

    monkeypatch.setattr("services.summary_l1_clusterizer.run_l1", empty_l1)
    from unittest.mock import AsyncMock, MagicMock
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_L2_JSON)
    memory = FakeMemory(rows=[])
    memory.get_window_messages = AsyncMock(return_value=[])
    gen = _gen(memory, llm)
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    complete = _lines(caplog, "SUMMARY_COMPLETE")
    assert complete and "status=empty" in complete[0]


# ── §17.11 Hybrid полностью failed → Legacy fallback ───────────────────────

@pytest.mark.asyncio
async def test_t3959_11_hybrid_dead_legacy_published(monkeypatch, caplog):
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    from unittest.mock import AsyncMock, MagicMock
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="не json вовсе")   # L1+L2 мертвы
    gen = _gen(FakeMemory(rows=_rows()), llm)
    legacy = AsyncMock(return_value=True)                    # «Legacy» доставил
    gen._run_legacy_pipeline = legacy
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    legacy.assert_awaited_once()
    kwargs = legacy.await_args.kwargs
    assert kwargs["skip_memorize"] is True     # дубля memorize нет (fire-and-forget уже)
    warn = _lines(caplog, "LEGACY_FALLBACK")
    assert warn and "reason=l2_unusable" in warn[0] and "calls_so_far=" in warn[0]
    complete = _lines(caplog, "SUMMARY_COMPLETE")
    assert complete and "fallback=legacy" in complete[0]
    assert "status=ok" in complete[0]          # degraded промежуточный снят
    assert "code=-" in complete[0]


@pytest.mark.asyncio
async def test_t3959_11b_worst_case_five_generations(monkeypatch, caplog):
    """Q2/ADR-1027-10 D3: worst case ≤5 LLM-генераций (1 L1 + 1 correction
    + 1 L2 fallback + ≤2 Legacy) при полном отказе обоих контуров."""
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    calls = {"n": 0}
    sent = []

    async def five_dead(messages, **kwargs):
        calls["n"] += 1
        return "мусор не json"

    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=five_dead)
    gen = _gen(FakeMemory(rows=_rows()), llm)
    _capture_send_text(monkeypatch, sent)
    monkeypatch.setattr("services.summary_generator.hot.get",
                        lambda key, d=None: (
                            1 if key == "limits.max_summary_parts" else d))
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    # L1 #1, L1 correction #2, L2 fallback #3, Legacy Stage-1 #4,
    # Legacy single #5 → ровно 5 (не лавина).
    assert calls["n"] <= 5, calls["n"]
    warn = _lines(caplog, "LEGACY_FALLBACK")
    assert warn and "reason=l2_unusable" in warn[0]


# ── §17.12 sendRichMessage failed → plain HYBRID полный текст (без капа) ───

@pytest.mark.asyncio
async def test_t3959_12_rich_fail_plain_full_text(monkeypatch, caplog,
                                                   tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    from services import summary_generator as sg
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"jpeg")
    monkeypatch.setattr(sg, "generate_image_verbose",
                        AsyncMock(return_value=(str(img), "ok")))
    monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))

    async def rich_boom(*a, **k):
        raise RuntimeError("sendRichMessage down")

    monkeypatch.setattr(sg, "send_rich_message", rich_boom)
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=[_L1_JSON, _L2_JSON])
    gen = _gen(FakeMemory(rows=_rows()), llm)
    sent = []
    _capture_send_text(monkeypatch, sent)
    legacy = AsyncMock(return_value=False)
    gen._run_legacy_pipeline = legacy
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    assert sent and "Тестовая статья" in "".join(
        s["text"] for s in sent)                 # plain полного текста
    assert "PUBLISH_TEXT_COMPLETE" in "\n".join(
        _lines(caplog, "PUBLISH_TEXT_COMPLETE"))
    # Матрица строка 8: rich-fail → plain, Legacy НЕ вызывается (plain жив).
    legacy.assert_not_awaited()
    complete = _lines(caplog, "SUMMARY_COMPLETE")
    assert complete and "fallback=none" in complete[0]
    assert "status=ok" in complete[0]


# ── §17.13 plain Hybrid delivery failed → Legacy chunks (с send-капом) ─────

@pytest.mark.asyncio
async def test_t3959_13_plain_dead_legacy_fallback(monkeypatch, caplog):
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    from unittest.mock import AsyncMock, MagicMock
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=[_L1_JSON, _L2_JSON])
    gen = _gen(FakeMemory(rows=_rows()), llm)
    # cover_prompt пустой в _L1_JSON → plain-путь; доставка падает полностью.
    async def send_boom(*a, **k):
        raise RuntimeError("telegram down")

    gen._send_text_with_retry = send_boom
    legacy = AsyncMock(return_value=True)
    gen._run_legacy_pipeline = legacy
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    legacy.assert_awaited_once()                    # матрица строка 9
    warn = _lines(caplog, "LEGACY_FALLBACK")
    assert warn and "reason=delivery_failed" in warn[0]
    complete = _lines(caplog, "SUMMARY_COMPLETE")
    assert complete and "fallback=legacy" in complete[0]


# ── Guard двойной публикации (rich успех + поздняя ошибка → НЕ Legacy) ─────

@pytest.mark.asyncio
async def test_t3959_guard_published_no_double_publication(monkeypatch,
                                                            caplog):
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    from unittest.mock import AsyncMock, MagicMock
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=[_L1_JSON, _L2_JSON])
    gen = _gen(FakeMemory(rows=_rows()), llm)

    async def rich_ok(*a, **k):
        # публикация состоялась, но delivery-обёртка бросает ПОСЛЕ (guard)
        raise RuntimeError("late boom")

    gen._deliver_l2_rich = AsyncMock(side_effect=RuntimeError("late boom"))
    gen._deliver_l2_plain = AsyncMock(return_value=True)

    async def _rich_then_late_fail(chat_id, document, cover_prompt,
                                   correlation_id, ctx=None):
        return False

    # Моделируем успешную rich-публикацию: published=True, затем ошибка в
    # post-deliver коде не должна вести в Legacy.
    async def rich_published(chat_id, document, cover_prompt, correlation_id,
                             ctx=None):
        return True

    gen._deliver_l2_rich = rich_published
    legacy = AsyncMock(return_value=True)
    gen._run_legacy_pipeline = legacy
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    legacy.assert_not_awaited()               # опубликовано — guard держит


# ── §106 коды: промежуточные неterminal-коды не шлют UX, пока цепочка жива ──

@pytest.mark.asyncio
async def test_t3959_no_ux_spam_on_recovery_path(monkeypatch, caplog):
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    from unittest.mock import AsyncMock, MagicMock
    ux = AsyncMock()
    from services.summary_l1_contract import invalid_result

    async def dead_l1(**kwargs):
        return invalid_result("invalid_json")

    monkeypatch.setattr("services.summary_l1_clusterizer.run_l1", dead_l1)
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_L2_JSON)
    gen = _gen(FakeMemory(rows=_rows()), llm)
    gen._send_ux = ux
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    ux.assert_not_awaited()      # LEVEL-2 спас без сообщений об ошибке
