# -*- coding: utf-8 -*-
"""ACCEPTANCE-91 final read-only post-check (prod 2.58.91)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
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
SYNTH_USER = 990002001
ADMIN_ID = 5885953495
OUT = {}


def info(tag, text):
    print("PC %s | %s" % (tag, text), flush=True)
    OUT[tag] = text


async def main() -> int:
    from services.config_cache import ConfigCache
    from services.hot_config import set_config_cache
    from services.chat_params import ChatParamsCache, set_chat_params_cache
    from services.worker_budget import set_worker_budget_pg
    from services.database import DatabaseService
    from services import hot_config as hot  # noqa: F401
    from config.settings import settings

    cache = ConfigCache()
    await cache.init()
    set_config_cache(cache)
    set_chat_params_cache(ChatParamsCache(cache.pg))
    set_worker_budget_pg(cache.pg)
    db = DatabaseService(settings.DB_PATH)
    await db.initialize_existing()

    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=APP, text=True).strip()
        tracked = int(subprocess.check_output(
            "git status --porcelain | grep -v '^??' | wc -l",
            cwd=APP, shell=True, text=True).strip() or 0)
        info("GIT", "HEAD=%s TRACKED_MOD=%s" % (head, tracked))
    except Exception as exc:  # noqa: BLE001
        info("GIT", "ERR %s" % type(exc).__name__)

    try:
        import httpx
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=20.0) as c:
            r = await c.get("/healthz")
            info("HEALTHZ", r.text)
            r = await c.get("/web/")
            html = r.text
            srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html)
            info("UI_WEB", "status=%s html_len=%d scripts=%s"
                 % (r.status_code, len(html), srcs[:6]))
            info("UI_MARKERS", "version=%d mod_vision=%d freq=%d"
                 % (html.count("2.58.91"), html.count("mod_vision"),
                    html.count("imageFreqActiveLabel")))
            for src in srcs[:6]:
                if not src.endswith(".js"):
                    continue
                path = src if src.startswith("/") else "/" + src
                rr = await c.get(path.split("?")[0])
                info("UI_SCRIPT", "%s status=%s len=%d"
                     % (path, rr.status_code, len(rr.content)))
                if rr.status_code == 200:
                    import hashlib
                    served = hashlib.sha256(rr.content).hexdigest()[:12]
                    repo_path = os.path.join(APP, "web", "app.js")
                    repo = hashlib.sha256(open(repo_path, "rb").read()
                                          ).hexdigest()[:12]
                    info("UI_HASH", "%s served=%s repo_appjs=%s same=%s"
                         % (path, served, repo, served == repo))
    except Exception as exc:  # noqa: BLE001
        info("UI", "ERR %s: %s" % (type(exc).__name__, str(exc)[:160]))

    try:
        from services import chat_params
        root = await chat_params.get_all_chat_params(WORK_CHAT, pg=cache.pg)
        ov = dict((root or {}).get("overrides") or {})
        info("OVERRIDES", "budgets=%r freq_keys=%s vision=%r"
             % (ov.get("flags.budgets_enabled"),
                [k for k in ov if k.startswith("limits.image_freq")],
                ov.get("flags.vision_enabled")))
    except Exception as exc:  # noqa: BLE001
        info("OVERRIDES", "ERR %s" % type(exc).__name__)

    try:
        from services import image_generation as ig
        limits, reason = await ig.image_freq_config(WORK_CHAT)
        state = await ig.image_freq_state(WORK_CHAT, SYNTH_USER)
        info("FREQ", "config_enabled=%s reason=%s limits=%s | state_applied=%s"
             % (getattr(limits, "enabled", None), reason, str(limits),
                getattr(state, "applied", None)))
        from services import worker_budget
        summary = await worker_budget.get_chat_summary(
            WORK_CHAT, viewer_user_id=ADMIN_ID)
        info("FREQ_UI", json.dumps({
            "active": (summary.get("freq") or {}).get("active"),
            "active_reason": (summary.get("freq") or {}).get("active_reason"),
            "enabled": (summary.get("freq") or {}).get("enabled"),
            "mode": (summary.get("freq") or {}).get("mode"),
            "burst": (summary.get("freq") or {}).get("burst"),
            "used": summary.get("used"),
        }, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        info("FREQ", "ERR %s: %s" % (type(exc).__name__, str(exc)[:160]))

    try:
        from services import mca_vision
        for target in (1165613, 1165606, 1165607):
            res = await mca_vision.resolve_target_assets(
                db, chat_id=WORK_CHAT, reply_tg_id=target)
            info("ASSET_RESOLVE", "target=%s status=%s assets=%d"
                 % (target, res.get("status"), len(res.get("assets") or [])))
        st = await mca_vision.resolve_effective_state(WORK_CHAT)
        info("VISION_STATE", "requested=%s effective=%s capability=%s reason=%s"
             % (getattr(st, "requested", None),
                getattr(st, "effective_enabled", None),
                getattr(st, "capability", None), getattr(st, "reason", None)))
    except Exception as exc:  # noqa: BLE001
        info("VISION_STATE", "ERR %s: %s" % (type(exc).__name__,
                                             str(exc)[:160]))

    try:
        cur = await db.db.execute("PRAGMA user_version")
        row = await cur.fetchone()
        info("USER_VERSION", str(dict(row).get("user_version")))
        cur = await db.db.execute(
            "SELECT COUNT(*) n FROM mca_events WHERE level IN "
            "('ERROR','CRITICAL') AND ts >= ?", (int(time.time()) - 10800,))
        info("MCA_ERRORS_3H", str(dict(await cur.fetchone()).get("n")))
    except Exception as exc:  # noqa: BLE001
        info("USER_VERSION", "ERR %s" % type(exc).__name__)

    try:
        rows = await worker_budget_get(cache)
        info("BUDGET_NOW", json.dumps(rows, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        info("BUDGET_NOW", "ERR %s" % type(exc).__name__)

    try:
        import asyncpg
        dsn = os.environ.get("POSTGRES_DSN") or ""
        if dsn:
            conn = await asyncpg.connect(dsn, timeout=10)
            try:
                rows = await conn.fetch(
                    "SELECT reservation_key, status, error_code, "
                    "delivery_failed, created_at FROM image_reservation "
                    "WHERE chat_id=$1 AND created_at >= to_timestamp($2) "
                    "ORDER BY created_at", WORK_CHAT,
                    int(time.time()) - 3600)
                info("RESERVATIONS", json.dumps(
                    [{k: str(v) for k, v in dict(r).items()} for r in rows],
                    ensure_ascii=False))
            finally:
                await conn.close()
    except Exception as exc:  # noqa: BLE001
        info("RESERVATIONS", "ERR %s: %s" % (type(exc).__name__,
                                             str(exc)[:160]))

    from services import mca_events
    try:
        await mca_events.flush_events(db)
    except Exception:
        pass
    try:
        await db.close()
        await cache.close()
    except Exception:
        pass
    with open("/tmp/accept91/evidence/postcheck.json", "w",
              encoding="utf-8") as fh:
        json.dump(OUT, fh, ensure_ascii=False, indent=2)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(0)


async def worker_budget_get(cache):
    from services import worker_budget
    rows = await worker_budget.get_usage(scope="global")
    out = [{k: str(v) for k, v in r.items()} for r in rows
           if r.get("metric") == "image_calls"]
    rows = await worker_budget.get_usage(scope="chat:%d" % WORK_CHAT)
    out += [{k: str(v) for k, v in r.items()} for r in rows
            if r.get("metric") == "image_calls"]
    return out


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print("PC FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]))
        raise SystemExit(4)
