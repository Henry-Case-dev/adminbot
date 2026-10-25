# -*- coding: utf-8 -*-
"""SPEECH-CANON R3b — канон = фактическое поведение (T20 + T10-BOUNDARY).

T20 (matrix §6.3 #20): после ответа человека на собственный уточняющий вопрос
бот продолжает исходную задачу, а не спрашивает о том же снова.
T10-BOUNDARY (matrix §6.1 #10): если в контексте есть пометка о том, что видна
только часть истории, ответ один раз честно называет это ограничение и не
публикует служебную метку.

Доказывается офлайн (0 LLM): байты канонов, отсутствие примеров фраз,
ступени лестницы/откат/идемпотентность/кастом. Живые прогоны — evidence/r3b.

TEST-LIFECYCLE: CONTRACT owner=SPEECH-CANON-R3B/T20+T10
"""
from __future__ import annotations

import hashlib

import pytest

from services import chat_prompts as cp
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services.prompt_style_blocks import resolve_prompt

L1_KEY = "prompts.direct_l1_planner_system_prompt"
L2_KEY = "prompts.direct_chat_verbalizer_system_prompt"


class _Cache:
    """ConfigCache-контракт: pg_available, sync get, async set (как в миграциях)."""

    def __init__(self, values=None, pg_available=True):
        self.pg_available = pg_available
        self.values = dict(values or {})
        self.set_calls = []
        # Провенанс (``character.prompt_history``) — отдельный журнал, не
        # «запись канона»: миграция пишет туда аттестацию ступени (P0-PROMPTS).
        self.provenance_sets = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        if key == "character.prompt_history":
            self.provenance_sets.append((key, value, category))
            self.values[key] = value
            return
        self.set_calls.append((key, value, category))

    def apply_writes(self):
        for key, value, _cat in self.set_calls:
            self.values[key] = value


# ── L2: граница истории (T10-BOUNDARY) ──────────────────────────────────────

def test_l2_boundary_instruction_present_once_and_narrow():
    canon = cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    para = cp._VERBALIZER_HISTORY_BOUNDARY_R3B
    assert canon.count(para) == 1
    # инструкция внутри раздела «КАК ПИСАТЬ», до «ВЫХОД»
    assert canon.index("КАК ПИСАТЬ") < canon.index(para) < canon.index("ВЫХОД")
    # одна узкая смысловая инструкция: назвать ограничение один раз,
    # пометку не цитировать, служебное не публиковать
    for anchor in ("один раз", "назови это ограничение", "обычными словами",
                   "не выдавай невидимое за известное", "не цитируй",
                   "служебные обозначения не публикуй"):
        assert anchor in para, anchor
    # примеров фраз и служебных литералов в инструкции нет
    for banned in ("«", "»", "например", "ГРАНИЦА ИСТОРИИ",
                   cp._VERBALIZER_HISTORY_BOUNDARY_R3B and
                   "более ранняя история не передана",
                   "показана только часть истории"):
        assert banned not in para, banned


def test_l2_owner_paragraphs_byte_intact():
    """Абзацы владельца §4.2 не пересказаны: канон = §3.1 + §4.2 + R3b."""
    anchor = cp._VERBALIZER_KAK_PISAT_ANCHOR
    prev = cp._ASAP_W1_VERBALIZER_31.replace(
        anchor, anchor + "\n\n" + cp._VERBALIZER_CLAR_PARAGRAPHS, 1)
    assert cp.PREV_CHAT_VERBALIZER_CLAR == prev
    assert cp.DIRECT_VERBALIZER_SYSTEM_PROMPT == prev.replace(
        cp._VERBALIZER_CLAR_PARAGRAPHS,
        cp._VERBALIZER_CLAR_PARAGRAPHS + "\n\n"
        + cp._VERBALIZER_HISTORY_BOUNDARY_R3B, 1)
    assert cp.DIRECT_VERBALIZER_SYSTEM_PROMPT != prev
    assert hashlib.sha256(
        cp.PREV_CHAT_VERBALIZER_CLAR.encode("utf-8")).hexdigest()[:12] == \
        "d1b210c156c8"


# ── L1: продолжение после уточнения (T20) ──────────────────────────────────

def test_l1_continuation_instruction_present_once_and_semantic():
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    para = cp._DIRECT_L1_CONTINUATION_R3B
    assert canon.count(para) == 1
    # внутри секции «УТОЧНЕНИЯ…», до ПРАВИЛ
    assert canon.index("УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА") < \
        canon.index(para) < canon.index("ПРАВИЛА:")
    for anchor in ("была уточняющим вопросом", "является ответом на него",
                   "считай недостающий предмет названным",
                   "не задавай тот же вопрос снова",
                   "задаётся один раз"):
        assert anchor in para, anchor
    # смысловые критерии, без перечней ключевых слов и примеров фраз
    for banned in ("«", "»", "URL", "url", "например", "http"):
        assert banned not in para, banned


def test_l1_owner_contract_byte_intact():
    """Текст владельца §4.1 в каноне не изменён ни на байт (R3b — добавка)."""
    contract = cp._DIRECT_L1_CLARIFICATION_CONTRACT
    assert contract in cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # SPEECH-P0-CORE-SERIOUS: правила R3b заморожены, активные правила — их
    # байты + правило 7 (личный разбор); слепок R3 собирается из R3b.
    assert cp.PREV_DIRECT_L1_PLANNER_R3 == (
        cp._DIRECT_L1_PLANNER_BASE_R3 + contract
        + cp._DIRECT_L1_PLANNER_RULES_R3B)
    assert cp.PREV_DIRECT_L1_PLANNER_R3B == (
        cp._DIRECT_L1_PLANNER_BASE_R3 + contract
        + cp._DIRECT_L1_CONTINUATION_R3B + cp._DIRECT_L1_PLANNER_RULES_R3B)
    assert cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT == (
        cp._DIRECT_L1_PLANNER_BASE_R3 + contract
        + cp._DIRECT_L1_CONTINUATION_R3B + cp._DIRECT_L1_PLANNER_RULES)
    assert hashlib.sha256(
        cp.PREV_DIRECT_L1_PLANNER_R3.encode("utf-8")).hexdigest()[:12] == \
        "ab6817a18657"
    assert hashlib.sha256(
        cp.PREV_DIRECT_L1_PLANNER_R3B.encode("utf-8")).hexdigest()[:12] == \
        "6c2ddc17c998"
    assert cp.PREV_DIRECT_L1_PLANNER_R3B != cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT


# ── лестница, откат, идемпотентность, кастом ────────────────────────────────

def test_ladder_and_rollback_chain():
    steps_l1 = dict(pm.PROMPT_MIGRATIONS[L1_KEY])
    steps_l2 = dict(pm.PROMPT_MIGRATIONS[L2_KEY])
    assert steps_l1[cp.PREV_DIRECT_L1_PLANNER_R3B] == \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert steps_l1[cp.PREV_DIRECT_L1_PLANNER_R3] == \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert steps_l2[cp.PREV_CHAT_VERBALIZER_CLAR] == \
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    # прежние ступени стека целы
    assert steps_l1[cp.PREV_DIRECT_L1_PLANNER_CLAR] == \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # цепочка отката: L1 — material-priority → P0CS2 → P0CS → R3b → R3 →
    # 2.58.113 (5 шагов), L2 — 1 шаг
    assert pm.ROLLBACK_MIGRATIONS[L1_KEY] == [
        (cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
         cp.PREV_DIRECT_L1_PLANNER_P0CINT),
        (cp.PREV_DIRECT_L1_PLANNER_P0CINT,
         cp.PREV_DIRECT_L1_PLANNER_P0CS2),
        (cp.PREV_DIRECT_L1_PLANNER_P0CS2, cp.PREV_DIRECT_L1_PLANNER_P0CS),
        (cp.PREV_DIRECT_L1_PLANNER_P0CS, cp.PREV_DIRECT_L1_PLANNER_R3B),
        (cp.PREV_DIRECT_L1_PLANNER_R3B, cp.PREV_DIRECT_L1_PLANNER_R3),
        (cp.PREV_DIRECT_L1_PLANNER_R3, cp.PREV_DIRECT_L1_PLANNER_CLAR)]
    assert pm.ROLLBACK_MIGRATIONS[L2_KEY] == [
        (cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, cp.PREV_CHAT_VERBALIZER_CLAR)]
    # новые слепки — известные каноны, не «кастом»; активные байты отличны
    assert pr.is_known_canon(cp.PREV_DIRECT_L1_PLANNER_R3)
    assert pr.is_known_canon(cp.PREV_DIRECT_L1_PLANNER_R3B)
    assert pr.is_known_canon(cp.PREV_CHAT_VERBALIZER_CLAR)
    assert cp.PREV_DIRECT_L1_PLANNER_R3 != cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert cp.PREV_CHAT_VERBALIZER_CLAR != cp.DIRECT_VERBALIZER_SYSTEM_PROMPT


def test_labels_and_fingerprint_consistent():
    assert pr.factory_text("direct.base.l1_planner") == \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert pr.factory_text("direct.base.l2_writer") == \
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    assert "l1-planner-material-priority" in pr.factory_revision(
        "direct.base.l1_planner")
    assert "l2-writer-clar-boundary" in pr.factory_revision(
        "direct.base.l2_writer")
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12


@pytest.mark.asyncio
async def test_migration_idempotent_rollback_custom_kept():
    cache = _Cache({L1_KEY: cp.PREV_DIRECT_L1_PLANNER_R3,
                    L2_KEY: cp.PREV_CHAT_VERBALIZER_CLAR})
    assert await pm.migrate_prompt_canons(cache) == {
        L1_KEY: "updated", L2_KEY: "updated"}
    assert {k: v for k, v, _c in cache.set_calls} == {
        L1_KEY: cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
        L2_KEY: cp.DIRECT_VERBALIZER_SYSTEM_PROMPT}
    assert {c for _k, _v, c in cache.set_calls} == {"prompts"}
    # аттестация провенанса пишется отдельным журналом (P0-PROMPTS), а не как
    # запись канона; обе ступени миграции в ней отмечены.
    assert len(cache.provenance_sets) == 1
    _pkey, _pdoc, _pcat = cache.provenance_sets[0]
    assert _pkey == "character.prompt_history"
    assert "direct.base.l2_writer" in _pdoc["provenance"]
    cache.apply_writes()
    # повторный прогон на активных байтах — no-op
    assert await pm.migrate_prompt_canons(cache) == {}
    assert len(cache.set_calls) == 2
    # effective-значение после миграции — новый канон
    from services import hot_config as hot
    hot.set_config_cache(cache)
    try:
        assert resolve_prompt(L1_KEY, "CODE_DEFAULT") == \
            cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
        assert resolve_prompt(L2_KEY, "CODE_DEFAULT") == \
            cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    finally:
        hot.set_config_cache(None)
    # откат — цепочка: 1-й вызов снимает редакцию 3 (→ P0CINT), 2-й —
    # приоритет разбора (→ P0CS2), 3-й — смысловую маршрутизацию (→ P0CS),
    # 4-й — P0CS→R3b, 5-й — R3b→R3, 6-й — L1 до 2.58.113, 7-й — no-op
    back = _Cache({L1_KEY: cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
                   L2_KEY: cp.DIRECT_VERBALIZER_SYSTEM_PROMPT})
    assert await pm.rollback_prompt_canons(back) == {
        L1_KEY: "rolled_back", L2_KEY: "rolled_back"}
    assert {k: v for k, v, _c in back.set_calls} == {
        L1_KEY: cp.PREV_DIRECT_L1_PLANNER_P0CINT,
        L2_KEY: cp.PREV_CHAT_VERBALIZER_CLAR}
    back.apply_writes()
    back.set_calls.clear()
    assert await pm.rollback_prompt_canons(back) == {L1_KEY: "rolled_back"}
    assert {k: v for k, v, _c in back.set_calls} == {
        L1_KEY: cp.PREV_DIRECT_L1_PLANNER_P0CS2}
    back.apply_writes()
    back.set_calls.clear()
    assert await pm.rollback_prompt_canons(back) == {L1_KEY: "rolled_back"}
    assert {k: v for k, v, _c in back.set_calls} == {
        L1_KEY: cp.PREV_DIRECT_L1_PLANNER_P0CS}
    back.apply_writes()
    back.set_calls.clear()
    assert await pm.rollback_prompt_canons(back) == {L1_KEY: "rolled_back"}
    assert {k: v for k, v, _c in back.set_calls} == {
        L1_KEY: cp.PREV_DIRECT_L1_PLANNER_R3B}
    back.apply_writes()
    back.set_calls.clear()
    assert await pm.rollback_prompt_canons(back) == {L1_KEY: "rolled_back"}
    assert {k: v for k, v, _c in back.set_calls} == {
        L1_KEY: cp.PREV_DIRECT_L1_PLANNER_R3}
    back.apply_writes()
    back.set_calls.clear()
    assert await pm.rollback_prompt_canons(back) == {L1_KEY: "rolled_back"}
    assert {k: v for k, v, _c in back.set_calls} == {
        L1_KEY: cp.PREV_DIRECT_L1_PLANNER_CLAR}
    back.apply_writes()
    back.set_calls.clear()
    assert [back.values[L1_KEY], back.values[L2_KEY]] == [
        cp.PREV_DIRECT_L1_PLANNER_CLAR, cp.PREV_CHAT_VERBALIZER_CLAR]
    assert await pm.rollback_prompt_canons(back) == {}
    assert back.set_calls == []
    assert await pm.migrate_prompt_canons(back) == {
        L1_KEY: "updated", L2_KEY: "updated"}
    back.apply_writes()
    assert [back.values[L1_KEY], back.values[L2_KEY]] == [
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT]
    # кастом владельца (не точное совпадение байт) не трогается ни в одну
    # сторону — ни миграцией, ни откатом
    custom = _Cache({L1_KEY: cp.PREV_DIRECT_L1_PLANNER_R3 + " правка",
                     L2_KEY: cp.PREV_CHAT_VERBALIZER_CLAR + " правка"})
    assert await pm.migrate_prompt_canons(custom) == {}
    assert await pm.rollback_prompt_canons(custom) == {}
    assert custom.set_calls == []
