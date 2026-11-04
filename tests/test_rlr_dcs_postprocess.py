"""RLR-04 (часть 2) — пост-обработка Direct: без постфактум-переписывания.

REMOVE-LEGACY-REPHRASING v2.0 (owner corrective 2026-11-05, source
`plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`):

* R-04.2 — `apply_numeric_guard` больше не правит доставляемый текст
  (ни свободную речь Writer'а, ни рассказ «Летописца»: его тоже пишет
  модель). Числа приходят в Writer ДО генерации; расхождение — наблюдение;
* R-04.5 / R-FAIL.5 — формат (списки/таблицы) не повод для нового
  LLM-вызова; невалидная HTML-разметка сериализуется в plain ТЕМ ЖЕ текстом;
* R-05.1–R-05.4 — `duplicate_guard_retry` (reroll по совпадению текста
  двух РАЗНЫХ событий) снят; идемпотентность ДОСТАВКИ одного события
  сохранена (идентичность update, а не текст);
* §8 «Настройки `no_quotes`/`no_emoji`» — ровно один механический проход,
  protected spans целы.

TEST-LIFECYCLE: CONTRACT owner=RLR-04-REROLL.
"""
import pytest

from services import direct_chat_service as dcs
from services import mca_events
from services import negative_constraints as nc
from services import style_policy as sp
from services.smart_cache import SmartCache
from tests.test_direct_chat import (
    CHAT_ID,
    FakeDB,
    FakeLLM,
    FakeMemory,
    _bot,
    _force_self_awareness,
    _make_service,
    _message,
    _user,
)

FORBIDDEN_REROLL_STEPS = {"duplicate_guard_retry"}


class StepLLM(FakeLLM):
    """FakeLLM + список `step` всех вызовов (доказательство отсутствия reroll)."""

    def __init__(self, text="ответ бота"):
        super().__init__(text=text)
        self.steps: list = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.steps.append(kwargs.get("step"))
        return await super().generate(messages, temperature=temperature,
                                      chat_id=chat_id)


class RecentDB(FakeDB):
    """FakeDB + последняя реплика бота в ledger (для duplicate-наблюдения)."""

    def __init__(self, recent_text=None, **kwargs):
        super().__init__(**kwargs)
        self.recent_text = recent_text

    async def list_recent_bot_outputs(self, chat_id, limit=1):
        if self.recent_text is None:
            return []
        return [{"content_text": self.recent_text,
                 "output_kind": "direct_reply"}]


@pytest.fixture(autouse=True)
def _self_awareness_off(monkeypatch):
    """Изоляция: фоновый экстрактор самоосознания не тратит вызовы FakeLLM."""
    _force_self_awareness(monkeypatch, False)


@pytest.fixture
def events(monkeypatch):
    """Перехват контракта mca-13: (event_name, outcome, fields)."""
    seen: list = []
    real = mca_events.emit_mca_event

    def spy(event_name, *, outcome, **fields):
        seen.append({"event_name": event_name, "outcome": outcome,
                     **fields})
        return None

    monkeypatch.setattr(mca_events, "emit_mca_event", spy)
    try:
        yield seen
    finally:
        mca_events.emit_mca_event = real


def _reasons(seen, event_name):
    return [e.get("reason_code") for e in seen
            if e.get("event_name") == event_name]


def _set_l1(monkeypatch, enabled: bool) -> None:
    from config.settings import Settings
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", enabled)


# ════════════════════════════════════════════════════════════════════════════
# (a)+(e) R-04.2: число вне проверенных данных доставляется как написано
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("l1", [False, True])
async def test_free_form_number_delivered_as_written(monkeypatch, events, l1):
    """Незаземлённое число не правится и не удаляется; расхождение —
    наблюдение с честным кодом (не `numeric_claim_corrected`)."""
    _set_l1(monkeypatch, l1)
    llm = StepLLM(text="Да я тебе 5 раз это говорил. Ну и что?")
    service = _make_service(memory=FakeMemory(window=[]), llm=llm,
                            db=RecentDB())
    bot = _bot()
    msg = _message(text="ты меня никогда не называл шизом",
                   message_id=771, chat_id=-1009877)
    await service.handle(bot, msg, msg.from_user)

    sent = bot.send_message.await_args.args[1]
    assert "5 раз" in sent                     # текст автора цел
    assert nc.NUMERIC_CLAIM_CAVEAT not in sent  # оговорка не подставлена
    assert "9" not in sent                      # verified_phrase не вставлена
    assert FORBIDDEN_REROLL_STEPS.isdisjoint(set(llm.steps))
    if not l1:
        assert llm.call_count == 1              # ни одного лишнего вызова

    assert "numeric_claim_corrected" not in _reasons(events,
                                                     "numeric_claim_guard")
    observed = [e for e in events
                if e["event_name"] == "numeric_claim_guard"]
    assert observed, "расхождение обязано быть видно наблюдаемо"
    assert observed[0]["reason_code"] == nc.NUMERIC_CLAIM_MISMATCH
    assert observed[0]["outcome"] == "skipped"       # guard не действовал
    assert observed[0]["usage_json"].get("corrected") is False
    assert "5 раз" not in str(observed[0].get("usage_json") or "")


@pytest.mark.asyncio
async def test_no_numeric_event_when_nothing_to_correct(monkeypatch, events):
    """(e) Числа в стат-контексте нет → нет и события «исправлено»."""
    _set_l1(monkeypatch, False)
    llm = StepLLM(text="обычная болтовня без измерений")
    service = _make_service(memory=FakeMemory(window=[]), llm=llm,
                            db=RecentDB())
    bot = _bot()
    msg = _message(text="как дела?", message_id=772, chat_id=-1009878)
    await service.handle(bot, msg, msg.from_user)

    assert _reasons(events, "numeric_claim_guard") == []
    assert all("numeric_claim_corrected" != e.get("reason_code")
               for e in events)


# ════════════════════════════════════════════════════════════════════════════
# (b) R-05.1–R-05.4: дубль текста ≠ дубль доставки
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("l1", [False, True])
async def test_two_events_same_text_are_two_answers(monkeypatch, events, l1):
    """Совпавший текст двух РАЗНЫХ событий: два независимых ответа, без
    reroll, без jitter-фразы."""
    _set_l1(monkeypatch, l1)
    same = "Ну и что тут скажешь, всё как обычно."
    llm = StepLLM(text=same)
    # Прошлая реплика бота ДРУГОМУ событию — нормализованный текст совпадает.
    db = RecentDB(recent_text=same)
    service = _make_service(memory=FakeMemory(window=[]), llm=llm, db=db)
    bot = _bot()
    await service.handle(bot, _message(text="первый вопрос", message_id=781,
                                       chat_id=-1009879), _user())
    await service.handle(bot, _message(text="второй вопрос", message_id=782,
                                       chat_id=-1009879), _user())

    assert FORBIDDEN_REROLL_STEPS.isdisjoint(set(llm.steps))
    assert bot.send_message.await_count == 2
    first = bot.send_message.await_args_list[0].args[1]
    second = bot.send_message.await_args_list[1].args[1]
    assert first == second                       # одинаковый текст законен
    assert "direct_freshness_retry" not in _reasons(events,
                                                    "DIRECT_FRESHNESS_RETRY")


@pytest.mark.asyncio
async def test_same_event_redelivery_is_blocked(tmp_path, monkeypatch, events):
    """Повторная доставка ОДНОГО события — по-прежнему без дубля (0 LLM,
    0 reply): идемпотентность держится на идентичности update."""
    _set_l1(monkeypatch, False)
    cache = SmartCache(str(tmp_path / "dcs_upd.db"))
    llm = StepLLM(text="ответ бота на вопрос")
    service = _make_service(memory=FakeMemory(window=[]), llm=llm, db=RecentDB(),
                            cache=cache)
    bot = _bot()
    try:
        msg = _message(text="вопрос", message_id=791, chat_id=-1009880)
        await service.handle(bot, msg, msg.from_user)
        assert llm.call_count == 1
        # тот же Telegram update приходит снова
        await service.handle(bot, msg, msg.from_user)
        assert llm.call_count == 1               # 0 LLM
        assert bot.send_message.await_count == 1  # 0 повторной отправки
        assert "direct_update_dedup_hit" in _reasons(events,
                                                    "DIRECT_UPDATE_DEDUP_HIT")
    finally:
        await cache.close()


# ════════════════════════════════════════════════════════════════════════════
# (c) R-04.5 / R-FAIL.5: формат — рендер того же текста, не новый автор
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "Вот расклад:\n| месяц | сообщений |\n|---|---|\n| май | 5 |",
    "Итоги:\n- пункт один\n- пункт два\n- пункт три",
])
async def test_table_and_list_delivered_without_new_generation(
        monkeypatch, text):
    """Список/таблица: один вызов Writer'а, доставлен тот же текст."""
    _set_l1(monkeypatch, False)
    llm = StepLLM(text=text)
    service = _make_service(memory=FakeMemory(window=[]), llm=llm,
                            db=RecentDB())
    bot = _bot()
    msg = _message(text="сделай список", message_id=801, chat_id=-1009881)
    await service.handle(bot, msg, msg.from_user)

    assert llm.call_count == 1
    assert FORBIDDEN_REROLL_STEPS.isdisjoint(set(llm.steps))
    assert bot.send_message.await_args.args[1] == text   # байт-в-байт


@pytest.mark.asyncio
async def test_invalid_html_renders_same_text_plain():
    """HTML не поддержан (TelegramBadRequest) → plain ТЕМ ЖЕ текстом."""
    from aiogram.exceptions import TelegramBadRequest

    answer = "итог: <b>важно</b> и 5 < 7 & готово"
    sent = type("Sent", (), {"message_id": 4242})()
    calls: list = []

    class _Bot:
        async def send_message(self, chat_id, text, **kwargs):
            calls.append({"text": text, **kwargs})
            if kwargs.get("parse_mode") == "HTML":
                raise TelegramBadRequest(method="sendMessage",
                                         message="can't parse entities")
            return sent

    result = await dcs.DirectChatService._send_direct_answer(
        _Bot(), CHAT_ID, answer, None, lore=True)

    assert result == 4242
    assert len(calls) == 2                        # HTML → plain, один текст
    assert calls[0]["parse_mode"] == "HTML"
    assert calls[0]["text"] != answer             # разметка была экранирована
    assert calls[1]["text"] == answer             # исходный смысловой payload
    assert calls[1].get("parse_mode") != "HTML"


# ════════════════════════════════════════════════════════════════════════════
# (d) §8: правила владельца — ровно один проход, protected spans целы
# ════════════════════════════════════════════════════════════════════════════

def _owner_policy():
    doc = sp.build_document(rules=[
        {"id": "quotation_marks.hard.no_graphic", "kind": "quotation_marks",
         "strictness": "hard", "params": {"mode": "strip"},
         "conflict_strategy": "exempt_protected"},
        {"id": "emoji.hard.off", "kind": "emoji", "strictness": "hard",
         "params": {}, "conflict_strategy": "exempt_protected"},
    ])
    return sp.effective_policy_sync(global_doc=doc, context="regular")


@pytest.mark.asyncio
async def test_owner_rules_single_pass_and_protected_spans(monkeypatch):
    """Один проход в реальном ходу; повторный — no-op; код/URL не испорчены."""
    _set_l1(monkeypatch, False)
    calls: list = []
    real = sp.apply_style_policy

    async def spy(*args, **kwargs):
        calls.append(kwargs.get("stage"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(sp, "apply_style_policy", spy)

    text = "Код `print(1)` и ссылка https://example.org/a?b=1 — готово"
    llm = StepLLM(text=text)
    service = _make_service(memory=FakeMemory(window=[]), llm=llm,
                            db=RecentDB())
    bot = _bot()
    msg = _message(text="покажи код", message_id=811, chat_id=-1009882)
    await service.handle(bot, msg, msg.from_user)

    assert calls.count("direct_pre_send") == 1     # ровно один проход
    delivered = bot.send_message.await_args.args[1]
    assert "`print(1)`" in delivered
    assert "https://example.org/a?b=1" in delivered

    policy = _owner_policy()
    raw = "🤖 Он сказал «привет»."
    first = await sp.apply_style_policy(raw, policy=policy, chat_id=0,
                                        record=False)
    second = await sp.apply_style_policy(first.text, policy=policy, chat_id=0,
                                         record=False)
    assert first.text == "Он сказал привет."       # no_quotes + no_emoji
    assert second.text == first.text and second.repaired == 0
    keeper = await sp.apply_style_policy(
        "Код `x = «y»` и 🤖", policy=policy, chat_id=0, record=False,
        extra_protected=["`x = «y»`"])
    assert "`x = «y»`" in keeper.text             # protected span цел


# ════════════════════════════════════════════════════════════════════════════
# R-04.2 (ревью 05.11): «Летописец» — текст МОДЕЛИ, а не сборка кода
# ════════════════════════════════════════════════════════════════════════════

STORY = "он писал 7 сообщений за всё время. И ещё пару раз упоминал это."
SINGLE = "он писал 7 сообщений за всё время."


class _Claim:
    value = 9
    unit = "messages"


def _story_service(monkeypatch, llm, contract, story):
    """handle() с доставкой текста «Летописца» (как его отдаёт компилятор)."""
    import services.direct_chat_service as _dcs

    monkeypatch.setattr(_dcs, "lore_story_override",
                        lambda tool_ctx, l1_plan=None, response_plan=None:
                        story)
    monkeypatch.setattr(dcs.DirectChatService,
                        "_numeric_contract_from_ctx",
                        lambda self, tool_ctx: contract)
    return _make_service(memory=FakeMemory(window=[]), llm=llm, db=RecentDB())


@pytest.mark.asyncio
@pytest.mark.parametrize("story", [SINGLE, STORY], ids=["single", "multi"])
@pytest.mark.parametrize("contract_kind", ["empty", "verified_phrase"])
async def test_lore_story_number_delivered_without_guard(
        monkeypatch, events, contract_kind, story):
    """Реальный `handle()`: рассказ с «7 сообщений» доставляется ЦЕЛИКОМ.

    Ревью 05.11: текст «Летописца» пишет модель (`LoreCompilerService.llm.
    generate`, writer `lore_writer`), поэтому numeric-гард к нему неприменим.
    (а) пустой контракт — с гардом пропадало предложение с числом (для
    однопредложенческого рассказа: 0 отправок + реакция «тишина»);
    (б) контракт с `verified_phrase` — вместо рассказа уходило «сообщений: 9».
    """
    _set_l1(monkeypatch, False)
    contract = (nc.NumericContract() if contract_kind == "empty" else
                nc.NumericContract(claims=(_Claim(),),
                                   verified_phrase="сообщений: 9"))
    llm = StepLLM(text="ответ Writer'а игнорируется при story-интенции")
    service = _story_service(monkeypatch, llm, contract, story)
    bot = _bot()
    msg = _message(text="расскажи историю про это", message_id=821,
                   chat_id=-1009883)
    await service.handle(bot, msg, msg.from_user)

    assert bot.send_message.await_count == 1          # доставка есть
    sent = bot.send_message.await_args.args[1]
    assert sent == story                              # рассказ цел
    assert "7 сообщений" in sent                      # число автора не снято
    assert "сообщений: 9" not in sent                 # verified_phrase не вставлена
    assert getattr(bot.set_message_reaction, "await_count", 0) == 0  # не тишина
    assert "numeric_claim_corrected" not in _reasons(events,
                                                     "numeric_claim_guard")


@pytest.mark.asyncio
async def test_lore_story_mismatch_is_only_observation(monkeypatch, events):
    """Расхождение числа в рассказе видно в событии как НАБЛЮДЕНИЕ."""
    _set_l1(monkeypatch, False)
    contract = nc.NumericContract(claims=(_Claim(),),
                                  verified_phrase="сообщений: 9")
    llm = StepLLM(text="не важно")
    service = _story_service(monkeypatch, llm, contract, STORY)
    bot = _bot()
    msg = _message(text="расскажи историю", message_id=822, chat_id=-1009884)
    await service.handle(bot, msg, msg.from_user)

    observed = [e for e in events if e["event_name"] == "numeric_claim_guard"]
    assert observed and observed[0]["reason_code"] == nc.NUMERIC_CLAIM_MISMATCH
    assert observed[0]["outcome"] == "skipped"
    assert observed[0]["usage_json"].get("corrected") is False


def test_apply_numeric_guard_has_no_product_caller():
    """R-04.2: хелпер жив, но НИ ОДИН доставляемый текст им не правится.

    Единственный продуктовый потребитель (доставка «Летописца») удалён в
    ревью 05.11: текст рассказа пишет модель, а не код.
    """
    import inspect
    import re
    from pathlib import Path

    root = Path(dcs.__file__).resolve().parents[1]
    callers: dict[str, list[int]] = {}
    for path in (list((root / "services").glob("*.py"))
                 + list((root / "handlers").glob("*.py"))):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"apply_numeric_guard\(", text):
            line = text.count("\n", 0, match.start()) + 1
            source_line = text.splitlines()[line - 1]
            if "def apply_numeric_guard" in source_line or \
                    source_line.lstrip().startswith("#"):
                continue
            callers.setdefault(path.name, []).append(line)
    assert callers == {}, callers
    # функция оставлена осознанно (будущая сборка строки кодом)
    assert callable(nc.apply_numeric_guard)
    assert "продуктовых вызывающих" in inspect.getdoc(nc.apply_numeric_guard)


def test_no_post_l2_llm_step_in_direct_postprocess_source():
    """Структурный инвариант: в пост-обработке Direct нет шага reroll."""
    import inspect
    source = inspect.getsource(dcs)
    assert 'step="duplicate_guard_retry"' not in source
