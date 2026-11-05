"""UNIFIED-REPLY UR-23 — единая история собственных сообщений (ledger).

Покрывает строки карты UR-C:
  * UR-23/23.2 — собственные доставленные сообщения доступны как события
    разговора через durable ledger (не только TTL-кеш), в хронологии, с
    `speaker_uid`, `tg_message_id`, `sent_at_utc`, `reply_to`,
    `correlation_id`, ревизией;
  * UR-23.3 — свой ответ вплетён в reply-граф по исходному
    `parent_message_ref` (в том числе после истечения TTL `bot_reply_parents`);
  * UR-23.5 — «бот это говорил» подтверждается ledger'ом, но не становится
    стилевым образцом/источником истины о мире;
  * UR-23.7 — scope строго по `chat_id`; старые/пустые/media-only/неудавшийся
    send/неизвестная дата/правки обрабатываются честно;
  * UR-23.4 — правка = новая ревизия, история ревизий доступна явным запросом.
"""
import pytest

from services import direct_context_composer as comp
from services import bot_output_ledger as ledger
from services.database import DatabaseService

CHAT = -100555
BOT_UID = 998000


async def _db(tmp_path, name="ur23.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _bot_output(db, *, chat_id=CHAT, tg=100, sent_at=1000, text="ответ",
                      parent=None, revision=1, correlation=None,
                      status="delivered", kind="direct_reply", bot_uid=BOT_UID,
                      content_ref=None):
    return await db.record_bot_output(
        chat_id=chat_id, bot_user_id=bot_uid, tg_message_id=tg,
        revision_no=revision, sent_at=sent_at, parent_message_ref=parent,
        output_kind=kind, content_text=text, content_ref=content_ref,
        correlation_id=correlation, delivery_status=status)


class TestLedgerHistoryReadPath:
    @pytest.mark.asyncio
    async def test_chronological_delivered_only_and_chat_scoped(self, tmp_path):
        db = await _db(tmp_path, "chrono.db")
        try:
            await _bot_output(db, tg=101, sent_at=3000, text="третий")
            await _bot_output(db, tg=102, sent_at=1000, text="первый")
            await _bot_output(db, tg=103, sent_at=2000, text="второй")
            await _bot_output(db, tg=104, sent_at=4000, text="провал",
                              status="failed")
            await _bot_output(db, chat_id=CHAT + 1, tg=105, sent_at=1500,
                              text="чужой чат")
            rows = await ledger.list_bot_output_history(db, CHAT)
            assert [row["tg_message_id"] for row in rows] == [102, 103, 101]
            assert all(row["delivery_status"] == "delivered" for row in rows)
            assert all(row["chat_id"] == CHAT for row in rows)
            assert rows[0]["source_id"].startswith("bot_output:")
            assert rows[0]["self_referential"] is True
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_latest_revision_wins_and_history_is_available(self, tmp_path):
        db = await _db(tmp_path, "edits.db")
        try:
            await _bot_output(db, tg=200, sent_at=1000, text="черновик",
                              revision=1)
            await _bot_output(db, tg=200, sent_at=1010, text="исправленный",
                              revision=2)
            rows = await ledger.list_bot_output_history(db, CHAT)
            assert len(rows) == 1
            assert rows[0]["text"] == "исправленный"
            assert rows[0]["revision"] == 2
            history = await db.get_bot_output_revisions(CHAT, 200)
            assert [row["content_text"] for row in history] == [
                "черновик", "исправленный"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_media_only_and_unknown_date_are_honest(self, tmp_path):
        db = await _db(tmp_path, "media.db")
        try:
            await _bot_output(db, tg=300, sent_at=None, text=None,
                              content_ref="caption_of:300")
            rows = await ledger.list_bot_output_history(db, CHAT)
            assert len(rows) == 1
            record = rows[0]
            assert record["text"] == ""
            assert record["media_only"] is True
            assert record["time_known"] is False
            assert record["sent_at"] == 0
            # Фрагмент: текст не выдуман, дата не подставлена «сейчас».
            frag = comp.ledger_record_to_fragment(record)
            assert frag.kind == comp.KIND_BOT_STATEMENT
            assert frag.text == ""
            assert frag.time_known is False
            assert frag.timestamp_utc == 0
            assert "медиа" in frag.note
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_chunks_share_correlation_and_keep_order(self, tmp_path):
        db = await _db(tmp_path, "chunks.db")
        try:
            await _bot_output(db, tg=401, sent_at=5000, text="часть 1",
                              correlation="logical-77", revision=1)
            await _bot_output(db, tg=402, sent_at=5001, text="часть 2",
                              correlation="logical-77", revision=1)
            rows = await ledger.list_bot_output_history(db, CHAT)
            assert [row["tg_message_id"] for row in rows] == [401, 402]
            assert {row["correlation_id"] for row in rows} == {"logical-77"}
            by_corr = await db.get_bot_output_by_correlation(
                CHAT, "logical-77")
            assert by_corr is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_range_filter_uses_real_sent_at(self, tmp_path):
        db = await _db(tmp_path, "range.db")
        try:
            await _bot_output(db, tg=501, sent_at=100)
            await _bot_output(db, tg=502, sent_at=500)
            await _bot_output(db, tg=503, sent_at=900)
            rows = await ledger.list_bot_output_history(
                db, CHAT, since_ts=200, until_ts=800)
            assert [row["tg_message_id"] for row in rows] == [502]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_gate_off_means_no_pretend_memory(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "gate.db")
        try:
            await _bot_output(db, tg=600, sent_at=1000, text="ответ")
            monkeypatch.setattr(ledger, "ledger_enabled", lambda: False)
            assert await ledger.list_bot_output_history(db, CHAT) == []
        finally:
            await db.close()


class TestThreadChainBotDating:
    @pytest.mark.asyncio
    async def test_ttl_cache_turn_gets_real_sent_at_from_ledger(self, tmp_path):
        import time as _time
        from services.thread_chain import collect_thread_chain
        db = await _db(tmp_path, "ttlcache.db")
        try:
            await db.save_smart_message(
                user_id=11, chat_id=CHAT, text="я обещал вернуть",
                reply_to_id=None, timestamp=1000, media_type="text",
                author_name="Вася", message_id=700)
            # TTL-кеш ЖИВ (иначе это уже ledger-путь), но времени отправки в
            # нём нет вообще (R16) — дату даёт только durable ledger.
            now = _time.time()
            await db.upsert_bot_reply(CHAT, 701, "верну завтра", now)
            await db.set_bot_reply_parent(CHAT, 701, 700, now)
            await _bot_output(db, tg=701, sent_at=1500, parent="tg:700",
                              text="верну завтра", correlation="c-1")
            chain = await collect_thread_chain(db, CHAT, 701, depth=4)
            bot = [item for item in chain if item.is_bot][0]
            assert bot.text == "верну завтра"
            # Дата — фактическая отправка из ledger, не «сейчас».
            assert bot.ts == 1500
            assert bot.source_kind == "bot_output"
            assert bot.correlation_id == "c-1"
            assert bot.reply_to_item_id == "tg:700"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_parent_link_survives_expired_bot_reply_parents(self, tmp_path):
        from services.thread_chain import collect_thread_chain
        db = await _db(tmp_path, "expired.db")
        try:
            await db.save_smart_message(
                user_id=11, chat_id=CHAT, text="старое сообщение",
                reply_to_id=None, timestamp=100, media_type="text",
                author_name="Вася", message_id=800)
            await db.upsert_bot_reply(CHAT, 801, "ответ на старое", 200.0)
            # Parent-линк TTL-кеша уже протух — остаётся только ledger.
            await db.set_bot_reply_parent(CHAT, 801, 800, 100.0)
            await _bot_output(db, tg=801, sent_at=150, parent="tg:800",
                              text="ответ на старое")
            chain = await collect_thread_chain(
                db, CHAT, 801, depth=4,
                bot_parent_getter=lambda cid, mid: _none())
            items = list(reversed(chain))
            assert [item.text for item in items] == [
                "старое сообщение", "ответ на старое"]
            assert items[0].uid == 11
            assert items[1].is_bot is True
        finally:
            await db.close()


async def _none():
    return None


class TestSelfOutputsInSelection:
    @pytest.mark.asyncio
    async def test_bot_turn_is_dialog_fact_not_style_anchor(self, tmp_path):
        db = await _db(tmp_path, "selection.db")
        try:
            await _bot_output(db, tg=901, sent_at=2000,
                              text="я обещал вернуть 174 тысячи",
                              parent="tg:900", correlation="turn-42")
            fragments = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=BOT_UID)
            selection = comp.build_context_selection(
                chat_id=CHAT, current_text="что ты обещал вчера?",
                reply_to_tg=950, timestamp_utc=3000,
                self_outputs=fragments, budget_tokens=10 ** 6)
            bot = selection.self_outputs[0]
            assert bot.kind == comp.KIND_BOT_STATEMENT
            assert bot.role == comp.ROLE_SELF_OUTPUT
            assert bot.authority == comp.AUTHORITY_SUPPORTING
            assert bot.timestamp_utc == 2000
            assert bot.reply_to_tg_id == 900
            # Никакой style-anchor семантики: это данные диалога.
            assert "подраж" not in bot.note.casefold()
            assert bot.source_id.startswith("bot_output:")
            dump = selection.as_dict()["self_outputs"][0]
            assert dump["kind"] == comp.KIND_BOT_STATEMENT
            assert "text" not in dump          # R17: без сырого текста

        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_duplicate_bot_turn_from_chain_and_ledger_dedups(self, tmp_path):
        from services.thread_chain import collect_thread_chain
        db = await _db(tmp_path, "dedup.db")
        try:
            await db.save_smart_message(
                user_id=11, chat_id=CHAT, text="вопрос", reply_to_id=None,
                timestamp=100, media_type="text", author_name="Вася",
                message_id=1000)
            await db.upsert_bot_reply(CHAT, 1001, "ответ бота", 4000.0)
            await db.set_bot_reply_parent(CHAT, 1001, 1000, 4000.0)
            await _bot_output(db, tg=1001, sent_at=150, parent="tg:1000",
                              text="ответ бота", correlation="c-2")
            chain = await collect_thread_chain(db, CHAT, 1001, depth=4)
            thread = [comp.chain_item_to_fragment(item,
                                                  role=comp.ROLE_THREAD)
                      for item in reversed(chain)]
            self_outputs = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=BOT_UID)
            selection = comp.build_context_selection(
                chat_id=CHAT, current_text="что ты сказал?",
                reply_to_tg=1001, timestamp_utc=5000, thread=thread,
                self_outputs=self_outputs, budget_tokens=10 ** 6)
            bot_fragments = [f for f in selection.fragments()
                             if f.kind == comp.KIND_BOT_STATEMENT
                             and f.tg_message_id == 1001]
            assert len(bot_fragments) == 1
            assert bot_fragments[0].correlation_id == "c-2"
            assert bot_fragments[0].timestamp_utc == 150
        finally:
            await db.close()
