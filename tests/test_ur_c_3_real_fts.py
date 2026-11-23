"""UR-C-3: candidate-bound proof on REAL SQLite FTS/graph/thread channels.

Каждый тест привязан к строке карты и проверяет live-путь
`DirectChatService._compose_user_content` с реальным `DatabaseService`
(temp SQLite + FTS5). FakeMemory используется ТОЛЬКО как vector-заглушка;
exact/lexical/reply-graph идут через реальные SQL-чтения.

Строки остаются PENDING до независимого ревью; VERIFIED здесь не заявляется.
"""
from types import SimpleNamespace

import pytest

import services.direct_chat_service as dcs
from services import direct_context_composer as comp
from services import mca_retrieval_context as rc
from services.database import DatabaseService
from services.token_counter import count_tokens
from tests.test_direct_chat import FakeMemory, _make_service, _message

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]

CHAT = -100777
BOT_UID = 999000
ADDRESSEE = 10
OTHER = 20


# ── Real DB helpers ─────────────────────────────────────────────────────────

async def _db(tmp_path, name="urc3.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add_msg(db, user_id, text, ts, tg, reply_to=None,
                   author_name="Аня"):
    return await db.save_smart_message(
        user_id=user_id, chat_id=CHAT, text=text, reply_to_id=reply_to,
        timestamp=ts, media_type="text", author_name=author_name,
        message_id=tg)


def _row(i, *, text="", uid=ADDRESSEE, ts=1_700_000_000, tg=None,
         reply_to=None, author="Аня"):
    return {
        "id": i, "tg_message_id": tg if tg is not None else 500 + i,
        "user_id": uid, "author_name": author, "text": text or f"строка {i}",
        "timestamp": ts + i, "reply_to_id": reply_to, "media_type": "text",
    }


def _global_parts(*, tail_rows=(), middle_rows=(), head_lines=(),
                  summary_row=None, window_end=0):
    return {
        "tail_rows": list(tail_rows),
        "tail_lines": [str(r.get("text") or "") for r in tail_rows],
        "middle_rows": list(middle_rows),
        "head_lines": list(head_lines),
        "summary_row": summary_row,
        "has_summary": summary_row is not None,
        "window_start_ts": 0,
        "window_end_ts": int(window_end or 0),
    }


def _force_budget(monkeypatch, svc, budget, *, window=200_000, pool=None):
    """Live capacity → ровно заданный effective input budget."""
    monkeypatch.setattr(
        dcs._model_capacity, "capacity_resolver_enabled", lambda: True)
    monkeypatch.setattr(dcs._auto_budget, "auto_budget_enabled", lambda: True)

    async def _win(base_url, model, slot=None):
        return int(window), "test-window"

    async def _stage(slot, **kwargs):
        return SimpleNamespace(
            context_window=int(window), source="test-window",
            auto_input_budget=int(budget), output_reserve=0,
            effective_input_budget=int(budget), policy_mode="dynamic")

    async def _external(chat_id, model_window, extra_prompt_blocks=()):
        return 0, 0, "test-estimate"

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _win)
    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _stage)
    monkeypatch.setattr(svc, "_estimate_external_payload_tokens", _external)
    if pool is not None:
        pool["budget"] = int(budget)


def _stub_episodes(svc, monkeypatch, *, rows=(), supplement=()):
    async def _episodes(*args, **kwargs):
        return "", {
            "count": 0, "messages": 0, "tokens": 0, "hits": 0,
            "spans": [], "rows": list(rows),
            "supplement_lines": list(supplement),
        }

    monkeypatch.setattr(svc, "_build_old_episodes", _episodes)


async def _live(svc, message, *, blocks=None, chain=(), window=None,
                global_parts=None, rag_memory=None, history_sample=None,
                out_excluded=None, out_prepared=None,
                target_user_id=ADDRESSEE, target_name="Аня"):
    return await svc._compose_user_content(
        chat_id=CHAT, message=message,
        blocks=list(blocks or []), chain=list(chain),
        window=list(window or ()), roster=[], suffix_map={},
        global_parts=global_parts or _global_parts(),
        target_name=target_name, target_user_id=target_user_id,
        trigger_message_id=getattr(message, "message_id", None),
        out_excluded=out_excluded, rag_memory=rag_memory,
        history_sample=history_sample, live_selection=True,
        out_prepared=out_prepared)


def _text(blocks) -> str:
    return "\n".join(str(block) for block in blocks or ())


# ── UR-09.1: real channel extraction beyond the window ──────────────────────

@pytest.mark.asyncio
async def test_ur_09_1_real_fts_message_beyond_window_lands_in_payload(
        tmp_path, monkeypatch):
    """UR-09.1 / URC2-RFL-01: старый FTS-хит вне окна попадает в payload."""
    db = await _db(tmp_path, "fts_msg.db")
    try:
        await _add_msg(db, ADDRESSEE, "квазарит лежит в секретном архиве",
                       1000, 100)
        # Свежее окно другой темы — старого сообщения в нём нет.
        window = [_row(i, text=f"свежая болтовня {i}", uid=30 + i,
                       ts=9000 + i, tg=900 + i) for i in range(6)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        out: dict = {}
        excluded: list = []
        msg = _message(text="напомни, что я рассказывал про квазарит?",
                       message_id=5000)
        blocks = await _live(svc, msg, window=window, out_excluded=excluded,
                             out_prepared=out)
        payload = _text(blocks)
        assert "секретном архиве" in payload
        assert "<Old_Episode>" in payload or "<RAG_Memory>" in payload
        primary = out["primary"]
        ids = [sid for block in primary.event_blocks
               for sid in block.get("source_ids") or ()]
        assert "msg:100" in ids
        assert 100 not in [int(r.get("tg_message_id") or 0) for r in window]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_09_1_real_fts_spots_bounded_reads(tmp_path, monkeypatch):
    """UR-09.1: реальные FTS/thread-чтения bounded (лимит/соседи, не скан)."""
    db = await _db(tmp_path, "fts_bounds.db")
    try:
        await _add_msg(db, ADDRESSEE, "квазарит один", 1000, 100)
        for i in range(4):
            await _add_msg(db, ADDRESSEE, f"квазарит продолжение {i}",
                           1100 + i, 101 + i, reply_to=100 + i)
        window = [_row(i, text=f"свежая болтовня {i}", uid=40 + i, tg=700 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        seen = {"fts": [], "around": []}
        real_fts = db.search_messages_fts
        real_facts = db.search_graph_facts_fts
        real_around = db.get_messages_around

        async def _fts(chat_id, match, limit, **kwargs):
            seen["fts"].append(int(limit))
            return await real_fts(chat_id, match, limit, **kwargs)

        async def _facts(chat_id, match, limit, now, **kwargs):
            seen["fts"].append(int(limit))
            return await real_facts(chat_id, match, limit, now, **kwargs)

        async def _around(chat_id, tg, before=0, after=0, **kwargs):
            seen["around"].append((int(before), int(after)))
            return await real_around(chat_id, tg, before=before, after=after,
                                     **kwargs)

        monkeypatch.setattr(db, "search_messages_fts", _fts)
        monkeypatch.setattr(db, "search_graph_facts_fts", _facts)
        monkeypatch.setattr(db, "get_messages_around", _around)
        msg = _message(text="квазарит?", message_id=5100)
        await _live(svc, msg, window=window,
                    out_prepared={})
        assert seen["fts"]
        assert all(0 < limit <= 64 for limit in seen["fts"])
        assert seen["around"]
        assert all(0 <= before <= 4 and 0 <= after <= 4
                   for before, after in seen["around"])
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_09_1_without_real_fts_channel_old_message_is_not_found(
        tmp_path, monkeypatch):
    """Falsification UR-09.1: без search_messages_fts старый хит исчезает."""
    db = await _db(tmp_path, "fts_off.db")
    try:
        await _add_msg(db, ADDRESSEE, "квазарит лежит в секретном архиве",
                       1000, 100)
        window = [_row(i, text=f"свежая болтовня {i}", uid=50 + i, tg=800 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)

        async def _empty_fts(*args, **kwargs):
            return []

        monkeypatch.setattr(db, "search_messages_fts", _empty_fts)
        msg = _message(text="напомни про квазарит?", message_id=5200)
        blocks = await _live(svc, msg, window=window)
        assert "секретном архиве" not in _text(blocks)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_09_1_real_graph_facts_fts_beyond_window(
        tmp_path, monkeypatch):
    """UR-09.1: граф-факт вне окна извлекается реальным graph_facts_fts."""
    db = await _db(tmp_path, "fts_graph.db")
    try:
        await _add_msg(db, ADDRESSEE, "старый разговор о бюджете", 1000, 100)
        fact_id = await db.insert_graph_fact(
            CHAT, "бюджет проекта ровно 348 тысяч", "chat_history", None,
            subject_ref_id=ADDRESSEE, target_user="Аня",
            speaker_author_id=ADDRESSEE, tg_message_id=100,
            message_timestamp=1000)
        window = [_row(i, text=f"свежая болтовня {i}", uid=60 + i, tg=900 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        msg = _message(text="бюджет проекта 348?", message_id=5300)
        blocks = await _live(svc, msg, window=window)
        payload = _text(blocks)
        assert "348" in payload
        assert fact_id > 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_09_1_without_graph_facts_fts_fact_is_not_found(
        tmp_path, monkeypatch):
    """Falsification UR-09.1: без graph_facts_fts граф-факт не достаётся."""
    db = await _db(tmp_path, "fts_graph_off.db")
    try:
        await _add_msg(db, ADDRESSEE, "старый разговор о бюджете", 1000, 100)
        await db.insert_graph_fact(
            CHAT, "бюджет проекта ровно 348 тысяч", "chat_history", None,
            subject_ref_id=ADDRESSEE, target_user="Аня",
            speaker_author_id=ADDRESSEE, tg_message_id=100,
            message_timestamp=1000)
        window = [_row(i, text=f"свежая болтовня {i}", uid=90 + i, tg=970 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)

        async def _empty_facts(*args, **kwargs):
            return []

        monkeypatch.setattr(db, "search_graph_facts_fts", _empty_facts)
        msg = _message(text="бюджет проекта 348?", message_id=5350)
        blocks = await _live(svc, msg, window=window)
        assert "тысяч" not in _text(blocks)
    finally:
        await db.close()


# ── UR-13.6: identity prior on real retrieved facts ─────────────────────────

def _identity_rows():
    # Векторная заглушка отдаёт ЧУЖОЙ факт первым: семантическая близость
    # выше. Identity-prior обязан поднять факт адресата (subject_ref_id=10).
    foreign = {
        "id": 3, "item_id": "fact:3", "origin": "chat_history",
        "fact": "чужой квазарит: очень близко по смыслу к вопросу",
        "rag_ts": 2_000, "status": "confirmed",
        "subject_ref_id": OTHER, "target_user": "Борис",
        "speaker_author_id": ADDRESSEE, "attribution_method": "self_report",
        "assertion_kind": "biographical",
    }
    addressee = {
        "id": 2, "item_id": "fact:2", "origin": "chat_history",
        "fact": "адресат говорил про квазарит прошлой осенью",
        "rag_ts": 1_000, "status": "confirmed",
        "subject_ref_id": ADDRESSEE, "target_user": "Аня",
        "speaker_author_id": ADDRESSEE, "attribution_method": "self_report",
        "assertion_kind": "biographical",
    }
    return foreign, addressee


@pytest.mark.asyncio
async def test_ur_13_6_identity_prior_keeps_addressee_first(
        tmp_path, monkeypatch):
    """UR-13.6: exact subject (+150) держит адресата выше чужой близости."""
    db = await _db(tmp_path, "identity.db")
    try:
        foreign, addressee = _identity_rows()
        window = [_row(1, text="свежая болтовня", uid=30, tg=980)]
        svc = _make_service(
            memory=FakeMemory(window=window,
                              rag_facts=[foreign, addressee]),
            db=db, bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        captured: dict = {}
        real_retrieve = rc.retrieve

        async def _retrieve(db_, memory_, request):
            result = await real_retrieve(db_, memory_, request)
            captured["result"] = result
            return result

        monkeypatch.setattr(dcs._mca_rc, "retrieve", _retrieve)
        msg = _message(text="что известно про квазарит?", message_id=5500)
        out: dict = {}
        blocks = await _live(svc, msg, window=window, out_prepared=out)
        result = captured["result"]
        ids = [cand.id for cand in result.candidates]
        assert ids, result
        assert ids[0] == "fact:2", ids
        assert result.candidates[0].subject_entity_id == ADDRESSEE
        payload = _text(blocks)
        assert payload.index("адресат говорил") < payload.index("чужой квазарит")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_13_6_real_graph_facts_identity_beats_fts_rank(
        tmp_path, monkeypatch):
    """UR-13.6: identity-prior работает на РЕАЛЬНЫХ graph_facts (FTS-ранг)."""
    db = await _db(tmp_path, "identity_real.db")
    try:
        await db.insert_graph_fact(
            CHAT, "адресат говорил про квазарит", "chat_history", None,
            subject_ref_id=ADDRESSEE, target_user="Аня",
            speaker_author_id=ADDRESSEE, tg_message_id=100,
            message_timestamp=1_000)
        # Чужой факт лексически сильнее (больше вхождений) — но не адресат.
        await db.insert_graph_fact(
            CHAT, "чужой квазарит квазарит квазарит", "chat_history", None,
            subject_ref_id=OTHER, target_user="Борис",
            speaker_author_id=ADDRESSEE, tg_message_id=101,
            message_timestamp=1_100)
        window = [_row(1, text="свежая болтовня", uid=30, tg=982)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        captured: dict = {}
        real_retrieve = rc.retrieve

        async def _retrieve(db_, memory_, request):
            result = await real_retrieve(db_, memory_, request)
            captured["result"] = result
            return result

        monkeypatch.setattr(dcs._mca_rc, "retrieve", _retrieve)
        msg = _message(text="что известно про квазарит?", message_id=5502)
        out: dict = {}
        blocks = await _live(svc, msg, window=window, out_prepared=out)
        result = captured["result"]
        ids = [cand.id for cand in result.candidates]
        assert ids, result
        assert ids[0] == "tg:100", ids
        assert result.candidates[0].subject_entity_id == ADDRESSEE
        payload = _text(blocks)
        assert payload.index("адресат говорил") < payload.index("чужой квазарит")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_13_6_without_identity_prior_foreign_wins(
        tmp_path, monkeypatch):
    """Falsification UR-13.6: без prior чужая близкая реплика выходит первой."""
    db = await _db(tmp_path, "identity_off.db")
    try:
        foreign, addressee = _identity_rows()
        window = [_row(1, text="свежая болтовня", uid=30, tg=981)]
        svc = _make_service(
            memory=FakeMemory(window=window,
                              rag_facts=[foreign, addressee]),
            db=db, bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        captured: dict = {}
        real_retrieve = rc.retrieve

        async def _retrieve(db_, memory_, request):
            result = await real_retrieve(db_, memory_, request)
            captured["result"] = result
            return result

        def _no_prior(candidates, **kwargs):
            return sorted(candidates, key=lambda c: c.score, reverse=True)

        monkeypatch.setattr(dcs._mca_rc, "retrieve", _retrieve)
        monkeypatch.setattr(rc, "apply_identity_prior", _no_prior)
        msg = _message(text="что известно про квазарит?", message_id=5501)
        await _live(svc, msg, window=window, out_prepared={})
        ids = [cand.id for cand in captured["result"].candidates]
        assert ids[0] == "fact:3", ids
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_09_1_real_thread_chain_beyond_window(
        tmp_path, monkeypatch):
    """UR-09.1: reply-parent без слов запроса достаётся реальным thread_chain."""
    db = await _db(tmp_path, "fts_thread.db")
    try:
        await _add_msg(db, ADDRESSEE, "принеси документы в пятницу", 1000, 100)
        # Триггер сохранён медиа-строкой без текста: лексически сам себя не
        # находит, поэтому родитель достижим ТОЛЬКО reply-графом.
        await _add_msg(db, ADDRESSEE, None, 2000, 101, reply_to=100)
        window = [_row(i, text=f"свежая болтовня {i}", uid=70 + i, tg=950 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        msg = _message(text="план на неделю?", message_id=101)
        blocks = await _live(svc, msg, window=window)
        assert "документы" in _text(blocks)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_09_1_without_thread_chain_reply_parent_is_not_found(
        tmp_path, monkeypatch):
    """Falsification UR-09.1: без реального thread_chain родитель не находится."""
    db = await _db(tmp_path, "fts_thread_off.db")
    try:
        await _add_msg(db, ADDRESSEE, "принеси документы в пятницу", 1000, 100)
        await _add_msg(db, ADDRESSEE, None, 2000, 101, reply_to=100)
        window = [_row(i, text=f"свежая болтовня {i}", uid=80 + i, tg=960 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 60_000)
        from services import thread_chain as tchain

        async def _empty_chain(*args, **kwargs):
            return []

        monkeypatch.setattr(tchain, "collect_thread_chain", _empty_chain)
        msg = _message(text="план на неделю?", message_id=101)
        blocks = await _live(svc, msg, window=window)
        assert "документы" not in _text(blocks)
    finally:
        await db.close()
