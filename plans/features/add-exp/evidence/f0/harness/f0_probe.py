# -*- coding: utf-8 -*-
"""ADD-EXP Ф0 — read-only prod probe (probe.json).

Facts (SELECT-only; no config/settings writes):
  1. character.expression global (bot_settings) + chat override
     (chat_profiles.chat_params.overrides) for the working chat.
  2. character.core presence (context), composer gates keys.
  3. Last 30 bot replies (bot_replies) + last 30 bot-authored smart_messages
     -> profanity frequency scan (hard/soft categories + instruction markers).
  4. Durable mca_events trace: prompt_layers events (composer layer skip
     reasons incl. expression:expression_absent) for the working chat.
  5. Recent direct_chat llm_usage_events (liveness of the live path).

Output: /tmp/addexp_f0/evidence/probe.json (+ probe.stdout summary).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORK_CHAT = -1002661910336
BOT_ID = 8802473181
EVID = "/tmp/addexp_f0/evidence"
TAG = os.environ.get("F0_PROBE_TAG", "probe")

# ── profanity scan (hard = obscene; soft = vulgar/coarse, not "mat") ───────
MAT_HARD = (
    r"\bху[йяеёию]\w*", r"\bхуйн\w*", r"\bзахуя\w*", r"\bнахуя\w*",
    r"\bпохуй\w*", r"\bохуе\w*", r"\bнихуя\b",
    r"\bпизд\w*",
    r"\bбля\w*",                       # matches бляха too -> manual review
    r"\bеб(а|ё|е|у|и|л|н|с|ш)\w*", r"\bёб\w*", r"\bзаеб\w*", r"\bнаеб\w*",
    r"\bвыеб\w*", r"\bотъеб\w*", r"\bуеб\w*", r"\bпроеб\w*", r"\bдолбоёб\w*",
    r"\bсука\b|\bсуки\b|\bсуке\b|\bсуку\b|\bсукой\b|\bсучк\w*",
    r"\bмудак\w*|\bмудил\w*",
    r"\bпидор\w*|\bпидар\w*|\bпедик\w*|\bпедераст\w*",
    r"\bгондон\w*|\bгандон\w*", r"\bмандав\w*",
    r"\bшлюх\w*", r"\bдроч\w*", r"\bзалуп\w*", r"\bелда\w*",
)
MAT_SOFT = (
    r"\bжоп\w*", r"\bговн\w*", r"\bсрать\w*|\bссан\w*|\bобосра\w*",
    r"\bхер\b|\bхерня\b|\bпохер\b|\bхеров\w*",
)
INSTR_MARKERS = (
    "Expression_Settings", "Мат и грубость", "Мат -", "Мат —",
    "profanity", "нецензур", "обсцен", "матерн", "без мата",
)


def out(tag, text):
    print("F0PROBE %s | %s" % (tag, text), flush=True)


def scan_text(text, limit_each=12):
    text = str(text or "")
    res = {"hard": [], "soft": [], "instr": []}
    for bucket, pats in (("hard", MAT_HARD), ("soft", MAT_SOFT)):
        seen = set()
        for pat in pats:
            for m in re.finditer(pat, text, re.IGNORECASE):
                key = (m.start(), m.end())
                if key in seen:
                    continue
                seen.add(key)
                s, e = max(0, m.start() - 40), min(len(text), m.end() + 40)
                res[bucket].append({"m": m.group(0),
                                    "ctx": " ".join(text[s:e].split())})
                if len(res[bucket]) >= limit_each * 4:
                    break
    low = text.lower()
    for marker in INSTR_MARKERS:
        if marker.lower() in low:
            res["instr"].append(marker)
    return res


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


def git_head():
    try:
        return subprocess.check_output(
            ["git", "-C", APP, "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return ""


def healthz():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/healthz",
                                    timeout=5) as r:
            return r.read().decode("utf-8", "replace")[:400]
    except Exception as exc:  # noqa: BLE001
        return "unavailable: %s" % type(exc).__name__


SETTING_KEYS = (
    "character.expression", "character.core",
    "flags.unified_composer_enabled", "flags.character_core_enabled",
    "flags.speech_style_policy_enabled", "flags.humor_library_enabled",
    "flags.humor_craft_enabled", "flags.persona_enabled",
    "prompts.direct_chat_system_prompt",
    "prompts.direct_chat_verbalizer_system_prompt",
)


async def main() -> int:
    import asyncpg
    from config.settings import settings as _settings  # noqa: F401
    # ↑ loads .env into os.environ (POSTGRES_DSN) — must precede os.getenv

    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    out("NOW_UTC", now)
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        out("FATAL", "POSTGRES_DSN empty")
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SET default_transaction_read_only = on")
    except Exception as exc:  # noqa: BLE001
        out("RO", "read-only set failed: %s" % type(exc).__name__)

    res: dict = {"tag": TAG, "now_utc": now, "head": git_head(),
                 "healthz": healthz(), "chat_id": WORK_CHAT}

    rows = await conn.fetch(
        "SELECT key, value::text AS value_text, category, "
        "updated_at::text AS updated_at FROM bot_settings "
        "WHERE key = ANY($1::text[]) ORDER BY key", list(SETTING_KEYS))
    res["bot_settings"] = [dict(r) for r in rows]

    ch = await conn.fetchrow(
        "SELECT chat_id, updated_at::text AS updated_at, "
        "(chat_params->'overrides'->'character.expression')::text "
        "AS expr_text, "
        "(SELECT array_agg(k) FROM jsonb_object_keys("
        "chat_params->'overrides') k) AS override_keys, "
        "chat_params->>'v' AS layout_v, gates_opt_in "
        "FROM chat_profiles WHERE chat_id = $1", WORK_CHAT)
    res["chat_profile"] = dict(ch) if ch else None
    expr_doc = None
    if ch and ch["expr_text"]:
        try:
            expr_doc = json.loads(ch["expr_text"])
        except Exception:
            expr_doc = {"raw": ch["expr_text"]}
    res["chat_expression_doc"] = expr_doc

    usage = await conn.fetch(
        "SELECT ts::text AS ts, module, step, model, input_tokens, "
        "output_tokens FROM llm_usage_events WHERE chat_id = $1 "
        "ORDER BY ts DESC LIMIT 15", WORK_CHAT)
    res["llm_usage_recent"] = [dict(r) for r in usage]
    usage_any = await conn.fetch(
        "SELECT ts::text AS ts, module, step, chat_id, model FROM "
        "llm_usage_events ORDER BY ts DESC LIMIT 10")
    res["llm_usage_recent_any_chat"] = [dict(r) for r in usage_any]

    replies = q(
        "SELECT tg_message_id, text, last_used_at FROM bot_replies "
        "WHERE chat_id=? ORDER BY tg_message_id DESC LIMIT 30", (WORK_CHAT,))
    res["bot_replies_last30"] = replies
    smart_bot = q(
        "SELECT tg_message_id, user_id, timestamp, substr(text,1,6000) AS text "
        "FROM smart_messages WHERE chat_id=? AND user_id=? "
        "ORDER BY tg_message_id DESC LIMIT 30", (WORK_CHAT, BOT_ID))
    res["smart_messages_bot_last30"] = smart_bot

    events = q(
        "SELECT id, ts, level, event_name, outcome, component, stage, "
        "reason_code, status FROM mca_events WHERE event_name='prompt_layers' "
        "AND chat_id=? ORDER BY id DESC LIMIT 50", (WORK_CHAT,))
    res["mca_prompt_layers"] = [
        {**e, "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.gmtime(int(e["ts"])))} for e in events]
    day_ago = int(time.time()) - 86400
    agg = q(
        "SELECT event_name, status, reason_code, COUNT(*) AS c, MAX(ts) AS last_ts "
        "FROM mca_events WHERE ts >= ? GROUP BY event_name, status, reason_code "
        "ORDER BY c DESC LIMIT 60", (day_ago,))
    res["mca_events_24h_agg"] = agg

    # profanity scan over the observed replies
    scan = {"bot_replies": {}, "smart_bot": {}}
    for r in replies:
        s = scan_text(r.get("text"))
        if s["hard"] or s["soft"] or s["instr"]:
            scan["bot_replies"][str(r["tg_message_id"])] = s
    for r in smart_bot:
        s = scan_text(r.get("text"))
        if s["hard"] or s["soft"] or s["instr"]:
            scan["smart_bot"][str(r["tg_message_id"])] = s
    res["profanity_scan"] = {
        "replies_checked": len(replies),
        "smart_bot_checked": len(smart_bot),
        "hits": scan,
        "hard_hits_total": sum(len(s["hard"]) for b in scan.values()
                               for s in b.values()),
        "soft_hits_total": sum(len(s["soft"]) for b in scan.values()
                               for s in b.values()),
    }

    os.makedirs(EVID, exist_ok=True)
    path = os.path.join(EVID, "%s.json" % TAG)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    out("SAVED", "%s (%d bytes)" % (path, os.path.getsize(path)))

    # compact stdout summary
    bs = {r["key"]: r for r in res["bot_settings"]}
    out("EXPR_GLOBAL",
        "present=%s updated=%s value=%s" % (
            "character.expression" in bs,
            (bs.get("character.expression") or {}).get("updated_at"),
            ((bs.get("character.expression") or {}).get("value_text") or "")[:300]))
    out("EXPR_CHAT", "present=%s doc=%s" % (
        expr_doc is not None, json.dumps(expr_doc, ensure_ascii=False)[:300]))
    out("CORE_GLOBAL", "present=%s" % ("character.core" in bs))
    out("REPLIES", "bot_replies=%d hard_hits=%d soft_hits=%d" % (
        len(replies), res["profanity_scan"]["hard_hits_total"],
        res["profanity_scan"]["soft_hits_total"]))
    statuses = sorted({str(e.get("status")) for e in events})
    out("PROMPT_LAYERS", "n=%d statuses=%s" % (len(events), statuses[:12]))
    await conn.close()
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("F0PROBE FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("F0PROBE RC=%d" % rc, flush=True)
    os._exit(rc)
