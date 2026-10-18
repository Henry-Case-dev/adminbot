"""Prod READ-ONLY: строки bot_settings + chat_profiles + логи admin_bot.

ОДНА SSH-сессия (fail2ban-политика проекта): один коннект, без ретраев.
Только чтение: SELECT + journalctl/awk. Ни одной записи в БД/файлы/сервис.
Пароли и DSN маскируются в выводе.

Запуск:
  .venv\\Scripts\\python.exe plans/features/p0-save-init-ux/evidence/audit-2026-10-18/probe_prod_readonly.py
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
CREDS = Path(__file__).resolve()

def _find_root(start: str) -> str:
    cur = os.path.abspath(start)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "deploy_commands.txt")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError("repo root not found")


ROOT = _find_root(os.path.dirname(__file__))
OUT = os.path.join(os.path.dirname(__file__), "probe_prod_readonly.json")


def _pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  Path(ROOT, "deploy_commands.txt").read_text(
                      encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def mask(text: str) -> str:
    text = re.sub(r"postgres(?:ql)?://[^\s\"']+", "postgresql://***", text)
    text = re.sub(r"(?i)(password|pass|pwd)\s*=\s*\S+", r"\1=***", text)
    return text


DSN_EXTRACT = (
    "DSN=$(grep -m1 '^POSTGRES_DSN=' /var/www/admin_bot/.env "
    "| cut -d= -f2- | tr -d '\\\"'); "
)

QUERIES = {
    "settings_rows": (
        "SELECT key, category, jsonb_typeof(value) AS jt, "
        "length(value::text) AS chars, value->>'revision' AS rev, "
        "to_char(updated_at,'YYYY-MM-DD HH24:MI') AS upd "
        "FROM bot_settings WHERE key LIKE 'character.%' OR key LIKE 'style.%' "
        "ORDER BY key"),
    "expression_doc": (
        "SELECT value::text FROM bot_settings WHERE key='character.expression'"),
    "core_doc_head": (
        "SELECT key, value->>'revision' AS rev, value->>'detail_level' AS lvl, "
        "value->>'enabled' AS en, value->>'origin' AS origin, "
        "value->>'updated_at' AS upd, "
        "length(coalesce(value->>'full_text','')) AS full_chars, "
        "length(coalesce(value->>'compact_text','')) AS compact_chars, "
        "(value ? 'history') AS has_hist, "
        "jsonb_array_length(coalesce(value->'history','[]'::jsonb)) AS hist_len "
        "FROM bot_settings WHERE key='character.core'"),
    "style_doc_head": (
        "SELECT value->>'revision' AS rev, "
        "jsonb_array_length(coalesce(value->'rules','[]'::jsonb)) AS rules, "
        "jsonb_array_length(coalesce(value->'soft_instructions','[]'::jsonb)) "
        "AS soft, value->>'reason' AS reason, value->>'updated_at' AS upd, "
        "coalesce(value->'rules'->0->>'kind','-') AS rule1_kind, "
        "coalesce(value->'rules'->0->>'id','-') AS rule1_id "
        "FROM bot_settings WHERE key='style.policy'"),
    "chat_overrides": (
        "SELECT chat_id, to_char(updated_at,'YYYY-MM-DD HH24:MI') AS upd, "
        "(chat_params->'overrides') ? 'style.policy' AS has_style, "
        "(chat_params->'overrides') ? 'character.expression' AS has_expr, "
        "(chat_params->'overrides') ? 'character.core' AS has_core "
        "FROM chat_profiles WHERE "
        "(chat_params->'overrides') ?| array['style.policy',"
        "'character.expression','character.core'] LIMIT 20"),
    "speech_history_rows": (
        "SELECT count(*) AS n FROM chat_lore_history WHERE field='chat_params' "
        "AND (new_value LIKE '%character.expression%' OR "
        "new_value LIKE '%style.policy%' OR new_value LIKE '%character.core%')"),
}

LOG_AWK = (
    "sudo -S -p '' journalctl -u admin_bot --since '14 days ago' --no-pager "
    "-o short-iso | awk '/\\\\[speech\\\\]|\\\\[style_policy\\\\]|"
    "\\\\[chat_params\\\\]|\\\\[config_cache\\\\] .*set \\\\|/ {n++; b[n]=$0} "
    "END {print \"MATCH_TOTAL=\" n; s=n-40; if (s<1) s=1; "
    "for(i=s;i<=n;i++) print b[i]}'"
)
LOG_COUNTS = (
    "sudo -S -p '' journalctl -u admin_bot --since '14 days ago' --no-pager "
    "| grep -cE 'document save failed|expression chat write failed|write failed|"
    "core meta chat write failed|chat document write failed|"
    "expression write failed'"
)


def main() -> int:
    pw = _pwd()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    report: dict = {"host": HOST, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "steps": {}}
    try:
        client.connect(HOST, 22, USER, pw, timeout=25, banner_timeout=25,
                       auth_timeout=25, allow_agent=False, look_for_keys=False)

        def run(cmd: str, sudo: bool = False, wait: int = 60) -> str:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=wait)
            if sudo:
                stdin.write(pw + "\n")
                stdin.flush()
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            return mask(out + ("\n[stderr] " + err if err.strip() else ""))

        report["steps"]["meta"] = run(
            "cd /var/www/admin_bot && echo HEAD=$(git rev-parse --short HEAD) && "
            "grep -m1 '^APP_VERSION' config/settings.py | cut -c1-40 && "
            "echo STARTED=$(systemctl show admin_bot -p ActiveEnterTimestamp "
            "--value) && echo NOW=$(date -Is)")
        for name, sql in QUERIES.items():
            cmd = (DSN_EXTRACT +
                   "psql \"$DSN\" -At -F '|' -c \"" + sql + "\"")
            report["steps"][name] = run(cmd)
        report["steps"]["log_counts"] = run(LOG_COUNTS, sudo=True, wait=180)
        report["steps"]["log_tail"] = run(LOG_AWK, sudo=True, wait=180)
    finally:
        client.close()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    for k, v in report["steps"].items():
        print(f"===== {k} =====")
        print(v.strip()[:4000])
    print(f"\n[probe] -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
