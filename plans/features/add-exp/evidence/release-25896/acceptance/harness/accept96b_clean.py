# -*- coding: utf-8 -*-
"""ACCEPTANCE-96 cleanup — удаление всех тестовых сообщений волн ADD-EXP Ф6.

Правило владельца: тестовые сообщения удаляются после проверок.
Safety-gate: mid удаляется, только если он наш (bot-отправка волны) или
синтетическая строка; сообщения реальных пользователей не трогаются.
Остаток-долг «1 фото 95a» (mid 1166469) удаляется ТОЛЬКО при надёжной
идентификации из spec (mca_media_assets/бот-реестр), не по догадке.

Вход: /tmp/accept96b/cleanup_spec.json
Выход: /tmp/accept96b/evidence/cleanup-register.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SYNTH_USER = 990002001
EXPECTED_BOT_ID = 8802473181
SPEC_IN = "/tmp/accept96b/cleanup_spec.json"
REGISTER_OUT = "/tmp/accept96b/evidence/cleanup-register.json"


def out(tag, text):
    print("ACC96CLEAN %s | %s" % (tag, text), flush=True)


def db_path():
    from config.settings import settings
    path = str(getattr(settings, "DB_PATH", "") or "local_database.db")
    if not os.path.isabs(path):
        path = os.path.join(APP, path)
    return path


def q(sql, args=()):
    con = sqlite3.connect(db_path(), timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=20000")
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def short(value, n=80):
    return " ".join(str(value or "").split())[:n]


async def main() -> int:
    from config.settings import settings
    from aiogram import Bot
    from services.local_bot_api import build_local_api_session

    try:
        os.umask(0o022)
    except Exception:
        pass
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    with open(SPEC_IN, "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    chat_a = int(spec.get("chat_a"))
    chat_b = spec.get("chat_b")
    delete_map = {int(k): sorted({int(m) for m in (v or [])})
                  for k, v in (spec.get("delete_mids") or {}).items()}
    residual = spec.get("residual_95a") or {}
    out("SPEC", "A=%s B=%s deleteA=%d deleteB=%d residual=%s"
        % (chat_a, chat_b, len(delete_map.get(chat_a) or []),
           len(delete_map.get(int(chat_b)) if chat_b else []) if chat_b else 0,
           residual.get("delete")))

    # инвентарь (до удаления) + safety-gate против реальных пользователей
    inventory = {}
    for chat_id, mids in delete_map.items():
        if not mids:
            inventory[str(chat_id)] = {"smart": [], "replies": [],
                                       "blocked": []}
            continue
        placeholders = ",".join("?" * len(mids))
        smart = q(
            "SELECT tg_message_id mid, user_id, substr(text,1,90) head "
            "FROM smart_messages WHERE chat_id=? AND tg_message_id IN (%s) "
            "ORDER BY tg_message_id" % placeholders, (chat_id, *mids))
        replies = q(
            "SELECT tg_message_id mid, substr(text,1,90) head FROM "
            "bot_replies WHERE chat_id=? AND tg_message_id IN (%s) "
            "ORDER BY tg_message_id" % placeholders, (chat_id, *mids))
        rep_by_mid = {r["mid"]: r for r in replies}
        blocked = []
        for row in smart:
            if row["user_id"] not in (SYNTH_USER, EXPECTED_BOT_ID) \
                    and row["mid"] not in rep_by_mid:
                blocked.append({"mid": row["mid"], "user_id": row["user_id"],
                                "head": short(row["head"]),
                                "reason": "real user message"})
        inventory[str(chat_id)] = {"smart": smart, "replies": replies,
                                   "blocked": blocked}
        if blocked:
            out("WARN", "chat=%s blocked mids (не трогаем): %s"
                % (chat_id, [b["mid"] for b in blocked]))
            delete_map[chat_id] = [m for m in mids
                                   if m not in {b["mid"] for b in blocked}]

    # остаток 95a: только надёжная идентификация (уже проверена harness-ом)
    residual_deleted = []
    if residual.get("delete"):
        delete_map.setdefault(chat_a, [])
        for mid in residual["delete"]:
            mid = int(mid)
            rows = q("SELECT user_id FROM smart_messages WHERE chat_id=? AND "
                     "tg_message_id=?", (chat_a, mid))
            if any(r["user_id"] not in (SYNTH_USER, EXPECTED_BOT_ID)
                   for r in rows):
                out("RESIDUAL", "skip %s — есть строка реального юзера" % mid)
                continue
            if mid not in delete_map[chat_a]:
                delete_map[chat_a].append(mid)
            residual_deleted.append(mid)
        out("RESIDUAL", "к удалению 95a: %s | %s"
            % (residual_deleted, residual.get("identification")))

    if bool(getattr(settings, "DOWNLOAD_ENABLED", False)):
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(
                      settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        me = await bot.get_me()
        out("BOT", "id=%s username=%s" % (me.id, me.username))
        if int(me.id) != EXPECTED_BOT_ID:
            out("ABORT", "unexpected bot id")
            return 5
        for chat_id, mids in sorted(delete_map.items()):
            for mid in sorted(mids):
                rec = {"chat_id": chat_id, "mid": mid}
                if mid in (residual.get("delete") or []):
                    rec["residual_95a"] = True
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=mid)
                    rec["status"] = "deleted"
                except Exception as exc:  # noqa: BLE001
                    text = str(exc)
                    if "not found" in text.lower():
                        rec["status"] = "already_deleted"
                    else:
                        rec["status"] = "error"
                        rec["error"] = (type(exc).__name__ + ": "
                                        + text)[:160]
                deleted.append(rec)
                out("DEL", "chat=%s %s %s" % (chat_id, mid, rec["status"]))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass

    # синтетические строки (smart/bot_replies/bot_reply_parents/throttle)
    removed = {"smart": 0, "bot_replies": 0, "bot_reply_parents": 0,
               "throttle": 0}
    try:
        con = sqlite3.connect(db_path(), timeout=20)
        con.execute("PRAGMA busy_timeout=20000")
        for chat_id, mids in delete_map.items():
            if not mids:
                continue
            placeholders = ",".join("?" * len(mids))
            rows = con.execute(
                "SELECT rowid rid, user_id FROM smart_messages WHERE "
                "chat_id=? AND tg_message_id IN (%s)" % placeholders,
                (chat_id, *mids)).fetchall()
            for rid, uid in rows:
                if uid not in (SYNTH_USER, EXPECTED_BOT_ID):
                    continue
                try:
                    con.execute("DELETE FROM smart_messages_fts WHERE "
                                "rowid=?", (rid,))
                except Exception:
                    pass
                con.execute("DELETE FROM smart_messages WHERE rowid=?",
                            (rid,))
                removed["smart"] += 1
            cur = con.execute(
                "DELETE FROM bot_replies WHERE chat_id=? AND "
                "tg_message_id IN (%s)" % placeholders, (chat_id, *mids))
            removed["bot_replies"] += int(cur.rowcount or 0)
            cur = con.execute(
                "DELETE FROM bot_reply_parents WHERE chat_id=? AND "
                "tg_message_id IN (%s)" % placeholders, (chat_id, *mids))
            removed["bot_reply_parents"] += int(cur.rowcount or 0)
            cur = con.execute(
                "DELETE FROM throttle_state WHERE scope IN "
                "('direct_chat','direct_silence') AND chat_id=? AND user_id=?",
                (chat_id, SYNTH_USER))
            removed["throttle"] += int(cur.rowcount or 0)
        con.commit()
        con.close()
    except Exception as exc:  # noqa: BLE001
        out("DBROWS", "cleanup failed: %s" % type(exc).__name__)

    # верификация
    verification = {}
    for chat_id, mids in delete_map.items():
        if not mids:
            continue
        placeholders = ",".join("?" * len(mids))
        verification[str(chat_id)] = {
            "residual_smart": q(
                "SELECT tg_message_id mid, user_id FROM smart_messages "
                "WHERE chat_id=? AND tg_message_id IN (%s)" % placeholders,
                (chat_id, *mids)),
            "residual_replies": q(
                "SELECT tg_message_id mid FROM bot_replies WHERE chat_id=? "
                "AND tg_message_id IN (%s)" % placeholders, (chat_id, *mids)),
            "residual_parents": q(
                "SELECT tg_message_id mid FROM bot_reply_parents WHERE "
                "chat_id=? AND tg_message_id IN (%s)" % placeholders,
                (chat_id, *mids)),
        }
    failed = [r for r in deleted if r["status"] == "error"]
    register = {
        "generated_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "method": ("Telegram Bot API deleteMessage через развёрнутого бота "
                   "(локальная сессия); safety-gate против реальных "
                   "пользователей; синтетические строки удалены"),
        "delete_map": {str(k): v for k, v in delete_map.items()},
        "deleted": deleted,
        "residual_95a": residual,
        "residual_95a_deleted": residual_deleted,
        "inventory": inventory,
        "synthetic_rows_removed": removed,
        "verification": verification,
        "failed": failed,
    }
    os.makedirs(os.path.dirname(REGISTER_OUT), exist_ok=True)
    with open(REGISTER_OUT, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(register, ensure_ascii=False, indent=1,
                            default=str))
    out("VERIFY", json.dumps({
        "deleted": sum(1 for r in deleted if r["status"] == "deleted"),
        "already": sum(1 for r in deleted
                       if r["status"] == "already_deleted"),
        "failed": [r["mid"] for r in failed],
        "removed": removed,
    }, ensure_ascii=False)[:400])
    residual_rows = sum(len(v.get("residual_smart") or [])
                        for v in verification.values())
    residual_reps = sum(len(v.get("residual_replies") or [])
                        for v in verification.values())
    out("DONE", "residual_rows=%d residual_replies=%d failed=%d"
        % (residual_rows, residual_reps, len(failed)))
    return 0 if not failed and not residual_rows and not residual_reps else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC96CLEAN FATAL | %s: %s" % (type(exc).__name__,
                                             str(exc)[:300]), flush=True)
        traceback.print_exc()
    print("ACC96CLEAN RC=%d" % rc, flush=True)
    os._exit(rc)

