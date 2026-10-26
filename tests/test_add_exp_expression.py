"""ADD-EXP — реальная управляемость мата: off / occasional / frequent.

Покрытие (§7.1 Ф2 RED, детерминированные тесты, 0 LLM):
  1. значения/нормализация (alias `allowed`, closed-set, нет 4-й степени);
  2. per-control effective (chat→global→factory) и источники;
  3. миграция `allowed`→`occasional` без потери данных; ни один чат не
     становится `frequent` сам;
  4. точные тексты владельца §2.1/§2.2 (байт-в-байт), отсутствие механических
   счётчиков/насильных вставок и запрещённые обороты;
  5. wiring: Direct L2 / authorial получают слой с ревизией; machine-writers —
     профильная причина; `budget_excluded` честен;
  6. приоритеты §4.3 (детерминированная часть) + байт-паритет Core/канона;
  7. диагностика §6: классы, дедуп, R17;
  8. UI payload: опции/метки, effective+источник, `runtime_wired`, изоляция
     чатов, миграционный баннер, live-check (без реального LLM);
  9. no-postprocessor (RULE_KINDS без profanity; egress не вырезает);
 10. few-shot: отбор ≤4 только своего режима/owner_approved; humor-путь не
     берёт `expression_register`; бюджет/`expression_examples_absent`.

TEST-LIFECYCLE: CONTRACT owner=ADD-EXP (EXP-UI.MODES/OFF/OCC/FREQ/INHERIT/
MIGRATION; EXP-INSTR.POSITIVE/FEWSHOT/NOPOST; EXP-RUNTIME.WIRING/PRIORITY/DIAG;
EXP-ACCEPT.PREVIEW; ADD-1.E1/E4/E5)
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import mca_expression as ex  # noqa: E402
from services import mca_events  # noqa: E402
from services import mca_sample_library as sl  # noqa: E402
from services import prompt_composer as pc  # noqa: E402
from web.api import speech as S  # noqa: E402
# Фикстура W6 (изолированный ConfigCache-двойник + реальный chat-слой).
from test_soul1_w6_speech_ui import api_env  # noqa: E402,F401

#: §2.1 header — ASAP W1 (P0-D, §3.4 source-2026-10-22.md, 22.10.2026):
#: текст владельца БАЙТ-В-БАЙТ (без «Выражение владельца»/приоритетных
#: рассуждений; правило «не переноси ограничения или разрешения из других
#: речевых слоёв»). Тексты режимов перекрыты позже — канон 25.10.2026
#: (source-owner-speech-simplify-2026-10-25.md §2.4–2.6).
HEADER = (
    "<Expression_Settings>\n"
    "ПРАВИЛА МАНЕРЫ РЕЧИ\n"
    "Применяй перечисленные ниже параметры к собственной речи в готовом "
    "ответе. Это действующие инструкции по выражению, а не описание настроек "
    "и не пожелания. Они не меняют факты, не дополняют память и не отменяют "
    "требования конкретной задачи к содержанию. Прямую цитату передавай без "
    "стилистической подмены. Если задан режим нецензурной лексики, "
    "руководствуйся именно им; не переноси ограничения или разрешения из "
    "других речевых слоёв."
)

#: §2.2 строки режимов — ТОЧНЫЕ тексты владельца (SPEECH-P0-A1,
#: source-owner-p0-hotfix-2026-10-25.md §2; OFF/OCCASIONAL — прежний канон
#: 25.10.2026), байт-в-байт. Квот/счётчиков/насильных вставок нет: частота
#: задаётся только инструкцией.
OFF_LINE = ("- Мат: Не используй мат в собственной речи. Цитаты и исходные "
            "пользовательские данные не переписывай ради этого правила.")
OCC_LINE = ("- Мат: Матерись иногда, когда это естественно вписывается в "
            "разговор. Не добавляй ругательства специально и не делай их "
            "обязательной частью каждого ответа.")
FREQ_LINE = ("- Мат: Матерись часто и естественно, как в обычном грубом "
             "интернет-разговоре. Не выдумывай сложные ругательные "
             "конструкции и не вставляй мат механически.")

#: Первоисточник действующего канона §2.2 (OFF/OCCASIONAL — 25.10.2026) —
#: сверка байт-в-байт.
OWNER_SOURCE_2510 = (ROOT / "plans" / "features" / "asap-speech-arch" /
                     "source-owner-speech-simplify-2026-10-25.md")
#: P0-hotfix §2 (25.10.2026): действующий текст FREQUENT.
OWNER_SOURCE_P0H = (ROOT / "plans" / "features" / "asap-speech-arch" /
                    "source-owner-p0-hotfix-2026-10-25.md")

#: Прежняя ступень §2.2, которую держит дизайн ADD-EXP (20.10.2026); в
#: runtime её заменил канон 25.10.
PREV_OFF_TEXT = "Не используй мат в собственной речи."
PREV_OCC_TEXT = ("Пиши разговорным языком с примесью мата. Нецензурные "
                 "выражения используй как обычные эмоциональные оценки и "
                 "междометия, без необходимости специально обосновывать их "
                 "появление. Мат не должен доминировать в речи.")


def _run(coro):
    return asyncio.run(coro)


class _FakeHot:
    """Двойник ConfigCache (get/set + get_config_cache-совместимость)."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes: list = []

    def get(self, key, default=None):
        if key in self.values:
            return self.values[key]
        return default

    def set(self, key, value):
        self.writes.append(("set", key))

    def set_many(self, items):
        self.writes.append(("set_many", len(items)))


def _expression_plan(**overrides) -> pc.PromptPlan:
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=777,
        base_prompt="КАНАЛ: факты.", base_source="default",
        core=pc.CoreRef(text="ЯДРО_ХАРАКТЕРА", revision="r1"),
        expression=pc.ExpressionSettings(
            text=ex.render_expression_text(
                ex.resolve_effective({"profanity": "frequent"}, None)),
            revision="e1", mode="frequent", source="chat"),
        gates=pc.GateState(unified_composer_enabled=True))
    return pc.PromptPlan(**{**plan.__dict__, **overrides}) \
        if overrides else plan


# ═══ 1. значения / нормализация ═════════════════════════════════════════════

def test_modes_are_closed_set_and_allowed_is_read_alias():
    assert ex.EXPRESSION_MODES == ("inherit", "off", "occasional", "frequent")
    assert ex.normalize_mode("allowed") == "occasional"
    assert ex.normalize_mode("ALLOWED") == "occasional"
    assert ex.normalize_mode("bogus") == "inherit"
    # «естественный» — НЕ четвёртая степень частоты (нет такого значения)
    assert ex.normalize_mode("natural") == "inherit"
    doc = ex.normalize_expression({"profanity": "allowed", "wit": "???"})
    assert doc["profanity"] == "occasional" and doc["wit"] == "inherit"
    # единственный владелец значений/текста: UI-таблица не держит копию
    assert S.EXPRESSION_VALUES["profanity"] == ex.EXPRESSION_MODES
    assert "allowed" not in S.EXPRESSION_VALUES["profanity"]
    assert S._normalize_expression is not None
    for control in S.EXPRESSION_CONTROLS:
        assert control["instruction"] == \
            ex.CONTROL_INSTRUCTIONS[control["id"]]


# ═══ 2. effective: per-control merge ════════════════════════════════════════

def test_effective_per_control_merge_chat_global_factory():
    eff = ex.resolve_effective({"sharpness": "soft"},
                               {"profanity": "allowed", "verbosity": "long"})
    controls = eff["controls"]
    assert controls["sharpness"] == {"value": "soft", "source": "chat",
                                     "migrated": False}
    assert controls["profanity"] == {"value": "occasional", "source": "global",
                                     "migrated": True}
    assert controls["verbosity"] == {"value": "long", "source": "global",
                                     "migrated": False}
    assert controls["wit"] == {"value": "inherit",
                               "source": "factory_default",
                               "migrated": False}
    # пустая цепочка → заводской occasional (§1.5)
    empty = ex.resolve_effective(None, None)
    assert empty["controls"]["profanity"]["value"] == "occasional"
    assert empty["controls"]["profanity"]["source"] == "factory_default"
    assert ex.effective_mode(empty) == "occasional"
    # inherit внутри документа = «нет явного выбора», дальше по цепочке
    part = ex.resolve_effective({"profanity": "inherit"},
                                {"profanity": "frequent"})
    assert part["controls"]["profanity"]["value"] == "frequent"
    assert part["controls"]["profanity"]["source"] == "global"
    # частичный chat-документ не теряет контролы global (дефект Ф0)
    assert ex.effective_source(part) == "global"
    assert ex.effective_source(eff) == "chat"


# ═══ 3. миграция allowed→occasional ═════════════════════════════════════════

def test_migration_read_alias_keeps_data_and_never_frequent():
    raw = {"profanity": "allowed", "wit": "high", "revision": 4,
           "history": [{"revision": 3}], "updated_at": "2026-10-18T14:37:25Z",
           "note": "прежнее пожелание"}
    eff = ex.resolve_effective(None, raw)
    assert eff["controls"]["profanity"]["value"] == "occasional"
    assert eff["controls"]["profanity"]["migrated"] is True
    assert ex.expression_migration(None, raw) == {
        "profanity": {"from": "allowed", "to": "occasional"}}
    # ни один чат не переводится в frequent без явного выбора владельца
    assert all(item["value"] != "frequent"
               for item in eff["controls"].values())
    # нормализация не теряет прочие контролы/примечание
    norm = ex.normalize_expression(raw)
    assert norm["wit"] == "high" and norm["note"] == "прежнее пожелание"
    # chat-документ с allowed: источник chat, миграция видна и там
    chat_eff = ex.resolve_effective({"profanity": "allowed"}, None)
    assert chat_eff["controls"]["profanity"] == {
        "value": "occasional", "source": "chat", "migrated": True}


# ═══ 4. тексты слоя (§2.1/§2.2) ═════════════════════════════════════════════

def test_instruction_texts_byte_exact_and_distinct():
    lines = {"off": OFF_LINE, "occasional": OCC_LINE, "frequent": FREQ_LINE}
    texts = {}
    for mode, line in lines.items():
        text = ex.render_expression_text(
            ex.resolve_effective({"profanity": mode}, None))
        texts[mode] = text
        assert text.startswith(HEADER + "\n"), mode
        assert line in text.splitlines(), mode
        assert text.endswith("\n</Expression_Settings>"), mode
    assert len(set(texts.values())) == 3, "три режима — три разных текста"
    # owner-канон 25.10.2026: короткие точные инструкции; запрет мата в
    # собственной речи не переписывает цитаты/пользовательские данные.
    assert "Не используй мат в собственной речи" in OFF_LINE
    assert ("Цитаты и исходные пользовательские данные не переписывай"
            in OFF_LINE)
    assert "Матерись иногда, когда это естественно вписывается" in OCC_LINE
    assert ("не делай их обязательной частью каждого ответа" in OCC_LINE)
    assert "Матерись часто и естественно" in FREQ_LINE
    assert "как в обычном грубом интернет-разговоре" in FREQ_LINE
    assert "не вставляй мат механически" in FREQ_LINE
    # «мат разрешён/допустим/…» — не единственное правило для occ/freq
    low = (OCC_LINE + " " + FREQ_LINE).casefold()
    for banned in ("мат разрешён", "мат допустим", "необязателен",
                   "не обязательный", "при необходимости", "по желанию",
                   "если хочешь"):
        assert banned not in low, banned
    # выключенный слой не рендерит инструкций
    assert ex.render_expression_text(
        {"enabled": False, "profanity": "off"}) == ""


def test_owner_exact_texts_are_canon():
    """(a) SPEECH-P0-A1 (source-owner-p0-hotfix-2026-10-25.md §2): канон
    `profanity` — ТОЧНЫЕ тексты владельца, байт-в-байт; сверяются и с
    литералами, и с blockquote первоисточника (без дрейфа).

    TEST-LIFECYCLE: CONTRACT owner=SPEECH-P0-A1/§2
    """
    assert ex.PROFANITY_INSTRUCTIONS == {
        "off": ("Не используй мат в собственной речи. Цитаты и исходные "
                "пользовательские данные не переписывай ради этого правила."),
        "occasional": ("Матерись иногда, когда это естественно вписывается в "
                       "разговор. Не добавляй ругательства специально и не "
                       "делай их обязательной частью каждого ответа."),
        "frequent": ("Матерись часто и естественно, как в обычном грубом "
                     "интернет-разговоре. Не выдумывай сложные ругательные "
                     "конструкции и не вставляй мат механически."),
    }
    # байт-в-байт с первоисточником владельца (25.10.2026, P0-hotfix §2) и
    # с прежним каноном OFF/OCCASIONAL
    quotes = [line[2:] for line in
              OWNER_SOURCE_2510.read_text(encoding="utf-8").splitlines()
              if line.startswith("> ")]
    quotes_p0h = [line[2:] for line in
                  OWNER_SOURCE_P0H.read_text(encoding="utf-8").splitlines()
                  if line.startswith("> ")]
    assert ex.PROFANITY_INSTRUCTIONS["frequent"] in quotes_p0h
    for mode in ("off", "occasional"):
        assert ex.PROFANITY_INSTRUCTIONS[mode] in quotes, mode
    for mode in ("off", "occasional", "frequent"):
        assert ("- Мат: " + ex.PROFANITY_INSTRUCTIONS[mode]) in (
            OFF_LINE if mode == "off" else
            OCC_LINE if mode == "occasional" else FREQ_LINE)


#: F3: механические формулы, отменённые владельцем (имитация живой речи,
#: runtime-счётчики реплик, обязательные вставки). Проверяются на всех строках.
MECHANICAL_MARKERS = (
    "4–5", "4-5", "по счёту", "вставляй сам", "каждом ответе",
    "каждой 4", "каждом собственном", "минимум одно", "N-й",
)


def test_no_mechanical_counters_or_forced_inserts():
    """(b) Никаких механических счётчиков/насильных вставок (F3 + owner
    25.10.2026: «не вставляй их механически», «не делай их обязательной
    частью каждого ответа»).

    TEST-LIFECYCLE: CONTRACT owner=ADD-EXP/EXP-INSTR (F3, 20.10.2026;
    SPEECH-SIMPLIFY §2.4–2.6, 25.10.2026)
    """
    for mode in ("off", "occasional", "frequent"):
        body = ex.PROFANITY_INSTRUCTIONS[mode].casefold()
        for marker in MECHANICAL_MARKERS:
            assert marker.casefold() not in body, (mode, marker)
        assert not re.search(r"\d+\s*[-–]\s*\d+", body), mode
        # Квота «каждый ответ/сообщение» запрещена; единственная допустимая
        # форма — запрет механической вставки в occasional.
        assert "в каждом ответе" not in body, mode
        assert "каждый ответ" not in body, mode
        assert "кажд" not in re.sub(r"каждого ответа", "", body), mode


def test_header_unified_rule_p0():
    """ASAP W1 (P0-D, §3.4, 22.10.2026): header = действующие инструкции
    владельца (не описание настроек); режим нецензурной лексики — владелец
    этого слоя, ограничения/разрешения из других слоёв не переносятся.

    Прежние P0-якоря («вся пользовательская речь», приоритеты C1/C8/C16)
    заменены текстом владельца §3.4 байт-в-байт; нейтрализаторы по-прежнему
    отсутствуют (CORRECTIVE-FOLLOWUP 21.10.2026).

    TEST-LIFECYCLE: CONTRACT owner=ASAP-W1 P0-D/ADD-EXP (§3.4)
    """
    assert "Применяй перечисленные ниже параметры к собственной речи" in HEADER
    assert "Это действующие инструкции по выражению, а не описание настроек" \
        in HEADER
    assert "Прямую цитату передавай без стилистической подмены." in HEADER
    # нейтрализаторы по-прежнему отсутствуют (follow-up 21.10.2026)
    assert "не вставляется насильно" not in HEADER
    assert "без мата» переопределяет" not in HEADER
    # служебные описания для разработчиков сняты (§1.4/REQ-META-CLEAN)
    assert "Выражение владельца" not in HEADER
    assert "важнее общего разрешения канона" not in HEADER
    # правило одного владельца режима мата (слой изолирован от других слоёв)
    assert ("не переноси ограничения или разрешения из других речевых слоёв"
            in HEADER)
    # жанровое исключение снято (P0): «не переписываются / не форсируется»
    assert "не переписываются" not in HEADER
    assert "не форсируется" not in HEADER


def test_header_has_no_false_l1_delegation():
    """F1/F2: уместность не делегируется стадии, которая не видит регистр.

    L1 — machine-профиль: слой «Выражение» туда не подключается, в его
    схеме нет регистра/уместности (behavior-diag §3). Header не должен
    обещать то, что не выполняется; F2 заменяет «контекст решает уместность»
    на требование выполнять настройки — честные опоры канона остаются.
    CORRECTIVE-FOLLOWUP (21.10.2026): строка «без мата» удалена вместе с
    прочими нейтрализаторами; C16 (прямая просьба о форме) осталась.
    """
    assert "Уместность выбирает L1" not in HEADER
    assert "L1" not in HEADER, "header не ссылается на стадию без регистра"
    assert "переопределяет частоту для этого ответа" not in HEADER
    # W1 §3.4: защита дословной цитаты — «без стилистической подмены»
    assert "Прямую цитату передавай без стилистической подмены." in HEADER
    assert "не переписываются" not in HEADER and "не форсируется" not in HEADER
    # рендер слоя (§2.1) тоже без ложного делегирования
    rendered = ex.render_expression_text({"profanity": "occasional"})
    assert "Уместность выбирает L1" not in rendered
    assert "L1" not in rendered
    # источник канона (модуль) не содержит фразы-делегирования
    module_src = (ROOT / "services" / "mca_expression.py").read_text(
        encoding="utf-8")
    assert "Уместность выбирает L1" not in module_src


def test_design_canonical_strings_match_module():
    """Анти-дрейф: дизайн ADD-EXP держит ПРЕЖНЮЮ ступень §2.2 (20.10.2026 /
    прод-текст 23.10), а runtime — канон владельца 25.10.2026
    (source-owner-speech-simplify-2026-10-25.md §2.4–2.6). Старые байты не
    переписаны задним числом, новые — не «мягкая правка» архива.

    TEST-LIFECYCLE: CONTRACT owner=ADD-EXP/SPEECH-SIMPLIFY (дельта канона)
    """
    source = (ROOT / "plans" / "features" / "asap-speech-arch" /
              "source-2026-10-22.md").read_text(encoding="utf-8")
    assert ex.EXPRESSION_HEADER in source, (
        "header §3.4 рассинхронизирован с текстом владельца")
    design = (ROOT / "plans" / "features" / "add-exp" /
              "design-add-exp.md").read_text(encoding="utf-8")
    previous = {"off": PREV_OFF_TEXT,
                "occasional": PREV_OCC_TEXT,
                "frequent": ex.PREV_PROFANITY_FREQUENT_TEXT}
    for mode, text in previous.items():
        assert "- Мат: " + text in design, mode + ": архив §2.2 потерян"
    # действующий канон 25.10 в старом дизайне отсутствует (дельта применена)
    for mode, text in ex.PROFANITY_INSTRUCTIONS.items():
        assert "- Мат: " + text not in design, mode


# ═══ 5. wiring ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_direct_l2_wiring_expression_present_with_revision(monkeypatch):
    from services import hot_config as hot
    from services import chat_params
    from services.direct_chat_service import DirectChatService
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot.set_config_cache(_FakeHot({
        "flags.unified_composer_enabled": True,
        ex.EXPRESSION_DOC_KEY: {"profanity": "frequent", "revision": 3}}))
    chat_params.set_chat_params_cache(None)
    try:
        system, manifest = await DirectChatService._compose_speech_system(
            None, chat_id=777, writer="l2_writer", run_id="run-add-exp",
            base_prompt="КАНАЛ: факты.", base_key="prompts.x",
            base_default="КАНАЛ: факты.", base_source="default",
            gates=pc.GateState(unified_composer_enabled=True))
    finally:
        hot.set_config_cache(None)
    trace = [t for t in manifest.layers if t.layer == "expression"][0]
    assert trace.rendered is True and trace.skip_reason == ""
    assert trace.revision and manifest.versions["expression"] == trace.revision
    assert HEADER in system and FREQ_LINE in system
    assert "expression_absent" not in [t.skip_reason
                                       for t in manifest.layers]


@pytest.mark.asyncio
async def test_authorial_system_gets_expression_layer(monkeypatch):
    from services import hot_config as hot
    from services import chat_params
    from services import mca_authorial_speech as authorial
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot.set_config_cache(_FakeHot({
        "flags.unified_composer_enabled": True,
        ex.EXPRESSION_DOC_KEY: {"profanity": "occasional"}}))
    chat_params.set_chat_params_cache(None)
    try:
        system, manifest = await authorial.authorial_system(
            chat_id=777, writer="nostalgia_writer", genre="nostalgia",
            legacy_canon="КАНОН_ЖАНРА")
    finally:
        hot.set_config_cache(None)
    assert manifest is not None
    assert HEADER in system and OCC_LINE in system
    trace = [t for t in manifest.layers if t.layer == "expression"][0]
    assert trace.rendered is True and trace.skip_reason == ""


def test_machine_writers_keep_profile_reason_not_expression_defect():
    manifest = pc.compose_machine_system("БАЗА", writer="l1_planner",
                                         chat_id=7)
    trace = [t for t in manifest.layers if t.layer == "expression"][0]
    assert trace.rendered is False
    assert trace.skip_reason == "profile:machine_stage"
    assert trace.skip_reason != "expression_absent"


def test_expression_is_never_excluded_by_local_quota(monkeypatch):
    """QUOTA-REMOVAL (A2/A6): Expression не вытесняется и не «конфликтует».

    Прежний `budget_excluded` скрывал настроенный FREQUENT из system и давал
    ложный «ноль различий». Квоты нет — слой рендерится всегда, без служебных
    конфликтов о перерасходе.
    """
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "40")
    expr_text = HEADER + "\n" + FREQ_LINE + "\n</Expression_Settings>"
    manifest = pc.compose_prompt(_expression_plan(
        expression=pc.ExpressionSettings(
            text=expr_text, revision="e1", mode="frequent")))
    trace = [t for t in manifest.layers if t.layer == "expression"][0]
    assert trace.rendered is True and trace.skip_reason == ""
    assert expr_text in manifest.system
    assert "<Expression_Settings>" in manifest.system
    assert not [c for c in manifest.conflicts
                if c.conflict_id == "expression_protected_from_budget"]
    assert "КАНАЛ: факты." in manifest.system, "база канала не вытесняется"


# ═══ 6. приоритеты §4.3 (детерминированная часть) ═══════════════════════════

def test_core_and_canon_byte_parity_with_expression_off():
    core_text = ("Мат и грубость. Мат - естественная часть речи, разговорная "
                 "норма. Используй его свободно, если он делает фразу "
                 "выразительнее.")
    canon = "Разрешен мат и сленг."
    manifest = pc.compose_prompt(_expression_plan(
        base_prompt=canon,
        core=pc.CoreRef(text=core_text, revision="r5"),
        expression=pc.ExpressionSettings(
            text=ex.render_expression_text(
                ex.resolve_effective({"profanity": "off"}, None)),
            revision="e1", mode="off")))
    # P5: Core/канон байт-в-байт (Expression не переписывает личность)
    assert canon in manifest.system
    assert core_text in manifest.system
    # P4: строка off присутствует — прямой запрет мата в собственной речи
    assert OFF_LINE in manifest.system
    assert "Не используй мат в собственной речи" in manifest.system


def test_factcheck_machine_plan_has_no_expression_and_no_examples():
    examples = ex.render_expression_examples_block("frequent", [{
        "context_note": "быт", "input_text": "x", "reply_text": "y"}])
    manifest = pc.compose_prompt(pc.PromptPlan(
        profile="machine_json", writer="factcheck_extract", chat_id=7,
        base_prompt="БАЗА",
        expression=pc.ExpressionSettings(text=HEADER + "\n" + FREQ_LINE
                                        + "\n</Expression_Settings>",
                                        mode="frequent"),
        expression_examples=(pc.SampleRef(
            block_id="expression_examples", text=examples),),
        gates=pc.GateState(unified_composer_enabled=True)))
    assert manifest.system == "БАЗА"
    skipped = [t.skip_reason for t in manifest.layers
               if t.layer in ("expression", "few_shot")]
    assert set(skipped) == {"profile:machine_stage"}


def test_style_policy_neither_removes_nor_inserts_profanity():
    from services import style_policy as sp
    from services.direct_chat_service import _delivered_payload
    doc = {"rules": [{"id": "tp", "kind": "trailing_period",
                      "strictness": "hard", "scope": "global",
                      "enabled": True, "params": {"ellipsis": "strip"}}],
           "soft_instructions": []}
    policy = sp.effective_policy_sync(None, doc, context="regular")
    text = "Ну и хуй с ним, бля."
    out = _run(sp.apply_style_policy(text, chat_id=0, policy=policy,
                                     context="regular", record=False))
    assert out.applied is True
    assert ex.count_profanity(out.text) == ex.count_profanity(text) == 2
    assert _delivered_payload(text) == text, "egress-guard не вырезает мат"
    assert not any("profan" in kind for kind in sp.RULE_KINDS)


# ═══ 7. диагностика §6 ══════════════════════════════════════════════════════

def test_diag_classes_closed_set_and_r17_dedup(monkeypatch):
    calls: list[dict] = []

    def _capture(name, **fields):
        calls.append({"name": name, **fields})
        return {"event_name": name}

    monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
    ex.reset_diag_dedup()
    ex.emit_expression_diag("policy_not_injected", chat_id=9,
                            stage="l2_writer", detail="marker_absent",
                            mode="frequent")
    ex.emit_expression_diag("policy_not_injected", chat_id=9,
                            stage="l2_writer", detail="marker_absent",
                            mode="frequent")
    assert len(calls) == 1, "дедуп 1×процесс на (chat, class, stage, detail)"
    event = calls[0]
    assert event["component"] == "expression"
    assert event["stage"] == "l2_writer"
    assert event["status"].startswith("expression_diag:policy_not_injected")
    assert event["reason_code"] == "source_missing"
    payload = json.dumps(calls, ensure_ascii=False)
    assert "policy_not_injected" in payload
    assert ex.EXPRESSION_DIAG_CLASSES == (
        "policy_not_injected", "composer_excluded", "model_ignored_instruction",
        "postprocess_changed", "provider_limitation", "unknown")
    # неизвестный класс → `unknown`, без падения и без текста
    ex.emit_expression_diag("что-то-своё", chat_id=9, stage="x")
    assert calls[-1]["status"].startswith("expression_diag:unknown")


def test_composer_excluded_diag_fires_for_expression_skip(monkeypatch):
    calls: list[dict] = []

    def _capture(name, **fields):
        calls.append({"name": name, **fields})
        return {"event_name": name}

    monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
    ex.reset_diag_dedup()
    pc.reset_state()
    manifest = pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=55,
        base_prompt="БАЗА_КАНАЛА",
        expression=pc.ExpressionSettings(enabled=False,
                                         skip_reason="expression_disabled"),
        gates=pc.GateState(unified_composer_enabled=True)))
    pc.emit_layer_events_once(manifest)
    diag = [c for c in calls if str(c.get("status", "")).startswith(
        "expression_diag:composer_excluded")]
    assert diag, calls
    assert diag[0]["chat_id"] == 55
    assert "expression_disabled" in str(diag[0].get("usage_json") or "")
    assert "БАЗА_КАНАЛА" not in json.dumps(calls, ensure_ascii=False), "R17"


def test_fallback_adapter_marker_loss_reports_policy_not_injected(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(mca_events, "emit_mca_event",
                        lambda name, **f: calls.append({"name": name, **f})
                        or {"event_name": name})
    ex.reset_diag_dedup()
    from services import direct_chat_service as dcs

    def adapter(payload):
        return {"messages": [{"role": "system", "content": "без маркера"},
                             {"role": "user", "content": "x"}]}

    wrapped = dcs._expression_marker_checked_adapter(adapter, chat_id=5,
                                                     mode="frequent")
    out = wrapped({"messages": []})
    assert out["messages"][0]["content"] == "без маркера", "адаптер не подменён"
    assert any(str(c.get("status", "")).startswith(
        "expression_diag:policy_not_injected") for c in calls)


def test_classify_expression_response_is_honest_about_single_probe():
    assert ex.classify_expression_response("Ну и хуй.", "frequent") == ""
    assert ex.classify_expression_response("Ну и всё.", "frequent",
                                           probes=1) == ""
    assert ex.classify_expression_response("Ну и всё.", "frequent",
                                           probes=5) == \
        "model_ignored_instruction"
    assert ex.classify_expression_response("Ну и хуй.", "off") == \
        "model_ignored_instruction"
    assert ex.classify_expression_response("без маркера", "frequent",
                                           marker_present=False) == \
        "policy_not_injected"
    assert ex.classify_expression_response("", "frequent",
                                           provider_error=True) == \
        "provider_limitation"
    assert ex.classify_expression_response("ok", "frequent",
                                           postprocess=True) == \
        "postprocess_changed"


@pytest.mark.asyncio
async def test_l2_write_answer_wires_expression_and_reports_diag(
        monkeypatch):
    from services import hot_config as hot
    from services import chat_params
    from services import direct_chat_service as dcs
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot.set_config_cache(_FakeHot({
        "flags.unified_composer_enabled": True,
        ex.EXPRESSION_DOC_KEY: {"profanity": "frequent"}}))
    chat_params.set_chat_params_cache(None)
    monkeypatch.setattr(dcs.anticliche_cache, "get_rules", lambda: None)
    captured: dict = {}

    async def fake_verbalize(generate, messages, **kwargs):
        captured["messages"] = messages
        reply = await generate(messages)
        return reply, {"attempts": 1, "retries": 0, "hits": [],
                       "fallback": False}

    monkeypatch.setattr(dcs, "verbalize_validated", fake_verbalize)

    class _FakeLLM:
        async def generate(self, messages, **kwargs):
            return "Ага, выдал. Хуёво выдал, зато никто не уснул."

    calls: list[dict] = []
    monkeypatch.setattr(mca_events, "emit_mca_event",
                        lambda name, **f: calls.append({"name": name, **f})
                        or {"event_name": name})
    ex.reset_diag_dedup()
    service = dcs.DirectChatService.__new__(dcs.DirectChatService)
    service.llm = _FakeLLM()
    diag_out: dict = {}
    try:
        result = await service._l2_write_answer(
            55, "ну ты и выдал", temperature=0.7, correlation_id="cid-exp-1",
            diag_out=diag_out)
    finally:
        hot.set_config_cache(None)
    assert result is not None
    text, _mode = result
    assert "<Expression_Settings>" in captured["messages"][0]["content"]
    assert diag_out["expression_marker"] is True
    assert diag_out["expression_mode"] == "frequent"
    assert diag_out["expression_rendered"] is True
    # §6 `postprocess_changed`: raw с матом, доставленный без — класс виден
    dcs._expression_postprocess_check(55, "cid-exp-1", "Ага, выдал.",
                                      stage="style_policy")
    assert any(str(c.get("status", "")).startswith(
        "expression_diag:postprocess_changed") for c in calls), calls
    # мат сохранён — класса нет
    calls.clear()
    ex.reset_diag_dedup()
    dcs._expression_postprocess_check(55, "cid-exp-1", text,
                                      stage="egress_guard")
    assert not [c for c in calls if "expression_diag" in str(c.get("status"))]


# ═══ 8. UI payload / endpoints ══════════════════════════════════════════════

def test_global_payload_explicit_effective_and_no_inherit(api_env):
    env = api_env
    view = _run(S.get_expression(None, env.user, None))
    assert view["runtime_wired"] is True and view["runtime_note"]
    assert view["effective"]["profanity"] == {
        "value": "occasional", "source": "factory_default", "migrated": False}
    prof = next(c for c in view["controls"] if c["id"] == "profanity")
    assert prof["question"] == "Как часто мат звучит в собственных ответах бота"
    assert [o["label"] for o in prof["options"]] == [
        "Без мата", "Эпизодически", "Часто"]
    assert all(o["value"] != "inherit" for o in prof["options"]), \
        "в глобальном scope наследование не предлагается"
    # у контролов без явного/заводского значения «как настроено» остаётся
    # честным описанием текущего состояния (не выдуманное значение)
    wit = next(c for c in view["controls"] if c["id"] == "wit")
    assert [o["value"] for o in wit["options"]] == [
        "inherit", "low", "normal", "high"]
    assert prof["instruction"] == ex.PROFANITY_INSTRUCTIONS
    assert prof["effective"] == "occasional"
    assert prof["effective_source"] == "factory_default"
    # форма получает явное эффективное значение (не «как в характере»)
    assert view["values"]["profanity"] == "occasional"
    assert view["migration"] == {}
    assert view["rendered_text"].startswith(HEADER)
    assert OCC_LINE in view["rendered_text"]
    assert "Как в характере" not in view["rendered_text"]
    assert view["notes"] == S.EXPRESSION_NOTES


def test_chat_scope_inherit_label_isolation_and_reset(api_env):
    env = api_env
    _run(S.post_expression(None, env.user, S.ExpressionWrite(
        values={"profanity": "frequent"}, scope="chat"), str(env.chat_id)))
    view_a = _run(S.get_expression(None, env.user, str(env.chat_id)))
    assert view_a["inheritance"] == "chat"
    assert view_a["values"]["profanity"] == "frequent"
    assert view_a["effective"]["profanity"]["source"] == "chat"
    assert FREQ_LINE in view_a["rendered_text"]
    prof_a = next(c for c in view_a["controls"] if c["id"] == "profanity")
    inherit = [o for o in prof_a["options"] if o["value"] == "inherit"]
    assert inherit and inherit[0]["label"] == \
        "Как в глобальных настройках (наследование)"
    # изоляция: другой чат видит заводское occasional, не frequent
    view_b = _run(S.get_expression(None, env.user, str(-100777)))
    assert view_b["effective"]["profanity"]["value"] == "occasional"
    assert view_b["effective"]["profanity"]["source"] == "factory_default"
    assert FREQ_LINE not in view_b["rendered_text"]
    assert view_b["values"]["profanity"] == "inherit"
    reset = _run(S.post_expression_reset_chat(None, env.user,
                                              str(env.chat_id)))
    assert reset["ok"] is True
    after = _run(S.get_expression(None, env.user, str(env.chat_id)))
    assert after["inheritance"] == "factory_default"
    assert after["effective"]["profanity"]["value"] == "occasional"


def test_allowed_alias_write_is_canonical_and_keeps_history(api_env):
    env = api_env
    env.cache.data[S.EXPRESSION_DOC_KEY] = {
        "profanity": "allowed", "wit": "high", "note": "прежнее",
        "revision": 1, "history": [], "updated_at": "2026-10-18T14:37:25Z"}
    view = _run(S.get_expression(None, env.user, None))
    assert view["migration"] == {"profanity": {"from": "allowed",
                                               "to": "occasional"}}
    assert view["effective"]["profanity"]["migrated"] is True
    assert view["effective"]["profanity"]["value"] == "occasional"
    assert view["document"]["wit"] == "high"
    # сохранение (как форма: все контролы из values) пишет канонический режим
    values = dict(view["values"])
    values["profanity"] = "occasional"
    values["note"] = view["note"]
    saved = _run(S.post_expression(None, env.user, S.ExpressionWrite(
        values=values, scope="global"), None))
    assert saved["ok"] is True
    doc = env.cache.data[S.EXPRESSION_DOC_KEY]
    assert doc["profanity"] == "occasional"
    assert doc["wit"] == "high" and doc["note"] == "прежнее"
    assert doc["revision"] == 2 and len(doc["history"]) == 1
    assert doc["updated_at"]
    assert saved["view"]["migration"] == {}, \
        "баннер миграции — только до первого сохранения"
    assert saved["view"]["effective"]["profanity"]["source"] == "global"


def test_live_check_endpoint_honest_paths(api_env, monkeypatch):
    env = api_env
    monkeypatch.setattr(S, "_direct_service", lambda: None)
    with pytest.raises(HTTPException) as exc:
        _run(S.post_expression_live_check(
            None, env.user, S.ExpressionLiveCheck(message="привет"),
            str(env.chat_id)))
    assert exc.value.status_code == 503, "нет Direct-пути — честный 503"
    with pytest.raises(HTTPException) as exc2:
        _run(S.post_expression_live_check(
            None, env.user, S.ExpressionLiveCheck(message=""),
            str(env.chat_id)))
    assert exc2.value.status_code == 422
    # реальный (стаб) L2-путь: один вызов, без доставки, класс/маркер видны
    class _FakeService:
        async def _l2_write_answer(self, chat_id, query, **kwargs):
            diag = kwargs.get("diag_out")
            if isinstance(diag, dict):
                diag.update({"expression_marker": True,
                             "expression_mode": "frequent",
                             "expression_rendered": True,
                             "provider_error": False})
            return "Ну и хуй с ним, бля.", "warm"

    monkeypatch.setattr(S, "_direct_service", lambda: _FakeService())

    async def _fake_settings(_chat):
        return pc.ExpressionSettings(text="x", mode="frequent")

    monkeypatch.setattr(pc, "resolve_expression_settings", _fake_settings)
    S._live_check_state["ts"] = 0.0
    S._live_check_state["busy"] = False
    try:
        first = _run(S.post_expression_live_check(
            None, env.user, S.ExpressionLiveCheck(message="ну ты и выдал"),
            str(env.chat_id)))
        assert first["ok"] is True
        assert first["mode"] == "frequent"
        assert first["profanity_roots"] >= 1
        assert first["diag_class"] == ""
        assert first["expression_marker"] is True
        assert first["delivery"]["telegram_send"] is False
        assert "без доставки" in first["note"]
        with pytest.raises(HTTPException) as exc3:
            _run(S.post_expression_live_check(
                None, env.user, S.ExpressionLiveCheck(message="ещё"),
                str(env.chat_id)))
        assert exc3.value.status_code == 429, "rate-limit одной пробы"
    finally:
        S._live_check_state["ts"] = 0.0
        S._live_check_state["busy"] = False


def test_live_check_class_reports_missing_marker(api_env, monkeypatch):
    env = api_env

    class _FakeService:
        async def _l2_write_answer(self, chat_id, query, **kwargs):
            diag = kwargs.get("diag_out")
            if isinstance(diag, dict):
                diag.update({"expression_marker": False,
                             "expression_mode": "frequent",
                             "expression_rendered": True,
                             "provider_error": False})
            return "Ну и всё.", "warm"

    monkeypatch.setattr(S, "_direct_service", lambda: _FakeService())

    async def _fake_settings(_chat):
        return pc.ExpressionSettings(text="x", mode="frequent")

    monkeypatch.setattr(pc, "resolve_expression_settings", _fake_settings)
    S._live_check_state["ts"] = 0.0
    S._live_check_state["busy"] = False
    try:
        out = _run(S.post_expression_live_check(
            None, env.user, S.ExpressionLiveCheck(message="привет"),
            str(env.chat_id)))
    finally:
        S._live_check_state["ts"] = 0.0
    assert out["diag_class"] == "policy_not_injected"


def test_ui_renders_payload_not_raw_codes():
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "data-speech-effective" in index
    assert "data-speech-migration" in index
    assert "data-speech-live-run" in index
    assert "data-speech-live-result" in index
    assert "Проверить вживую" in index
    assert "speechEffectiveText" in app_js
    assert "speechControlEffectiveText" in app_js
    assert "runExpressionLiveCheck" in app_js
    assert "c.instruction" in app_js, "предпросмотр из payload, не из копии"
    assert "Как в характере (естественный)" not in app_js
    assert "'allowed'" not in app_js


# ═══ 9. no-postprocessor ════════════════════════════════════════════════════

def test_no_profanity_postprocessor_exists():
    from services import style_policy as sp
    from services import outgoing_guard
    from services.direct_chat_service import _delivered_payload
    assert not any("profan" in kind for kind in sp.RULE_KINDS)
    assert outgoing_guard.EXTRA_PATTERNS == ()
    text = "Ну и хуй с ним, бля. Хуёво вышло."
    assert _delivered_payload(text) == text
    source = (ROOT / "services" / "style_policy.py").read_text(
        encoding="utf-8").casefold()
    assert "profan" not in source, "профильных правил мата в форме нет"


# ═══ 10. few-shot: отбор/изоляция/бюджет ════════════════════════════════════

@pytest_asyncio.fixture
async def db(tmp_path):
    from services.database import DatabaseService
    service = DatabaseService(str(tmp_path / "add-exp-samples.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


def test_expression_seed_composition_is_draft_only():
    assert len(sl.EXPRESSION_STARTER_SAMPLES) == 12
    modes = {}
    for sample in sl.EXPRESSION_STARTER_SAMPLES:
        assert sample["technique"] == "expression_register"
        tags = sl.parse_tags(json.dumps(sample["tags"], ensure_ascii=False))
        modes.setdefault(tags[0], []).append(sample)
        assert sample["context_note"] in (
            "дружеский стёб", "спор", "короткий ответ", "быт")
    assert set(modes) == {"mode:off", "mode:occasional", "mode:frequent"}
    assert all(len(rows) == 4 for rows in modes.values())
    # тексты не дублируют humor-сиды; метакомментариев о настройках нет
    humor = {str(s.get("reply_text") or "") for s in sl.STARTER_SAMPLES}
    expr = {str(s.get("reply_text") or "")
            for s in sl.EXPRESSION_STARTER_SAMPLES}
    assert not (humor & expr)
    for sample in sl.EXPRESSION_STARTER_SAMPLES:
        low = (str(sample["input_text"]) + " "
               + str(sample["reply_text"])).casefold()
        for banned in ("настройк", "инструкц", "сейчас добавлю", "мат:",
                       "режим"):
            assert banned not in low, (banned, sample["seed_key"])
    assert "expression_register" in sl.SAMPLE_TECHNIQUES


@pytest.mark.asyncio
async def test_expression_examples_seed_select_and_isolation(db, monkeypatch):
    monkeypatch.delenv("EXPRESSION_EXAMPLES_ENABLED", raising=False)
    first = await sl.seed_expression_samples(db)
    assert first["seeded"] == 12
    again = await sl.seed_expression_samples(db)
    assert again["seeded"] == 0 and again["skipped"] == 12
    # черновики (owner_approved=0) в runtime НЕ идут — честная причина
    assert await sl.resolve_expression_examples(777, "off", db=db) == ()
    rows = await sl.list_samples(db, technique="expression_register")
    assert len(rows) == 12
    for row in rows:
        await sl.set_approval(db, int(row["id"]), approved=True,
                              actor="owner")
    off_rows = await sl.resolve_expression_examples(777, "off", db=db)
    freq_rows = await sl.resolve_expression_examples(777, "frequent", db=db)
    assert len(off_rows) == 4 and len(freq_rows) == 4
    assert all(sl.EXPRESSION_MODE_TAGS["off"] in sl.parse_tags(r["tags"])
               for r in off_rows)
    assert all(sl.EXPRESSION_MODE_TAGS["frequent"]
               in sl.parse_tags(r["tags"]) for r in freq_rows)
    block = ex.render_expression_examples_block("off", off_rows)
    assert block.startswith('<Expression_Examples mode="off">')
    assert block.endswith("</Expression_Examples>")
    assert " -> " in block and "«" not in block and "→" not in block
    # QUOTA-REMOVAL (A5): локального лимита символов/токенов нет — все
    # применимые строки режима входят в блок, включая длинные авторские.
    long_block = ex.render_expression_examples_block("frequent", [
        {"context_note": "быт", "input_text": "и" * 900,
         "reply_text": "о" * 900}])
    assert long_block.startswith('<Expression_Examples mode="frequent">')
    assert long_block.endswith("</Expression_Examples>")
    assert "и" * 900 in long_block and "о" * 900 in long_block
    assert not hasattr(ex, "EXPRESSION_EXAMPLES_MAX_TOKENS")
    assert not hasattr(ex, "EXPRESSION_EXAMPLES_MAX_CHARS")
    # своя ось: OFF → пусто (набор не впрыскивается), инструкция живёт
    monkeypatch.setenv("EXPRESSION_EXAMPLES_ENABLED", "0")
    assert await sl.resolve_expression_examples(777, "off", db=db) == ()


def test_humor_path_never_takes_expression_register():
    row = {
        "id": 1, "input_text": "вход", "reply_text": "ответ",
        "technique": "expression_register", "context_note": "",
        "language": "ru", "tags": ["mode:off"], "rudeness_level": 0,
        "source_kind": "owner_manual", "scope": "global", "chat_id": None,
        "owner_approved": 1, "status": "active", "library_version": "v1",
        "revision": 1, "uses_count": 0, "last_used_at": None,
        "sensitivity_flags": [],
    }
    selection = sl.select_samples([row], chat_id=7, technique="deadpan",
                                  policy=None)
    assert selection.samples == ()
    assert any(item["reason"] == "expression_register"
               for item in selection.excluded)
    humor_row = dict(row, id=2, technique="deadpan")
    selection2 = sl.select_samples([row, humor_row], chat_id=7,
                                   technique="deadpan", policy=None)
    assert [int(r["id"]) for r in selection2.samples] == [2]


def test_composer_expression_examples_before_humor_and_budgeted(monkeypatch):
    expr_block = ex.render_expression_examples_block("occasional", [{
        "context_note": "спор", "input_text": "не работает",
        "reply_text": "у меня крутится"}])
    humor_block = "<Examples>\nВход: a\nОтвет: б\n</Examples>"
    plan = _expression_plan(
        expression=pc.ExpressionSettings(
            text=HEADER + "\n" + OCC_LINE + "\n</Expression_Settings>",
            revision="e1", mode="occasional"),
        expression_examples=(pc.SampleRef(
            block_id="expression_examples", text=expr_block,
            revision="ex1", source="global",
            technique="expression_register"),),
        samples=(pc.SampleRef(text=humor_block, library_version="v1",
                              revision="v1"),),
        gates=pc.GateState(unified_composer_enabled=True,
                           humor_library_enabled=True))
    manifest = pc.compose_prompt(plan)
    assert expr_block in manifest.system and humor_block in manifest.system
    assert manifest.system.index(expr_block) < manifest.system.index(
        humor_block), "набор регистра речи идёт ДО humor-примеров"
    trace = [t for t in manifest.layers
             if t.block_id == "expression_examples"][0]
    assert trace.rendered is True and trace.owner == "core"
    assert manifest.versions["expression_examples"] == "ex1"
    # QUOTA-REMOVAL (A5): локальной квоты нет — набор регистра речи остаётся
    # в payload даже при «тесном» значении прежней переменной.
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "20")
    tight = pc.compose_prompt(plan)
    trace_tight = [t for t in tight.layers
                   if t.block_id == "expression_examples"][0]
    assert trace_tight.rendered is True and trace_tight.skip_reason == ""
    assert expr_block in tight.system
    # своя ось OFF → своя причина, не humor `samples_disabled`
    off_axis = pc.compose_prompt(pc.PromptPlan(**{
        **plan.__dict__,
        "gates": pc.GateState(unified_composer_enabled=True,
                              expression_examples_enabled=False)}))
    trace_off = [t for t in off_axis.layers
                 if t.block_id == "expression_examples"][0]
    assert trace_off.skip_reason == "expression_examples_disabled"
    # нет набора → expression_examples_absent (честная причина)
    none_plan = pc.compose_prompt(pc.PromptPlan(**{
        **plan.__dict__, "expression_examples": ()}))
    trace_none = [t for t in none_plan.layers
                  if t.block_id == "expression_examples"][0]
    assert trace_none.skip_reason == "expression_examples_absent"


# ═══ 11. BLOCK-1: сид-флоу через прод-путь (эндпоинт) ════════════════════════

@pytest_asyncio.fixture
async def seed_db(tmp_path, monkeypatch):
    """temp-DB в прод-пути сида: `samples_lib.get_db()` → тестовая база."""
    from services.database import DatabaseService
    service = DatabaseService(str(tmp_path / "add-exp-seed.db"))
    await service.initialize()
    monkeypatch.setattr(sl, "get_db", lambda: service)
    yield service
    try:
        await service.close()
    except Exception:
        pass


def test_seed_endpoint_creates_expression_drafts_idempotently(api_env,
                                                              seed_db):
    """BLOCK-1: прод-эндпоинт сида заводит И набор регистра речи."""
    env = api_env
    first = _run(S.post_examples_seed(None, env.user, str(env.chat_id)))
    assert first["ok"] is True
    assert first["seeded"] == len(sl.STARTER_SAMPLES) == 18
    assert first["expression_seeded"] == \
        len(sl.EXPRESSION_STARTER_SAMPLES) == 12
    assert "not_owner_approved" in first["note"]
    rows = _run(sl.list_samples(seed_db, technique="expression_register"))
    assert len(rows) == 12
    assert all(not row["owner_approved"] for row in rows), \
        "черновики не выдаются за одобренные"
    assert all(row["scope"] == "global" for row in rows)
    assert all(row["source_kind"] == "bot_suggested" for row in rows)
    modes = {tag for row in rows for tag in row["tags"]
             if str(tag).startswith("mode:")}
    assert modes == {"mode:off", "mode:occasional", "mode:frequent"}
    # идемпотентность: повтор — no-op по обеим подборкам (без дублей)
    again = _run(S.post_examples_seed(None, env.user, str(env.chat_id)))
    assert again["seeded"] == 0 and again["expression_seeded"] == 0
    assert again["skipped"] == 18 and again["expression_skipped"] == 12
    assert len(_run(sl.list_samples(seed_db,
                                    technique="expression_register"))) == 12
    assert len(_run(sl.list_samples(seed_db))) == 30


def test_not_owner_approved_then_block_renders_after_approval(api_env,
                                                              seed_db):
    """BLOCK-1: «нет одобренных» ≠ «нет строк»; одобрение включает блок."""
    env = api_env
    _run(S.post_examples_seed(None, env.user, str(env.chat_id)))
    rows, reason = _run(sl.resolve_expression_examples_ex(777, "off",
                                                          db=seed_db))
    assert rows == () and reason == "not_owner_approved"
    refs = _run(ex.build_expression_examples_refs(777, "off", db=seed_db))
    assert len(refs) == 1 and refs[0].enabled is False
    assert refs[0].skip_reason == "not_owner_approved"
    assert refs[0].skip_reason in pc.SKIP_REASONS
    manifest = pc.compose_prompt(_expression_plan(expression_examples=refs))
    trace = [t for t in manifest.layers
             if t.block_id == "expression_examples"][0]
    assert trace.rendered is False
    assert trace.skip_reason == "not_owner_approved"
    assert "<Expression_Examples" not in manifest.system
    # владелец утверждает одну карточку существующим механизмом
    all_rows = _run(sl.list_samples(seed_db, technique="expression_register"))
    target = next(row for row in all_rows if "mode:off" in row["tags"])
    approved, _err = _run(sl.set_approval(seed_db, int(target["id"]),
                                          approved=True, actor="owner"))
    assert approved is not None and approved["owner_approved"] is True
    refs2 = _run(ex.build_expression_examples_refs(777, "off", db=seed_db))
    assert len(refs2) == 1 and refs2[0].enabled is True
    assert refs2[0].skip_reason == ""
    assert refs2[0].text.startswith('<Expression_Examples mode="off">')
    manifest2 = pc.compose_prompt(_expression_plan(expression_examples=refs2))
    assert refs2[0].text in manifest2.system
    # другие режимы остаются неодобренными (свой набор у каждого режима)
    other_rows, other_reason = _run(
        sl.resolve_expression_examples_ex(777, "frequent", db=seed_db))
    assert other_rows == () and other_reason == "not_owner_approved"


def test_examples_payload_exposes_expression_register_technique(api_env,
                                                                seed_db):
    """BLOCK-1: техника видна владельцу в разделе «Примеры» (человеческая метка)."""
    env = api_env
    _run(S.post_examples_seed(None, env.user, str(env.chat_id)))
    view = _run(S.get_examples(None, env.user, None))
    techniques = {t["id"]: t for t in view["techniques"]}
    assert "expression_register" in techniques
    assert techniques["expression_register"]["title"] == \
        S.EXPRESSION_REGISTER_TECHNIQUE["title"]
    assert "мат" in techniques["expression_register"]["title"].casefold()
    # ось юмора НЕ расширена (перечень приёмов прежний)
    assert [t["id"] for t in S.HUMOR_TECHNIQUES] == [
        "absurd_escalation", "literalism", "deadpan", "bureaucratic_logic",
        "unexpected_analogy", "other"]
    technique_field = next(f for f in view["entity_fields"]
                           if f["id"] == "technique")
    assert "expression_register" in technique_field["values"], \
        "правка карточки существующим редактором остаётся возможной"
    # счётчики подборок не склеены (18 юмор + 12 регистра речи)
    assert view["starter"]["expected"] == 18
    assert view["starter"]["seeded"] == 18
    assert view["starter"]["expression_expected"] == 12
    assert view["starter"]["expression_seeded"] == 12
    items = [row for row in view["items"]
             if row["technique"] == "expression_register"]
    assert len(items) == 12
    assert all(not row["owner_approved"] for row in items)
    # фильтр по технике работает (владелец видит только этот набор)
    filtered = _run(S.get_examples(None, env.user, None,
                                   technique="expression_register"))
    assert filtered["count"] == 12
    assert all(row["technique"] == "expression_register"
               for row in filtered["items"])


def test_ui_shows_expression_register_label_not_raw_code():
    """ADD-SAMPLES-UX §4: карточка не показывает сырой код техники; мат
    идёт своей категорией/подписью, человеческие метки приёмов — в
    редакторе и расширенном фильтре (`humorTechniqueOptions`/`sampleCaption`).
    """
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "sampleCaption(row)" in index
    assert "category_label" in app_js
    # сырой код техники в карточке не печатается
    assert "row.technique }}" not in index.split("data-speech-samples")[1] \
        .split("data-speech-examples-legacy")[0]
    assert "expression_seeded" in app_js
    assert "Мат" in index
