"""REMOVE-LEGACY-REPHRASING v2.0 — R-03.3: узкая проверка защищённых данных
ЯВНОЙ трансформации поданного текста (и никогда — свободной речи).

Owner corrective `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`:
R-03.1 (в свободном Direct контракта нет), R-03.2 (списки отрицаний не
расширяются), R-03.3 (для явных команд «перепиши/переведи/отредактируй»
допустим узкий контроль неизменяемых данных с прозрачным исходом), R-06
(«Явный запрос перепиши/переведи: L2 — автор запрошенной трансформации,
оригинал — source data»), §8 строка «Explicit rewrite/translate».

Проверяется ПРОДОВЫЙ шов, а не только `verbalize_validated`:

* сигнал «ход трансформирует поданный текст» — существующая классификация
  плана L1 (`response_act=summarization` / `structure=summary`) плюс реально
  поданный пользователем исходник (текст reply-родителя);
* для такого хода `DirectChatService.handle` строит
  `FormContract(source_text=<исходник>)` и передаёт его в единственный
  авторский вызов; нарушение защищённых данных → пользователю уходит
  ИСХОДНИК (прозрачно), второго литературного автора нет;
* свободная речь контракта не получает (`form_contract=None`) и уходит как
  написана, ровно одним вызовом Writer'а.

MUTATION: убрать построение контракта для явной трансформации (вернуть
`form_contract=None` в шов `handle`) → тест (a) красный (приходит испорченный
текст вместо исходника + пропадает сам контракт).

TEST-LIFECYCLE: CONTRACT owner=REMOVE-LEGACY-REPHRASING (R-03, R-06)
"""
import pytest

from services import negative_constraints as nc

pytestmark = pytest.mark.system2


SOURCE = "Кирилл не прислал 3 файла"
REWRITE_DROPS_FACTS = "Кирилл прислал 7 файлов."

HOT_CLOCK = {"today": "05.11.2026"}


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


def _drive(monkeypatch, *, query, l2_text, reply=None, plan_over=None):
    """Реальный Direct-путь (`handle`) с фейковым LLM; возвращает (svc, llm,
    захваченные kwargs шва `_l2_write_answer`)."""
    from services import direct_chat_service as dcs
    from tests.test_asap7_direct_l1 import _drive as drive_handle
    from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json

    plan = {"response_act": "summarization", "structure": "summary"}
    plan.update(plan_over or {})
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
    срабатывает, пользователь получает ИСХОДНИК, второй автор не вызывается."""
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch,
        query="перепиши этот текст: Кирилл не прислал 3 файла",
        l2_text=REWRITE_DROPS_FACTS, reply=_source_message())
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


@pytest.mark.asyncio
async def test_explicit_rewrite_without_supplied_source_stays_ungoverned(
        monkeypatch):
    """«Перескажи переписку» без поданного исходника: контракта нет.

    Иначе вопрос пользователя стал бы source-текстом и честный пересказ
    откатывался бы в эхо вопроса (защита границей «есть reply-исходник»)."""
    rewritten = "Обсуждали сервер: Кирилл прислал 2 файла, Аня ждала ответ."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="перескажи, о чём говорили",
        l2_text=rewritten, reply=None)
    await svc.handle(bot, msg, user)

    assert seen.get("form_contract") is None
    assert seen.get("form_fallback_text") in (None, "")
    assert _delivered(svc) == rewritten
    assert len(llm.calls_of("l2_writer")) == 1


# ════════════════════════════════════════════════════════════════════════════
# (b) Верная трансформация: данные целы → текст уходит как написан
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_faithful_rewrite_is_delivered_as_written(monkeypatch):
    faithful = "Как оказалось, Кирилл так и не прислал 3 файла."
    svc, llm, seen, bot, msg, user = _drive(
        monkeypatch, query="перепиши этот текст",
        l2_text=faithful, reply=_source_message())
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
        monkeypatch, query="ну как там с файлами?",
        l2_text=answer, reply=_source_message(),
        plan_over={"response_act": "answer", "structure": "chat"})
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
        monkeypatch, query="переведи этот текст",
        l2_text=translated, reply=_source_message(text=source))
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


# ════════════════════════════════════════════════════════════════════════════
# Границы: сигнал — план хода, а не угадывание формулировки
# ════════════════════════════════════════════════════════════════════════════

def test_transform_signal_comes_from_the_plan_only():
    """Контракт строится по плану L1 (`response_act`/`structure`) и наличию
    поданного исходника — без новых классификаторов и списков слов."""
    from services import direct_chat_service as dcs
    from services import response_extent as _extent

    sum_plan = _extent.ResponsePlan(task_kind="summarization",
                                    structure="summary")
    plain_plan = _extent.ResponsePlan(task_kind="answer", structure="chat")
    contract, source = dcs._explicit_transform_contract(
        sum_plan, SOURCE, roster_names=("Кирилл", "Вася"))
    assert isinstance(contract, nc.FormContract)
    assert contract.source_text == SOURCE
    assert source == SOURCE
    assert contract.roster_names == ("Вася", "Кирилл")
    # Свободный план — контракта нет даже при поданном исходнике.
    assert dcs._explicit_transform_contract(
        plain_plan, SOURCE) == (None, "")
    # План без полей / None (мусор) — тоже свободная речь.
    assert dcs._explicit_transform_contract(None, SOURCE) == (None, "")
