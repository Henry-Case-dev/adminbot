#!/usr/bin/env python3
"""VOICE-TRANSCRIPTION-RECOVERY-01 — production replay сохранённых сообщений.

Запускается в одноразовом checkout фикса с production `.env`, production
SQLite (`initialize_existing`, БЕЗ DDL) и штатной aiogram-сессией бота
(`build_local_api_session`, тот же конструктор, что в рантайме). Replay идёт
через существующие сервисы (`handlers.voice_transcription.replay_saved_media`
→ единый транспорт `services.media_download` → `VoiceTranscriber` →
`smart_messages`/FTS + существующая инъекция памяти).

Гарантии:
  * в Telegram НЕ отправляется ни одного сообщения (send/forward/copy
    запрещены на экземпляре бота — вызов уронил бы прогон, а не «ушёл»);
  * `file_id` не печатается (только префикс), токен/DSN/пути токена — нет;
  * второй прогон доказывает идемпотентность: нет новых строк, новых
    фактов памяти и новых source-ref'ов.

Выход: один JSON-объект в stdout (R17-safe), диагностические логи — stderr.
"""
import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

DB_PATH = os.environ.get("REPLAY_DB_PATH", "/var/www/admin_bot/local_database.db")
APP_ROOT = os.environ.get("REPLAY_APP_ROOT", "/var/www/admin_bot")

TARGETS = [
    {"label": "voice_personal_235", "chat_id": 5885953495, "message_id": 235,
     "kind": "voice", "expected_size": 128770, "expected_dir": "voice",
     "journal": ("2026-11-18 04:03:00", "2026-11-18 04:16:00")},
    {"label": "voice_channel_1222542", "chat_id": -1002661910336,
     "message_id": 1222542, "kind": "voice", "expected_size": 151886,
     "expected_dir": "voice",
     "journal": ("2026-11-18 02:15:00", "2026-11-18 02:32:00")},
    {"label": "video_note_channel_1221599", "chat_id": -1002661910336,
     "message_id": 1221599, "kind": "video_note", "expected_size": 3283115,
     "expected_dir": "video_notes",
     "journal": ("2026-11-17 11:20:00", "2026-11-17 11:35:00")},
]

CONFIG_KEYS = (
    "flags.download_enabled", "flags.enable_voice_transcription",
    "flags.graph_rag_enabled", "limits.voice_transcript_stale_seconds",
    "models.groq_max_concurrency", "limits.video_stt_timeout_seconds",
)


def _sha8(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:8]


def _utf8_stderr():
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class _MemorySpy:
    """Прозрачный регистратор: реальный MemoryManager + учёт вызовов."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.done = 0
        self.failed = 0
        self.last_error = ""

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def memorize_facts(self, *args, **kwargs):
        self.calls += 1
        coro = self.inner.memorize_facts(*args, **kwargs)

        async def _wrapped():
            try:
                await coro
            except Exception as exc:            # noqa: BLE001 - учёт, не глотание
                self.failed += 1
                self.last_error = type(exc).__name__
                raise
            self.done += 1

        return _wrapped()


def _journal_ids(since_utc: str, until_utc: str) -> list:
    def _epoch(value: str) -> str:
        return subprocess.check_output(
            ["date", "-u", "-d", value, "+%s"], text=True).strip()

    cmd = ["journalctl", "-u", "admin_bot", "-o", "cat", "--no-pager",
           "--since=@" + _epoch(since_utc), "--until=@" + _epoch(until_utc)]
    env = dict(os.environ, PAGER="cat", SYSTEMD_PAGER="cat")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                          env=env)
    ids, seen = [], set()
    for raw in (proc.stdout or "").splitlines():
        marker = "file_id="
        pos = raw.find(marker)
        if pos < 0:
            continue
        value = raw[pos + len(marker):].split()[0].strip()
        if len(value) < 40 or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids


def _snapshot(path: str) -> dict:
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    try:
        out = {"smart_messages": con.execute(
            "SELECT COUNT(*) FROM smart_messages").fetchone()[0]}
        for status in ("ready", "pending", "failed", "unavailable"):
            out["transcript_" + status] = con.execute(
                "SELECT COUNT(*) FROM smart_messages WHERE transcript_status=?",
                (status,)).fetchone()[0]
        out["message_revisions"] = con.execute(
            "SELECT COUNT(*) FROM message_revisions").fetchone()[0]
        out["mca_source_refs"] = con.execute(
            "SELECT COUNT(*) FROM mca_source_refs").fetchone()[0]
        out["mca_media_analyses"] = con.execute(
            "SELECT COUNT(*) FROM mca_media_analyses").fetchone()[0]
        out["rows"] = {}
        for target in TARGETS:
            row = con.execute(
                "SELECT transcript_status, transcript_revision, "
                "transcript_reason, media_type, media_ref, "
                "LENGTH(COALESCE(text,'')) FROM smart_messages "
                "WHERE chat_id=? AND tg_message_id=?",
                (target["chat_id"], target["message_id"])).fetchone()
            out["rows"][target["label"]] = (
                None if row is None else {
                    "status": row[0], "revision": row[1], "reason": row[2],
                    "media_type": row[3], "media_ref_prefix": str(row[4] or "")[:18],
                    "text_chars": row[5]})
        return out
    finally:
        con.close()


def _memory_proof(path: str, since_ts: int) -> dict:
    """Read-only: события инъекции памяти (FACTS_EXTRACT) по нашим чатам."""
    import sqlite3
    chats = sorted({int(t["chat_id"]) for t in TARGETS})
    marks = ",".join("?" for _ in chats)
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    try:
        rows = con.execute(
            "SELECT chat_id, outcome, COUNT(*) FROM mca_events "
            "WHERE event_name='FACTS_EXTRACT' AND ts >= ? "
            "AND chat_id IN (%s) GROUP BY chat_id, outcome" % marks,
            (int(since_ts), *chats)).fetchall()
        return {"since_utc": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(since_ts))),
                "events": [
                    {"chat_id": r[0], "outcome": r[1], "count": r[2]}
                    for r in rows]}
    finally:
        con.close()


async def _drain(timeout: float = 45.0) -> dict:
    """Дождаться fire-and-forget задач (инъекция памяти) и вернуть их итог."""
    deadline = time.monotonic() + timeout
    while True:
        pending = [t for t in asyncio.all_tasks()
                   if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return {"left": 0}
        if time.monotonic() >= deadline:
            names = []
            for task in pending[:5]:
                try:
                    coro = task.get_coro()
                    names.append(getattr(coro, "__qualname__",
                                         type(coro).__name__))
                except Exception:
                    names.append(type(task).__name__)
            return {"left": len(pending), "left_names": names}
        await asyncio.wait(pending, timeout=2.0)


async def _pg_snapshot() -> tuple:
    """Read-only снимок bot_settings: effective config без DDL/seed."""
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        return {}, "no_dsn"
    try:
        import asyncpg
        from services.param_catalog import normalize_value
    except Exception as exc:                        # pragma: no cover
        return {}, "import:%s" % type(exc).__name__
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=10)
    except Exception as exc:
        return {}, "connect:%s" % type(exc).__name__
    try:
        rows = await asyncio.wait_for(
            conn.fetch("SELECT key, value FROM bot_settings"), timeout=15)
        values = {r["key"]: normalize_value(r["key"], r["value"]) for r in rows}
        return values, "pg:%d" % len(values)
    except Exception as exc:
        return {}, "query:%s" % type(exc).__name__
    finally:
        try:
            await conn.close()
        except Exception:
            pass


class _SnapshotCache:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


async def _local_path_probe(bot, file_path, attempts: int = 3):
    """Маппинг container→host + факт материализации файла (с ожиданием)."""
    from services.media_download import local_file_path
    src = local_file_path(bot, file_path)
    if src is None:
        return {"mapped": False}
    last = "OSError"
    for attempt in range(1, max(1, attempts) + 1):
        try:
            stat = src.stat()
            return {"mapped": True, "exists": True, "size": stat.st_size,
                    "attempt": attempt}
        except OSError as exc:
            last = type(exc).__name__
            if attempt < attempts:
                await asyncio.sleep(1.0)
    return {"mapped": True, "exists": False, "error": last}


async def _replay_object(bot, db, service, memory, target, file_id):
    import handlers.voice_transcription as vt
    report = await vt.replay_saved_media(
        bot, chat_id=target["chat_id"], message_id=target["message_id"],
        file_id=file_id, media_type=target["kind"],
        service=service, db=db, memory=memory)
    out = {k: report.get(k) for k in (
        "status", "reason", "stage", "revision", "chars", "asr", "persisted",
        "file_id_prefix")}
    row = await db.get_smart_message_by_tg_id(
        target["chat_id"], target["message_id"])
    row = dict(row or {})
    out["row"] = {
        "status": row.get("transcript_status"),
        "revision": row.get("transcript_revision"),
        "reason": row.get("transcript_reason"),
        "text_chars": len(str(row.get("text") or "")),
        "text_sha8": _sha8(str(row.get("text") or "")),
    }
    return out


def _writer_message(chat_id, reply_to, *, voice=False, video_note=False):
    reply = types.SimpleNamespace(
        message_id=reply_to, voice=types.SimpleNamespace(file_id="x") if voice else None,
        video_note=types.SimpleNamespace(file_id="x") if video_note else None,
        from_user=types.SimpleNamespace(id=0, is_bot=False))
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id), message_id=2_000_000,
        text="что в голосовых?", caption=None, quote=None,
        reply_to_message=reply,
        from_user=types.SimpleNamespace(id=0, is_bot=False))


async def _writer_probe(db, chat_id, reply_to, *, voice=False,
                        video_note=False) -> dict:
    from services import voice_transcripts as vts
    message = _writer_message(chat_id, reply_to, voice=voice,
                              video_note=video_note)
    bundle = await vts.resolve_voice_bundle(
        db, chat_id=chat_id, message=message, query="что в голосовых?")
    if bundle is None:
        return {"bundle": None}
    block = vts.render_voice_block(bundle)
    return {
        "bundle": bundle.kind,
        "summary_status": bundle.summary_status(),
        "refs": list(bundle.refs),
        "items": [{"ref": item.source_ref, "status": item.status,
                   "chars": len(item.text or "")} for item in bundle.items],
        "block_chars": len(block),
        "block_sha8": _sha8(block),
        "texts_in_block": {
            "tg:%s" % reply_to: bool(
                next((it.text for it in bundle.items
                      if it.source_ref == "tg:%s" % reply_to), "")
                and next((it.text for it in bundle.items
                          if it.source_ref == "tg:%s" % reply_to)) in block),
        },
    }


async def main() -> int:
    _utf8_stderr()
    logging.basicConfig(level=logging.CRITICAL, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")
    for name in ("handlers.voice_transcription", "services.media_download",
                 "services.local_bot_api", "services.voice_transcripts"):
        logging.getLogger(name).setLevel(logging.INFO)

    from aiogram import Bot
    from config.settings import settings
    from services import hot_config as hot
    from services import local_bot_api
    from services import media_download as md
    from services.database import DatabaseService
    from services.llm_client import LLMClient
    from services.summary_aliases import AliasResolver, LiveAliasView
    from services.summary_memory import MemoryManager
    from SmartModule.service import VoiceTranscriber

    result = {"ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "config": {}, "objects": [], "counters": {},
              "writer": {}, "guards": {}, "errors": []}

    # ── effective config: read-only snapshot bot_settings ────────────────
    values, source = await _pg_snapshot()
    result["config"]["config_source"] = source
    if values:
        hot.set_config_cache(_SnapshotCache(values))
    result["config"]["effective"] = {
        key: hot.get(key, getattr(settings, key.upper().split(".")[-1], None))
        for key in CONFIG_KEYS}

    # ── DB: существующая production-база, без DDL/миграций ───────────────
    db = DatabaseService(DB_PATH)
    await db.initialize_existing()
    cursor = await db.db.execute("PRAGMA user_version")
    version_row = await cursor.fetchone()
    result["config"]["db"] = {
        "path_tail": Path(DB_PATH).name,
        "user_version": (version_row[0] if version_row is not None else None)}

    # ── штатная сессия бота (тот же конструктор, что в bot.py) ───────────
    session = local_bot_api.build_local_api_session()
    bot = Bot(token=settings.API_TOKEN, session=session)
    try:
        result["config"]["bot_api_mode"] = local_bot_api.bot_api_mode(bot)
        result["config"]["files_dir_readable"] = (
            local_bot_api.local_files_dir_readable())
        result["config"]["cloud_fallback"] = md.cloud_fallback_enabled()
        result["config"]["files_dir"] = str(
            local_bot_api.host_files_root())

        blocked = {"attempts": 0, "methods": []}

        def _forbid(name):
            async def _blocked(*args, **kwargs):
                blocked["attempts"] += 1
                blocked["methods"].append(name)
                raise RuntimeError("telegram send blocked: %s" % name)
            return _blocked

        for method in ("send_message", "send_audio", "send_voice",
                       "send_video_note", "send_document", "send_photo",
                       "forward_message", "copy_message"):
            setattr(bot, method, _forbid(method))

        # ── ASR + память (реальные сервисы) ─────────────────────────────
        service = VoiceTranscriber(max_concurrency=hot.get(
            "models.groq_max_concurrency", settings.GROQ_MAX_CONCURRENCY))
        aliases = LiveAliasView(AliasResolver(
            hot.get("limits.summary_aliases", settings.SUMMARY_ALIASES)))
        llm = LLMClient(
            hot.get("models.llm_base_url", settings.LLM_BASE_URL),
            hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
            hot.get("models.embedding_model_name",
                    settings.EMBEDDING_MODEL_NAME),
            embed_base_url=hot.get("models.embedding_base_url",
                                   settings.EMBEDDING_BASE_URL),
            embed_api_key=hot.get("keys.embedding_api_key",
                                  settings.EMBEDDING_API_KEY))
        inner_memory = MemoryManager(db, llm, aliases=aliases)
        memory_ok = False
        try:
            memory_ok = bool(await inner_memory.initialize())
        except Exception as exc:                     # noqa: BLE001
            result["errors"].append("memory_init:%s" % type(exc).__name__)
        spy = _MemorySpy(inner_memory) if memory_ok else None
        if spy is None:
            result["config"]["memory"] = "unavailable"
        else:
            result["config"]["memory"] = "ready" if memory_ok else "fts_only"

        # ── адресация файлов: journal → локальный getFile (идентичность) ─
        resolved = []
        for target in TARGETS:
            entry = {"label": target["label"], "candidates": 0,
                     "identity": {}}
            try:
                ids = _journal_ids(*target["journal"])
            except Exception as exc:                 # noqa: BLE001
                entry["error"] = "journal:%s" % type(exc).__name__
                ids = []
            entry["candidates"] = len(ids)
            best, best_score = None, 0
            for fid in ids:
                try:
                    tg_file = await bot.get_file(fid)
                except Exception as exc:             # noqa: BLE001
                    continue
                size = int(getattr(tg_file, "file_size", 0) or 0)
                path = str(getattr(tg_file, "file_path", "") or "")
                directory = path.split("/")[0] if path else ""
                unique = str(getattr(tg_file, "file_unique_id", "") or "")
                score = 0
                if size == target["expected_size"]:
                    score += 4
                if directory == target["expected_dir"]:
                    score += 2
                row = dict(await db.get_smart_message_by_tg_id(
                    target["chat_id"], target["message_id"]) or {})
                ref = str(row.get("media_ref") or "")
                if unique and ref and ref.split(":")[-1][:8] == unique[:8]:
                    score += 8
                if score > best_score:
                    best, best_score = (fid, tg_file, size, path, unique), score
            if best is None:
                entry["identity"] = {"resolved": False, "error": "no_match"}
                resolved.append((target, None, entry))
                continue
            fid, tg_file, size, path, unique = best
            entry["identity"] = {
                "resolved": True, "score": best_score,
                "file_id_prefix": fid[:6], "size": size,
                "size_matches_expected": size == target["expected_size"],
                "dir": path.split("/")[0] if path else "",
                "file_unique_prefix": unique[:8],
                "mapping": await _local_path_probe(bot, path),
            }
            resolved.append((target, fid, entry))

        result["objects"] = [entry for _t, _f, entry in resolved]

        # ── дымовой прогон БЕЗ записи в БД: local getFile → файл → ASR ────
        smoke = {"ok": False, "skipped": True}
        first = next(((t, f) for t, f, _e in resolved if f), (None, None))
        target0, fid0 = first
        if os.environ.get("REPLAY_SKIP_SMOKE") == "1":
            smoke = {"ok": True, "skipped": "env"}
        elif fid0:
            smoke_is_note = (target0 or {}).get("kind") == "video_note"
            fd, smoke_path = tempfile.mkstemp(
                prefix="vt_smoke_", suffix=".mp4" if smoke_is_note else ".ogg")
            os.close(fd)
            try:
                started = time.monotonic()
                diag: dict = {}
                await md.download_api_file_to_path(
                    bot, fid0, smoke_path, site="replay-smoke",
                    diagnostics=diag)
                fetched = os.path.getsize(smoke_path)
                stt_text = await service.transcribe_voice(
                    smoke_path, "mp4" if smoke_is_note else "ogg")
                smoke = {"ok": bool(str(stt_text or "").strip()),
                         "skipped": False, "bytes": fetched,
                         "chars": len(str(stt_text or "")),
                         "sha8": _sha8(stt_text),
                         "transport": {k: diag.get(k) for k in
                                       ("outcome", "stage", "error_class",
                                        "attempt")},
                         "ms": int((time.monotonic() - started) * 1000)}
            except Exception as exc:                 # noqa: BLE001
                smoke = {"ok": False, "skipped": False,
                         "error": type(exc).__name__,
                         "detail": str(exc)[:120]}
            finally:
                try:
                    os.unlink(smoke_path)
                except OSError:
                    pass
        result["smoke"] = smoke
        if not smoke.get("ok"):
            # Никаких записей в БД: воспроизведение не начинаем, если реальный
            # local-путь или ASR не работают (иначе «failed» был бы нашим
            # экспериментом, а не состоянием продукта).
            result["errors"].append("smoke_failed")
            result["ok"] = False
            print(json.dumps(result, ensure_ascii=False, indent=1))
            return 2

        # ── счётчики до/после и проходы replay (env REPLAY_PASSES) ───────
        try:
            passes_wanted = int(os.environ.get("REPLAY_PASSES", "2"))
        except ValueError:
            passes_wanted = 2
        passes_wanted = max(1, min(3, passes_wanted))
        only = {x.strip() for x in
                os.environ.get("REPLAY_LABELS", "").split(",") if x.strip()}
        counters = {"before": _snapshot(DB_PATH)}
        leftovers = []
        print("PROGRESS " + json.dumps(
            {"stage": "counters_before", "passes": passes_wanted,
             "labels": sorted(only)}, ensure_ascii=False), file=sys.stderr,
            flush=True)
        passes = []
        for pass_no in range(1, passes_wanted + 1):
            pass_reports = []
            for target, fid, entry in resolved:
                if fid is None or (only and target["label"] not in only):
                    pass_reports.append({"label": target["label"],
                                         "skipped": "filtered_or_no_file_id"})
                    continue
                started = time.monotonic()
                try:
                    report = await _replay_object(
                        bot, db, service, spy or inner_memory, target, fid)
                except Exception as exc:             # noqa: BLE001
                    report = {"status": "error",
                              "reason": type(exc).__name__}
                    result["errors"].append(
                        "replay:%s:%s" % (target["label"],
                                          type(exc).__name__))
                report["ms"] = int((time.monotonic() - started) * 1000)
                pass_reports.append(dict(report, label=target["label"]))
                print("PROGRESS " + json.dumps(
                    {"stage": "replay", "pass": pass_no,
                     "label": target["label"],
                     "status": report.get("status"),
                     "revision": report.get("revision"),
                     "chars": report.get("chars"),
                     "ms": report.get("ms")}, ensure_ascii=False),
                    file=sys.stderr, flush=True)
                drained = await _drain()
                if drained.get("left"):
                    leftovers.append(dict(drained, label=target["label"],
                                          pass_no=pass_no))
            counters["after_pass%d" % pass_no] = _snapshot(DB_PATH)
            passes.append(pass_reports)
        result["counters"] = counters
        result["passes"] = passes
        result["memory_events"] = _memory_proof(DB_PATH, time.time() - 3600)
        result["leftovers"] = leftovers
        print("PROGRESS " + json.dumps(
            {"stage": "counters_after", "counters": counters,
             "passes": passes, "memory": (
                 {"calls": spy.calls, "done": spy.done,
                  "failed": spy.failed} if spy is not None else None)},
            ensure_ascii=False), file=sys.stderr, flush=True)
        if spy is not None:
            result["memory"] = {"calls": spy.calls, "done": spy.done,
                                "failed": spy.failed,
                                "last_error": spy.last_error}

        # ── Writer: реальный блок source-ref'ов для тех же сообщений ────
        writer = {}
        for target, fid, entry in resolved:
            if fid is None:
                continue
            is_note = target["kind"] == "video_note"
            try:
                writer[target["label"]] = await _writer_probe(
                    db, target["chat_id"], target["message_id"],
                    voice=not is_note, video_note=is_note)
            except Exception as exc:                 # noqa: BLE001
                writer[target["label"]] = {"error": type(exc).__name__}
        result["writer"] = writer
        print("PROGRESS " + json.dumps(
            {"stage": "writer", "writer": writer}, ensure_ascii=False),
            file=sys.stderr, flush=True)

        # ── остатки временных файлов + запрет отправок ──────────────────
        tmp_left = sorted(p.name for p in Path(tempfile.gettempdir()).glob("vt_*"))
        result["guards"] = {
            "telegram_send_attempts": blocked["attempts"],
            "telegram_send_methods": blocked["methods"],
            "temp_files_left": len(tmp_left),
            "temp_sample": tmp_left[:5],
        }
        result["ok"] = not result["errors"]
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
        try:
            await db.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:                          # noqa: BLE001
        print(json.dumps({"ok": False, "fatal": type(exc).__name__,
                          "detail": str(exc)[:200]}, ensure_ascii=False))
        raise
