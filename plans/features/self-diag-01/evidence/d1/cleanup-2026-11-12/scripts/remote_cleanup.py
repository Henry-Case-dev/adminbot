#!/usr/bin/env python3
"""SELF-DIAG-01 D1: targeted removal of 5 orphaned Better Stack rows.

Read-only pre-check -> targeted backup (+restore script) -> single-transaction
DELETE of exactly 5 keys -> DB verify -> /api/config verify -> restart once
(in-memory ConfigCache is loaded at startup) -> re-verify.

Never prints secret values: only key names, lengths, presence/shape flags,
hashes and counts. Backup is base64-emitted between markers for the caller.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import asyncpg

APP = "/var/www/admin_bot"
KEYS = [
    "keys.checkup_betterstack_sql_password",
    "keys.checkup_betterstack_sql_user",
    "models.checkup_betterstack_sql_host",
    "models.checkup_betterstack_sql_query",
    "models.checkup_betterstack_sql_table",
]
BACKUP_DIR = "/root/adminbot_backup_self-diag-01"
BACKUP = os.path.join(BACKUP_DIR, "bot_settings_betterstack_2026-11-12.json")
RESTORE = os.path.join(BACKUP_DIR, "restore_bot_settings_betterstack.py")


def out(*a):
    print(*a, flush=True)


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_env():
    from dotenv import dotenv_values
    return dotenv_values(os.path.join(APP, ".env"))


ENV = read_env()
DSN = ENV.get("POSTGRES_DSN") or os.environ.get("POSTGRES_DSN") or ""
PORT = int(ENV.get("WEB_PORT") or 8000)
TOKEN = ENV.get("API_TOKEN") or ""


def build_initdata(user_id):
    user = {"id": int(user_id), "first_name": "ops"}
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(user, separators=(",", ":")),
    }
    dcs = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(dict(fields, hash=h))


def http_config(init_data):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/config" % PORT,
        headers={"X-Telegram-Init-Data": init_data},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # network/parse
        out("CFG_HTTP_EXC=%s" % type(exc).__name__)
        return 0, None


def summarize_config(label, status, data):
    if not data or "items" not in data:
        out("CFG_%s_HTTP=%s ITEMS=unavailable" % (label, status))
        return None
    items = data.get("items") or []
    by_key = {it.get("key"): it for it in items}
    matched = sorted(
        k for k in by_key
        if (k and ("betterstack" in k.lower() or k.startswith("models.checkup")))
    )
    out("CFG_%s_HTTP=%s ITEMS=%d MATCHED=%d"
        % (label, status, len(items), len(matched)))
    for key in matched:
        val = by_key[key].get("value")
        if isinstance(val, dict) and set(val) <= {"configured", "last4"}:
            out("CFG_%s_KEY %s shape=masked configured=%s"
                % (label, key, bool(val.get("configured"))))
        else:
            out("CFG_%s_KEY %s shape=%s" % (label, key, type(val).__name__))
    kept = [k for k in (
        "flags.checkup_enabled",
        "flags.checkup_memory_metrics_enabled",
        "limits.checkup_cooldown_seconds",
        "limits.checkup_max_symbols",
        "limits.checkup_max_input_symbols",
        "prompts.checkup_system_prompt",
    ) if k in by_key]
    out("CFG_%s_CHECKUP_KEPT=%d" % (label, len(kept)))
    return by_key


async def resolve_admin_ids(conn):
    rows = await conn.fetch(
        "SELECT a.telegram_id, "
        "COALESCE((r.permissions->>'wildcard')::boolean, false) AS w "
        "FROM bot_admins a JOIN bot_roles r ON r.role_name = a.role_name "
        "ORDER BY w DESC, a.telegram_id LIMIT 5")
    return [int(row["telegram_id"]) for row in rows]


def probe_config(admin_ids):
    """Pick an admin whose /api/config response exposes the keys.* section."""
    first = None
    for uid in admin_ids:
        init = build_initdata(uid)
        status, data = http_config(init)
        if not data or "items" not in data:
            continue
        has_keys_section = any(
            str(it.get("key", "")).startswith("keys.")
            for it in data["items"])
        if first is None:
            first = (init, status, data)
        if has_keys_section:
            out("CFG_ADMIN_PROBE=ok keys_section=visible")
            return init, status, data
    out("CFG_ADMIN_PROBE=weak keys_section=absent")
    return first if first else (None, 0, None)


async def cache_snapshot_matched():
    """Read-only fallback: what GET /api/config iterates (ConfigCache.get_all)."""
    try:
        from services.config_cache import ConfigCache
        cache = ConfigCache(dsn=DSN)
        await cache._pg.connect()
        try:
            await cache._load_all()
            return sorted(
                k for k in cache.get_all()
                if ("betterstack" in k.lower()
                    or k.startswith("models.checkup")))
        finally:
            await cache._pg.close()
    except Exception as exc:
        out("CACHE_SNAPSHOT_EXC=%s" % type(exc).__name__)
        return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def journal_counts(minutes):
    try:
        res = subprocess.run(
            ["journalctl", "-u", "admin_bot", "--since", "-%d min" % minutes,
             "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=30, check=False)
    except Exception as exc:
        return "JOURNAL_EXC=%s" % type(exc).__name__
    lines = res.stdout.splitlines()
    tb = sum(1 for ln in lines if "Traceback" in ln)
    er = sum(1 for ln in lines if "ERROR" in ln)
    cr = sum(1 for ln in lines if "CRITICAL" in ln)
    return "JOURNAL_LINES=%d TRACEBACK=%d ERROR=%d CRITICAL=%d" % (
        len(lines), tb, er, cr)


def unit_prop(prop):
    try:
        res = subprocess.run(
            ["systemctl", "show", "admin_bot", "-p", prop, "--value"],
            capture_output=True, text=True, timeout=15, check=False)
        return res.stdout.strip()
    except Exception:
        return "ERR"


def head_matches(rel_path):
    try:
        disk = hashlib.sha256(
            open(os.path.join(APP, rel_path), "rb").read()).hexdigest()
        head = subprocess.run(
            ["git", "-C", APP, "show", "HEAD:" + rel_path],
            capture_output=True, check=True).stdout
        return disk == hashlib.sha256(head).hexdigest()
    except Exception:
        return False


RESTORE_SRC = '''#!/usr/bin/env python3
"""Restore the 5 backed-up Better Stack rows (SELF-DIAG-01 D1 rollback)."""
import asyncio
import json
from datetime import datetime

import asyncpg
from dotenv import dotenv_values

APP = "/var/www/admin_bot"
BACKUP = "/root/adminbot_backup_self-diag-01/bot_settings_betterstack_2026-11-12.json"

env = dotenv_values(APP + "/.env")
dsn = env.get("POSTGRES_DSN")


async def main():
    doc = json.load(open(BACKUP, "r", encoding="utf-8"))
    rows = doc["rows"]
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        async with conn.transaction():
            for row in rows:
                await conn.execute(
                    "INSERT INTO bot_settings (key, value, category, updated_at) "
                    "VALUES ($1, $2::jsonb, $3, $4) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                    "category = EXCLUDED.category, updated_at = EXCLUDED.updated_at",
                    row["key"], row["value_json"], row["category"],
                    datetime.fromisoformat(row["updated_at"]))
        print("RESTORED_ROWS=%d" % len(rows))
    finally:
        await conn.close()


asyncio.run(main())
'''


async def main():
    out("PHASE=start utc=%s" % utcnow())
    out("HEAD=%s" % subprocess.run(
        ["git", "-C", APP, "rev-parse", "HEAD"],
        capture_output=True, text=True).stdout.strip())
    out("BRANCH=%s" % subprocess.run(
        ["git", "-C", APP, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True).stdout.strip())
    out("GIT_DIRTY_TRACKED=%s" % len(subprocess.run(
        ["git", "-C", APP, "status", "--porcelain", "--untracked-files=no"],
        capture_output=True, text=True).stdout.splitlines()))
    out("UNIT_ACTIVE=%s NRestarts=%s InvocationID=%s"
        % (unit_prop("ActiveState"), unit_prop("NRestarts"),
           unit_prop("InvocationID")))
    out("ENV_BETTERSTACK_HOST=%d ENV_LOGTAIL_SOURCE_TOKEN=%d"
        % (1 if "BETTERSTACK_HOST" in ENV else 0,
           1 if "LOGTAIL_SOURCE_TOKEN" in ENV else 0))
    grep = subprocess.run(
        ["git", "-C", APP, "grep", "-n", "checkup_betterstack_sql",
         "--", "services", "handlers", "config", "web", "bot.py"],
        capture_output=True, text=True)
    out("GIT_GREP_RUNTIME_RC=%d RUNTIME_HITS=%d"
        % (grep.returncode, len(grep.stdout.splitlines())))
    full = subprocess.run(
        ["git", "-C", APP, "grep", "-l", "checkup_betterstack_sql", "--", "."],
        capture_output=True, text=True)
    out("GIT_GREP_REPO_FILES_WITH_MENTIONS=%d"
        % len([ln for ln in full.stdout.splitlines() if ln.strip()]))
    out("HEAD_MATCH betterstack_handler.py=%s external_log.py=%s"
        % (head_matches("services/betterstack_handler.py"),
           head_matches("services/external_log.py")))

    if not DSN:
        out("ABORT=no_postgres_dsn")
        return 2

    conn = await asyncpg.connect(DSN, timeout=15)
    try:
        await conn.execute("SET lock_timeout = '5000'")
        await conn.execute("SET statement_timeout = '30000'")
        admin_ids = await resolve_admin_ids(conn)
        out("ADMIN_IDS_RESOLVED=%d" % len(admin_ids))
        if TOKEN and admin_ids:
            init_data, status, data = probe_config(admin_ids)
        else:
            init_data, status, data = None, 0, None
        out("TMA_PROBE_AVAILABLE=%s" % (init_data is not None))

        pre = await conn.fetch(
            "SELECT key, length(value::text) AS l, category, updated_at "
            "FROM bot_settings WHERE key = ANY($1::text[]) ORDER BY key", KEYS)
        out("PRE_COUNT=%d" % len(pre))
        for row in pre:
            out("PRE_ROW %s len=%s category=%s"
                % (row["key"], row["l"], row["category"]))
        extra = await conn.fetch(
            "SELECT key, length(value::text) AS l FROM bot_settings "
            "WHERE key ILIKE '%betterstack%' AND NOT (key = ANY($1::text[])) "
            "ORDER BY key", KEYS)
        out("PRE_EXTRA_BETTERSTACK=%d" % len(extra))
        for row in extra:
            out("PRE_EXTRA %s len=%s" % (row["key"], row["l"]))

        if init_data:
            out("CFG_PRE_HTTP=%s ITEMS=%d" % (status, len(data.get("items", [])) if data else 0))
            summarize_config("PRE", status, data)
        else:
            out("CFG_PRE=skipped")
            snap = await cache_snapshot_matched()
            out("CACHE_PRE_MATCHED=%s" % (snap if snap is not None else "ERR"))

        if len(pre) != 5 or extra:
            out("ABORT=preconditions_failed")
            return 2

        brows = await conn.fetch(
            "SELECT key, value::text AS v, category, updated_at "
            "FROM bot_settings WHERE key = ANY($1::text[]) ORDER BY key", KEYS)
        doc = {
            "meta": {
                "feature": "SELF-DIAG-01",
                "purpose": "D1 targeted backup of 5 orphaned Better Stack rows",
                "created_utc": utcnow(),
                "source": "production /var/www/admin_bot",
                "git_sha": subprocess.run(
                    ["git", "-C", APP, "rev-parse", "HEAD"],
                    capture_output=True, text=True).stdout.strip(),
                "rows": len(brows),
                "restore_script": RESTORE,
            },
            "rows": [
                {
                    "key": row["key"],
                    "value_json": row["v"],
                    "category": row["category"],
                    "updated_at": row["updated_at"].isoformat(),
                }
                for row in brows
            ],
        }
        os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
        os.chmod(BACKUP_DIR, 0o700)
        payload = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
        fd = os.open(BACKUP, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.chmod(BACKUP, 0o600)
        with open(RESTORE, "w", encoding="utf-8") as fh:
            fh.write(RESTORE_SRC)
        os.chmod(RESTORE, 0o600)
        compile(RESTORE_SRC, RESTORE, "exec")

        out("BACKUP_PATH=%s" % BACKUP)
        out("BACKUP_ROWS=%d" % len(brows))
        out("BACKUP_BYTES=%d" % len(payload))
        out("BACKUP_SHA256=%s" % sha256_file(BACKUP))
        out("RESTORE_PATH=%s" % RESTORE)
        out("RESTORE_SHA256=%s" % sha256_file(RESTORE))

        out("__BACKUP_B64_BEGIN__")
        out(base64.b64encode(payload).decode("ascii"))
        out("__BACKUP_B64_END__")

        async with conn.transaction():
            deleted = await conn.fetch(
                "DELETE FROM bot_settings WHERE key = ANY($1::text[]) "
                "RETURNING key", KEYS)
        dkeys = sorted(row["key"] for row in deleted)
        out("DELETE_RETURNED=%d" % len(dkeys))
        for key in dkeys:
            out("DELETED %s" % key)
        if dkeys != sorted(KEYS):
            out("DELETE_SET_MISMATCH=True")
            return 3

        cnt = await conn.fetchval(
            "SELECT count(*) FROM bot_settings WHERE key = ANY($1::text[])",
            KEYS)
        out("POST_COUNT=%d" % cnt)
        legacy = await conn.fetch(
            "SELECT key FROM bot_settings WHERE key ILIKE '%betterstack%' "
            "OR key LIKE 'models.checkup%' ORDER BY key")
        out("POST_LEGACY_ROWS=%d" % len(legacy))
        for row in legacy:
            out("POST_LEGACY %s" % row["key"])
        kept_checkup = await conn.fetch(
            "SELECT key FROM bot_settings WHERE key LIKE '%checkup%' "
            "ORDER BY key")
        out("POST_CHECKUP_ROWS=%d" % len(kept_checkup))
        for row in kept_checkup:
            out("POST_CHECKUP %s" % row["key"])

        if init_data:
            status, data = http_config(init_data)
            summarize_config("POST_DELETE_PRE_RESTART", status, data)
        else:
            snap = await cache_snapshot_matched()
            out("CACHE_POST_DELETE_MATCHED=%s"
                % (snap if snap is not None else "ERR"))

        out("RESTART=scheduled")
        subprocess.run(["systemctl", "restart", "admin_bot"],
                       check=True, timeout=90)
        healthy = False
        waited = 0
        for _ in range(45):
            time.sleep(2)
            waited += 2
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/healthz" % PORT,
                        timeout=5) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    if resp.status == 200 and body.get("status") == "ok":
                        out("POST_RESTART_HEALTH=ok version=%s waited=%ss"
                            % (body.get("version"), waited))
                        healthy = True
                        break
            except Exception:
                continue
        out("POST_RESTART_HEALTH_OK=%s" % healthy)
        if not healthy:
            out("ABORT=service_not_healthy_after_restart")
            return 4
        time.sleep(3)
        out("POST_RESTART_INVOCATION=%s NRestarts=%s"
            % (unit_prop("InvocationID"), unit_prop("NRestarts")))
        if init_data:
            status, data = http_config(init_data)
            summarize_config("POST_RESTART", status, data)
        else:
            snap = await cache_snapshot_matched()
            out("CACHE_POST_RESTART_MATCHED=%s"
                % (snap if snap is not None else "ERR"))
        cnt2 = await conn.fetchval(
            "SELECT count(*) FROM bot_settings WHERE key = ANY($1::text[])",
            KEYS)
        out("POST_RESTART_DB_COUNT=%d" % cnt2)
        out(journal_counts(10))
        out("PHASE=done utc=%s" % utcnow())
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # no secret values expected in messages
        out("FATAL=%s: %s" % (type(exc).__name__, str(exc)[:300]))
        sys.exit(9)
