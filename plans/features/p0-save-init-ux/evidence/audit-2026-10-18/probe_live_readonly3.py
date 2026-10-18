"""Prod READ-ONLY (live-3): scope-источник UI, чужие chat-overrides, Core-провенанс.

Только GET. Запуск:
  .venv\\Scripts\\python.exe plans/features/p0-save-init-ux/evidence/audit-2026-10-18/probe_live_readonly3.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode


def _find_root(start: str) -> str:
    cur = os.path.abspath(start)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "config", "settings.py")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError("repo root not found")


ROOT = _find_root(os.path.dirname(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from config.settings import settings  # noqa: E402

BASE = "https://admin-bot.duckdns.org"
UID = 5885953495
CHAT = -1002661910336          # PERMsoc: кукярик


def init_data() -> str:
    data = {"auth_date": str(int(time.time())),
            "user": json.dumps({"id": UID, "first_name": "Audit"},
                               separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


INIT = init_data()


def get(path, chat_id=None):
    req = urllib.request.Request(BASE + path, method="GET")
    req.add_header("X-Telegram-Init-Data", INIT)
    if chat_id is not None:
        req.add_header("X-Chat-Id", str(chat_id))
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return {"status": resp.status,
                    "json": json.loads(resp.read().decode("utf-8", "replace"))}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code,
                "body": exc.read().decode("utf-8", "replace")[:200]}
    except Exception as exc:                        # noqa: BLE001
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


out: dict = {}

ov_chat = get("/api/speech/overview", CHAT)
out["overview_chat"] = {
    "status": ov_chat.get("status"),
    "scope": (ov_chat.get("json") or {}).get("scope"),
    "chat_id": (ov_chat.get("json") or {}).get("chat_id"),
    "scope_source_ui": ("speechScopeChoice -> 'chat' при scope==='chat' "
                        "(app.js:18887)"),
}

cfg = get("/api/config", CHAT)
if cfg.get("status") == 200:
    j = cfg["json"] or {}
    items = j.get("items") if isinstance(j, dict) else None
    overridden = []
    if isinstance(items, list):
        for item in items:
            src = str(item.get("source") or item.get("origin") or "")
            if item.get("overridden") or src in ("chat", "override"):
                overridden.append(item.get("key"))
    out["config_chat"] = {
        "status": 200,
        "updated_at": j.get("updated_at"),
        "keys_visible": len(items) if isinstance(items, list) else None,
        "chat_overridden_keys_sample": overridden[:12],
        "chat_overridden_count": len(overridden),
        "raw_keys": sorted(j.keys())[:20] if isinstance(j, dict) else None,
    }
else:
    out["config_chat"] = cfg

blk = get("/api/speech/block/core.personality")
if blk.get("status") == 200:
    j = blk["json"] or {}
    out["core_block_global"] = {
        "source": j.get("effective", {}).get("source") if isinstance(j.get("effective"), dict) else None,
        "revision": j.get("effective", {}).get("revision") if isinstance(j.get("effective"), dict) else None,
        "differs_from_factory": (j.get("effective") or {}).get("differs_from_factory"),
        "chars": (j.get("effective") or {}).get("chars"),
        "history_len": len(j.get("history") or []),
        "history": [{k: row.get(k) for k in
                     ("kind", "scope", "sha256_12", "chars", "updated_at",
                      "actor", "reason")} for row in (j.get("history") or [])[:6]],
        "can_edit": j.get("can_edit"),
        "keys": sorted(j.keys()),
    }
else:
    out["core_block_global"] = blk

blk_chat = get("/api/speech/block/core.personality", CHAT)
if blk_chat.get("status") == 200:
    j = blk_chat["json"] or {}
    out["core_block_chat"] = {
        "source": (j.get("effective") or {}).get("source"),
        "chat_override_present": bool(j.get("has_chat_override")),
        "global_present": bool(j.get("has_global_value")),
    }
else:
    out["core_block_chat"] = blk_chat

with open(os.path.join(os.path.dirname(__file__),
                       "probe_live_readonly3.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False, indent=2)[:5000])
