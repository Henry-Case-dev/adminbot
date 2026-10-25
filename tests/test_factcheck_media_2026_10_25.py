"""P0-FACTCHECK MEDIA (owner 25.10.2026 §1–§9) — регрессия 15 случаев.

Проверяется ВХОД пайплайна, а не только финальная фраза: какие message_id
альбома прочитаны, какой текст/подпись/OCR/описание дошли до check_claim и
check_claim_envelope, что попало в ответ как честная оговорка.

Сеть/Telegram/LLM не используются: Vision-контур подменяется на уровне
`mca_vision.render_media_context_async` (реальный `load_claim_media` и
реальный резолвер публикации), БД — либо фейк, либо настоящий
`DatabaseService` во временной папке.
"""
import pytest
from aiogram.types import Chat, MessageOriginChannel
from unittest.mock import AsyncMock, MagicMock

import datetime

import handlers.factcheck as fh
from services import mca_vision
from services import temporal_factcheck as tf
from services.message_identity import save_live_message
from services.smartmodule_phrases import (
    FACTCHECK_CONTEXT_EMPTY_PHRASES,
    FACTCHECK_CONTEXT_ERROR_PHRASES,
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_IMAGE_NO_CLAIM_PHRASES,
    FACTCHECK_IMAGE_PENDING_PHRASES,
    FACTCHECK_MEDIA_ERROR_PHRASES,
)
from services.factcheck_service import load_claim_media

CHAT_ID = -1001234567890

# Элементы «пересланной публикации с несколькими изображениями и длинным
# текстом» (сценарий PERMsoc): caption только на ОДНОМ элементе.
ALBUM_ID = "album-permsoc-1"
CAPTION = ("⚡️ В Telegram добавили ИИ-агентов: Claude и ChatGPT подключены "
           "через API.\nФункция появилась в сборке 283365 на macOS 13.1.0.")


# ── Двойники ────────────────────────────────────────────────────────────────

class FakeDb:
    """Минимальный durable-слой: строки smart_messages по (chat, tg) и группе."""

    def __init__(self, rows_by_tg=None, group_rows=None, reply_rows=None, *,
                 around_rows=None, fail_group=False, fail_target=False):
        self.rows_by_tg = {int(k): v for k, v in (rows_by_tg or {}).items()}
        self.group_rows = {k: list(v) for k, v in (group_rows or {}).items()}
        self.reply_rows = {int(k): list(v)
                           for k, v in (reply_rows or {}).items()}
        self.around_rows = list(around_rows) if around_rows is not None else []
        self.fail_group = fail_group
        self.fail_target = fail_target
        self.calls = []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        self.calls.append(("target", int(chat_id), int(tg)))
        if self.fail_target:
            raise RuntimeError("db target boom")
        return self.rows_by_tg.get(int(tg))

    async def get_smart_messages_by_media_group(self, chat_id, mgid):
        self.calls.append(("group", int(chat_id), str(mgid)))
        if self.fail_group:
            raise RuntimeError("db group boom")
        return list(self.group_rows.get(str(mgid), []))

    async def get_smart_messages_reply_to(self, chat_id, reply_to_id, *,
                                          media_only=False, limit=10):
        self.calls.append(("reply", int(chat_id), int(reply_to_id)))
        rows = list(self.reply_rows.get(int(reply_to_id), []))
        if media_only:
            rows = [r for r in rows if r.get("media_group_id")]
        return rows[:int(limit)]

    async def get_messages_around(self, chat_id, target_tg_message_id,
                                  before, after):
        self.calls.append(("around", int(chat_id), target_tg_message_id,
                           int(before), int(after)))
        return list(self.around_rows)

    async def get_recent_messages(self, chat_id, limit):
        self.calls.append(("recent", int(chat_id), int(limit)))
        return list(self.around_rows[-int(limit):]) if limit else []


def _row(tg, *, caption=None, text=None, media_type="photo", mgid=ALBUM_ID,
         forward_source=None, origin_display_name=None, reply_to_id=None):
    return {
        "chat_id": CHAT_ID, "tg_message_id": tg, "caption": caption,
        "text": text, "media_type": media_type, "media_group_id": mgid,
        "forward_source": forward_source,
        "origin_display_name": origin_display_name,
        "reply_to_id": reply_to_id,
    }


def _win(tg, text, *, author="Вася", reply_to_id=None, chat_id=CHAT_ID,
         media_type="text", caption=None):
    """Строка окна wide-context (поля get_messages_around)."""
    return {
        "id": tg, "chat_id": chat_id, "tg_message_id": tg, "text": text,
        "caption": caption, "reply_to_id": reply_to_id,
        "timestamp": 1792200000 + tg, "media_type": media_type,
        "author_name": author, "is_forward": False, "forward_source": None,
    }


def _album_rows(caption_tg=71):
    return [
        _row(71, caption=CAPTION if caption_tg == 71 else None),
        _row(72, caption=CAPTION if caption_tg == 72 else None),
        _row(73, caption=CAPTION if caption_tg == 73 else None),
    ]


def _make_msg(text=None, caption=None, message_id=1, user_id=1,
              reply_to_message=None, forward_origin=None,
              media_group_id=None, photo=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply_to_message = reply_to_message
    msg.forward_origin = forward_origin
    msg.media_group_id = media_group_id
    msg.photo = list(photo) if photo else None
    msg.document = None
    msg.sticker = None
    return msg


def _channel_origin(title="Канал X", username="channelx", signature="Подпись"):
    return MessageOriginChannel(
        date=datetime.datetime.now(),
        chat=Chat(id=-777, type="channel", title=title, username=username),
        message_id=5,
        author_signature=signature,
    )


def _analysis(caption=None, ocr=(), desc=(), pending=False):
    return {
        "caption": caption,
        "untrusted_ocr_texts": list(ocr),
        "visual_descriptions": list(desc),
        "lines": (["изображение, содержание ещё не распознано"]
                  if pending else []),
        "knowledge_time": None if pending else 1792200000,
    }


def _render(payloads, *, fail_ids=(), calls=None):
    async def render(db, *, chat_id, tg_message_id):
        if calls is not None:
            calls.append(int(tg_message_id))
        if int(tg_message_id) in fail_ids:
            raise RuntimeError("vision provider down")
        return payloads.get(int(tg_message_id))
    return render


class _NullCtx:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeCache:
    """Герметичный SmartCache-двойник (без общего диска/БД)."""

    def __init__(self):
        self.store = {}
        self.markers = {}

    def build_key(self, slug, raw):
        return f"{slug}:{raw}"

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.markers.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.markers[key] = payload


@pytest.fixture
def handler_env(monkeypatch):
    """Хендлер без сети/БД-троттлинга: легаси-путь по умолчанию."""
    pool = MagicMock()
    permit = MagicMock()
    permit.release = lambda: None
    pool.try_acquire = AsyncMock(return_value=permit)
    monkeypatch.setattr(fh, "get_smartmodule_concurrency_pool", lambda: pool)
    monkeypatch.setattr(fh, "typing_active", lambda bot, chat: _NullCtx())
    monkeypatch.setattr(fh, "cooldown_remaining", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "cooldown_touch", AsyncMock())
    monkeypatch.setattr(fh, "_cp_g", AsyncMock(return_value="contextual"))
    monkeypatch.setattr(fh, "_fetch_context_with_gate",
                        AsyncMock(return_value=("", None)))
    monkeypatch.setattr(fh, "send_chunked_reply", AsyncMock())
    monkeypatch.setattr(fh, "_reply", AsyncMock())
    monkeypatch.setattr(fh, "react_moai", AsyncMock())
    monkeypatch.setattr(fh, "_temporal_on", lambda: False)
    monkeypatch.setattr(fh, "get_smart_cache", lambda: _FakeCache())
    yield fh
    fh._service = None
    fh._db = None


def _service(verdict="вердикт: проверено"):
    service = MagicMock()
    service.check_claim = AsyncMock(return_value=verdict)
    return service


async def _run(handler_env, service, db, target, *, text="фактчек",
               message_id=11):
    handler_env.setup_factcheck(service, db)
    msg = _make_msg(text=text, message_id=message_id,
                    reply_to_message=target)
    bot = AsyncMock()
    await handler_env.factcheck_handler(msg, bot=bot)
    return bot


def _claim_text(service) -> str:
    return service.check_claim.await_args.args[0]


def _sent_text(handler_env) -> str:
    return handler_env.send_chunked_reply.await_args.args[2]


def _reply_text(handler_env) -> str:
    return handler_env._reply.await_args.args[2]


# ── 1. Текстовый фактчек без изображений ────────────────────────────────────

class TestTextOnlyUnchanged:
    @pytest.mark.asyncio
    async def test_text_only_factcheck_input_unchanged(self, handler_env,
                                                       monkeypatch):
        calls = []
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}, calls=calls))
        service = _service()
        target = _make_msg(text="Земля плоская", message_id=77)
        await _run(handler_env, service, FakeDb(), target)
        service.check_claim.assert_awaited_once_with(
            "Земля плоская", None, None, chat_id=CHAT_ID, chat_context=None)
        assert _sent_text(handler_env) == "вердикт: проверено"
        assert calls == [77]          # медиа-шов существует, но материалов нет

    @pytest.mark.asyncio
    async def test_cache_hit_notice_free_for_text(self, handler_env,
                                                  monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        cache = _FakeCache()
        cache.store["factcheck:тезис"] = "старый вердикт"
        monkeypatch.setattr(fh, "get_smart_cache", lambda: cache)
        target = _make_msg(text="тезис", message_id=77)
        await _run(handler_env, service, FakeDb(), target)
        service.check_claim.assert_not_awaited()
        handler_env._reply.assert_awaited_once()
        assert handler_env._reply.await_args.args[2] == "старый вердикт"


# ── 2-4. Одиночные изображения ──────────────────────────────────────────────

class TestSingleImage:
    @pytest.mark.asyncio
    async def test_photo_with_caption_and_ocr(self, handler_env, monkeypatch):
        caption = "В сборке 283365 убрали старый API"
        payloads = {77: _analysis(caption=caption,
                                  ocr=["Сборка 283365 · macOS 13.1.0"])}
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads))
        service = _service()
        target = _make_msg(caption=caption, message_id=77,
                           photo=[object()])
        db = FakeDb(rows_by_tg={77: _row(77, caption=caption, mgid=None)})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert caption in claim                 # подпись не потеряна
        assert "283365" in claim                # OCR дошёл до тезиса
        assert "macos" in claim.lower()
        assert "не слова автора" in claim

    @pytest.mark.asyncio
    async def test_photo_without_caption_uses_ocr_not_empty(self, handler_env,
                                                            monkeypatch):
        payloads = {77: _analysis(
            ocr=["Версия 2.58.130 вышла 25.10.2026"])}
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads))
        service = _service()
        target = _make_msg(message_id=77, photo=[object()])
        db = FakeDb(rows_by_tg={77: _row(77, mgid=None)})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)             # пайплайн ЗАПУЩЕН
        assert "2.58.130" in claim
        assert claim.startswith("Текст с изображения")
        handler_env._reply.assert_not_awaited()  # пустой фразы НЕ было
        assert _sent_text(handler_env) == "вердикт: проверено"

    @pytest.mark.asyncio
    async def test_screenshot_multiple_text_blocks(self, handler_env,
                                                   monkeypatch):
        payloads = {77: _analysis(ocr=[
            "Заголовок: «Telegram запустил агентов»",
            "Дата публикации: 01.09.2026",
        ], desc=["скриншот новостной заметки"])}
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads))
        service = _service()
        target = _make_msg(message_id=77, photo=[object()])
        db = FakeDb(rows_by_tg={77: _row(77, mgid=None)})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert "агентов" in claim and "01.09.2026" in claim
        assert "Визуальное описание изображения" in claim
        assert "не доказывает подлинность" in claim


# ── 5-8. Альбомы: любой элемент, caption на любом элементе ──────────────────

class TestAlbumResolution:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("target_id", [71, 72, 73])
    async def test_reply_to_any_element_reads_whole_publication(
            self, handler_env, monkeypatch, target_id):
        calls = []
        payloads = {71: _analysis(ocr=["блок 1"]),
                    72: _analysis(ocr=["блок 2"]),
                    73: _analysis(ocr=["блок 3"])}
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads, calls=calls))
        service = _service()
        target = _make_msg(message_id=target_id, media_group_id=ALBUM_ID)
        db = FakeDb(rows_by_tg={r["tg_message_id"]: r
                                for r in _album_rows(caption_tg=71)},
                    group_rows={ALBUM_ID: _album_rows(caption_tg=71)})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert CAPTION.split(".")[0] in claim     # подпись первого элемента
        assert "блок 1" in claim and "блок 3" in claim
        assert calls == [71, 72, 73]              # ВСЕ элементы группы
        assert handler_env.send_chunked_reply.await_args.args[3] == target_id
        assert ("group", CHAT_ID, ALBUM_ID) in db.calls

    @pytest.mark.asyncio
    async def test_caption_on_non_first_element(self, handler_env,
                                                monkeypatch):
        calls = []
        monkeypatch.setattr(
            mca_vision, "render_media_context_async",
            _render({71: _analysis(ocr=["первое фото"]),
                     72: _analysis(ocr=["второе фото"]),
                     73: _analysis(ocr=["третье фото"])}, calls=calls))
        service = _service()
        target = _make_msg(message_id=73, media_group_id=ALBUM_ID)
        rows = _album_rows(caption_tg=72)
        db = FakeDb(rows_by_tg={r["tg_message_id"]: r for r in rows},
                    group_rows={ALBUM_ID: rows})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert "283365" in claim                  # caption со 2-го элемента
        assert calls == [71, 72, 73]

    @pytest.mark.asyncio
    async def test_album_does_not_merge_neighbour_messages(self, handler_env,
                                                           monkeypatch):
        calls = []
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({71: _analysis(), 72: _analysis(),
                                     73: _analysis()}, calls=calls))
        service = _service()
        target = _make_msg(message_id=72, media_group_id=ALBUM_ID)
        rows = _album_rows(caption_tg=71)
        neighbour = _row(99, text="соседнее сообщение вне альбома",
                         mgid=None)
        db = FakeDb(rows_by_tg={99: neighbour}, group_rows={
            ALBUM_ID: rows, "other-album": [_row(55, text="чужой альбом")]})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert "соседнее" not in claim and "чужой альбом" not in claim
        assert calls == [71, 72, 73]
        assert ("group", CHAT_ID, ALBUM_ID) in db.calls

    @pytest.mark.asyncio
    async def test_album_with_missing_element_is_partial(self, handler_env,
                                                         monkeypatch):
        """Элемент 72 без активов (данные недоступны) — честная оговорка."""
        payloads = {71: _analysis(), 73: _analysis()}
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads))
        service = _service()
        target = _make_msg(message_id=73, media_group_id=ALBUM_ID)
        rows = _album_rows(caption_tg=71)
        db = FakeDb(rows_by_tg={r["tg_message_id"]: r for r in rows},
                    group_rows={ALBUM_ID: rows})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert "283365" in claim                  # данные использованы
        sent = _sent_text(handler_env)
        assert "Не все изображения публикации удалось прочитать" in sent
        assert "Не все изображения" not in claim  # оговорка НЕ в тезисе

    @pytest.mark.asyncio
    async def test_album_group_read_failure_no_caption_is_technical(
            self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        target = _make_msg(message_id=73, media_group_id=ALBUM_ID,
                           photo=[object()])
        db = FakeDb(rows_by_tg={}, fail_group=True)
        await _run(handler_env, service, db, target)
        service.check_claim.assert_not_awaited()
        phrase = _reply_text(handler_env)
        assert phrase in FACTCHECK_MEDIA_ERROR_PHRASES
        assert phrase not in FACTCHECK_EMPTY_CONTEXT_PHRASES

    @pytest.mark.asyncio
    async def test_album_group_read_failure_keeps_buffer_caption(
            self, handler_env, monkeypatch):
        """Сбой чтения группы + caption в in-memory буфере → проверяем текст,
        честно помечая неполноту альбома."""
        from services import media_group_buffer as mgb

        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({73: _analysis()}))
        mgb.record_media_group_message(_make_msg(
            caption="буферная подпись альбома", message_id=71,
            media_group_id="album-buffer"))
        try:
            service = _service()
            target = _make_msg(message_id=73, media_group_id="album-buffer",
                               photo=[object()])
            db = FakeDb(rows_by_tg={}, fail_group=True)
            await _run(handler_env, service, db, target)
            claim = _claim_text(service)
            assert "буферная подпись" in claim
            assert "прочитаны не полностью" in _sent_text(handler_env)
        finally:
            mgb._buffer.clear()


# ── 9-10. Пересланные публикации ────────────────────────────────────────────

class TestForwardedPublication:
    @pytest.mark.asyncio
    async def test_forwarded_album_keeps_caption_images_and_source(
            self, handler_env, monkeypatch):
        calls = []
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({71: _analysis(ocr=["фото 1"]),
                                     72: _analysis(ocr=["фото 2"])},
                                    calls=calls))
        service = _service()
        target = _make_msg(message_id=72, media_group_id=ALBUM_ID,
                           forward_origin=_channel_origin())
        rows = [_row(71, caption=CAPTION), _row(72)]
        db = FakeDb(rows_by_tg={71: rows[0], 72: rows[1]},
                    group_rows={ALBUM_ID: rows})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert CAPTION in claim and "фактчек" not in claim
        assert calls == [71, 72]
        assert service.check_claim.await_args.args[2] == \
            "Канал X @channelx Подпись"

    @pytest.mark.asyncio
    async def test_forwarded_album_source_falls_back_to_stored_row(
            self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({71: _analysis(), 72: _analysis()}))
        service = _service()
        target = _make_msg(message_id=72, media_group_id=ALBUM_ID)
        rows = [_row(71, caption=CAPTION, forward_source="Канал X"),
                _row(72, forward_source="Канал X")]
        db = FakeDb(rows_by_tg={71: rows[0], 72: rows[1]},
                    group_rows={ALBUM_ID: rows})
        await _run(handler_env, service, db, target)
        assert service.check_claim.await_args.args[2] == "Канал X"

    @pytest.mark.asyncio
    async def test_forwarded_single_photo_without_caption(self, handler_env,
                                                          monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({77: _analysis(ocr=["заголовок с фото"])}))
        service = _service()
        target = _make_msg(message_id=77, photo=[object()],
                           forward_origin=_channel_origin())
        db = FakeDb(rows_by_tg={77: _row(77, mgid=None,
                                         forward_source="Канал X")})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert "заголовок с фото" in claim
        assert service.check_claim.await_args.args[2] == \
            "Канал X @channelx Подпись"


# ── 11-14. Технические исходы и «нет утверждения» ───────────────────────────

class TestMediaFailureSemantics:
    @pytest.mark.asyncio
    async def test_vision_error_without_text_is_technical_not_empty(
            self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}, fail_ids={77}))
        service = _service()
        target = _make_msg(message_id=77, photo=[object()])
        db = FakeDb(rows_by_tg={77: _row(77, mgid=None)})
        await _run(handler_env, service, db, target)
        service.check_claim.assert_not_awaited()
        phrase = _reply_text(handler_env)
        assert phrase in FACTCHECK_MEDIA_ERROR_PHRASES
        assert phrase not in FACTCHECK_EMPTY_CONTEXT_PHRASES

    @pytest.mark.asyncio
    async def test_vision_unavailable_with_caption_still_checks_text(
            self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}, fail_ids={77}))
        service = _service()
        caption = "Утверждение из подписи"
        target = _make_msg(caption=caption, message_id=77, photo=[object()])
        db = FakeDb(rows_by_tg={77: _row(77, caption=caption, mgid=None)})
        await _run(handler_env, service, db, target)
        assert _claim_text(service) == caption     # техническая недоступность
        sent = _sent_text(handler_env)
        assert sent.startswith("вердикт: проверено")
        assert "не удалось прочитать" in sent      # честная оговорка
        assert "не удалось прочитать" not in _claim_text(service)

    @pytest.mark.asyncio
    async def test_image_without_verifiable_claim_checks_context(
            self, handler_env, monkeypatch):
        """Уточнение №2: «на картинке нет тезиса» ещё не приговор —
        окружение проверено, и отказ называет окно."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({77: _analysis()}))
        service = _service()
        target = _make_msg(message_id=77, photo=[object()])
        window = [_win(74, "просто болтовня без фактов"),
                  _win(75, "и ещё одна реплика"), _win(76, "ага")]
        db = FakeDb(rows_by_tg={77: _row(77, mgid=None)},
                    around_rows=window)
        await _run(handler_env, service, db, target)
        service.check_claim.assert_not_awaited()
        phrase = _reply_text(handler_env)
        candidates = [p.format(scope="цель с изображением",
                               scope_of="цели с изображением",
                               window=len(window))
                      for p in FACTCHECK_CONTEXT_EMPTY_PHRASES]
        assert phrase in candidates
        assert phrase not in FACTCHECK_EMPTY_CONTEXT_PHRASES
        assert phrase not in FACTCHECK_IMAGE_NO_CLAIM_PHRASES
        assert str(len(window)) in phrase

    @pytest.mark.asyncio
    async def test_image_pending_is_honest_pending(self, handler_env,
                                                   monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({77: _analysis(pending=True)}))
        service = _service()
        target = _make_msg(message_id=77, photo=[object()])
        db = FakeDb(rows_by_tg={77: _row(77, mgid=None)})
        await _run(handler_env, service, db, target)
        service.check_claim.assert_not_awaited()
        phrase = _reply_text(handler_env)
        assert phrase in FACTCHECK_IMAGE_PENDING_PHRASES
        assert phrase not in FACTCHECK_EMPTY_CONTEXT_PHRASES

    @pytest.mark.asyncio
    async def test_truly_nothing_refusal_names_checked_window(
            self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        target = _make_msg(message_id=77)
        window = [_win(74, "просто болтовня без фактов"),
                  _win(75, "и ещё одна реплика"), _win(76, "ага")]
        db = FakeDb(rows_by_tg={77: _row(77, text=None, media_type="text",
                                         mgid=None)},
                    around_rows=window)
        await _run(handler_env, service, db, target)
        service.check_claim.assert_not_awaited()
        phrase = _reply_text(handler_env)
        assert phrase not in FACTCHECK_EMPTY_CONTEXT_PHRASES
        candidates = [p.format(scope="цель", scope_of="цели",
                               window=len(window))
                      for p in FACTCHECK_CONTEXT_EMPTY_PHRASES]
        assert phrase in candidates
        assert str(len(window)) in phrase

    @pytest.mark.asyncio
    async def test_context_unreadable_is_technical_not_empty(
            self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))

        class _BrokenDb(FakeDb):
            async def get_messages_around(self, *a, **kw):
                raise RuntimeError("db boom")

        service = _service()
        target = _make_msg(message_id=77)
        db = _BrokenDb(rows_by_tg={77: _row(77, text=None,
                                            media_type="text", mgid=None)})
        await _run(handler_env, service, db, target)
        service.check_claim.assert_not_awaited()
        assert _reply_text(handler_env) in FACTCHECK_CONTEXT_ERROR_PHRASES

    @pytest.mark.asyncio
    async def test_repost_variant_caption_command_is_not_a_claim(
            self, handler_env, monkeypatch):
        """Репост-вариант (D121): caption «фактчек» — команда, не публикация."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({77: _analysis()}))
        service = _service()
        window = [_win(74, "обычная болтовня"), _win(75, "ага")]
        db = FakeDb(rows_by_tg={77: _row(77, caption="фактчек", mgid=None)},
                    around_rows=window)
        handler_env.setup_factcheck(service, db)
        msg = _make_msg(caption="фактчек", message_id=77,
                        forward_origin=_channel_origin(), photo=[object()])
        await handler_env.factcheck_handler(msg, bot=AsyncMock())
        service.check_claim.assert_not_awaited()
        phrase = _reply_text(handler_env)
        assert phrase not in FACTCHECK_EMPTY_CONTEXT_PHRASES
        candidates = [p.format(scope="цель с изображением",
                               scope_of="цели с изображением",
                               window=len(window))
                      for p in FACTCHECK_CONTEXT_EMPTY_PHRASES]
        assert phrase in candidates


# ── 15. Текст и изображения, которые его не подтверждают ────────────────────

class TestTextAndContradictingImage:
    @pytest.mark.asyncio
    async def test_claim_carries_text_and_image_material_separately(
            self, handler_env, monkeypatch):
        caption = "На фото видно, что мост обрушился вчера"
        monkeypatch.setattr(
            mca_vision, "render_media_context_async",
            _render({77: _analysis(
                caption=caption,
                ocr=["Павильонная съёмка, 2019 год"],
                desc=["постановочный кадр со старой датой"])}))
        service = _service()
        target = _make_msg(caption=caption, message_id=77, photo=[object()])
        db = FakeDb(rows_by_tg={77: _row(77, caption=caption, mgid=None)})
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert caption in claim                    # слова автора
        assert "Павильонная съёмка" in claim       # данные изображения
        assert "постановочный кадр" in claim       # результат модели
        assert "не доказывает подлинность" in claim
        # вердикт — от сервиса, без выдуманных «просмотренных сайтов»
        assert _sent_text(handler_env) == "вердикт: проверено"


# ── Envelope-путь: собранный текст доходит до claim_text ────────────────────

class TestTemporalEnvelopeUsesPublication:
    @pytest.mark.asyncio
    async def test_album_caption_reaches_envelope_claim_text(
            self, handler_env, monkeypatch, tmp_path):
        from services.database import DatabaseService

        monkeypatch.setattr(fh, "_temporal_on", lambda: True)
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({71: _analysis(ocr=["фото 1"]),
                                     72: _analysis(ocr=["фото 2"])}))
        db = DatabaseService(str(tmp_path / "fcmedia.db"))
        await db.initialize()
        rows = [_row(71, caption=CAPTION), _row(72)]
        for row in rows:
            await save_live_message(
                db, chat_id=CHAT_ID, user_id=1, caption=row["caption"],
                timestamp=1792200000, sent_at=1792200000,
                media_type="photo", tg_message_id=row["tg_message_id"],
                media_group_id=ALBUM_ID)
        envelope_row = {
            "chat_id": CHAT_ID, "tg_message_id": 72, "text": None,
            "caption": None, "sent_at": 1792200000, "content_hash": "h",
            "current_revision": 1, "origin_type": None,
            "origin_sent_at": None, "origin_sender_user_id": None,
            "origin_chat_id": None, "origin_display_name": None,
            "author_name": "Вася", "forward_source": None,
        }

        async def _origin_block(chat_id, tg):
            return dict(envelope_row)

        db.get_smart_message_origin_block = _origin_block
        captured = {}

        async def _check_envelope(env, **kw):
            captured["claim_text"] = env.claim_text
            return tf.TemporalRunResult(
                envelope=env,
                verdict=tf.verdict_from_payload(
                    {"factual_verdict": "insufficient_evidence",
                     "temporal_status": "unknown"}, env),
                verdict_text="проверено: данных мало")

        service = MagicMock()
        service.check_claim_envelope = AsyncMock(side_effect=_check_envelope)
        target = _make_msg(message_id=72, media_group_id=ALBUM_ID)
        try:
            await _run(handler_env, service, db, target)
        finally:
            await db.close()
        assert "283365" in captured["claim_text"]      # caption в envelope
        assert "фото 1" in captured["claim_text"]      # OCR всех элементов
        await_text = handler_env.send_chunked_reply.await_args
        assert await_text.args[2].startswith("проверено: данных мало")
        assert await_text.args[3] == 72


# ── Уточнение владельца 25.10.2026: вся публикация, reply — точка входа ─────

POST_TEXT = ("Большой пост: 10 фотографий со стройки и длинный текст о том, "
             "что объект сдан в эксплуатацию 12.10.2026.")


class TestOwnerClarification2026_10_25:
    @pytest.mark.asyncio
    async def test_reply_to_text_part_covers_whole_post(self, handler_env,
                                                        monkeypatch):
        """Ответ на ТЕКСТОВУЮ часть поста = тот же охват, что ответ на фото."""
        calls = []
        payloads = {201: _analysis(ocr=["фото 1"]),
                    202: _analysis(ocr=["фото 2"]),
                    203: _analysis(ocr=["фото 3"])}
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads, calls=calls))
        service = _service()
        rows = [_row(201, caption="Подпись публикации", reply_to_id=200),
                _row(202, reply_to_id=200), _row(203, reply_to_id=200)]
        db = FakeDb(rows_by_tg={200: _row(200, text=POST_TEXT,
                                          media_type="text", mgid=None),
                                201: rows[0], 202: rows[1], 203: rows[2]},
                    group_rows={ALBUM_ID: rows},
                    reply_rows={200: rows})
        target = _make_msg(text=POST_TEXT, message_id=200)
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert POST_TEXT in claim                 # текст поста
        assert "Подпись публикации" in claim      # подпись элемента альбома
        assert "фото 1" in claim and "фото 3" in claim
        assert calls == [200, 201, 202, 203]      # все изображения поста
        assert ("reply", CHAT_ID, 200) in db.calls
        assert handler_env.send_chunked_reply.await_args.args[3] == 200

    @pytest.mark.asyncio
    async def test_post_text_as_separate_message_next_to_album(
            self, handler_env, monkeypatch):
        """Текст поста — отдельное сообщение, на которое отвечает альбом."""
        calls = []
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({201: _analysis(ocr=["фото 1"]),
                                     202: _analysis(ocr=["фото 2"])},
                                    calls=calls))
        service = _service()
        rows = [_row(201, text=None, caption=None, reply_to_id=300),
                _row(202, text=None, caption=None, reply_to_id=300)]
        db = FakeDb(rows_by_tg={300: _row(300, text=POST_TEXT,
                                          media_type="text", mgid=None),
                                201: rows[0], 202: rows[1]},
                    group_rows={ALBUM_ID: rows})
        target = _make_msg(message_id=202, media_group_id=ALBUM_ID,
                           photo=[object()])
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert POST_TEXT in claim                 # текст отдельного сообщения
        assert "фото 1" in claim and "фото 2" in claim  # все фото, не только цель
        assert calls == [201, 202]
        assert "нечего проверять" not in _sent_text(handler_env)

    @pytest.mark.asyncio
    async def test_parent_text_included_but_neighbours_not_merged(
            self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({201: _analysis(), 202: _analysis()}))
        service = _service()
        rows = [_row(201, caption=CAPTION, reply_to_id=300),
                _row(202, reply_to_id=300)]
        db = FakeDb(rows_by_tg={300: _row(300, text=POST_TEXT,
                                          media_type="text", mgid=None),
                                201: rows[0], 202: rows[1],
                                199: _row(199, text="соседнее сообщение",
                                          media_type="text", mgid=None)},
                    group_rows={ALBUM_ID: rows})
        target = _make_msg(message_id=202, media_group_id=ALBUM_ID,
                           photo=[object()])
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert POST_TEXT in claim and CAPTION in claim
        assert "соседнее сообщение" not in claim   # §3.8 не нарушен

    @pytest.mark.asyncio
    async def test_production_shape_album_10_caption_first_reply_ninth(
            self, handler_env, monkeypatch):
        """PERMsoc: 10 фото, подпись 2846 симв. на 1-м, reply на 9-е.
        Половина анализов failed (PENDING) — проверка идёт, ограничение
        называется честно."""
        album = "14343246299290082"
        caption = "П" * 2846
        ids = [1175403 + i for i in range(10)]
        calls = []
        payloads = {}
        for pos, tg in enumerate(ids):
            if pos in (0, 1, 2, 3, 4):        # 5 failed → PENDING-строка
                payloads[tg] = _analysis(caption=caption if pos == 0 else None,
                                         pending=True)
            else:                              # 5 ready
                payloads[tg] = _analysis(
                    caption=caption if pos == 0 else None,
                    ocr=[f"текст фото {pos + 1}"],
                    desc=["описание"] if pos == 8 else [])
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads, calls=calls))
        service = _service()
        rows = [_row(tg, caption=caption if tg == ids[0] else None, mgid=album)
                for tg in ids]
        db = FakeDb(rows_by_tg={r["tg_message_id"]: r for r in rows},
                    group_rows={album: rows})
        target = _make_msg(message_id=1175411, media_group_id=album,
                           photo=[object()])
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert claim.startswith("П" * 2846)       # длинная подпись не потеряна
        assert "текст фото 10" in claim            # материал всех фото
        assert calls == ids                        # ВСЕ 10, включая цель
        sent = _sent_text(handler_env)
        assert sent.startswith("вердикт: проверено")
        assert "Часть изображений публикации ещё не распознана" in sent
        assert "пустот" not in sent




    @pytest.mark.asyncio
    async def test_reply_to_text_reply_does_not_pull_parent(self, handler_env,
                                                            monkeypatch):
        """Обычный reply на текст, который сам reply: родитель не подмешивается."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        db = FakeDb(rows_by_tg={
            77: _row(77, text="проверяемый тезис", media_type="text",
                     mgid=None, reply_to_id=70),
            70: _row(70, text="родительский текст", media_type="text",
                     mgid=None),
        })
        target = _make_msg(text="проверяемый тезис", message_id=77)
        await _run(handler_env, service, db, target)
        assert _claim_text(service) == "проверяемый тезис"
        assert "родительский текст" not in _claim_text(service)


# ── Уточнение №2 (25.10.2026): пустая цель → окружение целиком ──────────────

class TestOwnerClarification2ContextWindow:
    @pytest.mark.asyncio
    async def test_claim_in_previous_message(self, handler_env, monkeypatch):
        """Цель без текста; утверждение — в предыдущем сообщении."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        window = [
            _win(73, "вчера обсуждали погоду"),
            _win(75, "Объект сдан 12.10.2026 по данным мэрии"),
            _win(76, "ага, видел"),
        ]
        db = FakeDb(rows_by_tg={77: _row(77, text=None, media_type="text",
                                         mgid=None)},
                    around_rows=window)
        target = _make_msg(message_id=77)
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert claim == "Объект сдан 12.10.2026 по данным мэрии"
        assert handler_env.send_chunked_reply.await_args.args[3] == 77
        handler_env._fetch_context_with_gate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_up_reply_chain(self, handler_env, monkeypatch):
        """Утверждение выше по reply-цепочке (вне окна) — цепочка читается."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        parent = _win(70, "Утверждение из корня цепочки: мост сдан в 2024")
        db = FakeDb(rows_by_tg={70: parent, 77: _row(
            77, text=None, media_type="text", mgid=None)},
            around_rows=[_win(76, "ага")])
        target = _make_msg(message_id=77)
        target.reply_to_message = _make_msg(message_id=70)
        await _run(handler_env, service, db, target)
        assert "мост сдан" in _claim_text(service)
        assert ("target", CHAT_ID, 70) in db.calls

    @pytest.mark.asyncio
    async def test_claim_in_discussion_far_from_target(self, handler_env,
                                                       monkeypatch):
        """Материал дальше 6 сообщений — окно не обрезается до узкого."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        window = [_win(240 + i, "просто болтовня и флуд без фактов")
                  for i in range(30)]
        window[0] = _win(240, "Курс вырос на 15 процентов за неделю")
        db = FakeDb(rows_by_tg={300: _row(300, text=None, media_type="text",
                                          mgid=None)},
                    around_rows=window)
        target = _make_msg(message_id=300)
        await _run(handler_env, service, db, target)
        assert "Курс вырос" in _claim_text(service)
        around = next(c for c in db.calls if c[0] == "around")
        assert around[3] > 6            # before >> узкого окна 6

    @pytest.mark.asyncio
    async def test_no_claims_anywhere_names_window(self, handler_env,
                                                   monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        window = [_win(75, "ага"), _win(76, "ну такое")]
        db = FakeDb(rows_by_tg={77: _row(77, text=None, media_type="text",
                                         mgid=None)},
                    around_rows=window)
        target = _make_msg(message_id=77)
        await _run(handler_env, service, db, target)
        service.check_claim.assert_not_awaited()
        phrase = _reply_text(handler_env)
        candidates = [p.format(scope="цель", scope_of="цели", window=len(window))
                      for p in FACTCHECK_CONTEXT_EMPTY_PHRASES]
        assert phrase in candidates
        assert phrase not in FACTCHECK_EMPTY_CONTEXT_PHRASES
        assert str(len(window)) in phrase

    @pytest.mark.asyncio
    async def test_other_chat_messages_not_used(self, handler_env, monkeypatch):
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        window = [
            _win(78, "Чужой чат: секретное утверждение 2026", chat_id=-999),
            _win(74, "Свой чат: объект сдан 12.10.2026"),
        ]
        db = FakeDb(rows_by_tg={77: _row(77, text=None, media_type="text",
                                         mgid=None)},
                    around_rows=window)
        target = _make_msg(message_id=77)
        await _run(handler_env, service, db, target)
        claim = _claim_text(service)
        assert "Свой чат" in claim
        assert "секретное" not in claim

    @pytest.mark.asyncio
    async def test_trigger_message_never_becomes_claim(self, handler_env,
                                                       monkeypatch):
        """Команда «фактчек …» — не публикация, даже если в ней есть тезис."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        window = [
            _win(11, "фактчек, Дуров убил Claude Code"),
            _win(75, "Сдан объект 12.10.2026"),
        ]
        db = FakeDb(rows_by_tg={77: _row(77, text=None, media_type="text",
                                         mgid=None)},
                    around_rows=window)
        target = _make_msg(message_id=77)
        handler_env.setup_factcheck(service, db)
        msg = _make_msg(text="фактчек, Дуров убил Claude Code", message_id=11,
                        reply_to_message=target)
        await handler_env.factcheck_handler(msg, bot=AsyncMock())
        claim = _claim_text(service)
        assert "Сдан объект" in claim
        assert "Дуров убил" not in claim

    @pytest.mark.asyncio
    async def test_context_probe_ignores_wide_gate_flag(self, handler_env,
                                                        monkeypatch):
        """Проводка: пустая цель смотрит окружение даже при гейте OFF."""
        from services import factcheck_context as fcx
        from services import factcheck_suitability as fsg

        monkeypatch.setattr(fcx, "wide_context_enabled", lambda: False)
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _service()
        db = FakeDb(rows_by_tg={77: _row(77, text=None, media_type="text",
                                         mgid=None)},
                    around_rows=[_win(75, "Сдан объект 12.10.2026")])
        target = _make_msg(message_id=77)
        await _run(handler_env, service, db, target)
        assert "Сдан объект" in _claim_text(service)
        probe = await fsg.resolve_context_claim(
            db, CHAT_ID, target_tg_message_id=77,
            trigger_tg_message_id=11,
            cache=handler_env.get_smart_cache())
        assert probe is not None and probe.claim is not None


class TestDurableAlbumStorage:
    @pytest.mark.asyncio
    async def test_media_group_query_orders_and_excludes_neighbours(
            self, tmp_path):
        from services.database import DatabaseService

        db = DatabaseService(str(tmp_path / "album.db"))
        await db.initialize()
        try:
            for tg, caption in ((71, CAPTION), (72, None), (73, None)):
                await save_live_message(
                    db, chat_id=CHAT_ID, user_id=1, caption=caption,
                    timestamp=1792200000, sent_at=1792200000,
                    media_type="photo", tg_message_id=tg,
                    media_group_id=ALBUM_ID)
            await save_live_message(
                db, chat_id=CHAT_ID, user_id=1, text="сосед вне группы",
                timestamp=1792200001, sent_at=1792200001,
                media_type="text", tg_message_id=74)
            rows = await db.get_smart_messages_by_media_group(
                CHAT_ID, ALBUM_ID)
        finally:
            await db.close()
        assert [int(r["tg_message_id"]) for r in rows] == [71, 72, 73]
        assert rows[0]["caption"] == CAPTION

    @pytest.mark.asyncio
    async def test_load_claim_media_aggregates_album_elements(self):
        payloads = {
            71: _analysis(caption="подпись", ocr=["текст 1"],
                          desc=["описание 1"]),
            72: _analysis(ocr=["текст 2"], desc=["описание 2"]),
        }
        media = await load_claim_media(
            FakeDb(), CHAT_ID, 71, render_async=_render(payloads),
            message_ids=[71, 72], expected_images=2)
        assert media.image_present and media.image_count == 2
        assert media.caption == "подпись"
        assert media.ocr_chars == len("текст 1") + len("текст 2")
        assert "Текст с изображения 1" in media.text_suffix
        assert "Текст с изображения 2" in media.text_suffix
        assert "описание 1" in media.text_suffix
        assert "не доказывает подлинность" in media.text_suffix
        assert media.notice() == ""
        assert media.vision_failed is False

    @pytest.mark.asyncio
    async def test_load_claim_media_expected_image_without_render(self):
        media = await load_claim_media(
            FakeDb(), CHAT_ID, 71, render_async=_render({}),
            message_ids=[71, 72], expected_images=2)
        assert media.image_present is False
        assert media.vision_failed is True
        assert "не удалось прочитать" in media.notice()
