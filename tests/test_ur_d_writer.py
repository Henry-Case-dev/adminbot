# -*- coding: utf-8 -*-
"""UR-D (UNIFIED-REPLY) — общий Writer Direct/Initiative, LLMCompletion с
finish_reason, продолжение при length, динамический output, безопасная
доставка.

Строки карты `plans/features/unified-reply/requirements-map.json` (slice UR-D):

* UR-04/UR-10.3 — единый Writer и общий речевой композер для обоих
  триггеров; диалог инициативы отбирает общий `ContextSelection`
  (без `render_window_lines(window, 12)` и без `max_tokens=700`);
* UR-18 — структурированный `LLMCompletion` доезжает до Writer:
  `finish_reason` читается потребителем, fallback не теряет finish_reason,
  `generate()` остаётся str-совместимым;
* UR-19/UR-19.1/UR-19.2 — output Writer'а вычисляется из реального
  max_output модели и фактического размера входа; универсальные константы
  (700/4096/16384) не подставляются; короткий extent не создаёт
  технический обрубок;
* UR-19.3/UR-19.4 + UR-RES-05 — при `length` тот же автор продолжает ответ
  ДО отправки; незавершённый текст не публикуется (честный отказ,
  инициатива отменяется);
* UR-19.5 — `chunk_text` без потери/смены текста; первый chunk привязан
  к reply, остальные нет; чанкование после валидированного завершения;
* UR-05 — SendRecheck/target/единый счётчик отправки сохранены на границе
  отправки (бизнес-логика доставки не стала вторым автором).

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-D
"""
import asyncio
import re
import time
from types import SimpleNamespace

import pytest

from services import auto_budget as _ab
from services import direct_chat_service as dcs
from services import mca_intents as mi
from services import model_capacity as _mcap
from services import prompt_composer as _pcomp
from services import turn_trace as _ttrace
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.direct_l1 import L1Plan
from services.llm_client import LLMClient, LLMCompletion, LLMError
from tests.test_asap7_direct_l1 import _FakeLLM, _drive, _plan_json
from tests.test_direct_chat import CHAT_ID, FakeMemory, _bot, _make_service

CHAT = CHAT_ID
BOT_ID = 12345


# ── общие помощники ──────────────────────────────────────────────────────────

def _window_row(uid=10, name="Вася", text="привет из окна", ts=100, tg=None,
                row_id=None):
    return {"user_id": uid, "author_name": name, "text": text,
            "timestamp": ts, "media_type": "text", "reply_to_id": None,
            "tg_message_id": tg, "id": row_id}


class _MetadataLLM:
    """Двойник клиента С метаданными (класс-метод `generate_with_metadata`).

    Ответы выдаются по очереди из `completions` на КАЖДЫЙ вызов (включая
    L1-план через текстовый фасад `generate`), поэтому последовательность
    отвечает порядку реального хода: план → writer → (continuation).
    """

    def __init__(self, completions, *, model="unit-model",
                 base_url="https://unit.example/v1"):
        self.completions = list(completions)
        self.calls = []
        self._chat_model = model
        self._base_url = base_url

    async def generate_with_metadata(self, messages, temperature=None,
                                     chat_id=None, *, module=None, step=None,
                                     correlation_id=None,
                                     fallback_payload_adapter=None,
                                     supervised_transport=None,
                                     max_output_tokens=None):
        self.calls.append({"step": str(step), "messages": messages,
                           "max_output_tokens": max_output_tokens,
                           "correlation_id": correlation_id})
        item = self.completions.pop(0) if self.completions else None
        if isinstance(item, Exception):
            raise item
        if item is None:
            item = _completion("")
        return item

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        # Текстовый фасад: обязан оставаться str-совместимым (UR-18).
        completion = await self.generate_with_metadata(
            messages, temperature=temperature, chat_id=chat_id, **kwargs)
        return completion.text

    def steps(self):
        return [c["step"] for c in self.calls]

    def calls_of(self, step):
        return [c for c in self.calls if c["step"] == str(step)]


def _completion(text, finish_reason="stop"):
    return LLMCompletion(
        text=text, finish_reason=finish_reason, model="unit-model",
        provider="unit.example", usage={"total_tokens": 10},
        max_output_tokens_sent=None, attempt=1, correlation_id="corr",
        fallback_chain=())


async def _init_db(tmp_path, name="ur_d.db"):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _make_intent(db, *, goal="что там с релизом?"):
    now = int(time.time())
    result = await mi.get_service(db).create_intent(
        CHAT, kind="follow_up", origin="unanswered_question",
        subject_ids=("q:test",), goal=goal, source_refs=("msg:11",),
        not_before=now - 7200, expires_at=now + 3 * 86400,
        activation_condition="time_due", created_at=now - 7200)
    # create_intent возвращает (intent_id, created) — распаковываем честно.
    intent_id = result[0] if isinstance(result, tuple) else result
    row = await mi.get_service(db).store.get_intent(intent_id)
    return intent_id, row


def _candidate(intent_id):
    return mi.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=CHAT, intent_id=intent_id,
        reason_code="default")


def _situation():
    return mi.InitiativeSituation(trigger_kind="intent_due", chat_id=CHAT)


def _words(text):
    return re.split(r"\s+", str(text or "").strip())


@pytest.fixture(autouse=True)
def _exploration_off(monkeypatch):
    """Детерминизм: mca-10b exploration-draw не подменяет intent-кандидата."""
    import services.mca_exploration as expl

    async def _off(db, purpose, chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)


@pytest.fixture(autouse=True)
def _clean_events():
    from services import mca_events
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


# ── UR-04/UR-10.3: один Writer и один композер на оба триггера ───────────────

class TestUnifiedWriterPath:
    @pytest.mark.asyncio
    async def test_both_triggers_share_writer_seam(
            self, monkeypatch, tmp_path):
        """Direct и Initiative пишут ОДНИМ швом `_l2_write_answer` (один код
        финального текста: тот же verbalizer-канал, тот же continuation и
        fallback); `writer=...` — только имя в трассе, не второй автор."""
        writer_calls: list = []

        real_l2 = DirectChatService._l2_write_answer

        async def _l2_spy(self, chat_id, query, **kwargs):
            writer_calls.append({"writer": str(kwargs.get("writer")
                                               or "l2_writer")})
            return await real_l2(self, chat_id, query, **kwargs)

        monkeypatch.setattr(DirectChatService, "_l2_write_answer", _l2_spy)
        # 1) Direct-триггер: полный ход handle().
        llm = _FakeLLM(l1=_plan_json(), l2="ответ Direct")
        svc, _react, bot, msg, user = _drive(monkeypatch, "как дела?",
                                             llm=llm)
        await svc.handle(bot, msg, user)
        assert llm.calls_of("l2_writer")
        # 2) Initiative-триггер: тот же класс, тот же шов.
        db = await _init_db(tmp_path, "ur_d_shared.db")
        try:
            intent_id, _row = await _make_intent(db)
            init_llm = _FakeLLM(l1=_plan_json(), l2="ответ Initiative")
            writer = _make_service(llm=init_llm)
            result = await dcs.handle_initiative(
                bot=_bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-d-shared", writer_service=writer)
            assert result["status"] == "sent", result
            assert init_llm.calls_of("l2_writer")
        finally:
            await db.close()
        # Один шов Writer'а на оба триггера; имена — наблюдаемость.
        names = {c["writer"] for c in writer_calls}
        assert names == {"l2_writer", "initiative_writer"}, writer_calls

    @pytest.mark.asyncio
    async def test_both_triggers_share_speech_composer(
            self, monkeypatch, tmp_path):
        """Общий речевой композер: при включённом UNIFIED_COMPOSER оба
        триггера собирают систему ОДНИМ `_compose_speech_system` с одним
        base_key (никакой отдельной инициативной сборки system нет)."""
        monkeypatch.setattr(_pcomp, "composer_enabled_now",
                            lambda gates: True)
        composer_calls: list = []
        real_compose = DirectChatService._compose_speech_system

        async def _compose_spy(self, *, base_prompt, base_key, **kwargs):
            composer_calls.append({"base_key": base_key,
                                   "writer": str(kwargs.get("writer") or "")})
            return await real_compose(self, base_prompt=base_prompt,
                                      base_key=base_key, **kwargs)

        monkeypatch.setattr(DirectChatService, "_compose_speech_system",
                            _compose_spy)
        llm = _FakeLLM(l1=_plan_json(), l2="ответ Direct")
        svc, _react, bot, msg, user = _drive(monkeypatch, "как дела?",
                                             llm=llm)
        await svc.handle(bot, msg, user)
        db = await _init_db(tmp_path, "ur_d_composer.db")
        try:
            intent_id, _row = await _make_intent(db)
            init_llm = _FakeLLM(l1=_plan_json(), l2="ответ Initiative")
            writer = _make_service(llm=init_llm)
            result = await dcs.handle_initiative(
                bot=_bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-d-composer", writer_service=writer)
            assert result["status"] == "sent", result
        finally:
            await db.close()
        keys = {c["base_key"] for c in composer_calls
                if c["writer"] in ("l2_writer", "initiative_writer")}
        assert keys == {"prompts.direct_chat_verbalizer_system_prompt"}, \
            composer_calls
        names = {c["writer"] for c in composer_calls}
        assert {"l2_writer", "initiative_writer"} <= names

    @pytest.mark.asyncio
    async def test_initiative_window_from_shared_selection_no_hard_cap(
            self, monkeypatch):
        """UR-10.3: окно Writer'а инициативы отбирает общий
        ContextSelection — при достаточном бюджете видны БОЛЬШЕ 12 строк
        (ручного потолка нет), а урезание бюджета снимает лишнее."""
        rows = [_window_row(uid=10 + i, text=f"реплика номер {i}",
                            ts=100 + i, tg=300 + i, row_id=i + 1)
                for i in range(30)]
        llm = _FakeLLM(l2="ответ инициативы")
        svc = _make_service(llm=llm, memory=FakeMemory(window=rows))
        text = await svc.generate_initiative_reply(
            CHAT, {"goal": "тест", "kind": "follow_up"},
            l1_plan=L1Plan(action="reply", extent="normal", source="llm"),
            correlation_id="corr-ur-d-window")
        assert text == "ответ инициативы"
        l2_calls = llm.calls_of("l2_writer")
        assert l2_calls
        payload = "".join(str(m.get("content"))
                          for m in l2_calls[-1]["messages"])
        visible = [t for t in (f"реплика номер {i}" for i in range(30))
                   if t in payload]
        assert len(visible) > 12, \
            f"ручной потолок 12 строк вернулся: visible={len(visible)}"
        assert "[M1]" in payload        # проекция меток — общий рендер

        # Аллокатор управляет видимым множеством: крошечный бюджет →
        # меньше строк (selection живой, не декорация).
        tiny = _ab.BudgetResult(
            stage="initiative.l2", model="unknown-model-xyz",
            context_window=16384, mandatory_tokens=0, output_reserve=1024,
            safety_reserve=64, auto_input_budget=40, policy_mode="dynamic",
            manual_cap=None, effective_input_budget=40, source="fallback")

        async def _tiny(stage, **kwargs):
            return tiny

        import services.auto_budget as ab_module
        monkeypatch.setattr(ab_module, "resolve_stage_budget", _tiny)
        llm2 = _FakeLLM(l2="ответ инициативы")
        svc2 = _make_service(llm=llm2, memory=FakeMemory(window=rows))
        await svc2.generate_initiative_reply(
            CHAT, {"goal": "тест", "kind": "follow_up"},
            l1_plan=L1Plan(action="reply", extent="normal", source="llm"),
            correlation_id="corr-ur-d-window-tiny")
        l2_calls2 = llm2.calls_of("l2_writer")
        assert l2_calls2
        payload2 = "".join(str(m.get("content"))
                           for m in l2_calls2[-1]["messages"])
        visible2 = [t for t in (f"реплика номер {i}" for i in range(30))
                    if t in payload2]
        assert 0 < len(visible2) <= 12, visible2

    @pytest.mark.asyncio
    async def test_initiative_no_hidden_briefness_directive(
            self, monkeypatch):
        """UR-04 (§3 источника): факты повода остаются в промпте, глобальная
        директива «не устраивай доклад» удалена; полноту несёт extent-блок
        ПЛАНА (longform → развёрнутый, compact → компакт)."""
        rows = [_window_row(uid=10, text="контекст реплика", ts=100, tg=301,
                            row_id=1)]
        llm = _FakeLLM(l1=_plan_json(extent="longform"), l2="ответ")
        svc = _make_service(llm=llm, memory=FakeMemory(window=rows))
        await svc.generate_initiative_reply(
            CHAT, {"goal": "тест", "kind": "follow_up"},
            l1_plan=L1Plan(action="reply", extent="longform", source="llm"),
            correlation_id="corr-ur-d-nocap")
        l2_calls = llm.calls_of("l2_writer")
        assert l2_calls
        payload = "".join(str(m.get("content"))
                          for m in l2_calls[-1]["messages"])
        assert "не устраивай доклад" not in payload
        assert "ОЖИДАЕМАЯ ПОЛНОТА: РАЗВЁРНУТЫЙ ТЕКСТ" in payload
        # extent из плана, не «be brief»-хак: короткий план → компактный блок.
        llm2 = _FakeLLM(l1=_plan_json(extent="compact"), l2="ответ")
        svc2 = _make_service(llm=llm2, memory=FakeMemory(window=rows))
        await svc2.generate_initiative_reply(
            CHAT, {"goal": "тест", "kind": "follow_up"},
            l1_plan=L1Plan(action="reply", extent="compact", source="llm"),
            correlation_id="corr-ur-d-compact")
        payload2 = "".join(str(m.get("content"))
                           for m in llm2.calls_of("l2_writer")[-1]["messages"])
        assert "ОЖИДАЕМАЯ ПОЛНОТА: КОМПАКТ" in payload2


# ── UR-19/UR-19.1/UR-19.2: динамический output ───────────────────────────────

class TestWriterDynamicOutput:
    @pytest.mark.asyncio
    async def test_output_computed_from_real_capacity(self, monkeypatch):
        """Известный ресурс: max_tokens = min(провайдерский max_output,
        окно − фактический вход); модель/endpoint — от клиента хода."""
        capacity = _mcap.CapacityResult(
            provider="unit", model="unit-model",
            declared_context_window=32768, runtime_context_window=32768,
            effective_context_window=32768, max_output_tokens=8000,
            source="provider_catalog", confidence="verified",
            resolved_at=0.0, fallback_used=False)

        async def _cap(base_url, model, **kwargs):
            return capacity

        monkeypatch.setattr(_mcap, "resolve_capacity", _cap)
        llm = _MetadataLLM([_completion("готово")])
        svc = _make_service(llm=llm)
        text, _mode = await svc._l2_write_answer(
            CHAT, "вопрос", temperature=0.5,
            plan_block="<Response_Plan>тест</Response_Plan>",
            user_blocks=["<Current_Question>вопрос</Current_Question>"])
        assert text == "готово"
        from services.token_counter import count_tokens
        call = llm.calls_of("l2_writer")[0]
        expected_input = sum(count_tokens(str(m.get("content") or ""))
                             for m in call["messages"])
        assert call["max_output_tokens"] == min(8000, 32768 - expected_input)

    @pytest.mark.asyncio
    async def test_unknown_resource_sends_no_max_tokens_key(self):
        """Неизвестный ресурс (нет факта max_output) → None → ключ
        не отправляется; константа «для всех» не подставляется вместо факта."""
        llm = _MetadataLLM([_completion("готово")],
                           model="unknown-model-xyz", base_url="")
        svc = _make_service(llm=llm)
        text, _mode = await svc._l2_write_answer(
            CHAT, "вопрос", temperature=0.5,
            user_blocks=["<Current_Question>вопрос</Current_Question>"])
        assert text == "готово"
        assert llm.calls_of("l2_writer")[0]["max_output_tokens"] is None

    @pytest.mark.asyncio
    async def test_semantic_constants_are_not_sent(self):
        """UR-19.1/UR-19.2: активный вызов Writer'а не несёт 700/4096/16384
        как семантическую границу (инициативный 700 удалён)."""
        llm = _MetadataLLM([_completion("ok"), _completion("ok 2")])
        svc = _make_service(llm=llm)
        await svc._l2_write_answer(CHAT, "q", temperature=0.5,
                                   user_blocks=["<Current_Question>q</CQ>"])
        await svc._l2_write_answer(CHAT, "q", temperature=0.5,
                                   user_blocks=["<Current_Question>q</CQ>"],
                                   writer="initiative_writer")
        for call in llm.calls_of("l2_writer"):
            assert call["max_output_tokens"] not in (700, 4096, 16384)


# ── UR-18: LLMCompletion доезжает до Writer ──────────────────────────────────

class TestCompletionMetadata:
    @pytest.mark.asyncio
    async def test_length_finish_reason_continues_same_author(self):
        """UR-19.3: `finish_reason=length` → продолжение ТЕМ ЖЕ автором с
        уже полученным текстом (assistant-граница); план/адресат не меняются,
        склейка без потери слова и без повтора."""
        llm = _MetadataLLM([
            _completion("Прочитай раздел про алго", finish_reason="length"),
            _completion("ритмы поиска до конца.", finish_reason="stop"),
        ])
        svc = _make_service(llm=llm)
        text, _mode = await svc._l2_write_answer(
            CHAT, "о чём раздел?", temperature=0.5,
            user_blocks=["<Current_Question>о чём раздел?</CQ>"])
        assert text == "Прочитай раздел про алгоритмы поиска до конца."
        steps = [c["step"] for c in llm.calls]
        assert steps == ["l2_writer", "l2_continuation"], steps
        cont_messages = llm.calls[-1]["messages"]
        assert cont_messages[-2]["role"] == "assistant"
        assert "Прочитай раздел про алго" in cont_messages[-2]["content"]
        # Исходный контекст хода не меняется (план и факты те же).
        assert cont_messages[0] == llm.calls[0]["messages"][0]

    @pytest.mark.asyncio
    async def test_generate_stays_str_compatible(self):
        """UR-18: легаси `generate()` по-прежнему возвращает str."""
        llm = _MetadataLLM([_completion("текст")])
        result = await llm.generate([{"role": "user", "content": "q"}],
                                    step="l2_writer")
        assert isinstance(result, str) and result == "текст"

    @pytest.mark.asyncio
    async def test_fallback_keeps_finish_reason(self):
        """UR-18: fallback-нога не теряет finish_reason — метаданные читаются
        из фактического ответа последней ноги, попытка перехода видна."""
        client = LLMClient(
            base_url="https://primary.example/v1", api_key="k-primary",
            chat_model="mystery-large-1m", embed_model="text-embed",
            fallback_base_url="https://fallback.example/v1",
            fallback_api_key="k-fb", fallback_model="mystery-small-16k")
        assert client._fallback_active

        class _OkResponse:
            def __init__(self, content, reason):
                self._payload = {
                    "choices": [{"message": {"content": content},
                                 "finish_reason": reason}],
                    "usage": {"prompt_tokens": 10}}

            def json(self):
                return self._payload

        async def fail_primary(path, payload, **kwargs):
            raise LLMError("primary down")

        async def fb(payload, sent=None):
            return _OkResponse("ответ с fallback", "length")

        client._post_with_key = fail_primary
        client._fallback_with_retries = fb
        completion = await client.generate_with_metadata(
            [{"role": "user", "content": "q"}], step="l2_writer")
        assert completion.text == "ответ с fallback"
        assert completion.finish_reason == "length"
        assert completion.fallback_chain and \
            completion.fallback_chain[0].channel == "primary"


# ── UR-19.4 + UR-RES-05: обрубок не публикуется ──────────────────────────────

class TestNoPartialPublish:
    @pytest.mark.asyncio
    async def test_unfinished_initiative_not_published(
            self, monkeypatch, tmp_path):
        """Продолжение невозможно → честный отказ Writer'а → инициатива
        writer_failed, Telegram ничего не отправляет (частичный текст не
        уходит в чат, точки к обрезанному слову никто не дописывает)."""
        db = await _init_db(tmp_path, "ur_d_unfinished.db")
        try:
            intent_id, _row = await _make_intent(db)
            sent: list = []

            async def _send_text(bot, chat_id, text, *a, **kw):
                sent.append(text)
                return SimpleNamespace(message_id=8001)

            monkeypatch.setattr("services.telegram_send.send_text",
                                _send_text)
            llm = _MetadataLLM([
                _completion(_plan_json(), "stop"),          # L1-план
                _completion("Оборванный ответ про релиз",
                            finish_reason="length"),
                _completion("Оборванный ответ про релиз",
                            finish_reason="length"),        # без прогресса
            ])
            writer = _make_service(llm=llm)
            result = await dcs.handle_initiative(
                bot=_bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-d-unfinished", writer_service=writer)
            assert result["status"] == "writer_failed", result
            assert sent == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_length_answer_completed_before_sending(
            self, monkeypatch, tmp_path):
        """UR-19.4: восстанавливаемый length → продолжение ДО отправки,
        в чат уходит целостный ответ одним логическим сообщением."""
        db = await _init_db(tmp_path, "ur_d_completed.db")
        try:
            intent_id, _row = await _make_intent(db)
            sent: list = []

            async def _send_text(bot, chat_id, text, *a, **kw):
                sent.append(text)
                return SimpleNamespace(message_id=8002)

            monkeypatch.setattr("services.telegram_send.send_text",
                                _send_text)
            llm = _MetadataLLM([
                _completion(_plan_json(), "stop"),          # L1-план
                _completion("Первая половина ответа про",
                            finish_reason="length"),
                _completion(" релиз: всё готово.", finish_reason="stop"),
            ])
            writer = _make_service(llm=llm)
            result = await dcs.handle_initiative(
                bot=_bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-d-completed", writer_service=writer)
            assert result["status"] == "sent", result
            assert sent == ["Первая половина ответа про релиз: всё готово."]
        finally:
            await db.close()


# ── UR-19.5: чанкование без потери; первый chunk — reply ─────────────────────

class TestChunkedDelivery:
    def test_chunk_text_is_lossless_and_pure(self):
        """chunk_text не меняет текст: конкатенация воспроизводит исходник,
        каждый chunk в лимите Telegram; функция чистая."""
        body = " ".join(f"предложение номер {i} про релиз и погоду"
                        for i in range(300))
        chunks = mi.chunk_text(body)
        assert len(chunks) > 1
        assert "".join(chunks) == body
        assert all(len(c) <= mi.CHUNK_LIMIT for c in chunks)
        assert chunks == mi.chunk_text(body)

    @pytest.mark.asyncio
    async def test_first_chunk_bound_to_reply_others_not(
            self, monkeypatch, tmp_path):
        """L1D/UR-19.5: план delivery=reply с валидной целью → первый chunk
        с reply_to_message_id, остальные без привязки; конкатенация чанков —
        авторский текст без потерь/перестановок."""
        db = await _init_db(tmp_path, "ur_d_chunks.db")
        try:
            row_id = await db.save_smart_message(
                7, CHAT, "вопрос про релиз", None, int(time.time()),
                "text", "Дима", message_id=555)
            intent_id, _row = await _make_intent(db)
            sent: list = []

            async def _send_text(bot, chat_id, text, *a, **kw):
                sent.append({"text": text, **kw})
                return SimpleNamespace(message_id=8100 + len(sent))

            monkeypatch.setattr("services.telegram_send.send_text",
                                _send_text)
            long_answer = ("Ответ по релизу. " +
                           " ".join(f"пункт {i}: детали сборки и отката"
                                    for i in range(300)))
            assert len(long_answer) > mi.CHUNK_LIMIT
            llm = _FakeLLM(
                l1=_plan_json(delivery="reply",
                              target_message_id=row_id,
                              target_user_id=7),
                l2=long_answer)
            writer = _make_service(llm=llm)
            result = await dcs.handle_initiative(
                bot=_bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-d-chunks", writer_service=writer)
            assert result["status"] == "sent", result
            assert len(sent) > 1
            assert sent[0].get("reply_to_message_id") == 555
            for extra in sent[1:]:
                assert not extra.get("reply_to_message_id")
            delivered = "".join(item["text"] for item in sent)
            # Типографика style-pass не меняет слова/смысл (chunking не
            # является вторым автором).
            assert _words(delivered) == _words(long_answer)
        finally:
            await db.close()


# ── UR-05: граница отправки — не второй автор ────────────────────────────────

class TestDeliveryBoundary:
    @pytest.mark.asyncio
    async def test_sendrecheck_suppresses_send_after_answer(
            self, monkeypatch, tmp_path):
        """SendRecheck сохранён на едином пути Writer'а: «человек уже получил
        ответ» → отмена без отправки."""
        db = await _init_db(tmp_path, "ur_d_recheck.db")
        try:
            intent_id, _row = await _make_intent(db)
            await db.record_bot_output(
                chat_id=CHAT, bot_user_id=BOT_ID, tg_message_id=8001,
                output_kind="direct_reply", content_text="держи ответ",
                sent_at=int(time.time()), delivery_status="delivered")
            sent: list = []

            async def _send_text(bot, chat_id, text, *a, **kw):
                sent.append(text)
                return SimpleNamespace(message_id=8003)

            monkeypatch.setattr("services.telegram_send.send_text",
                                _send_text)
            llm = _FakeLLM(l1=_plan_json(), l2="ответ инициативы")
            writer = _make_service(llm=llm)
            result = await dcs.handle_initiative(
                bot=_bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-d-recheck", writer_service=writer)
            assert result["status"] == "cancelled"
            assert result["reason_code"] == "already_answered"
            assert sent == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_stale_target_cancels_semantic_reply(
            self, monkeypatch, tmp_path):
        """План просит reply человеку, цель недоступна → отмена БЕЗ отправки
        «того же текста в общий чат» (проверка target сохранена)."""
        db = await _init_db(tmp_path, "ur_d_target.db")
        try:
            intent_id, _row = await _make_intent(db)
            sent: list = []

            async def _send_text(bot, chat_id, text, *a, **kw):
                sent.append(text)
                return SimpleNamespace(message_id=8004)

            monkeypatch.setattr("services.telegram_send.send_text",
                                _send_text)
            missing_id = 10_000_000          # нет такого row в smart_messages
            llm = _FakeLLM(
                l1=_plan_json(delivery="reply",
                              target_message_id=missing_id,
                              target_user_id=7),
                l2="прямой ответ человеку")
            writer = _make_service(llm=llm)
            result = await dcs.handle_initiative(
                bot=_bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-d-target", writer_service=writer)
            assert result["status"] == "cancelled", result
            assert sent == []
        finally:
            await db.close()


# ── мутация: второй автор ловится счётчиком хода ─────────────────────────────

class TestSecondAuthorMutation:
    @pytest.mark.asyncio
    async def test_second_authoring_call_is_caught(self):
        """Мутация-доказательство: второй литературный вызов с тем же
        `author_state` хода даёт semantic_rewrite_count > 0 — второго автора
        невозможно скрыть от трассы хода (тот же механизм, что у Writer'а)."""
        from services.negative_constraints import verbalize_validated

        llm = _MetadataLLM([_completion("первый автор"),
                            _completion("второй автор")])
        correlation = "corr-ur-d-mutation"
        author_state = _ttrace.author_state(correlation)

        async def _generate(messages):
            return await llm.generate(messages, step="l2_writer")

        _text1, stats1 = await verbalize_validated(
            _generate, [{"role": "system", "content": "s"},
                        {"role": "user", "content": "q"}],
            max_retries=0, author_state=author_state)
        assert stats1["semantic_rewrite_count"] == 0, stats1
        _text2, stats2 = await verbalize_validated(
            _generate, [{"role": "system", "content": "s"},
                        {"role": "user", "content": "q"}],
            max_retries=0, author_state=author_state)
        # Мутация (второй автор в том же ходе) — ОБНАРУЖЕНА счётчиком.
        assert stats2["semantic_rewrite_count"] == 1, stats2
