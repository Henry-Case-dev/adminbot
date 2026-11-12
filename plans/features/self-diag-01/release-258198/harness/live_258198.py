# -*- coding: utf-8 -*-
"""2.58.198 live/parity harness (read-only HTTP; no chat messages).

Auth: TMA initData signed with the bot token from the local .env (never printed).
Owner id also from .env. Non-admin identity: KOSTIK_USER_ID (read-only 403 probe).
Modes:
  parity <out.json>   surfaces hash snapshot (config/prompts/meme-settings/chat_params)
  live   <out.json>   self-diagnosis endpoint checks, RBAC, TTL, secret scan,
                      healthz, served-asset identity
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

SECRET_PATTERNS = (
    "Authorization", "authorization", "Bearer ", "x-api-key", "api_key=",
    "password", "Password", "cookie", "Cookie", "sk-live-", "sk-ant-",
    "ghp_", "xoxb-", "-----BEGIN", "bot_token", "refresh_token",
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
KOSTIK = int(ENV["KOSTIK_USER_ID"])


def init_data(user_id: int = OWNER, age: int = 0) -> str:
    user = json.dumps({"id": user_id, "first_name": "owner",
                       "username": "owner"}, separators=(",", ":"))
    fields = {"auth_date": str(int(time.time()) - age), "query_id": "AAH",
              "user": user}
    check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


INIT = init_data()
INIT_KOSTIK = init_data(KOSTIK)


def get(path: str, chat_id: int | None = None, init: str | None = None,
        timeout: int = 40):
    url = BASE + path
    req = urllib.request.Request(url)
    if init is not None:
        req.add_header("X-Telegram-Init-Data", init)
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


def parity_snapshot(store: Path | None = None) -> dict:
    out = {"taken_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "surfaces": {}}
    raw_store: dict = {}

    def keep(name: str, raw: bytes, body) -> None:
        if store is not None:
            raw_store[name] = body

    st, raw, body = get("/api/config", init=INIT)
    out["surfaces"]["config_global"] = {"http": st,
                                        "sha256": hashlib.sha256(raw).hexdigest()}
    keep("config_global", raw, body)
    st, raw, body = get("/api/config/overrides-map", init=INIT)
    out["surfaces"]["config_overrides_map"] = {"http": st,
                                               "sha256": hashlib.sha256(raw).hexdigest()}
    keep("config_overrides_map", raw, body)
    for chat in CHATS:
        st, raw, body = get("/api/config", chat, init=INIT)
        keep("config_chat_%d" % chat, raw, body)
        # per-item updated_at — устойчивый признак правок chat_params
        items = []
        if isinstance(body, dict):
            for it in body.get("items") or body.get("params") or []:
                items.append([it.get("key") or it.get("path"), it.get("updated_at")])
        out["surfaces"]["config_chat_%d" % chat] = {
            "http": st, "sha256": hashlib.sha256(raw).hexdigest(),
            "items_with_updated_at": len([i for i in items if i[1]]),
            "latest_updated_at": max([str(i[1]) for i in items if i[1]], default=None),
        }
    st, raw, body = get("/api/prompts/catalog", init=INIT)
    out["surfaces"]["prompts_catalog"] = {"http": st,
                                          "sha256": hashlib.sha256(raw).hexdigest()}
    keep("prompts_catalog", raw, body)
    versions = {}
    for key in PROMPT_KEYS:
        st, raw, body = get("/api/prompts/%s/versions" % urllib.parse.quote(key),
                            init=INIT)
        versions[key] = {"http": st, "sha256": hashlib.sha256(raw).hexdigest()}
        keep("prompt_versions_%s" % key, raw, body)
    out["surfaces"]["prompt_versions"] = {"sha256": sha(versions), "items": versions}
    for chat in CHATS:
        st, raw, body = get("/api/initiative/meme-settings", chat, init=INIT)
        keep("meme_settings_%d" % chat, raw, body)
        saved = {k: body.get(k) for k in SAVED_MEME_BLOCKS} if isinstance(body, dict) else {}
        out["surfaces"]["meme_settings_saved_%d" % chat] = {
            "http": st, "sha256": sha(saved),
            "present_blocks": sorted(saved.keys()),
        }
    if store is not None:
        (store / "raw.json").write_text(
            json.dumps(raw_store, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
    return out


def scan_secrets(text: str) -> dict:
    found = []
    for pat in SECRET_PATTERNS:
        n = text.count(pat)
        if n:
            found.append([pat, n])
    for name in ("API_TOKEN",):
        value = (ENV.get(name) or "").strip()
        if len(value) >= 8 and value in text:
            found.append([name + "_VALUE", 1])
    return {"hits": found, "hit_count": len(found), "chars": len(text)}


def self_diag_live() -> dict:
    out: dict = {"release": "2.58.198",
                 "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    st, raw, body = get("/healthz")
    out["healthz"] = {"http": st, "body": body}

    payloads = {}
    admin = {}
    for chat in CHATS:
        st, raw, body = get("/api/status/self-diagnosis", chat, init=INIT)
        text = raw.decode("utf-8", "replace")
        payloads[str(chat)] = text
        runtime = (body or {}).get("runtime") or {}
        analytics = (body or {}).get("analytics") or {}
        admin[str(chat)] = {
            "http": st,
            "top_keys": sorted((body or {}).keys()),
            "available": (body or {}).get("available"),
            "generated_at": (body or {}).get("generated_at"),
            "chat_id": (body or {}).get("chat_id"),
            "runtime": {
                "app_version": runtime.get("app_version"),
                "pid": runtime.get("pid"),
                "started_at": runtime.get("started_at"),
                "uptime_seconds": runtime.get("uptime_seconds"),
                "python": runtime.get("python"),
                "platform": runtime.get("platform"),
                "deployed_sha": runtime.get("deployed_sha"),
                "checkout_sha": runtime.get("checkout_sha"),
                "branch": runtime.get("branch"),
                "dirty": runtime.get("dirty"),
                "repo_origin": runtime.get("repo_origin"),
                "identity_source": runtime.get("identity_source"),
                "commits_since_deploy": runtime.get("commits_since_deploy"),
                "local_source_verification": runtime.get("local_source_verification"),
            },
            "sources": {
                "count": len((body or {}).get("sources") or []),
                "areas": sorted({(s or {}).get("area") for s in
                                 ((body or {}).get("sources") or [])}),
                "statuses": sorted({(s or {}).get("status") for s in
                                    ((body or {}).get("sources") or [])}),
                "first": ((body or {}).get("sources") or [None])[0],
            },
            "missing_evidence": (body or {}).get("missing_evidence"),
            "resources": {
                "available": ((body or {}).get("resources") or {}).get("available"),
                "source": ((body or {}).get("resources") or {}).get("source"),
                "cpu_percent": ((body or {}).get("resources") or {}).get("cpu_percent"),
                "cpu_count": ((body or {}).get("resources") or {}).get("cpu_count"),
                "memory": ((body or {}).get("resources") or {}).get("memory"),
                "disk": ((body or {}).get("resources") or {}).get("disk"),
                "process": ((body or {}).get("resources") or {}).get("process"),
            },
            "code_check": (body or {}).get("code_check"),
            "analytics": {
                "window_hours": analytics.get("window_hours"),
                "inspect_runtime": analytics.get("inspect_runtime"),
                "checkup": analytics.get("checkup"),
                "get_bot_health": analytics.get("get_bot_health"),
                "event_counts": analytics.get("event_counts"),
                "secret_value_disclosures": analytics.get("secret_value_disclosures"),
                "golden_eval": analytics.get("golden_eval"),
                "db_growth": analytics.get("db_growth"),
            },
        }
    out["admin"] = admin

    # TTL: two calls within 30 s must return the byte-identical cached payload
    st1, raw1, _b1 = get("/api/status/self-diagnosis", CHAT_A, init=INIT)
    time.sleep(2)
    st2, raw2, _b2 = get("/api/status/self-diagnosis", CHAT_A, init=INIT)
    out["ttl"] = {
        "http": [st1, st2],
        "sha256": [hashlib.sha256(raw1).hexdigest(),
                   hashlib.sha256(raw2).hexdigest()],
        "identical_within_30s": raw1 == raw2,
    }

    # RBAC: non-admin must not get the snapshot
    st, raw, body = get("/api/status/self-diagnosis", CHAT_A, init=INIT_KOSTIK)
    out["rbac_non_admin"] = {
        "http": st,
        "available": (body or {}).get("available"),
        "restricted": (body or {}).get("restricted"),
        "reason": (body or {}).get("reason"),
        "role": (body or {}).get("role"),
        "keys": sorted((body or {}).keys()),
        "leaked_runtime_keys": sorted(set(body or {}) & {"runtime", "resources",
                                                         "sources", "analytics"}),
    }
    # no initData at all
    st, raw, body = get("/api/status/self-diagnosis", CHAT_A)
    out["rbac_anonymous"] = {"http": st,
                             "body_head": json.dumps(body, ensure_ascii=False)[:200]}

    # Existing /api/status stays functional
    st, raw, body = get("/api/status", CHAT_A, init=INIT)
    out["status_endpoint"] = {"http": st,
                              "keys": sorted((body or {}).keys())[:20] if isinstance(body, dict) else None}

    # served asset identity vs committed blobs
    for path, name in (("/app.js", "app.js"), ("/index.html", "index.html")):
        try:
            st, raw, _ = get(path)
            out["served_" + name] = {"http": st,
                                     "sha256": hashlib.sha256(raw).hexdigest(),
                                     "bytes": len(raw)}
        except Exception as exc:  # pragma: no cover
            out["served_" + name] = {"error": type(exc).__name__}

    joined = "\n".join(payloads.values())
    out["secret_scan"] = scan_secrets(joined)
    out["payload_bytes"] = {k: len(v) for k, v in payloads.items()}
    return out


def main(mode: str, out_path: str) -> int:
    if mode == "parity":
        store = Path(out_path).with_suffix("")
        store.mkdir(parents=True, exist_ok=True)
        data = {"release": "2.58.198", "mode": "parity",
                "parity": parity_snapshot(store)}
    else:
        data = {"release": "2.58.198", "mode": "live", "live": self_diag_live()}
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
