"""DIRECT-SELF-CORRECTION-01 (EVOL-REPLY-CONTEXT-INTEGRITY-01 v5, §12/§13.71–96).

Контракт: ``plans/features/evol/arch/reply-context-integrity-v5-contract.md``
§3–§5; источник владельца ``plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md``
§12.1–§12.4 + §13 сц.71–96.

Проверяется РЕАЛЬНЫЙ payload Direct Writer'а (через те же производственные
функции, что зовёт рантайм): текущая реплика, собственное оспариваемое
утверждение, контраргумент и их источники видны как РАЗЛИЧИМЫЕ роли; единица
счёта не подменяется молча; собственная прошлая реплика не подаётся как
доказательство; при неоднозначности и нехватке данных — честное уточнение, а
не догадка. Имена/темы/ID в тестах произвольные (анти-хардкод сц.92).

TEST-LIFECYCLE: CONTRACT (owner=EVOL-REPLY-CONTEXT-INTEGRITY-01 v5, RC-DIRECT-SELFCORR).
"""
import re

import pytest

from services import chat_prompts
from services import direct_chat_service as dcs
from services import direct_context_composer as comp
from services import hot_config
from services import prompt_composer
from services.canonical_context import SpeechProjection
from tests.test_direct_chat import FakeDB, FakeMemory, _make_service, _message

CHAT_ID = -1007781
TS = 1_714_406_400            # 01.05.2024, произвольная точка
BOT_ID = 424242

_REF_RE = re.compile(r"\b(?:tg|msg|fact):\d+")
_FRAME_OPEN_RE = re.compile(r"<Correction_Frame\s([^>]*)>")


class _Cache:
    """Минимальный ConfigCache-совместимый стаб hot-ключа."""

    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def speech_on():
    saved = hot_config.get_config_cache()
    hot_config.set_config_cache(
        _Cache({"flags.context_speech_projection": True}))
    yield
    hot_config.set_config_cache(saved)


@pytest.fixture
def speech_off():
    saved = hot_config.get_config_cache()
    hot_config.set_config_cache(
        _Cache({"flags.context_speech_projection": False}))
    yield
    hot_config.set_config_cache(saved)


class OwnDB(FakeDB):
    """FakeDB + история собственных доставленных ответов (ledger)."""

    def __init__(self, rows=None, outputs=None):
        super().__init__(rows)
        self.outputs = list(outputs or [])

    async def list_recent_bot_outputs(self, chat_id, limit=20, kinds=None):
        return self.outputs[:limit]


def _row(tg_id, *, uid=11, name="Никита", text="реплика", ts=TS,
         reply_to_db=None, quote=None, quote_author=None):
    return {
        "id": (tg_id or 0) + 90_000,
        "tg_message_id": tg_id,
        "chat_id": CHAT_ID,
        "user_id": uid,
        "author_name": name,
        "text": text,
        "timestamp": ts,
        "reply_to_id": reply_to_db,
        "media_type": "text",
        "is_forward": 0,
        "forward_source": "",
        "quote_text": quote,
        "quote_author_id": quote_author,
    }


def _bot_msg(tg_id, text, *, from_id=BOT_ID, name="Adminbot"):
    from unittest.mock import MagicMock
    reply = MagicMock()
    reply.message_id = tg_id
    reply.text = text
    reply.caption = None
    reply.from_user = MagicMock()
    reply.from_user.id = from_id
    reply.from_user.first_name = name
    return reply


def _quote(text):
    from unittest.mock import MagicMock
    q = MagicMock()
    q.text = text
    return q


def _trigger(text, *, message_id=900, reply=None, quote=None,
             chat_type="supergroup", uid=11, name="Никита"):
    message = _message(text=text, message_id=message_id)
    message.chat.type = chat_type
    message.reply_to_message = reply
    message.quote = quote
    message.date = None
    message.from_user.first_name = name
    message.from_user.id = uid
    return message


async def _payload(*, window=(), db=None, message=None, run_id="rc-run",
                   target="Никита", target_uid=11):
    svc = _make_service(
        memory=FakeMemory(window=list(window)), db=db or OwnDB({}),
        bot_id=BOT_ID, bot_username="probe_bot")
    projection = SpeechProjection(run_id=run_id)
    blocks = await svc._build_user_content(
        CHAT_ID, message or _trigger("ну?"), target, target_user_id=target_uid,
        projection=projection)
    return "\n".join(str(b) for b in blocks if b), projection


def _frame(payload: str) -> str:
    """Текст рамки возражения или '' (рамки нет)."""
    start = payload.find("<Correction_Frame")
    if start < 0:
        return ""
    end = payload.find("</Correction_Frame>", start)
    return payload[start:end + len("</Correction_Frame>")]


def _attrs(payload: str) -> dict:
    found = _FRAME_OPEN_RE.search(payload)
    assert found is not None, payload
    return dict(re.findall(r'(\w+)="([^"]*)"', found.group(1)))


# ═══════════════════════════════════════════════════════════════════════════
# §12.2 п.1/п.9 + §13.74/75: предмет возражения и роли различимы
# ═══════════════════════════════════════════════════════════════════════════

class TestChallengeRoles:
    @pytest.mark.asyncio
    async def test_reply_to_own_answer_names_it_as_own_claim(self, speech_on):
        """Reply на свою реплику → в payload есть роль «твоё утверждение»."""
        payload, projection = await _payload(
            window=[_row(4100, text="моя старая реплика про лифты")],
            message=_trigger(
                "т.е. ты правда так считаешь?",
                reply=_bot_msg(4300, "я насчитал четыре случая")))
        frame = _frame(payload)
        assert frame, payload
        assert 'link="telegram_reply"' in frame
        assert 'subject="own_claim"' in frame
        assert "твоё прежнее утверждение" in frame
        assert "возражение (роль: текущая реплика человека)" in frame
        # Транспортная связь названа явно, а не «примерно помню».
        assert "Telegram Reply (подтверждено транспортом)" in frame
        # Текст своей реплики — из транспорта, не выдуман.
        assert "я насчитал четыре случая" in frame
        # Метка своей реплики разрешается обратной картой прогона.
        claim_label = re.search(r"оспаривают\): (M\d+)", frame).group(1)
        assert projection.raw_of(claim_label) == "tg:4300"

    @pytest.mark.asyncio
    async def test_own_previous_answer_is_not_evidence(self, speech_on):
        """§12.2 п.2/п.4: прошлый ответ — утверждение, а не доказательство."""
        payload, _ = await _payload(
            message=_trigger("это так не работает",
                             reply=_bot_msg(4301, "алгоритм считает именно так")))
        frame = _frame(payload)
        assert "а не доказательство собственной правоты" in frame

    @pytest.mark.asyncio
    async def test_quote_of_own_words_is_shown_as_quoted_fragment(self,
                                                                 speech_on):
        """Выделенная цитата своих слов — отдельной ролью (источник цитаты)."""
        payload, _ = await _payload(
            message=_trigger("вот именно это и не работает",
                             reply=_bot_msg(4302, "я так интерпретировал историю"),
                             quote=_quote("я так интерпретировал историю")))
        frame = _frame(payload)
        assert "выделенный фрагмент, на который указал человек" in frame
        assert "«я так интерпретировал историю»" in frame

    @pytest.mark.asyncio
    async def test_reply_to_participant_is_not_own_claim(self, speech_on):
        """§13.84/85: чужие слова не присваиваются — subject=participant."""
        payload, _ = await _payload(
            message=_trigger(
                "он врёт", reply=_bot_msg(4303, "моя версия", from_id=555,
                                          name="Алиса")))
        frame = _frame(payload)
        assert 'subject="participant"' in frame
        assert "слова человека, не твои" in frame
        assert "твоё прежнее утверждение" not in frame

    @pytest.mark.asyncio
    async def test_no_structural_link_no_frame(self, speech_on):
        """§13.85: без связи бот не изобретает предмет возражения."""
        payload, _ = await _payload(
            window=[_row(4102, text="обычная болтовня про погоду")],
            message=_trigger("привет"))
        assert _frame(payload) == ""
        assert "<Correction_Frame" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# §12.2 п.3 + §13.71–73: единица счёта не подменяется молча
# ═══════════════════════════════════════════════════════════════════════════

class TestCountingUnit:
    @pytest.mark.asyncio
    async def test_one_question_and_two_quotes_is_one_not_three(self,
                                                               speech_on):
        """§13.71: один исходный вопрос + две цитаты ≠ три вопроса."""
        window = [
            _row(4200, text="почему регресс всплыл только в пятницу?"),
            _row(4201, text="та же мысль", ts=TS + 10,
                 quote="почему регресс всплыл только в пятницу?",
                 quote_author=11),
            _row(4202, text="и ещё раз", ts=TS + 20,
                 quote="почему регресс всплыл только в пятницу?",
                 quote_author=11),
        ]
        payload, _ = await _payload(
            window=window,
            message=_trigger("я спрашивал один раз",
                             reply=_bot_msg(4304, "ты спрашивал три раза")))
        frame = _frame(payload)
        assert "самостоятельных реплик 1" in frame
        assert "вопросительных предложений 1" in frame
        assert "ссылок/цитат на свои прежние реплики 2" in frame
        assert _attrs(frame)["standalone"] == "1"
        assert _attrs(frame)["questions"] == "1"
        assert _attrs(frame)["refs_same"] == "2"
        # Ссылка на прежнюю реплику не выдаётся за новую самостоятельную.
        assert "- M2: ссылка/цитата на свою же прежнюю реплику" in frame
        assert "- M3: ссылка/цитата на свою же прежнюю реплику" in frame

    @pytest.mark.asyncio
    async def test_three_real_questions_are_three(self, speech_on):
        """§13.72: три самостоятельных вопроса — это три, и они видны."""
        window = [
            _row(4210, text="когда релиз?"),
            _row(4211, text="почему задержка?", ts=TS + 10),
            _row(4212, text="кто согласует?", ts=TS + 20),
        ]
        payload, _ = await _payload(
            window=window,
            message=_trigger("я трижды спрашивал",
                             reply=_bot_msg(4305, "спрашивал трижды")))
        frame = _frame(payload)
        assert "самостоятельных реплик 3" in frame
        assert "вопросительных предложений 3" in frame
        assert _attrs(frame)["standalone"] == "3"

    @pytest.mark.asyncio
    async def test_two_questions_in_one_message_are_not_two_messages(self,
                                                                    speech_on):
        """§13.73: два вопроса в одной реплике ≠ две реплики."""
        window = [
            _row(4220, text="что там с бэкапом? и когда отчёт?"),
            _row(4221, text="ладно, жду", ts=TS + 10),
            _row(4222, text="без спешки", ts=TS + 20),
        ]
        payload, _ = await _payload(
            window=window,
            message=_trigger("это был один вопрос",
                             reply=_bot_msg(4306, "ты спрашивал дважды")))
        frame = _frame(payload)
        assert "самостоятельных реплик 3" in frame
        assert "вопросительных предложений 2" in frame
        assert _attrs(frame)["standalone"] == "3"
        assert _attrs(frame)["questions"] == "2"
        # Число вопросов относится к ОДНОЙ реплике, а не к числу сообщений.
        assert "вопросительных предложений: 2" in frame

    def test_canon_keeps_unit_and_names_both_metrics(self):
        """§12.2 п.3: канон Writer'а требует сохранять единицу счёта."""
        canon = chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert "ВОЗРАЖЕНИЕ И СВОЙ ПРЕДЫДУЩИЙ ОТВЕТ" in canon
        assert "Не подменяй молча" in canon
        assert "сколько раз спросил" in canon
        assert "сколько раз тема возникала" in canon


# ═══════════════════════════════════════════════════════════════════════════
# §12.2 п.4/п.5 + §12.3 + §13.76–79, 86, 94
# ═══════════════════════════════════════════════════════════════════════════

class TestRevisionAndPragmatics:
    def test_canon_allows_justified_disagreement_and_honest_uncertainty(self):
        """§12.2 п.4: обоснованное несогласие и честная неопределённость."""
        canon = chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert "возражай аргументированно и покажи основание" in canon
        assert "не извиняясь автоматически" in canon
        assert "не объявляй, кто выиграл спор" in canon

    def test_canon_reads_indirect_critique_and_keeps_literal_questions(self):
        """§12.2 п.5/§13.78–79: намёк ≠ буквальный вопрос, но буквальный — да."""
        canon = chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert "обратной связью о твоём поведении" in canon
        assert "отвечай буквально" in canon
        # Никакого списка триггерных фраз и слов инцидентного диалога.
        assert "тест Тьюринга" not in canon.lower()
        assert "провален" not in canon.lower()

    def test_canon_forbids_invented_algorithm_knowledge(self):
        """§12.2 п.10/§13.86: без «мой алгоритм так считает»."""
        canon = chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert "О собственном устройстве не заявляй" in canon
        assert "как свою интерпретацию" in canon

    def test_canon_keeps_persona_and_ownership(self):
        """§12.2 п.7/п.9/§13.91: характер сохранён, отвечает за свои слова."""
        canon = chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert "Признание ошибки не требует стерильного тона" in canon
        assert "победа в споре не является критерием качества ответа" in canon
        assert "чужие слова остаются чужими" in canon

    @pytest.mark.asyncio
    async def test_semantic_link_is_marked_as_not_reply(self, speech_on):
        """§13.82/94: привязка без Reply названа смысловой, не Reply."""
        db = OwnDB({}, outputs=[{
            "tg_message_id": 4400, "content_text": "в отчёте две строки",
            "sent_at": TS + 50, "delivery_status": "delivered"}])
        payload, projection = await _payload(
            window=[_row(4300, text="ну и", ts=TS)],
            db=db,
            message=_trigger("опять мимо", chat_type="private"))
        frame = _frame(payload)
        assert 'link="semantic"' in frame
        assert 'semantic="1"' in frame
        assert "НЕ Telegram Reply" in frame
        assert "Telegram Reply (подтверждено транспортом)" not in frame
        claim_label = re.search(r"оспаривают\): (M\d+)", frame).group(1)
        assert projection.raw_of(claim_label) == "tg:4400"
        assert "в отчёте две строки" in frame

    @pytest.mark.asyncio
    async def test_two_equally_plausible_claims_ask_instead_of_guessing(
            self, speech_on):
        """§12.2 п.1/§13.4/§13.80: неоднозначность → уточнить, не выбирать."""
        db = OwnDB({}, outputs=[
            {"tg_message_id": 4410, "content_text": "первый вывод",
             "sent_at": TS + 60, "delivery_status": "delivered"},
            {"tg_message_id": 4411, "content_text": "другой вывод",
             "sent_at": TS + 50, "delivery_status": "delivered"}])
        payload, _ = await _payload(
            window=[_row(4310, text="ага", ts=TS + 70),
                    _row(4311, text="ага", ts=TS + 80, uid=21, name="Олег")],
            db=db, message=_trigger("это не так", chat_type="private"))
        frame = _frame(payload)
        assert 'link="ambiguous"' in frame
        assert "несколько твоих реплик одинаково подходят" in frame
        assert "уточни, а не выбирай наугад" in frame
        # Оба кандидата названы метками прогона.
        assert re.search(r"другие твои реплики в этом отрезке: M\d+", frame)

    @pytest.mark.asyncio
    async def test_reply_without_recoverable_text_is_honest(self, speech_on):
        """§13.77: текста своей реплики нет → честно, без выдумки истории."""
        payload, _ = await _payload(
            message=_trigger("ну и?", reply=_bot_msg(4420, "")))
        frame = _frame(payload)
        assert "текст не передан" in frame
        assert 'subject="own_claim"' in frame

    @pytest.mark.asyncio
    async def test_window_coverage_is_stated(self, speech_on):
        """§12.4: видимый объём истории назван (без него «нет данных» ложно)."""
        payload, _ = await _payload(
            window=[_row(4320, text="a"), _row(4321, text="b", ts=TS + 1),
                    _row(4322, text="c", ts=TS + 2)],
            message=_trigger("не согласен",
                             reply=_bot_msg(4430, "я посчитал")))
        frame = _frame(payload)
        assert "реплик человека в окне: 3" in frame
        assert _attrs(frame)["window"] == "3"


# ═══════════════════════════════════════════════════════════════════════════
# §12.3/§12.4/§13.93/96: одна сборка, наблюдаемость, отсутствие запрещённого
# ═══════════════════════════════════════════════════════════════════════════

class TestWiringAndObservability:
    def test_correction_is_p0_slot_before_current(self):
        """§12.3: рамка — существующий слот композера, не вытесняется."""
        assert comp.BLOCK_PRIORITY["correction"] == comp.P0
        order = comp.CANONICAL_ORDER
        assert order["correction"] < order["current"]
        legacy = ["map", "branch", "episode", "rag", "global_head",
                  "global_middle", "global_tail", "thread", "target",
                  "relations", "protected", "lore", "nostalgia", "mood",
                  "current", "anchors", "sandwich"]
        seq = [order[k] for k in legacy]
        assert seq == sorted(seq)

    @pytest.mark.asyncio
    async def test_frame_survives_tight_budget(self, speech_on):
        """P0: рамка возражения не режется бюджетом контекста."""
        piece = comp.ContextPiece(
            key="correction", kind="correction", text="<Correction_Frame/>",
            priority=comp.BLOCK_PRIORITY["correction"],
            keep=comp.PIECE_KEEP.get("correction", "span"),
            evictable=comp.BLOCK_PRIORITY["correction"] != comp.P0,
            position=comp.CANONICAL_ORDER["correction"])
        result = comp.allocate_budget([piece], 1, truncator=lambda t, n: "")
        assert [p.text for p in result.pieces] == ["<Correction_Frame/>"]

    @pytest.mark.asyncio
    async def test_manifest_and_event_carry_codes_not_texts(self, speech_on,
                                                           monkeypatch):
        """§12.4: защищённый манифест/событие — коды и счётчики, без текстов."""
        events = []
        monkeypatch.setattr(
            dcs._mca_events, "emit_mca_event",
            lambda name, **fields: events.append((name, fields)))
        window = [_row(4230, text="почему падает тест?")]
        payload, _ = await _payload(
            window=window,
            message=_trigger("это не ответ",
                             reply=_bot_msg(4500, "потому что кэш старый")))
        frame = _frame(payload)
        assert frame
        emitted = [e for e in events if e[0] == "direct_self_correction"]
        assert emitted, events
        name, fields = emitted[0]
        assert fields["message_id"] == 900          # реальный id текущей реплики
        assert fields["reason_code"] == "quote_resolved"
        usage = fields["usage_json"]
        assert usage["link"] == "telegram_reply"
        assert usage["subject"] == "own_claim"
        assert usage["source_present"] == "1"
        assert usage["semantic"] == "0"
        # Ни текстов участников, ни транспортных id в событии.
        blob = repr(fields)
        assert "кэш старый" not in blob and "потому что" not in blob
        assert "Признал" not in blob and "self-corrected" not in blob

    def test_manifest_publishes_self_correction_codes(self):
        """§12.4: манифест прогона отдаёт код-факты рамки."""
        manifest = prompt_composer.PromptManifest(
            system="s", self_correction={"link": "semantic",
                                         "subject": "own_claim"})
        events_manifest = prompt_composer.manifest_for_events(manifest)
        assert events_manifest["self_correction"] == {
            "link": "semantic", "subject": "own_claim"}

    @pytest.mark.asyncio
    async def test_flag_off_keeps_previous_payload(self, speech_off):
        """Рубильник OFF → прежний payload байт-в-байт (без рамки)."""
        payload, _ = await _payload(
            message=_trigger("это не ответ",
                             reply=_bot_msg(4510, "я так решил")))
        assert "<Correction_Frame" not in payload

    @pytest.mark.asyncio
    async def test_frame_has_no_service_ids(self, speech_on):
        """§9.2/§12.3: рамка адресует метками прогона, не `tg:`/uid."""
        payload, projection = await _payload(
            window=[_row(4240, text="вопрос про кэш")],
            message=_trigger("ты выдумал",
                             reply=_bot_msg(4520, "я проверил три раза")))
        frame = _frame(payload)
        assert frame
        assert not _REF_RE.search(frame), frame
        assert not re.search(r"\[\d{1,12}\]", frame), frame
        for label in set(re.findall(r"\b[MFU]\d+\b", frame)):
            assert projection.raw_of(label), label

    @pytest.mark.asyncio
    async def test_no_new_llm_call_or_regeneration(self, speech_on,
                                                  monkeypatch):
        """§13.96: решение принимается существующим Direct pipeline (0 LLM)."""
        calls = []

        class _LLM:
            async def generate(self, *args, **kwargs):
                calls.append(args)
                return "ответ"

        svc = _make_service(memory=FakeMemory(window=[]), db=OwnDB({}),
                            llm=_LLM(), bot_id=BOT_ID)
        await svc._build_user_content(
            CHAT_ID, _trigger("это не так", reply=_bot_msg(4530, "мой вывод")),
            "Никита", target_user_id=11,
            projection=SpeechProjection(run_id="run"))
        assert calls == []
        # Никакой постобработки готового текста: в модуле нет правки ответа.
        assert not hasattr(dcs, "_rewrite_correction")
