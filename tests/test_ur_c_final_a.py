"""Cluster A (UR-C final): blocks/source refs, no artificial caps, bounded reads, reason_code."""
from types import SimpleNamespace

import pytest

import services.direct_chat_service as dcs
from services import direct_context_composer as comp
from services import direct_l1 as l1
from services import style_policy as sp
from services.database import DatabaseService
from services.thread_chain import collect_thread_chain
from services import turn_trace
from tests.test_direct_chat import FakeMemory, _make_service, _message
from tests.test_ur_c_3_real_fts import (
    ADDRESSEE, BOT_UID, CHAT, _add_msg, _db, _force_budget, _global_parts,
    _row, _stub_episodes, _text,
)
from tests.test_ur_10_no_pre_truncation import (
    _large_l1, _l1_payload, _long_question, _patch_fixed_tool_flags,
    _run_direct, _svc, _window,
)
from tests.test_ur_d_writer import _MetadataLLM, _completion
from tests.test_ur_turn_engine import _plan

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]


def _paid_fact_row(fact_id, text):
    return {"id": fact_id, "item_id": f"fact:{fact_id}",
            "origin": "chat_history", "fact": text, "rag_ts": 2_000,
            "status": "confirmed", "subject_ref_id": ADDRESSEE,
            "target_user": "Аня", "speaker_author_id": ADDRESSEE,
            "tg_message_id": None}


def _spy_allocators(monkeypatch):
    counts = {"selection": 0, "budget": 0}
    real_selection = comp.allocate_selection
    real_budget = comp.allocate_budget

    def _selection(*args, **kwargs):
        counts["selection"] += 1
        return real_selection(*args, **kwargs)

    def _budget(*args, **kwargs):
        counts["budget"] += 1
        return real_budget(*args, **kwargs)

    monkeypatch.setattr(comp, "allocate_selection", _selection)
    monkeypatch.setattr(comp, "allocate_budget", _budget)
    return counts


@pytest.mark.asyncio
async def test_live_selection_keeps_blocks_and_source_refs(
        tmp_path, monkeypatch):
    """UR-09.9: активные блоки и refs живут в одном live selection."""
    db = await _db(tmp_path, "blocks.db")
    try:
        comp.reset_diagnostics()
        await _add_msg(db, ADDRESSEE, "корневое сообщение", 1000, 100)
        await _add_msg(db, ADDRESSEE, "ответ в ветке", 1100, 101,
                       reply_to=100)
        await _add_msg(db, ADDRESSEE, "ТЕКУЩИЙ_ВОПРОС", 1200, 102,
                       reply_to=101)
        msg = _message(text="ТЕКУЩИЙ_ВОПРОС", message_id=102)
        msg.reply_to_message = SimpleNamespace(
            message_id=101, text="ответ в ветке",
            from_user=SimpleNamespace(id=ADDRESSEE))
        chain = await collect_thread_chain(db, CHAT, 102, depth=4)
        assert chain
        window = [_row(1, text="свежая болтовня 1", uid=ADDRESSEE,
                       tg=100),
                  _row(2, text="свежая болтовня 2", uid=ADDRESSEE,
                       tg=101)]
        fact = _paid_fact_row(5, "ФАКТ_МАРКЕР: бюджет проверен")
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=[_row(
            901, text="ЭПИЗОД_МАРКЕР: старый разговор", uid=ADDRESSEE,
            ts=900, tg=990)])
        _force_budget(monkeypatch, svc, 200_000)
        counts = _spy_allocators(monkeypatch)
        out: dict = {}
        blocks = await svc._compose_user_content(
            chat_id=CHAT, message=msg, blocks=[], chain=chain,
            window=window, roster=[], suffix_map={},
            global_parts=_global_parts(tail_rows=window),
            target_name="Аня", target_user_id=ADDRESSEE,
            trigger_message_id=msg.message_id, out_excluded=None,
            rag_memory={"rows": [fact]}, live_selection=True,
            out_prepared=out)
        payload = _text(blocks)
        for tag in ("<Current_Question>", "<Conversation_Thread>",
                    "<Global_Context>", "<RAG_Memory>", "<Old_Episode>"):
            assert tag in payload, (tag, payload[:1000])
        assert "ФАКТ_МАРКЕР" in payload
        assert "ЭПИЗОД_МАРКЕР" in payload
        prepared = out["primary"]
        by_kind = {item.get("kind"): item for item in prepared.event_blocks}
        assert {"current", "thread", "global_tail", "rag", "episode"} <= \
            set(by_kind)
        # Source refs сохранены в тех блоках, которые их читают (trace).
        assert {"msg:100", "msg:101", "msg:102"} <= \
            set(by_kind["thread"]["source_ids"])
        assert {"msg:100", "msg:101"} <= \
            set(by_kind["global_tail"]["source_ids"])
        assert "msg:990" in by_kind["episode"]["source_ids"]
        assert "fact:5" in by_kind["rag"]["source_ids"]
        # Один allocator: live selection, без второго legacy-прохода.
        assert counts == {"selection": 1, "budget": 0}
        # Additive read-only reason_code присутствует и на live-пути.
        diag = comp.get_diagnostics(CHAT)
        assert diag is not None and "reason_code" in diag, diag
    finally:
        comp.reset_diagnostics()
        await db.close()


@pytest.mark.asyncio
async def test_legacy_diagnostics_reason_code(tmp_path, monkeypatch):
    """UR-21.11: legacy context-diagnostics получает read-only reason_code."""
    db = await _db(tmp_path, "reason.db")
    try:
        window = [_row(i, text=f"свежая болтовня {i}", uid=30 + i, tg=950 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=[_row(
            901, text=("ЭПИЗОД_МАРКЕР " * 80), uid=ADDRESSEE,
            ts=1500, tg=991)])
        _force_budget(monkeypatch, svc, 1)
        captured: dict = {}
        real = comp.record_diagnostics

        def _cap(chat_id, data):
            captured.update(data)
            return real(chat_id, data)

        monkeypatch.setattr(comp, "record_diagnostics", _cap)
        msg = _message(text="вопрос", message_id=6000)
        blocks = [("rag", "<RAG_Memory>\n" + ("RAG_МАРКЕР " * 100)
                   + "\n</RAG_Memory>")]
        texts = await svc._compose_user_content(
            chat_id=CHAT, message=msg, blocks=list(blocks), chain=[],
            window=window, roster=[], suffix_map={},
            global_parts=_global_parts(tail_rows=window),
            target_name="Аня", target_user_id=ADDRESSEE,
            trigger_message_id=msg.message_id, out_excluded=None,
            live_selection=False)
        assert texts
        assert captured.get("reason_code") == "physical_overflow", captured
        assert captured["physical_overflow"] is True
    finally:
        await db.close()


def test_reduction_reason_code_unknown_is_honest():
    assert comp.reduction_reason_code() is None
    assert comp.reduction_reason_code(
        dropped=[{"kind": "rag"}]) == "unknown"
    assert comp.reduction_reason_code(
        excluded=[{"kind": "rag"}], compressed_or_dropped=1) == "unknown"
    assert comp.reduction_reason_code(
        compressed_or_dropped=1) == "compressed"
    assert comp.reduction_reason_code(
        excluded=[{"kind": "rag", "reason_code": "budget_exceeded"}]
    ) == "budget_exceeded"
    assert comp.reduction_reason_code(
        physical_overflow=True,
        excluded=[{"reason_code": "budget_exceeded"}]) == "physical_overflow"


# ═══ UR-RES-03: no artificial 800/12x200/700; physical limits stay traced ═══

@pytest.mark.asyncio
async def test_live_l1_has_no_800_or_12x200(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    _large_l1(monkeypatch)
    rows = _window(26, long=True)
    service = _svc(_plan(), window=rows)
    _plan_out, meta = await _run_direct(
        service, text=_long_question(4200))
    assert meta["l1_window_rows_raw"] == 26
    assert meta["l1_window_rows_selected"] == 26, meta
    assert meta["l1_line_chars_cap"] == 0, meta
    payload = _l1_payload(service.llm)
    assert "ВОПРОС_НАЧАЛО" in payload and "ВОПРОС_ХВОСТ" in payload
    for i in range(1, 27):
        assert f"строка-{i}" in payload, i
        assert f"ДЛИННЫЙ_ХВОСТ_{i}" in payload, i
    assert "Z" * 450 in payload


@pytest.mark.asyncio
async def test_telegram_and_writer_limits_are_traced(monkeypatch):
    # Telegram-физика и legacy-пол остаются только физическими границами.
    assert l1.L1_CLIP_CHARS_MAX == 4096
    rows = [{"text": "x" * 800, "timestamp": i} for i in range(50)]
    assert l1.window_line_chars(rows, budget_tokens=100_000) > 200

    async def _writer_limit(**kwargs):
        return 1234

    monkeypatch.setattr(dcs._extent, "writer_max_output_tokens",
                        _writer_limit)
    llm = _MetadataLLM([_completion("ok")])
    svc = _make_service(llm=llm)
    corr = "ur-res-03-trace"
    turn_trace.begin(corr, chat_id=CHAT, trigger="direct")
    try:
        await svc._l2_write_answer(
            CHAT, "q", temperature=0.5, correlation_id=corr,
            user_blocks=["<Current_Question>q</Current_Question>"])
        call = llm.calls_of("l2_writer")[0]
        assert call["max_output_tokens"] == 1234
        trace = turn_trace.get(corr)
        assert trace is not None
        request = trace.writer_payload()["request"]
        assert request["max_output_tokens"] == 1234
        assert request["max_output_tokens"] != 700
    finally:
        turn_trace.reset()

    # Антицикл-окно сохраняет свой cap/TTL и видно в R17-наблюдении.
    sp.reset_repetition_state()
    sp.record_bot_output(CHAT, "фраза для наблюдения")
    view = sp.repetition_view(CHAT)
    assert view["cap"] == sp.REPEAT_WINDOW_MAX
    assert view["ttl_seconds"] == sp.REPEAT_TTL_SECONDS
    assert view["window"] == 1
    sp.reset_repetition_state()


@pytest.mark.asyncio
async def test_writer_does_not_fall_back_to_semantic_700():
    """Неизвестный ресурс не подменяется старыми 700/4096/16384."""
    llm = _MetadataLLM([_completion("ok")], model="unknown-model-xyz",
                       base_url="")
    svc = _make_service(llm=llm)
    await svc._l2_write_answer(
        CHAT, "q", temperature=0.5,
        user_blocks=["<Current_Question>q</Current_Question>"])
    sent = llm.calls_of("l2_writer")[0]["max_output_tokens"]
    assert sent is None or sent not in (700, 4096, 16384)


# ═══ UR-BAN-03: bounded reads; provenance/relevance, not volume ═════════════

class _TracingConn:
    def __init__(self, real):
        self.real = real
        self.calls: list = []

    async def execute(self, sql, params=()):
        self.calls.append((str(sql), tuple(params or ())))
        return await self.real.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.real, name)


@pytest.mark.asyncio
async def test_large_context_reads_are_bounded_not_full_scan():
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        rows = [(CHAT, 10, f"строка {i}", i, 10_000 + i)
                for i in range(1, 5_001)]
        await db.db.executemany(
            "INSERT INTO smart_messages (chat_id, user_id, text, timestamp, "
            "tg_message_id) VALUES (?, ?, ?, ?, ?)", rows)
        await db.db.commit()

        tracing = _TracingConn(db.db)
        db.db = tracing
        try:
            window = await db.get_smart_window(CHAT, 0, 50)
            recent = await db.get_recent_messages(CHAT, 1_200)
        finally:
            db.db = tracing.real
        assert len(window) == 50
        assert len(recent) == 1_200
        smart_reads = [(sql, params) for sql, params in tracing.calls
                       if "FROM smart_messages" in sql]
        assert smart_reads, tracing.calls
        assert all("LIMIT" in sql for sql, _params in smart_reads)
        limits = [int(params[-1]) for sql, params in smart_reads
                  if "LIMIT ?" in sql and params]
        assert limits and max(limits) <= 500, limits
        assert 5_000 not in limits
    finally:
        await db.close()


def test_relevance_and_provenance_beat_chronological_bulk():
    background = [
        comp.ContextFragment(
            kind=comp.KIND_CHAT_EVENT, source_id=f"msg:{i}",
            timestamp_utc=1_000 + i, speaker_uid=ADDRESSEE,
            text=f"нерелевантный фон {i}", role=comp.ROLE_BACKGROUND)
        for i in range(1, 101)
    ]
    relevant = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:999",
        timestamp_utc=10_000, speaker_uid=ADDRESSEE,
        text="РЕЛЕВАНТНЫЙ_ФАКТ про бюджет",
        role=comp.ROLE_THREAD, authority=comp.AUTHORITY_PRIMARY)
    selection = comp.build_context_selection(
        chat_id=CHAT, current_text="напомни про бюджет",
        timestamp_utc=11_000, thread=[relevant], background=background,
        budget_tokens=120)
    survivors = {f.source_id for f in selection.fragments()}
    assert "msg:999" in survivors
    dropped = {item.get("reason_code")
               for item in selection.provenance.dropped}
    assert "irrelevant_background" in dropped, dropped
    assert any(str(item.get("source_id", "")).startswith("msg:")
               and item.get("source_id") != "msg:999"
               for item in selection.provenance.dropped)
    assert len(survivors) < 101
