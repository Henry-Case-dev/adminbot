"""P0 corrective (25.11.2026), lane C — конечная цель хода и маршрутизация медиа.

Контракт (приёмка — контрактная, не оценка качества речи):

* ``P0I-GOAL-01`` — «изучи старые поздравления автора и напиши новое»: доставлен
  новый текст в заданной манере, а исследование о поиске не подменяет продукт;
  конечная цель сохраняется на ходе L1 → планирование → контекст → Writer.
  ``plans/features/unified-reply/requirements-map-p0-2026-11-25.json``.
* ``P0I-GOAL-02`` — если человек просит и анализ, и новый текст, доставленный
  ответ содержит обе части (обратный перекос — тоже нарушение).
* ``P0R-MEDIA-01`` — разговорная реплика в ответ на медиа не порождает
  скачивания/повторной отправки исходника.
  ``plans/features/smart-module-semantic-routing/requirements-map-p0-2026-11-25.json``.
* ``P0R-MEDIA-02`` — запрос преобразования выполняет именно запрошенную
  операцию, если она доступна; при недоступности — честный ответ, а не подмена
  другой операцией.

Источник: ``plans/owner_inputs/2026-11-25-p0-intent-memory-answer-quality.md``
§2 (sha256 0d2b3516…); границы приёмки —
``plans/owner_inputs/2026-11-25-p0-acceptance-boundaries-amendment.md`` §11-35.

TEST-LIFECYCLE: CONTRACT owner=P0-GOAL-MEDIA
"""
from __future__ import annotations

import asyncio
import hashlib

from services import chat_prompts as cp
from services import direct_capabilities as dcaps
from services import direct_execution as dx
from services import direct_l1 as l1
from services import tool_schemas as ts


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _plan(**kwargs) -> l1.L1Plan:
    base = dict(action="reply", response_act="answer", extent="normal",
                structure="answer", delivery_hint="plain")
    base.update(kwargs)
    return l1.L1Plan(**base)


class _RecordingRouter:
    """Заглушка только для НАБЛЮДЕНИЯ вызовов: тестируемое поведение —
    отсутствие/наличие инструментального шага, а не работа инструмента."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def dispatch(self, name, arguments, ctx):        # pragma: no cover
        self.calls.append((name, dict(arguments or {})))
        raise AssertionError("tool dispatch must not happen in this test")


# ── (a)/(b)/(c)/(f) — конечная цель в плане и у Writer ──────────────────────

def test_rule7_distinguishes_product_from_material():
    """Правило 7 больше не превращает «изучи X и напиши Y» в исследование
    вместо Y, но сохраняет research для настоящего разбора материала."""
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    rule = cp._DIRECT_L1_RULE7_PRODUCT_P0GM
    assert canon.count(rule) == 1
    # продукт назван результатом, подготовка — не результат
    assert "Разделяй конечный результат и материал для него" in rule
    assert "конечный результат - этот новый текст или действие" in rule
    assert "Такой ход не становится исследованием" in rule
    # обе запрошенные части обязательны (запрет обратного перекоса)
    assert "в ответе\n   нужны обе части" in rule or "нужны обе части" in rule
    # манера речи — стиль, не биография
    assert "служит стилем, а не\n   поводом рассказывать биографию" in rule \
        or "служит стилем" in rule
    # настоящий разбор/исследование сохранены
    assert "это разбор материала: response_act=research" in rule
    assert "Исследование, фактчек, исторический рассказ, сводка и технический" \
        in rule
    # прежняя ветка «разбор материала» не осталась активной в старом виде
    assert cp._DIRECT_L1_RULE7_PRODUCT_PREV_P0GM not in canon
    # прежние байты канона — точный слепок (ступень отката ADR-1013-3)
    assert _sha12(cp.PREV_DIRECT_L1_PLANNER_EVR6) == "619290834387"
    assert _sha12(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT) == "ce6931304b24"
    assert cp.PREV_DIRECT_L1_PLANNER_EVR6 != canon


def test_canon_has_no_incident_hardcode_or_trigger_lists():
    """Запрет P0 §2/§6: семантика без словарей триггеров и реплик инцидента."""
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT.casefold()
    for banned in ("дотер", "солнышко", "никита", "поздравления никиты",
                   "надо лицо", "download/media_download"):
        assert banned not in canon, banned
    # маршрутизация не решается отдельными словами
    assert "по отдельным словам" in canon


def test_final_goal_field_is_in_schema_and_plan_contract():
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert '"final_goal": ""' in canon
    assert "КОНЕЧНАЯ ЦЕЛЬ ХОДА (final_goal)" in canon
    contract = cp._DIRECT_L1_FINAL_GOAL_P0GM
    # цель — результат, а не подготовка
    assert "подготовка в нём не называется" in contract
    # несколько результатов называются все (P0I-GOAL-02)
    assert "назови их все" in contract
    # промежуточный инструмент цель не меняет
    assert "final_goal не меняют: это вход, а не результат" in contract


def test_normalize_reads_final_goal_and_never_invents_it():
    plan = l1.normalize_l1_plan({"action": "reply",
                                 "response_act": "creative",
                                 "final_goal": "  новое   поздравление  "})
    assert plan is not None
    assert plan.final_goal == "новое поздравление"
    # отсутствие/мусор → пусто, план валиден, цель не выдумана
    empty = l1.normalize_l1_plan({"action": "reply"})
    assert empty is not None and empty.final_goal == ""
    garbage = l1.normalize_l1_plan({"action": "reply", "final_goal": {"a": 1}})
    assert garbage is not None and garbage.final_goal == ""
    long_goal = l1.normalize_l1_plan({"action": "reply",
                                      "final_goal": "я" * 500})
    assert len(long_goal.final_goal) == l1.FINAL_GOAL_MAX


def test_writer_receives_requested_product_with_material_as_input():
    """«Разбор + новый текст»: Writer видит и акт, и запрошенный продукт."""
    plan = _plan(
        response_act="research", structure="answer", extent="normal",
        final_goal="новое поздравление в манере автора и краткий разбор манеры")
    block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan))
    assert "смысловой акт ответа: research" in block
    assert "цель хода: новое поздравление в манере автора" in block
    assert "служат входом, а не заменой" in block
    assert "не пересказывай" in block     # analysis-директива не сломана
    # обычный ход без цели: payload прежний (строки нет)
    plain = l1.build_l2_plan_block(_plan(response_act="banter",
                                         structure="chat"))
    assert "цель хода:" not in plain


def test_goal_survives_tool_phase_into_writer():
    """Цель едет в плане: tool-фаза работает на копии и не переписывает её."""
    plan = _plan(response_act="creative", capabilities_needed=("web_search",),
                 execution_mode="simple_tools",
                 final_goal="новое поздравление в манере автора")
    plan.search_intent = l1.SEARCH_NOT_APPLICABLE
    router = _RecordingRouter()
    result = asyncio.run(
        dx.run_tool_phase(
            plan=plan, router=router, ctx=object(), query="поздравь Никиту",
            chat_id=0, correlation_id="goal-test",
            tool_schemas=[ts.TOOL_EXECUTE_WEB_SEARCH],
            announced={"execute_web_search"}, emit_trace=False))
    assert result is not None
    assert router.calls == []          # поиск снят осью, шагов нет
    assert plan.final_goal == "новое поздравление в манере автора"
    assert plan.response_act == "creative"
    block = l1.build_l2_plan_block(plan)
    assert "цель хода: новое поздравление в манере автора" in block


def test_genuine_research_keeps_its_contract():
    """Настоящее исследование/фактчек/сводка не ослаблены новым правилом."""
    plan = _plan(response_act="research", structure="answer", extent="compact")
    setattr(plan, "final_goal", "исторический рассказ о событиях года")
    assert l1.plan_response_mode(plan) == "serious"
    assert l1.analysis_directive_needed(plan) is True
    assert l1.delta_instruction_needed(plan) is True
    # творческий/исторический ход по-прежнему может доставить готовую историю
    assert l1.lore_story_delivery_allowed(plan) is False
    story = _plan(response_act="historical_recall", structure="story")
    assert l1.lore_story_delivery_allowed(story) is True


def test_unknown_intent_is_not_research_by_default():
    """Неопределённая интенция не становится исследованием и отчётом."""
    plan = l1.L1Plan()
    assert plan.response_act == "other"
    assert l1.analysis_directive_needed(plan) is False
    assert l1.delta_instruction_needed(plan) is False
    assert l1.plan_response_mode(plan) == "casual"
    block = l1.build_l2_plan_block(plan)
    assert "смысловой акт ответа: research" not in block
    assert "цель хода:" not in block


# ── (d)/(e) — медиа: реплика ≠ операция, преобразование ≠ скачивание ────────

def test_media_section_states_reply_is_not_an_operation():
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    section = cp._DIRECT_L1_MEDIA_ACTIONS_P0GM
    assert canon.count(section) == 1
    assert "Разговорную реплику по поводу фото или видео не превращай" in section
    assert "Повторная отправка того же материала не является выполнением" \
        in section
    assert "не подменяй запрошенное действие другой доступной операцией" \
        in section
    assert "Не запрашивай возможность ради самого вызова инструмента" \
        in section


def test_download_media_description_forbids_reply_comment_invocation():
    desc = ts.TOOL_DOWNLOAD_MEDIA["function"]["description"]
    low = desc.casefold()
    assert "only when the user asks to get, save or send the file itself" \
        in low
    assert "comment, joke or remark about a video or photo is conversation" \
        in low
    assert "never call it just because the turn replies to media" in low
    assert "cannot transform" in low
    # схема не изменилась: только текст описания
    assert ts.TOOL_DOWNLOAD_MEDIA["function"]["parameters"]["required"] == []
    assert ts.TOOL_DOWNLOAD_MEDIA["function"]["parameters"][
        "additionalProperties"] is False


def test_conversational_reply_to_video_triggers_no_media_operation():
    """Сценарий A: реплика в ответ на видео → 0 инструментальных шагов."""
    plan = _plan(response_act="banter", structure="chat", extent="compact")
    ctx = type("Ctx", (), {"chat_id": 1, "reply_to_message_id": 42,
                           "media_target_message_id": 42})()
    steps, limitations = dx.derive_simple_steps(
        plan, query="Надо лицо дотера в это солнышко", ctx=ctx,
        announced={"download_media", "generate_image", "edit_image"})
    assert steps == []
    assert not any(s["tool"] == "download_media" for s in steps)
    assert limitations == []

    router = _RecordingRouter()
    result = asyncio.run(
        dx.run_simple_tools(
            plan=plan, router=router, ctx=ctx,
            query="Надо лицо дотера в это солнышко", chat_id=1,
            correlation_id="media-a",
            announced={"download_media", "generate_image", "edit_image"}))
    assert result is None          # ни вызовов, ни повторной отправки
    assert router.calls == []


def test_explicit_download_request_still_derives_the_download_step():
    """Положительный контроль: явная просьба о файле по-прежнему работает."""
    plan = _plan(response_act="answer", capabilities_needed=("media_download",))
    steps, _ = dx.derive_simple_steps(
        plan, query="скинь это видео файлом", ctx=None,
        announced={"download_media"})
    assert [s["tool"] for s in steps] == ["download_media"]


def test_transform_request_maps_to_the_transform_capability_not_download():
    """Запрос преобразования: доступная операция — именно преобразование."""
    resolved, rejected = dcaps.resolve_capabilities(
        ("image_edit",), {"edit_image", "download_media", "generate_image"})
    assert resolved == ["edit_image"]
    assert rejected == []
    # второй доступный инструмент не подставляется вместо запрошенного
    _steps, limitations = dx.derive_simple_steps(
        _plan(capabilities_needed=("image_edit",)),
        query="добавь на фото шляпу", ctx=None,
        announced={"edit_image", "download_media", "generate_image"})
    assert all("download_media" not in line for line in limitations)


def test_unavailable_transform_degrades_honestly_without_substitution():
    """Возможности нет → честная пометка, а не скачивание/повторная отправка."""
    resolved, rejected = dcaps.resolve_capabilities(
        ("image_edit",), {"download_media"})
    assert resolved == []
    assert rejected == [("image_edit", dcaps.REASON_NOT_ACTIVE)]
    note = dcaps.rejected_note(rejected)
    assert "редактирование картинок" in note
    assert "скачивание медиа" not in note
    assert "download_media" not in note


# ── канон-лестница: ступень P0GM добавлена, прежние байты целы ──────────────

def test_canon_ladder_has_p0gm_step():
    from services import prompt_migrations as pm
    key = "prompts.direct_l1_planner_system_prompt"
    steps = pm.PROMPT_MIGRATIONS[key]
    assert steps[0] == (cp.PREV_DIRECT_L1_PLANNER_EVR6,
                        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT)
    rollback = pm.ROLLBACK_MIGRATIONS[key]
    assert rollback[0] == (cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
                           cp.PREV_DIRECT_L1_PLANNER_EVR6)
    assert rollback[1] == (cp.PREV_DIRECT_L1_PLANNER_EVR6,
                           cp.PREV_DIRECT_L1_PLANNER_EVR5)
