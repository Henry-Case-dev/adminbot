"""Prod READ-ONLY: состояние речи по чатам владельца (только GET).

Запуск:
  .venv\\Scripts\\python.exe plans/features/p0-save-init-ux/evidence/audit-2026-10-18/probe_live_chat_scope.py
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
CHATS = [-1004482340693, -1002661910336, 5885953495]


def init_data(user_id: int = UID) -> str:
    data = {"auth_date": str(int(time.time())),
            "user": json.dumps({"id": user_id, "first_name": "Audit"},
                               separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def get(path: str, chat_id=None):
    req = urllib.request.Request(BASE + path, method="GET")
    req.add_header("X-Telegram-Init-Data", init_data())
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


def main() -> int:
    out: dict = {}
    for cid in CHATS:
        row: dict = {}
        e = get("/api/speech/expression", cid)
        if e.get("status") == 200:
            j = e["json"]
            row["expression"] = {"present": j.get("present"),
                                 "inheritance": j.get("inheritance"),
                                 "chat_present": j.get("chat_present"),
                                 "global_present": j.get("global_present"),
                                 "values": j.get("values"),
                                 "note": (j.get("note") or "")[:80],
                                 "rendered_text": (j.get("rendered_text") or "")[:200]}
        else:
            row["expression"] = e
        st = get("/api/speech/style", cid)
        if st.get("status") == 200:
            j = st["json"]
            row["style"] = {"source": j.get("source"), "revision": j.get("revision"),
                            "rules": len(j.get("rules") or []),
                            "soft": len(j.get("soft_instructions") or []),
                            "document": j.get("document")}
        else:
            row["style"] = st
        co = get("/api/speech/core", cid)
        if co.get("status") == 200:
            j = co["json"]
            row["core"] = {"inheritance": j.get("inheritance"),
                           "document": j.get("document"),
                           "selection_source": (j.get("selection") or {}).get("source"),
                           "selection_level": (j.get("selection") or {}).get("level"),
                           "selection_reason": (j.get("selection") or {}).get("reason"),
                           "full_chars": (j.get("editions") or {}).get("full", {}).get("chars"),
                           "compact_chars": (j.get("editions") or {}).get("compact", {}).get("chars")}
        else:
            row["core"] = co
        out[str(cid)] = row
    with open(os.path.join(os.path.dirname(__file__),
                           "probe_live_chat_scope.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
