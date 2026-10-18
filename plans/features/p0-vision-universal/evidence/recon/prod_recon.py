"""P0 vision recon — ОДИН read-only SSH-коннект на прод (fail2ban-дисциплина).

Ничего не меняет: только SELECT/чтение журнала. Секреты не печатаются
(ключи — только маска present/len/last4). Пароль берётся из
deploy_commands.txt и никогда не попадает ни в argv, ни в stdout.
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
APP = "/var/www/admin_bot"
CREDS = Path(__file__).resolve().parents[2] / "deploy_commands.txt"

REMOTE = r'''
import asyncio, json, os, re, sqlite3, time, glob

SQLITE = "/var/www/admin_bot/local_database.db"
KEYS = ("models.vision_api_base_url", "models.vision_api_type",
        "models.vision_model", "keys.vision_api_key",
        "flags.vision_enabled", "models.llm_base_url",
        "models.llm_model_name", "keys.llm_api_key",
        "limits.vision_image_max_dimension", "limits.vision_queue_capacity",
        "limits.vision_user_rate", "limits.vision_chat_rate")


def mask(v):
    s = "" if v is None else str(v)
    if not s:
        return "absent"
    return "present(len=%d,last4=%s)" % (len(s), s[-4:])


def load_env():
    try:
        for line in open("/var/www/admin_bot/.env", encoding="utf-8",
                         errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(),
                                      v.strip().strip('"').strip("'"))
    except OSError:
        pass


def flat(v):
    if isinstance(v, dict):
        for k in ("value", "v", "text", "string"):
            if k in v:
                return flat(v[k])
        return "dict(%s)" % ",".join(sorted(v.keys())[:8])
    return v


async def settings_part():
    load_env()
    dsn = os.environ.get("POSTGRES_DSN", "")
    print("== ENV (process env files) ==")
    for name in ("MCA_VISION_ENABLED", "MCA_VISION_AUTO_ENABLED",
                 "MCA_VISION_BACKFILL_ENABLED", "MCA_VISION_TOOL_ENABLED",
                 "MCA_VISION_CAPABILITY_TTL_HOURS",
                 "MCA_VISION_DEFERRED_TTL_HOURS", "VISION_ENABLED",
                 "VISION_API_TYPE", "VISION_MODEL", "VISION_API_BASE_URL",
                 "VISION_API_KEY"):
        raw = os.environ.get(name)
        val = "<unset>" if raw is None else (
            mask(raw) if name in ("VISION_API_KEY",) else raw)
        print("  %s=%s" % (name, val))
    if not dsn:
        print("== bot_settings: NO DSN ==")
        return
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn, timeout=10)
    except Exception as exc:
        print("== bot_settings: PG ERROR %s ==" % type(exc).__name__)
        return
    try:
        rows = await conn.fetch(
            "SELECT key, value FROM bot_settings WHERE key = ANY($1::text[])",
            list(KEYS))
        print("== bot_settings (effective config) ==")
        got = {r["key"]: r["value"] for r in rows}
        for key in KEYS:
            if key not in got:
                print("  %s = <no row>" % key)
                continue
            val = got[key]
            if isinstance(val, (bytes, bytearray)):
                val = val.decode("utf-8", "replace")
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
            val = flat(val)
            if key.startswith("keys."):
                val = mask(val)
            print("  %s = %r" % (key, val))
    finally:
        await conn.close()


def sqlite_part():
    now = int(time.time())
    con = sqlite3.connect("file:%s?mode=ro" % SQLITE, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    print("== mca_events: vision_capability_probe ==")
    try:
        rows = con.execute(
            "SELECT outcome, reason_code, stage, model, COUNT(*) c, "
            "MAX(ts) last_ts FROM mca_events "
            "WHERE event_name='vision_capability_probe' GROUP BY 1,2,3,4 "
            "ORDER BY c DESC LIMIT 20").fetchall()
        if not rows:
            print("  <нет событий>")
        for r in rows:
            print("  outcome=%s reason=%s stage=%s model=%s count=%d last=%s"
                  % (r["outcome"], r["reason_code"], r["stage"], r["model"],
                     r["c"],
                     time.strftime("%Y-%m-%d %H:%M:%SZ",
                                   time.gmtime(r["last_ts"] or 0))))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== mca_events: последние 12 probe-событий ==")
    try:
        for r in con.execute(
                "SELECT ts, level, outcome, reason_code, stage, model, "
                "component FROM mca_events "
                "WHERE event_name='vision_capability_probe' "
                "ORDER BY id DESC LIMIT 12").fetchall():
            print("  %s %s outcome=%s reason=%s stage=%s model=%s comp=%s"
                  % (time.strftime("%m-%d %H:%M:%SZ", time.gmtime(r["ts"])),
                     r["level"], r["outcome"], r["reason_code"], r["stage"],
                     r["model"], r["component"]))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== mca_events: vision.* события по имени (24ч) ==")
    try:
        for r in con.execute(
                "SELECT event_name, outcome, reason_code, COUNT(*) c "
                "FROM mca_events WHERE ts > ? AND "
                "(event_name LIKE 'vision%' OR component LIKE 'vision%') "
                "GROUP BY 1,2,3 ORDER BY c DESC LIMIT 25",
                (now - 86400,)).fetchall():
            print("  %s outcome=%s reason=%s count=%d"
                  % (r["event_name"], r["outcome"], r["reason_code"], r["c"]))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== task_jobs: vision ==")
    try:
        for r in con.execute(
                "SELECT kind, status, reason_code, COUNT(*) c, MAX(updated_at) "
                "last_u FROM task_jobs WHERE kind LIKE 'vision%' "
                "GROUP BY 1,2,3 ORDER BY 1,2").fetchall():
            print("  kind=%s status=%s reason=%s count=%d last=%s"
                  % (r["kind"], r["status"], r["reason_code"], r["c"],
                     time.strftime("%m-%d %H:%M:%SZ",
                                   time.gmtime(r["last_u"] or 0))))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== task_jobs: последние 10 vision-джоб ==")
    try:
        for r in con.execute(
                "SELECT job_id, kind, status, reason_code, attempt, "
                "max_attempts, created_at, updated_at, heartbeat_at "
                "FROM task_jobs WHERE kind LIKE 'vision%' "
                "ORDER BY created_at DESC LIMIT 10").fetchall():
            print("  %s.. kind=%s status=%s reason=%s att=%s/%s cr=%s up=%s"
                  % (str(r["job_id"])[:10], r["kind"], r["status"],
                     r["reason_code"], r["attempt"], r["max_attempts"],
                     time.strftime("%m-%d %H:%M:%SZ",
                                   time.gmtime(r["created_at"] or 0)),
                     time.strftime("%m-%d %H:%M:%SZ",
                                   time.gmtime(r["updated_at"] or 0))))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== mca_media_analyses: последние 8 ==")
    try:
        for r in con.execute(
                "SELECT id, status, analyzer_provider, analyzer_model, "
                "error_reason, completed_at FROM mca_media_analyses "
                "ORDER BY id DESC LIMIT 8").fetchall():
            print("  id=%s status=%s provider=%s model=%s err=%s done=%s"
                  % (r["id"], r["status"], r["analyzer_provider"],
                     r["analyzer_model"], r["error_reason"],
                     r["completed_at"]))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== mca_media_assets / analyses — счётчики ==")
    try:
        a = con.execute("SELECT COUNT(*) FROM mca_media_assets").fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM mca_media_analyses").fetchone()[0]
        print("  assets=%s analyses=%s" % (a, n))
    except Exception as exc:
        print("  ERROR %s" % exc)
    con.close()


if __name__ == "__main__":
    sqlite_part()
    asyncio.run(settings_part())
'''


def _pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def main() -> int:
    pw = _pwd()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                   auth_timeout=30, allow_agent=False, look_for_keys=False)

    def run(cmd: str, timeout: float = 180.0) -> str:
        _in, out, err = client.exec_command(cmd, timeout=timeout)
        text = out.read().decode("utf-8", "replace")
        etext = err.read().decode("utf-8", "replace")
        if etext.strip():
            text += "\n[stderr] " + etext[:800]
        return text.replace(pw, "***")

    try:
        print("== git ==")
        print(run("cd %s && git log -1 --format='%%h %%cd %%s' "
                  "--date=format:%%Y-%%m-%%dT%%H:%%M:%%SZ" % APP).strip())
        print("== интерпретатор ==")
        which = run(
            "for p in %s/venv/bin/python %s/.venv/bin/python3 "
            "/var/www/admin_bot/venv/bin/python python3; do "
            "if [ -x \"$p\" ] || command -v \"$p\" >/dev/null 2>&1; then "
            "if \"$p\" -c 'import asyncpg, sqlite3' 2>/dev/null; then "
            "echo PY_OK=$p; break; fi; fi; done" % (APP, APP))
        print(which.strip())
        m = re.search(r"PY_OK=(\S+)", which)
        if not m:
            print("!! python+asyncpg not found")
            return 2
        py = m.group(1)

        print("== upload ==")
        _in, out, err = client.exec_command(
            "cat > /tmp/p0vision_recon.py && wc -c /tmp/p0vision_recon.py",
            timeout=60)
        _in.write(REMOTE)
        _in.channel.shutdown_write()
        print(out.read().decode("utf-8", "replace").strip())
        etext = err.read().decode("utf-8", "replace").strip()
        if etext:
            print("[stderr] " + etext[:400])
        print("== RECON OUTPUT ==")
        print(run("%s /tmp/p0vision_recon.py" % py, timeout=300))
        print("== journalctl: skip-тики/vision ==")
        print(run(
            "echo SKIPPED_INSTANCES=$(journalctl -u admin_bot --since '-36 hours' "
            "--no-pager 2>/dev/null | grep -c 'maximum number of running instances') ; "
            "echo VISION_WORKER_START=$(journalctl -u admin_bot --since '-36 hours' "
            "--no-pager 2>/dev/null | grep -c 'vision media worker started') ; "
            "journalctl -u admin_bot --since '-36 hours' --no-pager 2>/dev/null "
            "| grep -iE 'vision' | tail -25", timeout=120))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
