"""Prod READ-ONLY (сессия 3, финальная): интерпретатор + DB-строки + трейсбеки.

Одна SSH-сессия, только чтение.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import paramiko

HOST = "198.46.175.136"
USER = "nik"


def _find_root(start: str) -> str:
    cur = os.path.abspath(start)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "deploy_commands.txt")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError("repo root not found")


ROOT = _find_root(os.path.dirname(__file__))
OUT = os.path.join(os.path.dirname(__file__), "probe_prod_readonly3.json")


def _pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  Path(ROOT, "deploy_commands.txt").read_text(
                      encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def mask(text: str) -> str:
    return re.sub(r"postgres(?:ql)?://[^\s\"']+", "postgresql://***", text)


PY_QUERIES = r'''
import asyncio, json, sys
dsn = None
for line in open("/var/www/admin_bot/.env", encoding="utf-8", errors="replace"):
    if line.startswith("POSTGRES_DSN="):
        dsn = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
if not dsn:
    print("###JSON###"); print(json.dumps({"error": "no DSN"})); raise SystemExit(0)
import asyncpg

QUERIES = {
 "settings_rows": """
   SELECT key, category, jsonb_typeof(value) AS jt, length(value::text) AS chars,
          value->>'revision' AS rev, to_char(updated_at,'MM-DD HH24:MI:SS') AS upd
   FROM bot_settings WHERE key LIKE 'character.%' OR key LIKE 'style.%'
   ORDER BY key""",
 "style_doc": "SELECT value::text AS v FROM bot_settings WHERE key='style.policy'",
 "core_doc_head": """
   SELECT value->>'revision' AS rev, value->>'detail_level' AS lvl,
          value->>'enabled' AS en, value->>'origin' AS origin,
          value->>'updated_at' AS upd,
          length(coalesce(value->>'full_text','')) AS full_chars,
          length(coalesce(value->>'compact_text','')) AS compact_chars,
          jsonb_array_length(coalesce(value->'history','[]'::jsonb)) AS hist_len
   FROM bot_settings WHERE key='character.core'""",
 "chat_overrides": """
   SELECT chat_id, to_char(updated_at,'MM-DD HH24:MI:SS') AS upd,
          (chat_params->'overrides') ? 'style.policy' AS has_style,
          (chat_params->'overrides') ? 'character.expression' AS has_expr,
          (chat_params->'overrides') ? 'character.core' AS has_core
   FROM chat_profiles
   WHERE (chat_params->'overrides') ?| array['style.policy',
        'character.expression','character.core'] LIMIT 20""",
 "honesty_counts": """
   SELECT
     (SELECT count(*) FROM bot_settings WHERE key='character.expression')
       AS expr_rows,
     (SELECT count(*) FROM bot_settings WHERE key='style.policy') AS style_rows,
     (SELECT count(*) FROM bot_settings WHERE key='character.core') AS core_rows,
     (SELECT count(*) FROM bot_settings WHERE key LIKE 'character%')
       AS character_keys""",
}


async def main():
    conn = await asyncpg.connect(dsn)
    out = {}
    for name, sql in QUERIES.items():
        try:
            out[name] = [dict(r) for r in await conn.fetch(sql)]
        except Exception as exc:
            out[name] = {"error": type(exc).__name__ + ": " + str(exc)[:200]}
    await conn.close()
    print("###JSON###")
    print(json.dumps(out, ensure_ascii=False, default=str))


asyncio.run(main())
'''

RUN_QUERIES = (
    "cd /var/www/admin_bot && for p in .venv/bin/python venv/bin/python "
    "env/bin/python /usr/bin/python3; do if [ -x \"$p\" ] && \"$p\" -c "
    "'import asyncpg' 2>/dev/null; then echo \"USING=$p\"; \"$p\" - <<'PYEOF'\n"
    + PY_QUERIES + "\nPYEOF\nbreak; fi; done")

STEPS = {
    "unit": ("systemctl cat admin_bot | grep -iE 'ExecStart|WorkingDirectory|"
             "EnvironmentFile' ; echo '---'; systemctl show admin_bot -p "
             "ActiveEnterTimestamp --value; echo '---'; ls /var/www/admin_bot "
             "| head -30; exit 0", False, 60),
    "db": (RUN_QUERIES, False, 120),
    "trace_style": (
        "sudo -S -p '' journalctl -u admin_bot --since '2026-10-18 07:55' "
        "--no-pager -o short-iso | grep -A16 'document save failed' | tail -40",
        True, 240),
    "trace_expr": (
        "sudo -S -p '' journalctl -u admin_bot --since '2026-10-18 07:55' "
        "--no-pager -o short-iso | grep -A16 'expression chat write failed' "
        "| tail -40", True, 240),
    "recent_speech_all": (
        "sudo -S -p '' journalctl -u admin_bot --since '2026-10-18 07:30' "
        "--no-pager -o short-iso | grep -aE 'web\\.api\\.speech|style_policy|"
        "config_cache\\] set \\| key=(style|character)|speech\\]' | tail -60",
        True, 240),
}


def main() -> int:
    pw = _pwd()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    report: dict = {"host": HOST, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "steps": {}}
    try:
        client.connect(HOST, 22, USER, pw, timeout=25, banner_timeout=25,
                       auth_timeout=25, allow_agent=False, look_for_keys=False)
        for name, (cmd, sudo, wait) in STEPS.items():
            try:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=wait)
                if sudo:
                    stdin.write(pw + "\n")
                    stdin.flush()
                out = stdout.read().decode("utf-8", "replace")
                err = stderr.read().decode("utf-8", "replace")
                report["steps"][name] = mask(
                    out + ("\n[stderr] " + err if err.strip() else ""))
            except Exception as exc:               # noqa: BLE001
                report["steps"][name] = f"[step failed] {type(exc).__name__}: {exc}"
    finally:
        client.close()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    for k, v in report["steps"].items():
        print(f"===== {k} =====")
        print(str(v).strip()[:7000])
    print(f"\n[probe] -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
