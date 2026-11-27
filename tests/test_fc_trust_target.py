"""FCT-S2-TARGET (fc-trust-01) — цель, claim-сегменты и провенанс.

Контракт: `plans/features/fc-trust-01/evidence/fct-s1-contract-2026-11-27.md`
(sha256 29a29052…). База — deployed SHA c974d3b81 (2.58.256).

Строки: FCT-022, FCT-101, FCT-102, FCT-103, FCT-104, FCT-105, FCT-106, FCT-701.

Проверяется НАБЛЮДАЕМОЕ поведение входа фактчека: какой тезис реально
проверяется, на каком элементе публикации он закреплён, сколько claim-сегментов
получилось и какие target/provenance-поля объявлены в трассе `factcheck_target`.
Сеть, Telegram и LLM не используются: Vision-контур подменяется существующей
точкой `mca_vision.render_media_context_async`, БД — минимальный фейк,
внешние стадии (поиск/анализ) не вызываются (envelope отключён фикстурой).

Ни один тест не утверждает «стало лучше вообще»: каждый ассерт привязан к
конкретному пункту замороженного контракта и убивается своей мутацией (§8).
"""
import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import handlers.factcheck as fh
import handlers.voice_transcription as vt
import services.factcheck_orchestrator as orch
import services.factcheck_service as fcs
from services import factcheck_suitability as fsg
from services import mca_vision
from services import temporal_factcheck as tf
from services.smartmodule_phrases import (
    FACTCHECK_CLARIFY_PHRASES,
    FACTCHECK_IMAGE_PENDING_AUTO_PHRASES,
    FACTCHECK_IMAGE_PENDING_PHRASES,
    FACTCHECK_MEDIA_ERROR_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
)

CHAT_ID = -1001234567890
_HERE = Path(__file__).resolve().parent
DATA = json.loads(
    (_HERE / "fixtures" / "fc_trust_target" / "album_claims.json").read_text(
        encoding="utf-8"))

#: Поля, которые обязаны совпадать у обеих исполняющих веток (parity).
PARITY_FIELDS = (
    "target_source", "target_kind", "target_chat_id", "target_tg_message_id",
    "reply_to_tg_id", "media_group_id", "claim_origin", "claim_count",
    "claim_anchor_tg_message_id", "claim_anchor_ids", "claim_anchor_source",
    "target_elements", "forward_origin_type", "forward_sender_user_id",
    "forward_chat_id", "forward_message_id", "forward_display_name",
    "author_identity_kind", "author_user_id", "url_count", "hint_resolution",
    "association_status", "media_dependency",
)


# ── Двойники (минимальный durable-слой) ─────────────────────────────────────

class FakeDb:
    def __init__(self, rows_by_tg=None, group_rows=None, reply_rows=None, *,
                 around_rows=None):
        self.rows_by_tg = {int(k): v for k, v in (rows_by_tg or {}).items()}
        self.group_rows = {k: list(v) for k, v in (group_rows or {}).items()}
        self.reply_rows = {int(k): list(v)
                           for k, v in (reply_rows or {}).items()}
        self.around_rows = list(around_rows or [])
        self.calls = []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        self.calls.append(("target", int(chat_id), int(tg)))
        return self.rows_by_tg.get(int(tg))

    async def get_smart_messages_by_media_group(self, chat_id, mgid):
        self.calls.append(("group", int(chat_id), str(mgid)))
        return list(self.group_rows.get(str(mgid), []))

    async def get_smart_messages_reply_to(self, chat_id, reply_to_id, *,
                                          media_only=False, limit=10):
        self.calls.append(("reply", int(chat_id), int(reply_to_id)))
        rows = list(self.reply_rows.get(int(reply_to_id), []))
        if media_only:
            rows = [row for row in rows if row.get("media_group_id")]
        return rows[:int(limit)]

    async def get_messages_around(self, chat_id, target_tg_message_id,
                                  before, after):
        self.calls.append(("around", int(chat_id), target_tg_message_id,
                           int(before), int(after)))
        return list(self.around_rows)

    async def get_recent_messages(self, chat_id, limit):
        self.calls.append(("recent", int(chat_id), int(limit)))
        return list(self.around_rows[-int(limit):]) if limit else []


class _FakeCache:
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


class _NullCtx:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _row(tg, *, caption=None, text=None, media_type="photo", mgid=None,
         forward_source=None, origin_display_name=None, reply_to_id=None,
         origin_type=None, origin_sender_user_id=None, origin_chat_id=None,
         origin_message_id=None, user_id=None):
    return {
        "chat_id": CHAT_ID, "tg_message_id": tg, "caption": caption,
        "text": text, "media_type": media_type, "media_group_id": mgid,
        "forward_source": forward_source,
        "origin_display_name": origin_display_name,
        "reply_to_id": reply_to_id,
        "origin_type": origin_type,
        "origin_sender_user_id": origin_sender_user_id,
        "origin_chat_id": origin_chat_id,
        "origin_message_id": origin_message_id,
        "user_id": user_id,
    }


def _window_row(tg, text, *, author="Ирма", reply_to_id=None,
                chat_id=CHAT_ID):
    """Строка wide-context (поля get_messages_around)."""
    return {
        "id": tg, "chat_id": chat_id, "tg_message_id": tg, "text": text,
        "caption": None, "reply_to_id": reply_to_id,
        "timestamp": 1792200000 + tg, "media_type": "text",
        "author_name": author, "is_forward": False, "forward_source": None,
    }


def _make_msg(text=None, caption=None, message_id=1, user_id=42,
              first_name="Ирма", reply_to_message=None, forward_origin=None,
              media_group_id=None, photo=None, sender_chat=None,
              author_signature=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.first_name = first_name
    msg.from_user.last_name = ""
    msg.sender_chat = sender_chat
    msg.author_signature = author_signature
    msg.reply_to_message = reply_to_message
    msg.forward_origin = forward_origin
    msg.media_group_id = media_group_id
    msg.photo = list(photo) if photo else None
    msg.voice = None
    msg.video_note = None
    msg.document = None
    msg.sticker = None
    msg.quote = None
    return msg


def _user_origin(uid=777, first_name="Илон", last_name="Маск"):
    return MagicMock(sender_user=MagicMock(id=uid, first_name=first_name,
                                           last_name=last_name),
                     sender_chat=None, sender_user_name=None, chat=None,
                     message_id=None)


def _hidden_origin(name="Илон Маск"):
    return MagicMock(sender_user=None, sender_chat=None,
                     sender_user_name=name, chat=None, message_id=None)


def _channel_origin(chat_id=-777, title="Канал X", message_id=5):
    origin = MagicMock(sender_user=None, sender_chat=None,
                       sender_user_name=None, message_id=message_id)
    origin.chat = MagicMock(id=chat_id, title=title)
    return origin


def _analysis(ocr=(), desc=(), pending=False):
    return {
        "caption": None,
        "untrusted_ocr_texts": list(ocr),
        "visual_descriptions": list(desc),
        "lines": (["изображение, содержание ещё не распознано"]
                  if pending else []),
        "knowledge_time": None if pending else 1792200000,
    }


def _render(payloads, *, fail_ids=()):
    async def render(db, *, chat_id, tg_message_id):
        if int(tg_message_id) in fail_ids:
            raise RuntimeError("vision provider down")
        return payloads.get(int(tg_message_id))
    return render


# ── Фикстуры ────────────────────────────────────────────────────────────────

@pytest.fixture
def env(monkeypatch):
    """Handler без сети/БД-троттлинга. Обе ветки выключены (legacy) —
    тесты явно включают нужную маршрутизацию."""
    pool = MagicMock()
    permit = MagicMock()
    permit.release = lambda: None
    pool.try_acquire = AsyncMock(return_value=permit)
    monkeypatch.setattr(fh, "get_smartmodule_concurrency_pool", lambda: pool)
    monkeypatch.setattr(orch, "get_smartmodule_concurrency_pool", lambda: pool)
    monkeypatch.setattr(fh, "typing_active", lambda bot, chat: _NullCtx())
    monkeypatch.setattr(orch, "typing_active", lambda bot, chat: _NullCtx())
    monkeypatch.setattr(fh, "cooldown_remaining", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "cooldown_touch", AsyncMock())
    monkeypatch.setattr(fh, "_refund_cooldown", AsyncMock(return_value=True))
    monkeypatch.setattr(fh, "_cp_g", AsyncMock(return_value="contextual"))
    monkeypatch.setattr(fh, "_fetch_context_with_gate",
                        AsyncMock(return_value=("", None)))
    monkeypatch.setattr(fh, "send_chunked_reply", AsyncMock())
    monkeypatch.setattr(fh, "_reply", AsyncMock())
    monkeypatch.setattr(fh, "react_moai", AsyncMock())
    monkeypatch.setattr(fh, "_temporal_on", lambda: False)
    monkeypatch.setattr(fh, "_pipeline_v2_enabled", lambda: False)
    monkeypatch.setattr(fh, "get_smart_cache", lambda: _FakeCache())
    old_service, old_db = fh._service, fh._db
    yield fh
    fh._service, fh._db = old_service, old_db


@pytest.fixture
def traces(monkeypatch):
    """Перехват ЕДИНСТВЕННОЙ поверхности трассы (фактическое событие)."""
    seen: list[dict] = []

    def _capture(publication, **kwargs):
        record = {}
        if publication is not None:
            record.update(publication.trace_fields())
        record.update({key: kwargs.get(key)
                       for key in ("route", "delivery_reply_to",
                                   "trigger_tg_message_id")})
        record["_publication"] = publication
        seen.append(record)
        return record

    monkeypatch.setattr(fcs, "emit_target_trace", _capture)
    return seen


def _use_temporal(monkeypatch):
    """Temporal-direct ветка без envelope-стадий (trace + check_claim)."""
    monkeypatch.setattr(fh, "_temporal_on", lambda: True)
    monkeypatch.setattr(tf, "build_envelope",
                        AsyncMock(return_value=(None, "fct-test-skip")))


def _admin_service(verdict="вердикт: проверено"):
    service = MagicMock()
    service.check_claim = AsyncMock(return_value=verdict)
    return service


async def _run(env, service, db, target, *, text="фактчек", message_id=11,
               bot=None):
    env.setup_factcheck(service, db)
    msg = _make_msg(text=text, message_id=message_id,
                    reply_to_message=target)
    bot = bot or AsyncMock()
    await env.factcheck_handler(msg, bot=bot)
    return bot


def _claim_text(service) -> str:
    assert service.check_claim.await_args is not None, "check_claim не вызван"
    return service.check_claim.await_args.args[0]


def _delivered(env) -> list[str]:
    return [str(call.args[2]) for call in env.send_chunked_reply.await_args_list]


# ── FCT-701: claim-сегменты, дедуп и порядок ────────────────────────────────

class TestClaimSegments:
    @pytest.mark.asyncio
    async def test_repeated_thesis_collapses_to_one_segment(self, env,
                                                            monkeypatch):
        """FCT-701/M4: один нормализованный тезис на трёх носителях → 1 сегмент,
        анкор = минимальный tg id, members = все носители по порядку."""
        thesis = DATA["thesis"]
        ocr_lower = thesis.lower()
        payloads = {
            element: _analysis(ocr=[ocr_lower])
            for element in DATA["thesis_ocr_elements"]
        }
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads))
        service = _admin_service()
        rows = [
            _row(71, mgid=DATA["album_id"]),
            _row(72, caption=thesis, mgid=DATA["album_id"]),
            _row(73, mgid=DATA["album_id"]),
        ]
        db = FakeDb(rows_by_tg={row["tg_message_id"]: row for row in rows},
                    group_rows={DATA["album_id"]: rows})
        target = _make_msg(message_id=71, media_group_id=DATA["album_id"],
                           photo=[object()])
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        publication = captured[0]
        segments = [dict(segment) for segment in publication.claim_segments]
        assert len(segments) == 1
        assert segments[0]["anchor_tg_message_id"] == 71
        assert segments[0]["member_tg_message_ids"] == (71, 72, 73)
        # Тезис ровно один раз (ни caption, ни OCR второго/третьего элемента).
        assert publication.text.casefold().count(thesis.casefold()) == 1
        assert "изображения 3" not in publication.text
        trace = publication.trace_fields()
        assert trace["claim_count"] == 1
        # §7 (review-fix F1): трасса обязана показать ВСЕ носители схлопнутого
        # тезиса, по возрастанию — иначе «один тезис на трёх носителях» и
        # «один носитель» в проде неразличимы.
        assert trace["claim_anchor_ids"] == [71, 72, 73]
        _ = ocr_lower

    @pytest.mark.asyncio
    async def test_anchor_ids_descending_reply_matches_ascending_contract(
            self, env, monkeypatch):
        """F1(b)/TP4: ответ на ПОЗДНИЙ элемент не делает трассу убывающей.

        Тот же схлопнутый тезис, но Reply адресован элементу 73: члены
        сегмента обязаны остаться (71,72,73), анкор — 71 (минимальный)."""
        thesis = DATA["thesis"]
        payloads = {
            element: _analysis(ocr=[thesis.lower()])
            for element in DATA["thesis_ocr_elements"]
        }
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads))
        service = _admin_service()
        rows = [
            _row(71, mgid=DATA["album_id"]),
            _row(72, caption=thesis, mgid=DATA["album_id"]),
            _row(73, mgid=DATA["album_id"]),
        ]
        db = FakeDb(rows_by_tg={row["tg_message_id"]: row for row in rows},
                    group_rows={DATA["album_id"]: rows})
        target = _make_msg(message_id=73, media_group_id=DATA["album_id"],
                           photo=[object()])
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        publication = captured[0]
        trace = publication.trace_fields()
        assert trace["target_tg_message_id"] == 73        # цель = Reply
        assert trace["claim_anchor_tg_message_id"] == 71  # носитель тезиса
        assert trace["claim_count"] == 1
        assert trace["claim_anchor_ids"] == [71, 72, 73]
        assert list(trace["claim_anchor_ids"]) == sorted(trace["claim_anchor_ids"])

    @pytest.mark.asyncio
    async def test_anchor_ids_ascending_for_distinct_theses_late_reply(
            self, env, monkeypatch):
        """F1(b)/анти-переслияние: два носителя, Reply на поздний → [71,72]."""
        first = "Курс доллара 95 рублей"
        second = "Курс доллара 96 рублей"
        album = "fc-trust-album-03"
        monkeypatch.setattr(
            mca_vision, "render_media_context_async",
            _render({71: _analysis(ocr=[first]), 72: _analysis(ocr=[second])}))
        service = _admin_service()
        rows = [_row(71, mgid=album), _row(72, mgid=album)]
        db = FakeDb(rows_by_tg={71: rows[0], 72: rows[1]},
                    group_rows={album: rows})
        target = _make_msg(message_id=72, media_group_id=album,
                           photo=[object()])
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        trace = captured[0].trace_fields()
        assert trace["claim_count"] == 2
        assert trace["claim_anchor_ids"] == [71, 72]

    @pytest.mark.asyncio
    async def test_buffered_caption_not_attributed_to_replied_element(
            self, env, monkeypatch):
        """B1/F1: caption из same-turn буфера не делает адресат Reply носителем.

        Ответ на 72, caption на 71 (durable-строка 71 несёт текст, буфер
        отдаёт его как base): член сегмента и анкор — 71, лишнего 72 нет."""
        from services import media_group_buffer as mgb

        thesis = DATA["thesis"]
        album = "fc-trust-album-b1"
        mgb._buffer.clear()
        try:
            mgb.record_media_group_message(_make_msg(
                caption=thesis, message_id=71, media_group_id=album))
            monkeypatch.setattr(mca_vision, "render_media_context_async",
                                _render({71: _analysis(), 72: _analysis()}))
            service = _admin_service()
            rows = [_row(71, caption=thesis, mgid=album),
                    _row(72, mgid=album)]
            db = FakeDb(rows_by_tg={71: rows[0], 72: rows[1]},
                        group_rows={album: rows})
            target = _make_msg(message_id=72, media_group_id=album,
                               photo=[object()])
            _use_temporal(monkeypatch)
            captured = []
            monkeypatch.setattr(
                fcs, "emit_target_trace",
                lambda publication, **kw: captured.append(publication))
            await _run(env, service, db, target)
            publication = captured[0]
            trace = publication.trace_fields()
            assert trace["claim_anchor_tg_message_id"] == 71
            assert trace["claim_count"] == 1
            assert trace["claim_anchor_ids"] == [71]
            segments = [dict(segment)
                        for segment in publication.claim_segments]
            assert len(segments) == 1
            assert segments[0]["member_tg_message_ids"] == (71,)
        finally:
            mgb._buffer.clear()

    @pytest.mark.asyncio
    async def test_distinct_theses_stay_separate(self, env, monkeypatch):
        """FCT-701/M5: разные числа — разные сегменты (анти-переслияние)."""
        theses = DATA["distinct"]["theses"]
        monkeypatch.setattr(
            mca_vision, "render_media_context_async",
            _render({81: _analysis(ocr=[theses["81"]]),
                     82: _analysis(ocr=[theses["82"]])}))
        service = _admin_service()
        album = DATA["distinct"]["album_id"]
        rows = [_row(81, mgid=album), _row(82, mgid=album)]
        db = FakeDb(rows_by_tg={81: rows[0], 82: rows[1]},
                    group_rows={album: rows})
        target = _make_msg(message_id=81, media_group_id=album,
                           photo=[object()])
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        publication = captured[0]
        trace = publication.trace_fields()
        assert trace["claim_count"] == 2
        assert trace["claim_anchor_ids"] == [81, 82]
        anchors = sorted(segment["anchor_tg_message_id"]
                         for segment in publication.claim_segments)
        assert anchors == [81, 82]


# ── FCT-022/FCT-104: альбом, носитель caption, forward+caption ──────────────

class TestAlbumCarrier:
    @pytest.mark.asyncio
    async def test_reply_to_first_element_caption_on_third_is_checked(
            self, env, monkeypatch):
        """FCT-022/M2b: ответ на 1-й элемент, caption на 3-м → subject из 3-го,
        не отказ «нечего проверять»."""
        thesis = DATA["thesis"]
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({71: _analysis(), 72: _analysis(),
                                     73: _analysis()}))
        service = _admin_service()
        album = DATA["album_id"]
        rows = [_row(71, mgid=album), _row(72, mgid=album),
                _row(73, caption=thesis, mgid=album)]
        db = FakeDb(rows_by_tg={row["tg_message_id"]: row for row in rows},
                    group_rows={album: rows})
        target = _make_msg(message_id=71, media_group_id=album)
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        assert thesis in _claim_text(service)
        env._reply.assert_not_awaited()
        publication = captured[0]
        assert publication.target_tg_message_id == 71      # цель = reply
        assert publication.claim_anchor_tg_message_id == 73  # тезис — на 3-м
        trace = publication.trace_fields()
        assert trace["claim_anchor_ids"] == [73]
        assert [element["tg_message_id"]
                for element in trace["target_elements"]] == [71, 72, 73]

    @pytest.mark.asyncio
    async def test_forward_caption_checked_when_vision_fails(self, env,
                                                             monkeypatch):
        """FCT-104/M6: сбой Vision не отменяет проверку caption/тела пересылки;
        оговорка — только про изображение."""
        caption = "В сборке 283365 убрали старый API"
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}, fail_ids={77}))
        service = _admin_service()
        db = FakeDb(rows_by_tg={77: _row(77, caption=caption, mgid=None)})
        target = _make_msg(message_id=77, caption=caption, photo=[object()],
                           forward_origin=_channel_origin())
        _use_temporal(monkeypatch)
        await _run(env, service, db, target)
        assert _claim_text(service) == caption
        delivered = " ".join(_delivered(env))
        assert delivered.startswith("вердикт: проверено")
        assert ("не удалось прочитать" in delivered
                or "НЕ проверено" in delivered)
        for phrase in FACTCHECK_NO_CLAIM_PHRASES:
            assert phrase not in delivered


# ── FCT-105: pending-медиа — не «нет тезиса» ─────────────────────────────────

class TestPendingMedia:
    @pytest.mark.asyncio
    async def test_pending_media_without_text_defers(self, env, monkeypatch):
        """FCT-105/M7: фото pending без текста → durable-намерение, а не
        терминальный отказ."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({77: _analysis(pending=True)}))
        defer = AsyncMock(return_value={"intent": "vision:intent:1"})
        monkeypatch.setattr(orch, "defer_factcheck_until_media_ready", defer)
        service = _admin_service()
        db = FakeDb(rows_by_tg={77: _row(77, mgid=None)})
        target = _make_msg(message_id=77, photo=[object()])
        await _run(env, service, db, target)
        service.check_claim.assert_not_awaited()
        defer.assert_awaited()
        reply_text = env._reply.await_args.args[2]
        pending_pool = set(FACTCHECK_IMAGE_PENDING_PHRASES) | set(
            FACTCHECK_IMAGE_PENDING_AUTO_PHRASES)
        assert reply_text in pending_pool
        for phrase in FACTCHECK_NO_CLAIM_PHRASES:
            assert phrase not in reply_text

    @pytest.mark.asyncio
    async def test_pending_media_with_caption_checks_immediately(
            self, env, monkeypatch):
        """FCT-105: при наличии текста проверка идёт сразу, несмотря на pending."""
        caption = "Курс вырос до 101 рубля"
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({77: _analysis(pending=True)}))
        service = _admin_service()
        db = FakeDb(rows_by_tg={77: _row(77, caption=caption, mgid=None)})
        target = _make_msg(message_id=77, caption=caption, photo=[object()])
        await _run(env, service, db, target)
        assert _claim_text(service) == caption
        env._reply.assert_not_awaited()


# ── FCT-103: референциальный намёк и структурный антецедент ──────────────────

def _hint_db():
    hint = DATA["hint"]
    rows = {
        hint["hint_element"]: _row(hint["hint_element"], text=hint["hint_text"],
                                   media_type="text",
                                   reply_to_id=hint["news_element"]),
        hint["news_element"]: _row(hint["news_element"], text=hint["news_text"],
                                   media_type="text"),
        hint["decoy_element"]: _row(hint["decoy_element"],
                                    text=hint["decoy_text"],
                                    media_type="text"),
    }
    window = [
        _window_row(hint["decoy_element"], hint["decoy_text"]),
        _window_row(hint["news_element"], hint["news_text"]),
    ]
    return FakeDb(rows_by_tg=rows, around_rows=window)


class TestReferentialHint:
    @pytest.mark.asyncio
    async def test_hint_resolves_to_structural_original_not_decoy(
            self, env, monkeypatch):
        """FCT-103/M3/M8: «ну и что там?» → оригинал по reply-ребру, хотя
        decoy ближе по tg id; текст намёка тезисом не становится."""
        hint = DATA["hint"]
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _admin_service()
        db = _hint_db()
        target = _make_msg(message_id=hint["hint_element"],
                           text=hint["hint_text"],
                           reply_to_message=_make_msg(
                               message_id=hint["news_element"]))
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(
                                (publication, kw)))
        await _run(env, service, db, target)
        claim = _claim_text(service)
        assert claim == hint["news_text"]
        assert hint["hint_text"] not in claim
        assert hint["decoy_text"] not in claim
        assert "<chat_context" not in claim
        publication, kwargs = captured[0]
        trace = publication.trace_fields()
        assert trace["target_source"] == "contextual"
        assert trace["claim_anchor_tg_message_id"] == hint["news_element"]
        assert trace["hint_resolution"] == "structural"
        assert kwargs["delivery_reply_to"] == hint["trigger_element"]

    @pytest.mark.asyncio
    async def test_literal_short_request_still_reaches_admission(
            self, env, monkeypatch):
        """FCT-102: короткий непустой текст цели не превращается в отказ из-за
        «референциальности» — проверка идёт прежним путём."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _admin_service()
        target = _make_msg(message_id=71, text="глянь это")
        db = FakeDb(rows_by_tg={71: _row(71, text="глянь это",
                                         media_type="text")})
        await _run(env, service, db, target)
        assert _claim_text(service) == "глянь это"
        env._reply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unresolved_hint_never_becomes_refusal_with_verdict(
            self, env, monkeypatch):
        """FCT-103: неразрешённый намёк не даёт вердикта по чужому тезису."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _admin_service()
        target = _make_msg(message_id=50, text="ну и что там?")
        db = FakeDb(rows_by_tg={50: _row(50, text="ну и что там?",
                                         media_type="text")})
        await _run(env, service, db, target)
        if service.check_claim.await_args is not None:
            # если проверка всё же идёт — только по собственному тексту цели
            assert _claim_text(service) == "ну и что там?"
        assert not any("Мост" in text for text in _delivered(env))


# ── FCT-101/FCT-106: провенанс и идентичность ───────────────────────────────

class TestIdentity:
    @pytest.mark.asyncio
    async def test_participant_identity_is_uid_not_display_name(
            self, env, monkeypatch):
        """FCT-106/M1/M9: участник «Илон Маск» — chat_participant + UID,
        display-name персоной не становится."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _admin_service()
        thesis = "Курс доллара вырос до 101 рубля"
        db = FakeDb(rows_by_tg={
            77: _row(77, text=thesis, media_type="text", user_id=42)})
        target = _make_msg(message_id=77, text=thesis, user_id=42,
                           first_name="Илон Маск")
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        trace = captured[0].trace_fields()
        assert trace["author_identity_kind"] == "chat_participant"
        assert trace["author_user_id"] == 42
        assert trace["forward_origin_type"] == "none"
        assert trace["forward_sender_user_id"] is None
        # Имя нигде не выдаётся за источник/персону.
        assert "Илон" not in json.dumps(trace, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_hidden_forward_identity_is_honest_unknown(self, env,
                                                             monkeypatch):
        """FCT-106/P3: hidden_user не даёт UID — identity unknown, имя только
        для отображения."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _admin_service()
        thesis = "Мост через Волгу обрушился 26.11.2026"
        db = FakeDb(rows_by_tg={77: _row(77, text=thesis, media_type="text")})
        target = _make_msg(message_id=77, text=thesis,
                           forward_origin=_hidden_origin("Илон Маск"))
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        trace = captured[0].trace_fields()
        assert trace["forward_origin_type"] == "hidden_user"
        assert trace["author_identity_kind"] == "hidden_name"
        assert trace["author_user_id"] is None
        assert trace["forward_display_name"] == "Илон Маск"   # только display

    @pytest.mark.asyncio
    async def test_forward_uid_comes_from_origin_not_display(self, env,
                                                             monkeypatch):
        """FCT-101/M12: forward origin — type + UID из structural origin."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _admin_service()
        thesis = "В сборке 283365 убрали старый API"
        db = FakeDb(rows_by_tg={77: _row(77, text=thesis, media_type="text")})
        target = _make_msg(message_id=77, text=thesis,
                           forward_origin=_user_origin(uid=777))
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        trace = captured[0].trace_fields()
        assert trace["forward_origin_type"] == "user"
        assert trace["forward_sender_user_id"] == 777
        assert trace["author_identity_kind"] == "public_user"
        assert trace["author_user_id"] == 777

    @pytest.mark.asyncio
    async def test_transcription_author_never_from_author_name(self, env,
                                                               monkeypatch):
        """FCT-101/FCT-106/M12: author_name из БД не становится forward_source,
        но структурный forward_source сохраняется."""
        monkeypatch.setattr(vt, "_bot_id", 999)
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        service = _admin_service()
        db = MagicMock()
        db.get_smart_message_by_tg_id = AsyncMock(
            return_value={"forward_source": "", "author_name": "Илон Маск"})
        env.setup_factcheck(service, db=db)
        orig_voice = _make_msg(message_id=555)
        target = _make_msg(message_id=77, text="Вася 🗣: заявление о дате",
                           user_id=999, reply_to_message=orig_voice)
        _use_temporal(monkeypatch)
        await env.factcheck_handler(
            _make_msg(text="фактчек", message_id=11,
                      reply_to_message=target),
            bot=AsyncMock())
        assert service.check_claim.await_args.args[2] is None
        assert service.check_claim.await_args.args[0] == "заявление о дате"


# ── FCT-022: семь форм входа дают непустой предмет ──────────────────────────

class TestSevenInputShapes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("shape", [
        "reply_text", "reply_caption", "forward_caption", "link",
        "transcript", "album", "related_reply",
    ])
    async def test_shape_yields_subject_and_factual_origin(self, env,
                                                           monkeypatch, shape):
        """FCT-022: 7 форм входа → непустой subject + фактический
        target_source/claim_origin в трассе."""
        monkeypatch.setattr(vt, "_bot_id", 999)
        thesis = DATA["thesis"]
        payloads = {}
        rows_by_tg = {}
        around_rows = []
        target = None
        allowed_origins = ()
        if shape == "reply_text":
            rows_by_tg[71] = _row(71, text=thesis, media_type="text")
            target = _make_msg(message_id=71, text=thesis)
            allowed_origins = ("target_text",)
        elif shape == "reply_caption":
            rows_by_tg[71] = _row(71, caption=thesis)
            payloads[71] = _analysis()
            target = _make_msg(message_id=71, caption=thesis, photo=[object()])
            allowed_origins = ("target_text", "target_caption")
        elif shape == "forward_caption":
            rows_by_tg[71] = _row(71, caption=thesis)
            payloads[71] = _analysis()
            target = _make_msg(message_id=71, caption=thesis, photo=[object()],
                               forward_origin=_channel_origin())
            allowed_origins = ("target_text", "target_caption")
        elif shape == "link":
            thesis = "Мост обрушился: https://example.com/news"
            rows_by_tg[71] = _row(71, text=thesis, media_type="text")
            target = _make_msg(message_id=71, text=thesis)
            allowed_origins = ("target_text",)
        elif shape == "transcript":
            thesis = "заявление о дате"
            rows_by_tg[77] = _row(77, text="Вася 🗣: заявление о дате",
                                  media_type="text")
            target = _make_msg(message_id=77, text="Вася 🗣: заявление о дате",
                               user_id=999, reply_to_message=_make_msg(
                                   message_id=555))
            allowed_origins = ("target_transcript",)
        elif shape == "album":
            album = DATA["album_id"]
            rows = [_row(71, mgid=album), _row(72, caption=thesis, mgid=album),
                    _row(73, mgid=album)]
            rows_by_tg = {row["tg_message_id"]: row for row in rows}
            payloads = {71: _analysis(), 72: _analysis(), 73: _analysis()}
            target = _make_msg(message_id=71, media_group_id=album,
                               photo=[object()])
            allowed_origins = ("target_caption",)
        elif shape == "related_reply":
            rows_by_tg[60] = _row(60, text=thesis, media_type="text")
            rows_by_tg[50] = _row(50, text="", media_type="text",
                                  reply_to_id=60)
            around_rows = [_window_row(60, thesis)]
            target = _make_msg(message_id=50, text="",
                               reply_to_message=_make_msg(message_id=60))
            allowed_origins = ("context_window",)
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render(payloads))
        service = _admin_service()
        group_rows = {}
        if shape == "album":
            group_rows = {DATA["album_id"]: list(rows_by_tg.values())}
        db = FakeDb(rows_by_tg=rows_by_tg, group_rows=group_rows,
                    around_rows=around_rows)
        _use_temporal(monkeypatch)
        captured = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: captured.append(publication))
        await _run(env, service, db, target)
        claim = _claim_text(service)
        assert claim.strip(), f"{shape}: пустой предмет проверки"
        assert thesis in claim
        trace = captured[0].trace_fields()
        assert trace["claim_origin"] in allowed_origins, shape
        assert trace["target_source"] in (
            "explicit_reply", "forward", "album", "contextual", "media",
            "command_text", "stored_reply")
        assert trace["target_chat_id"] == CHAT_ID
        if shape == "related_reply":
            assert trace["target_tg_message_id"] == 60
        else:
            assert trace["target_tg_message_id"] == target.message_id


# ── FCT-102: ingress не получает новых триггеров ───────────────────────────

def _module_regex_patterns(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    patterns: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if (isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "compile"
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == "re"
                and value.args
                and isinstance(value.args[0], ast.Constant)):
            patterns.append(str(value.args[0].value))
    return patterns


class TestIngressUnchanged:
    def test_no_new_trigger_regex_in_ingress(self):
        """FCT-102/M13: набор регулярок ingress не расширен.

        Пин — фактический deployed-набор (c974d3b81). Новый триггер или
        обязательное слово в ingress обязан ломать этот тест."""
        patterns = _module_regex_patterns(
            _HERE.parent / "handlers" / "factcheck.py")
        assert sorted(patterns) == sorted([
            r"^фактчек\b",
            r"^[\s,:;]+",
            r"🗣:\s?(.*)",
        ])

    @pytest.mark.asyncio
    async def test_explicit_command_and_natural_request_both_admitted(
            self, env, monkeypatch):
        """FCT-102: явная команда работает как раньше; вопрос «это правда?»
        как reply на новость доходит до допуска (не отказ)."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        thesis = DATA["hint"]["news_text"]
        service = _admin_service()
        db = FakeDb(rows_by_tg={60: _row(60, text=thesis, media_type="text")})
        target = _make_msg(message_id=60, text=thesis)
        await _run(env, service, db, target, text="фактчек: это правда?")
        assert _claim_text(service) == thesis
        env._reply.assert_not_awaited()


# ── Единый ingress: supersede отложенного намерения (M11) ──────────────────

class TestSingleIngress:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("route", ["legacy", "temporal", "v2"])
    async def test_exactly_one_target_trace_per_ingress(self, env, monkeypatch,
                                                        route):
        """§2/§6: ровно одна трасса `factcheck_target` на вход, независимо от
        исполняющей ветки (дубль ingress+ветка запрещён)."""
        import dataclasses

        thesis = DATA["thesis"]
        rows = [_row(71, mgid=None)]
        db = FakeDb(rows_by_tg={71: rows[0]})
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        if route == "temporal":
            _use_temporal(monkeypatch)
        elif route == "v2":
            monkeypatch.setattr(fh, "_pipeline_v2_enabled", lambda: True)
            no_claim = dataclasses.replace(
                fsg.evaluate_suitability(
                    "лол", None, None,
                    target_ref={"chat_id": CHAT_ID,
                                "target_tg_message_id": 71}),
                decision=fsg.DECISION_NO_CLAIM)
            monkeypatch.setattr(fsg, "evaluate_with_expansion",
                                AsyncMock(return_value=(no_claim, None)))
        emitted = []
        monkeypatch.setattr(fcs, "emit_target_trace",
                            lambda publication, **kw: emitted.append(
                                kw.get("route")))
        service = _admin_service()
        target = _make_msg(message_id=71, text=thesis)
        await _run(env, service, db, target)
        assert len(emitted) == 1, f"{route}: трасс {len(emitted)}"
        assert emitted[0] in ("handler_v1", "handler_legacy",
                              "orchestrator_v2")

    @pytest.mark.asyncio
    async def test_fresh_request_cancels_deferred_intent_once(self, env,
                                                              monkeypatch):
        """M11: свежий запрос отменяет отложенное намерение; ровно одна
        доставка на (chat, цель, claim)."""
        monkeypatch.setattr(mca_vision, "render_media_context_async",
                            _render({}))
        cancel = AsyncMock()
        monkeypatch.setattr(orch, "cancel_deferred_factcheck", cancel)
        service = _admin_service()
        thesis = DATA["thesis"]
        db = FakeDb(rows_by_tg={71: _row(71, text=thesis, media_type="text")})
        target = _make_msg(message_id=71, text=thesis)
        await _run(env, service, db, target)
        cancel.assert_awaited_once()
        assert cancel.await_args.kwargs["target_message_id"] == 71
        assert len(_delivered(env)) == 1
        service.check_claim.assert_awaited_once()


# ── Паритет target/provenance-полей при обоих состояниях флага (M10) ───────

class TestFlagParity:
    @pytest.mark.asyncio
    async def test_target_fields_identical_in_both_flag_states(
            self, env, monkeypatch):
        """§2/M10: исправленное разрешение цели безусловно.

        Один и тот же вход прогоняется дважды: (a) temporal-direct
        (`flags.factcheck_pipeline_v2` off), (b) v2 (`on`). Обе ветки обязаны
        объявить ОДНИ И ТЕ ЖЕ target/provenance-поля, и публикация резолвится
        РОВНО ОДИН раз за вход."""
        import dataclasses

        thesis = DATA["thesis"]
        album = DATA["album_id"]
        rows = [_row(71, mgid=album), _row(72, caption=thesis, mgid=album),
                _row(73, mgid=album)]
        no_claim = dataclasses.replace(
            fsg.evaluate_suitability("лол", None, None,
                                     target_ref={"chat_id": CHAT_ID,
                                                 "target_tg_message_id": 71}),
            decision=fsg.DECISION_NO_CLAIM)
        runs: dict[str, dict] = {}
        resolve_counts: dict[str, int] = {}

        async def _run_once(v2_enabled: bool) -> dict:
            db = FakeDb(rows_by_tg={row["tg_message_id"]: row for row in rows},
                        group_rows={album: rows})
            monkeypatch.setattr(
                mca_vision, "render_media_context_async",
                _render({71: _analysis(), 72: _analysis(), 73: _analysis()}))
            resolve_calls: list = []
            real_resolve = fcs.resolve_claim_publication

            async def _resolve(*args, **kwargs):
                resolve_calls.append(kwargs.get("target_source"))
                return await real_resolve(*args, **kwargs)

            monkeypatch.setattr(fcs, "resolve_claim_publication", _resolve)
            if v2_enabled:
                monkeypatch.setattr(fh, "_pipeline_v2_enabled", lambda: True)
                monkeypatch.setattr(fh, "_temporal_on", lambda: False)
                monkeypatch.setattr(
                    fsg, "evaluate_with_expansion",
                    AsyncMock(return_value=(no_claim, None)))
            else:
                monkeypatch.setattr(fh, "_pipeline_v2_enabled", lambda: False)
                _use_temporal(monkeypatch)
            recalled: list = []
            monkeypatch.setattr(
                fcs, "emit_target_trace",
                lambda publication, **kw: recalled.append(
                    (publication.trace_fields(), kw.get("route"))))
            service = _admin_service()
            target = _make_msg(message_id=71, media_group_id=album,
                               photo=[object()])
            await _run(env, service, db, target)
            assert recalled, "трасса factcheck_target не объявлена"
            resolve_counts["v2" if v2_enabled else "temporal"] = len(
                resolve_calls)
            fields, route = recalled[0]
            expected_route = ("orchestrator_v2" if v2_enabled
                              else "handler_v1")
            assert route == expected_route
            return fields

        runs["temporal"] = await _run_once(False)
        runs["v2"] = await _run_once(True)
        for name, count in resolve_counts.items():
            assert count == 1, f"{name}: публикация резолвилась {count} раз"
        for key in PARITY_FIELDS:
            assert runs["v2"][key] == runs["temporal"][key], (
                f"расхождение target/provenance-поля {key}")
