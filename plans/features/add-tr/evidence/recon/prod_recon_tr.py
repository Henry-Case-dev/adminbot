# -*- coding: utf-8 -*-
"""TR-RECON prod (ADD-TR.0/2/3/4): ОДИН read-only SSH-коннект.

Только SELECT/журнал; секреты не печатаются; пароль не попадает в argv/stdout.
Переиспользует схему из p0-vision-universal/evidence/recon/prod_recon.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
APP = "/var/www/admin_bot"
_root = Path(__file__).resolve()
while _root.name and not (_root / "deploy_commands.txt").exists():
    if _root.parent == _root:
        break
    _root = _root.parent
CREDS = _root / "deploy_commands.txt"

REMOTE = r'''
import asyncio, json, os, sqlite3, time

SQLITE = "/var/www/admin_bot/local_database.db"

KEYS = (
    "flags.direct_l1_enabled", "flags.direct_l1_fallback_enabled",
    "flags.vision_enabled", "flags.factcheck_enabled",
    "flags.checkup_enabled", "flags.image_generation_module_enabled",
    "flags.direct_chat_botword_enabled", "flags.lore_compiler_enabled",
    "flags.summary_enabled", "flags.character_speech_enabled",
    "temporal.tool_enabled", "flags.humor_craft_enabled",
    "flags.search_enabled", "flags.webpage_enabled",
    "flags.video_summary_enabled", "flags.download_enabled",
)

ENV_NAMES = (
    "DIRECT_L1_ENABLED", "AGENTIC_EVENTS_ENABLED", "SUMMARY_ENABLED",
    "TEMPORAL_TOOL_ENABLED", "FACTCHECK_ENABLED", "CHECKUP_ENABLED",
    "IMAGE_GENERATION_ENABLED", "UNIFIED_IMAGE_REQUEST_ENABLED",
    "NATIVE_MEDIA_TOOLS_ENABLED", "MEDIA_TRANSCRIBE_TOOL_ENABLED",
    "ARTICLE_TOOL_ENABLED", "MEMORY_LOOKUP_ENABLED",
    "MCA_TOOL_RESULT_ENABLED", "MCA_TOOL_CHAIN_STAGES_ENABLED",
    "MCA_VISION_ENABLED", "MCA_VISION_TOOL_ENABLED",
    "MCA_VISION_AUTO_ENABLED", "MCA_VISION_BACKFILL_ENABLED",
    "MCA_TEMPORAL_FACTCHECK_ENABLED",
    "MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED",
)


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


def ts(v):
    try:
        return time.strftime("%m-%d %H:%M:%SZ", time.gmtime(int(v)))
    except Exception:
        return str(v)


async def pg_part():
    print("== ENV (.env оси) ==")
    load_env()
    for name in ENV_NAMES:
        raw = os.environ.get(name)
        print("  %s=%s" % (name, "<unset>" if raw is None else raw))
    dsn = os.environ.get("POSTGRES_DSN", "")
    if not dsn:
        print("== PG: NO DSN ==")
        return
    import asyncpg
    try:
        conn = await asyncpg.connect(dsn, timeout=10)
    except Exception as exc:
        print("== PG ERROR %s ==" % type(exc).__name__)
        return
    try:
        rows = await conn.fetch(
            "SELECT key, value FROM bot_settings WHERE key = ANY($1::text[])",
            list(KEYS))
        got = {r["key"]: r["value"] for r in rows}
        print("== bot_settings (effective flags) ==")
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
            print("  %s = %r" % (key, flat(val)))
        print("== chat_profiles: relevant overrides ==")
        try:
            crows = await conn.fetch(
                "SELECT chat_id, chat_params FROM chat_profiles")
            for r in crows:
                params = r["chat_params"]
                if isinstance(params, (bytes, bytearray)):
                    params = params.decode("utf-8", "replace")
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except Exception:
                        params = {"raw": str(params)[:120]}
                if not isinstance(params, dict):
                    print("  chat=%s params=%r" % (r["chat_id"], params))
                    continue
                ov = params.get("overrides") or {}
                interesting = {}
                for k, v in (ov.items() if isinstance(ov, dict) else []):
                    if (k.startswith("flags.") or k.startswith("temporal.")
                            or k.startswith("models.vision")
                            or k.startswith("limits.vision")):
                        interesting[k] = flat(v)
                if interesting:
                    print("  chat=%s overrides=%r" % (r["chat_id"], interesting))
                else:
                    print("  chat=%s overrides: no flags/vision/temporal keys"
                          % r["chat_id"])
        except Exception as exc:
            print("  chat_profiles ERROR: %s" % type(exc).__name__)
        print("== llm_usage_events: 7 дней по module/step/tool ==")
        try:
            urows = await conn.fetch(
                "SELECT module, step, tool_name, source, COUNT(*) c, "
                "MAX(ts) last FROM llm_usage_events "
                "WHERE ts > now() - interval '7 days' "
                "GROUP BY 1,2,3,4 ORDER BY c DESC LIMIT 40")
            for r in urows:
                print("  %s/%s tool=%s src=%s count=%d last=%s"
                      % (r["module"], r["step"], r["tool_name"], r["source"],
                         r["c"], r["last"].strftime("%m-%d %H:%M:%SZ")))
        except Exception as exc:
            print("  usage ERROR: %s" % type(exc).__name__)
        print("== plan_meta последних L1-планов (capabilities/tools) ==")
        try:
            prows = await conn.fetch(
                "SELECT ts, plan_meta FROM llm_usage_events "
                "WHERE module='direct_chat' AND step='l1_planner' "
                "ORDER BY ts DESC LIMIT 8")
            if not prows:
                print("  <нет записей l1_planner>")
            for r in prows:
                pm = r["plan_meta"]
                if isinstance(pm, str):
                    try:
                        pm = json.loads(pm)
                    except Exception:
                        pm = {"raw": pm[:160]}
                pm = pm or {}
                keep = {k: pm.get(k) for k in
                        ("action", "execution_mode", "capabilities", "tools",
                         "bucket", "confidence", "source",
                         "required_capability", "planner_fallback_reason")
                        if pm.get(k) is not None}
                print("  %s %r"
                      % (r["ts"].strftime("%m-%d %H:%M:%SZ"), keep))
        except Exception as exc:
            print("  plan_meta ERROR: %s" % type(exc).__name__)
        print("== worker_budget: image_calls ==")
        try:
            wrows = await conn.fetch(
                "SELECT day::text d, scope, metric, used FROM worker_budget "
                "WHERE metric='image_calls' ORDER BY day DESC, scope LIMIT 12")
            if not wrows:
                print("  <нет строк image_calls>")
            for r in wrows:
                print("  day=%s scope=%s used=%s" % (r["d"], r["scope"],
                                                     r["used"]))
        except Exception as exc:
            print("  worker_budget ERROR: %s" % type(exc).__name__)
    finally:
        await conn.close()


def sqlite_part():
    now = int(time.time())
    week = now - 7 * 86400
    con = sqlite3.connect("file:%s?mode=ro" % SQLITE, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    print("== mca_events: 7 дней по event/outcome (top 45) ==")
    try:
        rows = con.execute(
            "SELECT event_name, outcome, component, COUNT(*) c, MAX(ts) last "
            "FROM mca_events WHERE ts > ? GROUP BY 1,2,3 "
            "ORDER BY c DESC LIMIT 45", (week,)).fetchall()
        for r in rows:
            print("  %s outcome=%s comp=%s count=%d last=%s"
                  % (r["event_name"], r["outcome"], r["component"], r["c"],
                     ts(r["last"])))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== mca_events: tool_call/tool_delivery/tool_accounting (последние 30) ==")
    try:
        rows = con.execute(
            "SELECT ts, event_name, outcome, status, reason_code, component, "
            "entity_ids, duration_ms, chat_id FROM mca_events "
            "WHERE event_name IN ('tool_call','tool_delivery','tool_accounting') "
            "ORDER BY id DESC LIMIT 30").fetchall()
        if not rows:
            print("  <нет событий tool_*>")
        for r in rows:
            tool = ""
            try:
                eid = json.loads(r["entity_ids"] or "{}")
                tool = eid.get("tool", "")
            except Exception:
                tool = ""
            print("  %s %s outcome=%s status=%s reason=%s tool=%s comp=%s "
                  "chat=%s dur=%s"
                  % (ts(r["ts"]), r["event_name"], r["outcome"],
                     r["status"], r["reason_code"], tool, r["component"],
                     r["chat_id"], r["duration_ms"]))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== mca_events: capability_check / capability_message (последние 20) ==")
    try:
        rows = con.execute(
            "SELECT ts, event_name, outcome, status, reason_code, entity_id, "
            "chat_id FROM mca_events "
            "WHERE event_name IN ('capability_check','capability_message') "
            "ORDER BY id DESC LIMIT 20").fetchall()
        if not rows:
            print("  <нет событий capability_*>")
        for r in rows:
            print("  %s %s outcome=%s status=%s reason=%s entity=%s chat=%s"
                  % (ts(r["ts"]), r["event_name"], r["outcome"], r["status"],
                     r["reason_code"], r["entity_id"], r["chat_id"]))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== mca_events: vision/factcheck/temporal (7 дней) ==")
    try:
        rows = con.execute(
            "SELECT event_name, outcome, reason_code, COUNT(*) c, MAX(ts) last "
            "FROM mca_events WHERE ts > ? AND (event_name LIKE 'vision%' "
            "OR event_name LIKE 'temporal%' OR event_name LIKE 'fact%') "
            "GROUP BY 1,2,3 ORDER BY c DESC LIMIT 30", (week,)).fetchall()
        if not rows:
            print("  <нет событий>")
        for r in rows:
            print("  %s outcome=%s reason=%s count=%d last=%s"
                  % (r["event_name"], r["outcome"], r["reason_code"], r["c"],
                     ts(r["last"])))
    except Exception as exc:
        print("  ERROR %s" % exc)
    print("== task_jobs: все kind, 7 дней ==")
    try:
        rows = con.execute(
            "SELECT kind, status, reason_code, COUNT(*) c, MAX(updated_at) u "
            "FROM task_jobs WHERE created_at > ? GROUP BY 1,2,3 "
            "ORDER BY c DESC LIMIT 30", (week,)).fetchall()
        if not rows:
            print("  <нет джоб за 7 дней>")
        for r in rows:
            print("  kind=%s status=%s reason=%s count=%d last=%s"
                  % (r["kind"], r["status"], r["reason_code"], r["c"],
                     ts(r["u"])))
    except Exception as exc:
        print("  ERROR %s" % exc)
    con.close()


if __name__ == "__main__":
    sqlite_part()
    asyncio.run(pg_part())
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
        print(run("cd %s && git log -1 --format='%%H %%cd %%s' "
                  "--date=format:%%Y-%%m-%%dT%%H:%%M:%%SZ && "
                  "git status --porcelain | wc -l" % APP).strip())
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
            "cat > /tmp/addtr_recon.py && wc -c /tmp/addtr_recon.py",
            timeout=60)
        _in.write(REMOTE)
        _in.channel.shutdown_write()
        print(out.read().decode("utf-8", "replace").strip())
        etext = err.read().decode("utf-8", "replace").strip()
        if etext:
            print("[stderr] " + etext[:400])
        print("== RECON OUTPUT ==")
        print(run("%s /tmp/addtr_recon.py" % py, timeout=300))
        print("== journal: retention ==")
        print(run(
            "journalctl --disk-usage 2>/dev/null; "
            "journalctl -u admin_bot --no-pager 2>/dev/null | head -1", timeout=60))
        print("== journal: TOOL_CALL по инструментам (вся доступная история) ==")
        print(run(
            "journalctl -u admin_bot --no-pager 2>/dev/null "
            "| grep -E 'event=TOOL_CALL_(START|COMPLETE|FAILED)' "
            "| grep -oE 'tool=[a-z_]+' | sort | uniq -c | sort -rn",
            timeout=120))
        print("== journal: наши 4 инструмента, последние строки (7д) ==")
        print(run(
            "journalctl -u admin_bot --since '-7 days' --no-pager 2>/dev/null "
            "| grep -E 'tool=(recognize_image|fact_check|generate_image|get_bot_health)' "
            "| tail -30", timeout=120))
        print("== journal: L1_CAPABILITY_REJECTED (7д) ==")
        print(run(
            "journalctl -u admin_bot --since '-7 days' --no-pager 2>/dev/null "
            "| grep 'event=L1_CAPABILITY_REJECTED' | grep -oE "
            "'capability=[a-z_]+ \\| reason=[a-z_]+|reason=[a-z_]+' "
            "| sort | uniq -c | sort -rn | head -20", timeout=120))
        print("== journal: TOOL_CALL_COMPLETE по tool (7д) ==")
        print(run(
            "journalctl -u admin_bot --since '-7 days' --no-pager 2>/dev/null "
            "| grep 'event=TOOL_CALL_COMPLETE' | grep -oE 'tool=[a-z_]+' "
            "| sort | uniq -c | sort -rn", timeout=120))
        print("== journal: [image] / image-события (7д, хвост 20) ==")
        print(run(
            "journalctl -u admin_bot --since '-7 days' --no-pager 2>/dev/null "
            "| grep -E '\\[image\\]|TOOL_CALL_START.*generate_image' | tail -20",
            timeout=120))
        print("== journal: factcheck (7д, хвост 15) ==")
        print(run(
            "journalctl -u admin_bot --since '-7 days' --no-pager 2>/dev/null "
            "| grep -iE 'factcheck' | tail -15", timeout=120))
        print("== journal: L1_PLAN эмиссии (7д, счётчики) ==")
        print(run(
            "journalctl -u admin_bot --since '-7 days' --no-pager 2>/dev/null "
            "| grep -c 'event=L1_PLAN'; "
            "journalctl -u admin_bot --since '-7 days' --no-pager 2>/dev/null "
            "| grep 'event=L1_PLAN' | tail -6", timeout=120))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
