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


async def _fake_chain_rows(db, chat_id, tg_id, depth):
    return []


async def _fake_cp_g(chat_id, key, default=None):
    return default



