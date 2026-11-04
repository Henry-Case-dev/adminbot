"""EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 — потребительская волна (B/E/F).

Контракт: ``plans/features/evol/arch/reply-context-integrity-v5-contract.md``
§4.1 (P1–P7 — полный инвентарь речевых путей), §4.2 п.2–п.5 (одна структура —
две проекции, метки как адресная разметка, обратная карта на прогон), §4.4
(CONTEXT-FIDELITY: отношения/авторы/адресаты/forward/абсолютные даты/алиасы
остаются), §4.5 (манифест: представление + типы, без текстов), §7.1 R2
(дедуп на структурном ключе), §7.2 (осознанно обновляемые пины).
Источник владельца: ``plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md``
§5.4, §9.2–§9.5.

Проверяется НАБЛЮДАЕМОЕ поведение потребителей: что РЕАЛЬНО уходит в payload
(через те же производственные функции, что зовёт рантайм), а не внутренности:
  * в речевом payload нет ``tg:``/``msg:``/``fact:`` и голого user id;
  * отношения/автор/адресат/дата/`Переслано:`/роль бота/цитата сохранены;
  * каждая метка разрешается обратной картой прогона в реальный ID;
  * один общий прогон на все под-блоки (окно и цепочка адресуют одинаково);
  * рубильник OFF и отсутствие проекции → прежний сырой канон.

TEST-LIFECYCLE: CONTRACT (owner=EVOL-REPLY-CONTEXT-INTEGRITY-01 v5, волна B/E/F).
"""
import json
import re

import pytest

from services import canonical_context as cc
from services import chat_context
from services import direct_l1
from services import factcheck_context
from services import hot_config
from services import lore_compiler_service
from services import meme_initiative
from services import prompt_composer
from services import summary_memory
from services import thread_chain
from services import tool_router
from services.canonical_context import SpeechProjection, format_context_item
from services.thread_chain import ChainItem

CHAT_ID = -1007002
TS = 1_714_492_800          # 30.04.2024
TS2 = TS + 60
TG_ROOT = 500
TG_CHILD = 501

#: ``tg:<id>`` / ``msg:<id>`` / ``fact:<id>`` — то, чего в речи быть не должно.
_REF_RE = re.compile(r"\b(?:tg|msg|fact):\d+")
#: Голый uid в скобках канона: `вася [10]`.
_UID_RE = re.compile(r"\[\d{1,12}\]")


class _Cache:
    """Минимальный ConfigCache-совместимый стаб для hot-ключа."""

    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def speech_off():
    """Рубильник речевой проекции OFF (живой hot-ключ), затем восстановление."""
    saved = hot_config.get_config_cache()
    hot_config.set_config_cache(
        _Cache({"flags.context_speech_projection": False}))
    yield
    hot_config.set_config_cache(saved)


@pytest.fixture
def speech_on():
    saved = hot_config.get_config_cache()
    hot_config.set_config_cache(
        _Cache({"flags.context_speech_projection": True}))
    yield
    hot_config.set_config_cache(saved)


def _row(tg_id, *, uid=10, name="Вася", text="сообщение", ts=TS,
         reply_to_db=None, forward=None, media="text", db_id=None):
    """Строка smart_messages (dict-форма, как её видит рендер).

    ``reply_to_db`` — id строки-родителя (``smart_messages.id``): именно так
    хранит БД (`reply_to_id`), а не Telegram id."""
    return {
        "id": db_id if db_id is not None else (tg_id or 0) + 10_000,
        "tg_message_id": tg_id,
        "chat_id": CHAT_ID,
        "user_id": uid,
        "author_name": name,
        "text": text,
        "timestamp": ts,
        "reply_to_id": reply_to_db,
        "is_forward": 1 if forward else 0,
        "forward_source": forward,
        "media_type": media,
    }


def _service():
    from services.summary_aliases import AliasResolver
    from tests.test_direct_chat import FakeDB, FakeLLM, FakeMemory
    from services.direct_chat_service import DirectChatService

    return DirectChatService(
        FakeMemory(), FakeDB(), FakeLLM(text="ответ"),
        AliasResolver("{}"), bot_id=12345, bot_username="test_bot",
        breaker=None, cache=None, tool_router=None)


def _service_with_window(rows):
    from services.summary_aliases import AliasResolver
    from tests.test_direct_chat import FakeDB, FakeLLM, FakeMemory
    from services.direct_chat_service import DirectChatService

    return DirectChatService(
        FakeMemory(window=list(rows)), FakeDB(), FakeLLM(text="ответ"),
        AliasResolver("{}"), bot_id=12345, bot_username="test_bot",
        breaker=None, cache=None, tool_router=None)


def _message(text="бот, что нового?", message_id=1004):
    from unittest.mock import MagicMock
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = 10
    m.from_user.username = "vasya"
    m.reply_to_message = None
    m.entities = None
    return m


def _labels(payload):
    """Все метки прогона, реально попавшие в текст."""
    return set(re.findall(r"\b[MFU]\d+\b", payload))


_UIDS_MAP_RE = re.compile(r"<UserResolutionMap>.*?</UserResolutionMap>",
                          re.S)


def _without_alias_map(payload: str) -> str:
    """Текст без `<UserResolutionMap>`.

    Таблица имён — АДРЕСНАЯ карта «имя ↔ user_id» (§4.2 п.1: типизированные
    refs специализированным стадиям; она и существует для сопоставления имён,
    и её инструкция — объявленный заводской промпт, менять который без бампа
    ревизии запрещено контрактом версионирования). Поэтому номер участника
    допустим ТОЛЬКО там, а весь остальной речевой контекст — без служебных id.
    """
    return _UIDS_MAP_RE.sub("", payload)


def _assert_no_service_ids(payload):
    assert not _REF_RE.search(payload), payload
    assert not _UID_RE.search(payload), payload


def _assert_all_labels_resolve(payload, projection):
    for label in _labels(payload):
        assert projection.raw_of(label), f"метка без обратной карты: {label}"


# ── Direct: окно/фон (<Global_Context>), P1 ────────────────────────────────

class TestDirectWindowSpeech:
    @pytest.mark.asyncio
    async def test_global_context_carries_relations_without_service_ids(
            self, speech_on):
        """§4.4: автор/абсолютная дата/forward/uid-различение остаются, `tg:` нет."""
        svc = _service_with_window([
            _row(TG_ROOT, text="первая реплика", forward="Канал X"),
            _row(TG_CHILD, uid=20, name="Марина", text="вторая реплика",
                 ts=TS2),
        ])
        projection = SpeechProjection(run_id="direct-run")
        blocks = await svc._build_user_content(
            CHAT_ID, _message(), "Вася", target_user_id=10,
            projection=projection)
        payload = "\n".join(str(b) for b in blocks if b)
        speech_part = _without_alias_map(payload)

        _assert_no_service_ids(speech_part)
        _assert_all_labels_resolve(speech_part, projection)
        # Абсолютное время и «Переслано:» — не заменяются порядком.
        assert "30.04.2024" in speech_part
        assert "Переслано: Канал X" in speech_part
        # Два разных человека различимы метками, ники сохранены.
        assert "Вася (U1)" in speech_part
        assert "Марина (U2)" in speech_part
        # Обратная карта указывает на реальные Telegram id.
        values = set(projection.manifest()["items"].values())
        assert f"tg:{TG_ROOT}" in values and f"tg:{TG_CHILD}" in values
        # Содержательный текст участников не переписан.
        assert "первая реплика" in speech_part
        assert "вторая реплика" in speech_part
        # Адресная карта имён — единственное место с номером участника.
        assert re.search(r"Вася\s*[-—]\s*10", payload)

    @pytest.mark.asyncio
    async def test_same_name_participants_are_not_collapsed(self, speech_on):
        """§5.4/§13 сц.97: одинаковый ник ≠ один человек."""
        svc = _service_with_window([
            _row(TG_ROOT, uid=10, name="Марина", text="моя версия"),
            _row(TG_CHILD, uid=20, name="Марина", text="а я против", ts=TS2),
        ])
        projection = SpeechProjection(run_id="run")
        blocks = await svc._build_user_content(
            CHAT_ID, _message(), "Вася", target_user_id=10,
            projection=projection)
        payload = "\n".join(str(b) for b in blocks if b)
        speech_part = _without_alias_map(payload)
        assert "(U1)" in speech_part and "(U2)" in speech_part
        assert "Марина" in speech_part
        assert projection.raw_of("U1") == "10"
        assert projection.raw_of("U2") == "20"
        assert projection.raw_of("U1") == "10"
        assert projection.raw_of("U2") == "20"

    @pytest.mark.asyncio
    async def test_flag_off_restores_raw_canon(self, speech_off):
        """§6.2: рубильник OFF → прежний сырой канон (id и uid на месте)."""
        svc = _service_with_window([_row(TG_ROOT, text="первая реплика")])
        blocks = await svc._build_user_content(
            CHAT_ID, _message(), "Вася", target_user_id=10,
            projection=SpeechProjection(run_id="run"))
        payload = "\n".join(str(b) for b in blocks if b)
        assert f"tg:{TG_ROOT}" in payload
        assert "Вася [10]" in payload
        assert "Вася (U1)" not in payload

    def test_target_marker_survives_projection(self, speech_on):
        """§4.3 п.4: маркер цели остаётся на триггере (текст не редактируется)."""
        from services.target_marking import TARGET_MARKER_CORE
        svc = _service()
        row = _row(TG_ROOT, text="это моя команда")
        line = svc._context_row_line(
            row, {}, trigger_message_id=TG_ROOT,
            projection=SpeechProjection(run_id="run"))
        assert TARGET_MARKER_CORE in line
        assert f"tg:{TG_ROOT}" not in line

    def test_forward_and_bot_role_are_kept_in_thread(self, speech_on):
        """§5.4: `Переслано:` и роль бота не теряются при снятии ID."""
        svc = _service()
        projection = SpeechProjection(run_id="run")
        chain = [
            ChainItem(uid=None, name="Adminbot", text="мой прошлый ответ",
                      is_bot=True, ts=TS2, item_id=f"tg:{TG_CHILD}",
                      reply_to_item_id=f"tg:{TG_ROOT}"),
            ChainItem(uid=10, name="Вася", text="исходный вопрос", is_bot=False,
                      ts=TS, item_id=f"tg:{TG_ROOT}",
                      forward_source="Канал X"),
        ]
        block = svc._render_thread(chain, {}, trigger_message_id=TG_CHILD,
                                   truncate=False, projection=projection)
        _assert_no_service_ids(block)
        assert "(бот)" in block
        assert "Переслано: Канал X" in block
        # Reply-край печатается явно и указывает на метку родителя.
        assert "↳ Reply" in block
        assert "30.04.2024" in block

    def test_quote_text_never_contains_run_labels(self, speech_on):
        """§4.3 п.3: метка — адресная разметка, НЕ часть цитируемой реплики."""
        svc = _service()
        projection = SpeechProjection(run_id="run")
        chain = [
            ChainItem(uid=10, name="Вася", text="мой ответ", is_bot=False,
                      ts=TS2, item_id=f"tg:{TG_CHILD}",
                      reply_to_item_id=f"tg:{TG_ROOT}",
                      quote_text="фрагмент участника", quote_author_id=20,
                      quote_author_name="Марина"),
            ChainItem(uid=20, name="Марина", text="исходный текст",
                      is_bot=False, ts=TS, item_id=f"tg:{TG_ROOT}"),
        ]
        block = svc._render_thread(chain, {}, trigger_message_id=TG_CHILD,
                                   truncate=False, projection=projection)
        _assert_no_service_ids(block)
        # Автор цитаты — человек (U-метка), а внутри «…» нет ни одной метки.
        quoted = re.findall(r"«([^»]*)»", block)
        assert quoted, block
        for fragment in quoted:
            assert not re.search(r"\b[MFU]\d+\b", fragment), block
        assert "автор: Марина (U" in block, block

    def test_dedup_key_is_structural_in_both_forms(self):
        """§7.1 R2: ключ дедупа middle↔tail — ref ИЛИ метка, не текст реплики."""
        from services.direct_chat_service import _context_line_dedup_key
        raw = format_context_item(ts=TS, author="Вася [10]",
                                  item_id=f"tg:{TG_ROOT}", text="x")
        speech = cc.format_speech_item(
            ts=TS, author="Вася", author_uid=10, item_id=f"tg:{TG_ROOT}",
            text="x", projection=SpeechProjection(run_id="run"))
        assert _context_line_dedup_key(raw) == f"tg:{TG_ROOT}"
        assert _context_line_dedup_key(speech) == "M1"
        # Слово «M1» в чужих словах ключом не становится (не редактируем текст).
        assert _context_line_dedup_key("без заголовка M1") == ""


# ── F1 ревью волны потребителей: автор цитаты — ЧЕЛОВЕК, не метка ──────────

class _ChainDb:
    """Минимальный источник строк reply-цепочки (без бот-ответов)."""

    def __init__(self, messages):
        self.messages = messages

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return self.messages.get(tg_message_id)

    async def get_bot_reply(self, *args, **kwargs):        # pragma: no cover
        return None

    async def get_bot_reply_parent(self, *args, **kwargs):  # pragma: no cover
        return None


class TestQuoteAuthorIsAPerson:
    """`цитата (автор: Имя (U3))`, а не `цитата (автор: U3)` (§5.4, §9.2).

    Продовая проводка обязана передавать резолвер имени: у автора цитаты
    может не быть хода в собранном окне, поэтому одной `UserResolutionMap`
    для имени не хватает. Неизвестное имя объявляется честно.
    """

    AUTHOR_UID = 55

    def _rows(self):
        quoting = dict(_row(TG_CHILD, uid=20, name="Марина", text="разбор",
                            ts=TS2, reply_to_db=TG_ROOT + 10_000))
        quoting.update({"quote_text": "у мышц свои волокна",
                        "quote_author_id": self.AUTHOR_UID,
                        "quote_position": 0, "quote_is_manual": 1})
        return {TG_CHILD: quoting,
                TG_ROOT: _row(TG_ROOT, uid=10, name="Хан",
                              text="исходный вопрос про волокна")}

    def _svc(self, aliases_json):
        from services.direct_chat_service import DirectChatService
        from services.summary_aliases import AliasResolver
        from tests.test_direct_chat import FakeDB, FakeLLM, FakeMemory
        return DirectChatService(
            FakeMemory(), FakeDB(self._rows()), FakeLLM(text="ответ"),
            AliasResolver(aliases_json), bot_id=12345,
            bot_username="test_bot", breaker=None, cache=None,
            tool_router=None)

    async def _thread_block(self, svc, projection):
        chain = await svc._collect_thread_chain(
            CHAT_ID, _message(message_id=TG_CHILD), depth=5)
        return svc._render_thread(chain, {}, trigger_message_id=TG_CHILD,
                                  truncate=False, projection=projection)

    @pytest.mark.asyncio
    async def test_production_wiring_names_the_quote_author(self, speech_on):
        """Прод-вызов `_collect_thread_chain` → имя человека в речевой строке.

        Убрать резолвер из проводки (`quote_author_resolver=`) — тест
        краснеет: в блоке снова остаётся голая `U`-метка."""
        svc = self._svc('{"55": "Пётр"}')
        projection = SpeechProjection(run_id="f1")
        block = await self._thread_block(svc, projection)
        assert "у мышц свои волокна" in block, block
        assert "(автор: Пётр (U" in block, block
        # Голой адресной метки на месте автора нет.
        assert not re.search(r"\(автор: U\d+\)", block), block
        _assert_no_service_ids(block)
        # Обратная карта автора живёт в проекции прогона (машинный слой).
        assert str(self.AUTHOR_UID) in set(
            projection.manifest()["participants"].values())

    @pytest.mark.asyncio
    async def test_unknown_author_is_declared_not_mislabelled(self, speech_on):
        """Нет привязки имени → «автор цитаты не определён», а не `автор: U3`."""
        svc = self._svc("{}")
        block = await self._thread_block(svc, SpeechProjection(run_id="f1b"))
        assert "автор цитаты не определён" in block, block
        assert not re.search(r"\(автор: U\d+\)", block), block

    @pytest.mark.asyncio
    async def test_factcheck_reply_chains_use_the_same_resolver(
            self, speech_on, monkeypatch):
        """Второй продовый вызывающий (`handlers.factcheck`) — тоже с именем."""
        import handlers.factcheck as fc
        from services import summary_aliases as sa

        async def _cp_g(chat_id, key, default=None):
            return default

        monkeypatch.setattr(fc, "_db", _ChainDb(self._rows()))
        monkeypatch.setattr(fc, "_cp_g", _cp_g)
        sa.set_turn_alias_resolver(sa.AliasResolver('{"55": "Пётр"}'))
        try:
            block = await fc._build_reply_chains(
                CHAT_ID, TG_CHILD,
                projection=SpeechProjection(run_id="f1c"))
        finally:
            sa.set_turn_alias_resolver(None)
        assert "(автор: Пётр (U" in block, block
        assert not re.search(r"\(автор: U\d+\)", block), block

    def test_semantic_addressee_is_named_not_labelled(self, speech_on):
        """Тот же корень F1: адресат называется как в окне — «Пётр (U2)»."""
        projection = SpeechProjection(run_id="f1d")
        plan = direct_l1.L1Plan(delivery="chat",
                                target_user_id=self.AUTHOR_UID)
        block = direct_l1.build_l2_plan_block(
            plan, include_delivery=True, projection=projection,
            name_of=lambda uid: ("Пётр"
                                 if int(uid) == self.AUTHOR_UID else ""))
        assert "смысловой адресат: Пётр (U" in block, block
        assert not re.search(r"смысловой адресат: U\d+", block), block

    def test_unknown_addressee_is_not_a_bare_label(self, speech_on):
        """Имени нет → «участник», а не неозвучиваемая метка (§9.2)."""
        projection = SpeechProjection(run_id="f1e")
        plan = direct_l1.L1Plan(delivery="chat",
                                target_user_id=self.AUTHOR_UID)
        block = direct_l1.build_l2_plan_block(
            plan, include_delivery=True, projection=projection)
        assert "смысловой адресат: участник" in block, block
        assert not re.search(r"смысловой адресат: U\d+", block), block


# ── FactCheck: широкий фид и цепочка — ОДИН прогон (§4.2 п.3, N1) ──────────
class TestFactcheckSharedProjection:
    def _ctx(self):
        messages = (
            factcheck_context.ContextMessage(
                message_id=10_000, tg_message_id=TG_ROOT,
                chat_id=CHAT_ID, author="Вася", timestamp=TS,
                reply_to_tg_id=None, is_forward=False, forward_source=None,
                text="исходный тезис", verbatim=True, author_uid=10),
            factcheck_context.ContextMessage(
                message_id=10_001, tg_message_id=TG_CHILD,
                chat_id=CHAT_ID, author="Марина", timestamp=TS2,
                reply_to_tg_id=TG_ROOT, is_forward=False,
                forward_source=None, text="ответ на тезис", verbatim=True,
                author_uid=20),
        )
        return factcheck_context.ConversationContext(
            chat_id=CHAT_ID, target_tg_message_id=TG_ROOT,
            trigger_tg_message_id=TG_CHILD, messages=messages,
            window={"before": 10, "after": 2})

    def test_feed_line_shape(self, speech_on):
        projection = SpeechProjection(run_id="fc")
        feed = self._ctx().render_feed(projection=projection)
        _assert_no_service_ids(feed)
        _assert_all_labels_resolve(feed, projection)
        assert "Вася (U1)" in feed and "Марина (U2)" in feed
        assert "30.04.2024" in feed
        assert "исходный тезис" in feed

    def test_window_and_chain_address_the_same_message(self, speech_on):
        """N1 ревью шва: одна метка на сообщение во ВСЕХ под-блоках payload."""
        projection = SpeechProjection(run_id="fc")
        ctx = self._ctx()
        feed = ctx.render_feed(projection=projection)
        chain = [
            ChainItem(uid=20, name="Марина", text="ответ на тезис", is_bot=False,
                      ts=TS2, item_id=f"tg:{TG_CHILD}",
                      reply_to_item_id=f"tg:{TG_ROOT}"),
            ChainItem(uid=10, name="Вася", text="исходный тезис", is_bot=False,
                      ts=TS, item_id=f"tg:{TG_ROOT}"),
        ]
        block = thread_chain.render_reply_chains(
            chain, TG_CHILD, projection=projection, chat_id=CHAT_ID)
        assert block
        window_label = projection.label_of_item(f"tg:{TG_ROOT}")
        assert window_label in feed
        # Метка того же сообщения в цепочке — та же, что в окне.
        assert f"[{window_label}]" in block or window_label in block
        assert len(re.findall(rf"\b{window_label}\b", feed + block)) >= 2

    def test_flag_off_feed_keeps_raw_canon(self, speech_off):
        projection = SpeechProjection(run_id="fc")
        feed = self._ctx().render_feed(projection=projection)
        assert f"tg:{TG_ROOT}" in feed
        assert "(U1)" not in feed


# ── Результаты инструментов (§4.1 P5) ──────────────────────────────────────

class TestToolResults:
    def _router(self):
        from unittest.mock import MagicMock
        deps = tool_router.ToolDeps(search=MagicMock(),
                                    memory=MagicMock(), aliases=None)
        return tool_router.ToolRouter(deps)

    def test_recent_history_lines_are_speech(self, speech_on):
        router = self._router()
        projection = SpeechProjection(run_id="tools")
        lines = router._history_lines(
            [_row(TG_ROOT, text="факт из чата")], with_user_id=True,
            projection=projection)
        payload = "\n".join(lines)
        _assert_no_service_ids(payload)
        assert "Вася (U1)" in payload
        assert "30.04.2024" in payload
        assert projection.raw_of("U1") == "10"
        assert projection.raw_of("M1") == f"tg:{TG_ROOT}"

    def test_recent_history_lines_raw_without_projection(self):
        router = self._router()
        lines = router._history_lines([_row(TG_ROOT, text="факт из чата")],
                                      with_user_id=True)
        assert f"tg:{TG_ROOT}" in lines[0]
        assert "Вася [10]" in lines[0]

    @pytest.mark.asyncio
    async def test_dig_facts_use_labels(self, speech_on):
        """`fact:`-происхождение в речь не идёт: факт адресуется меткой `F`."""
        router = self._router()
        projection = SpeechProjection(run_id="tools")
        ctx = tool_router.ToolContext(CHAT_ID, "когда релиз?", speech=projection)
        assert ctx.speech is projection      # wiring: та же проекция хода
        fact_projection = SpeechProjection(run_id="dig")
        line = cc.format_speech_item(
            ts=TS, author="Вася", item_id=f"fact:{7}", text="релиз 30.04",
            kind="fact", projection=fact_projection)
        assert "fact:7" not in line
        assert fact_projection.raw_of("F1") == "fact:7"


# ── Память / RAG (§4.1 P4, P6) ─────────────────────────────────────────────

class TestMemoryAndRag:
    def test_origin_labeled_line_keeps_provenance_and_drops_fact_id(
            self, speech_on):
        projection = SpeechProjection(run_id="rag")
        text = summary_memory.build_rag_context(
            [("chat_history", "в чате обсуждали релиз", TS, "Вася",
              f"tg:{TG_ROOT}", None)],
            origin_labels=True, projection=projection)
        assert f"tg:{TG_ROOT}" not in text
        assert "Вася" in text
        assert "30.04.2024" not in text       # kind=fact — ММ.ГГГГ (канон)
        assert "04.2024" in text
        assert projection.raw_of("M1") == f"tg:{TG_ROOT}"
        # origin-метка (происхождение факта) сохранена.
        assert "[" in text.split("]")[0] + "]"

    def test_graph_fact_gets_fact_label(self, speech_on):
        projection = SpeechProjection(run_id="rag")
        text = summary_memory.build_rag_context(
            [("dream", "факт из графа", TS, "Марина", f"fact:{11}", None)],
            origin_labels=True, projection=projection)
        assert "fact:11" not in text
        assert projection.raw_of("F1") == "fact:11"

    def test_raw_rag_without_projection_is_unchanged(self):
        text = summary_memory.build_rag_context(
            [("chat_history", "факт", TS, "Вася", f"tg:{TG_ROOT}", None)],
            origin_labels=True)
        assert f"tg:{TG_ROOT}" in text

    def test_legacy_rag_structure_also_speaks(self, speech_on):
        projection = SpeechProjection(run_id="rag")
        text = summary_memory.build_rag_context(
            [("chat_history", "факт", TS, "Вася", f"tg:{TG_ROOT}", None)],
            projection=projection)
        assert f"tg:{TG_ROOT}" not in text
        assert "<user_gossip>" in text


# ── Летописец (lore) ───────────────────────────────────────────────────────

class TestLoreCompiler:
    def test_graph_facts_and_dialogs_speak(self, speech_on):
        from services.summary_aliases import AliasResolver
        projection = SpeechProjection(run_id="lore")
        compiler = lore_compiler_service.LoreCompilerService.__new__(
            lore_compiler_service.LoreCompilerService)
        compiler.tz_name = "UTC"
        compiler.aliases = AliasResolver("{}")
        facts = compiler._graph_facts(
            {"facts": [{"id": 5, "fact": "факт о чате", "rag_ts": TS,
                        "target_user": "Вася"}], "edges": []},
            projection)
        dialogues = compiler._dialog_pairs(
            [[_row(TG_ROOT, text="реплика")]], projection)
        payload = "\n".join(facts) + "\n" + "\n".join(line for line, _ in dialogues)
        _assert_no_service_ids(payload)
        assert "Вася" in payload
        assert projection.raw_of("F1") == "fact:5"

    def test_raw_without_projection(self):
        from services.summary_aliases import AliasResolver
        compiler = lore_compiler_service.LoreCompilerService.__new__(
            lore_compiler_service.LoreCompilerService)
        compiler.tz_name = "UTC"
        compiler.aliases = AliasResolver("{}")
        facts = compiler._graph_facts(
            {"facts": [{"id": 5, "fact": "факт", "rag_ts": TS,
                        "target_user": "Вася"}], "edges": []})
        assert "fact:5" in facts[0]


# ── Мем: выжимка становится словами/картинкой (§4.1 P7) ────────────────────

class TestMemeSummary:
    @staticmethod
    def _payload(**kwargs):
        import asyncio

        seen = {}

        class _Client:
            _chat_model = "chat-model"

            async def generate(self, messages, **_kwargs):
                seen["messages"] = messages
                return "хук"

        rows = [{"id": 41, "tg_message_id": 901, "text": "привет"},
                {"id": 42, "tg_message_id": 902, "text": "пока"}]
        asyncio.run(meme_initiative._default_summarize(
            _Client(), rows, "система", chat_id=CHAT_ID, **kwargs))
        return json.loads(seen["messages"][1]["content"])

    def test_ids_are_labels_not_internal_numbers(self, speech_on):
        body = self._payload(projection=SpeechProjection(run_id="meme"))
        ids = [item["id"] for item in body["messages"]]
        assert ids == ["M1", "M2"]
        assert all(not str(value).isdigit() for value in ids)
        # Тексты сообщений не тронуты (это данные, а не адресация).
        assert [item["text"] for item in body["messages"]] == ["привет", "пока"]

    def test_without_projection_payload_is_unchanged(self):
        body = self._payload()
        assert [item["id"] for item in body["messages"]] == [41, 42]


# ── Текстовая инициатива: окно Writer'а и форма доставки ───────────────────

class TestInitiativeWriterWindow:
    def test_window_lines_use_labels_and_keep_reply_edge(self, speech_on):
        projection = SpeechProjection(run_id="init")
        rows = [_row(TG_ROOT, text="вопрос", db_id=10_000),
                _row(TG_CHILD, text="ответ", ts=TS2, db_id=10_001,
                     reply_to_db=10_000)]
        lines = direct_l1.render_window_lines(
            rows, 12, with_ids=True, projection=projection)
        payload = "\n".join(lines)
        _assert_no_service_ids(payload)
        assert "[M1]" in lines[0] and "[M2]" in lines[1]
        assert "Вася (U1)" in lines[0]
        assert "↳ Reply M1" in lines[1]
        _assert_all_labels_resolve(payload, projection)

    def test_window_lines_raw_without_projection(self):
        rows = [_row(TG_ROOT, text="вопрос", db_id=10_000),
                _row(TG_CHILD, text="ответ", ts=TS2, db_id=10_001,
                     reply_to_db=10_000)]
        lines = direct_l1.render_window_lines(rows, 12, with_ids=True)
        assert lines[0].startswith("[msg:10000] [user:10]")
        assert "(ответ на msg:10000)" in lines[1]

    def test_delivery_line_uses_label_and_honest_gap(self, speech_on):
        projection = SpeechProjection(run_id="init")
        projection.reserve([f"tg:{TG_ROOT}"])
        plan = direct_l1.L1Plan(delivery="reply", target_message_id=10_000)
        block = direct_l1.build_l2_plan_block(
            plan, include_delivery=True, projection=projection,
            label_of=lambda db_id: projection.label_of_item(f"tg:{db_id}"))
        assert "msg:" not in block
        assert "нет в показанном окне" in block

    def test_delivery_line_prints_label_for_visible_target(self, speech_on):
        projection = SpeechProjection(run_id="init")
        label = projection.message_label(f"tg:{TG_ROOT}")
        plan = direct_l1.L1Plan(delivery="reply", target_message_id=TG_ROOT)
        block = direct_l1.build_l2_plan_block(
            plan, include_delivery=True, projection=projection,
            label_of=lambda item: projection.label_of_item(f"tg:{item}"))
        assert label in block
        assert "Telegram-reply на сообщение" in block

    def test_raw_delivery_line_without_projection(self):
        plan = direct_l1.L1Plan(delivery="reply", target_message_id=57)
        block = direct_l1.build_l2_plan_block(plan, include_delivery=True)
        assert "[msg:57]" in block


# ── Наблюдаемость: представление контекста в манифесте (§4.5) ─────────────

class TestManifestObservability:
    @pytest.mark.asyncio
    async def test_direct_egress_observation_makes_no_second_writer_call(
            self, speech_on, monkeypatch):
        """BGS-02: срабатывание egress-guard'а не создаёт второго Writer'а.

        Раньше тест проверял, что повтор guard'а идёт по ТОЙ ЖЕ проекции прогона.
        Повтора больше нет (смысловая постцензура снята): единственный вызов
        Writer'а уже несёт проекцию и объявляет реальное представление, а
        доставленный текст совпадает с L2 байт-в-байт — «второй манифест»,
        который мог бы соврать, физически не существует.
        """
        from services import direct_chat_service as dcs
        from services import evidence_policy as ep
        from tests.test_asap7_direct_l1 import _drive, _FakeLLM, _plan_json

        calls: list[dict] = []
        l2_text = "Вышла версия 1.5 этого ядра."

        async def _writer(self, chat_id, query, *, temperature=None,
                          correlation_id=None, **kw):
            calls.append({"speech": kw.get("speech")})
            return (l2_text, "reply")

        async def _preflight(self, chat_id, correlation_id, **kwargs):
            return ep.EvidenceDecision(required=True,
                                       evidence_class="externally_factual")

        svc, _react, bot, msg, user = _drive(
            monkeypatch, "бот, какая версия вышла?",
            llm=_FakeLLM(l1=_plan_json(response_act="answer"),
                         l2=l2_text))
        monkeypatch.setattr(dcs.DirectChatService, "_l2_write_answer", _writer)
        monkeypatch.setattr(dcs.DirectChatService, "_evidence_preflight",
                            _preflight)
        await svc.handle(bot, msg, user)

        # Ни одного дополнительного Writer-вызова: guard только наблюдает.
        assert len(calls) == 1, calls
        assert calls[0]["speech"] is not None, calls
        # Доставлен ровно L2-текст (неподтверждённая версия не вырезана).
        assert svc._send_direct_answer.await_args.kwargs.get("correlation_id")
        delivered = svc._send_direct_answer.await_args.args[2]
        assert delivered == l2_text, delivered

    @pytest.mark.asyncio
    async def test_egress_observation_makes_no_second_initiative_writer_call(
            self, speech_on, monkeypatch):
        """BGS-02: инициатива не получает второго Writer'а после guard'а.

        Раньше тест проверял, что повтор egress-guard'а идёт по той же
        проекции (`generate_initiative_reply` → `_init_rewrite`). Повтора нет:
        единственный Writer получает проекцию прогона, а наблюдение едет в
        событие — манифест не может объявить `internal` при речевом payload,
        потому что второго манифеста не существует (§9.4, сц.70).
        """
        from services import direct_chat_service as dcs
        from tests.test_evol_evidence_routing import (
            _permissive_context, _plan, _Router)

        calls: list[dict] = []
        l2_text = "Вышла версия 1.5 этого ядра."

        class _Mem:
            @staticmethod
            async def get_window_messages(chat_id):
                return [{"id": 900, "tg_message_id": TG_ROOT,
                         "chat_id": CHAT_ID, "user_id": 10,
                         "author_name": "Вася",
                         "text": "обсуждали релиз 1017", "timestamp": TS,
                         "reply_to_id": None, "media_type": "text",
                         "is_forward": 0, "forward_source": None}]

        async def _persona(chat_id):
            return "persona"

        async def _writer(self, chat_id, query, *, temperature=None,
                          correlation_id=None, **kw):
            calls.append({"query": query, "speech": kw.get("speech")})
            return (l2_text, "reply")

        svc = object.__new__(dcs.DirectChatService)
        svc.tool_router = _Router(outputs={
            "execute_web_search": "Релиз 1017 вышел 1 октября"})
        svc.llm = None
        svc.db = None
        svc.memory = _Mem()
        svc._initiative_persona_block = _persona
        monkeypatch.setattr(dcs.DirectChatService, "_l2_write_answer", _writer)
        monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)

        plan = _plan(response_act="answer", external_claims=[
            {"entity": "релиз 1017", "relation": "event",
             "date": "1 октября"}])
        delivered = await svc.generate_initiative_reply(
            CHAT_ID, {"goal": "напомнить про релиз 1017"}, l1_plan=plan,
            correlation_id="run-f4i")
        # Один Writer-вызов: повтора по эвристике не существует.
        assert len(calls) == 1, calls
        assert calls[0]["speech"] is not None, calls
        # Проекция — именно этого прогона.
        assert calls[0]["speech"].run_id == "run-f4i"
        assert calls[0]["speech"].manifest()["items"], calls
        # Текст доставлен байт-в-байт (claim не вырезан).
        assert delivered == l2_text, delivered

    @pytest.mark.asyncio
    async def test_initiative_addressee_is_named_from_the_window(
            self, speech_on, monkeypatch):
        """F1 (тот же корень): адресат в plan-блоке инициативы — по имени.

        Продовый вызов: `generate_initiative_reply` собирает план через
        `build_l2_plan_block(name_of=…)` из ТОГО ЖЕ окна — «Вася (U1)», а не
        неозвучиваемая `U1` (§5.4 «Кто», §9.2).
        """
        from services import direct_chat_service as dcs
        from tests.test_evol_evidence_routing import (
            _permissive_context, _plan, _Router)

        seen: list[dict] = []

        class _Mem:
            @staticmethod
            async def get_window_messages(chat_id):
                return [{"id": 900, "tg_message_id": TG_ROOT,
                         "chat_id": CHAT_ID, "user_id": 10,
                         "author_name": "Вася",
                         "text": "обсуждали релиз 1017", "timestamp": TS,
                         "reply_to_id": None, "media_type": "text",
                         "is_forward": 0, "forward_source": None}]

        async def _persona(chat_id):
            return "persona"

        async def _writer(self, chat_id, query, *, temperature=None,
                          correlation_id=None, **kw):
            seen.append({"plan_block": kw.get("plan_block")})
            return ("Кстати, релиз уже вышел.", "reply")

        svc = object.__new__(dcs.DirectChatService)
        svc.tool_router = _Router(outputs={})
        svc.llm = None
        svc.db = None
        svc.memory = _Mem()
        svc._initiative_persona_block = _persona
        monkeypatch.setattr(dcs.DirectChatService, "_l2_write_answer", _writer)
        monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)

        plan = _plan(delivery="chat", target_user_id=10)
        await svc.generate_initiative_reply(
            CHAT_ID, {"goal": "обратиться к Васе"}, l1_plan=plan,
            correlation_id="run-f1i")
        assert seen, "инициативный Writer не вызывался"
        block = str(seen[-1]["plan_block"] or "")
        assert "смысловой адресат: Вася (U" in block, block
        assert not re.search(r"смысловой адресат: U\d+", block), block

    @pytest.mark.asyncio
    async def test_writer_reports_the_real_representation(
            self, speech_on, monkeypatch):
        """F4 ревью (сохранено после BGS-02): Writer пишет РЕАЛЬНОЕ представление.

        Повтора egress-guard'а больше нет, поэтому «манифест повтора» проверить
        нечем — но сам инвариант остаётся: единственный Writer-вызов объявляет
        `writer` и пары «метка → ID», а не `internal` (§9.3 п.7/§9.4).
        """
        from services import direct_chat_service as dcs
        from services import prompt_composer as pc

        seen: dict = {}

        def _fake_compose(**kwargs):
            seen.update(kwargs)
            return "СИСТЕМА", None

        async def _fake_compose_async(**kwargs):
            return _fake_compose(**kwargs)

        async def _gates(chat_id):
            return pc.gates_from_config()

        monkeypatch.setattr(pc, "compose_speech_system", _fake_compose_async)
        monkeypatch.setattr(pc, "composer_enabled_now", lambda gates: True)
        monkeypatch.setattr(dcs, "_composer_resolve_gates", _gates)

        svc = _service()
        projection = SpeechProjection(run_id="f4")
        projection.message_label(f"tg:{TG_ROOT}")
        out = await svc._l2_write_answer(
            CHAT_ID, "бот, это правда?",
            plan_block="", user_blocks=[f"<Global_Context>M1</Global_Context>"],
            response_plan=None, character_block="", style_directives="",
            numeric_contract=None, time_line="", evidence="",
            lessons_block="", speech_block="", temperature=0.5,
            correlation_id="corr-f4", speech=projection)
        assert out is not None and out[0] == "ответ", out
        assert seen.get("context_representation") == "writer", seen
        assert seen.get("speech_projection", {}).get("items") == {
            "M1": f"tg:{TG_ROOT}"}, seen

    @pytest.mark.asyncio
    async def test_manifest_carries_representation_and_counts(self):
        projection = SpeechProjection(run_id="run-42")
        projection.message_label(f"tg:{TG_ROOT}")
        projection.person_label(10, "Вася")
        _system, manifest = await prompt_composer.compose_speech_system(
            chat_id=CHAT_ID, writer="l2_writer", base_prompt="база",
            run_id="run-42", context_representation="writer",
            speech_projection=projection.manifest())
        assert manifest is not None
        assert manifest.context_representation == "writer"
        assert manifest.speech_projection["items"] == {"M1": f"tg:{TG_ROOT}"}
        events = prompt_composer.manifest_for_events(manifest)
        assert events["context_representation"] == "writer"
        assert events["speech_manifest"]["counts"]["items"] == 1
        # В события — только типы/счётчики, без пар «метка → ID» и текстов.
        assert "items" not in events["speech_manifest"]
        assert "participants" not in events["speech_manifest"]

    def test_effective_layers_carry_representation(self):
        manifest = prompt_composer.PromptManifest(
            system="база", chat_id=CHAT_ID, writer="l2_writer",
            context_representation="internal")
        rendered = prompt_composer.render_effective_layers(manifest)
        assert rendered["context_representation"] == "internal"
        assert rendered["speech_manifest"] == {}


# ── chat_context (узкое окно FactCheck/поиска) ─────────────────────────────

class TestWindowTruncationNoticeIsReserved:
    """F3 ревью волны потребителей: объявление вытеснения окна не исчезает.

    Место под пометку резервируется ДО распределения бюджета, поэтому при
    тесном бюджете она печатается с ТОЧНЫМ числом вытесненных строк, а не
    заменяется строкой в логе (§5.4 п.153 / §8 п.5, сц.67/111).
    """

    ROWS = 12
    BUDGET_FITS_ALL = 2000
    BUDGET_TIGHT = 700          # ровно тот случай ревью: строки вытеснены
    BUDGET_TIGHTER = 420

    def _rows(self):
        return [
            _row(1500 + i, uid=10 + (i % 3), name=f"Участник{i % 3}",
                 text=f"реплика номер {i} про волокна и прочие дела чата",
                 ts=TS + i * 60)
            for i in range(self.ROWS)
        ]

    @staticmethod
    def _shown(block: str) -> int:
        """Сколько строк окна реально показано (заголовок `[... | ...]:`)."""
        return len([line for line in block.splitlines()
                    if line.startswith("[") and "]:" in line])

    def _notice_number(self, block: str) -> int | None:
        found = re.findall(r"часть окна не показана \((\d+)\)", block)
        return int(found[0]) if found else None

    def test_tight_budget_still_announces_omission(self):
        rows = self._rows()
        full = chat_context.format_chat_context(
            rows, max_chars=self.BUDGET_FITS_ALL)
        assert self._shown(full) == self.ROWS
        assert self._notice_number(full) is None

        tight = chat_context.format_chat_context(
            rows, max_chars=self.BUDGET_TIGHT)
        shown = self._shown(tight)
        assert shown < self.ROWS, tight          # обрезка реально была
        # Пометка ЕСТЬ, и число в ней — точное число вытесненных строк.
        assert self._notice_number(tight) == self.ROWS - shown, tight
        assert len(tight) <= self.BUDGET_TIGHT

    def test_tighter_budget_keeps_exact_number(self):
        rows = self._rows()
        block = chat_context.format_chat_context(
            rows, max_chars=self.BUDGET_TIGHTER)
        shown = self._shown(block)
        assert 0 < shown < self.ROWS, block
        assert self._notice_number(block) == self.ROWS - shown, block
        assert len(block) <= self.BUDGET_TIGHTER

    def test_notice_is_reserved_not_appended(self):
        """Пометка входит в бюджет: блок НЕ превышает max_chars ни на строку."""
        rows = self._rows()
        for budget in (self.BUDGET_TIGHT, self.BUDGET_TIGHTER, 500, 350):
            block = chat_context.format_chat_context(rows, max_chars=budget)
            assert block, budget
            assert len(block) <= budget, (budget, len(block))
            if self._shown(block) < self.ROWS:
                assert self._notice_number(block) is not None, (budget, block)


class TestNarrowWindow:
    def test_narrow_window_speaks(self, speech_on):
        projection = SpeechProjection(run_id="narrow")
        block = chat_context.format_chat_context(
            [_row(TG_ROOT, text="болтовня", forward="Канал X")],
            projection=projection)
        _assert_no_service_ids(block)
        assert "Вася (U1)" in block
        assert "Переслано: Канал X" in block
        assert projection.raw_of("M1") == f"tg:{TG_ROOT}"

    def test_narrow_window_raw_without_projection(self):
        block = chat_context.format_chat_context([_row(TG_ROOT, text="x")])
        assert f"tg:{TG_ROOT}" in block
        assert "Вася" in block and "(U1)" not in block


# ── F2 ревью волны потребителей: медиа-свидетельство без служебного id ─────

class TestMediaEvidenceSpeaksInLabels:
    """`<media_analysis>` не вносит `msg:<tg_id>` в payload (§9.2, сц.67).

    Провенанс ревизии Vision — машинный слой: картинку называет метка
    прогона, а пара «метка → реальный id» остаётся в проекции/трассе.
    """

    MEDIA_TG = 7004

    def _readiness(self):
        from services import media_readiness as mr
        asset = mr.MediaAssetState(
            asset_id="asset-7004-abcdef", tg_message_id=self.MEDIA_TG,
            asset_kind="image", analysis_status=mr.ANALYSIS_READY,
            analysis_revision=3,
            ocr_blocks=({"text": "Курс доллара 92 рубля"},),
            visual_description="скриншот таблицы с курсами")
        return mr.MediaReadiness(
            chat_id=CHAT_ID, target_message_id=self.MEDIA_TG,
            source_message_ids=(self.MEDIA_TG,),
            association_kind=mr.ASSOC_REPLY,
            association_status=mr.ASSOC_RESOLVED,
            asset_id="asset-7004-abcdef", analysis_status=mr.ANALYSIS_READY,
            analysis_revision=3, ocr_blocks=asset.ocr_blocks,
            visual_description=asset.visual_description,
            assets=(asset,), media_dependent=True)

    @pytest.mark.asyncio
    async def test_media_evidence_adds_no_service_id_to_payload(self, speech_on):
        """Сканируется ВЕСЬ собранный payload хода, не только сам блок."""
        svc = _service_with_window([_row(TG_ROOT, text="смотри скрин")])
        projection = SpeechProjection(run_id="f2")
        blocks = await svc._build_user_content(
            CHAT_ID, _message(), "Вася", target_user_id=10,
            projection=projection)
        # Порядок продовый (handle): окно → медиа-свидетельство.
        blocks = svc._insert_media_evidence(
            blocks, self._readiness(), projection=projection)
        payload = "\n".join(str(b) for b in blocks if b)

        assert "<media_analysis" in payload, payload
        assert f"msg:{self.MEDIA_TG}" not in payload
        _assert_no_service_ids(_without_alias_map(payload))
        labels = re.findall(r"изображение (M\d+)", payload)
        assert labels, payload
        assert projection.raw_of(labels[0]) == f"tg:{self.MEDIA_TG}"

    def test_media_block_without_projection_stays_raw(self):
        """OFF/без проекции — прежний сырой вид байт-в-байт (откат §6.2)."""
        block = self._readiness().evidence_block()
        assert f"изображение msg:{self.MEDIA_TG}" in block


# ── Direct: медиа-маркеры текущей реплики (P1, body-маркер) ────────────────

class TestCurrentQuestionMediaMarkers:
    def test_own_media_marker_uses_run_label(self, speech_on):
        """§4.1 P1: маркер медиа в теле реплики адресует сообщение меткой."""
        from services.canonical_context import SpeechProjection
        svc = _service()
        msg = _message()
        msg.text = None
        msg.caption = "смотри"
        msg.video = None
        msg.video_note = None
        msg.photo = [object()]          # own media (photo)
        projection = SpeechProjection(run_id="run")
        block = svc._render_current_question(msg, projection=projection)
        _assert_no_service_ids(block)
        assert "[медиа: photo" in block, block
        # Метка разрешается в реальный id того же сообщения.
        labels = [label for label in _labels(block)]
        assert labels, block
        assert projection.raw_of(labels[0]) == f"tg:{msg.message_id}"

    def test_earlier_image_marker_is_rewritten_to_label(self, speech_on):
        """Доверенный маркер способа (C) — тот же речевой диалект в payload."""
        from services.canonical_context import SpeechProjection
        svc = _service()
        projection = SpeechProjection(run_id="run")
        block = svc._render_current_question(
            _message(text="что на том скрине?"),
            extra_markers=("[медиа: photo tg:777]",), projection=projection)
        _assert_no_service_ids(block)
        assert "tg:777" not in block
        assert "[медиа: photo M1]" in block, block
        assert projection.raw_of("M1") == "tg:777"

    def test_raw_form_keeps_tg_reference(self):
        """Без проекции (и для media-readiness) реф остаётся настоящим."""
        svc = _service()
        block = svc._render_current_question(
            _message(text="что на том скрине?"),
            extra_markers=("[медиа: photo tg:777]",))
        assert "tg:777" in block
        assert "[медиа: photo M1]" not in block


# ── Результат инструмента фактчека (P5): опоры видны, trace id — нет ───────

class _OriginDb:
    """Минимальная БД для envelope-маршрута tool-фактчека (свободный текст)."""

    async def get_smart_message_origin_block(self, chat_id, tg_id):
        return None

    async def get_latest_message_revision(self, chat_id, tg_id):
        return None


async def _tool_fact_check_payload(monkeypatch, *, recorded):
    """`fact_check` с подменённым сервисом: payload собирается прод-кодом."""
    import unittest.mock as mock
    from services import temporal_factcheck as tf
    from services import tool_router as tr

    evidence = ({
        "evidence_id": "ev-1", "claim_part": None,
        "url": "https://example.org/fact",
        "support": "первоисточник подтверждает тезис",
        "published_at": 1_700_000_000,
        "date_parse_status": "parsed",
        "source_kind": "primary"},)

    class _Svc:
        def __init__(self, *_a, **_kw):
            pass

        async def check_claim_envelope(self, envelope, **_kw):
            verdict = tf.verdict_from_payload(
                {"factual_verdict": "supported",
                 "temporal_status": "unknown"}, envelope)
            return tf.TemporalRunResult(
                envelope=envelope, verdict=verdict,
                verdict_text="Подтверждается. https://example.org/fact",
                evidence_rows=evidence)

    async def _fake_record(db, result, *, scope="global", cache_hit=False):
        recorded.append({"scope": scope, "claim": result.envelope.claim_text})
        return "run-machine-1"

    monkeypatch.setattr("services.factcheck_service.FactCheckService", _Svc)
    monkeypatch.setattr(tf, "record_temporal_run", _fake_record)
    router = tr.ToolRouter(tr.ToolDeps(
        mock.MagicMock(), mock.MagicMock(), db=_OriginDb(),
        llm=mock.MagicMock()))
    ctx = tr.ToolContext(CHAT_ID, "фактчек")
    ctx.reply_source_text = ""           # claim — из аргумента, не из reply
    ctx.reply_source_message_id = None
    return json.loads(await router.dispatch(
        "fact_check", {"claim": "озеро Байкал"}, ctx))


class TestToolFactCheckPayload:
    @pytest.mark.asyncio
    async def test_support_is_visible_and_trace_id_stays_machine_side(
            self, monkeypatch):
        """§9.2/§9.3 п.3: тезис/дата/автор/ссылка — модели, run id — трассе."""
        recorded: list = []
        payload = await _tool_fact_check_payload(monkeypatch,
                                                recorded=recorded)
        assert payload["status"] == "ready", payload
        assert payload["claim"] == "озеро Байкал"
        assert payload["as_of"]                                # дата проверки
        # Свободный тезис без источника: автор НЕ выдумывается (R16).
        assert payload["claim_author"] is None
        assert payload["evidence"][0]["url"] == "https://example.org/fact"
        assert payload["evidence"][0]["published_at"] == 1_700_000_000
        assert payload["evidence"][0]["source_kind"] == "primary"
        assert "первоисточник" in payload["evidence"][0]["excerpt"]
        # Корреляционная связка ушла в машинный слой (запись прогона)…
        assert recorded and recorded[0]["scope"] == f"chat:{CHAT_ID}"
        # …а служебный run id в результат инструмента не попал.
        assert "run_id" not in payload
        assert "run-machine-1" not in json.dumps(payload, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_claim_author_visible_for_reply_sourced_claim(
            self, tmp_path, monkeypatch):
        """§5.4 «Что и чьи слова»: автор проверяемого тезиса виден модели."""
        import unittest.mock as mock
        from services import temporal_factcheck as tf
        from services import tool_router as tr
        from services.database import DatabaseService

        db = DatabaseService(str(tmp_path / "tool_author.db"))
        await db.initialize()
        try:
            await db.save_smart_message(
                10, CHAT_ID, "у людей нет таких волокон", None,
                1_714_492_800, "text", "Марина", message_id=900,
                origin_type="user")

            class _Svc:
                def __init__(self, *_a, **_kw):
                    pass

                async def check_claim_envelope(self, envelope, **_kw):
                    verdict = tf.verdict_from_payload(
                        {"factual_verdict": "insufficient_evidence",
                         "temporal_status": "unknown"}, envelope)
                    return tf.TemporalRunResult(
                        envelope=envelope, verdict=verdict,
                        verdict_text="Данных недостаточно.")

            monkeypatch.setattr("services.factcheck_service.FactCheckService",
                                _Svc)
            monkeypatch.setattr(tf, "record_temporal_run",
                                _noop_record_run)
            router = tr.ToolRouter(tr.ToolDeps(
                mock.MagicMock(), mock.MagicMock(), db=db,
                llm=mock.MagicMock()))
            ctx = tr.ToolContext(CHAT_ID, "бот, это правда?")
            ctx.reply_to_message_id = 1000
            ctx.reply_source_message_id = 900
            ctx.reply_source_text = "у людей нет таких волокон"
            payload = json.loads(await router.dispatch(
                "fact_check", {"claim": "бот, это правда?"}, ctx))
            assert payload["status"] == "ready", payload
            assert payload["claim"] == "у людей нет таких волокон", payload
            assert payload["claim_author"] == "Марина", payload
        finally:
            await db.close()


async def _noop_record_run(db, result, *, scope="global", cache_hit=False):
    return "run-machine-2"


# ── Один прогон на маршрут: поиск и узкое окно фактчека ────────────────────

class TestOneProjectionPerRoute:
    @pytest.mark.asyncio
    async def test_search_route_speaks_and_keeps_reverse_map(
            self, speech_on, monkeypatch):
        """§9.3 п.3 «ответы по поиску» + §4.2 п.5: метки и обратная карта."""
        import handlers.search as search_handler
        from services import mca_events

        captured: list = []

        def _capture(name, **kwargs):
            captured.append((name, kwargs))

        monkeypatch.setattr(mca_events, "emit_mca_event", _capture)

        class _Db:
            async def get_recent_messages(self, chat_id, limit):
                return [_row(TG_ROOT, text="в чате обсуждали релиз")]

        monkeypatch.setattr(search_handler, "_db", _Db())
        block = await search_handler._fetch_chat_context(CHAT_ID, 10)
        _assert_no_service_ids(block)
        assert "Вася (U1)" in block
        assert "30.04.2024" in block
        # Обратная карта прогона — в защищённом событии (пары метка↔ID).
        events = [k for n, k in captured if n == "speech_projection"]
        assert events, captured
        items = events[-1]["entity_ids"]["items"]
        assert f"tg:{TG_ROOT}" in items.values()
        assert "U1" in events[-1]["entity_ids"]["participants"]

    @pytest.mark.asyncio
    async def test_factcheck_narrow_window_shares_one_projection(
            self, speech_on, monkeypatch):
        """N1 ревью шва: окно и цепочка узкого маршрута адресуют одной меткой."""
        import handlers.factcheck as fc_handler
        from services import chat_context as cc_mod
        from services import factcheck_context as fcx
        from services import thread_chain

        seen: dict = {}

        async def _fake_build(db, rows, **kwargs):
            seen["projection"] = kwargs.get("projection")
            return "<chat_context>ok</chat_context>"

        def _fake_chains(chain, trigger_message_id=None, *,
                     projection=None, chat_id=None, **kwargs):
            seen["chain_projection"] = projection
            return "<reply_chains/>"

        monkeypatch.setattr(cc_mod, "build_chat_context", _fake_build)
        monkeypatch.setattr(thread_chain, "render_reply_chains", _fake_chains)
        monkeypatch.setattr(fcx, "wide_context_enabled", lambda: False)
        monkeypatch.setattr(fc_handler, "_db", _DbAround())
        monkeypatch.setattr(fc_handler, "_cp_g", _fake_cp_g)
        monkeypatch.setattr(thread_chain, "collect_thread_chain",
                            _fake_chain_rows)
        await fc_handler._fetch_chat_context(
            CHAT_ID, 2, 2, target_tg_message_id=TG_ROOT,
            trigger_message_id=TG_CHILD)
        projection = seen.get("projection")
        assert isinstance(projection, SpeechProjection), seen
        # Цепочка получила ТУ ЖЕ проекцию прогона (не свою).
        assert seen.get("chain_projection") is projection


class _DbAround:
    async def get_messages_around(self, chat_id, anchor, before, after):
        return [_row(TG_ROOT, text="тезис")]


async def _fake_chain_rows(db, chat_id, tg_id, depth, **_kwargs):
    return []


async def _fake_cp_g(chat_id, key, default=None):
    return default



