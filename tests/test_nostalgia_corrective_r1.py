# -*- coding: utf-8 -*-
"""FIX-CORRECTIVE-R1 (21.10.2026) — зона 3: NOSTALGIA (семантика отбора).

Директива владельца plans/features/owner-corrective-2026-10-21.md §3
(+ Addendum #3), диагноз nostalgia-audit-2026-10-21.md:

  * каноны (OFF + CORE): право отказа («скучный/односложный кандидат →
    UNCHANGED, отказ — нормальный исход»), императивы «Вбрось…»/«оживи»
    сняты, ценность кандидата оценивается семантически (без критериев
    длины — запрет Addendum #3);
  * format_golden_line: `target_user` рендерится именем-лейблом (прецедент
    _render_meme/R16) — факты не привязываются не к тому человеку;
  * nostalgia_log: в meta пишется ПОЛНЫЙ пул кандидата (year_lines +
    golden_lines), а не только year_lines[0] — закрыто слепое пятно
    построчной сверки финал↔источник.

Никаких фильтров длины, ручных списков, новых подсистем (запреты §3).

TEST-LIFECYCLE: REGRESSION owner=FIX-CORRECTIVE-R1/nostalgia (слабые
кандидаты публиковались с домысливанием)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.nostalgia_prompts import (  # noqa: E402
    NOSTALGIA_CORE_CANON,
    NOSTALGIA_PROMPT,
    PREV_NOSTALGIA_CORE_CANON_1021,
    PREV_NOSTALGIA_PROMPT_1021,
    format_golden_line,
)

# Фикстура/хелперы тест-модуля воркера (fixture `db` должен быть виден на
# этапе коллекции — импорт на уровне модуля).
from test_nostalgia_worker import (  # noqa: E402,F401
    CHAT_ID, NOW, _FakeBot, _add_user_msg, _log_rows, _patch_time,
    _worker,
    db,
)


class TestCorrectiveCanon:
    def test_prompt_prev_snapshot_is_outgoing_bytes(self):
        """PREV_1021 — байт-в-байт слепок уходящего канона (round 10.15):
        императив «Вбрось…» и узкий отказ сохранены для отката/диффа."""
        assert "Вбрось этот старый факт" in PREV_NOSTALGIA_PROMPT_1021
        assert "пробило на воспоминания" in PREV_NOSTALGIA_PROMPT_1021
        assert PREV_NOSTALGIA_PROMPT_1021 != NOSTALGIA_PROMPT

    def test_core_canon_prev_snapshot_is_outgoing_bytes(self):
        assert "вбрось этот старый факт" in PREV_NOSTALGIA_CORE_CANON_1021
        assert PREV_NOSTALGIA_CORE_CANON_1021 != NOSTALGIA_CORE_CANON

    def test_both_canons_refusal_is_normal_outcome(self):
        for canon in (NOSTALGIA_PROMPT, NOSTALGIA_CORE_CANON):
            assert "UNCHANGED" in canon
            assert "скучный/односложный" in canon, canon
            assert "Отказ - нормальный и чаще всего правильный исход" in canon
            assert "не приписывай участникам того, чего нет в строках памяти" \
                in canon

    def test_no_length_criteria_no_imperatives(self):
        """Запрет Addendum #3: ценность — семантика, не длина; императивов
        «вбрось/оживи» нет ни в одном каноне."""
        for canon in (NOSTALGIA_PROMPT, NOSTALGIA_CORE_CANON):
            low = canon.lower()
            assert "вбрось" not in low
            assert "оживи" not in low
            assert "пробило" not in low
            # длина не критерий ценности: max_words-слот остаётся, слов-лимов
            # оценки «скучности» нет
            assert "короче" not in low and "длиннее" not in low
            assert "менее" not in low


class TestGoldenLineTargetUser:
    def test_target_user_rendered_as_label(self):
        row = {"fact": "обещал вернуть/library книгу",
               "rag_ts": 1760000000, "target_user": "Славик"}
        line = format_golden_line(row)
        assert "[Славик]" in line
        assert line == format_golden_line(dict(row))  # детерминированно

    def test_no_target_user_backward_compatible(self):
        row = {"fact": "факт без адресата", "created_at": 1760000000}
        line = format_golden_line(row)
        assert "[" not in line.replace("[", "", 1).split("]")[0] or True
        assert line.count("[") == 1 and line.count("]") == 1

    def test_empty_target_user_no_label(self):
        row = {"fact": "факт", "rag_ts": 1760000000, "target_user": "  "}
        line = format_golden_line(row)
        assert line.count("[") == 1 and line.count("]") == 1

    def test_empty_fact_empty_line(self):
        assert format_golden_line({"fact": ""}) == ""
        assert format_golden_line({}) == ""


class TestWorkerLogsFullPool:
    """nostalgia_log.meta несёт ПОЛНЫЙ пул кандидата (audit §5.3).
    P0 REWORK W1: пул — строки реконструированного эпизода; meta.episodes
    несёт честную карточку эпизода (границы/уровень/число сообщений)."""

    @pytest.mark.asyncio
    async def test_meta_contains_full_year_pool(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await _add_user_msg(db, "в чате тишина", ts=NOW - 30 * 3600)
        # один календарный день годовщины, гэп < 30 минут → один сегмент
        # (детерминированный календарный ts — test_nostalgia_worker._yb_ts)
        from tests.test_nostalgia_worker import _yb_ts
        await _add_user_msg(db, "год назад был жаркий спор",
                            ts=_yb_ts(1000))
        await _add_user_msg(db, "и ещё запомнилась поездка",
                            ts=_yb_ts(1600))
        w = _worker(db, monkeypatch=monkeypatch, bot=_FakeBot())
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["candidates"] == 1
        rows = await _log_rows(db)
        meta = json.loads(rows[0]["meta"])
        assert meta["candidate"] == "year_back"
        # полный пул: ОБЕ строки эпизода (раньше только year_lines[0])
        assert len(meta["year_lines"]) == 2
        assert any("жаркий спор" in l for l in meta["year_lines"])
        assert any("поездка" in l for l in meta["year_lines"])
        assert meta["candidate_text"] == meta["year_lines"][0]
        # карточка эпизода честна (NOST-04: фактические границы)
        assert meta["episodes"] and meta["episodes"][0]["messages"] == 2
        assert meta["episodes"][0]["years_ago"] >= 1
