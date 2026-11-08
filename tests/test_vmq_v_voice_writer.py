"""VMQ-V (VOICE-01 P0) — голосовые source-ref'ы → фактический payload Writer'а.

Проверяется НЕ «статус STT success», а содержимое, которое реально получает
Writer: текст готовых расшифровок с автором/хронологией/source-ref, честные
состояния pending/failed/unavailable/missing, разрешение группы 2–3 соседних
голосовых (Reply/цитата/дейксис/хронология), приоритет запрошенного медиа над
фоном при тесном окне и cross-chat изоляция.

Строки требований: V-01 (source-ref ↔ версия расшифровки), V-02 (группа 2–3
медиа), V-03 (ready-транскрипт реально доставлен Writer), V-04 (pending/
failed/restart/кэш без ложного «не вижу»).
"""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from services import voice_transcripts as vt
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.payload_builder import build_messages

CHAT_ID = -1007777770001
OTHER_CHAT = -1007777770002
BOT_ID = 999
USER_A = 111
USER_B = 222

T0 = int(time.time()) - 600


# ── инфраструктура ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    service = DatabaseService(":memory:")
    await service.initialize()
    try:
        yield service
    finally:
        await service.close()


async def add_message(db, chat_id=CHAT_ID, tg_id=100, *, ts=T0, author="Вася",
                      user_id=USER_A, text=None, media_type="voice",
                      caption=None, reply_to=None, is_forward=False,
                      forward_source=""):
    row_id = await db.save_smart_message(
        user_id=user_id, chat_id=chat_id, text=text, reply_to_id=reply_to,
        timestamp=ts, media_type=media_type, author_name=author,
        is_forward=is_forward, forward_source=forward_source,
        message_id=tg_id)
    if caption is not None:
        await db.db.execute(
            "UPDATE smart_messages SET caption = ? WHERE id = ?",
            (caption, row_id))
        await db.db.commit()
    return row_id


async def add_voice(db, chat_id=CHAT_ID, tg_id=101, *, ts=T0, author="Вася",
                    user_id=USER_A, status=None, transcript=None,
                    reason="", caption=None, is_forward=False,
                    forward_source=""):
    await add_message(db, chat_id, tg_id, ts=ts, author=author,
                      user_id=user_id, text=None, caption=caption,
                      is_forward=is_forward, forward_source=forward_source)
    if status is not None:
        await db.set_smart_message_transcript(
            chat_id, tg_id, status=status, text=transcript, reason=reason)
    return tg_id


def make_query(text, *, message_id=10000, reply=None, quote=None):
    return SimpleNamespace(message_id=message_id, text=text,
                           quote=(SimpleNamespace(text=quote)
                                  if quote is not None else None),
                           reply_to_message=reply,
                           caption=None, from_user=SimpleNamespace(id=USER_A))


def make_reply(tg_id, *, bot=False):
    """aiogram-подобный reply-таргет: у голосового есть `.voice`."""
    return SimpleNamespace(
        message_id=tg_id,
        from_user=SimpleNamespace(id=BOT_ID if bot else USER_A),
        voice=(None if bot else SimpleNamespace(duration=5, file_id="r1")),
        video_note=None)


def make_service(db, *, bot_id=BOT_ID):
    return DirectChatService(
        memory=MagicMock(), db=db, llm=MagicMock(), aliases=MagicMock(),
        bot_id=bot_id, bot_username="test_bot")


# ══════════════════════════════════════════════════════════════════════════
# V-01: один source-ref, расшифровка — версия содержимого
# ══════════════════════════════════════════════════════════════════════════

class TestSourceRevision:
    @pytest.mark.asyncio
    async def test_transcript_is_version_of_single_source_ref(self, db):
        row_id = await add_message(db, tg_id=501)
        pending = await db.set_smart_message_transcript(
            CHAT_ID, 501, status="pending")
        assert pending == 0                   # версии содержимого ещё нет
        first = await db.set_smart_message_transcript(
            CHAT_ID, 501, status="ready", text="первый вариант")
        assert first == 1
        row = await db.get_smart_message_by_tg_id(CHAT_ID, 501)
        assert row["text"] == "первый вариант"
        assert row["transcript_status"] == "ready"
        assert row["transcript_revision"] == 1
        assert row["transcript_updated_at"]
        # Повторная публикация ТОГО ЖЕ текста — та же версия (не мигает).
        again = await db.set_smart_message_transcript(
            CHAT_ID, 501, status="ready", text="первый вариант")
        assert again == 1
        # Новая расшифровка — новая ВЕРСИЯ того же source-ref.
        second = await db.set_smart_message_transcript(
            CHAT_ID, 501, status="ready", text="исправленный вариант")
        assert second == 2
        # И ровно одна строка: расшифровка не создаёт новую реплику.
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
            (CHAT_ID,))
        assert (await cursor.fetchone())["n"] == 1
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_terminal_failure_keeps_previous_text_without_revision(self, db):
        await add_voice(db, tg_id=502, status="ready", transcript="готовый текст")
        rev = await db.set_smart_message_transcript(
            CHAT_ID, 502, status="failed", reason="stt_failed")
        assert rev == 1
        row = await db.get_smart_message_by_tg_id(CHAT_ID, 502)
        # Провал повторного STT не стирает уже полученную версию.
        assert row["text"] == "готовый текст"
        assert row["transcript_status"] == "failed"
        assert row["transcript_reason"] == "stt_failed"

    @pytest.mark.asyncio
    async def test_ready_without_text_is_honest_unavailable(self, db):
        await add_voice(db, tg_id=503)
        await db.set_smart_message_transcript(
            CHAT_ID, 503, status="ready", text="   ")
        row = await db.get_smart_message_by_tg_id(CHAT_ID, 503)
        assert row["transcript_status"] == "unavailable"
        assert row["transcript_reason"] == "empty_transcript"

    @pytest.mark.asyncio
    async def test_caption_is_not_a_transcript(self, db):
        await add_voice(db, tg_id=504, caption="подпись к голосовому")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в голосовых?"),
            query="что в голосовых?")
        assert bundle is not None
        assert [i.status for i in bundle.items] == [vt.TRANSCRIPT_PENDING]
        assert bundle.items[0].text == ""


# ══════════════════════════════════════════════════════════════════════════
# V-02: группа 2–3 соседних голосовых (хронология/Reply/цитата/дейксис)
# ══════════════════════════════════════════════════════════════════════════

class TestGroupResolution:
    @pytest.mark.asyncio
    async def test_two_adjacent_voices_delivered_with_authors(self, db):
        await add_voice(db, tg_id=101, ts=T0, author="Вася", user_id=USER_A,
                        status="ready", transcript="первое голосовое про поезд")
        await add_voice(db, tg_id=102, ts=T0 + 5, author="Лена", user_id=USER_B,
                        status="ready", transcript="второе про билеты")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("Что думаешь про верхние голосовые?"),
            query="Что думаешь про верхние голосовые?")
        assert bundle is not None
        assert bundle.refs == ("tg:101", "tg:102")
        assert [i.author for i in bundle.items] == ["Вася", "Лена"]
        assert [i.text for i in bundle.items] == [
            "первое голосовое про поезд", "второе про билеты"]
        assert [i.revision for i in bundle.items] == [1, 1]
        # Хронология, а не «случайный сосед из хвоста».
        assert [i.timestamp for i in bundle.items] == [T0, T0 + 5]

    @pytest.mark.asyncio
    async def test_three_adjacent_voices_ordered(self, db):
        for tg, ts, text in ((101, T0, "раз"), (102, T0 + 3, "два"),
                             (103, T0 + 6, "три")):
            await add_voice(db, tg_id=tg, ts=ts, status="ready", transcript=text)
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("разбери эти голосовые"),
            query="разбери эти голосовые")
        assert bundle.refs == ("tg:101", "tg:102", "tg:103")
        assert bundle.summary_status() == vt.TRANSCRIPT_READY

    @pytest.mark.asyncio
    async def test_first_two_and_last_two_are_not_interchangeable(self, db):
        for tg, ts, text in ((101, T0, "раз"), (102, T0 + 3, "два"),
                             (103, T0 + 6, "три")):
            await add_voice(db, tg_id=tg, ts=ts, status="ready", transcript=text)
        first = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("расшифруй первые два голосовых"),
            query="расшифруй первые два голосовых")
        last = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("расшифруй последние два голосовых"),
            query="расшифруй последние два голосовых")
        assert first.refs == ("tg:101", "tg:102")
        assert last.refs == ("tg:102", "tg:103")

    @pytest.mark.asyncio
    async def test_interrupting_text_message_breaks_the_run(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready", transcript="старое")
        await add_message(db, tg_id=102, ts=T0 + 2, text="обычная реплика",
                          media_type="text")
        await add_voice(db, tg_id=103, ts=T0 + 4, status="ready",
                        transcript="свежее")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в верхних голосовых?"),
            query="что в верхних голосовых?")
        assert bundle.refs == ("tg:103",)

    @pytest.mark.asyncio
    async def test_reply_targets_that_message_first(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready", transcript="раз")
        await add_voice(db, tg_id=102, ts=T0 + 3, status="ready", transcript="два")
        await add_voice(db, tg_id=103, ts=T0 + 6, status="ready", transcript="три")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("что тут сказано?", message_id=200,
                               reply=make_reply(102)),
            query="что тут сказано?")
        assert bundle.kind == "reply"
        assert bundle.primary_ref == "tg:102"
        # Полный исходный текст связанных голосовых — контекст.
        assert bundle.refs == ("tg:101", "tg:102", "tg:103")

    @pytest.mark.asyncio
    async def test_quote_selects_the_quoted_source(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="мы поедем в Казань в июле")
        await add_voice(db, tg_id=102, ts=T0 + 3, status="ready",
                        transcript="билеты уже куплены")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("что он сказал про Казань?",
                               quote="мы поедем в Казань"),
            query="что он сказал про Казань?")
        assert bundle.kind == "quote"
        assert bundle.primary_ref == "tg:101"
        assert bundle.items[0].quote_fragment == "мы поедем в Казань"

    @pytest.mark.asyncio
    async def test_quote_of_text_message_is_not_a_voice_source(self, db):
        await add_message(db, tg_id=100, ts=T0, text="обычный текст про Казань",
                          media_type="text")
        await add_voice(db, tg_id=101, ts=T0 + 3, status="ready",
                        transcript="речь про билеты")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("что тут было?", quote="обычный текст про Казань"),
            query="что тут было?")
        # Цитата текстовой реплики не делает её голосовым source-ref'ом.
        assert bundle is None or "tg:100" not in bundle.refs

    @pytest.mark.asyncio
    async def test_quoted_bot_message_is_not_a_source(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="настоящая речь первого")
        await add_voice(db, tg_id=102, ts=T0 + 3, status="ready",
                        transcript="настоящая речь второго")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("а что там было?", message_id=200,
                               reply=make_reply(150, bot=True),
                               quote="настоящая речь первого"),
            query="а что там было?")
        refs = set(bundle.refs)
        assert "tg:150" not in refs               # цитата бота — не источник
        assert refs == {"tg:101", "tg:102"}       # реальные строки чата
        # Фрагмент нашёлся в РЕАЛЬНОЙ расшифровке — источник честный.
        assert bundle.primary_ref == "tg:101"

    @pytest.mark.asyncio
    async def test_forwarded_voice_keeps_local_ref_and_origin(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="пересланная речь", is_forward=True,
                        forward_source="Канал «Новости»")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в голосовом?"),
            query="что в голосовом?")
        block = vt.render_voice_block(bundle)
        assert 'source="tg:101"' in block
        assert 'forwarded_from="Канал «Новости»"' in block

    @pytest.mark.asyncio
    async def test_cross_chat_voice_is_not_resolved(self, db):
        await add_voice(db, chat_id=OTHER_CHAT, tg_id=101, ts=T0,
                        status="ready", transcript="чужая речь")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в голосовых?"),
            query="что в голосовых?")
        assert bundle is not None
        assert bundle.missing and bundle.kind == "missing"
        assert "чужая речь" not in vt.render_voice_block(bundle)

    @pytest.mark.asyncio
    async def test_plain_question_does_not_claim_voice_group(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready", transcript="речь")
        assert await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("как дела?"),
            query="как дела?") is None


class TestQueryClasses:
    """Дейксис разбирается классами, а не списком готовых фраз."""

    @pytest.mark.parametrize("text", [
        "Что думаешь про верхние голосовые?",
        "разбери эти голосовые",
        "прослушай их",
        "расшифруй первые два голосовых",
        "последние голосовые посмотри",
        "что там в гс?",
        "перескажи аудиосообщения",
    ])
    def test_voice_reference_detected(self, text):
        assert vt.analyze_voice_query(text).references is True

    @pytest.mark.parametrize("text", [
        "как дела?",
        "голосование в партии закончилось",
        "не голосуй за это",
        "купи кружку",
        "эти два фото посмотри",
    ])
    def test_no_false_voice_reference(self, text):
        assert vt.analyze_voice_query(text).references is False

    @pytest.mark.parametrize("text,count,direction", [
        ("первые два голосовых", 2, "earliest"),
        ("последние три голосовых", 3, "latest"),
        ("верхние голосовые", None, "earliest"),
        ("оба голосовых", 2, "all"),
    ])
    def test_order_and_count_classes(self, text, count, direction):
        parsed = vt.analyze_voice_query(text)
        assert parsed.count == count
        assert parsed.direction == direction


# ══════════════════════════════════════════════════════════════════════════
# V-03/V-04: фактическая доставка и честные состояния
# ══════════════════════════════════════════════════════════════════════════

class TestDeliveryStates:
    @pytest.mark.asyncio
    async def test_ready_transcript_text_reaches_payload_block(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="встречаемся в семь у вокзала")
        service = make_service(db)
        bundle = await service._prepare_turn_voice_evidence(
            CHAT_ID, make_query("что он сказал?"), query="что в голосовом?")
        blocks = service._insert_voice_evidence(
            ["<Global_Context>\nфон\n</Global_Context>",
             "<Current_Question>что в голосовом?</Current_Question>"], bundle)
        payload = build_messages("sys", blocks)[1]["content"]
        assert "<voice_transcripts" in payload
        assert 'source="tg:101"' in payload
        assert 'author="Вася"' in payload
        assert "встречаемся в семь у вокзала" in payload
        assert payload.index("<voice_transcripts") < payload.index(
            "<Current_Question>")

    @pytest.mark.asyncio
    async def test_one_failed_one_ready_is_honest(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="готовый текст")
        await add_voice(db, tg_id=102, ts=T0 + 3, status="failed",
                        reason="stt_failed")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("оба голосовых"),
            query="оба голосовых")
        block = vt.render_voice_block(bundle)
        assert "готовый текст" in block
        assert 'status="failed"' in block
        assert "сообщение существует" in block
        assert bundle.summary_status() == vt.TRANSCRIPT_FAILED

    @pytest.mark.asyncio
    async def test_concurrent_stt_completes_during_bounded_wait(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="pending")
        bundle0 = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в голосовом?"),
            query="что в голосовом?")
        assert bundle0.summary_status() == vt.TRANSCRIPT_PENDING

        async def _finish_stt():
            await asyncio.sleep(0.2)
            await db.set_smart_message_transcript(
                CHAT_ID, 101, status="ready", text="речь после гонки")

        task = asyncio.create_task(_finish_stt())
        bundle = await vt.wait_for_voice_bundle(db, bundle0, wait_seconds=2.0)
        await task
        assert bundle.summary_status() == vt.TRANSCRIPT_READY
        assert bundle.items[0].text == "речь после гонки"
        assert bundle.items[0].revision == 1

    @pytest.mark.asyncio
    async def test_unfinished_stt_stays_honest_pending(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="pending")
        bundle = await vt.prepare_voice_evidence(
            db, chat_id=CHAT_ID, message=make_query("что в голосовом?"),
            query="что в голосовом?", wait_seconds=0.2)
        block = vt.render_voice_block(bundle)
        assert 'status="pending"' in block
        assert "ещё идёт" in block
        assert "НЕИЗВЕСТНО" in block
        assert "не было" in block               # запрет ложного отрицания

    @pytest.mark.asyncio
    async def test_restart_between_stt_and_question_keeps_ready_text(self,
                                                                     tmp_path):
        path = str(tmp_path / "restart.db")
        first = DatabaseService(path)
        await first.initialize()
        try:
            await add_voice(first, tg_id=101, ts=T0, status="ready",
                            transcript="речь переживает рестарт")
        finally:
            await first.close()
        second = DatabaseService(path)
        await second.initialize()
        try:
            service = make_service(second)
            bundle = await service._prepare_turn_voice_evidence(
                CHAT_ID, make_query("что в голосовом?"),
                query="что в голосовом?")
            payload = build_messages(
                "sys", service._insert_voice_evidence([], bundle))[1]["content"]
            assert "речь переживает рестарт" in payload
            assert 'revision="1"' in payload
        finally:
            await second.close()

    @pytest.mark.asyncio
    async def test_stale_voice_without_status_is_not_reported_as_in_progress(
            self, db):
        await add_voice(db, tg_id=101, ts=int(time.time()) - 7200)
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в голосовом?"),
            query="что в голосовом?")
        assert bundle.items[0].status == vt.TRANSCRIPT_UNAVAILABLE
        assert bundle.items[0].reason == "no_transcript"
        block = vt.render_voice_block(bundle)
        assert "ещё идёт" not in block

    @pytest.mark.asyncio
    async def test_failed_retry_keeps_previous_transcript_text(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="первая удачная расшифровка")
        # Повторный STT упал: статус терминальный, но прежняя версия — нет.
        await db.set_smart_message_transcript(
            CHAT_ID, 101, status="failed", reason="stt_failed")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в голосовом?"),
            query="что в голосовом?")
        block = vt.render_voice_block(bundle)
        assert "первая удачная расшифровка" in block
        assert "новая попытка: сбой распознавания" in block
        assert bundle.items[0].status == vt.TRANSCRIPT_FAILED

    @pytest.mark.asyncio
    async def test_voice_outside_window_is_not_denied(self, db):
        """Старое голосовое вне окна: «не установлен ряд», а не «их не было»."""
        await add_voice(db, tg_id=95, ts=int(time.time()) - 8 * 3600,
                        status="ready", transcript="старая речь")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("что в голосовых?"),
            query="что в голосовых?")
        assert bundle.missing and bundle.reason == "outside_window"
        block = vt.render_voice_block(bundle)
        assert 'reason="outside_window"' in block
        assert "в чате есть" in block
        assert "Не утверждай, что голосовых не было" in block

    @pytest.mark.asyncio
    async def test_missing_group_does_not_claim_material_absent(self, db):
        await add_message(db, tg_id=100, ts=T0, text="просто текст",
                          media_type="text")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=make_query("верхние голосовые"),
            query="верхние голосовые")
        block = vt.render_voice_block(bundle)
        assert 'status="missing"' in block
        assert "не выдумывай" in block

    @pytest.mark.asyncio
    async def test_voice_without_durable_status_does_not_stall_the_turn(self,
                                                                        db):
        """«Ещё не расшифровано» без запущенного STT не ждёт 8 секунд:
        ждём только durable `pending` (реально идущее распознавание)."""
        await add_voice(db, tg_id=101, ts=T0)
        started = time.monotonic()
        bundle = await vt.prepare_voice_evidence(
            db, chat_id=CHAT_ID, message=make_query("что в голосовом?"),
            query="что в голосовом?")
        assert time.monotonic() - started < 1.0
        assert bundle.summary_status() == vt.TRANSCRIPT_PENDING
        assert bundle.items[0].in_flight is False

    @pytest.mark.asyncio
    async def test_reply_target_older_than_window_is_still_delivered(self, db):
        await add_voice(db, tg_id=90, ts=int(time.time()) - 7200,
                        status="ready", transcript="вчерашняя речь")
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=make_query("что тут сказано?", reply=make_reply(90)),
            query="что тут сказано?")
        assert bundle.kind == "reply"
        assert bundle.refs == ("tg:90",)
        assert "вчерашняя речь" in vt.render_voice_block(bundle)

    @pytest.mark.asyncio
    async def test_refresh_applies_revision_before_writer(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="pending")
        service = make_service(db)
        bundle = await service._prepare_turn_voice_evidence(
            CHAT_ID, make_query("что в голосовом?"), query="что в голосовом?")
        blocks = service._insert_voice_evidence(
            ["<Current_Question>что в голосовом?</Current_Question>"], bundle)
        assert "ещё идёт" in "\n".join(blocks)
        # STT завершился между снимком контекста и финальной сборкой payload.
        await db.set_smart_message_transcript(
            CHAT_ID, 101, status="ready", text="поздний, но реальный текст")
        blocks = await service._refresh_turn_voice_evidence(bundle, blocks)
        payload = build_messages("sys", blocks)[1]["content"]
        assert "поздний, но реальный текст" in payload
        assert "ещё идёт" not in payload
        # Блок не задвоен.
        assert payload.count("<voice_transcripts") == 1

    @pytest.mark.asyncio
    async def test_requested_voice_outranks_background_in_tight_window(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="важная речь")
        await add_voice(db, tg_id=102, ts=T0 + 2, status="ready",
                        transcript="ещё одна важная речь")
        service = make_service(db)
        bundle = await service._prepare_turn_voice_evidence(
            CHAT_ID, make_query("что в голосовых?"), query="что в голосовых?")
        background = ("<Global_Context>\n" + ("фон " * 500)
                      + "\n</Global_Context>")
        blocks = [background,
                  "<Current_Question>что в голосовых?</Current_Question>"]
        before = list(blocks)
        blocks = service._insert_voice_evidence(blocks, bundle)
        payload = build_messages("sys", blocks)[1]["content"]
        assert "важная речь" in payload and "ещё одна важная речь" in payload
        # История источников не переписана: фон остался байт-в-байт.
        assert background in payload
        assert before[0] == background

    @pytest.mark.asyncio
    async def test_long_transcript_is_delivered_without_silent_cut(self, db):
        long_text = "длинная речь " * 300          # ~3900 символов
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript=long_text)
        service = make_service(db)
        bundle = await service._prepare_turn_voice_evidence(
            CHAT_ID, make_query("что в голосовом?"), query="что в голосовом?")
        payload = build_messages(
            "sys", service._insert_voice_evidence([], bundle))[1]["content"]
        assert long_text.strip() in payload

    @pytest.mark.asyncio
    async def test_truncated_window_still_delivers_requested_voice(self, db):
        await add_voice(db, tg_id=101, ts=T0, status="ready",
                        transcript="текст из усечённого окна")
        service = make_service(db)
        bundle = await service._prepare_turn_voice_evidence(
            CHAT_ID, make_query("что в голосовом?"), query="что в голосовом?")
        truncated = (
            '<chat_context note="болтовня">\n'
            "…часть окна не показана (5)\n"
            "[медиа: voice tg:101]\n</chat_context>")
        blocks = service._insert_voice_evidence(
            [truncated, "<Current_Question>что в голосовом?</Current_Question>"],
            bundle)
        payload = build_messages("sys", blocks)[1]["content"]
        assert "текст из усечённого окна" in payload
        assert "часть окна не показана" in payload


# ══════════════════════════════════════════════════════════════════════════
# STT-хендлер: статусы версии (сквозная трасса V-01/V-04)
# ══════════════════════════════════════════════════════════════════════════

class TestHandlerStatuses:
    @pytest.mark.asyncio
    async def test_failed_stt_records_terminal_status(self, db, monkeypatch):
        from handlers import voice_transcription as hvt
        from SmartModule.service import TranscriptionUnavailable

        old = (hvt._service, hvt._db, hvt._aliases, hvt._memory, hvt._bot_id)
        service = MagicMock()
        service.transcribe_voice = AsyncMock(
            side_effect=TranscriptionUnavailable("boom"))
        aliases = MagicMock()
        aliases.resolve = MagicMock(side_effect=lambda uid, nickname=None,
                                    username=None: nickname or "Вася")
        hvt.setup_voice_transcription(service, db, aliases, None, bot_id=BOT_ID)
        try:
            await add_voice(db, tg_id=601)

            async def _noop(*_a, **_kw):
                return None

            msg = SimpleNamespace(
                message_id=601, text=None, caption=None,
                chat=SimpleNamespace(id=CHAT_ID),
                from_user=SimpleNamespace(id=USER_A, first_name="Вася",
                                          last_name=None, username="vasya"),
                voice=SimpleNamespace(duration=5, file_id="f1"),
                video_note=None, forward_origin=None)
            msg.reply = _noop
            bot = MagicMock()
            bot.send_chat_action = _noop

            async def _fake_fetch(_bot, _media, path):
                with open(path, "wb") as handle:
                    handle.write(b"data")
            monkeypatch.setattr(hvt, "_fetch_media_to_tmp", _fake_fetch)
            ok = await hvt.transcribe_media_message(msg, bot)
            assert ok is False
            row = await db.get_smart_message_by_tg_id(CHAT_ID, 601)
            assert row["transcript_status"] == "failed"
            assert row["transcript_reason"] == "stt_failed"
        finally:
            hvt._service, hvt._db, hvt._aliases, hvt._memory, hvt._bot_id = old

    @pytest.mark.asyncio
    async def test_success_stores_ready_version_of_same_row(self, db,
                                                            monkeypatch):
        from handlers import voice_transcription as hvt

        old = (hvt._service, hvt._db, hvt._aliases, hvt._memory, hvt._bot_id)
        service = MagicMock()
        service.transcribe_voice = AsyncMock(return_value="распознанная речь")
        aliases = MagicMock()
        aliases.resolve = MagicMock(side_effect=lambda uid, nickname=None,
                                    username=None: nickname or "Вася")
        hvt.setup_voice_transcription(service, db, aliases, None, bot_id=BOT_ID)
        try:
            await add_voice(db, tg_id=602)

            async def _noop(*_a, **_kw):
                return None

            msg = SimpleNamespace(
                message_id=602, text=None, caption=None,
                chat=SimpleNamespace(id=CHAT_ID),
                from_user=SimpleNamespace(id=USER_A, first_name="Вася",
                                          last_name=None, username="vasya"),
                voice=SimpleNamespace(duration=5, file_id="f1"),
                video_note=None, forward_origin=None)
            msg.reply = _noop

            async def _fake_fetch(_bot, _media, path):
                with open(path, "wb") as handle:
                    handle.write(b"data")
            monkeypatch.setattr(hvt, "_fetch_media_to_tmp", _fake_fetch)
            ok = await hvt.transcribe_media_message(msg, MagicMock())
            assert ok is True
            row = await db.get_smart_message_by_tg_id(CHAT_ID, 602)
            assert row["text"] == "распознанная речь"
            assert row["transcript_status"] == "ready"
            assert row["transcript_revision"] == 1
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
                (CHAT_ID,))
            assert (await cursor.fetchone())["n"] == 1
        finally:
            hvt._service, hvt._db, hvt._aliases, hvt._memory, hvt._bot_id = old
