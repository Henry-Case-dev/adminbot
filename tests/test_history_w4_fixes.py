"""P0-HA волна 4 — правки по ревью review-w4-isolation-quality.md.

Блокеры:
* 1 — детерминированные страховки качества (claim_envelope) стоят НА ХОДЕ
  сегментного накопления: тип находки, гейт черт из шуток/единичных
  реплик, атрибуция пересылок, придуманные количества/даты не едут в
  @@HISTORY_COVERAGE как факт (честный флаг/срез, не краш сегмента);
* 2 — идентичность по Telegram user_id: строки выборки несут uid (приём
  `_speaker_tag`), сравнение людей — по uid (строка 475/H25), путь B
  (query) и ходы без выборки не меняются;
* 3 — при композере OFF баннер дополнения вешается ТОЛЬКО на head-конспект
  (вне диапазона), дословные строки окна не метятся;
* 4 — system2 Stage-2 при активной выборке получает ПОЛНЫЙ
  HISTORY_COVERAGE_ASSEMBLY_BLOCK после scrub; без выборки — байт-паритет.

SQLite in-memory, без сети; тексты сообщений в логи не попадают (R17).
TEST-LIFECYCLE: REGRESSION owner=P0-HA wave-4 review fixes
"""
import json
import os
import re
from unittest.mock import MagicMock

import pytest

from config.settings import settings
from services import chat_params
from services import claim_envelope as _ce
from services import hot_config as hot
from services import prompt_composer as pc
from services.chat_prompts import DIRECT_VERBALIZER_SYSTEM_PROMPT
from services.canonical_context import format_context_item
from services.claim_envelope import (
    FINDING_KIND_BOT_STATEMENT,
    FINDING_KIND_JOKE,
    classify_finding_kind,
    parse_finding_identity,
)
from services.database import DatabaseService
from services.direct_chat_service import (
    DirectChatService,
    _ha_strip_invented_claims,
    _history_line_item_id,
)
from services.prompt_style_blocks import (
    HISTORY_COVERAGE_ASSEMBLY_BLOCK,
    compose_verbalizer_system,
)
from services.summary_aliases import AliasResolver
from services.token_counter import count_tokens, safe_budget
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolRouter,
    capture_history_sample,
)

CHAT_ID = -1001234567890

# Граничная строка in-range региона <Global_Context> (блокер A review-w4-fix)
# — пин литерала: зеркалит services.direct_chat_service._HA_INRANGE_TAIL_LABEL.
HA_INRANGE_TAIL_LABEL = ("фон: ниже — дословные сообщения "
                         "запрошенного диапазона")


@pytest.fixture(autouse=True)
def _pg_down():
    """Код-каноны и композер OFF (дефолт офлайн-стендов)."""
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    prev = os.environ.pop("UNIFIED_COMPOSER_ENABLED", None)
    yield
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    if prev is not None:
        os.environ["UNIFIED_COMPOSER_ENABLED"] = prev


# ── сегментный стенд (зеркало test_history_segments.py) ─────────────────────

def _pad(text: str, width: int = 650) -> str:
    """Удлинить текст, чтобы выборка не влезала в минимальный слот 500 —
    иначе сработает короткий путь без сегментации."""
    return f"{text} " + "х" * max(1, width - len(text))


async def _make_db(rows) -> DatabaseService:
    """Реальная DatabaseService на SQLite in-memory; ts = tg_id = i."""
    db = DatabaseService(":memory:")
    await db.initialize()
    for i, row in enumerate(rows, start=1):
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name, "
            "reply_to_id, tg_message_id, is_forward, forward_source) "
            "VALUES (?, ?, ?, ?, 'text', ?, NULL, ?, ?, ?)",
            (row.get("user_id", 1), CHAT_ID, row["text"], i,
             row.get("author_name", "автор"), i,
             1 if row.get("forward_source") else 0,
             row.get("forward_source", "")))
    await db.db.commit()
    return db


class SegmentLLM:
    """Фейковый LLM: ответ как функция (индекс вызова, промпт)."""

    def __init__(self, responder=None):
        self.calls = []
        self.responder = responder

    async def generate(self, messages, temperature=None, chat_id=None, **kw):
        prompt = messages[0]["content"]
        self.calls.append((prompt, {"step": kw.get("step")}))
        if self.responder is None:
            return '{"events":[],"status":"ok"}'
        return self.responder(len(self.calls) - 1, prompt)


def _service(db, llm) -> DirectChatService:
    router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                 aliases=None, db=db))
    return DirectChatService(MagicMock(), db, llm, AliasResolver("{}"),
                             tool_router=router)


async def _make_turn(db, depth):
    """Захват выборки + первая страница инструмента → (ctx, raw)."""
    ctx = ToolContext(CHAT_ID, f"проанализируй последние {depth} сообщений")
    bound = await capture_history_sample(db, CHAT_ID, depth)
    assert bound is not None
    ctx.history_sample = bound
    page = await ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     aliases=None, db=db)).dispatch(
        "get_recent_history", {"depth": depth}, ctx)
    from services.direct_execution import ChainResult, EvidenceSource
    raw = ChainResult(page, evidence_sources=[
        EvidenceSource(tool="get_recent_history", status="ok",
                       content=page, total_chars=len(page))],
        chain_meta={})
    return ctx, raw


def _coverage(block: str):
    """(поля головы, строки event) блока покрытия."""
    lines = block.splitlines()
    assert lines[0].startswith("@@HISTORY_COVERAGE"), block[:200]
    fields: dict = {}
    event_lines: list = []
    after_end = False
    for line in lines[1:]:
        if line == "@@END_COVERAGE":
            after_end = True
            continue
        if line.startswith("event "):
            event_lines.append(line)
            continue
        if line.startswith("seg "):
            continue
        if not after_end and "=" in line:
            key, _, val = line.partition("=")
            fields[key.strip()] = val.strip()
    return fields, event_lines


def _event_field(line: str, key: str) -> str:
    """Значение ключа на строке события (до следующего « ключ=» или конца)."""
    match = re.search(rf"(?:^| ){re.escape(key)}=(.*?)(?: \w+=|$)", line)
    assert match is not None, f"{key} не найден: {line}"
    return match.group(1)


def _note_responder(note: str, *, refs=None):
    """Сегмент-осведомлённый стаб: событие с фиксированной note на КАЖДЫЙ
    сегмент; refs = все id из тела сегмента (или фиксированный список).
    Нужен потому, что принудительная сегментация (слот 500) при короткой
    выборке режет её на несколько сегментов — по одному вызову LLM на
    каждый (H20)."""

    def respond(idx, prompt):
        start = prompt.find("<segment>") + len("<segment>")
        end = prompt.find("</segment>")
        body = prompt[start:end]
        found: list = []
        for line in body.splitlines():
            item_id = _history_line_item_id(line)
            if item_id and item_id not in found:
                found.append(item_id)
        use = refs if refs is not None else found
        return json.dumps({"events": [{"refs": use, "continues": 0,
                                       "note": note}],
                           "status": "ok"})

    return respond


# ── блокер 2: uid в строках выборки и identity по uid ───────────────────────

class TestSampleLinesCarryUserId:
    @pytest.mark.asyncio
    async def test_sample_page_lines_render_uid(self):
        """Страница выборки (путь A) различает двух «Алексеев» по uid."""
        db = await _make_db([
            {"user_id": 111, "author_name": "Алексей", "text": "я за"},
            {"user_id": 222, "author_name": "Алексей", "text": "я против"},
        ])
        try:
            out = await ToolRouter(ToolDeps(
                search=MagicMock(), memory=MagicMock(), aliases=None,
                db=db)).dispatch("get_recent_history", {"depth": 2},
                                 ToolContext(CHAT_ID, "последние 2"))
        finally:
            await db.db.close()
        assert "Алексей [111]" in out and "Алексей [222]" in out

    @pytest.mark.asyncio
    async def test_query_path_lines_unchanged(self):
        """Путь B (FTS query) — не выборка: формат строк не меняется."""
        import time as _time
        memory = MagicMock()

        async def fake_search(*a, **k):
            return [{"user_id": 111, "author_name": "Алексей",
                     "text": "нашли меня", "timestamp": int(_time.time()),
                     "id": 7, "chat_id": CHAT_ID}]

        memory.search_long_term = fake_search
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory,
                                     aliases=None, db=None))
        out = await router.dispatch("get_recent_history",
                                    {"query": "нашли"},
                                    ToolContext(CHAT_ID, "нашли"))
        assert "Алексей [111]" not in out
        assert "Алексей" in out

    @pytest.mark.asyncio
    async def test_segment_tail_lines_render_uid(self):
        """Недочитанный хвост выборки (keyset-читатель) тоже несёт uid."""
        rows = [{"user_id": 111, "author_name": "Алексей",
                 "text": _pad(f"м{i}", 40)} for i in range(1, 51)]
        db = await _make_db(rows)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 50)
        try:
            block = await service.collect_history_segments(
                ctx, raw, slot_chars=100000, chat_id=CHAT_ID)
        finally:
            await db.db.close()
        assert block is not None
        assert llm.calls
        seen_uid = False
        for prompt, _kw in llm.calls:
            body = prompt.split("<segment>\n", 1)[1].split("\n</segment>", 1)[0]
            seen_uid = seen_uid or "Алексей [111]" in body
        assert seen_uid, "строки хвоста выборки без Telegram user_id"

    def test_parse_finding_identity_extracts_uid(self):
        """Разбор канонической строки с uid: display без скобки + user_id."""
        line = format_context_item(
            ts=1000, author="Алексей [111]", item_id="tg:5",
            text="привет", kind="msg")
        ident = parse_finding_identity(line)
        assert getattr(ident, "user_id", None) == 111
        assert ident.display_name == "Алексей"
        assert ident.ref == "tg:5"

    def test_parse_finding_identity_without_uid(self):
        """Строки без uid (старый формат/путь B) — user_id None, имя целое."""
        line = format_context_item(
            ts=1000, author="Алексей", item_id="tg:5", text="привет",
            kind="msg")
        ident = parse_finding_identity(line)
        assert getattr(ident, "user_id", None) is None
        assert ident.display_name == "Алексей"

    def test_identity_matches_by_user_id(self):
        """H25 по uid: разные uid с одним именем НЕ сливаются; два сообщения
        одного uid — один человек; без uid — падение на сравнение ref."""
        line_a = format_context_item(ts=1000, author="Алексей [111]",
                                     item_id="tg:11", text="я за", kind="msg")
        line_b = format_context_item(ts=2000, author="Алексей [222]",
                                     item_id="tg:22", text="я против",
                                     kind="msg")
        line_c = format_context_item(ts=3000, author="Алексей [111]",
                                     item_id="tg:33", text="и ещё раз",
                                     kind="msg")
        a, b, c = (parse_finding_identity(x) for x in (line_a, line_b, line_c))
        assert _ce.identity_matches(a, b) is False      # разные uid
        assert _ce.identity_matches(a, c) is True       # тот же uid
        # совместимый падение: без uid — сравнение по ref сообщения
        assert _ce.identity_matches("tg:11", "tg:11") is True
        assert _ce.identity_matches("tg:11", "tg:22") is False


# ── блокер 1: страховки качества на ходе ────────────────────────────────────

class TestClassifierWordBoundary:
    def test_cosmic_ship_is_not_news(self):
        """«сми» внутри «космический» не делает строку новостью."""
        assert classify_finding_kind("космический корабль") \
            != _ce.FINDING_KIND_EXTERNAL_NEWS

    def test_dispute_markers_still_match(self):
        assert classify_finding_kind("поспорили о религии") \
            == _ce.FINDING_KIND_DISPUTE
        assert classify_finding_kind("разногласия по срокам") \
            == _ce.FINDING_KIND_DISPUTE

    def test_besporyadki_not_dispute(self):
        assert classify_finding_kind(
            "навели порядок после беспорядков") \
            != _ce.FINDING_KIND_DISPUTE

    def test_joke_prefixed_verb(self):
        assert classify_finding_kind("вася пошутил про дедлайн") \
            == FINDING_KIND_JOKE

    def test_news_joke_markers_still_match(self):
        assert classify_finding_kind("новость о задержке рейсов") \
            == _ce.FINDING_KIND_EXTERNAL_NEWS
        assert classify_finding_kind("объяснение было шуткой") \
            == FINDING_KIND_JOKE


class TestTraitNoteMarker:
    def test_trait_language_detected(self):
        assert _ce.note_claims_stable_trait("вася циник по натуре") is True
        assert _ce.note_claims_stable_trait("он всегда так шутит") is True
        assert _ce.note_claims_stable_trait("обсуждали релиз") is False
        assert _ce.note_claims_stable_trait("") is False


class TestSegmentGuards:
    async def _run(self, rows, responder):
        db = await _make_db(rows)
        llm = SegmentLLM(responder)
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, len(rows))
        try:
            return await service.collect_history_segments(
                ctx, raw, slot_chars=500, chat_id=CHAT_ID)
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_joke_as_trait_flagged(self):
        """Шутка, превращённая моделью в черту: kind=joke, флаг
        trait_unverified — черта не едет в покрытие как факт."""
        rows = [{"user_id": 111, "author_name": "Алексей",
                 "text": _pad("ну да, дедлайн как всегда")}]

        def respond(idx, prompt):
            return json.dumps({"events": [{"refs": ["tg:1"], "continues": 0,
                                           "note": "это была шутка, а "
                                           "алексей — циник по натуре"}],
                               "status": "ok"})

        block = await self._run(rows, respond)
        assert block is not None
        _fields, events = _coverage(block)
        assert len(events) == 1
        assert _event_field(events[0], "kind") == FINDING_KIND_JOKE
        assert "trait_unverified" in _event_field(events[0], "flags")

    @pytest.mark.asyncio
    async def test_invented_count_stripped_and_flagged(self):
        """«5 раз» при меньшем числе refs: число не едет в note как факт."""
        rows = [{"user_id": 1, "author_name": "вася", "text": _pad("релиз")},
                {"user_id": 1, "author_name": "вася",
                 "text": _pad("снова релиз")}]

        block = await self._run(
            rows, _note_responder("обсуждали релиз 5 раз"))
        _fields, events = _coverage(block)
        assert events
        for line in events:
            note = _event_field(line, "note")
            assert "5" not in note
            assert "обсуждали релиз" in note
            assert "invented_count:5" in _event_field(line, "flags")

    @pytest.mark.asyncio
    async def test_invented_date_stripped_and_flagged(self):
        """Дата вне дат refs: не едет в note как факт."""
        rows = [{"user_id": 1, "author_name": "вася",
                 "text": _pad("встреча")}]

        block = await self._run(
            rows, _note_responder("15.03.2025 была встреча"))
        _fields, events = _coverage(block)
        assert len(events) == 1
        note = _event_field(events[0], "note")
        assert "15.03.2025" not in note
        assert "встреча" in note
        assert "invented_date:15.03.2025" in _event_field(events[0], "flags")

    @pytest.mark.asyncio
    async def test_invented_date_nonpadded_stripped_and_flagged(self):
        """Неприбитая нулём дата (блокер B review-w4-fix): срезается из
        note, флаг несёт ТОЧНОЕ написание из note («5.10.2024», не
        нормализованную «05.10.2024»)."""
        rows = [{"user_id": 1, "author_name": "вася",
                 "text": _pad("встреча")}]

        block = await self._run(
            rows, _note_responder("5.10.2024 была встреча"))
        _fields, events = _coverage(block)
        assert len(events) == 1
        note = _event_field(events[0], "note")
        assert "5.10.2024" not in note
        assert "встреча" in note
        assert "invented_date:5.10.2024" in _event_field(events[0], "flags")

    @pytest.mark.asyncio
    async def test_invented_date_month_nonpadded_stripped(self):
        """«15.3.2025» (месяц без нуля): тот же срез из note и точный
        флаг, что и у прибитой формы."""
        rows = [{"user_id": 1, "author_name": "вася",
                 "text": _pad("встреча")}]

        block = await self._run(
            rows, _note_responder("15.3.2025 была встреча"))
        _fields, events = _coverage(block)
        assert len(events) == 1
        note = _event_field(events[0], "note")
        assert "15.3.2025" not in note
        assert "встреча" in note
        assert "invented_date:15.3.2025" in _event_field(events[0], "flags")

    @pytest.mark.asyncio
    async def test_ref_stamp_date_stays_in_note(self):
        """Дата, которую подтверждает штамп ref-строки (ts=1 →
        01.01.1970): в note остаётся, флага выдуманной нет."""
        rows = [{"user_id": 1, "author_name": "вася",
                 "text": _pad("встреча")}]

        block = await self._run(
            rows, _note_responder("01.01.1970 была встреча"))
        _fields, events = _coverage(block)
        assert len(events) == 1
        note = _event_field(events[0], "note")
        assert "01.01.1970" in note
        assert "встреча" in note
        assert " flags=" not in events[0]

    @pytest.mark.asyncio
    async def test_forward_attribution_owner_and_conflict(self):
        """Пересылка от РБК: контент — слова исходного автора; «Вася
        сообщил» — конфликт атрибуции, владелец указан."""
        rows = [{"user_id": 1, "author_name": "Вася",
                 "forward_source": "РБК Новости", "text": _pad("Курс")}]

        def respond(idx, prompt):
            return json.dumps({"events": [{"refs": ["tg:1"], "continues": 0,
                                           "note": "Вася сообщил про курс"}],
                               "status": "ok"})

        block = await self._run(rows, respond)
        _fields, events = _coverage(block)
        assert len(events) == 1
        assert "attribution_conflict" in _event_field(events[0], "flags")
        assert _event_field(events[0], "owner") == "РБК Новости"
        assert _event_field(events[0], "kind") == _ce.FINDING_KIND_FORWARDED

    @pytest.mark.asyncio
    async def test_clean_note_no_flags_kind_annotated(self):
        """Чистая находка: флагов нет, тип аннотирован — прежнее содержимое
        (refs/note/continues/mentions) сохранено."""
        rows = [{"user_id": 1, "author_name": "вася", "text": _pad("релиз")},
                {"user_id": 1, "author_name": "вася",
                 "text": _pad("ещё релиз")}]

        block = await self._run(rows, _note_responder("обсуждали релиз"))
        _fields, events = _coverage(block)
        assert events
        for line in events:
            assert " flags=" not in line
            # сегмент-осведомлённый стаб: refs — id тела сегмента
            assert _event_field(line, "kind") \
                == _ce.FINDING_KIND_SINGLE_REMARK
            assert _event_field(line, "note") == "обсуждали релиз"

    @pytest.mark.asyncio
    async def test_foreign_ref_still_dropped(self):
        """refs вне сегмента/выборки отброшены (шов own через общий
        валидатор) — прежнее поведение волны 3 сохранено."""
        rows = [{"user_id": 1, "author_name": "вася", "text": _pad("релиз")}]

        def respond(idx, prompt):
            return json.dumps({"events": [{"refs": ["tg:1", "tg:999"],
                                           "continues": 0,
                                           "note": "обсуждали релиз"}],
                               "status": "ok"})

        block = await self._run(rows, respond)
        _fields, events = _coverage(block)
        assert len(events) == 1
        assert _event_field(events[0], "refs") == "tg:1"

    @pytest.mark.asyncio
    async def test_bot_statement_kind_by_uid(self):
        """Сообщение бота: kind=bot_statement, черты из него не выводятся."""
        rows = [{"user_id": 4242, "author_name": "AsapBot",
                 "text": _pad("я подтверждаю деплой")}]
        db = await _make_db(rows)
        llm = SegmentLLM()
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     aliases=None, db=db))
        service = DirectChatService(MagicMock(), db, llm, AliasResolver("{}"),
                                    tool_router=router)
        service.bot_id = 4242

        def respond(idx, prompt):
            return json.dumps({"events": [{"refs": ["tg:1"], "continues": 0,
                                           "note": "бот подтвердил деплой, "
                                           "он надёжен по натуре"}],
                               "status": "ok"})

        llm.responder = respond
        ctx, raw = await _make_turn(db, 1)
        try:
            block = await service.collect_history_segments(
                ctx, raw, slot_chars=500, chat_id=CHAT_ID)
        finally:
            await db.db.close()
        assert block is not None
        _fields, events = _coverage(block)
        assert len(events) == 1
        assert _event_field(events[0], "kind") == FINDING_KIND_BOT_STATEMENT
        assert "trait_unverified" in _event_field(events[0], "flags")

    @pytest.mark.asyncio
    async def test_guard_failure_degrades_not_crashes(self):
        """Сбой страховки — честный флаг guard_error, сегмент не падает."""
        rows = [{"user_id": 1, "author_name": "вася", "text": _pad("релиз")}]
        db = await _make_db(rows)
        llm = SegmentLLM()

        def boom(*a, **k):
            raise RuntimeError("guard down")

        orig = _ce.invented_count_violations
        _ce.invented_count_violations = boom
        try:
            service = _service(db, llm)

            def respond(idx, prompt):
                return json.dumps({"events": [{"refs": ["tg:1"],
                                               "continues": 0,
                                               "note": "обсуждали релиз"}],
                                   "status": "ok"})

            llm.responder = respond
            ctx, raw = await _make_turn(db, 1)
            block = await service.collect_history_segments(
                ctx, raw, slot_chars=500, chat_id=CHAT_ID)
        finally:
            _ce.invented_count_violations = orig
            await db.db.close()
        assert block is not None
        fields, events = _coverage(block)
        assert fields["failed"] == "0"
        assert len(events) == 1
        assert "guard_error" in _event_field(events[0], "flags")
        assert _event_field(events[0], "note") == "обсуждали релиз"


# ── блокер B review-w4-fix2: срез даты — целый токен ────────────────────────

class TestInventedDateTokenBoundary:
    """«5.10.2024» — подстрока «15.10.2024» и «05.10.2024»: сырой
    str.replace уничтожал подтверждённую штампом дату и оставлял обрывок
    «1». Срез — только целый токен даты (границы по слову/цифре);
    одиночные неприбитые формы срезаются как прежде (флаг — точное
    написание из note)."""

    def _svc(self) -> DirectChatService:
        svc = object.__new__(DirectChatService)
        svc.bot_id = 999
        return svc

    @staticmethod
    def _line(ts: int) -> str:
        return format_context_item(ts=ts, author="vasya [10]",
                                   item_id="tg:1", text="встреча",
                                   kind="msg")

    def test_strip_is_whole_token(self):
        """Чистая функция: подтверждённая «15.10.2024» не задета срезом
        выдуманной «5.10.2024»."""
        assert _ha_strip_invented_claims(
            "15.10.2024 ok 5.10.2024 bad", [], ["5.10.2024"]) \
            == "15.10.2024 ok bad"

    def test_confirmed_date_survives_short_invented_neighbour(self):
        """Штамп 15.10.2024 подтверждает «15.10.2024»; соседняя выдуманная
        «5.10.2024» уходит целиком — без обрывка «1 was real»."""
        result = self._svc()._ha_guard_event(
            "15.10.2024 was real, but 5.10.2024 was not",
            ["tg:1"], {"tg:1": self._line(1728993600)})  # 15.10.2024 12:00
        assert result["note"] == "15.10.2024 was real, but was not"
        assert result["flags"] == ["invented_date:5.10.2024"]

    def test_march_pair_same_behavior(self):
        """Та же пара «15.03.2025» / «5.03.2025» при штампе 15.03.2025."""
        result = self._svc()._ha_guard_event(
            "15.03.2025 was real, but 5.03.2025 was not",
            ["tg:1"], {"tg:1": self._line(1742031000)})  # 15.03.2025 09:30
        assert result["note"] == "15.03.2025 was real, but was not"
        assert result["flags"] == ["invented_date:5.03.2025"]

    def test_two_invented_dates_both_stripped_whole(self):
        """Обе даты выдуманы (штамп не подтверждает ни одну): длинная
        «15.10.2024» уходит ЦЕЛИКОМ, цифры «1» в note не остаётся; флаг —
        оба точных написания в порядке детектора."""
        result = self._svc()._ha_guard_event(
            "5.10.2024 and 15.10.2024 both invented",
            ["tg:1"], {"tg:1": self._line(1000)})        # 01.01.1970
        assert result["note"] == "and both invented"
        assert result["flags"] == ["invented_date:5.10.2024,15.10.2024"]


# ── блокер 3: композер OFF — баннер только у конспекта ──────────────────────

class _FakeMemory:
    def __init__(self, window):
        self.window = window

    async def get_window_messages(self, chat_id):
        return self.window


class _FakeDb:
    def __init__(self, summary):
        self.summary = summary

    async def get_running_summary(self, chat_id, now):
        return self.summary

    async def get_summary_level(self, chat_id, level):
        return None


def _window_row(uid, name, text, ts, tg):
    return {"user_id": uid, "author_name": name, "text": text,
            "timestamp": ts, "id": tg, "tg_message_id": tg,
            "is_forward": 0, "forward_source": "", "reply_to_id": None}


def _off_service(window, summary):
    """DirectChatService с реальными `_build_user_content` и
    `_build_global_context`; тяжёлые соседи заглушены (композер OFF)."""
    import services.direct_chat_service as dcs

    class _Svc(DirectChatService):
        def _participant_roster(self, window, active, usernames=None):
            return {}, {}

        def _alias_map_block(self, roster):
            return ""

        def _is_reply_trigger(self, message):
            return False

        def _render_thread(self, chain, suffix_map, limit,
                           trigger_message_id=None, truncate=True):
            return ""

        def _render_current_question(self, message, extra_markers=()):
            return ""

        def _build_mood_block(self, text):
            return ""

        def _apply_context_budget(self, blocks, *a, **kw):
            return list(blocks)

        async def _active_participants(self, chat_id):
            return []

        async def _collect_thread_chain(self, chat_id, message, depth=None):
            return []

        async def _build_rag_block(self, *a, **kw):
            return "", ""

        async def _thread_limit(self, chat_id):
            return 100

        async def _build_user_relations(self, *a, **kw):
            return ""

        async def _chat_lore_state(self, chat_id):
            return False, ""

        async def _build_protected_facts(self, *a, **kw):
            return ""

        async def _build_style_anchors(self, chat_id):
            return ""

        async def _check_context_config_invariant(self, *a, **kw):
            return None

    svc = _Svc.__new__(_Svc)
    svc.memory = _FakeMemory(window)
    svc.db = _FakeDb(summary)
    svc.bot_id = 999
    svc.aliases = AliasResolver("{}")
    return svc, dcs


class _Msg:
    message_id = 1
    text = "разбери последние сообщения"


class TestComposerOffBannerPlacement:
    async def _global_block(self, window, summary, with_sample,
                            max_tokens=None):
        import services.budget_gate as bg

        async def _master(chat_id=None):
            return False

        old = bg.budgets_enabled
        bg.budgets_enabled = _master
        try:
            svc, dcs = _off_service(window, summary)
            prev_limit = None
            if max_tokens is not None:
                # штатная ветка усечения: потолок фона ниже конспекта
                # (settings — frozen dataclass: патч через object.__setattr__)
                prev_limit = dcs.settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS
                object.__setattr__(dcs.settings,
                                   "CHAT_GLOBAL_CONTEXT_MAX_TOKENS",
                                   max_tokens)
            prev = dcs.chat_summary_enabled

            async def _summ_on(chat_id):
                return summary is not None

            dcs.chat_summary_enabled = _summ_on
            try:
                blocks = await svc._build_user_content(
                    CHAT_ID, _Msg(), "вася", None,
                    history_sample=({"sample_id": "hs_ab12cd34ef56"}
                                    if with_sample else None))
            finally:
                dcs.chat_summary_enabled = prev
                if prev_limit is not None:
                    object.__setattr__(dcs.settings,
                                       "CHAT_GLOBAL_CONTEXT_MAX_TOKENS",
                                       prev_limit)
            return blocks
        finally:
            bg.budgets_enabled = old

    @pytest.mark.asyncio
    async def test_banner_on_conspect_only_in_range_lines_unlabeled(self):
        """OFF + выборка + конспект: баннер возглавляет ТОЛЬКО регион
        конспекта (вне диапазона); дословные строки окна идут после явной
        граничной строки in-range региона — «не подтверждает события
        внутри запрошенного диапазона» их не накрывает (блокер A
        review-w4-fix: баннер над склейкой head+tail был дефектом)."""
        window = [_window_row(10, "вася", "свежее сообщение из окна", 500, 7)]
        blocks = await self._global_block(
            window, {"summary": "конспект прошлого фона", "raw_count": 7,
                     "window_end_ts": 0}, with_sample=True)
        global_block = next(t for k, t in blocks if k == "global")
        lines = global_block.splitlines()
        assert lines[0] == "<Global_Context>"
        assert lines[1].startswith("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_ab12cd34ef56")
        assert global_block.count("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ") == 1
        verbatim = [ln for ln in lines if "свежее сообщение из окна" in ln]
        assert verbatim, "дословный хвост окна потерян"
        idx_verbatim = lines.index(verbatim[0])
        # порядок регионов: баннер → конспект → граница → дословные строки
        assert HA_INRANGE_TAIL_LABEL in lines, \
            "in-range регион не отделён явной граничной строкой"
        idx_boundary = lines.index(HA_INRANGE_TAIL_LABEL)
        idx_conspect = next(i for i, ln in enumerate(lines)
                            if "конспект из 7 сообщений" in ln)
        assert 1 < idx_conspect < idx_boundary < idx_verbatim
        # регион дополнения (баннер..граница) несёт конспект; in-range
        # регион (после границы) — без меток дополнения
        supplement_region = "\n".join(lines[1:idx_boundary])
        assert "конспект прошлого фона" in supplement_region
        inrange_region = "\n".join(lines[idx_boundary:])
        assert "ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ" not in inrange_region
        assert "вне выборки" not in inrange_region

    @pytest.mark.asyncio
    async def test_inrange_region_covers_all_window_lines(self):
        """Все дословные строки окна — в in-range регионе после граничной
        строки, ни одна не осталась под баннером дополнения."""
        window = [_window_row(10, "вася", "первое сообщение окна", 500, 7),
                  _window_row(11, "петя", "второе сообщение окна", 510, 8)]
        blocks = await self._global_block(
            window, {"summary": "конспект прошлого фона", "raw_count": 7,
                     "window_end_ts": 0}, with_sample=True)
        global_block = next(t for k, t in blocks if k == "global")
        lines = global_block.splitlines()
        idx_boundary = lines.index(HA_INRANGE_TAIL_LABEL)
        for marker in ("первое сообщение окна", "второе сообщение окна"):
            hit = [ln for ln in lines if marker in ln]
            assert hit, f"строка окна потеряна: {marker}"
            assert lines.index(hit[0]) > idx_boundary, \
                f"строка окна под баннером дополнения: {marker}"
        inrange_region = "\n".join(lines[idx_boundary:])
        assert "ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ" not in inrange_region
        assert "вне выборки" not in inrange_region

    @pytest.mark.asyncio
    async def test_verbatim_only_global_gets_no_banner(self):
        """OFF + выборка БЕЗ конспекта: всё тело — дословные строки окна
        (внутри диапазона) — баннера нет вовсе."""
        window = [_window_row(10, "вася", "свежее сообщение из окна", 500, 7)]
        blocks = await self._global_block(window, None, with_sample=True)
        global_block = next(t for k, t in blocks if k == "global")
        assert "ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ" not in global_block
        assert "свежее сообщение из окна" in global_block

    @pytest.mark.asyncio
    async def test_no_sample_parity_no_banner(self):
        """OFF без выборки: баннера нет (прежний ход)."""
        window = [_window_row(10, "вася", "обычное сообщение", 500, 7)]
        blocks = await self._global_block(window, None, with_sample=False)
        global_block = next(t for k, t in blocks if k == "global")
        assert "ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ" not in global_block
        assert "обычное сообщение" in global_block

    @pytest.mark.asyncio
    async def test_overflow_conspect_remainder_stays_under_banner(self):
        """Конспект длиннее потолка фона (штатная keep-head ветка
        усечения, блокер A review-w4-fix2): выживший остаток конспекта
        остаётся под баннером дополнения; граничной строки нет — её может
        открыть только выжившая строка окна, а усечение её унесло.
        Инвариант: после границы не бывает не-оконного контента."""
        long_summary = ("CONSPECTUS_TAIL_MARKER остаток конспекта "
                        + "заполнение фона " * 300)
        window = [_window_row(10, "вася", "свежее сообщение из окна", 500, 7)]
        blocks = await self._global_block(
            window, {"summary": long_summary, "raw_count": 100,
                     "window_end_ts": 0}, with_sample=True, max_tokens=40)
        global_block = next(t for k, t in blocks if k == "global")
        lines = global_block.splitlines()
        assert lines[1].startswith("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_ab12cd34ef56")
        # дословная строка окна срезана потолком (стенд переполнения верен)
        assert "свежее сообщение из окна" not in global_block, \
            "строка окна пережила усечение — стенд не переполнен"
        assert "CONSPECTUS_TAIL_MARKER" in global_block, \
            "остаток конспекта не пережил keep-head срез — стенд неверен"
        assert HA_INRANGE_TAIL_LABEL not in lines, \
            "граница без выживших строк окна: остаток конспекта " \
            "назван дословными сообщениями диапазона"
        idx_conspect = next(i for i, ln in enumerate(lines)
                            if "CONSPECTUS_TAIL_MARKER" in ln)
        assert 1 < idx_conspect, "остаток конспекта не под баннером"

    @pytest.mark.asyncio
    async def test_no_inrange_lines_no_boundary(self):
        """Все строки окна старше window_end_ts (дословный хвост пуст):
        баннер над конспектом, граничной строки нет — инвариант «граница
        только перед строками окна»."""
        window = [_window_row(10, "вася", "старое сообщение окна", 500, 7)]
        blocks = await self._global_block(
            window, {"summary": "конспект прошлого фона", "raw_count": 7,
                     "window_end_ts": 10 ** 9}, with_sample=True)
        global_block = next(t for k, t in blocks if k == "global")
        lines = global_block.splitlines()
        assert "старое сообщение окна" not in global_block
        assert "конспект прошлого фона" in global_block
        assert HA_INRANGE_TAIL_LABEL not in lines
        assert global_block.count("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ") == 1


# ── блокер review-w4-fix4: штатный потолок — пересчёт выживших строк окна ───

def _max_tokens_for_budget(budget: int) -> int:
    """max_tokens, дающий safe_budget ровно ``budget`` (множитель запаса —
    из дефолтов стенда; hot-кэш сброшен фикстурой)."""
    mult = float(hot.get("models.token_safety_multiplier",
                         settings.TOKEN_SAFETY_MULTIPLIER))
    start = max(1, int(budget * mult) - 3)
    for mt in range(start, start + 8):
        if safe_budget(mt) == budget:
            return mt
    raise AssertionError(f"safe_budget не достигает {budget}")


class TestStandardCeilingBoundaryRecount:
    """Блокер review-w4-fix4: ШТАТНАЯ ветка усечения (шаг 1 —
    trim_verbatim_lines под потолком; keep-head резерв не запускается).
    Существующие тесты переполнения берут крошечный потолок и попадают в
    другую ветку, поэтому дефект не ловили. До фикса счёт выживших строк
    окна не пересчитывался после штатного трима: граница in-range региона
    вставала ВНУТРИ выживших дословных строк окна (часть in-range
    сообщений под баннером, дубль строки) или оставалась пустой при
    полностью срезанном хвосте. Родитель 6d800b07 в обоих стендах вёл
    себя верно (граница перед всеми выжившими / границы нет вовсе)."""

    async def _block(self, window, summary, budget):
        helper = TestComposerOffBannerPlacement()
        return await helper._global_block(
            window, summary, with_sample=True,
            max_tokens=_max_tokens_for_budget(budget))

    @staticmethod
    def _rendered(window):
        """Точные канонические строки окна тем же рендером, что в
        _build_global_context (для экзакт-замеров счётчиком токенов)."""
        probe, _dcs = _off_service(window, None)
        return [probe._context_row_line(row, {}) for row in window]

    @staticmethod
    def _head_units(summary: str) -> int:
        """Мера head-региона («фон: конспект из 7 сообщений…» + конспект)
        тем же счётчиком, что в _build_global_context."""
        return count_tokens("фон: конспект из 7 сообщений, "
                            "ниже дословно свежий хвост\n" + summary)

    @pytest.mark.asyncio
    async def test_partial_trim_boundary_before_first_survivor(self):
        """5699→4347-стиль: потолок срезает ЧАСТЬ строк окна штатным
        тримом. Граница — перед ПЕРВОЙ выжившей строкой окна; до границы
        дословных строк нет; выжившие строки не дублируются."""
        words = ("ОДИН", "ДВА", "ТРИ", "ЧЕТЫРЕ", "ПЯТЬ")
        window = [_window_row(10, "вася",
                              f"дословное сообщение окна {w} " + "х" * 120,
                              500 + i, 7 + i)
                  for i, w in enumerate(words)]
        summary = "фон-конспект прошлого " * 4
        rendered = self._rendered(window)
        head_units = self._head_units(summary)
        join_m = {m: count_tokens("\n".join(rendered[-m:]))
                  for m in (2, 3, 4, 5)}
        # выживают ровно 3 строки  ⇔  mu = budget − head ∈ [join_3, join_4)
        low = head_units + join_m[3]
        high = head_units + join_m[4]
        assert high - low >= 8, "строки окна слишком коротки для стенда"
        budget = (low + high) // 2
        assert head_units + join_m[5] > budget, \
            "штатное усечение не запускается — стенд неверен"
        blocks = await self._block(
            window, {"summary": summary, "raw_count": 7, "window_end_ts": 0},
            budget)
        global_block = next(t for k, t in blocks if k == "global")
        lines = global_block.splitlines()
        assert lines[1].startswith("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_ab12cd34ef56")
        assert HA_INRANGE_TAIL_LABEL in lines, "граница потеряна"
        idx_boundary = lines.index(HA_INRANGE_TAIL_LABEL)
        for marker in ("ОДИН", "ДВА"):
            assert not any(marker in ln for ln in lines), \
                "строка окна пережила штатный трим — стенд не в той ветке"
        for marker in ("ТРИ", "ЧЕТЫРЕ", "ПЯТЬ"):
            hits = [i for i, ln in enumerate(lines) if marker in ln]
            assert len(hits) == 1, \
                f"выжившая строка окна задублирована/потеряна: {marker}"
            assert hits[0] > idx_boundary, \
                f"строка окна до граничной строки (под баннером): {marker}"
        supplement = "\n".join(lines[:idx_boundary])
        for marker in ("ТРИ", "ЧЕТЫРЕ", "ПЯТЬ"):
            assert marker not in supplement, \
                "дословная строка окна в регионе дополнения"

    @pytest.mark.asyncio
    async def test_fully_trimmed_tail_emits_no_boundary(self):
        """4532→4347-стиль: потолок срезает хвост окна ЦЕЛИКОМ (конспект
        сам помещается в бюджет). Граничной строки нет вовсе — пустой
        in-range регион («дословные сообщения диапазона» без единой
        строки) запрещён; родитель 6d800b07 границы не ставил."""
        window = [_window_row(10, "вася",
                              "МАРКЕРПОЛНЫЙПЕРВЫЙ " + "х" * 300, 500, 7),
                  _window_row(11, "петя",
                              "МАРКЕРПОЛНЫЙВТОРОЙ " + "х" * 300, 510, 8)]
        summary = "фон-конспект прошлого " * 4
        rendered = self._rendered(window)
        head_units = self._head_units(summary)
        line_units = count_tokens(rendered[0])
        tail_join = count_tokens("\n".join(rendered))
        # mu = budget − head < line_units ⇒ обе строки уходят целиком;
        # budget ≥ head ⇒ keep-head резерв не запускается
        budget = head_units + max(1, line_units // 2)
        assert head_units + tail_join > budget, \
            "штатное усечение не запускается — стенд неверен"
        blocks = await self._block(
            window, {"summary": summary, "raw_count": 7, "window_end_ts": 0},
            budget)
        global_block = next(t for k, t in blocks if k == "global")
        lines = global_block.splitlines()
        assert HA_INRANGE_TAIL_LABEL not in lines, \
            "пустая граничная строка: хвост окна срезан целиком"
        assert global_block.count("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ") == 1
        assert "фон-конспект прошлого" in global_block, "конспект потерян"
        for marker in ("МАРКЕРПОЛНЫЙПЕРВЫЙ", "МАРКЕРПОЛНЫЙВТОРОЙ"):
            assert marker not in global_block, \
                "строка окна пережила штатный трим — стенд не в той ветке"


# ── блокер 4: system2 Stage-2 получает assembly-блок при выборке ────────────

class _S2LLM:
    def __init__(self):
        self.captured: list[dict] = []

    async def generate(self, messages, **kwargs):
        self.captured.append({"step": kwargs.get("step"),
                              "messages": [dict(m) for m in messages]})
        if kwargs.get("step") == "stage1":
            return json.dumps({"user_question": "что было?",
                               "answer_outline": "кратко по фактам",
                               "facts": [], "response_mode": "serious"})
        return "ЗАГЛУШКА ОТВЕТА"


class _S2StubMemory:
    async def get_window_messages(self, chat_id):
        return []


def _s2_service(llm):
    """Стенд Stage-2 system2 (зеркало test_soul1_composer_parity_off)."""
    from services.direct_chat_service import DirectChatService as D

    class Stub:
        _render_current_question = D._render_current_question
        _l1_reply_block = staticmethod(D._l1_reply_block)
        _l1_speech_hints = D._l1_speech_hints
        _build_speech_understanding = D._build_speech_understanding
        _attach_l1_plan_meta = D._attach_l1_plan_meta
        _compose_speech_system = D._compose_speech_system

        def __init__(self, llm):
            self.llm = llm
            self.memory = _S2StubMemory()
            self.db = None
            self.bot_id = 999
            self.aliases = None

    return Stub, D


CHARACTER_BLOCK = (
    "<Persona>\nИмя: Бот. Характер: язвительный, прямой.\n</Persona>\n\n"
    "<Character_Rules>\nНе раскрывать, что ты ИИ.\n</Character_Rules>")


class TestSystem2AssemblyBlock:
    def _raw(self):
        return type("R", (), {"tool_context": "tool output", "tool_trace": [
            {"tool": "get_recent_history", "out_chars": 812}]})()

    @pytest.mark.asyncio
    async def test_stage2_gets_full_block_with_sample(self):
        llm = _S2LLM()
        Stub, D = _s2_service(llm)
        result = await D._synthesize_direct_answer(
            Stub(llm), 12345, "проанализируй последние сообщения",
            self._raw(), 0.7, character_block=CHARACTER_BLOCK,
            history_assembly_block=HISTORY_COVERAGE_ASSEMBLY_BLOCK)
        assert result is not None
        stage2 = next(c for c in llm.captured if c["step"] == "stage2")
        system = stage2["messages"][0]["content"]
        assert system.count(HISTORY_COVERAGE_ASSEMBLY_BLOCK) == 1
        assert system.endswith(HISTORY_COVERAGE_ASSEMBLY_BLOCK)
        base = system[: -len("\n\n" + HISTORY_COVERAGE_ASSEMBLY_BLOCK)]
        assert base == compose_verbalizer_system(
            DIRECT_VERBALIZER_SYSTEM_PROMPT, "serious", "plain",
            html_safe=True, character_block=CHARACTER_BLOCK,
            style_directives="", extent_block="")

    @pytest.mark.asyncio
    async def test_stage2_without_sample_byte_parity(self):
        llm_a, llm_b = _S2LLM(), _S2LLM()
        Stub, D = _s2_service(llm_a)
        await D._synthesize_direct_answer(
            Stub(llm_a), 12345, "почему упал сервис", self._raw(), 0.7,
            character_block=CHARACTER_BLOCK)
        system_plain = llm_a.captured[-1]["messages"][0]["content"]
        assert HISTORY_COVERAGE_ASSEMBLY_BLOCK not in system_plain
        Stub2, D2 = _s2_service(llm_b)
        await D2._synthesize_direct_answer(
            Stub2(llm_b), 12345, "почему упал сервис", self._raw(), 0.7,
            character_block=CHARACTER_BLOCK, history_assembly_block="")
        assert llm_b.captured[-1]["messages"][0]["content"] == system_plain
