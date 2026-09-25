"""A8 `telegram-reactions-round1026` (Эпик 3 Wave 5, §41/§44-механика,
ADR-1026-21 D1–D14).

Покрытие (T-3671…T-3680):
  * Исполнитель `react_moai` — единственный официальный `setMessageReaction`
    (SC-A8-01); аддитивная сигнатура, legacy-сайты байт-в-байт (D11).
  * Детерминированная карта `reason_code → эмодзи` (D1/D8): 😂/👍/🔥/🗿;
    🗿 — только дефолт/fallback; стандартный набор, одна реакция.
  * Доступность реактивно (D2): `REACTION_INVALID` → детерминированная
    альтернатива из `REACTION_FALLBACK_ORDER`; ≤2 попытки, затем тихий отказ;
    порядок фиксирован, без `random` (§52 п.21).
  * Таксономия ошибок (D5): закрытый enum 7 исходов, fail-silently; ни один
    исход не порождает текст (§41 `:5402`); R17-логи (id/enum/reason).
  * `TelegramRetryAfter`/429 — без повтора, `rate_limited` (D6).
  * Правильная цель (D4): trigger `message_id`; не `reply_to_id`/prev-bot;
    media-group — переданный id не подменяется (серверное «первое неудалённое»).
  * Интеграция T-3678: `CoordinatorDecision.reaction` реально доставляется в
    `set_message_reaction` (SC-A8-10).
  * Kill-switch `REACTION_MECHANICS_ENABLED` OFF → точный legacy 🗿 (D10).
  * Границы: канон 12, Δ DDL=0, Δ каталога=0 (473/430/448/102/100/21),
    прочие `react_moai`-сайты вне diff, `setMessageReaction` — один call-site.
"""
import dataclasses
import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config.settings import APP_VERSION, Settings
from services import param_catalog as pc
from services import smartmodule_utils as utils
from services.direct_chat_service import (
    REACTION_MOAI,
    REASON_EMOJI_REACTION,
    REASON_EMOTION,
    REASON_IMAGE_REACTION,
    REASON_LAUGHTER,
    _reaction_for_reason,
)
from services.smartmodule_utils import (
    MAX_REACTION_ATTEMPTS,
    REACTION_APPROVE,
    REACTION_DEFAULT,
    REACTION_FALLBACK_ORDER,
    REACTION_FIRE,
    REACTION_FORBIDDEN,
    REACTION_LAUGH,
    REACTION_MESSAGE_GONE,
    REACTION_OK,
    REACTION_OUTCOMES,
    REACTION_RATE_LIMITED,
    REACTION_SERVICE,
    REACTION_UNAVAILABLE,
    REACTION_UNKNOWN,
    STANDARD_REACTION_EMOJIS,
    _classify_reaction_error,
    _reaction_candidates,
    react_moai,
    reaction_mechanics_enabled,
)
from services.tool_schemas import TOOL_CALLING_TOOLS

ROOT = Path(__file__).resolve().parents[1]
CHAT_ID = -1001234567890
MSG_ID = 4242


# ── helpers ────────────────────────────────────────────────────────────────

def _bot():
    bot = AsyncMock()
    sent = MagicMock()
    sent.message_id = 999
    bot.send_message = AsyncMock(return_value=sent)
    bot.set_message_reaction = AsyncMock(return_value=True)
    return bot


def _bad(msg: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=None, message=msg)


def _retry() -> TelegramRetryAfter:
    return TelegramRetryAfter(method=None, message="flood", retry_after=5)


def _emojis(call) -> list[str]:
    return [r.emoji for r in call.kwargs["reaction"]]


def _drive(monkeypatch, text, *, reply=None, decision=True):
    """Мини-стенд direct-чата: реальный `react_moai` + spy
    `bot.set_message_reaction` (без подмены исполнителя)."""
    from tests.test_direct_chat import _bot as dc_bot, _make_service, _message, _user
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", decision)
    monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    svc = _make_service()
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc._send_direct_answer = AsyncMock(return_value=999)
    svc.remember_bot_reply = AsyncMock()
    msg = _message(text=text)
    if reply is not None:
        msg.reply_to_message = reply
    return svc, dc_bot(), msg, _user()


def _bot_photo_reply(message_id: int = 700):
    """Ответ бота с изображением (reply_to_bot + photo)."""
    m = MagicMock()
    m.message_id = message_id
    m.text = None
    m.from_user = MagicMock()
    m.from_user.id = 12345                      # bot_id из _make_service
    m.web_page = None
    for attr in ("video", "video_note", "voice", "audio", "animation",
                 "sticker", "document"):
        setattr(m, attr, None)
    m.photo = MagicMock()
    return m


# ── 1. Карта reason_code → эмодзи (D1/D8; T-3671/T-3674) ───────────────────

class TestReasonEmojiMap:
    def test_default_is_moai(self):
        assert REACTION_MOAI == REACTION_DEFAULT == "🗿"

    def test_standard_set_closed(self):
        assert STANDARD_REACTION_EMOJIS == {
            "🗿", "😂", "👍", "🔥"}
        assert len(STANDARD_REACTION_EMOJIS) == 4

    @pytest.mark.parametrize("reason,expected", [
        (REASON_IMAGE_REACTION, REACTION_LAUGH),
        (REASON_LAUGHTER, REACTION_LAUGH),
        (REASON_EMOJI_REACTION, REACTION_APPROVE),
        (REASON_EMOTION, REACTION_FIRE),
        (None, REACTION_MOAI),
        ("unknown_code", REACTION_MOAI),
    ])
    def test_map_is_deterministic(self, reason, expected, monkeypatch):
        monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", True)
        assert _reaction_for_reason(reason) == expected

    def test_map_flips_to_moai_when_off(self, monkeypatch):
        monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", False)
        for reason in (REASON_IMAGE_REACTION, REASON_LAUGHTER,
                       REASON_EMOJI_REACTION, REASON_EMOTION):
            assert _reaction_for_reason(reason) == REACTION_MOAI


# ── 2. Кандидаты/альтернативы (D3; SC-A8-04/-09) ──────────────────────────

class TestCandidates:
    def test_two_attempts_max(self):
        assert MAX_REACTION_ATTEMPTS == 2
        assert REACTION_FALLBACK_ORDER == (
            REACTION_LAUGH, REACTION_APPROVE, REACTION_FIRE, REACTION_DEFAULT)

    @pytest.mark.parametrize("primary,expected", [
        (REACTION_LAUGH, (REACTION_LAUGH, REACTION_APPROVE)),
        (REACTION_APPROVE, (REACTION_APPROVE, REACTION_LAUGH)),
        (REACTION_FIRE, (REACTION_FIRE, REACTION_LAUGH)),
        (REACTION_DEFAULT, (REACTION_DEFAULT, REACTION_LAUGH)),
        ("🧨", (REACTION_DEFAULT, REACTION_LAUGH)),   # вне набора → default
        (None, (REACTION_DEFAULT, REACTION_LAUGH)),
    ])
    def test_candidates_fixed_no_random(self, primary, expected):
        assert _reaction_candidates(primary) == expected


# ── 3. Доступность + fallback/отказ (§52 п.21; T-3673/T-3679) ─────────────

class TestAvailabilityFallback:
    @pytest.mark.asyncio
    async def test_preferred_rejected_then_alternative_sent(self):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=[_bad("Bad Request: REACTION_INVALID"), True])
        code = await react_moai(bot, CHAT_ID, MSG_ID,
                                reaction=REACTION_LAUGH,
                                reason_code=REASON_LAUGHTER)
        assert code == REACTION_OK
        assert bot.set_message_reaction.await_count == 2
        first, second = bot.set_message_reaction.await_args_list
        assert _emojis(first) == [REACTION_LAUGH]
        assert _emojis(second) == [REACTION_APPROVE]

    @pytest.mark.asyncio
    async def test_all_unavailable_silent_decline(self):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=_bad("Bad Request: REACTION_INVALID"))
        code = await react_moai(bot, CHAT_ID, MSG_ID,
                                reaction=REACTION_FIRE,
                                reason_code=REASON_EMOTION)
        assert code == REACTION_UNAVAILABLE
        assert bot.set_message_reaction.await_count == MAX_REACTION_ATTEMPTS
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_order_stable_across_runs(self):
        emojis = []
        for _ in range(25):
            bot = _bot()
            bot.set_message_reaction = AsyncMock(
                side_effect=[_bad("REACTION_INVALID"), True])
            await react_moai(bot, CHAT_ID, MSG_ID, reaction=REACTION_LAUGH)
            emojis.append(_emojis(bot.set_message_reaction.await_args)[0])
        assert emojis == [REACTION_APPROVE] * 25

    @pytest.mark.asyncio
    async def test_forbidden_stops_without_fallback(self):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=_bad("Bad Request: not enough rights"))
        code = await react_moai(bot, CHAT_ID, MSG_ID,
                                reaction=REACTION_LAUGH)
        assert code == REACTION_FORBIDDEN
        assert bot.set_message_reaction.await_count == 1


# ── 4. Таксономия ошибок (D5; T-3676/T-3680) ──────────────────────────────

class TestErrorTaxonomy:
    def test_closed_enum_seven(self):
        assert REACTION_OUTCOMES == {
            "ok", "unavailable", "forbidden", "message_gone", "service",
            "rate_limited", "unknown"}
        assert len(REACTION_OUTCOMES) == 7

    @pytest.mark.parametrize("msg,expected", [
        ("Bad Request: REACTION_INVALID", REACTION_UNAVAILABLE),
        ("Bad Request: not enough rights", REACTION_FORBIDDEN),
        ("Forbidden: CHAT_WRITE_FORBIDDEN", REACTION_FORBIDDEN),
        ("Bad Request: CHAT_ADMIN_REQUIRED", REACTION_FORBIDDEN),
        ("Forbidden: bot was blocked by the user", REACTION_FORBIDDEN),
        ("Bad Request: message to react not found", REACTION_MESSAGE_GONE),
        ("Bad Request: message not found", REACTION_MESSAGE_GONE),
        ("Bad Request: MESSAGE_ID_INVALID", REACTION_MESSAGE_GONE),
        ("Bad Request: can't react to this message type", REACTION_SERVICE),
        ("Bad Request: something else entirely", REACTION_UNKNOWN),
    ])
    def test_classification_table(self, msg, expected):
        assert _classify_reaction_error(_bad(msg)) == expected

    @pytest.mark.asyncio
    async def test_unexpected_exception_is_unknown_fail_silent(self):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(side_effect=RuntimeError("boom"))
        code = await react_moai(bot, CHAT_ID, MSG_ID, reaction=REACTION_LAUGH)
        assert code == REACTION_UNKNOWN
        bot.send_message.assert_not_called()


# ── 5. Rate limit: без повтора (D6; T-3680) ────────────────────────────────

class TestRateLimit:
    @pytest.mark.asyncio
    async def test_retryafter_no_retry_single_attempt(self):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(side_effect=_retry())
        code = await react_moai(bot, CHAT_ID, MSG_ID,
                                reaction=REACTION_LAUGH)
        assert code == REACTION_RATE_LIMITED
        assert bot.set_message_reaction.await_count == 1
        bot.send_message.assert_not_called()


# ── 6. Нет текста на ошибку (§41 `:5402`; T-3676/T-3679) ──────────────────

class TestNoTextOnError:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("error", [
        _bad("REACTION_INVALID"),
        _bad("not enough rights"),
        _bad("message to react not found"),
        _bad("can't react to this message type"),
        _retry(),
        RuntimeError("boom"),
    ])
    async def test_failure_never_sends_text(self, error):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(side_effect=error)
        code = await react_moai(bot, CHAT_ID, MSG_ID,
                                reaction=REACTION_LAUGH,
                                reason_code=REASON_LAUGHTER)
        assert code in REACTION_OUTCOMES and code != REACTION_OK
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_r17_safe(self, caplog):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=_bad("Bad Request: REACTION_INVALID"))
        with caplog.at_level(logging.WARNING, logger="services.smartmodule_utils"):
            await react_moai(bot, CHAT_ID, MSG_ID,
                             reaction=REACTION_LAUGH,
                             reason_code=REASON_LAUGHTER)
        records = [r for r in caplog.records
                   if "moai reaction failed" in r.getMessage()]
        assert records
        blob = records[-1].getMessage()
        assert "code=unavailable" in blob
        assert "reason=laughter" in blob
        assert str(MSG_ID) in blob
        assert "АХАХА" not in blob            # R17: контента сообщений нет


# ── 7. BACKWARD-COMPAT / OFF-ПАРИТЕТ (D10/D11; T-3671/T-3681) ──────────────

class TestLegacyParity:
    @pytest.mark.asyncio
    async def test_three_arg_legacy_fixed_moai_single_attempt(self):
        bot = _bot()
        code = await react_moai(bot, CHAT_ID, MSG_ID)
        assert code == REACTION_OK
        assert bot.set_message_reaction.await_count == 1
        assert _emojis(bot.set_message_reaction.await_args) == [REACTION_DEFAULT]
        assert bot.set_message_reaction.await_args.kwargs["is_big"] is False

    @pytest.mark.asyncio
    async def test_legacy_error_no_fallback(self):
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=_bad("Bad Request: REACTION_INVALID"))
        code = await react_moai(bot, CHAT_ID, MSG_ID)
        assert code == REACTION_UNAVAILABLE
        assert bot.set_message_reaction.await_count == 1

    @pytest.mark.asyncio
    async def test_off_killswitch_ignores_contextual_emoji(self, monkeypatch):
        monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", False)
        assert reaction_mechanics_enabled() is False
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=[_bad("REACTION_INVALID"), True])
        code = await react_moai(bot, CHAT_ID, MSG_ID,
                                reaction=REACTION_FIRE,
                                reason_code=REASON_EMOTION)
        # OFF → legacy: один вызов 🗿, без fallback-цепочки.
        assert code == REACTION_UNAVAILABLE
        assert bot.set_message_reaction.await_count == 1
        assert _emojis(bot.set_message_reaction.await_args) == [REACTION_DEFAULT]

    @pytest.mark.asyncio
    async def test_no_bot_or_no_message_id_noop(self):
        bot = _bot()
        assert await react_moai(None, CHAT_ID, MSG_ID) == REACTION_UNKNOWN
        assert await react_moai(bot, CHAT_ID, None) == REACTION_UNKNOWN
        bot.set_message_reaction.assert_not_called()


# ── 8. Детерминизм вариативности (D1/D3; T-3674/T-3680) ───────────────────

class TestDeterministicVariety:
    def test_same_reason_100_runs(self, monkeypatch):
        monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", True)
        assert len({_reaction_for_reason(REASON_LAUGHTER)
                    for _ in range(100)}) == 1

    def test_distinct_contexts_distinct_emojis(self, monkeypatch):
        monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", True)
        mapped = {
            _reaction_for_reason(REASON_IMAGE_REACTION),
            _reaction_for_reason(REASON_LAUGHTER),
            _reaction_for_reason(REASON_EMOJI_REACTION),
            _reaction_for_reason(REASON_EMOTION),
        }
        assert mapped == {REACTION_LAUGH, REACTION_APPROVE, REACTION_FIRE}

    def test_executor_has_no_random(self):
        src = (ROOT / "services" / "smartmodule_utils.py").read_text(
            encoding="utf-8")
        block = src[src.index("def _reaction_candidates"):
                    src.index("# Все кандидаты недоступны")]
        assert "random" not in block


# ── 9. Интеграция T-3678: доставка выбора A7 (SC-A8-10) ────────────────────

class TestDeliveryFromDecision:
    @pytest.mark.asyncio
    async def test_laughter_delivers_laugh_to_trigger(self, monkeypatch):
        svc, bot, msg, user = _drive(monkeypatch, "АХАХА")
        msg.message_id = 4242
        await svc.handle(bot, msg, user)
        assert bot.set_message_reaction.await_count == 1
        call = bot.set_message_reaction.await_args
        assert call.args[:2] == (msg.chat.id, 4242)
        assert _emojis(call) == [REACTION_LAUGH]
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_image_emoji_reply_delivers_approve(self, monkeypatch):
        # Одиночный эмодзи (не из _ACK_WORDS/смеха) в ответ на изображение
        # бота → reason `emoji_reaction` → 👍 (карта D1).
        svc, bot, msg, user = _drive(
            monkeypatch, "😀", reply=_bot_photo_reply())
        msg.message_id = 111
        await svc.handle(bot, msg, user)
        call = bot.set_message_reaction.await_args
        assert _emojis(call) == [REACTION_APPROVE]
        assert call.args[:2] == (msg.chat.id, 111)
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_image_laugh_delivers_laugh(self, monkeypatch):
        svc, bot, msg, user = _drive(
            monkeypatch, "АХАХА", reply=_bot_photo_reply())
        await svc.handle(bot, msg, user)
        assert _emojis(bot.set_message_reaction.await_args) == [REACTION_LAUGH]


# ── 10. Правильная цель + media-group (D4; §53 :5844; T-3675) ─────────────

class TestTargetCorrectness:
    @pytest.mark.asyncio
    async def test_reply_situation_targets_trigger_not_reply(self, monkeypatch):
        svc, bot, msg, user = _drive(
            monkeypatch, "АХАХА", reply=_bot_photo_reply(message_id=700))
        msg.message_id = 4242
        await svc.handle(bot, msg, user)
        call = bot.set_message_reaction.await_args
        assert call.args[:2] == (msg.chat.id, 4242)
        assert call.args[1] != 700

    @pytest.mark.asyncio
    async def test_media_group_id_not_rewritten(self, monkeypatch):
        # media-group: Telegram сам ставит на первое неудалённое сообщение;
        # код передаёт trigger-id без подмены (D4).
        svc, bot, msg, user = _drive(monkeypatch, "АХАХА")
        msg.message_id = 555
        msg.media_group_id = "grp-1"
        await svc.handle(bot, msg, user)
        assert bot.set_message_reaction.await_args.args[1] == 555

    @pytest.mark.asyncio
    async def test_integration_error_produces_no_text(self, monkeypatch):
        svc, bot, msg, user = _drive(monkeypatch, "АХАХА")
        bot.set_message_reaction = AsyncMock(
            side_effect=_bad("Bad Request: REACTION_INVALID"))
        await svc.handle(bot, msg, user)
        bot.send_message.assert_not_called()
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_log_has_no_user_content(self, monkeypatch, caplog):
        svc, bot, msg, user = _drive(monkeypatch, "АХАХА")
        bot.set_message_reaction = AsyncMock(
            side_effect=_bad("Bad Request: REACTION_INVALID"))
        with caplog.at_level(logging.WARNING):
            await svc.handle(bot, msg, user)
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert "АХАХА" not in blob
        bot.send_message.assert_not_called()


# ── 11. Границы / один call-site / прочие сайты (D11/D14; T-3672/T-3682) ──

class TestBoundaries:
    _HANDLER_SITES = (
        "handlers/youtube.py", "handlers/web.py", "handlers/search.py",
        "handlers/factcheck.py", "handlers/checkup.py",
    )
    _CALL_RE = re.compile(r"react_moai\((.*?)\)", re.S)

    def test_single_official_call_site(self):
        src = (ROOT / "services" / "smartmodule_utils.py").read_text(
            encoding="utf-8")
        assert src.count("await bot.set_message_reaction(") == 1
        dcs = (ROOT / "services" / "direct_chat_service.py").read_text(
            encoding="utf-8")
        assert "set_message_reaction" not in dcs

    def test_other_react_sites_untouched_legacy(self):
        for rel in self._HANDLER_SITES:
            src = (ROOT / rel).read_text(encoding="utf-8")
            calls = self._CALL_RE.findall(src)
            assert calls, rel
            for args in calls:
                assert "reaction=" not in args, (rel, args)
                assert "reason_code=" not in args, (rel, args)

    def test_direct_safety_net_calls_legacy(self):
        src = (ROOT / "services" / "direct_chat_service.py").read_text(
            encoding="utf-8")
        # safety-net: message.message_id без kwargs (вне direct-решения).
        assert src.count("await react_moai(bot, chat_id, message.message_id)") == 2

    def test_counts_unchanged(self):
        assert len(pc.REGISTRY) == 473
        assert len({f.name for f in dataclasses.fields(Settings)}) == 430
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 448
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21

    def test_canon_twelve_and_version(self):
        assert len(TOOL_CALLING_TOOLS) == 12
        assert APP_VERSION == "2.58.31"

    def test_kill_switch_env_only_not_catalog(self):
        assert "REACTION_MECHANICS_ENABLED" not in pc.REGISTRY
        assert "REACTION_MECHANICS_ENABLED" not in {
            f.name for f in dataclasses.fields(Settings)}

    def test_kill_switch_default_on(self, monkeypatch):
        monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", True)
        assert reaction_mechanics_enabled() is True
        monkeypatch.setattr(Settings, "REACTION_MECHANICS_ENABLED", False)
        assert reaction_mechanics_enabled() is False

    def test_no_ddl(self):
        for rel in ("services/smartmodule_utils.py",
                    "services/direct_chat_service.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            assert "CREATE TABLE" not in src
            assert "ALTER TABLE" not in src

    def test_a9_events_scope_reconciled(self):
        # A8 (ADR-1026-21) сам A9-события не реализовывал. A9 (ADR-1026-22
        # D5/D6) санкционированно добавляет `REACTION_SENT`/`MESSAGE_IGNORED`
        # в direct_chat_service через единую обёртку `emit_agentic_event`;
        # механика A8 (`smartmodule_utils.py`) A9-события НЕ содержит.
        smart = (ROOT / "services" / "smartmodule_utils.py").read_text(
            encoding="utf-8")
        for marker in ("REACTION_SENT", "MESSAGE_IGNORED",
                       "reaction_sent", "message_ignored"):
            assert marker not in smart, ("smartmodule_utils.py", marker)
        dcs = (ROOT / "services" / "direct_chat_service.py").read_text(
            encoding="utf-8")
        for marker in ("REACTION_SENT", "MESSAGE_IGNORED"):
            assert marker in dcs, ("direct_chat_service.py", marker)
