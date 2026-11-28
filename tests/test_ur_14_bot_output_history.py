"""UNIFIED-REPLY UR-14.1 — собственные сообщения бота как участники истории.

Требование: доставленные ответы бота остаются полноценными участниками
хронологической истории и доступны по ``chat_id``/``tg_message_id``/
``sent_at``/reply-parent/ревизии/``correlation_id`` с source-маркером
``bot_output`` — а не только как TTL-кеш или стилевой якорь.

Тест идёт через настоящий write-path ledger'а, настоящий read-path истории,
живой producer `ContextSelection` и канонический L2-материализатор. Ни одна
проверяемая функция не подменяется.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-14.1
"""
import pytest

import services.direct_chat_service as dcs
from services import bot_output_ledger as ledger
from services import direct_context_composer as comp
from services.database import DatabaseService
from services.thread_chain import collect_thread_chain

pytestmark = [pytest.mark.system2]

CHAT = -100777
BOT_UID = 998111
HUMAN_TG = 400
BOT_TG = 501


class _Aliases:
    def resolve(self, uid, name, username):
        return name or f"u{uid}"


def _human_row() -> dict:
    return {
        "id": HUMAN_TG, "tg_message_id": HUMAN_TG, "user_id": 11,
        "author_name": "Вася", "text": "напомни, что ты обещал",
        "timestamp": 1000, "media_type": "text", "reply_to_id": None,
    }


def _render_row(service, frag, source):
    base = dict(source or {})
    base["text"] = frag.text
    return service._context_row_line(
        base, {}, trigger_message_id=None, projection=None, window_items=None)


@pytest.mark.asyncio
async def test_delivered_bot_output_is_full_history_participant(tmp_path):
    db = DatabaseService(str(tmp_path / "ur14.db"))
    await db.initialize()
    try:
        output_id = await ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=BOT_TG,
            text="я обещал вернуть 174 тысячи",
            bot_user_id=BOT_UID, output_kind="direct_reply", sent_at=2000,
            parent_message_ref=f"tg:{HUMAN_TG}",
            correlation_id="turn-ur14", revision_no=2)
        assert output_id is not None

        # ── запись ledger'а: все оси участника истории ────────────────────
        record = await db.get_bot_output_by_tg(CHAT, BOT_TG)
        assert record is not None
        assert record["chat_id"] == CHAT
        assert record["tg_message_id"] == BOT_TG
        assert record["sent_at"] == 2000
        assert record["parent_message_ref"] == f"tg:{HUMAN_TG}"
        assert record["revision_no"] == 2
        assert record["correlation_id"] == "turn-ur14"
        assert record["delivery_status"] == "delivered"

        # ── единый read-path: source-маркер bot_output ────────────────────
        rows = await ledger.list_bot_output_history(db, CHAT)
        assert len(rows) == 1
        history_row = rows[0]
        assert history_row["source"] == "bot_output_ledger"
        assert history_row["source_id"] == f"bot_output:{output_id}"
        assert history_row["chat_id"] == CHAT
        assert history_row["revision"] == 2

        # ── thread-chain: собственный ход — обычный факт диалога ──────────
        await db.save_smart_message(
            user_id=11, chat_id=CHAT, text="напомни, что ты обещал",
            reply_to_id=None, timestamp=1000, media_type="text",
            author_name="Вася", message_id=HUMAN_TG)
        chain = await collect_thread_chain(db, CHAT, BOT_TG, depth=4)
        bot_items = [item for item in chain
                     if item.item_id == f"tg:{BOT_TG}"]
        assert bot_items, "ход бота не попал в цепочку истории"
        assert bot_items[0].source_kind == "bot_output"
        assert bot_items[0].correlation_id == "turn-ur14"

        # ── composer: фрагмент с полными осями ────────────────────────────
        fragments = await comp.collect_self_output_fragments(
            db, chat_id=CHAT, bot_user_id=BOT_UID)
        assert len(fragments) == 1
        frag = fragments[0]
        assert frag.kind == comp.KIND_BOT_STATEMENT
        assert frag.role == comp.ROLE_SELF_OUTPUT
        assert frag.source_id == f"bot_output:{output_id}"
        assert frag.tg_message_id == BOT_TG
        assert frag.timestamp_utc == 2000
        assert frag.time_known is True
        assert frag.reply_to == f"tg:{HUMAN_TG}"
        assert frag.reply_to_tg_id == HUMAN_TG
        assert frag.revision == 2
        assert frag.correlation_id == "turn-ur14"
        assert frag.speaker_uid == BOT_UID
        assert frag.text == "я обещал вернуть 174 тысячи"
        assert frag.authority == comp.AUTHORITY_SUPPORTING

        # ── живой L2 producer: собственный ход в общей истории ────────────
        human = _human_row()
        selection = dcs._build_l2_selection_candidates(
            current_text="что ты обещал вчера?", window_rows=[human],
            working_window_messages=3, self_output_records=rows,
            budget_tokens=0, allocate=False, preserve_projections=True)
        selected = [f for f in selection.fragments()
                    if f.source_id == frag.source_id]
        assert len(selected) == 1
        assert selected[0].tg_message_id == BOT_TG
        assert selected[0].revision == 2
        assert selected[0].correlation_id == "turn-ur14"

        service = dcs.DirectChatService(None, None, None, _Aliases(),
                                        bot_id=BOT_UID)
        source_index = {f"msg:{HUMAN_TG}": human,
                        frag.source_id: {
                            "tg_message_id": BOT_TG, "timestamp": 2000,
                            "user_id": BOT_UID, "author_name": "бот",
                            "text": frag.text,
                            "reply_to_id": HUMAN_TG}}
        blocks = dict(dcs._materialize_selection(
            selection, render_chain_line=lambda f, s: "",
            render_row_line=lambda f, s: _render_row(service, f, s),
            source_index=source_index))
        body = blocks.get("global", "")
        assert "я обещал вернуть 174 тысячи" in body
        assert f"tg:{BOT_TG}" in body
        # Это история диалога, а не style-anchor/подражание.
        assert "style_anchors" not in body
        assert "подражай" not in body.casefold()
    finally:
        await db.close()
