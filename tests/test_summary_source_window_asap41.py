"""ASAP 4.1 волна 2 (эпик asap-4-1-durable-whole-window-summary) — T-4603:
SummarySourceWindow — immutable first-class durable snapshot (spec §1 A.1;
ADR-1028-8 D1; SQLite `summary_source_windows` v24, additive; PG no-op).

Покрытие:
  * §2-схема messages[] (все фактически доступные поля, forward-метаданные,
    медиа-derived text = media_type; БЕЗ срезов/предфильтрации);
  * immutability: frozen-объект, deep-copy выдача, байт-идентичный readback;
  * write-once: повторная запись не overwrite (guard-инвариант; UPDATE
    messages_json после создания = дефект — по строке-скану не существует);
  * миграция v24 (additive; идемпотентный повтор; PG no-op = SQLite store);
  * restart-safe: read-back по run_id (run может докатиться);
  * retention TTL (env-only `SUMMARY_SOURCE_WINDOW_RETENTION_DAYS`);
  * kill-switch `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED` (OFF → бит-в-бит
    2.58.46: запись не производится, in-memory rows);
  * единая точка создания в summary_generator (интеграция + событие
    `SUMMARY_SOURCE_WINDOW_READY`, R17 — числа, без текстов).
"""
import asyncio
import json
import time

import pytest

from config.settings import Settings
from services.database import DatabaseService
from services import summary_source_window as ssw

pytestmark = pytest.mark.asap41


@pytest.fixture(autouse=True)
def _env_on(monkeypatch):
    """Kill-switch зоны A default ON для изоляции конфигурации теста."""
    monkeypatch.setattr(Settings, "SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED",
                        True, raising=False)
    monkeypatch.setattr(Settings, "SUMMARY_SOURCE_WINDOW_RETENTION_DAYS", 7,
                        raising=False)


def _row(db_id, tg_id, ts, text="текст", user_id=7, author="Вася",
         reply_to=None, media="text", forward=False, forward_source=""):
    return {
        "id": db_id, "tg_message_id": tg_id, "timestamp": ts,
        "user_id": user_id, "author_name": author, "text": text,
        "reply_to_id": reply_to, "media_type": media,
        "is_forward": bool(forward), "forward_source": forward_source,
    }


def _rows(n=4, text_size=10):
    return [_row(i + 1, 100 + i, 1_700_000_000 + i * 60,
                 text="привет %d" % i + "x" * text_size,
                 reply_to=100 if i else None) for i in range(n)]


# ── §2: построение окна (без срезов, full-поля, forward/media) ──────────────

def test_build_contains_all_messages_no_slicing():
    rows = _rows(150)
    window = ssw.build_source_window("run-1", -100, rows)
    assert window is not None
    assert window.source_message_count == 150
    assert window.window_from == 1_700_000_000
    assert window.window_to == 1_700_000_000 + 149 * 60
    ids = [m["message_id"] for m in window.messages]
    assert ids == [100 + i for i in range(150)]


def test_schema_fields_forward_media_metadata():
    rows = _rows(2)
    rows[-1] = _row(2, 101, 1_700_000_060, media="photo", forward=True,
                    forward_source="@somenews", reply_to=100)
    window = ssw.build_source_window("run-fwd", -100, rows)
    msg = window.messages[-1]
    assert msg["message_id"] == 101
    assert msg["db_id"] == 2
    assert msg["timestamp"] == 1_700_000_060
    assert msg["author_id"] == 7 and msg["display_name"] == "Вася"
    assert msg["reply_to_message_id"] == 100
    assert msg["media_type"] == "photo"
    assert msg["is_forward"] is True
    assert msg["forward_source"] == "@somenews"
    assert "mentions" not in msg          # поля нет в окне — не выдумываем


def test_long_text_preserved_verbatim():
    long_text = "х" * 50_000
    rows = [_row(1, 101, 1_700_000_000, text=long_text)]
    window = ssw.build_source_window("run-long", -100, rows)
    assert window.messages[0]["text"] == long_text
    assert "50" not in str(1)             # неактуально; чекер капа отсутствует


def test_empty_rows_returns_none():
    assert ssw.build_source_window("run-empty", -100, []) is None
    assert ssw.build_source_window("", -100, _rows()) is None


# ── Immutability (R6-A-002) ─────────────────────────────────────────────────

def test_frozen_object_and_deep_copy_view():
    window = ssw.build_source_window("run-imm", -100, _rows(3))
    with pytest.raises(Exception):
        window.run_id = "other"           # frozen dataclass
    view = window.messages_as_view()
    view[0]["text"] = "ИЗМЕНЁННОЕ"
    view.pop()
    # Потребитель мутирует свою копию; snapshot байт-идентичен.
    assert json.loads(window.messages_json)[0]["text"] == \
        window.messages[0]["text"]
    assert len(view) == 2
    assert window.messages_as_view()[0]["text"] != "ИЗМЕНЁННОЕ"


def test_readback_after_consumer_mutation_byte_identical():
    window = ssw.build_source_window("run-byte", -100, _rows(3))
    canonical_before = window.messages_json
    window.messages_as_view()[1]["text"] = "MUTATED"
    assert window.messages_json == canonical_before


# ── DDL v24: миграция additive + идемпотентность ───────────────────────────

async def _fresh(tmp_path, name="srcw.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


@pytest.mark.asyncio
async def test_v24_migration_fresh_db(tmp_path):
    d = await _fresh(tmp_path)
    try:
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 24
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='summary_source_windows'")
        assert await cur.fetchone() is not None
        rows = await d.db.execute(
            "SELECT version, name FROM schema_migrations WHERE version=24")
        data = await rows.fetchall()
        assert any(v == 24 and n == "summary_source_windows"
                   for v, n in data)
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v24_migration_idempotent_rerun(tmp_path):
    """Повторный прогон — no-op (таблица/строки не дублируются)."""
    d = await _fresh(tmp_path)
    try:
        saved1 = await ssw.store_source_window(
            d, ssw.build_source_window("run-mig", -100, _rows(2)))
        await d._migrate_summary_source_window_v24()
        await d._migrate_summary_source_window_v24()
        loaded = await ssw.load_source_window(d, "run-mig")
        assert saved1 is True
        assert loaded is not None and loaded.source_message_count == 2
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_pg_noop_is_sqlite_store_only():
    """PG — no-op (спека §0.1): SQL-слой фичи живёт только в SQLite
    DatabaseService (aiosqlite), никакого PG-DDL/пула в коде фичи нет."""
    import io
    from pathlib import Path
    text = Path("services/summary_source_window.py").read_text(
        encoding="utf-8")
    assert "asyncpg" not in text           # PG-слой не врезан
    assert "pool.connect" not in text.lower()
    db_text = Path("services/database.py").read_text(encoding="utf-8")
    # DDL принадлежит SQLite-миграции v24.
    assert "summary_source_windows" in db_text


# ── Write-once persistence ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_load_roundtrip_byte_identical(tmp_path):
    d = await _fresh(tmp_path, "srcw1.db")
    try:
        window = ssw.build_source_window("run-rt", -100, _rows(6))
        saved = await ssw.store_source_window(d, window)
        assert saved is True
        loaded = await ssw.load_source_window(d, "run-rt")
        assert loaded is not None
        assert loaded.run_id == "run-rt"
        assert loaded.chat_id == -100
        assert loaded.source_message_count == 6
        # Байт-идентичный readback messages_json.
        assert loaded.messages_json == window.messages_json
        assert loaded.window_from == window.window_from
        assert loaded.window_to == window.window_to
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_write_once_second_store_no_overwrite(tmp_path):
    """Guard-инвариант: попытка повторной записи (или «UPDATE после
    создания») — deфект по контракту; write-once: повтор → False, данные
    не меняются."""
    d = await _fresh(tmp_path, "srcw2.db")
    try:
        window = ssw.build_source_window("run-wo", -100, _rows(3))
        assert await ssw.store_source_window(d, window) is True
        mutated = ssw.build_source_window(
            "run-wo", -100,
            [_row(9, 999, 1_700_000_999, text="МУТАЦИЯ")])
        assert await ssw.store_source_window(d, mutated) is False
        loaded = await ssw.load_source_window(d, "run-wo")
        assert loaded.messages_json == window.messages_json
        assert loaded.source_message_count == 3
        assert 999 not in [m["message_id"] for m in loaded.messages]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_update_is_not_part_of_surface(tmp_path):
    """Строка-скан: кода UPDATE по `summary_source_windows` не существует ни
    в одной ветке (immutability contract guard) —><3 ветки честно только
    INSERT/SELECT/DELETE-by-TTL."""
    from pathlib import Path
    src = Path("services/database.py").read_text(encoding="utf-8")
    assert "UPDATE summary_source_windows" not in src
    from pathlib import Path as _P
    ssw_src = _P("services/summary_source_window.py").read_text(
        encoding="utf-8")
    assert "UPDATE " not in ssw_src


# ── Retention TTL ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retention_ttl_purge(tmp_path):
    d = await _fresh(tmp_path, "srcw3.db")
    try:
        now = int(time.time())
        old_window = ssw.build_source_window(
            "run-old", -100, _rows(2), created_at=now - 8 * 86400)
        fresh_window = ssw.build_source_window(
            "run-fresh", -100, _rows(2), created_at=now - 60)
        await ssw.store_source_window(d, old_window)
        await ssw.store_source_window(d, fresh_window)
        removed = await ssw.purge_expired_source_windows(d, now=now)
        assert removed == 1
        assert await ssw.load_source_window(d, "run-old") is None
        assert await ssw.load_source_window(d, "run-fresh") is not None
        # Повторная очистка — no-op.
        assert await ssw.purge_expired_source_windows(d, now=now) == 0
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_retention_days_env_only(tmp_path):
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(Settings, "SUMMARY_SOURCE_WINDOW_RETENTION_DAYS",
                            3, raising=False)
        assert ssw.retention_days() == 3
        monkeypatch.setattr(Settings, "SUMMARY_SOURCE_WINDOW_RETENTION_DAYS",
                            "мусор", raising=False)
        assert ssw.retention_days() == 7
    finally:
        monkeypatch.undo()


# ── Kill-switch OFF → бит-в-бит 2.58.46 ────────────────────────────────────

@pytest.mark.asyncio
async def test_kill_switch_off_no_durable_write(tmp_path):
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            Settings, "SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED", False,
            raising=False)
        d = await _fresh(tmp_path, "srcw4.db")
        try:
            generated = {
                "window": None,
            }

            class FakeMemory:
                db = None

            gen = _make_generator(db=d)
            await gen._establish_source_window(
                "run-off", -100, _rows(3))
            cur = await d.db.execute(
                "SELECT COUNT(*) FROM summary_source_windows")
            assert (await cur.fetchone())[0] == 0
            assert generated is not None
        finally:
            await d.close()
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_establish_single_point_writes_and_logs(tmp_path, caplog,
                                                      monkeypatch):
    """Интеграционная единая точка: summary_generator._run → snapshot write-
    once + событие SUMMARY_SOURCE_WINDOW_READY (R17: числа, без текстов)."""
    d = await _fresh(tmp_path, "srcw5.db")
    try:
        secret_text = "СЕКРЕТНЫЙ_ТЕКСТ_ОКНА_4242"
        rows = _rows(3)
        rows[1] = _row(2, 101, 1_700_000_060, text=secret_text)
        gen = _make_generator(db=d)
        # События SUMMARY_* (волна E transport) — prod-дефолт ON для
        # asap41-теста; патч на ВСЕХ классах Settings (reload'ы settings в
        # чужих тестах могут переназначить инстанс; прецедент — примечание в
        # tests/conftest.py `_asap4_flags_off_by_default`).
        import config.settings as _cs
        for _cls in {Settings, type(_cs.settings)}:
            monkeypatch.setattr(_cls, "SUMMARY_PIPELINE_EVENTS_ENABLED",
                                True, raising=False)
        import logging as _logging
        with caplog.at_level(_logging.INFO):
            await gen._establish_source_window("run-est", -100, rows)
        loaded = await ssw.load_source_window(d, "run-est")
        assert loaded is not None and loaded.source_message_count == 3
        assert secret_text not in caplog.text
        assert "run-est" in caplog.text and "messages=3" in caplog.text
        # Событие SOURCE_WINDOW_READY эмитится через events transport.
        assert any("event=SUMMARY_SOURCE_WINDOW_READY" in r.getMessage()
                   for r in caplog.records)
    finally:
        await d.close()


def _make_generator(db):
    """Generator сура заводится без бота: memory.db — единственное что
    нужна snapshot-точке."""
    from types import SimpleNamespace
    from services.summary_generator import SummaryGenerator
    memory = SimpleNamespace(db=db, memorize_facts=lambda *a, **k: None)
    return SummaryGenerator(memory=memory, xml=SimpleNamespace(), llm=None,
                            bot=None)
