"""TR-FIX2 (живая приёмка 2.58.91, 19.10.2026) — reply-путь Direct:
MessageRef фото из ``reply_to_message`` и claim из replied-сообщения.

Контракт (evidence release-25891/acceptance, findings 3 и 5):

  (1) **reply-на-фото** («бот, прочитай надпись» на сообщение с фото):
      ``recognize_image`` обязан целиться в медиа replied-сообщения
      (``reply_to_message``), а не в текущее сообщение-вопрос. Та же
      последовательность (photo → текстовый ответ бота → reply к фото)
      даёт тот же результат и при «живом» id текущего сообщения (реальный
      Telegram) → неверный ref — свойство продукта, а не харнесса
      (в живом прогоне харнесс переиспользовал id ответа бота как id
      синтетического сообщения).
  (2) **reply-мета-вопрос** «бот, это правда?» → claim = текст
      replied-сообщения, target = replied-сообщение; envelope резолвится
      (``ready``), а не ``temporal_envelope_rejected``. «Как работает
      фактчек?» — НЕ референтный claim (подстановки нет).

TEST-LIFECYCLE: REGRESSION owner=TR-FIX2/live-25891 (findings 3/5)
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

import handlers.direct_chat as dc_mod
from services import capability_registry as caps
from services import hot_config as hot
from services import temporal_factcheck as tf
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from tests.test_asap8_v6_wc_direct_d04 import _Router
from tests.test_direct_chat import _message
from tests.test_mca20_integration_round1045 import FakeAggregator
from tests.test_soul1_capability_intent import _drive, _plan_json, _run

CHAT_ID = -1001234567890
BOT_ID = 12345
USER_ID = 990002001
PHOTO_ID = 700            # replied-фото (живой прогон: 1165606)
OTHER_PHOTO_ID = 640      # «своё» фото первого хода (живой прогон: 1165607)
BOT_REPLY_ID = 999        # id ответа бота (живой прогон: 1165613 = anchor)
FRESH_ID = 1000           # «живой» id нового сообщения (реальный Telegram)
CLAIM = "Вода закипает при 100 °C на уровне моря."
META_Q = "бот, это правда?"

_MEDIA_ATTRS = ("video", "video_note", "voice", "audio", "animation",
                "sticker", "document")


@pytest.fixture(autouse=True)
def _clean_state():
    caps.reset_cache()
    hot.set_config_cache(None)
    yield
    caps.reset_cache()
    hot.set_config_cache(None)
    dc_mod.setup_direct_chat(None, None, None)


def _neutralize_media(m, *, photo=None, caption=None):
    """Явные значения медиа-полей: MagicMock-автоатрибуты не должны
    выглядеть как «медиа есть» (прецедент test_addtr_entry_caption._msg)."""
    m.photo = photo
    m.caption = caption
    for name in _MEDIA_ATTRS:
        setattr(m, name, None)
    m.media_group_id = None
    m.forward_origin = None
    return m


def _photo_message(message_id, caption=None, text=None, user_id=USER_ID):
    m = MagicMock()
    m.message_id = message_id
    m.text = text
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.reply_to_message = None
    return _neutralize_media(m, photo=[MagicMock()], caption=caption)


def _text_message(message_id, text, reply_to=None, user_id=USER_ID):
    m = _message(text=text, message_id=message_id, chat_id=CHAT_ID)
    m.from_user.id = user_id
    m.reply_to_message = reply_to
    return _neutralize_media(m)


def _recognize_router():
    return _Router(outputs={"recognize_image": json.dumps(
        {"status": "disabled", "reason": "vision_rate_limited"},
        ensure_ascii=False)})


def _recognize_calls(router):
    return [d for d in router.dispatched if d["tool"] == "recognize_image"]


def _wire_handler(svc):
    dc_mod.setup_direct_chat(svc, BOT_ID, "test_bot")


# ── (1) reply-на-фото: цель = медиа replied-сообщения ───────────────────────


class TestReplyPhotoTarget:
    @pytest.mark.asyncio
    async def test_live_sequence_harness_message_id(self, monkeypatch):
        """Точная живая последовательность: фото → ответ бота → reply к фото
        (id текущего сообщения = id ответа бота, как у харнесса 2.58.91)."""
        router = _recognize_router()
        svc, _llm, bot, msg, user, _gen, _ann = _drive(
            monkeypatch, "бот, прочитай надпись",
            l1=_plan_json(capabilities_needed=["image_understanding"]),
            router=router)
        photo = _photo_message(PHOTO_ID)
        _neutralize_media(msg)
        msg.message_id = BOT_REPLY_ID
        msg.reply_to_message = photo
        await _run(svc, bot, msg, user)
        calls = _recognize_calls(router)
        assert len(calls) == 1, router.dispatched
        assert calls[0]["arguments"]["target"]["message_id"] == PHOTO_ID, (
            "цель reply-хода — медиа replied-сообщения, не текущее")

    @pytest.mark.asyncio
    async def test_live_sequence_fresh_message_id(self, monkeypatch):
        """Та же последовательность с «живым» id нового сообщения: цель —
        всё равно фото replied-сообщения (продукт, а не харнесс)."""
        router = _recognize_router()
        svc, _llm, bot, msg, user, _gen, _ann = _drive(
            monkeypatch, "бот, прочитай надпись",
            l1=_plan_json(capabilities_needed=["image_understanding"]),
            router=router)
        photo = _photo_message(PHOTO_ID)
        _neutralize_media(msg)
        msg.message_id = FRESH_ID
        msg.reply_to_message = photo
        await _run(svc, bot, msg, user)
        calls = _recognize_calls(router)
        assert len(calls) == 1, router.dispatched
        assert calls[0]["arguments"]["target"]["message_id"] == PHOTO_ID

    @pytest.mark.asyncio
    async def test_two_turn_live_sequence_own_photo_then_reply_other(
            self, monkeypatch):
        """Полная живая последовательность 2.58.91 двумя ходами (через 0h
        handler): (1) своё фото+подпись → цель = своё сообщение; (2) reply
        на ДРУГОЕ фото → цель = это фото (не «последнее медиа» и не текущее
        сообщение)."""
        router = _recognize_router()
        svc, _llm, bot, msg1, user, _gen, _ann = _drive(
            monkeypatch, "бот, что на картинке?",
            l1=_plan_json(capabilities_needed=["image_understanding"]),
            router=router)
        _wire_handler(svc)
        # ход 1: своё фото + подпись (own-media)
        msg1.text = None
        msg1.message_id = OTHER_PHOTO_ID
        msg1.reply_to_message = None
        _neutralize_media(msg1, photo=[MagicMock()],
                          caption="бот, что на картинке?")
        await dc_mod.direct_chat_handler(msg1, bot=bot)
        # ход 2: текстовый reply на ДРУГОЕ фото (id ответа бота — как в живом
        # прогоне, где харнесс переиспользовал id последнего ответа бота)
        photo2 = _photo_message(PHOTO_ID)
        msg2 = _text_message(BOT_REPLY_ID, "бот, прочитай надпись",
                             reply_to=photo2)
        await dc_mod.direct_chat_handler(msg2, bot=bot)
        calls = _recognize_calls(router)
        assert [c["arguments"]["target"]["message_id"] for c in calls] == [
            OTHER_PHOTO_ID, PHOTO_ID], router.dispatched


# ── (2) reply-фактчек: claim из replied-сообщения ──────────────────────────


class TestReplyFactcheckClaim:
    @pytest.mark.asyncio
    async def test_meta_question_claim_from_replied_message_ready(
            self, tmp_path):
        """Живой кейс CFG-06 (регистрированная цель, fidelity проду):
        reply «бот, это правда?» → claim = текст replied-сообщения,
        target = replied-сообщение → ready (а не rejected)."""
        from services.database import DatabaseService
        db = DatabaseService(str(tmp_path / "trfix2.db"))
        await db.initialize()
        try:
            await db.save_smart_message(
                USER_ID, CHAT_ID, CLAIM, None, int(time.time()), "text",
                "Acceptance", message_id=PHOTO_ID, origin_type="user")
            router = ToolRouter(ToolDeps(FakeAggregator(), MagicMock(),
                                         db=db, llm=None))
            ctx = ToolContext(
                CHAT_ID, META_Q, reply_to_message_id=FRESH_ID,
                reply_source_message_id=PHOTO_ID, reply_source_text=CLAIM)
            raw = await router.dispatch("fact_check", {
                "claim": META_Q,
                "target": {"chat_id": CHAT_ID, "message_id": FRESH_ID}}, ctx)
            payload = json.loads(raw)
            assert payload["status"] == "ready", payload
            assert payload["claim"] == CLAIM, payload
            stored = await db.get_factcheck_run(payload["run_id"])
            assert stored["target_tg_message_id"] == PHOTO_ID, stored
            assert stored["claim_text"] == CLAIM, stored
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_full_handle_reply_meta_question_envelope_ref(
            self, monkeypatch):
        """Сквозь реальный Direct-ход (L1 → simple_tools → единый пайплайн
        фактчека): дет. шаг и envelope несут claim/target replied-сообщения."""
        captured = {}

        async def _capture(db, ref, **kwargs):
            captured["ref"] = ref
            return None, "captured"

        monkeypatch.setattr(tf, "build_envelope", _capture)
        inner = ToolRouter(ToolDeps(FakeAggregator(), MagicMock(),
                                    db=None, llm=None))

        class _Rec:
            def __init__(self, inner_router):
                self.inner = inner_router
                self.calls = []

            async def dispatch(self, name, arguments, ctx):
                self.calls.append({"tool": name,
                                   "arguments": dict(arguments or {})})
                return await self.inner.dispatch(name, arguments, ctx)

        router = _Rec(inner)
        svc, _llm, bot, msg, user, _gen, _ann = _drive(
            monkeypatch, META_Q,
            l1=_plan_json(capabilities_needed=["fact_check"]),
            router=router)
        replied = _text_message(PHOTO_ID, CLAIM, user_id=USER_ID)
        _neutralize_media(msg)
        msg.message_id = FRESH_ID
        msg.reply_to_message = replied
        await _run(svc, bot, msg, user)
        fc = [c for c in router.calls if c["tool"] == "fact_check"]
        assert len(fc) == 1, router.calls
        # (a) дет. шаг уже несёт claim/target replied-сообщения
        assert fc[0]["arguments"]["claim"] == CLAIM, fc[0]
        assert fc[0]["arguments"]["target"]["message_id"] == PHOTO_ID, fc[0]
        # (b) единый пайплайн получил envelope-ссылку с той же целью
        ref = captured["ref"]
        assert ref.claim_text == CLAIM
        assert ref.target_tg_message_id == PHOTO_ID
        assert ref.trigger_tg_message_id == FRESH_ID

    def test_referential_claim_detector_boundary(self):
        """Референтные формы («это правда?», «проверь его слова», «не врёт?»)
        — да; «как работает фактчек?» и собственный claim («правда ли, что
        вода закипает при 100 °C…») — нет."""
        assert tf.is_referential_claim(META_Q) is True
        assert tf.is_referential_claim("бот, проверь его слова") is True
        assert tf.is_referential_claim("бот, не врёт?") is True
        assert tf.is_referential_claim("бот, это правда ли?") is True
        assert tf.is_referential_claim("бот, как работает фактчек?") is False
        assert tf.is_referential_claim(
            "бот, правда ли, что вода закипает при 100 °C?") is False
        assert tf.is_referential_claim(CLAIM) is False
        assert tf.is_referential_claim("") is False

    def test_derive_factcheck_step_no_substitution_for_feature_question(self):
        """«Как работает фактчек?» при reply-контексте: claim НЕ подменяется
        текстом reply (не референтный вопрос), цель — текущее сообщение."""
        from services import direct_execution as dx
        from services import direct_l1 as l1
        plan = l1.normalize_l1_plan({"action": "reply", "confidence": 0.9,
                                     "capabilities_needed": ["fact_check"]})
        ctx = ToolContext(CHAT_ID, "бот, как работает фактчек?",
                          reply_to_message_id=FRESH_ID,
                          reply_source_message_id=PHOTO_ID,
                          reply_source_text=CLAIM)
        steps, limitations = dx.derive_simple_steps(
            plan, query="бот, как работает фактчек?", ctx=ctx,
            announced={"fact_check"})
        assert [s["tool"] for s in steps] == ["fact_check"]
        assert steps[0]["arguments"]["claim"] == "бот, как работает фактчек?"
        assert steps[0]["arguments"]["target"]["message_id"] == FRESH_ID
        assert not limitations, limitations

    def test_derive_image_step_uses_media_target(self):
        """Дет. шаг image_understanding целится в разрешённую медиа-цель
        хода; без неё — паритет прежнего поведения (текущее сообщение)."""
        from services import direct_execution as dx
        from services import direct_l1 as l1
        plan = l1.normalize_l1_plan({"action": "reply", "confidence": 0.9,
                                     "capabilities_needed":
                                         ["image_understanding"]})
        ctx = ToolContext(CHAT_ID, "бот, прочитай надпись",
                          reply_to_message_id=FRESH_ID,
                          reply_source_message_id=PHOTO_ID,
                          media_target_message_id=PHOTO_ID)
        steps, _ = dx.derive_simple_steps(
            plan, query="бот, прочитай надпись", ctx=ctx,
            announced={"recognize_image"})
        assert steps[0]["arguments"]["target"] == {
            "chat_id": CHAT_ID, "message_id": PHOTO_ID}
        legacy = ToolContext(CHAT_ID, "бот, что на картинке?",
                             reply_to_message_id=OTHER_PHOTO_ID)
        steps2, _ = dx.derive_simple_steps(
            plan, query="бот, что на картинке?", ctx=legacy,
            announced={"recognize_image"})
        assert steps2[0]["arguments"]["target"] == {
            "chat_id": CHAT_ID, "message_id": OTHER_PHOTO_ID}
