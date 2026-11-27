"""P0-FTS-INDEX-INTEGRITY-01 — целостность external-content FTS `graph_facts_fts`.

Источник: plans/features/p0-fts-index-integrity-01/source-2026-11-28.md.
Прод-факт 2.58.259: `docsize` = 44 216 при 44 196 строках `graph_facts` и
`malformed inverted index`. Причина: `INSERT OR REPLACE INTO graph_facts`
(scenically `restore_user_snapshot`) — скрытый DELETE, невидимый FTS5:
  * конфликт по НЕ-PK UNIQUE удаляет ЧУЖУЮ строку, её FTS-запись остаётся
    (docsize растёт, MATCH находит удалённый id);
  * замена текста по PK оставляет СТАРЫЕ токены в индексе (после корректного
    удаления строки старый текст всё ещё находится MATCH'ем).

Проверки:
  * RED (база): restore с UNIQUE-конфликтом → `docsize` > facts / orphan;
  * RED (база): restore с заменой текста → старый токен остаётся в MATCH;
  * негативный контроль: чистая БД — 0 расхождений;
  * maintenance: `inspect_graph_facts_fts` находит искусственную порчу,
    `repair_graph_facts_fts` чинит штатным `'rebuild'` и идемпотентен;
  * MATCH после удаления не возвращает удалённую строку;
  * CLI `manage.py memory fts-check / fts-repair` (read-only / apply).

TEST-LIFECYCLE: REGRESSION owner=FTSI-ACC-01/02/03/05
R17: только числа/идентификаторы, без текстов фактов и путей.
"""
import asyncio
import json

import pytest

import manage
from services import dossier_rebuild_jobs as drj
from services.database import DatabaseService

CHAT = -100700
TS = 1_700_000_000


async def _db(tmp_path):
    db = DatabaseService(str(tmp_path / "fts_integrity.db"))
    await db.initialize()
    return db


async def _scalar(db, sql, params=()):
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return row[0] if row else None


async def _match_ids(db, term):
    cursor = await db.db.execute(
        "SELECT rowid FROM graph_facts_fts WHERE graph_facts_fts MATCH ? "
        "ORDER BY rowid", (f'"{term}"*',))
    return [int(r[0]) for r in await cursor.fetchall()]


async def _snapshot_row(db, fact_id):
    cursor = await db.db.execute(
        "SELECT * FROM graph_facts WHERE id = ?", (fact_id,))
    return dict(await cursor.fetchone())


def _write_snapshot(path, row):
    path.write_text(json.dumps(row, ensure_ascii=False, default=str) + "\n",
                    encoding="utf-8")


@pytest.mark.asyncio
async def test_restore_unique_conflict_leaves_no_orphan_docsize(tmp_path):
    """FTSI-ACC-01/02 (RED на базе): скрытый DELETE от `INSERT OR REPLACE`
    по частичному UNIQUE `(chat_id, fact, message_timestamp)` не должен
    оставлять docsize-строку удалённого id."""
    db = await _db(tmp_path)
    try:
        old_id = await db.insert_graph_fact(
            CHAT, "импортный факт про ракетоносец", "history_import", None,
            message_timestamp=TS)
        row = await _snapshot_row(db, old_id)
        row["id"] = 900001          # новый id, тот же UNIQUE-ключ
        path = tmp_path / "snap_unique.jsonl"
        _write_snapshot(path, row)

        restored = await drj.restore_user_snapshot(db, path)
        assert restored == 1

        facts = await _scalar(db, "SELECT COUNT(*) FROM graph_facts")
        docsize = await _scalar(
            db, "SELECT COUNT(*) FROM graph_facts_fts_docsize")
        orphan = await _scalar(
            db, "SELECT COUNT(*) FROM graph_facts_fts_docsize "
                "WHERE rowid NOT IN (SELECT id FROM graph_facts)")
        assert facts == 1
        assert docsize == facts            # RED на базе: 2 != 1
        assert orphan == 0
        # Единственный живой факт находится; удалённый id 1 — нет.
        assert await _match_ids(db, "ракетоносец") == [900001]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_restore_text_replacement_drops_old_tokens(tmp_path):
    """FTSI-ACC-01/02 (RED на базе): замена текста по PK не должна оставлять
    старые токены; после удаления строки старый текст не находится MATCH'ем."""
    db = await _db(tmp_path)
    try:
        fid = await db.insert_graph_fact(
            CHAT, "старый факт про трактор", "chat_history", None)
        row = await _snapshot_row(db, fid)
        row["fact"] = "новый факт про комбайн"
        path = tmp_path / "snap_replace.jsonl"
        _write_snapshot(path, row)

        await drj.restore_user_snapshot(db, path)
        assert await _match_ids(db, "трактор") == []   # RED на базе: [fid]
        assert await _match_ids(db, "комбайн") == [fid]

        await db.delete_graph_fact(fid)
        assert await _match_ids(db, "трактор") == []
        assert await _match_ids(db, "комбайн") == []
        facts = await _scalar(db, "SELECT COUNT(*) FROM graph_facts")
        docsize = await _scalar(
            db, "SELECT COUNT(*) FROM graph_facts_fts_docsize")
        assert facts == docsize == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_clean_database_has_no_fts_discrepancy(tmp_path):
    """FTSI-ACC-05 (негативный контроль): штатные insert/delete не создают
    расхождений — счётчики сходятся, висячих/пропущенных записей нет."""
    from services.memory_rebuild import inspect_graph_facts_fts

    db = await _db(tmp_path)
    try:
        ids = [
            await db.insert_graph_fact(
                CHAT, f"чистый факт {i}", "chat_history", None)
            for i in range(3)
        ]
        await db.delete_graph_fact(ids[1])

        report = await inspect_graph_facts_fts(db)
        assert report["ok"] is True
        assert report["facts"] == 2
        assert report["docsize"] == report["fts_docs"] == 2
        assert report["orphan_docsize"] == 0
        assert report["missing_docsize"] == 0
        assert report["db_integrity"] == "ok"
        assert report["fts_integrity"] in ("ok", "skipped_readonly")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fts_repair_heals_artificial_orphan_and_is_idempotent(tmp_path):
    """FTSI-ACC-03: maintenance находит искусственную порчу, чинит штатным
    `'rebuild'` и не делает ничего при повторном запуске."""
    from services.memory_rebuild import (
        inspect_graph_facts_fts,
        repair_graph_facts_fts,
    )

    db = await _db(tmp_path)
    try:
        await db.insert_graph_fact(
            CHAT, "живой факт про двигатель", "chat_history", None)
        # Искусственная «историческая» утечка: FTS-строка без content-строки.
        await db.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (424242, "фантомный токен"))
        await db.db.commit()

        before = await inspect_graph_facts_fts(db)
        assert before["ok"] is False
        assert before["docsize"] == before["facts"] + 1
        assert before["orphan_docsize"] == 1
        assert 424242 in before["orphan_sample"]
        assert await _match_ids(db, "фантомный") == [424242]

        repaired = await repair_graph_facts_fts(db)
        assert repaired["rebuilt"] is True
        after = repaired["after"]
        assert after["ok"] is True
        assert after["docsize"] == after["facts"]
        assert after["orphan_docsize"] == 0
        assert await _match_ids(db, "фантомный") == []
        assert await _match_ids(db, "двигатель") != []

        again = await repair_graph_facts_fts(db)
        assert again["rebuilt"] is False
        assert again["after"] == again["before"]
        assert again["after"]["ok"] is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_match_after_delete_returns_no_deleted_row(tmp_path):
    """FTSI-ACC-01(d): после удаления факта MATCH не возвращает его id и
    docsize соответствует таблице (прямой штатный путь delete_graph_fact)."""
    db = await _db(tmp_path)
    try:
        fid = await db.insert_graph_fact(
            CHAT, "удаляемый факт про подводную лодку", "chat_history", None)
        assert await _match_ids(db, "лодку") == [fid]
        await db.delete_graph_fact(fid)
        assert await _match_ids(db, "лодку") == []
        facts = await _scalar(db, "SELECT COUNT(*) FROM graph_facts")
        docsize = await _scalar(
            db, "SELECT COUNT(*) FROM graph_facts_fts_docsize")
        assert facts == docsize == 0
    finally:
        await db.close()


def _prepare_cli_db(path):
    async def _prepare():
        db = DatabaseService(str(path))
        await db.initialize()
        try:
            await db.insert_graph_fact(
                CHAT, "факт для CLI проверки", "chat_history", None)
            await db.db.execute(
                "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
                (424242, "фантомный токен"))
            await db.db.commit()
        finally:
            await db.close()

    asyncio.run(_prepare())


def test_cli_fts_check_and_repair(tmp_path, capsys):
    """FTSI-ACC-03: существующая maintenance-обвязка `manage.py memory`.
    `fts-check` — read-only (rc=1 при расхождении), `fts-repair` — починка
    (rc=0), повторный `fts-check` — ok, повторный `fts-repair` — no-op."""
    path = tmp_path / "cli_fts.db"
    _prepare_cli_db(path)

    rc = manage.main(["memory", "fts-check", "--db", str(path)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "ok=False" in out
    assert "orphan_docsize=1" in out

    rc = manage.main(["memory", "fts-repair", "--db", str(path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "rebuilt=yes" in out

    rc = manage.main(["memory", "fts-check", "--db", str(path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "ok=True" in out
    assert "docsize=1" in out

    rc = manage.main(["memory", "fts-repair", "--db", str(path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "rebuilt=no" in out
