"""F1 (`urgent-rebuild-dossiers-target-chat-round1022`, ADR-1022-1, UPD3):
confirmed-cleanup досье-фактов + окно 180 дней + инварианты.

Проверяем (spec §2.5/§2.6, задачи T-2090/T-2091):
  * удаляются РОВНО `chat_id AND kind='fact' AND status='confirmed' AND
    target_user` (непустой) — питают «Досье» (`get_persona_card`);
  * beliefs/парадигмы, `nodes`/`edges`, `persona_dossier_overrides` и сырая
    история (`smart_messages`+FTS) НЕ мутируются;
  * защита `source_ids`/`evidence` живых beliefs (`protected_belief_sources`);
  * JSONL-архив ДО удаления + сверка `candidates == archived` (иначе отмена);
  * окно боевого прогона = 4320 ч + `effective_window`/`source_age_days` (R1b);
  * `rebuild_empty` → reason + ненулевой exit-код.

Фикстуры синтетические (временная SQLite). R17: в отчётах/логах только числа.
"""
import argparse
import json

import pytest

import manage
from services import memory_rebuild as mr
from services.database import DatabaseService

TARGET_CHAT_ID = -1002661910336
CHAT = -500


async def _db(tmp_path, name="cleanup.db"):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _count(db, sql, params=()):
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _insert_msg(db, chat_id, text, ts=1):
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type) VALUES (1, ?, ?, ?, 'text')", (chat_id, text, ts))
    await db.db.execute(
        "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
        (cursor.lastrowid, text))
    await db.db.commit()


async def _age_fact(db, fact_id, seconds):
    """Сдвинуть created_at тестовой строки в прошлое (R1b-кейс)."""
    import time
    await db.db.execute("UPDATE graph_facts SET created_at = ? WHERE id = ?",
                        (int(time.time()) - int(seconds), int(fact_id)))
    await db.db.commit()


class _FakePipeline:
    def __init__(self, written=0):
        self.calls = []
        self.written = written

    async def __call__(self, chat_id):
        self.calls.append(chat_id)
        return self.written


class _WindowPipeline:
    """Pipeline, принимающий effective_window (как CLI-обёртка)."""

    def __init__(self, written=0):
        self.calls = []
        self.windows = []
        self.written = written

    async def __call__(self, chat_id, window_hours=None):
        self.calls.append(chat_id)
        self.windows.append(window_hours)
        return self.written


class TestConfirmedCleanupScope:
    @pytest.mark.asyncio
    async def test_deletes_only_confirmed_person_facts(self, tmp_path):
        db = await _db(tmp_path)
        try:
            f_del = await db.insert_graph_fact(
                CHAT, "мусорный факт", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            f_no_user = await db.insert_graph_fact(
                CHAT, "чат-факт без личности", "chat_history", None,
                target_user=None, status="confirmed", kind="fact")
            f_empty = await db.insert_graph_fact(
                CHAT, "пустой target", "chat_history", None,
                target_user="", status="confirmed", kind="fact")
            f_belief = await db.insert_graph_fact(
                CHAT, "убеждение Ани", "derived_belief", None,
                target_user="Аня", status="confirmed", kind="belief")
            f_unconf = await db.insert_graph_fact(
                CHAT, "неподтверждённый", "chat_history", None,
                target_user="Аня", status="unconfirmed", kind="fact")
            await db.set_dossier_override(CHAT, 7, "ручная", 1)
            n1 = await db.upsert_node(CHAT, "Аня", "user")
            n2 = await db.upsert_node(CHAT, "тема", "topic")
            await db.upsert_edge(n1, n2, "about", fact_id=f_del)
            await _insert_msg(db, CHAT, "сырая история")

            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=False,
                backup_dir=tmp_path / "bak")

            assert report["candidates"] == report["cleaned"] == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE id = ?",
                (f_del,)) == 0
            for kept in (f_no_user, f_empty, f_belief, f_unconf):
                assert await _count(
                    db, "SELECT COUNT(*) FROM graph_facts WHERE id = ?",
                    (kept,)) == 1
            # overrides / nodes / edges / сырая история — целы
            assert await db.get_dossier_override(CHAT, 7) == "ручная"
            assert await _count(db, "SELECT COUNT(*) FROM nodes") == 2
            assert await _count(db, "SELECT COUNT(*) FROM edges") == 1
            assert await db.count_smart_messages(CHAT) == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM smart_messages_fts") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_jsonl_archive_written_before_delete(self, tmp_path):
        db = await _db(tmp_path)
        bak = tmp_path / "bak"
        try:
            await db.insert_graph_fact(
                CHAT, "архивный факт", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=False, backup_dir=bak)
            assert report["cleaned"] == report["archived"] == 1
            files = list(bak.glob("memory_generated_confirmed_*.jsonl"))
            assert len(files) == 1
            payload = json.loads(
                files[0].read_text(encoding="utf-8").strip())
            assert payload["fact"] == "архивный факт"
            assert payload["target_user"] == "Аня"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_archive_mismatch_aborts_delete(self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        try:
            await db.insert_graph_fact(
                CHAT, "неудаляемый", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")

            async def _bad_archive(rows, directory, label):
                return True, 999, str(directory / "x.jsonl")
            monkeypatch.setattr(mr, "_archive_generated_rows", _bad_archive)
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=False,
                backup_dir=tmp_path / "bak")
            assert report["reasons"].get(
                "confirmed_cleanup_archive_mismatch") == 1
            assert report["cleaned"] == 0
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ?",
                (CHAT,)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_dry_run_counts_but_keeps(self, tmp_path):
        db = await _db(tmp_path)
        bak = tmp_path / "bak"
        try:
            await db.insert_graph_fact(
                CHAT, "кандидат", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=True, backup_dir=bak)
            assert report["candidates"] == 1 and report["cleaned"] == 0
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ?",
                (CHAT,)) == 1
            assert not bak.exists()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_pagination_cleans_beyond_first_batch(self, tmp_path):
        """Ревью (High-1): keyset-пагинация очищает > batch кандидатов."""
        db = await _db(tmp_path)
        try:
            for i in range(5):
                await db.insert_graph_fact(
                    CHAT, f"факт {i}", "chat_history", None,
                    target_user="Аня", status="confirmed", kind="fact")
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=False,
                backup_dir=tmp_path / "bak", batch=2)
            assert report["candidates"] == 5
            assert report["cleaned"] == 5
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE chat_id = ? "
                    "AND kind = 'fact' AND status = 'confirmed'",
                (CHAT,)) == 0
        finally:
            await db.close()


class TestBeliefProtection:
    @pytest.mark.asyncio
    async def test_belief_sources_protected(self, tmp_path):
        db = await _db(tmp_path)
        try:
            f_src = await db.insert_graph_fact(
                CHAT, "опора убеждения", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            await db.insert_graph_fact(
                CHAT, "убеждение", "derived_belief", None,
                target_user="Аня", status="confirmed", kind="belief",
                source_ids=json.dumps([f_src]),
                belief_meta=json.dumps({"type": "belief"}))
            f_free = await db.insert_graph_fact(
                CHAT, "свободный факт", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=False,
                backup_dir=tmp_path / "bak")
            # candidates — только УДАЛЯЕМЫЕ (опора belief исключена и посчитана
            # отдельно в protected_belief_sources)
            assert report["candidates"] == 1
            assert report["cleaned"] == 1
            assert report["protected_belief_sources"] == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE id = ?",
                (f_src,)) == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE id = ?",
                (f_free,)) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_belief_protection_beyond_first_batch(self, tmp_path):
        """Ревью (High-1): опора belief из «хвостового» батча защищена."""
        db = await _db(tmp_path)
        try:
            f_protected = await db.insert_graph_fact(
                CHAT, "опора из хвоста", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            for i in range(2):
                await db.insert_graph_fact(
                    CHAT, f"прочее убеждение {i}", "derived_belief", None,
                    target_user="Аня", status="confirmed", kind="belief")
            await db.insert_graph_fact(
                CHAT, "убеждение-хвост", "derived_belief", None,
                target_user="Аня", status="confirmed", kind="belief",
                source_ids=json.dumps([f_protected]),
                belief_meta=json.dumps({"type": "belief"}))
            for i in range(3):
                await db.insert_graph_fact(
                    CHAT, f"мусор {i}", "chat_history", None,
                    target_user="Аня", status="confirmed", kind="fact")
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=False,
                backup_dir=tmp_path / "bak", batch=2)
            assert report["protected_belief_sources"] == 1
            assert report["cleaned"] == 3
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE id = ?",
                (f_protected,)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_target_user_scoped(self, tmp_path):
        db = await _db(tmp_path)
        try:
            await db.insert_graph_fact(
                CHAT, "факт Ани", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            await db.insert_graph_fact(
                CHAT, "факт Бори", "chat_history", None,
                target_user="Боря", status="confirmed", kind="fact")
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], target_user="Аня", dry_run=False,
                backup_dir=tmp_path / "bak")
            assert report["candidates"] == report["cleaned"] == 1
            names = [r["target_user"] for r in
                     (await (await db.db.execute(
                         "SELECT target_user FROM graph_facts "
                         "WHERE chat_id = ?", (CHAT,))).fetchall())]
            assert names == ["Боря"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_belief_read_error_skips_chat_fail_closed(
            self, tmp_path, monkeypatch):
        """S10.22-1: ошибка чтения beliefs НЕ глушится — чат помечается
        `read_error` и его cleanup пропускается (fail-closed), иначе пустой
        `protected_ids` удалил бы опоры живых убеждений (класс S10.21-3)."""
        db = await _db(tmp_path)
        try:
            f_src = await db.insert_graph_fact(
                CHAT, "опора убеждения", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            await db.insert_graph_fact(
                CHAT, "убеждение", "derived_belief", None,
                target_user="Аня", status="confirmed", kind="belief",
                source_ids=json.dumps([f_src]))

            async def _boom(*args, **kwargs):
                raise RuntimeError("simulated locked")

            monkeypatch.setattr(mr, "_list_beliefs", _boom)
            report = await mr.cleanup_confirmed_dossier_facts(
                db, chat_ids=[CHAT], dry_run=False, backup_dir=tmp_path / "bak")
            assert report["reasons"].get("read_error") == 1
            assert report["cleaned"] == 0 and report["candidates"] == 0
            # факт-опора не удалён (cleanup чата аварийно прерван)
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE id = ?",
                (f_src,)) == 1
        finally:
            await db.close()


class TestWindowAndRebuild:
    def test_effective_window_covers_old_rows(self):
        now = 100_000_000.0
        # 200 дней назад → окно обязано быть ≥ 4800 ч (200*24 + 24)
        oldest = now - 200 * 86400
        eff, age_days = mr._effective_window(4320, oldest, now)
        assert eff >= 200 * 24
        assert age_days == 200.0

    def test_window_zero_is_unlimited(self):
        now = 100_000_000.0
        eff, age_days = mr._effective_window(0, now - 100 * 86400, now)
        assert eff == 0
        assert age_days == 100.0

    @pytest.mark.asyncio
    async def test_rebuild_uses_effective_window(self, tmp_path):
        db = await _db(tmp_path)
        try:
            fid = await db.insert_graph_fact(
                CHAT, "старый мем", "chat_history", None,
                target_user="Аня", status="chat_meme", kind="fact")
            await _age_fact(db, fid, 200 * 86400)
            pipeline = _WindowPipeline(written=2)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[CHAT], pipeline=pipeline, window_hours=4320,
                db_path=tmp_path / "cleanup.db", backup_dir=tmp_path / "bak")
            assert report["reset"] == 1 and report["rebuilt"] == 2
            assert report["window_hours_used"] >= 200 * 24
            assert pipeline.windows == [report["window_hours_used"]]
            assert report["source_age_days"] >= 199
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_empty_reason_and_exit_code(self, tmp_path):
        db = await _db(tmp_path)
        try:
            await db.insert_graph_fact(
                CHAT, "старый мем", "chat_history", None,
                target_user="Аня", status="chat_meme", kind="fact")
            pipeline = _FakePipeline(written=0)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[CHAT], pipeline=pipeline,
                db_path=tmp_path / "cleanup.db", backup_dir=tmp_path / "bak")
            assert report["reasons"].get("rebuild_empty") == 1
            assert manage._memory_exit_code("rebuild-dossiers", report) == 1
            assert manage._memory_exit_code(
                "rebuild-dossiers", {"reasons": {}}) == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rebuild_cleans_confirmed_and_reports(self, tmp_path):
        db = await _db(tmp_path)
        try:
            await db.insert_graph_fact(
                CHAT, "мусор Ани", "chat_history", None,
                target_user="Аня", status="confirmed", kind="fact")
            await _insert_msg(db, CHAT, "сырая")
            pipeline = _FakePipeline(written=1)
            report = await mr.rebuild_dossiers(
                db, chat_ids=[CHAT], pipeline=pipeline,
                db_path=tmp_path / "cleanup.db", backup_dir=tmp_path / "bak")
            assert report["cleaned_facts"] == 1
            assert report["confirmed_candidates"] == 1
            assert report["rebuilt"] == 1
            assert report["window_hours_used"] == 4320
            # сырая история не изменена
            assert await db.count_smart_messages(CHAT) == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM smart_messages_fts") == 1
        finally:
            await db.close()

    def test_default_rebuild_window_is_180_days(self):
        parser = manage.build_parser()
        args = parser.parse_args(["memory", "rebuild-dossiers", "--all"])
        assert args.window_hours == 4320


class TestTargetChatShortcut:
    def test_target_chat_flag_implies_scope(self):
        parser = manage.build_parser()
        args = parser.parse_args(
            ["memory", "rebuild-dossiers", "--target-chat"])
        assert args.target_chat is True
        assert manage._memory_scope(
            args, [TARGET_CHAT_ID, CHAT], required=True) == [TARGET_CHAT_ID]

    def test_all_still_excludes_target(self):
        parser = manage.build_parser()
        args = parser.parse_args(["memory", "rebuild-dossiers", "--all"])
        assert manage._memory_scope(
            args, [TARGET_CHAT_ID, CHAT], required=True) == [CHAT]

    def test_target_chat_only_on_rebuild(self):
        parser = manage.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["memory", "sanitize-beliefs", "--target-chat", "--all"])
