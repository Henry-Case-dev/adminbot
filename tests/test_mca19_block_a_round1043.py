"""MCA-19 Wave 1, блок A (`mca-19-image-understanding`, round 10.43) —
единая запись сообщения / assets / атрибуция (ADR-1028-19 D1–D3; T-5100…T-5102).

Покрытие:
  * v32 через реестр mca-14: +10 Origin-колонок `smart_messages` (guard
    PRAGMA), `mca_media_assets` / `mca_media_analyses` (CHECK-статусы +
    UNIQUE-гранула), 4 индекса; аддитивно/идемпотентно; v31 → v32 upgrade;
  * Origin-блок: canonical write (`save_smart_message_identity` через
    `save_live_message`) и legacy-путь; sent_at ≠ ingested_at (SC-R1b);
  * атрибуция (D3): sender ≠ origin-автор ≠ автор текста на картинке —
    Origin пишется отдельно, forward_source (display) сохраняется;
  * intake-активы: photo/document/sticker; альбом — по asset на item с общей
    media_group_id; caption НЕ размножается; идемпотентный re-observe;
    K1 (мастер) OFF → паритет (активов нет);
  * analyses: idempotent upsert по UNIQUE-грануле (singleflight-примитив),
    CAS/fencing по revision (stale job отброшен — примитив A66), success-кеш
    только status='ready', кросс-чат изоляция по access_scope (TH-5,
    негативный тест SC-R3c), content-hash привязка CAS;
  * security RED→GREEN митигации: кросс-чат-утечка отсутствует; OCR-канал
    недоверенных данных (см. block B) — здесь SourceRef на сообщение.
"""
import asyncio
import datetime

import pytest
from aiogram.types import (Chat, Document, Message, MessageOriginChannel,
                           MessageOriginUser, PhotoSize, Sticker, User)

from services import mca_gates, mca_vision
from services.database import (
    DatabaseService,
    _SCHEMA_VERSION_MEDIA_VISION,
    _SMART_MESSAGES_ORIGIN_COLUMNS,
)

CHAT_A = -1004000000001
CHAT_B = -1004000000002

DT = datetime.datetime(2026, 10, 6, 12, 0, 0,
                       tzinfo=datetime.timezone.utc)


def _target_version() -> int:
    return max(s.version for s in DatabaseService.migration_steps())


async def _fresh(tmp_path, name="mca19a.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


def _photo(size="large"):
    return PhotoSize(file_id=f"fid_{size}", file_unique_id=f"uniq_{size}",
                     width=800, height=600, file_size=12345)


def _photo_message(chat_id=CHAT_A, tg_id=101, *, media_group_id=None,
                   origin=None, caption=None):
    return Message(
        message_id=tg_id,
        date=DT,
        chat=Chat(id=chat_id, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Вася"),
        photo=[_photo("small"), _photo("large")],
        caption=caption,
        media_group_id=media_group_id,
        forward_origin=origin,
    )


# ── v32: миграция ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v32_registered_and_applied(tmp_path):
    d = await _fresh(tmp_path)
    try:
        assert _SCHEMA_VERSION_MEDIA_VISION == 32
        assert _target_version() >= 32
        step = next(s for s in DatabaseService.migration_steps()
                    if s.version == 32)
        assert step.name == "media_vision"
        cur = await d.db.execute("SELECT name FROM schema_migrations "
                                 "WHERE version = 32")
        assert (await cur.fetchone())["name"] == "media_vision"
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 32
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v32_shape_columns_tables_indexes(tmp_path):
    d = await _fresh(tmp_path)
    try:
        cur = await d.db.execute("PRAGMA table_info(smart_messages)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {name for name, _ in _SMART_MESSAGES_ORIGIN_COLUMNS} <= cols
        assert len(_SMART_MESSAGES_ORIGIN_COLUMNS) == 10
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in await cur.fetchall()}
        assert {"mca_media_assets", "mca_media_analyses"} <= tables
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")
        idx = {r["name"] for r in await cur.fetchall()}
        assert {"idx_mca_media_assets_chat_tg",
                "idx_mca_media_assets_file_unique",
                "idx_mca_media_assets_content_hash",
                "idx_mca_media_analyses_scope_status"} <= idx
        # CHECK-статусы: различимые 5+ (no_text ≠ unreadable ≠ unsupported ≠
        # unavailable ≠ failed); недопустимый статус отклонён схемой.
        with pytest.raises(Exception):
            await d.db.execute(
                "INSERT INTO mca_media_analyses (asset_id, status) "
                "VALUES ('x', 'success')")
        await d.db.rollback()
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v32_unique_granule_and_idempotent_rerun(tmp_path):
    d = await _fresh(tmp_path, name="mca19a_unique.db")
    path = str(d.db_path)
    await d.close()
    d2 = DatabaseService(path)
    await d2.initialize()          # повтор — no-op
    try:
        await d2.db.execute(
            "INSERT INTO mca_media_analyses (asset_id, access_scope, "
            "analysis_schema_version, analyzer_config_revision, "
            "quality_profile, status) VALUES ('a1', 'chat:1', 1, 'cfg1', "
            "'default', 'pending')")
        await d2.db.commit()
        # Та же гранула напрямую — UNIQUE отклоняет (атомарность в хранилище).
        with pytest.raises(Exception):
            await d2.db.execute(
                "INSERT INTO mca_media_analyses (asset_id, access_scope, "
                "analysis_schema_version, analyzer_config_revision, "
                "quality_profile, status) VALUES ('a1', 'chat:1', 1, 'cfg1', "
                "'default', 'running')")
        await d2.db.rollback()
    finally:
        await d2.close()


# ── T-5100: Origin-блок в канонической записи ───────────────────────────────

@pytest.mark.asyncio
async def test_origin_block_written_canonical(tmp_path):
    d = await _fresh(tmp_path)
    try:
        origin = MessageOriginUser(
            type="user", date=DT - datetime.timedelta(hours=2),
            sender_user=User(id=7, is_bot=False, first_name="Оригинал",
                             last_name="Автор", username="orig"))
        msg = _photo_message(origin=origin, caption="смотри")
        from handlers import summary as summary_mod

        class _A:
            def resolve(self, user_id, nickname=None, username=None):
                return nickname or str(user_id)

        old_db, old_alias, old_bot = (summary_mod._db, summary_mod._aliases,
                                      summary_mod._bot_id)
        summary_mod._db, summary_mod._aliases = d, _A()
        summary_mod._bot_id = None
        try:
            from handlers.summary import summary_observer
            await summary_observer(msg)
        finally:
            summary_mod._db, summary_mod._aliases = old_db, old_alias
            summary_mod._bot_id = old_bot
        cur = await d.db.execute(
            "SELECT * FROM smart_messages WHERE chat_id=? AND "
            "tg_message_id=101", (CHAT_A,))
        row = await cur.fetchone()
        assert row is not None
        # sent_at (событие 12:00 UTC → epoch) ≠ ingested_at (время записи):
        # два НЕЗАВИСИМЫХ времени (SC-R1b; сообщение может прийти раньше/позже
        # записи — приравнивание запрещено D3).
        assert row["sent_at"] == int(DT.timestamp())
        assert row["ingested_at"] != row["sent_at"]
        # Origin: автор пересылки ≠ отправитель (D3); display/ID честные.
        assert row["origin_type"] == "user"
        assert row["origin_sender_user_id"] == 7
        assert row["origin_sent_at"] == int((DT - datetime.timedelta(
            hours=2)).timestamp())
        assert (row["origin_display_name"] or "").find("Оригинал") >= 0
        assert row["user_id"] == 42                 # sender не подменён
        assert (row["forward_source"] or "") != ""  # display-строка рядом
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_origin_channel_signature_and_thread(tmp_path):
    d = await _fresh(tmp_path)
    try:
        origin = MessageOriginChannel(
            type="channel", date=DT - datetime.timedelta(minutes=30),
            chat=Chat(id=-100555, type="channel", title="Канал"),
            author_signature="Подпись автора", message_id=77)
        rec = {
            "chat_id": CHAT_A, "tg_message_id": 202, "text": "пересылка",
            "user_id": 42, "sent_at": int(DT.timestamp()),
            "ingested_at": int(DT.timestamp()) + 420,
            "media_type": "photo",
        }
        from services.message_identity import save_live_message
        from handlers.summary import _extract_origin_fields
        fields = _extract_origin_fields(origin)
        await save_live_message(d, **rec, **fields,
                                thread_id=5, media_group_id=None)
        cur = await d.db.execute(
            "SELECT * FROM smart_messages WHERE chat_id=? AND "
            "tg_message_id=202", (CHAT_A,))
        row = await cur.fetchone()
        assert row["origin_type"] == "channel"
        assert row["origin_chat_id"] == -100555
        assert row["origin_display_name"] == "Канал"
        assert row["origin_author_signature"] == "Подпись автора"
        assert row["origin_message_id"] == 77
        # SC-R1b: 12:00 событие и 12:07 обработка — два разных времени.
        assert row["sent_at"] != row["ingested_at"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_legacy_path_off_parity_and_origin_kwargs(tmp_path):
    d = await _fresh(tmp_path)
    try:
        # Keyword-only Origin-поля опциональны: legacy-вызовы без них — NULL.
        row_id = await d.save_smart_message(
            42, CHAT_A, "текст", None, 1000, "text", "u")
        cur = await d.db.execute(
            "SELECT origin_type, media_group_id FROM smart_messages "
            "WHERE id=?", (row_id,))
        row = await cur.fetchone()
        assert row["origin_type"] is None and row["media_group_id"] is None
        # Явная передача Origin в legacy-путь (D1: прокинуть новые поля).
        row_id2 = await d.save_smart_message(
            42, CHAT_A, "текст2", None, 1001, "photo", "u",
            origin_type="channel", origin_sent_at=900,
            media_group_id="grp-1")
        cur = await d.db.execute(
            "SELECT origin_type, origin_sent_at, media_group_id FROM "
            "smart_messages WHERE id=?", (row_id2,))
        row = await cur.fetchone()
        assert (row["origin_type"], row["origin_sent_at"],
                row["media_group_id"]) == ("channel", 900, "grp-1")
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_reobserve_does_not_duplicate(tmp_path):
    d = await _fresh(tmp_path)
    try:
        from services.message_identity import save_live_message
        base = dict(chat_id=CHAT_A, tg_message_id=303, user_id=42,
                    text="x", sent_at=111, ingested_at=222)
        id1 = await save_live_message(d, **base, origin_type="user",
                                      origin_sender_user_id=7)
        id2 = await save_live_message(d, **base, origin_type="user",
                                      origin_sender_user_id=7)
        assert id1 == id2
        cur = await d.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages WHERE chat_id=? AND "
            "tg_message_id=303", (CHAT_A,))
        assert (await cur.fetchone())["c"] == 1
    finally:
        await d.close()


# ── T-5101/T-5100: intake-активы (фото/документ/стикер/альбом) ──────────────

@pytest.mark.asyncio
async def test_intake_assets_photo_document_sticker(tmp_path):
    d = await _fresh(tmp_path)
    try:
        photo_msg = _photo_message(tg_id=401)
        doc_msg = Message(
            message_id=402, date=DT, chat=Chat(id=CHAT_A, type="supergroup"),
            from_user=User(id=42, is_bot=False, first_name="В"),
            document=Document(file_id="doc_fid", file_unique_id="doc_uniq",
                              mime_type="image/png", file_size=2048),
        )
        sticker_msg = Message(
            message_id=403, date=DT, chat=Chat(id=CHAT_A, type="supergroup"),
            from_user=User(id=42, is_bot=False, first_name="В"),
            sticker=Sticker(file_id="st_fid", file_unique_id="st_uniq",
                            width=512, height=512, is_animated=False,
                            is_video=False, type="regular"),
        )
        ids = []
        for m in (photo_msg, doc_msg, sticker_msg):
            ids += await mca_vision.register_intake_assets(d, m)
        assert len(ids) == 3
        rows = await d.get_media_assets_for_message(CHAT_A, 401)
        assert len(rows) == 1
        assert rows[0]["asset_kind"] == "photo"
        assert rows[0]["size_variant"] == "large"
        assert rows[0]["message_key"] == f"{CHAT_A}:401"
        kinds = {}
        for tg in (401, 402, 403):
            for r in await d.get_media_assets_for_message(CHAT_A, tg):
                kinds[r["asset_kind"]] = r["asset_kind"]
        assert kinds == {"photo": "photo", "document": "document",
                         "sticker": "sticker"}
        # Поддерживаемость: animation — НЕ в поддерживаемых (честный
        # unsupported у анализа, Wave 2).
        assert mca_vision.ASSET_KIND_ANIMATION not in \
            mca_vision.SUPPORTED_ASSET_KINDS
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_album_each_item_own_asset_shared_group(tmp_path):
    d = await _fresh(tmp_path)
    try:
        # SC-R1a: альбом — каждый item свой asset + общая media_group_id;
        # подпись первого НЕ размножается (caption живёт в smart_messages).
        m1 = _photo_message(tg_id=501, media_group_id="grp-9",
                            caption="подпись первого")
        m2 = _photo_message(tg_id=502, media_group_id="grp-9")
        ids1 = await mca_vision.register_intake_assets(d, m1)
        ids2 = await mca_vision.register_intake_assets(d, m2)
        assert ids1 and ids2 and ids1 != ids2
        rows2 = await d.get_media_assets_for_message(CHAT_A, 502)
        assert rows2[0]["media_group_id"] == "grp-9"
        # Идемпотентный re-observe: повторное наблюдение не дублирует.
        ids1_again = await mca_vision.register_intake_assets(d, m1)
        assert ids1_again == ids1
        cur = await d.db.execute(
            "SELECT COUNT(*) AS c FROM mca_media_assets WHERE chat_id=? "
            "AND media_group_id='grp-9'", (CHAT_A,))
        assert (await cur.fetchone())["c"] == 2
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_intake_assets_master_off_parity(tmp_path, monkeypatch):
    d = await _fresh(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "vision_enabled", lambda: False)
        ids = await mca_vision.register_intake_assets(
            d, _photo_message(tg_id=601))
        assert ids == []
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM mca_media_assets")
        assert (await cur.fetchone())["c"] == 0
    finally:
        await d.close()


# ── analyses: singleflight-примитив / CAS / кеш / кросс-чат изоляция ────────

def _analysis_rec(asset_id, scope, **kw):
    rec = dict(asset_id=asset_id, access_scope=scope,
               analysis_schema_version=1, analyzer_provider="openai_compat",
               analyzer_model="vlm-x", analyzer_config_revision="cfg1",
               prompt_version="vision_v1", quality_profile="default",
               status="pending")
    rec.update(kw)
    return rec


@pytest.mark.asyncio
async def test_analysis_idempotent_upsert_singleflight(tmp_path):
    d = await _fresh(tmp_path)
    try:
        id1 = await d.record_media_analysis(_analysis_rec("a1", "chat:1"))
        id2 = await d.record_media_analysis(_analysis_rec("a1", "chat:1"))
        assert id1 == id2 and id1 > 0
        # Смена модели НЕ инвалидирует: новая гранула (config_revision) —
        # отдельная строка (D19).
        rec2 = _analysis_rec("a1", "chat:1", analyzer_config_revision="cfg2")
        id3 = await d.record_media_analysis(rec2)
        assert id3 != id1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_analysis_cas_stale_discarded(tmp_path):
    d = await _fresh(tmp_path)
    try:
        aid = await d.record_media_analysis(_analysis_rec("a2", "chat:1"))
        row = await d.get_media_analysis(aid)
        assert row["status"] == "pending" and row["revision"] == 1
        # Второй worker (Wave 2) уже завершил с revision=1 → revision=2.
        ok = await d.finish_media_analysis(
            aid, expected_revision=1, status="ready",
            ocr_blocks=[{"text": "привет", "channel": "untrusted_image_data"}],
            visual_description="скрин чата",
            uncertainty=["нижняя строка обрезана"],
            self_reported_confidence=0.8, completed_at=999)
        assert ok is True
        # Stale job (те же revision=1) — отброшен CAS (примитив A66).
        stale = await d.finish_media_analysis(
            aid, expected_revision=1, status="failed", error_reason="late")
        assert stale is False
        row = await d.get_media_analysis(aid)
        assert row["status"] == "ready" and row["revision"] == 2
        assert row["error_reason"] is None       # воскрешения/перезаписи нет
        assert row["completed_at"] == 999
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_success_cache_only_ready_and_scope_isolated(tmp_path):
    d = await _fresh(tmp_path)
    try:
        # Актив в чате A + контент-хеш.
        asset_id = await d.upsert_media_asset({
            "asset_id": "a3", "message_key": f"{CHAT_A}:701",
            "chat_id": CHAT_A, "tg_message_id": 701, "asset_kind": "photo",
            "file_id": "f", "file_unique_id": "u3", "size_variant": "large"})
        rev = await d.set_media_asset_content_hash("a3", "h3")
        assert rev == 2
        # CAS-fencing контент-хеша: ожидание по старому revision — отказ.
        assert await d.set_media_asset_content_hash(
            "a3", "hX", expected_revision=1) is None
        # pending НЕ success-кеш.
        aid = await d.record_media_analysis(_analysis_rec("a3", "chat:A"))
        assert await d.get_ready_analysis(
            "a3", "chat:A", analyzer_config_revision="cfg1") is None
        assert await d.find_ready_analysis_by_content_hash(
            "h3", "chat:A") is None
        await d.finish_media_analysis(aid, expected_revision=1,
                                      status="ready")
        hit = await d.get_ready_analysis(
            "a3", "chat:A", analyzer_config_revision="cfg1")
        assert hit is not None and hit["id"] == aid
        # Кеш по байтам — в пределах scope.
        hit2 = await d.find_ready_analysis_by_content_hash("h3", "chat:A")
        assert hit2 is not None
        # TH-5/SC-R3c (негативный): тот же контент в ДРУГОМ чате не
        # возвращает чужой анализ — ни по грануле, ни по хешу.
        assert await d.get_ready_analysis(
            "a3", "chat:B", analyzer_config_revision="cfg1") is None
        assert await d.find_ready_analysis_by_content_hash(
            "h3", "chat:B") is None
        # Кеш отдаёт содержимое (нейтральное) — автор/дата/пересылка не в нём.
        assert "author" not in (hit2.get("visual_description") or "").lower()
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_message_source_ref_honest(tmp_path):
    d = await _fresh(tmp_path)
    try:
        ref = await mca_vision.message_source_ref(
            d, chat_id=CHAT_A, tg_message_id=999)
        if mca_gates.provenance_enabled():
            assert ref is not None
        else:
            assert ref is None
        # Повтор — дедуп (тот же id), не новая строка.
        ref2 = await mca_vision.message_source_ref(
            d, chat_id=CHAT_A, tg_message_id=999)
        assert ref2 == ref
    finally:
        await d.close()


# ── wrap_media_fact: event-time исходника (T-5100/D1) ───────────────────────

def test_wrap_media_fact_event_time():
    import re
    from handlers.media_common import wrap_media_fact
    now_iso = wrap_media_fact("photo", "Вася", "текст")
    with_event = wrap_media_fact("photo", "Вася", "текст",
                                 event_ts=1764000000)
    # Прежнее поведение (без event_ts) не сломано: timestamp = now (UTC ISO).
    assert re.search(r'timestamp="\d{4}-\d{2}-\d{2}T[\d:.]+\+00:00"', now_iso)
    # Event-time исходника (12:00 ≠ 12:07): время события, не обработки.
    assert 'timestamp="2025-11-24T' in with_event
    # None/битый event_ts → прежнее поведение (now-формат).
    for bad in (None, 0, -5, "x"):
        out = wrap_media_fact("photo", "В", "т", event_ts=bad)
        assert re.search(r'timestamp="\d{4}-\d{2}-\d{2}T', out)
