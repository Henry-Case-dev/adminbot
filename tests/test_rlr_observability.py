"""RLR-06-OBSERVABILITY (§7) — трасса одного хода: авторский текст не изменён.

REMOVE-LEGACY-REPHRASING v2.0 (owner corrective 2026-11-05, источник
`plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`), §7:

* по `correlation_id` видна вся цепочка хода: trigger/чат/ChatClock → L1 →
  инструменты → запрос L2 (манифест) → завершение L2 (finish_reason, digest
  raw final) → упорядоченные доставочные операции (digest после каждой) →
  итог доставки (идемпотентный ключ, реальные Telegram ID);
* `semantic_rewrite_count=0` для обычного ответа — это ИЗМЕРЕНИЕ, а не
  литерал; LLM-вызовы классифицированы (planning/tool/final/continuation/
  provider_retry), а не «всё под stage2»;
* при расхождении raw_final ↔ delivered трасса называет ТОЧНУЮ разрешённую
  причину (имя операции), без нового LLM-судьи;
* приватность: в событии нет ни одного фрагмента текста чата — только
  digest'ы/коды/числа/id (доступ к сырью остаётся у `mca_bot_outputs`).

TEST-LIFECYCLE: CONTRACT owner=RLR-06-OBSERVABILITY.
"""
import json

import pytest

from services import mca_events
from services import turn_trace
from services.direct_chat_service import DirectChatService
from services.llm_client import LLMCompletion

pytestmark = pytest.mark.system2

CHAT_ID = -1009876543210
#: Сентinel-строки: их НЕ должно быть ни в одном payload'е трассы.
SECRET_QUERY = "СЕКРЕТНЫЙ_ВОПРОС_123456"
SECRET_ANSWER = "УНИКАЛЬНЫЙ_ОТВЕТ_987654"


@pytest.fixture(autouse=True)
def _clean_trace():
    turn_trace.reset()
    yield
    turn_trace.reset()


@pytest.fixture
def events(monkeypatch):
    """Перехват ЕДИНСТВЕННОЙ точки эмиссии (`mca_events.emit_mca_event`)."""
    seen: list = []

    def spy(event_name, *, outcome, **fields):
        seen.append({"event_name": event_name, "outcome": outcome,
                     **fields})
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
    item = _event(seen, name)
    return dict(item.get("usage_json") or {})


def _plan(**over):
    from tests.test_asap7_direct_l1 import _plan_json
    return _plan_json(**over)


class _StagedLLM:
    """Двойник клиента: L1-план + финальный Writer с МЕТАДАННЫМИ UR-18.

    `generate_with_metadata` объявлен на КЛАССЕ — как у настоящего
    `LLMClient`, поэтому продовый шов выбирает именно его.
    """

    def __init__(self, *, l1=None, writer=None):
        self.l1_reply = l1 if l1 is not None else _plan()
        self.writer = list(writer or [(SECRET_ANSWER, "stop")])
        self.calls: list = []
        # Атрибуты реального клиента, которые читает манифест запроса L2.
        self._chat_model = "chat-model-x"
        self._base_url = "https://api.test/v1"
        self._fallback_model = "fb-model"

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append({"step": step, "metadata": False})
        if step == "l1_planner":
            return self.l1_reply
        return SECRET_ANSWER

    async def generate_with_metadata(self, messages, temperature=None,
                                     chat_id=None, module=None, step=None,
                                     correlation_id=None, **kwargs):
        self.calls.append({"step": step, "metadata": True})
        if step == "l1_planner":
            return _completion(self.l1_reply, "stop", correlation_id)
        if step in ("l2_writer", "l2_continuation"):
            text, finish = self.writer.pop(0)
            if isinstance(text, Exception):
                raise text
            return _completion(text, finish, correlation_id)
        return _completion(SECRET_ANSWER, "stop", correlation_id)

    def steps(self):
        return [c["step"] for c in self.calls]


def _completion(text, finish_reason, correlation_id=None):
    return LLMCompletion(
        text=text, finish_reason=finish_reason, provider="test-provider",
        model="test-model", usage={"prompt_tokens": 11, "completion_tokens": 7,
                                   "total_tokens": 18},
        max_output_tokens_sent=1000, attempt=1,
        correlation_id=correlation_id)


def _drive(monkeypatch, llm, *, text="бот, как дела?", composer=False):
    """Продовый ход Direct (`handle`) с РЕАЛЬНОЙ доставкой (не замоканной)."""
    from config.settings import Settings
    from tests.test_direct_chat import _bot, _make_service, _message, _user

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    # Композер речевых слоёв: ось переключаема, оба пути обязаны нести
    # манифест запроса L2 (блоки + ревизии owner-промптов) — часть §7.
    from services import mca_gates as _gates
    from services import prompt_composer as _pcomp
    monkeypatch.setattr(_gates, "unified_composer_env_enabled",
                        lambda: bool(composer))
    monkeypatch.setattr(_gates, "unified_composer_enabled",
                        lambda: bool(composer))
    monkeypatch.setattr(_pcomp, "composer_enabled_now",
                        lambda gates: bool(getattr(
                            gates, "unified_composer_enabled", False)))
    svc = _make_service(llm=llm)
    bot = _bot()
    msg = _message(text=text, message_id=4242, chat_id=CHAT_ID)
    return svc, bot, msg, _user()


def _turn(seen, correlation_id=None):
    """События одного хода (по `trace_id`), если id известен."""
    if correlation_id is None:
        contexts = [e for e in seen
                    if e.get("event_name") == turn_trace.EVENT_CONTEXT]
        assert contexts, "контекст хода не эмитирован"
        correlation_id = contexts[-1].get("trace_id")
    return correlation_id, [e for e in seen
                            if e.get("trace_id") == correlation_id]


# ════════════════════════════════════════════════════════════════════════════
# (a) обычный ход: L1 → tools → L2 → операции доставки; digest совпадает
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("composer", [False, True])
async def test_normal_turn_traces_stages_and_digests_match(monkeypatch, events,
                                                           composer):
    """Обычный ответ: одна финальная генерация, `semantic_rewrite_count=0`,
    digest raw final == digest доставленного текста.

    Оба режима композера: манифест запроса (блоки + ревизии owner-промптов)
    обязан быть непустым и на пути без композера."""
    llm = _StagedLLM(writer=[(SECRET_ANSWER, "stop")])
    svc, bot, msg, user = _drive(monkeypatch, llm, composer=composer)
    await svc.handle(bot, msg, user)

    correlation_id, turn = _turn(events)
    assert correlation_id

    # ── контекст: trigger/чат/ChatClock/L1/идемпотентный ключ
    ctx = _payload(events, turn_trace.EVENT_CONTEXT)
    assert ctx["flow"] == "direct"
    assert ctx["trigger"] == "force_keyword"      # реальное значение матрицы
    assert ctx["chat_id"] == CHAT_ID
    assert ctx["source_message_id"] == 4242
    assert ctx["clock"], "ChatClock хода не зафиксирован"
    assert ctx["l1"]["action"] == "reply"
    assert ctx["idempotency_key"].startswith("direct:%d:4242:" % CHAT_ID)
    assert ctx["llm_calls"].get("planning") == 1
    assert turn_trace.EVENT_CONTEXT in [e["event_name"] for e in turn]

    # ── Writer: манифест запроса, завершение, измеренный счётчик авторов
    writer = _payload(events, turn_trace.EVENT_WRITER)
    assert writer["semantic_rewrite_count"] == 0
    assert writer["completion"]["finish_reason"] == "stop"
    assert writer["completion"]["completed"] is True
    assert writer["completion"]["text_source"] == "author"
    assert writer["completion"]["raw_final_digest"]
    assert writer["completion"]["usage"]["total_tokens"] == 18
    assert writer["request"]["model"] == "chat-model-x"
    assert writer["request"]["provider"] == "api.test"
    assert writer["request"]["fallback_model"] == "fb-model"
    # фактический автор ответа — из метаданных завершения UR-18
    assert writer["completion"]["model"] == "test-model"
    assert writer["llm_calls"].get("final") == 1
    # манифест запроса: блоки/ревизии owner-промптов (payload не хранится)
    manifest = writer["manifest"]
    assert manifest["composer"] is composer
    assert manifest["blocks"], "контекстные блоки Writer'а не записаны"
    assert all("block" in b and "rendered" in b for b in manifest["blocks"])
    assert manifest["revisions"], "ревизии owner-промптов не записаны"
    assert manifest["writer"] == "l2_writer"

    # ── доставка: операции с digest'ом, совпадение raw_final ↔ delivered
    delivery = _payload(events, turn_trace.EVENT_DELIVERY)
    ops = [op["op"] for op in delivery["ops"]]
    assert turn_trace.OP_PLAIN in ops
    assert turn_trace.OP_EGRESS_SANITIZE in ops
    assert ops[-1] == turn_trace.OP_CHUNK
    assert delivery["raw_final_digest"] == delivery["delivered_digest"]
    assert delivery["digest_match"] is True
    assert delivery["divergence_reason"] == ""
    assert delivery["semantic_rewrite_count"] == 0
    assert delivery["delivery"]["outcome"] == "success"
    assert delivery["delivery"]["tg_message_ids"] == [999]
    assert delivery["delivery"]["idempotency_key"] == ctx["idempotency_key"]
    # ровно один финальный авторский вызов (без reroll/второго писателя)
    assert llm.steps().count("l2_writer") == 1


# ════════════════════════════════════════════════════════════════════════════
# (b) продолжение после finish_reason=length — классифицируется отдельно
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_continuation_is_classified_not_a_rewrite(monkeypatch, events):
    """Второй вызов провайдера — `continuation` (тот же ответ), а не новый
    автор: `semantic_rewrite_count` остаётся 0."""
    llm = _StagedLLM(writer=[("Первая часть ответа", "length"),
                             (". Вторая часть.", "stop")])
    svc, bot, msg, user = _drive(monkeypatch, llm)
    await svc.handle(bot, msg, user)

    _, turn = _turn(events)
    writer = _payload(events, turn_trace.EVENT_WRITER)
    assert writer["completion"]["finish_reason"] == "length"
    assert writer["completion"]["continuation_calls"] == 1
    assert writer["completion"]["completed"] is True
    assert writer["semantic_rewrite_count"] == 0, "продолжение ≠ второй автор"
    assert writer["llm_calls"].get("continuation") == 1
    assert writer["llm_calls"].get("final") == 1
    # отдельный шаг провайдера виден как продолжение того же ответа
    assert llm.steps().count("l2_continuation") == 1
    assert llm.steps().count("l2_writer") == 1

    delivery = _payload(events, turn_trace.EVENT_DELIVERY)
    assert delivery["semantic_rewrite_count"] == 0
    assert delivery["digest_match"] is True


# ════════════════════════════════════════════════════════════════════════════
# (c) снятие машинного маркера: digest меняется, причина названа точно
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reasoning_marker_strip_names_the_exact_cause(monkeypatch, events):
    """Черновик-тег снят технической очисткой: digest изменился, а трасса
    называет ровно `reasoning_marker_strip` (не «что-то почистили»)."""
    llm = _StagedLLM(
        writer=[("<thinking>внутренний черновик</thinking>Готово, ответ.",
                 "stop")])
    svc, bot, msg, user = _drive(monkeypatch, llm)
    await svc.handle(bot, msg, user)

    _, turn = _turn(events)
    writer = _payload(events, turn_trace.EVENT_WRITER)
    delivery = _payload(events, turn_trace.EVENT_DELIVERY)

    assert writer["completion"]["raw_final_digest"]
    assert delivery["raw_final_digest"] != delivery["delivered_digest"]
    assert delivery["digest_match"] is False
    assert delivery["divergence_reason"] == turn_trace.OP_REASONING_STRIP
    changed = [op["op"] for op in delivery["ops"] if op.get("changed")]
    assert changed == [turn_trace.OP_REASONING_STRIP]
    # снятый черновик до пользователя не доехал
    sent = bot.send_message.await_args.args[1]
    assert "черновик" not in sent and "Готово" in sent


# ════════════════════════════════════════════════════════════════════════════
# (e) незавершённый ответ — честный отказ, а не «обычный успех»
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unfinished_answer_is_not_a_normal_success(monkeypatch, events):
    """Продолжение невозможно → трасса показывает отказ и его причину,
    доставки нет (обрезок не публикуется как готовый ответ)."""
    llm = _StagedLLM(writer=[("Обрезок ответа", "length"),
                             ("", "length")])
    svc, bot, msg, user = _drive(monkeypatch, llm)
    await svc.handle(bot, msg, user)

    _, turn = _turn(events)
    writer = _event(events, turn_trace.EVENT_WRITER)
    assert writer["outcome"] == "failed"
    payload = _payload(events, turn_trace.EVENT_WRITER)
    assert payload["completion"]["refused"] is True
    assert payload["completion"]["refused_reason"] == "unfinished_answer"
    assert payload["completion"]["text_source"] == "none"

    delivery = _event(events, turn_trace.EVENT_DELIVERY)
    assert delivery["outcome"] != "success"
    assert _payload(events, turn_trace.EVENT_DELIVERY)["delivery"]["outcome"] \
        != "success"
    # обрезок не ушёл в чат: доставки не было вовсе
    assert bot.send_message.await_count == 0


# ════════════════════════════════════════════════════════════════════════════
# (d) приватность: в payload'ах трассы нет ни фрагмента текста чата
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_no_chat_text_in_trace_payloads(monkeypatch, events):
    """События трассы содержат только digest'ы/коды/числа/id."""
    llm = _StagedLLM(writer=[(SECRET_ANSWER, "stop")])
    svc, bot, msg, user = _drive(monkeypatch, llm, text=SECRET_QUERY)
    await svc.handle(bot, msg, user)

    correlation_id, turn = _turn(events)
    assert turn, "трасса хода пуста"
    blob = json.dumps(turn, ensure_ascii=False)
    assert SECRET_QUERY not in blob, "вопрос чата попал в трассу"
    assert SECRET_ANSWER not in blob, "авторский текст попал в трассу"
    # и при этом digest'ы на месте — сравнение возможно без хранения текста
    delivery = _payload(events, turn_trace.EVENT_DELIVERY)
    assert len(delivery["raw_final_digest"]) == turn_trace.DIGEST_CHARS
    assert len(delivery["delivered_digest"]) == turn_trace.DIGEST_CHARS
    # каждый payload укладывается в лимит `usage_json` (JSON остаётся целым)
    for item in turn:
        assert len(json.dumps(item.get("usage_json") or {},
                              ensure_ascii=False)) <= 2000
