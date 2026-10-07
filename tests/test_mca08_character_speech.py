"""MCA-08 `mca-08-character-speech` — блоки A+B (T-4894…T-4902, ADR-1028-11).

Focused-контракты (без полного suite):
  * A (K1): read-side слои/приоритет §28.4; <Character_Rules> только с
    непустым persona-блоком; anti-generic (режимы/оффсеты не срезают
    владельческий блок); character_block у verbalizer; OFF-паритет.
  * B (K2): SpeechUnderstanding — фасад над `classify_speech_act` (второй
    классификатор не создаётся); clarify-матрица ask/assume/none; носитель
    <Speech_Understanding> в ответном пути; notable-события clarify.
  * T-4899: склейка mca-22 canonical envelope/reply/quote на прямом пути
    («почему?» под разными родителями → разный контекст; адресат не теряется).
  * T-4901: write-gate «шутка ≠ биография» на существующих контурах
    mca-04a/mca-22 (unit-матрица + интеграция `remember_user_fact`).

R17: в события/логи — только коды/флаги/числа; тестовые строки синтетические.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from config.settings import settings
from services import bot_persona
from services import claim_envelope as ce
from services import mca_gates
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver
from services.summary_memory import MemoryManager
from tests.test_direct_chat import (
    CHAT_ID,
    FakeLLM,
    _bot,
    _force_persona_flag,
    _force_self_awareness,
    _make_service,
    _message,
)


@pytest.fixture(autouse=True)
def _self_awareness_off(monkeypatch):
    """Изоляция: фоновый self-awareness-экстрактор иначе добавляет LLM-вызов."""
    _force_self_awareness(monkeypatch, False)


def _gates(monkeypatch, *, layers: bool, speech: bool) -> None:
    monkeypatch.setattr(mca_gates, "character_layers_enabled",
                        lambda: layers)
    monkeypatch.setattr(mca_gates, "character_speech_enabled",
                        lambda: speech)


def _persona_patch(monkeypatch, *, name="Костик", biography="дворовый кот",
                   overrides="циник", aware=True,
                   traits=("шутит про грибы",)):
    async def _resolve(chat_id):
        return bot_persona.BotPersona(name=name, biography=biography,
                                      overrides=overrides, is_aware_ai=aware,
                                      is_global=True)

    async def _traits(limit=50, chat_id=None):
        return [{"text": t} for t in traits]

    monkeypatch.setattr(bot_persona, "resolve_bot_persona", _resolve)
    monkeypatch.setattr(bot_persona, "get_traits", _traits)


def _persona_block(name="Костик", biography="дворовый кот", overrides="циник",
                   aware=True, traits=("шутит про грибы",)):
    return bot_persona.build_persona_prompt_block(
        bot_persona.BotPersona(name=name, biography=biography,
                               overrides=overrides, is_aware_ai=aware,
                               is_global=True),
        list(traits), enabled=True)


async def _db(tmp_path, name="mca08.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add(db, user_id, text, tg_id, *, reply_to=None,
               reply_author=None, quote_text=None, quote_author=None,
               author_name=""):
    from services import message_identity
    await message_identity.save_live_message(
        db, chat_id=CHAT_ID, user_id=user_id, text=text, timestamp=1000,
        sent_at=1000, ingested_at=1000, author_name=author_name,
        tg_message_id=tg_id, reply_to_id=reply_to,
        reply_to_author_id=reply_author, quote_text=quote_text,
        quote_author_id=quote_author)


class _Msg:
    """Минимальный message-двойник (message_id/chat.id/text/reply)."""

    def __init__(self, message_id=100, chat_id=CHAT_ID, text="почему?",
                 reply=None):
        self.message_id = message_id
        self.chat = type("Chat", (), {"id": chat_id, "type": "supergroup"})()
        self.text = text
        self.reply_to_message = reply


# ── A: read-side слои (T-4894) ──────────────────────────────────────────────

class TestReadSideLayers:
    def test_precedence_canon_28_4(self):
        assert bot_persona.CHARACTER_LAYERS == (
            "owner_core", "owner_style", "derived_traits")
        # ядро владельца выше любой просьбы; просьба выше динамики;
        # состояние — последнее (§28.4).
        assert bot_persona.CHARACTER_PRECEDENCE == (
            "owner_core", "owner_style", "scoped_request", "derived_traits",
            "state")

    @pytest.mark.asyncio
    async def test_resolve_context_fail_open_no_pg(self):
        bot_persona.reset_persona_pool()
        ctx = await bot_persona.resolve_character_context(CHAT_ID)
        assert ctx.persona.is_empty
        assert ctx.traits == ()
        assert ctx.traits_scope == "global"

    @pytest.mark.asyncio
    async def test_resolve_context_reads_persona_and_traits(self, monkeypatch):
        _persona_patch(monkeypatch)
        ctx = await bot_persona.resolve_character_context(CHAT_ID)
        assert ctx.persona.name == "Костик"
        assert ctx.traits == ("шутит про грибы",)
        assert ctx.traits_scope == "global"      # шов mca-18: общий пул

    def test_public_signatures_mca18_compatible(self):
        # сигнатуры не меняются (совместимость с mca-18 / AMEND).
        assert list(inspect.signature(
            bot_persona.resolve_bot_persona).parameters) == ["chat_id"]
        params = inspect.signature(bot_persona.get_traits).parameters
        assert list(params) == ["limit", "chat_id"]
        assert params["limit"].default == 50
        assert params["chat_id"].default is None


# ── A: врезка в ответные пути (T-4895/T-4896) ───────────────────────────────

class TestCharacterRulesInDirect:
    @pytest.mark.asyncio
    async def test_rules_rendered_with_nonempty_persona(self, monkeypatch):
        from config.settings import Settings
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        # MCA-23: байт-паритет этого теста — про MCA-08 слои; план OFF.
        monkeypatch.setattr(Settings, "DIRECT_RESPONSE_PLAN_ENABLED", False,
                            raising=False)
        _force_persona_flag(monkeypatch, True)
        _persona_patch(monkeypatch)
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="расскажи о себе", message_id=91)
        await svc.handle(_bot(), msg, msg.from_user)
        assert llm.messages[0]["content"] == (
            CHAT_SYSTEM_PROMPT + "\n\n" + _persona_block() + "\n\n"
            + bot_persona.build_character_rules_block())

    @pytest.mark.asyncio
    async def test_empty_persona_no_rules_parity(self, monkeypatch):
        from config.settings import Settings
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        # MCA-23: байт-паритет этого теста — про MCA-08 слои; план OFF.
        monkeypatch.setattr(Settings, "DIRECT_RESPONSE_PLAN_ENABLED", False,
                            raising=False)
        _force_persona_flag(monkeypatch, True)
        _persona_patch(monkeypatch, name="", biography="", overrides="",
                       traits=())
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="привет", message_id=92)
        await svc.handle(_bot(), msg, msg.from_user)
        # пустая персона/пустые traits → ни Persona, ни Character_Rules
        assert llm.messages[0]["content"] == CHAT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_k1_off_byte_parity(self, monkeypatch):
        from config.settings import Settings
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        # MCA-23: байт-паритет этого теста — про MCA-08 слои; план OFF.
        monkeypatch.setattr(Settings, "DIRECT_RESPONSE_PLAN_ENABLED", False,
                            raising=False)
        _force_persona_flag(monkeypatch, True)
        _persona_patch(monkeypatch)
        _gates(monkeypatch, layers=False, speech=False)
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="расскажи о себе", message_id=93)
        await svc.handle(_bot(), msg, msg.from_user)
        # ровно прежние байты 2.58.54: персона-блок без правил/речи
        assert llm.messages[0]["content"] == (
            CHAT_SYSTEM_PROMPT + "\n\n" + _persona_block())

    def test_anti_generic_modes_keep_character_tail(self):
        from services.prompt_style_blocks import compose_verbalizer_system
        block = _persona_block() + "\n\n" \
            + bot_persona.build_character_rules_block()
        for mode in ("casual", "serious", "deep_research"):
            text = compose_verbalizer_system("BASE", mode, "plain",
                                             character_block=block)
            assert text.endswith(block)         # хвост не срезан режимом
            assert "<Character_Rules>" in text
            assert "Своё мнение" in text

    @pytest.mark.asyncio
    async def test_verbalizer_character_block_forwarded(self, monkeypatch):
        from services.chat_prompts import DIRECT_VERBALIZER_SYSTEM_PROMPT
        from services.prompt_style_blocks import compose_verbalizer_system
        from tests.test_direct_two_call_round1022 import _SYNTH_JSON, \
            _tool_raw
        svc = DirectChatService.__new__(DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "ответ"])
        block = _persona_block()
        await svc._synthesize_direct_answer(
            CHAT_ID, "q", _tool_raw(), None, character_block=block)
        stage2 = svc.llm.generate.await_args_list[1].args[0]
        assert stage2[0]["content"] == compose_verbalizer_system(
            DIRECT_VERBALIZER_SYSTEM_PROMPT, "", "plain",
            character_block=block)

    @pytest.mark.asyncio
    async def test_verbalizer_default_parity(self):
        from services.chat_prompts import DIRECT_VERBALIZER_SYSTEM_PROMPT
        from services.prompt_style_blocks import compose_verbalizer_system
        from tests.test_direct_two_call_round1022 import _SYNTH_JSON, \
            _tool_raw
        svc = DirectChatService.__new__(DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "ответ"])
        await svc._synthesize_direct_answer(CHAT_ID, "q", _tool_raw(), None)
        stage2 = svc.llm.generate.await_args_list[1].args[0]
        assert stage2[0]["content"] == compose_verbalizer_system(
            DIRECT_VERBALIZER_SYSTEM_PROMPT, "", "plain")

    def test_character_rules_canon_text(self):
        rules = bot_persona.build_character_rules_block()
        assert rules.startswith("<Character_Rules>\n")
        assert rules.endswith("\n</Character_Rules>")
        # канон §4: мнение помечается; события/люди — только по материалам.
        assert "мнение" in rules and "факт" in rules
        assert "материал" in rules
        assert "выдумывай" in rules


# ── B: SpeechUnderstanding — канон и clarify-матрица (T-4898/T-4900) ────────

class TestSpeechFacade:
    def test_inactive_signal_renders_nothing(self):
        u = ce.build_speech_understanding("привет, бот", is_group=True)
        assert not u.active
        assert ce.render_speech_block(u) == ""

    def test_quote_marker_renders_quote_rule(self):
        u = ce.build_speech_understanding(
            "> он вчера уехал\nи что", is_group=True)
        assert u.quote is True
        block = ce.render_speech_block(u)
        assert block.startswith("<Speech_Understanding>")
        assert "не приписывай" in block

    def test_quote_phrase_classified(self):
        u = ce.build_speech_understanding(
            "по словам Васи, я был в отпуске", is_group=True)
        assert u.speech_act == ce.SPEECH_ACT_QUOTE
        assert u.quote is True

    def test_tg_quote_presence_from_bundle(self):
        # native TG-цитата: наличие/автор приходят из mca-22-контура
        u = ce.build_speech_understanding(
            "и что", is_group=True, quote_text_present=True,
            quote_attribution_known=True)
        assert u.quote is True
        assert u.quote_attribution == ce.QUOTE_ATTRIBUTION_KNOWN
        assert "не приписывай" in ce.render_speech_block(u)

    def test_joke_not_biography(self):
        u = ce.build_speech_understanding(
            "шучу, я вчера был на Марсе", is_group=True)
        assert u.humor_risk is True
        assert u.speech_act == ce.SPEECH_ACT_JOKE_CANDIDATE
        assert "биографический факт" in ce.render_speech_block(u)

    def test_negation_literal(self):
        u = ce.build_speech_understanding(
            "я не был на встрече", is_group=True)
        assert u.negation is True
        assert "отрицание" in ce.render_speech_block(u)

    def test_deny_act_is_negation(self):
        u = ce.build_speech_understanding(
            "я не говорил, что был на встрече", is_group=True)
        assert u.speech_act == ce.SPEECH_ACT_DENY
        assert u.negation is True

    def test_render_cap_and_no_raw_text(self):
        u = ce.build_speech_understanding(
            "> цитата\nшучу, я не был дома", is_group=True)
        assert u.quote and u.humor_risk and u.negation
        block = ce.render_speech_block(u)
        assert len(block) <= 500
        assert "цитата" not in block and "дома" not in block  # R17-safe

    def test_clarify_matrix(self):
        ask = ce.clarify_action(short_dependency=True, has_reply_parent=False,
                                is_group=True)
        assert ask == ce.CLARIFY_ASK
        # ЛС — не материално
        assert ce.clarify_action(short_dependency=True, has_reply_parent=False,
                                 is_group=False) == ce.CLARIFY_NONE
        # reply-родитель (человек) — не материално
        assert ce.clarify_action(short_dependency=True, has_reply_parent=True,
                                 is_group=True) == ce.CLARIFY_NONE
        # anti-loop: родитель — вопрос бота → assume, без повторного вопроса
        assert ce.clarify_action(
            short_dependency=True, has_reply_parent=True, is_group=True,
            reply_parent_from_bot=True,
            reply_parent_ends_with_question=True) == ce.CLARIFY_ASSUME
        # не короткая/не зависимая
        assert ce.clarify_action(short_dependency=False, has_reply_parent=False,
                                 is_group=True) == ce.CLARIFY_NONE

    @pytest.mark.parametrize("text,expected", [
        ("почему?", ce.CLARIFY_ASK),
        ("зачем", ce.CLARIFY_ASK),
        ("а как?", ce.CLARIFY_ASK),
        ("и что мне теперь делать", ce.CLARIFY_NONE),   # >3 слов
        ("как дела?", ce.CLARIFY_NONE),                 # не маркер
        ("! почему", ce.CLARIFY_NONE),                  # команда (D7)
    ])
    def test_short_dependency_closed_markers(self, text, expected):
        u = ce.build_speech_understanding(text, is_group=True)
        assert u.clarify == expected

    def test_ask_instruction_bounded_single_question(self):
        u = ce.build_speech_understanding("почему?", is_group=True)
        block = ce.render_speech_block(u)
        assert "ровно ОДИН" in block

    def test_flags_are_codes_only(self):
        u = ce.build_speech_understanding(
            "> он уехал", is_group=True, quote_attribution_known=True)
        assert "quote_attribution:known" in u.flags
        assert all(" " not in f for f in u.flags)

    def test_no_second_classifier_or_resolver(self):
        src = inspect.getsource(ce.build_speech_understanding)
        assert "classify_speech_act" in src
        assert "quote_resolver" not in src
        assert "resolve_quote" not in src


# ── B: врезка в direct-путь (T-4898/T-4900) ─────────────────────────────────

class TestSpeechInDirectPath:
    @pytest.mark.asyncio
    async def test_speech_block_rendered_on_negation(self, monkeypatch):
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="я не был на встрече", message_id=94)
        await svc.handle(_bot(), msg, msg.from_user)
        system = llm.messages[0]["content"]
        assert system.startswith(CHAT_SYSTEM_PROMPT)
        assert "<Speech_Understanding>" in system
        assert "не переворачивай" in system
        # пустая персона → правил характера нет
        assert "<Character_Rules>" not in system

    @pytest.mark.asyncio
    async def test_no_speech_block_on_plain_message(self, monkeypatch):
        from config.settings import Settings
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        # MCA-23: байт-паритет этого теста — про MCA-08 слои; план OFF.
        monkeypatch.setattr(Settings, "DIRECT_RESPONSE_PLAN_ENABLED", False,
                            raising=False)
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="привет, бот", message_id=95)
        await svc.handle(_bot(), msg, msg.from_user)
        assert llm.messages[0]["content"] == CHAT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_k2_off_byte_parity(self, monkeypatch):
        from config.settings import Settings
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        # MCA-23: байт-паритет этого теста — про MCA-08 слои; план OFF.
        monkeypatch.setattr(Settings, "DIRECT_RESPONSE_PLAN_ENABLED", False,
                            raising=False)
        _gates(monkeypatch, layers=True, speech=False)
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="я не был на встрече", message_id=96)
        await svc.handle(_bot(), msg, msg.from_user)
        assert llm.messages[0]["content"] == CHAT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_clarify_event_asked(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = []
        monkeypatch.setattr(
            dcs._mca_events, "emit_mca_event",
            lambda name, **kw: calls.append({"event_name": name, **kw}))
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="почему?", message_id=97)
        await svc.handle(_bot(), msg, msg.from_user)
        assert any(c.get("event_name") == "speech_understanding"
                   and c.get("reason_code") == "clarification_asked"
                   for c in calls)

    @pytest.mark.asyncio
    async def test_clarify_event_assumption_anti_loop(self, monkeypatch):
        import services.direct_chat_service as dcs
        calls = []
        monkeypatch.setattr(
            dcs._mca_events, "emit_mca_event",
            lambda name, **kw: calls.append({"event_name": name, **kw}))
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        reply = MagicMock()
        reply.from_user = MagicMock()
        reply.from_user.id = 12345              # bot_id из _make_service
        reply.text = "Ты уверен?"
        msg = _message(text="почему?", message_id=98)
        msg.reply_to_message = reply
        await svc.handle(_bot(), msg, msg.from_user)
        system = llm.messages[0]["content"]
        assert "явным допущением" in system      # assume, не вопрос
        assert any(c.get("reason_code") == "clarification_assumption_used"
                   for c in calls)

    @pytest.mark.asyncio
    async def test_private_dm_no_clarify(self, monkeypatch):
        llm = FakeLLM(text="ок")
        svc = _make_service(llm=llm)
        msg = _message(text="почему?", message_id=99)
        msg.chat.type = "private"
        await svc.handle(_bot(), msg, msg.from_user)
        assert "<Speech_Understanding>" not in llm.messages[0]["content"]


# ── T-4899: canonical envelope/reply/quote на прямом пути ───────────────────

class TestReplyStitchingDirect:
    @pytest.mark.asyncio
    async def test_same_question_different_parents(self, tmp_path):
        """«почему?» под разными родителями → разные branch-блоки и
        reply_addressee (A04/A07 на прямом пути; без второго резолвера)."""
        db = await _db(tmp_path, "a04.db")
        svc = DirectChatService(memory=_FakeMemory(), db=db, llm=None,
                                aliases=AliasResolver("{}"), bot_id=42)
        await _add(db, 2, "родитель два", 300, author_name="Б")
        await _add(db, 3, "родитель три", 301, author_name="В")
        await _add(db, 1, "почему?", 501, reply_to=300, reply_author=2,
                   author_name="А")
        await _add(db, 1, "почему?", 502, reply_to=301, reply_author=3,
                   author_name="А")

        blocks_a = await svc._build_user_content(
            CHAT_ID, _Msg(501, text="почему?", reply=object()), "Аня", 1)
        blocks_b = await svc._build_user_content(
            CHAT_ID, _Msg(502, text="почему?", reply=object()), "Аня", 1)
        branch_a = [b for b in blocks_a
                    if b.startswith("<Conversation_Branch>")]
        branch_b = [b for b in blocks_b
                    if b.startswith("<Conversation_Branch>")]
        assert branch_a and branch_b and branch_a != branch_b
        assert "tg:300" in branch_a[0] and "tg:301" not in branch_a[0]
        assert "tg:301" in branch_b[0] and "tg:300" not in branch_b[0]

        bundle_a = await svc._build_evidence_bundle(
            CHAT_ID, _Msg(501, text="почему?", reply=object()), "почему?",
            "Аня", 1, blocks_a)
        bundle_b = await svc._build_evidence_bundle(
            CHAT_ID, _Msg(502, text="почему?", reply=object()), "почему?",
            "Аня", 1, blocks_b)
        assert bundle_a.reply_addressee == "2"
        assert bundle_b.reply_addressee == "3"
        assert bundle_a.direct_addressee == bundle_b.direct_addressee == "bot"
        assert bundle_a.context_version != bundle_b.context_version
        await db.close()

    @pytest.mark.asyncio
    async def test_quote_not_attributed_to_sender(self, tmp_path):
        """A07: цитата третьего лица не приписывается отправителю."""
        db = await _db(tmp_path, "a07.db")
        svc = DirectChatService(memory=_FakeMemory(), db=db, llm=None,
                                aliases=AliasResolver("{}"), bot_id=42)
        await _add(db, 2, "уехал в отпуск", 600, author_name="Б")
        await _add(db, 1, "> уехал в отпуск\nи что", 601,
                   reply_to=600, reply_author=2, quote_text="уехал в отпуск",
                   quote_author=2, author_name="А")
        msg = _Msg(601, text="> уехал в отпуск\nи что", reply=object())
        blocks = await svc._build_user_content(CHAT_ID, msg, "Аня", 1)
        bundle = await svc._build_evidence_bundle(
            CHAT_ID, msg, "> уехал в отпуск\nи что", "Аня", 1, blocks)
        assert bundle.author == "1"
        assert bundle.quoted_speaker == "2"     # автор цитаты ≠ sender
        await db.close()


class _FakeMemory:
    def __init__(self, window=()):
        self.window = list(window)

    async def get_window_messages(self, chat_id):
        return self.window


# ── T-4901: write-gate «шутка ≠ биография» ─────────────────────────────────

class TestWriteGateJokeNotBiography:
    @pytest.mark.parametrize("text,outcome,reason", [
        ("шучу, я вчера был на Марсе", ce.OUTCOME_REJECTED,
         "gated_speech_act:joke_candidate"),
        ("ну да, я великий спортсмен))", ce.OUTCOME_REJECTED, None),
        ("я не говорил, что был на встрече", ce.OUTCOME_REJECTED,
         "negation_guard"),
        ("ты был на встрече?", ce.OUTCOME_REJECTED,
         "gated_speech_act:question"),
        ("может быть, я был на встрече", ce.OUTCOME_REJECTED,
         "gated_speech_act:hypothesis"),
        ("! я был на встрече", ce.OUTCOME_REJECTED,
         "gated_speech_act:command"),
        # цитата не гейтится как факт: авторство остаётся в тексте/контуре
        ("по словам Васи, я был в отпуске", ce.OUTCOME_ACCEPTED, None),
        # гипербола закрытым детерминированным набором не детектируется
        # (не строим несостоятельный NLP; генерация — под Character_Rules)
        ("я тебе миллион раз говорил", ce.OUTCOME_ACCEPTED, None),
    ])
    def test_matrix(self, text, outcome, reason):
        got_outcome, got_reason = ce.gate_personal_text_write(text)
        assert got_outcome == outcome
        if reason is not None:
            assert got_reason == reason

    def test_third_party_quote_tentative_not_confirmed(self):
        env = ce.build_envelope(
            speaker_entity_id=1, subject_entity_id=2,
            claim_text="по словам Васи, Лёха уехал", attribution_method=
            "third_party")
        outcome, _reason = ce.validate_personal_write(env)
        assert outcome == ce.OUTCOME_TENTATIVE      # не confirmed-биография

    def test_gate_off_parity(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "canonical_attribution_enabled",
                            lambda: False)
        assert ce.gate_personal_text_write("шучу, я был на Марсе") == \
            (ce.OUTCOME_ACCEPTED, None)

    @pytest.mark.asyncio
    async def test_joke_not_stored_as_confirmed_fact(self, tmp_path):
        db = await _db(tmp_path, "gate.db")
        mm = MemoryManager(db, llm=None)
        mm._vec_available = False
        result = await mm.remember_user_fact(
            CHAT_ID, "шучу, я вчера был на Марсе", target_user="вася",
            ttl_days=365)
        assert result == "skipped_gated"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts "
            "WHERE origin='user_memory'")
        assert (await cursor.fetchone())["c"] == 0
        # контроль: обычный личный факт сохраняется confirmed
        saved = await mm.remember_user_fact(
            CHAT_ID, "мой любимый цвет синий", target_user="вася",
            ttl_days=365)
        assert saved == "saved"
        cursor = await db.db.execute(
            "SELECT status FROM graph_facts WHERE origin='user_memory'")
        assert (await cursor.fetchone())["status"] == "confirmed"
        await db.close()


# ── K1/K2: реестр kill-switch'ей и Δ каталога ────────────────────────────────

class TestKillSwitches:
    def test_registered_default_on(self):
        names = {"MCA_CHARACTER_LAYERS_ENABLED",
                 "MCA_CHARACTER_SPEECH_ENABLED"}
        assert names <= set(mca_gates.KILL_SWITCHES)
        for name in names:
            default, parity = mca_gates.KILL_SWITCHES[name]
            assert default is True and parity
        assert mca_gates.character_layers_enabled() is True
        assert mca_gates.character_speech_enabled() is True
        assert settings.MCA_CHARACTER_LAYERS_ENABLED is True
        assert settings.MCA_CHARACTER_SPEECH_ENABLED is True

    def test_resolvers_wired_in_registry(self):
        from services import mca_process_registry as reg
        for gate, resolver in (
                ("MCA_CHARACTER_LAYERS_ENABLED", "character_layers_enabled"),
                ("MCA_CHARACTER_SPEECH_ENABLED", "character_speech_enabled")):
            assert reg._GATE_RESOLVERS.get(gate) == resolver
            assert callable(getattr(mca_gates, resolver))

    def test_catalog_delta_zero(self):
        try:
            from services.param_catalog import PARAM_DEFS
        except Exception:
            from services import param_catalog
            names = {str(getattr(v, "key", ""))
                     for v in getattr(param_catalog, "_PARAMS", [])}
        else:
            names = {d.key for d in PARAM_DEFS}
        assert not ({"MCA_CHARACTER_LAYERS_ENABLED",
                     "MCA_CHARACTER_SPEECH_ENABLED"} & names)

    def test_reason_codes_registered(self):
        from services import mca_events
        assert {"clarification_asked",
                "clarification_assumption_used"} <= mca_events.REASON_CODES
