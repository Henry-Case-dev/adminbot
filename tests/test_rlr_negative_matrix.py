# -*- coding: utf-8 -*-
"""RLR-07-PROOF — R-08.21: негативная матрица §8 на РЕАЛЬНЫХ гейтах.

Источник: `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md` §8
(негативные строки) и карта
`plans/features/remove-legacy-rephrasing/requirements-map.json`,
срез RLR-07-PROOF:

* R-08.6 (а) — «Вася не писал» / «писал» / «никогда не писал» /
  «не отказывался»: после L2 смысл не меняется ни regex, ни переписчиком,
  ни fallback-черновиком;
* R-08.7 (б) — «неделя», «небо», «немного», «не без таланта»: ретрая
  free-form ответа по лексическому правилу не возникает;
* R-08.8 (в) — несколько отрицаний / мат / сарказм: никаких post-L2
  semantic rewrites;
* R-08.9 (г) — неподтверждённый внешний факт при недоступном поиске: нет
  удаления предложения и нет post-L2 переписывания, L2 получает честный
  статус evidence ДО генерации;
* R-08.5 (д) — совпавший текст двух разных событий: два ответа, нет reroll;
  настоящая повторная доставка одного события заблокирована;
* R-08.18 (е) — `no_quotes`/`no_emoji`: ровно один механический проход,
  protected spans целы;
* R-08.19 (ж) — отправленная картинка/файл: второго текста от Writer нет,
  record/send/idempotency сохранены;
* R-08.16 (з) — HTML/Rich/plain fallback: один и тот же смысловой payload.

ОТЛИЧИЕ ОТ «мокированного happy path» (требование R-08.CFG): каждое
утверждение проходит через РЕАЛЬНЫЕ швы продакшена —
`DirectChatService.handle` (живой pipeline L1/L2), `negative_constraints`
(вербализатор/гарды), `evidence_policy` (политика + egress-наблюдение),
`style_policy` (реальный конфиг-слой `style.policy` через hot-кэш),
`response_freshness` + `SmartCache` (реальный SQLite), `telegram_send`
(реальная отправка). Мокаются только I/O-края: LLM-клиент (фейк,
считающий стадии), ввод контента, telegram-бот, провайдер картинки.
Реальные feature gates (mca_gates/settings) НЕ подменяются: их состояние
проверяется ассертом, чтобы «гейт случайно OFF» не выдавался за PASS.

ЧЕСТНАЯ ГРАНИЦА: живой прогон на реальном провайдере LLM/поиска и
сравнение `raw_final` ↔ Telegram-payload — это RLR-07/live-стадия
(отдельные прогоны), здесь — реальные внутренние швы на детерминированных
фейках моделей.

TEST-LIFECYCLE: CONTRACT + REGRESSION owner=RLR-07-PROOF
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from services import evidence_policy as evp
from services import hot_config as hot
from services import mca_events
from services import mca_gates
from services import negative_constraints as nc
from services import public_speech_guard as psg
from services import response_freshness as fresh
from services import style_policy as sp
from services.direct_chat_service import DirectChatService
from services.smart_cache import SmartCache
from services.summary_aliases import AliasResolver
from tests.test_asap7_direct_l1 import _FakeLLM, _FakeRouter, _drive, _plan_json
from tests.test_direct_chat import (
    CHAT_ID,
    FakeDB,
    FakeMemory,
    _bot,
    _message,
    _user,
)

pytestmark = [pytest.mark.system2, pytest.mark.asap3]


# ── инфраструктура ──────────────────────────────────────────────────────────


class StepLLM(_FakeLLM):
    """Фейк LLM со списком стадий: доказательство «0 лишних вызовов»."""

    def stages(self):
        return [c["step"] for c in self.calls]


@pytest.fixture(autouse=True)
def _self_awareness_off(monkeypatch):
    """Изоляция: фоновый экстрактор самоосознания не тратит вызовы LLM."""
    real = hot.get
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: False
        if key == "flags.bot_self_awareness_enabled"
        else real(key, default))


@pytest.fixture
def events(monkeypatch):
    """Наблюдаемый канал mca-13: перехват (event_name, outcome, fields)."""
    seen: list = []
    real = mca_events.emit_mca_event

    def spy(event_name, *, outcome, **fields):
        seen.append({"event_name": event_name, "outcome": outcome, **fields})
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
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", enabled)


def _drive_cached(monkeypatch, text, *, cache, llm, l1=True,
                  tool_router=None, message_id=100, chat_id=CHAT_ID):
    """`_drive` + реальный durable-кеш (для update-идемпотентности)."""
    import services.direct_chat_service as dcs
    from services.direct_chat_service import DirectChatService

    _set_l1(monkeypatch, l1)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    svc = DirectChatService(FakeMemory(), FakeDB(), llm, AliasResolver("{}"),
                            cache=cache, tool_router=tool_router)
    real_send = DirectChatService._send_direct_answer

    async def _send(bot, chat_id_arg, answer, reply_to=None, **kwargs):
        return await real_send(bot, chat_id_arg, answer, reply_to, **kwargs)

    # Счётчик доставок БЕЗ подмены поведения: внутри — реальный
    # `_send_direct_answer` (HTML/Rich/plain и чанкинг остаются продакшн).
    svc._send_direct_answer = AsyncMock(side_effect=_send)
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc.remember_bot_reply = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", AsyncMock())
    msg = _message(text=text, message_id=message_id, chat_id=chat_id)
    return svc, _bot(), msg, _user()


def _delivered(svc):
    """Текст, реально ушедший в доставку (единственный шов Direct-ответа)."""
    assert svc._send_direct_answer.await_count == 1, \
        svc._send_direct_answer.await_args_list
    return svc._send_direct_answer.await_args.args[2]


#: Закрытый набор ДЕТЕРМИНИРОВАННЫХ типографических замен реального
#: style-pass продакшена (factory-правила: тире и кавычки). Это НЕ смысловая
#: правка: слова, отрицания и порядок предложений не меняются.
_TYPOGRAPHIC_MAP = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"',
                                  "—": "-", "–": "-"})
_WORD_RE = re.compile(r"[а-яёa-z0-9]+")


def _assert_same_meaning(delivered: str, authored: str) -> None:
    """Тот же авторский текст: слова и отрицания целы, только типографика."""
    assert delivered in (authored, authored.translate(_TYPOGRAPHIC_MAP)), (
        f"смысловая правка готовой речи: {delivered!r} != {authored!r}")
    assert _WORD_RE.findall(delivered.casefold()) == \
        _WORD_RE.findall(authored.casefold())
    assert nc._negation_signature(delivered) == \
        nc._negation_signature(authored)


def _no_reroll(llm):
    """Ни одного шага «повтора/второго автора» в LLM-стадиях хода."""
    stages = [str(s) for s in llm.stages()]
    forbidden = {"duplicate_guard_retry", "freshness_retry", "form_retry",
                 "numeric_retry", "cliche_retry", "format_retry",
                 "metatext_retry", "stage1", "stage2"}
    assert forbidden.isdisjoint(set(stages)), stages


# ════════════════════════════════════════════════════════════════════════════
# (а) R-08.6 — отрицания: смысл после L2 не меняется
# ════════════════════════════════════════════════════════════════════════════

NEGATION_ANSWERS = (
    "Вася не писал мне вчера ни слова.",
    "Вася писал мне вчера, я ответил.",
    "Вася никогда не писал мне первым.",
    "Вася не отказывался от встречи.",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("l1", [False, True], ids=["l1_off", "l1_on"])
@pytest.mark.parametrize("answer", NEGATION_ANSWERS)
async def test_negation_semantics_delivered_unchanged(monkeypatch, events,
                                                      l1, answer):
    """(а) Готовая речь с отрицанием уходит без смысловой правки.

    Проверяются ВСЕ три запрещённых пути подмены смысла: regex-гард
    (`check_form_contract`), «переписчик» (второй литературный вызов) и
    fallback-черновик (`form_fallback`/`fallback_text`). Допустим только
    закрытый набор детерминированных типографических замен (тире/кавычки).
    """
    # Реальный гейт формы ВКЛЮЧЁН — значит отсутствие находки не «гейт OFF».
    assert mca_gates.postprocess_form_guard_enabled() is True
    form_checks: list = []
    real_check = nc.check_form_contract

    def spy_check(candidate, contract, **kwargs):
        form_checks.append(str(candidate))
        return real_check(candidate, contract, **kwargs)

    monkeypatch.setattr(nc, "check_form_contract", spy_check)

    llm = StepLLM(l1=_plan_json(), l2=answer, single=answer)
    svc, _react, bot, msg, user = _drive(monkeypatch, "что там по Васе?",
                                         l1=l1, llm=llm)
    await svc.handle(bot, msg, user)

    delivered = _delivered(svc)
    _assert_same_meaning(delivered, answer)     # ни одного изменённого слова
    assert form_checks == []                    # regex-гард к речи не применён
    assert "form_guard_rejected" not in _reasons(events, "direct_style_guard")
    _no_reroll(llm)
    # Никакого fallback-черновика: ровно один литературный вызов.
    assert len(llm.calls) == (2 if l1 else 1), llm.stages()


# ════════════════════════════════════════════════════════════════════════════
# (б) R-08.7 — «неделя/небо/немного/не без таланта»: нет ретрая по лексике
# ════════════════════════════════════════════════════════════════════════════

LEXICAL_TEXTS = (
    "Неделя выдалась тяжёлой, но мы справились.",
    "Небо сегодня немного серое.",
    "Он не без таланта, просто ленивый.",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("l1", [False, True], ids=["l1_off", "l1_on"])
@pytest.mark.parametrize("answer", LEXICAL_TEXTS)
async def test_lexical_negation_lookalikes_trigger_no_retry(monkeypatch, l1,
                                                            answer):
    """(б) Слова на «не-/ни-» без отрицания не запускают ни ретрай, ни повтор.

    Ключевое: закрытый список куэ-токенов (`_NEGATION_CUES`) не считает
    «неделя/небо/немного» отрицанием, а «не без таланта» — locked-пара
    двойного отрицания. Поэтому лексическое правило не может стать причиной
    повторной генерации free-form ответа.
    """
    assert mca_gates.postprocess_form_guard_enabled() is True
    # Реальное правило детектора: ни одного куэ-токена в этих словах.
    assert nc._negation_signature("неделя") == frozenset()
    assert nc._negation_signature("небо") == frozenset()
    assert nc._negation_signature("немного") == frozenset()
    assert nc._negation_signature("не без таланта") == frozenset()

    llm = StepLLM(l1=_plan_json(), l2=answer, single=answer)
    svc, _react, bot, msg, user = _drive(monkeypatch, "как прошла неделя?",
                                         l1=l1, llm=llm)
    await svc.handle(bot, msg, user)

    _assert_same_meaning(_delivered(svc), answer)
    _no_reroll(llm)
    assert len(llm.calls) == (2 if l1 else 1), llm.stages()


# ════════════════════════════════════════════════════════════════════════════
# (в) R-08.8 — несколько отрицаний / мат / сарказм: нет post-L2 rewrites
# ════════════════════════════════════════════════════════════════════════════

HARSH_ANSWERS = (
    "Не мог не сказать: нихрена себе, конечно «гениально», да?",
    "Я не то чтобы не согласен — просто это полная хуйня, и ты это знаешь.",
    "Ну да, конечно, «лучший план века». Сарказм, если что.",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("l1", [False, True], ids=["l1_off", "l1_on"])
@pytest.mark.parametrize("answer", HARSH_ANSWERS)
async def test_harsh_speech_is_not_rewritten_post_l2(monkeypatch, l1, answer):
    """(в) Мат/сарказм/двойные отрицания доставляются как написаны.

    Оба реальных наблюдателя (`negative_constraints` вербализатор и
    `public_speech_guard`) — ТОЛЬКО диагностика: ни вырезания слов, ни
    «приведения к форме», ни второго автора.
    """
    llm = StepLLM(l1=_plan_json(), l2=answer, single=answer)
    svc, _react, bot, msg, user = _drive(monkeypatch, "что скажешь по плану?",
                                         l1=l1, llm=llm)
    await svc.handle(bot, msg, user)

    _assert_same_meaning(_delivered(svc), answer)
    _no_reroll(llm)
    assert len(llm.calls) == (2 if l1 else 1), llm.stages()

    # Реальный outbound-наблюдатель: findings есть/нет — текст не меняется.
    obs = psg.guard_public_text(answer)
    assert obs.text == answer
    assert obs.changed is False


# ════════════════════════════════════════════════════════════════════════════
# (г) R-08.9 — неподтверждённый внешний факт при недоступном поиске
# ════════════════════════════════════════════════════════════════════════════

UNCONFIRMED_CLAIM = ("Модели GeForce RTX 9090 не существует, "
                     "её выпустили в 2026 году за 700$.")


@pytest.mark.asyncio
async def test_search_unavailable_honest_evidence_and_no_sentence_dropped(
        monkeypatch, events):
    """(г) Поиск недоступен → честный статус ДО генерации, ответ не режется.

    Проверяется реальный L1-путь: `run_tool_phase` с падающим поиском даёт
    `search_status=unavailable` и честные «ОГРАНИЧЕНИЯ» в payload Writer'а;
    затем egress-наблюдение (`evidence_policy.guard_egress`) фиксирует
    неподтверждённое утверждение, но доставленный текст остаётся прежним.
    """
    assert evp.egress_guard_enabled() is True          # реальный рубильник ON
    assert mca_gates.response_freshness_guard_enabled() is True

    # Наблюдаем сам egress-шов: вход/выход guard'а (правка текста видна).
    import services.direct_chat_service as dcs

    seam: list = []
    real_guard = dcs._run_evidence_egress_guard

    async def spy_guard(**kwargs):
        out = await real_guard(**kwargs)
        seam.append((kwargs.get("answer"), out[0]))
        return out

    monkeypatch.setattr(dcs, "_run_evidence_egress_guard", spy_guard)

    router = _FakeRouter(fail={"execute_web_search"})
    llm = StepLLM(
        l1=_plan_json(tool_policy="auto",
                      capabilities_needed=["web_search"]),
        l2=UNCONFIRMED_CLAIM)
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "проверь в интернете, есть ли RTX 9090",
        tool_router=router, llm=llm)
    await svc.handle(bot, msg, user)

    # Поиск реально пытались выполнить и он упал — статус честный.
    assert router.dispatched, router.dispatched
    assert "reply_search_evidence" in [e["event_name"] for e in events]
    search_events = [e for e in events
                     if e["event_name"] == "reply_search_evidence"]
    assert search_events[0]["source_ref_json"]["search_status"] == \
        "unavailable"
    assert search_events[0]["outcome"] == "failed"

    # Честный статус evidence дошёл до Writer'а ДО генерации.
    payload = "".join(str(m.get("content"))
                      for m in llm.last_messages("l2_writer"))
    assert "<Tool_Evidence>" in payload
    assert "СТАТУС ИНСТРУМЕНТОВ" in payload
    assert "не выполнился" in payload          # без «всё проверил, всё ок»
    assert "честно скажи, что эта часть недоступна" in payload

    # Утверждение доставлено КАК НАПИСАНО: ни одного вырезанного предложения.
    assert _delivered(svc) == UNCONFIRMED_CLAIM
    # ...и сам guard вернул РОВНО свой вход (никакой смысловой постцензуры).
    assert seam == [(UNCONFIRMED_CLAIM, UNCONFIRMED_CLAIM)], seam
    _no_reroll(llm)
    assert len(llm.calls) == 2, llm.stages()   # planner + writer, без второго

    # Egress-наблюдение сработало (код + место), но текст не изменился.
    egress = [e for e in events if e["event_name"] == "evidence_egress_check"]
    assert egress, [e["event_name"] for e in events]
    usage = egress[0]["usage_json"]
    assert usage["observed"] == 1
    assert usage["code"] == evp.GUARD_OBSERVED_UNVERIFIED
    assert egress[0]["reason_code"] == evp.REASON_EVIDENCE_CLAIM_OBSERVED
    assert usage["sentence_index"] == 0
    assert usage["char_end"] - usage["char_start"] == len(UNCONFIRMED_CLAIM)

# ════════════════════════════════════════════════════════════════════════════
# (д) R-08.5 — одинаковый текст двух СОБЫТИЙ: два ответа, без reroll
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_equal_text_two_events_two_answers_and_redelivery_blocked(
        tmp_path, monkeypatch, events):
    """(д) Совпадение текста — не повод переписать; тот же update — блок.

    Идемпотентность держится на идентичности Telegram-события
    (`response_freshness` + SQLite-маркер), а не на тексте: два РАЗНЫХ
    события законно получают одинаковый ответ и доставляют его как написан,
    а повторная доставка ОДНОГО события не отвечается вовсе.
    """
    assert mca_gates.response_freshness_guard_enabled() is True
    same = "Ну и что тут скажешь, всё как обычно."
    cache = SmartCache(str(tmp_path / "matrix_dedup.db"))
    llm = StepLLM(l1=_plan_json(), l2=same, single=same)
    svc, bot, msg1, user = _drive_cached(
        monkeypatch, "первый вопрос", cache=cache, llm=llm, l1=True,
        message_id=781, chat_id=-1009879)
    try:
        msg2 = _message(text="второй вопрос", message_id=782,
                        chat_id=-1009879)
        await svc.handle(bot, msg1, user)
        await svc.handle(bot, msg2, user)

        assert svc._send_direct_answer.await_count == 2
        first = svc._send_direct_answer.await_args_list[0].args[2]
        second = svc._send_direct_answer.await_args_list[1].args[2]
        assert first == second == same       # одинаковый текст законен
        _no_reroll(llm)
        assert llm.stages().count("l2_writer") == 2
        assert "direct_freshness_retry" not in [
            str(x) for x in _reasons(events, "DIRECT_FRESHNESS_RETRY")]

        # Настоящая повторная доставка ПЕРВОГО события — 0 LLM, 0 отправки.
        before = llm.stages().count("l2_writer")
        await svc.handle(bot, msg1, user)
        assert svc._send_direct_answer.await_count == 2
        assert llm.stages().count("l2_writer") == before
        assert "direct_update_dedup_hit" in _reasons(
            events, "DIRECT_UPDATE_DEDUP_HIT")
    finally:
        await cache.close()


# ════════════════════════════════════════════════════════════════════════════
# (е) R-08.18 — no_quotes/no_emoji: ровно один механический проход
# ════════════════════════════════════════════════════════════════════════════

OWNER_RULES_DOC = None


def _owner_rules_doc():
    """Реальный документ правил владельца (no_quotes + no_emoji)."""
    global OWNER_RULES_DOC
    if OWNER_RULES_DOC is None:
        OWNER_RULES_DOC = sp.build_document(rules=[
            {"id": "quotation_marks.hard.no_graphic",
             "kind": "quotation_marks", "strictness": "hard",
             "params": {"mode": "strip"},
             "conflict_strategy": "exempt_protected"},
            {"id": "emoji.hard.off", "kind": "emoji", "strictness": "hard",
             "params": {}, "conflict_strategy": "exempt_protected"},
        ])
    return OWNER_RULES_DOC


@pytest.mark.asyncio
async def test_owner_no_quotes_no_emoji_exactly_one_mechanical_pass(
        monkeypatch):
    """(е) Правила владельца применяются ОДИН раз и не ломают protected spans.

    Правила берутся из РЕАЛЬНОГО конфиг-слоя (`style.policy` в hot-кэше,
    как в проде), а не инъекцией policy-объекта. Второй проход — no-op,
    значит «единственный предсказуемый механический pass» достигнут, а не
    «повторяем, пока не станет красиво».
    """
    assert mca_gates.speech_style_policy_enabled() is True
    doc = _owner_rules_doc()

    class _Cfg:
        def get(self, key, default=None):
            return doc if key == sp.DOC_KEY else default

    passes: list = []
    real_apply = sp.apply_style_policy

    async def spy_apply(*args, **kwargs):
        passes.append(kwargs.get("stage"))
        return await real_apply(*args, **kwargs)

    hot.set_config_cache(_Cfg())
    monkeypatch.setattr(sp, "apply_style_policy", spy_apply)
    try:
        answer = ("🤖 Он сказал «привет», код `print(1)` и ссылка "
                  "https://example.org/a?b=1 — готово 👍")
        llm = StepLLM(l1=_plan_json(), l2=answer, single=answer)
        svc, _react, bot, msg, user = _drive(monkeypatch, "покажи код",
                                             l1=True, llm=llm)
        await svc.handle(bot, msg, user)

        assert passes.count("direct_pre_send") == 1     # ровно один проход
        delivered = _delivered(svc)
        # Правило владельца `no_quotes` (strip) РЕАЛЬНО сработало: кавычки не
        # просто нормализованы factory-правилом («» → ""), а убраны.
        assert not ({"«", "»", '"'} & set(delivered)), delivered
        assert "🤖" not in delivered and "👍" not in delivered
        # protected spans целы
        assert "`print(1)`" in delivered
        assert "https://example.org/a?b=1" in delivered
        _no_reroll(llm)

        # Повторный проход по реальной резолвнутой политике — no-op.
        policy = await sp.effective_style_policy(-1001234567890)
        second = await real_apply(delivered, policy=policy, chat_id=0,
                                  record=False)
        assert second.text == delivered
        assert second.repaired == 0
    finally:
        hot.set_config_cache(None)


# ════════════════════════════════════════════════════════════════════════════
# (ж) R-08.19 — отправленная картинка: второго текста от Writer'а нет
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tool_delivered_media_suppresses_second_text(tmp_path,
                                                           monkeypatch):
    """(ж) Картинка доставлена инструментом → ровно одно исходящее сообщение.

    Подменяется ТОЛЬКО провайдер генерации (`_fake_generator`), отправку фото
    делает реальный `telegram_send.send_photo`; подавление текста — реальная
    ветка `handle`. Идемпотентность (`record/send`) проверяется durable-
    маркером: повторная доставка того же update не даёт второго фото/текста.
    """
    from services.direct_chat_service import DirectChatService as _DCS
    from tests.test_direct_chat import _bot as _plain_bot
    from tests.test_direct_chat import _make_service
    from tests.test_p0_meme_image_only import _fake_generator, _patch_image_env
    from unittest.mock import MagicMock

    cache = SmartCache(str(tmp_path / "media_dedup.db"))
    hot_cfg = _patch_image_env(monkeypatch)
    bot = _plain_bot()
    calls: list = []

    async def _send_photo(*args, **kwargs):
        calls.append(("photo", kwargs))
        return SimpleNamespace(message_id=501)

    async def _send_message(*args, **kwargs):
        calls.append(("text", kwargs))
        return SimpleNamespace(message_id=502)

    bot.send_photo = AsyncMock(side_effect=_send_photo)
    bot.send_message = AsyncMock(side_effect=_send_message)
    monkeypatch.setattr("services.image_generation.generate_and_send",
                        _fake_generator(bot))

    llm = StepLLM(l1=_plan_json(), l2="ВНУТРЕННИЙ ТЕКСТ WRITER'А",
                  single="ВНУТРЕННИЙ ТЕКСТ WRITER'А")
    # Реальные пре-гейты (как в проде): не подменяем их, иначе изображение
    # никогда не запрашивается и тест доказывал бы пустоту.
    svc = _make_service(llm=llm, cache=cache, tool_router=MagicMock())
    user = _user()
    msg = _message(text="Бот, нарисуй мем про дедлайн", message_id=1101,
                   chat_id=-1009911)
    try:
        await svc.handle(bot, msg, user)
        assert [k for k, _ in calls] == ["photo"], calls   # ни одного текста
        assert "caption" not in calls[0][1]
        assert bot.send_message.await_count == 0

        # record/send/idempotency сохранены: update помечен durable-маркером.
        assert await fresh.check_update_seen(cache, -1009911, 1101,
                                             revision=1,
                                             user_id=user.id) is True

        # Повторная доставка того же события — без второго фото и без текста.
        await svc.handle(bot, _message(text="Бот, нарисуй мем про дедлайн",
                                       message_id=1101, chat_id=-1009911),
                         user)
        assert [k for k, _ in calls] == ["photo"], calls

        # Калибровка: обычный текстовый ход ТЕМ ЖЕ ботом всё равно отвечает
        # текстом — значит «ни одного текста» выше не артефакт наблюдения.
        await svc.handle(bot, _message(text="как дела?", message_id=1102,
                                       chat_id=-1009911), user)
        assert [k for k, _ in calls] == ["photo", "text"], calls
    finally:
        await cache.close()
        hot_cfg.set_config_cache(None)


# ════════════════════════════════════════════════════════════════════════════
# (з) R-08.16 — HTML / Rich / plain fallback: один смысловой payload
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_html_and_rich_fallback_keep_same_payload(monkeypatch):
    """(з) Битый HTML и неудачный Rich отдают ТОТ ЖЕ смысловой текст.

    Проверяется реальный `_send_direct_answer`: та же строка уходит plain,
    без потерь слов и без второй генерации.
    """
    from aiogram.exceptions import TelegramBadRequest
    from services import telegram_send as tg

    answer = "итог: <b>важно</b> и 5 < 7 & готово"

    async def _rich_fails(*args, **kwargs):
        raise RuntimeError("Bot API 10.1 недоступен")

    monkeypatch.setattr(tg, "send_rich_message", _rich_fails)

    # safe-HTML → TelegramBadRequest → plain тем же текстом
    html_calls: list = []

    class _HtmlBot:
        async def send_message(self, chat_id, text, **kwargs):
            html_calls.append({"text": text, **kwargs})
            if kwargs.get("parse_mode") == "HTML":
                raise TelegramBadRequest(method="sendMessage",
                                         message="can't parse entities")
            return SimpleNamespace(message_id=4242)

    result = await DirectChatService._send_direct_answer(
        _HtmlBot(), CHAT_ID, answer, None, lore=True)
    assert result == 4242
    assert len(html_calls) == 2
    assert html_calls[0]["parse_mode"] == "HTML"
    assert html_calls[0]["text"] != answer          # экранированная разметка
    assert html_calls[1]["text"] == answer          # тот же смысловой payload
    assert html_calls[1].get("parse_mode") != "HTML"

    # Rich fail → plain того же документа (без deep_research: HTML-ветка
    # иначе отправила бы экранированный текст раньше fallback'а).
    plain_calls: list = []

    class _RichBot:
        async def send_message(self, chat_id, text, **kwargs):
            plain_calls.append({"text": text, **kwargs})
            return SimpleNamespace(message_id=4343)

    rich_result = await DirectChatService._send_direct_answer(
        _RichBot(), CHAT_ID, answer, None, rich=True)
    assert rich_result == 4343
    assert plain_calls and plain_calls[0]["text"] == answer
    assert plain_calls[0].get("parse_mode") != "HTML"
