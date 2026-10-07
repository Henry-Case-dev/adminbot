"""MCA-17 (`mca17-perimeter`, W1-C3) — focused-тесты новых emit §17.1.

Покрытие терминальных исходов и fail-open для процессов группы
«Ingest, планировщики и периметр»: ingestion.live, ingestion.import,
chat.lifecycle, goodmorning.run, media.download, image.generate (deliver),
factcheck.run, maintenance.retention, backup.memory.

uptime.heartbeat — сознательно НЕ инструментируется (собственный журнал
uptime_events PG); scheduler.reactions — due_check-воркера в коде нет
(аменд реестра — merge-лейн).

R17: события переносят только id/счётчики/коды/длительность.
"""
import asyncio
import datetime
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message, User

from services import mca_events
from services.database import DatabaseService


def _events(name: str) -> list[dict]:
    return [e for e in mca_events._pending
            if e.get("event_name") == name]


def _last(name: str) -> dict:
    evs = _events(name)
    assert evs, f"событие {name} не эмитировано"
    return evs[-1]


@pytest.fixture(autouse=True)
def _reset_events():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


# ── ingestion.live (handlers/summary.py) ─────────────────────────────────────

def _make_message() -> Message:
    now = datetime.datetime.now()
    return Message(
        message_id=77,
        date=now,
        chat=Chat(id=-1003000000099, type="group"),
        from_user=User(id=42, is_bot=False, first_name="Аня"),
        text="привет из теста",
    )


@pytest.mark.asyncio
async def test_ingestion_live_success_emit_after_persist():
    import handlers.summary as hs
    msg = _make_message()
    saved = AsyncMock(return_value=1)
    with patch.object(hs, "_db", MagicMock()), \
            patch.object(hs, "_aliases", MagicMock()), \
            patch.object(hs, "_bot_id", None), \
            patch.object(hs, "record_media_group_message", MagicMock()), \
            patch.object(hs.message_identity, "save_live_message", saved), \
            patch("services.mca_vision.register_intake_assets",
                  AsyncMock(return_value=[])), \
            patch("services.mca_vision.enqueue_intake_jobs", AsyncMock()):
        result = await hs.summary_observer(msg)
    assert result.name == "UNHANDLED"
    ev = _last("ingestion_live")
    assert ev["outcome"] == "success"
    assert int(ev["chat_id"]) == -1003000000099
    assert int(ev["message_id"]) == 77
    assert isinstance(ev.get("duration_ms"), int)
    saved.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingestion_live_failed_emit_on_persist_error():
    import handlers.summary as hs
    msg = _make_message()
    with patch.object(hs, "_db", MagicMock()), \
            patch.object(hs, "_aliases", MagicMock()), \
            patch.object(hs, "_bot_id", None), \
            patch.object(hs, "record_media_group_message", MagicMock()), \
            patch.object(hs.message_identity, "save_live_message",
                         AsyncMock(side_effect=RuntimeError("db down"))), \
            patch("services.mca_vision.register_intake_assets",
                  AsyncMock(return_value=[])), \
            patch("services.mca_vision.enqueue_intake_jobs", AsyncMock()):
        result = await hs.summary_observer(msg)
    assert result.name == "UNHANDLED"        # observer не роняет поток
    ev = _last("ingestion_live")
    assert ev["outcome"] == "failed"
    assert ev["level"] == "WARN"


@pytest.mark.asyncio
async def test_ingestion_live_emit_fail_open():
    """Телеметрия сломана → основной путь не рвётся (fail-open §17.1)."""
    import handlers.summary as hs
    msg = _make_message()
    with patch.object(hs, "_db", MagicMock()), \
            patch.object(hs, "_aliases", MagicMock()), \
            patch.object(hs, "_bot_id", None), \
            patch.object(hs, "record_media_group_message", MagicMock()), \
            patch.object(hs.message_identity, "save_live_message",
                         AsyncMock(return_value=1)), \
            patch("services.mca_vision.register_intake_assets",
                  AsyncMock(return_value=[])), \
            patch("services.mca_vision.enqueue_intake_jobs", AsyncMock()), \
            patch("services.mca_events.emit_mca_event",
                  side_effect=RuntimeError("telemetry boom")):
        result = await hs.summary_observer(msg)
    assert result.name == "UNHANDLED"


# ── chat.lifecycle (handlers/chat_lifecycle.py) ──────────────────────────────

@pytest.mark.asyncio
async def test_chat_id_migration_success_emit():
    import handlers.chat_lifecycle as lc
    msg = MagicMock()
    msg.chat.id = -100111
    msg.migrate_to_chat_id = -100222
    with patch.object(lc, "_db", MagicMock()), \
            patch.object(lc, "_store", AsyncMock()), \
            patch("services.message_identity.register_chat_id_migration",
                  AsyncMock(return_value=1)):
        await lc.on_chat_migrated(msg)
    ev = _last("chat_id_migration")
    assert ev["outcome"] == "success"
    assert int(ev["chat_id"]) == -100222
    assert json.loads(ev["entity_ids"])["old_chat_id"] == -100111


@pytest.mark.asyncio
async def test_chat_id_migration_failed_emit():
    import handlers.chat_lifecycle as lc
    msg = MagicMock()
    msg.chat.id = -100111
    msg.migrate_to_chat_id = -100222
    with patch.object(lc, "_db", MagicMock()), \
            patch.object(lc, "_store", AsyncMock()), \
            patch("services.message_identity.register_chat_id_migration",
                  AsyncMock(side_effect=RuntimeError("pg down"))):
        await lc.on_chat_migrated(msg)      # fail-open: хендлер не падает
    ev = _last("chat_id_migration")
    assert ev["outcome"] == "failed"
    assert ev["level"] == "WARN"


# ── ingestion.import (tools/history_import/loader.py) ────────────────────────

@pytest.mark.asyncio
async def test_import_batch_failed_emit_notable():
    from tools.history_import import loader
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=RuntimeError("db down"))
    fr = loader.FileResult(path="export.json", read=3)
    msg = {"user_id": 1, "chat_id": -100, "text": "x", "reply_to_id": None,
           "timestamp": 1700000000, "media_type": "text", "author_name": "a",
           "is_forward": False, "forward_source": "", "import_key": "k1"}
    with pytest.raises(RuntimeError):
        await loader._flush_batch(conn, fr, [msg], "export.json", None, -100)
    ev = _last("import_history_batch")
    assert ev["outcome"] == "failed"
    assert ev["level"] == "WARN"
    assert json.loads(ev["usage_json"])["read"] == 3


@pytest.mark.asyncio
async def test_import_history_fts_terminal_success(tmp_path):
    from tools.history_import.loader import import_history_fts
    d = DatabaseService(str(tmp_path / "imp.db"))
    await d.initialize()
    try:
        export = tmp_path / "result.json"
        export.write_text(json.dumps({
            "name": "Export", "id": 42,
            "messages": [
                {"type": "message", "id": 1, "date_unixtime": 1700000000,
                 "text": "привет", "from_id": "user1", "from": "Аня"},
                {"type": "service", "id": 2, "date_unixtime": 1700000100,
                 "text": "создан чат"},
            ],
        }), encoding="utf-8")
        summary = await import_history_fts(str(d.db_path), [str(export)],
                                           -100999)
        assert summary["inserted"] == 1
        ev = _last("import_history_fts")
        assert ev["outcome"] == "success"
        usage = json.loads(ev["usage_json"])
        assert usage["inserted"] == 1
        assert usage["files"] == 1
        assert int(ev["chat_id"]) == -100999
    finally:
        await d.close()


# ── goodmorning.run (services/goodmorning_scheduler.py) ──────────────────────

def _gm_service(relay, targets):
    from services.goodmorning_scheduler import GoodmorningSchedulerService
    return GoodmorningSchedulerService(relay, "07:00", "UTC", targets)


@pytest.mark.asyncio
async def test_goodmorning_run_success_and_silent_and_skipped():
    from services import permsoc
    relay = AsyncMock()
    relay.send_goodmorning.return_value = True
    svc = _gm_service(relay, (-1001, -1002))
    with patch.object(permsoc, "block_enabled", AsyncMock(return_value=True)):
        await svc._tick()
    ev = _last("goodmorning_run")
    assert ev["outcome"] == "success"
    assert json.loads(ev["usage_json"])["sent"] == 2

    mca_events.reset_pending()
    relay2 = AsyncMock()
    relay2.send_goodmorning.return_value = False   # папка релея пуста
    svc2 = _gm_service(relay2, (-1001,))
    with patch.object(permsoc, "block_enabled", AsyncMock(return_value=True)):
        await svc2._tick()
    assert _last("goodmorning_run")["outcome"] == "silent"

    mca_events.reset_pending()
    svc3 = _gm_service(AsyncMock(), ())
    await svc3._tick()
    ev3 = _last("goodmorning_run")
    assert ev3["outcome"] == "skipped"
    assert ev3["reason_code"] == "disabled"


@pytest.mark.asyncio
async def test_goodmorning_run_failed_emit_on_delivery_error():
    from services import permsoc
    relay = AsyncMock()
    relay.send_goodmorning.side_effect = RuntimeError("telegram down")
    svc = _gm_service(relay, (-1001,))
    with patch.object(permsoc, "block_enabled", AsyncMock(return_value=True)):
        await svc._tick()                    # fail-open: тик не падает
    ev = _last("goodmorning_run")
    assert ev["outcome"] == "failed"
    assert ev["level"] == "WARN"
    assert ev["reason_code"] == "delivery_unknown"
    assert json.loads(ev["usage_json"])["failed"] == 1


# ── media.download (tools/video_downloader.py) ───────────────────────────────

@pytest.mark.asyncio
async def test_media_download_success_emit(tmp_path):
    from tools import video_downloader as vd
    svc = vd.VideoDownloader("http://cobalt.invalid", str(tmp_path))
    out = tmp_path / "f.mp4"
    out.write_bytes(b"x")

    async def _direct(url, progress_cb=None):
        return out

    with patch.object(vd, "is_direct_media_url", return_value=True):
        svc.download_direct = _direct
        assert await svc.download("http://x/file.mp4") == out
    ev = _last("media_download")
    assert ev["outcome"] == "success"
    assert isinstance(ev.get("duration_ms"), int)


@pytest.mark.asyncio
async def test_media_download_busy_skipped_and_failed_reason_map(tmp_path):
    from tools import video_downloader as vd
    svc = vd.VideoDownloader("http://cobalt.invalid", str(tmp_path))
    await svc._lock.acquire()
    try:
        with pytest.raises(vd.DownloadBusyError):
            await svc.download("http://x/file.mp4")
    finally:
        svc._lock.release()
    ev = _last("media_download")
    assert ev["outcome"] == "skipped"
    assert ev["reason_code"] == "queue_busy"

    mca_events.reset_pending()

    async def _boom(url, progress_cb=None):
        raise vd.DownloadTooBigError("too big", reason="direct_too_big")

    with patch.object(vd, "is_direct_media_url", return_value=True):
        svc.download_direct = _boom
        with pytest.raises(vd.DownloadTooBigError):
            await svc.download("http://x/file.mp4")
    ev2 = _last("media_download")
    assert ev2["outcome"] == "failed"
    assert ev2["level"] == "WARN"
    assert ev2["reason_code"] == "too_many_bytes"


@pytest.mark.asyncio
async def test_media_download_unexpected_exception_no_invented_reason(tmp_path):
    from tools import video_downloader as vd
    svc = vd.VideoDownloader("http://cobalt.invalid", str(tmp_path))

    async def _bug(url, progress_cb=None):
        raise ZeroDivisionError("defect")

    with patch.object(vd, "is_direct_media_url", return_value=True):
        svc.download_direct = _bug
        with pytest.raises(ZeroDivisionError):
            await svc.download("http://x/file.mp4")
    ev = _last("media_download")
    assert ev["outcome"] == "failed"
    assert "reason_code" not in ev          # код не выдумывается
    assert "error_json" in ev


# ── image.generate deliver (services/image_generation.py) ────────────────────

@pytest.mark.asyncio
async def test_image_generate_success_and_deny_and_send_failed():
    import services.image_generation as ig
    with patch.object(ig, "_reserve_or_consume",
                      AsyncMock(return_value=("reserve", "key", "ok"))), \
            patch.object(ig, "generate",
                         AsyncMock(return_value=ig.GenerationResult(
                             ok=True, content=b"img"))), \
            patch("services.telegram_send.send_photo", AsyncMock()):
        res = await ig.generate_and_send(AsyncMock(), -100, "котик")
    assert res.ok is True
    ev = _last("image_generate")
    assert ev["outcome"] == "success"
    assert int(ev["chat_id"]) == -100

    mca_events.reset_pending()
    with patch.object(ig, "_reserve_or_consume",
                      AsyncMock(return_value=("deny", "", "budget"))):
        res = await ig.generate_and_send(AsyncMock(), -100, "котик")
    assert res.ok is False
    ev = _last("image_generate")
    assert ev["outcome"] == "skipped"
    assert ev["reason_code"] == "financial_limit_reached"

    mca_events.reset_pending()
    with patch.object(ig, "_reserve_or_consume",
                      AsyncMock(return_value=("reserve", "key", "ok"))), \
            patch.object(ig, "generate",
                         AsyncMock(return_value=ig.GenerationResult(
                             ok=True, content=b"img"))), \
            patch("services.telegram_send.send_photo",
                  AsyncMock(side_effect=RuntimeError("tg down"))):
        res = await ig.generate_and_send(AsyncMock(), -100, "котик")
    assert res.reason == "send_failed"
    ev = _last("image_generate")
    assert ev["outcome"] == "failed"
    assert ev["reason_code"] == "delivery_unknown"


@pytest.mark.asyncio
async def test_image_generate_generation_failed_and_already():
    import services.image_generation as ig
    with patch.object(ig, "_reserve_or_consume",
                      AsyncMock(return_value=("reserve", "key", "ok"))), \
            patch.object(ig, "generate",
                         AsyncMock(return_value=ig.GenerationResult(
                             ok=False, reason="timeout"))):
        res = await ig.generate_and_send(AsyncMock(), -100, "котик")
    assert res.ok is False
    ev = _last("image_generate")
    assert ev["outcome"] == "failed"
    assert ev["reason_code"] == "timeout"

    mca_events.reset_pending()
    with patch.object(ig, "_reserve_or_consume",
                      AsyncMock(return_value=("already_ok", "key", "already"))):
        res = await ig.generate_and_send(AsyncMock(), -100, "котик")
    assert res.ok is True and res.reason == "already"
    ev = _last("image_generate")
    assert ev["outcome"] == "skipped"
    assert ev["reason_code"] == "action_idempotent_replay"


# ── factcheck.run (services/factcheck_service.py) ────────────────────────────

def _factcheck_service():
    from services.factcheck_service import FactCheckService
    agg = AsyncMock()
    agg.search.return_value = "поисковая выдача"
    return FactCheckService(agg, AsyncMock())


def _factcheck_settings_off():
    """Stub settings: System2 OFF + лимит (Settings — frozen dataclass)."""
    from types import SimpleNamespace
    return SimpleNamespace(SYSTEM2_FACTCHECK_ENABLED=False,
                           FACTCHECK_MAX_SYMBOLS=3000)


@pytest.mark.asyncio
async def test_factcheck_run_success_emit():
    from services import factcheck_service as fs
    svc = _factcheck_service()
    svc._invoke_llm = AsyncMock(return_value=("вердикт чистый", False))
    with patch.object(fs, "settings", _factcheck_settings_off()):
        out = await svc.check_claim("утверждение", chat_id=-77)
    assert "вердикт" in out
    ev = _last("factcheck_run")
    assert ev["outcome"] == "success"
    assert int(ev["chat_id"]) == -77
    assert isinstance(ev.get("duration_ms"), int)


@pytest.mark.asyncio
async def test_factcheck_run_failed_reason_map():
    from services.factcheck_service import FactCheckService
    from services.llm_client import LLMError
    from services.search_aggregator import AllSearchEnginesFailedException
    svc = _factcheck_service()
    svc.aggregator.search = AsyncMock(
        side_effect=AllSearchEnginesFailedException("no engines"))
    with pytest.raises(AllSearchEnginesFailedException):
        await svc.check_claim("утверждение", chat_id=-77)
    ev = _last("factcheck_run")
    assert ev["outcome"] == "failed"
    assert ev["reason_code"] == "provider_unavailable"

    mca_events.reset_pending()
    svc2 = _factcheck_service()
    svc2._invoke_llm = AsyncMock(side_effect=LLMError("model down"))
    with pytest.raises(LLMError):
        await svc2.check_claim("утверждение", chat_id=-77)
    ev2 = _last("factcheck_run")
    assert ev2["outcome"] == "failed"
    assert ev2["reason_code"] == "model_unavailable"


@pytest.mark.asyncio
async def test_factcheck_run_distinct_from_temporal_events():
    """factcheck_run — отдельная ось: temporal-события mca-20 не эмитятся
    этим путём (пайплайн 10.22 — legacy verify, не check_claim_envelope)."""
    from services import factcheck_service as fs
    svc = _factcheck_service()
    svc._invoke_llm = AsyncMock(return_value=("вердикт", False))
    with patch.object(fs, "settings", _factcheck_settings_off()):
        await svc.check_claim("утверждение", chat_id=-77)
    names = {e.get("event_name") for e in mca_events._pending}
    assert "factcheck_run" in names
    assert "factcheck_temporal" not in names


# ── maintenance.retention (services/disk_retention.py) ───────────────────────

def test_retention_success_and_skip_and_silent(tmp_path):
    from services import disk_retention as dr
    base = tmp_path / "backup"
    base.mkdir()
    old = base / "snap_nonhistory.jsonl"
    old.write_text('{"foo": 1}\n', encoding="utf-8")
    stale = datetime.datetime.now().timestamp() - 400 * 86400
    os.utime(old, (stale, stale))
    fresh_db = base / "local_database_20261007.db"
    fresh_db.write_bytes(b"\x00" * 32)      # свежий валидный бэкап

    plan = dr.plan_cleanup([str(base)])
    assert plan, "jsonl старше окна должен попасть в план"
    out = dr.apply_cleanup(plan, dirs=[str(base)])
    assert out["deleted"] >= 1
    ev = _last("maintenance_retention")
    assert ev["outcome"] == "success"
    usage = json.loads(ev["usage_json"])
    assert usage["deleted"] >= 1
    assert usage["bytes_freed"] >= 1

    # fail-closed abort → skipped с существующим кодом
    mca_events.reset_pending()
    plan2 = [{"path": str(base / "missing.jsonl"),
              "category": "jsonl_retention", "reason": "jsonl_old",
              "bytes": 1}]
    out2 = dr.apply_cleanup(plan2, dirs=[str(tmp_path)])   # бэкапа нет
    assert out2["aborted_reason"] == "no_valid_backup"
    ev2 = _last("maintenance_retention")
    assert ev2["outcome"] == "skipped"
    assert ev2["reason_code"] == "cleanup_deferred_dependency_unverified"

    # пустой план → silent
    mca_events.reset_pending()
    dr.apply_cleanup([])
    assert _last("maintenance_retention")["outcome"] == "silent"


# ── backup.memory (services/memory_backup.py) ────────────────────────────────

def _backup_db(row):
    db = MagicMock()
    cursor = AsyncMock()
    cursor.fetchone.return_value = row
    db.db.execute = AsyncMock(return_value=cursor)
    return db


@pytest.mark.asyncio
async def test_backup_memory_success_and_skipped():
    from services.memory_backup import MemoryBackupService
    svc = MemoryBackupService(_backup_db((5,)))
    svc._backup_db = AsyncMock()
    svc._export_facts = AsyncMock()
    svc._rotate = MagicMock()
    await svc.backup_and_export()
    ev = _last("memory_backup")
    assert ev["outcome"] == "success"
    svc._rotate.assert_called_once()

    mca_events.reset_pending()
    svc2 = MemoryBackupService(_backup_db((0,)))
    await svc2.backup_and_export()
    ev2 = _last("memory_backup")
    assert ev2["outcome"] == "skipped"


@pytest.mark.asyncio
async def test_backup_memory_failed_emit_on_job_error():
    from services.memory_backup import MemoryBackupService
    db = _backup_db((5,))
    svc = MemoryBackupService(db)
    svc._backup_db = AsyncMock(side_effect=RuntimeError("vacuum failed"))
    await svc._tick()                        # fail-open: job не роняет бот
    ev = _last("memory_backup")
    assert ev["outcome"] == "failed"
    assert ev["level"] == "WARN"
    assert "error_json" in ev
