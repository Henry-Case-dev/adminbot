"""REMOVE-LEGACY-REPHRASING v2.0 — R-03.3: узкая проверка защищённых данных
ЯВНОЙ трансформации поданного текста (и никогда — сводки или свободной речи).

Owner corrective `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`:
R-03.1 (в свободном Direct контракта нет), R-03.2 (списки отрицаний не
расширяются), R-03.3 (для явных команд «перепиши/переведи/отредактируй»
допустим узкий контроль неизменяемых данных с прозрачным исходом), R-06
(«Явный запрос перепиши/переведи: L2 — автор запрошенной трансформации,
оригинал — source data»), §8 строка «Explicit rewrite/translate».

Сигнал — функциональное необязательное поле плана L1
``preserve_source_facts`` (канон EVR5, `services/chat_prompts.py`, описано
рядом с `recheck`/осью поиска): модель ставит ``true`` только когда человек
просит изменить/перевести ПОДАННЫЙ им текст с сохранением смысла. Ни акт
`summarization`/`structure=summary`, ни обычные акты сами по себе контракта не
создают: сводка — законная трансформация, где числа исходника могут сжиматься.

Проверяется ПРОДОВЫЙ шов, а не только `verbalize_validated`:

* для хода с ``preserve_source_facts=true`` и реально поданным исходником
  `DirectChatService.handle` строит `FormContract(source_text=<исходник>)` и
  передаёт его в единственный авторский вызов; нарушение защищённых данных →
  пользователю уходит ИСХОДНИК (прозрачно), второго автора нет;
* сводка/пересказ и свободная речь контракта не получают
  (`form_contract=None`) и уходят как написаны, ровно одним вызовом Writer'а.

MUTATION: убрать построение контракта по `preserve_source_facts` (вернуть
`form_contract=None` в шов `handle`) → тест (a) красный (приходит испорченный
текст вместо исходника + пропадает сам контракт).

TEST-LIFECYCLE: CONTRACT owner=REMOVE-LEGACY-REPHRASING (R-03, R-06)
"""
import pytest

from services import negative_constraints as nc

pytestmark = pytest.mark.system2


SOURCE = "Кирилл не прислал 3 файла"
REWRITE_DROPS_FACTS = "Кирилл прислал 7 файлов."

#: Реалистичный план явной трансформации: обычный акт ответа + новый сигнал.
TRANSFORM_PLAN = {"response_act": "answer", "structure": "chat",
                  "preserve_source_facts": True}
#: Сводка/пересказ: акт сводки БЕЗ сигнала сохранения фактов.
SUMMARY_PLAN = {"response_act": "summarization", "structure": "summary",
                "preserve_source_facts": False}
#: Обычный разговорный ответ: ни акта трансформации, ни сигнала.
CHAT_PLAN = {"response_act": "answer", "structure": "chat",
             "preserve_source_facts": False}


def _source_message(text=SOURCE, message_id=501, from_user_id=777):
    """Reply-родитель: текст, который пользователь просит трансформировать."""
    from unittest.mock import MagicMock

    msg = MagicMock()
    msg.message_id = message_id
    msg.text = text
    msg.caption = None
    msg.from_user = MagicMock()
    msg.from_user.id = from_user_id        # не bot_id (12345) — человек
    msg.from_user.first_name = "Кирилл"
    msg.from_user.username = "kirill"
    msg.web_page = None
    for attr in ("photo", "video", "video_note", "voice", "audio",
                 "animation", "sticker", "document"):
        setattr(msg, attr, None)
    return msg


def _drive(monkeypatch, *, query, l2_text, plan, reply=None):
    """Реальный Direct-путь (`handle`) с фейковым LLM; возвращает (svc, llm,
    захваченные kwargs шва `_l2_write_answer`, bot, msg, user)."""
    from services import direct_chat_service as dcs
    from tests.test_asap7_direct_l1 import _drive as drive_handle
    from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json

    llm = _FakeLLM(l1=_plan_json(**plan), l2=l2_text)
    svc, _react, bot, msg, user = drive_handle(
        monkeypatch, query, reply=reply, llm=llm)
    seen: dict = {}
    real = dcs.DirectChatService._l2_write_answer

    async def _spy(self, chat_id, query, **kwargs):
        seen.update(kwargs)
        return await real(self, chat_id, query, **kwargs)

    monkeypatch.setattr(dcs.DirectChatService, "_l2_write_answer", _spy)
    return svc, llm, seen, bot, msg, user


def _delivered(svc):
    assert svc._send_direct_answer.await_count == 1
    return svc._send_direct_answer.await_args.args[2]


# ════════════════════════════════════════════════════════════════════════════
# (a) Явная трансформация: автор потерял отрицание/число → прозрачный исход
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_explicit_rewrite_that_breaks_protected_facts_returns_source(
        monkeypatch):
    """«Перепиши этот текст» с потерей «не» и подменой числа: узел проверки
    срабатывает, пользователь получает ИСХОДНИК, второго автора нет."""
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch,
        query="перепиши этот текст: Кирилл не прислал 3 файла",
        l2_text=REWRITE_DROPS_FACTS, plan=TRANSFORM_PLAN,
        reply=_source_message())
    await svc.handle(bot, msg, user)

    # Контракт реально построен в продовом шве и несёт исходник пользователя.
    contract = seen.get("form_contract")
    assert isinstance(contract, nc.FormContract), seen.get("form_contract")
    assert contract.source_text == SOURCE
    assert seen.get("form_fallback_text") == SOURCE

    # Нарушение защищённых данных → доставлен исходник, а не испорченный текст.
    delivered = _delivered(svc)
    assert delivered == SOURCE, delivered
    assert "7 файлов" not in delivered
    # Ровно один авторский вызов: второй литературной правки не существует.
    assert len(llm.calls_of("l2_writer")) == 1


# ════════════════════════════════════════════════════════════════════════════
# (b) Верная трансформация: данные целы → текст уходит как написан
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_faithful_rewrite_is_delivered_as_written(monkeypatch):
    faithful = "Как оказалось, Кирилл так и не прислал 3 файла."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="перепиши этот текст", l2_text=faithful,
        plan=TRANSFORM_PLAN, reply=_source_message())
    await svc.handle(bot, msg, user)

    assert isinstance(seen.get("form_contract"), nc.FormContract)
    assert _delivered(svc) == faithful
    assert len(llm.calls_of("l2_writer")) == 1


# ════════════════════════════════════════════════════════════════════════════
# (c) Свободная речь: контракта нет, проверки нет, текст как написан
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_free_form_reply_has_no_form_contract(monkeypatch):
    """Обычный разговорный ответ: `form_contract=None`, один вызов, текст
    байт-в-байт (числа/отрицания не сравниваются с чужим текстом)."""
    answer = "Да не парься, я всё видел: скинул 2 файла вчера."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="ну как там с файлами?", l2_text=answer,
        plan=CHAT_PLAN, reply=_source_message())
    await svc.handle(bot, msg, user)

    assert seen.get("form_contract") is None
    assert seen.get("form_fallback_text") in (None, "")
    assert _delivered(svc) == answer
    assert len(llm.calls_of("l2_writer")) == 1


# ════════════════════════════════════════════════════════════════════════════
# (d) Явный перевод: числа/имена/даты сохраняются, текст не подменяется
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_translation_keeps_numbers_names_and_dates(monkeypatch):
    source = "Кирилл прислал 3 файла 5 ноября, автор Вася."
    translated = "Kirill sent 3 files on 5 November, author Vasya."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="переведи этот текст", l2_text=translated,
        plan={"response_act": "other", "structure": "chat",
              "preserve_source_facts": True},
        reply=_source_message(text=source))
    await svc.handle(bot, msg, user)

    contract = seen.get("form_contract")
    assert isinstance(contract, nc.FormContract)
    assert contract.source_text == source
    delivered = _delivered(svc)
    # Ничего не потеряно и ничего не подменено исходником.
    assert delivered == translated
    assert "3" in delivered and "5" in delivered
    assert "Kirill" in delivered and "Vasya" in delivered
    assert len(llm.calls_of("l2_writer")) == 1


@pytest.mark.asyncio
async def test_translation_with_negation_is_delivered_as_written(monkeypatch):
    """Блокер приёмки: верный перевод отрицательной фразы не откатывается.

    «Кирилл не прислал 3 файла 5 ноября.» → «Kirill did not send 3 files on
    5 November.»: русской «не» в переводе нет по построению, поэтому
    лексикон отрицаний к другой письменности не применяется — текст уходит
    как написан, а числа/даты остаются под проверкой.
    """
    source = "Кирилл не прислал 3 файла 5 ноября."
    translated = "Kirill did not send 3 files on 5 November."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="переведи этот текст на английский", l2_text=translated,
        plan={"response_act": "other", "structure": "chat",
              "preserve_source_facts": True},
        reply=_source_message(text=source))
    await svc.handle(bot, msg, user)

    assert isinstance(seen.get("form_contract"), nc.FormContract)
    assert _delivered(svc) == translated
    assert len(llm.calls_of("l2_writer")) == 1


@pytest.mark.asyncio
async def test_translation_that_drops_a_number_returns_source(monkeypatch):
    """Перевод, потерявший число, защищённые данные нарушил → исходник."""
    source = "Кирилл не прислал 3 файла 5 ноября."
    translated = "Kirill did not send the files on 5 November."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="переведи этот текст на английский", l2_text=translated,
        plan={"response_act": "other", "structure": "chat",
              "preserve_source_facts": True},
        reply=_source_message(text=source))
    await svc.handle(bot, msg, user)

    assert isinstance(seen.get("form_contract"), nc.FormContract)
    assert _delivered(svc) == source
    assert len(llm.calls_of("l2_writer")) == 1


@pytest.mark.asyncio
async def test_russian_answer_with_long_latin_quote_keeps_negation_check(
        monkeypatch):
    """Ужесточение: «латиницы больше» — НЕ основание пропускать проверку.

    Русский ответ с длинной латинской цитатой содержит кириллицу, поэтому
    русский лексикон отрицаний к нему применим: потерянное «не» → исходник,
    хотя латинских букв в кандидате больше."""
    source = "Кирилл не прислал 3 файла 5 ноября."
    l2_text = ("Kirill sent 3 files on 5 November. The quick brown fox jumps "
               "over the lazy dog again and again in a long english quote. "
               "Это цитата из документа.")
    assert nc._has_cyrillic(l2_text)                 # кириллица есть
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="перескажи этот текст по-русски", l2_text=l2_text,
        plan={"response_act": "answer", "structure": "chat",
              "preserve_source_facts": True},
        reply=_source_message(text=source))
    await svc.handle(bot, msg, user)

    assert isinstance(seen.get("form_contract"), nc.FormContract)
    assert _delivered(svc) == source
    assert len(llm.calls_of("l2_writer")) == 1


def test_same_script_negation_loss_is_still_rejected():
    """Регресс не сломан: русский → русский с потерей «не» — по-прежнему
    отказ узкой проверки (в результате есть кириллица, лексикон применим)."""
    source = "Кирилл не прислал 3 файла 5 ноября."
    assert nc._has_cyrillic(source)
    # потеря «не» при сохранённых числах
    assert nc.check_form_contract(
        "Кирилл прислал 3 файла 5 ноября.",
        nc.FormContract(source_text=source)) == nc.FORM_GUARD_REJECTED
    # верная правка того же языка — проходит
    assert nc.check_form_contract(
        "Как выяснилось, Кирилл не прислал 3 файла 5 ноября.",
        nc.FormContract(source_text=source)) is None
    # латиница ↔ латиница: лексикон тот же (русский), проверка остаётся
    # строгой по числам
    assert nc.check_form_contract(
        "Kirill sent 3 files on 5 November.",
        nc.FormContract(source_text="Kirill sent 3 files on 5 November.")) is None
    assert nc.check_form_contract(
        "Kirill sent files on 5 November.",
        nc.FormContract(source_text="Kirill sent 3 files on 5 November.")) \
        == nc.FORM_GUARD_REJECTED


# ════════════════════════════════════════════════════════════════════════════
# (e) Сводка/пересказ поданного текста: строгой буквальной проверки НЕТ
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_short_summary_with_number_is_delivered_as_summary(
        monkeypatch):
    """Сводка вправе сжать числа: «Кирилл не прислал 3 файла, ждали до 20:00»
    → «Кирилл не прислал файлы» доставляется как пересказ, а не полный
    исходник (регресс прежнего сигнала `summarization`)."""
    source = "Кирилл не прислал 3 файла, Аня ждала до 20:00."
    summary = "Кирилл не прислал файлы, ждали до вечера."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="перескажи этот текст коротко", l2_text=summary,
        plan=SUMMARY_PLAN, reply=_source_message(text=source))
    await svc.handle(bot, msg, user)

    assert seen.get("form_contract") is None
    assert seen.get("form_fallback_text") in (None, "")
    assert _delivered(svc) == summary
    assert len(llm.calls_of("l2_writer")) == 1


# ════════════════════════════════════════════════════════════════════════════
# Границы сигнала: только поле плана + реально поданный исходник
# ════════════════════════════════════════════════════════════════════════════

def test_contract_signal_comes_from_the_plan_field_only():
    """Контракт строит только `preserve_source_facts=True` плана L1; акт
    сводки и «перескажи переписку» без поданного исходника — без контракта."""
    from services import direct_chat_service as dcs
    from services import direct_l1 as _l1

    transform = _l1.L1Plan(response_act="answer", structure="chat",
                           preserve_source_facts=True)
    contract, source = dcs._explicit_transform_contract(
        transform, SOURCE, roster_names=("Кирилл", "Вася"))
    assert isinstance(contract, nc.FormContract)
    assert contract.source_text == SOURCE
    assert source == SOURCE
    assert contract.roster_names == ("Вася", "Кирилл")

    # Сводка сигнала не несёт — контракта нет даже при поданном исходнике.
    summary = _l1.L1Plan(response_act="summarization", structure="summary")
    assert dcs._explicit_transform_contract(summary, SOURCE) == (None, "")
    # Обычный акт без поля — тоже свободная речь.
    assert dcs._explicit_transform_contract(
        _l1.L1Plan(response_act="answer", structure="chat"), SOURCE) \
        == (None, "")
    # Поле есть, но исходник не подан — контракта нет (иначе «перескажи
    # переписку» откатывался бы в эхо вопроса).
    assert dcs._explicit_transform_contract(transform, "") == (None, "")
    assert dcs._explicit_transform_contract(None, SOURCE) == (None, "")


def test_plan_field_is_a_strict_boolean():
    """`preserve_source_facts` — строгий boolean (прецедент `recheck`):
    только реальный true включает сигнал, «true»-строка/1/мусор — нет."""
    from services import direct_l1 as _l1

    base = {"action": "reply", "response_act": "answer", "structure": "chat"}
    assert _l1.normalize_l1_plan(
        dict(base, preserve_source_facts=True)).preserve_source_facts is True
    for junk in ("true", 1, None, [], {}, "yes"):
        plan = _l1.normalize_l1_plan(
            dict(base, preserve_source_facts=junk))
        assert plan.preserve_source_facts is False, junk
    assert _l1.normalize_l1_plan(dict(base)).preserve_source_facts is False


def test_transform_signal_is_documented_in_the_l1_canon():
    """Канон L1 реально учит модель полю (иначе оно снова станет мёртвым)."""
    from services import chat_prompts as cp

    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert '"preserve_source_facts": false' in canon
    assert "СОХРАНЕНИЕ ФАКТОВ ПОДАННОГО ТЕКСТА" in canon
    assert "переписать, отредактировать или перевести" in canon
    # Прежняя ревизия — ступень отката, не активные байты.
    assert cp.PREV_DIRECT_L1_PLANNER_EVR4 != canon
    assert "preserve_source_facts" not in cp.PREV_DIRECT_L1_PLANNER_EVR4
