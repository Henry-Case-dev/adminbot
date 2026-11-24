"""UR-C-3: live proof for mixed-tier pressure, tight-budget P0 and authority.

Используется фактический `DirectChatService._compose_user_content` (live_-
selection). Реальный `DatabaseService` даёт окно/durable-ledger и memory-канал;
FakeMemory — только vector-заглушка. Каждый тест привязан к строке карты и
содержит discriminator/negative control; VERIFIED здесь не заявляется.
"""
import pytest

import services.direct_chat_service as dcs
from services import direct_context_composer as comp
from tests.test_direct_chat import FakeMemory, _make_service, _message
from tests.test_ur_c_3_real_fts import (
    ADDRESSEE,
    BOT_UID,
    CHAT,
    _add_msg,
    _db,
    _force_budget,
    _global_parts,
    _live,
    _row,
    _stub_episodes,
    _text,
)

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]


def _selection_spy(monkeypatch):
    """Захватить РЕАЛЬНУЮ selection/allocator, не подменяя поведение."""
    calls: list = []
    real = comp.allocate_selection

    def _select(selection, budget, **kwargs):
        result = real(selection, budget, **kwargs)
        calls.append((selection, int(budget), result))
        return result

    monkeypatch.setattr(comp, "allocate_selection", _select)
    return calls


def _tier_tokens(selection, tier: int) -> int:
    return sum(f.tokens() for f in selection.memory
               if f.role == comp.ROLE_MEMORY
               and int(getattr(f, "memory_tier", 0) or 0) == tier)


def _paid_fact_row(fact_id, text, *, tg=None, uid=ADDRESSEE):
    return {
        "id": fact_id, "item_id": f"fact:{fact_id}", "origin": "chat_history",
        "fact": text, "rag_ts": 2_000, "status": "confirmed",
        "subject_ref_id": uid, "target_user": "Аня",
        "speaker_author_id": uid, "tg_message_id": tg,
    }


# ── UR-09.6: mixed-tier order on the live path ──────────────────────────────

@pytest.mark.asyncio
async def test_ur_09_6_live_pressure_drops_tier4_then_tier3(
        tmp_path, monkeypatch):
    """UR-09.6: tier 4 снимается раньше tier 3; exact/lexical tier 2 живёт."""
    db = await _db(tmp_path, "tiers.db")
    try:
        await _add_msg(db, ADDRESSEE, "старый факт ZXQUARTZ про оплату",
                       1000, 100)
        episode_rows = [_row(
            900, text=("ЭПИЗОДНЫЙ_МАРКЕР " * 60), uid=ADDRESSEE,
            ts=1_500, tg=990)]
        rag_rows = [_paid_fact_row(
            5, ("ВЕКТОРНЫЙ_МАРКЕР " * 50))]
        window = [_row(i, text=f"свежая болтовня {i}", uid=40 + i, tg=920 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=episode_rows)
        calls = _selection_spy(monkeypatch)
        msg = _message(text="напомни ZXQUARTZ?", message_id=6000)

        # 1) Свободный бюджет: захватить фактическую full selection.
        _force_budget(monkeypatch, svc, 200_000)
        out: dict = {}
        await _live(svc, msg, window=window, rag_memory={"rows": rag_rows},
                    out_prepared=out)
        full = calls[-1][0]
        fixed = int(out["primary"].budget["fixed_p0_tokens"])
        current = sum(f.tokens() for f in
                      [full.current_question, *full.current_parts])
        tier2 = _tier_tokens(full, 2)
        tier3 = _tier_tokens(full, 3)
        tier4 = _tier_tokens(full, 4)
        assert tier2 > 0 and tier3 > 0 and tier4 > 0

        # 2) Хватает на current+tier2, но не на tier3/tier4.
        budget_two = fixed + current + tier2 + 5
        _force_budget(monkeypatch, svc, budget_two)
        excluded: list = []
        blocks = await _live(svc, msg, window=window,
                             rag_memory={"rows": rag_rows},
                             out_excluded=excluded)
        payload = _text(blocks)
        assert "старый факт" in payload
        assert "ВЕКТОРНЫЙ_МАРКЕР" not in payload
        assert "ЭПИЗОДНЫЙ_МАРКЕР" not in payload
        reasons = {item.get("reason_code") for item in excluded}
        assert {"memory_tier_4", "memory_tier_3"} <= reasons

        # 3) Хватает на tier 3 — tier 4 всё ещё снимается первым.
        budget_three = fixed + current + tier2 + tier3 + 5
        _force_budget(monkeypatch, svc, budget_three)
        excluded2: list = []
        blocks2 = await _live(svc, msg, window=window,
                              rag_memory={"rows": rag_rows},
                              out_excluded=excluded2)
        payload2 = _text(blocks2)
        assert "старый факт" in payload2
        assert "ВЕКТОРНЫЙ_МАРКЕР" in payload2
        assert "ЭПИЗОДНЫЙ_МАРКЕР" not in payload2
        reasons2 = {item.get("reason_code") for item in excluded2}
        assert "memory_tier_4" in reasons2
        assert "memory_tier_3" not in reasons2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_09_6_duplicate_source_id_is_not_duplicated(
        tmp_path, monkeypatch):
    """UR-09.6: дубль по source ID не дублируется в payload."""
    db = await _db(tmp_path, "dedup.db")
    try:
        await _add_msg(db, ADDRESSEE, "уникальный ZXDEDUP факт", 1000, 100)
        # Тот же источник приходит вторым каналом (episode rows).
        episode_rows = [_row(100, text="уникальный ZXDEDUP факт",
                             uid=ADDRESSEE, ts=1000, tg=100)]
        window = [_row(i, text=f"свежая болтовня {i}", uid=50 + i, tg=930 + i)
                  for i in range(3)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=episode_rows)
        calls = _selection_spy(monkeypatch)
        _force_budget(monkeypatch, svc, 200_000)
        msg = _message(text="напомни ZXDEDUP?", message_id=6100)
        blocks = await _live(svc, msg, window=window)
        full = calls[-1][0]
        same = [f for f in full.memory if f.source_id == "msg:100"]
        assert len(same) == 1
        duplicates = [item for item in full.provenance.dropped
                      if item.get("reason_code") == "duplicate_source"]
        assert duplicates and duplicates[0].get("count", 0) >= 1
        assert _text(blocks).count("уникальный ZXDEDUP") == 1
    finally:
        await db.close()


# ── UR-11.6: correction P0 under tight budget / physical overflow ───────────

def _correction_blocks():
    return [
        ("target", "<Target_User>Аня</Target_User>"),
        ("correction",
         "<Correction_Frame>\nПРАВКА_МАРКЕР: зарплата 90 тысяч, не 60\n"
         "</Correction_Frame>"),
        ("sandwich", dcs._SANDWICH_REMINDER),
    ]


def _long_question() -> str:
    return ("ТЕКУЩИЙ_ВОПРОС " + ("длинный вопрос про зарплату и бюджет "
                                 * 30) + "КОНЕЦ_ВОПРОСА")


@pytest.mark.asyncio
async def test_ur_11_6_tight_budget_keeps_correction_and_current(
        tmp_path, monkeypatch):
    """UR-11.6: correction+current переживают давление; не-P0 снимаются."""
    db = await _db(tmp_path, "tight.db")
    try:
        window = [_row(1, text="свежая болтовня", uid=30, tg=940)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=[_row(
            901, text=("ЭПИЗОДНЫЙ_МАРКЕР " * 60), uid=ADDRESSEE,
            ts=1_500, tg=991)])
        calls = _selection_spy(monkeypatch)
        msg = _message(text=_long_question(), message_id=6200)
        blocks = _correction_blocks()
        rag_rows = [_paid_fact_row(5, "ВЕКТОРНЫЙ_МАРКЕР " * 50)]

        _force_budget(monkeypatch, svc, 200_000)
        out: dict = {}
        await _live(svc, msg, blocks=blocks, window=window,
                    rag_memory={"rows": rag_rows}, out_prepared=out)
        full = calls[-1][0]
        fixed = int(out["primary"].budget["fixed_p0_tokens"])
        current = sum(f.tokens() for f in
                      [full.current_question, *full.current_parts])
        tight = fixed + current + 1

        _force_budget(monkeypatch, svc, tight)
        excluded: list = []
        out2: dict = {}
        blocks2 = await _live(svc, msg, blocks=blocks, window=window,
                              rag_memory={"rows": rag_rows},
                              out_excluded=excluded, out_prepared=out2)
        payload = _text(blocks2)
        assert "ПРАВКА_МАРКЕР" in payload
        assert "ТЕКУЩИЙ_ВОПРОС" in payload and "КОНЕЦ_ВОПРОСА" in payload
        assert "ВЕКТОРНЫЙ_МАРКЕР" not in payload
        assert "ЭПИЗОДНЫЙ_МАРКЕР" not in payload
        reasons = {item.get("reason_code") for item in excluded}
        assert {"memory_tier_4", "memory_tier_3"} <= reasons
        assert out2["primary"].budget["physical_overflow"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ur_11_6_physical_overflow_reports_parts_without_loss(
        tmp_path, monkeypatch):
    """UR-11.6: физическое переполнение P0 — явные части, правка не теряется."""
    db = await _db(tmp_path, "overflow.db")
    try:
        window = [_row(1, text="свежая болтовня", uid=30, tg=941)]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=[_row(
            902, text=("ЭПИЗОДНЫЙ_МАРКЕР " * 60), uid=ADDRESSEE,
            ts=1_500, tg=992)])
        calls = _selection_spy(monkeypatch)
        msg = _message(text=_long_question(), message_id=6300)
        blocks = _correction_blocks()
        rag_rows = [_paid_fact_row(5, "ВЕКТОРНЫЙ_МАРКЕР " * 50)]

        _force_budget(monkeypatch, svc, 200_000)
        out: dict = {}
        await _live(svc, msg, blocks=blocks, window=window,
                    rag_memory={"rows": rag_rows}, out_prepared=out)
        full = calls[-1][0]
        fixed = int(out["primary"].budget["fixed_p0_tokens"])
        current_tokens = sum(f.tokens() for f in
                             [full.current_question, *full.current_parts])
        tiny = fixed + max(1, current_tokens // 3)

        _force_budget(monkeypatch, svc, tiny)
        out2: dict = {}
        blocks2 = await _live(svc, msg, blocks=blocks, window=window,
                              rag_memory={"rows": rag_rows},
                              out_prepared=out2)
        payload = _text(blocks2)
        assert "ПРАВКА_МАРКЕР" in payload
        prepared = out2["primary"]
        assert prepared.budget["physical_overflow"] is True

        allocated = calls[-1][2]
        assert allocated.provenance.overflow is True
        overflow_current = [p for p in allocated.provenance.overflow_parts
                            if p.get("source_id") == full.current_question.source_id]
        included = [allocated.current_question, *allocated.current_parts]
        # Части не исчезают молча: вошедшие + явно названные = всем частям
        # детерминированного дробления того же текста.
        share = max(24, int((tiny - fixed) * 0.6))
        expected = comp.split_overflow_fragments(
            full.current_question, share)
        included_indices = [int(f.part_index) for f in included]
        expected_text = {int(p.part_index): str(p.text or "")
                         for p in expected}
        # Вошедшие части — ровно свои части исходника (без подмены текста).
        assert [expected_text[i] for i in included_indices] == \
            [str(f.text or "") for f in included]
        overflow_indices = {
            int(str(p.get("part") or "0/0").split("/", 1)[0])
            for p in overflow_current}
        # Ни одна часть не исчезает молча: вошедшие + явно названные =
        # полному детерминированному дроблению, пересечений нет.
        assert not (set(included_indices) & overflow_indices)
        assert set(included_indices) | overflow_indices == \
            set(range(1, len(expected) + 1))
        assert all(p.get("reason_code") == "physical_overflow"
                   for p in overflow_current)
    finally:
        await db.close()


# ── UR-BAN-04: authority matrix in one live payload ─────────────────────────

@pytest.mark.asyncio
async def test_ur_ban_04_live_authority_matrix(tmp_path, monkeypatch):
    """UR-BAN-04: participant/episode primary, bot supporting, summary/fact bg."""
    db = await _db(tmp_path, "authority.db")
    try:
        participant = _row(1, text="УЧАСТНИК_МАРКЕР: я согласен",
                           uid=ADDRESSEE, tg=600)
        await _add_msg(db, ADDRESSEE, "УЧАСТНИК_МАРКЕР: я согласен",
                       1_000, 600)
        await db.record_bot_output(
            chat_id=CHAT, bot_user_id=BOT_UID, tg_message_id=700,
            sent_at=1_100, parent_message_ref="tg:600",
            output_kind="direct_reply",
            content_text="БОТ_МАРКЕР: я тоже так думаю",
            correlation_id="c-urc3")
        episode_rows = [_row(2, text="ЭПИЗОД_МАРКЕР: слова участника",
                             uid=ADDRESSEE, ts=900, tg=601)]
        rag_rows = [_paid_fact_row(7, "ФАКТ_МАРКЕР: проверено в чате")]
        summary = {"summary": "САММАРИ_МАРКЕР", "window_end_ts": 3_000,
                   "raw_count": 10, "chat_id": CHAT}
        window = [participant]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=episode_rows)
        calls = _selection_spy(monkeypatch)
        _force_budget(monkeypatch, svc, 200_000)
        msg = _message(text="что скажешь?", message_id=6400)
        blocks = await _live(
            svc, msg, window=window, rag_memory={"rows": rag_rows},
            global_parts=_global_parts(
                tail_rows=window, head_lines=["САММАРИ_МАРКЕР"],
                summary_row=summary, window_end=3_000))
        full = calls[-1][0]
        by_text = {f.text: f for f in full.fragments()}
        participant_frag = by_text["УЧАСТНИК_МАРКЕР: я согласен"]
        bot_frag = by_text["БОТ_МАРКЕР: я тоже так думаю"]
        episode_frag = by_text["ЭПИЗОД_МАРКЕР: слова участника"]
        fact_frag = by_text["ФАКТ_МАРКЕР: проверено в чате"]
        summary_frag = by_text["САММАРИ_МАРКЕР"]
        assert participant_frag.authority == comp.AUTHORITY_PRIMARY
        assert participant_frag.kind == comp.KIND_USER_STATEMENT
        assert bot_frag.authority == comp.AUTHORITY_SUPPORTING
        assert bot_frag.kind == comp.KIND_BOT_STATEMENT
        assert summary_frag.authority == comp.AUTHORITY_BACKGROUND
        assert fact_frag.authority == comp.AUTHORITY_BACKGROUND
        assert episode_frag.authority == comp.AUTHORITY_PRIMARY
        # UR-13.4: внешнее доказательство — primary by contract; в Direct-L2
        # сейчас нет live-производителя external evidence (не выдумываем его).
        assert comp.authority_for_kind(comp.KIND_EXTERNAL_EVIDENCE) == \
            comp.AUTHORITY_PRIMARY
        # summary и слова бота не занимают primary и не подменяют источники.
        assert summary_frag.authority != comp.AUTHORITY_PRIMARY
        assert bot_frag.authority != comp.AUTHORITY_PRIMARY

        payload = _text(blocks)
        assert "САММАРИ_МАРКЕР" in payload
        assert "БОТ_МАРКЕР" in payload
        assert "УЧАСТНИК_МАРКЕР" in payload
        assert "ФАКТ_МАРКЕР" in payload
        assert "ЭПИЗОД_МАРКЕР" in payload
        rag_body = payload.split("<RAG_Memory>", 1)[1].split(
            "</RAG_Memory>", 1)[0]
        assert "САММАРИ_МАРКЕР" not in rag_body
        assert "ФАКТ_МАРКЕР" in rag_body
    finally:
        await db.close()
