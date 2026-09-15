"""F7 (10.19, ADR-1019-6 / ADR-1019-8) — retention импортированной истории,
guard «0=вечно», изоляция импорта/чекпоинтов (SQLite v11).

Покрытие spec §6:
  * `purge_imported_history` — dry_run считает без удаления; реальный прогон
    удаляет только import_key NOT NULL + history_processed=1 + timestamp<cutoff
    для чатов из `chat_cutoffs`; live-строки не тронуты; FTS синхронен;
    повторный прогон — no-op; без маппинга → TypeError (структурный guard);
  * guard: `imported_history_purge_allowed(chat)` при `0` → `(False, 0, …)`,
    fail-closed при ошибке резолва; целевой чат не попадает в `chat_cutoffs`;
  * sentinel: `retention_state(0/180/-1)`; `run_import_retention` — архив перед
    purge (fail-safe) и dry-run;
  * изоляция (v11): один контент в двух чатах → ДВЕ строки; тот же чат — дубль;
    чекпоинт чужого чата не влияет.
"""
import asyncio
import dataclasses
import json
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from config.settings import settings as real_settings
from services import chat_params
from services import hot_config as hot
from services import memory_maintenance as mm
from services import retention_policy as rp
from services import summary_memory as sm
from services import worker_settings
from services.database import DatabaseService
from tools.history_import import checkpoints as ck

# Целевой чат — ТОЛЬКО как данные теста (в services/* его быть не должно;
# инвариант держит tests/test_chat_settings_seed_round1019.py).
TARGET_CHAT_ID = -1002661910336


def _cfg(**overrides):
    return dataclasses.replace(real_settings, **overrides)


async def _db(tmp_path, name="ret.db"):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _insert(db, chat_id, text, ts, *, import_key=None,
                  history_processed=0, media_type="text"):
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, import_key, history_processed) VALUES (1, ?, ?, ?, ?, ?, ?)",
        (chat_id, text, ts, media_type, import_key, history_processed))
    if text:
        await db.db.execute(
            "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
            (cursor.lastrowid, text))
    await db.db.commit()


class TestRetentionState:
    def test_sentinel_family(self):
        assert rp.retention_state(0) == "eternal"
        assert rp.retention_state(180) == "cap"
        assert rp.retention_state(-1) == "invalid"
        assert rp.retention_state("garbage") == "invalid"


class TestPurgeGateDefaults:
    def test_env_gate_defaults_safe(self):
        """D-2 (High): деструктивный purge по умолчанию выключен, первый
        прогон — dry-run."""
        assert real_settings.IMPORT_RETENTION_ENABLED is False
        assert real_settings.IMPORT_RETENTION_DRY_RUN is True

    def test_backup_confirmed_default_off(self):
        """UPD4 п.3: без подтверждённого бэкапа БД авто-крон не удаляет."""
        assert real_settings.IMPORT_RETENTION_BACKUP_CONFIRMED is False

    def test_auto_purge_gate_requires_backup(self):
        """UPD4 п.3 (D-2 High, бэкап-гейт): DELETE авто-крона возможен ТОЛЬКО
        при ЯВНОМ apply И подтверждённом бэкапе; иначе — dry-run."""
        assert mm.auto_purge_dry_run(dry_run=True, backup_confirmed=True) is True
        assert mm.auto_purge_dry_run(dry_run=True, backup_confirmed=False) is True
        assert mm.auto_purge_dry_run(
            dry_run=False, backup_confirmed=False) is True
        assert mm.auto_purge_dry_run(
            dry_run=False, backup_confirmed=True) is False

    def test_manage_cli_retention_dry_run_and_apply(self):
        """D-2/UPD4 п.3: `manage.py retention` (dry-run по умолчанию) /
        `--dry-run` / `--apply`; alias `retention-dry-run`; `--apply --dry-run`
        → dry-run (безопасный приоритет)."""
        import manage
        parser = manage.build_parser()
        assert parser.parse_args(["retention"]).apply is False
        assert parser.parse_args(["retention", "--apply"]).apply is True
        assert parser.parse_args(["retention", "--dry-run"]).dry_run is True
        alias = parser.parse_args(["retention-dry-run", "--apply"])
        assert alias.command == "retention-dry-run"
        assert manage._retention_dry_run(
            parser.parse_args(["retention"])) is True
        assert manage._retention_dry_run(
            parser.parse_args(["retention", "--apply"])) is False
        assert manage._retention_dry_run(
            parser.parse_args(["retention", "--apply", "--dry-run"])) is True
        assert manage._retention_dry_run(alias) is True


class TestPurgeGuard:
    @pytest.mark.asyncio
    async def test_eternal_forbids_purge(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            return 0, "chat"
        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _resolve)
        allowed, days, source = await rp.imported_history_purge_allowed(-100)
        assert allowed is False and days == 0 and source == "chat"

    @pytest.mark.asyncio
    async def test_cap_allows_purge(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            return 180, "global"
        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _resolve)
        allowed, days, source = await rp.imported_history_purge_allowed(-100)
        assert allowed is True and days == 180 and source == "global"

    @pytest.mark.asyncio
    async def test_resolve_error_fail_closed(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            raise RuntimeError("pg down")
        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _resolve)
        allowed, days, source = await rp.imported_history_purge_allowed(-100)
        assert allowed is False and days == 0 and source == "error"

    @pytest.mark.asyncio
    async def test_invalid_override_falls_back_to_default(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            return -5, "chat"
        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _resolve)
        allowed, days, source = await rp.imported_history_purge_allowed(-100)
        assert allowed is True and days == rp.RETENTION_DEFAULT
        assert source == "default"

    @pytest.mark.asyncio
    async def test_hard_deny_target_from_seed_data(self, monkeypatch):
        """D-1 (defence-in-depth): целевой чат из `enforce`-данных сида запрещён
        даже если резолв вернул «разрешающий» fail-open дефолт."""
        async def _resolve(key, *, chat_id=None, default=None):
            return 180, "default"          # симулируем fail-open
        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _resolve)
        allowed, days, source = await rp.imported_history_purge_allowed(
            TARGET_CHAT_ID)
        assert allowed is False and days == 0
        assert source == "seed_enforced"

    @pytest.mark.asyncio
    async def test_real_resolver_chat_layer_unavailable_fail_closed(
            self, monkeypatch):
        """D-1 на РЕАЛЬНОМ резолвере (без monkeypatch policy): chat-слой
        недоступен (нет ChatParamsPool) → source='error', purge запрещён."""
        monkeypatch.setattr(chat_params, "_chat_params_cache", None)
        monkeypatch.setattr(hot, "_cache", None)
        allowed, days, source = await rp.imported_history_purge_allowed(-100)
        assert allowed is False and days == 0 and source == "error"

    def test_invalid_global_default_no_recursion(self, monkeypatch):
        """D-2.1 (Medium): негативный глобальный дефолт НЕ вызывает
        саморекурсию `_normalized` (RecursionError) — детерминированный
        fallback 180."""
        assert rp._fallback_for(-5) == 180
        assert rp._fallback_for(0) == 0
        assert rp._fallback_for(180) == 180
        monkeypatch.setattr(rp, "_FALLBACK_DAYS", 180)
        # ключ регресса: раньше здесь была бесконечная саморекурсия
        assert rp._normalized(-5, "default") == (180, "default")
        assert rp._normalized("garbage", "chat") == (180, "default")
        assert rp._normalized(0, "chat") == (0, "chat")
        assert rp._normalized(180, "global") == (180, "global")

    @pytest.mark.asyncio
    async def test_unreadable_seed_denies_purge(self, monkeypatch):
        """D-2.4 (Low): нечитаемый сид → fail-safe (purge запрещён),
        а не молчаливое отключение второго барьера."""
        monkeypatch.setattr(rp, "_enforced_eternal_chat_ids",
                            lambda: (set(), False))
        allowed, days, source = await rp.imported_history_purge_allowed(-100)
        assert allowed is False and days == 0
        assert source == "seed_unavailable"

    @pytest.mark.asyncio
    async def test_negative_env_default_purges_with_chat_layer(
            self, tmp_path, monkeypatch):
        """D-2.1: негативный env-дефолт + ДОСТУПНЫЙ chat-слой → штатный purge
        (fallback 180), без RecursionError."""
        db = await _db(tmp_path, "neg_default.db")
        try:
            await _insert(db, -100, "old", 1, import_key="k1",
                          history_processed=1)
            monkeypatch.setattr(rp, "RETENTION_DEFAULT", -5)
            monkeypatch.setattr(rp, "_FALLBACK_DAYS", 180)

            async def _resolve(key, *, chat_id=None, default=None):
                return default, "default"      # доступный chat-слой
            monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                                _resolve)
            out = await mm.run_import_retention(db, archive_dir=tmp_path / "b")
            assert out["reason"] == "ok"
            assert out["deleted"] == 1
            assert await db.count_smart_messages(-100) == 0
        finally:
            await db.close()


class TestPurgeImportedHistory:
    @pytest.mark.asyncio
    async def test_structural_guard_no_mapping(self, tmp_path):
        db = await _db(tmp_path, "guard.db")
        try:
            with pytest.raises(TypeError):
                await db.purge_imported_history()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_dry_run_counts_without_deleting(self, tmp_path):
        db = await _db(tmp_path, "dry.db")
        try:
            await _insert(db, -100, "old import", 1, import_key="k1",
                          history_processed=1)
            await _insert(db, -100, "pending import", 1, import_key="k2",
                          history_processed=0)
            await _insert(db, -100, "live", 1)
            out = await db.purge_imported_history(
                chat_cutoffs={-100: 2_000_000_000}, dry_run=True)
            assert out["candidates"] == 1 and out["deleted"] == 0
            assert await db.count_smart_messages(-100) == 3
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_purge_only_mapped_chats_and_processed(self, tmp_path):
        db = await _db(tmp_path, "purge.db")
        try:
            await _insert(db, -100, "old import a", 1, import_key="k1",
                          history_processed=1)
            await _insert(db, -100, "pending a", 1, import_key="k2",
                          history_processed=0)
            await _insert(db, -100, "live a", 1)
            await _insert(db, -200, "old import b", 1, import_key="k3",
                          history_processed=1)
            out = await db.purge_imported_history(
                chat_cutoffs={-100: 2_000_000_000}, batch=1)
            assert out["deleted"] == 1 and out["batches"] == 1
            # чат -200 не в маппинге → не тронут
            assert await db.count_smart_messages(-200) == 1
            assert await db.count_smart_messages(-100) == 2
            # FTS чата -100: удалённая строка не находится, оставшиеся — да
            assert await db.search_messages_fts(-100, '"old"', 10) == []
            assert len(await db.search_messages_fts(-100, '"pending"', 10)) == 1
            # чат -200 не тронут (в т.ч. FTS)
            assert len(await db.search_messages_fts(-200, '"old"', 10)) == 1
            # идемпотентность: повторный прогон — no-op
            out2 = await db.purge_imported_history(
                chat_cutoffs={-100: 2_000_000_000})
            assert out2["deleted"] == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_chat_max_ids_limits_to_archived_set(self, tmp_path):
        """D-7 (ревью Батча E): purge ограничен `id <= chat_max_ids[chat]`
        — строки, ставшие `history_processed=1` позже (id выше архива), НЕ
        удаляются; candidates — не `deleted`."""
        db = await _db(tmp_path, "maxid.db")
        try:
            await _insert(db, -100, "archived", 1, import_key="k1",
                          history_processed=1)
            await _insert(db, -100, "flipped later", 1, import_key="k2",
                          history_processed=1)
            cursor = await db.db.execute(
                "SELECT id FROM smart_messages ORDER BY id")
            ids = [r[0] for r in await cursor.fetchall()]
            out = await db.purge_imported_history(
                chat_cutoffs={-100: 2_000_000_000}, dry_run=False,
                chat_max_ids={-100: ids[0]})
            assert out["candidates"] == 1
            assert out["deleted"] == 1
            # «поздняя» строка (id > заархивированного максимума) сохранена
            assert await db.count_smart_messages(-100) == 1
        finally:
            await db.close()


class TestRunImportRetention:
    @pytest.mark.asyncio
    async def test_dry_run_reports_candidates(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "run_dry.db")
        try:
            await _insert(db, -100, "old", 1, import_key="k1",
                          history_processed=1)

            async def _allowed(chat_id):
                return True, 180, "default"
            monkeypatch.setattr(rp, "imported_history_purge_allowed", _allowed)
            out = await mm.run_import_retention(db, dry_run=True)
            assert out["dry_run"] is True
            assert out["candidates"] == 1 and out["deleted"] == 0
            assert await db.count_smart_messages(-100) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_eternal_zero_never_in_cutoffs(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "run_eternal.db")
        try:
            await _insert(db, -100, "eternal", 1, import_key="k1",
                          history_processed=1)
            calls = []

            async def _allowed(chat_id):
                calls.append(chat_id)
                return False, 0, "chat"          # 0=вечно
            monkeypatch.setattr(rp, "imported_history_purge_allowed", _allowed)
            out = await mm.run_import_retention(db, dry_run=False)
            assert calls == [-100]
            assert out["reason"] == "no_candidates"
            assert await db.count_smart_messages(-100) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_real_resolver_unavailable_layer_aborts_whole_run(
            self, tmp_path, monkeypatch):
        """D-1 (главный регресс): РЕАЛЬНЫЙ резолвер + недоступный chat-слой
        → прогон ОТМЕНЯЕТСЯ целиком, строка целевого чата НЕ удаляется."""
        db = await _db(tmp_path, "run_layer_error.db")
        try:
            await _insert(db, TARGET_CHAT_ID, "history", 1, import_key="vk",
                          history_processed=1)
            await _insert(db, -100, "normal history", 1, import_key="nk",
                          history_processed=1)
            monkeypatch.setattr(chat_params, "_chat_params_cache", None)
            monkeypatch.setattr(hot, "_cache", None)
            out = await mm.run_import_retention(db, archive_dir=tmp_path / "b")
            assert out["reason"] == "chat_layer_unavailable"
            assert out["deleted"] == 0 and out["chats"] == 0
            assert await db.count_smart_messages(TARGET_CHAT_ID) == 1
            assert await db.count_smart_messages(-100) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_archive_mismatch_aborts_purge(self, tmp_path, monkeypatch):
        """D-7: расхождение `candidates != archived` (гонка history_processed)
        → purge прерывается, строки не удаляются."""
        db = await _db(tmp_path, "run_mismatch.db")
        arch = tmp_path / "backups"
        try:
            await _insert(db, -100, "import row", 1, import_key="k1",
                          history_processed=1)

            async def _allowed(chat_id):
                return True, 180, "default"
            monkeypatch.setattr(rp, "imported_history_purge_allowed", _allowed)

            # Архив «зафиксировал» 5 строк с max_id=0, кандидатов по этому
            # множеству 0 → расхождение → удаление отменяется.
            async def _fake_archive(_db, _cutoffs, _dir):
                return True, 5, str(arch / "x.jsonl"), {-100: 0}
            monkeypatch.setattr(mm, "_archive_imported_history", _fake_archive)
            out = await mm.run_import_retention(db, archive_dir=arch)
            assert out["reason"] == "archive_mismatch"
            assert out["deleted"] == 0
            assert await db.count_smart_messages(-100) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_archive_before_purge(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "run_arch.db")
        arch = tmp_path / "backups"
        try:
            await _insert(db, -100, "secret old text", 1, import_key="k1",
                          history_processed=1)

            async def _allowed(chat_id):
                return True, 180, "default"
            monkeypatch.setattr(rp, "imported_history_purge_allowed", _allowed)
            out = await mm.run_import_retention(db, archive_dir=arch)
            assert out["deleted"] == 1 and out["archived"] == 1
            files = list(arch.glob("imported_history_*.jsonl"))
            assert len(files) == 1
            payload = json.loads(files[0].read_text(encoding="utf-8").strip())
            assert payload["text"] == "secret old text"
            assert await db.count_smart_messages(-100) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_archive_failure_keeps_rows(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "run_fail.db")
        try:
            await _insert(db, -100, "keep me", 1, import_key="k1",
                          history_processed=1)

            async def _allowed(chat_id):
                return True, 180, "default"
            monkeypatch.setattr(rp, "imported_history_purge_allowed", _allowed)

            async def _boom(*a, **k):
                raise OSError("disk full")
            monkeypatch.setattr(db, "select_imported_history", _boom)
            out = await mm.run_import_retention(db,
                                                archive_dir=tmp_path / "b")
            assert out["reason"] == "archive_failed" and out["deleted"] == 0
            assert await db.count_smart_messages(-100) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_archive_fsync_before_first_delete(self, tmp_path, monkeypatch):
        """D-2.2 (Medium): архив fsync'ится ДО первого реального DELETE, файл
        непуст и синхронизирован. Порядок событий: «fsync» раньше «delete»."""
        db = await _db(tmp_path, "fsync.db")
        arch = tmp_path / "backups"
        events: list = []
        sizes: list = []
        try:
            await _insert(db, -100, "durable text", 1, import_key="k1",
                          history_processed=1)

            async def _allowed(chat_id):
                return True, 180, "default"
            monkeypatch.setattr(rp, "imported_history_purge_allowed", _allowed)

            real_flush = mm._flush_and_fsync

            def _spy_fsync(fh):
                events.append("fsync")
                real_flush(fh)
            monkeypatch.setattr(mm, "_flush_and_fsync", _spy_fsync)

            real_purge = db.purge_imported_history

            async def _spy_purge(*a, **kw):
                if not kw.get("dry_run"):
                    events.append("delete")
                    files = list(arch.glob("imported_history_*.jsonl"))
                    sizes.append(files[0].stat().st_size if files else 0)
                return await real_purge(*a, **kw)
            monkeypatch.setattr(db, "purge_imported_history", _spy_purge)

            out = await mm.run_import_retention(db, archive_dir=arch)
            assert out["deleted"] == 1
            assert "fsync" in events and "delete" in events
            assert events.index("fsync") < events.index("delete")
            # архив непуст (строка записана) к моменту удаления
            assert sizes and sizes[0] > 0
        finally:
            await db.close()

    def test_flush_and_fsync_calls_os_fsync(self, tmp_path, monkeypatch):
        """D-2.2: helper реально вызывает `os.fsync`, а не только flush."""
        calls: list = []
        real_fsync = mm.os.fsync

        def _spy(fd):
            calls.append(fd)
            return real_fsync(fd)
        monkeypatch.setattr(mm.os, "fsync", _spy)
        path = tmp_path / "x.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("data\n")
            mm._flush_and_fsync(fh)
        assert calls and isinstance(calls[0], int)


class TestIsolationV11:
    @pytest.mark.asyncio
    async def test_same_content_two_chats_two_rows(self, tmp_path):
        db = await _db(tmp_path, "iso.db")
        try:
            await _insert(db, -100, "same text", 5, import_key="dup")
            await _insert(db, -200, "same text", 5, import_key="dup")
            assert await db.count_smart_messages(-100) == 1
            assert await db.count_smart_messages(-200) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_same_chat_duplicate_rejected(self, tmp_path):
        db = await _db(tmp_path, "iso2.db")
        try:
            await _insert(db, -100, "same text", 5, import_key="dup")
            with pytest.raises(aiosqlite.IntegrityError):
                await _insert(db, -100, "same text", 5, import_key="dup")
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_checkpoint_isolated_per_chat(self, tmp_path):
        conn = await aiosqlite.connect(str(tmp_path / "ck.db"))
        conn.row_factory = aiosqlite.Row
        try:
            await ck.ensure_table(conn)
            await ck.mark(conn, "dump.json", -100, 10, 10, done=True)
            await conn.commit()
            row_a = await ck.get(conn, "dump.json", -100)
            row_b = await ck.get(conn, "dump.json", -200)
            assert row_a["done"] == 1
            assert row_b is None
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_migration_v11_index_and_legacy_checkpoints(self, tmp_path):
        path = tmp_path / "v11.db"
        db = DatabaseService(str(path))
        await db.initialize()
        # симулируем «legacy» состояние v11-до: глобальный индекс + старые чекпоинты
        await db.db.execute("DROP INDEX IF EXISTS idx_smart_messages_chat_import_key")
        await db.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_messages_import_key "
            "ON smart_messages(import_key) WHERE import_key IS NOT NULL")
        await db.db.execute("DROP TABLE IF EXISTS import_checkpoints")
        await db.db.execute(
            "CREATE TABLE import_checkpoints (path TEXT PRIMARY KEY, "
            "processed INTEGER NOT NULL DEFAULT 0, total INTEGER, "
            "done INTEGER NOT NULL DEFAULT 0, updated_at INTEGER)")
        await db.db.execute(
            "INSERT INTO import_checkpoints (path, processed, total, done) "
            "VALUES ('x.json', 1, 1, 1)")
        await db.db.execute("PRAGMA user_version = 10")
        await db.db.commit()
        await db.close()
        # ре-инициализация → v11
        db2 = DatabaseService(str(path))
        await db2.initialize()
        try:
            cursor = await db2.db.execute("PRAGMA user_version")
            assert (await cursor.fetchone())[0] == 11
            cursor = await db2.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
                "('idx_smart_messages_import_key', "
                "'idx_smart_messages_chat_import_key')")
            names = {r["name"] for r in await cursor.fetchall()}
            assert names == {"idx_smart_messages_chat_import_key"}
            cursor = await db2.db.execute("PRAGMA table_info(import_checkpoints)")
            cols = {r["name"] for r in await cursor.fetchall()}
            assert "chat_id" in cols
            cursor = await db2.db.execute(
                "SELECT path, chat_id FROM import_checkpoints")
            rows = [tuple(r) for r in await cursor.fetchall()]
            assert rows == [("x.json", 0)]      # legacy → unscoped chat_id=0
        finally:
            await db2.close()
        # D-Low (ревью Батча E): повторный прогон миграции идемпотентен —
        # нет хвоста import_checkpoints_old, данные/версия сохранены.
        db3 = DatabaseService(str(path))
        await db3.initialize()
        try:
            cursor = await db3.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name "
                "IN ('import_checkpoints', 'import_checkpoints_old')")
            names = {r["name"] for r in await cursor.fetchall()}
            assert names == {"import_checkpoints"}
            cursor = await db3.db.execute(
                "SELECT path, chat_id, done FROM import_checkpoints")
            assert [tuple(r) for r in await cursor.fetchall()] == [("x.json", 0, 1)]
            cursor = await db3.db.execute("PRAGMA user_version")
            assert (await cursor.fetchone())[0] == 11
        finally:
            await db3.close()


class _FakeLLM:
    """Мини-LLM: retention-шаг вызывается до сжатия; фактов нет — не нужен."""
    async def generate(self, messages):        # noqa: ARG002
        return ""


class TestAutoCronBackupGate:
    """UPD4 п.3 / D-2 (High): авто-крон (`compress_and_purge`) НЕ удаляет без
    подтверждённого бэкапа БД — при `ENABLED=true`/`DRY_RUN=false`/
    `BACKUP_CONFIRMED=false` шаг выполняется как dry-run (+WARNING)."""

    @pytest.mark.asyncio
    async def test_backup_unconfirmed_forces_dry_run(self, tmp_path,
                                                     monkeypatch):
        db = await _db(tmp_path, "cron_gate.db")
        captured: dict = {}

        async def _fake_run(_db, *, dry_run=False, **kw):   # noqa: ARG001
            captured["dry_run"] = dry_run
            return {"reason": "dry_run" if dry_run else "ok"}

        monkeypatch.setattr(mm, "run_import_retention", _fake_run)
        monkeypatch.setattr(type(real_settings), "IMPORT_RETENTION_ENABLED",
                            True)
        monkeypatch.setattr(type(real_settings), "IMPORT_RETENTION_DRY_RUN",
                            False)
        monkeypatch.setattr(type(real_settings),
                            "IMPORT_RETENTION_BACKUP_CONFIRMED", False)
        monkeypatch.setattr(sm, "_import_retention_last_ts", 0)
        try:
            await sm.MemoryManager(db, _FakeLLM()).compress_and_purge(-100)
        finally:
            await db.close()
        assert captured["dry_run"] is True

    @pytest.mark.asyncio
    async def test_backup_confirmed_allows_apply(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "cron_gate_ok.db")
        captured: dict = {}

        async def _fake_run(_db, *, dry_run=False, **kw):   # noqa: ARG001
            captured["dry_run"] = dry_run
            return {"reason": "ok"}

        monkeypatch.setattr(mm, "run_import_retention", _fake_run)
        monkeypatch.setattr(type(real_settings), "IMPORT_RETENTION_ENABLED",
                            True)
        monkeypatch.setattr(type(real_settings), "IMPORT_RETENTION_DRY_RUN",
                            False)
        monkeypatch.setattr(type(real_settings),
                            "IMPORT_RETENTION_BACKUP_CONFIRMED", True)
        monkeypatch.setattr(sm, "_import_retention_last_ts", 0)
        try:
            await sm.MemoryManager(db, _FakeLLM()).compress_and_purge(-100)
        finally:
            await db.close()
        assert captured["dry_run"] is False
