# -*- coding: utf-8 -*-
"""ACCEPTANCE-92C — definitive download-path test (ONE tiny run).

Confirms whether bot.download() with the prod local-Bot-API session fails
(aiogram is_local=True reads the file from the LOCAL FILESYSTEM path returned
by the server), while the cloud session downloads fine.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORK_CHAT = -1002661910336
ASSET_MID = 1165720
OUT = "/tmp/accept92c/evidence/dl-test-register.json"


def out(tag, text):
    print("DLT92C %s | %s" % (tag, text), flush=True)


def _mask_path(path: str) -> str:
    """Mask the bot-token fragment inside telegram-bot-api paths."""
    import re as _re
    p = str(path or "")
    p = _re.sub(r"\d{6,}:[A-Za-z0-9_-]{6,}", "<bot-id:masked>", p)
    return p[:120]


async def main() -> int:
    from config.settings import settings
    from services.config_cache import ConfigCache
    from services.hot_config import set_config_cache
    from services import hot_config as hot

    res = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    cache = ConfigCache()
    await cache.init()
    set_config_cache(cache)

    import sqlite3
    db_path = str(getattr(settings, "DB_PATH", "local_database.db"))
    if not os.path.isabs(db_path):
        db_path = os.path.join(APP, db_path)
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    row = con.execute(
        "SELECT file_id FROM mca_media_assets WHERE chat_id=? AND "
        "tg_message_id=? AND asset_kind='photo' LIMIT 1",
        (WORK_CHAT, ASSET_MID)).fetchone()
    con.close()
    file_id = str(row[0]) if row else ""

    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    enabled = bool(hot.get("flags.download_enabled",
                           settings.DOWNLOAD_ENABLED))
    res["download_enabled"] = enabled

    # A) cloud session: get_file + download
    if file_id:
        try:
            b = Bot(token=settings.API_TOKEN)
            f = await b.get_file(file_id)
            buf = io.BytesIO()
            await b.download(f, destination=buf)
            res["cloud"] = {"get_file": True, "download": True,
                            "bytes": len(buf.getvalue())}
            await b.session.close()
        except Exception as exc:  # noqa: BLE001
            res["cloud"] = {"error": "%s: %s" % (type(exc).__name__,
                                                 str(exc)[:180])}
        # B) prod-config session (local Bot API): get_file + download + exists
        try:
            sess = AiohttpSession(
                api=TelegramAPIServer.from_base(settings.LOCAL_BOT_API_URL,
                                                is_local=True))
            b2 = Bot(token=settings.API_TOKEN, session=sess)
            f2 = await b2.get_file(file_id)
            raw_path = str(getattr(f2, "file_path", "") or "")
            local_path = sess.api.wrap_local_file.to_local(raw_path)
            res["local"] = {"get_file": True,
                            "file_path_masked": _mask_path(raw_path),
                            "to_local_masked": _mask_path(str(local_path)),
                            "host_exists": os.path.exists(str(local_path))}
            try:
                buf2 = io.BytesIO()
                await b2.download(f2, destination=buf2)
                res["local"]["download"] = True
                res["local"]["bytes"] = len(buf2.getvalue())
            except Exception as exc:  # noqa: BLE001
                res["local"]["download"] = False
                res["local"]["download_error"] = "%s: %s" % (
                    type(exc).__name__, str(exc)[:200])
            await b2.session.close()
        except Exception as exc:  # noqa: BLE001
            res["local"] = {"error": "%s: %s" % (type(exc).__name__,
                                                 str(exc)[:180])}
    out("RESULT", json.dumps({k: res.get(k) for k in ("cloud", "local")},
                             ensure_ascii=False))
    try:
        await cache.close()
    except Exception:
        pass
    os.makedirs("/tmp/accept92c/evidence", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    out("DONE", "saved")
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("DLT92C FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("DLT92C RC=%d" % rc, flush=True)
    os._exit(rc)
