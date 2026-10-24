# -*- coding: utf-8 -*-
"""FIX-CORRECTIVE-R1 (21.10.2026) — зона 1: DIRECT-L1 planner.

Директива владельца plans/features/owner-corrective-2026-10-21.md §1
(+ Addendum #3), диагноз direct-l1-rootcause-2026-10-21.md:

  * P1: правила 2-3 канона L1 получают ПОЗИТИВНЫЕ критерии react/silent
    (silent — полноценный и часто предпочтительный исход), без списков
    конкретных слов; правило 1 и force-контракт не тронуты;
  * лестница миграций признаёт прод-байты 2.58.106 (SHA256[:16]
    99a207313889711d) и ведёт их на новый канон;
  * P2: L1-контекст получает недавние ответы бота (существующая таблица
    bot_replies, то же окно recent_reply) — секция ОТВЕТЫ БОТА;
  * P3: allowed-набор реакций доезжает до планера одной строкой факта в
    существующем блоке УСЛОВИЯ.

Никаких новых подсистем/тумблеров/хардкодов реакций (запреты §1).

TEST-LIFECYCLE: REGRESSION owner=FIX-CORRECTIVE-R1/direct-l1 (43/43 reply)
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import direct_l1 as _l1  # noqa: E402
from services.chat_prompts import (  # noqa: E402
    DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    PREV_DIRECT_L1_PLANNER_1021,
    _DIRECT_L1_PLANNER_BASE,
    _DIRECT_L1_PLANNER_RULES,
    _DIRECT_L1_PLANNER_RULES_R1028,
)
from services.direct_llm_react import ALLOWED_LLM_REACTIONS  # noqa: E402
from services.prompt_migrations import PROMPT_MIGRATIONS  # noqa: E402

#: Прод-байты 2.58.106 (direct-l1-rootcause §1: 2423 символа).
PROD_SHA16 = "99a207313889711d"


# ═══ P1: канон (правила 2-3) ════════════════════════════════════════════════

def _flatten(text: str) -> str:
    """Канон в одну строку (проверки смысла, не переносов)."""
    return " ".join(text.split())


def test_l1_rules_positive_criteria_present():
    """Правила 2-3: позитивные критерии react/silent вместо «только когда»."""
    rules = _DIRECT_L1_PLANNER_RULES
    flat = _flatten(rules)
    assert "только когда уместнее эмодзи-реакция" not in flat
    assert "только когда лучшее решение" not in flat
    # react: смысловые критерии без списков конкретных слов
    assert ("когда смысл лучше передаёт эмодзи-реакция, чем текст" in flat)
    assert "смех" in flat and "согласие" in flat
    # silent: полноценный и часто предпочтительный исход + критерии владельца
    assert ("полноценное и часто предпочтительное действие, а не отказ "
            "и не ошибка" in flat)
    for criterion in ("бессмысленным повторением",
                      "навязчивым продолжением",
                      "ненужным пояснением",
                      "вмешательством ради вмешательства"):
        assert criterion in flat, criterion
    # типичный случай из диагноза: участник лишь отреагировал на ответ бота
    assert "лишь отреагировал" in flat
    # force-контракт не задет: правило 1 байт-в-байт прежнее, схема целая
    assert "Короткая\n   реплика вроде «а этот?»" in rules
    # ASAP 2 (§4.1 asap2 source): канон = база + контракт уточнений + правила
    # SPEECH-CANON R3b: + узкое усиление продолжения (текст §4.1 цел)
    from services.chat_prompts import (_DIRECT_L1_CLARIFICATION_CONTRACT,
                                       _DIRECT_L1_CONTINUATION_R3B,
                                       _DIRECT_L1_PLANNER_BASE_R3)
    new_canon = (_DIRECT_L1_PLANNER_BASE_R3
                 + _DIRECT_L1_CLARIFICATION_CONTRACT
                 + _DIRECT_L1_CONTINUATION_R3B + rules)
    assert new_canon == DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert '"action": "reply|react|silent"' in new_canon


def test_l1_rules_no_hardcoded_word_lists():
    """Запрет §1: в правилах нет хардкода конкретных слов-триггеров."""
    rules = DIRECT_L1_PLANNER_SYSTEM_PROMPT
    for banned in ("«лол»", "«ахах", "«ок»", "лол,", "ахахаха"):
        assert banned not in rules, banned


def test_l1_rule1_and_schema_byte_preserved():
    """Правило 1 и правила 4/6-7 не менялись (force/D14 контракты целы).
    ASAP 2 (§4.1 asap2 source): единственная дельта активных правил против
    замороженных W1 — правило 5 (отсылка к контракту уточнений)."""
    from services.chat_prompts import _DIRECT_L1_PLANNER_RULES_W1
    old_rules = _DIRECT_L1_PLANNER_RULES_R1028
    new_rules = _DIRECT_L1_PLANNER_RULES
    old_r1 = old_rules.split("2. action=react")[0]
    new_r1 = new_rules.split("2. action=react")[0]
    assert old_r1 == new_r1
    # правило 4 байт-в-байт
    old_r4 = old_rules.split("4. capabilities_needed")[1].split(
        "5. needs_clarification")[0]
    new_r4 = new_rules.split("4. capabilities_needed")[1].split(
        "5. needs_clarification")[0]
    assert old_r4 == new_r4
    # хвост после правила 5 — правило 6 и дисциплина JSON байт-в-байт
    # (SPEECH-P0-CORE-SERIOUS добавил правило 7 маршрутизации личного разбора,
    # поэтому JSON-строка сдвинулась на номер 8; её текст не менялся)
    old_head = old_rules.split("6. confidence")[1].split("7. В ответе")[0]
    new_head = new_rules.split("6. confidence")[1].split("7. Просьба оценить")[0]
    assert old_head == new_head
    assert new_rules.split("8. В ответе")[1] == old_rules.split("7. В ответе")[1]
    # правило 5: единственная дельта против замороженных правил W1 —
    # отсылка к контракту; capability-запрет уточнения сохранён
    w1_r5 = _DIRECT_L1_PLANNER_RULES_W1.split(
        "5. needs_clarification")[1].split("6. confidence")[0]
    new_r5 = new_rules.split("5. needs_clarification")[1].split(
        "6. confidence")[0]
    assert new_r5 != w1_r5
    assert "«УТОЧНЕНИЯ" in new_r5 and "выше" in new_r5
    assert "не выбирай capabilities" in new_r5


# ═══ лестница миграций ══════════════════════════════════════════════════════

def test_l1_prev_snapshot_is_exact_prod_bytes():
    """Прод-канон 2.58.106 признан байт-в-байт (ADR-1013-3 слепок).
    L1D (22.10.2026): активная база заменена каноном с формой участия —
    слепок 1021 собирается из замороженной базы R1022 (байты те же)."""
    from services.chat_prompts import _DIRECT_L1_PLANNER_BASE_R1022
    assert PREV_DIRECT_L1_PLANNER_1021 == (
        _DIRECT_L1_PLANNER_BASE_R1022 + _DIRECT_L1_PLANNER_RULES_R1028)
    assert len(PREV_DIRECT_L1_PLANNER_1021) == 2423
    assert hashlib.sha256(
        PREV_DIRECT_L1_PLANNER_1021.encode("utf-8")).hexdigest()[:16] == \
        PROD_SHA16
    assert PREV_DIRECT_L1_PLANNER_1021 != DIRECT_L1_PLANNER_SYSTEM_PROMPT


def test_l1_migration_ladder_recognizes_prod_value():
    """Ступени ключа: база (без правил) и полный прод-канон → новый канон."""
    steps = PROMPT_MIGRATIONS["prompts.direct_l1_planner_system_prompt"]
    targets = {src: dst for src, dst in steps}
    assert targets[PREV_DIRECT_L1_PLANNER_1021] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    from services.chat_prompts import PREV_DIRECT_L1_PLANNER_BASE
    assert targets[PREV_DIRECT_L1_PLANNER_BASE] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # идемпотентность: новый канон не совпадает ни с одной ступенью-источником
    assert DIRECT_L1_PLANNER_SYSTEM_PROMPT not in targets


# ═══ P2: контекст планера (ответы бота) ═════════════════════════════════════

def test_autonomous_line_names_bot_replies_and_equal_outcomes():
    assert "ОТВЕТЫ БОТА" in _l1.AUTONOMOUS_LINE
    assert "равноправные исходы" in _l1.AUTONOMOUS_LINE
    assert _l1.FORCE_LINE == \
        "прямое обращение к боту: текстовый ответ обязателен"


def test_build_l1_context_includes_bot_replies_section():
    ctx = _l1.build_l1_context(
        query="лол",
        bot_replies=("Типичный ремонт: план на час, разобран весь санузел.",),
        force_line=_l1.AUTONOMOUS_LINE)
    assert _l1.BOT_REPLIES_SECTION in ctx
    assert "Типичный ремонт" in ctx


def test_build_l1_context_bot_replies_caps_and_limit():
    lines = tuple(f"ответ-{i} " + "x" * 600 for i in range(5))
    ctx = _l1.build_l1_context(query="?", bot_replies=lines)
    section = ctx.split(f"[{_l1.BOT_REPLIES_SECTION}]")[1]
    section = section.split("\n\n[")[0]
    body_lines = section.splitlines()[1:]          # без заголовка секции
    assert len(body_lines) == 3                    # максимум 3 строки
    assert all(len(ln) <= _l1.L1_REPLY_BLOCK_CHARS for ln in body_lines)


def test_build_l1_context_without_bot_replies_no_section():
    ctx = _l1.build_l1_context(query="привет", bot_replies=())
    assert _l1.BOT_REPLIES_SECTION not in ctx
    ctx_dirty = _l1.build_l1_context(query="привет",
                                     bot_replies=("", "   "))
    assert _l1.BOT_REPLIES_SECTION not in ctx_dirty


# ═══ P2/P3: факты в УСЛОВИЯХ (композиция вызывающего) ═══════════════════════

def test_conditions_line_composes_recent_and_reactions():
    """УСЛОВИЯ = autonomous/force + recent-факт + allowed-реакции."""
    parts = [_l1.AUTONOMOUS_LINE,
             "бот недавно сам отвечал в этом чате",
             "разрешённые реакции: " + " ".join(ALLOWED_LLM_REACTIONS)]
    ctx = _l1.build_l1_context(query="лол", force_line="; ".join(parts))
    conditions = ctx.split("[УСЛОВИЯ]")[1].split("\n\n[")[0].strip()
    assert _l1.AUTONOMOUS_LINE in conditions
    assert "бот недавно сам отвечал" in conditions
    for emoji in ALLOWED_LLM_REACTIONS:
        assert emoji in conditions


def test_allowed_reactions_set_is_the_existing_constant():
    """Набор = существующий ALLOWED_LLM_REACTIONS (без новых реакций)."""
    assert ALLOWED_LLM_REACTIONS == (
        "😂", "🤣", "👍", "👌", "❤️", "🔥", "🤨", "🤔", "💀", "🤡")


# ═══ сервис: чтение bot_replies (fail-open, то же окно) ═════════════════════

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.seen = None
        self.db = self          # сервис читает self.db.db.execute(...)

    async def execute(self, sql, params):
        self.seen = (sql, params)
        if self.fail:
            raise RuntimeError("db down")
        return _FakeCursor(self.rows)


class _FakeRow:
    def __init__(self, text):
        self._text = text

    def __getitem__(self, key):
        return self._text if key == "text" else None


class _ServiceStub:
    """Только _recent_bot_replies (MRO-проверка логики чтения)."""
    from services.direct_chat_service import DirectChatService as _DCS  # noqa

    _recent_bot_replies = _DCS._recent_bot_replies

    def __init__(self, db):
        self.db = db


def test_recent_bot_replies_reads_window_ordered_fail_open():
    db = _FakeDb([_FakeRow("свежий"), _FakeRow("старее")])
    svc = _ServiceStub(db)
    out = asyncio.run(svc._recent_bot_replies(777, limit=3))
    # DESC-выборка разворачивается в хронологию (старое → свежее)
    assert out == ("старее", "свежий")
    sql, params = db.seen
    assert "FROM bot_replies" in sql and "last_used_at > ?" in sql
    assert params[0] == 777
    from services.direct_chat_service import bot_replied_recently_window_seconds
    assert params[1] == pytest.approx(
        time.time() - bot_replied_recently_window_seconds(), abs=60)
    assert params[2] == 3
    # пусто/мусор отфильтрованы; fail-open → ()
    assert asyncio.run(_ServiceStub(_FakeDb([]))._recent_bot_replies(1)) == ()
    assert asyncio.run(
        _ServiceStub(_FakeDb([_FakeRow("  ")]))._recent_bot_replies(1)) == ()
    assert asyncio.run(
        _ServiceStub(_FakeDb(fail=True))._recent_bot_replies(1)) == ()
