"""F5 (`memory-rebuild-sanitation-round1021`, ADR-1021-5 / T-1980…T-1989):
деструктивный CLI-контур `manage.py memory`.

Критические инварианты spec §3.1/§6:
  * ⛔ сырая история (`smart_messages` + FTS) не мутируется;
  * guard allowlist → abort на DELETE из запрещённой таблицы;
  * авто-бэкап + JSONL-архив со сверкой `candidates == archived`;
  * guard целевого чата (не входит в `--all`, нужен `--allow-target-chat`);
  * `persona_dossier_overrides` неприкосновенны без `--include-overrides`;
  * `--dry-run` ничего не пишет; идемпотентность/классы валидатора.
Фикстуры синтетические (временная БД), реальные данные не используются.
"""
import argparse
import json
import sqlite3

import pytest

import manage
from services import memory_rebuild as mr
from services import summary_aliases
from services.database import DatabaseService

TARGET_CHAT_ID = -1002661910336


async def _db(tmp_path, name="mem.db"):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _insert_msg(db, chat_id, text, ts=1):
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type) VALUES (1, ?, ?, ?, 'text')",
        (chat_id, text, ts))
    await db.db.execute(
        "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
        (cursor.lastrowid, text))
    await db.db.commit()


async def _count(db, sql, params=()):
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


class _FakePipeline:
    def __init__(self, written=0):
        self.calls = []
        self.written = written

    async def __call__(self, chat_id):
        self.calls.append(chat_id)
        return self.written


class TestGuardAllowlist:
    def test_raw_history_never_allowed(self):
        for table in ("smart_messages", "smart_messages_fts",
                      "import_checkpoints"):
            with pytest.raises(mr.UnsafeMutationError):
                mr.assert_derived_table(table)

    def test_unknown_table_rejected(self):
        with pytest.raises(mr.UnsafeMutationError):
            mr.assert_derived_table("mystery_table")

    def test_derived_allowed(self):
        mr.assert_derived_table("graph_facts")
        mr.assert_derived_table("edges")

    @pytest.mark.asyncio
    async def test_guarded_delete_aborts_and_keeps_rows(self, tmp_path):
        db = await _db(tmp_path, "guard.db")
        try:
            await _insert_msg(db, -100, "raw")
            with pytest.raises(mr.UnsafeMutationError):
                await mr._guarded_delete(db, "smart_messages",
                                         "chat_id = ?", (-100,))
            assert await db.count_smart_messages(-100) == 1
        finally:
            await db.close()


class TestRawHistoryInvariant:
    @pytest.mark.asyncio
    async def test_sanitize_does_not_mutate_smart_messages(
            self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "inv_san.db")
        try:
            await _insert_msg(db, -100, "raw one")
            await _insert_msg(db, -100, "raw two")
            await db.insert_graph_fact(-100, "orphan fact", "chat_history", None)
            before_msgs = await db.count_smart_messages()
            before_fts = await _count(db, "SELECT COUNT(*) FROM smart_messages_fts")
            mutations = []
            real_exec = db.db.execute

            async def _spy(sql, params=()):
                low = str(sql).lower()
                if any(v in low for v in ("delete", "update", "insert")) \
                        and "smart_messages" in low:
                    mutations.append(low)
                return await real_exec(sql, params)
            monkeypatch.setattr(db.db, "execute", _spy)

            report = await mr.sanitize_beliefs(
                db, chat_ids=[-100], db_path=tmp_path / "inv_san.db",
                backup_dir=tmp_path / "bak")
            assert report["deleted"] >= 1
            assert mutations == []
            assert await db.count_smart_messages() == before_msgs
            assert await _count(db, "SELECT COUNT(*) FROM smart_messages_fts") \
                == before_fts
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_does_not_mutate_smart_messages(self, tmp_path):
        db = await _db(tmp_path, "inv_rb.db")
        try:
            await _insert_msg(db, -100, "raw")
            await db.insert_graph_fact(
                -100, "old meme", "chat_history", None, status="chat_meme",
                kind="fact")
            before = await db.count_smart_messages()
            pipeline = _FakePipeline(written=1)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=pipeline,
                db_path=tmp_path / "inv_rb.db", backup_dir=tmp_path / "bak")
            assert report["reset"] == 1 and report["rebuilt"] == 1
            assert pipeline.calls == [-100]
            assert await db.count_smart_messages() == before
        finally:
            await db.close()


class TestSafetyNet:
    @pytest.mark.asyncio
    async def test_archive_matches_candidates_and_is_written(self, tmp_path):
        db = await _db(tmp_path, "arch.db")
        bak = tmp_path / "bak"
        try:
            await db.insert_graph_fact(-100, "orphan", "chat_history", None)
            report = await mr.sanitize_beliefs(
                db, chat_ids=[-100], db_path=tmp_path / "arch.db",
                backup_dir=bak)
            assert report["candidates"] == report["archived"] == report["deleted"] == 1
            files = list(bak.glob("memory_generated_sanitize_*.jsonl"))
            assert len(files) == 1
            payload = json.loads(files[0].read_text(encoding="utf-8").strip())
            assert payload["fact"] == "orphan"
            # авто-бэкап создан (Backup API) — файл .db непуст
            backups = list(bak.glob("memory_rebuild_*.db"))
            assert backups and backups[0].stat().st_size > 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_archive_mismatch_aborts_delete(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "mism.db")
        try:
            await db.insert_graph_fact(-100, "orphan", "chat_history", None)

            async def _bad_archive(rows, directory, label):
                return True, 999, str(directory / "x.jsonl")
            monkeypatch.setattr(mr, "_archive_generated_rows", _bad_archive)
            report = await mr.sanitize_beliefs(
                db, chat_ids=[-100], db_path=tmp_path / "mism.db",
                backup_dir=tmp_path / "bak")
            assert report["reasons"].get("archive_mismatch") == 1
            assert report["deleted"] == 0
            # строки не удалены
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ?",
                (-100,)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_backup_unavailable_aborts(self, tmp_path):
        db = await _db(tmp_path, "nobak.db")
        try:
            await db.insert_graph_fact(-100, "orphan", "chat_history", None)
            report = await mr.sanitize_beliefs(
                db, chat_ids=[-100], db_path=None, backup_dir=tmp_path / "b")
            assert report["reasons"].get("backup_unavailable") == 1
            assert report["deleted"] == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_fsync_called_before_delete(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "fsync.db")
        events = []
        try:
            await db.insert_graph_fact(-100, "orphan", "chat_history", None)
            real_archive = mr._archive_generated_rows
            real_delete = mr.delete_generated_facts

            async def _spy_archive(rows, directory, label):
                result = await real_archive(rows, directory, label)
                events.append("fsync")
                return result

            async def _spy_delete(_db, ids, **kw):
                events.append("delete")
                return await real_delete(_db, ids, **kw)
            monkeypatch.setattr(mr, "_archive_generated_rows", _spy_archive)
            monkeypatch.setattr(mr, "delete_generated_facts", _spy_delete)
            await mr.sanitize_beliefs(
                db, chat_ids=[-100], db_path=tmp_path / "fsync.db",
                backup_dir=tmp_path / "bak")
            assert events == ["fsync", "delete"]
        finally:
            await db.close()


class TestPortraitResetAndRestore:
    @pytest.mark.asyncio
    async def test_rebuild_resets_portrait_and_rebuilds_one(
            self, tmp_path):
        db = await _db(tmp_path, "port.db")
        try:
            await db.insert_graph_fact(
                -100, "old meme", "chat_history", None, status="chat_meme",
                kind="fact")
            await db.upsert_generated_dossier(
                -100, "Никита", "старый портрет", ["p"], ["t"], 1)
            await db.set_dossier_override(-100, 7, "ручная", 1)

            async def _pipeline(chat_id):
                await db.upsert_generated_dossier(
                    chat_id, "Никита", "новый портрет", ["p2"], ["t2"], 2)
                return 1

            report = await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=_pipeline,
                db_path=tmp_path / "port.db", backup_dir=tmp_path / "bak")
            assert report["reset"] == 1
            assert report["reset_portraits"] == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ? "
                    "AND status = 'dossier_portrait'", (-100,)) == 1
            got = await db.get_generated_dossier(-100, "Никита")
            assert got["portrait"] == "новый портрет"
            assert got["patterns"] == ["p2"]
            assert await db.get_dossier_override(-100, 7) == "ручная"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_idempotent_second_run(self, tmp_path):
        db = await _db(tmp_path, "port_idem.db")
        try:
            async def _pipeline(chat_id):
                await db.upsert_generated_dossier(
                    chat_id, "Никита", "портрет", ["p"], ["t"], 2)
                return 0

            await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=_pipeline,
                db_path=tmp_path / "port_idem.db",
                backup_dir=tmp_path / "bak")
            await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=_pipeline,
                db_path=tmp_path / "port_idem.db",
                backup_dir=tmp_path / "bak")
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ? "
                    "AND status = 'dossier_portrait'", (-100,)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_dry_run_counts_portraits_but_keeps(self, tmp_path):
        db = await _db(tmp_path, "port_dry.db")
        try:
            await db.upsert_generated_dossier(
                -100, "Никита", "портрет", ["p"], ["t"], 1)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=None, dry_run=True,
                db_path=tmp_path / "port_dry.db", backup_dir=tmp_path / "bak")
            assert report["reset_portraits"] == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ? "
                    "AND status = 'dossier_portrait'", (-100,)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_point_restore_from_jsonl(self, tmp_path):
        """F5 spec §6.4: точечный restore сгенерированной строки из архива."""
        db = await _db(tmp_path, "restore.db")
        bak = tmp_path / "bak"
        try:
            await db.insert_graph_fact(
                -100, "спасённый мем", "chat_history", None,
                target_user="Вася", status="chat_meme", kind="fact",
                weight=0.4)
            pipeline = _FakePipeline(written=0)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=pipeline,
                db_path=tmp_path / "restore.db", backup_dir=bak)
            assert report["reset"] == 1
            assert await db.list_chat_memes(-100) == []
            files = list(bak.glob("memory_generated_rebuild_*.jsonl"))
            assert len(files) == 1
            payload = json.loads(
                files[0].read_text(encoding="utf-8").strip())
            assert payload["fact"] == "спасённый мем"
            restored = await db.insert_graph_fact(
                payload.get("chat_id", -100), payload["fact"],
                "chat_history", None,
                target_user=payload["target_user"],
                status=payload["status"], kind=payload["kind"],
                weight=payload["weight"])
            assert restored > 0
            memes = await db.list_chat_memes(-100, "Вася")
            assert [m["fact"] for m in memes] == ["спасённый мем"]
        finally:
            await db.close()


class TestOverrides:
    @pytest.mark.asyncio
    async def test_overrides_untouched_by_default(self, tmp_path):
        db = await _db(tmp_path, "ovr.db")
        try:
            await db.insert_graph_fact(
                -100, "old meme", "chat_history", None, status="chat_meme",
                kind="fact")
            await db.set_dossier_override(-100, 7, "ручная правка", 1)
            pipeline = _FakePipeline(written=0)
            await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=pipeline,
                db_path=tmp_path / "ovr.db", backup_dir=tmp_path / "bak")
            assert await db.get_dossier_override(-100, 7) == "ручная правка"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_overrides_reset_with_flag(self, tmp_path):
        db = await _db(tmp_path, "ovr2.db")
        try:
            await db.set_dossier_override(-100, 7, "ручная правка", 1)
            pipeline = _FakePipeline(written=0)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=pipeline, include_overrides=True,
                db_path=tmp_path / "ovr2.db", backup_dir=tmp_path / "bak")
            assert report["reasons"].get("overrides_reset") == 1
            assert await db.get_dossier_override(-100, 7) == ""
        finally:
            await db.close()


class TestDryRun:
    @pytest.mark.asyncio
    async def test_sanitize_dry_run_writes_nothing(self, tmp_path):
        db = await _db(tmp_path, "dry.db")
        bak = tmp_path / "bak"
        try:
            await db.insert_graph_fact(-100, "orphan", "chat_history", None)
            report = await mr.sanitize_beliefs(
                db, chat_ids=[-100], dry_run=True, db_path=tmp_path / "dry.db",
                backup_dir=bak)
            assert report["deleted"] == 0 and report["archived"] == 0
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ?",
                (-100,)) == 1
            assert not bak.exists()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_dry_run_writes_nothing(self, tmp_path):
        db = await _db(tmp_path, "dry_rb.db")
        try:
            await db.insert_graph_fact(
                -100, "old meme", "chat_history", None, status="chat_meme",
                kind="fact")
            pipeline = _FakePipeline(written=5)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=pipeline, dry_run=True,
                db_path=tmp_path / "dry_rb.db", backup_dir=tmp_path / "bak")
            assert report["reset"] == 1 and report["rebuilt"] == 0
            assert pipeline.calls == []
            assert len(await db.list_chat_memes(-100)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_without_pipeline_aborts(self, tmp_path):
        db = await _db(tmp_path, "nopipe.db")
        try:
            await db.insert_graph_fact(
                -100, "old meme", "chat_history", None, status="chat_meme",
                kind="fact")
            report = await mr.rebuild_dossiers(
                db, chat_ids=[-100], pipeline=None,
                db_path=tmp_path / "nopipe.db", backup_dir=tmp_path / "bak")
            assert report["reasons"].get("no_pipeline") == 1
            assert report["reset"] == 0
            assert len(await db.list_chat_memes(-100)) == 1
        finally:
            await db.close()


class TestBeliefValidator:
    def test_count_agnostic_valid_and_invalid(self):
        good = {"fact": "убеждение", "source_ids": "[1, 2]",
                "belief_meta": '{"type": "belief"}'}
        assert mr.validate_belief_row(good, {1, 2}) is None
        assert mr.validate_belief_row(
            {"fact": "", "source_ids": "[1]"}, {1}) == "empty_text"
        assert mr.validate_belief_row(
            {"fact": "x", "source_ids": "[]"}, set()) == "no_sources"
        assert mr.validate_belief_row(
            {"fact": "x", "source_ids": "[1]"}, {2}) == "missing_sources"
        assert mr.validate_belief_row(
            {"fact": "x", "source_ids": "[1]", "belief_meta": "{bad"},
            {1}) == "bad_meta"

    @pytest.mark.asyncio
    async def test_sanitize_removes_invalid_belief_only(self, tmp_path):
        db = await _db(tmp_path, "bel.db")
        try:
            f1 = await db.insert_graph_fact(-100, "fact", "chat_history", None)
            valid = await db.insert_graph_fact(
                -100, "valid belief", "derived_belief", None, kind="belief",
                source_ids=json.dumps([f1]),
                belief_meta=json.dumps({"type": "belief"}))
            invalid = await db.insert_graph_fact(
                -100, "broken belief", "derived_belief", None, kind="belief",
                source_ids=json.dumps([999999]),
                belief_meta=json.dumps({"type": "belief"}))
            report = await mr.sanitize_beliefs(
                db, chat_ids=[-100], db_path=tmp_path / "bel.db",
                backup_dir=tmp_path / "bak")
            assert report["classes"].get("invalid_belief") == 1
            ids = [r["id"] for r in await db.list_recent_beliefs(chat_id=-100)]
            assert valid in ids and invalid not in ids
        finally:
            await db.close()


class TestTargetChatGuard:
    def test_all_excludes_target(self):
        args = argparse.Namespace(chat=None, all=True, allow_target_chat=False)
        chats = manage._memory_scope(args, [TARGET_CHAT_ID, -100],
                                     required=True)
        assert chats == [-100]

    def test_explicit_target_requires_flag(self):
        args = argparse.Namespace(chat=[TARGET_CHAT_ID], all=False,
                                  allow_target_chat=False)
        with pytest.raises(SystemExit):
            manage._memory_scope(args, [TARGET_CHAT_ID, -100], required=True)

    def test_explicit_target_with_flag_allowed(self):
        args = argparse.Namespace(chat=[TARGET_CHAT_ID], all=False,
                                  allow_target_chat=True)
        assert manage._memory_scope(args, [TARGET_CHAT_ID], required=True) \
            == [TARGET_CHAT_ID]

    def test_scope_required(self):
        args = argparse.Namespace(chat=None, all=False, allow_target_chat=False)
        with pytest.raises(SystemExit):
            manage._memory_scope(args, [-100], required=True)

    def test_consolidate_optional_scope(self):
        args = argparse.Namespace(chat=None, all=False, allow_target_chat=False)
        assert manage._memory_scope(args, [TARGET_CHAT_ID, -100],
                                    required=False) == [-100]


class TestCliContract:
    def test_default_is_apply(self):
        parser = manage.build_parser()
        args = parser.parse_args(["memory", "sanitize-beliefs", "--all"])
        assert args.dry_run is False
        args2 = parser.parse_args(
            ["memory", "rebuild-dossiers", "--all", "--dry-run"])
        assert args2.dry_run is True

    def test_subcommands_present(self):
        parser = manage.build_parser()
        for command in ("rebuild-dossiers", "sanitize-beliefs", "consolidate",
                        "audit"):
            args = parser.parse_args(["memory", command])
            assert args.memory_command == command
