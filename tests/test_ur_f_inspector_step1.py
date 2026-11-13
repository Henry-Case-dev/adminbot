"""UR-F «Полнота инспектора хода» — ШАГ 1 (контракт данных, без UI).

Источник: `plans/features/unified-reply/evidence/ur-f-inspector-contract.md`
(§2 — новое событие `direct_turn_selection`, §3 — приватность/allow-ветка
ссылок, §6 шаг 1). Покрывается именно контракт записи:

* `direct_turn_selection` эмитится для РЕАЛЬНОГО хода с полями
  `counts/budget/blocks/dropped/self_outputs/policy_version` и связан с
  трассой хода тем же `trace_id`;
* событие пишется БЕЗ in-memory `TurnTrace` (иначе теряется, когда
  `begin()` не состоялся) — это прямое требование контракта;
* жёсткие лимиты списков (блоки ≤16, id ≤8, потерянное ≤8, свои реплики ≤6):
  переполнение усекается детерминированно и видно (`truncated`), а не
  исчезает молча;
* `_scrub` принимает ровно `source_url` вида `^https?://…` (остальное — ""),
  `source_title` ≤120, любой другой длинный текст по-прежнему digest;
* сбой сборки выбора НЕ ломает ответ (fail-open, §7 R3);
* `style_policy` получает `trace_id` и СРАБОТАВШИЕ правила (id/причина) без
  текста правил и без `RuleOutcome.detail`.

TEST-LIFECYCLE: CONTRACT owner=UR-F (`ur-f-inspector-contract.md`, шаг 1).
"""
import json

import pytest

from services import direct_chat_service
from services import mca_events
from services import style_policy as _sp
from services import thread_chain
from services import turn_trace
from services.llm_client import LLMCompletion

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

CHAT_ID = -1009876543210
BOT_ID = 12345
#: Сентinel-строки: их НЕ должно быть ни в одном payload'е новой трассы.
SECRET_QUERY = "СЕКРЕТНЫЙ_ВОПРОС_URF_123456"
SECRET_ANSWER = "УНИКАЛЬНЫЙ_ОТВЕТ_URF_987654"


@pytest.fixture(autouse=True)
def _clean_trace():
    turn_trace.reset()
    yield
    turn_trace.reset()


@pytest.fixture
def events(monkeypatch):
    """Перехват единственной точки эмиссии (`mca_events.emit_mca_event`)."""
    seen: list = []

    def spy(event_name, *, outcome, **fields):
        seen.append({"event_name": event_name, "outcome": outcome, **fields})
        return {"event_name": event_name, "outcome": outcome, **fields}

    monkeypatch.setattr(mca_events, "emit_mca_event", spy)
    return seen


def _event(seen, name):
    for item in seen:
        if item.get("event_name") == name:
            return item
    raise AssertionError("нет события %r; есть %r"
                         % (name, [e.get("event_name") for e in seen]))


def _payload(seen, name):
    return dict(_event(seen, name).get("usage_json") or {})


def _payload_of(seen, name, trace_id):
    """Payload КОНКРЕТНОГО события (по `trace_id`) — списки могут повторяться."""
    for item in seen:
        if item.get("event_name") == name \
                and item.get("trace_id") == trace_id:
            return dict(item.get("usage_json") or {})
    raise AssertionError("нет события %r для trace_id=%r"
                         % (name, trace_id))


# ── ход целиком (тот же харнесс, что у RLR-06-OBSERVABILITY) ────────────────

def _rows(count=6):
    """Строки окна чата: часть — реплики БОТА (для `self_outputs`)."""
    rows = []
    for i in range(1, count + 1):
        is_bot = (i % 3 == 0)
        rows.append({
            "id": i, "tg_message_id": 500 + i,
            "user_id": BOT_ID if is_bot else 10,
            "author_name": "бот" if is_bot else "Вася",
            "text": "строка окна %d" % i,
            "timestamp": 1_700_000_000 + i,
            "reply_to_id": None, "media_type": "text",
        })
    return rows


class _StagedLLM:
    """L1-план + финальный Writer с метаданными (как в проде)."""

    def __init__(self, *, plan=None):
        self.l1_reply = plan if plan is not None else _plan()
        self.calls: list = []
        self.last: list = []          # фактический payload последнего вызова
        self._chat_model = "chat-model-x"
        self._base_url = "https://api.test/v1"
        self._fallback_model = "fb-model"

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append(step)
        self.last = list(messages or ())
        if step == "l1_planner":
            return self.l1_reply
        return SECRET_ANSWER

    async def generate_with_metadata(self, messages, temperature=None,
                                     chat_id=None, module=None, step=None,
                                     correlation_id=None, **kwargs):
        self.calls.append(step)
        self.last = list(messages or ())
        sent = {"model": "chat-model-x",
                "messages": [dict(m or {}) for m in (messages or ())]}
        if step == "l1_planner":
            return _completion(self.l1_reply, "stop", correlation_id, sent)
        return _completion(SECRET_ANSWER, "stop", correlation_id, sent)


def _plan():
    from tests.test_asap7_direct_l1 import _plan_json
    return _plan_json()


def _completion(text, finish_reason, correlation_id=None, sent_body=None):
    return LLMCompletion(
        text=text, finish_reason=finish_reason, provider="test-provider",
        model="test-model", usage={"prompt_tokens": 11, "completion_tokens": 7,
                                   "total_tokens": 18},
        max_output_tokens_sent=1000, attempt=1,
        correlation_id=correlation_id, sent_body=sent_body)


def _confirm_small_window(monkeypatch, window_tokens: int) -> None:
    """SMART D1: маленькое окно модели — ПОДТВЕРЖДЁННОЕ значение резолвера.

    Прежде эти сценарии опирались на удалённый аварийный 16384-fallback
    неизвестной модели; теперь неизвестная модель планирует 1M, поэтому
    «тесное окно» задаётся явно на уровне источника окна. Бюджетная
    арифметика (reserve/policy) остаётся прежней — подменяется только окно."""
    from services import model_capacity as _mc

    async def _window(base_url, model, slot=None):
        return (int(window_tokens), "runtime")

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _window)
    # Legacy-контур (`resolver_on` OFF): окно берётся из
    # `resolve_effective_window` прямо в `direct_chat_service`.
    monkeypatch.setattr(
        dcs, "resolve_effective_window",
        lambda primary, fallback=None: (int(window_tokens),
                                        _mc.WINDOW_SOURCE_FALLBACK))


def _drive(monkeypatch, llm, *, text="бот, как дела?", window=None,
           facts=None, model_window=None):
    """Продовый ход Direct (композер ON) с РЕАЛЬНОЙ доставкой.

    ``model_window`` — подтверждённое окно модели для сценариев, которым нужно
    сжатие контекста (иначе неизвестная модель планирует 1M, SMART D1)."""
    from config.settings import Settings
    from tests.test_direct_chat import FakeMemory, _bot, _make_service, \
        _message, _user

    if model_window is not None:
        _confirm_small_window(monkeypatch, int(model_window))
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    memory = FakeMemory(window=list(window or ()),
                        rag_facts=list(facts) if facts else None)
    svc = _make_service(memory=memory, llm=llm)
    bot = _bot()
    msg = _message(text=text, message_id=4242, chat_id=CHAT_ID)
    return svc, bot, msg, _user()


def _turn_events(seen, name):
    """События одного хода по `trace_id` его контекстного события."""
    correlation_id = _event(seen, turn_trace.EVENT_CONTEXT).get("trace_id")
    assert correlation_id
    return correlation_id, [e for e in seen
                            if e.get("trace_id") == correlation_id]


# ════════════════════════════════════════════════════════════════════════════
# 1. Событие выбора для реального хода: форма payload'а и связь с трассой
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_real_turn_emits_selection_event_with_contract_shape(
        monkeypatch, events):
    """Реальный ход: `direct_turn_selection` с тем же `trace_id`, что трасса.

    Проверяются ФАКТИЧЕСКИЕ значения: блоки ссылаются на сообщения окна
    (source_id/даты), свои реплики бота видны отдельным списком, счётчики
    описывают реальное окно, бюджет — посчитанный ходом."""
    from services import direct_context_composer as _composer

    rows = _rows(6)
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=rows)
    await svc.handle(bot, msg, user)

    correlation_id, turn = _turn_events(events, turn_trace.EVENT_SELECTION)
    selection = [e for e in turn
                 if e.get("event_name") == turn_trace.EVENT_SELECTION]
    assert len(selection) == 1, "событие выбора должно быть ровно одно"
    event = selection[0]
    payload = dict(event.get("usage_json") or {})

    # ── привязка к трассе хода и стадия
    assert event.get("trace_id") == correlation_id
    assert event.get("stage") == "turn_selection"
    assert event.get("component") == "direct_chat"
    assert event.get("chat_id") == CHAT_ID

    # ── версия политики: без неё «0» в счётчиках не честен (§2 контракта)
    assert payload.get("policy_version") == \
        _composer.COMPOSER_POLICY_VERSION

    # ── счётчики: реальное окно хода
    counts = payload.get("counts") or {}
    assert counts.get("window_messages") == len(rows)
    assert counts.get("available_messages") >= len(rows)
    assert counts.get("included_messages") >= 1

    # ── бюджет: посчитанные ходом числа (а не заглушки)
    budget = payload.get("budget") or {}
    assert budget.get("slot") == "direct.primary"
    assert isinstance(budget.get("window"), int) and budget["window"] > 0
    assert isinstance(budget.get("budget"), int) and budget["budget"] > 0
    assert budget.get("policy_mode")
    assert isinstance(budget.get("payload_tokens"), int)

    # ── блоки: свежий хвост окна с РЕАЛЬНЫМИ source_id и датами
    blocks = payload.get("blocks") or []
    assert blocks, "блоки контекста не записаны"
    tail = [b for b in blocks if b.get("kind") == "global_tail"]
    assert tail, "нет блока свежего хвоста: %r" % [b.get("kind")
                                                   for b in blocks]
    tail_ids = list(tail[0].get("source_ids") or ())
    assert tail_ids, "у блока хвоста нет source_ids"
    assert len(tail_ids) <= turn_trace.SELECTION_SOURCE_IDS_MAX
    # id — по формуле композера (msg:/bot_output_tg:), не выдуманные
    assert all(ref.split(":", 1)[0] in ("msg", "bot_output_tg", "row")
               for ref in tail_ids), tail_ids
    expected_tg = {str(row["tg_message_id"]) for row in rows}
    assert {ref.split(":", 1)[1] for ref in tail_ids} <= expected_tg
    assert tail[0].get("first_ts") and tail[0].get("last_ts")
    assert tail[0]["first_ts"] <= tail[0]["last_ts"]
    assert isinstance(tail[0].get("tokens"), int)

    # ── свои реплики в истории: реальные бот-строки окна
    self_outputs = payload.get("self_outputs") or []
    assert self_outputs, "свои реплики бота не записаны"
    bot_tgs = {row["tg_message_id"] for row in rows
               if row["user_id"] == BOT_ID}
    assert {row.get("tg_message_id") for row in self_outputs} <= bot_tgs
    assert all(str(row.get("source_id", "")).startswith("bot_output_tg:")
               for row in self_outputs), self_outputs

    # ── приватность: ни вопроса, ни ответа, ни текста строк окна
    blob = json.dumps(event, ensure_ascii=False)
    for forbidden in (SECRET_QUERY, SECRET_ANSWER, "строка окна"):
        assert forbidden not in blob, "текст попал в событие выбора: %s" % \
            forbidden


# ════════════════════════════════════════════════════════════════════════════
# 2. Событие пишется БЕЗ in-memory трассы (`begin()` не состоялся)
# ════════════════════════════════════════════════════════════════════════════

def test_selection_is_recorded_without_in_memory_trace(events):
    """`begin()` не вызывался → события всё равно есть (требование §2).

    Иначе ровно тот случай, ради которого событие вводилось (нет/вытеснена
    трасса), терял бы данные о том, что вошло в запрос."""
    assert turn_trace.get("cid-no-trace") is None

    turn_trace.note_selection(
        "cid-no-trace", chat_id=CHAT_ID,
        payload={
            "counts": {"available_messages": 3, "included_messages": 2,
                       "window_messages": 4},
            "budget": {"slot": "direct.primary", "window": 8000,
                       "window_source": "model_capacity", "output_reserve": 500,
                       "available": 7000, "budget": 6000,
                       "policy_mode": "dynamic", "payload_tokens": 1200,
                       "fallback_window": None},
            "blocks": [{"kind": "global_tail", "role": "p1", "rendered": True,
                        "source_ids": ["msg:501"], "first_ts": 1700000001,
                        "last_ts": 1700000001, "tokens": 12}],
            "dropped": [{"reason_code": "budget_exceeded",
                         "kind": "global_middle", "count": 2}],
            "self_outputs": [{"source_id": "bot_output_tg:503",
                              "tg_message_id": 503, "ts": 1700000003}],
            "policy_version": "asap3-composer-1",
        })

    event = _event(events, turn_trace.EVENT_SELECTION)
    assert event.get("trace_id") == "cid-no-trace"
    payload = _payload(events, turn_trace.EVENT_SELECTION)
    assert payload["counts"]["window_messages"] == 4
    assert payload["budget"]["fallback_window"] is None
    assert payload["dropped"] == [{"reason_code": "budget_exceeded",
                                   "kind": "global_middle", "count": 2}]
    assert payload["self_outputs"][0]["tg_message_id"] == 503
    # трассы в памяти так и не появилось — событие не зависело от неё
    assert turn_trace.get("cid-no-trace") is None


# ════════════════════════════════════════════════════════════════════════════
# 2. UR-20.4/UR-20.8: аддитивные поля контекстного события
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_context_event_carries_source_reply_parent_and_clock_stages(
        monkeypatch, events):
    """`context_payload`: источник хода, родитель ответа, дата и РОВНО два
    пер-ходовых алиаса (не ростер), плюс стадии, реально получившие часы."""
    import datetime

    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=_rows(3))
    from tests.test_direct_chat import _message, _user as _chat_user
    parent = _message(text="вопрос родителя", message_id=400,
                      user=_chat_user(user_id=11, first_name="Петя",
                                      username="petya"))
    msg.reply_to_message = parent
    stamp = datetime.datetime(2026, 11, 10, 12, 0, 0,
                              tzinfo=datetime.timezone.utc)
    parent_stamp = datetime.datetime(2026, 11, 10, 11, 30, 0,
                                     tzinfo=datetime.timezone.utc)
    msg.date = stamp
    parent.date = parent_stamp
    await svc.handle(bot, msg, user)

    ctx = _payload(events, turn_trace.EVENT_CONTEXT)
    assert ctx["source_message_id"] == 4242
    assert ctx["source_author_id"] == 10
    assert ctx["reply_to_message_id"] == 400
    assert ctx["reply_to_author_id"] == 11
    assert ctx["source_message_ts"] == int(stamp.timestamp())
    # UR-20.4: время сообщения-родителя — иначе карточка показывала «в ответ
    # на: Петя (сообщение 400)» без даты.
    assert ctx["reply_to_message_ts"] == int(parent_stamp.timestamp())
    # алиасы — два значения на ход (полный ростер участников не пишется)
    alias_keys = {key for key in ctx if key.startswith("alias_")}
    assert alias_keys == {"alias_source_author", "alias_reply_parent"}
    assert ctx["alias_source_author"] == "Вася"
    assert ctx["alias_reply_parent"] == "Петя"
    assert "@" not in ctx["alias_source_author"]
    # стадии, реально получившие TimeContext (tool-фазы в этом ходе нет)
    assert ctx["clock_stages"] == ["l1", "l2"], ctx.get("clock_stages")


@pytest.mark.asyncio
async def test_reply_parent_without_date_adds_no_timestamp_field(
        monkeypatch, events):
    """Родитель без даты → поля нет вовсе (не `0` и не `None`-заглушка).

    «Честная пустота» §2: старая/двойниковая реплика без `date` не должна
    давать карточке выдуманное «01.01 00:00»."""
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=_rows(3))
    from tests.test_direct_chat import _message, _user as _chat_user
    parent = _message(text="вопрос родителя", message_id=401,
                      user=_chat_user(user_id=11, first_name="Петя"))
    parent.date = None
    msg.reply_to_message = parent
    await svc.handle(bot, msg, user)

    ctx = _payload(events, turn_trace.EVENT_CONTEXT)
    assert ctx["reply_to_message_id"] == 401
    assert "reply_to_message_ts" not in ctx, ctx.get("reply_to_message_ts")


def test_clock_stage_marks_are_canonical_and_deduplicated():
    """Порядок стадий фиксирован (l1→tool→l2), повторный маркер — не дубль."""
    turn_trace.begin("cid-clock", chat_id=CHAT_ID)
    turn_trace.note_clock_stage("cid-clock", "l2")
    turn_trace.note_clock_stage("cid-clock", "l1")
    turn_trace.note_clock_stage("cid-clock", "l2")
    turn_trace.note_clock_stage("cid-clock", "bogus")
    payload = turn_trace.get("cid-clock").context_payload()
    assert payload["clock_stages"] == ["l1", "l2"]


# ════════════════════════════════════════════════════════════════════════════
# 2b. UR-20.6: слот и модель ПЛАНИРОВАНИЯ L1 в контекстном событии
# ════════════════════════════════════════════════════════════════════════════

class _DedicatedLLM(_StagedLLM):
    """Транспорт выделенного L1-слота: план уходит через `llm._post`.

    `SlotBudgetMeta`/`L1ModelSlot` реальные — подменён только резолв слота
    и HTTP-мост, чтобы проверить, какое значение уезжает в трассу."""

    def __init__(self, *, plan=None):
        super().__init__(plan=plan)
        self.posts: list = []

    async def _post(self, path, payload, *, api_key=None, base_url=None, **kw):
        self.posts.append({"path": path, "payload": dict(payload),
                           "base_url": base_url, "api_key": api_key})
        return _FakeResponse({
            "choices": [{"message": {"content": self.l1_reply}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                      "total_tokens": 18}})


class _FakeResponse:
    """Мини-ответ провайдера для `dedicated_generate` (нужен только `.json`)."""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _dedicated_slot(monkeypatch, *, model="dedicated-l1-model"):
    from services import direct_l1 as _l1
    monkeypatch.setattr(
        _l1, "resolve_l1_model",
        lambda chat_id=None, **kw: _l1.L1ModelSlot(
            base_url="https://l1.example", model=model, api_key="k",
            dedicated=True, source="l1"))


@pytest.mark.asyncio
async def test_l1_event_records_main_slot_when_main_model_plans(
        monkeypatch, events):
    """UR-20.6: ход, планированный основной моделью, пишет слот `main`.

    Раньше слот вообще не попадал в событие — карточка на КАЖДОМ ходу
    писала «слот не зафиксирован», хотя `SlotBudgetMeta.slot` известен ДО
    планирования."""
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=_rows(3))
    await svc.handle(bot, msg, user)

    ctx = _payload(events, turn_trace.EVENT_CONTEXT)
    assert ctx["l1"]["slot"] == "main", ctx["l1"]
    # Модель main-пути — та, которой клиент реально отвечает.
    assert ctx["l1"]["model"] == "chat-model-x", ctx["l1"]


@pytest.mark.asyncio
async def test_l1_event_records_dedicated_slot_and_its_model(
        monkeypatch, events):
    """UR-20.6: ход на выделенном слоте L1 пишет `l1_slot` и его модель.

    Модель берётся из фактически отправленного payload'а слота: иначе
    карточка показывала бы модель основной ветки для хода, который
    планировала выделенная."""
    _dedicated_slot(monkeypatch)
    llm = _DedicatedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_rows(3))
    await svc.handle(bot, msg, user)

    ctx = _payload(events, turn_trace.EVENT_CONTEXT)
    assert ctx["l1"]["slot"] == "l1_slot", ctx["l1"]
    assert ctx["l1"]["model"] == "dedicated-l1-model", ctx["l1"]
    # Никакой догадки: именно эта модель ушла в запрос выделенного слота.
    assert llm.posts, "выделенный слот не вызывался"
    assert llm.posts[0]["payload"]["model"] == ctx["l1"]["model"]
    assert llm.posts[0]["base_url"] == "https://l1.example"


def test_trace_written_before_this_change_has_no_invented_slot(events):
    """Старая трасса/старый продюсер: слота нет — `main` НЕ выдумывается.

    Именно пустое значение (а не подставленный `main`) даёт карточке право
    честно сказать «слот не зафиксирован»."""
    turn_trace.begin("cid-old-l1", chat_id=CHAT_ID)
    turn_trace.note_l1("cid-old-l1", action="reply", model="test-model")
    payload = turn_trace.get("cid-old-l1").context_payload()
    assert payload["l1"]["slot"] == "", payload["l1"]
    assert payload["l1"]["model"] == "test-model"


def test_l1_slot_is_validated_as_a_code():
    """Слот — код: свободный текст в поле не пропускается (общий enum-путь)."""
    turn_trace.begin("cid-bad-slot", chat_id=CHAT_ID)
    turn_trace.note_l1("cid-bad-slot", action="reply", model="test-model",
                       slot="выделенный слот планировщика")
    payload = turn_trace.get("cid-bad-slot").context_payload()
    assert payload["l1"]["slot"] == ""


# ════════════════════════════════════════════════════════════════════════════
# 3. Жёсткие лимиты списков: усечение видно, а не молчаливая потеря
# ════════════════════════════════════════════════════════════════════════════

def _oversized_selection(*, ids_per_block: int = 12,
                         minimal_blocks: bool = False) -> dict:
    if minimal_blocks:
        blocks = [{"kind": "k%d" % i, "role": "p1", "rendered": True}
                  for i in range(25)]
        dropped = [{"reason_code": "budget_exceeded", "kind": "k",
                    "count": 1}]
        self_outputs = [{"source_id": "bot_output_tg:1",
                         "tg_message_id": 1, "ts": 1700000000}]
    else:
        blocks = [{"kind": "k%d" % i, "role": "p1", "rendered": True,
                   "source_ids": ["msg:%d" % (i * 100 + n)
                                  for n in range(ids_per_block)],
                   "first_ts": 1700000000 + i, "last_ts": 1700000000 + i,
                   "tokens": 10} for i in range(25)]
        dropped = [{"reason_code": "budget_exceeded",
                    "kind": "kind%d" % (i % 3), "count": 1} for i in range(20)]
        self_outputs = [{"source_id": "bot_output_tg:%d" % i,
                         "tg_message_id": i, "ts": 1700000000 + i}
                        for i in range(9)]
    return {
        "counts": {"available_messages": 25, "included_messages": 25,
                   "window_messages": 25},
        "budget": {"slot": "direct.primary", "window": 8000,
                   "window_source": "model_capacity", "output_reserve": 500,
                   "available": 7000, "budget": 6000,
                   "policy_mode": "dynamic", "payload_tokens": 1200,
                   "fallback_window": None},
        "blocks": blocks,
        "dropped": dropped,
        "self_outputs": self_outputs,
        "policy_version": "asap3-composer-1",
    }


def test_selection_list_limits_are_enforced_not_silently_dropped(events):
    """Переполнение режется ДЕТЕРМИНИРОВАННО и ВИДИМО.

    Литералы лимитов закреплены здесь числами (16 блоков, 8 id, 8 строк
    потерянного, 6 своих реплик): дрейф констант в модуле не пройдёт зелёным.
    Срабатывание любого лимита ставит `truncated: true`, а потери сохраняют
    честный итог (`dropped_total`), а не «сколько строк осталось»."""
    blocks_max, ids_max = 16, 8
    dropped_max, self_max = 8, 6

    # 1) кап блоков: 25 → 16, порядок сохранён, усечение помечено
    turn_trace.note_selection("cid-cap", chat_id=CHAT_ID,
                              payload=_oversized_selection(minimal_blocks=True))
    compact = _payload_of(events, turn_trace.EVENT_SELECTION, "cid-cap")
    compact_blocks = compact.get("blocks") or []
    assert len(compact_blocks) == blocks_max
    assert [b["kind"] for b in compact_blocks] == \
        ["k%d" % i for i in range(blocks_max)]
    assert compact.get("truncated") is True, \
        "кап блоков сработал — это обязано быть видно (не молчаливая потеря)"

    # 2) блоки с 12 id: id → 8, объём режется блоками С КОНЦА
    turn_trace.note_selection("cid-fat", chat_id=CHAT_ID,
                              payload=_oversized_selection())
    fat = _payload_of(events, turn_trace.EVENT_SELECTION, "cid-fat")
    fat_blocks = fat.get("blocks") or []
    assert isinstance(fat_blocks, list), "блоки обязаны остаться списком"
    assert 0 < len(fat_blocks) <= blocks_max
    assert fat.get("truncated") is True
    assert [b["kind"] for b in fat_blocks] == \
        ["k%d" % i for i in range(len(fat_blocks))]
    assert all(len(b.get("source_ids") or ()) <= ids_max for b in fat_blocks)
    assert all(len(b["source_ids"]) == ids_max for b in fat_blocks)
    assert len(fat.get("dropped") or ()) <= dropped_max
    assert len(fat.get("self_outputs") or ()) <= self_max

    # 3) потери: строки ≤8, но ИТОГ честный (усечение строк не теряет счёт)
    many_groups = {
        "dropped": [{"reason_code": "budget_exceeded", "kind": "k%d" % i,
                     "count": 1} for i in range(12)],
        "policy_version": "asap3-composer-1",
    }
    dropped_only = turn_trace._selection_payload(many_groups)
    assert len(dropped_only["dropped"]) == dropped_max, "12 групп → 8 строк"
    assert dropped_only.get("truncated") is True
    assert dropped_only.get("dropped_total") == 12, \
        "«12 → 8» не должно читаться как «потеряно 8»"
    assert sum(row["count"] for row in dropped_only["dropped"]) == 8

    # 4) агрегат по (причина, блок) не теряет счётчики и не ставит флаг зря
    aggregate_src = _oversized_selection()
    aggregate_src["blocks"] = []      # без блоков payload влезает целиком
    clean = turn_trace._selection_payload(aggregate_src)
    assert len(clean["dropped"]) == 3, "группы (причина, kind), а не записи"
    assert sum(row["count"] for row in clean["dropped"]) == 20
    assert "dropped_total" not in clean, "строки покрывают всё — итог не нужен"
    assert len(clean["self_outputs"]) == self_max
    assert clean.get("truncated") is True, "9 своих реплик → 6 (кап сработал)"


def _plain_rows(count, *, start=1):
    """Строки окна БЕЗ реплик бота (для счётчиков «вошло/доступно»)."""
    return [{
        "id": i, "tg_message_id": 600 + i, "user_id": 10,
        "author_name": "Вася", "text": "строка окна %d" % i,
        "timestamp": 1_700_000_000 + i, "reply_to_id": None,
        "media_type": "text",
    } for i in range(start, start + count)]


@pytest.mark.asyncio
async def test_real_turn_counts_entered_messages_not_capped_ids(
        monkeypatch, events):
    """РЕАЛЬНЫЙ ход с окном 25 сообщений: `included_messages` == 25.

    Регресс, который поймал ревьюер: счётчик считался по УЖЕ срезанным до 8
    `source_ids`, поэтому Inspector утверждал «вошло 8» при 25 реально
    вошедших сообщениях (противоречие UR-20.4 по смыслу). Срез списка ссылок
    обязан быть видимым (`truncated`), но не менять счётчик."""
    rows = _plain_rows(25)

    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=rows)
    await svc.handle(bot, msg, user)

    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    assert counts.get("window_messages") == 25
    assert counts.get("included_messages") == 25, \
        "счётчик обязан считать ВОШЕДШИЕ сообщения, а не срез ссылок"
    assert counts.get("available_messages") == 25

    tail = next(b for b in payload["blocks"] if b.get("kind") == "global_tail")
    assert len(tail["source_ids"]) == 8, "контрактный размер списка — 8"
    assert payload.get("truncated") is True, \
        "срез 25 → 8 обязан быть видимым, а не молчаливым"


@pytest.mark.asyncio
async def test_real_turn_window_40_counts_all_messages(monkeypatch, events):
    """Окно 40: `included_messages` == 40 — больше 32.

    Специально перешагивает «32» (лимит id, который сборщик передаёт в
    трассу): если счётчик снова начнёт читать срезанный список, тест упадёт
    (32 ≠ 40), тогда как окно 25 такую регрессию не заметило бы."""
    rows = _plain_rows(40)

    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=rows)
    await svc.handle(bot, msg, user)

    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    assert counts.get("window_messages") == 40
    assert counts.get("available_messages") == 40
    assert counts.get("included_messages") == 40, \
        "счётчик обязан считать все вошедшие сообщения (срез 32 — не предел)"
    tail = next(b for b in payload["blocks"] if b.get("kind") == "global_tail")
    assert len(tail["source_ids"]) == 8
    assert payload.get("truncated") is True


@pytest.mark.asyncio
async def test_real_turn_memory_facts_do_not_inflate_message_count(
        monkeypatch, events):
    """Факты памяти — НЕ сообщения: 25 сообщений + 5 фактов → `{25, 25}`.

    Прежний счётчик складывал `fact:…` в «вошло», и шаг 3 показал бы
    невозможное «доступно 25 · вошло 30» (UR-20.4 по смыслу ломается)."""
    facts = [{"id": i, "item_id": "fact:%d" % i, "origin": "user_memory",
              "fact": "факт про дрожжи %d" % i, "rag_ts": 1_700_000_000 + i,
              "status": "confirmed", "subject_ref_id": 1,
              "speaker_author_id": 1} for i in range(1, 6)]
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=_plain_rows(25),
                                 facts=facts)
    await svc.handle(bot, msg, user)

    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    rag = next(b for b in payload["blocks"] if b.get("kind") == "rag")
    assert len(rag["source_ids"]) == 5, "факты памяти не попали в блок"
    assert all(ref.startswith("fact:") for ref in rag["source_ids"])

    assert counts.get("available_messages") == 25
    assert counts.get("included_messages") == 25, \
        "факты памяти не должны попадать в счётчик СООБЩЕНИЙ"
    assert counts["included_messages"] <= counts["available_messages"], \
        "«вошло больше, чем доступно» — невозможное состояние"


@pytest.mark.asyncio
@pytest.mark.parametrize("rows_count", [36, 40])
async def test_episode_span_longer_than_32_counts_all_messages(
        monkeypatch, rows_count):
    """Спан эпизода длиннее 32 считается ЦЕЛИКОМ (36 и 40 строк).

    `CHAT_EPISODE_MAX_MESSAGES` = 40, поэтому спан реально бывает > 32: срез
    32 при построении спана терял бы 4 сообщения в счётчике."""
    from services import mca_gates
    from services import direct_chat_service as dcs
    from tests.test_vmq_mem_retrieval_fixes import (
        CHAT_ID as VMQ_CHAT_ID, _make_db, _seed_message, _service, _ts)

    monkeypatch.setattr(mca_gates, "retrieval_context_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "episodes_compiler_facade_enabled",
                        lambda: False)
    db = await _make_db()
    try:
        for i in range(rows_count):
            await _seed_message(db, "дроны над дачей раз %d" % i,
                                _ts(2023, 5, 1) + i * 60, tg_id=9000 + i)
        block, stats = await _service(db)._build_old_episodes(
            VMQ_CHAT_ID, "расскажи историю про дроны", [], {})
    finally:
        await db.close()

    assert block.startswith("<Old_Episode>")
    assert stats["count"] == 1 and stats["messages"] == rows_count
    spans = stats["spans"]
    assert len(spans) == 1, spans
    assert len(spans[0]["source_ids"]) == rows_count, \
        "спан %d строк: срез 32 не должен терять сообщения" % rows_count
    assert spans[0]["first_ts"] and spans[0]["last_ts"]
    # и это ровно тот набор, по которому считается included_messages
    assert dcs._MESSAGE_BLOCK_KINDS and "episode" in dcs._MESSAGE_BLOCK_KINDS


@pytest.mark.asyncio
async def test_real_turn_within_cap_counts_equal_and_not_truncated(
        monkeypatch, events):
    """Ход в пределах капа: `included_messages` == числу вошедших, флага нет."""
    rows = _plain_rows(4)

    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=rows)
    await svc.handle(bot, msg, user)

    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    assert counts.get("window_messages") == 4
    assert counts.get("included_messages") == 4
    assert counts.get("included_messages") == counts.get("available_messages")

    tail = next(b for b in payload["blocks"] if b.get("kind") == "global_tail")
    assert len(tail["source_ids"]) == 4
    assert "truncated" not in payload


def _block_text(payload_text: str, tag: str) -> str:
    """Тело блока `<tag>…</tag>` из РЕАЛЬНОГО payload запроса."""
    start = payload_text.find("<%s>" % tag)
    end = payload_text.find("</%s>" % tag)
    if start < 0 or end < 0:
        return ""
    return payload_text[start + len(tag) + 2:end]


def _payload_row_keys(llm) -> set:
    """Сколько РАЗНЫХ сообщений реально лежит в запросе к модели.

    Считается по фактическому payload (`<Global_Context>` + ветка): ключ
    строки (`tg:`/`msg:`) биективен сообщению — это и есть «строки, которые
    реально доехали», независимо от того, что думает счётчик."""
    text = "\n".join(str(m.get("content") or "") for m in (llm.last or ()))
    keys: set = set()
    for tag in ("Global_Context", "Conversation_Thread",
                "Old_Episode"):
        body = _block_text(text, tag)
        for line in body.split("\n"):
            key = direct_chat_service._context_line_dedup_key(line)
            if key:
                keys.add(key)
    return keys


def _chain_items(count, *, item_id_base=700, chars=0, start=1):
    from services.thread_chain import ChainItem
    return [ChainItem(uid=10, name="Вася", is_bot=False,
                      text=("звено %d " % i) + ("текст " * (chars // 6)),
                      ts=1_700_000_000 + i,
                      item_id="tg:%d" % (item_id_base + i))
            for i in range(start, start + count)]


@pytest.mark.asyncio
async def test_thread_compressed_by_allocator_counts_only_rows_in_request(
        monkeypatch, events):
    """РЕПРО P: длинная ветка сжата аллокатором — «вошло» = строки в запросе.

    Прежний счётчик брал ВСЕ звенья цепочки, хотя в payload после сжатия
    остаётся часть строк: событие объявляло «вошло 40» при 20 реальных, а
    `dropped` был пуст. Теперь ids/даты/«вошло» считаются по выжившим строкам
    (та же техника, что у tail/middle), а вырезанное названо причиной."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3),
                                 model_window=16384)
    long_chain = _chain_items(40, chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return long_chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    rows_in_request = _payload_row_keys(llm)
    assert len(rows_in_request) < 40, "ветка должна была сжаться — иначе репро пустое"

    assert counts.get("included_messages") == len(rows_in_request), \
        "«вошло» обязано равняться строкам, реально лежащим в запросе"
    # пул «доступно» = объединение (3 хвоста + 40 звеньев), без дублей
    assert counts.get("available_messages") == 43, counts

    dropped = payload.get("dropped") or []
    thread_dropped = [row for row in dropped if row.get("kind") == "thread"]
    assert thread_dropped, "срез ветки обязан быть назван в dropped"
    assert thread_dropped[0]["reason_code"], "у потери должна быть причина"
    assert thread_dropped[0]["count"] >= 1

    thread_block = next(b for b in payload["blocks"]
                        if b.get("kind") == "thread")
    assert len(thread_block["source_ids"]) == 8
    assert payload.get("truncated") is True


@pytest.mark.asyncio
async def test_available_is_union_of_pools_not_their_sum(monkeypatch, events):
    """РЕПРО H2: одни и те же сообщения в хвосте, ветке и эпизоде.

    `available_messages` — размер ОБЪЕДИНЕНИЯ пулов: 13 различных сообщений,
    а не 13+13+13=39 (прежняя сумма давала физически невозможное «доступно
    больше, чем существует»)."""
    rows = _plain_rows(13)                       # tg 601..613
    ids = ["msg:%d" % row["tg_message_id"] for row in rows]
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=rows)

    async def _fake_chain(chat_id, message, depth=None):
        return _chain_items(13, item_id_base=600)   # те же tg 601..613

    async def _fake_episodes(chat_id, query, tail_rows, suffix_map,
                            history_sample=None, projection=None):
        return "", {"count": 1, "messages": 13, "tokens": 50, "hits": 1,
                    "spans": [{"source_ids": list(ids),
                               "first_ts": 1_700_000_001,
                               "last_ts": 1_700_000_013}]}

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    monkeypatch.setattr(svc, "_build_old_episodes", _fake_episodes)
    await svc.handle(bot, msg, user)

    counts = _payload(events, turn_trace.EVENT_SELECTION).get("counts") or {}
    assert counts.get("available_messages") == 13, \
        "доступно = объединение пулов (13), а не сумма (39)"
    assert counts.get("included_messages") == 13
    assert counts["included_messages"] <= counts["available_messages"]


@pytest.mark.asyncio
async def test_one_quoted_thread_item_emits_single_delivery_event(
        monkeypatch, events):
    """РЕГРЕСС шага 1: измерение выживших звеньев НЕ перерендеривает строку.

    Счётчики считают выживание по строкам piece'а, но ключ строки нельзя
    добывать повторным `_chain_line`: у рендера есть побочный эффект
    (EVOL-015, «render = delivery») — событие `quote_delivered_to_context`.
    Второй вызов ради измерения объявлял одну и ту же цитату доставленной
    ДВАЖДЫ (репро ревью: 1 событие на базе → 2 на шаге 1).

    Проверяется фактическая телеметрия одного хода: ровно одно событие
    доставки, с id именно цитирующего звена, при том что звено реально
    посчитано вошедшим (измерение работает, а не отключено)."""
    from services.thread_chain import ChainItem

    quoted = ChainItem(uid=11, name="Петя", is_bot=False,
                       text="реплика с цитатой", ts=1_700_000_003,
                       item_id="tg:703", quote_text="выделенный фрагмент",
                       quote_author_id=10, quote_position=0,
                       quote_is_manual=1, quote_original_available=True)
    chain = [quoted] + _chain_items(2, item_id_base=700)

    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    delivered = [e for e in events
                 if e.get("event_name") == "quote"
                 and e.get("stage") == "quote_delivered_to_context"]
    assert len(delivered) == 1, \
        "одна цитата в ветке — ровно одно событие доставки, а не %d" % \
        len(delivered)
    assert delivered[0].get("message_id") == 703, delivered[0]
    assert delivered[0].get("component") == "context"

    # …и это измерение, а не отказ от него: звено посчитано вошедшим.
    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    assert counts.get("included_messages") == 6, counts       # 3 окна + 3 ветки
    assert counts.get("available_messages") == 6, counts
    thread_block = next(b for b in payload["blocks"]
                        if b.get("kind") == "thread")
    assert "msg:703" in thread_block["source_ids"], thread_block


QUOTED_DROP_SENTINEL = "QUOTED_DROP_SENTINEL_URF"


def _quoted_chain(count, *, quoted_item_id, chars=0):
    """Цепочка, у одного звена — цитата с маркером (иначе — обычные звенья)."""
    return [item._replace(quote_text=QUOTED_DROP_SENTINEL + " фрагмент",
                          quote_author_id=10, quote_position=0,
                          quote_is_manual=1, quote_original_available=True)
            if item.item_id == quoted_item_id else item
            for item in _chain_items(count, chars=chars)]


@pytest.mark.asyncio
async def test_evicted_quoted_thread_line_reports_no_delivery(
        monkeypatch, events):
    """Событие цитаты — о ДОСТАВКЕ, а не о рендере: вытесненная строка молчит.

    Рендер ветки идёт ДО аллокации. В сжатой ветке из 40 звеньев самое старое
    звено (`tg:740`, несущее цитату) в payload не попадает: модель цитаты не
    видит — значит `quote_delivered_to_context` не должно быть вовсе. Раньше
    событие эмитилось на рендере, и телеметрия объявляла доставленной цитату,
    которой в запросе нет (репро ревью)."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3),
                                 model_window=16384)
    chain = _quoted_chain(40, quoted_item_id="tg:740", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    # precondition: цитаты в payload НЕТ (иначе тест ничего не проверяет)
    payload_text = "\n".join(str(m.get("content") or "")
                             for m in (llm.last or ()))
    assert QUOTED_DROP_SENTINEL not in payload_text, \
        "звено должно было вытесниться — иначе репро пустое"

    delivered = [e for e in events
                 if e.get("event_name") == "quote"
                 and e.get("stage") == "quote_delivered_to_context"]
    assert delivered == [], \
        "цитаты в запросе нет — событий доставки быть не должно: %r" % \
        [e.get("message_id") for e in delivered]

    # счётчики шага 1 не изменились (тот же ход, что в репро P)
    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    assert counts.get("available_messages") == 43, counts
    assert counts.get("included_messages") == len(_payload_row_keys(llm))
    assert counts.get("included_messages") == 23, counts
    thread_dropped = [row for row in (payload.get("dropped") or [])
                      if row.get("kind") == "thread"]
    assert thread_dropped and thread_dropped[0]["count"] == 20, \
        payload.get("dropped")


@pytest.mark.asyncio
async def test_surviving_quote_in_compressed_thread_reports_one_delivery(
        monkeypatch, events):
    """Тот же сжатый ход, но цитата в СВЕЖЕМ звене: ровно одно событие.

    Контроль к предыдущему тесту: отличие только в том, какое звено цитирует,
    поэтому «0 событий» там означает «не доставлено», а не «сломан эмиттер».
    Цитата на самом деле лежит в payload."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    payload_text = "\n".join(str(m.get("content") or "")
                             for m in (llm.last or ()))
    assert QUOTED_DROP_SENTINEL in payload_text, \
        "свежее звено обязано остаться в payload — иначе тест пустой"

    delivered = [e for e in events
                 if e.get("event_name") == "quote"
                 and e.get("stage") == "quote_delivered_to_context"]
    assert len(delivered) == 1, \
        "одна доставленная цитата — ровно одно событие, а не %d" % \
        len(delivered)
    assert delivered[0].get("message_id") == 701, delivered[0]


@pytest.mark.asyncio
async def test_quote_in_branch_and_thread_reports_one_delivery(
        monkeypatch, events):
    """Цитата видна и в `<Conversation_Branch>`, и в треде — событие ОДНО.

    Reply-триггер рендерит свежие звенья дважды (ветка P0 + тред), поэтому
    проверка доставки обязана дедуплицировать: две копии одной цитаты в
    payload — это одна доставленная цитата."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    parent = _reply_parent()
    msg.reply_to_message = parent
    chain = _quoted_chain(3, quoted_item_id="tg:701")

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    payload_text = "\n".join(str(m.get("content") or "")
                             for m in (llm.last or ()))
    assert "<Conversation_Branch>" in payload_text, \
        "нужен reply-триггер: ветка рендерится в payload"
    assert QUOTED_DROP_SENTINEL in payload_text

    delivered = [e for e in events
                 if e.get("event_name") == "quote"
                 and e.get("stage") == "quote_delivered_to_context"]
    assert len(delivered) == 1, \
        "одна цитата в двух блоках — одно событие, а не %d" % len(delivered)
    assert delivered[0].get("message_id") == 701, delivered[0]


def _reply_parent():
    from tests.test_direct_chat import _message, _user
    return _message(text="вопрос родителя", message_id=400,
                    user=_user(user_id=11, first_name="Петя"))


def _same_quote(chain, *, source_id, target_id):
    """Цитата звена `source_id` — ещё и звену `target_id` (ПОЛНАЯ копия:
    текст и метаданные совпадают)."""
    source = next(it for it in chain if it.item_id == source_id)
    fields = {name: getattr(source, name) for name in
              ("quote_text", "quote_author_id", "quote_position",
               "quote_is_manual", "quote_original_available")}
    return [it._replace(**fields) if it.item_id == target_id else it
            for it in chain]


def _payload_text(llm) -> str:
    return "\n".join(str(m.get("content") or "") for m in (llm.last or ()))


def _delivered_ids(seen) -> list:
    return [e.get("message_id") for e in seen
            if e.get("event_name") == "quote"
            and e.get("stage") == "quote_delivered_to_context"]


def _degrade_allocator(monkeypatch, *, budget):
    """Деградация аллокатора: `allocate_budget` падает, payload собирает
    legacy-бюджет с жёстким капом `budget` (ветка репро ревью)."""
    from services import budget_gate, chat_params

    def _boom(*args, **kwargs):
        raise RuntimeError("allocator down")

    async def _budgets_enabled(chat_id):
        return True

    async def _get_chat_param(chat_id, key, default=None):
        if key == "limits.chat_context_budget_tokens":
            return budget
        if key == "flags.chat_context_budgets_enabled":
            return True
        return default

    monkeypatch.setattr(direct_chat_service._composer, "allocate_budget",
                        _boom)
    monkeypatch.setattr(budget_gate, "budgets_enabled", _budgets_enabled)
    monkeypatch.setattr(chat_params, "get_chat_param", _get_chat_param)


@pytest.mark.asyncio
async def test_identical_quotes_credit_only_the_surviving_item(
        monkeypatch, events):
    """Одинаковый текст цитаты у ДВУХ звеньев: событие — только за выжившее.

    РЕПРО ревью: `tg:701` и `tg:740` несут одну и ту же цитату (текст и
    метаданные совпадают). Аллокатор оставляет в payload ровно одну
    аннотацию — звена `tg:701`; звено `tg:740` вытеснено вместе со своей
    строкой. Проверка «фрагмент встречается в общем тексте ветки» засчитывала
    это выживание ОБОИМ звеньям (`[701, 740]`): доставку одного хода
    приписывали другому. Атрибуция обязана идти по тождеству звена.

    Тест падает, если атрибуция снова начнёт опираться на совпадение текста
    (проверено мутацией): в payload одна аннотация, событий тоже одно."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3),
                                 model_window=16384)
    chain = _same_quote(_quoted_chain(40, quoted_item_id="tg:740", chars=800),
                        source_id="tg:740", target_id="tg:701")

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    blob = _payload_text(llm)
    # предусловия репро: аннотация в payload ровно одна, и она — выжившего
    # звена (текст `tg:701` в запросе, текст `tg:740` — нет)
    assert blob.count(QUOTED_DROP_SENTINEL) == 1, \
        "в payload обязана остаться ровно одна такая аннотация"
    assert "звено 1 " in blob, "свежее звено обязано остаться в payload"
    assert "звено 40 " not in blob, \
        "цитирующее звено должно было вытесниться — иначе репро пустое"
    quote_line = next(ln for ln in blob.split("\n")
                      if QUOTED_DROP_SENTINEL in ln)
    assert "звено 1 " in quote_line, \
        "аннотация обязана стоять в СТРОКЕ выжившего звена: %r" % \
        quote_line[:160]

    assert _delivered_ids(events) == [701], \
        "событие обязано быть одно и только за выжившее звено: %r" % \
        _delivered_ids(events)

    # счётчики шага 1 не поехали: «вошло» = строки, реально лежащие в запросе
    payload = _payload(events, turn_trace.EVENT_SELECTION)
    counts = payload.get("counts") or {}
    assert counts.get("available_messages") == 43, counts
    assert counts.get("included_messages") == len(_payload_row_keys(llm)), counts


@pytest.mark.asyncio
async def test_quote_on_cut_header_line_still_reports_delivery(
        monkeypatch, events):
    """Заголовок строки срезан, но текст цитаты доехал — событие ОДНО.

    Усечение ветки держит весь текст как хвост тела и отдельно сохраняет
    заголовок ПЕРВОЙ строки. Поэтому граница среза приходится ВНУТРЬ тела
    одной из строк: её заголовок срезан, а хвост с аннотацией цитаты в
    payload остался (`tg:720`, репро ревью). Доставка определяется позицией
    аннотации в собственной строке, а не наличием заголовка, — иначе такой
    ход молчал бы о реально доставленной цитате."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3),
                                 model_window=16384)
    chain = _quoted_chain(40, quoted_item_id="tg:720", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    blob = _payload_text(llm)
    assert blob.count(QUOTED_DROP_SENTINEL) == 1, "цитата должна быть в payload"
    quote_line = next(ln for ln in blob.split("\n")
                      if QUOTED_DROP_SENTINEL in ln)
    # предусловие: голова СВОЕЙ строки хода срезана вместе с заголовком —
    # аннотация доехала «приклеенной» к заголовку другого звена
    assert "звено 20 " not in quote_line, \
        "предусловие: начало собственной строки обязано быть срезано: %r" % \
        quote_line[:120]
    assert quote_line.lstrip().startswith("["), \
        "предусловие: выживший хвост стоит при заголовке другой строки: %r" % \
        quote_line[:120]

    assert _delivered_ids(events) == [720], \
        "доставленная цитата = одно событие: %r" % _delivered_ids(events)


@pytest.mark.asyncio
async def test_raw_view_keeps_identity_attribution(monkeypatch, events):
    """Сырой вид (речевая проекция OFF): та же атрибуция по тождеству.

    Рубильник меняет только представление (`tg:`-ref'ы вместо меток прогона),
    а не то, ЧЬЯ цитата доехала: две одинаковые цитаты, одно выжившее звено —
    одно событие, и в payload остаются сырые ref'ы."""
    monkeypatch.setattr(direct_chat_service, "speech_projection_enabled",
                        lambda: False)
    monkeypatch.setattr(thread_chain, "speech_projection_enabled",
                        lambda: False)
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3),
                                 model_window=16384)
    chain = _same_quote(_quoted_chain(40, quoted_item_id="tg:740", chars=800),
                        source_id="tg:740", target_id="tg:701")

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    blob = _payload_text(llm)
    assert "| tg:701]" in blob, "сырой вид обязан оставить tg:-ref'ы"
    assert "| M" not in blob, "меток прогона в сыром виде быть не должно"
    assert blob.count(QUOTED_DROP_SENTINEL) == 1

    assert _delivered_ids(events) == [701], \
        "в сыром виде событие тоже только за выжившее звено: %r" % \
        _delivered_ids(events)


@pytest.mark.asyncio
async def test_allocator_failure_with_tight_budget_credits_no_quote(
        monkeypatch, events):
    """Аллокатор упал → payload собрал legacy-бюджет: цитаты нет — событий нет.

    РЕПРО ревью (деградация): `_composer.allocate_budget` бросает, payload
    собирается legacy-бюджетом, и вытесненное звено `tg:740` в запросе
    отсутствует. Прежняя ветка «аллокатора нет» засчитывала доставку ВСЕМ
    цитирующим звеням по факту рендера (`[740]`), хотя модель цитаты не
    видела. Решение обязано считаться по ФИНАЛЬНОМУ тексту и на этом пути, а
    эмиссия — стоять там, где финальный payload уже известен.

    Тест падает, если вернуть зачёт «по умолчанию» на деградации (проверено
    мутацией)."""
    _degrade_allocator(monkeypatch, budget=1500)
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    chain = _quoted_chain(40, quoted_item_id="tg:740", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    blob = _payload_text(llm)
    # ответ реально собран и отправлен на формулировку (путь деградации живой)
    assert blob.strip(), "деградация не должна ломать ответ"
    assert "<Current_Question>" in blob, "payload хода не собран"
    # предусловие репро: цитаты в финальном запросе НЕТ
    assert QUOTED_DROP_SENTINEL not in blob, \
        "цитирующее звено должно было вытесниться — иначе репро пустое"

    assert _delivered_ids(events) == [], \
        "цитаты в запросе нет — событий доставки быть не должно: %r" % \
        _delivered_ids(events)


@pytest.mark.asyncio
async def test_allocator_failure_credits_surviving_quote(monkeypatch, events):
    """Тот же путь деградации, но цитата выжила: ровно одно событие.

    Контроль к предыдущему тесту: отличие только в том, какое звено цитирует.
    Значит «0 событий» там — это «не доставлено», а не «эмиттер отключён»."""
    _degrade_allocator(monkeypatch, budget=1500)
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    blob = _payload_text(llm)
    assert blob.strip() and "<Current_Question>" in blob
    assert blob.count(QUOTED_DROP_SENTINEL) == 1, \
        "свежее звено обязано остаться в payload — иначе контроль пустой"

    assert _delivered_ids(events) == [701], \
        "доставленная цитата = одно событие: %r" % _delivered_ids(events)


@pytest.mark.asyncio
async def test_unused_context_emits_no_quote_events(events):
    """Нет receipt — нет снимка: событий доставки не бывает.

    Сборка контекста (`PreparedTurnPayload`) событий не даёт вовсе; снимок
    печатается только по успешному receipt с фактическим `sent_body`.
    Второй блок — контроль: тот же prepared + receipt даёт ровно одно
    событие цитаты и одно событие выбора."""
    from services.thread_chain import ChainItem

    item = ChainItem(uid=10, name="Вася", is_bot=False, text="реплика",
                     ts=1_700_000_001, item_id="tg:777",
                     quote_text="выделенный фрагмент", quote_author_id=11,
                     quote_position=0, quote_is_manual=1,
                     quote_original_available=True)
    line = thread_chain.format_chain_line(item, {}, emit_quote=False)
    block = ("<Conversation_Thread>\n"
             f"{direct_chat_service.escape_xml_text(line)}\n"
             "</Conversation_Thread>")
    prepared = direct_chat_service._prepared_turn_payload(
        chat_id=CHAT_ID, correlation_id="cid-unused",
        blocks=[("thread", block)], event_blocks=[],
        available_item_ids={"tg:777"}, window_messages=1, budget={},
        dropped=(), self_outputs=(),
        chain_rendered={"thread": [(item.item_id, line,
                                    thread_chain.quote_delivery_fragment(
                                        item, None, None))]},
        projection=None)

    # 1) receipt нет → снимка нет → событий нет
    idle = direct_chat_service._settle_delivered_turn(None, prepared, None)
    direct_chat_service._project_delivered_turn(idle, None)
    assert idle is None
    assert _delivered_ids(events) == []
    assert not [e for e in events
                if e.get("event_name") == turn_trace.EVENT_SELECTION]

    # 2) контроль: успешный receipt с тем же телом → снимок и одно событие
    receipt = direct_chat_service.SuccessfulOutboundReceipt(
        path="l2_writer",
        sent_body={"messages": [{"role": "user", "content": block}]})
    snapshot = direct_chat_service._settle_delivered_turn(
        receipt, prepared, None)
    assert snapshot is not None
    direct_chat_service._project_delivered_turn(snapshot, None)
    assert _delivered_ids(events) == [777]
    assert snapshot.counts["included_messages"] == 1


@pytest.mark.asyncio
async def test_cancel_before_final_model_call_emits_no_quote_event(
        monkeypatch, events):
    """Отмена ДО финального вызова модели: контекст провайдеру не ушёл → 0.

    Репро ревью: `used` выставлялся сразу после `build_messages`, то есть до
    фактического вызова модели. Ход, отменённый (или упавший) между сборкой
    payload и финальным вызовом, не делал НИ ОДНОГО вызова провайдера с
    контекстом, но успевал записать «цитата доставлена». Теперь `used`
    поднимается только ПОСЛЕ возврата финального вызова, поэтому отмена до
    него событий не даёт."""
    import asyncio as _asyncio

    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    async def _cancelled(*args, **kwargs):
        raise _asyncio.CancelledError()

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    # финальный вызов модели (`l2_writer`) не состоялся — отмена до него
    monkeypatch.setattr(svc, "_l2_write_answer", _cancelled)

    with pytest.raises(_asyncio.CancelledError):
        await svc.handle(bot, msg, user)

    assert "l2_writer" not in llm.calls, \
        "финального вызова модели быть не должно: %r" % (llm.calls,)
    assert _delivered_ids(events) == [], \
        "контекст не уходил провайдеру — событий доставки нет: %r" % \
        _delivered_ids(events)


@pytest.mark.asyncio
async def test_telegram_failure_after_model_call_keeps_quote_event(
        monkeypatch, events):
    """Сбой доставки в Telegram ПОСЛЕ вызова модели: событие остаётся.

    Событие описывает доставку в КОНТЕКСТ модели, а не получение ответа
    пользователем: модель цитату увидела, значит `quote_delivered_to_context`
    обязан быть, даже если отправка в чат упала."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    async def _send_fails(*args, **kwargs):
        raise RuntimeError("telegram send failed")

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    monkeypatch.setattr(svc, "_send_direct_answer", _send_fails)
    await svc.handle(bot, msg, user)

    assert "l2_writer" in llm.calls, \
        "модель обязана была получить контекст: %r" % (llm.calls,)
    assert _delivered_ids(events) == [701], \
        "доставка в контекст состоялась — событие обязано быть: %r" % \
        _delivered_ids(events)


@pytest.mark.asyncio
async def test_quote_event_is_correlated_with_turn(monkeypatch, events):
    """Событие цитаты присоединяется к ходу: те же `chat_id` и `trace_id`.

    Репро ревью: `quote_delivered_to_context` шёл с `chat_id=None` и без
    `trace_id`, тогда как `direct_turn_context` того же хода нёс реальные
    `chat_id` и `trace_id` — инспектор не мог связать события. Корреляция
    хода теперь прокидывается в эмиссию."""
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    chain = _quoted_chain(3, quoted_item_id="tg:701")

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    context_ev = _event(events, turn_trace.EVENT_CONTEXT)
    quote_ev = next((e for e in events
                     if e.get("event_name") == "quote"
                     and e.get("stage") == "quote_delivered_to_context"), None)
    assert quote_ev is not None, "события цитаты нет"
    assert quote_ev.get("chat_id") == context_ev.get("chat_id"), \
        "chat_id события цитаты обязан совпадать с трассой хода: %r vs %r" % (
            quote_ev.get("chat_id"), context_ev.get("chat_id"))
    assert quote_ev.get("trace_id") == context_ev.get("trace_id"), \
        "trace_id события цитаты обязан совпадать с трассой хода: %r vs %r" % (
            quote_ev.get("trace_id"), context_ev.get("trace_id"))
    assert quote_ev.get("trace_id"), "trace_id не должен быть пустым"


#: Инвентаризация исходящих вызовов модели в пути хода (`_handle_turn`).
#: Ключ — (файл, функция, вызов, step). Значение — как учтена доставка цитаты:
#: ``marked`` — сразу после вызова стоит `_mark_quote_delivery_used`;
#: ``covered`` — вызов вложен в помеченный вызов вызывающего;
#: ``no_chain`` — контекст хода (блок цепочки с цитатой) в payload не попадает;
#: ``other_entry`` — другой вход (не `_handle_turn`).
OUTBOUND_CONTEXT_CALLS = {
    ("services/direct_chat_service.py", "_handle_turn",
     "self._l2_write_answer", None): "receipt:l2_writer",
    ("services/direct_chat_service.py", "_handle_turn",
     "self.llm.generate", "react"): "receipt:react",
    ("services/direct_chat_service.py", "_handle_turn",
     "chat_with_tools", None): "receipt:tools",
    # Тот же путь `single` без literal-step (kwargs-словарь): receipt
    # оставляет metadata-вариант; у голого str его нет — недоучёт.
    ("services/direct_chat_service.py", "_handle_turn",
     "self.llm.generate", None): "receipt:single",
    # L1-планировщик планирует БЕЗ собранного user-контекста (окно + вопрос +
    # reply-блок): блока цепочки и аннотации цитаты в его payload нет.
    ("services/direct_chat_service.py", "_call",
     "self.llm.generate", "l1_planner"): "no_chain:planner",
    ("services/direct_chat_service.py", "_call",
     "_l1.dedicated_generate", None): "no_chain:planner",
    # Tool-фаза: оркестратор получает query+tools+время, не блоки цепочки.
    ("services/direct_chat_service.py", "_l1_tool_phase",
     "_dx.run_tool_phase", None): "no_chain:orchestrator",
    # Сегменты выборки истории — отдельные окна, не контекст хода.
    ("services/direct_chat_service.py", "_flush",
     "self.llm.generate", "history_segment"): "no_chain:history_sample",
    # Финальный писатель: доставка учтена маркером у вызывающего
    # `_l2_write_answer` (обе стадии — первый вызов и продолжение — идут
    # через `_call_l2`, а тот через `self.llm.generate`).
    ("services/direct_chat_service.py", "_call_l2",
     "self.llm.generate", None): "covered:l2_writer",
    ("services/direct_chat_service.py", "_generate",
     "_call_l2", "l2_writer"): "covered:l2_writer",
    ("services/direct_chat_service.py", "_generate",
     "_call_l2", "l2_continuation"): "covered:l2_writer",
    # SMART D6: ограниченное восстановление L2 после context-overflow. Тот же
    # собранный контекст хода (цепочка+evidence), payload заменяется целиком;
    # доставка учтена обёрткой `_l2_write_answer` — `covered:l2_writer`.
    ("services/direct_chat_service.py", "_recover_l2_overflow",
     "_call_l2", "l2_recovery"): "covered:l2_writer",
    ("services/direct_chat_service.py", "generate_initiative_reply",
     "self._l2_write_answer", None): "other_entry:initiative",
    ("services/direct_execution.py", "run_adaptive_chain",
     "llm.generate", "orchestrator"): "no_chain:orchestrator",
    ("services/tool_loop.py", "chat_with_tools",
     "llm.generate_chat", None): "covered:tools",
    ("services/tool_loop.py", "chat_with_tools",
     "llm.generate", "single"): "covered:tools",
    # §G: финальный Writer-вызов по накопленным tool-данным. Ответ этого
    # вызова возвращается через `chat_with_tools` и учитывается его receipt'ом
    # (`covered:tools`); без metadata-варианта sent_body недоступен → снимок
    # доставки не строится (консервативно, без ложного доказательства).
    ("services/tool_loop.py", "_finalize_from_evidence",
     "llm.generate", None): "covered:tools",
}


def _callee_name(node) -> str:
    parts = []
    while isinstance(getattr(node, "attr", None), str):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, __import__("ast").Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _outbound_sites(rel_path: str) -> list:
    """Все вызовы модели в файле: (функция, вызов, step, end_lineno).

    Функция-владелец — САМАЯ ГЛУБОКАЯ объемлющая (вложенные замыкания не
    маскируются внешней функцией)."""
    import ast

    source = open(rel_path, encoding="utf-8").read()
    tree = ast.parse(source)
    targets = ("self.llm.generate", "llm.generate", "llm.generate_chat",
               "self.llm.generate_chat", "self.llm.generate_with_metadata",
               "chat_with_tools", "self._l2_write_answer",
               "_dx.run_tool_phase", "_call_l2", "_l1.dedicated_generate")
    funcs = [(node.lineno, node.end_lineno, node.name)
             for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    sites: list = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node.func)
        if name not in targets:
            continue
        step = None
        for kw in node.keywords:
            if kw.arg == "step" and isinstance(kw.value, ast.Constant):
                step = kw.value.value
        owner, best = "<module>", -1
        for start, end, fname in funcs:
            if start <= node.lineno <= end and start > best:
                owner, best = fname, start
        sites.append((owner, name, step, node.end_lineno))
    return sites, source.splitlines()


def test_outbound_model_calls_inventory_is_classified():
    """Страж: КАЖДЫЙ исходящий вызов модели в пути хода учтён явно.

    Событие `quote_delivered_to_context` эмитится только после вызова,
    получившего собранный контекст. Новый такой вызов, добавленный без
    маркера и без записи в инвентаре, обязан уронить тест — иначе появится
    пятый путь, где цитата «доставлена» без доказательства (репро ревью:
    `step="react"`).
    """
    found = set()
    for rel in ("services/direct_chat_service.py",
                "services/direct_execution.py", "services/tool_loop.py"):
        sites, lines = _outbound_sites(rel)
        for owner, name, step, end_line in sites:
            key = (rel, owner, name, step)
            found.add(key)
            assert key in OUTBOUND_CONTEXT_CALLS, (
                "новый исходящий вызов модели не классифицирован: %r "
                "(функция %s, step=%r). Реши: контекст хода с цепочкой в "
                "payload? Тогда `_mark_quote_delivery_used` сразу после "
                "вызова и запись 'marked:…'; иначе — запись "
                "'no_chain:<причина>'." % (key, owner, step))
            kind = OUTBOUND_CONTEXT_CALLS[key]

    # Четыре ответообразующих пути обязаны оставлять receipt: у receipt'а
    # есть фактический `sent_body`, у голого `str` его нет.
    import re as _re
    source = open("services/direct_chat_service.py", encoding="utf-8").read()
    for path in ("l2_writer", "react", "chat_with_tools", "single"):
        assert _re.search(
            r"_remember_receipt\([^)]*\"%s\"" % path, source), (
            "путь %r не оставляет receipt (нет _remember_receipt)" % path)
    assert "_mark_quote_delivery_used" not in source, (
        "ручные маркеры доставки должны быть удалены")
    assert "_settle_quote_delivery" not in source, (
        "второй источник истины по цитатам должен быть удалён")

    missing = set(OUTBOUND_CONTEXT_CALLS) - found
    assert not missing, "инвентарь ссылается на исчезнувшие вызовы: %r" % (
        sorted(missing),)


def _force_react_path(monkeypatch):
    """Включить legacy-REACT-путь (LLM выбирает emoji) — ветка репро ревью.

    `DIRECT_L1_ENABLED=false` + решение REACT (без Decision Task) + гейт
    выбора реакции ON: ровно тот маршрут, где контекст хода уходит модели
    вызовом `step="react"`."""
    from config.settings import Settings

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
    monkeypatch.setattr(direct_chat_service._l1, "direct_l1_enabled",
                        lambda: False)
    monkeypatch.setattr(direct_chat_service._llm_react,
                        "llm_decision_enabled", lambda reactions: False)
    monkeypatch.setattr(direct_chat_service._llm_react,
                        "llm_reaction_enabled", lambda reactions: True)
    monkeypatch.setattr(
        direct_chat_service, "_decision_pre_action",
        lambda **kwargs: (direct_chat_service.ACTION_REACT, "repro", "👍",
                          4242))


@pytest.mark.asyncio
async def test_react_path_emits_one_quote_event_with_correlation(
        monkeypatch, events):
    """Цитата доехала вызовом `step="react"` — одно событие с корреляцией.

    РЕПРО ревью: legacy-REACT-путь (`DIRECT_L1_ENABLED=false`) отправляет
    модели payload с собранным контекстом (и цитатой в нём), но маркер
    доставки там отсутствовал — `calls=['react']`, ответ модели есть, а
    события нет. Теперь маркер стоит сразу после успешного вызова."""
    llm = _StagedLLM()
    # без бот-слова в тексте: иначе включается FORCE DIRECT (всегда REPLY) и
    # REACT-ветка недостижима
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3),
                                 text="как дела?")
    _force_react_path(monkeypatch)
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    assert llm.calls == ["react"], \
        "ожидался один исходящий вызов хода: %r" % (llm.calls,)
    blob = _payload_text(llm)
    assert blob.count(QUOTED_DROP_SENTINEL) == 1, \
        "цитата обязана быть в payload react-вызова"

    assert _delivered_ids(events) == [701], \
        "цитата доехала — ровно одно событие: %r" % _delivered_ids(events)
    context_ev = _event(events, turn_trace.EVENT_CONTEXT)
    quote_ev = next(e for e in events
                    if e.get("event_name") == "quote"
                    and e.get("stage") == "quote_delivered_to_context")
    assert quote_ev.get("chat_id") == context_ev.get("chat_id")
    assert quote_ev.get("trace_id") == context_ev.get("trace_id")
    assert quote_ev.get("trace_id"), "trace_id не должен быть пустым"


@pytest.mark.asyncio
async def test_react_call_failure_emits_no_quote_event(monkeypatch, events):
    """Сбой вызова `step="react"` — контекст до модели не дошёл: 0 событий."""
    from services.llm_client import LLMError

    class _ReactFails(_StagedLLM):
        async def generate_with_metadata(self, messages, **kwargs):
            if kwargs.get("step") == "react":
                self.calls.append("react")      # вызов СОСТОЯЛСЯ, но отказ
                raise LLMError("react provider down")
            return await super().generate_with_metadata(messages, **kwargs)

        async def generate(self, messages, **kwargs):
            if kwargs.get("step") == "react":
                self.calls.append("react")
                raise LLMError("react provider down")
            return await super().generate(messages, **kwargs)

    llm = _ReactFails()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3),
                                 text="как дела?")
    _force_react_path(monkeypatch)
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    assert llm.calls == ["react"], "вызов был, но провайдер отказал"
    assert _delivered_ids(events) == [], \
        "ответа модели нет — события доставки быть не должно: %r" % \
        _delivered_ids(events)


def _thread_block(items, projection=None, trigger=None):
    """Блок `<Conversation_Thread>` из реальных строк + бухгалтерия рендера."""
    lines = [thread_chain.format_chain_line(item, {}, trigger, emit_quote=False)
             for item in items]
    rendered = [(item.item_id, line,
                 thread_chain.quote_delivery_fragment(item, projection, trigger))
                for item, line in zip(items, lines)]
    body = "\n".join(lines)
    block = ("<Conversation_Thread>\n"
             f"{direct_chat_service.escape_xml_text(body)}\n"
             "</Conversation_Thread>")
    return block, rendered


def test_fallback_variant_counters_describe_sent_payload(events):
    """Fallback заменил payload → счётчики описывают ФАКТИЧЕСКИ отправленное.

    РЕПРО (реальный дефект): counters/blocks считались из ПЕРВИЧНОЙ
    аллокации, а fallback-рекомпоз заменял payload и ничего не пересчитывал —
    событие описывало контекст, которого модель не получала. Здесь два
    prepared-варианта (primary — 5 звеньев с цитатой, fallback — 2 звена без
    неё) и receipt с телом FALLBACK: снимок обязан дать счётчики и цитаты
    fallback-варианта.

    Мутация (взять primary вместо fallback) роняет этот тест."""
    items = _chain_items(5, item_id_base=700)
    quoted = [it._replace(quote_text=QUOTED_DROP_SENTINEL + " фрагмент",
                          quote_author_id=10, quote_position=0,
                          quote_is_manual=1, quote_original_available=True)
              if it.item_id == "tg:705" else it for it in items]
    primary_block, primary_rendered = _thread_block(quoted)
    fallback_block, fallback_rendered = _thread_block(quoted[:2])

    primary = direct_chat_service._prepared_turn_payload(
        chat_id=CHAT_ID, correlation_id="cid-fb",
        blocks=[("thread", primary_block)], event_blocks=[],
        available_item_ids={it.item_id for it in quoted}, window_messages=0,
        budget={"budget": 6000}, dropped=(), self_outputs=(),
        chain_rendered={"thread": primary_rendered}, projection=None)
    fallback = direct_chat_service._prepared_turn_payload(
        chat_id=CHAT_ID, correlation_id="cid-fb",
        blocks=[("thread", fallback_block)], event_blocks=[],
        available_item_ids={it.item_id for it in quoted}, window_messages=0,
        budget={"budget": 1500, "fallback": True}, dropped=(), self_outputs=(),
        chain_rendered={"thread": fallback_rendered}, projection=None)

    receipt = direct_chat_service.SuccessfulOutboundReceipt(
        path="l2_writer",
        sent_body={"messages": [{"role": "user", "content": fallback_block}]})

    snapshot = direct_chat_service._settle_delivered_turn(
        receipt, fallback, None)
    assert snapshot is not None
    # счётчики — проекция ОТПРАВЛЕННОГО (fallback) варианта, не первичного
    assert snapshot.counts["included_messages"] == 2, snapshot.counts
    assert snapshot.counts["available_messages"] == 5, snapshot.counts
    # цитата вытеснена fallback-рекомпозом → событий цитаты нет
    assert snapshot.delivered_quote_ids == ()
    direct_chat_service._project_delivered_turn(snapshot, None)
    assert _delivered_ids(events) == []

    # контроль первичного варианта: цитата доставлена, звеньев больше
    primary_snapshot = direct_chat_service._settle_delivered_turn(
        direct_chat_service.SuccessfulOutboundReceipt(
            path="l2_writer",
            sent_body={"messages": [{"role": "user", "content": primary_block}]}),
        primary, None)
    assert primary_snapshot.counts["included_messages"] == 5
    assert primary_snapshot.delivered_quote_ids == (705,)


"""Три недостающие проверки шага 1 (поведение уже реализовано)."""
from types import SimpleNamespace

import pytest

import tests.test_ur_f_inspector_step1 as T
from services import direct_chat_service as dcs
from services import llm_client as _llm_client
from services import mca_events
from services import thread_chain
from services import turn_trace
from tests.test_ur_f_inspector_step1 import (
    CHAT_ID, QUOTED_DROP_SENTINEL, _chain_items, _delivered_ids, _drive,
    _event, _payload, _payload_row_keys, _payload_text, _plain_rows,
    _quoted_chain, _StagedLLM,
)


@pytest.mark.asyncio
async def test_legacy_path_emits_selection_snapshot(monkeypatch, events):
    """Composer OFF: legacy-путь ТОЖЕ даёт `direct_turn_selection`.

    Ранее этот путь не выпускал факты выбора вовсе. Теперь legacy-бюджет
    отдаёт `PreparedTurnPayload`, а проектор печатает событие с той же
    корреляцией, что `direct_turn_context`.

    Чего legacy-путь честно НЕ знает (и что поэтому нулевое, а не выдуманное):
    даты блоков (`first_ts`/`last_ts` = 0 — строк окна под рукой нет) и
    `self_outputs` (пусто)."""
    monkeypatch.setattr(dcs._composer, "composer_on", lambda: False)
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    # цитата в звене, которое legacy-бюджет вытесняет → ложных плюсов быть не должно
    chain = _quoted_chain(40, quoted_item_id="tg:740", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    selection = _payload(events, turn_trace.EVENT_SELECTION)
    counts = selection["counts"]
    assert counts["window_messages"] == 3, counts
    payload_rows = len(_payload_row_keys(llm))
    assert counts["included_messages"] == payload_rows, (counts, payload_rows)
    assert counts["available_messages"] >= counts["included_messages"]

    thread_block = next(b for b in selection["blocks"]
                        if b.get("kind") == "thread")
    assert thread_block["rendered"] is True
    assert thread_block.get("first_ts", 0) == 0, \
        "legacy не измеряет даты окна — ноль честнее выдуманного"
    assert thread_block.get("last_ts", 0) == 0
    assert selection.get("self_outputs") in (None, []), \
        "legacy не перечисляет свои реплики — пусто, а не выдумано"

    context_ev = _event(events, turn_trace.EVENT_CONTEXT)
    sel_ev = _event(events, turn_trace.EVENT_SELECTION)
    assert sel_ev.get("chat_id") == context_ev.get("chat_id")
    assert sel_ev.get("trace_id") == context_ev.get("trace_id")
    assert sel_ev.get("trace_id")

    assert _delivered_ids(events) == [], \
        "цитата вытеснена — событий доставки нет: %r" % _delivered_ids(events)


@pytest.mark.asyncio
async def test_single_path_emits_one_correlated_snapshot(monkeypatch, events):
    """Путь `single` (L1 OFF, без tools): ровно один снимок и корреляция.

    Ранее у этого пути не было событийных проверок: receipt и селектор
    связаны, но матрица не снималась."""
    monkeypatch.setattr(dcs._l1, "direct_l1_enabled", lambda: False)
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    await svc.handle(bot, msg, user)

    assert llm.calls == ["single"], llm.calls
    selection = _payload(events, turn_trace.EVENT_SELECTION)
    assert selection["counts"]["included_messages"] == len(_payload_row_keys(llm))
    assert selection["counts"]["available_messages"] == 43, selection["counts"]
    assert _delivered_ids(events) == [701]

    context_ev = _event(events, turn_trace.EVENT_CONTEXT)
    sel_ev = _event(events, turn_trace.EVENT_SELECTION)
    quote_ev = next(e for e in events
                    if e.get("event_name") == "quote"
                    and e.get("stage") == "quote_delivered_to_context")
    assert sel_ev.get("trace_id") == context_ev.get("trace_id")
    assert quote_ev.get("trace_id") == context_ev.get("trace_id")
    assert quote_ev.get("chat_id") == context_ev.get("chat_id")


@pytest.mark.asyncio
async def test_chat_with_tools_path_emits_one_correlated_snapshot(
        monkeypatch, events):
    """Путь `chat_with_tools`: ровно один снимок, корреляция, цитата по identity.

    tool-loop подменён на возврат настоящего `ToolLoopResult` с `sent_body`
    (сам цикл покрыт своими тестами): проверяется именно receipt-проводка и
    проекция снимка."""
    monkeypatch.setattr(dcs._l1, "direct_l1_enabled", lambda: False)
    llm = _StagedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    svc.tool_router = object()          # включает ветку chat_with_tools
    chain = _quoted_chain(40, quoted_item_id="tg:701", chars=800)

    async def _fake_chain(chat_id, message, depth=None):
        return chain

    sent_bodies = []

    async def _fake_tools(client, payload, **kwargs):
        body = {"model": "chat-model-x",
                "messages": [dict(m or {}) for m in payload]}
        sent_bodies.append(body)
        return _tool_loop_result("ответ", body)

    monkeypatch.setattr(svc, "_collect_thread_chain", _fake_chain)
    monkeypatch.setattr(dcs, "chat_with_tools", _fake_tools)
    await svc.handle(bot, msg, user)

    assert len(sent_bodies) == 1, "ровно один outbound-вызов пути"
    selection = _payload(events, turn_trace.EVENT_SELECTION)
    assert selection["counts"]["included_messages"] == \
        len(_payload_row_keys(llm) | _payload_row_keys_from_body(sent_bodies[0]))
    assert _delivered_ids(events) == [701]

    context_ev = _event(events, turn_trace.EVENT_CONTEXT)
    sel_ev = _event(events, turn_trace.EVENT_SELECTION)
    quote_ev = next(e for e in events
                    if e.get("event_name") == "quote"
                    and e.get("stage") == "quote_delivered_to_context")
    assert sel_ev.get("trace_id") == context_ev.get("trace_id")
    assert quote_ev.get("trace_id") == context_ev.get("trace_id")
    assert quote_ev.get("chat_id") == context_ev.get("chat_id")


def _tool_loop_result(text, body):
    """Настоящий `ToolLoopResult` с receipt (без запуска tool-цикла)."""
    from services.tool_loop import ToolLoopResult
    return ToolLoopResult(text, rounds_used=1, tool_trace=[],
                          sent_body=body)


def _payload_row_keys_from_body(body):
    """Ключи строк контекста из фактически отправленного тела."""
    text = "\n".join(str(m.get("content") or "")
                     for m in (body or {}).get("messages") or ()
                     if str(m.get("role") or "") == "user")
    keys: set = set()
    for tag in ("Global_Context", "Conversation_Thread", "Old_Episode"):
        body_text = T._block_text(text, tag)
        for line in body_text.split("\n"):
            key = dcs._context_line_dedup_key(line)
            if key:
                keys.add(key)
    return keys


@pytest.mark.asyncio
async def test_fallback_end_to_end_describes_adapted_body(monkeypatch, events):
    """Реальный `llm_client` + адаптер рекомпоза + снимок.

    Primary падает → LLMClient пересобирает payload адаптером и уходит на
    fallback-ногу. Снимок обязан описывать ФАКТИЧЕСКИ отправленное (fallback)
    тело, а не первичный контекст; отказ адаптера (invalid shape / исключение)
    оставляет primary-тело, которое реально ушло модели (Q6)."""
    client = _llm_client.LLMClient(
        "https://api.test/v1", "k", "chat-model-x", "emb-model",
        fallback_base_url="https://api.fb/v1", fallback_model="fb-model",
        fallback_api_key="fk")

    class _Resp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    async def _primary_down(*args, **kwargs):
        raise _llm_client.LLMTransportError("primary down")

    captured = {}

    async def _fallback_ok(payload, *, sent=None):
        captured["body"] = payload
        return _Resp({"choices": [{"message": {"content": "ответ FB"},
                                   "finish_reason": "stop"}],
                      "usage": {}})

    monkeypatch.setattr(client, "_post", _primary_down)
    monkeypatch.setattr(client, "_fallback_with_retries", _fallback_ok)

    # Адаптер рекомпоза строит настоящий legacy-prepared (как fallback-вариант).
    items = _chain_items(3, item_id_base=700)
    thread_block, rendered = T._thread_block(items) \
        if hasattr(T, "_thread_block") else (None, None)
    assert thread_block is not None

    def _adapter(payload):
        prepared = dcs._prepared_turn_payload(
            chat_id=CHAT_ID, correlation_id="cid-e2e",
            blocks=[("thread", thread_block)], event_blocks=[],
            available_item_ids={it.item_id for it in items},
            window_messages=0, budget={"fallback": True}, dropped=(),
            self_outputs=(), chain_rendered={"thread": rendered},
            projection=None)
        adapted = dict(payload)
        adapted["messages"] = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": thread_block},
        ]
        return adapted, prepared

    primary_payload = {"model": "chat-model-x",
                       "messages": [{"role": "system", "content": "SYS"},
                                    {"role": "user", "content": "СТАРЫЙ КОНТЕКСТ"}]}
    completion = await client.generate_with_metadata(
        primary_payload["messages"], step="l2_writer",
        correlation_id="cid-e2e", fallback_payload_adapter=_adapter)
    assert completion.sent_body is not None
    assert thread_block in dcs._sent_user_text(completion.sent_body), \
        "отправлено именно адаптированное (fallback) тело"

    primary_prepared = dcs._prepared_turn_payload(
        chat_id=CHAT_ID, correlation_id="cid-e2e",
        blocks=[("thread", T._thread_block(items[:1])[0])], event_blocks=[],
        available_item_ids={it.item_id for it in items}, window_messages=0,
        budget={}, dropped=(), self_outputs=(),
        chain_rendered={"thread": T._thread_block(items[:1])[1]},
        projection=None)

    snapshot = dcs._settle_delivered_turn(
        completion, _adapter(primary_payload)[1], None)
    assert snapshot is not None
    assert snapshot.counts["included_messages"] == len(items), snapshot.counts
    assert snapshot.counts["included_messages"] != \
        dcs._settle_delivered_turn(completion, primary_prepared, None) \
        .counts["included_messages"]
    assert snapshot.trace_id == "cid-e2e"

    # ── отказ адаптера: invalid shape → отправлено PRIMARY-тело (Q6)
    def _bad_shape(payload):
        return {}, None

    completion2 = await client.generate_with_metadata(
        primary_payload["messages"], step="l2_writer",
        correlation_id="cid-e2e", fallback_payload_adapter=_bad_shape)
    assert "СТАРЫЙ КОНТЕКСТ" in dcs._sent_user_text(completion2.sent_body)

    def _raises(payload):
        raise RuntimeError("adapter boom")

    completion3 = await client.generate_with_metadata(
        primary_payload["messages"], step="l2_writer",
        correlation_id="cid-e2e", fallback_payload_adapter=_raises)
    assert "СТАРЫЙ КОНТЕКСТ" in dcs._sent_user_text(completion3.sent_body)


@pytest.mark.asyncio
async def test_fallback_projection_uses_fallback_variant_counters(events):
    """Проекция снимка: счётчики/блоки — из fallback-варианта, не первичного.

    Контроль к предыдущему тесту: тот проверяет реальный клиент, этот —
    что селектор берёт вариант, соответствующий отправленному телу (иначе
    событие описывало бы payload, которого модель не получала)."""
    items = _chain_items(5, item_id_base=700)
    quoted = [it._replace(quote_text=QUOTED_DROP_SENTINEL + " фрагмент",
                          quote_author_id=10, quote_position=0,
                          quote_is_manual=1, quote_original_available=True)
              if it.item_id == "tg:705" else it for it in items]
    primary_block, primary_rendered = T._thread_block(quoted)
    fallback_block, fallback_rendered = T._thread_block(quoted[:2])
    primary = dcs._prepared_turn_payload(
        chat_id=CHAT_ID, correlation_id="cid-fb", blocks=[("thread", primary_block)],
        event_blocks=[], available_item_ids={it.item_id for it in quoted},
        window_messages=0, budget={"budget": 6000}, dropped=(), self_outputs=(),
        chain_rendered={"thread": primary_rendered}, projection=None)
    fallback = dcs._prepared_turn_payload(
        chat_id=CHAT_ID, correlation_id="cid-fb", blocks=[("thread", fallback_block)],
        event_blocks=[], available_item_ids={it.item_id for it in quoted},
        window_messages=0, budget={"budget": 1500, "fallback": True},
        dropped=(), self_outputs=(),
        chain_rendered={"thread": fallback_rendered}, projection=None)
    receipt = dcs.SuccessfulOutboundReceipt(
        path="l2_writer",
        sent_body={"messages": [{"role": "user", "content": fallback_block}]})

    snapshot = dcs._settle_delivered_turn(receipt, fallback, None)
    assert snapshot.counts["included_messages"] == 2, snapshot.counts
    assert snapshot.delivered_quote_ids == ()
    dcs._project_delivered_turn(snapshot, None)
    payload = _payload(events, turn_trace.EVENT_SELECTION)
    assert payload["counts"]["included_messages"] == 2
    assert payload["counts"]["available_messages"] == 5
    assert _delivered_ids(events) == []


@pytest.mark.asyncio
async def test_empty_window_reports_zero_messages(monkeypatch, events):
    """Пустое окно: `{0, 0, 0}` — честные нули, без «неизвестно»."""
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=[])
    await svc.handle(bot, msg, user)

    counts = _payload(events, turn_trace.EVENT_SELECTION).get("counts") or {}
    assert counts == {"available_messages": 0, "included_messages": 0,
                      "window_messages": 0}, counts


@pytest.mark.asyncio
async def test_window_60_without_pressure_counts_all(monkeypatch, events):
    """Окно 60 без давления: `{60, 60, 60}` — прежние числа не изменились."""
    rows = _plain_rows(60)
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=rows)
    await svc.handle(bot, msg, user)

    counts = _payload(events, turn_trace.EVENT_SELECTION).get("counts") or {}
    assert counts == {"available_messages": 60, "included_messages": 60,
                      "window_messages": 60}, counts


def test_selection_within_limits_is_not_flagged_truncated():
    """Полный, не урезанный payload не помечается `truncated` (флаг — факт,
    а не постоянный шум)."""
    payload = turn_trace._selection_payload({
        "counts": {"available_messages": 3, "included_messages": 2,
                   "window_messages": 4},
        "blocks": [{"kind": "global_tail", "role": "p1", "rendered": True,
                    "source_ids": ["msg:1", "msg:2"],
                    "first_ts": 1700000001, "last_ts": 1700000002,
                    "tokens": 12}],
        "dropped": [{"reason_code": "budget_exceeded",
                     "kind": "global_middle", "count": 1}],
        "self_outputs": [{"source_id": "bot_output_tg:2",
                          "tg_message_id": 2, "ts": 1700000002}],
        "policy_version": "asap3-composer-1",
    })
    assert "truncated" not in payload
    assert "dropped_total" not in payload
    assert len(payload["blocks"]) == 1
    assert payload["blocks"][0]["source_ids"] == ["msg:1", "msg:2"]


# ════════════════════════════════════════════════════════════════════════════
# 4. `_scrub`: единственная allow-ветка (source_url) и её негативный тест
# ════════════════════════════════════════════════════════════════════════════

def test_scrub_allows_only_public_source_url_and_title():
    """URL выдачи остаётся, текст чата в `source_url` — отброшен, любой
    другой длинный текст по-прежнему digest (UR-F §3 R4)."""
    url = "https://example.com/news/2026/11/10" + "a" * 200
    payload = {"source_links": [{
        "source_id": "web:abc123",
        "source_url": url,
        "source_title": "Заголовок страницы " * 20,
        "published_at": "",
    }]}
    packed = turn_trace._pack(payload)
    link = packed["source_links"][0]
    assert link["source_url"] == url, "публичный адрес не должен становиться digest"
    assert len(link["source_title"]) <= turn_trace.SOURCE_TITLE_MAX
    assert link["source_id"] == "web:abc123"

    # негатив: текст чата в source_url — значение отброшено, не сохранено
    chat_text = "привет, это текст сообщения из чата, а не адрес"
    broken = turn_trace._pack({"source_links": [
        {"source_url": chat_text},
        {"source_url": "javascript:alert(1)"},
        {"source_url": "https://ok.example/x"},
    ]})["source_links"]
    assert broken[0]["source_url"] == ""
    assert broken[1]["source_url"] == ""
    assert broken[2]["source_url"] == "https://ok.example/x"

    # любой ДРУГОЙ длинный ключ — как раньше: digest + длина
    other = turn_trace._pack({"something_else": "x" * 100})["something_else"]
    assert other == {"digest": turn_trace.text_digest("x" * 100), "chars": 100}


# ════════════════════════════════════════════════════════════════════════════
# 5. Fail-open: сбой сборки выбора не ломает ответ
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_selection_build_failure_does_not_break_the_turn(
        monkeypatch, events):
    """Исключение внутри сборки выбора → ответ всё равно доставляется.

    Ломаем РЕАЛЬНЫЙ участник сборки (`_sel_block`, вызывается из
    `_compose_user_content`), а не границу: проверяется именно fail-open
    нового кода на пути записи (§7 R3: «ход важнее трассы»)."""

    def _boom(*args, **kwargs):
        raise RuntimeError("selection build exploded")

    monkeypatch.setattr(direct_chat_service, "_sel_block", _boom)
    svc, bot, msg, user = _drive(monkeypatch, _StagedLLM(), window=_rows(4))
    await svc.handle(bot, msg, user)

    # ответ доставлен обычным путём
    assert bot.send_message.await_count >= 1
    sent = bot.send_message.await_args.args[1]
    assert sent.strip()
    # и трасса хода в остальном цела (контекст/доставка эмитированы)
    names = [e.get("event_name") for e in events]
    assert turn_trace.EVENT_CONTEXT in names
    assert turn_trace.EVENT_DELIVERY in names


def test_note_selection_failure_is_fail_open(monkeypatch, events):
    """Сбой внутри `note_selection` не пробрасывается наружу (никогда)."""
    def _boom(*args, **kwargs):
        raise RuntimeError("payload build exploded")

    monkeypatch.setattr(turn_trace, "_selection_payload", _boom)
    turn_trace.note_selection("cid-broken", chat_id=CHAT_ID, payload={})
    assert [e.get("event_name") for e in events] == []


# ════════════════════════════════════════════════════════════════════════════
# 6. `style_policy`: trace_id + сработавшие правила без текста правил
# ════════════════════════════════════════════════════════════════════════════

def _line_breaks_policy():
    rule = _sp.StyleRule(
        id="owner.line_breaks", kind="line_breaks", strictness="hard",
        params={"max_breaks": 1},
        reason="правило владельца: не больше одной пустой строки")
    return _sp.EffectiveStylePolicy(
        context="regular", rules=(_sp.ResolvedRule(rule=rule),),
        source="global", revision="7")


def _dash_policy():
    """Заводское правило тире: на «—» правило РЕАЛЬНО правит текст."""
    rule = _sp.StyleRule(
        id="owner.dash", kind="dash", strictness="hard",
        reason="правило владельца: короткий дефис вместо длинного тире")
    return _sp.EffectiveStylePolicy(
        context="regular", rules=(_sp.ResolvedRule(rule=rule),),
        source="global", revision="3")


@pytest.mark.asyncio
async def test_style_repair_only_outcome_is_recorded(monkeypatch, events):
    """БЛОКЕР 1: починка (styled=True, без повтора) ОБЯЗАНА попасть в трассу.

    Именно этот исход самый частый у владельческих правил: текст изменён,
    значит Inspector не может показывать «правила не зафиксированы»."""
    from services import mca_gates
    monkeypatch.setattr(mca_gates, "speech_style_policy_enabled",
                        lambda: True)
    outcome = await _sp.apply_style_policy(
        "привет — как дела", chat_id=CHAT_ID, policy=_dash_policy(),
        context="regular", emit_events=True, stage="direct_pre_send",
        correlation_id="cid-repair", record=False)

    # исход действительно «починка», а не конфликт/повтор
    assert outcome.styled is True
    assert not outcome.repetition
    assert outcome.repaired == 1
    assert "-" in outcome.text and "—" not in outcome.text

    event = _event(events, "style_policy")
    assert event.get("trace_id") == "cid-repair"
    # правка — это успешный проход, а не «пропущено»
    assert event.get("outcome") == "success"
    payload = dict(event.get("usage_json") or {})
    rules = payload.get("rules") or []
    assert [row["rule_id"] for row in rules] == ["owner.dash"]
    assert rules[0]["status"] == _sp.STATUS_REPAIRED


@pytest.mark.asyncio
async def test_style_clean_pass_without_rules_emits_nothing(monkeypatch,
                                                           events):
    """Чистый проход без сработавших правил события не создаёт (как раньше):
    иначе на каждый ход появлялся бы шум без информации."""
    from services import mca_gates
    monkeypatch.setattr(mca_gates, "speech_style_policy_enabled",
                        lambda: True)
    outcome = await _sp.apply_style_policy(
        "привет - как дела", chat_id=CHAT_ID, policy=_dash_policy(),
        context="regular", emit_events=True, stage="direct_pre_send",
        correlation_id="cid-clean", record=False)

    assert outcome.styled is True
    assert outcome.repaired == 0 and not outcome.repetition
    assert _sp.fired_rules(outcome) == []
    assert [e.get("event_name") for e in events] == []


def _max_rules_outcome(count: int) -> "_sp.StyleOutcome":
    """Исход с МАКСИМАЛЬНЫМ числом сработавших правил (12 = потолок)."""
    results = [
        _sp.RuleOutcome(
            rule_id="owner.rule_%02d_long_identifier" % i,
            kind="line_breaks", status=_sp.STATUS_REPAIRED,
            reason="blank_line_runs_collapsed", source="global")
        for i in range(count)]
    return _sp.StyleOutcome(
        text="текст", context="regular", applied=True,
        policy_revision="2026.11.11", policy_source="chat",
        results=results,
        repetition=tuple({"phrase_id": "p%d" % i, "count": 3}
                         for i in range(6)),
        extent=None, repair_used=1, elapsed_ms=12.5)


def test_style_event_payload_survives_storage_truncation(events):
    """БЛОКЕР 2: payload события укладывается в лимит хранилища, поэтому
    `sanitize(json.dumps(...))[:2000]` НЕ режет его и JSON остаётся валидным.

    Проверяется ровно то, что делает хранилище: `mca_events.build_event`
    сериализует `usage_json` с обрезкой на 2000 символах."""
    from services import mca_events

    # (A) максимальный исход: 12 сработавших правил + повторы
    outcome = _max_rules_outcome(_sp.STYLE_RULES_MAX)
    _sp._emit_style_event(outcome, chat_id=CHAT_ID, stage="direct_pre_send",
                          correlation_id="cid-max")
    payload = dict(_event(events, "style_policy").get("usage_json") or {})

    size = len(json.dumps(payload, ensure_ascii=False))
    assert size <= 1900, "payload события обязан укладываться в 1900 символов"
    assert payload.get("rules"), "правила обязаны остаться в payload"
    assert len(payload["rules"]) <= _sp.STYLE_RULES_MAX
    assert all(row.get("rule_id") for row in payload["rules"])
    assert payload.get("truncated") is True, \
        "сокращение ради лимита обязано быть видно"

    # та же обрезка, что делает хранилище → строка остаётся JSON
    event = mca_events.build_event("style_policy", outcome="success",
                                   usage_json=payload)
    assert event is not None and event.get("usage_json")
    restored = json.loads(event["usage_json"])
    assert isinstance(restored, dict)
    assert restored.get("rules"), "правила обязаны выжить обрезку хранилища"

    # (B) небольшой исход правил влезает ЦЕЛИКОМ и не помечается усечённым
    small = _max_rules_outcome(3)
    _sp._emit_style_event(small, chat_id=CHAT_ID, stage="direct_pre_send",
                          correlation_id="cid-small")
    small_payload = _payload_of(events, "style_policy", "cid-small")
    assert len(small_payload["rules"]) == 3
    assert "truncated" not in small_payload


def test_bounded_style_payload_keeps_machine_scalars_when_extreme():
    """Крайний случай: даже огромный payload остаётся разбираемым JSON."""
    payload = {"applied": True, "context": "regular",
               "rules": [{"rule_id": "r%d" % i, "kind": "dash",
                          "status": "repaired", "reason": "x" * 48,
                          "source": "global"} for i in range(200)],
               "notes": ["n" * 200] * 50}
    bounded = _sp.bounded_style_payload(payload)
    assert len(json.dumps(bounded, ensure_ascii=False)) <= 1900
    assert bounded.get("applied") is True
    assert isinstance(json.loads(json.dumps(bounded)), dict)


@pytest.mark.asyncio
async def test_style_event_carries_trace_id_and_fired_rules(monkeypatch,
                                                            events):
    """Сработавшее правило видно (id/kind/причина), текст правила — нет."""
    from services import mca_gates
    monkeypatch.setattr(mca_gates, "speech_style_policy_enabled",
                        lambda: True)
    outcome = await _sp.apply_style_policy(
        "раз\nдва\nтри\nчетыре", chat_id=CHAT_ID,
        policy=_line_breaks_policy(), context="regular",
        emit_events=True, stage="direct_pre_send",
        correlation_id="cid-style", record=False)

    assert outcome.results, "правило не проверялось"
    assert not outcome.styled, "конфликт правила должен быть виден"
    assert outcome.failed or outcome.conflicts

    event = _event(events, "style_policy")
    assert event.get("trace_id") == "cid-style"
    payload = dict(event.get("usage_json") or {})
    rules = payload.get("rules") or []
    assert rules, "сработавшие правила не записаны"
    assert all(set(row) <= {"rule_id", "kind", "status", "reason", "source"}
               for row in rules), rules
    assert [row["rule_id"] for row in rules] == ["owner.line_breaks"]
    assert rules[0]["status"] in _sp.FIRED_STATUSES
    assert rules[0]["kind"] == "line_breaks"
    assert rules[0]["reason"] == "line_breaks_exceeded"
    # текст правила владельца в событие не попадает
    blob = json.dumps(event, ensure_ascii=False)
    assert "не больше одной пустой строки" not in blob


def test_fired_rules_skip_pass_and_drop_free_text_reason():
    """`rules` — только сработавшие: pass/not_applicable не едут, а
    описательная причина правила не выдаётся за код."""
    outcome = _sp.StyleOutcome(results=[
        _sp.RuleOutcome(rule_id="dash", kind="dash", status=_sp.STATUS_PASS),
        _sp.RuleOutcome(rule_id="quotes", kind="quotation_marks",
                        status=_sp.STATUS_NA, reason="soft_habit_writer_only"),
        _sp.RuleOutcome(rule_id="one_word", kind="one_word",
                        status=_sp.STATUS_CONFLICT,
                        reason="owner_rule_vs_task",
                        detail=(("fragment", "ТЕКСТ_ЧАТА_XYZ"),)),
        _sp.RuleOutcome(rule_id="emoji", kind="emoji",
                        status=_sp.STATUS_REPAIRED,
                        reason="заводское правило: срезать эмодзи"),
    ])
    fired = _sp.fired_rules(outcome)
    assert [row["rule_id"] for row in fired] == ["one_word", "emoji"]
    assert fired[0]["reason"] == "owner_rule_vs_task"
    assert fired[1]["reason"] == "", "описательная причина не является кодом"
    blob = json.dumps(fired, ensure_ascii=False)
    assert "ТЕКСТ_ЧАТА_XYZ" not in blob, "detail правила попал в трассу"
    assert "заводское правило" not in blob


# ════════════════════════════════════════════════════════════════════════════
# 7. Полный ход (`_handle_turn`): снимок описывает ОТПРАВЛЕННОЕ тело
#
# Подменяется только ТРАНСПОРТ (или — где указано — маршрутизатор моделей).
# Держатель `_delivery`, `_remember_receipt`, `_settle_delivered_turn`,
# проектор и фоллбэк-адаптеры — продовые: тесты доказывают проводку
# receipt→prepared→снимок, а не свою собственную сборку prepared вручную.
# ════════════════════════════════════════════════════════════════════════════

import services.tool_loop as _tool_loop
from services import auto_budget as _auto_budget
from services.llm_client import LLMChatResult, LLMToolCall

PRIMARY_WINDOW = 8000      # primary-окно (в репро: budget=8000)
FALLBACK_WINDOW = 300      # окно fallback-модели (в репро: fallback_window=300)
TURN_ROWS = 12


def _plan_json(**over):
    """План L1 из общего фикстура (`tests.test_asap7_direct_l1`)."""
    from tests.test_asap7_direct_l1 import _plan_json as _base
    return _base(**over)


def _stage_result(stage: str, window: int, policy_mode: str = "dynamic"):
    return _auto_budget.BudgetResult(
        stage=stage, model="m", context_window=int(window),
        mandatory_tokens=0, output_reserve=0, safety_reserve=0,
        auto_input_budget=int(window), policy_mode=str(policy_mode),
        manual_cap=None, effective_input_budget=int(window),
        source="runtime")


def _force_fallback_capacity(monkeypatch, *, primary=PRIMARY_WINDOW,
                            fallback=FALLBACK_WINDOW):
    """Резолвер бюджетов: primary 8000 / fallback 300 (числа репро).

    При fallback < primary сервис обязан выдать НАСТОЯЩИЙ fallback-адаптер
    рекомпоза (`_fallback_adapter_factory`), поэтому тест идёт по живому
    fallback-соглашению, а не по подставленному prepared."""
    async def _resolve(stage, **kwargs):
        return _stage_result(stage,
                             fallback if stage == "direct.fallback"
                             else primary)

    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _resolve)
    monkeypatch.setattr(dcs._auto_budget, "auto_budget_enabled", lambda: True)
    monkeypatch.setattr(dcs._model_capacity, "capacity_resolver_enabled",
                        lambda: True)

    async def _window(base_url, model, slot=None):
        return (int(primary), "runtime")

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _window)


def _drive_with_db(monkeypatch, llm, *, window=None, db=None):
    """Тот же продовый ход, что `_drive`, но с двойником БД (конспект)."""
    from config.settings import Settings
    from tests.test_direct_chat import FakeMemory, _bot, _make_service, \
        _message, _user

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    memory = FakeMemory(window=list(window or ()))
    svc = _make_service(memory=memory, llm=llm, db=db)
    bot = _bot()
    msg = _message(text="бот, как дела?", message_id=4242, chat_id=CHAT_ID)
    return svc, bot, msg, _user()


class _Response:
    def __init__(self, content):
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10}}


class _FallbackClient(_llm_client.LLMClient):
    """НАСТОЯЩИЙ LLMClient: план L1 отдаётся локально, primary падает.

    Подменён только транспорт (`_post`/`_fallback_with_retries`) — так же,
    как в `test_direct_fallback_recompose_asap32`. Адаптер рекомпоза,
    `sent_body` и receipt — продовые."""

    def __init__(self, plan, *, answer="ответ FB"):
        super().__init__(
            "https://api.test/v1", "k", "chat-model-x", "emb-model",
            fallback_base_url="https://api.fb/v1",
            fallback_model="fb-model", fallback_api_key="fk")
        assert self._fallback_active
        self.plan = plan
        self.answer = answer
        self.calls: list = []
        self.last: list = []
        self.primary_payload: dict | None = None
        self.fallback_payload: dict | None = None

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.calls.append(kwargs.get("step"))
        self.last = list(messages or ())
        if kwargs.get("step") == "l1_planner":
            return self.plan
        return await super().generate(messages, temperature, chat_id,
                                      **kwargs)


def _wire_failing_primary(client) -> None:
    """Primary-нога транспорта падает, fallback-нога возвращает ответ."""
    async def _down(*args, **kwargs):
        captured = kwargs.get("payload")
        if captured is None and len(args) > 1:
            captured = args[1]
        client.primary_payload = captured
        raise _llm_client.LLMTransportError("primary down")

    async def _fallback(payload, *, sent=None):
        client.fallback_payload = payload
        return _Response(client.answer)

    client._post = _down
    client._fallback_with_retries = _fallback


class _ToolsRejectedLLM:
    """Клиент, у которого провайдер не умеет tools.

    `generate_chat` отказывает, plain-ответ обязан прийти metadata-вариантом
    (`generate` в этом случае вызываться не должен — у него нет receipt)."""

    _chat_model = "chat-model-x"
    _base_url = "https://api.test/v1"
    _fallback_model = ""
    _fallback_base_url = ""

    def __init__(self, answer="простой ответ"):
        self.answer = answer
        self.tool_calls = 0
        self.plain_generate_called = False
        self.plain_body: dict | None = None

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.plain_generate_called = True
        return self.answer

    async def generate_chat(self, messages, **kwargs):
        self.tool_calls += 1
        raise _llm_client.LLMError("provider rejects tools")

    async def generate_with_metadata(self, messages, temperature=None,
                                     chat_id=None, **kwargs):
        sent = {"model": self._chat_model,
                "messages": [dict(m or {}) for m in (messages or ())]}
        self.plain_body = sent
        return _completion(self.answer, "stop", kwargs.get("correlation_id"),
                           sent)


class _MultiRoundLLM:
    """Клиент многорaундового tool-цикла: нога задаётся по раундам.

    ``legs`` — "fallback" (primary падает → адаптер рекомпоза заменяет body
    и этот body уходит модели) либо "primary" (успех без замены payload).
    Последний раунд возвращает финальный текст без tool_calls."""

    _chat_model = "chat-model-x"
    _base_url = "https://api.test/v1"
    _fallback_model = "fb-model"
    _fallback_base_url = "https://api.fb/v1"

    def __init__(self, legs, *, answer="финальный ответ"):
        self.legs = list(legs)
        self.answer = answer
        self.round = 0
        self.bodies: list = []

    async def generate(self, messages, **kwargs):
        return self.answer

    def _body(self, messages):
        return {"model": self._chat_model,
                "messages": [dict(m or {}) for m in (messages or ())]}

    async def generate_chat(self, messages, *, tools=None,
                            fallback_payload_adapter=None, **kwargs):
        leg = self.legs[self.round]
        self.round += 1
        final = self.round >= len(self.legs)
        payload = self._body(messages)
        if leg == "fallback":
            assert fallback_payload_adapter is not None, \
                "fallback-нога без адаптера рекомпоза"
            out = fallback_payload_adapter(dict(payload))
            body = out[0] if isinstance(out, tuple) else out
            assert body.get("messages") and body["messages"] != payload["messages"], (
                "рекомпоз обязан заменить messages: %r" % (body,))
        else:
            body = payload
        self.bodies.append(body)
        return LLMChatResult(
            content=(None if not final else self.answer),
            tool_calls=(None if final else
                        [LLMToolCall(id="call-%d" % self.round,
                                     name="chat_history",
                                     arguments='{"limit": 3}')]),
            finish_reason="stop", sent_body=body)


def _body_rows(body) -> set:
    return _payload_row_keys_from_body(body)


def _long_rows(count):
    """Окно с длинными строками: пол-хвоста не съедает весь fallback-бюджет."""
    return [{
        "id": i, "tg_message_id": 600 + i, "user_id": 10,
        "author_name": "Вася",
        "text": ("строка окна %d " % i) + ("содержательный текст " * 10),
        "timestamp": 1_700_000_000 + i, "reply_to_id": None,
        "media_type": "text",
    } for i in range(1, count + 1)]


def _tools_turn(monkeypatch, llm, *, rows):
    """Ход по tool-пути с ЖИВЫМ циклом (подменён только транспорт модели)."""
    monkeypatch.setattr(dcs._l1, "direct_l1_enabled", lambda: False)
    # пол свежего хвоста: при дефолтных 20 строках хвост не вытесняется вовсе
    monkeypatch.setenv("CHAT_FRESH_TAIL_MIN_MESSAGES", "3")
    svc, bot, msg, user = _drive(monkeypatch, llm, window=rows)
    svc.tool_router = object()

    async def _real_tools(*args, **kwargs):
        return await _tool_loop.chat_with_tools(*args, **kwargs)

    monkeypatch.setattr(dcs, "chat_with_tools", _real_tools)
    return svc, bot, msg, user


#: Бюджеты tool-хода: fallback-окно меньше primary, но больше резерва
#: tool-схем (иначе рекомпоз честно упирается в 1 токен и ничего не меняет).
TOOLS_PRIMARY_WINDOW = 200_000
TOOLS_FALLBACK_WINDOW = 7_000
TOOLS_ROWS = 40


@pytest.mark.asyncio
async def test_l2_fallback_full_turn_describes_adapted_body(monkeypatch, events):
    """РЕПРО: primary упал → ушло адаптированное тело, а событие описывало
    первичную сборку (`policy_mode=dynamic`, `budget=8000`,
    `fallback_window=300`, `included_messages=0`).

    Ход целиком (`svc.handle`): receipt/flat/проектор — продовые, подменён
    только транспорт LLMClient. Снимок обязан нести бюджет, окно и счётчики
    ТОГО варианта, который реально ушёл модели."""
    _force_fallback_capacity(monkeypatch)
    client = _FallbackClient(T._plan())
    _wire_failing_primary(client)
    svc, bot, msg, user = _drive(monkeypatch, client,
                                 window=_plain_rows(TURN_ROWS))
    await svc.handle(bot, msg, user)

    assert client.fallback_payload is not None, "fallback-нога не вызывалась"
    adapted_rows = _body_rows(client.fallback_payload)
    primary_rows = _body_rows(client.primary_payload)
    assert len(primary_rows) == TURN_ROWS, sorted(primary_rows)
    # Рекомпоз ужал контекст: адаптированное тело короче первичного, поэтому
    # варианты различимы по счётчикам (иначе проверка была бы тавтологией).
    assert len(adapted_rows) < len(primary_rows), (
        "адаптированное тело обязано быть не полным: %r"
        % (sorted(adapted_rows),))

    correlation_id, turn = _turn_events(events, turn_trace.EVENT_CONTEXT)
    selection = [e for e in turn
                 if e.get("event_name") == turn_trace.EVENT_SELECTION]
    assert len(selection) == 1, "снимок хода ровно один: %d" % len(selection)
    event = selection[0]
    assert event.get("trace_id") == correlation_id
    payload = dict(event.get("usage_json") or {})
    budget = payload.get("budget") or {}
    counts = payload.get("counts") or {}

    # бюджет — FALLBACK-варианта (адаптированное тело), не первичный:
    # у первичного были `window`/`payload_tokens`/`window_source`.
    assert budget.get("policy_mode") == "fallback_recompose", budget
    assert budget.get("budget") == FALLBACK_WINDOW, budget
    assert "window" not in budget, budget
    assert "payload_tokens" not in budget, budget
    assert "window_source" not in budget, budget

    # счётчики — про строки, реально доехавшие в отправленном теле
    assert counts.get("included_messages") == len(adapted_rows), counts
    assert counts.get("included_messages") != len(primary_rows), counts


@pytest.mark.asyncio
async def test_tools_rejected_turn_plain_answer_has_receipt(monkeypatch,
                                                           events):
    """REPRO: провайдер отказал в tools → plain-ответ доставлен, но
    `ToolLoopResult.sent_body=None` и снимка хода нет вовсе.

    Теперь plain-фолбэк идёт metadata-вариантом: `sent_body` есть, и
    коррелированный `direct_turn_selection` описывает именно это тело."""
    monkeypatch.setattr(dcs._l1, "direct_l1_enabled", lambda: False)
    rows = _plain_rows(3)
    llm = _ToolsRejectedLLM()
    svc, bot, msg, user = _drive(monkeypatch, llm, window=rows)
    svc.tool_router = object()          # включает ветку chat_with_tools
    captured = {}

    async def _real_tools(*args, **kwargs):
        result = await _tool_loop.chat_with_tools(*args, **kwargs)
        captured["result"] = result
        return result

    monkeypatch.setattr(dcs, "chat_with_tools", _real_tools)
    await svc.handle(bot, msg, user)

    assert llm.tool_calls == 1, "tools-вызов обязан состояться"
    assert llm.plain_generate_called is False, (
        "plain-фолбэк обязан использовать metadata-вариант: у generate() "
        "нет receipt")
    sent = llm.plain_body
    assert sent and sent.get("messages")
    result = captured["result"]
    assert isinstance(getattr(result, "sent_body", None), dict), (
        "ToolLoopResult без sent_body — доставка не доказана")
    assert result.sent_body.get("messages") == sent["messages"]

    correlation_id, turn = _turn_events(events, turn_trace.EVENT_CONTEXT)
    selection = [e for e in turn
                 if e.get("event_name") == turn_trace.EVENT_SELECTION]
    assert len(selection) == 1, "снимок хода ровно один: %d" % len(selection)
    assert selection[0].get("trace_id") == correlation_id
    counts = dict(selection[0].get("usage_json") or {}).get("counts") or {}
    assert counts.get("included_messages") == len(_body_rows(sent)), counts


@pytest.mark.asyncio
async def test_multi_round_tools_fallback_first_describes_final_primary(
        monkeypatch, events):
    """Раунд 1 — fallback (адаптированное тело), раунд 2 — primary.

    Отвечает ПОСЛЕДНИЙ вызов, значит снимок обязан описывать его (primary)
    бюджет и счётчики, а не ранний fallback-вариант. Снимок ровно один."""
    _force_fallback_capacity(monkeypatch, primary=TOOLS_PRIMARY_WINDOW,
                            fallback=TOOLS_FALLBACK_WINDOW)
    llm = _MultiRoundLLM(["fallback", "primary"])
    svc, bot, msg, user = _tools_turn(monkeypatch, llm,
                                      rows=_long_rows(TOOLS_ROWS))
    await svc.handle(bot, msg, user)

    assert llm.round == 2, "ожидалось два tool-раунда: %r" % (llm.round,)
    final_rows = _body_rows(llm.bodies[-1])
    early_rows = _body_rows(llm.bodies[0])
    assert len(final_rows) == TOOLS_ROWS, sorted(final_rows)
    assert len(early_rows) < len(final_rows), (
        "ранний раунд обязан быть адаптированным: %r" % (sorted(early_rows),))

    correlation_id, turn = _turn_events(events, turn_trace.EVENT_CONTEXT)
    selection = [e for e in turn
                 if e.get("event_name") == turn_trace.EVENT_SELECTION]
    assert len(selection) == 1, "снимок хода ровно один: %d" % len(selection)
    assert selection[0].get("trace_id") == correlation_id
    payload = dict(selection[0].get("usage_json") or {})
    budget = payload.get("budget") or {}
    counts = payload.get("counts") or {}
    assert budget.get("policy_mode") != "fallback_recompose", (
        "отвечал primary — отчёт не может описывать fallback-вариант: %r"
        % (budget,))
    assert budget.get("budget") == TOOLS_PRIMARY_WINDOW, budget
    assert counts.get("included_messages") == len(final_rows), counts


@pytest.mark.asyncio
async def test_multi_round_tools_fallback_last_describes_adapted_body(
        monkeypatch, events):
    """Раунд 1 — primary, раунд 2 — fallback (адаптированное тело).

    Отвечал fallback-вызов: снимок обязан дать бюджет/счётчики
    адаптированного тела. Снимок ровно один."""
    _force_fallback_capacity(monkeypatch, primary=TOOLS_PRIMARY_WINDOW,
                            fallback=TOOLS_FALLBACK_WINDOW)
    llm = _MultiRoundLLM(["primary", "fallback"])
    svc, bot, msg, user = _tools_turn(monkeypatch, llm,
                                      rows=_long_rows(TOOLS_ROWS))
    await svc.handle(bot, msg, user)

    assert llm.round == 2, "ожидалось два tool-раунда: %r" % (llm.round,)
    final_rows = _body_rows(llm.bodies[-1])
    early_rows = _body_rows(llm.bodies[0])
    assert len(early_rows) == TOOLS_ROWS, sorted(early_rows)
    assert 0 < len(final_rows) < len(early_rows), (
        "финальный раунд обязан быть адаптированным: %r" % (sorted(final_rows),))

    correlation_id, turn = _turn_events(events, turn_trace.EVENT_CONTEXT)
    selection = [e for e in turn
                 if e.get("event_name") == turn_trace.EVENT_SELECTION]
    assert len(selection) == 1, "снимок хода ровно один: %d" % len(selection)
    assert selection[0].get("trace_id") == correlation_id
    payload = dict(selection[0].get("usage_json") or {})
    budget = payload.get("budget") or {}
    counts = payload.get("counts") or {}
    assert budget.get("policy_mode") == "fallback_recompose", budget
    assert counts.get("included_messages") == len(final_rows), counts


SUMMARY_TEXT = "конспект: обсуждали дроны и отчёты за прошлую неделю"
SUMMARY_START_TS = 1_700_000_000
SUMMARY_END_TS = 1_700_000_003
SUMMARY_POST_ROWS = 5


def _summary_window():
    return _plain_rows(SUMMARY_POST_ROWS + 3)


def _summary_db():
    """FakeDB + РЕАЛЬНЫЙ бегущий конспект (метка объёма и watermark).

    Записи `window_start_ts` здесь НЕТ намеренно: старая запись/двойник без
    колонки не должна рвать сборку и не должна выдумывать начало диапазона."""
    from tests.test_direct_chat import FakeDB

    class _DB(FakeDB):
        async def get_running_summary(self, chat_id, now):
            return {"summary": SUMMARY_TEXT, "window_end_ts": SUMMARY_END_TS,
                    "raw_count": 3}

        async def get_summary_level(self, chat_id, level):
            return None

        async def get_smart_raw(self, chat_id, **kwargs):
            return []

    return _DB()


@pytest.mark.asyncio
async def test_summary_turn_composer_on_and_off_agree_on_counts(
        monkeypatch, events):
    """Один и тот же конспект+хвост через композер ON и legacy OFF.

    Счётчики вошедших сообщений обязаны совпадать (конспект — не сообщения),
    а вид блока честно различает роли: `global_head` = конспект,
    `global_tail` = дословные строки. Legacy-блок «конспект+хвост» НЕ
    переименовывается в `global_tail`: иначе конспект выдавался бы за свежие
    дословные сообщения."""
    window = _summary_window()

    # ── композер ON
    on_llm = _StagedLLM()
    svc, bot, msg, user = _drive_with_db(monkeypatch, on_llm, window=window,
                                         db=_summary_db())
    await svc.handle(bot, msg, user)
    on_payload = _payload(events, turn_trace.EVENT_SELECTION)
    on_body = {"messages": [dict(m or {}) for m in (on_llm.last or ())]}
    on_blocks = {b.get("kind"): b for b in (on_payload.get("blocks") or ())}
    assert "global_head" in on_blocks, sorted(on_blocks)
    assert "global_tail" in on_blocks, sorted(on_blocks)
    # конспект — в head, дословные строки — в tail: head не несёт сообщений
    assert not (on_blocks["global_head"].get("source_ids") or ()), \
        on_blocks["global_head"]
    assert len(on_blocks["global_tail"].get("source_ids") or ()) == \
        min(SUMMARY_POST_ROWS, turn_trace.SELECTION_SOURCE_IDS_MAX)

    # ── тот же контент, композер OFF (legacy-бюджет)
    events.clear()
    monkeypatch.setattr(dcs._composer, "composer_on", lambda: False)
    off_llm = _StagedLLM()
    svc2, bot2, msg2, user2 = _drive_with_db(monkeypatch, off_llm,
                                             window=window,
                                             db=_summary_db())
    await svc2.handle(bot2, msg2, user2)
    off_payload = _payload(events, turn_trace.EVENT_SELECTION)
    off_body = {"messages": [dict(m or {}) for m in (off_llm.last or ())]}
    off_blocks = list(off_payload.get("blocks") or ())
    off_global = [b for b in off_blocks if b.get("kind") == "global"]
    assert len(off_global) == 1, [b.get("kind") for b in off_blocks]
    assert not [b for b in off_blocks
                if b.get("kind") in ("global_tail", "global_head")], (
        "legacy-блок «конспект+хвост» выдан за %r"
        % ([b.get("kind") for b in off_blocks],))
    assert off_global[0].get("kind") not in dcs._MESSAGE_BLOCK_KINDS, (
        "конспект нельзя выдавать за дословные сообщения")

    assert off_payload["counts"]["included_messages"] == \
        on_payload["counts"]["included_messages"], (off_payload["counts"],
                                                    on_payload["counts"])
    assert off_payload["counts"]["window_messages"] == \
        on_payload["counts"]["window_messages"]
    assert off_payload["counts"]["included_messages"] == SUMMARY_POST_ROWS, \
        off_payload["counts"]

    # Блок ДЕЙСТВИТЕЛЬНО смешанный: конспект и дословные строки в одном
    # тексте — поэтому переименование в `global_tail` было бы ложью.
    on_global = T._block_text(
        "\n".join(str(m.get("content") or "") for m in on_body["messages"]),
        "Global_Context")
    off_global_text = T._block_text(
        "\n".join(str(m.get("content") or "") for m in off_body["messages"]),
        "Global_Context")
    assert SUMMARY_TEXT in on_global and SUMMARY_TEXT in off_global_text
    assert "строка окна %d" % len(window) in off_global_text
    assert on_global.count(SUMMARY_TEXT) == 1
    assert off_global_text.count(SUMMARY_TEXT) == 1


@pytest.mark.asyncio
async def test_summary_block_carries_window_range_not_invented_ids(
        monkeypatch, events):
    """UR-20.5: у блока `global_head` есть ДАТЫ окна конспекта и нет
    выдуманного `source_id`.

    Раньше `_sel_block` заполнял ids/даты только для `global_tail`/
    `global_middle`, поэтому конспект приходил без дат и без ссылок — карточка
    не могла сказать ни «конспект до <дата>», ни диапазон."""
    from tests.test_direct_chat import FakeDB

    class _DB(FakeDB):
        async def get_running_summary(self, chat_id, now):
            return {"summary": SUMMARY_TEXT,
                    "window_start_ts": SUMMARY_START_TS,
                    "window_end_ts": SUMMARY_END_TS,
                    "raw_count": 3}

        async def get_summary_level(self, chat_id, level):
            return None

        async def get_smart_raw(self, chat_id, **kwargs):
            return []

    svc, bot, msg, user = _drive_with_db(monkeypatch, _StagedLLM(),
                                         window=_summary_window(), db=_DB())
    await svc.handle(bot, msg, user)

    payload = _payload(events, turn_trace.EVENT_SELECTION)
    blocks = {b.get("kind"): b for b in (payload.get("blocks") or ())}
    head = blocks["global_head"]
    # Диапазон окна — ровно из записи конспекта (начало и конец).
    assert head.get("first_ts") == SUMMARY_START_TS, head
    assert head.get("last_ts") == SUMMARY_END_TS, head
    # Единого id у конспекта нет — он и не выдумывается.
    assert not (head.get("source_ids") or ()), head


DASH_ANSWER = "Да — конечно"


class _DashAnswerLLM(_StagedLLM):
    """Отвечает текстом с длинным тире — срабатывает правило владельца."""

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        if step == "l1_planner":
            return await super().generate(
                messages, temperature, chat_id, module=module, step=step,
                correlation_id=correlation_id, **kwargs)
        self.calls.append(step)
        self.last = list(messages or ())
        return DASH_ANSWER

    async def generate_with_metadata(self, messages, temperature=None,
                                     chat_id=None, module=None, step=None,
                                     correlation_id=None, **kwargs):
        self.calls.append(step)
        self.last = list(messages or ())
        sent = {"model": "chat-model-x",
                "messages": [dict(m or {}) for m in (messages or ())]}
        return _completion(DASH_ANSWER, "stop", correlation_id, sent)


def _force_dash_policy(monkeypatch):
    """Реальный документ политики (build_document) с правилом «тире»."""
    from services import mca_gates

    monkeypatch.setattr(mca_gates, "speech_style_policy_enabled", lambda: True)
    doc = _sp.build_document(
        rules=[{"id": "owner.dash", "kind": "dash", "strictness": "hard"}],
        revision=3, owner=1, reason="test")

    async def _layers(chat_id):
        return (doc, None, True)

    monkeypatch.setattr(_sp, "_read_layers", _layers)


@pytest.mark.asyncio
async def test_extent_planned_turn_emits_one_extent_metric_and_one_style_event(
        monkeypatch, events):
    """SOUL-14.2: extent-план хода → ровно одна КОРРЕЛИРОВАННАЯ метрика
    `speech_extent` (значения прежние) и ровно одно событие `style_policy`.

    Мутация «убрать проекцию extent из снимка» роняет этот тест: событие
    выпускает ТОЛЬКО проектор (у прохода стиля `emit_events=False`)."""
    _force_dash_policy(monkeypatch)
    llm = _DashAnswerLLM(plan=_plan_json(extent="micro"))
    svc, bot, msg, user = _drive(monkeypatch, llm, window=_plain_rows(3))
    await svc.handle(bot, msg, user)

    # правило реально правило текст — иначе проверять нечего
    delivered = bot.send_message.await_args.args[1]
    assert "—" not in delivered and "-" in delivered, delivered

    correlation_id, turn = _turn_events(events, turn_trace.EVENT_CONTEXT)
    extent = [e for e in turn if e.get("event_name") == "speech_extent"]
    styles = [e for e in turn if e.get("event_name") == "style_policy"]
    assert len(extent) == 1, "метрика extent ровно одна на ход: %d" % len(extent)
    assert len(styles) == 1, "событие стиля ровно одно на ход: %d" % len(styles)

    event = extent[0]
    assert event.get("trace_id") == correlation_id, (
        "метрика extent обязана быть связана с трассой хода: %r"
        % (event.get("trace_id"),))
    assert event.get("chat_id") == CHAT_ID
    assert event.get("component") == "style_policy"
    assert event.get("stage") == "direct_pre_send"
    assert event.get("outcome") == "success"
    payload = dict(event.get("usage_json") or {})
    assert payload.get("extent") == "micro", payload
    assert payload.get("status") == "pass", payload
    assert payload.get("one_word") == 0
    assert payload.get("one_word_exact") == 0
    assert payload.get("words") == 2, payload
    assert payload.get("context") == "regular"

    style = styles[0]
    assert style.get("trace_id") == correlation_id
    fired = (dict(style.get("usage_json") or {})).get("rules") or []
    assert [row.get("rule_id") for row in fired] == ["owner.dash"], fired
