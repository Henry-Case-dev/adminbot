"""F8 round 10.22 (dossier-rebuild-async-ui-round1022, ADR-1022-8).

Покрытие (spec §2/§3, задачи T-2078…T-2088):
  * job-store: атомарная персистентность, retention, `interrupted` при
    рестарте, in-memory/файловый job-view «X/Y» (R17: числа/коды);
  * снапшот производных юзера + rollback (восстановление досье/фактов,
    идемпотентность), неприкосновенность `smart_messages`/
    `persona_dossier_overrides`/beliefs/nodes/edges;
  * раннер: cancel → rollback, `done` без отмены, `snapshot_failed` fail-closed;
  * API: start (202)/status/latest/cancel, 409 конкурентность, RBAC, флаг OFF,
    fail-open `latest` → 204, маппинг period→окно;
  * движок `LoreWorker.rebuild_dossier_for_user`: чанки, progress_cb, cancel_cb,
    target-scoped запись.

R17: в тестах проверяются числа/коды; секреты не используются.
"""
import asyncio
import json
import time
import types

import pytest
from fastapi.testclient import TestClient

import manage
from config.settings import Settings, settings
from services import dossier_rebuild_jobs as drj
from services import lore_runtime
from services.config_cache import ConfigCache
from services.database import DatabaseService
from services.lore_cache import LoreProfile
from services.lore_worker import LoreWorker
from web.app import create_app
from web.api import chat_lore as cl_mod
from web.api import deps as deps_mod

CHAT = -100500
USER_ID = 5
ADMIN_ID = 5885953495
USER_TG = 999999999
TARGET = "Аня"

TEST_TOKEN = "123456:TEST_TOKEN_DOSSIER_REBUILD"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    import hashlib
    import hmac
    import urllib.parse

    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHDossier",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _h(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": _hdr(user_id)}


# ── БД-хелперы ──────────────────────────────────────────────────────────────

async def _db(tmp_path, name="dossier_rebuild.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _count(db, sql, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _add_msg(db, chat_id, author, text, ts=None, user_id=2):
    ts = int(ts if ts is not None else time.time())
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "author_name, media_type) VALUES (?, ?, ?, ?, ?, 'text')",
        (user_id, chat_id, text, ts, author))
    await db.db.execute(
        "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
        (cursor.lastrowid, text))
    await db.db.commit()
    return cursor.lastrowid


# ═══ Job-store ══════════════════════════════════════════════════════════════

class TestJobStore:
    @pytest.mark.asyncio
    async def test_persists_across_instances(self, tmp_path):
        store = drj.DossierRebuildJobStore(base_dir=tmp_path)
        await store.create("j1", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET, period="180",
                           window_hours=4320, chunk_size=40, total=3)
        await store.update("j1", status="running", processed=1)

        reopened = drj.DossierRebuildJobStore(base_dir=tmp_path)
        job = await reopened.get("j1")
        assert job is not None and job["status"] == "running"
        assert job["processed"] == 1
        assert (await reopened.latest(CHAT, USER_ID))["job_id"] == "j1"
        assert await reopened.latest(CHAT, 999) is None

    @pytest.mark.asyncio
    async def test_view_is_counts_only(self, tmp_path):
        store = drj.DossierRebuildJobStore(base_dir=tmp_path)
        await store.create("j1", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET, period="90",
                           window_hours=2160, chunk_size=40, total=4)
        await store.update("j1", status="running", processed=2)
        view = drj.job_view(await store.get("j1"))
        assert view["percent"] == 50
        assert view["total"] == 4 and view["processed"] == 2
        # R17: текстов/полных путей/резолва имён нет
        assert "target_name" not in view
        assert "/" not in view["snapshot_ref"]
        assert set(view).issuperset(
            {"job_id", "status", "stage", "rollback", "percent"})

    @pytest.mark.asyncio
    async def test_retention_keeps_active_and_caps_terminal(self, tmp_path):
        store = drj.DossierRebuildJobStore(base_dir=tmp_path, retention_max=5,
                                           retention_days=3650)
        await store.create("active", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET)
        for index in range(8):
            jid = f"t{index}"
            await store.create(jid, chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET)
            await store.update(jid, status="done", finished_at=1000 + index)
        jobs = json.loads(
            (store.dir_path / "dossier_rebuild_jobs.json").read_text("utf-8"))
        terminal = [j for j in jobs["jobs"] if j["status"] == "done"]
        active = [j for j in jobs["jobs"] if j["job_id"] == "active"]
        assert len(terminal) <= 5
        assert len(active) == 1
        # самые старые терминальные вытеснены
        assert "t0" not in {j["job_id"] for j in jobs["jobs"]}

    @pytest.mark.asyncio
    async def test_reconcile_marks_nonterminal_interrupted(self, tmp_path):
        store = drj.DossierRebuildJobStore(base_dir=tmp_path,
                                           retention_days=3650)
        await store.create("run", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET)
        await store.update("run", status="running")
        await store.create("fin", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET)
        await store.update("fin", status="done",
                           finished_at=int(time.time()))

        changed = await store.reconcile_interrupted()
        assert changed == 1
        assert (await store.get("run"))["status"] == "interrupted"
        assert (await store.get("fin"))["status"] == "done"

    @pytest.mark.asyncio
    async def test_interrupted_does_not_block_new_start(self, tmp_path):
        """S10.22-5: `interrupted` не считается активным — новый старт
        разрешён (find_active → None), прежний job остаётся для отката."""
        store = drj.DossierRebuildJobStore(base_dir=tmp_path,
                                           retention_days=3650)
        await store.create("old", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET)
        await store.update("old", status="interrupted",
                           error_code="process_restart")
        assert await store.find_active(CHAT, USER_ID) is None
        # работающий job по-прежнему блокирует
        await store.create("live", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET)
        await store.update("live", status="running")
        assert (await store.find_active(CHAT, USER_ID))["job_id"] == "live"

    @pytest.mark.asyncio
    async def test_interrupted_evicted_by_retention(self, tmp_path):
        """S10.22-5: `interrupted` подчиняется retention (не копится вечно)."""
        store = drj.DossierRebuildJobStore(base_dir=tmp_path,
                                           retention_max=0, retention_days=1)
        await store.create("stale", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET)
        old = int(time.time()) - 10 * 86400
        await store.update("stale", status="interrupted", created_at=old,
                           finished_at=old)
        await store.create("new", chat_id=CHAT, user_id=USER_ID,
                           target_name=TARGET)
        assert await store.get("stale") is None
        assert await store.get("new") is not None

    @pytest.mark.asyncio
    async def test_chat_lock_exclusive_and_stale(self, tmp_path):
        first = drj.acquire_chat_lock(tmp_path, CHAT)
        assert first is not None
        assert drj.acquire_chat_lock(tmp_path, CHAT) is None
        first.release()
        again = drj.acquire_chat_lock(tmp_path, CHAT)
        assert again is not None
        again.release()
        # stale-перехват по TTL
        lock = drj.acquire_chat_lock(tmp_path, CHAT)
        lock_path = lock.path
        lock_path.write_text(json.dumps({"pid": 1, "ts": 1}), encoding="utf-8")
        lock._released = True
        assert drj.acquire_chat_lock(tmp_path, CHAT, ttl_seconds=1) is not None

    @pytest.mark.asyncio
    async def test_fresh_lock_not_stolen(self, tmp_path):
        """Ревью (Medium-6): свежий lock (наш pid/ts) не перехватывается."""
        first = drj.acquire_chat_lock(tmp_path, CHAT)
        assert first is not None
        assert drj.acquire_chat_lock(tmp_path, CHAT, ttl_seconds=3600) is None
        first.release()

    @pytest.mark.asyncio
    async def test_stale_takeover_serialized_by_marker(self, tmp_path):
        """Ревью (Medium-6): stale-перехват атомарен (takeover-маркер)."""
        lock = drj.acquire_chat_lock(tmp_path, CHAT)
        lock.path.write_text(json.dumps({"pid": 1, "ts": 1}), encoding="utf-8")
        lock._released = True
        takeover = lock.path.with_name(f"rebuild_{CHAT}.takeover")
        takeover.write_text("", encoding="utf-8")
        try:
            assert drj.acquire_chat_lock(tmp_path, CHAT, ttl_seconds=1) is None
        finally:
            takeover.unlink(missing_ok=True)
        assert drj.acquire_chat_lock(tmp_path, CHAT, ttl_seconds=1) is not None


# ═══ Снапшот + rollback ═════════════════════════════════════════════════════

class TestSnapshotRollback:
    @pytest.mark.asyncio
    async def test_snapshot_and_restore_roundtrip(self, tmp_path):
        db = await _db(tmp_path)
        try:
            fid = await db.insert_graph_fact(
                CHAT, "факт Ани", "chat_history", None, target_user=TARGET,
                status="confirmed", kind="fact")
            other = await db.insert_graph_fact(
                CHAT, "факт Бори", "chat_history", None, target_user="Боря",
                status="confirmed", kind="fact")
            path = tmp_path / "rollback.jsonl"
            count = await drj.create_user_snapshot(db, CHAT, TARGET, path)
            assert count == 1
            # изменили производные юзера
            from services.memory_rebuild import delete_generated_facts

            deleted = await delete_generated_facts(db, [fid])
            assert deleted == 1
            new_id = await db.insert_graph_fact(
                CHAT, "новый портрет", "chat_history", None, target_user=TARGET,
                status="dossier_portrait", kind="fact")
            restored = await drj.restore_user_snapshot(db, path)
            assert restored == 1
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE id = ?", (fid,)) == 1
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE id = ?", (new_id,)) == 1
            # чужой факт не тронут
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE id = ?", (other,)) == 1
            # FTS восстановлен
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts_fts "
                                     "WHERE rowid = ?", (fid,)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_restore_missing_snapshot_raises(self, tmp_path):
        db = await _db(tmp_path)
        try:
            with pytest.raises(FileNotFoundError):
                await drj.restore_user_snapshot(
                    db, tmp_path / "nope.jsonl")
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_restore_ignores_unknown_columns(self, tmp_path):
        """S10.22-9 (defense-in-depth): имена колонок для INSERT берутся из
        схемы `graph_facts`, а не из JSONL — посторонний ключ игнорируется."""
        db = await _db(tmp_path)
        try:
            fid = await db.insert_graph_fact(
                CHAT, "факт", "chat_history", None, target_user=TARGET,
                status="confirmed", kind="fact")
            row = dict(await (await db.db.execute(
                "SELECT * FROM graph_facts WHERE id = ?", (fid,))
            ).fetchone())
            row["evil\"; DROP TABLE graph_facts; --"] = "x"
            row["fact"] = "восстановленный"
            path = tmp_path / "snap.jsonl"
            path.write_text(json.dumps(row, default=str) + "\n",
                            encoding="utf-8")
            restored = await drj.restore_user_snapshot(db, path)
            assert restored == 1
            cursor = await db.db.execute(
                "SELECT fact FROM graph_facts WHERE id = ?", (fid,))
            value = (await cursor.fetchone())[0]
            assert value == "восстановленный"
        finally:
            await db.close()


# ═══ Раннер: done / cancel→rollback / fail-closed снапшот ═══════════════════

class _RecordingWorker:
    """Мок движка: пишет новый производный факт и (опц.) запрашивает отмену."""

    def __init__(self, db, store, job_id, *, cancel_after_write=False,
                 cancel_on_return=False):
        self.db = db
        self.store = store
        self.job_id = job_id
        self.cancel_after_write = cancel_after_write
        self.cancel_on_return = cancel_on_return
        self.progress_calls = []

    async def rebuild_dossier_for_user(self, chat_id, *, target_user,
                                       window_hours=4320, limit=None,
                                       chunk_size=40, progress_cb=None,
                                       cancel_cb=None) -> int:
        await self.db.insert_graph_fact(
            chat_id, "пересобранный портрет", "chat_history", None,
            target_user=target_user, status="dossier_portrait", kind="fact")

        async def _report(processed, total, stage):
            result = progress_cb(processed, total, stage)
            if asyncio.iscoroutine(result):
                await result

        if progress_cb is not None:
            await _report(1, 2, "extract")
            self.progress_calls.append("extract")
        if self.cancel_after_write:
            await self.store.update(self.job_id, cancel_requested=True)
        if cancel_cb is not None and cancel_cb():
            raise asyncio.CancelledError()
        if progress_cb is not None:
            await _report(2, 2, "write")
        if self.cancel_on_return:
            # Гонка: отмена пришла ровно перед финальной записью (после return
            # воркера раннер должен уйти в rollback, а не в 'done').
            await self.store.update(self.job_id, cancel_requested=True)
        return 1


class _ZeroWorker:
    """Мок движка: ничего не пишет — пустая пересборка (S10.22-2)."""

    async def rebuild_dossier_for_user(self, chat_id, *, target_user,
                                       window_hours=4320, limit=None,
                                       chunk_size=40, progress_cb=None,
                                       cancel_cb=None) -> int:
        return 0


async def _runner_setup(tmp_path):
    db = await _db(tmp_path)
    await db.insert_graph_fact(
        CHAT, "старый confirmed", "chat_history", None, target_user=TARGET,
        status="confirmed", kind="fact")
    await db.insert_graph_fact(
        CHAT, "старый портрет", "chat_history", None, target_user=TARGET,
        status="dossier_portrait", kind="fact")
    await db.insert_graph_fact(
        CHAT, "старый мем", "chat_history", None, target_user=TARGET,
        status="chat_meme", kind="fact")
    await db.insert_graph_fact(
        CHAT, "убеждение", "derived_belief", None, target_user=TARGET,
        status="confirmed", kind="belief")
    await db.set_dossier_override(CHAT, USER_ID, "ручная правка", 1)
    n1 = await db.upsert_node(CHAT, TARGET, "user")
    n2 = await db.upsert_node(CHAT, "тема", "topic")
    await db.upsert_edge(n1, n2, "about", fact_id=None)
    await _add_msg(db, CHAT, TARGET, "сырое сообщение")
    return db


class TestRunner:
    @pytest.mark.asyncio
    async def test_done_keeps_new_data(self, tmp_path):
        db = await _runner_setup(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j1", chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET, period="180",
                               window_hours=4320, chunk_size=40, total=2)
            worker = _RecordingWorker(db, store, "j1")
            await drj.run_dossier_rebuild(
                store=store, db=db, worker=worker, job_id="j1", chat_id=CHAT,
                user_id=USER_ID, target_name=TARGET, window_hours=4320,
                chunk_size=40, jobs_dir=tmp_path,
                archive_dir=tmp_path / "archive")
            job = await store.get("j1")
            assert job["status"] == "done"
            assert job["rebuilt"] == 1
            assert job["cleaned"] == 1
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE status='dossier_portrait'") == 2
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE status='confirmed' "
                                     "AND kind='fact'") == 0
            # вечные инварианты
            assert await db.get_dossier_override(CHAT, USER_ID) == "ручная правка"
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE kind='belief'") == 1
            assert await _count(db, "SELECT COUNT(*) FROM nodes") == 2
            assert await db.count_smart_messages(CHAT) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cleanup_without_rebuild_is_failed_not_done(self, tmp_path):
        """S10.22-2: cleaned>0 & rebuilt==0 → `failed`/`rebuild_empty`, а не
        молчаливый `done`; снапшот цел → доступен ручной откат (UI-критерий)."""
        db = await _runner_setup(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j7", chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET, period="180",
                               window_hours=4320, chunk_size=40, total=2)
            await drj.run_dossier_rebuild(
                store=store, db=db, worker=_ZeroWorker(), job_id="j7",
                chat_id=CHAT, user_id=USER_ID, target_name=TARGET,
                window_hours=4320, chunk_size=40, jobs_dir=tmp_path,
                archive_dir=tmp_path / "archive")
            job = await store.get("j7")
            assert job["status"] == "failed"
            assert job["error_code"] == "rebuild_empty"
            assert job["cleaned"] == 1 and job["rebuilt"] == 0
            # ручной откат достижим (критерий очищено>0 + снапшот на месте)
            assert cl_mod._rebuild_rollback_retryable(job) is True
            # confirmed-факт участника действительно удалён (cleanup сработал)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE status='confirmed' "
                                     "AND kind='fact'") == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cancel_rolls_back_user_derived(self, tmp_path):
        db = await _runner_setup(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j2", chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET, period="180",
                               window_hours=4320, chunk_size=40, total=2)
            worker = _RecordingWorker(db, store, "j2",
                                      cancel_after_write=True)
            await drj.run_dossier_rebuild(
                store=store, db=db, worker=worker, job_id="j2", chat_id=CHAT,
                user_id=USER_ID, target_name=TARGET, window_hours=4320,
                chunk_size=40, jobs_dir=tmp_path,
                archive_dir=tmp_path / "archive")
            job = await store.get("j2")
            assert job["status"] == "cancelled"
            assert job["rollback"]["done"] is True
            assert job["rollback"]["restored_facts"] == 3
            # старые производные восстановлены, новый портрет удалён
            facts = await (await db.db.execute(
                "SELECT fact, status FROM graph_facts WHERE chat_id = ? "
                "AND target_user = ?", (CHAT, TARGET))).fetchall()
            texts = {r["fact"] for r in facts}
            assert "старый confirmed" in texts
            assert "старый портрет" in texts
            assert "старый мем" in texts
            assert "пересобранный портрет" not in texts
            # инварианты не тронуты
            assert await db.get_dossier_override(CHAT, USER_ID) == "ручная правка"
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE kind='belief'") == 1
            assert await _count(db, "SELECT COUNT(*) FROM nodes") == 2
            assert await _count(db, "SELECT COUNT(*) FROM edges") == 1
            assert await db.count_smart_messages(CHAT) == 1
            assert await _count(
                db, "SELECT COUNT(*) FROM smart_messages_fts") == 1
            # аудит-архив отменённых производных записан
            assert (tmp_path / "cancelled_j2.jsonl").exists()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cancel_race_before_finalize_rolls_back(self, tmp_path):
        """Ревью (Medium-4): cancel пришёл во время финальной записи → не
        'done', а 'cancelled' + rollback из снапшота."""
        db = await _runner_setup(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j5", chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET, period="180",
                               window_hours=4320, chunk_size=40, total=2)
            worker = _RecordingWorker(db, store, "j5", cancel_on_return=True)
            await drj.run_dossier_rebuild(
                store=store, db=db, worker=worker, job_id="j5", chat_id=CHAT,
                user_id=USER_ID, target_name=TARGET, window_hours=4320,
                chunk_size=40, jobs_dir=tmp_path,
                archive_dir=tmp_path / "archive")
            job = await store.get("j5")
            assert job["status"] == "cancelled"
            assert job["rollback"]["done"] is True
            facts = await (await db.db.execute(
                "SELECT fact FROM graph_facts WHERE chat_id = ? "
                "AND target_user = ?", (CHAT, TARGET))).fetchall()
            texts = {r["fact"] for r in facts}
            assert "пересобранный портрет" not in texts
            assert "старый confirmed" in texts
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_snapshot_failure_is_fail_closed(self, tmp_path, monkeypatch):
        db = await _runner_setup(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j3", chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET, period="180",
                               window_hours=4320, chunk_size=40, total=2)

            async def _boom(*args, **kwargs):
                raise OSError("disk full")

            monkeypatch.setattr(drj, "create_user_snapshot", _boom)
            worker = _RecordingWorker(db, store, "j3")
            await drj.run_dossier_rebuild(
                store=store, db=db, worker=worker, job_id="j3", chat_id=CHAT,
                user_id=USER_ID, target_name=TARGET, window_hours=4320,
                chunk_size=40, jobs_dir=tmp_path,
                archive_dir=tmp_path / "archive")
            job = await store.get("j3")
            assert job["status"] == "failed"
            assert job["error_code"] == "snapshot_failed"
            # НИЧЕГО не удалено до снапшота
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts "
                                     "WHERE status='confirmed' "
                                     "AND kind='fact'") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_interrupted_manual_rollback(self, tmp_path):
        db = await _runner_setup(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j4", chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET, period="180",
                               window_hours=4320, chunk_size=40, total=2)
            snap = tmp_path / "rollback_j4.jsonl"
            await drj.create_user_snapshot(db, CHAT, TARGET, snap)
            # имитируем «процесс умер»: running + новый производный факт
            await store.update("j4", status="running")
            await db.insert_graph_fact(
                CHAT, "недострой", "chat_history", None, target_user=TARGET,
                status="dossier_portrait", kind="fact")
            await store.reconcile_interrupted()
            assert (await store.get("j4"))["status"] == "interrupted"
            await drj.perform_rollback(
                store, db, "j4", jobs_dir=tmp_path, chat_id=CHAT,
                target_name=TARGET)
            job = await store.get("j4")
            assert job["status"] == "cancelled"
            texts = {r[0] for r in await (await db.db.execute(
                "SELECT fact FROM graph_facts WHERE target_user = ?",
                (TARGET,))).fetchall()}
            assert "недострой" not in texts
            assert "старый confirmed" in texts
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_failed_rollback_failed_retry_restores(self, tmp_path):
        """Ревью (Medium-2): `failed` + `rollback_failed` — не тупик:
        повторный rollback восстанавливает производные из снапшота."""
        db = await _runner_setup(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j6", chat_id=CHAT, user_id=USER_ID,
                               target_name=TARGET, period="180",
                               window_hours=4320, chunk_size=40, total=2)
            # раннер успел сделать стартовый снапшот…
            await drj.create_user_snapshot(
                db, CHAT, TARGET, tmp_path / "rollback_j6.jsonl")
            # …записать частичный производный факт и упасть на откате
            await db.insert_graph_fact(
                CHAT, "частичный портрет", "chat_history", None,
                target_user=TARGET, status="dossier_portrait", kind="fact")
            await store.update(
                "j6", status="failed", error_code="rollback_failed",
                cleaned=1, rebuilt=1,
                rollback={"done": False, "restored_facts": 0,
                          "reason": "rollback_failed"},
                finished_at=int(time.time()))
            assert cl_mod._rebuild_rollback_retryable(
                await store.get("j6")) is True
            job = await drj.perform_rollback(
                store, db, "j6", jobs_dir=tmp_path, chat_id=CHAT,
                target_name=TARGET)
            assert job["status"] == "cancelled"
            assert job["rollback"]["done"] is True
            texts = {r[0] for r in await (await db.db.execute(
                "SELECT fact FROM graph_facts WHERE target_user = ?",
                (TARGET,))).fetchall()}
            assert "частичный портрет" not in texts
            assert "старый confirmed" in texts
            # инварианты не тронуты
            assert await db.get_dossier_override(CHAT, USER_ID) == "ручная правка"
            assert await db.count_smart_messages(CHAT) == 1
        finally:
            await db.close()


class TestRollbackRetryDecision:
    """Ревью (Medium-2): матрица «можно ли повторить откат» (зеркало UI)."""

    def _job(self, **over):
        base = {"status": "failed", "snapshot_ref": "rollback_x.jsonl",
                "rollback": {"done": False}, "cleaned": 0, "rebuilt": 0,
                "error_code": None}
        base.update(over)
        return base

    def test_retryable_cases(self):
        assert cl_mod._rebuild_rollback_retryable(
            self._job(error_code="rollback_failed")) is True
        assert cl_mod._rebuild_rollback_retryable(
            self._job(error_code="rebuild_failed", cleaned=2)) is True
        assert cl_mod._rebuild_rollback_retryable(
            self._job(error_code="rebuild_failed", rebuilt=1)) is True

    def test_not_retryable_cases(self):
        assert cl_mod._rebuild_rollback_retryable(
            self._job(error_code="rebuild_failed")) is False
        assert cl_mod._rebuild_rollback_retryable(
            self._job(error_code="snapshot_failed")) is False
        assert cl_mod._rebuild_rollback_retryable(
            self._job(error_code="rollback_failed",
                      rollback={"done": True})) is False
        assert cl_mod._rebuild_rollback_retryable(
            self._job(error_code="rollback_failed", snapshot_ref="")) is False
        assert cl_mod._rebuild_rollback_retryable(
            self._job(status="interrupted",
                      error_code="rollback_failed")) is False
        assert cl_mod._rebuild_rollback_retryable(
            self._job(status="cancelled")) is False
        assert cl_mod._rebuild_rollback_retryable(None) is False


# ═══ Движок rebuild_dossier_for_user ════════════════════════════════════════

class _SeqLLM:
    """LLM-мок: последовательность ответов (A, A, …, B)."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = 0

    async def generate(self, messages, temperature=None):
        return self.sequence[min(self.calls, len(self.sequence) - 1)]

    async def generate_worker(self, role, messages, *, temperature=None):
        value = self.sequence[min(self.calls, len(self.sequence) - 1)]
        self.calls += 1
        return value


def _layer_a(target, text, kind="person_fact"):
    return json.dumps({"candidates": [{"target": target, "kind": kind,
                                       "text": text, "evidence": [1],
                                       "confidence": 0.8}]})


def _layer_b(target, portrait, meme):
    return json.dumps({
        "portraits": [{"target": target, "portrait": portrait,
                       "patterns": [], "themes": []}],
        "memes": [{"target": target, "text": meme, "classified_by": "llm"}],
    })


class TestEngineChunked:
    def _worker(self, db, llm, monkeypatch):
        monkeypatch.setattr(Settings, "MULTILAYER_EXTRACTION_ENABLED", True)
        return LoreWorker(store=None, db=db, llm=llm, bot_id=1)

    @pytest.mark.asyncio
    async def test_chunks_progress_and_target_scoped(self, tmp_path,
                                                     monkeypatch):
        db = await _db(tmp_path)
        try:
            for index in range(5):
                await _add_msg(db, CHAT, TARGET,
                               f"длинное сообщение номер {index} тест")
            await _add_msg(db, CHAT, "Боря", "чужое длинное сообщение тут")
            llm = _SeqLLM([
                _layer_a(TARGET, "любит кофе"),
                _layer_a(TARGET, "бегает"),
                _layer_b(TARGET, "портрет Ани", "мем Ани"),
            ])
            worker = self._worker(db, llm, monkeypatch)
            progress = []
            written = await worker.rebuild_dossier_for_user(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=3,
                progress_cb=lambda p, t, s: progress.append((p, t, s)))
            assert written >= 1
            assert any(p > 0 and s == "extract" for p, _t, s in progress)
            assert progress[-1][2] == "write"
            # портрет/мем — только для target, чужих нет
            rows = await (await db.db.execute(
                "SELECT target_user, status, fact FROM graph_facts "
                "WHERE status IN ('dossier_portrait','chat_meme')")).fetchall()
            targets = {r["target_user"] for r in rows}
            assert targets == {TARGET}
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cancel_cb_aborts(self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        try:
            for index in range(4):
                await _add_msg(db, CHAT, TARGET,
                               f"длинное сообщение для отмены {index}")
            llm = _SeqLLM([_layer_a(TARGET, "факт"),
                           _layer_b(TARGET, "портрет", "мем")])
            worker = self._worker(db, llm, monkeypatch)
            with pytest.raises(asyncio.CancelledError):
                await worker.rebuild_dossier_for_user(
                    CHAT, target_user=TARGET, window_hours=0, chunk_size=1,
                    cancel_cb=lambda: True)
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts "
                    "WHERE status='dossier_portrait'") == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_window_messages(self, tmp_path, monkeypatch):
        db = await _db(tmp_path)
        try:
            for index in range(3):
                await _add_msg(db, CHAT, TARGET,
                               f"длинное сообщение номер {index} ок")
            await _add_msg(db, CHAT, TARGET, "/command")
            worker = self._worker(db, _SeqLLM([_layer_b(TARGET, "p", "m")]),
                                  monkeypatch)
            assert await worker.count_window_messages(
                CHAT, window_hours=0) == 3
        finally:
            await db.close()


# ═══ API ════════════════════════════════════════════════════════════════════

class _DummyTask:
    def done(self):
        return True


class _FakeConn:
    def __init__(self, role_rows=(), admin_rows=()):
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        outer = self

        class _CM:
            async def __aenter__(self):
                return outer._conn

            async def __aexit__(self, *exc):
                return False

        return _CM()

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings=True):
        pass

    async def close(self):
        pass


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    {"role_name": "user", "permissions": {}, "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-09-06T10:00:00+00:00"},
]

_TS = "2026-09-06T10:00:00+00:00"


class _FakeChatStore:
    def __init__(self):
        self.profiles = {CHAT: LoreProfile(
            chat_id=CHAT, manual_lore="", auto_lore="", auto_enabled=True,
            auto_period_hours=24, auto_window_hours=24, is_active=True,
            last_auto_at=None, updated_at=_TS)}

    async def resolve_chat_id(self, chat_id):
        return chat_id

    async def get_profile(self, chat_id):
        return self.profiles.get(chat_id)

    async def list_profiles(self):
        return list(self.profiles.values())

    async def is_chat_admin(self, telegram_id, chat_id):
        return False


class _FakeEngineWorker:
    def __init__(self, count=100):
        self.count = count

    async def count_window_messages(self, chat_id, *, window_hours=4320):
        return self.count

    async def rebuild_dossier_for_user(self, *args, **kwargs):
        return 0


class _FakeDb:
    db = None


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        deps_mod, "settings",
        types.SimpleNamespace(API_TOKEN=TEST_TOKEN, ADMIN_USER_ID=ADMIN_ID))
    drj.reset_job_store()
    # Изолированный job-store в tmp (settings — frozen dataclass, не патчим).
    drj._store = drj.DossierRebuildJobStore(base_dir=tmp_path)
    drj._store_reconciled = True

    conn = _FakeConn(_ROLE_ROWS, _ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    store = _FakeChatStore()
    worker = _FakeEngineWorker()
    lore_runtime.reset_lore_runtime()
    lore_runtime.set_lore_components(store=store, worker=worker,
                                     db=_FakeDb())
    app = create_app(cache)
    client = TestClient(app)

    captured: list = []
    monkeypatch.setattr(cl_mod, "_schedule_rebuild",
                        lambda coro: captured.append(coro) or _DummyTask())

    yield types.SimpleNamespace(client=client, store=store, worker=worker,
                                cache=cache, captured=captured)

    for coro in captured:
        coro.close()
    lore_runtime.reset_lore_runtime()
    drj.reset_job_store()


def _url(user_id=USER_ID, suffix="", job_id=None):
    base = f"/api/chat_lore/{CHAT}/dossier/{user_id}/rebuild"
    if job_id:
        base += f"/{job_id}"
    return base + suffix


class TestApi:
    def test_start_202_and_status_latest(self, api_env):
        resp = api_env.client.post(
            _url() + "?name=" + TARGET, headers=_h(ADMIN_ID),
            json={"period": "180"})
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["window_hours"] == 4320 and body["total"] == 3
        assert body["status"] == "queued"
        job_id = body["job_id"]

        status = api_env.client.get(_url(job_id=job_id), headers=_h(ADMIN_ID))
        assert status.status_code == 200
        assert status.json()["job_id"] == job_id

        latest = api_env.client.get(_url(suffix="/latest"),
                                    headers=_h(ADMIN_ID))
        assert latest.status_code == 200
        assert latest.json()["job_id"] == job_id

    def test_latest_204_when_no_jobs(self, api_env):
        resp = api_env.client.get(_url(suffix="/latest"),
                                  headers=_h(ADMIN_ID))
        assert resp.status_code == 204

    @pytest.mark.parametrize("period,window", [
        ("30", 720), ("90", 2160), ("180", 4320), ("all", 0)])
    def test_period_maps_to_window(self, api_env, period, window):
        resp = api_env.client.post(
            _url() + "?name=" + TARGET, headers=_h(ADMIN_ID),
            json={"period": period})
        assert resp.status_code == 202, resp.text
        assert resp.json()["window_hours"] == window

    def test_bad_period_422(self, api_env):
        resp = api_env.client.post(
            _url() + "?name=" + TARGET, headers=_h(ADMIN_ID),
            json={"period": "7"})
        assert resp.status_code == 422

    def test_second_start_409_already_running(self, api_env):
        first = api_env.client.post(_url() + "?name=" + TARGET,
                                    headers=_h(ADMIN_ID), json={})
        assert first.status_code == 202
        second = api_env.client.post(_url() + "?name=" + TARGET,
                                     headers=_h(ADMIN_ID), json={})
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert detail["code"] == "already_running"
        assert detail["job_id"] == first.json()["job_id"]

    def test_start_after_interrupted_allowed(self, api_env):
        """S10.22-5: после «рестарта» (`interrupted`) новый старт проходит."""
        first = api_env.client.post(_url() + "?name=" + TARGET,
                                    headers=_h(ADMIN_ID), json={})
        assert first.status_code == 202
        job_id = first.json()["job_id"]
        jobs = drj.get_job_store()
        jobs._ensure_loaded()
        jobs._jobs[job_id].update({"status": "interrupted",
                                   "error_code": "process_restart"})
        # fake-раннер не выполнился и не освободил lock первого старта.
        drj.release_chat_lock(CHAT, jobs.dir_path)
        second = api_env.client.post(_url() + "?name=" + TARGET,
                                     headers=_h(ADMIN_ID), json={})
        assert second.status_code == 202, second.text
        assert second.json()["job_id"] != job_id

    def test_cancel_active_202_schedules_rollback(self, api_env):
        start = api_env.client.post(_url() + "?name=" + TARGET,
                                    headers=_h(ADMIN_ID), json={})
        job_id = start.json()["job_id"]
        before = len(api_env.captured)
        resp = api_env.client.post(_url(job_id=job_id, suffix="/cancel"),
                                   headers=_h(ADMIN_ID))
        assert resp.status_code == 202
        assert resp.json()["status"] == "cancelling"
        # dummy-задача считается завершённой → ручной rollback запланирован
        assert len(api_env.captured) == before + 1
        status = api_env.client.get(_url(job_id=job_id), headers=_h(ADMIN_ID))
        assert status.json()["cancel_requested"] is True

    def test_cancel_twice_409_cancelling(self, api_env):
        start = api_env.client.post(_url() + "?name=" + TARGET,
                                    headers=_h(ADMIN_ID), json={})
        job_id = start.json()["job_id"]
        first = api_env.client.post(_url(job_id=job_id, suffix="/cancel"),
                                    headers=_h(ADMIN_ID))
        assert first.status_code == 202
        second = api_env.client.post(_url(job_id=job_id, suffix="/cancel"),
                                     headers=_h(ADMIN_ID))
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "cancelling"

    def test_rbac_403_for_plain_user(self, api_env):
        resp = api_env.client.post(_url() + "?name=" + TARGET,
                                   headers=_h(USER_TG), json={})
        assert resp.status_code == 403

    def test_flag_off_404(self, api_env, monkeypatch):
        monkeypatch.setattr(Settings, "DOSSIER_REBUILD_UI_ENABLED", False)
        assert api_env.client.post(_url() + "?name=" + TARGET,
                                   headers=_h(ADMIN_ID),
                                   json={}).status_code == 404
        assert api_env.client.get(_url(suffix="/latest"),
                                  headers=_h(ADMIN_ID)).status_code == 404

    def test_latest_fail_open_204_on_store_error(self, api_env, monkeypatch):
        async def _boom(*args, **kwargs):
            raise RuntimeError("store broken")

        monkeypatch.setattr(drj.DossierRebuildJobStore, "latest", _boom)
        resp = api_env.client.get(_url(suffix="/latest"), headers=_h(ADMIN_ID))
        assert resp.status_code == 204

    # ── Ревью (Medium-2): повторный откат после rollback_failed ─────────────
    def _seed_failed_job(self, api_env, *, error_code="rollback_failed",
                         cleaned=1, rebuilt=1):
        start = api_env.client.post(_url() + "?name=" + TARGET,
                                    headers=_h(ADMIN_ID), json={})
        assert start.status_code == 202
        job_id = start.json()["job_id"]
        store = drj.get_job_store()
        store._ensure_loaded()
        store._jobs[job_id].update({
            "status": "failed", "error_code": error_code,
            "cleaned": cleaned, "rebuilt": rebuilt,
            "rollback": {"done": False, "restored_facts": 0,
                         "reason": "rollback_failed"},
            "finished_at": int(time.time()),
        })
        return job_id

    def test_cancel_retries_rollback_after_failed(self, api_env):
        job_id = self._seed_failed_job(api_env)
        before = len(api_env.captured)
        resp = api_env.client.post(_url(job_id=job_id, suffix="/cancel"),
                                   headers=_h(ADMIN_ID))
        assert resp.status_code == 202
        assert resp.json()["status"] == "cancelling"
        # ручной rollback реально запланирован (был терминал — не планировался)
        assert len(api_env.captured) == before + 1
        status = api_env.client.get(_url(job_id=job_id), headers=_h(ADMIN_ID))
        assert status.json()["status"] == "cancelling"
        assert status.json()["cancel_requested"] is True

    def test_cancel_failed_without_rollback_reason_is_terminal(self, api_env):
        job_id = self._seed_failed_job(
            api_env, error_code="snapshot_failed", cleaned=0, rebuilt=0)
        before = len(api_env.captured)
        resp = api_env.client.post(_url(job_id=job_id, suffix="/cancel"),
                                   headers=_h(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert len(api_env.captured) == before       # откатывать нечего


class TestCliChatLock:
    """Ревью (High-1): CLI F1 участвует в том же кросс-процессном lock,
    что и UI-джоба (spec §2.7 / R6)."""

    def test_cli_lock_blocks_api_start(self, api_env, monkeypatch):
        # CLI-хелпер берёт файл-lock в том же каталоге, что API-джоба.
        jobs = drj._store.dir_path
        monkeypatch.setattr(drj, "jobs_dir", lambda base_dir=None: jobs)
        handles, busy = manage._acquire_memory_locks([CHAT])
        assert busy is None and len(handles) == 1
        try:
            resp = api_env.client.post(_url() + "?name=" + TARGET,
                                       headers=_h(ADMIN_ID), json={})
            assert resp.status_code == 409
            assert resp.json()["detail"] == {"code": "chat_locked"}
        finally:
            manage._release_memory_locks(handles)

    def test_api_lock_blocks_cli(self, tmp_path, monkeypatch):
        jobs = tmp_path / "dossier_jobs"
        monkeypatch.setattr(drj, "jobs_dir", lambda base_dir=None: jobs)
        held = drj.acquire_chat_lock(jobs, CHAT)
        assert held is not None
        try:
            handles, busy = manage._acquire_memory_locks([CHAT])
            assert handles == [] and busy == CHAT
        finally:
            held.release()
        handles, busy = manage._acquire_memory_locks([CHAT])
        assert busy is None and len(handles) == 1
        manage._release_memory_locks(handles)
        again = drj.acquire_chat_lock(jobs, CHAT)
        assert again is not None
        again.release()

    def test_jobs_dir_helper_matches_store(self, tmp_path):
        assert drj.jobs_dir(tmp_path) == tmp_path / "dossier_jobs"
        store = drj.DossierRebuildJobStore(base_dir=tmp_path)
        assert store.dir_path == drj.jobs_dir(tmp_path)
