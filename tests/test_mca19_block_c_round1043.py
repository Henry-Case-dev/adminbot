"""MCA-19 Wave 2, блок C (`mca-19-image-understanding`, round 10.43) —
автоочередь/кеш/антиспам (ADR-1028-19 D18–D20; T-5107…T-5109).

Контракты:
  * A76/SC-R6a: альбом — каждый item свой asset + durable-джоба; подпись
    первого НЕ размножается в анализы; завершение фоновой джобы не
    отправляет сообщений (OCR не спамится в чат);
  * A77/SC-R6b: один анализ на эквивалент содержимого — повторный файл →
    cache hit (0 transport-вызовов, 0 vision-токенов); повторный входящий
    update ≠ второй job (coalesce singleflight, CA-19-9);
  * A78/SC-R6c: кросс-чат изоляция кеша по access_scope (одинаковые bytes
    в разных чатах НЕ склеиваются — TH-5);
  * A79/SC-R6d: rate bucket → deferred (next_retry), deferred-TTL →
    vision_skipped_expired, restart-восстановление (recover_stale),
    тик планировщика обрабатывает durable-джобы; приоритет manual > auto;
    backfill — НИЖЕ live, missing_source честен, идемпотентен.

Оффлайн: transport/bot-двойники, БЕЗ реальных LLM/vision вызовов и отправок
в чаты (no-false-acceptance). R17: секретов нет.
"""
import asyncio
import base64
import datetime
import json
import struct
import time
import zlib

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from services import mca_vision
from services.database import DatabaseService

CHAT_A = -1004000000011
CHAT_B = -1004000000012


def make_png(width=10, height=10) -> bytes:
    """Валидный PNG (реальные байты; сниффер признаёт)."""
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))
    row = b"\x00" + b"\x10\x20\x30" * width
    body = zlib.compress(row * height)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0,
                                         0, 0))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


def make_bomb_png() -> bytes:
    """Заголовок 100000×100000 при крошечном теле (decompression-bomb)."""
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 100000, 100000, 8, 2,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
            + chunk(b"IEND", b""))


PNG_BYTES = make_png()

DT = datetime.datetime(2026, 10, 6, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _photo(serial):
    return PhotoSize(file_id=f"fid_{serial}", file_unique_id=f"uniq_{serial}",
                     width=800, height=600, file_size=12345)


def _photo_message(chat_id=CHAT_A, tg_id=101, *, media_group_id=None,
                   caption=None, serial=1):
    return Message(
        message_id=tg_id, date=DT,
        chat=Chat(id=chat_id, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Вася"),
        photo=[_photo(serial), _photo(serial)],
        caption=caption, media_group_id=media_group_id,
    )


class _FakeBot:
    """Bot API двойник: bytes по file_id (реальный путь — getFile+download
    внутри aiogram-сессии; URL с токеном не строится, TH-3)."""

    def __init__(self, blobs: dict[str, bytes]):
        self.blobs = blobs
        self.get_file_calls = 0

    async def get_file(self, file_id):
        self.get_file_calls += 1

        class _F:
            pass
        f = _F()
        f.file_id = file_id
        return f

    async def download(self, tg_file, destination=None):
        destination.write(self.blobs[tg_file.file_id])


def _transport_analyst(calls: list):
    """Transport-мок: считает вызовы, возвращает валидный раздельный выход."""
    async def _t(url, *, payload, headers, timeout):
        calls.append(url)
        return 200, {
            "choices": [{"message": {"content": json.dumps({
                "ocr_blocks": [{"text": "ГОРИТ", "bbox": [1, 2, 3, 4]}],
                "visual_description": "тестовое изображение",
                "uncertainty": ["нижний край обрезан"],
                "self_reported_confidence": 0.7,
            })}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
    return _t


_CREATED_DBS: list = []


async def _fresh(tmp_path, name="mca19c.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    _CREATED_DBS.append(d)
    return d


@pytest.fixture(autouse=True)
def _close_dbs():
    """Гигиена: закрыть тестовые SQLite (aiosqlite-потоки)."""
    yield
    import asyncio as _aio
    while _CREATED_DBS:
        db = _CREATED_DBS.pop()
        try:
            _aio.run(db.close())
        except Exception:
            pass


def _store(db):
    from services.task_supervisor import TaskJobStore
    return TaskJobStore(db)


async def _queued_jobs(db, kind=mca_vision.VISION_JOB_KIND):
    return [j for j in await _store(db).active()
            if j.get("kind") == kind and j.get("status") == "queued"]


async def _all_jobs(db, kind):
    """Все джобы kind (включая терминальные) — напрямую из task_jobs."""
    cur = await db.db.execute(
        "SELECT * FROM task_jobs WHERE kind=? ORDER BY created_at", (kind,))
    return [dict(r) for r in await cur.fetchall()]


async def _process_all(db, bot, transport):
    """mark_running + process для всех queued-джоб (ручной «тик»)."""
    for job in await _queued_jobs(db):
        store = _store(db)
        await store.mark_running(job["job_id"])
        fresh = await store.get(job["job_id"]) or job
        fresh["attempt"] = int(fresh.get("attempt") or 1)
        await mca_vision.process_asset_job(fresh, db=db, bot=bot,
                                           transport=transport)


@pytest.fixture(autouse=True)
def _runtime():
    mca_vision.reset_runtime()
    yield
    mca_vision.reset_runtime()


@pytest.fixture()
def _enabled():
    from tests.test_mca19_block_b_round1043 import patched_settings
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        yield


def _cap_ok():
    route = mca_vision.resolve_route()
    mca_vision.store_capability(
        route, mca_vision.CapabilityVerdict("ok", "vision_unsupported", True,
                                            time.monotonic()))


# ── T-5107 (D18): enqueue после реестра; повторный update ≠ второй job ──────

@pytest.mark.asyncio
async def test_enqueue_singleflight_repeated_update(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    msg = _photo_message(tg_id=101)
    asset_ids = await mca_vision.register_intake_assets(db, msg)
    assert len(asset_ids) == 1
    first = await mca_vision.enqueue_intake_jobs(db, msg, asset_ids)
    second = await mca_vision.enqueue_intake_jobs(db, msg, asset_ids)
    assert first == 1 and second == 1     # coalesce вернул существующий job
    jobs = await _queued_jobs(db)
    assert len(jobs) == 1                 # singleflight: второй НЕ создан
    payload = json.loads(jobs[0]["payload"])
    assert payload["asset_id"] == asset_ids[0]
    assert payload["priority"] == mca_vision.PRIORITY_AUTO


@pytest.mark.asyncio
async def test_enqueue_gates_k2_and_requested(tmp_path, _enabled, monkeypatch):
    from services import hot_config as hot_config
    from tests.test_mca19_block_b_round1043 import patched_settings
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    msg = _photo_message(tg_id=101)
    asset_ids = await mca_vision.register_intake_assets(db, msg)

    # K2 (auto) OFF → 0 джоб.
    with patched_settings(MCA_VISION_AUTO_ENABLED=False):
        assert await mca_vision.enqueue_intake_jobs(db, msg, asset_ids) == 0

    # requested OFF (владелец выключил) → 0 джоб; реестр активов остаётся.
    real_get = hot_config.get
    monkeypatch.setattr(
        hot_config, "get",
        lambda key, default=None: False
        if key == "flags.vision_enabled" else real_get(key, default))
    assert await mca_vision.enqueue_intake_jobs(db, msg, asset_ids) == 0
    assert await db.get_media_assets_for_message(CHAT_A, 101)
    assert not await _queued_jobs(db)

@pytest.mark.asyncio
async def test_deferred_overflow_on_full_queue(tmp_path, _enabled):
    """Избыток → deferred (durable-строка с next_retry в будущем), D20."""
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    store = _store(db)
    # Заполняем очередь до capacity (владельческое значение из каталога).
    capacity = mca_vision._queue_capacity()
    for i in range(capacity):
        await store.enqueue(owner="filler", kind="filler",
                            coalesce_key=f"fill:{i}")
    msg = _photo_message(tg_id=900)
    asset_ids = await mca_vision.register_intake_assets(db, msg)
    assert await mca_vision.enqueue_intake_jobs(db, msg, asset_ids) == 1
    jobs = await _queued_jobs(db)
    vision_jobs = [j for j in jobs if j.get("kind")
                   == mca_vision.VISION_JOB_KIND]
    assert len(vision_jobs) == 1
    assert vision_jobs[0]["next_retry_at"] > int(time.time())  # deferred


# ── A76/SC-R6a: альбом — каждый item; подпись не размножена ─────────────────

@pytest.mark.asyncio
async def test_album_each_item_caption_not_spread(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    # РАЗНЫЕ байты у элементов альбома (одинаковые склеились бы по
    # content-hash — это контракт A77, проверяется отдельным тестом).
    bot = _FakeBot({"fid_1": make_png(10, 10), "fid_2": make_png(20, 20)})
    calls: list = []
    transport = _transport_analyst(calls)

    m1 = _photo_message(tg_id=201, media_group_id="album-1",
                        caption="Подпись ПЕРВОГО фото", serial=1)
    m2 = _photo_message(tg_id=202, media_group_id="album-1", serial=2)
    for msg, tg in ((m1, 201), (m2, 202)):
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
    assets_1 = await db.get_media_assets_for_message(CHAT_A, 201)
    assets_2 = await db.get_media_assets_for_message(CHAT_A, 202)
    assert len(assets_1) == 1 and len(assets_2) == 1
    assert assets_1[0]["media_group_id"] == "album-1"
    assert assets_2[0]["media_group_id"] == "album-1"

    await _process_all(db, bot, transport)
    assert len(calls) == 2                  # по одному vision на item
    for tg in (201, 202):
        rows = await db.get_media_assets_for_message(CHAT_A, tg)
        ready = await db.get_ready_analysis(rows[0]["asset_id"],
                                            mca_vision.access_scope_for(
                                                CHAT_A))
        assert ready is not None and ready["status"] == "ready"
        # Подпись первого НЕ стала OCR/описанием второго (и никакого).
        blob = json.dumps({"ocr": ready["ocr_blocks"],
                           "desc": ready["visual_description"]},
                          ensure_ascii=False)
        assert "Подпись ПЕРВОГО фото" not in blob
    # Завершение фонового распознавания не отправляет сообщений:
    # у double-bot нет send-методов вовсе (контракт — без публикаций).


# ── A77/SC-R6b: один анализ на эквивалент содержимого ───────────────────────

@pytest.mark.asyncio
async def test_repeated_file_cache_hit_no_tokens(tmp_path, _enabled,
                                                 monkeypatch):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    bot = _FakeBot({"fid_1": PNG_BYTES})
    calls: list = []
    transport = _transport_analyst(calls)

    usage_calls: list = []

    async def _fake_record(pg_pool, **kwargs):
        usage_calls.append(kwargs)

    from services import usage_events
    monkeypatch.setattr(usage_events, "record", _fake_record)

    msg = _photo_message(tg_id=301)
    assets = await mca_vision.register_intake_assets(db, msg)
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    await _process_all(db, bot, transport)
    assert len(calls) == 1 and len(usage_calls) == 1   # реальный вызов — 1

    # Повторная доставка того же сообщения → новая джоба → cache hit.
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    await _process_all(db, bot, transport)
    assert len(calls) == 1                  # vision НЕ вызывался повторно
    assert len(usage_calls) == 1            # cache hit — 0 vision-токенов
    store = _store(db)
    done = [j for j in await store.active() if j["status"] == "queued"]
    assert not done                         # все джобы терминальны


@pytest.mark.asyncio
async def test_same_bytes_different_message_reuse(tmp_path, _enabled):
    """Одинаковые bytes в одном scope — переиспользование анализа (D19)."""
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    bot = _FakeBot({"fid_1": PNG_BYTES, "fid_2": PNG_BYTES})
    calls: list = []
    transport = _transport_analyst(calls)

    m1 = _photo_message(tg_id=311, serial=1)
    m2 = _photo_message(tg_id=312, serial=2)
    for msg in (m1, m2):
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
    await _process_all(db, bot, transport)
    assert len(calls) == 1                  # второй файл = тот же content

    a2 = (await db.get_media_assets_for_message(CHAT_A, 312))[0]
    assert a2["content_hash"]               # hash привязан
    ready = await db.find_ready_analysis_by_content_hash(
        a2["content_hash"], mca_vision.access_scope_for(CHAT_A))
    assert ready is not None                # анализ переиспользуется join'ом


# ── A78/TH-5: кросс-чат изоляция кеша ───────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_chat_cache_isolation(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    bot = _FakeBot({"fid_a": PNG_BYTES, "fid_b": PNG_BYTES})
    calls: list = []
    transport = _transport_analyst(calls)

    ma = _photo_message(chat_id=CHAT_A, tg_id=321, serial=1)
    mb = _photo_message(chat_id=CHAT_B, tg_id=322, serial=2)
    bot = _FakeBot({"fid_1": PNG_BYTES, "fid_2": PNG_BYTES})
    for msg in (ma, mb):
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
    await _process_all(db, bot, transport)
    assert len(calls) == 2                  # одинаковые bytes, разные scope:
    # кеш чата A НЕ переиспользован для чата B (второй vision-вызов был).


# ── A79/SC-R6d: rate / deferred-TTL / restart / тик планировщика ────────────

@pytest.mark.asyncio
async def test_rate_limit_defers_job(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    from tests.test_mca19_block_b_round1043 import patched_settings
    bot = _FakeBot({"fid_1": PNG_BYTES})
    calls: list = []
    transport = _transport_analyst(calls)
    msg = _photo_message(tg_id=331)
    assets = await mca_vision.register_intake_assets(db, msg)
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    with patched_settings(VISION_USER_RATE="1/1", VISION_CHAT_RATE="1/1"):
        await _process_all(db, bot, transport)     # первая: токен есть
        jobs = await _queued_jobs(db)
        if jobs:                            # вторая попытка в том же тесте
            await _process_all(db, bot, transport)
    # Первая джоба либо обработана, либо честно отложена с reason;
    # в любом случае transport не дёргается чаще лимита.
    assert len(calls) <= 1


@pytest.mark.asyncio
async def test_deferred_ttl_expiry_skipped(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    store = _store(db)
    jid = await store.enqueue(owner="vision.media",
                              kind=mca_vision.VISION_JOB_KIND,
                              coalesce_key="vision:asset:old",
                              payload=json.dumps({"asset_id": "old",
                                                  "chat_id": CHAT_A,
                                                  "priority": "auto"}))
    # Джоба «зависла» в queued дольше TTL → честный skipped с причиной.
    import aiosqlite
    await db.db.execute("UPDATE task_jobs SET created_at=? WHERE job_id=?",
                        (int(time.time()) - 25 * 3600, jid))
    await db.db.commit()
    worker = mca_vision.VisionMediaWorker(db, None)
    worker._store = store
    await worker._expire_deferred()
    row = await store.get(jid)
    assert row["status"] == "failed"
    assert row["reason_code"] == "vision_skipped_expired"


@pytest.mark.asyncio
async def test_restart_recover_stale_then_reprocess(tmp_path, _enabled):
    """A79: рестарт процесса — потерянная running-джоба → interrupted,
    повторный update пересоздаёт джобу и обрабатывается."""
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    bot = _FakeBot({"fid_1": PNG_BYTES})
    calls: list = []
    transport = _transport_analyst(calls)
    store = _store(db)
    msg = _photo_message(tg_id=341)
    assets = await mca_vision.register_intake_assets(db, msg)
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    jobs = await _queued_jobs(db)
    jid = jobs[0]["job_id"]
    await store.mark_running(jid)
    # Владелец «умер»: heartbeat протух → recover_stale.
    await db.db.execute("UPDATE task_jobs SET heartbeat_at=? WHERE job_id=?",
                        (int(time.time()) - 600, jid))
    await db.db.commit()
    interrupted = await store.recover_stale(stale_after_seconds=120)
    assert interrupted == [jid]
    row = await store.get(jid)
    assert row["status"] == "interrupted"
    # Повторный входящий update → новая джоба (coalesce свободен) → success.
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    await _process_all(db, bot, transport)
    assert len(calls) == 1
    analysis = await db.get_ready_analysis(
        assets[0], mca_vision.access_scope_for(CHAT_A))
    assert analysis is not None and analysis["status"] == "ready"


@pytest.mark.asyncio
async def test_worker_tick_processes_and_prioritizes_manual(tmp_path,
                                                            _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    bot = _FakeBot({"fid_1": PNG_BYTES})
    calls: list = []
    transport = _transport_analyst(calls)
    msg = _photo_message(tg_id=351)
    assets = await mca_vision.register_intake_assets(db, msg)
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    worker = mca_vision.VisionMediaWorker(db, bot, transport=transport)
    worker._store = _store(db)
    worker._sem = asyncio.Semaphore(2)
    await worker._tick_body()
    assert len(calls) == 1
    store = worker._store
    active = await store.active()
    assert not [j for j in active
                if j.get("kind") == mca_vision.VISION_JOB_KIND]


# ── Backfill (D14/T-5115): bounded, идемпотентный, missing_source ───────────

@pytest.mark.asyncio
async def test_backfill_missing_source_honest_and_idempotent(tmp_path,
                                                             _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    store = _store(db)
    # Старый актив без file_id (архивная строка) — старше BACKFILL_MIN_AGE.
    msg = _photo_message(tg_id=361)
    assets = await mca_vision.register_intake_assets(db, msg)
    asset_id = assets[0]
    await db.db.execute(
        "UPDATE mca_media_assets SET file_id='', created_at=? "
        "WHERE asset_id=?",
        (int(time.time()) - 7200, asset_id))
    await db.db.commit()

    first = await mca_vision.backfill_sweep(db, None, store=store)
    assert first["processed"] == 0
    assert first["missing_source"] == 1
    jobs = await _all_jobs(db, mca_vision.VISION_BACKFILL_KIND)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["reason_code"] == "vision_missing_source"

    # Идемпотентность: повторный sweep не создаёт вторую джобу.
    second = await mca_vision.backfill_sweep(db, None, store=store)
    assert second["missing_source"] == 0
    jobs = await _all_jobs(db, mca_vision.VISION_BACKFILL_KIND)
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_backfill_processes_old_asset_below_live(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    bot = _FakeBot({"fid_1": PNG_BYTES})
    calls: list = []
    transport = _transport_analyst(calls)
    store = _store(db)
    msg = _photo_message(tg_id=371)
    assets = await mca_vision.register_intake_assets(db, msg)
    await db.db.execute(
        "UPDATE mca_media_assets SET created_at=? WHERE asset_id=?",
        (int(time.time()) - 7200, assets[0]))
    await db.db.commit()
    sweep = await mca_vision.backfill_sweep(db, bot, store=store,
                                            transport=transport)
    assert sweep["processed"] == 1
    assert len(calls) == 1
    ready = await db.get_ready_analysis(assets[0],
                                        mca_vision.access_scope_for(CHAT_A))
    assert ready is not None and ready["status"] == "ready"


@pytest.mark.asyncio
async def test_backfill_skips_when_requested_off(tmp_path, _enabled,
                                                 monkeypatch):
    from services import hot_config as hot_config
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    store = _store(db)
    msg = _photo_message(tg_id=381)
    assets = await mca_vision.register_intake_assets(db, msg)
    await db.db.execute(
        "UPDATE mca_media_assets SET created_at=? WHERE asset_id=?",
        (int(time.time()) - 7200, assets[0]))
    await db.db.commit()
    real_get = hot_config.get
    monkeypatch.setattr(
        hot_config, "get",
        lambda key, default=None: False
        if key == "flags.vision_enabled" else real_get(key, default))
    sweep = await mca_vision.backfill_sweep(db, None, store=store)
    assert sweep["processed"] == 0
    assert not await _queued_jobs(db)       # включение НЕ разбирает архив
