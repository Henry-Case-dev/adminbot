# -*- coding: utf-8 -*-
"""P0C-INT R2: требование «первое предложение — суть» стоит последним.

TEST-LIFECYCLE: CONTRACT
owner=P0-SPEECH/hotfix
why=`probes_final4.md` §6: директива из plan-блока доезжает 1×, но модель всё
    равно открывала 2 ответа из 8 подводкой («Давай посмотрим…»). После
    plan-блока идут Global_Context, Target_User и Current_Question, поэтому
    ограничение стояло далеко от последнего слова. Здесь фиксируется: краткое
    положительное требование — ПОСЛЕДНИЙ блок user-части, ровно один раз, в
    system его нет; основная директива остаётся в plan-блоке.
replace_when=если порядок user-блоков L2 Writer изменится по контракту.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import direct_l1 as l1  # noqa: E402
from services import prompt_style_blocks as psb  # noqa: E402

QUESTIONS = "\n".join(["МАРКЕР_ВОПРОСА"])
CURRENT = "<Current_Question>\n%s\n</Current_Question>" % QUESTIONS
GLOBAL_CTX = "<Global_Context>\nокно чата\n</Global_Context>"


class _StubLLM:
    def __init__(self) -> None:
        self.captured: list[dict] = []

    async def generate(self, messages, **kwargs):
        self.captured.append({"messages": [dict(m) for m in messages],
                              "step": kwargs.get("step")})
        return "ЗАГЛУШКА ОТВЕТА"


def _service(llm):
    from services.direct_chat_service import DirectChatService as D

    class _Svc:
        _l2_write_answer = D._l2_write_answer
        _compose_speech_system = D._compose_speech_system

        def __init__(self, llm_):
            self.llm = llm_
            self.memory = None
            self.db = None
            self.bot_id = 999
            self.aliases = None

    return _Svc(llm)


async def _run_writer(response_act: str):
    llm = _StubLLM()
    plan = l1.normalize_l1_plan({
        "action": "reply", "response_act": response_act, "extent": "compact",
        "structure": "answer", "delivery_hint": "plain", "confidence": 0.9})
    plan_block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan),
        modes_on=True)
    result = await _service(llm)._l2_write_answer(
        -1001, QUESTIONS, temperature=0.7, plan_block=plan_block,
        user_blocks=[GLOBAL_CTX, CURRENT])
    assert result is not None, "L2 writer не ответил"
    messages = llm.captured[-1]["messages"]
    return messages[0]["content"], messages[1]["content"]


@pytest.mark.asyncio
async def test_closing_requirement_is_the_last_user_block():
    system, user = await _run_writer("research")
    assert user.count(psb.NO_META_CLOSING_TEXT) == 1
    assert user.rstrip().endswith(psb.NO_META_CLOSING_TEXT.strip())
    assert user.index(psb.NO_META_CLOSING_TEXT) > user.index(
        "</Current_Question>")
    assert psb.NO_META_CLOSING_TEXT not in system


@pytest.mark.asyncio
async def test_main_directive_stays_in_plan_block():
    _, user = await _run_writer("research")
    assert user.count(psb.NO_META_STRUCTURE_TEXT) == 1
    assert user.index(psb.NO_META_STRUCTURE_TEXT) < user.index(
        "<Current_Question>")


@pytest.mark.asyncio
async def test_plain_answer_also_gets_closing_but_no_analysis_texts():
    _, user = await _run_writer("answer")
    assert user.count(psb.NO_META_CLOSING_TEXT) == 1
    assert user.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 0
    assert user.count(psb.ANALYSIS_WRITER_TEXT) == 0


@pytest.mark.asyncio
async def test_closing_is_announcement_only_and_keeps_no_length_or_schema():
    """Решение владельца 26.10.2026: хвост запрещает только анонс.

    Никакого «первое предложение — суть», никакой композиции: только
    «не сообщай, что сейчас сделаешь».
    """
    text = psb.NO_META_CLOSING_TEXT
    assert "анонс" in text.lower()
    assert "сейчас сделаешь" in text.lower()
    # снятая формула и любое управление композицией/длиной
    for banned in ("первое предложение", "сразу суть", "сразу", "вывод",
                   "заключ", "начинай", "начни", "порядок", "символ",
                   "токен", "не длиннее", "не короче", "пункт"):
        assert banned not in text.lower(), banned


@pytest.mark.asyncio
async def test_payload_has_no_start_with_conclusion_formula():
    """В собранном payload нет формулы «начинай с вывода/заключения»."""
    for act in ("research", "answer"):
        _, user = await _run_writer(act)
        low = user.lower()
        for banned in ("первое предложение", "сразу суть", "сразу вывод",
                       "начинай с вывода", "начни с вывода",
                       "начинай с заключения"):
            assert banned not in low, (act, banned)
