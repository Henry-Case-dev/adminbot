# -*- coding: utf-8 -*-
"""2.58.196 live/parity harness (read-only HTTP + Playwright screenshots).

No messages to chats, no /meme, no probability changes.
Auth: valid TMA initData signed with the bot token from the local .env
(never printed). Owner id also from .env.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://admin-bot.duckdns.org"
ENV_PATH = Path(r"C:\Code\Python\adminbot\.env")
CHAT_A = -1004482340693
CHAT_B = -1002661910336
CHATS = (CHAT_A, CHAT_B)
PROMPT_KEYS = (
    "prompts.meme_image",
    "prompts.meme_joke",
    "initiative.meme.summary",
    "internal.initiative_observer",
)
SAVED_MEME_BLOCKS = (
    "chat_id", "day", "defaults", "delivery", "image_prefix", "length_limit",
    "master_key", "own_key", "prompts", "quota", "schema_present", "settings",
    "template",
)


def load_env() -> dict:
    data = {}
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


ENV = load_env()
TOKEN = ENV["API_TOKEN"]
OWNER = int(ENV["ADMIN_USER_ID"])


def init_data(user_id: int = OWNER) -> str:
    user = json.dumps({"id": user_id, "first_name": "owner",
                       "username": "owner"}, separators=(",", ":"))
    fields = {"auth_date": str(int(time.time())), "query_id": "AAH",
              "user": user}
    check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


INIT = init_data()


def get(path: str, chat_id: int | None = None, timeout: int = 40):
    url = BASE + path
    req = urllib.request.Request(url)
    req.add_header("X-Telegram-Init-Data", INIT)
    if chat_id is not None:
        req.add_header("X-Chat-Id", str(chat_id))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, raw, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {"raw": raw.decode("utf-8", "replace")[:300]}
        return exc.code, raw, body


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(obj) -> str:
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def parity_snapshot() -> dict:
    out = {"taken_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "surfaces": {}}
    st, raw, body = get("/api/config")
    out["surfaces"]["config_global"] = {"http": st, "sha256": hashlib.sha256(raw).hexdigest()}
    st, raw, body = get("/api/config/overrides-map")
    out["surfaces"]["config_overrides_map"] = {"http": st, "sha256": hashlib.sha256(raw).hexdigest()}
    for chat in CHATS:
        st, raw, body = get("/api/config", chat)
        out["surfaces"]["config_chat_%d" % chat] = {"http": st,
                                                    "sha256": hashlib.sha256(raw).hexdigest()}
    st, raw, body = get("/api/prompts/catalog")
    out["surfaces"]["prompts_catalog"] = {"http": st, "sha256": hashlib.sha256(raw).hexdigest()}
    versions = {}
    for key in PROMPT_KEYS:
        st, raw, body = get("/api/prompts/%s/versions" % urllib.parse.quote(key))
        versions[key] = {"http": st, "sha256": hashlib.sha256(raw).hexdigest()}
    out["surfaces"]["prompt_versions"] = {"sha256": sha(versions), "items": versions}
    for chat in CHATS:
        st, raw, body = get("/api/initiative/meme-settings", chat)
        saved = {k: body.get(k) for k in SAVED_MEME_BLOCKS} if isinstance(body, dict) else {}
        out["surfaces"]["meme_settings_saved_%d" % chat] = {
            "http": st, "sha256": sha(saved),
            "present_blocks": sorted(saved.keys()),
        }
    return out


DOC = {}


def main(mode: str) -> int:
    out = {"release": "2.58.196", "mode": mode,
           "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if mode == "parity":
        out["parity"] = parity_snapshot()
        print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
        Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        return 0

    # --- diagnostics + meme settings, both chats ---
    diag = {}
    pub = {}
    meme = {}
    for chat in CHATS:
        st, raw, body = get("/api/initiative/mechanism-diagnostics", chat)
        diag[str(chat)] = {"http": st, "body": body}
        st, raw, body = get("/api/initiative/meme-settings", chat)
        saved = {k: body.get(k) for k in SAVED_MEME_BLOCKS} if isinstance(body, dict) else {}
        meme[str(chat)] = {"http": st, "saved": saved,
                           "availability": (body or {}).get("availability"),
                           "analytics_keys": sorted((body or {}).get("analytics", {}).keys())
                           if isinstance((body or {}).get("analytics"), dict) else [],
                           "generated_at": (body or {}).get("generated_at")}
        st, raw, body = get("/api/initiative/publications?days=7&limit=5", chat)
        pub[str(chat)] = {"http": st, "body": body}
    out["diagnostics"] = diag
    out["meme_settings"] = meme
    out["publications_preview"] = pub

    # --- PB-FILTERS: six server filters + pagination + validation ---
    filters = {}
    for chat in CHATS:
        cases = {
            "kind_meme": "kind=meme",
            "kind_text": "kind=text_initiative",
            "mode_auto": "mode=auto",
            "mode_manual": "mode=manual",
            "outcome_published": "outcome=published",
            "outcome_deferred": "outcome=deferred",
            "outcome_failed": "outcome=failed",
            "reason_cooldown": "reason=cooldown_active",
            "days_7": "days=7",
            "days_0": "days=0",
            "days_90": "days=90",
            "page_0": "limit=1&offset=0",
            "page_1": "limit=1&offset=1",
            "page_5": "limit=1&offset=5",
            "bad_days": "days=91",
            "bad_limit0": "limit=0",
            "bad_limit500": "limit=500",
            "bad_offset": "offset=-1",
        }
        res = {}
        for name, query in cases.items():
            st, raw, body = get("/api/initiative/publications?" + query, chat)
            item = {"http": st}
            if isinstance(body, dict):
                item["total"] = body.get("counts", {}).get("total")
                item["next_offset"] = body.get("next_offset")
                rows = body.get("rows") or []
                item["rows"] = len(rows)
                item["kinds"] = sorted({r.get("kind") for r in rows})
                item["modes"] = sorted({r.get("mode") for r in rows})
                item["outcomes"] = sorted({r.get("outcome") for r in rows})
                item["reason_codes"] = sorted({c for r in rows
                                               for c in (r.get("reason_codes") or [])})[:8]
                item["attempt_ids"] = [r.get("attempt_id") for r in rows[:3]]
                if st == 422:
                    item["detail"] = body.get("detail")
            res[name] = item
        filters[str(chat)] = res
    out["publication_filters"] = filters

    # --- pick attempts and read traces ---
    traces = {}
    for chat in CHATS:
        st, _, listing = get("/api/initiative/publications?days=90&limit=50", chat)
        rows = (listing or {}).get("rows") or []
        meme_row = next((r for r in rows if r.get("kind") == "meme"), None)
        text_row = next((r for r in rows if r.get("kind") == "text_initiative"), None)
        picked = {}
        for label, row in (("meme", meme_row), ("text", text_row)):
            if not row:
                picked[label] = None
                continue
            aid = row.get("attempt_id")
            st, raw, detail = get("/api/initiative/publications/detail?attempt_id="
                                  + urllib.parse.quote(str(aid)), chat)
            picked[label] = {"attempt_id": aid, "http": st, "detail": detail}
        traces[str(chat)] = picked
    out["traces"] = traces

    # --- PB-ACCESS: inspector correlation behaviour ---
    insp = {}
    for chat in CHATS:
        trace = (traces.get(str(chat)) or {}).get("meme") or {}
        detail = trace.get("detail") or {}
        full = detail.get("full_text") or {}
        steps = full.get("steps") or []
        corr = next((s.get("correlation_id") for s in steps
                     if s.get("correlation_id")), "")
        cases = {}
        if corr:
            st, raw, body = get("/api/speech/inspector?correlation_id="
                                + urllib.parse.quote(corr), chat)
            cases["own_correlation"] = {"http": st, "body": body}
        st, raw, body = get("/api/speech/inspector?correlation_id="
                            + urllib.parse.quote("no-such-job#meme_summary"), chat)
        cases["miss"] = {"http": st, "body": body}
        other = CHAT_B if chat == CHAT_A else CHAT_A
        if corr:
            st, raw, body = get("/api/speech/inspector?correlation_id="
                                + urllib.parse.quote(corr), other)
            cases["foreign_chat"] = {"http": st, "body": body}
        insp[str(chat)] = {"correlation_used": corr, "cases": cases,
                           "full_text_block": full}
    out["inspector"] = insp

    # --- OV-SAMPLE semantics anchors ---
    ov = {}
    for chat in CHATS:
        d = (diag.get(str(chat)) or {}).get("body") or {}
        meme_block = d.get("meme") or {}
        text_block = d.get("text_initiative") or {}
        ov[str(chat)] = {
            "generated_at": d.get("generated_at"),
            "heartbeat_ok": d.get("heartbeat_ok"),
            "heartbeat": d.get("heartbeat"),
            "meme": {
                "enabled": (meme_block.get("conditions") or {}).get("meme_enabled"),
                "ready": (meme_block.get("conditions") or {}).get("cooldown_ready"),
                "image_module": ((meme_block.get("configuration") or {}).get(
                    "parts") or []),
                "image_provider": meme_block.get("image_provider"),
                "quota": meme_block.get("quota"),
                "publication": meme_block.get("publication"),
                "attempts": ((meme_block.get("analytics") or {}).get("attempts")
                             or [])[:3],
                "attempt_mode": ((meme_block.get("analytics") or {}).get("attempt_mode")),
                "last_action": (meme_block.get("last_action") or {}),
            },
            "text": {
                "quota": text_block.get("quota"),
                "publication": text_block.get("publication"),
                "image_provider": text_block.get("image_provider"),
                "last_action": (text_block.get("last_action") or {}),
            },
            "degraded": d.get("degraded"),
        }
    out["ov_sample"] = ov

    # --- secret scan over every collected payload ---
    blob = json.dumps(out, ensure_ascii=False)
    patterns = {
        "authorization_header": r"authorization",
        "api_key_field": r"x-api-key",
        "password_field": r"\"password\"",
        "secret_field": r"\"secret\"",
        "cookie_field": r"cookie",
        "bot_token_shape": r"\d{8,10}:[A-Za-z0-9_-]{30,}",
        "bearer": r"Bearer\s+[A-Za-z0-9._-]{10,}",
        "sk_live": r"sk-live-",
    }
    scan = {}
    for name, pat in patterns.items():
        hits = re.findall(pat, blob, flags=re.IGNORECASE)
        scan[name] = len(hits)
    out["secret_scan"] = scan
    out["doc_len"] = len(blob)

    Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("secret_scan", "doc_len")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
