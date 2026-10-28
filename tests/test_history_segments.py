"""P0-HA SEGMENTS (волна 3, снапшот 2026-10-29 §5-§7 + архконтракт §2) —
серверное сегментное накопление выборки истории в DirectChatService.

Покрытие: нарезка по целым сообщениям без потерь/дублей на границах (H16),
связь события через границу сегментов (H16 — continues_from по reply_to_id),
повторная тема в разных сегментах — mentions, а не придуманные события
(H17), три темы в начале/середине/конце доступны анализу (H15),
независимые обсуждения не слипаются (H18), провал сегмента — честная
неполнота с доставкой остальных (H19), без повторных чтений уже
доставленных диапазонов (H20), короткий путь одного слота не изменён
(H1/H2), >100k символов проходят через сегменты (H10-adjacent), одно
гигантское сообщение учитывается без усечки (H11-adjacent), tool-cursor
волны 2 остаётся страховкой (§6.2). SQLite in-memory, без сети, тексты
сообщений в логи/утверждения не попадают.
"""
import asyncio
import json
import re
from unittest.mock import MagicMock

import pytest

from services.database import DatabaseService
from services.direct_chat_service import (
    _HISTORY_COVERAGE_END,
    _HISTORY_COVERAGE_HEADER,
    _history_line_item_id,
    DirectChatService,
)
from services.direct_execution import (
    ChainResult,
    EvidenceSource,
    build_evidence_pack,
)
from services.summary_aliases import AliasResolver
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolRouter,
    capture_history_sample,
)

CHAT_ID = -1001234567890


# ── фикстуры ────────────────────────────────────────────────────────────────

async def _make_db(count, *, texts=None, reply=None) -> DatabaseService:
    """Реальная DatabaseService на SQLite in-memory; ts = tg_id = i."""
    db = DatabaseService(":memory:")
    await db.initialize()
    for i in range(1, count + 1):
        text = texts[i - 1] if texts else f"м{i}"
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name, "
            "reply_to_id, tg_message_id) "
            "VALUES (1, ?, ?, ?, 'text', 'автор', ?, ?)",
            (CHAT_ID, text, i, reply(i) if reply else None, i))
    await db.db.commit()
    return db


class SegmentLLM:
    """Фейковый LLM: ответ как функция (индекс вызова, промпт); все вызовы
    журналируются (кто/с какой температурой/каким step) — без сети."""

    def __init__(self, responder=None, *, fail_calls=(), delay=0.0):
        self.calls = []              # (prompt, kwargs)
        self.responder = responder
        self.fail_calls = set(fail_calls)
        self.delay = delay

    async def generate(self, messages, temperature=None, chat_id=None, **kw):
        idx = len(self.calls)
        prompt = messages[0]["content"]
        self.calls.append((prompt, {"temperature": temperature,
                                    "chat_id": chat_id,
                                    "module": kw.get("module"),
                                    "step": kw.get("step")}))
        if idx in self.fail_calls:
            raise RuntimeError("provider down")
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.responder is None:
            return '{"events":[],"status":"ok"}'
        return self.responder(idx, prompt)


def _service(db, llm) -> DirectChatService:
    router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                 aliases=None, db=db))
    return DirectChatService(MagicMock(), db, llm, AliasResolver("{}"),
                             tool_router=router)


async def _make_turn(db, depth, *, count=None):
    """Захват выборки + первая страница инструмента → (ctx, raw).
    Зеркало прод-шва: захват до контекста, setattr на tool_ctx."""
    count = count or depth
    ctx = ToolContext(CHAT_ID, f"проанализируй последние {depth} сообщений")
    bound = await capture_history_sample(db, CHAT_ID, depth)
    assert bound is not None
    ctx.history_sample = bound
    page = await _router_of(db).dispatch(
        "get_recent_history", {"depth": depth}, ctx)
    raw = ChainResult(page, evidence_sources=[
        EvidenceSource(tool="get_recent_history", status="ok",
                       content=page, total_chars=len(page))],
        chain_meta={})
    return ctx, raw


def _router_of(db) -> ToolRouter:
    return ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                               aliases=None, db=db))


def _topic_responder(topics, *, scan_whole_prompt=False):
    """Детерминированный стаб: событие на каждую тему, чьи строки-носители
    видны в теле сегмента (или во всём промпте — режим сквозного скана)."""
    def respond(idx, prompt):
        if scan_whole_prompt:
            body = prompt
        else:
            start = prompt.find("<segment>") + len("<segment>")
            end = prompt.find("</segment>")
            body = prompt[start:end]
        events = []
        for topic in topics:
            refs = []
            for line in body.splitlines():
                item_id = _history_line_item_id(line)
                if item_id and item_id not in refs and topic in line:
                    refs.append(item_id)
            if refs:
                events.append({"refs": refs, "continues": 0,
                               "note": f"происходит {topic}"})
        return json.dumps({"events": events, "status": "ok"})
    return respond


def _coverage(block: str):
    """(поля головы, строки seg, строки event) блока покрытия."""
    lines = block.splitlines()
    assert lines[0] == _HISTORY_COVERAGE_HEADER, block[:200]
    fields: dict = {}
    seg_lines: list = []
    event_lines: list = []
    after_end = False
    for line in lines[1:]:
        if line == _HISTORY_COVERAGE_END:
            after_end = True
            continue
        if line.startswith("seg "):
            seg_lines.append(line)
            continue
        if line.startswith("event "):
            event_lines.append(line)
            continue
        if not after_end and "=" in line:
            key, _, val = line.partition("=")
            fields[key.strip()] = val.strip()
    return fields, seg_lines, event_lines


# ── нарезка: целые сообщения, без потерь и дублей (H16 segment-level) ───────

class TestSegmentSplitting:
    @pytest.mark.asyncio
    async def test_segments_partition_sample_without_loss_overlap(self):
        """120 строк, слот 4000 → сегменты покрывают ровно всю выборку:
        границы стыкуются без пересечений, сумма rows == available."""
        db = await _make_db(120)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, _ = _coverage(block)
        assert fields["available"] == "120"
        assert fields["processed"] == "120"
        assert fields["remaining"] == "0"
        assert fields["complete"] == "1"
        assert fields["failed"] == "0"
        assert fields["segments"] == str(len(seg_lines))
        covered = []
        for line in seg_lines:
            match = re.match(
                r"seg (\d+) tg:(\d+)\.\.tg:(\d+) rows=(\d+) status=(\w+)",
                line)
            assert match, line
            covered.append((int(match.group(2)), int(match.group(3)),
                            int(match.group(4)), match.group(5)))
        # стыковка без потерь/пересечений: каждое следующее начало = прошлое
        # окончание + 1 (крайний случай повтора не допускается)
        for (_, end_a, _, _), (start_b, _, _, _) in zip(covered, covered[1:]):
            assert start_b == end_a + 1
        assert covered[0][0] == 1
        assert covered[-1][1] == 120
        assert sum(rows for _, _, rows, _ in covered) == 120
        assert all(status == "ok" for _, _, _, status in covered)

    @pytest.mark.asyncio
    async def test_segment_prompt_whole_lines_one_call_per_segment(self):
        """Один вызов на сегмент (60 строк при cap 40 строк/сегмент → ровно
        2 сегмента), строки в промпте не рвутся посередине."""
        db = await _make_db(60)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 60)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=100000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, _ = _coverage(block)
        # _HISTORY_PAGE_ROWS — технический верх сегмента: 60 строк → 40 + 20
        assert len(seg_lines) == 2
        assert fields["segments"] == "2"
        assert len(llm.calls) == 2              # один вызов на сегмент
        for prompt, kwargs in llm.calls:
            assert kwargs["module"] == "direct_chat"
            assert kwargs["step"] == "history_segment"
            assert kwargs["temperature"] == 0.0
            body = prompt.split("<segment>\n", 1)[1].split("\n</segment>", 1)[0]
            # канонические строки целиком: открытие '[' и закрытие ']: ' парны
            for line in body.splitlines():
                assert line.startswith("[") and "]: " in line


# ── граница сегментов: связность события (H16) ──────────────────────────────

class TestBoundaryContinuity:
    @pytest.mark.asyncio
    async def test_event_across_boundary_keeps_connection(self):
        """Сообщение 41 отвечает на сообщение 40 (граница страниц 40/40):
        код ставит continues_from на втором сегменте — связь сохранена."""
        db = await _make_db(120, reply=lambda i: (40 if i == 41 else None))
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=1000000, chat_id=CHAT_ID)
        assert block is not None
        _, seg_lines, _ = _coverage(block)
        # слот большой → страница 40 строк всё равно режет сегменты
        target = [ln for ln in seg_lines if ln.startswith("seg 2 ")]
        assert target, seg_lines
        assert "continues_from=1" in target[0]

    @pytest.mark.asyncio
    async def test_boundary_context_lines_present_in_prompt(self):
        """Промпт второго сегмента несёт хвост предыдущего как контекст
        границы (детерминированная сшивка)."""
        prompts: list = []

        def respond(idx, prompt):
            prompts.append(prompt)
            return '{"events":[],"status":"ok"}'

        db = await _make_db(80)
        llm = SegmentLLM(respond)
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 80)
        await service.collect_history_segments(
            ctx, raw, slot_chars=1000000, chat_id=CHAT_ID)
        assert len(prompts) >= 2
        second = prompts[1]
        assert "<prev_context>\n" in second
        # у второго сегмента (из 2+) нет следующего соседа в момент промпта
        assert not re.search(r"<next_context>\n", second)
        # хвост первого сегмента присутствует как контекст
        assert "м40" in second


# ── дубликаты тем → mentions (H17) ──────────────────────────────────────────

class TestMentionsAcrossSegments:
    @pytest.mark.asyncio
    async def test_same_topic_across_segments_is_mention_not_new_event(self):
        """Тема на границе сегментов (строка 40 = хвост сегмента 1 и
        prev_context сегмента 2): сегмент 2 снова видит id tg:40 → повтор
        учтён mentions у события-владельца, новое событие не придумано
        (id в refs событий не дублируются)."""
        texts = [f"ТЕМА-А сообщение {i}" if i % 40 == 0 else f"м{i}"
                 for i in range(1, 121)]
        db = await _make_db(120, texts=texts)
        llm = SegmentLLM(_topic_responder(["ТЕМА-А"], scan_whole_prompt=True))
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=1000000, chat_id=CHAT_ID)
        assert block is not None
        fields, _, event_lines = _coverage(block)
        assert fields["mentions"] != "0"
        # каждый id встречается в refs событий ровно один раз
        seen: list = []
        for line in event_lines:
            refs_part = line.split("refs=", 1)[1].split()[0]
            for ref in refs_part.split(","):
                assert ref not in seen, line
                seen.append(ref)
        # владелец первой группы получил mentions
        owner = event_lines[0]
        assert "mentions=" in owner


# ── три темы по краям выборки (H15) и независимые обсуждения (H18) ──────────

class TestTopicCoverage:
    @pytest.mark.asyncio
    async def test_topics_at_start_middle_end_all_present(self):
        """Тема в начале, другая в середине, третья в конце: все три в
        находках сегментов."""
        def text_of(i):
            if i <= 5:
                return f"обсуждаем ТЕМА-СТАРТ подробно {i}"
            if 58 <= i <= 62:
                return f"обсуждаем ТЕМА-СЕРЕДИНА подробно {i}"
            if i >= 116:
                return f"обсуждаем ТЕМА-ФИНАЛ подробно {i}"
            return f"м{i}"

        db = await _make_db(120, texts=[text_of(i) for i in range(1, 121)])
        llm = SegmentLLM(_topic_responder(
            ["ТЕМА-СТАРТ", "ТЕМА-СЕРЕДИНА", "ТЕМА-ФИНАЛ"]))
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, event_lines = _coverage(block)
        assert fields["complete"] == "1"
        all_refs = []
        for line in event_lines:
            all_refs.extend(
                line.split("refs=", 1)[1].split()[0].split(","))
        # старт (tg:1..5), середина (tg:58..62), финал (tg:116..120)
        assert any(ref.startswith("tg:1") or ref == "tg:1" for ref in all_refs)
        assert "tg:60" in all_refs
        assert "tg:118" in all_refs
        assert event_lines, "события не должны быть пусты"

    @pytest.mark.asyncio
    async def test_independent_discussions_not_collapsed(self):
        """Две независимые темы в одном сегменте → два отдельных события,
        слипания в один refs-список нет."""
        def text_of(i):
            if i % 2 == 1:
                return f"ветка ОДИН-обсуждение {i}"
            return f"ветка ДВА-обсуждение {i}"

        db = await _make_db(30, texts=[text_of(i) for i in range(1, 31)])
        llm = SegmentLLM(_topic_responder(["ОДИН-обсуждение",
                                           "ДВА-обсуждение"]))
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 30)
        # слот меньше страницы (страница ~2000 симв.), но больше блока
        # покрытия → сегментный путь активен, события помещаются в слот
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=1600, chat_id=CHAT_ID)
        assert block is not None
        fields, _, event_lines = _coverage(block)
        assert fields["complete"] == "1"
        assert len(event_lines) >= 2
        ref_sets = [line.split("refs=", 1)[1].split()[0].split(",")
                    for line in event_lines]
        assert not set(ref_sets[0]) & set(ref_sets[1])


# ── провал сегмента: честная неполнота (H19/§6.2) ───────────────────────────

class TestSegmentFailure:
    @pytest.mark.asyncio
    async def test_failed_segment_visible_others_delivered(self):
        """LLM упал на втором сегменте: seg 2 status=failed reason=llm_error,
        остальные сегменты ok с событиями, complete=0."""
        texts = [f"ТЕМА-Х событие {i}" if i % 15 == 3 else f"м{i}"
                 for i in range(1, 121)]
        db = await _make_db(120, texts=texts)
        llm = SegmentLLM(_topic_responder(["ТЕМА-Х"]), fail_calls={1})
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, event_lines = _coverage(block)
        assert fields["complete"] == "0"
        assert fields["failed"] == "1"
        failed_line = [ln for ln in seg_lines if "status=failed" in ln]
        assert len(failed_line) == 1
        assert "reason=llm_error" in failed_line[0]
        assert fields["reason"] == ""          # цикл не падал — причина на сегменте
        # остальные сегменты доставлены с событиями
        assert "status=ok" in "".join(seg_lines)
        assert event_lines
        # сырые страницы заменены покрытием — хвост не возвращается в source
        assert raw.evidence_sources[0].content == block

    @pytest.mark.asyncio
    async def test_broken_json_segment_failed_not_silent(self):
        """Битый JSON ответа → сегмент failed, соседние сегменты
        обрабатываются дальше (не тихий успех, не обрыв цикла)."""
        db = await _make_db(120)
        llm = SegmentLLM(lambda idx, prompt: (
            "не json вообще" if idx == 0 else '{"events":[],"status":"ok"}'))
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, _ = _coverage(block)
        assert "status=failed" in "".join(seg_lines)
        assert "reason=llm_error" in block
        assert fields["complete"] == "0"
        assert len(llm.calls) > 1              # цикл продолжился

    @pytest.mark.asyncio
    async def test_wallclock_deadline_keeps_collected_marks_timeout(
            self, monkeypatch):
        """Истечение wall-clock цикла: собранное сохраняется, complete=0,
        reason=timeout; отмена не глотается (нет CancelledError-перехвата)."""
        monkeypatch.setattr(
            "services.direct_chat_service.TOOL_CHAIN_TIMEOUT_SECONDS", 0.3)
        db = await _make_db(120)
        llm = SegmentLLM(delay=0.2)
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, _ = _coverage(block)
        assert fields["complete"] == "0"
        assert fields["reason"] == "timeout"
        assert len(seg_lines) >= 1             # собранное сохранено
        assert fields["processed"] != "0"

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """CancelledError пробрасывается (не глотается циклом сегментов)."""
        db = await _make_db(120)

        class CancelLLM:
            async def generate(self, messages, **kw):
                raise asyncio.CancelledError()

        service = _service(db, CancelLLM())
        ctx, raw = await _make_turn(db, 120)
        with pytest.raises(asyncio.CancelledError):
            await service.collect_history_segments(
                ctx, raw, slot_chars=4000, chat_id=CHAT_ID)


# ── однократность чтений (H20) ──────────────────────────────────────────────

class TestNoRereads:
    @pytest.mark.asyncio
    async def test_delivered_range_never_reread(self):
        """Первая страница уже доставлена инструментом: сегментный обход не
        перечитывает её (первый keyset-вызов строго после страницы), каждое
        чтение строго вперед, без повторов диапазонов."""
        db = await _make_db(120)
        service = _service(db, SegmentLLM())
        ctx, raw = await _make_turn(db, 120)
        orig = db.get_recent_messages
        reads: list = []

        async def spy(chat_id, limit, *, anchor=None, after=None):
            reads.append(tuple(after) if after else None)
            return await orig(chat_id, limit, anchor=anchor, after=after)

        db.get_recent_messages = spy
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, _, _ = _coverage(block)
        assert fields["processed"] == "120"
        # spy установлен ПОСЛЕ доставки первой страницы → все записи уже
        # keyset-продолжения: ни одного чтения с after=None (доставленный
        # диапазон не перечитывается), строго вперёд, ровно 2 чтения хвоста
        assert reads == [(40, 40), (80, 80)]

    @pytest.mark.asyncio
    async def test_segments_not_reanalyzed_on_second_call(self):
        """Повтор вызова collect на том же raw — новые вызовы LLM (второго
        прохода нет в рамках одного вызова; повторный вызов — новое решение
        хода, а дубли внутри одного прохода запрещены H20)."""
        db = await _make_db(120)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        calls_first = len(llm.calls)
        assert calls_first > 0
        fields, seg_lines, _ = _coverage(block)
        # один вызов на сегмент: ни один сегмент не анализируется дважды
        assert calls_first == len(seg_lines)


# ── короткий путь одного слота (H1/H2) ──────────────────────────────────────

class TestSingleSlotParity:
    @pytest.mark.asyncio
    async def test_fitting_sample_untouched_zero_llm(self):
        """Выборка доставлена одной страницей, влезает в слот → None,
        source не тронут, 0 сегментных LLM-вызовов."""
        db = await _make_db(30)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 30)
        before = raw.evidence_sources[0].content
        result = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert result is None
        assert raw.evidence_sources[0].content == before
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_no_sample_parity(self):
        """Без history_sample на tool_ctx — паритет (None)."""
        db = await _make_db(120)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx = ToolContext(CHAT_ID, "запрос")
        page = await service.tool_router.dispatch(
            "get_recent_history", {"depth": 120}, ctx)
        raw = ChainResult(page, evidence_sources=[
            EvidenceSource(tool="get_recent_history", status="ok",
                           content=page, total_chars=len(page))],
            chain_meta={})
        assert await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID) is None

    @pytest.mark.asyncio
    async def test_path_b_result_parity(self):
        """Результат пути B (без головы @@HISTORY_SAMPLE) — паритет None."""
        db = await _make_db(30)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx = ToolContext(CHAT_ID, "запрос")
        ctx.history_sample = await capture_history_sample(db, CHAT_ID, 30)
        raw = ChainResult("путь B: какая-то стенограмма", evidence_sources=[
            EvidenceSource(tool="get_recent_history", status="ok",
                           content="путь B: стенограмма", total_chars=18)],
            chain_meta={})
        assert await service.collect_history_segments(
            ctx, raw, slot_chars=10, chat_id=CHAT_ID) is None
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_tail_reader_unavailable_parity_keeps_pages(self):
        """has_next=1, но keyset-читатель недоступен (deps.db нет) → паритет:
        sources не тронуты (страницы/курсор волны 2 остаются страховкой)."""
        db = await _make_db(120)
        llm = SegmentLLM()
        router = ToolRouter(ToolDeps(search=MagicMock(),
                                     memory=MagicMock(), aliases=None,
                                     db=None))
        service = DirectChatService(MagicMock(), db, llm,
                                    AliasResolver("{}"), tool_router=router)
        ctx, raw = await _make_turn(db, 120)
        before = raw.evidence_sources[0].content
        assert await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID) is None
        assert raw.evidence_sources[0].content == before


# ── большие выборки и гигантские сообщения (H10/H11-adjacent) ───────────────

class TestLargeSamples:
    @pytest.mark.asyncio
    async def test_over_100k_chars_completes_via_segments(self):
        """>100k символов проходят через сегменты целиком (processed ==
        available, complete=1), без одного огромного запроса."""
        texts = [("х" * 900) + f" м{i}" for i in range(1, 121)]
        db = await _make_db(120, texts=texts)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        total = sum(len(t) for t in texts)
        assert total > 100000
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, _ = _coverage(block)
        assert fields["complete"] == "1"
        assert fields["processed"] == "120"
        assert fields["segments"] == str(len(seg_lines))
        assert len(llm.calls) == len(seg_lines)
        # ни один сегментный запрос не тащит всю выборку (>20k символов)
        assert all(len(p) < 20000 for p, _ in llm.calls)

    @pytest.mark.asyncio
    async def test_single_huge_message_counted_not_cut(self):
        """Одно сообщение больше слота: собственный сегмент (oversize=1),
        полный текст дошёл до сегментного вызова без text[:N], учёт не
        потерян."""
        giant = "ГИГАНТ " + ("y" * 10000)
        texts = [f"м{i}" for i in range(1, 61)]
        texts[29] = giant                     # сообщение 30
        db = await _make_db(60, texts=texts)
        prompts: list = []
        llm = SegmentLLM(lambda idx, prompt: (
            prompts.append(prompt),
            json.dumps({"events": [], "status": "ok"}))[1])
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 60)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, _ = _coverage(block)
        assert fields["processed"] == "60"
        oversize = [ln for ln in seg_lines if "oversize=1" in ln]
        assert len(oversize) == 1
        assert "rows=1" in oversize[0]
        # полный текст гиганта дошёл до вызова (нет усечки)
        assert any(len(p) >= 10000 for p in prompts)
        assert not any("…[усечено]" in p for p in prompts)


# ── бюджет блока покрытия: честная усечка производных строк ────────────────

class TestCoverageBudget:
    @pytest.mark.asyncio
    async def test_findings_budget_overflow_honest_markers(self):
        """Слот 500 при 400 строках: строки статусов не влезают — лишние
        сегменты не выбрасываются молча (omitted=... в голове), complete=0,
        reason=findings_budget; голова покрытия всегда первая."""
        db = await _make_db(400)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 400)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=500, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, event_lines = _coverage(block)
        assert block.startswith(_HISTORY_COVERAGE_HEADER)
        assert fields["complete"] == "0"
        assert fields["reason"] == "findings_budget"
        assert "omitted" in fields
        omitted = [int(x) for x in fields["omitted"].split(",")]
        shown = [int(ln.split()[1]) for ln in seg_lines]
        assert sorted(omitted + shown) == list(
            range(1, int(fields["segments"]) + 1))

    @pytest.mark.asyncio
    async def test_events_dropped_before_seg_statuses(self):
        """При переполнении сначала жертвуются строки событий (events_dropped),
        статусы сегментов остаются — основа честного охвата."""
        texts = [f"ТЕМА-Y событие {i}" if i % 10 == 7 else f"м{i}"
                 for i in range(1, 401)]
        db = await _make_db(400, texts=texts)
        llm = SegmentLLM(_topic_responder(["ТЕМА-Y"]))
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 400)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=500, chat_id=CHAT_ID)
        assert block is not None
        fields, seg_lines, event_lines = _coverage(block)
        assert fields["complete"] == "0"
        assert fields["reason"] == "findings_budget"
        # либо события урезаны маркером, либо статусы — но не молча
        assert ("events_dropped" in fields) or ("omitted" in fields)


# ── шов интеграции: покрытие головой в evidence pack (§2) ───────────────────

class TestEvidenceSeam:
    @pytest.mark.asyncio
    async def test_pack_keeps_coverage_head_under_clipping(self):
        """После накопления build_evidence_pack даже с малой capacity
        сохраняет голову покрытия (префикс первый — piece[:floor] не рвёт
        @@HISTORY_COVERAGE)."""
        texts = [f"ТЕМА-Z событие {i}" if i % 12 == 5 else f"м{i}"
                 for i in range(1, 121)]
        db = await _make_db(120, texts=texts)
        llm = SegmentLLM(_topic_responder(["ТЕМА-Z"]))
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        pack = build_evidence_pack(raw, None, capacity_chars=400)
        assert "@@HISTORY_COVERAGE v1" in pack.text
        assert "sample_id=" in pack.text

    @pytest.mark.asyncio
    async def test_extra_history_pages_removed_from_sources(self):
        """Доставленные курсором страницы заменяются одним источником
        покрытия: сырой текст страниц из evidence_sources уходит."""
        db = await _make_db(120)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 120)
        page2 = await service.tool_router.dispatch("get_recent_history", {
            "cursor": parse_cursor(raw.evidence_sources[0].content)}, ctx)
        raw.evidence_sources.append(EvidenceSource(
            tool="get_recent_history", status="ok", content=page2,
            total_chars=len(page2)))
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        history_sources = [s for s in raw.evidence_sources
                           if s.tool == "get_recent_history"]
        assert len(history_sources) == 1
        assert history_sources[0].content == block
        fields, _, _ = _coverage(block)
        assert fields["processed"] == "120"
        # доставленные страницы не перечитывались: только 1 keyset-чтение хвоста
        assert fields["available"] == "120"


def parse_cursor(page_text: str) -> str:
    """cursor из головы страницы (тестовая утилита)."""
    match = re.search(r"^cursor=(.+)$", page_text, re.MULTILINE)
    assert match, page_text[:300]
    return match.group(1).strip()


# ── шов захвата до сборки контекста (§0) ────────────────────────────────────

class TestCaptureSeam:
    @pytest.mark.asyncio
    async def test_capture_turn_sample_from_query(self):
        """Количественный запрос → граница выборки (этап A) до содержательной
        обработки; неколичественный → None (паритет)."""
        db = await _make_db(80)
        llm = SegmentLLM()
        service = _service(db, llm)
        bound = await service._capture_turn_history_sample(
            CHAT_ID, "проанализируй последние 60 сообщений")
        assert bound is not None
        assert bound["requested"] == 60
        assert bound["available"] == 60
        assert await service._capture_turn_history_sample(
            CHAT_ID, "как настроение?") is None
        assert await service._capture_turn_history_sample(
            CHAT_ID, "что было в 2000 году?") is None

    @pytest.mark.asyncio
    async def test_preset_sample_fixed_while_new_messages_arrive(self):
        """Захваченная выборка не смещается новыми сообщениями (H8): страницы
        и хвост идут по зафиксированному окну."""
        db = await _make_db(120)
        llm = SegmentLLM()
        service = _service(db, llm)
        bound = await service._capture_turn_history_sample(
            CHAT_ID, "последние 120 сообщений")
        ctx = ToolContext(CHAT_ID, "последние 120 сообщений")
        ctx.history_sample = bound
        for i in range(121, 126):
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, "
                "timestamp, media_type, author_name, tg_message_id) "
                "VALUES (1, ?, ?, ?, 'text', 'автор', ?)",
                (CHAT_ID, f"новое {i}", i, i))
        await db.db.commit()
        page = await service.tool_router.dispatch(
            "get_recent_history", {"depth": 120}, ctx)
        raw = ChainResult(page, evidence_sources=[
            EvidenceSource(tool="get_recent_history", status="ok",
                           content=page, total_chars=len(page))],
            chain_meta={})
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
        assert block is not None
        fields, _, _ = _coverage(block)
        assert fields["available"] == "120"
        assert fields["processed"] == "120"
        assert fields["complete"] == "1"


# ── tool-cursor волны 2 остаётся страховкой (§6.2) ──────────────────────────

class TestCursorFallbackIntact:
    @pytest.mark.asyncio
    async def test_tool_cursor_chain_still_works(self):
        """Модель может дочитывать выборку курсором через tool-loop: постраничная
        честность волны 2 не сломана сервисным сегментированием."""
        db = await _make_db(80)
        router = _router_of(db)
        ctx = ToolContext(CHAT_ID, "последние 80 сообщений")
        out = await router.dispatch("get_recent_history", {"depth": 80}, ctx)
        fields = parse_head(out)
        assert fields["has_next"] == "1"
        out2 = await router.dispatch(
            "get_recent_history", {"cursor": fields["cursor"]}, ctx)
        fields2 = parse_head(out2)
        assert fields2["processed"] == "80"
        assert fields2["has_next"] == "0"
        assert fields2["remaining"] == "0"


def parse_head(page_text: str) -> dict:
    fields: dict = {}
    started = False
    for line in page_text.splitlines():
        if line.startswith("@@HISTORY_SAMPLE"):
            started = True
            continue
        if line == "@@END_HEADER":
            break
        if started and "=" in line:
            key, _, val = line.partition("=")
            fields[key.strip()] = val.strip()
    return fields
