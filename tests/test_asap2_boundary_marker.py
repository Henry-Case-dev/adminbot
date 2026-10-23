# -*- coding: utf-8 -*-
"""ASAP2 T10-BOUNDARY / CLAR-CTX-HONEST — честная пометка границы истории.

Первоисточник: plans/features/asap2-direct-chat/source-2026-10-22.md
§6.1 #10 («ответ из видимой части с честным указанием ограничения»),
§3.4 («недостаток контекста»), §3.5 (граница знания). Реализация — одна
строка данных в существующей сборке (`ГРАНИЦА ИСТОРИИ`), без анализаторов,
порогов и новых подсистем. 0 LLM, 0 сети, 0 БД.

TEST-LIFECYCLE: CONTRACT owner=ASAP2-T10-BOUNDARY (§6.1 #10/§3.4/§3.5)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import direct_l1 as _l1  # noqa: E402
from services import direct_chat_service as dcs  # noqa: E402

MARKER = f"[{_l1.HISTORY_SCOPE_SECTION}]"


def _window(n: int, *, prefix: str = "реплика") -> list[dict]:
    return [{"author_name": "Кирилл", "text": f"{prefix} номер {i}",
             "timestamp": 1_700_000_000 + i, "user_id": 101,
             "media_type": None}
            for i in range(n)]


def _build(window, **kw) -> str:
    return _l1.build_l1_context(query="запрос", window=window, **kw)


# ── усечённое окно → пометка присутствует ───────────────────────────────────

def test_partial_flag_adds_single_marker():
    text = _build(_window(3), history_partial=True)
    assert text.count(MARKER) == 1
    assert _l1.HISTORY_PARTIAL_LINE in text


def test_window_above_l1_limit_marks_without_flag():
    text = _build(_window(_l1.L1_WINDOW_MESSAGES + 5))
    assert text.count(MARKER) == 1


def test_cap_context_trim_marks(monkeypatch):
    # 20 строк не влезают в бюджет → _cap_context режет окно сам;
    # факт среза обязан стать видимым (раньше резал молча).
    text = _build(_window(_l1.L1_WINDOW_MESSAGES, prefix="x" * 120),
                  budget_tokens=200)
    assert text.count(MARKER) == 1
    # вопрос и его хвост не потеряны (структурные блоки неприкосновенны)
    assert "[СООБЩЕНИЕ]" in text and "запрос" in text


# ── полное окно → пометки нет ───────────────────────────────────────────────

def test_full_window_has_no_marker():
    text = _build(_window(3))
    assert MARKER not in text and _l1.HISTORY_PARTIAL_LINE not in text


def test_empty_window_without_flag_has_no_marker():
    text = _build([])
    assert MARKER not in text


# ── пометка не ломает payload и не приносит имён/текстов ────────────────────

def test_marker_carries_no_history_content():
    window = _window(4, prefix="секретное-слово")
    text = _build(window, history_partial=True)
    marker_body = text.split(MARKER, 1)[1]
    marker_body = marker_body.split("\n\n", 1)[0]
    assert "секретное-слово" not in marker_body
    assert "Кирилл" not in marker_body
    # остальной payload по-прежнему содержит историю и заголовки
    assert "[ПОСЛЕДНИЕ СООБЩЕНИЯ]" in text
    assert "Кирилл: секретное-слово номер 0" in text


# ── факт из БД: только реальное наличие более старых сообщений ──────────────

class _FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple] = []

    async def get_smart_raw(self, chat_id, older_than_ts=None, limit=1, **kw):
        self.calls.append((chat_id, older_than_ts, limit))
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


@pytest.mark.asyncio
async def test_history_partial_true_when_older_rows_exist():
    window = _window(2)
    db = _FakeDb([{"id": 1, "timestamp": 1}])
    svc = SimpleNamespace(db=db)
    assert await dcs.DirectChatService._history_partial(svc, 7, window) is True
    # ровно один read-only запрос, кат-офф = самое раннее видимое сообщение
    assert db.calls == [(7, window[0]["timestamp"], 1)]


@pytest.mark.asyncio
async def test_history_partial_false_for_full_window_and_on_failure():
    window = _window(2)
    assert await dcs.DirectChatService._history_partial(
        SimpleNamespace(db=_FakeDb([])), 7, window) is False
    assert await dcs.DirectChatService._history_partial(
        SimpleNamespace(db=_FakeDb(RuntimeError("db down"))), 7, window) is False
    # неожиданный тип ответа (мок/ошибка слоя) — пометки нет
    assert await dcs.DirectChatService._history_partial(
        SimpleNamespace(db=_FakeDb("string")), 7, window) is False
